"""Lone surrogates in JSON **object keys** must not crash the server.

Fix #372 (``3c81af3``) eliminated a ``500`` on request bodies carrying an
unpaired UTF-16 surrogate (``"\\uD83D"`` with no paired low surrogate): such a
string cannot be UTF-8-encoded, so echoing it back inside a 422
``detail[].input`` field crashed ``JSONResponse``. That fix guarded two spots —
``HelloRequest``'s ``field_validator`` (for the ``name`` *value*) and
``_replace_lone_surrogates`` (which sanitized surrogate strings in the echoed
error payload).

But ``_replace_lone_surrogates`` originally recursed into dict **values** while
rebuilding dict **keys** untouched (``{k: _replace_lone_surrogates(v) ...}``).
A lone surrogate can also arrive as a JSON object **key** — e.g. a
``{"\\uD83D": "x"}`` body with no ``name`` field. Pydantic reports a ``missing``
error whose ``input`` is the *whole body dict*, surrogate key and all; JSON
object keys are UTF-8-encoded exactly like values, so the un-sanitized key
re-triggered the same ``UnicodeEncodeError`` → ``500``. This is the identical
DoS-shaped defect #372 set out to fix, reached through the key path.

The fix sanitizes keys as well as values. These tests pin the end-to-end HTTP
contract (never a ``5xx``; always a well-formed, UTF-8-encodable 422) and the
pure-function key-sanitization behaviour, so the regression cannot silently
return.

The ``client`` fixture raises on server exceptions, so any regression back to
the ``500`` surfaces as a loud test error rather than a silent pass.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import _replace_lone_surrogates

from .conftest import JSON_HEADERS

# A representative unpaired high surrogate escape, used as a JSON object *key*.
# ``\uD83D`` is the high half of the 😀 pair; alone it is not valid Unicode
# text and cannot be UTF-8-encoded.
_LONE_HIGH = "\ud83d"


class TestLoneSurrogateInObjectKeyReturns422:
    """A lone surrogate in a JSON object key yields a clean 422, never a 5xx."""

    @pytest.mark.parametrize(
        "raw_body,why",
        [
            (
                b'{"\\uD83D":"x"}',
                "lone surrogate is the only (extra) key; name missing",
            ),
            (
                b'{"name":123,"\\uDC00":"y"}',
                "name present but wrong type; lone-surrogate key alongside",
            ),
            (
                b'{"nested":{"\\uD83D":1},"name":5}',
                "lone-surrogate key nested one level deep; name wrong type",
            ),
            (
                b'{"\\uD800":"a","\\uDFFF":"b"}',
                "two distinct lone-surrogate keys, name missing",
            ),
        ],
        ids=["extra_key_missing_name", "wrong_type_sibling", "nested_key", "two_keys"],
    )
    def test_surrogate_key_returns_422(self, client: TestClient, raw_body: bytes, why: str) -> None:
        """A body with a lone-surrogate object key returns 422, not 500.

        Before the fix, the un-sanitized surrogate key was echoed into
        ``detail[].input`` and crashed ``JSONResponse`` on UTF-8 encode. The
        ``client`` fixture raises on server exceptions, so a regression would
        error the request out here rather than pass silently.
        """
        response = client.post("/api/hello", content=raw_body, headers=JSON_HEADERS)
        assert response.status_code == 422, (
            f"{why}: expected 422, got {response.status_code} — a surrogate in "
            "an object key must not crash response serialization"
        )
        assert response.json()["detail"], f"{why}: 422 detail list must be non-empty"

    def test_422_body_is_utf8_encodable_and_wellformed(self, client: TestClient) -> None:
        """The 422 payload from a surrogate-key body is valid, re-parseable JSON.

        The crux of the regression: the response bytes must round-trip through
        UTF-8 + JSON. If any lone surrogate survived into the payload, either
        ``response.content`` would never have been produced (500) or it would
        not be UTF-8-decodable here.
        """
        response = client.post("/api/hello", content=b'{"\\uD83D":"x"}', headers=JSON_HEADERS)
        assert response.status_code == 422
        # Raw bytes must be valid UTF-8 (this is what JSONResponse emits).
        decoded = response.content.decode("utf-8")
        # And valid JSON with the standard FastAPI error envelope.
        parsed = json.loads(decoded)
        assert isinstance(parsed["detail"], list) and parsed["detail"]

    def test_surrogate_key_never_500(self, client: TestClient) -> None:
        """Explicit guard: the status is never in the 5xx range."""
        response = client.post("/api/hello", content=b'{"\\uD83D":"x"}', headers=JSON_HEADERS)
        assert response.status_code < 500, "malformed client input must never 5xx"


class TestReplaceLoneSurrogatesSanitizesKeys:
    """Unit pins on ``_replace_lone_surrogates`` handling of dict keys."""

    def test_lone_surrogate_key_is_transcribed(self) -> None:
        """A dict key holding a lone surrogate is replaced with a UTF-8-safe form."""
        out = _replace_lone_surrogates({_LONE_HIGH: "v"})
        assert list(out.keys()) == ["\\ud83d"], "key should be backslash-transcribed"
        assert out["\\ud83d"] == "v", "value under the sanitized key is preserved"

    def test_sanitized_key_is_utf8_encodable(self) -> None:
        """Every key in the sanitized dict can be UTF-8-encoded (the whole point)."""
        out = _replace_lone_surrogates({_LONE_HIGH: 1, "ok": 2})
        for key in out:
            key.encode("utf-8")  # must not raise

    def test_nested_surrogate_key_is_transcribed(self) -> None:
        """Surrogate keys nested inside dict values are sanitized recursively."""
        out = _replace_lone_surrogates({"outer": {_LONE_HIGH: [{_LONE_HIGH: "z"}]}})
        assert "\\ud83d" in out["outer"]
        assert "\\ud83d" in out["outer"]["\\ud83d"][0]

    def test_valid_keys_pass_through_unchanged(self) -> None:
        """Ordinary keys — including legal astral characters — are left untouched."""
        original = {"name": 1, "emoji_😀": 2, "café": 3}
        assert _replace_lone_surrogates(original) == original

    def test_non_string_keys_pass_through(self) -> None:
        """A non-string key (defensively) survives sanitization unchanged.

        Bodies decoded from JSON always have string keys, but the sanitizer is
        applied to arbitrary ``jsonable_encoder`` output; a non-string key must
        not be corrupted or raise.
        """
        assert _replace_lone_surrogates({1: "a"}) == {1: "a"}
