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

from .conftest import LOCALHOST_ORIGIN, get_openapi_schema

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
                "Origin": LOCALHOST_ORIGIN,
                "Access-Control-Request-Method": "POST",
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
                "Origin": LOCALHOST_ORIGIN,
                "Access-Control-Request-Method": "POST",
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
