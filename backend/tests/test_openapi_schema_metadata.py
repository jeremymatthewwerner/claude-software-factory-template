"""Pin the OpenAPI **schema metadata** surface that Python line-coverage misses.

Backend line coverage is already at 100% (``app/main.py`` has every statement
and branch exercised). The remaining contract surface lives in the JSON that
FastAPI auto-derives from the source — Pydantic model docstrings, function
names, the ``info`` block inventory — and those fields are emitted by
metaprogramming, not by Python statements, so they are invisible to
``pytest --cov``.

A future edit that renames ``HelloResponse.message`` field, drops a docstring,
or stuffs an extra key into the ``FastAPI(...)`` constructor would currently
ship without any failing test, even though every SDK generator and the
``/docs`` UI would change downstream. This module fills those gaps.

Each test below pins a behaviour that:

* is **not** covered by ``--cov`` (FastAPI derives it without executing a
  statement we own), and
* is **not** asserted anywhere else in the suite — verified by grepping
  ``tests/`` before adding each pin (see commit message for the search
  patterns used).

The grouping mirrors the layers an SDK-generator walks:

* ``TestOpenAPIInfoBlockInventory`` — the top-level ``info`` block.
* ``TestComponentSchemaDescriptionsPinned`` — each Pydantic model's
  docstring → schema ``description``.
* ``TestComponentSchemaTitlesPinned`` — each model's class name → schema
  ``title`` (what generators emit as the TypeScript ``interface`` name).
* ``TestComponentSchemaRequiredFieldsPinned`` — per-model ``required: []``
  arrays.
* ``TestComponentSchemaPropertyTitlesPinned`` — per-field ``title`` strings
  (rendered as ``/docs`` labels and JSDoc names by some generators).
* ``TestPathOperationSummariesPinned`` — FastAPI's auto-derived per-route
  ``summary`` from the handler function name.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import __version__


def _components(client: TestClient) -> dict[str, dict[str, Any]]:
    """Return ``schema["components"]["schemas"]`` for the live OpenAPI doc."""
    schema = client.get("/openapi.json").json()
    components: dict[str, dict[str, Any]] = schema["components"]["schemas"]
    return components


def _operation(client: TestClient, path: str, method: str) -> dict[str, Any]:
    """Return the OpenAPI operation object at ``paths[path][method]``."""
    schema = client.get("/openapi.json").json()
    op: dict[str, Any] = schema["paths"][path][method]
    return op


class TestOpenAPIInfoBlockInventory:
    """The OpenAPI ``info`` block exposes exactly ``title``, ``version`` and
    ``description`` today.

    ``TestRegressionMessageFormat`` pins each of the three values
    individually, but does not pin **the set of keys** — a regression that
    adds a stray ``info.termsOfService`` (e.g. via a future
    ``FastAPI(terms_of_service=...)`` argument) would silently expose a new
    field on every SDK generator's documentation comments and on the
    ``/docs`` UI header. Pinning the inventory makes additions visible.
    """

    EXPECTED_INFO_KEYS: frozenset[str] = frozenset({"title", "version", "description"})

    def test_info_block_keys_are_exactly_expected(self, client: TestClient) -> None:
        """``info`` block contains exactly ``title``, ``version`` and ``description`` — no extras."""
        info: dict[str, Any] = client.get("/openapi.json").json()["info"]
        actual = set(info.keys())
        unexpected = actual - self.EXPECTED_INFO_KEYS
        missing = self.EXPECTED_INFO_KEYS - actual
        assert not unexpected, (
            f"OpenAPI info block exposes unexpected keys {unexpected}. "
            f"A FastAPI constructor argument is publishing a new field — "
            f"either pin it in EXPECTED_INFO_KEYS or remove the constructor arg."
        )
        assert not missing, (
            f"OpenAPI info block is missing expected key(s) {missing} — "
            f"a constructor argument was dropped."
        )

    def test_info_version_equals_app_dunder_version(self, client: TestClient) -> None:
        """``info.version`` equals ``app.__version__`` — pinning the wiring, not the literal.

        ``test_openapi_version_matches_app_version`` in ``TestRegressionMessageFormat``
        already pins this exact wiring, but reaches in through a different
        comparison style; duplicating it here is intentional — the inventory
        test above could pass with an empty-string version, and we want any
        future split of ``__version__`` from the FastAPI ``version=`` arg
        to surface in the same file as the inventory assertion.
        """
        info: dict[str, Any] = client.get("/openapi.json").json()["info"]
        assert info["version"] == __version__, (
            f"info.version regressed: got {info['version']!r}, "
            f"expected {__version__!r} from app/__init__.py"
        )


# Pydantic model class name -> docstring -> OpenAPI schema description.
# The docstring strings below are read verbatim from the Pydantic models in
# ``app.main``; a regression that rewrites a docstring (e.g. for clarity)
# silently changes SDK-generated doc comments downstream.
EXPECTED_COMPONENT_DESCRIPTIONS: dict[str, str] = {
    "HealthResponse": "Health check response.",
    "VersionResponse": "Version information response.",
    "HelloRequest": "Request model for personalized greeting.",
    "HelloResponse": "Response model for greeting.",
}


class TestComponentSchemaDescriptionsPinned:
    """Each Pydantic model in ``app.main`` has a docstring that FastAPI
    surfaces as the schema ``description`` in OpenAPI.

    SDK generators (``openapi-typescript-codegen``, ``swagger-codegen``)
    render these as JSDoc/Python module docstrings on the generated types.
    The existing suite pins the **set** of component names
    (``TestOpenAPIComponentInventoryPinned``) but not their **descriptions**:
    a future "tighten the docstrings" pass that rewrites every model
    docstring would currently pass all tests, while every consumer would
    see their generated documentation churn.
    """

    @pytest.mark.parametrize(
        "model_name,expected_description",
        sorted(EXPECTED_COMPONENT_DESCRIPTIONS.items()),
    )
    def test_component_description_matches_model_docstring(
        self,
        client: TestClient,
        model_name: str,
        expected_description: str,
    ) -> None:
        """``components.schemas[X].description`` matches the Pydantic model docstring."""
        schemas = _components(client)
        assert model_name in schemas, (
            f"{model_name} is missing from OpenAPI components — "
            f"a model rename should be reflected in EXPECTED_COMPONENT_DESCRIPTIONS."
        )
        actual = schemas[model_name].get("description")
        assert actual == expected_description, (
            f"{model_name} description regressed: got {actual!r}, "
            f"expected {expected_description!r}. A model docstring was rewritten — "
            f"SDK-generated doc comments will churn for every downstream consumer."
        )


# Pydantic model class name -> OpenAPI schema ``title`` field. FastAPI
# defaults this to the class name; SDK generators use it as the emitted
# TypeScript ``interface``/Python class name. The existing suite already
# pins that the component is **keyed** by this name in components.schemas
# but does **not** pin the inner ``title`` field — a future
# ``model_config = {"title": "Greeting"}`` override would silently change
# every consumer's generated type name without touching the component key.
EXPECTED_COMPONENT_TITLES: dict[str, str] = {
    "HealthResponse": "HealthResponse",
    "VersionResponse": "VersionResponse",
    "HelloRequest": "HelloRequest",
    "HelloResponse": "HelloResponse",
}


class TestComponentSchemaTitlesPinned:
    """Each component schema declares a ``title`` field equal to the
    Pydantic class name.

    A ``model_config = {"title": "Greeting"}`` override on ``HelloResponse``
    would leave the components dict still keyed under ``HelloResponse``
    (so ``TestOpenAPIComponentInventoryPinned`` keeps passing), but every
    SDK generator that emits the *inner* title as the type name would
    silently swap to ``Greeting`` — a public contract change with no
    test failure.
    """

    @pytest.mark.parametrize(
        "model_name,expected_title",
        sorted(EXPECTED_COMPONENT_TITLES.items()),
    )
    def test_component_inner_title_matches_class_name(
        self,
        client: TestClient,
        model_name: str,
        expected_title: str,
    ) -> None:
        """``components.schemas[X].title`` equals the Pydantic class name."""
        schemas = _components(client)
        actual = schemas[model_name].get("title")
        assert actual == expected_title, (
            f"{model_name}.title regressed: got {actual!r}, expected {expected_title!r}. "
            f"A ``model_config = {{'title': ...}}`` override has been added — "
            f"this changes the emitted type name in generated SDKs."
        )


# Pydantic model name -> exact set of required field names. The current
# models have no Optional/default fields, so every field is required;
# pinning this catches a silent regression that drops a field or makes it
# optional.
EXPECTED_COMPONENT_REQUIRED: dict[str, set[str]] = {
    "HealthResponse": {"status", "timestamp"},
    "VersionResponse": {"version", "name", "environment"},
    "HelloRequest": {"name"},
    "HelloResponse": {"message", "timestamp"},
}


class TestComponentSchemaRequiredFieldsPinned:
    """Every Pydantic field in ``app.main`` is currently required (no
    ``Optional[...]`` or default-valued fields).

    ``TestOpenAPISchemaContract`` checks that the **handler output**
    matches the documented field set, but it does not pin the
    ``required: [...]`` array directly. A future ``timestamp: str = ""``
    default on ``HelloResponse`` would drop ``timestamp`` from the
    required list — handlers still return it, the cross-endpoint contract
    test still passes, and every typed SDK silently flips the field to
    optional, breaking exhaustiveness checks downstream.
    """

    @pytest.mark.parametrize(
        "model_name,expected_required",
        sorted(EXPECTED_COMPONENT_REQUIRED.items()),
    )
    def test_component_required_array_is_exact(
        self,
        client: TestClient,
        model_name: str,
        expected_required: set[str],
    ) -> None:
        """``components.schemas[X].required`` equals the documented required set."""
        schemas = _components(client)
        actual = set(schemas[model_name].get("required", []))
        unexpected = actual - expected_required
        missing = expected_required - actual
        assert not unexpected, (
            f"{model_name}.required gained unexpected field(s) {unexpected} — "
            f"a new required field was added without updating EXPECTED_COMPONENT_REQUIRED."
        )
        assert not missing, (
            f"{model_name}.required dropped field(s) {missing} — a field was made "
            f"optional or removed; every typed SDK consumer flips to optional."
        )


# (component, field) -> property ``title``. FastAPI/Pydantic default this
# to the field name in Title Case ("status" -> "Status"). Some SDK
# generators emit this as JSDoc/property documentation.
EXPECTED_PROPERTY_TITLES: list[tuple[str, str, str]] = [
    ("HealthResponse", "status", "Status"),
    ("HealthResponse", "timestamp", "Timestamp"),
    ("VersionResponse", "version", "Version"),
    ("VersionResponse", "name", "Name"),
    ("VersionResponse", "environment", "Environment"),
    ("HelloRequest", "name", "Name"),
    ("HelloResponse", "message", "Message"),
    ("HelloResponse", "timestamp", "Timestamp"),
]


class TestComponentSchemaPropertyTitlesPinned:
    """Each property in each component declares the default Pydantic
    ``title`` (field name in Title Case).

    A ``Field(..., title="Greeting Text")`` override on
    ``HelloResponse.message`` would silently change the emitted JSDoc on
    that field for every generator that propagates property titles
    (``openapi-typescript-codegen`` does). The existing suite pins the
    field **names** (via the required-array and the handler-output match
    in ``TestOpenAPISchemaContract``) but not the field-level titles.
    """

    @pytest.mark.parametrize(
        "model_name,field_name,expected_title",
        EXPECTED_PROPERTY_TITLES,
        ids=[f"{m}.{f}" for (m, f, _) in EXPECTED_PROPERTY_TITLES],
    )
    def test_property_title_matches_pydantic_default(
        self,
        client: TestClient,
        model_name: str,
        field_name: str,
        expected_title: str,
    ) -> None:
        """``components.schemas[X].properties[Y].title`` is the Pydantic default."""
        schemas = _components(client)
        properties = schemas[model_name].get("properties", {})
        assert field_name in properties, (
            f"{model_name}.{field_name} is missing from the schema — "
            f"field rename should be reflected in EXPECTED_PROPERTY_TITLES."
        )
        actual_title = properties[field_name].get("title")
        assert actual_title == expected_title, (
            f"{model_name}.{field_name}.title regressed: got {actual_title!r}, "
            f"expected {expected_title!r}. A ``Field(..., title=...)`` override "
            f"has been added — generated SDK property docs will churn."
        )


# (method, path) -> auto-derived OpenAPI ``summary``. FastAPI derives this
# from the handler function name (snake_case -> Title Case). The existing
# suite pins ``operationId`` (which encodes the function name + path) but
# does not pin the user-visible ``summary`` shown in the ``/docs`` UI.
EXPECTED_OPERATION_SUMMARIES: list[tuple[str, str, str]] = [
    ("get", "/health", "Health Check"),
    ("get", "/api/version", "Get Version"),
    ("get", "/api/hello", "Hello World"),
    ("post", "/api/hello", "Hello Name"),
]


class TestPathOperationSummariesPinned:
    """Each path operation declares a ``summary`` derived from the handler
    function name.

    ``TestRegressionOpenAPIRouteMetadata.test_route_operation_id_pinned``
    pins the **operationId** (which encodes both function name and path),
    but every SDK generator that uses the **summary** instead — and the
    ``/docs`` UI, which renders the summary as each operation's header —
    sees a different surface. A function rename + ``operation_id=`` kwarg
    on the decorator would keep ``operationId`` stable while the summary
    silently drifts; pinning the summary catches that mismatch.
    """

    @pytest.mark.parametrize(
        "method,path,expected_summary",
        EXPECTED_OPERATION_SUMMARIES,
        ids=[f"{m.upper()} {p}" for (m, p, _) in EXPECTED_OPERATION_SUMMARIES],
    )
    def test_operation_summary_matches_handler_name(
        self,
        client: TestClient,
        method: str,
        path: str,
        expected_summary: str,
    ) -> None:
        """``paths[path][method].summary`` matches the Title-Cased handler name."""
        op = _operation(client, path, method)
        actual = op.get("summary")
        assert actual == expected_summary, (
            f"{method.upper()} {path} summary regressed: got {actual!r}, "
            f"expected {expected_summary!r}. The handler function was renamed "
            f"or an ``operation_id=`` kwarg desynced summary from operationId."
        )
