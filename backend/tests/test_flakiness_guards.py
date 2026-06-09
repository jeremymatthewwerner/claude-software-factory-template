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
* ``TestOpenAPISchemaUnderConcurrency`` — concurrent fetches of
  ``/openapi.json``, both hot- and cold-cache, must agree on one body.
  Cold-cache forces parallel schema generation, surfacing any
  non-determinism in the generator that the hot-cache path would hide.
* ``TestMixedMethodConcurrentDeterminism`` — concurrent fan-out that mixes
  ``/health``, ``/api/hello`` (GET and POST), ``/api/version``, and
  ``/openapi.json`` must each return its own correct shape; catches
  cross-handler state leakage that identical-input fan-out cannot.
* ``TestGCInvariance`` — forced ``gc.collect()`` between calls must not
  change response content; CPython gc timing is the canonical source of
  non-deterministic execution order inside a single test session.
* ``TestGlobalRandomSeedIndependence`` — handler outputs must be identical
  under different ``random`` global seeds; catches any future accidental
  use of the global RNG that would silently produce per-session variance.
* ``TestTZEnvironmentVariableIndependence`` — handler timestamps must be
  UTC regardless of the ``TZ`` environment variable. Catches the canonical
  ``datetime.now()`` (naive, local-tz) regression that would only fail in
  CI environments whose ``TZ`` differs from UTC.
* ``TestTimestampIsoFormatRoundTrip`` — every emitted timestamp must
  survive ``isoformat → fromisoformat → isoformat`` byte-for-byte. A
  regression that emits a non-canonical or lossy ISO-8601 form (e.g.
  truncated sub-second precision) would still *parse* but would silently
  break downstream byte-comparators.
* ``TestOpenAPIParityHTTPVsDirectCall`` — ``client.get("/openapi.json")``
  and ``app.openapi()`` are two code paths. They must produce the same
  schema dict; a divergence indicates middleware or transport-layer
  mutation that would silently corrupt clients fetching via HTTP.
* ``TestRepeatedSequentialColdCache`` — ``app.openapi_schema = None``
  followed by a refetch must yield byte-identical output across many
  cold-rebuild cycles. Catches cumulative side effects of schema
  generation (e.g. appending operations to a module-level list each
  rebuild) that single-shot cold-cache tests would miss.
* ``TestErrorResponseBodyDeterminism`` — 404/405/422 responses are
  emitted by Starlette's defaults rather than application code, but
  their bodies must still be byte-identical across many iterations and
  across origin variation; otherwise clients that compare error bodies
  byte-for-byte would see intermittent diffs.

Bounds are deliberately generous on iteration counts (200–500) because the
underlying handlers are sub-millisecond — the whole module adds <2s of
wall-clock to the suite while exercising paths that no existing test reaches.
"""

from __future__ import annotations

import asyncio
import gc
import json
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.main import app

from .conftest import (
    DISALLOWED_ORIGIN,
    LOCALHOST_ORIGIN,
    assert_utc_iso8601,
    cors_preflight_headers,
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
                **cors_preflight_headers("POST"),
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


class TestOpenAPISchemaUnderConcurrency:
    """``/openapi.json`` must remain byte-identical when fetched concurrently.

    FastAPI builds the schema once and caches it on ``app.openapi_schema``. The
    sequential byte-identity guard in :class:`TestOpenAPISchemaByteStability`
    exercises the *cached* read path. This class exercises the *cache-fill*
    path: if many requests arrive before the cache is populated (e.g. the first
    request after a deploy, or after a future cache invalidation), each call
    triggers schema generation in parallel. A race between two builders could
    publish a partially-built schema, producing intermittent corruption that
    is *only* visible under concurrent first-touch.

    Resetting ``app.openapi_schema`` to ``None`` simulates the cold-cache
    scenario; the test restores the original cache value in a ``finally`` block
    so it cannot leak into other tests.
    """

    @pytest.mark.asyncio
    async def test_50_concurrent_openapi_fetches_return_one_body(
        self, async_client: AsyncClient
    ) -> None:
        """50 concurrent ``/openapi.json`` fetches yield exactly one body hash."""
        responses = await asyncio.gather(*[async_client.get("/openapi.json") for _ in range(50)])
        assert all(r.status_code == 200 for r in responses)
        bodies = {r.content for r in responses}
        assert len(bodies) == 1, (
            f"50 concurrent /openapi.json fetches produced {len(bodies)} distinct bodies"
        )

    @pytest.mark.asyncio
    async def test_concurrent_cold_cache_openapi_fetches_return_one_body(
        self, async_client: AsyncClient
    ) -> None:
        """Concurrent fetches against a *cleared* schema cache still agree on one body.

        Forces the cache-fill race path: with ``app.openapi_schema = None``,
        every parallel request must regenerate the schema. The contract is that
        the *generated* output is deterministic — never that two builders write
        without coordinating. If a future change introduces non-determinism in
        the generator (e.g. dict ordering tied to insertion-time), this test
        will fail intermittently and we will see the flake immediately rather
        than weeks later.
        """
        original = app.openapi_schema
        app.openapi_schema = None
        try:
            responses = await asyncio.gather(
                *[async_client.get("/openapi.json") for _ in range(30)]
            )
            assert all(r.status_code == 200 for r in responses)
            # Compare parsed dicts (not bytes), because two parallel builders
            # may serialise with different key orderings even though the
            # documented behaviour is "the same schema".
            schemas = [r.json() for r in responses]
            first = schemas[0]
            for i, other in enumerate(schemas[1:], start=1):
                assert other == first, (
                    f"Concurrent cold-cache /openapi.json fetch #{i} diverged from #0"
                )
        finally:
            app.openapi_schema = original


class TestMixedMethodConcurrentDeterminism:
    """Concurrent calls that mix endpoints must each return their own correct shape.

    Existing concurrency guards interleave the *same* call with itself. This
    class interleaves *different* endpoints (GET /health, GET /api/hello,
    POST /api/hello, GET /api/version, GET /openapi.json) and asserts each
    response carries the body for its own route. Catches the regression class
    where shared per-app state (a module-level dict, a default-mutable arg) is
    mutated by one handler and read by another while a request is in flight.
    """

    @pytest.mark.asyncio
    async def test_interleaved_mixed_calls_each_return_correct_shape(
        self, async_client: AsyncClient
    ) -> None:
        """40 mixed-method calls fired concurrently each return a body matching their route."""
        # Build a deterministic, repeating mix of calls — using ``cycle``-like
        # indexing makes the test fail with the *same* signature every time if
        # it ever does fail, rather than producing a different ordering noise
        # on each run.
        calls: list[tuple[str, str, dict[str, str] | None]] = []
        for i in range(8):
            calls.append(("GET", "/health", None))
            calls.append(("GET", "/api/hello", None))
            calls.append(("POST", "/api/hello", {"name": f"Mixed{i}"}))
            calls.append(("GET", "/api/version", None))
            calls.append(("GET", "/openapi.json", None))

        async def run(
            method: str, path: str, body: dict[str, str] | None
        ) -> tuple[str, str, dict[str, object]]:
            if method == "POST":
                resp = await async_client.post(path, json=body)
            else:
                resp = await async_client.get(path)
            assert resp.status_code == 200, (
                f"{method} {path} returned {resp.status_code} under concurrency"
            )
            return method, path, resp.json()

        results = await asyncio.gather(*[run(m, p, b) for m, p, b in calls])

        # Every response must carry the shape its own route declares — not
        # the shape of any other route that happened to be in flight.
        for idx, ((method, path, _), (_, _, body)) in enumerate(zip(calls, results, strict=True)):
            if path == "/health":
                assert body == {"status": "healthy", "timestamp": body.get("timestamp")}, (
                    f"call #{idx} ({method} {path}) returned non-health body: {body!r}"
                )
                assert body["status"] == "healthy"
                assert_utc_iso8601(str(body["timestamp"]))
            elif path == "/api/hello" and method == "GET":
                assert "World" in str(body["message"]), (
                    f"GET /api/hello returned non-default message: {body!r}"
                )
                assert_utc_iso8601(str(body["timestamp"]))
            elif path == "/api/hello" and method == "POST":
                # The POST body for call #idx carries "Mixed{i}" — derive i
                # back from the slot in the cycle. Each slot of length 5
                # contains one POST as the third element.
                cycle_i = idx // 5
                assert f"Mixed{cycle_i}" in str(body["message"]), (
                    f"POST /api/hello at idx {idx} did not echo its name: {body!r}"
                )
            elif path == "/api/version":
                assert "version" in body and "name" in body and "environment" in body, (
                    f"/api/version returned non-version body under concurrency: {body!r}"
                )
            elif path == "/openapi.json":
                assert "openapi" in body and "paths" in body, (
                    f"/openapi.json returned non-schema body under concurrency: {body!r}"
                )


class TestGCInvariance:
    """Response bodies must be byte-identical after a forced ``gc.collect()``.

    The garbage collector is one of the few sources of *truly* non-deterministic
    timing inside a CPython process: collections fire on allocation thresholds
    that depend on the order in which prior tests ran. If a handler ever relied
    on object identity (e.g. cached a response keyed by ``id(obj)``), repeating
    the same call after a forced collection would surface a different cached
    entry — and the same call across two CI runs would behave differently.
    Pinning the invariant catches that class of regression deterministically.
    """

    def test_health_body_byte_identical_across_forced_gc_cycles(self, client: TestClient) -> None:
        """``/health`` ``status`` is unchanged across 20 forced ``gc.collect()`` cycles."""
        statuses: set[str] = set()
        for _ in range(20):
            gc.collect()
            statuses.add(client.get("/health").json()["status"])
            gc.collect()
        assert statuses == {"healthy"}, (
            f"/health status varied across forced gc cycles: {statuses!r}"
        )

    def test_post_hello_message_byte_identical_across_forced_gc_cycles(
        self, client: TestClient
    ) -> None:
        """``POST /api/hello`` returns one message across 20 forced ``gc.collect()`` cycles."""
        messages: set[str] = set()
        for _ in range(20):
            gc.collect()
            response = client.post("/api/hello", json={"name": "GCStable"})
            messages.add(response.json()["message"])
            gc.collect()
        assert len(messages) == 1, f"POST /api/hello varied across forced gc cycles: {messages!r}"

    def test_openapi_body_byte_identical_across_forced_gc_cycles(self, client: TestClient) -> None:
        """``/openapi.json`` bytes are stable across 10 forced ``gc.collect()`` cycles."""
        bodies: set[bytes] = set()
        for _ in range(10):
            gc.collect()
            bodies.add(client.get("/openapi.json").content)
            gc.collect()
        assert len(bodies) == 1, (
            f"/openapi.json bytes varied across forced gc cycles ({len(bodies)} distinct)"
        )


class TestGlobalRandomSeedIndependence:
    """Handler outputs must not depend on the global ``random`` module state.

    The pattern that produces this flake class is innocuous-looking:

        import random
        @app.get(...)
        async def handler():
            return {"id": random.randint(0, 1 << 32), ...}

    A handler that consults the global RNG produces different outputs in two
    test sessions because the seed is set differently (test runners often
    re-seed for ordering randomness — ``pytest-randomly`` does so by default).
    This test seeds ``random`` to a fresh value before each call and asserts
    the response is unchanged. If a future change ever wires a handler to
    ``random``, these tests fail deterministically — the regression cannot hide
    behind a particular ``pytest-randomly`` seed.

    The test restores the RNG state in a ``finally`` block so it cannot leak
    into adjacent tests.
    """

    def test_health_unchanged_across_random_seeds(self, client: TestClient) -> None:
        """``/health`` status field is identical under 30 different RNG seeds."""
        rng_state = random.getstate()
        try:
            statuses: set[str] = set()
            for seed in range(30):
                random.seed(seed)
                statuses.add(client.get("/health").json()["status"])
            assert statuses == {"healthy"}, (
                f"/health responded differently under different RNG seeds: {statuses!r}"
            )
        finally:
            random.setstate(rng_state)

    def test_post_hello_message_unchanged_across_random_seeds(self, client: TestClient) -> None:
        """``POST /api/hello`` returns one ``message`` under 30 different RNG seeds."""
        rng_state = random.getstate()
        try:
            messages: set[str] = set()
            for seed in range(30):
                random.seed(seed)
                response = client.post("/api/hello", json={"name": "SeedStable"})
                messages.add(response.json()["message"])
            assert len(messages) == 1, (
                f"POST /api/hello responded differently under different RNG seeds: {messages!r}"
            )
        finally:
            random.setstate(rng_state)

    def test_version_body_unchanged_across_random_seeds(self, client: TestClient) -> None:
        """``/api/version`` body is byte-identical under 30 different RNG seeds.

        ``/api/version`` has no timestamp field, so a regression that injected
        a random component anywhere in the body would surface here first.
        """
        rng_state = random.getstate()
        try:
            bodies: set[bytes] = set()
            for seed in range(30):
                random.seed(seed)
                bodies.add(client.get("/api/version").content)
            assert len(bodies) == 1, (
                f"/api/version varied under different RNG seeds ({len(bodies)} distinct)"
            )
        finally:
            random.setstate(rng_state)


# Non-UTC IANA zones used to exercise the ``TZ`` env-var path. Each has a
# *different* offset from UTC so any naive-clock regression would produce a
# visibly different result under at least one of them.
NON_UTC_TZ_VALUES = ("America/New_York", "Asia/Tokyo", "Europe/Berlin", "Pacific/Auckland")


class TestTZEnvironmentVariableIndependence:
    """Handler timestamps must be UTC regardless of the ``TZ`` env variable.

    This is the canonical real-world flake source. A handler that uses
    ``datetime.now()`` (naive, returning *local* time) instead of
    ``datetime.now(UTC)`` produces correct output on developer machines
    running in UTC and on most CI runners — but silently fails (and only
    sometimes) on runners whose ``TZ`` is set to a non-UTC zone. Pin the
    invariant by toggling ``TZ`` via ``os.environ`` + ``time.tzset()``
    and asserting the emitted timestamp is still UTC ISO 8601.

    The original ``TZ`` value is restored in a ``finally`` block so the
    environment cannot leak into adjacent tests.
    """

    @staticmethod
    def _with_tz(tz: str | None, fn: object) -> object:
        """Run ``fn()`` with ``TZ`` set to ``tz`` (or unset if ``None``); restore on exit."""
        original = os.environ.get("TZ")
        try:
            if tz is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = tz
            time.tzset()
            return fn()  # type: ignore[operator]
        finally:
            if original is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = original
            time.tzset()

    @pytest.mark.parametrize("tz", NON_UTC_TZ_VALUES)
    def test_health_timestamp_is_utc_under_each_tz(self, client: TestClient, tz: str) -> None:
        """``/health`` returns a UTC-offset timestamp under every non-UTC ``TZ``."""
        timestamp = self._with_tz(tz, lambda: client.get("/health").json()["timestamp"])
        # ``assert_utc_iso8601`` raises if the offset isn't zero, which is
        # exactly the failure mode a naive-clock regression would produce
        # under a non-UTC ``TZ``.
        assert_utc_iso8601(str(timestamp))

    @pytest.mark.parametrize("tz", NON_UTC_TZ_VALUES)
    def test_post_hello_timestamp_is_utc_under_each_tz(self, client: TestClient, tz: str) -> None:
        """``POST /api/hello`` returns a UTC-offset timestamp under every non-UTC ``TZ``."""
        timestamp = self._with_tz(
            tz,
            lambda: client.post("/api/hello", json={"name": "TZGuard"}).json()["timestamp"],
        )
        assert_utc_iso8601(str(timestamp))

    def test_get_hello_timestamp_is_utc_under_rapid_tz_changes(self, client: TestClient) -> None:
        """Repeatedly flipping ``TZ`` between calls never produces a non-UTC timestamp.

        The combination — many requests *and* many ``TZ`` flips — exercises
        the worst case for the regression class: a handler that builds the
        timezone once at import time would pass single-tz tests but fail
        when ``TZ`` is mutated mid-session.
        """
        for tz in NON_UTC_TZ_VALUES * 5:  # 20 flips
            ts = self._with_tz(tz, lambda: client.get("/api/hello").json()["timestamp"])
            assert_utc_iso8601(str(ts))


class TestTimestampIsoFormatRoundTrip:
    """Every emitted timestamp must survive a ``isoformat → fromisoformat → isoformat``
    round-trip byte-for-byte.

    A regression that emits a non-canonical ISO 8601 form (e.g. omitting
    microseconds when they happen to be zero, then including them when
    they're non-zero) would still *parse* successfully — every existing
    test that calls ``datetime.fromisoformat`` would pass — but downstream
    consumers that compare timestamps byte-for-byte (log aggregators,
    cache keys, signed payloads) would see intermittent diffs.

    Pin the invariant: the emitted string equals
    ``datetime.fromisoformat(s).isoformat()``.
    """

    @staticmethod
    def _assert_round_trip(timestamp: str) -> None:
        round_tripped = datetime.fromisoformat(timestamp).isoformat()
        assert round_tripped == timestamp, (
            f"Timestamp {timestamp!r} did not survive isoformat round-trip (got {round_tripped!r})"
        )

    def test_health_timestamp_round_trips_across_50_calls(self, client: TestClient) -> None:
        """Every one of 50 sequential ``/health`` timestamps round-trips exactly."""
        for _ in range(50):
            self._assert_round_trip(client.get("/health").json()["timestamp"])

    def test_post_hello_timestamp_round_trips_across_50_calls(self, client: TestClient) -> None:
        """Every one of 50 sequential ``POST /api/hello`` timestamps round-trips exactly."""
        for _ in range(50):
            ts = client.post("/api/hello", json={"name": "RoundTrip"}).json()["timestamp"]
            self._assert_round_trip(ts)

    def test_health_timestamp_ends_with_utc_offset_marker(self, client: TestClient) -> None:
        """Every one of 50 ``/health`` timestamps ends with the canonical ``+00:00`` UTC marker.

        ``datetime.fromisoformat`` accepts both ``Z`` and ``+00:00`` — but
        switching between them mid-session would produce intermittent
        byte-level diffs even though both forms parse. Pin the *exact*
        suffix the handler emits today.
        """
        for _ in range(50):
            ts = client.get("/health").json()["timestamp"]
            assert ts.endswith("+00:00"), (
                f"Timestamp {ts!r} does not end with canonical '+00:00' marker"
            )


class TestOpenAPIParityHTTPVsDirectCall:
    """``/openapi.json`` (HTTP) and ``app.openapi()`` (direct) must agree.

    Two code paths lead to the schema dict — HTTP through the routing
    layer, and direct in-process via ``app.openapi()``. They should
    produce the same dict. A regression where a middleware mutates the
    response body (e.g. injects a per-request trace ID into the schema
    bytes) would diverge silently: every test that uses *only* the HTTP
    path would still see a deterministic response, and every test that
    uses *only* the direct path would too, but the two would no longer
    agree. Clients that fetch via HTTP would then see a different schema
    than tools that import ``app`` directly.
    """

    def test_http_openapi_equals_direct_openapi_call(self, client: TestClient) -> None:
        """The dict from ``/openapi.json`` deep-equals the dict from ``app.openapi()``."""
        http_schema = get_openapi_schema(client)
        direct_schema = app.openapi()
        assert http_schema == direct_schema, (
            "HTTP /openapi.json schema diverged from in-process app.openapi() output"
        )

    def test_http_and_direct_openapi_paths_match(self, client: TestClient) -> None:
        """The set of declared paths is identical between HTTP and direct."""
        http_paths = set(get_openapi_schema(client)["paths"].keys())
        direct_paths = set(app.openapi()["paths"].keys())
        assert http_paths == direct_paths, (
            f"HTTP paths {http_paths!r} != direct paths {direct_paths!r}"
        )

    def test_http_and_direct_openapi_components_match(self, client: TestClient) -> None:
        """The set of component-schema names is identical between HTTP and direct."""
        http_components = set(get_openapi_schema(client)["components"]["schemas"].keys())
        direct_components = set(app.openapi()["components"]["schemas"].keys())
        assert http_components == direct_components, (
            f"HTTP components {http_components!r} != direct components {direct_components!r}"
        )


class TestRepeatedSequentialColdCache:
    """Repeated sequential ``app.openapi_schema = None`` resets must yield
    byte-identical output every cycle.

    ``TestOpenAPISchemaUnderConcurrency`` clears the cache once and fires
    parallel rebuilds. This class instead clears the cache *many* times
    sequentially, which catches a different regression class: a generator
    with a *cumulative* per-rebuild side effect (e.g. appending the
    handler's tags to a module-level list on every rebuild). A single
    cold-cache reset would not surface that — but 30 sequential resets
    would visibly grow the output. Pin the invariant: every cycle
    produces the same bytes as the first.

    The original cache value is restored in a ``finally`` block so the
    reset cannot leak into adjacent tests.
    """

    def test_30_sequential_cold_cache_rebuilds_are_byte_identical(self, client: TestClient) -> None:
        """30 cycles of ``schema=None → fetch`` yield exactly one body hash."""
        original = app.openapi_schema
        app.openapi_schema = None
        try:
            bodies: set[bytes] = set()
            for _ in range(30):
                app.openapi_schema = None
                bodies.add(client.get("/openapi.json").content)
            assert len(bodies) == 1, (
                f"30 sequential cold-cache rebuilds produced {len(bodies)} distinct bodies "
                "(cumulative side-effect regression)"
            )
        finally:
            app.openapi_schema = original

    def test_cold_cache_rebuild_components_count_does_not_grow(self, client: TestClient) -> None:
        """The number of declared components stays constant across 20 cold rebuilds.

        Targets the specific cumulative-side-effect failure mode where a
        rebuild appends to ``app.openapi_components`` — bytes-identity
        catches the same regression, but a count check produces a
        clearer error message (``20 → 24`` rather than
        ``hash A → hash B``).
        """
        original = app.openapi_schema
        app.openapi_schema = None
        try:
            counts: set[int] = set()
            for _ in range(20):
                app.openapi_schema = None
                counts.add(len(get_openapi_schema(client)["components"]["schemas"]))
            assert len(counts) == 1, (
                f"Component count drifted across 20 cold rebuilds: observed {sorted(counts)}"
            )
        finally:
            app.openapi_schema = original


class TestErrorResponseBodyDeterminism:
    """404/405/422 error response bodies must be byte-identical across iterations.

    These responses come from Starlette's default exception handlers, not
    application code — but clients that compare error bodies byte-for-byte
    (log aggregators, fuzz-test oracles, cache keys) would still see
    intermittent diffs if a future change wired the error handler to
    e.g. include a per-request trace ID in the body. Pin the byte
    determinism so any such regression fails loudly here rather than
    surfacing as confusing client-side intermittence weeks later.

    Each test asserts both that the body is byte-stable *and* that the
    same body appears for both allow-listed and disallowed origins — a
    regression that varied the body by origin would fail one of the two
    assertions even if the per-origin body itself was stable.
    """

    def test_404_body_is_byte_identical_across_50_calls(self, client: TestClient) -> None:
        """50 ``GET /no-such-path`` responses share exactly one body hash."""
        bodies = {client.get("/no-such-path").content for _ in range(50)}
        assert len(bodies) == 1, (
            f"/no-such-path 404 body varied across 50 calls ({len(bodies)} distinct)"
        )

    def test_405_body_is_byte_identical_across_50_calls(self, client: TestClient) -> None:
        """50 ``DELETE /api/hello`` responses (method not allowed) share one body hash."""
        bodies = {client.delete("/api/hello").content for _ in range(50)}
        assert len(bodies) == 1, (
            f"/api/hello 405 body varied across 50 calls ({len(bodies)} distinct)"
        )

    def test_422_body_is_byte_identical_across_50_calls(self, client: TestClient) -> None:
        """50 malformed ``POST /api/hello`` requests yield exactly one 422 body."""
        # Missing required ``name`` field → 422 with a stable, schema-driven body.
        bodies = {client.post("/api/hello", json={}).content for _ in range(50)}
        assert len(bodies) == 1, (
            f"/api/hello 422 body varied across 50 calls ({len(bodies)} distinct)"
        )

    def test_404_body_does_not_depend_on_origin(self, client: TestClient) -> None:
        """The 404 body is the same whether the request comes from an allow-listed
        or a disallowed origin.

        A regression that wove origin into the error body (e.g. echoing the
        origin into a CORS-rejection JSON payload) would break clients that
        compare 404 bodies across runs from different deployment hosts.
        """
        allowed = client.get("/no-such-path", headers={"Origin": LOCALHOST_ORIGIN}).content
        disallowed = client.get("/no-such-path", headers={"Origin": DISALLOWED_ORIGIN}).content
        no_origin = client.get("/no-such-path").content
        assert allowed == disallowed == no_origin, (
            "404 body varied by Origin header — error body should be origin-agnostic"
        )


# Number of OS threads / requests for the threaded-concurrency guards. 32 is
# enough to genuinely overlap on a multi-core runner without producing test-
# runner noise; each request is sub-millisecond so the whole class adds <1s.
THREADED_FANOUT = 32


class TestThreadedConcurrencyDeterminism:
    """Handlers must stay correct under *true OS-thread* parallelism.

    Every other concurrency guard in this module fans out with
    ``asyncio.gather`` on a single-threaded event loop — coroutines interleave
    but never run on two CPUs at the same instant. Starlette's synchronous
    ``TestClient`` instead drives the ASGI app through an internal worker
    thread, so a pool of threads issuing requests exercises a genuinely
    different execution model: handlers can run *simultaneously* on multiple
    cores. A regression that is invisible to cooperative interleaving — a
    module-level mutable default, a non-atomic read-modify-write on shared
    state, a handler that stashes the request name on a shared object — would
    surface here as cross-contaminated responses, and only intermittently,
    because the race window depends on OS thread scheduling.

    These tests pin the invariant that the pure-function handlers return the
    same answers under thread-pool parallelism as they do sequentially.
    """

    def test_threaded_posts_each_receive_their_own_name(self) -> None:
        """32 distinct POSTs fired across a thread pool each echo their own name.

        Cross-contamination (request A receiving request B's name) is the
        canonical symptom of shared mutable per-request state and is exactly
        the failure mode that only a true-parallel runner can surface.
        """
        names = [f"Thread{i:03d}" for i in range(THREADED_FANOUT)]

        def post_name(name: str) -> tuple[str, str]:
            # A fresh client per thread mirrors the multi-worker production
            # model and avoids serialising on a single client's internals.
            with TestClient(app) as c:
                message = c.post("/api/hello", json={"name": name}).json()["message"]
            return name, name_from_greeting(message)

        with ThreadPoolExecutor(max_workers=THREADED_FANOUT) as pool:
            results = list(pool.map(post_name, names))

        mismatches = [(sent, got) for sent, got in results if sent != got]
        assert not mismatches, (
            f"{len(mismatches)} threaded POSTs received another request's name "
            f"(cross-contamination under true parallelism): {mismatches[:5]!r}"
        )

    def test_threaded_identical_posts_return_one_message(self) -> None:
        """32 identical POSTs across a thread pool yield exactly one ``message``.

        The complement of the distinct-name test: with identical input, true
        parallel execution must still collapse to a single deterministic
        answer. A divergence means a handler consulted some non-deterministic
        shared state (a clock baked into ``message``, a counter, the RNG).
        """

        def post_stable(_: int) -> str:
            with TestClient(app) as c:
                return str(c.post("/api/hello", json={"name": "ThreadStable"}).json()["message"])

        with ThreadPoolExecutor(max_workers=THREADED_FANOUT) as pool:
            messages = set(pool.map(post_stable, range(THREADED_FANOUT)))
        assert len(messages) == 1, (
            f"{THREADED_FANOUT} identical threaded POSTs produced "
            f"{len(messages)} distinct messages: {messages!r}"
        )

    def test_threaded_health_all_healthy(self) -> None:
        """32 concurrent ``/health`` calls across a thread pool all report healthy.

        A shared-state regression in an unrelated handler could corrupt the
        ``/health`` response if state leaked across handlers running on
        different threads. Pin the constant.
        """

        def get_status(_: int) -> str:
            with TestClient(app) as c:
                return str(c.get("/health").json()["status"])

        with ThreadPoolExecutor(max_workers=THREADED_FANOUT) as pool:
            statuses = set(pool.map(get_status, range(THREADED_FANOUT)))
        assert statuses == {"healthy"}, (
            f"Threaded /health calls returned non-uniform statuses: {statuses!r}"
        )

    def test_threaded_mixed_get_post_each_correct_shape(self) -> None:
        """Interleaved GET and POST across a thread pool each return their own shape.

        Mixing read and write handlers on genuinely parallel threads is the
        worst case for a shared-state leak between *different* handlers (as
        opposed to two instances of the same handler). Each response must
        carry the body its own route declares.
        """

        def call(i: int) -> tuple[str, str]:
            with TestClient(app) as c:
                if i % 2 == 0:
                    return "GET", str(c.get("/api/hello").json()["message"])
                return "POST", str(
                    c.post("/api/hello", json={"name": f"Mix{i:03d}"}).json()["message"]
                )

        with ThreadPoolExecutor(max_workers=THREADED_FANOUT) as pool:
            results = list(pool.map(call, range(THREADED_FANOUT)))

        for idx, (kind, message) in enumerate(results):
            if kind == "GET":
                assert "World" in message, (
                    f"threaded GET /api/hello returned non-default message: {message!r}"
                )
            else:
                assert name_from_greeting(message) == f"Mix{idx:03d}", (
                    f"threaded POST at idx {idx} did not echo its own name: {message!r}"
                )
