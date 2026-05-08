"""
Pytest configuration, fixtures, and shared test helpers.
"""

from collections.abc import AsyncGenerator
from datetime import datetime

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
