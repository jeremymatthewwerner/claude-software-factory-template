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
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.conftest import LOCALHOST_ORIGIN, openapi_component_for_response

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
        schema = client.get("/openapi.json").json()
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
        schema = client.get("/openapi.json").json()
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
