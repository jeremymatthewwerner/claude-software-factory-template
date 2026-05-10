"""
Integration tests verifying API endpoints work together correctly.

These tests simulate real usage patterns — specifically the sequence of calls
the frontend makes on initialization and user interaction — and validate the
API contract (response shapes) that the frontend TypeScript interfaces depend on.
"""

import pytest
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


class TestOpenAPISchemaContract:
    """
    Verifies the OpenAPI schema accurately describes the implemented API.

    The OpenAPI schema is the source of truth for code generators (Swagger
    Codegen, openapi-typescript), the /docs and /redoc UIs, and any external
    SDK consumers. If a field is added to a response without updating the
    Pydantic model, or vice versa, the schema silently lies to consumers.
    These tests catch field-level drift between the documented contract and
    the actual responses on every endpoint.
    """

    def test_openapi_documents_all_defined_routes(self, client: TestClient) -> None:
        """Every defined route + method appears in OpenAPI paths.

        Without this, a route registered programmatically but missed by FastAPI's
        introspection (or accidentally hidden via include_in_schema=False) would
        not appear in /docs and would be invisible to SDK generators.
        """
        schema = client.get("/openapi.json").json()
        paths = schema["paths"]

        assert "/health" in paths and "get" in paths["/health"]
        assert "/api/version" in paths and "get" in paths["/api/version"]
        assert "/api/hello" in paths
        assert "get" in paths["/api/hello"]
        assert "post" in paths["/api/hello"]

    def test_openapi_post_hello_request_body_requires_name_string(self, client: TestClient) -> None:
        """OpenAPI POST /api/hello body schema requires `name` as a string.

        The frontend's HelloRequest TypeScript type and any SDK client depend on
        this schema. If the Pydantic model loses the `name` field or its type
        changes (e.g. to `int`), generated clients break — this test fails first.
        """
        schema = client.get("/openapi.json").json()
        post_op = schema["paths"]["/api/hello"]["post"]
        ref = post_op["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        # $ref is like "#/components/schemas/HelloRequest"
        component_name = ref.rsplit("/", 1)[-1]
        component = schema["components"]["schemas"][component_name]

        assert "name" in component["required"], "Schema must mark 'name' as required"
        assert component["properties"]["name"]["type"] == "string", (
            "Schema must declare 'name' as a string"
        )

    def test_openapi_health_response_schema_matches_actual_response(
        self, client: TestClient
    ) -> None:
        """OpenAPI HealthResponse fields are exactly the fields returned by /health.

        Catches drift in either direction: a field added to the response but not
        the model, or removed from the model but still emitted by the handler.
        """
        schema = client.get("/openapi.json").json()
        ref = schema["paths"]["/health"]["get"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        component_name = ref.rsplit("/", 1)[-1]
        documented_fields = set(schema["components"]["schemas"][component_name]["properties"])
        actual_fields = set(client.get("/health").json().keys())

        assert documented_fields == actual_fields, (
            f"OpenAPI declares {documented_fields} but /health returns {actual_fields}"
        )

    def test_openapi_version_response_schema_matches_actual_response(
        self, client: TestClient
    ) -> None:
        """OpenAPI VersionResponse fields are exactly the fields returned by /api/version."""
        schema = client.get("/openapi.json").json()
        ref = schema["paths"]["/api/version"]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]["$ref"]
        component_name = ref.rsplit("/", 1)[-1]
        documented_fields = set(schema["components"]["schemas"][component_name]["properties"])
        actual_fields = set(client.get("/api/version").json().keys())

        assert documented_fields == actual_fields, (
            f"OpenAPI declares {documented_fields} but /api/version returns {actual_fields}"
        )

    def test_openapi_get_hello_response_schema_matches_actual_response(
        self, client: TestClient
    ) -> None:
        """OpenAPI HelloResponse fields are exactly the fields returned by GET /api/hello."""
        schema = client.get("/openapi.json").json()
        ref = schema["paths"]["/api/hello"]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]["$ref"]
        component_name = ref.rsplit("/", 1)[-1]
        documented_fields = set(schema["components"]["schemas"][component_name]["properties"])
        actual_fields = set(client.get("/api/hello").json().keys())

        assert documented_fields == actual_fields, (
            f"OpenAPI declares {documented_fields} but GET /api/hello returns {actual_fields}"
        )

    def test_openapi_post_hello_response_schema_matches_actual_response(
        self, client: TestClient
    ) -> None:
        """OpenAPI HelloResponse fields are exactly the fields returned by POST /api/hello."""
        schema = client.get("/openapi.json").json()
        ref = schema["paths"]["/api/hello"]["post"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]["$ref"]
        component_name = ref.rsplit("/", 1)[-1]
        documented_fields = set(schema["components"]["schemas"][component_name]["properties"])
        actual_fields = set(client.post("/api/hello", json={"name": "SchemaCheck"}).json().keys())

        assert documented_fields == actual_fields, (
            f"OpenAPI declares {documented_fields} but POST /api/hello returns {actual_fields}"
        )


class TestCrossEndpointContract:
    """
    Verifies API-wide conventions hold across every endpoint.

    Per-endpoint tests check each endpoint in isolation. A new endpoint added
    later without these conventions (e.g. emitting text/plain instead of JSON,
    or a non-UTC timestamp) would slip past unit tests that only know about
    the endpoints they were written for. These tests treat the whole API
    surface as a single contract.
    """

    def test_all_success_responses_are_json(self, client: TestClient) -> None:
        """Every defined endpoint emits Content-Type: application/json on a 200 response.

        The frontend uses `response.json()` on every response without negotiation
        — a non-JSON content-type would throw at parse time.
        """
        responses = [
            client.get("/health"),
            client.get("/api/version"),
            client.get("/api/hello"),
            client.post("/api/hello", json={"name": "ContentType"}),
        ]
        for r in responses:
            assert r.status_code == 200, f"{r.request.method} {r.request.url} → {r.status_code}"
            assert "application/json" in r.headers["content-type"], (
                f"{r.request.method} {r.request.url} content-type was {r.headers['content-type']}"
            )

    def test_all_endpoint_timestamps_share_utc_iso8601_format(self, client: TestClient) -> None:
        """Timestamps from /health, GET /api/hello, and POST /api/hello are all UTC ISO 8601.

        The frontend parses any of these via `new Date(timestamp)` and any
        observability tooling treats them uniformly — a non-UTC or non-ISO format
        on one endpoint silently breaks downstream consumers.
        """
        from datetime import datetime

        timestamps = [
            client.get("/health").json()["timestamp"],
            client.get("/api/hello").json()["timestamp"],
            client.post("/api/hello", json={"name": "TimestampCheck"}).json()["timestamp"],
        ]
        for ts in timestamps:
            parsed = datetime.fromisoformat(ts)
            assert parsed.tzinfo is not None, f"Timestamp {ts!r} is naive (no timezone)"
            offset = parsed.utcoffset()
            assert offset is not None and offset.total_seconds() == 0, (
                f"Timestamp {ts!r} is not UTC (offset={offset})"
            )

    def test_all_4xx_responses_have_detail_key(self, client: TestClient) -> None:
        """404, 405, and 422 responses across endpoints all include a top-level `detail` key.

        FastAPI's convention is that all error responses have `detail`. Any
        custom handler added later that bypasses this convention would break
        clients that uniformly read `error.detail` to surface failures.
        """
        cases = [
            ("404 unknown route", client.get("/api/nonexistent")),
            ("405 wrong method on /health", client.delete("/health")),
            ("405 wrong method on /api/hello", client.put("/api/hello", json={"name": "x"})),
            ("422 missing name", client.post("/api/hello", json={})),
            ("422 wrong type", client.post("/api/hello", json={"name": 42})),
        ]
        for label, r in cases:
            assert r.status_code in {404, 405, 422}, f"{label}: unexpected status {r.status_code}"
            body = r.json()
            assert "detail" in body, f"{label}: response missing 'detail' key — body was {body!r}"


class TestFrontendInitSequenceCORS:
    """
    Verifies the real-browser frontend init sequence works end-to-end with CORS.

    `TestFullWorkflow` simulates the multi-call init sequence without an Origin
    header. `TestCORSMiddleware` checks CORS on a single endpoint. Real browsers
    send `Origin: http://localhost:3000` on every cross-origin request, and if
    even one response in the init sequence omits Access-Control-Allow-Origin,
    the browser blocks the JavaScript from reading it — leaving the frontend
    stuck on "Checking..." with no useful error. These tests cover the
    intersection: full init sequence + real frontend Origin header.
    """

    def test_init_sequence_all_responses_carry_cors_for_localhost_3000(
        self, client: TestClient
    ) -> None:
        """All three init endpoints return Access-Control-Allow-Origin for localhost:3000."""
        origin = "http://localhost:3000"
        for path in ("/health", "/api/version", "/api/hello"):
            response = client.get(path, headers={"Origin": origin})
            assert response.status_code == 200, f"{path} returned {response.status_code}"
            assert response.headers.get("access-control-allow-origin") == origin, (
                f"{path} missing or wrong Access-Control-Allow-Origin header "
                f"(got {response.headers.get('access-control-allow-origin')!r})"
            )

    def test_post_hello_response_carries_cors_for_localhost_3000(self, client: TestClient) -> None:
        """POST /api/hello also returns Access-Control-Allow-Origin for the frontend origin.

        Once the user submits the form, the browser issues a POST. Without the
        CORS header on this response, the frontend cannot read the greeting
        even if the request itself succeeds.
        """
        response = client.post(
            "/api/hello",
            json={"name": "CorsCheck"},
            headers={"Origin": "http://localhost:3000"},
        )
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == "http://localhost:3000", (
            f"POST /api/hello missing CORS header (got "
            f"{response.headers.get('access-control-allow-origin')!r})"
        )


class TestRegressionCORSAllowListBoundary:
    """The CORS allow-list contains two entries: ``http://localhost:3000`` and
    ``http://127.0.0.1:3000``. Existing tests cover the **allowed** boundary
    (those two origins) and **one obviously-wrong** origin (``evil.example.com``).

    These tests pin three **realistic near-miss** origins that look superficially
    similar to the allow-list and would be silently accepted if a regression
    relaxed the matching (e.g. to a wildcard, a substring match, or a bug that
    treats scheme/port as optional). All three are common deployment mistakes:

    - ``https://localhost:3000`` — the **scheme** flipped to https. A future
      change that switches the dev frontend to https without updating the
      backend would silently break.
    - ``http://localhost:3001`` — the **port** drifted (e.g. someone bumps
      the dev port for a side project). Browsers treat origin equality as
      tuple equality (scheme, host, port).
    - ``http://localhost`` — the **port omitted**. RFC 6454 treats a missing
      port as the scheme default (80), distinct from ``:3000``.

    Pinning these three near-miss origins ensures the CORS middleware
    continues to enforce strict origin equality, not a relaxed prefix or
    fuzzy match. Without these pins, a regression in the middleware (or a
    dev who misreads the FastAPI ``allow_origins`` docs and adds a wildcard
    "for convenience") would land green.
    """

    @pytest.mark.parametrize(
        "near_miss_origin,reason",
        [
            ("https://localhost:3000", "scheme flipped to https"),
            ("http://localhost:3001", "port drifted to 3001"),
            ("http://localhost", "port omitted (defaults to 80)"),
        ],
    )
    def test_get_does_not_expose_allow_origin_for_near_miss(
        self, client: TestClient, near_miss_origin: str, reason: str
    ) -> None:
        """Near-miss origins do NOT receive ``Access-Control-Allow-Origin``."""
        response = client.get("/health", headers={"Origin": near_miss_origin})
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") is None, (
            f"CORS regression: {near_miss_origin!r} ({reason}) was accepted "
            f"by the allow-list — got {response.headers.get('access-control-allow-origin')!r}"
        )
