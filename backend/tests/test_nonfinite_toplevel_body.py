"""Regression pins for non-finite-float sanitization at the **top level** of a request body.

The #328 fix (``app.main.validation_exception_handler`` + ``_replace_non_finite``) stops a
JSON body carrying the non-standard tokens ``NaN`` / ``Infinity`` / ``-Infinity`` from crashing
the request with a 500: the rejected non-finite ``float`` is echoed back inside the 422
``detail[].input`` field, and ``JSONResponse``'s ``allow_nan=False`` encoder would otherwise
choke on it. The handler rebuilds the payload with the non-finite floats stringified.

The existing regression suites (``test_regression_nonfinite_sanitization.py``,
``test_numeric_overflow_nonfinite.py``) pin this **only for the ``{"name": <non-finite>}``
object shape** — i.e. the non-finite value nested under a field, with validation ``loc ==
["body", "name"]``. That leaves the **top-level body shape entirely unpinned**:

* ``POST /api/hello`` with body ``NaN`` — the non-finite value *is* ``detail[0].input``
  directly, and the validation error's ``loc`` is just ``["body"]`` (Pydantic rejects the
  whole body because a bare scalar is not a valid ``HelloRequest`` object).
* ``POST /api/hello`` with body ``[NaN]`` / ``[1, NaN, Infinity]`` — a **top-level array** is
  the rejected ``input``, exercising the list-recursion branch at the document root rather
  than nested under a key.

These drive the sanitizer through a *different validation-error shape* than every existing
test: the rejected non-finite value sits at the root of ``detail[0].input`` instead of inside
a dict. A regression that, for example, only walked dict-valued inputs (or special-cased the
``"name"`` field) would 500 on a bare top-level ``NaN`` body while the entire existing suite
stayed green. This file closes that gap.
"""

import pytest
from fastapi.testclient import TestClient

from .conftest import JSON_HEADERS, first_error, strict_json_loads


class TestTopLevelBareNonFiniteBody:
    """A bare top-level non-finite scalar body must yield a clean 422, not a 500.

    Here the *entire* request body is a non-finite token, so Pydantic's rejected ``input`` is
    the non-finite ``float`` itself at the root of ``detail[0]`` (``loc == ["body"]``). This is
    the one place the nested-``{"name": ...}`` suites never reach — the sanitizer has to operate
    on a scalar that is the top-level input, not a value buried inside a container.
    """

    @pytest.mark.parametrize(
        "body,expected",
        [
            (b"NaN", "nan"),
            (b"Infinity", "inf"),
            (b"-Infinity", "-inf"),
        ],
        ids=["nan", "infinity", "neg-infinity"],
    )
    def test_bare_non_finite_body_returns_clean_422(
        self, client: TestClient, body: bytes, expected: str
    ) -> None:
        """``POST /api/hello`` with body ``NaN``/``Infinity``/``-Infinity`` → 422 with stringified input."""
        response = client.post("/api/hello", content=body, headers=JSON_HEADERS)
        assert response.status_code == 422, (
            f"a bare top-level non-finite body must not 500: got {response.status_code}, "
            f"body {response.text!r}"
        )
        error = first_error(response.text)
        assert error["input"] == expected, (
            f"top-level non-finite scalar must be stringified to {expected!r}; "
            f"got input={error['input']!r}"
        )

    def test_bare_non_finite_body_loc_is_body_root(self, client: TestClient) -> None:
        """The validation error for a bare body is anchored at ``["body"]``, not a field.

        This distinguishes the top-level shape from the nested ``{"name": NaN}`` shape (whose
        ``loc`` is ``["body", "name"]``). Pinning ``loc`` documents *why* this case is a
        separate code path: the rejected ``input`` lives at the document root.
        """
        response = client.post("/api/hello", content=b"NaN", headers=JSON_HEADERS)
        assert response.status_code == 422
        error = first_error(response.text)
        assert error["loc"] == ["body"], (
            f"a bare top-level body should fail at loc ['body'], not under a field: "
            f"got loc={error['loc']!r}"
        )


class TestTopLevelNonFiniteArrayBody:
    """A top-level JSON array carrying non-finite floats exercises root-level list recursion.

    Unlike the nested ``{"name": [NaN, ...]}`` case, the array here is the *entire* rejected
    ``input`` — the sanitizer's list branch runs at the document root. Finite siblings must be
    preserved with their JSON type and only the non-finite entries stringified.
    """

    def test_top_level_array_of_non_finite_is_selectively_stringified(
        self, client: TestClient
    ) -> None:
        """``[1, NaN, Infinity]`` echoes as ``[1, "nan", "inf"]`` — finite int 1 preserved."""
        response = client.post("/api/hello", content=b"[1, NaN, Infinity]", headers=JSON_HEADERS)
        assert response.status_code == 422, (
            f"a top-level array with non-finite floats must not 500: got {response.status_code}, "
            f"body {response.text!r}"
        )
        error = first_error(response.text)
        assert error["input"] == [1, "nan", "inf"], (
            "root-level list recursion regressed: only the non-finite floats should be "
            f"stringified and the finite int 1 preserved; got input={error['input']!r}"
        )

    def test_top_level_array_with_nested_container_is_walked(self, client: TestClient) -> None:
        """``[{"k": -Infinity}, NaN]`` echoes as ``[{"k": "-inf"}, "nan"]``.

        Drives dict-inside-top-level-list recursion: the handler must descend into a container
        that is itself an element of the root array, not just stringify the array's scalars.
        """
        response = client.post(
            "/api/hello", content=b'[{"k": -Infinity}, NaN]', headers=JSON_HEADERS
        )
        assert response.status_code == 422
        error = first_error(response.text)
        assert error["input"] == [{"k": "-inf"}, "nan"], (
            "recursion into a container nested inside the root array regressed; "
            f"got input={error['input']!r}"
        )

    def test_top_level_non_finite_leaks_no_bare_token(self, client: TestClient) -> None:
        """A top-level non-finite body leaves no bare ``NaN``/``Infinity`` in the response JSON.

        ``strict_json_loads`` raises on any surviving non-standard token, so a clean parse here
        proves the whole 422 body is RFC-8259-valid JSON even when the offending value sat at the
        document root rather than under a field.
        """
        response = client.post("/api/hello", content=b"[NaN, -Infinity]", headers=JSON_HEADERS)
        assert response.status_code == 422
        parsed = strict_json_loads(response.text)
        assert isinstance(parsed, dict) and "detail" in parsed, (
            f"422 body should be a JSON object with a detail list; got {parsed!r}"
        )
