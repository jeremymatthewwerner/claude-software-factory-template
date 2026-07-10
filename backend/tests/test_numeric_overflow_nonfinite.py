"""Numbers that overflow to infinity on parse reach the non-finite sanitizer.

``app/main.py`` already sits at 100% line + branch coverage, so these tests
chase *behaviour*, not lines. They pin a single, previously-unpinned door into
``app.main._replace_non_finite``:

Every existing non-finite test — ``test_edge_cases_error_paths.py``'s
``TestNonStandardJSONConstantsDoNotCrash`` and the whole
``test_regression_nonfinite_sanitization.py`` suite — reaches the sanitizer via
the **non-standard JSON tokens** ``NaN`` / ``Infinity`` / ``-Infinity``. RFC 8259
§6 forbids those tokens; Python's ``json`` parser accepts them as a dialect
extension. But ``json.loads`` *also* yields a non-finite ``float`` from a
perfectly **RFC-8259-valid number literal** whose magnitude overflows the
IEEE-754 ``double`` range: ``1e400`` parses to ``inf`` (``json.loads("1e400")``
``== inf``). That value is then rejected by Pydantic (``name`` is a ``str``) and
echoed back inside the 422 ``detail[].input`` field — the exact shape that, before
#328, crashed the request with a 500 because ``JSONResponse``'s
``allow_nan=False`` encoder could not serialize the non-finite float.

So the overflow path exercises the *same* crash-prone code through a *different,
syntactically-valid door*. A regression that re-introduced the 500 only for
RFC-valid overflow (e.g. a parser swap that special-cased the named tokens but
let overflow through unsanitized), or that started leaking a bare ``Infinity``
token into the response for overflowed numbers, would slip past every existing
test — they only ever send the literal tokens. These pins close that gap:

* **``1e400`` → clean 422, never a 500**, with the input stringified to ``"inf"``.
* **It is RFC-valid syntax** — the discriminator is ``string_type`` (it parsed and
  reached Pydantic), explicitly *not* ``json_invalid`` (which the ``Infinity``
  *token* contrast in ``TestPythonJSONExtensionsRejected`` does not cover for
  numbers).
* **The finite boundary is preserved** — ``1e308`` is below ``float`` max
  (~1.8e308) so it stays a JSON *number* in the echoed input, never stringified.
* **Overflow recurses** through arrays/objects exactly like the token path.
* **No bare ``Infinity`` / ``NaN`` token leaks** into the response, so strict
  client parsers (``JSON.parse``) still accept the 422 body.
"""

import json
import math

import pytest
from fastapi.testclient import TestClient

from .conftest import JSON_HEADERS, strict_json_loads


class TestOverflowNumberDoesNotCrash:
    """An RFC-valid number that overflows to ``inf`` yields a clean 422, not a 500.

    ``1e400`` / ``-1e400`` / ``1e999`` are all well-formed JSON numbers (digits +
    exponent, no dialect extension) that ``json.loads`` rounds to ``inf`` / ``-inf``
    because they exceed the IEEE-754 ``double`` range. The rejected non-finite float
    is echoed into the 422 ``detail[].input`` field; without the #328 sanitizer the
    ``allow_nan=False`` response encoder would choke on it and 500. This pins that
    the request stays a well-formed 422 with the overflowed value stringified.
    """

    @pytest.mark.parametrize(
        "raw_body,expected_input,why",
        [
            (b'{"name": 1e400}', "inf", "positive overflow rounds up to +inf"),
            (b'{"name": -1e400}', "-inf", "negative overflow rounds down to -inf"),
            (b'{"name": 1e999}', "inf", "absurd exponent still overflows to +inf"),
            (b'{"name": 1E400}', "inf", "uppercase exponent marker overflows too"),
        ],
        ids=["pos-overflow", "neg-overflow", "huge-exponent", "uppercase-E"],
    )
    def test_overflow_number_returns_clean_422_with_stringified_input(
        self, client: TestClient, raw_body: bytes, expected_input: str, why: str
    ) -> None:
        """An overflowing number is a 422 whose echoed ``input`` is the ``inf`` repr string."""
        response = client.post("/api/hello", content=raw_body, headers=JSON_HEADERS)
        assert response.status_code == 422, (
            f"{why}: expected 422, got {response.status_code} — an overflowed number "
            f"must not crash the request with a 500. Body: {response.text!r}"
        )
        detail = response.json()["detail"]
        assert isinstance(detail, list) and detail, (
            f"{why}: 422 body must carry a non-empty 'detail' list, got {detail!r}"
        )
        assert detail[0]["input"] == expected_input, (
            f"{why}: overflowed value should be stringified to {expected_input!r}, "
            f"got {detail[0]['input']!r}"
        )


class TestOverflowNumberIsValidJSONSyntax:
    """The overflow path is RFC-valid syntax — ``string_type``, never ``json_invalid``.

    This is the load-bearing distinction from the ``Infinity`` *token*. The token is a
    dialect extension that ``TestPythonJSONExtensionsRejected`` keeps in the
    parse-error (``json_invalid``) bucket; an overflowing *number* parses cleanly and
    reaches Pydantic, so it is rejected as a wrong-type field (``string_type``), exactly
    like any other non-string ``name``. Pinning the discriminator documents that
    overflow is a *validation* failure, not a *syntax* failure — a client branching on
    ``string_type`` keeps working, and a regression that started reporting overflow as
    ``json_invalid`` (or as a 500) fails here.
    """

    def test_overflow_number_is_wrong_type_not_parse_error(self, client: TestClient) -> None:
        """``{"name": 1e400}`` is ``type=='string_type'`` at ``loc==['body','name']``."""
        response = client.post("/api/hello", content=b'{"name": 1e400}', headers=JSON_HEADERS)
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail[0]["type"] == "string_type", (
            "an overflowed *number* parses cleanly and reaches validation — it must be a "
            f"wrong-type (string_type) error, not a parse error; got {detail[0]['type']!r}"
        )
        assert detail[0]["loc"] == ["body", "name"]

    def test_overflow_body_is_genuinely_rfc_valid_json(self) -> None:
        """``json.loads("1e400")`` succeeds and yields ``inf`` — proving it is valid syntax.

        Anchors the suite's premise at the parser level: the body is not a dialect
        extension the way the ``Infinity`` token is, it is a standard number literal
        that simply overflows the ``double`` range.
        """
        parsed = json.loads("1e400")
        assert parsed == float("inf") and not math.isfinite(parsed)


class TestFiniteHugeNumberBoundaryPreserved:
    """The complementary boundary: a finite-but-huge number is *not* stringified.

    ``1e308`` is below ``float`` max (~1.7976931348623157e308), so ``json.loads``
    keeps it a finite ``float``. The sanitizer must leave it untouched — the echoed
    422 ``input`` stays a JSON *number*, byte-identical to FastAPI's default. Pinning
    this guards against an over-eager regression that stringifies *any* large
    magnitude (e.g. ``str(value)`` whenever ``abs(value) > 1e300``) rather than only
    genuinely non-finite values. It is the negative that gives the overflow pins their
    meaning: the line is drawn exactly at the finite/non-finite boundary.
    """

    def test_finite_huge_number_echoed_as_number_not_string(self, client: TestClient) -> None:
        """``{"name": 1e308}`` echoes ``input`` back as the finite ``float``, not ``"1e+308"``."""
        response = client.post("/api/hello", content=b'{"name": 1e308}', headers=JSON_HEADERS)
        assert response.status_code == 422
        input_value = response.json()["detail"][0]["input"]
        assert isinstance(input_value, float) and math.isfinite(input_value), (
            f"a finite magnitude must stay a JSON number, got {input_value!r} "
            f"({type(input_value).__name__}) — the sanitizer over-reached past the "
            "finite/non-finite boundary"
        )
        assert input_value == 1e308


class TestNestedOverflowRecursesLikeTokenPath:
    """Overflow inside a container is sanitized leaf-by-leaf, just like ``NaN`` tokens.

    ``test_regression_nonfinite_sanitization.py`` pins the recursion for the literal
    ``NaN`` / ``Infinity`` *tokens*; this proves the *overflow* door feeds the same
    recursive walk. A non-finite value produced by overflow, nested inside an array or
    object, must be stringified while finite siblings and structure survive untouched —
    so a refactor that handled overflow on a separate (non-recursive) branch is caught.
    """

    def test_overflow_inside_array_is_selectively_stringified(self, client: TestClient) -> None:
        """``{"name": [1e400, 1.5]}`` echoes ``["inf", 1.5]`` — array recursion via overflow."""
        response = client.post(
            "/api/hello", content=b'{"name": [1e400, 1.5]}', headers=JSON_HEADERS
        )
        assert response.status_code == 422
        assert response.json()["detail"][0]["input"] == ["inf", 1.5], (
            "array-recursion over an overflowed value regressed: the non-finite element "
            "must be stringified and the finite sibling preserved by value and type"
        )

    def test_overflow_inside_nested_dict_is_selectively_stringified(
        self, client: TestClient
    ) -> None:
        """``{"name": {"big": -1e400, "ok": 2}}`` echoes ``{"big": "-inf", "ok": 2}``."""
        response = client.post(
            "/api/hello",
            content=b'{"name": {"big": -1e400, "ok": 2}}',
            headers=JSON_HEADERS,
        )
        assert response.status_code == 422
        assert response.json()["detail"][0]["input"] == {"big": "-inf", "ok": 2}, (
            "dict-recursion over an overflowed value regressed: only the non-finite value "
            "should be stringified; the finite sibling and the keys must survive"
        )


class TestOverflowResponseLeaksNoNonStandardTokens:
    """An overflowed value never leaks a bare ``Infinity`` / ``NaN`` token into the body.

    The whole point of the #328 sanitizer is to keep the 422 body RFC-8259-valid so a
    strict client parser (``JSON.parse``) accepts it. A regression that sanitized the
    *token* path but not the *overflow* path would emit ``{"input": Infinity}`` — a bare,
    non-standard token that ``JSON.parse`` rejects outright. This pins that the raw
    response text carries no un-quoted ``Infinity`` / ``-Infinity`` / ``NaN`` token and
    round-trips through a strict parser.
    """

    @pytest.mark.parametrize(
        "raw_body",
        [b'{"name": 1e400}', b'{"name": -1e400}', b'{"name": [1e400]}'],
        ids=["scalar-pos", "scalar-neg", "nested"],
    )
    def test_response_is_strict_json_with_no_bare_nonfinite_token(
        self, client: TestClient, raw_body: bytes
    ) -> None:
        """The 422 body parses under a strict (``allow_nan=False``) decoder, token-free."""
        response = client.post("/api/hello", content=raw_body, headers=JSON_HEADERS)
        assert response.status_code == 422
        # A leaked token would appear bare (no surrounding quotes); the sanitized form is
        # the quoted string "inf"/"-inf", which contains no Infinity/NaN substring at all.
        assert "Infinity" not in response.text and "NaN" not in response.text, (
            f"response leaked a non-standard bare token: {response.text!r}"
        )
        # A strict decoder rejects the non-standard constants, so a successful parse
        # proves the body is strict RFC-8259 JSON.
        strict_json_loads(response.text)
