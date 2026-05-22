"""Edge-case behavioural pins for the public HTTP contract.

These tests do not chase line coverage (``app/main.py`` already sits at
100% line + branch coverage) — they pin behaviours that the live server
exhibits today but that no existing test asserts. A future regression that
silently flips any of these — for example, a middleware swap that starts
accepting wrong Content-Types, a router config that case-normalizes
paths, or a Starlette upgrade that changes BOM handling — would fail here
first.

Each test documents the specific edge that was *unpinned* before this
file existed; collectively they cover:

* Top-level non-object JSON bodies (``null`` / ``true`` / ``42`` / a
  bare string) — orthogonal to ``TestHelloNameTypeValidation`` which
  pins wrong types **inside** the object.
* Request ``Content-Type`` permissiveness (parameterised charset,
  case-insensitivity) and strictness (missing, unrelated MIME).
* Tolerance of a UTF-8 BOM prefix and of trailing whitespace after the
  JSON object; rejection of trailing garbage.
* URL routing edges: double-slashed paths and percent-encoded path
  segments.
* Echo fidelity at boundaries: single-char, ~50K-char, and
  ASCII-control / Unicode-noncharacter inputs that current tests don't
  cover.
* Response ``Content-Type`` is exactly ``application/json`` (no charset
  suffix) — pinned so a later switch to a custom response class can't
  silently drop the bare media type that some strict clients require.
"""

from fastapi.testclient import TestClient

from .conftest import expected_greeting


class TestTopLevelNonObjectBodyReturns422:
    """The request body must be a JSON object — ``null``, booleans,
    numbers, arrays, and bare strings are all rejected with 422.

    ``TestHelloNameTypeValidation`` pins the wrong-type-for-``name`` cases
    (the value sits *inside* an object). The cases below put the wrong
    type at the *top level* of the body, which is a different Pydantic
    validation branch (body parsing vs. field parsing). A regression that
    started auto-wrapping scalars or coercing ``null`` to ``{}`` would
    bypass the existing field-level tests but fail here.
    """

    def test_top_level_null_body_returns_422(self, client: TestClient) -> None:
        """POST /api/hello with a body of literal ``null`` returns 422."""
        response = client.post(
            "/api/hello",
            content=b"null",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422

    def test_top_level_boolean_body_returns_422(self, client: TestClient) -> None:
        """POST /api/hello with a body of literal ``true`` returns 422."""
        response = client.post(
            "/api/hello",
            content=b"true",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422

    def test_top_level_number_body_returns_422(self, client: TestClient) -> None:
        """POST /api/hello with a body of a bare integer returns 422."""
        response = client.post(
            "/api/hello",
            content=b"42",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422

    def test_top_level_string_body_returns_422(self, client: TestClient) -> None:
        """POST /api/hello with a body of a bare JSON string returns 422.

        Bare-string body is a common client mistake (someone calls
        ``json.dumps(name)`` instead of ``json.dumps({"name": name})``);
        pinning the rejection prevents a regression that would
        silently start treating ``"Alice"`` as the name itself.
        """
        response = client.post(
            "/api/hello",
            content=b'"Alice"',
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422


class TestRequestContentTypePermissiveness:
    """FastAPI's JSON body parser accepts a few Content-Type variants that
    are equivalent per RFC 9110 / RFC 8259. These tests pin that
    behaviour so a future custom middleware doesn't tighten the parser
    and break clients that send a charset parameter or a non-lowercased
    media type.
    """

    def test_content_type_with_charset_parameter_is_accepted(self, client: TestClient) -> None:
        """``application/json; charset=utf-8`` is treated as JSON (200)."""
        response = client.post(
            "/api/hello",
            content=b'{"name":"Alice"}',
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        assert response.status_code == 200
        assert "Alice" in response.json()["message"]

    def test_content_type_mixed_case_is_accepted(self, client: TestClient) -> None:
        """``Application/JSON`` (case-insensitive media type) is treated as JSON (200).

        Per RFC 9110 §8.3.1 media types are case-insensitive. Some clients
        (older curl wrappers, certain Java HTTP libraries) emit ``Application/Json``
        — pinning acceptance prevents a regression that lower-cases the comparison
        on only one side.
        """
        response = client.post(
            "/api/hello",
            content=b'{"name":"Bob"}',
            headers={"Content-Type": "Application/JSON"},
        )
        assert response.status_code == 200
        assert "Bob" in response.json()["message"]


class TestRequestContentTypeStrictness:
    """The complementary negative pins for ``TestRequestContentTypePermissiveness``.

    ``TestContentTypeNegotiation`` pins form-encoded and text/plain;
    these pin the no-header case and an unrelated structured-data MIME.
    """

    def test_post_without_content_type_header_returns_422(self, client: TestClient) -> None:
        """POST with a body but no ``Content-Type`` header returns 422.

        FastAPI's body parser dispatches on Content-Type; without one,
        the JSON branch is never entered and validation fails. Pinning
        prevents a regression that defaults to ``application/json`` and
        starts accepting requests with no declared body type.
        """
        # httpx's TestClient sets Content-Type automatically when ``json=`` is
        # used; using ``content=`` with no headers omits it entirely.
        response = client.post("/api/hello", content=b'{"name":"Bob"}')
        assert response.status_code == 422

    def test_post_with_application_xml_content_type_returns_422(self, client: TestClient) -> None:
        """POST with ``application/xml`` (structured non-JSON) returns 422.

        Distinct from ``text/plain`` (free text) — pins that any structured
        non-JSON MIME is rejected, not just ``text/*``.
        """
        response = client.post(
            "/api/hello",
            content=b'{"name":"Bob"}',
            headers={"Content-Type": "application/xml"},
        )
        assert response.status_code == 422


class TestJSONBodyParsingEdges:
    """Whitespace / BOM / trailing-bytes tolerances on the request body."""

    def test_utf8_bom_prefix_on_body_is_accepted(self, client: TestClient) -> None:
        """A UTF-8 BOM (``EF BB BF``) before the JSON object is tolerated (200).

        Some Windows-origin clients prepend a BOM to UTF-8 payloads. The
        current JSON parser strips/tolerates the prefix and returns 200;
        pinning it prevents a regression to strict-RFC-8259 parsing
        (which forbids a leading BOM) without an explicit decision.
        """
        response = client.post(
            "/api/hello",
            content=b"\xef\xbb\xbf" + b'{"name":"Bob"}',
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200
        assert "Bob" in response.json()["message"]

    def test_trailing_whitespace_after_json_object_is_accepted(self, client: TestClient) -> None:
        """Trailing ASCII whitespace after ``}`` is tolerated (200).

        RFC 8259 §2 allows whitespace surrounding JSON values; pinning
        the lenient behaviour guards against a parser swap that
        rejects ``{"name":"X"}\\n`` (common from CLI clients).
        """
        response = client.post(
            "/api/hello",
            content=b'{"name":"Carol"}   \r\n\t',
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200
        assert "Carol" in response.json()["message"]

    def test_trailing_garbage_after_json_object_returns_422(self, client: TestClient) -> None:
        """Non-whitespace bytes after ``}`` cause a 422.

        Complement to the trailing-whitespace test: the parser is lenient
        about *whitespace* but strict about *content*. Pinning this
        prevents a regression to a "read first valid JSON value, ignore
        the rest" parser that would silently drop part of a malformed
        request — a class of bug that can hide truncated payloads.
        """
        response = client.post(
            "/api/hello",
            content=b'{"name":"Carol"}xxx',
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422


class TestPathRoutingEdges:
    """Routing behaviour on path shapes that valid clients almost never
    send but that proxies and misbehaving SDKs sometimes do.

    Complements ``TestPathRouting`` (case sensitivity, trailing slash,
    query string) — these pin the double-slash and percent-encoded
    branches of the Starlette router.
    """

    def test_double_slash_prefix_does_not_route_to_health(self, client: TestClient) -> None:
        """``GET //health`` returns 404 (the leading double slash is not collapsed).

        If a future routing middleware started collapsing duplicate
        slashes, every URL would have multiple aliases — a small but
        real risk of cache poisoning and route confusion. Pinning the
        404 keeps each canonical URL singular.
        """
        response = client.get("//health")
        assert response.status_code == 404

    def test_percent_encoded_path_segment_resolves_to_canonical_route(
        self, client: TestClient
    ) -> None:
        """``GET /he%61lth`` resolves to ``/health`` and returns 200.

        Starlette percent-decodes path segments before routing, so
        ``%61`` (``a``) recovers the canonical ``/health`` path. Some
        deployments place a reverse proxy that re-encodes paths; pinning
        this lets such a proxy compose without breaking routing — and
        flags a regression to strict-byte routing that would silently
        404 these requests.
        """
        response = client.get("/he%61lth")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"


class TestNameEchoBoundaries:
    """Length and character-class boundaries for the POST-hello echo.

    Existing tests cover 10K-char performance, common Unicode (emoji,
    RTL, zero-width), and a few specific control characters. These
    fill the remaining boundaries: single-char, ~50K-char (well beyond
    the perf test), pure-whitespace, and an ASCII control / Unicode
    noncharacter the existing tests don't touch.
    """

    def test_single_character_name_echoed_verbatim(self, client: TestClient) -> None:
        """A one-character name is echoed verbatim in the greeting.

        The smallest legal name. Pinning prevents a regression that
        introduces a minimum length validator without an explicit
        product decision.
        """
        response = client.post("/api/hello", json={"name": "X"})
        assert response.status_code == 200
        assert response.json()["message"] == expected_greeting("X")

    def test_fifty_thousand_character_name_round_trips_verbatim(self, client: TestClient) -> None:
        """A 50_000-character name is echoed verbatim with the exact length preserved.

        ``TestLargePayloadPerformance`` measures latency at 10K chars
        but doesn't assert byte-exact round-trip at scale. This pins
        the behaviour: no truncation, no normalisation, exact length.
        A regression that adds a request-body size limit would fail
        here loudly, prompting an explicit product decision rather
        than silent truncation.
        """
        name = "A" * 50_000
        response = client.post("/api/hello", json={"name": name})
        assert response.status_code == 200
        message = response.json()["message"]
        assert name in message
        # ``"Hello, {name}! Welcome to your Software Factory."`` -> name + 42 fixed chars
        assert len(message) == len(name) + 42

    def test_pure_whitespace_name_echoed_verbatim(self, client: TestClient) -> None:
        """A name consisting only of whitespace bytes is echoed verbatim.

        The endpoint does not call ``.strip()`` on the name; pinning
        the verbatim echo guards against a future "tidy up the name"
        change that would silently change responses for these inputs.
        Frontends that *want* to reject whitespace-only must do so
        client-side (and the frontend tests pin that they do).
        """
        response = client.post("/api/hello", json={"name": "\t\r\n "})
        assert response.status_code == 200
        assert response.json()["message"] == expected_greeting("\t\r\n ")

    def test_ascii_bel_character_in_name_echoed_verbatim(self, client: TestClient) -> None:
        """The ASCII BEL byte (``\\x07``) inside a name is echoed verbatim.

        ``TestHelloNameSpecialCharacters`` covers TAB, CR, and the NUL
        byte but not the other non-printable C0 controls. BEL is the
        most likely to be filtered by a misguided sanitiser (terminal
        beep concerns) — pinning verbatim echo flags such a regression.
        """
        response = client.post("/api/hello", json={"name": "A\x07B"})
        assert response.status_code == 200
        assert "A\x07B" in response.json()["message"]

    def test_unicode_noncharacter_in_name_echoed_verbatim(self, client: TestClient) -> None:
        """A Unicode noncharacter (``U+FFFE``) inside a name is echoed verbatim.

        U+FFFE is reserved as a "noncharacter" — valid in transit, never
        a legal interchange character. Some Unicode-normalising layers
        strip it silently. Pinning verbatim echo guards against a
        regression that introduces NFC normalisation on the request
        body (a common "helpful" middleware).
        """
        name = "A￾B"
        response = client.post("/api/hello", json={"name": name})
        assert response.status_code == 200
        assert name in response.json()["message"]


class TestResponseContentTypePinned:
    """The response Content-Type is exactly ``application/json``.

    FastAPI's default ``JSONResponse`` emits a bare ``application/json``
    media type (no charset suffix). Some strict clients reject responses
    with a charset parameter; others reject responses without one. The
    current contract is "bare media type" and that is pinned here so a
    later switch to ``UJSONResponse`` / a custom response class can't
    silently change it.
    """

    def test_health_response_content_type_is_exactly_application_json(
        self, client: TestClient
    ) -> None:
        """``GET /health`` returns ``Content-Type: application/json`` (no parameters)."""
        response = client.get("/health")
        assert response.headers.get("content-type") == "application/json"

    def test_post_hello_response_content_type_is_exactly_application_json(
        self, client: TestClient
    ) -> None:
        """``POST /api/hello`` returns ``Content-Type: application/json`` (no parameters)."""
        response = client.post("/api/hello", json={"name": "Alice"})
        assert response.headers.get("content-type") == "application/json"

    def test_version_response_content_type_is_exactly_application_json(
        self, client: TestClient
    ) -> None:
        """``GET /api/version`` returns ``Content-Type: application/json`` (no parameters)."""
        response = client.get("/api/version")
        assert response.headers.get("content-type") == "application/json"
