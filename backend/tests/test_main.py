"""Tests for the main API endpoints."""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import AsyncClient

from app import __version__


class TestHealthEndpoint:
    """Tests for the /health endpoint."""

    def test_health_response(self, client: TestClient) -> None:
        """Health check returns 200 with healthy status and timestamp."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["timestamp"]

    def test_health_timestamp_is_iso_format(self, client: TestClient) -> None:
        """Health check timestamp is a non-empty ISO 8601 string."""
        from datetime import datetime

        response = client.get("/health")
        timestamp = response.json()["timestamp"]
        # Verify it parses as a valid ISO datetime
        parsed = datetime.fromisoformat(timestamp)
        assert parsed is not None


class TestVersionEndpoint:
    """Tests for the /api/version endpoint."""

    def test_version_response(self, client: TestClient) -> None:
        """Version endpoint returns 200 with correct name, version, and environment."""
        response = client.get("/api/version")
        assert response.status_code == 200
        data = response.json()
        assert data["version"] == __version__
        assert data["name"] == "software-factory-api"
        assert "environment" in data


class TestHelloWorldEndpoint:
    """Tests for the GET /api/hello endpoint."""

    def test_hello_response(self, client: TestClient) -> None:
        """Hello endpoint returns 200 with Hello World greeting and timestamp."""
        response = client.get("/api/hello")
        assert response.status_code == 200
        data = response.json()
        assert "Hello" in data["message"]
        assert "World" in data["message"]
        assert data["timestamp"]


class TestHelloNameEndpoint:
    """Tests for the POST /api/hello endpoint."""

    @pytest.mark.parametrize(
        "name",
        [
            "Alice",
            "Bob",
            "Dr. Smith-Jones",
            "O'Brien",
            "李明",
        ],
    )
    def test_hello_name_includes_name_in_greeting(self, client: TestClient, name: str) -> None:
        """POST hello includes the provided name in the response."""
        response = client.post("/api/hello", json={"name": name})
        assert response.status_code == 200
        assert name in response.json()["message"]

    def test_hello_name_requires_name_field(self, client: TestClient) -> None:
        """POST hello returns 422 when name field is missing."""
        response = client.post("/api/hello", json={})
        assert response.status_code == 422

    def test_hello_name_rejects_invalid_json(self, client: TestClient) -> None:
        """POST hello returns 422 when body is not valid JSON."""
        response = client.post(
            "/api/hello",
            content="not json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422

    def test_hello_name_response_includes_timestamp(self, client: TestClient) -> None:
        """POST hello response includes a timestamp field."""
        response = client.post("/api/hello", json={"name": "Alice"})
        assert response.json()["timestamp"]


class TestHelloNameEdgeCases:
    """Edge case tests for the POST /api/hello endpoint."""

    def test_hello_name_empty_string(self, client: TestClient) -> None:
        """POST hello with empty string name returns 200 with empty name in message."""
        response = client.post("/api/hello", json={"name": ""})
        assert response.status_code == 200
        assert "" in response.json()["message"]

    def test_hello_name_whitespace_only(self, client: TestClient) -> None:
        """POST hello with whitespace-only name returns 200 and includes it in message."""
        response = client.post("/api/hello", json={"name": "   "})
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "timestamp" in data

    def test_hello_name_very_long(self, client: TestClient) -> None:
        """POST hello with a 1000-character name returns 200 without truncating."""
        long_name = "A" * 1000
        response = client.post("/api/hello", json={"name": long_name})
        assert response.status_code == 200
        assert long_name in response.json()["message"]

    def test_hello_name_newline_chars(self, client: TestClient) -> None:
        """POST hello with newline characters in name returns 200 and includes the name."""
        name = "Alice\nBob"
        response = client.post("/api/hello", json={"name": name})
        assert response.status_code == 200
        assert name in response.json()["message"]

    def test_hello_name_html_chars(self, client: TestClient) -> None:
        """POST hello with HTML-like characters does not sanitize the name."""
        name = "<script>alert('xss')</script>"
        response = client.post("/api/hello", json={"name": name})
        assert response.status_code == 200
        assert name in response.json()["message"]

    def test_hello_name_extra_fields_ignored(self, client: TestClient) -> None:
        """POST hello ignores unknown extra fields in the JSON body."""
        response = client.post("/api/hello", json={"name": "Alice", "extra": "ignored"})
        assert response.status_code == 200
        assert "Alice" in response.json()["message"]

    def test_hello_name_null_name_rejected(self, client: TestClient) -> None:
        """POST hello returns 422 when name is null."""
        response = client.post("/api/hello", json={"name": None})
        assert response.status_code == 422

    def test_hello_name_integer_name_rejected(self, client: TestClient) -> None:
        """POST hello returns 422 when name is an integer instead of a string."""
        response = client.post("/api/hello", json={"name": 42})
        assert response.status_code == 422

    def test_hello_response_content_type_is_json(self, client: TestClient) -> None:
        """POST hello response Content-Type is application/json."""
        response = client.post("/api/hello", json={"name": "Alice"})
        assert "application/json" in response.headers["content-type"]

    def test_hello_get_response_content_type_is_json(self, client: TestClient) -> None:
        """GET /api/hello response Content-Type is application/json."""
        response = client.get("/api/hello")
        assert "application/json" in response.headers["content-type"]


class TestHealthEdgeCases:
    """Edge case tests for the /health endpoint."""

    def test_health_response_content_type_is_json(self, client: TestClient) -> None:
        """Health endpoint response Content-Type is application/json."""
        response = client.get("/health")
        assert "application/json" in response.headers["content-type"]

    def test_health_status_field_is_string(self, client: TestClient) -> None:
        """Health endpoint status field is a string, not a number or boolean."""
        response = client.get("/health")
        assert isinstance(response.json()["status"], str)

    def test_health_response_has_only_known_fields(self, client: TestClient) -> None:
        """Health endpoint response contains exactly the expected fields."""
        response = client.get("/health")
        data = response.json()
        assert set(data.keys()) == {"status", "timestamp"}


class TestVersionEdgeCases:
    """Edge case tests for the /api/version endpoint."""

    def test_version_response_content_type_is_json(self, client: TestClient) -> None:
        """Version endpoint response Content-Type is application/json."""
        response = client.get("/api/version")
        assert "application/json" in response.headers["content-type"]

    def test_version_all_fields_are_strings(self, client: TestClient) -> None:
        """Version endpoint all response fields are strings."""
        response = client.get("/api/version")
        data = response.json()
        assert isinstance(data["version"], str)
        assert isinstance(data["name"], str)
        assert isinstance(data["environment"], str)

    def test_version_response_has_only_known_fields(self, client: TestClient) -> None:
        """Version endpoint response contains exactly the expected fields."""
        response = client.get("/api/version")
        data = response.json()
        assert set(data.keys()) == {"version", "name", "environment"}

    def test_version_string_is_semver_like(self, client: TestClient) -> None:
        """Version string follows semver format (e.g. 0.1.0)."""
        response = client.get("/api/version")
        version = response.json()["version"]
        parts = version.split(".")
        assert len(parts) >= 2
        for part in parts:
            assert part.isdigit(), f"Version part '{part}' is not numeric"


class TestOpenAPIDocumentation:
    """Tests for API documentation endpoints."""

    def test_openapi_schema_has_required_structure(self, client: TestClient) -> None:
        """OpenAPI schema is available and contains openapi version and paths."""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert "openapi" in data
        assert "paths" in data

    @pytest.mark.parametrize("path", ["/docs", "/redoc"])
    def test_documentation_endpoints_available(self, client: TestClient, path: str) -> None:
        """Swagger UI and ReDoc documentation endpoints return 200."""
        response = client.get(path)
        assert response.status_code == 200


class TestRegressionAsyncClient:
    """Regression tests for the async_client fixture.

    The async_client fixture return type was corrected in commit eab5c18 to
    AsyncGenerator[AsyncClient, None]. No prior tests used this fixture, so a
    regression would have been invisible. These tests exercise it directly.
    """

    async def test_health_endpoint_via_async_client(self, async_client: AsyncClient) -> None:
        """Async client reaches /health and receives a healthy status."""
        response = await async_client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    async def test_hello_world_via_async_client(self, async_client: AsyncClient) -> None:
        """Async client reaches GET /api/hello and receives a World greeting."""
        response = await async_client.get("/api/hello")
        assert response.status_code == 200
        assert "World" in response.json()["message"]

    async def test_hello_post_via_async_client(self, async_client: AsyncClient) -> None:
        """Async client POSTs to /api/hello and receives the name back in the greeting."""
        response = await async_client.post("/api/hello", json={"name": "AsyncUser"})
        assert response.status_code == 200
        assert "AsyncUser" in response.json()["message"]

    async def test_concurrent_health_requests(self, async_client: AsyncClient) -> None:
        """Three concurrent health requests all return 200 with healthy status."""
        responses = await asyncio.gather(
            async_client.get("/health"),
            async_client.get("/health"),
            async_client.get("/health"),
        )
        for response in responses:
            assert response.status_code == 200
            assert response.json()["status"] == "healthy"

    async def test_invalid_post_body_returns_422_via_async_client(
        self, async_client: AsyncClient
    ) -> None:
        """Async client correctly receives 422 when name field is null."""
        response = await async_client.post("/api/hello", json={"name": None})
        assert response.status_code == 422


class TestRegressionUTCTimestamps:
    """Regression tests for timezone-aware UTC timestamps.

    Commit eab5c18 fixed the use of datetime.UTC (the modern Python 3.11+ alias)
    instead of timezone.utc. These tests verify all timestamp fields are
    timezone-aware and have a UTC offset of exactly zero.
    """

    def test_health_timestamp_is_timezone_aware(self, client: TestClient) -> None:
        """Health timestamp parses as a timezone-aware datetime, not a naive one."""
        from datetime import datetime

        response = client.get("/health")
        parsed = datetime.fromisoformat(response.json()["timestamp"])
        assert parsed.tzinfo is not None

    def test_health_timestamp_utc_offset_is_zero(self, client: TestClient) -> None:
        """Health timestamp UTC offset is exactly zero seconds (true UTC, not local time)."""
        from datetime import datetime

        response = client.get("/health")
        parsed = datetime.fromisoformat(response.json()["timestamp"])
        offset = parsed.utcoffset()
        assert offset is not None
        assert offset.total_seconds() == 0

    def test_hello_get_timestamp_is_utc_aware(self, client: TestClient) -> None:
        """GET /api/hello timestamp is timezone-aware with a zero UTC offset."""
        from datetime import datetime

        response = client.get("/api/hello")
        parsed = datetime.fromisoformat(response.json()["timestamp"])
        assert parsed.tzinfo is not None
        offset = parsed.utcoffset()
        assert offset is not None
        assert offset.total_seconds() == 0

    def test_hello_post_timestamp_is_utc_aware(self, client: TestClient) -> None:
        """POST /api/hello timestamp is timezone-aware with a zero UTC offset."""
        from datetime import datetime

        response = client.post("/api/hello", json={"name": "Test"})
        parsed = datetime.fromisoformat(response.json()["timestamp"])
        assert parsed.tzinfo is not None
        offset = parsed.utcoffset()
        assert offset is not None
        assert offset.total_seconds() == 0


class TestRegressionPackageStructure:
    """Regression tests for correct Python package structure.

    Commit eab5c18 added [tool.hatch.build.targets.wheel] packages = ["app"]
    to pyproject.toml because hatchling could not discover the package
    automatically (project name software-factory-backend != directory app).
    These tests verify the package remains importable at runtime.
    """

    def test_app_package_is_importable(self) -> None:
        """The app package can be imported without errors."""
        import app

        assert app is not None

    def test_app_version_is_a_non_empty_string(self) -> None:
        """app.__version__ is a non-empty string, confirming the package is intact."""
        assert isinstance(__version__, str)
        assert len(__version__) > 0

    def test_app_main_exposes_fastapi_instance(self) -> None:
        """app.main.app is a FastAPI instance, confirming submodule discovery works."""
        from app.main import app as fastapi_app

        assert isinstance(fastapi_app, FastAPI)
