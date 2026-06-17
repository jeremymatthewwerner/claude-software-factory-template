"""
Meta-endpoint HTTP-contract gap tests (Wednesday QA focus: integration-gaps).

Line/branch coverage for ``app/main.py`` is already at 100%, so the remaining
gap is *behavioural*, not line-based. The application routes (``/health``,
``/api/version``, ``/api/hello``) are pinned exhaustively, but the three
endpoints FastAPI serves *for free* — ``/openapi.json``, ``/docs`` (Swagger UI)
and ``/redoc`` — are part of the live HTTP surface and almost entirely
unpinned. Today they are only asserted to return ``200`` (``test_main``) and to
honour the CORS allow-list (``test_edge_cases``). Their HTTP *contract* is not:

1. **Content-Type.** ``/openapi.json`` must serve ``application/json`` and the
   two HTML UIs must serve ``text/html; charset=utf-8``. A regression that
   re-routed ``/docs`` to a JSON responder, or dropped the charset, would break
   browser rendering while every status-code test still passed.

2. **Method rejection.** These are GET surfaces; ``POST``/``PUT``/``DELETE``/
   ``PATCH`` must return ``405``. The ``405`` ``Allow`` header advertises the
   methods the route *does* accept, which clients (and the Railway health-check
   that opens ``/docs``) rely on.

3. **HEAD is auto-handled here — the asymmetry worth pinning.** Unlike the
   app's ``@app.get`` routes, which register a method set of exactly ``{"GET"}``
   and therefore answer ``HEAD`` with ``405`` (see
   ``test_routing_integration_gaps.TestHeadMethodReturns405``), the FastAPI
   meta-endpoints are mounted as plain Starlette routes whose default method
   set includes ``HEAD``. So ``HEAD /openapi.json`` returns ``200`` and their
   ``405`` ``Allow`` header reads ``GET, HEAD``. This GET-vs-meta divergence is
   surprising and entirely unpinned; a FastAPI upgrade or a ``docs_url`` change
   could flip it silently.

4. **Served ``/openapi.json`` body shape.** Beyond returning ``200``, the bytes
   on the wire must parse as JSON and carry an OpenAPI ``3.x`` ``openapi``
   version field plus the app's ``info.title`` — the contract any client
   introspecting the schema endpoint depends on.

Every behaviour below was confirmed empirically over the in-process
``TestClient`` **and** the real-ASGI ``AsyncClient`` transport before the tests
were written.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

from app.main import app
from tests.conftest import GET_PATHS, LOCALHOST_ORIGIN, get_openapi_schema

# The three endpoints FastAPI mounts automatically from the ``FastAPI(...)``
# constructor args (``openapi_url`` defaults to ``/openapi.json``,
# ``docs_url="/docs"``, ``redoc_url="/redoc"``). Centralised here so each suite
# parametrizes over one source of truth.
META_PATHS = ["/openapi.json", "/docs", "/redoc"]

# Non-GET verbs a client might mistakenly send to a read-only meta-endpoint.
# ``HEAD`` is deliberately excluded — it is *accepted* by these routes and is
# pinned separately in ``TestMetaEndpointHeadIsAutoHandled``.
NON_GET_METHODS = ["POST", "PUT", "DELETE", "PATCH"]


class TestMetaEndpointContentType:
    """The served meta-endpoints must declare the Content-Type clients expect.

    ``/openapi.json`` is consumed by schema tooling that dispatches on
    ``application/json``; ``/docs`` and ``/redoc`` are rendered by a browser
    that needs ``text/html``. Only the status code is pinned today, so a
    regression that swapped the responder (or dropped the ``charset``) would be
    invisible.
    """

    def test_openapi_json_content_type_is_application_json(self, client: TestClient) -> None:
        """``GET /openapi.json`` serves ``application/json``."""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")
        assert content_type.startswith("application/json"), (
            f"/openapi.json Content-Type is {content_type!r}, expected application/json"
        )

    @pytest.mark.parametrize("path", ["/docs", "/redoc"])
    def test_docs_ui_content_type_is_html_with_charset(self, client: TestClient, path: str) -> None:
        """``GET /docs`` and ``/redoc`` serve ``text/html; charset=utf-8``.

        The charset matters: browsers fall back to a locale-dependent encoding
        without it, mojibaking any non-ASCII in the rendered schema.
        """
        response = client.get(path)
        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")
        assert content_type.startswith("text/html"), (
            f"{path} Content-Type is {content_type!r}, expected text/html"
        )
        assert "charset=utf-8" in content_type.lower(), (
            f"{path} Content-Type {content_type!r} dropped the utf-8 charset"
        )


class TestMetaEndpointMethodRejection:
    """Non-GET verbs on the read-only meta-endpoints must return 405.

    These surfaces only *read* the schema/UI; a ``POST`` (or ``PUT``/``DELETE``/
    ``PATCH``) has no handler and Starlette answers ``405 Method Not Allowed``.
    The accompanying ``Allow`` header tells a client which methods *are*
    accepted — and (see the HEAD suite) reveals that these routes accept
    ``GET, HEAD``.
    """

    @pytest.mark.parametrize("path", META_PATHS)
    @pytest.mark.parametrize("method", NON_GET_METHODS)
    def test_non_get_method_returns_405(self, client: TestClient, path: str, method: str) -> None:
        """``<method> <meta-path>`` returns 405."""
        response = client.request(method, path)
        assert response.status_code == 405, (
            f"{method} {path} returned {response.status_code}, expected 405"
        )

    @pytest.mark.parametrize("path", META_PATHS)
    def test_405_allow_header_advertises_get_and_head(self, client: TestClient, path: str) -> None:
        """The 405 ``Allow`` header lists exactly ``GET`` and ``HEAD``.

        This is the positive inventory of accepted methods. It also documents
        the contrast with the app's ``@app.get`` routes, whose 405 ``Allow``
        header is ``GET`` only (no ``HEAD``) — pinned in
        ``test_routing_integration_gaps``.
        """
        response = client.post(path)
        assert response.status_code == 405
        allow = response.headers.get("allow", "")
        advertised = {m.strip().upper() for m in allow.split(",") if m.strip()}
        assert advertised == {"GET", "HEAD"}, (
            f"{path} 405 Allow header was {allow!r}, expected exactly GET, HEAD"
        )


class TestMetaEndpointHeadIsAutoHandled:
    """HEAD on a meta-endpoint returns 200 — unlike the app's GET routes.

    FastAPI mounts ``/openapi.json``, ``/docs`` and ``/redoc`` as plain
    Starlette routes whose default method set includes ``HEAD``, so a ``HEAD``
    request succeeds with an empty body. The application's ``@app.get`` routes
    register a method set of exactly ``{"GET"}`` and therefore answer ``HEAD``
    with ``405``. Pinning both halves makes the asymmetry an explicit,
    intentional contract rather than an accident a refactor could erase.
    """

    @pytest.mark.parametrize("path", META_PATHS)
    def test_head_on_meta_endpoint_returns_200(self, client: TestClient, path: str) -> None:
        """``HEAD <meta-path>`` returns 200 (auto-handled by Starlette)."""
        response = client.request("HEAD", path)
        assert response.status_code == 200, (
            f"HEAD {path} returned {response.status_code}, expected 200 "
            f"(meta-endpoints auto-handle HEAD)"
        )

    @pytest.mark.parametrize("path", META_PATHS)
    def test_head_on_meta_endpoint_has_empty_body(self, client: TestClient, path: str) -> None:
        """A ``HEAD`` response carries no body even though ``GET`` would."""
        response = client.request("HEAD", path)
        assert response.content == b"", (
            f"HEAD {path} returned a non-empty body of {len(response.content)} bytes"
        )

    @pytest.mark.parametrize("path", GET_PATHS)
    def test_head_on_app_get_routes_returns_405_contrast(
        self, client: TestClient, path: str
    ) -> None:
        """Contrast pin: ``HEAD`` on an app ``@app.get`` route is 405, not 200.

        Co-located with the meta-endpoint HEAD pins so the divergence is visible
        in one place: if a FastAPI/Starlette upgrade ever made ``@app.get``
        routes auto-handle HEAD, this test fails and the asymmetry assumption is
        re-examined deliberately.
        """
        response = client.request("HEAD", path)
        assert response.status_code == 405, (
            f"HEAD {path} returned {response.status_code}; app GET routes are "
            f"expected to reject HEAD with 405"
        )


class TestServedOpenAPIJsonBodyContract:
    """The bytes served at ``/openapi.json`` must be a usable OpenAPI document.

    Status-200 and CORS are pinned elsewhere; this pins that the *payload*
    parses as JSON and carries the fields a schema consumer reads first — the
    ``openapi`` version (must be ``3.x``) and ``info.title`` (must match the
    title declared on the ``FastAPI`` app). A responder that returned ``200``
    with an empty or malformed body would pass every existing test.
    """

    def test_openapi_json_parses_and_declares_openapi_3x(self, client: TestClient) -> None:
        """The served schema parses as JSON and declares an OpenAPI ``3.x`` version."""
        schema = get_openapi_schema(client)
        version = schema.get("openapi", "")
        assert version.startswith("3."), (
            f"/openapi.json declared OpenAPI version {version!r}, expected a 3.x version"
        )

    def test_openapi_json_info_title_matches_app_title(self, client: TestClient) -> None:
        """The served ``info.title`` matches the title configured on the app.

        Reads ``app.title`` directly rather than hard-coding the string, so the
        pin tracks the constructor argument and a deliberate rename updates in
        one place.
        """
        schema = get_openapi_schema(client)
        assert schema["info"]["title"] == app.title, (
            f"/openapi.json info.title was {schema['info']['title']!r}, expected {app.title!r}"
        )


class TestMetaEndpointAsyncTransportParity:
    """The meta-endpoint contract holds over the real-ASGI async transport too.

    The synchronous ``TestClient`` and the ASGI ``AsyncClient`` exercise
    different request/response framing. A custom response class or middleware
    that behaved differently on the async path (e.g. altering Content-Type or
    method handling) would be caught here.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", META_PATHS)
    async def test_get_meta_endpoint_status_and_type_via_async_client(
        self, async_client: AsyncClient, path: str
    ) -> None:
        """``GET <meta-path>`` over async ASGI returns 200 with the right type."""
        response = await async_client.get(path)
        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")
        expected = "application/json" if path == "/openapi.json" else "text/html"
        assert content_type.startswith(expected), (
            f"async GET {path} Content-Type {content_type!r} did not start with {expected!r}"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", META_PATHS)
    async def test_post_meta_endpoint_returns_405_via_async_client(
        self, async_client: AsyncClient, path: str
    ) -> None:
        """``POST <meta-path>`` over async ASGI returns 405, matching the sync path."""
        response = await async_client.post(path)
        assert response.status_code == 405, (
            f"async POST {path} returned {response.status_code}, expected 405"
        )

    @pytest.mark.asyncio
    async def test_openapi_json_carries_cors_for_allowlisted_origin_via_async_client(
        self, async_client: AsyncClient
    ) -> None:
        """Async ``GET /openapi.json`` from an allow-listed origin echoes ACAO.

        Pins that CORS is applied to the meta-endpoint on the async path the
        browser actually uses — not only the sync ``TestClient`` path.
        """
        response = await async_client.get("/openapi.json", headers={"Origin": LOCALHOST_ORIGIN})
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == LOCALHOST_ORIGIN, (
            "async /openapi.json did not echo the allow-listed Origin in ACAO"
        )
