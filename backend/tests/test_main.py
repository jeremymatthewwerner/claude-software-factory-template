"""Tests for the main API endpoints."""

import asyncio
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import AsyncClient

from app import __version__

from .conftest import LOCALHOST_ORIGIN, assert_utc_iso8601


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
        response = client.get("/health")
        timestamp = response.json()["timestamp"]
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

    @pytest.mark.parametrize(
        "method,path,json_body",
        [
            ("GET", "/health", None),
            ("GET", "/api/hello", None),
            ("POST", "/api/hello", {"name": "Test"}),
        ],
        ids=["health", "hello_get", "hello_post"],
    )
    def test_response_timestamp_is_utc_iso8601(
        self,
        client: TestClient,
        method: str,
        path: str,
        json_body: dict[str, str] | None,
    ) -> None:
        """Each timestamped endpoint returns a timezone-aware ISO 8601 UTC timestamp."""
        response = client.request(method, path, json=json_body)
        assert_utc_iso8601(response.json()["timestamp"])


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
                "Origin": LOCALHOST_ORIGIN,
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers

    def test_cors_get_response_includes_allow_origin_for_allowed_origin(
        self, client: TestClient
    ) -> None:
        """GET /health with an allowed origin includes Access-Control-Allow-Origin header."""
        response = client.get("/health", headers={"Origin": LOCALHOST_ORIGIN})
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == LOCALHOST_ORIGIN

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
                "Origin": LOCALHOST_ORIGIN,
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers


class TestHTTPMethodNotAllowed:
    """Tests that unsupported HTTP methods return 405 Method Not Allowed.

    Covers DELETE/PUT/PATCH against every defined route. Each row asserts
    FastAPI's automatic 405 handling for a method not registered on the route.
    """

    @pytest.mark.parametrize(
        "method,path",
        [
            ("DELETE", "/health"),
            ("PUT", "/health"),
            ("PATCH", "/health"),
            ("DELETE", "/api/version"),
            ("PATCH", "/api/version"),
            ("PUT", "/api/hello"),
            ("DELETE", "/api/hello"),
            ("PATCH", "/api/hello"),
        ],
    )
    def test_unsupported_method_returns_405(
        self, client: TestClient, method: str, path: str
    ) -> None:
        """Unsupported method on a defined route returns 405."""
        response = client.request(method, path)
        assert response.status_code == 405


class TestTimestampOrdering:
    """Flakiness prevention: timestamps must advance, never go backwards or be cached."""

    @pytest.mark.parametrize(
        "method,path",
        [("GET", "/health"), ("GET", "/api/hello")],
        ids=["health", "hello_get"],
    )
    def test_successive_timestamps_are_non_decreasing(
        self, client: TestClient, method: str, path: str
    ) -> None:
        """Two successive calls return timestamps where the second is not earlier."""
        ts1 = datetime.fromisoformat(client.request(method, path).json()["timestamp"])
        ts2 = datetime.fromisoformat(client.request(method, path).json()["timestamp"])
        assert ts2 >= ts1, f"Second timestamp {ts2} must not precede first {ts1}"

    def test_hello_post_timestamp_within_request_window(self, client: TestClient) -> None:
        """POST /api/hello timestamp falls between the start and end of the request."""
        before = datetime.now(UTC)
        response = client.post("/api/hello", json={"name": "TimestampWindow"})
        after = datetime.now(UTC)
        ts = datetime.fromisoformat(response.json()["timestamp"])
        assert before <= ts <= after, f"Timestamp {ts} not in [{before}, {after}]"

    def test_health_timestamps_monotone_across_10_sequential_calls(
        self, client: TestClient
    ) -> None:
        """Ten sequential /health calls return a strictly non-decreasing timestamp sequence.

        Extends the two-call ordering test to a longer run so that any cached or
        coarsely-rounded timestamp implementation fails quickly rather than occasionally.
        """
        timestamps = [
            datetime.fromisoformat(client.get("/health").json()["timestamp"]) for _ in range(10)
        ]
        for i in range(1, len(timestamps)):
            assert timestamps[i] >= timestamps[i - 1], (
                f"Timestamp regression at position {i}: {timestamps[i]} < {timestamps[i - 1]}"
            )


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


class TestNotFoundRoutes:
    """Tests that requests to undefined routes return 404."""

    def test_unknown_api_route_returns_404(self, client: TestClient) -> None:
        """GET to an undefined route under /api/ returns 404."""
        response = client.get("/api/nonexistent")
        assert response.status_code == 404

    def test_unknown_route_404_response_has_detail_key(self, client: TestClient) -> None:
        """FastAPI 404 responses include a JSON body with a 'detail' key."""
        response = client.get("/api/nonexistent")
        assert "detail" in response.json()

    def test_root_path_returns_404(self, client: TestClient) -> None:
        """GET / returns 404 since no route is registered at the root."""
        response = client.get("/")
        assert response.status_code == 404


class TestCORSDisallowedOrigin:
    """Tests that CORS middleware withholds headers for origins not in the allowlist."""

    def test_cors_get_does_not_expose_allow_origin_for_disallowed_origin(
        self, client: TestClient
    ) -> None:
        """GET /health from a disallowed origin does NOT receive Access-Control-Allow-Origin."""
        response = client.get("/health", headers={"Origin": "https://evil.example.com"})
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") is None

    def test_cors_preflight_does_not_expose_allow_origin_for_disallowed_origin(
        self, client: TestClient
    ) -> None:
        """OPTIONS preflight from a disallowed origin does NOT expose Access-Control-Allow-Origin."""
        response = client.options(
            "/health",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.headers.get("access-control-allow-origin") is None


class TestHEADMethod:
    """Tests for HEAD method behavior.

    Starlette 1.0 does NOT auto-handle HEAD for GET routes — HEAD returns 405.
    HTTP semantics still apply: HEAD responses have no body regardless of status.
    """

    @pytest.mark.parametrize("path", ["/health", "/api/version", "/api/hello"])
    def test_head_returns_405(self, client: TestClient, path: str) -> None:
        """HEAD on a defined route returns 405 (Starlette 1.0 does not auto-register HEAD)."""
        response = client.head(path)
        assert response.status_code == 405

    def test_head_health_response_has_no_body(self, client: TestClient) -> None:
        """HEAD /health response body is empty per HTTP HEAD semantics, even for 405."""
        response = client.head("/health")
        assert response.content == b""


class TestRegressionMessageFormat:
    """Regression tests locking in the exact API message content.

    These catch unintentional changes to message strings, the API name, the
    environment label, and OpenAPI metadata — all things that existing tests
    only check at the substring/presence level.
    """

    def test_get_hello_exact_message(self, client: TestClient) -> None:
        """GET /api/hello message is exactly the expected string.

        Pins the full greeting so a template change (e.g. dropping 'Welcome to
        your Software Factory.') is detected immediately.
        """
        response = client.get("/api/hello")
        assert response.json()["message"] == "Hello, World! Welcome to your Software Factory."

    def test_post_hello_exact_message_format(self, client: TestClient) -> None:
        """POST /api/hello message follows 'Hello, {name}! Welcome to your Software Factory.'

        Pins the surrounding template text so a refactor that changes the prefix
        or suffix (e.g. 'Hi, Alice!' or 'Greetings Alice') is detected.
        """
        response = client.post("/api/hello", json={"name": "Alice"})
        assert response.json()["message"] == "Hello, Alice! Welcome to your Software Factory."

    def test_version_environment_is_development(self, client: TestClient) -> None:
        """GET /api/version environment field is 'development'.

        The field presence is tested elsewhere; this pins the VALUE so that a
        hard-coded 'production' or 'staging' slip doesn't silently pass.
        """
        response = client.get("/api/version")
        assert response.json()["environment"] == "development"

    def test_openapi_title_is_software_factory_api(self, client: TestClient) -> None:
        """OpenAPI title is 'Software Factory API'.

        Prevents accidental renames from propagating to generated clients and
        public docs before anyone notices.
        """
        response = client.get("/openapi.json")
        assert response.json()["info"]["title"] == "Software Factory API"

    def test_openapi_version_matches_app_version(self, client: TestClient) -> None:
        """OpenAPI version matches app.__version__ (no drift allowed).

        FastAPI is configured with version=__version__; this test ensures the
        wiring is never accidentally removed or overridden.
        """
        response = client.get("/openapi.json")
        assert response.json()["info"]["version"] == __version__


class TestSecurityInputs:
    """Tests verifying the API handles adversarial name inputs correctly.

    These tests complement TestHelloNameEdgeCases by focusing on inputs that
    carry security significance — injection patterns, non-ASCII encodings, and
    binary-adjacent strings.  The endpoint echoes names verbatim inside JSON, so
    no server-side sanitisation is expected; the test documents that contract.
    """

    def test_sql_injection_in_name_returned_verbatim(self, client: TestClient) -> None:
        """SQL injection pattern in name echoed back unchanged (no DB, so no injection risk)."""
        payload = "'; DROP TABLE users; --"
        response = client.post("/api/hello", json={"name": payload})
        assert response.status_code == 200
        assert payload in response.json()["message"]

    def test_emoji_in_name_round_trips_correctly(self, client: TestClient) -> None:
        """Emoji characters in name are serialised and deserialised through JSON correctly."""
        payload = "Alice \U0001f389\U0001f916"  # 🎉🤖
        response = client.post("/api/hello", json={"name": payload})
        assert response.status_code == 200
        assert payload in response.json()["message"]

    def test_rtl_unicode_in_name_round_trips_correctly(self, client: TestClient) -> None:
        """Right-to-left Unicode text (Arabic) in name is returned correctly."""
        payload = "مرحبا"  # مرحبا (Arabic "Hello")
        response = client.post("/api/hello", json={"name": payload})
        assert response.status_code == 200
        assert payload in response.json()["message"]

    def test_zero_width_chars_in_name_returned_verbatim(self, client: TestClient) -> None:
        """Zero-width joiner and non-joiner characters in name are echoed back unchanged."""
        payload = "Alice​‌Bob"  # zero-width space + zero-width non-joiner
        response = client.post("/api/hello", json={"name": payload})
        assert response.status_code == 200
        assert payload in response.json()["message"]


class TestLargeScaleConcurrency:
    """Stress-test the async server under a burst of concurrent requests.

    The smaller concurrent tests (3 requests in TestRegressionAsyncClient and
    TestRequestIsolation) catch obvious race conditions.  These 20-request
    variants amplify any resource exhaustion, shared-state, or scheduling
    non-determinism that only manifests under higher load.
    """

    async def test_20_concurrent_health_requests_all_return_200(
        self, async_client: AsyncClient
    ) -> None:
        """20 simultaneous GET /health requests all return 200 with healthy status."""
        responses = await asyncio.gather(*[async_client.get("/health") for _ in range(20)])
        for i, resp in enumerate(responses):
            assert resp.status_code == 200, f"Request {i} returned {resp.status_code}"
            assert resp.json()["status"] == "healthy", f"Request {i} not healthy"

    async def test_20_concurrent_hello_posts_have_no_name_crosscontamination(
        self, async_client: AsyncClient
    ) -> None:
        """20 concurrent POST /api/hello calls each receive only their own name.

        Each response must contain exactly its own submitted name and must not
        contain any of the other 19 names — catching any global mutable state
        that could cause responses to bleed across concurrent handlers.
        """
        names = [f"Stress_{i:02d}" for i in range(20)]
        responses = await asyncio.gather(
            *[async_client.post("/api/hello", json={"name": name}) for name in names]
        )
        for i, resp in enumerate(responses):
            assert resp.status_code == 200, f"Request {i} returned {resp.status_code}"
            msg = resp.json()["message"]
            assert names[i] in msg, f"Response {i} missing own name {names[i]!r}"
            for j, other in enumerate(names):
                if i != j:
                    assert other not in msg, (
                        f"Name {other!r} from request {j} leaked into response {i}"
                    )


class TestContentTypeNegotiation:
    """Tests verifying that the API correctly rejects non-JSON request bodies.

    FastAPI parses POST body as JSON when a Pydantic model is declared.  Clients
    sending form-encoded or plain-text bodies receive 422 because those payloads
    are not valid JSON, ensuring the API contract is strictly JSON-only.
    """

    def test_post_hello_with_form_encoded_body_returns_422(self, client: TestClient) -> None:
        """POST with application/x-www-form-urlencoded body returns 422 (expects JSON)."""
        response = client.post(
            "/api/hello",
            content=b"name=Alice",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert response.status_code == 422

    def test_post_hello_with_text_plain_body_returns_422(self, client: TestClient) -> None:
        """POST with text/plain body returns 422 (expects JSON)."""
        response = client.post(
            "/api/hello",
            content=b"Alice",
            headers={"Content-Type": "text/plain"},
        )
        assert response.status_code == 422
