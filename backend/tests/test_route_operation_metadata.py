"""Pin per-operation OpenAPI metadata not yet asserted elsewhere.

``app/main.py`` is at 100 % line and branch coverage, so the
"coverage-sprint" frontier has moved off Python statements and onto the
**auto-derived OpenAPI surface** that the existing test suite has not yet
pinned. Each metadata slot below is emitted by FastAPI as a side effect of
the route decorator (function docstring, ``response_model=``, no explicit
``security=`` / ``deprecated=`` kwargs, ...) and is therefore invisible to
``pytest --cov`` — a future edit that rewrites a docstring, adds
``security=...`` to a decorator, or flips a route to ``deprecated=True``
ships green today, even though every SDK generator and ``/docs`` consumer
would see the change.

What the test classes below pin (in order):

* ``TestPerOperationDescriptionMatchesHandlerDocstring`` — the
  per-operation ``description`` field is the verbatim ``inspect.cleandoc``
  of the handler docstring. The existing suite already pins ``summary``
  (auto-derived from function name), ``operationId`` (function name +
  path), ``tags`` (decorator kwarg) and the **info-level** ``description``,
  but not the per-operation ``description`` rendered as the body text of
  each ``/docs`` operation panel.

* ``TestEndpointsDeclareNoQueryOrPathParameters`` — no route declares a
  ``parameters`` array today. Adding a query- or path-parameter to a
  handler signature is a backwards-compatible feature on the server but
  generates new arguments in every typed SDK. Pinning the **absence** of
  ``parameters`` makes that addition loud.

* ``TestEndpointsAreNotDeprecated`` — no route declares ``deprecated=True``.
  ``deprecated`` flips ``/docs`` strikethrough styling and SDK generators
  emit ``@deprecated`` annotations. Pinning the absence catches an
  accidental ``@app.get("/health", deprecated=True)``.

* ``TestEndpointsHaveNoSecurityRequirement`` — no route declares a
  ``security`` requirement today. Adding one (e.g. ``Depends(oauth2)``)
  introduces an auth requirement every client must satisfy; pinning the
  absence catches the silent contract change.

* ``TestSuccess200DescriptionIsFastAPIDefault`` — each 200 response's
  ``description`` is the FastAPI default string ``"Successful Response"``.
  A change here means someone has overridden the per-response description
  via ``responses={...}`` on the decorator — a deliberate but
  consumer-visible change worth pinning.

* ``TestSuccess200ResponseDeclaresOnlyApplicationJSON`` — each 200
  response declares exactly one content-type, ``application/json``.
  A regression that flipped a handler to ``response_class=HTMLResponse``
  (or added a streaming-CSV alternative) would silently change the
  Accept-negotiation surface.

* ``TestPostHelloRequestBodyIsRequiredJSON`` — POST /api/hello declares
  ``requestBody.required: true`` and the body content-type is
  ``application/json``. Both flags are auto-derived from the Pydantic
  parameter, and both control whether SDK generators emit the parameter
  as required and how clients set ``Content-Type``.

* ``TestGetEndpointsDeclareOnly200`` — GET endpoints document **exactly**
  one response code, 200. Adding a documented 4xx (e.g. via ``responses=``
  on the decorator) changes the SDK error-handling surface and should be
  explicit.

* ``TestPostHelloDeclaresExactly200And422`` — POST /api/hello documents
  exactly ``{200, 422}``. A new declared code (404, 500) would change
  the SDK exception surface.

Every assertion below verifies a behaviour that is NOT asserted elsewhere
in ``tests/``; the gaps were verified by grepping for each metadata slot
before adding the corresponding pin.
"""

from __future__ import annotations

import inspect

import pytest
from fastapi.testclient import TestClient

from app.main import (
    get_version,
    health_check,
    hello_name,
    hello_world,
)

from .conftest import get_openapi_schema

# (method, path, handler-function) tuples for every user-facing route the
# project ships today. Keeping a single source of truth means a new route
# (or a rename) updates one constant rather than every parametrized id list
# in this module.
ROUTES = [
    ("get", "/health", health_check),
    ("get", "/api/version", get_version),
    ("get", "/api/hello", hello_world),
    ("post", "/api/hello", hello_name),
]

# Parametrize ids reused across many classes — the format mirrors the
# existing project convention ("GET /api/hello" -> "GET /api/hello").
_ROUTE_IDS = [f"{m.upper()} {p}" for (m, p, _) in ROUTES]


class TestPerOperationDescriptionMatchesHandlerDocstring:
    """Each ``paths[path][method].description`` equals the handler docstring.

    FastAPI lifts the function docstring through ``inspect.cleandoc`` and
    plants it as the per-operation ``description`` in OpenAPI. The
    ``/docs`` UI renders it as the body text under each operation, and
    SDK generators emit it as the method docstring / JSDoc.

    A docstring rewrite that "just tightens the wording" therefore changes
    every consumer's generated documentation silently. Pinning the
    description per-operation makes the rewrite visible at test time.
    """

    @pytest.mark.parametrize(
        "method,path,handler",
        ROUTES,
        ids=_ROUTE_IDS,
    )
    def test_operation_description_equals_cleaned_handler_docstring(
        self,
        client: TestClient,
        method: str,
        path: str,
        handler: object,
    ) -> None:
        """``description`` matches ``inspect.cleandoc(handler.__doc__)``."""
        schema = get_openapi_schema(client)
        actual = schema["paths"][path][method].get("description")
        docstring = handler.__doc__ or ""
        expected = inspect.cleandoc(docstring)
        assert actual == expected, (
            f"{method.upper()} {path} description drifted from handler docstring.\n"
            f"got:      {actual!r}\n"
            f"expected: {expected!r}\n"
            f"A handler docstring rewrite silently churns every SDK generator's "
            f"method docstring and the ``/docs`` body text for this operation."
        )


class TestEndpointsDeclareNoQueryOrPathParameters:
    """No declared operation has a ``parameters`` array.

    None of the current handlers take query, path or header parameters,
    so FastAPI emits no ``parameters`` key. The first time a handler
    grows a ``q: str | None = None`` query parameter, a ``parameters``
    array appears — and every typed SDK gains a new (often optional)
    method argument that consumers can pass even when the server stops
    using it. Pinning the absence makes the addition surface explicitly.
    """

    @pytest.mark.parametrize(
        "method,path",
        [(m, p) for (m, p, _) in ROUTES],
        ids=_ROUTE_IDS,
    )
    def test_operation_has_no_parameters_array(
        self, client: TestClient, method: str, path: str
    ) -> None:
        """``paths[path][method]`` does not declare a ``parameters`` key."""
        op = get_openapi_schema(client)["paths"][path][method]
        assert "parameters" not in op, (
            f"{method.upper()} {path} gained a ``parameters`` declaration "
            f"{op.get('parameters')!r}. A new query/path/header parameter "
            f"will appear as a (potentially optional) argument on every "
            f"generated SDK method — update this pin if intentional."
        )


class TestEndpointsAreNotDeprecated:
    """No operation declares ``deprecated: true``.

    The ``deprecated=True`` decorator kwarg controls Swagger UI
    strikethrough rendering and SDK ``@deprecated`` annotations. A
    silent flip ships a "please migrate" message to every consumer.
    The OpenAPI default is ``deprecated`` being either absent or
    ``false`` — we pin both possibilities are non-truthy.
    """

    @pytest.mark.parametrize(
        "method,path",
        [(m, p) for (m, p, _) in ROUTES],
        ids=_ROUTE_IDS,
    )
    def test_operation_is_not_deprecated(self, client: TestClient, method: str, path: str) -> None:
        """``paths[path][method].deprecated`` is absent or falsy."""
        op = get_openapi_schema(client)["paths"][path][method]
        deprecated = op.get("deprecated")
        assert not deprecated, (
            f"{method.upper()} {path} is now marked deprecated={deprecated!r}. "
            f"Swagger UI will render this operation struck through and SDK "
            f"generators emit ``@deprecated`` annotations. Update this pin if "
            f"the deprecation is intentional."
        )


class TestEndpointsHaveNoSecurityRequirement:
    """No operation declares a ``security`` requirement.

    The ``security`` field on an operation lists the auth schemes a
    client must satisfy. The current app declares no security schemes
    and no per-route security; pinning the absence catches the silent
    addition of ``Depends(oauth2_scheme)`` or a global security override.
    """

    @pytest.mark.parametrize(
        "method,path",
        [(m, p) for (m, p, _) in ROUTES],
        ids=_ROUTE_IDS,
    )
    def test_operation_has_no_security_requirement(
        self, client: TestClient, method: str, path: str
    ) -> None:
        """``paths[path][method]`` does not declare a ``security`` key."""
        op = get_openapi_schema(client)["paths"][path][method]
        assert "security" not in op, (
            f"{method.upper()} {path} gained a ``security`` requirement "
            f"{op.get('security')!r}. Every client must now negotiate auth — "
            f"a major public-surface change. Update this pin if intentional."
        )


class TestSuccess200DescriptionIsFastAPIDefault:
    """Each 200 response declares the FastAPI default description.

    FastAPI auto-generates ``"Successful Response"`` as the per-response
    description unless overridden via the ``responses={...}`` decorator
    kwarg. Pinning the default catches a per-route override that would
    surface different copy in the ``/docs`` response section and in any
    SDK generator that emits response docstrings.
    """

    @pytest.mark.parametrize(
        "method,path",
        [(m, p) for (m, p, _) in ROUTES],
        ids=_ROUTE_IDS,
    )
    def test_200_response_description_is_default(
        self, client: TestClient, method: str, path: str
    ) -> None:
        """``responses["200"].description`` is FastAPI's default."""
        op = get_openapi_schema(client)["paths"][path][method]
        actual = op["responses"]["200"].get("description")
        assert actual == "Successful Response", (
            f"{method.upper()} {path} 200-response description regressed: "
            f"got {actual!r}. A ``responses={{200: {{'description': ...}}}}`` "
            f"override on the decorator changed the per-response copy — update "
            f"this pin if intentional."
        )


class TestSuccess200ResponseDeclaresOnlyApplicationJSON:
    """Each 200 response declares exactly one content-type: ``application/json``.

    A response with multiple content-types means the route uses
    content-negotiation (``Accept`` header determines the body format).
    None of the current routes do that. A regression that added
    ``response_class=HTMLResponse`` to one route — or that listed
    multiple media types via the ``responses=`` decorator kwarg —
    would silently expand the negotiation surface.
    """

    @pytest.mark.parametrize(
        "method,path",
        [(m, p) for (m, p, _) in ROUTES],
        ids=_ROUTE_IDS,
    )
    def test_200_response_content_types_are_application_json_only(
        self, client: TestClient, method: str, path: str
    ) -> None:
        """``responses["200"].content`` lists exactly ``application/json``."""
        op = get_openapi_schema(client)["paths"][path][method]
        actual = set(op["responses"]["200"].get("content", {}).keys())
        assert actual == {"application/json"}, (
            f"{method.upper()} {path} 200-response content-types regressed: "
            f"got {actual!r}, expected {{'application/json'}}. A response "
            f"class change or ``responses={{200: {{'content': ...}}}}`` "
            f"override expanded the negotiation surface."
        )


class TestPostHelloRequestBodyIsRequiredJSON:
    """POST /api/hello declares ``requestBody.required: true`` and
    ``application/json`` as the only requestBody content-type.

    The ``required`` flag controls whether typed SDKs mark the body
    parameter optional or required. FastAPI auto-derives ``required: true``
    when the body model has no default, but a future change (e.g.
    ``request: HelloRequest | None = None``) would flip it to
    ``required: false`` silently. The content-type list controls whether
    a client may submit ``application/x-www-form-urlencoded`` or similar;
    auto-derivation gives ``application/json`` only.
    """

    def test_request_body_required_flag_is_true(self, client: TestClient) -> None:
        """``requestBody.required`` is the literal boolean ``True``."""
        op = get_openapi_schema(client)["paths"]["/api/hello"]["post"]
        actual = op["requestBody"].get("required")
        assert actual is True, (
            f"POST /api/hello requestBody.required regressed: got {actual!r}, "
            f"expected True. Likely cause: the body parameter type became "
            f"optional (``HelloRequest | None``) — typed SDKs will now mark "
            f"the body argument as optional."
        )

    def test_request_body_content_types_are_application_json_only(self, client: TestClient) -> None:
        """``requestBody.content`` lists exactly ``application/json``."""
        op = get_openapi_schema(client)["paths"]["/api/hello"]["post"]
        actual = set(op["requestBody"].get("content", {}).keys())
        assert actual == {"application/json"}, (
            f"POST /api/hello requestBody content-types regressed: got "
            f"{actual!r}, expected {{'application/json'}}. A new media type "
            f"(``Form()``, ``File()``, ``UploadFile``) was likely added."
        )


class TestGetEndpointsDeclareOnly200:
    """GET endpoints document exactly one response code, ``200``.

    None of the GET routes consume a body, so FastAPI does not declare a
    422 for them; none of them declare custom 4xx responses today. A
    silent addition of ``responses={500: {...}}`` to a decorator would
    expand the documented error surface — typed SDK generators would
    emit a new exception class. Pinning ``{200}`` makes the addition
    visible.
    """

    @pytest.mark.parametrize(
        "method,path",
        [(m, p) for (m, p, _) in ROUTES if m == "get"],
        ids=[f"GET {p}" for (m, p, _) in ROUTES if m == "get"],
    )
    def test_get_route_declares_only_200_response(
        self, client: TestClient, method: str, path: str
    ) -> None:
        """``responses`` keys for the GET operation are exactly ``{'200'}``."""
        op = get_openapi_schema(client)["paths"][path][method]
        actual = set(op.get("responses", {}).keys())
        assert actual == {"200"}, (
            f"GET {path} response codes regressed: got {actual!r}, "
            f"expected {{'200'}}. A new documented response code expands the "
            f"SDK error-handling surface."
        )


class TestPostHelloDeclaresExactly200And422:
    """POST /api/hello documents exactly ``{200, 422}``.

    FastAPI adds 422 automatically because the route consumes a Pydantic
    body. Any third documented code (404 from a path param, 500 from a
    custom ``responses=`` override) would expand the SDK exception
    surface; any drop (e.g. via ``include_in_schema=False`` on the
    422-default) would shrink it.
    """

    def test_post_hello_response_codes_are_exactly_200_and_422(self, client: TestClient) -> None:
        """``responses`` keys for POST /api/hello are exactly ``{'200','422'}``."""
        op = get_openapi_schema(client)["paths"]["/api/hello"]["post"]
        actual = set(op.get("responses", {}).keys())
        assert actual == {"200", "422"}, (
            f"POST /api/hello response codes regressed: got {actual!r}, "
            f"expected {{'200','422'}}. A new documented response code "
            f"(404, 500, ...) changed the SDK exception surface."
        )


class TestRequestBodyReferencesHelloRequestComponent:
    """POST /api/hello's requestBody schema is ``$ref`` to ``HelloRequest``.

    ``TestOpenAPIPostHelloRequestBodyRequiresNameString`` in the
    integration suite resolves the ``$ref`` and asserts properties of the
    target component, but does not pin **which** component is referenced.
    A handler change that swapped the parameter type to ``dict[str, str]``
    or to a new ``HelloInput`` model would drop the ``$ref`` entirely
    (or point it at a different component) — silently breaking every SDK
    that imports the ``HelloRequest`` type. Pinning the ``$ref`` target
    catches the swap at test time.
    """

    def test_request_body_schema_ref_target_is_hello_request(self, client: TestClient) -> None:
        """``requestBody.content['application/json'].schema['$ref']`` ends in ``HelloRequest``."""
        op = get_openapi_schema(client)["paths"]["/api/hello"]["post"]
        body_schema = op["requestBody"]["content"]["application/json"]["schema"]
        assert body_schema == {"$ref": "#/components/schemas/HelloRequest"}, (
            f"POST /api/hello requestBody schema regressed: got {body_schema!r}, "
            f"expected ``$ref`` to ``#/components/schemas/HelloRequest``. The "
            f"handler parameter type was likely renamed or inlined — every SDK "
            f"that imports ``HelloRequest`` would lose its type binding."
        )


class TestSuccess200ResponseReferencesExpectedComponent:
    """Each 200 response references the expected component schema.

    ``TestOpenAPIComponentInventoryPinned`` pins the **component
    inventory**, and ``TestRegressionResponseModelPresent`` checks
    indirectly that every route has *some* component reference — but
    nothing pins **which** component each 200 response points to.
    A copy-paste mistake that wired ``response_model=HealthResponse``
    onto ``/api/version`` would still pass every other test in the
    suite, while silently breaking SDK clients that decode the body
    against the wrong type.
    """

    EXPECTED_200_COMPONENT = {
        ("get", "/health"): "HealthResponse",
        ("get", "/api/version"): "VersionResponse",
        ("get", "/api/hello"): "HelloResponse",
        ("post", "/api/hello"): "HelloResponse",
    }

    @pytest.mark.parametrize(
        "method,path",
        list(EXPECTED_200_COMPONENT.keys()),
        ids=[f"{m.upper()} {p}" for (m, p) in EXPECTED_200_COMPONENT],
    )
    def test_200_response_schema_ref_target(
        self, client: TestClient, method: str, path: str
    ) -> None:
        """``responses['200'].content['application/json'].schema['$ref']`` targets the documented component."""
        op = get_openapi_schema(client)["paths"][path][method]
        body_schema = op["responses"]["200"]["content"]["application/json"]["schema"]
        expected_name = self.EXPECTED_200_COMPONENT[(method, path)]
        expected_ref = {"$ref": f"#/components/schemas/{expected_name}"}
        assert body_schema == expected_ref, (
            f"{method.upper()} {path} 200-response schema regressed: got "
            f"{body_schema!r}, expected {expected_ref!r}. The ``response_model=`` "
            f"kwarg was likely swapped — clients will decode the body against the "
            f"wrong type."
        )
