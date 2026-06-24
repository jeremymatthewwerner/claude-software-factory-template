"""Integration-gap pins for the ``Allow`` header on 405 responses.

RFC 7231 §6.5.5 requires a ``405 Method Not Allowed`` response to carry an
``Allow`` header enumerating the methods the target resource *does* support, so
a client can recover by re-issuing the request with a permitted verb. The app
relies entirely on Starlette's router to synthesise this header — nothing in the
app code constructs it — which makes its exact contents an emergent property of
how FastAPI registers routes.

Existing coverage (verified by ``grep`` before adding) only pins the **HEAD**
case (``HEAD /health`` → ``Allow: GET`` in ``test_routing_integration_gaps.py``).
The ordinary disallowed verbs (``DELETE``/``PUT``/``PATCH``) and the bare
``OPTIONS`` 405, the GET-only *meta* routes (``/openapi.json``/``/docs``/
``/redoc``), and — most importantly — the **multi-method** ``/api/hello`` path
are all unpinned.

The headline gotcha pinned here: ``/api/hello`` registers *both* a GET and a POST
handler, yet a ``DELETE /api/hello`` 405 advertises ``Allow: GET`` **only**, not
``GET, POST``. FastAPI creates a separate ``APIRoute`` object per decorator, and
Starlette returns the first path-matching route's methods on a partial (method)
mismatch rather than aggregating across sibling routes. A future Starlette
release that started aggregating — or that dropped the ``Allow`` header — would
silently change the HTTP contract; these tests catch it in either direction.
"""

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

from app.main import app

from .conftest import GET_PATHS, LOCALHOST_ORIGIN

# Methods that are not registered on any app route and therefore always trigger a
# 405 on an existing path. HEAD is deliberately excluded — it is already pinned
# by ``test_routing_integration_gaps.py`` and carries an empty body (no header
# parity to assert beyond what that suite covers). OPTIONS is excluded here
# because, with an ``Origin``/preflight, it is intercepted by the CORS middleware;
# the bare-OPTIONS 405 is pinned separately below.
DISALLOWED_VERBS = ["DELETE", "PUT", "PATCH"]

# The tokens a well-formed ``Allow`` header may contain: uppercase HTTP method
# names. Used to assert the header is not just present but syntactically valid.
VALID_METHOD_TOKENS = {
    "GET",
    "HEAD",
    "POST",
    "PUT",
    "DELETE",
    "PATCH",
    "OPTIONS",
    "TRACE",
    "CONNECT",
}


def _allow_tokens(allow_header: str) -> set[str]:
    """Split a comma-separated ``Allow`` header into a set of method tokens.

    RFC 7231 §7.4.1 defines ``Allow`` as a comma-separated list; tokens may carry
    optional surrounding whitespace (``"GET, POST"``). Normalising to a set lets
    assertions ignore both ordering and incidental spacing.
    """
    return {token.strip() for token in allow_header.split(",") if token.strip()}


class TestAllowHeaderPresentOnEvery405:
    """Every 405 from a real route must carry a non-empty, valid ``Allow`` header.

    This is the core RFC 7231 §6.5.5 contract: the response that says "you used
    the wrong method" is obligated to tell the client which methods are right.
    """

    @pytest.mark.parametrize("path", GET_PATHS)
    @pytest.mark.parametrize("method", DISALLOWED_VERBS)
    def test_405_carries_allow_header(self, client: TestClient, path: str, method: str) -> None:
        """``<METHOD> <path>`` is a 405 that includes an ``Allow`` header."""
        response = client.request(method, path)
        assert response.status_code == 405, (
            f"{method} {path} should be 405 (verb not registered); got {response.status_code}"
        )
        assert "allow" in response.headers, (
            f"{method} {path} 405 is missing the RFC 7231-required Allow header"
        )

    @pytest.mark.parametrize("path", GET_PATHS)
    @pytest.mark.parametrize("method", DISALLOWED_VERBS)
    def test_405_allow_header_is_non_empty(
        self, client: TestClient, path: str, method: str
    ) -> None:
        """The ``Allow`` header lists at least one method — an empty list is useless."""
        allow = client.request(method, path).headers.get("allow", "")
        assert _allow_tokens(allow), f"{method} {path} 405 has an empty Allow header ({allow!r})"

    @pytest.mark.parametrize("path", GET_PATHS)
    @pytest.mark.parametrize("method", DISALLOWED_VERBS)
    def test_405_allow_header_contains_only_valid_method_tokens(
        self, client: TestClient, path: str, method: str
    ) -> None:
        """Every token in ``Allow`` is a recognised uppercase HTTP method name."""
        tokens = _allow_tokens(client.request(method, path).headers.get("allow", ""))
        unknown = tokens - VALID_METHOD_TOKENS
        assert not unknown, f"{method} {path} 405 Allow header has invalid tokens: {unknown}"


class TestAllowHeaderAdvertisesGet:
    """All app routes are GET-registered, so their 405 ``Allow`` must include GET.

    ``/health``, ``/api/version`` and ``/api/hello`` each have a GET handler. A
    client that receives a 405 and reads ``Allow: GET`` can recover by switching
    to GET — pinning this keeps that recovery path honest.
    """

    @pytest.mark.parametrize("path", GET_PATHS)
    @pytest.mark.parametrize("method", DISALLOWED_VERBS)
    def test_405_advertises_get(self, client: TestClient, path: str, method: str) -> None:
        """``Allow`` for a GET-registered path includes ``GET``."""
        allow = client.request(method, path).headers.get("allow", "")
        assert "GET" in _allow_tokens(allow), (
            f"{method} {path} 405 should advertise GET; got Allow: {allow!r}"
        )


class TestApiHelloAllowHeaderDoesNotAggregate:
    """``/api/hello`` 405 advertises ``GET`` only — *not* ``GET, POST``.

    The path carries both a GET and a POST handler, so a naive reading of RFC
    7231 would expect ``Allow: GET, POST``. FastAPI instead registers each verb
    as its own ``APIRoute``; Starlette reports the first path-matching route's
    methods on a method mismatch without merging siblings. This pins that
    real-world behaviour so an upgrade that changes the aggregation (in either
    direction) is caught rather than silently shipped.
    """

    def test_delete_api_hello_allow_is_get_only(self, client: TestClient) -> None:
        """A disallowed verb on the dual-method path advertises exactly ``{GET}``."""
        allow = client.delete("/api/hello").headers.get("allow", "")
        assert _allow_tokens(allow) == {"GET"}, (
            "DELETE /api/hello 405 should advertise exactly {GET} (FastAPI does not "
            f"aggregate sibling routes); got Allow: {allow!r}"
        )

    @pytest.mark.parametrize("method", DISALLOWED_VERBS)
    def test_disallowed_verbs_on_api_hello_omit_post(self, client: TestClient, method: str) -> None:
        """POST is *not* advertised even though ``/api/hello`` accepts POST."""
        allow = client.request(method, "/api/hello").headers.get("allow", "")
        assert "POST" not in _allow_tokens(allow), (
            f"{method} /api/hello 405 unexpectedly advertised POST in Allow: {allow!r} — "
            "sibling-route aggregation behaviour changed"
        )


class TestBareOptionsAllowHeader:
    """A bare ``OPTIONS`` (no CORS preflight headers) hits the router → 405.

    Without an ``Origin`` + ``Access-Control-Request-Method`` pair the CORS
    middleware does not synthesise a 200 preflight, so the request falls through
    to the router, which has no OPTIONS handler and returns 405 with an ``Allow``
    header — the same contract as any other disallowed verb.
    """

    @pytest.mark.parametrize("path", GET_PATHS)
    def test_bare_options_405_advertises_get(self, client: TestClient, path: str) -> None:
        """Bare ``OPTIONS <path>`` is a 405 whose ``Allow`` includes ``GET``."""
        response = client.options(path)
        assert response.status_code == 405, (
            f"Bare OPTIONS {path} should be 405 (no preflight synthesised); got "
            f"{response.status_code}"
        )
        assert "GET" in _allow_tokens(response.headers.get("allow", "")), (
            f"Bare OPTIONS {path} 405 should advertise GET in Allow header"
        )


class TestMetaRouteAllowHeader:
    """The framework GET-only routes also honour the 405 ``Allow`` contract.

    ``/openapi.json``, ``/docs`` and ``/redoc`` are GET-only routes FastAPI
    registers automatically. Existing tests pin that non-GET verbs return 405
    there (``test_edge_cases.py``) but never assert the ``Allow`` header — pinning
    it confirms the recovery hint is present on the schema/UI surfaces too.
    """

    @pytest.mark.parametrize("path", ["/openapi.json", "/docs", "/redoc"])
    @pytest.mark.parametrize("method", DISALLOWED_VERBS)
    def test_meta_route_405_advertises_get(
        self, client: TestClient, path: str, method: str
    ) -> None:
        """``<METHOD> <meta-path>`` is a 405 advertising ``Allow: GET``."""
        response = client.request(method, path)
        assert response.status_code == 405, (
            f"{method} {path} should be 405 (meta routes are GET-only); got {response.status_code}"
        )
        assert "GET" in _allow_tokens(response.headers.get("allow", "")), (
            f"{method} {path} 405 should advertise GET; got Allow: "
            f"{response.headers.get('allow')!r}"
        )


class TestAllowHeaderDeterminism:
    """The ``Allow`` header value is stable across repeated identical requests.

    Route registration is fixed at import time, so the synthesised ``Allow`` must
    never vary call-to-call. A non-deterministic value would point to mutable
    routing state leaking between requests — exactly the kind of flakiness a
    50-call hash check surfaces deterministically.
    """

    def test_allow_header_is_byte_identical_across_50_calls(self, client: TestClient) -> None:
        """50 ``DELETE /api/hello`` responses return one distinct ``Allow`` value."""
        values = {client.delete("/api/hello").headers.get("allow") for _ in range(50)}
        assert len(values) == 1, f"/api/hello 405 Allow header varied across 50 calls: {values}"


class TestAllowHeaderCorsParityOnError:
    """A 405 from an allow-listed origin carries *both* ``Allow`` and CORS headers.

    The router supplies ``Allow`` and the CORS middleware (on the response's way
    out) supplies ``Access-Control-Allow-Origin``. A regression that let one
    layer clobber the other would leave a browser ``fetch`` unable to read the
    405 status *or* unable to learn the permitted methods. Pinning both on a
    single response guards the interaction between the two layers.
    """

    def test_405_from_allowlisted_origin_has_allow_and_acao(self, client: TestClient) -> None:
        """``DELETE /health`` from localhost:3000 carries Allow *and* ACAO."""
        response = client.delete("/health", headers={"Origin": LOCALHOST_ORIGIN})
        assert response.status_code == 405
        assert "GET" in _allow_tokens(response.headers.get("allow", "")), (
            "405 lost its Allow header when CORS headers were attached"
        )
        assert response.headers.get("access-control-allow-origin") == LOCALHOST_ORIGIN, (
            "405 lost its CORS Allow-Origin header"
        )


class TestAllowHeaderAsyncTransportParity:
    """The 405 ``Allow`` contract holds over the real ASGI transport too.

    The in-process ``TestClient`` and the ``httpx.AsyncClient`` + ``ASGITransport``
    pair drive different framing code paths. Repeating the headline pin over the
    async transport guards against a regression that only manifests under uvicorn
    (the production transport).
    """

    @pytest.mark.asyncio
    async def test_delete_api_hello_allow_is_get_only_via_async_client(
        self, async_client: AsyncClient
    ) -> None:
        """``DELETE /api/hello`` over real ASGI is a 405 advertising exactly ``{GET}``."""
        response = await async_client.delete("/api/hello")
        assert response.status_code == 405
        assert _allow_tokens(response.headers.get("allow", "")) == {"GET"}, (
            "async-transport DELETE /api/hello 405 Allow diverged from {GET}"
        )


def test_no_app_route_registers_a_405_disallowed_verb() -> None:
    """Guard: the verbs this suite treats as 'disallowed' really are unregistered.

    If a future route added (say) a DELETE handler on a GET path, the parametrized
    405 assertions above would silently start exercising a 2xx/4xx-from-handler
    path instead of the router's 405. This structural check fails loudly at the
    source so the suite's premise can never quietly rot.
    """
    registered: set[str] = set()
    for route in app.routes:
        registered |= getattr(route, "methods", set()) or set()
    overlap = registered & set(DISALLOWED_VERBS)
    assert not overlap, (
        f"DISALLOWED_VERBS {overlap} are actually registered on a route — the 405 "
        "premise of this suite no longer holds; update DISALLOWED_VERBS"
    )
