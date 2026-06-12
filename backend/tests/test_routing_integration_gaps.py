"""
Routing-integration gap tests (Wednesday QA focus).

Line/branch coverage for ``app/main.py`` is already at 100% and ``grep`` across
the suite shows two real router/ASGI integrations that nothing pins:

1. **Trailing-slash redirects.** FastAPI's router runs with
   ``redirect_slashes=True``, so ``GET /health/`` short-circuits to a ``307``
   pointing at the canonical ``/health``. The existing tests only ever hit the
   canonical (slash-free) paths, so a regression that flipped
   ``redirect_slashes`` to ``False`` — turning every trailing-slash request into
   a ``404`` — would slip through unnoticed. The redirect is also where method
   and body preservation (``307`` vs ``308``/``302``) and CORS-on-redirect
   matter for a browser.

2. **HEAD is not auto-handled.** ``@app.get(...)`` registers a FastAPI
   ``APIRoute`` whose method set is exactly ``{"GET"}``. Unlike bare Starlette
   ``Route`` objects, FastAPI does **not** auto-append ``HEAD``, so ``HEAD
   /health`` returns ``405`` with ``Allow: GET`` and an empty body. This is
   surprising (many assume HEAD piggybacks on GET) and entirely unpinned — a
   future change that either added HEAD support or broke the ``405`` framing
   would go uncaught.

Both behaviours were confirmed empirically over the in-process ``TestClient``
**and** the real-ASGI ``AsyncClient`` transport before these tests were written.
``404`` paths (no canonical target to redirect to, no route to reject a method
on) are pinned alongside the happy paths so the negative inventory is explicit.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

from app.main import app
from tests.conftest import (
    DISALLOWED_ORIGIN,
    GET_PATHS,
    LOCALHOST_ORIGIN,
    expected_greeting,
)

# ``DISALLOWED_ORIGIN`` (imported) is an origin *not* on the CORS allow-list,
# used to assert that redirect / 405 responses to a foreign origin do not leak
# an Allow-Origin header. ``GET_PATHS`` (imported) are the canonical
# (slash-free) GET paths the app serves; each has a trailing-slash sibling that
# the router answers with a 307 to the canonical form.


class TestTrailingSlashRedirectIntegration:
    """A trailing slash on a real route must 307-redirect to the canonical path.

    The router's ``redirect_slashes=True`` (FastAPI's default) means
    ``/health/`` is not a 404 — Starlette's router detects that the slash-free
    variant exists and emits a ``307 Temporary Redirect`` whose ``Location`` is
    the canonical path. ``307`` (not ``302``/``308``) is the contract that
    preserves the request method and body, which is what lets a browser replay
    a ``POST`` against the canonical URL. No existing test touches a
    trailing-slash URL, so a regression that disabled ``redirect_slashes`` (a
    one-line change that turns every such request into a 404) would be silent.
    """

    @pytest.mark.parametrize("path", GET_PATHS)
    def test_trailing_slash_get_redirects_307_to_canonical(
        self, client: TestClient, path: str
    ) -> None:
        """``GET <path>/`` returns 307 with ``Location`` set to ``<path>``."""
        response = client.get(f"{path}/", follow_redirects=False)
        assert response.status_code == 307, (
            f"GET {path}/ should 307-redirect to the canonical path; got "
            f"{response.status_code} (redirect_slashes regression?)"
        )
        # Location may be absolute (scheme+host) — assert it ends at the
        # canonical, slash-free path rather than hard-coding the test host.
        location = response.headers.get("location", "")
        assert location.endswith(path), (
            f"GET {path}/ redirect Location {location!r} must point at the canonical path {path!r}"
        )

    def test_post_trailing_slash_redirects_307_preserving_method(self, client: TestClient) -> None:
        """``POST /api/hello/`` uses 307 (not 308/302) so the method is preserved."""
        response = client.post("/api/hello/", json={"name": "Ada"}, follow_redirects=False)
        assert response.status_code == 307, (
            f"POST /api/hello/ must 307 (method-preserving) redirect; got {response.status_code}"
        )
        assert response.headers.get("location", "").endswith("/api/hello")

    def test_post_trailing_slash_followed_reaches_handler_with_body(
        self, client: TestClient
    ) -> None:
        """Following the 307 replays the POST body and yields the real greeting.

        This is the end-to-end pin: the redirect is only useful if the client,
        on following it, lands on the POST handler *with the original JSON body
        intact*. A 302 here would downgrade the replay to a GET and lose the
        body, producing a 405 instead of the greeting.
        """
        response = client.post("/api/hello/", json={"name": "Ada"}, follow_redirects=True)
        assert response.status_code == 200
        assert response.json()["message"] == expected_greeting("Ada")

    def test_trailing_slash_redirect_carries_cors_for_allowlisted_origin(
        self, client: TestClient
    ) -> None:
        """The 307 itself must carry CORS headers for an allow-listed origin.

        The browser sees the redirect *response* before it follows it. If the
        redirect lacks ``Access-Control-Allow-Origin``, a CORS fetch fails at
        the redirect step and never reaches the canonical URL.
        """
        response = client.get(
            "/health/", headers={"Origin": LOCALHOST_ORIGIN}, follow_redirects=False
        )
        assert response.status_code == 307
        assert response.headers.get("access-control-allow-origin") == LOCALHOST_ORIGIN
        assert response.headers.get("vary") == "Origin"

    def test_trailing_slash_redirect_omits_cors_for_disallowed_origin(
        self, client: TestClient
    ) -> None:
        """A 307 to a disallowed origin must not leak an Allow-Origin header."""
        response = client.get(
            "/health/", headers={"Origin": DISALLOWED_ORIGIN}, follow_redirects=False
        )
        assert response.status_code == 307
        assert response.headers.get("access-control-allow-origin") is None

    def test_trailing_slash_redirect_body_is_empty(self, client: TestClient) -> None:
        """The 307 redirect response carries no body (it is a pure redirect)."""
        response = client.get("/health/", follow_redirects=False)
        assert response.status_code == 307
        assert response.content == b""

    def test_nonexistent_path_with_trailing_slash_is_404_not_redirect(
        self, client: TestClient
    ) -> None:
        """A trailing slash on a path with no canonical sibling is a 404, not a 307.

        ``redirect_slashes`` only fires when the slash-free variant is a real
        route. ``/api/missing`` is not, so ``/api/missing/`` must 404 — pinning
        that the redirect logic does not fabricate targets for unknown paths.
        """
        response = client.get("/api/missing/", follow_redirects=False)
        assert response.status_code == 404

    def test_router_redirect_slashes_is_enabled(self) -> None:
        """Pin the router flag that the redirect behaviour above depends on.

        A direct instance assertion documents *why* the HTTP-level redirects
        happen and fails fast (with a clear message) if someone sets
        ``redirect_slashes=False`` without realising it changes the contract.
        """
        assert app.router.redirect_slashes is True


class TestHeadMethodReturns405:
    """``HEAD`` on a GET route returns 405 — FastAPI does not auto-add HEAD.

    A FastAPI ``APIRoute`` created by ``@app.get`` has ``methods == {"GET"}``;
    FastAPI (unlike a raw Starlette ``Route``) never appends ``HEAD``. So a
    ``HEAD /health`` is a disallowed method → ``405 Method Not Allowed`` with an
    ``Allow: GET`` header and an empty body. ``grep`` shows nothing pins this
    surprising behaviour. Pinning it both documents the gotcha and guards
    against an accidental future change in either direction (silently adding
    HEAD, or breaking the 405 contract).
    """

    @pytest.mark.parametrize("path", GET_PATHS)
    def test_head_on_get_route_returns_405(self, client: TestClient, path: str) -> None:
        """``HEAD <path>`` returns 405 because HEAD is not a registered method."""
        response = client.head(path)
        assert response.status_code == 405, (
            f"HEAD {path} should be 405 (FastAPI does not auto-handle HEAD); got "
            f"{response.status_code}"
        )

    def test_head_405_advertises_get_in_allow_header(self, client: TestClient) -> None:
        """The 405 must advertise the methods that *are* allowed (``GET``)."""
        response = client.head("/health")
        assert response.status_code == 405
        allow = response.headers.get("allow", "")
        assert "GET" in allow, f"HEAD /health 405 should advertise Allow: GET; got Allow: {allow!r}"

    def test_head_405_body_is_empty(self, client: TestClient) -> None:
        """A HEAD response must never carry a body, even on the 405 path."""
        response = client.head("/health")
        assert response.content == b""

    def test_head_405_from_allowlisted_origin_carries_acao(self, client: TestClient) -> None:
        """The 405 must still carry CORS headers for an allow-listed origin.

        So the browser can read the 405 status off a ``fetch(..., {method:
        'HEAD'})`` rather than seeing an opaque network error.
        """
        response = client.head("/health", headers={"Origin": LOCALHOST_ORIGIN})
        assert response.status_code == 405
        assert response.headers.get("access-control-allow-origin") == LOCALHOST_ORIGIN

    def test_head_on_nonexistent_path_returns_404_not_405(self, client: TestClient) -> None:
        """HEAD to an unknown path is a 404 (no route), distinct from the 405 case."""
        response = client.head("/api/missing")
        assert response.status_code == 404


class TestRoutingGapsAsyncTransportParity:
    """The redirect / HEAD behaviour holds over the real ASGI transport too.

    The in-process ``TestClient`` and the ``httpx.AsyncClient`` + ``ASGITransport``
    pair drive different request/response framing code paths. Repeating the two
    headline pins over the async transport guards against a regression that only
    manifests under uvicorn (the production transport), where the in-process
    client would stay green.
    """

    @pytest.mark.asyncio
    async def test_trailing_slash_redirect_307_via_async_client(
        self, async_client: AsyncClient
    ) -> None:
        """``GET /health/`` is a 307 to the canonical path over real ASGI."""
        response = await async_client.get("/health/", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers.get("location", "").endswith("/health")

    @pytest.mark.asyncio
    async def test_head_returns_405_via_async_client(self, async_client: AsyncClient) -> None:
        """``HEAD /health`` is a 405 over the real ASGI transport."""
        response = await async_client.head("/health")
        assert response.status_code == 405
