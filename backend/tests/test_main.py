"""
Tests for the main API endpoints.

These tests verify the Hello World API functionality and serve as
examples for writing tests in the Software Factory.
"""

from fastapi.testclient import TestClient

from app import __version__


class TestHealthEndpoint:
    """Tests for the /health endpoint."""

    def test_health_returns_200(self, client: TestClient) -> None:
        """Health check should return 200 OK."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_returns_healthy_status(self, client: TestClient) -> None:
        """Health check should return healthy status."""
        response = client.get("/health")
        data = response.json()
        assert data["status"] == "healthy"

    def test_health_includes_timestamp(self, client: TestClient) -> None:
        """Health check should include a timestamp."""
        response = client.get("/health")
        data = response.json()
        assert "timestamp" in data
        assert len(data["timestamp"]) > 0


class TestVersionEndpoint:
    """Tests for the /api/version endpoint."""

    def test_version_returns_200(self, client: TestClient) -> None:
        """Version endpoint should return 200 OK."""
        response = client.get("/api/version")
        assert response.status_code == 200

    def test_version_returns_correct_version(self, client: TestClient) -> None:
        """Version should match package version."""
        response = client.get("/api/version")
        data = response.json()
        assert data["version"] == __version__

    def test_version_includes_name(self, client: TestClient) -> None:
        """Version response should include API name."""
        response = client.get("/api/version")
        data = response.json()
        assert data["name"] == "software-factory-api"

    def test_version_includes_environment(self, client: TestClient) -> None:
        """Version response should include environment."""
        response = client.get("/api/version")
        data = response.json()
        assert "environment" in data


class TestHelloWorldEndpoint:
    """Tests for the /api/hello GET endpoint."""

    def test_hello_returns_200(self, client: TestClient) -> None:
        """Hello endpoint should return 200 OK."""
        response = client.get("/api/hello")
        assert response.status_code == 200

    def test_hello_returns_greeting(self, client: TestClient) -> None:
        """Hello endpoint should return a greeting message."""
        response = client.get("/api/hello")
        data = response.json()
        assert "message" in data
        assert "Hello" in data["message"]
        assert "World" in data["message"]

    def test_hello_includes_timestamp(self, client: TestClient) -> None:
        """Hello endpoint should include a timestamp."""
        response = client.get("/api/hello")
        data = response.json()
        assert "timestamp" in data


class TestHelloNameEndpoint:
    """Tests for the /api/hello POST endpoint."""

    def test_hello_name_returns_200(self, client: TestClient) -> None:
        """POST hello should return 200 OK."""
        response = client.post("/api/hello", json={"name": "Alice"})
        assert response.status_code == 200

    def test_hello_name_includes_name_in_greeting(self, client: TestClient) -> None:
        """POST hello should include the provided name."""
        response = client.post("/api/hello", json={"name": "Bob"})
        data = response.json()
        assert "Bob" in data["message"]

    def test_hello_name_with_special_characters(self, client: TestClient) -> None:
        """POST hello should handle special characters in names."""
        response = client.post("/api/hello", json={"name": "Dr. Smith-Jones"})
        assert response.status_code == 200
        data = response.json()
        assert "Dr. Smith-Jones" in data["message"]

    def test_hello_name_requires_name_field(self, client: TestClient) -> None:
        """POST hello should require the name field."""
        response = client.post("/api/hello", json={})
        assert response.status_code == 422  # Validation error

    def test_hello_name_rejects_invalid_json(self, client: TestClient) -> None:
        """POST hello should reject invalid JSON."""
        response = client.post(
            "/api/hello",
            content="not json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422


class TestOpenAPIDocumentation:
    """Tests for API documentation endpoints."""

    def test_openapi_schema_available(self, client: TestClient) -> None:
        """OpenAPI schema should be available."""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert "openapi" in data
        assert "paths" in data

    def test_docs_endpoint_available(self, client: TestClient) -> None:
        """Swagger UI docs should be available."""
        response = client.get("/docs")
        assert response.status_code == 200

    def test_redoc_endpoint_available(self, client: TestClient) -> None:
        """ReDoc documentation should be available."""
        response = client.get("/redoc")
        assert response.status_code == 200
