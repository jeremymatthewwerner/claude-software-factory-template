"""Request-body **byte-encoding** edge-case pins.

``app/main.py`` already sits at 100% line + branch coverage, and
``test_edge_cases.py`` exhaustively pins the HTTP-contract edges that
operate on *already-decoded* JSON (top-level non-object bodies, trailing
garbage, escape-sequence decoding, …). This file pins the layer *below*
that — what happens to the raw request **bytes** before they ever reach
the JSON value parser. Three behaviours are pinned, none of them covered
by any existing test:

1. **Undecodable bytes → 400, not 422.** When the body cannot be decoded
   to text at all (invalid / truncated UTF-8), Starlette short-circuits
   with a ``400`` whose ``detail`` is a bare **string**
   (``"There was an error parsing the body"``). This is a structurally
   different response from the ``422`` ``json_invalid`` case — which fires
   for *decodable* bytes that simply aren't valid JSON and returns a
   ``detail`` **list** of error items (pinned in
   ``TestValidationErrorDiscriminators.test_malformed_json_discriminator_is_json_invalid``).
   A client that branches on the ``detail`` shape to render an error
   depends on this split; nothing pinned it before.

2. **UTF-16 / UTF-32 bodies are auto-detected → 200.** Starlette hands the
   raw bytes to ``json.loads``, which performs RFC 4627 §3 encoding
   detection (BOM or leading-null-byte sniffing) and transparently decodes
   UTF-16 / UTF-32 input. A "tidy-up" regression that pre-decodes with
   ``body.decode("utf-8")`` before parsing would silently start ``400``-ing
   every UTF-16/32 client. These are characterization pins: they record
   what the parser does today so the behaviour can't change unnoticed.

3. **Lone surrogate escape currently 500s.** A ``\\uD83D`` escape with no
   paired low surrogate decodes into a Python ``str`` containing a lone
   surrogate, which then fails UTF-8 re-encoding during *response*
   serialization — an unhandled error surfacing as ``500``. That is a
   latent defect (malformed client input must never crash the server), so
   it is pinned with ``xfail(strict=True)`` asserting the *desired*
   contract (status ``< 500``). The test documents the limitation today
   and will flip to a hard failure (xpass) the moment the crash is fixed,
   prompting removal of the marker.
"""

import pytest
from fastapi.testclient import TestClient

from .conftest import name_from_greeting

JSON_CT = {"Content-Type": "application/json"}


class TestUndecodableBodyBytesReturn400:
    """Bytes that cannot be decoded to text at all yield ``400`` with a
    string ``detail`` — distinct from the ``422``/list ``json_invalid`` path.

    The cases below send byte sequences that are illegal UTF-8 *inside* an
    otherwise well-formed JSON skeleton, so the failure is purely at the
    decode step (not the JSON-grammar step). Each represents a real way a
    misconfigured client mangles its payload: a Latin-1 byte sent without
    transcoding, a multibyte sequence truncated by a buffer boundary, and a
    stray UTF-8 continuation byte.
    """

    @pytest.mark.parametrize(
        "raw_body,why",
        [
            (b'{"name":"\xe9"}', "lone 0xE9 — Latin-1 'e-acute' sent without UTF-8 transcoding"),
            (b'{"name":"\xc3"}', "truncated 2-byte sequence — lead byte 0xC3 with no continuation"),
            (b'{"name":"\x80"}', "stray 0x80 — a UTF-8 continuation byte with no lead byte"),
        ],
        ids=["latin1_e_acute", "truncated_multibyte", "stray_continuation"],
    )
    def test_undecodable_bytes_return_400(
        self, client: TestClient, raw_body: bytes, why: str
    ) -> None:
        """Illegal-UTF-8 body bytes return ``400`` (the body-decode error path).

        Pins that the server distinguishes "I could not even read your
        bytes" (400) from "I read them but they weren't valid JSON" (422).
        A regression that funnelled the decode failure through the same
        422 validation path would change the status code clients see.
        """
        response = client.post("/api/hello", content=raw_body, headers=JSON_CT)
        assert response.status_code == 400, (
            f"undecodable body ({why}) returned {response.status_code} — expected 400 "
            f"(the byte-decode error path, distinct from 422 json_invalid): {response.text}"
        )

    def test_undecodable_body_detail_is_a_bare_string_not_a_list(self, client: TestClient) -> None:
        """The ``400`` body-decode error's ``detail`` is a string, not a list.

        This is the machine-readable half of the contract: the ``422``
        validation path returns ``detail`` as a **list** of ``{loc,msg,type}``
        items (pinned in ``TestValidationErrorDiscriminators``), whereas the
        ``400`` decode path returns ``detail`` as a single human-readable
        **string**. A client that does ``for err in detail`` would iterate
        the characters of the string if these two shapes were ever merged —
        pinning the type split guards against that silent breakage.
        """
        response = client.post("/api/hello", content=b'{"name":"\xe9"}', headers=JSON_CT)
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert isinstance(detail, str) and detail.strip(), (
            f"400 decode-error detail must be a non-empty string (not the 422 list "
            f"shape), got {detail!r}"
        )

    def test_undecodable_body_is_400_while_decodable_garbage_is_422(
        self, client: TestClient
    ) -> None:
        """The 400-vs-422 split is pinned side by side in one test.

        Same endpoint, two malformed bodies: one undecodable (illegal UTF-8
        bytes → 400 / string detail), one decodable-but-not-JSON (valid
        ASCII that isn't JSON → 422 / list detail). Asserting both in a
        single test documents the contrast a client relies on and fails
        loudly if a framework change collapses the two paths into one.
        """
        undecodable = client.post("/api/hello", content=b'{"name":"\xff"}', headers=JSON_CT)
        decodable_garbage = client.post("/api/hello", content=b"not valid json", headers=JSON_CT)
        assert undecodable.status_code == 400
        assert isinstance(undecodable.json()["detail"], str)
        assert decodable_garbage.status_code == 422
        assert isinstance(decodable_garbage.json()["detail"], list)


class TestBodyEncodingAutoDetection:
    """Raw UTF-16 / UTF-32 bodies are transparently decoded by ``json.loads``
    (RFC 4627 §3 encoding detection) and return ``200``.

    Starlette's ``Request.json()`` passes the raw ``bytes`` straight to
    ``json.loads``, which sniffs the encoding from a leading BOM or from the
    null-byte pattern of the first characters. The endpoint therefore
    accepts UTF-16/32 payloads that no client *should* send to a JSON API
    but that some misconfigured stacks (Windows PowerShell's default
    ``Out-File`` UTF-16, certain Java writers) emit anyway.

    These are **characterization** pins, not endorsements: the value is that
    a future "normalise everything to UTF-8 first" refactor —
    ``json.loads(body.decode("utf-8"))`` — would flip every case here from
    ``200`` to ``400``, and that regression would otherwise ship silently
    because the happy-path UTF-8 tests would still pass.
    """

    @pytest.mark.parametrize(
        "encoding,name,why",
        [
            ("utf-16", "Bob", "UTF-16 with BOM (PowerShell Out-File default)"),
            ("utf-32", "Zoe", "UTF-32 with BOM"),
            ("utf-16-be", "Ann", "UTF-16-BE without BOM (sniffed from leading null bytes)"),
        ],
        ids=["utf16_bom", "utf32_bom", "utf16be_no_bom"],
    )
    def test_wide_encoding_body_round_trips(
        self, client: TestClient, encoding: str, name: str, why: str
    ) -> None:
        """A body encoded as ``{encoding}`` is decoded and the name echoed (200)."""
        raw = f'{{"name":"{name}"}}'.encode(encoding)
        response = client.post("/api/hello", content=raw, headers=JSON_CT)
        assert response.status_code == 200, (
            f"{why} returned {response.status_code} — the parser's RFC-4627 encoding "
            f"auto-detection regressed (a switch to utf-8-only pre-decode does this): "
            f"{response.text}"
        )
        assert name_from_greeting(response.json()["message"]) == name


class TestMalformedInputNeverCrashesServer:
    """Malformed client input must never produce a ``5xx``.

    A lone UTF-16 surrogate escape (a high surrogate ``\\uD83D`` with no
    paired low surrogate, or vice versa) is accepted by the JSON *decoder*
    into a Python ``str`` holding an unpaired surrogate. FastAPI then fails
    to UTF-8-encode that surrogate when serializing the *response*, raising
    an unhandled error that surfaces as ``500``.

    This is a latent defect, not a contract: a client should get a ``4xx``
    (its input was bad), never a ``5xx`` (the server fell over). The test
    asserts the desired contract (``status < 500``) under
    ``xfail(strict=True)`` so it:

    * documents the known limitation without pretending the crash is correct,
    * does not redden CI today (reported as xfail), and
    * flips to a hard failure (xpass) the instant the underlying framework
      or a local fix starts returning a proper ``4xx`` — at which point the
      marker should be removed.
    """

    @pytest.mark.xfail(
        reason="Lone surrogate escapes currently 500 on response serialization; "
        "desired contract is a 4xx. Remove this marker once fixed.",
        strict=True,
    )
    @pytest.mark.parametrize(
        "raw_body,which",
        [
            (b'{"name":"\\uD83D"}', "lone high surrogate"),
            (b'{"name":"\\uDE00"}', "lone low surrogate"),
        ],
        ids=["lone_high_surrogate", "lone_low_surrogate"],
    )
    def test_lone_surrogate_escape_does_not_return_5xx(self, raw_body: bytes, which: str) -> None:
        """A {which} escape must not crash the server (no 5xx).

        Uses a client configured with ``raise_server_exceptions=False`` so
        the unhandled error is surfaced as a real ``500`` response rather
        than re-raised into the test, letting the assertion express the
        desired status-code contract directly.
        """
        from app.main import app

        non_raising_client = TestClient(app, raise_server_exceptions=False)
        response = non_raising_client.post("/api/hello", content=raw_body, headers=JSON_CT)
        assert response.status_code < 500, (
            f"{which} produced {response.status_code} — malformed client input must "
            f"never yield a 5xx; expected a 4xx rejection"
        )
