"""Lone-surrogate request-body rejection — the fix for a latent ``500`` defect.

``test_request_body_encoding_edges.py`` originally documented, under
``xfail(strict=True)``, that a JSON body carrying an *unpaired* UTF-16
surrogate escape (``"\\uD83D"`` with no paired low surrogate) crashed the
server with a ``500``: the value decodes into a Python ``str`` holding a lone
surrogate, passes the ``name: str`` annotation, and then fails UTF-8 encoding
when the *response* is serialized — an unhandled ``UnicodeEncodeError``. A
``500`` on parseable client input is a denial-of-service-shaped defect.

The fix has two parts, both pinned here:

1. ``HelloRequest`` rejects unpaired surrogates in a ``field_validator`` so the
   request is turned away with a clean ``422`` *before* the handler builds a
   response it cannot encode. Legal surrogate *pairs* (which decode to real
   astral characters and are UTF-8-encodable) are unaffected.
2. ``app.main._replace_lone_surrogates`` sanitizes any lone surrogate that the
   validation-error payload would otherwise echo back in ``detail[].input`` —
   because that echo would itself re-trigger the same encode failure and turn
   the 422 back into a 500. This mirrors the existing ``_replace_non_finite``
   sanitizer for non-finite floats.

These tests pin the end-to-end HTTP contract (status, discriminator, body
well-formedness, no-regression on pairs) and the pure-function behaviour of
the new sanitizer.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import _replace_lone_surrogates

from .conftest import JSON_HEADERS, expected_greeting


class TestLoneSurrogateBodyReturns422:
    """Every unpaired-surrogate shape yields a clean ``422``, never a ``5xx``."""

    @pytest.mark.parametrize(
        "raw_body,why",
        [
            (b'{"name":"\\uD800"}', "lowest high surrogate (U+D800), alone"),
            (b'{"name":"\\uDBFF"}', "highest high surrogate (U+DBFF), alone"),
            (b'{"name":"\\uDC00"}', "lowest low surrogate (U+DC00), alone"),
            (b'{"name":"\\uDFFF"}', "highest low surrogate (U+DFFF), alone"),
            (b'{"name":"A\\uD83DB"}', "lone high surrogate embedded between ASCII"),
            (b'{"name":"\\uDE00\\uD83D"}', "reversed pair — low then high, never joins"),
        ],
        ids=[
            "high_min",
            "high_max",
            "low_min",
            "low_max",
            "embedded",
            "reversed_pair",
        ],
    )
    def test_unpaired_surrogate_returns_422(
        self, client: TestClient, raw_body: bytes, why: str
    ) -> None:
        """A body with an unpaired surrogate returns 422 with a non-empty detail list.

        ``client`` raises on server exceptions by default, so a regression back
        to the 500 crash would surface as an error in the request itself — this
        test would then error out (not silently pass), which is the intended
        loud signal.
        """
        response = client.post("/api/hello", content=raw_body, headers=JSON_HEADERS)
        assert response.status_code == 422, (
            f"{why}: expected 422, got {response.status_code} — an unpaired "
            f"surrogate must never crash the server: {response.text!r}"
        )
        detail = response.json()["detail"]
        assert isinstance(detail, list) and detail, (
            f"{why}: 422 body must carry a non-empty 'detail' list, got {detail!r}"
        )

    def test_lone_surrogate_discriminator_and_loc(self, client: TestClient) -> None:
        """The rejection is a field ``value_error`` at ``loc==['body','name']``.

        The ``field_validator`` raises ``ValueError``, which Pydantic v2 tags as
        ``type=='value_error'`` on the ``name`` field. Clients that branch on the
        discriminator to render an inline "invalid text" message under the name
        input depend on both the type and the loc; pinning them guards against a
        refactor that moved the check to a different layer (e.g. a body-level
        model validator, which would report ``loc==['body']`` instead).
        """
        response = client.post("/api/hello", content=b'{"name":"\\uD83D"}', headers=JSON_HEADERS)
        assert response.status_code == 422
        error = response.json()["detail"][0]
        assert error["type"] == "value_error", (
            f"lone-surrogate discriminator drifted to {error['type']!r} — clients "
            "branching on 'value_error' to show a text-validity hint would break"
        )
        assert error["loc"] == ["body", "name"], (
            f"lone-surrogate loc drifted to {error['loc']!r} — clients can no "
            "longer map the error back to the 'name' input"
        )

    def test_422_body_is_reparseable_and_input_is_sanitized(self, client: TestClient) -> None:
        """The 422 ``detail[].input`` is a plain ASCII-safe string, not a raw surrogate.

        If the lone surrogate were echoed verbatim, serializing the 422 response
        would hit the *same* ``UnicodeEncodeError`` and 500 all over again. The
        ``_replace_lone_surrogates`` sanitizer rewrites it to its
        ``backslashreplace`` form (``"\\ud83d"``), keeping the whole response
        RFC-8259-valid. Reaching ``response.json()`` at all proves the body
        decoded; we further assert the echoed input is a string carrying no raw
        surrogate code point.
        """
        response = client.post("/api/hello", content=b'{"name":"\\uD83D"}', headers=JSON_HEADERS)
        assert response.status_code == 422
        echoed = response.json()["detail"][0]["input"]
        assert isinstance(echoed, str), f"echoed input should be a string, got {echoed!r}"
        # No raw surrogate code point survived into the echoed value.
        assert not any(0xD800 <= ord(ch) <= 0xDFFF for ch in echoed), (
            f"echoed input still contains a raw surrogate code point: {echoed!r}"
        )


class TestLegalSurrogatePairStillAccepted:
    """The fix must not regress legal surrogate *pairs* — they decode to real
    astral characters that are perfectly valid UTF-8 text.
    """

    def test_surrogate_pair_still_round_trips(self, client: TestClient) -> None:
        """``\\uD83D\\uDE00`` decodes to 😀 (U+1F600) and echoes with 200 — unchanged."""
        response = client.post(
            "/api/hello",
            content=b'{"name":"\\uD83D\\uDE00"}',
            headers=JSON_HEADERS,
        )
        assert response.status_code == 200
        assert response.json()["message"] == expected_greeting("\U0001f600")

    def test_astral_character_sent_as_raw_utf8_still_round_trips(self, client: TestClient) -> None:
        """The same astral char sent as raw UTF-8 bytes (not an escape) still echoes (200).

        Guards against a validator so aggressive it rejected *any* astral-plane
        code point (whose in-memory ``str`` uses surrogate-free code points but
        whose UTF-16 representation would need a pair). The validator keys off
        UTF-8 encodability, so a genuine astral char passes.
        """
        response = client.post("/api/hello", json={"name": "😀"})
        assert response.status_code == 200
        assert response.json()["message"] == expected_greeting("😀")


class TestReplaceLoneSurrogatesUnit:
    """Direct pins on the pure ``_replace_lone_surrogates`` recursion.

    Complements the end-to-end HTTP tests: exercises the branches
    (scalar str, dict-recursion, list-recursion, passthrough) in isolation so a
    refactor of the helper is caught without needing a full request round-trip.
    """

    def test_lone_surrogate_scalar_is_backslash_escaped(self) -> None:
        """A bare lone-surrogate string becomes its ASCII ``backslashreplace`` form."""
        assert _replace_lone_surrogates("\ud83d") == "\\ud83d"

    @pytest.mark.parametrize(
        "value",
        ["", "Alice", "😀", "café", "\t\n", 0, 1, -1, 1.5, True, False, None],
        ids=[
            "empty",
            "ascii",
            "astral",
            "accented",
            "whitespace",
            "int_zero",
            "int_one",
            "int_neg",
            "float",
            "bool_true",
            "bool_false",
            "none",
        ],
    )
    def test_encodable_and_non_string_values_pass_through_unchanged(self, value: object) -> None:
        """Values that are already UTF-8-safe (or not strings) are returned identically."""
        assert _replace_lone_surrogates(value) == value

    def test_nested_dict_and_list_are_recursively_sanitized(self) -> None:
        """A lone surrogate buried in nested containers is rewritten in place."""
        payload = {
            "a": ["ok", "\ud83d", {"b": "\udc00", "c": "fine"}],
            "d": "clean",
        }
        assert _replace_lone_surrogates(payload) == {
            "a": ["ok", "\\ud83d", {"b": "\\udc00", "c": "fine"}],
            "d": "clean",
        }

    def test_input_object_is_not_mutated(self) -> None:
        """Sanitization returns a fresh structure and leaves the original intact."""
        original = {"x": ["\ud83d", "ok"]}
        result = _replace_lone_surrogates(original)
        assert result == {"x": ["\\ud83d", "ok"]}
        # The original still holds the raw lone surrogate.
        assert original["x"][0] == "\ud83d"
