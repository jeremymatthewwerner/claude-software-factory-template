"""
Flakiness regression guards.

Focus: flaky-hunt (Tuesday). The suite is currently stable — five back-to-back
runs of the full backend and frontend test suites produced zero flakes. These
tests pin the *sources* of stability so that a regression which would re-
introduce flakiness fails loudly rather than slipping in and only surfacing as
an intermittent CI failure weeks later.

Each test class targets a specific class of flakiness:

* ``TestOpenAPISchemaByteStability`` — guards against non-deterministic schema
  generation (set-ordering, dict-ordering, lazy import side effects).
* ``TestHighIterationMessageDeterminism`` — extends the existing 3–5-call
  idempotence checks to 200+ iterations. A 1-in-100 race in a future handler
  would pass every existing test but trip these.
* ``TestConcurrentIdenticalInputDeterminism`` — fires identical concurrent
  POSTs and verifies *all* responses are byte-identical on ``message``. Pure-
  function semantics must survive event-loop interleaving.
* ``TestMultipleTestClientIsolation`` — creating multiple ``TestClient``
  instances against the same ``app`` must not introduce cross-instance state
  leakage; this matches the parallel-test runner model.
* ``TestAppSingletonInvariant`` — ``from app.main import app`` must always
  return the *same* object so the middleware stack does not silently double-
  register on re-import.
* ``TestStressMonotonicTimestamps`` — extends the existing 10-call monotonicity
  test to 500 sequential calls. A coarsely-rounded or cached clock would only
  fail intermittently at low iteration counts.
* ``TestCORSPreflightByteDeterminism`` — repeat preflights must yield the same
  set of CORS headers. A future change that bound CORS headers to a per-request
  random value would silently corrupt browser caches.
* ``TestRouteInventoryStability`` — the OpenAPI route inventory must be the
  same set across repeated schema fetches; catches lazy-route registration
  that would only surface under specific request orderings.

Bounds are deliberately generous on iteration counts (200–500) because the
underlying handlers are sub-millisecond — the whole module adds <2s of
wall-clock to the suite while exercising paths that no existing test reaches.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.main import app

from .conftest import (
    LOCALHOST_ORIGIN,
    assert_utc_iso8601,
    get_openapi_schema,
    name_from_greeting,
)

# Iteration count for "high-iteration" determinism checks. 200 is high enough
# to catch ~1% probability flakes (>86% chance of detection per run) but adds
# only ~400 ms of wall-clock for sub-millisecond handlers.
HIGH_ITERATION_COUNT = 200

# Sequential timestamp stress count. 500 keeps the test sub-second while
# exercising orders of magnitude more clock reads than the existing 10-call
# monotonicity check.
TIMESTAMP_STRESS_COUNT = 500

# Concurrent identical-input fan-out. 100 is enough to interleave heavily on
# the event loop without producing test-runner noise.
CONCURRENT_FANOUT = 100


class TestOpenAPISchemaByteStability:
    """``/openapi.json`` must be byte-identical across repeated fetches.

    FastAPI caches the schema after first generation. If that cache ever
    starts returning a freshly-built schema (e.g. an accidental
    ``app.openapi_schema = None`` in a handler, or a regenerate-on-fetch
    flag), small non-determinisms in dict/set ordering can surface as
    intermittently-changing schemas. Such churn breaks clients that hash
    the schema for compatibility checks and silently invalidates HTTP
    caches.
    """

    def test_repeated_openapi_json_responses_are_byte_identical(self, client: TestClient) -> None:
        """Twenty back-to-back ``GET /openapi.json`` responses share one body hash."""
        bodies = {client.get("/openapi.json").content for _ in range(20)}
        assert len(bodies) == 1, (
            f"/openapi.json returned {len(bodies)} distinct bodies across 20 calls"
        )

    def test_openapi_schema_dict_equal_across_repeated_calls(self, client: TestClient) -> None:
        """Parsed schema dicts are deeply equal across repeated calls.

        Byte-identity is the strongest property, but if a future change adds
        a stable-but-reordered serialisation (e.g. sorted JSON keys), this
        weaker check still catches *semantic* drift — the parsed dict must
        remain stable even if the bytes change order.
        """
        first = get_openapi_schema(client)
        for i in range(1, 10):
            other = get_openapi_schema(client)
            assert other == first, f"OpenAPI schema diverged on call {i}"


class TestHighIterationMessageDeterminism:
    """Pure-function handlers must remain byte-deterministic on ``message``
    across many iterations.

    Existing idempotence tests use 3–5 iterations, which catches a
    deterministic bug but not a 1%-probability race. These tests run at
    200 iterations so that a flake-introducing regression (e.g. a non-zero
    chance of appending a uuid suffix) fails fast.
    """

    def test_post_hello_message_is_byte_identical_across_200_calls(
        self, client: TestClient
    ) -> None:
        """200 POSTs with the same name yield exactly one distinct ``message`` value."""
        messages = {
            client.post("/api/hello", json={"name": "Stable"}).json()["message"]
            for _ in range(HIGH_ITERATION_COUNT)
        }
        assert len(messages) == 1, (
            f"POST /api/hello returned {len(messages)} distinct messages over "
            f"{HIGH_ITERATION_COUNT} identical calls: {messages!r}"
        )

    def test_get_hello_message_is_byte_identical_across_200_calls(self, client: TestClient) -> None:
        """200 ``GET /api/hello`` calls yield exactly one distinct ``message`` value."""
        messages = {client.get("/api/hello").json()["message"] for _ in range(HIGH_ITERATION_COUNT)}
        assert len(messages) == 1, (
            f"GET /api/hello returned {len(messages)} distinct messages over "
            f"{HIGH_ITERATION_COUNT} calls: {messages!r}"
        )

    def test_health_status_field_is_byte_identical_across_200_calls(
        self, client: TestClient
    ) -> None:
        """The literal ``status`` value never varies — guards against locale leaks."""
        statuses = {client.get("/health").json()["status"] for _ in range(HIGH_ITERATION_COUNT)}
        assert statuses == {"healthy"}, (
            f"/health status field is no longer the constant 'healthy': {statuses!r}"
        )

    def test_version_response_body_is_byte_identical_across_200_calls(
        self, client: TestClient
    ) -> None:
        """All non-timestamp fields of ``/api/version`` are stable across calls.

        ``/api/version`` has no timestamp field — the *entire* body must be
        byte-identical. A divergence here means an accidental non-deterministic
        field has been added.
        """
        bodies = {client.get("/api/version").content for _ in range(HIGH_ITERATION_COUNT)}
        assert len(bodies) == 1, (
            f"/api/version returned {len(bodies)} distinct bodies over {HIGH_ITERATION_COUNT} calls"
        )


class TestConcurrentIdenticalInputDeterminism:
    """Pure-function semantics must survive event-loop interleaving.

    The existing concurrency tests use *distinct* inputs to check that names
    don't leak across requests. These use *identical* inputs to check the
    complementary property: that the handler returns the same answer regardless
    of how it interleaves with itself.
    """

    @pytest.mark.asyncio
    async def test_100_concurrent_identical_posts_return_one_message(
        self, async_client: AsyncClient
    ) -> None:
        """100 concurrent POSTs with the same name yield exactly one distinct ``message``."""
        responses = await asyncio.gather(
            *[
                async_client.post("/api/hello", json={"name": "Concurrent"})
                for _ in range(CONCURRENT_FANOUT)
            ]
        )
        assert all(r.status_code == 200 for r in responses)
        messages = {r.json()["message"] for r in responses}
        assert len(messages) == 1, (
            f"{CONCURRENT_FANOUT} identical concurrent POSTs produced "
            f"{len(messages)} distinct messages: {messages!r}"
        )

    @pytest.mark.asyncio
    async def test_100_concurrent_health_calls_return_one_status(
        self, async_client: AsyncClient
    ) -> None:
        """100 concurrent ``/health`` calls all return ``status='healthy'``."""
        responses = await asyncio.gather(
            *[async_client.get("/health") for _ in range(CONCURRENT_FANOUT)]
        )
        assert all(r.status_code == 200 for r in responses)
        statuses = {r.json()["status"] for r in responses}
        assert statuses == {"healthy"}, (
            f"Concurrent /health calls returned non-uniform statuses: {statuses!r}"
        )

    @pytest.mark.asyncio
    async def test_concurrent_identical_timestamps_are_all_valid_utc(
        self, async_client: AsyncClient
    ) -> None:
        """Every timestamp from 50 concurrent ``/api/hello`` POSTs parses as UTC ISO 8601.

        Race conditions on shared timestamp state often surface as malformed
        strings under concurrency (e.g. half-written format strings). Pin the
        invariant.
        """
        responses = await asyncio.gather(
            *[async_client.post("/api/hello", json={"name": "TimestampRace"}) for _ in range(50)]
        )
        for r in responses:
            assert_utc_iso8601(r.json()["timestamp"])


class TestMultipleTestClientIsolation:
    """Creating multiple ``TestClient`` instances against the same ``app``
    must not introduce cross-instance state leakage.

    Pytest test runners (``pytest-xdist``, custom parallel suites) commonly
    instantiate multiple clients in the same process. If middleware or app
    state were tied to a TestClient lifecycle, behaviour would diverge from
    what users see in production with persistent processes.
    """

    def test_two_clients_against_same_app_return_identical_health(self) -> None:
        """Two independent ``TestClient`` instances see the same ``/health`` response."""
        c1, c2 = TestClient(app), TestClient(app)
        b1 = c1.get("/health").json()
        b2 = c2.get("/health").json()
        # status field must match exactly; timestamps may differ but must both
        # be valid UTC ISO 8601.
        assert b1["status"] == b2["status"] == "healthy"
        assert_utc_iso8601(b1["timestamp"])
        assert_utc_iso8601(b2["timestamp"])

    def test_ten_clients_serially_each_return_200(self) -> None:
        """Creating and tearing down 10 ``TestClient`` instances each succeed independently."""
        for i in range(10):
            with TestClient(app) as c:
                response = c.get("/health")
                assert response.status_code == 200, f"Client #{i} failed: {response.status_code}"

    def test_new_client_after_post_does_not_inherit_prior_post_state(self) -> None:
        """A POST on one client does not affect the message returned by another."""
        c1 = TestClient(app)
        c1.post("/api/hello", json={"name": "Leak"})
        c2 = TestClient(app)
        msg = c2.get("/api/hello").json()["message"]
        assert "Leak" not in msg, f"State from prior client's POST leaked into new client: {msg!r}"


class TestAppSingletonInvariant:
    """``from app.main import app`` must return the same object across imports.

    If a future refactor accidentally creates a new ``FastAPI()`` per import
    (e.g. by moving the construction inside a function), middleware would
    silently double-register and routes would diverge from what tests expect.
    """

    def test_repeated_imports_return_same_object(self) -> None:
        """Two ``from app.main import app`` statements yield the same identity."""
        from app.main import app as app_again
        from app.main import app as app_third

        assert app is app_again is app_third, (
            "app.main.app is not a stable singleton across imports"
        )

    def test_app_routes_set_is_stable_across_repeated_access(self) -> None:
        """The set of registered route paths is identical on repeated reads.

        Lazy route registration would surface here as a growing or shrinking
        set across reads.
        """
        # FastAPI's routes property is a list; we hash by path+method to get
        # a stable identity for comparison.
        snap1 = sorted((getattr(r, "path", None), getattr(r, "name", None)) for r in app.routes)
        snap2 = sorted((getattr(r, "path", None), getattr(r, "name", None)) for r in app.routes)
        snap3 = sorted((getattr(r, "path", None), getattr(r, "name", None)) for r in app.routes)
        assert snap1 == snap2 == snap3, "app.routes inventory changed across reads"


class TestStressMonotonicTimestamps:
    """Long-run timestamp monotonicity stress test.

    The existing 10-call check would only catch a *consistent* clock
    regression. A coarsely-rounded or cached clock might pass 10 calls and
    fail at 100+. Running 500 calls keeps the test sub-second while pushing
    the failure window down to ~0.2% probability of false negatives for any
    real regression.
    """

    def test_500_sequential_health_timestamps_are_non_decreasing(self, client: TestClient) -> None:
        """500 sequential ``/health`` timestamps never go backward."""
        timestamps = [
            client.get("/health").json()["timestamp"] for _ in range(TIMESTAMP_STRESS_COUNT)
        ]
        parsed = [assert_utc_iso8601(ts) for ts in timestamps]
        for i in range(1, len(parsed)):
            assert parsed[i] >= parsed[i - 1], (
                f"Timestamp regression at position {i}: "
                f"{parsed[i].isoformat()} < {parsed[i - 1].isoformat()}"
            )

    def test_500_sequential_post_timestamps_are_non_decreasing(self, client: TestClient) -> None:
        """500 sequential ``POST /api/hello`` timestamps never go backward."""
        timestamps = [
            client.post("/api/hello", json={"name": "Mono"}).json()["timestamp"]
            for _ in range(TIMESTAMP_STRESS_COUNT)
        ]
        parsed = [assert_utc_iso8601(ts) for ts in timestamps]
        for i in range(1, len(parsed)):
            assert parsed[i] >= parsed[i - 1], (
                f"POST timestamp regression at position {i}: "
                f"{parsed[i].isoformat()} < {parsed[i - 1].isoformat()}"
            )


class TestCORSPreflightByteDeterminism:
    """Repeated CORS preflights with identical input must yield identical
    response headers (modulo per-response date/server values).

    The CORS allow-origin, allow-methods, allow-headers, and max-age values
    are deterministic functions of the middleware config. If they ever start
    varying per-request, browsers would silently drop the preflight from
    their cache and double every cross-origin request.
    """

    def _do_preflight(self, client: TestClient) -> dict[str, str]:
        response = client.options(
            "/api/hello",
            headers={
                "Origin": LOCALHOST_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert response.status_code == 200
        return {
            "allow-origin": response.headers.get("access-control-allow-origin", ""),
            "allow-methods": response.headers.get("access-control-allow-methods", ""),
            "allow-headers": response.headers.get("access-control-allow-headers", ""),
            "allow-credentials": response.headers.get("access-control-allow-credentials", ""),
            "max-age": response.headers.get("access-control-max-age", ""),
        }

    def test_repeated_preflight_returns_identical_cors_headers(self, client: TestClient) -> None:
        """Twenty preflights yield exactly one distinct set of CORS headers."""
        snapshots = {json.dumps(self._do_preflight(client), sort_keys=True) for _ in range(20)}
        assert len(snapshots) == 1, f"CORS preflight headers varied across 20 calls: {snapshots!r}"

    def test_preflight_followed_by_post_preflight_unchanged(self, client: TestClient) -> None:
        """A POST between two preflights must not alter the preflight response.

        Catches the case where middleware accidentally records per-origin or
        per-request state that subtly alters preflight output.
        """
        before = self._do_preflight(client)
        client.post("/api/hello", json={"name": "Between"}, headers={"Origin": LOCALHOST_ORIGIN})
        after = self._do_preflight(client)
        assert before == after, (
            f"Preflight headers changed after intervening POST: before={before!r} after={after!r}"
        )


class TestRouteInventoryStability:
    """The OpenAPI route inventory must be stable across repeated fetches.

    A lazy or per-request route registration scheme would only surface as a
    flake under a particular ordering (e.g. ``/openapi.json`` called before
    any application route). Pin the invariant.
    """

    def test_openapi_paths_set_is_identical_across_repeated_calls(self, client: TestClient) -> None:
        """The set of declared paths in ``/openapi.json`` is identical on repeated calls."""
        snapshots = [tuple(sorted(get_openapi_schema(client)["paths"].keys())) for _ in range(10)]
        assert len(set(snapshots)) == 1, (
            f"OpenAPI paths set varied across 10 calls: {set(snapshots)!r}"
        )

    def test_openapi_components_schemas_set_is_identical_across_repeated_calls(
        self, client: TestClient
    ) -> None:
        """The set of declared component-schema names is identical on repeated calls."""
        snapshots = [
            tuple(sorted(get_openapi_schema(client)["components"]["schemas"].keys()))
            for _ in range(10)
        ]
        assert len(set(snapshots)) == 1, (
            f"OpenAPI components.schemas set varied across 10 calls: {set(snapshots)!r}"
        )


class TestAsyncClientReuseDeterminism:
    """A single ``AsyncClient`` reused across many calls must not accumulate
    state that alters response content.

    The ``async_client`` fixture is created once per test. Within a test, the
    fixture is reused for every call. If httpx/Starlette ever introduced
    connection-level state that leaked into response bodies, repeat-call
    determinism would silently degrade.
    """

    @pytest.mark.asyncio
    async def test_50_sequential_calls_on_one_async_client_return_one_message(self) -> None:
        """50 sequential POSTs on a single AsyncClient yield exactly one ``message``."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            responses = [
                await ac.post("/api/hello", json={"name": "AsyncReuse"}) for _ in range(50)
            ]
        messages = {r.json()["message"] for r in responses}
        assert len(messages) == 1, (
            f"50 reuses of one AsyncClient produced {len(messages)} distinct messages: {messages!r}"
        )

    @pytest.mark.asyncio
    async def test_alternating_get_post_on_one_async_client_each_correct(self) -> None:
        """Alternating GET and POST on the same AsyncClient each return their own shape.

        Catches the case where a shared client mutates request-level state
        (e.g. headers) such that a POST starts returning GET content.
        """
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            for i in range(20):
                get_r = await ac.get("/api/hello")
                post_r = await ac.post("/api/hello", json={"name": f"User{i}"})
                assert get_r.status_code == 200
                assert post_r.status_code == 200
                # POST message must include the submitted name; GET message
                # must not (only the literal "World" template).
                assert f"User{i}" in post_r.json()["message"]
                assert name_from_greeting(post_r.json()["message"]) == f"User{i}"
                assert "User" not in get_r.json()["message"]
