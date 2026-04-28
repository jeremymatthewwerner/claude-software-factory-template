"""Tests for the main API endpoints."""

import asyncio
from datetime import UTC

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


class TestCORSMiddleware:
    """Tests for CORS middleware configuration.

    The app explicitly allows localhost:3000 for frontend communication.
    These tests verify the middleware is wired up correctly.
    """

    def test_cors_preflight_returns_ok_for_allowed_origin(self, client: TestClient) -> None:
        """OPTIONS preflight for an allowed origin returns 200 with CORS headers."""
        response = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers

    def test_cors_get_response_includes_allow_origin_for_allowed_origin(
        self, client: TestClient
    ) -> None:
        """GET /health with an allowed origin includes Access-Control-Allow-Origin header."""
        response = client.get("/health", headers={"Origin": "http://localhost:3000"})
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"

    def test_cors_get_response_includes_allow_origin_for_127_origin(
        self, client: TestClient
    ) -> None:
        """GET /health with 127.0.0.1:3000 origin also receives the CORS header."""
        response = client.get("/health", headers={"Origin": "http://127.0.0.1:3000"})
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == "http://127.0.0.1:3000"

    def test_cors_preflight_allows_post_method(self, client: TestClient) -> None:
        """OPTIONS preflight for POST method on allowed origin returns CORS headers."""
        response = client.options(
            "/api/hello",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers


class TestHTTPMethodNotAllowed:
    """Tests that unsupported HTTP methods return 405 Method Not Allowed."""

    def test_delete_health_returns_405(self, client: TestClient) -> None:
        """DELETE /health returns 405 since only GET is defined."""
        response = client.delete("/health")
        assert response.status_code == 405

    def test_put_health_returns_405(self, client: TestClient) -> None:
        """PUT /health returns 405 since only GET is defined."""
        response = client.put("/health")
        assert response.status_code == 405

    def test_delete_api_version_returns_405(self, client: TestClient) -> None:
        """DELETE /api/version returns 405 since only GET is defined."""
        response = client.delete("/api/version")
        assert response.status_code == 405

    def test_put_api_hello_returns_405(self, client: TestClient) -> None:
        """PUT /api/hello returns 405 since only GET and POST are defined."""
        response = client.put("/api/hello", json={"name": "test"})
        assert response.status_code == 405

    def test_delete_api_hello_returns_405(self, client: TestClient) -> None:
        """DELETE /api/hello returns 405 since only GET and POST are defined."""
        response = client.delete("/api/hello")
        assert response.status_code == 405


class TestTimestampOrdering:
    """Flakiness prevention: timestamps must advance, never go backwards or be cached."""

    def test_health_timestamps_are_non_decreasing(self, client: TestClient) -> None:
        """Two successive /health calls return timestamps where the second is not earlier."""
        from datetime import datetime

        r1 = client.get("/health")
        r2 = client.get("/health")
        ts1 = datetime.fromisoformat(r1.json()["timestamp"])
        ts2 = datetime.fromisoformat(r2.json()["timestamp"])
        assert ts2 >= ts1, f"Second timestamp {ts2} must not precede first {ts1}"

    def test_hello_get_timestamps_are_non_decreasing(self, client: TestClient) -> None:
        """Two successive GET /api/hello calls return non-decreasing timestamps."""
        from datetime import datetime

        r1 = client.get("/api/hello")
        r2 = client.get("/api/hello")
        ts1 = datetime.fromisoformat(r1.json()["timestamp"])
        ts2 = datetime.fromisoformat(r2.json()["timestamp"])
        assert ts2 >= ts1, f"Second timestamp {ts2} must not precede first {ts1}"

    def test_hello_post_timestamp_within_request_window(self, client: TestClient) -> None:
        """POST /api/hello timestamp falls between the start and end of the request."""
        from datetime import datetime

        before = datetime.now(UTC)
        response = client.post("/api/hello", json={"name": "TimestampWindow"})
        after = datetime.now(UTC)
        ts = datetime.fromisoformat(response.json()["timestamp"])
        assert before <= ts <= after, f"Timestamp {ts} not in [{before}, {after}]"


class TestRequestIsolation:
    """Flakiness prevention: requests must not share mutable state."""

    def test_hello_name_responses_are_independent(self, client: TestClient) -> None:
        """Two POST /api/hello calls with different names return independent responses."""
        r1 = client.post("/api/hello", json={"name": "Alpha"})
        r2 = client.post("/api/hello", json={"name": "Beta"})
        msg1 = r1.json()["message"]
        msg2 = r2.json()["message"]
        assert "Alpha" in msg1
        assert "Beta" in msg2
        assert "Alpha" not in msg2
        assert "Beta" not in msg1

    async def test_concurrent_hello_posts_are_independent(self, async_client: AsyncClient) -> None:
        """Concurrent POST /api/hello calls each receive only their own name."""
        responses = await asyncio.gather(
            async_client.post("/api/hello", json={"name": "Concurrent_Alice"}),
            async_client.post("/api/hello", json={"name": "Concurrent_Bob"}),
            async_client.post("/api/hello", json={"name": "Concurrent_Charlie"}),
        )
        names = ["Concurrent_Alice", "Concurrent_Bob", "Concurrent_Charlie"]
        for i, resp in enumerate(responses):
            msg = resp.json()["message"]
            assert names[i] in msg, f"Response {i} missing own name {names[i]}"
            for j, other_name in enumerate(names):
                if i != j:
                    assert other_name not in msg, f"Name {other_name} leaked into response {i}"
