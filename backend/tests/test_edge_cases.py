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

from .conftest import cors_preflight_headers, expected_greeting


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


class TestAcceptHeaderIgnored:
    """The server does not perform content negotiation — every successful
    response is ``application/json`` regardless of ``Accept``.

    ``TestResponseContentTypePinned`` pins the response media type when the
    client sends *no* ``Accept``. These tests pin the same media type when
    the client explicitly asks for something else (or excludes JSON). A
    regression that adds a content-negotiation middleware — emitting HTML,
    XML, or a 406 — would fail here.
    """

    def test_accept_text_html_still_returns_json(self, client: TestClient) -> None:
        """``Accept: text/html`` is ignored — server returns JSON with 200."""
        response = client.get("/health", headers={"Accept": "text/html"})
        assert response.status_code == 200
        assert response.headers.get("content-type") == "application/json"

    def test_accept_application_xml_still_returns_json(self, client: TestClient) -> None:
        """``Accept: application/xml`` is ignored — server returns JSON with 200.

        Distinct from ``text/html`` because XML is a structured format some
        misguided middleware might try to transcode to; pinning JSON here
        guards against an "if XML is requested, serialise via xmltodict"
        regression.
        """
        response = client.get("/health", headers={"Accept": "application/xml"})
        assert response.status_code == 200
        assert response.headers.get("content-type") == "application/json"

    def test_accept_excludes_json_still_returns_json(self, client: TestClient) -> None:
        """``Accept: application/json;q=0, text/html`` (JSON explicitly excluded)
        still returns JSON with 200.

        Per RFC 9110 §12.5.1 a ``q=0`` accept parameter means "not acceptable";
        a content-negotiating server would respond 406. The current server has
        no content negotiation, so it returns its only representation. Pinning
        this guards against silently *adding* negotiation that would start
        returning 406 to clients who happened to send this header.
        """
        response = client.get(
            "/health",
            headers={"Accept": "application/json;q=0, text/html"},
        )
        assert response.status_code == 200
        assert response.headers.get("content-type") == "application/json"

    def test_accept_wildcard_returns_json(self, client: TestClient) -> None:
        """``Accept: */*`` returns JSON — the only representation the server has."""
        response = client.get("/health", headers={"Accept": "*/*"})
        assert response.status_code == 200
        assert response.headers.get("content-type") == "application/json"


class TestNullOriginNotAllowlisted:
    """The literal Origin string ``"null"`` (sent by sandboxed iframes,
    ``file://`` pages, and some data-URI contexts) is **not** allow-listed.

    Browsers send ``Origin: null`` from contexts where the real origin is
    sensitive or undefined. Allow-listing ``null`` is a common
    misconfiguration that effectively re-enables CORS for any attacker that
    can host a sandboxed iframe. ``TestRegressionCORSAllowListBoundary``
    pins three realistic same-host near-misses; these tests pin the
    cross-context ``"null"`` case.
    """

    def test_get_with_null_origin_receives_no_acao(self, client: TestClient) -> None:
        """``GET /health`` with ``Origin: null`` returns no ``Access-Control-Allow-Origin``."""
        response = client.get("/health", headers={"Origin": "null"})
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") is None

    def test_preflight_with_null_origin_is_rejected(self, client: TestClient) -> None:
        """OPTIONS preflight with ``Origin: null`` is rejected (no ``Access-Control-Allow-Origin``).

        Starlette's ``CORSMiddleware`` short-circuits a preflight from a
        disallowed origin with a 400 and no allow-origin header. Whether the
        status code is exactly 400 is a middleware-internal detail, but the
        absence of the allow-origin header is the security-relevant pin —
        and that is what we assert.
        """
        response = client.options(
            "/api/hello",
            headers=cors_preflight_headers("POST", origin="null"),
        )
        assert response.headers.get("access-control-allow-origin") is None


class TestRequestBodyJSONStrictness:
    """Strict JSON parsing pins — extensions to ``TestJSONBodyParsingEdges``.

    Those tests cover BOM / trailing whitespace / trailing garbage. The
    cases below pin behaviours adjacent to "valid JSON object" that
    permissive parsers sometimes accept: mixed-case keys, JS-style
    comments, multiple concatenated objects, and a trailing extra brace.
    A swap to a lenient parser (``demjson``, ``json5``) would fail here.
    """

    def test_mixed_case_name_key_returns_422(self, client: TestClient) -> None:
        """``{"Name":"Alice"}`` (capital ``N``) returns 422 — field names are case-sensitive.

        Pydantic does not auto-fold field-name casing. Pinning this prevents
        a regression that adds ``populate_by_name`` with a case-insensitive
        alias generator (a "helpful" change that would silently start
        accepting two distinct spellings as the same field).
        """
        response = client.post("/api/hello", json={"Name": "Alice"})
        assert response.status_code == 422

    def test_javascript_comment_in_body_returns_422(self, client: TestClient) -> None:
        """A JS-style comment inside the JSON object returns 422 — strict JSON, no JSON5.

        RFC 8259 forbids comments; some hand-rolled clients (and a few
        config-file libraries) emit them anyway. Pinning the 422 prevents
        a regression to a JSON5/HJSON-tolerant parser that would silently
        accept the comment and parse the surrounding object.
        """
        response = client.post(
            "/api/hello",
            content=b'{"name":"Alice"/* a comment */}',
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422

    def test_multiple_concatenated_json_objects_returns_422(self, client: TestClient) -> None:
        """``{"name":"X"}{"name":"Y"}`` returns 422 — exactly one object per request.

        Distinct from ``test_trailing_garbage_after_json_object_returns_422``:
        the bytes after the first ``}`` here are themselves *valid JSON*. A
        regression to a "parse the first JSON value, ignore the rest"
        strategy would silently accept and the second object would be
        dropped. The 422 guards against that — and also against an
        accidental switch to a streaming/NDJSON parser.
        """
        response = client.post(
            "/api/hello",
            content=b'{"name":"X"}{"name":"Y"}',
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422

    def test_extra_closing_brace_returns_422(self, client: TestClient) -> None:
        """``{"name":"X"}}`` (extra ``}``) returns 422 — distinct from the ``xxx`` case.

        ``test_trailing_garbage_after_json_object_returns_422`` pins that
        non-whitespace *letters* after the object fail. This pins the
        specific case where the trailing byte is a JSON structural
        character — a more plausible client bug (over-quoted/over-braced
        template output) — and guards against a parser that re-uses
        balanced-brace counting and would close the outer object early.
        """
        response = client.post(
            "/api/hello",
            content=b'{"name":"X"}}',
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422


class TestTrailingSlashOnAllEndpoints:
    """Trailing-slash tolerance pinned for every public route.

    ``TestPathRouting.test_health_with_trailing_slash_succeeds`` pins
    ``GET /health/``. These tests pin the same behaviour for the other
    three public routes so a future ``redirect_slashes=False`` (or a
    custom router) can't silently start returning 404 / 307 for only a
    subset of paths. A consistent contract across endpoints is what
    callers — and frontend URL-join helpers — actually depend on.
    """

    def test_api_version_with_trailing_slash_succeeds(self, client: TestClient) -> None:
        """``GET /api/version/`` returns 200 with the same body shape as ``/api/version``."""
        response = client.get("/api/version/")
        assert response.status_code == 200
        body = response.json()
        assert set(body.keys()) == {"version", "name", "environment"}

    def test_get_api_hello_with_trailing_slash_succeeds(self, client: TestClient) -> None:
        """``GET /api/hello/`` returns 200 with the standard hello message."""
        response = client.get("/api/hello/")
        assert response.status_code == 200
        assert "Hello, World" in response.json()["message"]

    def test_post_api_hello_with_trailing_slash_succeeds(self, client: TestClient) -> None:
        """``POST /api/hello/`` returns 200 — the trailing slash does not switch HTTP method.

        A misconfigured router that auto-redirects trailing slashes via 307
        would here downgrade the POST to a follow-up GET (most clients
        preserve method on 307, but some don't) — pinning the direct 200
        guards against that subtle regression.
        """
        response = client.post("/api/hello/", json={"name": "Alice"})
        assert response.status_code == 200
        assert "Alice" in response.json()["message"]


class TestSpuriousURLsReturn404:
    """Convention-named URLs that the app does not serve must 404 — not
    silently start responding with default content.

    These guard against three plausible regressions:

    * A future ``openapi_yaml_url=`` flag (FastAPI does not provide one
      today, but a custom adapter could) silently exposes a second
      schema format.
    * A static-files middleware mounted at ``/`` accidentally serving a
      bundled ``favicon.ico``.
    * A URL-normalisation middleware that collapses whitespace inside
      path segments (so ``/he alth`` would resolve to ``/health``).
    """

    def test_openapi_yaml_returns_404(self, client: TestClient) -> None:
        """``GET /openapi.yaml`` returns 404 — only ``/openapi.json`` is served."""
        response = client.get("/openapi.yaml")
        assert response.status_code == 404

    def test_favicon_ico_returns_404(self, client: TestClient) -> None:
        """``GET /favicon.ico`` returns 404 — no implicit favicon is served.

        Browsers request ``/favicon.ico`` unsolicited on every navigation.
        Returning an empty 200 (a common "fix" to silence browser logs) or
        a default image would surprise monitoring and complicate
        ``/`` routing later. Pinning 404 keeps the surface deliberately
        minimal.
        """
        response = client.get("/favicon.ico")
        assert response.status_code == 404

    def test_path_with_embedded_space_returns_404(self, client: TestClient) -> None:
        """``GET /he alth`` returns 404 — whitespace inside a path segment is not collapsed.

        Some URL-normalisation libraries strip or collapse whitespace before
        routing; a regression that introduced one would create silent
        aliases for every endpoint. Pinning 404 keeps each canonical URL
        singular.
        """
        # ``%20`` is the wire-encoding of the space; httpx encodes spaces
        # this way automatically, but using the literal makes the intent
        # explicit.
        response = client.get("/he%20alth")
        assert response.status_code == 404


class TestPostQueryStringIgnored:
    """Query strings on ``POST /api/hello`` do not affect body parsing.

    ``TestPathRouting.test_hello_get_query_string_is_ignored`` pins the
    GET side. The POST side is structurally different (FastAPI dispatches
    on the body, not the URL) and a regression that introduced a
    ``Query()`` parameter on the POST handler — perhaps a "name override"
    feature gone stale — would silently change behaviour for any client
    that happens to append a tracking parameter. Pinning the body-only
    contract guards against that.
    """

    def test_post_hello_ignores_query_string(self, client: TestClient) -> None:
        """``POST /api/hello?name=Bob`` with body ``{"name":"Alice"}`` greets ``Alice``."""
        response = client.post("/api/hello?name=Bob", json={"name": "Alice"})
        assert response.status_code == 200
        assert response.json()["message"] == expected_greeting("Alice")
