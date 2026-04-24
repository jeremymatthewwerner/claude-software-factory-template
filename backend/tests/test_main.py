"""Tests for the main API endpoints."""

import pytest
from fastapi.testclient import TestClient

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
