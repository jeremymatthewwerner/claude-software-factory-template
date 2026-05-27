"""
Integration-gap tests (Wednesday QA focus).

Line coverage for ``app/main.py`` is already at 100% — these tests target
cross-component integrations that the existing suite does not pin:

1. CORS headers on error responses (404 / 405 / 422). The existing CORS tests
   only assert behaviour on successful 2xx responses, so a regression that
   strips CORS headers from FastAPI's error responses would silently break the
   browser's ability to surface the real error to JavaScript.
2. ASGI lifespan integration. ``grep -r lifespan backend/tests`` returns
   nothing, so a regression that adds a throwing startup hook would pass tests
   yet fail at runtime under uvicorn.
3. ``/docs`` and ``/redoc`` HTML wiring. Existing tests only assert a 200
   status — they would still pass if FastAPI were configured with
   ``openapi_url=None`` (which breaks the docs UIs in practice).
4. AsyncClient schema-contract integration. ``TestOpenAPISchemaContract``
   covers this via ``TestClient`` only; the real ASGI transport path is
   untested for documented-shape conformance.
5. ``Vary: Origin`` on real allow-listed responses (not just preflight),
   which shared caches need to keep per-origin entries safe.
6. ``OPTIONS`` without any CORS headers. Existing tests cover OPTIONS with
   malformed CORS headers but not the bare OPTIONS-without-Origin case.
7. Interleaved requests from both allow-listed origins
   (``http://localhost:3000`` and ``http://127.0.0.1:3000``), to pin that
   the ``Access-Control-Allow-Origin`` echo is computed per-request.

Wednesday top-up (integration scenarios not covered by 1–7 above and not
duplicated anywhere else in the suite — verified by ``grep`` before adding):

8. CORS **preflight to a non-existent route**. ``CORSMiddleware`` runs
   *before* the router, so a real preflight (Origin + ACRM) on ``/api/missing``
   short-circuits to 200 with full CORS headers — never reaching the 404
   handler. A regression that reorders middleware or moves CORS *inside* the
   router would silently break the browser's preflight for any path the
   browser is exploring.
9. ``OPTIONS`` with **Origin only, no ACRM**. Bare-OPTIONS-without-Origin is
   pinned by `TestOPTIONSWithoutCORSHeaders`. The half-CORS case — Origin
   present but ``Access-Control-Request-Method`` absent — must fall through
   to the router (405) yet still get CORS headers attached on the way out.
10. OpenAPI schema must **not** declare ``OPTIONS`` or ``HEAD`` operations.
    CORSMiddleware handles OPTIONS; FastAPI auto-handles HEAD. An accidental
    ``methods=["OPTIONS", ...]`` on a decorator would pollute SDK generators
    with phantom operations — pin the negative inventory.
11. **AsyncClient error-path parity** (404 / 405). 422 over the real ASGI
    transport is pinned (``test_invalid_post_body_returns_422_via_async_client``);
    404 and 405 are not. A regression that changed framing only on the error
    path would slip past the in-process ``TestClient``.
12. ``/openapi.json`` **byte-equivalence between TestClient and AsyncClient**.
    Byte stability across calls of *one* transport is pinned; cross-transport
    parity is not. Catches a regression that emits transport-specific framing
    bytes (e.g. an extra trailing newline only on one path).
13. ``Access-Control-Expose-Headers`` is **not** advertised. The middleware
    was not configured with ``expose_headers``; pinning the negative guards
    against an accidental addition that would leak internal headers to JS.
14. Sequential calls through one persistent ``AsyncClient`` maintain handler
    isolation. Existing async-concurrency tests use ``asyncio.gather``;
    sequential reuse of a single client (which keeps the ASGI transport alive
    across calls) is not pinned and exercises a different code path.
15. ``Access-Control-Request-Method`` is **case-sensitive** per Starlette's
    implementation: ``POST`` → 200, ``post`` → 400 ``Disallowed CORS method``.
    The Fetch spec keeps the token case-sensitive (browsers always send
    uppercase), but a regression that lower-cased the comparison would
    silently accept malformed clients — pin the current behaviour.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.conftest import (
    LOCALHOST_ORIGIN,
    get_openapi_schema,
    openapi_component_for_response,
)

LOOPBACK_ORIGIN = "http://127.0.0.1:3000"
DISALLOWED_ORIGIN = "http://evil.example"


class TestCORSOnErrorResponses:
    """CORS headers must survive on 404 / 405 / 422 from an allow-listed origin.

    A browser issuing ``fetch('http://api/...', { mode: 'cors' })`` cannot read
    the body of an error response unless the response carries the CORS headers
    that match the request's origin. If the middleware ever stops wrapping
    error responses (e.g. a regression that registers an exception handler
    *outside* the CORSMiddleware chain), the JS client just sees an opaque
    network error and can never tell a 404 from a 500.
    """

    def test_404_from_allowlisted_origin_carries_acao_and_vary(self, client: TestClient) -> None:
        """A 404 from an allow-listed origin still echoes the origin and Vary."""
        response = client.get("/api/missing", headers={"Origin": LOCALHOST_ORIGIN})
        assert response.status_code == 404
        assert response.headers.get("access-control-allow-origin") == LOCALHOST_ORIGIN
        assert response.headers.get("vary") == "Origin"

    def test_405_from_allowlisted_origin_carries_acao_and_vary(self, client: TestClient) -> None:
        """A 405 from an allow-listed origin still echoes the origin and Vary."""
        response = client.delete("/health", headers={"Origin": LOCALHOST_ORIGIN})
        assert response.status_code == 405
        assert response.headers.get("access-control-allow-origin") == LOCALHOST_ORIGIN
        assert response.headers.get("vary") == "Origin"

    def test_422_from_allowlisted_origin_carries_acao_and_vary(self, client: TestClient) -> None:
        """A 422 from an allow-listed origin still echoes the origin and Vary."""
        response = client.post("/api/hello", json={}, headers={"Origin": LOCALHOST_ORIGIN})
        assert response.status_code == 422
        assert response.headers.get("access-control-allow-origin") == LOCALHOST_ORIGIN
        assert response.headers.get("vary") == "Origin"

    def test_404_from_disallowed_origin_omits_acao(self, client: TestClient) -> None:
        """A 404 from a disallowed origin must not leak any ACAO header."""
        response = client.get("/api/missing", headers={"Origin": DISALLOWED_ORIGIN})
        assert response.status_code == 404
        assert response.headers.get("access-control-allow-origin") is None

    def test_422_from_disallowed_origin_omits_acao(self, client: TestClient) -> None:
        """A 422 from a disallowed origin must not leak any ACAO header."""
        response = client.post("/api/hello", json={}, headers={"Origin": DISALLOWED_ORIGIN})
        assert response.status_code == 422
        assert response.headers.get("access-control-allow-origin") is None


class TestASGILifespanIntegration:
    """Pin that the FastAPI app boots and tears down through the ASGI lifespan.

    ``app.router.lifespan_context`` is what uvicorn enters in production. The
    existing suite uses ``TestClient`` and ``AsyncClient`` fixtures, both of
    which start the app, but no test exercises the lifespan window *directly*
    or asserts that a request inside that window succeeds. A regression that
    adds a startup hook raising an exception would only surface under uvicorn.
    """

    @pytest.mark.asyncio
    async def test_app_serves_requests_inside_lifespan_window(self) -> None:
        """Entering the lifespan, a request must succeed; exit must not raise."""
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                response = await ac.get("/health")
                assert response.status_code == 200
                assert response.json()["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_lifespan_can_be_entered_and_exited_repeatedly(self) -> None:
        """Repeated lifespan cycles must not raise (no stuck startup state)."""
        for _ in range(3):
            async with app.router.lifespan_context(app):
                pass


class TestDocsHTMLWiring:
    """``/docs`` and ``/redoc`` HTML must reference the canonical openapi URL.

    Existing tests only assert ``200``. They would still pass if FastAPI were
    configured with ``openapi_url=None`` (no schema served) or
    ``openapi_url="/api/openapi.json"`` (schema moved): the docs UIs would
    appear loaded but fetch a 404 for the schema and render an empty page.
    These tests pin the HTML payload so that breakage fails loudly.
    """

    def test_docs_html_references_canonical_openapi_url(self, client: TestClient) -> None:
        """Swagger UI HTML must point at ``/openapi.json``, not at None."""
        response = client.get("/docs")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "/openapi.json" in response.text

    def test_docs_html_embeds_app_title(self, client: TestClient) -> None:
        """Swagger UI HTML must embed the app title for window-title parity."""
        response = client.get("/docs")
        assert "Software Factory API" in response.text

    def test_redoc_html_references_canonical_openapi_url(self, client: TestClient) -> None:
        """ReDoc HTML must point at ``/openapi.json``, not at None."""
        response = client.get("/redoc")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "/openapi.json" in response.text

    def test_redoc_html_embeds_app_title(self, client: TestClient) -> None:
        """ReDoc HTML must embed the app title for window-title parity."""
        response = client.get("/redoc")
        assert "Software Factory API" in response.text


class TestAsyncClientSchemaContract:
    """Every documented 200 route must conform to its schema via real ASGI.

    ``TestOpenAPISchemaContract`` already does this with ``TestClient`` (which
    drives the app in-process without exercising the ASGI transport's
    request/response framing). This class repeats the check via the
    ``httpx.AsyncClient`` + ``ASGITransport`` pair so a regression that breaks
    response framing on the async path (e.g. switching to a non-conforming
    response class) is caught here.
    """

    @pytest.mark.asyncio
    async def test_documented_get_routes_response_keys_match_schema(
        self, async_client: AsyncClient, client: TestClient
    ) -> None:
        """For every documented GET 200, the live keys must match the component."""
        schema = get_openapi_schema(client)
        for path, methods in schema["paths"].items():
            if "get" not in methods:
                continue
            component = openapi_component_for_response(schema, path, "get", "200")
            documented_keys = set(component["properties"].keys())
            response = await async_client.get(path)
            assert response.status_code == 200, (
                f"GET {path} returned {response.status_code} via AsyncClient"
            )
            actual_keys = set(response.json().keys())
            assert actual_keys == documented_keys, (
                f"GET {path}: schema documents {documented_keys}, response returned {actual_keys}"
            )

    @pytest.mark.asyncio
    async def test_documented_post_hello_response_keys_match_schema(
        self, async_client: AsyncClient, client: TestClient
    ) -> None:
        """The documented POST 200 keys must match the live response keys."""
        schema = get_openapi_schema(client)
        component = openapi_component_for_response(schema, "/api/hello", "post", "200")
        documented_keys = set(component["properties"].keys())
        response = await async_client.post("/api/hello", json={"name": "Ada"})
        assert response.status_code == 200
        assert set(response.json().keys()) == documented_keys


class TestCORSVaryOnRealRequest:
    """Real (non-preflight) allow-listed responses must carry ``Vary: Origin``.

    Preflight ``Vary: Origin`` is already pinned by
    ``TestCORSCacheCorrectness.test_preflight_response_includes_vary_origin``.
    A shared cache (CDN, browser disk cache) also needs ``Vary: Origin`` on
    the *actual* GET/POST response — otherwise a cached response served to
    origin A could be replayed for origin B with the wrong ACAO header.
    """

    def test_allowlisted_get_response_includes_vary_origin(self, client: TestClient) -> None:
        """GET from an allow-listed origin must carry ``Vary: Origin``."""
        response = client.get("/health", headers={"Origin": LOCALHOST_ORIGIN})
        assert response.status_code == 200
        assert response.headers.get("vary") == "Origin"

    def test_allowlisted_post_response_includes_vary_origin(self, client: TestClient) -> None:
        """POST from an allow-listed origin must carry ``Vary: Origin``."""
        response = client.post(
            "/api/hello",
            json={"name": "Ada"},
            headers={"Origin": LOCALHOST_ORIGIN},
        )
        assert response.status_code == 200
        assert response.headers.get("vary") == "Origin"


class TestOPTIONSWithoutCORSHeaders:
    """Bare OPTIONS (no Origin, no Access-Control-Request-Method) must be 405.

    ``CORSMiddleware`` synthesizes a 200 only for *real* preflights — i.e. when
    the request carries ``Origin`` and ``Access-Control-Request-Method``. A
    plain OPTIONS request (e.g. ``curl -X OPTIONS``) must fall through to the
    router, which has no OPTIONS handler and so returns 405. Pinning this
    behaviour prevents a regression where the middleware starts answering 200
    to any OPTIONS, which would mask a real CORS misconfiguration in
    integration tests.
    """

    def test_options_without_cors_headers_on_api_hello_returns_405(
        self, client: TestClient
    ) -> None:
        """Bare OPTIONS to ``/api/hello`` must be 405, not a synthesized 200."""
        response = client.options("/api/hello")
        assert response.status_code == 405

    def test_options_without_cors_headers_on_health_returns_405(self, client: TestClient) -> None:
        """Bare OPTIONS to ``/health`` must be 405, not a synthesized 200."""
        response = client.options("/health")
        assert response.status_code == 405


class TestMultipleAllowListedOriginsInterleaved:
    """Both allow-listed origins must be echoed per-request, not first-wins.

    ``CORSMiddleware`` is stateless per request, but a regression that caches
    the matched origin at module import time (e.g. via ``functools.cache``)
    would have ACAO ‘stick’ to whichever origin called first. Pin the
    per-request behaviour with interleaved calls from both allow-listed
    origins so a stickiness regression fails loudly.
    """

    def test_acao_is_echoed_per_request_across_allowlisted_origins(
        self, client: TestClient
    ) -> None:
        """Interleaved GETs from two allow-listed origins each get their own echo."""
        for _ in range(3):
            r1 = client.get("/health", headers={"Origin": LOCALHOST_ORIGIN})
            r2 = client.get("/health", headers={"Origin": LOOPBACK_ORIGIN})
            assert r1.headers.get("access-control-allow-origin") == LOCALHOST_ORIGIN
            assert r2.headers.get("access-control-allow-origin") == LOOPBACK_ORIGIN

    def test_acao_is_echoed_per_request_for_post(self, client: TestClient) -> None:
        """Interleaved POSTs from two allow-listed origins each get their own echo."""
        for _ in range(3):
            r1 = client.post(
                "/api/hello",
                json={"name": "a"},
                headers={"Origin": LOCALHOST_ORIGIN},
            )
            r2 = client.post(
                "/api/hello",
                json={"name": "b"},
                headers={"Origin": LOOPBACK_ORIGIN},
            )
            assert r1.headers.get("access-control-allow-origin") == LOCALHOST_ORIGIN
            assert r2.headers.get("access-control-allow-origin") == LOOPBACK_ORIGIN


class TestCORSPreflightShortCircuitsBeforeRouting:
    """A real preflight on a **non-existent** route returns 200 from CORSMiddleware.

    Starlette's ``CORSMiddleware`` is installed *before* the router. When it
    sees a request carrying both ``Origin`` and
    ``Access-Control-Request-Method``, it handles the preflight directly and
    never delegates to the router — so the path can be anything (registered
    or not). A regression that moved CORS *into* the router, or installed an
    exception handler that intercepted OPTIONS before CORS, would break the
    browser's preflight for any URL the JS client tries (including 404 paths
    explored during development), even though normal requests still work.
    """

    def test_preflight_on_nonexistent_path_returns_200(self, client: TestClient) -> None:
        """OPTIONS + Origin + ACRM on ``/api/missing`` is handled by CORSMiddleware (200)."""
        response = client.options(
            "/api/missing",
            headers={
                "Origin": LOCALHOST_ORIGIN,
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 200, (
            f"Preflight on a non-existent path must be handled by CORSMiddleware "
            f"before routing — got {response.status_code} (router-level 404 would "
            f"indicate middleware ordering regression)"
        )

    def test_preflight_on_nonexistent_path_carries_acao(self, client: TestClient) -> None:
        """The short-circuited preflight still echoes the allow-listed origin."""
        response = client.options(
            "/api/missing",
            headers={
                "Origin": LOCALHOST_ORIGIN,
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.headers.get("access-control-allow-origin") == LOCALHOST_ORIGIN

    def test_preflight_on_nonexistent_path_advertises_allow_methods(
        self, client: TestClient
    ) -> None:
        """The short-circuited preflight advertises ``Access-Control-Allow-Methods``."""
        response = client.options(
            "/api/missing",
            headers={
                "Origin": LOCALHOST_ORIGIN,
                "Access-Control-Request-Method": "POST",
            },
        )
        allow_methods = response.headers.get("access-control-allow-methods")
        assert allow_methods is not None and "POST" in allow_methods, (
            f"Preflight short-circuit must advertise allowed methods; got {allow_methods!r}"
        )


class TestOPTIONSWithOriginButNoACRMFallsThrough:
    """``OPTIONS`` with ``Origin`` set but **no** ``Access-Control-Request-Method``.

    The Fetch spec defines a CORS preflight as a request that carries *both*
    headers. ``CORSMiddleware`` treats a request with only ``Origin`` (no
    ACRM) as a non-preflight, so it falls through to the router. The router
    has no OPTIONS handler for ``/api/hello`` or ``/health`` and returns 405.
    On the way back the middleware still attaches the allow-listed CORS
    headers (because Origin was present and allow-listed).

    A regression that classified this half-CORS case as a preflight would
    synthesize a 200 with no application logic — silently letting browsers
    "succeed" the preflight even though the real method would 405. Pin the
    distinction.
    """

    def test_options_with_origin_only_returns_405(self, client: TestClient) -> None:
        """OPTIONS to ``/api/hello`` with Origin but no ACRM returns 405 (router)."""
        response = client.options(
            "/api/hello",
            headers={"Origin": LOCALHOST_ORIGIN},
        )
        assert response.status_code == 405, (
            f"OPTIONS with Origin but no Access-Control-Request-Method must fall "
            f"through to the router (405), not be treated as a preflight. Got "
            f"{response.status_code}."
        )

    def test_options_with_origin_only_still_carries_acao(self, client: TestClient) -> None:
        """The 405 response still carries the allow-listed CORS headers.

        Because the request came from an allow-listed origin, CORSMiddleware
        wraps the 405 with ``Access-Control-Allow-Origin`` on the way out —
        so the browser can read the 405 status.
        """
        response = client.options(
            "/api/hello",
            headers={"Origin": LOCALHOST_ORIGIN},
        )
        assert response.headers.get("access-control-allow-origin") == LOCALHOST_ORIGIN

    def test_options_with_disallowed_origin_only_omits_acao(self, client: TestClient) -> None:
        """OPTIONS with a disallowed Origin (no ACRM) returns 405 *without* ACAO."""
        response = client.options(
            "/api/hello",
            headers={"Origin": DISALLOWED_ORIGIN},
        )
        assert response.status_code == 405
        assert response.headers.get("access-control-allow-origin") is None


class TestOpenAPIPathsDoNotDeclareOptionsOrHead:
    """Documented OpenAPI operations must not include ``OPTIONS`` or ``HEAD``.

    ``CORSMiddleware`` handles OPTIONS implicitly; FastAPI auto-handles HEAD
    by reusing the GET handler. Neither should appear as a *documented*
    operation in ``/openapi.json`` — they are protocol-level conveniences,
    not part of the public API contract.

    A regression that decorated a handler with
    ``@app.api_route(..., methods=["GET", "OPTIONS", "HEAD"])`` (a common
    mistake when chasing a CORS issue) would pollute generated SDKs with
    phantom ``optionsHealth()`` / ``headHealth()`` methods. Pin the negative
    so the SDK surface stays minimal.
    """

    def test_no_path_declares_an_options_operation(self, client: TestClient) -> None:
        """No path in ``/openapi.json`` declares an ``options`` operation."""
        schema = get_openapi_schema(client)
        offending = {
            path: list(methods.keys())
            for path, methods in schema["paths"].items()
            if "options" in methods
        }
        assert not offending, (
            f"OpenAPI paths must not declare OPTIONS operations (CORSMiddleware "
            f"handles them); found: {offending}"
        )

    def test_no_path_declares_a_head_operation(self, client: TestClient) -> None:
        """No path in ``/openapi.json`` declares a ``head`` operation."""
        schema = get_openapi_schema(client)
        offending = {
            path: list(methods.keys())
            for path, methods in schema["paths"].items()
            if "head" in methods
        }
        assert not offending, (
            f"OpenAPI paths must not declare HEAD operations (FastAPI auto-handles "
            f"them); found: {offending}"
        )


class TestAsyncClientErrorPathParity:
    """404 and 405 over the real ASGI transport match the in-process TestClient.

    ``TestRegressionAsyncClient.test_invalid_post_body_returns_422_via_async_client``
    pins 422 across the AsyncClient path. 404 and 405 are not pinned over the
    real ASGI transport — a regression that broke error-response framing only
    on the async path (e.g. a custom response class that bypassed Starlette's
    error handlers) would slip past the in-process ``TestClient`` and only
    surface under uvicorn.
    """

    @pytest.mark.asyncio
    async def test_404_via_async_client_has_documented_shape(
        self, async_client: AsyncClient
    ) -> None:
        """GET /api/missing via AsyncClient returns 404 with the documented body."""
        response = await async_client.get("/api/missing")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/json")
        body = response.json()
        assert body == {"detail": "Not Found"}

    @pytest.mark.asyncio
    async def test_405_via_async_client_has_documented_shape(
        self, async_client: AsyncClient
    ) -> None:
        """DELETE /health via AsyncClient returns 405 with the documented body."""
        response = await async_client.delete("/health")
        assert response.status_code == 405
        assert response.headers["content-type"].startswith("application/json")
        body = response.json()
        assert body == {"detail": "Method Not Allowed"}


class TestOpenAPIByteEquivalentAcrossTransports:
    """``/openapi.json`` body must be byte-identical from TestClient and AsyncClient.

    Existing flakiness guards pin byte stability across repeated calls of
    *one* transport. Cross-transport parity is a different pin: a regression
    that emitted transport-specific framing (e.g. an extra trailing newline,
    a different ``ensure_ascii`` setting, key reordering) only on one path
    would slip past every existing test. Pinning byte equality between the
    two ASGI paths catches that.
    """

    @pytest.mark.asyncio
    async def test_openapi_bytes_are_identical_via_both_transports(
        self, client: TestClient, async_client: AsyncClient
    ) -> None:
        """``/openapi.json`` returns byte-identical bodies via TestClient and AsyncClient."""
        sync_body = client.get("/openapi.json").content
        async_body = (await async_client.get("/openapi.json")).content
        assert sync_body == async_body, (
            f"/openapi.json diverged across transports: TestClient "
            f"{len(sync_body)} bytes, AsyncClient {len(async_body)} bytes"
        )


class TestNoExposeHeadersAdvertised:
    """``Access-Control-Expose-Headers`` must not be present on any response.

    The CORS middleware was instantiated without an ``expose_headers``
    argument, so by default Starlette does not emit
    ``Access-Control-Expose-Headers``. Pinning the *absence* of this header
    guards against an accidental addition (e.g. someone copy-pasting a
    middleware config that exposed internal headers like ``X-Request-ID``
    or ``X-Internal-Trace``) — a quiet information-disclosure regression
    that no other test would catch.
    """

    def test_get_response_does_not_advertise_expose_headers(self, client: TestClient) -> None:
        """GET /health from an allow-listed origin omits Access-Control-Expose-Headers."""
        response = client.get("/health", headers={"Origin": LOCALHOST_ORIGIN})
        assert response.headers.get("access-control-expose-headers") is None, (
            f"Unexpected Access-Control-Expose-Headers on GET /health: "
            f"{response.headers.get('access-control-expose-headers')!r}"
        )

    def test_post_response_does_not_advertise_expose_headers(self, client: TestClient) -> None:
        """POST /api/hello from an allow-listed origin omits Access-Control-Expose-Headers."""
        response = client.post(
            "/api/hello",
            json={"name": "ExposeProbe"},
            headers={"Origin": LOCALHOST_ORIGIN},
        )
        assert response.headers.get("access-control-expose-headers") is None

    def test_preflight_response_does_not_advertise_expose_headers(self, client: TestClient) -> None:
        """The preflight response itself also omits Access-Control-Expose-Headers."""
        response = client.options(
            "/api/hello",
            headers={
                "Origin": LOCALHOST_ORIGIN,
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 200
        assert response.headers.get("access-control-expose-headers") is None


class TestSequentialReuseAcrossPersistentAsyncClient:
    """Sequential calls through one ``AsyncClient`` maintain handler isolation.

    Existing async-concurrency tests use ``asyncio.gather`` to fire requests
    in parallel. **Sequential reuse** of one persistent client — the pattern
    a real SDK uses (one client, many awaited calls) — is not pinned. The
    transport here is ``ASGITransport`` which keeps the app alive across
    calls; if a handler ever cached request-local state on the app instance,
    a sequential pattern through one client would expose it where parallel
    fire-and-collect would not.
    """

    @pytest.mark.asyncio
    async def test_sequential_posts_through_one_client_isolate_names(
        self, async_client: AsyncClient
    ) -> None:
        """Five sequential POSTs through one AsyncClient each echo their own name."""
        names = ["Ada", "Bob", "Carol", "Dan", "Eve"]
        for name in names:
            response = await async_client.post("/api/hello", json={"name": name})
            assert response.status_code == 200
            assert name in response.json()["message"], (
                f"Sequential reuse leaked name across requests — POST({name}) "
                f"got back {response.json()['message']!r}"
            )

    @pytest.mark.asyncio
    async def test_sequential_get_then_post_through_one_client(
        self, async_client: AsyncClient
    ) -> None:
        """A GET followed by a POST through one client returns each shape correctly."""
        get_response = await async_client.get("/api/hello")
        post_response = await async_client.post("/api/hello", json={"name": "Sequence"})
        assert get_response.status_code == 200
        assert post_response.status_code == 200
        assert "World" in get_response.json()["message"]
        assert "Sequence" in post_response.json()["message"]


class TestCORSPreflightACRMIsCaseSensitive:
    """``Access-Control-Request-Method`` is case-sensitive per Starlette.

    The Fetch spec treats the ACRM token as case-sensitive — browsers always
    send uppercase tokens (``POST``, ``GET``, …). Starlette's
    ``CORSMiddleware`` honours that: uppercase ACRM → 200, lowercase or
    mixed-case → 400 ``Disallowed CORS method``.

    A regression that lower-cased the comparison for "permissiveness" would
    silently accept malformed clients and mask client-side bugs. Pin the
    current behaviour so a future change is a conscious decision.
    """

    @pytest.mark.parametrize(
        "method",
        ["POST", "GET", "PUT", "DELETE"],
        ids=["POST", "GET", "PUT", "DELETE"],
    )
    def test_uppercase_acrm_succeeds(self, client: TestClient, method: str) -> None:
        """Uppercase ACRM tokens pass the preflight and return 200."""
        response = client.options(
            "/api/hello",
            headers={
                "Origin": LOCALHOST_ORIGIN,
                "Access-Control-Request-Method": method,
            },
        )
        assert response.status_code == 200, (
            f"Uppercase ACRM {method!r} should pass preflight, got {response.status_code}"
        )

    @pytest.mark.parametrize(
        "method",
        ["post", "Post", "pOST"],
        ids=["lowercase", "titlecase", "mixedcase"],
    )
    def test_non_uppercase_acrm_returns_400(self, client: TestClient, method: str) -> None:
        """Lower/mixed-case ACRM tokens are rejected with 400."""
        response = client.options(
            "/api/hello",
            headers={
                "Origin": LOCALHOST_ORIGIN,
                "Access-Control-Request-Method": method,
            },
        )
        assert response.status_code == 400, (
            f"ACRM {method!r} (non-uppercase) should be rejected with 400, "
            f"got {response.status_code}"
        )
