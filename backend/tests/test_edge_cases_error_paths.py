"""Request-body error-path edge cases not pinned elsewhere.

``app/main.py`` already sits at 100% line + branch coverage, so these tests
chase *behaviour*, not lines. They pin error-path edges around malformed or
non-standard request bodies that the existing suites leave unpinned, and they
guard the fix for a real defect uncovered during this edge-case pass:

* **Non-standard JSON constants crash the server.** Python's ``json`` parser
  accepts ``NaN``, ``Infinity`` and ``-Infinity`` even though RFC 8259 §6
  forbids them. Such a token parses to a non-finite ``float``; Pydantic rejects
  it, but the rejected value is echoed back inside the 422 ``detail[].input``
  field, and ``JSONResponse`` serializes with ``allow_nan=False`` — so encoding
  the non-finite float raised and the request returned **500** instead of a
  clean 422. ``app.main.validation_exception_handler`` now sanitizes those
  values; the tests below pin that the response is a well-formed 422 and that
  no other input shape regressed back to a 500.

The remaining classes pin lenient/strict parser boundaries (whitespace-only
body, single quotes, trailing comma, leading-zero numbers) and the fact that
the app does not honour ``Content-Encoding`` on *requests* — all behaviours a
parser or middleware swap could silently flip.
"""

import pytest
from fastapi.testclient import TestClient

from .conftest import JSON_HEADERS, expected_greeting


class TestNonStandardJSONConstantsDoNotCrash:
    """``NaN`` / ``Infinity`` / ``-Infinity`` yield a clean 422 — never a 500.

    These three tokens are the only JSON-ish values that Python's stdlib parser
    accepts but cannot round-trip through a strict (``allow_nan=False``) encoder.
    Before the fix, sending one crashed the request with a 500 because the
    validation-error payload echoed the non-finite ``float`` back to the client
    and the response serializer choked on it. A 500 on a *parseable* request is
    a denial-of-service-shaped defect: any client library that emits ``Infinity``
    for an overflowed number would take the endpoint down.

    The pin asserts the status is 422 **and** that the body is well-formed JSON
    with a non-empty ``detail`` list, so a regression that reintroduces the 500
    (or that starts returning an empty/garbled error body) fails here.
    """

    @pytest.mark.parametrize(
        "raw_body,why",
        [
            (b'{"name": NaN}', "NaN as the field value"),
            (b'{"name": Infinity}', "Infinity as the field value"),
            (b'{"name": -Infinity}', "-Infinity as the field value"),
            (b"NaN", "bare NaN as the whole body"),
            (b"Infinity", "bare Infinity as the whole body"),
            (b"-Infinity", "bare -Infinity as the whole body"),
        ],
        ids=["nan-value", "inf-value", "neg-inf-value", "nan-body", "inf-body", "neg-inf-body"],
    )
    def test_non_finite_constant_returns_clean_422(
        self, client: TestClient, raw_body: bytes, why: str
    ) -> None:
        """A non-finite JSON constant returns a well-formed 422, not a 500."""
        response = client.post("/api/hello", content=raw_body, headers=JSON_HEADERS)
        assert response.status_code == 422, (
            f"{why}: expected 422, got {response.status_code} — a non-finite "
            f"constant must not crash the request with a 500. Body: {response.text!r}"
        )
        detail = response.json()["detail"]
        assert isinstance(detail, list) and detail, (
            f"{why}: 422 body must carry a non-empty 'detail' list, got {detail!r}"
        )

    def test_non_finite_field_value_discriminator_is_string_type(self, client: TestClient) -> None:
        """``{"name": NaN}`` is rejected as a wrong-type field (``type=='string_type'``).

        The constant *parses* (to ``nan``) and reaches Pydantic, which rejects it
        like any other non-string ``name``. Pinning the discriminator documents
        that the sanitisation happens at response-encode time only — it does not
        change *which* validation error the client sees, so a client branching on
        ``string_type`` keeps working.
        """
        response = client.post("/api/hello", content=b'{"name": NaN}', headers=JSON_HEADERS)
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail[0]["type"] == "string_type"
        assert detail[0]["loc"] == ["body", "name"]

    def test_sanitized_input_field_is_json_serialisable(self, client: TestClient) -> None:
        """The 422 ``detail[].input`` for a ``NaN`` value is encoded as a plain string.

        The raw input was a non-finite ``float``; the handler replaces it with its
        ``repr`` so the payload is RFC-8259-valid JSON. Asserting the value is a
        string (not a bare ``NaN`` token) guards against a regression that drops
        the sanitisation and starts emitting non-standard JSON — which strict
        client parsers (``JSON.parse``) would reject outright.
        """
        response = client.post("/api/hello", content=b'{"name": NaN}', headers=JSON_HEADERS)
        assert response.status_code == 422
        # ``response.text`` is the raw bytes the client receives; a leaked NaN
        # would appear as the bare token ``NaN`` (no surrounding quotes).
        assert "NaN" not in response.text.replace('"NaN"', ""), (
            f"response leaked a non-standard bare NaN token: {response.text!r}"
        )
        input_value = response.json()["detail"][0]["input"]
        assert isinstance(input_value, str), (
            f"non-finite input should be stringified, got {input_value!r}"
        )


class TestWhitespaceOnlyBodyIsMalformed:
    """A body that is only whitespace is malformed JSON — 422 ``json_invalid``.

    ``TestJSONBodyParsingEdges`` pins that trailing whitespace *after* a valid
    object is tolerated, and ``test_empty_body`` covers the zero-byte case (which
    reports ``missing``). A body of *only* whitespace is a third, distinct branch:
    there is content to parse, but it contains no JSON value, so the parser fails
    outright. Some over-eager "treat blank as empty object" middleware would turn
    this into a ``missing``-field 422 (or even a 200); pinning ``json_invalid``
    keeps blank-but-present bodies firmly in the parse-error bucket.
    """

    @pytest.mark.parametrize(
        "raw_body",
        [b"   ", b"\t\t", b"\r\n", b" \t\r\n "],
        ids=["spaces", "tabs", "crlf", "mixed"],
    )
    def test_whitespace_only_body_returns_json_invalid(
        self, client: TestClient, raw_body: bytes
    ) -> None:
        """A whitespace-only body returns 422 with ``type=='json_invalid'``."""
        response = client.post("/api/hello", content=raw_body, headers=JSON_HEADERS)
        assert response.status_code == 422
        assert response.json()["detail"][0]["type"] == "json_invalid"


class TestPythonJSONExtensionsRejected:
    """Python-/JS-flavoured JSON that RFC 8259 forbids is rejected (422 ``json_invalid``).

    ``TestRequestBodyJSONStrictness`` pins comments, concatenated objects and an
    extra closing brace. These pin three more dialect features that a lenient
    parser (``json5``, ``demjson``, ``PyYAML.safe_load``) would silently accept —
    each a realistic client mistake:

    * **Single-quoted strings** — the most common hand-written-JSON error and the
      default repr of a Python ``dict`` stringified with ``str()`` instead of
      ``json.dumps``.
    * **Trailing comma** — emitted by some template engines and JS object
      literals copy-pasted into a request body.
    * **Leading-zero number** — ``007`` is a valid C/JS integer literal but
      invalid JSON; a YAML-based parser would read it as ``7``.
    """

    @pytest.mark.parametrize(
        "raw_body,why",
        [
            (b"{'name':'Alice'}", "single-quoted keys/strings"),
            (b'{"name":"Alice",}', "trailing comma after the last member"),
            (b"007", "number with a leading zero"),
        ],
        ids=["single-quotes", "trailing-comma", "leading-zero"],
    )
    def test_dialect_extension_returns_json_invalid(
        self, client: TestClient, raw_body: bytes, why: str
    ) -> None:
        """A non-RFC-8259 JSON dialect feature returns 422 ``json_invalid``."""
        response = client.post("/api/hello", content=raw_body, headers=JSON_HEADERS)
        assert response.status_code == 422, (
            f"{why}: expected 422 json_invalid, got {response.status_code}"
        )
        assert response.json()["detail"][0]["type"] == "json_invalid", (
            f"{why}: a lenient parser would accept this — discriminator drifted to "
            f"{response.json()['detail'][0]['type']!r}"
        )


class TestRequestContentEncodingIgnored:
    """The server does not decode ``Content-Encoding`` on *requests*.

    Starlette reads the raw request body as-is; it does not inflate a declared
    ``gzip``/``deflate``/``br`` encoding (request decompression, if wanted, is the
    reverse proxy's job). So a request that *declares* ``Content-Encoding: gzip``
    but sends plain (un-gzipped) JSON is parsed normally and succeeds. Pinning
    this guards against a regression that bolts on a request-decompression
    middleware: such a middleware would try to inflate the already-plain body,
    fail, and start 400/500-ing requests that work today. The complementary risk
    — a client that sends *actually* gzipped bytes expecting the server to inflate
    them — is also pinned: those bytes are not valid JSON, so the request is a
    clean 422, documenting that decompression is genuinely absent.
    """

    def test_gzip_declared_plain_body_is_parsed_normally(self, client: TestClient) -> None:
        """``Content-Encoding: gzip`` over a *plain* JSON body still succeeds (200)."""
        response = client.post(
            "/api/hello",
            content=b'{"name":"Gzip"}',
            headers={**JSON_HEADERS, "Content-Encoding": "gzip"},
        )
        assert response.status_code == 200
        assert response.json()["message"] == expected_greeting("Gzip")

    def test_actually_gzipped_body_is_not_inflated(self, client: TestClient) -> None:
        """Real gzip bytes are treated as raw (non-JSON) — a 4xx, not transparently inflated.

        Proves the server performs no request-side decompression: the gzip magic
        bytes are not valid JSON (in fact not valid UTF-8), so the request is
        rejected client-side. A regression that *added* inflation would flip this
        to a 200, silently changing the wire contract for every client. The exact
        4xx code (Starlette returns 400 when the body is not decodable, 422 when it
        decodes but is not JSON) is a parser-internal detail, so the pin is "a
        client error, and specifically not a 200".
        """
        import gzip

        gzipped = gzip.compress(b'{"name":"Gzip"}')
        response = client.post(
            "/api/hello",
            content=gzipped,
            headers={**JSON_HEADERS, "Content-Encoding": "gzip"},
        )
        assert response.status_code != 200, (
            "raw gzip bytes were accepted with 200 — the server must not "
            "transparently inflate request bodies"
        )
        assert 400 <= response.status_code < 500, (
            f"expected a 4xx client error for un-inflatable bytes, got {response.status_code}"
        )
