"""Boundary astral characters must survive the surrogate validator — accept-side of #372.

Fix ``3c81af3`` (#372) added a ``field_validator`` on ``HelloRequest.name`` that
rejects *unpaired* UTF-16 surrogates (a lone ``"\\uD83D"``) to stop a latent 500,
while keeping legal surrogate *pairs* — which decode to real astral-plane
characters — accepted unchanged. The reject-side of that fix is pinned
exhaustively (``test_lone_surrogate_rejection.py``,
``test_regression_surrogate_object_keys.py``,
``test_combined_sanitizer_composition.py``). The **accept-side**, however, is
pinned at a *single* mid-range code point: 😀 / U+1F600, whose UTF-16 pair is
``\\uD83D\\uDE00``.

That leaves the *boundaries* of the valid astral range untested:

* **U+10000** — the first astral scalar (``𐀀``), UTF-16 ``\\uD800\\uDC00``: the
  **minimum** high surrogate paired with the **minimum** low surrogate.
* **U+10FFFF** — the last valid Unicode scalar (``\U0010ffff``), UTF-16
  ``\\uDBFF\\uDFFF``: the **maximum** high surrogate paired with the **maximum**
  low surrogate.

These two pairs occupy the extreme corners of the surrogate code-unit block.
U+10FFFF in particular is the **maximum** valid Unicode scalar — a boundary the
mid-range 😀 test can never reach. Pinning the extremes guards against a validator
narrowed to a sub-range of valid text: e.g. one that keyed off the *UTF-16*
representation and rejected anything needing a surrogate pair (which flags every
astral scalar), or one clamped below U+10FFFF. The validator keys off UTF-8
*encodability* — a correctly decoded surrogate *pair* is a single non-surrogate
scalar that always encodes — so these must all pass; the boundary cases assert
the accept-side holds all the way out to the last valid code point.

These tests pin that end-to-end at the boundaries, in both the JSON ``\\uXXXX``
escape form (exercising surrogate-pair decoding at the min/max code units) and
the raw-UTF-8-bytes form, and assert the 200 body is itself UTF-8-clean and
echoes the exact character. A companion class re-pins the stable client-facing
*rejection* contract so the accept/reject split of #372 cannot silently move.

The ``client`` fixture raises on server exceptions, so any regression back to a
500 (or a wrongful 422) surfaces as a loud failure rather than a silent pass.
"""

import pytest
from fastapi.testclient import TestClient

from .conftest import JSON_HEADERS, expected_greeting

# The boundary astral scalars and their UTF-16 surrogate-pair escapes. Each entry
# is (label, python_char, json_escape_body). The escapes deliberately use the
# extreme surrogate code units so a range-based over-rejection is caught:
#   U+10000  -> \uD800 (min high) + \uDC00 (min low)
#   U+10FFFF -> \uDBFF (max high) + \uDFFF (max low)
_BOUNDARY_ASTRALS = [
    ("U+10000_first_astral", "\U00010000", b'{"name":"\\uD800\\uDC00"}'),
    ("U+10FFFF_last_valid", "\U0010ffff", b'{"name":"\\uDBFF\\uDFFF"}'),
]


class TestBoundaryAstralPairAcceptedViaEscape:
    """A boundary surrogate *pair* sent as a ``\\uXXXX`` escape is accepted (200)."""

    @pytest.mark.parametrize(
        "label,char,body",
        _BOUNDARY_ASTRALS,
        ids=[case[0] for case in _BOUNDARY_ASTRALS],
    )
    def test_boundary_pair_round_trips_200(
        self, client: TestClient, label: str, char: str, body: bytes
    ) -> None:
        """The escaped boundary pair decodes to its scalar and echoes with 200.

        Python's JSON decoder joins the two surrogate escapes into the single
        astral scalar *before* the validator sees it, so ``name`` holds a normal
        UTF-8-encodable character and the validator (which keys off encodability)
        lets it through. U+10FFFF is the maximum valid Unicode scalar, so this
        pins the accept-side all the way to the top of the range — a validator
        clamped below it, or one rejecting anything represented by a UTF-16
        surrogate pair, would wrongly 422 here.
        """
        response = client.post("/api/hello", content=body, headers=JSON_HEADERS)
        assert response.status_code == 200, (
            f"{label}: a legal boundary surrogate pair must be accepted, got "
            f"{response.status_code}: {response.text!r}"
        )
        assert response.json()["message"] == expected_greeting(char), (
            f"{label}: greeting must echo the decoded scalar {char!r} verbatim"
        )

    @pytest.mark.parametrize(
        "label,char,body",
        _BOUNDARY_ASTRALS,
        ids=[case[0] for case in _BOUNDARY_ASTRALS],
    )
    def test_200_body_bytes_are_utf8_clean(
        self, client: TestClient, label: str, char: str, body: bytes
    ) -> None:
        """The raw 200 response bytes are valid UTF-8 carrying the astral scalar.

        The whole point of #372 was that malformed input never yields a body the
        UTF-8 encoder chokes on. Here the *accepted* boundary char must survive
        the same encode: the emitted bytes must UTF-8-decode and contain the
        literal scalar (proving no lone surrogate leaked into the success path).
        """
        response = client.post("/api/hello", content=body, headers=JSON_HEADERS)
        assert response.status_code == 200
        decoded = response.content.decode("utf-8")  # must not raise
        assert char in decoded, (
            f"{label}: the decoded astral scalar {char!r} is missing from the "
            f"UTF-8 response body {decoded!r}"
        )


class TestBoundaryAstralAcceptedViaRawUtf8:
    """The same boundary scalars sent as raw UTF-8 bytes (not escapes) also 200.

    Guards the other direction of the accept-side: a validator so aggressive it
    rejected any string whose *UTF-16* representation needs a surrogate pair
    would break real astral input even when it never touched a ``\\uXXXX`` escape.
    ``httpx``'s ``json=`` serializes the char as native UTF-8 bytes, so this is
    the path a real client using a JSON library takes.
    """

    @pytest.mark.parametrize(
        "label,char",
        [(case[0], case[1]) for case in _BOUNDARY_ASTRALS],
        ids=[case[0] for case in _BOUNDARY_ASTRALS],
    )
    def test_raw_utf8_boundary_char_round_trips_200(
        self, client: TestClient, label: str, char: str
    ) -> None:
        """A raw-UTF-8 boundary astral scalar is accepted and echoed (200)."""
        response = client.post("/api/hello", json={"name": char})
        assert response.status_code == 200, (
            f"{label}: raw UTF-8 astral scalar {char!r} must be accepted, got "
            f"{response.status_code}: {response.text!r}"
        )
        assert response.json()["message"] == expected_greeting(char), (
            f"{label}: greeting must echo the raw astral scalar {char!r} verbatim"
        )


class TestLoneSurrogateRejectionContractStable:
    """Re-pin the client-facing *rejection* contract so the accept/reject split holds.

    The accept-side pins above only have teeth if the reject-side stays put: a
    regression could "pass" the boundary-accept tests by disabling the validator
    entirely. This class pins the exact client-facing contract a UI relies on to
    render an inline "invalid text" hint — discriminator, error location, and the
    human-readable message — for a genuinely unpaired surrogate. Together the two
    sides fence the validator's behaviour on both ends.
    """

    def test_unpaired_surrogate_still_rejected_with_stable_contract(
        self, client: TestClient
    ) -> None:
        """A lone ``\\uD83D`` yields 422 with ``value_error`` at ``['body','name']``.

        The message is pinned verbatim because it is a client-facing string
        (shown under the ``name`` input); a drift to a generic Pydantic message
        or a reworded validator would silently change what users see.
        """
        response = client.post("/api/hello", content=b'{"name":"\\uD83D"}', headers=JSON_HEADERS)
        assert response.status_code == 422, (
            f"a lone high surrogate must still be rejected, got {response.status_code}: "
            f"{response.text!r}"
        )
        error = response.json()["detail"][0]
        assert error["type"] == "value_error", (
            f"rejection discriminator drifted to {error['type']!r}; clients branch on "
            "'value_error' to show a text-validity hint"
        )
        assert error["loc"] == ["body", "name"], (
            f"rejection loc drifted to {error['loc']!r}; clients map it back to 'name'"
        )
        assert error["msg"] == (
            "Value error, name contains an unpaired UTF-16 surrogate code point, "
            "which is not valid Unicode text"
        ), f"client-facing rejection message drifted to {error['msg']!r}"

    def test_rejection_message_does_not_leak_the_offending_value(self, client: TestClient) -> None:
        """The ``msg`` is static — it must not interpolate the un-encodable input.

        If a future "improvement" spliced the offending value into the message
        (e.g. ``f"'{value}' is invalid"``), the ``msg`` field would itself carry a
        lone surrogate and re-introduce the exact ``UnicodeEncodeError`` #372
        fixed — just through ``msg`` instead of ``input``. Pinning that no raw
        surrogate code point appears anywhere in the message keeps that door shut.
        """
        response = client.post("/api/hello", content=b'{"name":"\\uD83D"}', headers=JSON_HEADERS)
        assert response.status_code == 422
        msg = response.json()["detail"][0]["msg"]
        assert not any(0xD800 <= ord(ch) <= 0xDFFF for ch in msg), (
            f"rejection message leaked a raw surrogate code point: {msg!r}"
        )
