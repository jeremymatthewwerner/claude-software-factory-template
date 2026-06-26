"""
Pytest configuration, fixtures, and shared test helpers.
"""

from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.main import app

# Origin used by the local dev frontend; allow-listed by the backend's CORS
# middleware. Centralised here so a port/host change touches one location.
LOCALHOST_ORIGIN = "http://localhost:3000"

# The loopback-IP form of the dev frontend origin — the *second* entry on the
# backend's CORS allow-list. Centralised alongside LOCALHOST_ORIGIN so positive
# CORS tests can exercise both allow-listed origins from one source of truth.
LOOPBACK_ORIGIN = "http://127.0.0.1:3000"

# Origin that is *not* allow-listed by the CORS middleware. Used by negative
# CORS tests to assert that disallowed origins receive no allow-origin header.
DISALLOWED_ORIGIN = "https://evil.example.com"

# Exact greeting template produced by the /api/hello endpoints. Centralised so
# a template change touches a single location instead of every assertion that
# pins the full string.
GREETING_TEMPLATE = "Hello, {name}! Welcome to your Software Factory."

# The canonical (slash-free) GET paths the app serves: ``/health``,
# ``/api/version`` and ``/api/hello``. Centralised as the single source of
# truth for the route list that several suites parametrize over — previously
# each file repeated this literal under its own name (``GET_PATHS``,
# ``CANONICAL_GET_PATHS``, ``ALL_ROUTE_PATHS``), so adding a fourth GET route
# meant hunting down every copy. Import this instead of re-declaring the list.
GET_PATHS = ["/health", "/api/version", "/api/hello"]

# Request headers that mark a body as JSON. Centralised as the single source of
# truth for the ``{"Content-Type": "application/json"}`` dict that body-parsing
# and validation tests attach to ``POST /api/hello`` requests. Previously each
# suite either inlined the literal or re-declared its own module-level constant
# under a divergent name (``JSON_CT`` in some files, ``JSON_HEADERS`` in others),
# so the same idea lived under three spellings. Import this instead. Treat it as
# immutable — when a test needs extra headers, spread it (``{**JSON_HEADERS,
# "Origin": ...}``) rather than mutating it in place.
JSON_HEADERS = {"Content-Type": "application/json"}


@pytest.fixture
def client() -> TestClient:
    """Create a synchronous test client."""
    return TestClient(app)


@pytest.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """Create an async test client for async endpoint testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def expected_greeting(name: str) -> str:
    """Return the exact greeting message the API emits for ``name``.

    Single source of truth for the ``"Hello, {name}! Welcome..."`` template
    that tests pin verbatim. A template change touches one constant instead
    of every assertion that hard-codes the full string.
    """
    return GREETING_TEMPLATE.format(name=name)


def cors_preflight_headers(request_method: str, origin: str = LOCALHOST_ORIGIN) -> dict[str, str]:
    """Return the header dict for a CORS preflight (OPTIONS) request.

    A valid preflight carries both ``Origin`` and
    ``Access-Control-Request-Method``. Centralising the dict construction
    avoids the same two-key literal appearing in dozens of tests.
    """
    return {
        "Origin": origin,
        "Access-Control-Request-Method": request_method,
    }


def get_openapi_schema(client: TestClient) -> dict[str, Any]:
    """Fetch the OpenAPI schema and return it as a parsed dict.

    Centralises the ``client.get("/openapi.json").json()`` idiom that
    appears in dozens of tests, both reducing duplication and giving the
    pattern a name that documents intent at each call site.
    """
    data: dict[str, Any] = client.get("/openapi.json").json()
    return data


def assert_utc_iso8601(timestamp: str) -> datetime:
    """Assert that ``timestamp`` is an ISO 8601 string with a zero UTC offset.

    Returns the parsed datetime so callers can do further ordering checks.
    Raises AssertionError with a contextual message if any check fails.
    """
    parsed = datetime.fromisoformat(timestamp)
    assert parsed.tzinfo is not None, f"Timestamp {timestamp!r} is naive (no timezone)"
    offset = parsed.utcoffset()
    assert offset is not None and offset.total_seconds() == 0, (
        f"Timestamp {timestamp!r} is not UTC (offset={offset})"
    )
    return parsed


def response_timestamp(response: Any) -> datetime:
    """Return the parsed, UTC-validated ``timestamp`` of a JSON response.

    Wraps the ``datetime.fromisoformat(response.json()["timestamp"])`` idiom
    that timestamp-ordering tests repeat verbatim. Beyond removing the
    duplication, routing every extraction through :func:`assert_utc_iso8601`
    means each ordering test now *also* asserts the timestamp is a
    zero-offset UTC ISO 8601 string — strengthening assertions for free.

    The parsed :class:`datetime` is returned so callers can keep doing the
    ordering/window comparisons they did before.
    """
    return assert_utc_iso8601(response.json()["timestamp"])


def name_from_greeting(message: str) -> str:
    """Extract the name from a ``"Hello, {name}! Welcome..."`` message.

    Used by concurrent-POST tests to verify that each response carries back
    the name it was called with. Centralised so the message-template format
    is parsed in exactly one place.
    """
    return message.split("Hello, ", 1)[1].split("!", 1)[0]


def openapi_component_for_response(
    schema: dict[str, Any], path: str, method: str, status: str = "200"
) -> dict[str, Any]:
    """Return the OpenAPI component schema referenced by a route's response.

    Resolves the ``$ref`` for ``schema["paths"][path][method]["responses"]
    [status]["content"]["application/json"]["schema"]`` and returns the
    target component dict. Used to compare documented fields with the
    fields actually emitted by a handler.
    """
    ref = schema["paths"][path][method]["responses"][status]["content"]["application/json"][
        "schema"
    ]["$ref"]
    component_name = ref.rsplit("/", 1)[-1]
    component: dict[str, Any] = schema["components"]["schemas"][component_name]
    return component
