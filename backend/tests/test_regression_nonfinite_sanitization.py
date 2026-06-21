"""Regression pins for the recursive non-finite-float sanitization shipped in #328.

The Saturday edge-cases fix (#328) added ``app.main.validation_exception_handler``
plus the pure helper ``app.main._replace_non_finite`` to stop a JSON body
containing the non-standard constants ``NaN`` / ``Infinity`` / ``-Infinity`` from
crashing the request with a 500 (the rejected non-finite ``float`` was echoed back
inside the 422 ``detail[].input`` field and ``JSONResponse``'s ``allow_nan=False``
encoder choked on it). The helper *recursively* walks the rejected input and
replaces only the non-finite floats with their ``repr`` string, leaving every
other value untouched.

``test_edge_cases_error_paths.py`` pins that fix at the HTTP boundary, but only for
the **top-level** ``{"name": NaN}`` shape. The parts most likely to regress under a
future refactor of the helper — its *recursion* through nested containers and its
*selectivity* (finite values pass through unchanged) — are left unpinned. This file
pins them, both end-to-end through the API and as direct unit tests of the pure
helper:

* **Finite values are never stringified** — the common-case 422 stays byte-identical
  to FastAPI's default (an ``int`` echoes back as an ``int``, not ``"123"``).
* **Recursion through lists and nested dicts** replaces only the non-finite floats
  and preserves sibling finite values, keys, and structure.
* **No bare ``NaN`` / ``Infinity`` token leaks** into the response JSON for a
  *nested* non-finite value, so strict client parsers (``JSON.parse``) accept it.
* **The exact replacement tokens** are ``nan`` / ``inf`` / ``-inf`` (Python's
  ``str(float)`` repr), pinning the wire format the edge-cases suite only checked
  was *a* string.
"""

import json
import math

import pytest
from fastapi.testclient import TestClient

from app.main import _replace_non_finite

JSON_HEADERS = {"Content-Type": "application/json"}


def _strict_json_loads(text: str) -> object:
    """Parse ``text`` rejecting the non-standard ``NaN`` / ``Infinity`` tokens.

    Python's ``json.loads`` accepts those tokens by default (the very leniency that
    caused the original 500). Passing a ``parse_constant`` that raises makes the
    parser strict — equivalent to a browser's ``JSON.parse`` — so any bare
    non-finite token surviving in the response body fails loudly here.
    """

    def _reject(token: str) -> object:
        raise AssertionError(f"response body contains a non-standard JSON token: {token!r}")

    return json.loads(text, parse_constant=_reject)


def _first_error_input(response_text: str) -> object:
    """Return ``detail[0].input`` from a 422 body, parsed strictly."""
    body = _strict_json_loads(response_text)
    assert isinstance(body, dict)
    detail = body["detail"]
    assert isinstance(detail, list) and detail
    return detail[0]["input"]


class TestNonFiniteSanitizationRecursesThroughContainers:
    """The #328 handler recurses into lists/dicts, replacing only non-finite floats.

    Each test drives a real request whose ``name`` field is a *container* holding a
    mix of non-finite and finite values, then asserts the echoed
    ``detail[0].input`` has every ``NaN``/``Infinity`` stringified and every finite
    value preserved with its original JSON type. A regression that flattened the
    helper to handle only the top level (or that broke the list/dict branch) would
    either crash with a 500 again or leak a bare ``NaN`` token — both caught here.
    """

    def test_nan_inside_list_is_selectively_stringified(self, client: TestClient) -> None:
        """``[NaN, 1, Infinity]`` echoes as ``["nan", 1, "inf"]`` — list-recursion branch."""
        response = client.post(
            "/api/hello", content=b'{"name": [NaN, 1, Infinity]}', headers=JSON_HEADERS
        )
        assert response.status_code == 422, (
            f"a list containing non-finite floats must not 500: got {response.status_code}, "
            f"body {response.text!r}"
        )
        assert _first_error_input(response.text) == ["nan", 1, "inf"], (
            "list-recursion regressed: the non-finite floats must be stringified and the "
            "finite int 1 preserved"
        )

    def test_nan_inside_nested_dict_is_selectively_stringified(self, client: TestClient) -> None:
        """``{"x": NaN, "y": 2}`` echoes as ``{"x": "nan", "y": 2}`` — dict-recursion branch."""
        response = client.post(
            "/api/hello", content=b'{"name": {"x": NaN, "y": 2}}', headers=JSON_HEADERS
        )
        assert response.status_code == 422
        assert _first_error_input(response.text) == {"x": "nan", "y": 2}, (
            "dict-recursion regressed: only the non-finite value should be stringified; the "
            "key 'y' and finite value 2 must survive unchanged"
        )

    def test_deeply_nested_alternating_containers_are_walked(self, client: TestClient) -> None:
        """``{"a": [{"b": -Infinity}]}`` echoes as ``{"a": [{"b": "-inf"}]}``.

        Exercises dict→list→dict alternation in a single payload — the recursion must
        descend through both container types, not just one level of each.
        """
        response = client.post(
            "/api/hello",
            content=b'{"name": {"a": [{"b": -Infinity}]}}',
            headers=JSON_HEADERS,
        )
        assert response.status_code == 422
        assert _first_error_input(response.text) == {"a": [{"b": "-inf"}]}, (
            "deep alternating-container recursion regressed — the handler stopped "
            "descending through mixed dict/list nesting"
        )

    def test_nested_non_finite_does_not_leak_a_bare_token(self, client: TestClient) -> None:
        """A *nested* non-finite value leaves no bare ``NaN``/``Infinity`` in the body.

        The edge-cases suite pins this only for the top-level ``{"name": NaN}`` case.
        A regression that broke recursion would 500 (or, if it half-worked, emit a
        bare nested token) — ``_strict_json_loads`` rejects any such token, so a
        clean parse here proves the whole nested body is RFC-8259-valid JSON.
        """
        response = client.post(
            "/api/hello",
            content=b'{"name": {"deep": [NaN, Infinity, -Infinity]}}',
            headers=JSON_HEADERS,
        )
        assert response.status_code == 422
        # Raises if any bare NaN/Infinity/-Infinity token survived anywhere in the body.
        parsed = _strict_json_loads(response.text)
        assert isinstance(parsed, dict) and "detail" in parsed


class TestFiniteValuesAreNeverStringified:
    """The common-case 422 stays byte-identical to FastAPI's default handler.

    The handler delegates to ``request_validation_exception_handler`` and only
    sanitizes when the default would crash on a non-finite float. So a validation
    error whose echoed input is *finite* must round-trip with its original JSON type
    — an ``int`` stays an ``int``, a finite ``float`` stays a ``float`` — never
    stringified. This pins that the fix did not broaden sanitization to finite
    values (which would silently change the ``input`` type every SDK error model
    branches on).
    """

    def test_finite_int_input_is_not_stringified(self, client: TestClient) -> None:
        """``{"name": 123}`` echoes ``input`` as the int ``123`` — not ``"123"``."""
        response = client.post("/api/hello", content=b'{"name": 123}', headers=JSON_HEADERS)
        assert response.status_code == 422
        value = _first_error_input(response.text)
        assert value == 123 and isinstance(value, int) and not isinstance(value, bool), (
            f"finite int input was altered to {value!r} — the common-case 422 must stay "
            f"byte-identical to FastAPI's default (no stringification)"
        )

    def test_finite_float_input_is_not_stringified(self, client: TestClient) -> None:
        """``{"name": 1.5}`` echoes ``input`` as the float ``1.5`` — not ``"1.5"``."""
        response = client.post("/api/hello", content=b'{"name": 1.5}', headers=JSON_HEADERS)
        assert response.status_code == 422
        value = _first_error_input(response.text)
        assert value == 1.5 and isinstance(value, float), (
            f"finite float input was altered to {value!r} — only non-finite floats may be "
            f"stringified"
        )


class TestReplaceNonFiniteHelperContract:
    """Direct unit pins on the pure ``_replace_non_finite`` recursion.

    The HTTP-level tests above prove the *observable* contract; these pin the
    helper's contract directly so a refactor of the function body (e.g. switching to
    an iterative walk, or special-casing only ``dict``) is caught at the unit it
    actually changed. The function must: stringify exactly the non-finite floats,
    preserve everything else by value *and* type, and recurse through arbitrarily
    nested ``dict``/``list`` structures without mutating the input.
    """

    @pytest.mark.parametrize(
        "value,expected",
        [
            (float("nan"), "nan"),
            (float("inf"), "inf"),
            (float("-inf"), "-inf"),
        ],
        ids=["nan", "inf", "-inf"],
    )
    def test_scalar_non_finite_becomes_its_repr_string(self, value: float, expected: str) -> None:
        """A bare non-finite float is replaced by ``str(value)`` (``nan``/``inf``/``-inf``)."""
        assert _replace_non_finite(value) == expected

    @pytest.mark.parametrize(
        "value",
        [0, 1, -1, 123, 1.5, -3.14, 0.0, "text", "nan", True, False, None],
        ids=[
            "zero-int",
            "one",
            "neg-one",
            "int",
            "float",
            "neg-float",
            "zero-float",
            "str",
            "str-nan-literal",
            "true",
            "false",
            "none",
        ],
    )
    def test_finite_and_non_float_values_pass_through_unchanged(self, value: object) -> None:
        """Every finite/non-float scalar is returned identically (by value and type)."""
        result = _replace_non_finite(value)
        assert result == value and type(result) is type(value), (
            f"{value!r} ({type(value).__name__}) was altered to {result!r} "
            f"({type(result).__name__}) — only non-finite floats may change"
        )
        # Belt-and-braces: the only floats that change are the non-finite ones.
        if isinstance(value, float):
            assert math.isfinite(value)

    def test_recursion_replaces_only_non_finite_in_mixed_structure(self) -> None:
        """A deeply nested mix keeps structure/finite values and stringifies non-finite floats."""
        payload = {
            "a": [1, float("nan"), {"b": float("inf"), "c": 2}],
            "d": "keep",
            "e": [[float("-inf")], 3.5],
        }
        assert _replace_non_finite(payload) == {
            "a": [1, "nan", {"b": "inf", "c": 2}],
            "d": "keep",
            "e": [["-inf"], 3.5],
        }

    def test_helper_does_not_mutate_its_input(self) -> None:
        """The walk builds new containers — the caller's input dict/list is untouched.

        ``validation_exception_handler`` passes ``jsonable_encoder(exc.errors())`` in,
        but pinning purity guards a future caller that reuses the input afterwards
        (e.g. for logging) and would be surprised by in-place mutation.
        """
        inner = [float("nan"), 1]
        original = {"x": inner}
        result = _replace_non_finite(original)
        assert result == {"x": ["nan", 1]}
        # Inputs unchanged: the nan is still a float, the list object is the same one.
        assert math.isnan(original["x"][0]) and original["x"][1] == 1
        assert original["x"] is inner
