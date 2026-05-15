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
