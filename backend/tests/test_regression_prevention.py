"""Regression-prevention pins for the public API contract.

The existing suite already covers exact message strings, OpenAPI title /
version / description / operationIds / tags, the CORS allow-list and
near-miss origins, preflight contents, content-type strictness and
permissiveness, BOM and trailing-byte parsing, path routing edges, the
50K-char echo, the 422 schema shape, p95 / p99 latency, and the response
schema vs. handler-output match for every route.

This file pins behaviours that are still load-bearing for downstream
consumers (SDK generators, monitoring tools, the dev frontend) and that
would silently change under realistic future edits:

* The canonical ``/openapi.json`` URL and the absence of alternate aliases.
* The exact set of OpenAPI component schema names that map to public
  Pydantic class names.
* The fact that ``ErrorResponse`` is defined in ``app.main`` but **not**
  exposed in OpenAPI components — a guard against a future endpoint
  silently wiring it as a ``response_model``.
* The absence of ``Cache-Control`` / ``ETag`` / ``Expires`` headers on
  timestamp-bearing endpoints (caching them would break ``/health``
  liveness signals and freeze ``timestamp`` fields).
* The preflight reflecting an arbitrary ``Access-Control-Request-Headers``
  back in ``Access-Control-Allow-Headers``, pinning ``allow_headers=["*"]``.
* Every route's 200 response is a component ``$ref`` (not inline) —
  pinning that ``response_model=`` remains set on every endpoint.
* ``HelloRequest.name`` has no length or pattern constraints — pinning
  that a future ``Field(min_length=1)`` cannot silently start rejecting
  inputs the rest of the suite deliberately exercises.
* POST /api/hello documents 422 as a ``$ref`` to ``HTTPValidationError``.
* The OpenAPI spec version is the 3.1.x family.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

from .conftest import LOCALHOST_ORIGIN, cors_preflight_headers, get_openapi_schema

# The exact set of Pydantic class names that the public OpenAPI surface exposes
# as component schemas today. SDK generators emit these as TypeScript types /
# generated client classes; a rename silently breaks every downstream consumer.
EXPECTED_OPENAPI_COMPONENTS: set[str] = {
    "HealthResponse",
    "VersionResponse",
    "HelloRequest",
    "HelloResponse",
    # FastAPI-derived components for validation error responses.
    "HTTPValidationError",
    "ValidationError",
}

# Endpoints whose responses embed a fresh ``datetime.now(UTC)`` timestamp.
# Any cache-control header (Cache-Control / ETag / Expires) on these would
# freeze the timestamp at the cache layer and break ``/health`` liveness.
TIMESTAMPED_REQUESTS: list[tuple[str, str, dict[str, str] | None]] = [
    ("GET", "/health", None),
    ("GET", "/api/version", None),
    ("GET", "/api/hello", None),
    ("POST", "/api/hello", {"name": "CacheCheck"}),
]


class TestOpenAPIURLIsCanonical:
    """The OpenAPI schema is served at the FastAPI default ``/openapi.json``
    and **only** at that path.

    ``TestRegressionDocumentationURLs`` pins ``/docs`` and ``/redoc`` but
    leaves ``/openapi.json`` itself unpinned — every other test reaches it
    incidentally, so a regression to ``openapi_url=None`` (disabling the
    schema) or ``openapi_url="/api/openapi.json"`` (relocating it) would
    surface only in the unrelated tests that read the schema, with a
    confusing failure mode. Pin the canonical URL directly here.
    """

    def test_canonical_openapi_url_returns_200(self, client: TestClient) -> None:
        """``GET /openapi.json`` returns 200 — FastAPI's default schema URL."""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        assert response.json().get("openapi"), "Body is not an OpenAPI document"

    @pytest.mark.parametrize(
        "alias_path",
        [
            "/openapi",
            "/openapi.yaml",
            "/swagger.json",
            "/api/openapi.json",
            "/api-docs.json",
        ],
    )
    def test_common_aliases_are_not_routed(self, client: TestClient, alias_path: str) -> None:
        """Common alternative OpenAPI URLs all return 404 — only the canonical path is served.

        Pinning the absence of aliases catches a regression that double-mounts
        the schema (e.g. a custom middleware that re-serves it at ``/swagger.json``
        "for convenience"). Without this pin, both URLs would silently work
        and any docs that point clients at the canonical one would drift.
        """
        response = client.get(alias_path)
        assert response.status_code == 404, (
            f"{alias_path!r} unexpectedly returned {response.status_code} — "
            f"only /openapi.json should serve the schema"
        )


class TestOpenAPIComponentInventoryPinned:
    """The exact set of OpenAPI component schemas equals the Pydantic
    classes the project exports.

    ``TestRegressionMessageFormat`` pins ``info.title``, ``info.version``
    and a few per-operation strings; ``TestOpenAPISchemaContract`` checks
    each component's *fields* against the handler output but does **not**
    pin the **names** of the components. SDK generators emit each
    component name as a generated type — a rename like
    ``HelloResponse`` → ``GreetingResponse`` would silently change every
    consumer's TypeScript / Python / Go client surface.
    """

    def test_component_inventory_is_exactly_the_expected_set(self, client: TestClient) -> None:
        """The OpenAPI components contain exactly the expected schema names — no more, no less."""
        schema = get_openapi_schema(client)
        actual: set[str] = set(schema["components"]["schemas"])
        unexpected = actual - EXPECTED_OPENAPI_COMPONENTS
        missing = EXPECTED_OPENAPI_COMPONENTS - actual
        assert not unexpected, (
            f"OpenAPI exposes unexpected components {unexpected}. Either pin them "
            f"in EXPECTED_OPENAPI_COMPONENTS or remove the Pydantic class."
        )
        assert not missing, (
            f"Expected component(s) {missing} are missing from OpenAPI — a Pydantic "
            f"class was renamed or stopped being referenced by a route."
        )


class TestUnusedErrorResponseNotExposedInOpenAPI:
    """``ErrorResponse`` is defined in ``app.main`` but is not currently
    wired to any ``response_model=`` declaration, so FastAPI does not
    surface it in the OpenAPI components.

    A future "let's standardise error bodies" change that adds
    ``response_model=ErrorResponse`` to an endpoint would silently expose
    the component in the OpenAPI surface — a public contract change. By
    pinning that the class **exists as a Python symbol** but does **not**
    appear in OpenAPI today, any such change becomes a visible test
    failure that prompts a deliberate decision (update the pin, add a
    matching ``response_model``, or drop the unused class).
    """

    def test_error_response_class_is_still_importable(self) -> None:
        """``ErrorResponse`` remains importable from ``app.main`` — base symbol still exists."""
        from app.main import ErrorResponse

        # The class should be usable as a Pydantic model with the documented fields.
        instance = ErrorResponse(error="bad", detail="something")
        assert instance.error == "bad"
        assert instance.detail == "something"

    def test_error_response_is_not_in_openapi_components(self, client: TestClient) -> None:
        """``ErrorResponse`` is **not** in OpenAPI components — pin its unused status."""
        schema = get_openapi_schema(client)
        assert "ErrorResponse" not in schema["components"]["schemas"], (
            "ErrorResponse appeared in OpenAPI components — a route must now "
            "use it as a response_model. Update EXPECTED_OPENAPI_COMPONENTS in "
            "test_regression_prevention.py if this is intentional."
        )


class TestNoCacheControlOnTimestampedEndpoints:
    """Every endpoint embeds a fresh ``datetime.now(UTC)`` timestamp; a
    cache-related header on the response would let a CDN or browser
    cache the response and silently serve a stale timestamp.

    For ``/health`` in particular, a cached response would break the
    liveness signal that the DevOps agent and Railway healthcheck poll
    every few minutes — the app could be hard-down and the cache would
    keep returning ``status: healthy``. These pins guard the negative
    contract: caching headers must remain **absent**.
    """

    @pytest.mark.parametrize(
        "method,path,json_body",
        TIMESTAMPED_REQUESTS,
        ids=["health", "version", "hello_get", "hello_post"],
    )
    def test_response_has_no_cache_control_header(
        self,
        client: TestClient,
        method: str,
        path: str,
        json_body: dict[str, str] | None,
    ) -> None:
        """``Cache-Control`` is absent on every timestamp-bearing response."""
        response = client.request(method, path, json=json_body)
        assert response.status_code == 200
        assert "cache-control" not in {k.lower() for k in response.headers}, (
            f"{method} {path} unexpectedly returned a Cache-Control header — "
            f"would let a CDN cache the embedded timestamp"
        )

    @pytest.mark.parametrize(
        "method,path,json_body",
        TIMESTAMPED_REQUESTS,
        ids=["health", "version", "hello_get", "hello_post"],
    )
    def test_response_has_no_etag_or_expires_header(
        self,
        client: TestClient,
        method: str,
        path: str,
        json_body: dict[str, str] | None,
    ) -> None:
        """``ETag`` and ``Expires`` are absent — both imply cacheability of a
        response that contains a freshly-stamped timestamp.

        ``ETag`` enables conditional GETs that return 304 from the cache
        layer; ``Expires`` is the legacy form of ``Cache-Control: max-age``.
        Either header reaching a caching proxy would freeze the response.
        """
        response = client.request(method, path, json=json_body)
        assert response.status_code == 200
        lower_headers = {k.lower() for k in response.headers}
        assert "etag" not in lower_headers, f"{method} {path} returned an ETag header"
        assert "expires" not in lower_headers, f"{method} {path} returned an Expires header"


class TestCORSPreflightReflectsRequestedHeaders:
    """The CORS middleware is configured with ``allow_headers=["*"]``,
    which makes Starlette echo whatever the browser advertised in
    ``Access-Control-Request-Headers`` back in
    ``Access-Control-Allow-Headers``.

    ``TestRegressionCORSPreflightContents`` pins ``Access-Control-Allow-Methods``
    and ``Access-Control-Max-Age`` but does **not** exercise the
    ``allow_headers`` config. A regression that tightens the config to
    ``allow_headers=["Content-Type"]`` would silently break any frontend
    that adds another header (e.g. ``Authorization``, ``X-Trace-Id``) —
    those headers would be missing from the preflight response and the
    browser would refuse the request.
    """

    def test_preflight_reflects_custom_request_header_back(self, client: TestClient) -> None:
        """A custom header in ``Access-Control-Request-Headers`` is mirrored to ``Allow-Headers``."""
        response = client.options(
            "/api/hello",
            headers={
                **cors_preflight_headers("POST"),
                "Access-Control-Request-Headers": "x-custom-header,content-type",
            },
        )
        assert response.status_code == 200
        allowed = response.headers.get("access-control-allow-headers", "").lower()
        assert "x-custom-header" in allowed, (
            f"Preflight did not advertise the requested custom header "
            f"(got Access-Control-Allow-Headers: {allowed!r}) — possible "
            f"regression to a narrower allow_headers config"
        )
        # Content-Type is the one the frontend actually sends today; pin it too.
        assert "content-type" in allowed, (
            f"Preflight did not advertise Content-Type — frontend POST would break "
            f"(got Access-Control-Allow-Headers: {allowed!r})"
        )

    def test_preflight_reflects_auth_style_header(self, client: TestClient) -> None:
        """``Authorization`` survives the preflight too — pins the open allow-list.

        Authorization is the header most likely to be added in a future
        commit (when an auth layer ships). Pinning that the preflight
        already advertises it today documents the "no-op" contract — any
        such future commit should not have to add CORS config, and a
        narrowing change would break first here.
        """
        response = client.options(
            "/api/hello",
            headers={
                **cors_preflight_headers("POST"),
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert response.status_code == 200
        allowed = response.headers.get("access-control-allow-headers", "").lower()
        assert "authorization" in allowed, (
            f"Preflight did not advertise Authorization (got {allowed!r}) — "
            f"a future auth header would be blocked by the browser"
        )


class TestEveryRouteUses200ResponseModelComponentRef:
    """Each route declares ``response_model=Xxx`` on its decorator today.

    A future endpoint that omits ``response_model=`` falls back to
    FastAPI's "anything goes" response schema (``{}``) and SDK
    generators emit ``unknown`` / ``any`` for it — silently dropping
    type safety on a public endpoint. The OpenAPI ``$ref`` is the
    visible signal that a response model is wired up.

    ``TestOpenAPISchemaContract.test_openapi_response_schema_matches_actual_response``
    checks fields **inside** the referenced component but does not pin
    that the response **is** a ``$ref`` (vs. an inline schema). These
    tests pin that signal so omitting ``response_model=`` is loud.
    """

    @pytest.mark.parametrize(
        "method,path",
        [
            ("get", "/health"),
            ("get", "/api/version"),
            ("get", "/api/hello"),
            ("post", "/api/hello"),
        ],
    )
    def test_route_200_response_is_component_ref(
        self, client: TestClient, method: str, path: str
    ) -> None:
        """The 200 response schema for each route is a ``$ref`` to a component."""
        schema = get_openapi_schema(client)
        op = schema["paths"][path][method]
        success_schema = op["responses"]["200"]["content"]["application/json"]["schema"]
        assert "$ref" in success_schema, (
            f"{method.upper()} {path} 200 response is inline, not a $ref — "
            f"response_model= is likely missing from the route decorator. "
            f"Got schema: {success_schema!r}"
        )
        # And the ref points into the components/schemas namespace (not, e.g.,
        # an external URL or a stray top-level ref).
        assert success_schema["$ref"].startswith("#/components/schemas/"), (
            f"{method.upper()} {path} 200 $ref is not local: {success_schema['$ref']!r}"
        )


class TestHelloRequestNameHasNoConstraints:
    """``HelloRequest.name`` is currently typed ``str`` with no
    additional Pydantic constraints (``min_length``, ``max_length``,
    ``pattern``, etc.).

    Half the suite — ``TestHelloNameEdgeCases.test_hello_name_empty_string``,
    ``TestNameEchoBoundaries.test_fifty_thousand_character_name_round_trips_verbatim``,
    ``TestExactGreetingFormat.test_empty_name_message_format`` and others —
    depends on this open contract. A "defensive" change that adds e.g.
    ``Field(min_length=1)`` would silently start returning 422 for those
    inputs and several tests would fail with confusing per-test messages.
    Pinning the absence of constraints here documents the design choice
    and makes the failure mode explicit.
    """

    def test_name_property_has_no_length_constraints(self, client: TestClient) -> None:
        """``HelloRequest.name`` declares no ``minLength`` or ``maxLength``."""
        schema = get_openapi_schema(client)
        name_prop = schema["components"]["schemas"]["HelloRequest"]["properties"]["name"]
        assert "minLength" not in name_prop, (
            f"HelloRequest.name gained a minLength constraint: {name_prop.get('minLength')!r}. "
            f"This breaks the empty-string and whitespace-only contract — multiple "
            f"existing tests deliberately exercise those inputs."
        )
        assert "maxLength" not in name_prop, (
            f"HelloRequest.name gained a maxLength constraint: {name_prop.get('maxLength')!r}. "
            f"This breaks the 50_000-char echo contract in TestNameEchoBoundaries."
        )

    def test_name_property_has_no_pattern_constraint(self, client: TestClient) -> None:
        """``HelloRequest.name`` declares no regex ``pattern`` constraint.

        The endpoint is contractually a verbatim echo (SQL-injection /
        emoji / RTL / control-char tests all depend on this). A
        ``pattern=`` would start rejecting those inputs silently from
        the schema, even before reaching the handler.
        """
        schema = get_openapi_schema(client)
        name_prop = schema["components"]["schemas"]["HelloRequest"]["properties"]["name"]
        assert "pattern" not in name_prop, (
            f"HelloRequest.name gained a pattern constraint: {name_prop.get('pattern')!r}. "
            f"This breaks the verbatim-echo contract for adversarial / Unicode inputs."
        )
        # And the declared type is still plain ``string`` — not a ``string|null``
        # tuple introduced by a stray ``Optional[str]``.
        assert name_prop.get("type") == "string", (
            f"HelloRequest.name lost its plain string type: {name_prop!r}"
        )


class TestPostHello422IsHTTPValidationErrorRef:
    """The POST /api/hello 422 response declares its body schema as a
    ``$ref`` to ``HTTPValidationError``.

    ``TestOpenAPI422SchemaMatchesActual422Body.test_post_hello_openapi_declares_422_response``
    only pins that **some** 422 response is declared. It does not pin
    **how** it is declared — a regression that inlined the schema or
    pointed it at a different (renamed) component would still pass that
    test, but every SDK generator that emits a typed error class would
    silently change its output.
    """

    def test_422_response_uses_http_validation_error_ref(self, client: TestClient) -> None:
        """POST /api/hello 422 response schema is ``$ref`` to ``HTTPValidationError``."""
        schema = get_openapi_schema(client)
        body_schema = schema["paths"]["/api/hello"]["post"]["responses"]["422"]["content"][
            "application/json"
        ]["schema"]
        assert body_schema == {"$ref": "#/components/schemas/HTTPValidationError"}, (
            f"POST /api/hello 422 response schema regressed: got {body_schema!r}, "
            f"expected {{'$ref': '#/components/schemas/HTTPValidationError'}}"
        )


class TestOpenAPISpecVersionPinned:
    """The OpenAPI document declares a top-level ``openapi`` field with
    the spec version.  FastAPI's 0.110+ default is 3.1.0; many SDK
    generators behave differently for 3.0.x vs 3.1.x (notably in how
    they emit nullable and oneOf types).

    Pinning the major.minor (but not the patch) lets a FastAPI patch
    bump through silently while making a 3.0 / 3.1 family change loud.
    """

    def test_openapi_field_is_3_1_family(self, client: TestClient) -> None:
        """``openapi`` field starts with ``3.1.`` — pinning the OpenAPI spec family."""
        schema = get_openapi_schema(client)
        version = schema.get("openapi", "")
        assert isinstance(version, str) and version.startswith("3.1."), (
            f"OpenAPI spec version regressed from the 3.1.x family: got {version!r}. "
            f"A change in the openapi spec family affects every downstream SDK generator."
        )


# ---------------------------------------------------------------------------
# Sunday regression-prevention additions (extending the unpinned-behaviour
# surface uncovered while reviewing the past week's commits).
# ---------------------------------------------------------------------------

# The four (method, path, json_body) request tuples used by the byte-shape
# and Server-header pins below. Sharing one constant keeps the surface
# enumerated in a single place — if a new route ships, this list updates
# once and every shape-level pin picks it up.
ALL_SUCCESSFUL_REQUESTS: list[tuple[str, str, dict[str, str] | None]] = [
    ("GET", "/health", None),
    ("GET", "/api/version", None),
    ("GET", "/api/hello", None),
    ("POST", "/api/hello", {"name": "RegressionPin"}),
]


class TestOperationIdsAreGloballyUnique:
    """Every OpenAPI ``operationId`` is unique across paths × methods.

    SDK generators (``openapi-typescript``, ``openapi-python-client``,
    ``oapi-codegen``) emit **one function per operationId** — a collision
    drops one of the colliding operations from the generated client with
    no warning. FastAPI's default operationId is
    ``{function_name}_{path_with_underscores}_{method}``, which is
    collision-free by construction, but an explicit
    ``operation_id=`` kwarg on a route decorator (a common "give it a
    friendly name" refactor) can silently collide.

    ``TestRegressionOpenAPIRouteMetadata.test_route_operation_id_pinned``
    pins each individual value but does **not** assert that the four
    values are distinct from each other. Pinning uniqueness explicitly
    documents the SDK-generation contract.
    """

    def test_every_operation_has_a_unique_operation_id(self, client: TestClient) -> None:
        """No two (path, method) operations share an ``operationId``."""
        schema = get_openapi_schema(client)
        seen: dict[str, tuple[str, str]] = {}
        for path, methods in schema["paths"].items():
            for method, op in methods.items():
                if not isinstance(op, dict) or "operationId" not in op:
                    continue
                op_id = op["operationId"]
                assert op_id not in seen, (
                    f"operationId {op_id!r} appears on both "
                    f"{seen[op_id][0].upper()} {seen[op_id][1]} and "
                    f"{method.upper()} {path} — SDK generators emit one "
                    f"function per operationId and would silently drop one."
                )
                seen[op_id] = (method, path)


class TestOpenAPITopLevelKeysPinned:
    """The OpenAPI document exposes exactly the expected top-level keys.

    ``TestRegressionMessageFormat`` and ``TestOpenAPIInfoBlockInventory``
    pin the **contents** of ``info``, ``paths`` and ``components``, but
    the set of **top-level keys themselves** is unpinned. A regression
    that adds a ``servers=`` argument to ``FastAPI(...)`` would silently
    introduce a ``servers`` block into every SDK's generated client base
    URL — the kind of "well-intentioned" change that surfaces only
    when a deploy points at the wrong environment.

    Pin both halves of the contract:

    * Required top-level keys are present.
    * Optional top-level keys (``servers``, ``security``, ``externalDocs``,
      ``webhooks``, ``tags``, ``jsonSchemaDialect``) are absent — adding
      any of them changes the public surface.
    """

    def test_required_top_level_keys_present(self, client: TestClient) -> None:
        """``openapi``, ``info``, ``paths`` and ``components`` are all present."""
        schema = get_openapi_schema(client)
        required = {"openapi", "info", "paths", "components"}
        missing = required - set(schema)
        assert not missing, (
            f"OpenAPI document is missing required top-level keys {missing} — "
            f"a base structural contract regression."
        )

    @pytest.mark.parametrize(
        "optional_key",
        [
            "servers",
            "security",
            "externalDocs",
            "webhooks",
            "tags",
            "jsonSchemaDialect",
        ],
    )
    def test_optional_top_level_keys_absent(self, client: TestClient, optional_key: str) -> None:
        """Optional top-level OpenAPI keys are absent — public surface stays minimal.

        Each of these keys, when present, has consumer-visible side
        effects:

        * ``servers`` rewrites every SDK's base URL.
        * ``security`` adds an auth requirement clients must satisfy.
        * ``externalDocs`` adds a link many docs UIs surface prominently.
        * ``webhooks`` is OpenAPI 3.1's reverse-callback surface — adding
          it implies the server invokes callers, a major capability bump.
        * ``tags`` at the document level (vs. per-operation tags, which
          *are* used today) controls tag grouping in Swagger UI.
        * ``jsonSchemaDialect`` switches the validation dialect for every
          consumer.
        """
        schema = get_openapi_schema(client)
        assert optional_key not in schema, (
            f"OpenAPI document gained a top-level {optional_key!r} key — "
            f"public surface changed in a consumer-visible way. If this is "
            f"intentional, update test_optional_top_level_keys_absent."
        )


class TestResponseBodyHasNoTrailingNewline:
    """Successful response bodies end at the closing ``}`` byte — no
    trailing newline.

    Some web frameworks (and many hand-written wrappers) append ``\\n``
    to JSON responses "for readability". A trailing newline:

    * Inflates the Content-Length by one byte on every response.
    * Confuses byte-exact comparison in ``TestOpenAPISchemaByteStability``
      and the existing flakiness suite.
    * Can produce subtle bugs in HTTP/2 clients that count bytes for
      flow control.

    FastAPI's default response (``JSONResponse``) does **not** append
    a newline. Pin that contract directly so a regression to a custom
    response class (``ORJSONResponse`` with ``indent=2``, or a manual
    ``Response`` with ``"\\n"`` concatenated) fails here.
    """

    @pytest.mark.parametrize(
        "method,path,json_body",
        ALL_SUCCESSFUL_REQUESTS,
        ids=["health", "version", "hello_get", "hello_post"],
    )
    def test_response_body_ends_with_closing_brace_byte(
        self,
        client: TestClient,
        method: str,
        path: str,
        json_body: dict[str, str] | None,
    ) -> None:
        """The last byte of every 200 body is ``}`` (no trailing newline / whitespace)."""
        response = client.request(method, path, json=json_body)
        assert response.status_code == 200
        assert response.content.endswith(b"}"), (
            f"{method} {path} body does not end with '}}' — trailing bytes were "
            f"{response.content[-8:]!r}. Likely a response class change added a "
            f"trailing newline or pretty-print whitespace."
        )


class TestServerHeaderNotEmitted:
    """No ``Server`` header is emitted on any response.

    ``TestClient`` runs Starlette directly (no uvicorn), so the Server
    header would only appear if FastAPI / Starlette itself set one — or
    if a future middleware (a "Powered-By: FastAPI" marketing header)
    explicitly added it. Pinning the absence guards against:

    * Server-software fingerprinting being silently re-enabled.
    * A custom middleware (e.g. for proxy hop counting) leaking the
      header to clients.
    """

    @pytest.mark.parametrize(
        "method,path,json_body",
        ALL_SUCCESSFUL_REQUESTS,
        ids=["health", "version", "hello_get", "hello_post"],
    )
    def test_no_server_header_on_200_responses(
        self,
        client: TestClient,
        method: str,
        path: str,
        json_body: dict[str, str] | None,
    ) -> None:
        """``Server`` header is absent on every successful response."""
        response = client.request(method, path, json=json_body)
        assert response.status_code == 200
        lower_headers = {k.lower() for k in response.headers}
        assert "server" not in lower_headers, (
            f"{method} {path} returned a Server header "
            f"({response.headers.get('server')!r}) — server-software "
            f"fingerprinting should stay disabled."
        )


class TestAcceptHeaderIgnoredOnPost:
    """Content negotiation is also disabled on the **POST** path.

    ``TestAcceptHeaderIgnored`` (in ``test_edge_cases.py``) pins this
    on ``GET /health`` only. POST has a request body — a future change
    that wires content negotiation based on ``Accept`` could plausibly
    treat the two paths differently (e.g. negotiate on writes but not
    reads, to avoid breaking ``/health``). Pin the POST side too so the
    contract is uniform.
    """

    @pytest.mark.parametrize(
        "accept_header",
        ["text/html", "application/xml", "application/json;q=0, text/html"],
    )
    def test_post_hello_with_non_json_accept_still_returns_json(
        self, client: TestClient, accept_header: str
    ) -> None:
        """``POST /api/hello`` with non-JSON ``Accept`` still returns JSON 200."""
        response = client.post(
            "/api/hello",
            json={"name": "Alice"},
            headers={"Accept": accept_header},
        )
        assert response.status_code == 200, (
            f"POST with Accept: {accept_header!r} returned "
            f"{response.status_code} — content negotiation may have been added"
        )
        assert response.headers.get("content-type") == "application/json"


class TestNullOriginOnPostNotAllowlisted:
    """``Origin: null`` is rejected on the **POST** path too.

    ``TestNullOriginNotAllowlisted`` covers ``GET /health`` and the
    preflight on ``/api/hello``. The real POST request itself (the one
    that actually mutates / receives the body) is unpinned. A regression
    that re-uses request-level origin matching distinct from preflight
    matching (e.g. a custom middleware that allow-lists ``"null"`` for
    "developer convenience") would slip past the GET pin and the
    preflight pin while breaking the POST contract.
    """

    def test_post_with_null_origin_receives_no_acao(self, client: TestClient) -> None:
        """``POST /api/hello`` with ``Origin: null`` returns no ``Access-Control-Allow-Origin``."""
        response = client.post(
            "/api/hello",
            json={"name": "Alice"},
            headers={"Origin": "null"},
        )
        # Request succeeds (CORS is enforced by the browser, not the server),
        # but the security-relevant header is absent.
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") is None, (
            "POST with Origin: null received an Access-Control-Allow-Origin "
            "header — sandboxed iframes / file:// pages would gain CORS access."
        )


class TestAdditionalSpuriousURLsReturn404:
    """Convention-named URLs the app does not serve must 404.

    Extends ``TestSpuriousURLsReturn404`` (which covers ``/openapi.yaml``,
    ``/favicon.ico``, ``/he%20alth``) with five more URLs that a static-files
    middleware, a route-prefix regression, or a "catch-all" fallback handler
    could silently start answering:

    * ``/robots.txt`` and ``/sitemap.xml`` — SEO-related URLs many web
      frameworks serve by default.
    * ``/`` — root URL; if a future ``HTMLResponse`` landing page is mounted
      there, it should be a deliberate choice, not an accident from a
      mis-configured static-files mount.
    * ``/api`` and ``/api/`` — common-prefix "directory" URLs that some
      routers will silently 200 on as a listing page.
    """

    @pytest.mark.parametrize(
        "spurious_path",
        ["/robots.txt", "/sitemap.xml", "/", "/api", "/api/"],
    )
    def test_spurious_url_returns_404(self, client: TestClient, spurious_path: str) -> None:
        """``GET {spurious_path}`` returns 404 — only the documented routes are served."""
        response = client.get(spurious_path)
        assert response.status_code == 404, (
            f"{spurious_path!r} unexpectedly returned {response.status_code} — "
            f"a static-files middleware or catch-all route may have been added."
        )


class TestPostQueryStringWithoutBodyIs422:
    """``POST /api/hello?name=Bob`` with **no body** returns 422.

    ``TestPostQueryStringIgnored`` (Saturday) pins that the query
    string is ignored *when a body is present*. The complementary case
    — query string with **no** body — is unpinned. A regression that
    introduced a ``Query()`` parameter named ``name`` on the POST
    handler (perhaps reusing the variable name from the body model)
    would silently start succeeding here with ``"Hello, Bob!"``,
    breaking the body-only contract pinned by Saturday's test.
    """

    def test_post_hello_with_query_only_returns_422(self, client: TestClient) -> None:
        """``POST /api/hello?name=Bob`` without a JSON body returns 422 (body required)."""
        response = client.post("/api/hello?name=Bob")
        assert response.status_code == 422, (
            f"POST /api/hello?name=Bob without a body returned {response.status_code} — "
            f"the request body is no longer required, possibly because a Query() "
            f"parameter was introduced on the handler."
        )


class TestHelloRequestNameLiteralNullIs422:
    """``{"name": null}`` returns 422 — Pydantic does not coerce ``None`` to ``"None"``.

    ``HelloRequest.name`` is typed ``str`` (not ``Optional[str]``), so
    a literal JSON ``null`` fails validation. Several tests deliberately
    submit unusual *string* values (empty string, whitespace, 50K chars)
    — pinning the **null** case explicitly catches a regression that
    silently widened the type to ``str | None``, which would start
    rendering ``"Hello, None!"`` to clients passing null on accident.
    """

    def test_post_with_null_name_returns_422(self, client: TestClient) -> None:
        """``POST /api/hello`` with body ``{"name": null}`` returns 422."""
        response = client.post("/api/hello", json={"name": None})
        assert response.status_code == 422, (
            f"POST with {{'name': null}} returned {response.status_code} — "
            f"HelloRequest.name may have silently become Optional[str], which "
            f"would let null inputs render as 'Hello, None!' to real clients."
        )


class TestHealthTrailingSlashReturnsSameShape:
    """``/health/`` and ``/health`` return bodies with the same key set
    and the same ``status`` field.

    ``TestPathRouting.test_health_with_trailing_slash_succeeds`` (and
    Saturday's ``TestTrailingSlashOnAllEndpoints``) pin **status codes**
    of 200, but neither asserts that the **body shape** is the same on
    both URL forms. A future ``redirect_slashes=False`` plus a hand-rolled
    fallback handler for the trailing-slash form could plausibly return a
    different body shape (e.g. an HTML redirect notice, or a stripped
    response) while keeping the status at 200. Pinning shape equivalence
    catches that.

    The ``timestamp`` field deliberately differs across calls (different
    instants of ``datetime.now(UTC)``), so the comparison is
    shape-level only.
    """

    def test_health_trailing_slash_returns_same_keys_and_status(self, client: TestClient) -> None:
        """``/health/`` and ``/health`` return the same key set and status value."""
        no_slash = client.get("/health").json()
        with_slash = client.get("/health/").json()
        assert set(no_slash) == set(with_slash), (
            f"/health/ returned keys {set(with_slash)}, /health returned "
            f"{set(no_slash)} — trailing-slash form is no longer the same handler."
        )
        assert no_slash["status"] == with_slash["status"], (
            f"/health/ status {with_slash['status']!r} != /health status "
            f"{no_slash['status']!r} — different code paths."
        )


# ---------------------------------------------------------------------------
# 2026-05-31 Sunday regression-prevention additions: behaviours exercised by
# the past week's commits (#242–#258) but left unpinned by them.
# ---------------------------------------------------------------------------

# Forbidden response headers shared between ``TestResponseHeaderHygiene`` (in
# ``test_edge_cases.py``, /health-only) and the two new hygiene pins below.
# Centralised so that adding a fifth forbidden header touches one tuple
# instead of three parametrize blocks.
FORBIDDEN_RESPONSE_HEADERS: list[tuple[str, str]] = [
    ("set-cookie", "app is stateless — no server-side session"),
    ("x-powered-by", "framework fingerprint — should not be advertised"),
    ("strict-transport-security", "HSTS belongs at the edge, not the app"),
    ("x-frame-options", "framing policy belongs at the edge, not the app"),
]

# All non-/health public routes — the surfaces ``TestResponseHeaderHygiene``
# leaves uncovered. Listed verbatim rather than imported from another file so a
# future route addition is visible at the test site.
NON_HEALTH_SUCCESS_REQUESTS: list[tuple[str, str, dict[str, str] | None]] = [
    ("GET", "/api/version", None),
    ("GET", "/api/hello", None),
    ("POST", "/api/hello", {"name": "HygieneCheck"}),
    ("GET", "/openapi.json", None),
]


class TestHelloResponseKeysAreExactlyDocumentedSet:
    """GET and POST ``/api/hello`` return JSON bodies whose key set is
    **exactly** ``{"message", "timestamp"}``.

    ``test_hello_name_extra_fields_ignored`` (test_main.py) asserts that
    the *request body* extra fields don't break the call, but only checks
    ``"Alice" in response.json()["message"]`` — never the *response* key
    set. An ergonomic refactor like
    ``return {**request.model_dump(), "message": ..., "timestamp": ...}``
    would leak request keys into the documented response, and FastAPI's
    ``response_model=HelloResponse`` coercion would filter them at the
    boundary today, but no test directly pins that filter's outcome.
    A regression that dropped ``response_model=`` on the route would
    silently start echoing every request key.
    """

    def test_get_hello_response_keys_are_exactly_message_and_timestamp(
        self, client: TestClient
    ) -> None:
        """``GET /api/hello`` returns exactly ``{"message", "timestamp"}`` — no more, no less."""
        response = client.get("/api/hello")
        assert response.status_code == 200
        body = response.json()
        assert set(body.keys()) == {"message", "timestamp"}, (
            f"GET /api/hello response key set is {set(body.keys())}, expected "
            f"exactly {{'message', 'timestamp'}}. A new key on the documented "
            f"response is a public-contract change."
        )

    def test_post_hello_response_keys_are_exactly_message_and_timestamp(
        self, client: TestClient
    ) -> None:
        """``POST /api/hello`` returns exactly ``{"message", "timestamp"}`` — no more, no less."""
        response = client.post("/api/hello", json={"name": "Alice"})
        assert response.status_code == 200
        body = response.json()
        assert set(body.keys()) == {"message", "timestamp"}, (
            f"POST /api/hello response key set is {set(body.keys())}, expected "
            f"exactly {{'message', 'timestamp'}}. A new key on the documented "
            f"response is a public-contract change."
        )

    def test_post_hello_extra_request_field_does_not_leak_into_response(
        self, client: TestClient
    ) -> None:
        """A request-body ``stowaway`` field is not echoed in the response body.

        Pydantic v2's default ``extra='ignore'`` drops it at parse time, and
        FastAPI's ``response_model=HelloResponse`` filters it at the response
        boundary. Either layer alone is sufficient today, but pinning the
        end-to-end outcome catches a refactor that breaks both.
        """
        response = client.post(
            "/api/hello",
            json={"name": "Alice", "stowaway": "should-not-appear", "another": 42},
        )
        assert response.status_code == 200
        body = response.json()
        # No key leaks through.
        assert "stowaway" not in body, (
            f"'stowaway' request field appeared in response body: {body!r}. "
            f"The response_model boundary or Pydantic ignore behaviour regressed."
        )
        assert "another" not in body
        # And no value leaks anywhere in the body either (catches a refactor
        # that wrapped extras into a sub-field like ``{"extras": {...}}``).
        body_text = response.text
        assert "stowaway" not in body_text
        assert "should-not-appear" not in body_text


class TestResponseHeaderHygieneAcrossAllRoutes:
    """The four-header hygiene contract pinned for ``GET /health`` in
    ``TestResponseHeaderHygiene`` (test_edge_cases.py) holds uniformly on
    every non-/health route too.

    A regression that wired a "smart" middleware injecting
    ``X-Powered-By: FastAPI/Starlette`` (or ``Set-Cookie`` for debug
    tracing) to only the API routes — or only the schema URL — would
    slip past the /health-only Saturday pin entirely. Extend the same
    four-header guarantee to ``GET /api/version``, ``GET /api/hello``,
    ``POST /api/hello`` and ``GET /openapi.json``.
    """

    @pytest.mark.parametrize(
        "method,path,json_body",
        NON_HEALTH_SUCCESS_REQUESTS,
        ids=["version", "hello_get", "hello_post", "openapi_json"],
    )
    @pytest.mark.parametrize(
        "forbidden_header,why",
        FORBIDDEN_RESPONSE_HEADERS,
        ids=[h for h, _ in FORBIDDEN_RESPONSE_HEADERS],
    )
    def test_non_health_route_omits_forbidden_header(
        self,
        client: TestClient,
        method: str,
        path: str,
        json_body: dict[str, str] | None,
        forbidden_header: str,
        why: str,
    ) -> None:
        """The named forbidden header is absent on the given non-/health route."""
        response = client.request(method, path, json=json_body)
        assert response.status_code == 200
        lower_headers = {k.lower() for k in response.headers}
        assert forbidden_header not in lower_headers, (
            f"{method} {path} unexpectedly emitted {forbidden_header!r} — {why}. "
            f"Got headers: {dict(response.headers)!r}"
        )


class TestOptionsWithOriginOnlyOmitsExposeHeaders:
    """The half-CORS 405 fall-through path also omits
    ``Access-Control-Expose-Headers``.

    ``TestNoExposeHeadersAdvertised`` (test_integration_gaps.py) pins the
    absence on GET, POST, and the *real* preflight (Origin + ACRM). The
    fourth response shape produced by the CORS surface — OPTIONS with
    ``Origin`` only, no ``Access-Control-Request-Method`` — is
    structurally distinct: CORSMiddleware classifies it as a non-preflight
    and the router emits a 405, which CORSMiddleware then wraps with
    allow-origin headers on the way out. That wrap-on-the-way-out path
    is the most plausible place a future ``expose_headers=`` config
    would first leak through, because it re-enters CORSMiddleware's
    response-header logic from a different branch than the preflight
    case the Wednesday pin covers.
    """

    def test_options_with_origin_only_omits_expose_headers(self, client: TestClient) -> None:
        """OPTIONS with only ``Origin`` returns 405 without ``Access-Control-Expose-Headers``."""
        response = client.options("/api/hello", headers={"Origin": LOCALHOST_ORIGIN})
        # Confirms the 405 fall-through path is still the one being exercised
        # (so the assertion below pins the right response shape).
        assert response.status_code == 405, (
            f"OPTIONS with Origin only no longer returns 405 (got {response.status_code}); "
            f"the half-CORS fall-through behaviour has changed and this pin "
            f"must be reviewed against TestOPTIONSWithOriginButNoACRMFallsThrough."
        )
        assert response.headers.get("access-control-expose-headers") is None, (
            f"Half-CORS 405 response unexpectedly advertised "
            f"Access-Control-Expose-Headers="
            f"{response.headers.get('access-control-expose-headers')!r} — "
            f"the CORS middleware likely gained an expose_headers= config."
        )


# Error-response request specs reused by the two error-path pins below.
# Each tuple is (method, path, json_body, expected_status) — pinning each
# request to its expected error status keeps the parametrize ids readable
# and the failure messages self-describing.
ERROR_RESPONSE_REQUESTS: list[tuple[str, str, dict[str, str] | None, int]] = [
    # POST /api/hello with no body — Pydantic raises 422 (body required).
    ("POST", "/api/hello", None, 422),
    # Spurious URL — FastAPI emits 404 with detail "Not Found".
    ("GET", "/spurious-regression-pin-url", None, 404),
    # Disallowed method on a real route — Starlette emits 405 with
    # detail "Method Not Allowed".
    ("DELETE", "/health", None, 405),
]


class TestErrorResponseContentLengthMatchesBody:
    """``Content-Length`` on 422 / 404 / 405 responses equals
    ``len(response.content)``.

    ``TestContentLengthMatchesResponseBody`` (test_edge_cases.py) pins
    the byte-length match on the five 200 response routes today. Error
    responses (422 from validation, 404 from routing, 405 from method
    rejection) are emitted by FastAPI / Starlette's *separate* error
    handlers, not the route handlers — a future custom error response
    (a per-app JSON-API error envelope, say) could drift on the header
    without touching the success path. Pin the contract symmetrically
    on the error side.
    """

    @pytest.mark.parametrize(
        "method,path,json_body,expected_status",
        ERROR_RESPONSE_REQUESTS,
        ids=["422_post_no_body", "404_spurious", "405_disallowed_method"],
    )
    def test_error_response_content_length_matches_body_byte_length(
        self,
        client: TestClient,
        method: str,
        path: str,
        json_body: dict[str, str] | None,
        expected_status: int,
    ) -> None:
        """``Content-Length`` equals ``len(response.content)`` on the error response."""
        response = client.request(method, path, json=json_body)
        assert response.status_code == expected_status, (
            f"{method} {path} returned {response.status_code}, expected {expected_status} "
            f"— the test request no longer hits the documented error path."
        )
        declared = response.headers.get("content-length")
        assert declared is not None, (
            f"{method} {path} ({expected_status}) did not emit a Content-Length header "
            f"— strict HTTP/1.1 clients that count bytes will block waiting for EOF."
        )
        assert int(declared) == len(response.content), (
            f"{method} {path} ({expected_status}) Content-Length={declared} but body "
            f"is {len(response.content)} bytes — header/body length mismatch on "
            f"the error path."
        )


class TestErrorResponsesAlsoOmitForbiddenHeaders:
    """The forbidden-header hygiene contract holds on 422 / 404 / 405
    responses too.

    ``TestResponseHeaderHygiene`` covers 200 ``GET /health`` only;
    ``TestResponseHeaderHygieneAcrossAllRoutes`` (above) extends it to
    the other 200 routes. Error responses come from a different
    Starlette code path (the exception handlers, not the route
    handlers) and could be wrapped by a future error-formatting
    middleware that emits ``Set-Cookie: trace_id=...`` "for debugging"
    — invisible to every 200-only pin.
    """

    @pytest.mark.parametrize(
        "method,path,json_body,expected_status",
        ERROR_RESPONSE_REQUESTS,
        ids=["422_post_no_body", "404_spurious", "405_disallowed_method"],
    )
    @pytest.mark.parametrize(
        "forbidden_header,why",
        FORBIDDEN_RESPONSE_HEADERS,
        ids=[h for h, _ in FORBIDDEN_RESPONSE_HEADERS],
    )
    def test_error_response_omits_forbidden_header(
        self,
        client: TestClient,
        method: str,
        path: str,
        json_body: dict[str, str] | None,
        expected_status: int,
        forbidden_header: str,
        why: str,
    ) -> None:
        """The named forbidden header is absent on the given error response."""
        response = client.request(method, path, json=json_body)
        assert response.status_code == expected_status
        lower_headers = {k.lower() for k in response.headers}
        assert forbidden_header not in lower_headers, (
            f"{method} {path} ({expected_status}) unexpectedly emitted "
            f"{forbidden_header!r} — {why}. Got headers: {dict(response.headers)!r}"
        )


class TestSpuriousURL404IsJSON:
    """The 404 bodies emitted for the convention-named URLs pinned by
    ``TestAdditionalSpuriousURLsReturn404`` (last Sunday) are JSON
    ``{"detail": "Not Found"}``, not HTML.

    The Sunday pin only checks ``status_code == 404``. A regression that
    added a static-files middleware mounting a ``404.html`` page (or a
    catch-all that rendered a friendly HTML error) would still return
    404 — passing the existing pin — while breaking every JSON-only
    consumer that introspects ``error.detail``.
    """

    @pytest.mark.parametrize(
        "spurious_path",
        ["/robots.txt", "/sitemap.xml", "/", "/api", "/api/"],
    )
    def test_spurious_url_404_is_documented_json(
        self, client: TestClient, spurious_path: str
    ) -> None:
        """``GET {spurious_path}`` 404 is JSON ``{"detail": "Not Found"}`` with JSON content-type."""
        response = client.get(spurious_path)
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/json"), (
            f"{spurious_path!r} 404 content-type is "
            f"{response.headers.get('content-type')!r} — a static-files or "
            f"catch-all middleware likely started serving HTML 404s."
        )
        assert response.json() == {"detail": "Not Found"}, (
            f"{spurious_path!r} 404 body is {response.json()!r}, expected "
            f"{{'detail': 'Not Found'}} — the documented FastAPI 404 envelope."
        )


class TestCORSPreflightContentLengthMatchesBody:
    """The 200 preflight response declares a ``Content-Length`` equal to
    ``len(response.content)``.

    ``TestContentLengthMatchesResponseBody`` deliberately enumerates
    five success routes but excludes the OPTIONS preflight (a different
    response shape — empty body, generated by CORSMiddleware rather
    than a route handler). A regression that omitted ``Content-Length``
    on the preflight (or set it to a non-zero value when the body is
    empty) would break HTTP/1.1 clients that count bytes to detect
    message end on a kept-alive connection — Chrome ignores this,
    so the regression would only surface in CI for custom integration
    test harnesses that read socket bytes directly.
    """

    def test_preflight_content_length_matches_empty_body(self, client: TestClient) -> None:
        """``OPTIONS /api/hello`` preflight ``Content-Length`` matches body byte length."""
        response = client.options(
            "/api/hello",
            headers=cors_preflight_headers("POST"),
        )
        assert response.status_code == 200
        declared = response.headers.get("content-length")
        assert declared is not None, (
            "CORS preflight did not emit a Content-Length header — HTTP/1.1 "
            "clients keeping the connection alive will block waiting for EOF."
        )
        assert int(declared) == len(response.content), (
            f"Preflight Content-Length={declared} but body is "
            f"{len(response.content)} bytes — header/body length mismatch."
        )


# Every registered path, paired with HTTP methods that are *not* registered on
# it and therefore must yield a 405. DELETE/PUT/PATCH are registered nowhere in
# the app, so they exercise the method-not-allowed path on every route without
# overlapping the HEAD-405 surface already pinned in
# ``test_routing_integration_gaps.py``.
ALL_ROUTE_PATHS: list[str] = ["/health", "/api/version", "/api/hello"]
DISALLOWED_METHODS: list[str] = ["DELETE", "PUT", "PATCH"]

# Routes that serve a body on a 2xx happy path, paired with a method/payload
# that reaches the handler. Used to pin that ``Allow`` is a 405-only header and
# never leaks onto a successful response.
SUCCESSFUL_REQUESTS: list[tuple[str, str, dict[str, str] | None]] = [
    ("GET", "/health", None),
    ("GET", "/api/version", None),
    ("GET", "/api/hello", None),
    ("POST", "/api/hello", {"name": "AllowCheck"}),
]


class TestMethodNotAllowedAllowHeaderExactSurface:
    """The 405 ``Allow`` header advertises *exactly* ``GET`` on every route —
    including ``/api/hello``, whose ``POST`` is a valid method that the header
    nonetheless omits.

    ``test_routing_integration_gaps.py`` (Wednesday) pins HEAD→405 with a
    substring check — ``"GET" in allow`` — on ``/health`` only. That leaves the
    machine-readable method advertisement under-pinned in two orthogonal ways
    that downstream tooling (HTTP clients that retry against advertised methods,
    API-surface diff tools, OpenAPI-vs-runtime auditors) actually reads:

    1. **The exact value, route-wide.** A substring match on one route would
       still pass if a regression appended a bogus method (``"GET, TRACE"``) or
       changed the value on ``/api/version``. These tests pin string-equality
       (``== "GET"``) across *every* route and *every* disallowed method.

    2. **The surprising ``POST`` omission on ``/api/hello``.** ``@app.get`` and
       ``@app.post`` register ``/api/hello`` as **two separate ``APIRoute``
       objects**, not one route with ``methods={"GET", "POST"}``. Starlette's
       router builds the ``Allow`` header from the *first* path-matching route
       it encounters, so a ``DELETE /api/hello`` reports ``Allow: GET`` and
       silently drops the equally-valid ``POST``. Nothing pins this; a Starlette
       upgrade that aggregated partial matches into the union ``GET, POST`` —
       or a refactor merging the two handlers into one multi-method route —
       would change the advertised surface in a way no current test would catch.
       The contract is pinned *in both directions*: the value is ``GET`` today,
       and ``POST`` (proven valid by a paired 200) is absent.
    """

    @pytest.mark.parametrize("path", ALL_ROUTE_PATHS)
    @pytest.mark.parametrize("method", DISALLOWED_METHODS)
    def test_405_allow_header_is_exactly_get(
        self, client: TestClient, method: str, path: str
    ) -> None:
        """``{method} {path}`` → 405 whose ``Allow`` header equals exactly ``GET``."""
        response = client.request(method, path)
        assert response.status_code == 405, (
            f"{method} {path} should be 405 (method not registered); got {response.status_code}"
        )
        allow = response.headers.get("allow")
        assert allow is not None, (
            f"{method} {path} 405 is missing the Allow header (RFC 7231 §6.5.5 requires it)."
        )
        assert allow.strip() == "GET", (
            f"{method} {path} 405 advertises Allow: {allow!r}, expected exactly 'GET' — "
            f"a stray/extra method in the Allow header is a router-surface regression."
        )

    def test_hello_405_allow_omits_post_despite_post_being_valid(self, client: TestClient) -> None:
        """``DELETE /api/hello`` advertises ``Allow: GET`` even though POST is valid.

        This is the headline surprise: ``/api/hello`` accepts POST (proven by the
        paired 200 below), yet its 405 ``Allow`` header lists only ``GET`` because
        Starlette reports the first path-matching route's methods, not the union.
        Pinning both halves means a change in *either* direction — the framework
        starting to advertise ``GET, POST``, or POST silently ceasing to be a
        valid method — fails this test and gets a human's eyes.
        """
        # POST is genuinely a valid, registered method on this path...
        ok = client.post("/api/hello", json={"name": "AllowProof"})
        assert ok.status_code == 200, (
            "Precondition failed: POST /api/hello must be a valid 200 for this "
            f"omission pin to be meaningful; got {ok.status_code}."
        )
        # ...yet the 405 Allow header for a disallowed method omits it entirely.
        not_allowed = client.delete("/api/hello")
        assert not_allowed.status_code == 405
        allow = not_allowed.headers.get("allow", "")
        assert allow.strip() == "GET", (
            f"DELETE /api/hello 405 Allow is {allow!r}; expected 'GET'. If this now "
            f"reads 'GET, POST', Starlette's partial-match aggregation changed — "
            f"review whether the new advertised surface is intended."
        )
        assert "POST" not in allow, (
            f"DELETE /api/hello 405 Allow unexpectedly contains POST ({allow!r}). "
            f"This documents Starlette's first-route-wins behaviour; a change here "
            f"is a framework-surface regression to review, not silently accept."
        )

    @pytest.mark.parametrize("path", ALL_ROUTE_PATHS)
    @pytest.mark.parametrize("method", DISALLOWED_METHODS)
    def test_405_allow_header_is_always_present(
        self, client: TestClient, method: str, path: str
    ) -> None:
        """Every 405 carries a non-empty ``Allow`` header (RFC 7231 §7.4.1 MUST)."""
        response = client.request(method, path)
        assert response.status_code == 405
        allow = response.headers.get("allow")
        assert allow is not None and allow.strip() != "", (
            f"{method} {path} 405 has an absent/empty Allow header ({allow!r}); a "
            f"405 without Allow violates RFC 7231 and breaks clients that branch "
            f"on the advertised method list to decide a fallback request."
        )

    @pytest.mark.parametrize("method,path,payload", SUCCESSFUL_REQUESTS)
    def test_2xx_responses_omit_allow_header(
        self,
        client: TestClient,
        method: str,
        path: str,
        payload: dict[str, str] | None,
    ) -> None:
        """``Allow`` is a 405-only advertisement and never leaks onto a 2xx body.

        ``Allow`` describes the rejection of a disallowed method; a successful
        response has no business carrying it. A middleware that began emitting
        ``Allow`` unconditionally would confuse caches and method-discovery
        tooling, so the absence on the happy path is itself a contract.
        """
        response = client.request(method, path, json=payload)
        assert response.status_code == 200
        assert "allow" not in {k.lower() for k in response.headers}, (
            f"{method} {path} 200 unexpectedly carries an Allow header "
            f"({response.headers.get('allow')!r}); Allow belongs on 405s only."
        )

    @pytest.mark.parametrize("method", DISALLOWED_METHODS + ["HEAD", "POST"])
    def test_404_unknown_path_has_no_allow_header(self, client: TestClient, method: str) -> None:
        """A 404 (no matching route) carries no ``Allow`` header, unlike a 405.

        The Allow header is the wire-level signal that distinguishes *"the
        resource exists but not for this method"* (405 + Allow) from *"no such
        resource"* (404, no Allow). A catch-all route or middleware that started
        answering unknown paths with a 405-style envelope would blur that
        distinction; pinning the 404's absence of Allow keeps the two failure
        modes machine-distinguishable.
        """
        response = client.request(method, "/api/does-not-exist")
        assert response.status_code == 404
        assert "allow" not in {k.lower() for k in response.headers}, (
            f"{method} /api/does-not-exist 404 carries an Allow header "
            f"({response.headers.get('allow')!r}); a 404 must not advertise methods."
        )

    @pytest.mark.parametrize("path", ALL_ROUTE_PATHS)
    def test_405_allow_header_is_request_method_independent(
        self, client: TestClient, path: str
    ) -> None:
        """The ``Allow`` value describes the *route*, so it is identical no matter
        which disallowed method triggered the 405.

        ``Allow`` must enumerate the route's registered methods, never echo the
        offending request method. Driving the same path with DELETE, PUT, and
        PATCH must therefore yield byte-identical Allow headers — a regression
        that accidentally reflected the request method would diverge here.
        """
        allows = {
            method: client.request(method, path).headers.get("allow")
            for method in DISALLOWED_METHODS
        }
        distinct = set(allows.values())
        assert len(distinct) == 1, (
            f"{path} 405 Allow header varies by request method: {allows!r}. The "
            f"Allow header must describe the route's methods, not the request."
        )

    @pytest.mark.asyncio
    async def test_405_allow_header_exact_over_async_transport(
        self, async_client: AsyncClient
    ) -> None:
        """The exact ``Allow: GET`` 405 contract holds over the real ASGI transport.

        The in-process ``TestClient`` and ``httpx.AsyncClient`` + ``ASGITransport``
        drive different response-framing code paths; repeating the headline pin
        over async guards a regression that only manifests under uvicorn (the
        production transport) while the sync client stays green.
        """
        response = await async_client.request("DELETE", "/api/hello")
        assert response.status_code == 405
        assert response.headers.get("allow", "").strip() == "GET", (
            "DELETE /api/hello 405 Allow header diverges from 'GET' over the real "
            f"ASGI transport: {response.headers.get('allow')!r}"
        )
