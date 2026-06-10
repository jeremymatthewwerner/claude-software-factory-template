"""
Request-body contract gap tests (Wednesday QA focus: integration-gaps).

Line/branch coverage for ``app/main.py`` is already at 100% and the POST body
contract is exhaustively pinned elsewhere: ``requestBody.required: true``
(``test_route_operation_metadata.py``), the ``422`` response in OpenAPI and the
``name`` field being required (``test_integration.py``). The *inverse* contract
— what GET routes must **not** declare, and how the app treats a body that a
client wrongly attaches to a GET — has no test. Two real integrations were
confirmed empirically over both the in-process ``TestClient`` and the real-ASGI
``AsyncClient`` transport before these tests were written:

1. **GET routes declare no request body and no validation error.** Every
   ``@app.get(...)`` handler takes no body parameters, so its OpenAPI operation
   carries neither a ``requestBody`` nor a ``422`` response — only the lone
   ``POST /api/hello`` does. Nothing pins this asymmetry. A regression that
   added a validated query parameter (or a body model) to a GET route would
   inject a ``422``/``requestBody`` into that route's schema and silently change
   every generated SDK, with no existing test failing.

2. **GET ignores an attached request body.** Clients, intermediary proxies, and
   replayed/retried requests sometimes attach a body to a GET. Because the GET
   handlers bind no body, Starlette never reads it: the request returns ``200``
   with the canonical payload, the body is neither validated against
   ``HelloRequest`` nor echoed back. A regression that wired body parsing onto a
   GET handler — or a middleware that rejected GET bodies with a ``400`` — would
   go entirely uncaught today.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

from tests.conftest import (
    assert_utc_iso8601,
    expected_greeting,
    get_openapi_schema,
)

# Canonical (slash-free) GET paths the app serves. Each takes no request body,
# so none may declare a requestBody or a 422 in its OpenAPI operation.
GET_PATHS = ["/health", "/api/version", "/api/hello"]

# The documented top-level JSON key unique to each GET route's success payload.
# Used to prove the handler ran normally even when a stray body is attached.
GET_PATH_MARKER_KEY = {
    "/health": "status",
    "/api/version": "version",
    "/api/hello": "message",
}

# A body that is *valid* for POST /api/hello but meaningless to a GET. Attaching
# it to a GET must not turn the GET into a greeting endpoint.
VALID_POST_BODY = {"name": "Ada"}

# A body that would be *rejected* (422) by POST /api/hello's HelloRequest model.
# Attaching it to a GET must still yield 200 — proof the GET never validates it.
POST_INVALID_BODY = {"name": 123}


class TestGetRoutesDeclareNoBodyContract:
    """Every GET operation in OpenAPI omits both ``requestBody`` and ``422``.

    This is the inverse of the well-pinned POST contract. FastAPI only emits a
    ``requestBody`` for a handler that binds a Pydantic body, and only attaches a
    ``422`` response to operations that can raise ``RequestValidationError`` —
    which, for this app, is exactly the single ``POST /api/hello``. Pinning the
    inverse turns "a GET grew a validated parameter" from a silent SDK-shape
    drift into a failing test.
    """

    @pytest.mark.parametrize("path", GET_PATHS)
    def test_get_operation_declares_no_request_body(self, client: TestClient, path: str) -> None:
        """``GET <path>`` carries no ``requestBody`` key in its OpenAPI operation."""
        schema = get_openapi_schema(client)
        operation = schema["paths"][path]["get"]
        assert "requestBody" not in operation, (
            f"GET {path} unexpectedly declares a requestBody in OpenAPI: "
            f"{operation.get('requestBody')!r}. A body-bearing GET breaks every "
            f"generated SDK — pin it deliberately or revert."
        )

    @pytest.mark.parametrize("path", GET_PATHS)
    def test_get_operation_declares_no_422_response(self, client: TestClient, path: str) -> None:
        """``GET <path>`` declares no ``422`` response (it validates no input)."""
        schema = get_openapi_schema(client)
        responses = schema["paths"][path]["get"]["responses"]
        assert "422" not in responses, (
            f"GET {path} now declares a 422 response in OpenAPI; got "
            f"{list(responses)}. That means a validated parameter was added to a "
            f"GET — confirm intent and update the request-body contract pins."
        )

    def test_post_hello_is_the_sole_body_bearing_operation(self, client: TestClient) -> None:
        """Exactly one operation across the whole schema declares a ``requestBody``.

        Guards against a *new* body-bearing route (GET or otherwise) slipping in
        unnoticed: if a second ``requestBody`` appears, this fails and forces the
        change to be acknowledged here.
        """
        schema = get_openapi_schema(client)
        body_bearing = {
            (method.upper(), path)
            for path, methods in schema["paths"].items()
            for method, operation in methods.items()
            if "requestBody" in operation
        }
        assert body_bearing == {("POST", "/api/hello")}, (
            f"Exactly one body-bearing operation (POST /api/hello) is expected; "
            f"got {body_bearing}. A new requestBody appeared — pin it."
        )


class TestGetRequestsIgnoreAttachedBody:
    """A body attached to a GET is ignored: the route returns its normal 200.

    The GET handlers bind no body parameter, so Starlette never reads the request
    stream. A client/proxy that wrongly attaches a body must still receive the
    canonical payload — not a 400, not a 422, not a 5xx. These tests send a real
    JSON body on each GET and assert the response is byte-for-byte the contract
    the body-less call already guarantees.
    """

    @pytest.mark.parametrize("path", GET_PATHS)
    def test_get_with_attached_body_returns_200_with_canonical_shape(
        self, client: TestClient, path: str
    ) -> None:
        """``GET <path>`` + a JSON body returns 200 and the route's documented key."""
        response = client.request(
            "GET",
            path,
            content=json.dumps(VALID_POST_BODY),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200, (
            f"GET {path} with an attached body should be ignored and return 200; "
            f"got {response.status_code}. Did a handler start binding the body?"
        )
        assert GET_PATH_MARKER_KEY[path] in response.json(), (
            f"GET {path} with a body returned a payload missing its marker key "
            f"{GET_PATH_MARKER_KEY[path]!r}: {response.json()!r}"
        )

    def test_get_hello_with_body_does_not_become_a_greeting(self, client: TestClient) -> None:
        """A ``{"name": ...}`` body on ``GET /api/hello`` does not personalise the message.

        ``GET /api/hello`` returns the static welcome string; only ``POST`` reads
        ``name``. If the GET ever started honouring the body, this would surface
        as the personalised greeting and fail here.
        """
        response = client.request(
            "GET",
            "/api/hello",
            content=json.dumps(VALID_POST_BODY),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200
        message = response.json()["message"]
        assert message != expected_greeting(VALID_POST_BODY["name"]), (
            "GET /api/hello honoured the attached body and personalised the "
            f"greeting ({message!r}) — GET must ignore the body."
        )
        assert VALID_POST_BODY["name"] not in message, (
            f"GET /api/hello leaked the attached body's name into the response: {message!r}"
        )

    def test_get_hello_does_not_validate_attached_body(self, client: TestClient) -> None:
        """A body that POST would reject (422) is silently ignored by GET.

        ``{"name": 123}`` violates ``HelloRequest`` (name must be a string), so
        ``POST /api/hello`` answers 422. The same payload on ``GET /api/hello``
        must still be 200 — proving the GET path never feeds the body through
        ``HelloRequest`` validation.
        """
        get_response = client.request(
            "GET",
            "/api/hello",
            content=json.dumps(POST_INVALID_BODY),
            headers={"Content-Type": "application/json"},
        )
        assert get_response.status_code == 200, (
            f"GET /api/hello validated an attached body (got {get_response.status_code}); "
            f"it must ignore the body entirely."
        )
        # Contrast: the very same body is a 422 on POST. Pinned inline so the
        # asymmetry that motivates this test is self-evident.
        post_response = client.post("/api/hello", json=POST_INVALID_BODY)
        assert post_response.status_code == 422, (
            f"Sanity check failed: POST /api/hello should reject {POST_INVALID_BODY!r} "
            f"with 422, got {post_response.status_code}"
        )

    @pytest.mark.parametrize("path", GET_PATHS)
    def test_get_with_body_matches_bodiless_response_shape(
        self, client: TestClient, path: str
    ) -> None:
        """Attaching a body does not change the set of JSON keys a GET returns."""
        bodiless = set(client.get(path).json())
        with_body = set(
            client.request(
                "GET",
                path,
                content=json.dumps(VALID_POST_BODY),
                headers={"Content-Type": "application/json"},
            ).json()
        )
        assert bodiless == with_body, (
            f"GET {path} response shape changed when a body was attached: "
            f"bodiless={bodiless}, with_body={with_body}"
        )

    def test_get_with_body_still_emits_valid_utc_timestamp(self, client: TestClient) -> None:
        """The handler runs normally with a stray body — its timestamp is valid UTC ISO 8601.

        A handler that errored or short-circuited on the unexpected body could
        return a malformed/absent timestamp. Reusing the shared UTC assertion
        proves the normal code path executed end-to-end.
        """
        response = client.request(
            "GET",
            "/health",
            content=json.dumps(VALID_POST_BODY),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200
        assert_utc_iso8601(response.json()["timestamp"])


class TestGetWithBodyIgnoredViaAsyncTransport:
    """The GET-ignores-body contract holds over the real-ASGI ``AsyncClient`` too.

    ``TestClient`` is synchronous and built on a portal; ``AsyncClient`` +
    ``ASGITransport`` exercises the genuine async request pipeline. Pinning the
    behaviour on both transports guards against a regression that only manifests
    under real ASGI body handling.
    """

    @pytest.mark.asyncio
    async def test_get_hello_with_body_returns_200_via_async_client(
        self, async_client: AsyncClient
    ) -> None:
        """``GET /api/hello`` + body returns 200 with the static welcome over async ASGI."""
        response = await async_client.request(
            "GET",
            "/api/hello",
            content=json.dumps(VALID_POST_BODY),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200
        message = response.json()["message"]
        assert message != expected_greeting(VALID_POST_BODY["name"]), (
            f"Async GET /api/hello honoured the attached body: {message!r}"
        )

    @pytest.mark.asyncio
    async def test_get_health_with_invalid_body_returns_200_via_async_client(
        self, async_client: AsyncClient
    ) -> None:
        """A POST-invalid body on ``GET /health`` is ignored (200) over async ASGI."""
        response = await async_client.request(
            "GET",
            "/health",
            content=json.dumps(POST_INVALID_BODY),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"
