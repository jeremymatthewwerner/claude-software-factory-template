"""Regression pins for the **composition** of the two request-body sanitizers.

``app.main.validation_exception_handler`` never crashes on a malformed body: when
the default handler fails to JSON-encode the echoed ``detail[].input``, it rebuilds
the payload through *both* sanitizers, chained::

    _replace_lone_surrogates(_replace_non_finite(jsonable_encoder(exc.errors())))

Two independent failure modes make ``JSONResponse`` (rendered with
``allow_nan=False`` then ``.encode("utf-8")``) raise:

* a **non-finite float** (``NaN`` / ``Infinity`` / ``-Infinity``) — rejected by the
  strict ``allow_nan=False`` encoder → ``ValueError``; fixed by ``_replace_non_finite``.
* a **lone UTF-16 surrogate** (e.g. ``"\\uD83D"`` with no paired low surrogate) —
  not UTF-8-encodable → ``UnicodeEncodeError``; fixed by ``_replace_lone_surrogates``.

Every existing suite exercises **exactly one** of these at a time:
``test_nonfinite_toplevel_body.py`` / ``test_regression_nonfinite_sanitization.py``
send only non-finite floats; ``test_lone_surrogate_rejection.py`` /
``test_regression_surrogate_object_keys.py`` send only lone surrogates. **None sends
a single body carrying both.**

That leaves the composition unpinned. A regression that, say, ran only the first
sanitizer, short-circuited on the first defect found, or let one sanitizer's output
re-introduce a value the other had already fixed, would 500 on a body holding *both*
a non-finite float and a lone surrogate — while the entire existing single-defect
suite stayed green. Only a payload that requires **both** sanitizers to fire in the
same pass can catch that. This file closes the gap, at both the HTTP boundary and
the pure-function level.
"""

import json
import math
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import _replace_lone_surrogates, _replace_non_finite

from .conftest import JSON_HEADERS, first_error, strict_json_loads

# The three canonical non-finite JSON tokens paired with the ``repr`` string
# ``_replace_non_finite`` rewrites them to. Centralised so the HTTP and unit
# tests below agree on the exact stringification.
NONFINITE_TOKEN_TO_REPR = {"NaN": "nan", "Infinity": "inf", "-Infinity": "-inf"}

# A raw JSON escape for a lone high surrogate (U+D83D, the leading half of the
# 😀 pair) and the ASCII ``backslashreplace`` transcription
# ``_replace_lone_surrogates`` rewrites it to. Reused across the file so a single
# constant documents "this is the lone surrogate we inject and expect back".
LONE_SURROGATE_ESCAPE = "\\uD83D"
LONE_SURROGATE_SANITIZED = "\\ud83d"


def _assert_clean_422(response: Any) -> dict[str, Any]:
    """Assert ``response`` is a 422 whose body is strict-JSON *and* UTF-8 clean.

    Returns ``detail[0]`` for further inspection. This is the crux of the whole
    file: a body that still held a non-finite float would trip the strict
    ``parse_constant`` inside :func:`~tests.conftest.strict_json_loads` (via
    :func:`~tests.conftest.first_error`), and a body that still held a lone
    surrogate would raise ``UnicodeEncodeError`` on ``.encode("utf-8")`` — so both
    survivals are caught here, proving *both* sanitizers ran.
    """
    assert response.status_code == 422, (
        f"a body carrying both a non-finite float and a lone surrogate must yield a "
        f"clean 422, not {response.status_code}: {response.text!r}"
    )
    # No lone surrogate survived: the response text must be UTF-8 encodable.
    response.text.encode("utf-8")
    # No non-finite token survived: strict parse rejects NaN/Infinity.
    return first_error(response.text)


def _assert_no_raw_surrogate(value: Any) -> None:
    """Recursively assert no string in ``value`` holds a raw surrogate code point."""
    if isinstance(value, str):
        assert not any(0xD800 <= ord(ch) <= 0xDFFF for ch in value), (
            f"a raw surrogate code point survived sanitization: {value!r}"
        )
    elif isinstance(value, dict):
        for k, v in value.items():
            _assert_no_raw_surrogate(k)
            _assert_no_raw_surrogate(v)
    elif isinstance(value, list):
        for item in value:
            _assert_no_raw_surrogate(item)


def _assert_no_nonfinite_float(value: Any) -> None:
    """Recursively assert no ``float`` in ``value`` is ``NaN``/``inf``/``-inf``."""
    if isinstance(value, float):
        assert math.isfinite(value), f"a non-finite float survived sanitization: {value!r}"
    elif isinstance(value, dict):
        for v in value.values():
            _assert_no_nonfinite_float(v)
    elif isinstance(value, list):
        for item in value:
            _assert_no_nonfinite_float(item)


class TestBothDefectsInOneRequestBodyYieldCleanResponse:
    """A single body carrying both a non-finite float and a lone surrogate → clean 422.

    These drive the exception handler's ``_replace_lone_surrogates(_replace_non_finite(...))``
    chain with a payload that requires *both* links to fire. Skipping or breaking
    either one leaves a value the strict ``allow_nan=False`` / ``.encode("utf-8")``
    response encoder chokes on — surfacing as a 500 (or an error inside the request,
    since ``TestClient`` re-raises server exceptions), which :func:`_assert_clean_422`
    turns into a loud failure.
    """

    @pytest.mark.parametrize(
        "token,expected_repr",
        list(NONFINITE_TOKEN_TO_REPR.items()),
        ids=list(NONFINITE_TOKEN_TO_REPR),
    )
    def test_top_level_array_root_with_both_defects(
        self, client: TestClient, token: str, expected_repr: str
    ) -> None:
        """Body ``[<non-finite>, "<lone surrogate>"]`` → 422, both values sanitized.

        A top-level JSON array is not a valid ``HelloRequest`` object, so Pydantic
        rejects the whole body and echoes the *array itself* as ``detail[0].input``.
        That echoed list holds both defects at the document root, exercising the
        **list-recursion branch** of both sanitizers on one value.
        """
        body = f'[{token}, "{LONE_SURROGATE_ESCAPE}"]'.encode()
        first = _assert_clean_422(client.post("/api/hello", content=body, headers=JSON_HEADERS))
        echoed = first["input"]
        assert echoed == [expected_repr, LONE_SURROGATE_SANITIZED], (
            f"array-root echoed input drifted to {echoed!r}; expected the non-finite "
            f"stringified to {expected_repr!r} and the surrogate to {LONE_SURROGATE_SANITIZED!r}"
        )

    @pytest.mark.parametrize(
        "token,expected_repr",
        list(NONFINITE_TOKEN_TO_REPR.items()),
        ids=list(NONFINITE_TOKEN_TO_REPR),
    )
    def test_missing_name_object_with_both_defects_in_values(
        self, client: TestClient, token: str, expected_repr: str
    ) -> None:
        """Body ``{"a": <non-finite>, "b": "<surrogate>"}`` (no ``name``) → 422.

        The missing required ``name`` makes Pydantic echo the *whole body dict* as
        ``detail[0].input``, so both defects sit in **dict values** — the branch a
        naive "only walk lists" or "only special-case the name field" sanitizer
        would miss.
        """
        body = f'{{"a": {token}, "b": "{LONE_SURROGATE_ESCAPE}"}}'.encode()
        first = _assert_clean_422(client.post("/api/hello", content=body, headers=JSON_HEADERS))
        echoed = first["input"]
        assert echoed == {"a": expected_repr, "b": LONE_SURROGATE_SANITIZED}, (
            f"missing-name echoed input drifted to {echoed!r}"
        )

    def test_nested_dict_under_name_with_both_defects(self, client: TestClient) -> None:
        """Body ``{"name": {"deep": NaN, "s": "<surrogate>"}}`` → 422, nested sanitized.

        ``name`` expects a ``str``; supplying a nested object makes Pydantic echo
        that object as the field's ``input``, so both defects live one level deep.
        This exercises the sanitizers' recursion into a dict nested *inside* the
        error structure rather than at the document root.
        """
        body = f'{{"name": {{"deep": NaN, "s": "{LONE_SURROGATE_ESCAPE}"}}}}'.encode()
        first = _assert_clean_422(client.post("/api/hello", content=body, headers=JSON_HEADERS))
        echoed = first["input"]
        assert echoed == {"deep": "nan", "s": LONE_SURROGATE_SANITIZED}, (
            f"nested-under-name echoed input drifted to {echoed!r}"
        )

    @pytest.mark.parametrize(
        "token,expected_repr",
        list(NONFINITE_TOKEN_TO_REPR.items()),
        ids=list(NONFINITE_TOKEN_TO_REPR),
    )
    def test_nested_list_under_name_with_both_defects(
        self, client: TestClient, token: str, expected_repr: str
    ) -> None:
        """Body ``{"name": [<non-finite>, "<surrogate>"]}`` → 422, nested list sanitized.

        ``name`` expects a ``str``; supplying a JSON **array** makes Pydantic echo
        that array as the field's ``input``, so both defects live inside a ``list``
        that sits *one level deep* under the error structure — not at the document
        root. The existing combined-defect suite drives the sanitizers' list-recursion
        branch only via a **top-level array root**
        (:meth:`test_top_level_array_root_with_both_defects`) and its nested case
        (:meth:`test_nested_dict_under_name_with_both_defects`) recurses through a
        **dict**, never a nested list. A regression that walked lists only at the
        document root — or special-cased the root container's type — would 500 here
        while every existing test stayed green. This pins the one uncovered shape:
        both sanitizers recursing through a list nested beneath a field.
        """
        body = f'{{"name": [{token}, "{LONE_SURROGATE_ESCAPE}"]}}'.encode()
        first = _assert_clean_422(client.post("/api/hello", content=body, headers=JSON_HEADERS))
        assert first["loc"] == ["body", "name"], (
            f"echoed error should locate the offending list at body.name, got {first['loc']!r}"
        )
        echoed = first["input"]
        assert echoed == [expected_repr, LONE_SURROGATE_SANITIZED], (
            f"nested-list-under-name echoed input drifted to {echoed!r}; expected the "
            f"non-finite stringified to {expected_repr!r} and the surrogate to "
            f"{LONE_SURROGATE_SANITIZED!r}"
        )

    def test_lone_surrogate_in_object_key_alongside_nonfinite_value(
        self, client: TestClient
    ) -> None:
        """Body ``{"<surrogate>": Infinity}`` (no ``name``) → 422, key *and* value sanitized.

        A lone surrogate can appear in a JSON object **key**, and the whole dict is
        echoed as the missing-``name`` error's ``input``. This is the one shape that
        needs ``_replace_lone_surrogates`` on a dict *key* and ``_replace_non_finite``
        on the paired *value* simultaneously — an un-sanitized key alone would
        re-trigger the encode crash.
        """
        body = f'{{"{LONE_SURROGATE_ESCAPE}": Infinity}}'.encode()
        first = _assert_clean_422(client.post("/api/hello", content=body, headers=JSON_HEADERS))
        echoed = first["input"]
        assert echoed == {LONE_SURROGATE_SANITIZED: "inf"}, (
            f"surrogate-key + non-finite-value echoed input drifted to {echoed!r}"
        )


class TestSanitizerCompositionIsSerializable:
    """Pure-function pins on ``_replace_lone_surrogates ∘ _replace_non_finite``.

    These bypass HTTP and assert the invariant the exception handler relies on
    directly: after both sanitizers run, the value survives the exact encoding
    ``JSONResponse`` performs — ``json.dumps(..., allow_nan=False,
    ensure_ascii=False).encode("utf-8")``. A single payload holding both defect
    kinds is fed through the same chain the handler uses.
    """

    def _mixed_payload(self) -> dict[str, Any]:
        """A structure holding both defect kinds at several nesting depths."""
        return {
            "scalar_nan": float("nan"),
            "scalar_surrogate": "\ud83d",
            "mixed_list": [float("inf"), "\udc00", "plain"],
            "nested": {"neg_inf": float("-inf"), "s": "A\ud83dB"},
            "\udbff": "surrogate key with finite value",
        }

    def test_composition_output_is_json_response_encodable(self) -> None:
        """The chained output serializes exactly as ``JSONResponse`` would, no raise."""
        payload = self._mixed_payload()
        composed = _replace_lone_surrogates(_replace_non_finite(payload))
        # This mirrors Starlette's JSONResponse.render: strict floats, non-ASCII kept,
        # then UTF-8 encoded. Either surviving defect would make one of these raise.
        encoded = json.dumps(composed, allow_nan=False, ensure_ascii=False).encode("utf-8")
        assert encoded, "composed payload encoded to empty bytes"
        # And it must be strict-JSON on the way back in (no NaN/Infinity tokens).
        strict_json_loads(encoded.decode("utf-8"))

    def test_composition_removes_both_defect_kinds(self) -> None:
        """After composition, no non-finite float and no raw surrogate remain."""
        composed = _replace_lone_surrogates(_replace_non_finite(self._mixed_payload()))
        _assert_no_nonfinite_float(composed)
        _assert_no_raw_surrogate(composed)

    def test_composition_is_order_independent(self) -> None:
        """Applying the two sanitizers in either order yields the same result.

        ``_replace_non_finite`` only rewrites ``float`` values (its outputs are
        ASCII ``repr`` strings) and ``_replace_lone_surrogates`` only rewrites
        un-encodable ``str`` values — disjoint domains, so neither can re-introduce
        or clobber the other's fix. Pinning order-independence guards against a
        future change that couples them (e.g. one emitting a value the other would
        then mangle).
        """
        payload = self._mixed_payload()
        surrogate_first = _replace_non_finite(_replace_lone_surrogates(payload))
        nonfinite_first = _replace_lone_surrogates(_replace_non_finite(payload))
        assert surrogate_first == nonfinite_first, (
            "sanitizer order changed the result — the two passes are no longer "
            f"commutative: {surrogate_first!r} != {nonfinite_first!r}"
        )

    def test_composition_does_not_mutate_input(self) -> None:
        """Both sanitizers build new containers; the caller's payload is untouched.

        The handler passes ``jsonable_encoder(exc.errors())`` through the chain and
        must not corrupt the original error objects. Verifying the raw defect values
        still sit in the source structure guards against an in-place-mutation
        refactor that would leave the echoed errors half-sanitized.
        """
        payload = self._mixed_payload()
        _replace_lone_surrogates(_replace_non_finite(payload))
        assert math.isnan(payload["scalar_nan"]), "input NaN was mutated in place"
        assert payload["mixed_list"][0] == float("inf"), "input inf was mutated in place"
        assert payload["scalar_surrogate"] == "\ud83d", "input surrogate was mutated in place"
