"""Integration-gap pins for HTTP conditional-request & content-negotiation neutrality.

The app registers **no** caching or compression middleware. Real clients
(browsers, CDNs, generated SDKs) nonetheless attach conditional-request and
content-negotiation headers to routine GETs — ``If-None-Match``,
``If-Modified-Since`` and ``Accept-Encoding``. This suite pins that those
request headers are *inert*: the server never short-circuits to a
``304 Not Modified`` and never compresses the body, so every request still
yields a fresh, full, uncompressed ``200`` carrying the per-request timestamp.

**Why this is a gap, not a duplicate.** ``test_regression_prevention.py``
already pins the *absence* of ``Cache-Control`` / ``ETag`` / ``Expires``
*response* headers. That is the emission side. What was never pinned is the
request-side *behavior* those absent headers imply:

* A conditional GET must return ``200`` with a body, never ``304`` — otherwise a
  caching layer that started honouring ``If-None-Match`` would starve clients of
  the fresh ``timestamp`` these dynamic endpoints exist to serve.
* An ``Accept-Encoding: gzip`` request must come back uncompressed with **no**
  ``Content-Encoding`` header and **no** ``Accept-Encoding`` token in ``Vary``.
  A ``GZipMiddleware`` regression would trip this — and would slip past every
  existing ETag/Cache-Control assertion, because GZip emits *neither* of those.

Both the sync ``TestClient`` and the real-ASGI ``AsyncClient`` transports are
exercised so a divergence in either request path is caught.
"""

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient, Response

from tests.conftest import (
    GET_PATHS,
    JSON_HEADERS,
    assert_utc_iso8601,
    expected_greeting,
    strict_json_loads,
)

# An unconditionally future HTTP-date. If the app ever grew ``Last-Modified``
# support, an ``If-Modified-Since`` at or after the resource's mtime would elicit
# a ``304``; a date this far in the future makes such a regression unambiguous.
FUTURE_HTTP_DATE = "Wed, 21 Oct 2099 07:28:00 GMT"

# A syntactically valid strong ETag value a conditional client might send. The
# app mints no ETags, so this can only ever "match" if some cache layer invented
# one — exactly the regression these tests guard against.
ARBITRARY_ETAG = '"deadbeef-cafe"'


def _vary_tokens(response: Response) -> set[str]:
    """Return the lowercased token set of a response's ``Vary`` header.

    ``Vary`` is a comma-separated list (RFC 7231 §7.1.4). CORS legitimately adds
    ``Vary: Origin`` on origin-bearing requests, so membership — not equality —
    is the right check when asserting ``Accept-Encoding`` is *absent*.
    """
    raw = response.headers.get("vary", "")
    return {token.strip().lower() for token in raw.split(",") if token.strip()}


class TestConditionalRequestNeverReturns304:
    """A conditional GET on any read route returns ``200`` — never ``304``.

    These endpoints carry no validators (``ETag``/``Last-Modified``), so a
    conditional request has nothing to match against and must serve the resource
    in full. A ``304`` here would mean a cache layer crept in and began answering
    conditionally — silently withholding the fresh timestamp the endpoints exist
    to emit.
    """

    @pytest.mark.parametrize("path", GET_PATHS)
    def test_if_none_match_wildcard_returns_200(self, client: TestClient, path: str) -> None:
        """``If-None-Match: *`` (matches any existing representation) still yields 200."""
        response = client.get(path, headers={"If-None-Match": "*"})
        assert response.status_code == 200, (
            f"GET {path} with If-None-Match:* returned {response.status_code}; a "
            "conditional request must serve a full 200, never a 304"
        )

    @pytest.mark.parametrize("path", GET_PATHS)
    def test_if_none_match_specific_etag_returns_200(self, client: TestClient, path: str) -> None:
        """A concrete ``If-None-Match`` ETag the app never minted still yields 200."""
        response = client.get(path, headers={"If-None-Match": ARBITRARY_ETAG})
        assert response.status_code == 200, (
            f"GET {path} with If-None-Match:{ARBITRARY_ETAG} returned "
            f"{response.status_code}; expected a full 200"
        )

    @pytest.mark.parametrize("path", GET_PATHS)
    def test_if_modified_since_future_returns_200(self, client: TestClient, path: str) -> None:
        """A far-future ``If-Modified-Since`` still yields 200 (no ``Last-Modified`` to beat)."""
        response = client.get(path, headers={"If-Modified-Since": FUTURE_HTTP_DATE})
        assert response.status_code == 200, (
            f"GET {path} with a future If-Modified-Since returned "
            f"{response.status_code}; expected 200 since the app sets no Last-Modified"
        )

    @pytest.mark.parametrize("path", GET_PATHS)
    def test_all_conditional_headers_combined_returns_200(
        self, client: TestClient, path: str
    ) -> None:
        """``If-None-Match`` *and* ``If-Modified-Since`` together still yield 200."""
        response = client.get(
            path,
            headers={"If-None-Match": "*", "If-Modified-Since": FUTURE_HTTP_DATE},
        )
        assert response.status_code == 200, (
            f"GET {path} with combined conditional headers returned "
            f"{response.status_code}; expected 200"
        )


class TestConditionalRequestServesFreshBody:
    """A conditional GET returns the *full, fresh* body, not an empty/stale 304.

    Beyond the status code, the body must be the real payload with a live
    timestamp — proving the request was actually handled, not answered from a
    cache short-circuit that a ``304``-shaped regression might introduce.
    """

    def test_conditional_get_health_returns_full_healthy_body(self, client: TestClient) -> None:
        """Conditional ``GET /health`` returns ``status: healthy`` with a fresh UTC timestamp."""
        body = client.get("/health", headers={"If-None-Match": "*"}).json()
        assert body["status"] == "healthy", f"conditional /health body was {body!r}"
        assert_utc_iso8601(body["timestamp"])

    def test_conditional_get_version_returns_full_body(self, client: TestClient) -> None:
        """Conditional ``GET /api/version`` returns the full three-field payload."""
        body = client.get("/api/version", headers={"If-None-Match": ARBITRARY_ETAG}).json()
        assert set(body.keys()) == {"version", "name", "environment"}, (
            f"conditional /api/version body had unexpected keys: {body!r}"
        )

    def test_conditional_get_hello_returns_full_greeting(self, client: TestClient) -> None:
        """Conditional ``GET /api/hello`` returns the full greeting and a fresh timestamp."""
        body = client.get("/api/hello", headers={"If-Modified-Since": FUTURE_HTTP_DATE}).json()
        assert body["message"], f"conditional /api/hello returned empty message: {body!r}"
        assert_utc_iso8601(body["timestamp"])

    def test_two_conditional_gets_both_serve_fresh_200(self, client: TestClient) -> None:
        """Two back-to-back conditional GETs *both* return 200 with a body.

        A cache that honoured conditionals would typically populate on the first
        request and answer the *second* with a 304. Asserting both are full 200s
        rules out that "warm on first, short-circuit on second" failure mode.
        """
        first = client.get("/health", headers={"If-None-Match": "*"})
        second = client.get("/health", headers={"If-None-Match": "*"})
        assert (first.status_code, second.status_code) == (200, 200), (
            f"expected both conditional GETs to be 200; got "
            f"{first.status_code} then {second.status_code}"
        )
        assert first.json()["status"] == "healthy"
        assert second.json()["status"] == "healthy"


class TestConditionalRequestDoesNotBlockWrites:
    """Conditional headers on ``POST /api/hello`` never suppress body processing.

    Conditional preconditions are a *read*-cache concept; a POST must ignore them
    and process its body normally. A precondition layer that mistakenly gated the
    write path could turn a valid greeting into a ``304``/``412`` — this pins that
    it does not.
    """

    def test_post_hello_with_if_none_match_wildcard_processes_body(
        self, client: TestClient
    ) -> None:
        """``POST /api/hello`` with ``If-None-Match: *`` still returns the greeting."""
        response = client.post(
            "/api/hello",
            json={"name": "Ada"},
            headers={**JSON_HEADERS, "If-None-Match": "*"},
        )
        assert response.status_code == 200, (
            f"conditional POST returned {response.status_code}; expected 200"
        )
        assert response.json()["message"] == expected_greeting("Ada")

    def test_post_hello_with_if_modified_since_processes_body(self, client: TestClient) -> None:
        """``POST /api/hello`` with ``If-Modified-Since`` still returns the greeting."""
        response = client.post(
            "/api/hello",
            json={"name": "Grace"},
            headers={**JSON_HEADERS, "If-Modified-Since": FUTURE_HTTP_DATE},
        )
        assert response.status_code == 200
        assert response.json()["message"] == expected_greeting("Grace")


class TestAcceptEncodingDoesNotCompress:
    """``Accept-Encoding: gzip`` never causes the response to be compressed.

    No compression middleware is registered, so an ``Accept-Encoding``-bearing
    request must come back with the raw JSON body: no ``Content-Encoding`` header
    and no ``Accept-Encoding`` token added to ``Vary``. A ``GZipMiddleware``
    regression would trip these — and would evade every existing ETag/Cache-Control
    assertion, since GZip emits neither of those headers.
    """

    @pytest.mark.parametrize("path", GET_PATHS)
    def test_gzip_request_yields_no_content_encoding(self, client: TestClient, path: str) -> None:
        """A gzip-accepting GET returns 200 with no ``Content-Encoding`` header."""
        response = client.get(path, headers={"Accept-Encoding": "gzip, deflate, br"})
        assert response.status_code == 200
        assert "content-encoding" not in {k.lower() for k in response.headers}, (
            f"GET {path} returned a Content-Encoding header for a gzip-accepting "
            "request — compression middleware may have been added"
        )

    @pytest.mark.parametrize("path", GET_PATHS)
    def test_gzip_request_body_is_valid_json(self, client: TestClient, path: str) -> None:
        """The gzip-accepting response body parses as plain (uncompressed) JSON.

        ``httpx`` transparently inflates a *real* gzip response, so a bare
        ``.json()`` could mask compression. Parsing ``response.text`` (the decoded
        payload) strictly confirms the bytes on the wire were plain JSON, and that
        no bare non-standard token leaked in.
        """
        response = client.get(path, headers={"Accept-Encoding": "gzip"})
        parsed = strict_json_loads(response.text)
        assert isinstance(parsed, dict), f"GET {path} gzip-accepting body was not a JSON object"

    @pytest.mark.parametrize("path", GET_PATHS)
    def test_gzip_request_content_length_matches_uncompressed_body(
        self, client: TestClient, path: str
    ) -> None:
        """``Content-Length`` equals the uncompressed body length for a gzip-accepting GET.

        A compressed response would advertise a *shorter* ``Content-Length`` than
        the decoded body; pinning equality catches that inflation mismatch.
        """
        response = client.get(path, headers={"Accept-Encoding": "gzip"})
        declared = response.headers.get("content-length")
        assert declared is not None, f"GET {path} gzip-accepting response omitted Content-Length"
        assert int(declared) == len(response.content), (
            f"GET {path} Content-Length={declared} but body is {len(response.content)} bytes — "
            "a compression layer may have rewritten the body without fixing the header"
        )

    @pytest.mark.parametrize("path", GET_PATHS)
    def test_response_vary_does_not_advertise_accept_encoding(
        self, client: TestClient, path: str
    ) -> None:
        """The response never adds ``Accept-Encoding`` to ``Vary`` (GZip's fingerprint)."""
        response = client.get(path, headers={"Accept-Encoding": "gzip"})
        assert "accept-encoding" not in _vary_tokens(response), (
            f"GET {path} advertised 'Accept-Encoding' in Vary — a content-negotiating "
            "compression middleware may have been introduced"
        )


class TestAcceptEncodingNeutralityOnPost:
    """``Accept-Encoding: gzip`` on the write path returns an uncompressed greeting."""

    def test_post_hello_gzip_accept_yields_uncompressed_greeting(self, client: TestClient) -> None:
        """``POST /api/hello`` with ``Accept-Encoding: gzip`` returns the plain greeting."""
        response = client.post(
            "/api/hello",
            json={"name": "Linus"},
            headers={**JSON_HEADERS, "Accept-Encoding": "gzip, br"},
        )
        assert response.status_code == 200
        assert "content-encoding" not in {k.lower() for k in response.headers}, (
            "POST /api/hello returned a Content-Encoding header for a gzip-accepting request"
        )
        assert response.json()["message"] == expected_greeting("Linus")


class TestContentNegotiationAsyncTransportParity:
    """The same neutrality holds over the real-ASGI async transport.

    The sync ``TestClient`` and the async ``AsyncClient`` drive different request
    plumbing; a middleware that behaved differently on the async path (a known
    class of transport-specific regression) would otherwise slip through.
    """

    async def test_conditional_get_returns_200_via_async_client(
        self, async_client: AsyncClient
    ) -> None:
        """A conditional ``GET /health`` returns a full 200 over the async transport."""
        response = await async_client.get(
            "/health",
            headers={"If-None-Match": "*", "If-Modified-Since": FUTURE_HTTP_DATE},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    async def test_gzip_request_uncompressed_via_async_client(
        self, async_client: AsyncClient
    ) -> None:
        """A gzip-accepting ``GET /api/hello`` is uncompressed over the async transport."""
        response = await async_client.get("/api/hello", headers={"Accept-Encoding": "gzip"})
        assert response.status_code == 200
        assert "content-encoding" not in {k.lower() for k in response.headers}
        assert "accept-encoding" not in _vary_tokens(response)
