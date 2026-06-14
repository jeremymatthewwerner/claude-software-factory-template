"""Full-contract pins for the **400 body-decode error** response.

``test_request_body_encoding_edges.py`` (#304) opened this path: when a POST
body cannot be decoded to text at all (illegal / truncated UTF-8), Starlette
short-circuits *while reading the body* — before the route handler runs — with
a ``400`` whose ``detail`` is the bare string
``"There was an error parsing the body"``. That commit pinned exactly two
things: the **status** (400) and that ``detail`` is a **string** (not the 422
list shape).

The rest of the 400 decode-error response contract is unpinned, and it is a
*structurally distinct* code path from the 404/405/422 responses whose CORS and
hygiene contracts are already pinned (those flow through FastAPI/Starlette's
exception handlers; this one is raised by the body-reading middleware before
the router dispatches). The gaps pinned here:

* **Content-Type is ``application/json``** — a client introspecting
  ``error.detail`` needs JSON, not ``text/plain``. A regression to a plain-text
  error envelope would still satisfy #304's "detail is a string" pin (because
  ``response.json()`` would fail differently) yet break every JSON consumer.

* **CORS headers survive on the 400 from an allow-listed origin.**
  ``TestCORSOnErrorResponses`` (test_integration_gaps.py) pins that 404 / 405 /
  422 from an allow-listed origin echo ``Access-Control-Allow-Origin`` and
  ``Vary: Origin``. The 400 decode path is raised *earlier* in the stack, so a
  regression (e.g. a body-size guard middleware mounted *outside*
  ``CORSMiddleware``) could drop CORS headers on the 400 while leaving the
  exception-handler paths intact. When that happens the browser hides the real
  400 from the frontend JS and surfaces a misleading "CORS error" instead —
  exactly the failure mode CORS-on-error pins exist to prevent. Pinned for the
  400 here.

* **No ``Access-Control-Allow-Origin`` from a disallowed / absent origin** on
  the 400 — the negative half of the CORS contract on this path.

* **``Content-Length`` matches the body byte length** — error-path symmetry
  with ``TestErrorResponseContentLengthMatchesBody`` (which enumerates 422 /
  404 / 405 but not this 400).

* **Exact ``detail`` string** — #304 pinned only the *type*; SDKs that branch on
  the human-readable message need the *value* pinned too.

* **Forbidden hygiene headers absent** — the same four-header hygiene contract
  the 200 and 404/405/422 paths already honour.

All facets are pinned over both the in-process ``TestClient`` and the real-ASGI
``AsyncClient`` transport, since body-decode framing differs between them.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient, Response

from .conftest import DISALLOWED_ORIGIN, LOCALHOST_ORIGIN

# A POST body that is illegal UTF-8 *inside* an otherwise well-formed JSON
# skeleton, so the failure is purely at the byte-decode step (the 400 path),
# not the JSON-grammar step (the 422 path). 0xE9 is Latin-1 'é' sent without
# UTF-8 transcoding — a real way a misconfigured client mangles its payload.
UNDECODABLE_BODY = b'{"name":"\xe9"}'
JSON_CT = {"Content-Type": "application/json"}

# The exact human-readable message Starlette emits for a body it cannot decode.
# #304 pinned only that this is a *string*; SDK error renderers that match on the
# message text depend on the *value*, so pin it here.
EXPECTED_DETAIL = "There was an error parsing the body"

# The four-header hygiene contract honoured everywhere else in the suite. A
# body-decode 400 is emitted from a distinct code path, so re-pin it here.
FORBIDDEN_RESPONSE_HEADERS: list[str] = [
    "set-cookie",
    "x-powered-by",
    "strict-transport-security",
    "x-frame-options",
    "server",
]


def _post_undecodable(client: TestClient, origin: str | None = None) -> Response:
    """POST the undecodable body, optionally from ``origin``; return the response."""
    headers = dict(JSON_CT)
    if origin is not None:
        headers["Origin"] = origin
    return client.post("/api/hello", content=UNDECODABLE_BODY, headers=headers)


class TestBodyDecodeErrorBaseContract:
    """The 400 decode-error response is JSON with the exact documented detail.

    Pins the two facets #304 left open on the success-shape side: the
    Content-Type (must be ``application/json``) and the exact ``detail`` string
    (only its *type* was pinned before).
    """

    def test_decode_error_content_type_is_json(self, client: TestClient) -> None:
        """The 400 body-decode error declares ``Content-Type: application/json``."""
        response = _post_undecodable(client)
        assert response.status_code == 400
        content_type = response.headers.get("content-type", "")
        assert content_type.startswith("application/json"), (
            f"400 body-decode error Content-Type is {content_type!r}, expected "
            f"application/json — a regression to a text/plain error envelope would "
            f"break every client that parses error.detail as JSON."
        )

    def test_decode_error_detail_is_exact_documented_string(self, client: TestClient) -> None:
        """The 400 body matches ``{'detail': 'There was an error parsing the body'}``."""
        response = _post_undecodable(client)
        assert response.status_code == 400
        assert response.json() == {"detail": EXPECTED_DETAIL}, (
            f"400 body-decode error body regressed: got {response.json()!r}, expected "
            f"{{'detail': {EXPECTED_DETAIL!r}}}. SDK error renderers match on this string."
        )

    def test_decode_error_content_length_matches_body(self, client: TestClient) -> None:
        """``Content-Length`` on the 400 equals the body byte length.

        ``TestErrorResponseContentLengthMatchesBody`` pins this for 422 / 404 /
        405 but not the 400 decode path. A custom error envelope that mis-set the
        header would block HTTP/1.1 clients that count bytes on a kept-alive
        connection.
        """
        response = _post_undecodable(client)
        assert response.status_code == 400
        declared = response.headers.get("content-length")
        assert declared is not None, (
            "400 body-decode error did not emit a Content-Length header — strict "
            "HTTP/1.1 clients that count bytes will block waiting for EOF."
        )
        assert int(declared) == len(response.content), (
            f"400 Content-Length={declared} but body is {len(response.content)} bytes "
            f"— header/body length mismatch on the body-decode error path."
        )

    @pytest.mark.parametrize("forbidden_header", FORBIDDEN_RESPONSE_HEADERS)
    def test_decode_error_omits_forbidden_header(
        self, client: TestClient, forbidden_header: str
    ) -> None:
        """The named hygiene-forbidden header is absent on the 400 decode error.

        The decode-error response comes from the body-reading layer, not a route
        handler — a future error-formatting middleware that injected
        ``Set-Cookie: trace_id=...`` "for debugging" would be invisible to every
        200/404/405/422-only hygiene pin.
        """
        response = _post_undecodable(client)
        assert response.status_code == 400
        lower_headers = {k.lower() for k in response.headers}
        assert forbidden_header not in lower_headers, (
            f"400 body-decode error unexpectedly emitted {forbidden_header!r} "
            f"(value {response.headers.get(forbidden_header)!r}) — hygiene contract "
            f"must hold on the body-decode path too."
        )


class TestBodyDecodeErrorCarriesCORSFromAllowlistedOrigin:
    """The 400 decode error from an allow-listed origin keeps its CORS headers.

    This is the headline gap: ``TestCORSOnErrorResponses`` (test_integration_gaps)
    pins ``Access-Control-Allow-Origin`` + ``Vary: Origin`` on 404 / 405 / 422,
    all of which are produced by FastAPI/Starlette exception handlers *inside*
    the CORS middleware. The 400 body-decode error is raised one layer up (while
    reading the request stream). If CORS headers were dropped there, a browser
    POST from the dev frontend that sent mangled bytes would have its 400 hidden
    by the browser and reported to the JS as an opaque CORS failure — masking the
    real error. Pin that the 400 carries the full CORS header set.
    """

    def test_decode_error_echoes_allowlisted_origin(self, client: TestClient) -> None:
        """The 400 from ``http://localhost:3000`` echoes that origin in ACAO."""
        response = _post_undecodable(client, origin=LOCALHOST_ORIGIN)
        assert response.status_code == 400
        assert response.headers.get("access-control-allow-origin") == LOCALHOST_ORIGIN, (
            f"400 body-decode error from an allow-listed origin did not echo "
            f"Access-Control-Allow-Origin (got "
            f"{response.headers.get('access-control-allow-origin')!r}) — the browser "
            f"would hide this 400 from the frontend JS as a CORS error."
        )

    def test_decode_error_carries_vary_origin(self, client: TestClient) -> None:
        """The 400 from an allow-listed origin carries ``Vary: Origin``.

        A shared cache keyed without ``Vary: Origin`` could serve a
        cross-origin client a cached error body whose ``Access-Control-Allow-Origin``
        names a *different* origin, which the browser would then reject.
        """
        response = _post_undecodable(client, origin=LOCALHOST_ORIGIN)
        assert response.status_code == 400
        assert response.headers.get("vary") == "Origin", (
            f"400 body-decode error from an allow-listed origin is missing "
            f"Vary: Origin (got {response.headers.get('vary')!r})."
        )

    def test_decode_error_carries_allow_credentials(self, client: TestClient) -> None:
        """The 400 from an allow-listed origin carries ``Allow-Credentials: true``.

        The app is configured with ``allow_credentials=True``; a credentialed
        ``fetch`` (cookies / auth) needs this header even on the error response,
        or the browser rejects the response before the JS can read the 400.
        """
        response = _post_undecodable(client, origin=LOCALHOST_ORIGIN)
        assert response.status_code == 400
        assert response.headers.get("access-control-allow-credentials") == "true", (
            f"400 body-decode error from an allow-listed origin is missing "
            f"Access-Control-Allow-Credentials: true (got "
            f"{response.headers.get('access-control-allow-credentials')!r})."
        )


class TestBodyDecodeErrorOmitsCORSFromNonAllowlistedOrigin:
    """The negative half: no ACAO on the 400 from a disallowed / absent origin.

    Symmetry with the positive pin above and with every other CORS-on-error
    pin: an origin not on the allow-list (or no ``Origin`` header at all) must
    not receive an ``Access-Control-Allow-Origin`` header, even on the
    body-decode error path. A regression that reflected *any* origin here would
    hand sandboxed / cross-site pages CORS access to the error surface.
    """

    def test_decode_error_from_disallowed_origin_has_no_acao(self, client: TestClient) -> None:
        """The 400 from ``https://evil.example.com`` carries no ACAO header."""
        response = _post_undecodable(client, origin=DISALLOWED_ORIGIN)
        assert response.status_code == 400
        assert response.headers.get("access-control-allow-origin") is None, (
            f"400 body-decode error from a disallowed origin leaked "
            f"Access-Control-Allow-Origin="
            f"{response.headers.get('access-control-allow-origin')!r}."
        )

    def test_decode_error_with_no_origin_has_no_acao(self, client: TestClient) -> None:
        """The 400 with no ``Origin`` header carries no ACAO header."""
        response = _post_undecodable(client, origin=None)
        assert response.status_code == 400
        assert response.headers.get("access-control-allow-origin") is None, (
            f"400 body-decode error with no Origin leaked "
            f"Access-Control-Allow-Origin="
            f"{response.headers.get('access-control-allow-origin')!r}."
        )


class TestBodyDecodeErrorOverAsyncTransport:
    """The 400 decode-error contract holds over the real-ASGI ``AsyncClient`` too.

    ``TestClient`` is synchronous (built on a portal); ``AsyncClient`` +
    ``ASGITransport`` drives the genuine async request pipeline, where the
    body-read-and-decode step that produces this 400 lives. A regression that
    only manifested under real ASGI body handling (the production transport)
    would leave the sync pins green — so re-pin the load-bearing facets here.
    """

    @pytest.mark.asyncio
    async def test_async_decode_error_status_content_type_and_detail(
        self, async_client: AsyncClient
    ) -> None:
        """Over async ASGI: 400, JSON content-type, exact detail string."""
        response = await async_client.post("/api/hello", content=UNDECODABLE_BODY, headers=JSON_CT)
        assert response.status_code == 400
        assert response.headers.get("content-type", "").startswith("application/json")
        assert response.json() == {"detail": EXPECTED_DETAIL}

    @pytest.mark.asyncio
    async def test_async_decode_error_carries_cors_from_allowlisted_origin(
        self, async_client: AsyncClient
    ) -> None:
        """Over async ASGI: the 400 from an allow-listed origin keeps CORS headers."""
        response = await async_client.post(
            "/api/hello",
            content=UNDECODABLE_BODY,
            headers={**JSON_CT, "Origin": LOCALHOST_ORIGIN},
        )
        assert response.status_code == 400
        assert response.headers.get("access-control-allow-origin") == LOCALHOST_ORIGIN
        assert response.headers.get("vary") == "Origin"
        assert response.headers.get("access-control-allow-credentials") == "true"
