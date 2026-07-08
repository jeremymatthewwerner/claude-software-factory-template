"""
CORS-on-sanitized-error-path integration tests (Wednesday QA focus).

Line/branch coverage of ``app/main.py`` is already 100%, so this file targets a
cross-component *integration* the existing suite does not pin.

The validation exception handler (``app/main.py`` ``validation_exception_handler``)
has two distinct code paths:

1. **Default path** — delegates to FastAPI's
   ``request_validation_exception_handler``, whose ``JSONResponse`` is created
   *inside* FastAPI.
2. **Sanitized rebuild path** (``except ValueError``) — the default handler
   raises while JSON-encoding an offending input that cannot be serialized (a
   non-finite ``float`` like ``NaN``/``Infinity`` under ``allow_nan=False``, or a
   string holding a lone UTF-16 surrogate that cannot be UTF-8-encoded). The
   handler catches that and builds a **brand-new** ``JSONResponse(status_code=422,
   ...)`` with the values sanitized.

``TestCORSOnErrorResponses`` (test_integration_gaps.py) pins CORS survival on
404, 405 and a *missing-field* (``json={}``) 422 — all of which travel the
**default** path. Nothing asserts that the CORS middleware still wraps the
**freshly-constructed** ``JSONResponse`` produced by the ``except ValueError``
branch. Because that response is a different object built in different code, a
regression that registered the handler outside the ``CORSMiddleware`` chain, or
that hand-set ``headers=`` on the rebuilt response in a way that clobbered the
middleware's, would strip CORS headers from exactly this path — leaving a
browser unable to read the sanitized validation error while every existing test
stayed green.

Both trigger inputs were confirmed empirically to exercise the rebuild branch:
the sanitized token (``"nan"`` / ``"\\ud83d"``) appears in the echoed
``detail[].input`` field, which only the ``except ValueError`` path produces.
Each test re-asserts that marker so it is *self-validating* — if a future change
routed these inputs through the default path instead, the guard would fail
rather than silently pin the wrong path.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

from tests.conftest import (
    DISALLOWED_ORIGIN,
    JSON_HEADERS,
    LOCALHOST_ORIGIN,
    LOOPBACK_ORIGIN,
)

# A JSON body whose ``name`` is the non-standard token ``NaN``. Python's json
# decoder accepts it as a non-finite ``float``; Pydantic rejects it for the
# ``name: str`` field and echoes the value back, forcing the encoder (and thus
# the rebuild branch) to sanitize the non-finite float to the string ``"nan"``.
NONFINITE_BODY = b'{"name": NaN}'

# A JSON body carrying a lone high surrogate in a key *other* than ``name`` (so
# the ``name`` field-validator never sees it — the value only fails when the
# whole ``{"extra": ...}`` dict is echoed back as the ``missing``-field error's
# ``input`` and the encoder tries to UTF-8-encode the lone surrogate). Encoded
# with ``surrogatepass`` so the lone surrogate survives into the request bytes.
LONE_SURROGATE_BODY = '{"extra": "\ud83d"}'.encode("utf-8", "surrogatepass")

# The sanitized markers each body leaves in the echoed ``detail[].input`` — the
# fingerprint of the ``except ValueError`` rebuild path. ``"nan"`` is the
# ``str(float('nan'))`` form; ``\\ud83d`` is the ``backslashreplace``
# transcription of the lone surrogate.
NONFINITE_MARKER = "nan"
LONE_SURROGATE_MARKER = "\\ud83d"

# The two request bodies paired with the marker that proves the rebuild branch
# ran, so both sanitizer cases share one parametrization.
SANITIZED_BODIES = [
    pytest.param(NONFINITE_BODY, NONFINITE_MARKER, id="non-finite-float"),
    pytest.param(LONE_SURROGATE_BODY, LONE_SURROGATE_MARKER, id="lone-surrogate"),
]


def _assert_rebuild_path(response_text: str, marker: str) -> None:
    """Fail unless the response is a sanitized-rebuild 422 (not the default path)."""
    assert marker in response_text, (
        "expected the sanitized marker in detail[].input — this body must travel "
        f"the except-ValueError rebuild path, got: {response_text!r}"
    )


class TestCORSOnSanitizedErrorPath:
    """CORS headers must survive on the freshly-rebuilt sanitized 422 response."""

    @pytest.mark.parametrize("origin", [LOCALHOST_ORIGIN, LOOPBACK_ORIGIN])
    @pytest.mark.parametrize(("body", "marker"), SANITIZED_BODIES)
    def test_allowlisted_origin_gets_acao_and_vary_on_rebuilt_422(
        self, client: TestClient, origin: str, body: bytes, marker: str
    ) -> None:
        """Each allow-listed origin is echoed (+ ``Vary: Origin``) on the rebuild path."""
        response = client.post(
            "/api/hello", content=body, headers={**JSON_HEADERS, "Origin": origin}
        )
        assert response.status_code == 422
        _assert_rebuild_path(response.text, marker)
        assert response.headers.get("access-control-allow-origin") == origin
        assert response.headers.get("vary") == "Origin"

    @pytest.mark.parametrize(("body", "marker"), SANITIZED_BODIES)
    def test_disallowed_origin_omits_acao_on_rebuilt_422(
        self, client: TestClient, body: bytes, marker: str
    ) -> None:
        """A disallowed origin must not leak an ACAO header off the rebuild path."""
        response = client.post(
            "/api/hello", content=body, headers={**JSON_HEADERS, "Origin": DISALLOWED_ORIGIN}
        )
        assert response.status_code == 422
        _assert_rebuild_path(response.text, marker)
        assert response.headers.get("access-control-allow-origin") is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("body", "marker"), SANITIZED_BODIES)
    async def test_rebuilt_422_carries_cors_over_real_asgi_transport(
        self, async_client: AsyncClient, body: bytes, marker: str
    ) -> None:
        """The rebuild path keeps CORS integration over the real ASGI transport too.

        ``TestClient`` runs the app in-process; ``AsyncClient`` drives the real
        ASGI transport uvicorn uses. Pinning the allow-listed case over both
        rules out a framing regression that only manifests on one transport.
        """
        response = await async_client.post(
            "/api/hello", content=body, headers={**JSON_HEADERS, "Origin": LOCALHOST_ORIGIN}
        )
        assert response.status_code == 422
        _assert_rebuild_path(response.text, marker)
        assert response.headers.get("access-control-allow-origin") == LOCALHOST_ORIGIN
        assert response.headers.get("vary") == "Origin"
