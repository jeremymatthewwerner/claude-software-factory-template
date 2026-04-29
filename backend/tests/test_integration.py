"""
Integration tests verifying API endpoints work together correctly.

These tests simulate real usage patterns — specifically the sequence of calls
the frontend makes on initialization and user interaction — and validate the
API contract (response shapes) that the frontend TypeScript interfaces depend on.
"""

from fastapi.testclient import TestClient


class TestFullWorkflow:
    """Tests that simulate the frontend's full API interaction sequence."""

    def test_full_page_load_sequence(self, client: TestClient) -> None:
        """Frontend init sequence: health → version → hello (GET) all succeed."""
        health_res = client.get("/health")
        assert health_res.status_code == 200
        assert health_res.json()["status"] == "healthy"

        version_res = client.get("/api/version")
        assert version_res.status_code == 200
        assert "version" in version_res.json()

        hello_res = client.get("/api/hello")
        assert hello_res.status_code == 200
        assert "message" in hello_res.json()

    def test_full_user_interaction_flow(self, client: TestClient) -> None:
        """Full flow: page load init sequence followed by a POST greeting."""
        # Simulate frontend initialization
        assert client.get("/health").status_code == 200
        assert client.get("/api/version").status_code == 200
        assert client.get("/api/hello").status_code == 200

        # Simulate user submitting their name
        post_res = client.post("/api/hello", json={"name": "Alice"})
        assert post_res.status_code == 200
        assert "Alice" in post_res.json()["message"]

    def test_multiple_users_get_distinct_greetings(self, client: TestClient) -> None:
        """Concurrent users with different names receive correctly personalized responses."""
        alice = client.post("/api/hello", json={"name": "Alice"})
        bob = client.post("/api/hello", json={"name": "Bob"})

        assert "Alice" in alice.json()["message"]
        assert "Bob" in bob.json()["message"]
        assert alice.json()["message"] != bob.json()["message"]

    def test_health_check_after_hello_calls(self, client: TestClient) -> None:
        """Health check remains healthy after handling multiple hello requests."""
        for _ in range(3):
            client.post("/api/hello", json={"name": "User"})

        health_res = client.get("/health")
        assert health_res.status_code == 200
        assert health_res.json()["status"] == "healthy"


class TestAPIContractHealth:
    """
    Validates the /health response shape matches what the frontend expects.

    Frontend reads: response.ok (HTTP status), no specific JSON fields used.
    Backend must return: HTTP 200, JSON with 'status' string.
    """

    def test_health_response_has_status_field(self, client: TestClient) -> None:
        """Frontend checks response.ok; backend must return HTTP 200."""
        response = client.get("/health")
        assert "status" in response.json()

    def test_health_status_field_is_string(self, client: TestClient) -> None:
        """The 'status' field must be a string (not a boolean or number)."""
        response = client.get("/health")
        assert isinstance(response.json()["status"], str)

    def test_health_response_is_200(self, client: TestClient) -> None:
        """Frontend uses response.ok — must be HTTP 200."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_response_has_timestamp(self, client: TestClient) -> None:
        """Health response includes timestamp for observability."""
        response = client.get("/health")
        data = response.json()
        assert "timestamp" in data
        assert isinstance(data["timestamp"], str)
        assert len(data["timestamp"]) > 0


class TestAPIContractVersion:
    """
    Validates the /api/version response shape matches what the frontend expects.

    Frontend reads: versionData.version (string)
    Backend must return: JSON with 'version' as a non-empty string.
    """

    def test_version_response_has_version_field(self, client: TestClient) -> None:
        """Frontend reads 'version' from the response."""
        response = client.get("/api/version")
        assert "version" in response.json()

    def test_version_field_is_non_empty_string(self, client: TestClient) -> None:
        """Frontend displays the version string; it must be non-empty."""
        response = client.get("/api/version")
        version = response.json()["version"]
        assert isinstance(version, str)
        assert len(version) > 0

    def test_version_response_contains_extra_fields(self, client: TestClient) -> None:
        """
        Backend returns 'name' and 'environment' in addition to 'version'.
        Frontend only reads 'version' — extra fields must not break the response.
        """
        response = client.get("/api/version")
        data = response.json()
        assert "name" in data
        assert "environment" in data
        assert "version" in data  # frontend-required field still present

    def test_version_response_is_200(self, client: TestClient) -> None:
        """Version endpoint must return HTTP 200."""
        response = client.get("/api/version")
        assert response.status_code == 200


class TestAPIContractHello:
    """
    Validates the /api/hello response shapes match what the frontend expects.

    Frontend reads: helloData.message (GET), data.message (POST)
    Backend must return: JSON with 'message' as a non-empty string.
    """

    def test_get_hello_response_has_message_field(self, client: TestClient) -> None:
        """Frontend reads 'message' from GET /api/hello."""
        response = client.get("/api/hello")
        assert "message" in response.json()

    def test_get_hello_message_is_non_empty_string(self, client: TestClient) -> None:
        """GET hello 'message' must be a non-empty string for the frontend to display."""
        response = client.get("/api/hello")
        message = response.json()["message"]
        assert isinstance(message, str)
        assert len(message) > 0

    def test_post_hello_response_has_message_field(self, client: TestClient) -> None:
        """Frontend reads 'message' from POST /api/hello."""
        response = client.post("/api/hello", json={"name": "Test"})
        assert "message" in response.json()

    def test_post_hello_message_is_non_empty_string(self, client: TestClient) -> None:
        """POST hello 'message' must be a non-empty string for the frontend to display."""
        response = client.post("/api/hello", json={"name": "Test"})
        message = response.json()["message"]
        assert isinstance(message, str)
        assert len(message) > 0

    def test_post_hello_message_contains_submitted_name(self, client: TestClient) -> None:
        """POST hello 'message' must include the submitted name — contract with frontend display."""
        response = client.post("/api/hello", json={"name": "IntegrationTest"})
        assert "IntegrationTest" in response.json()["message"]

    def test_get_hello_response_has_timestamp(self, client: TestClient) -> None:
        """GET hello includes timestamp (used for observability, not displayed by frontend)."""
        response = client.get("/api/hello")
        data = response.json()
        assert "timestamp" in data
        assert isinstance(data["timestamp"], str)

    def test_post_hello_response_has_timestamp(self, client: TestClient) -> None:
        """POST hello includes timestamp (used for observability, not displayed by frontend)."""
        response = client.post("/api/hello", json={"name": "Test"})
        data = response.json()
        assert "timestamp" in data
        assert isinstance(data["timestamp"], str)


class TestValidationErrorFormat:
    """
    Validates FastAPI's 422 error response structure.

    The frontend's POST handler does not parse 422 body explicitly, but any
    API consumer must be able to depend on a predictable error format.
    """

    def test_missing_name_field_returns_422(self, client: TestClient) -> None:
        """POST /api/hello without 'name' returns HTTP 422."""
        response = client.post("/api/hello", json={})
        assert response.status_code == 422

    def test_422_response_has_detail_key(self, client: TestClient) -> None:
        """FastAPI 422 responses use a top-level 'detail' key."""
        response = client.post("/api/hello", json={})
        assert "detail" in response.json()

    def test_422_detail_is_a_list(self, client: TestClient) -> None:
        """The 'detail' value is a list of validation error objects."""
        response = client.post("/api/hello", json={})
        detail = response.json()["detail"]
        assert isinstance(detail, list)
        assert len(detail) > 0

    def test_422_each_error_has_loc_msg_type(self, client: TestClient) -> None:
        """Each validation error object has 'loc', 'msg', and 'type' fields."""
        response = client.post("/api/hello", json={})
        for error in response.json()["detail"]:
            assert "loc" in error, f"Missing 'loc' in error: {error}"
            assert "msg" in error, f"Missing 'msg' in error: {error}"
            assert "type" in error, f"Missing 'type' in error: {error}"

    def test_422_loc_points_to_name_field(self, client: TestClient) -> None:
        """When 'name' is missing, the validation error points to the 'name' field."""
        response = client.post("/api/hello", json={})
        locations = [err["loc"] for err in response.json()["detail"]]
        # FastAPI loc is a list like ["body", "name"]
        name_errors = [loc for loc in locations if "name" in loc]
        assert len(name_errors) > 0

    def test_invalid_json_body_returns_422(self, client: TestClient) -> None:
        """Non-JSON body returns 422 (not 500)."""
        response = client.post(
            "/api/hello",
            content=b"not valid json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422

    def test_null_name_returns_422(self, client: TestClient) -> None:
        """null name field returns 422 since 'name' must be a string."""
        response = client.post("/api/hello", json={"name": None})
        assert response.status_code == 422

    def test_integer_name_returns_422(self, client: TestClient) -> None:
        """Integer name field returns 422 since 'name' must be a string."""
        response = client.post("/api/hello", json={"name": 42})
        assert response.status_code == 422
