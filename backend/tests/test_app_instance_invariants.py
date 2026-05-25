"""Pin the FastAPI ``app`` instance attributes and runtime invariants
that line-coverage misses.

Backend coverage (line + branch) is already at 100% on ``app/main.py`` and
``app/__init__.py``: every executable statement is exercised by the 390
tests in the existing suite. The remaining behavioural surface is the
configuration metaprogramming that FastAPI / Starlette / Pydantic apply
**without** running a statement we own — middleware kwargs, app-instance
attributes, ``app.openapi()`` caching, the Pydantic ``extra`` policy on
request models, and whether handler functions are coroutines.

Every pin in this file targets a regression class that:

* would not be caught by ``--cov`` because the behaviour is derived by a
  third-party library from the source we ship (constructor kwargs,
  Pydantic v2 default model config, route-decorator metadata), **and**
* is not pinned by any of the 390 existing tests — verified by grep for
  the attribute name being asserted (``app.title``, ``app.docs_url``,
  ``user_middleware``, ``iscoroutinefunction``, ``model_config``,
  ``app.openapi()`` identity).

A regression here typically ships silently — for example, dropping
``allow_credentials=True`` from the CORS middleware kwargs would let
every browser-side cookie session break in production while the OpenAPI
schema, status-code assertions, and CORS-header presence checks all
still pass.
"""

from __future__ import annotations

import inspect
import re

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.main import (
    HelloRequest,
    app,
    get_version,
    health_check,
    hello_name,
    hello_world,
)


class TestAppInstancePythonAttributes:
    """Pin the Python-level attributes set on the FastAPI ``app`` instance.

    ``TestRegressionMessageFormat`` and ``TestRegressionFastAPIDescription``
    pin the OpenAPI **info** block (``info.title``, ``info.version``,
    ``info.description``). ``TestRegressionDocumentationURLs`` pins that
    ``/docs`` and ``/redoc`` return 200.

    None of those tests pin the **Python attributes** on the ``app``
    object itself. A regression that programmatically reassigns
    ``app.title = ...`` after construction (e.g. inside a future
    ``configure_metadata()`` helper) would change the OpenAPI value via a
    different code path than the constructor kwarg — pinning the attribute
    directly closes that gap.

    Similarly, ``app.docs_url`` / ``app.redoc_url`` / ``app.openapi_url``
    are read by FastAPI lazily when serving the routes; pinning the
    attribute catches a future
    ``app = FastAPI(..., docs_url=None, redoc_url=None)`` change that
    would only fail the existing 200-check tests, while the attribute pin
    here gives a direct, narrower error message.
    """

    def test_app_is_a_fastapi_instance(self) -> None:
        """``app`` is a :class:`FastAPI` instance — not a subclass or wrapper.

        If a future refactor wraps ``app`` in middleware-application
        boilerplate (e.g. ``app = Starlette(routes=[Mount('/', app)])``),
        the public route surface changes shape silently. Pin the concrete
        class so a swap is loud.
        """
        assert type(app) is FastAPI, (
            f"app is no longer a FastAPI instance (got {type(app).__name__}); "
            f"a refactor wrapped the app and changed downstream behaviour."
        )

    def test_app_title_attribute_pinned(self) -> None:
        """``app.title`` is the documented title literal."""
        assert app.title == "Software Factory API"

    def test_app_description_attribute_pinned(self) -> None:
        """``app.description`` is the documented description literal."""
        assert app.description == "Backend API powered by Claude Software Factory"

    def test_app_version_attribute_equals_dunder_version(self) -> None:
        """``app.version`` is wired through ``app.__version__`` (one source of truth)."""
        assert app.version == __version__, (
            f"app.version diverged from app.__version__: "
            f"got {app.version!r}, expected {__version__!r}"
        )

    def test_app_docs_url_attribute_pinned(self) -> None:
        """``app.docs_url == '/docs'`` — Swagger UI mount point."""
        assert app.docs_url == "/docs"

    def test_app_redoc_url_attribute_pinned(self) -> None:
        """``app.redoc_url == '/redoc'`` — ReDoc UI mount point."""
        assert app.redoc_url == "/redoc"

    def test_app_openapi_url_attribute_is_default(self) -> None:
        """``app.openapi_url == '/openapi.json'`` — FastAPI's default.

        The constructor doesn't pass ``openapi_url``, so this attribute
        captures FastAPI's default. A future change that overrides it
        (e.g. to ``/api/openapi.json``) would silently move the schema
        endpoint and break clients that fetch it by canonical path.
        """
        assert app.openapi_url == "/openapi.json"

    def test_app_root_path_is_empty(self) -> None:
        """``app.root_path == ''`` — no ASGI sub-mount prefix.

        A non-empty ``root_path`` would alter the URLs FastAPI emits in
        the OpenAPI ``servers`` block, breaking any client that derives
        base URLs from the schema.
        """
        assert app.root_path == ""


class TestCORSMiddlewareInstanceConfiguration:
    """Pin the **constructor kwargs** of the installed CORS middleware.

    ``TestCORSMiddleware``, ``TestCORSCacheCorrectness``,
    ``TestRegressionCORSPreflightContents`` pin the *response headers*
    that CORS emits — the externally observable surface. None of them
    inspect the live middleware instance's kwargs.

    The kwargs are the *source* of those headers. A regression that
    changes ``allow_credentials=True`` to ``allow_credentials=False``
    drops the ``Access-Control-Allow-Credentials: true`` header on every
    response; while the existing tests catch that downstream, this
    upstream pin gives a precise diagnostic ("the kwarg flipped") so the
    fix-site is obvious.

    Reading ``app.user_middleware`` is a Starlette-documented API — it is
    the public way to introspect the middleware stack before the ASGI
    transport is built.
    """

    EXPECTED_CORS_KWARGS: dict[str, object] = {
        "allow_origins": ["http://localhost:3000", "http://127.0.0.1:3000"],
        "allow_credentials": True,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }

    def test_exactly_one_cors_middleware_installed(self) -> None:
        """Exactly one CORSMiddleware is registered — no duplicate stacking.

        A future ``app.add_middleware(CORSMiddleware, ...)`` call appended
        without removing the original would silently apply CORS twice,
        duplicating ``Vary: Origin`` headers and confusing browsers.
        """
        # Starlette types ``Middleware.cls`` as ``_MiddlewareFactory[P]``,
        # which mypy can't reconcile with a concrete class identity check;
        # the comparison is valid at runtime (cls is the class object passed
        # to ``add_middleware``), so silence the static check here.
        cors = [m for m in app.user_middleware if m.cls is CORSMiddleware]  # type: ignore[comparison-overlap]
        assert len(cors) == 1, (
            f"Expected exactly one CORSMiddleware in app.user_middleware, "
            f"got {len(cors)} (full stack: "
            f"{[getattr(m.cls, '__name__', repr(m.cls)) for m in app.user_middleware]})"
        )

    def test_cors_middleware_kwargs_match_documented_config(self) -> None:
        """All four documented kwargs are present with their documented values.

        Inspects ``app.user_middleware[i].kwargs`` directly. A change to
        any of the four kwargs would flip the response-header contract
        the frontend depends on; pin them as a set so an added/removed
        kwarg is also visible.
        """
        cors = next(m for m in app.user_middleware if m.cls is CORSMiddleware)  # type: ignore[comparison-overlap]
        kwargs = cors.kwargs
        assert kwargs == self.EXPECTED_CORS_KWARGS, (
            f"CORSMiddleware kwargs diverged from documented config: "
            f"got {kwargs!r}, expected {self.EXPECTED_CORS_KWARGS!r}"
        )

    def test_cors_allow_origins_excludes_wildcard(self) -> None:
        """``allow_origins`` does not include ``'*'``.

        With ``allow_credentials=True`` the CORS spec **forbids**
        ``allow_origins=['*']``; browsers reject the combination. A
        future "open up CORS" change that adds ``'*'`` would not just
        be a policy expansion — it would silently break every browser
        request that carries credentials.
        """
        cors = next(m for m in app.user_middleware if m.cls is CORSMiddleware)  # type: ignore[comparison-overlap]
        # ``kwargs`` is typed as ``Mapping[str, Any]``; the value here is the
        # documented ``list[str]`` of origins.
        origins: list[str] = list(cors.kwargs["allow_origins"])  # type: ignore[call-overload]
        assert "*" not in origins, (
            f"allow_origins contains wildcard '*' but allow_credentials=True — "
            f"this combination is forbidden by the CORS spec and browsers will "
            f"reject every request. Got allow_origins={origins!r}"
        )


class TestOpenAPISchemaCached:
    """``FastAPI.openapi()`` returns the same cached dict object across calls.

    FastAPI caches the generated schema on ``self.openapi_schema`` after
    the first call. A regression that disables the cache (e.g. by
    overriding ``app.openapi`` with a method that regenerates each call)
    would multiply schema-generation work on every ``/openapi.json``
    request and on every test that fetches the schema (this suite alone
    fetches it dozens of times).

    No test in the existing suite asserts identity (``is``) on the
    return value — they all call ``client.get("/openapi.json").json()``
    which deserialises a fresh dict each time. This pin checks the
    underlying Python invariant directly.
    """

    def test_openapi_returns_same_object_across_calls(self) -> None:
        """Two consecutive ``app.openapi()`` calls return the same dict instance."""
        first = app.openapi()
        second = app.openapi()
        assert first is second, (
            "app.openapi() returned a different dict on the second call. "
            "The schema cache (app.openapi_schema) has been disabled or invalidated; "
            "this multiplies schema-generation cost on every /openapi.json request."
        )

    def test_openapi_schema_attribute_is_populated_after_call(self) -> None:
        """``app.openapi_schema`` is non-None after at least one ``openapi()`` call.

        This is the underlying mechanism that backs the caching invariant
        above. Pinning it directly catches a regression where the
        ``openapi()`` override returns a memoised value via a different
        attribute, leaving ``openapi_schema`` empty (so anything that
        reads ``app.openapi_schema`` directly — including some FastAPI
        internals — silently regenerates the schema).
        """
        app.openapi()
        assert app.openapi_schema is not None, (
            "app.openapi_schema is None after calling app.openapi() — "
            "the cache attribute is no longer being populated, defeating memoisation."
        )


class TestVersionStringShape:
    """``app.__version__`` has the structural shape we publish.

    ``TestRegressionMessageFormat.test_openapi_version_matches_app_version``
    pins that the literal in ``app/__init__.py`` equals the OpenAPI
    ``info.version`` and the ``/api/version`` body. It does *not* pin the
    **shape** of that literal — a regression that changes
    ``__version__ = "0.1.0"`` to ``__version__ = "dev"`` or
    ``__version__ = ""`` would silently break version-comparison logic
    in any client that does ``packaging.version.parse(...)``.

    The shape we publish is "N.N.N" (three dot-separated integers), the
    PEP 440 ``MAJOR.MINOR.MICRO`` shape that ``packaging.version`` parses
    as a release. Pin that shape so a future "let's use semver suffixes"
    edit (which is fine to make, but should be explicit) flags this test.
    """

    def test_version_is_a_nonempty_string(self) -> None:
        """``__version__`` is a non-empty :class:`str`."""
        assert isinstance(__version__, str) and __version__, (
            f"__version__ must be a non-empty string, got {__version__!r}"
        )

    def test_version_matches_three_part_dotted_shape(self) -> None:
        """``__version__`` matches the ``MAJOR.MINOR.MICRO`` PEP 440 shape."""
        assert re.fullmatch(r"\d+\.\d+\.\d+", __version__), (
            f"__version__ {__version__!r} does not match the documented "
            f"three-part 'MAJOR.MINOR.MICRO' shape. If you are introducing a "
            f"pre-release suffix (e.g. '0.1.0rc1') intentionally, update this "
            f"test alongside the literal in app/__init__.py."
        )


class TestHelloRequestExtraFieldsPolicy:
    """``HelloRequest`` silently drops extra fields (Pydantic v2 default).

    Pydantic v2's default ``model_config`` is ``extra='ignore'``: unknown
    keys in a JSON body are silently dropped rather than rejected with a
    422. The model in ``app.main`` does not override this — so a client
    that POSTs ``{"name": "Alice", "nickname": "Ally"}`` today gets
    ``{"message": "Hello, Alice! ...", "timestamp": ...}`` back and the
    ``nickname`` field is discarded without error.

    This is a **public API contract**: tightening it to ``extra='forbid'``
    would start returning 422 to every client that includes extra fields
    (which is allowed by the OpenAPI spec by default). The change might
    be intentional, but it must be deliberate. Pin the current policy so
    the choice is visible in the test diff.
    """

    def test_hello_request_extra_field_is_dropped_silently(self) -> None:
        """Constructing ``HelloRequest`` with extra kwargs does not raise and drops them."""
        # No exception — pydantic v2 default policy.
        req = HelloRequest(name="Alice", surprise="ignored")  # type: ignore[call-arg]
        assert req.model_dump() == {"name": "Alice"}, (
            f"HelloRequest no longer drops extra fields silently. "
            f"This is a public-API tightening — confirm the policy change is intentional, "
            f"then update this test. Got {req.model_dump()!r}"
        )

    def test_hello_request_model_config_is_empty(self) -> None:
        """``HelloRequest.model_config`` is the empty dict (no overrides set).

        The previous test confirms the *behaviour*; this test confirms
        the *cause*. A regression that adds ``extra='forbid'`` to
        ``model_config`` (or any other override) flips behaviour and the
        cause is right here in ``model_config``.
        """
        # Pydantic v2 stores the user-supplied config dict on the class.
        assert HelloRequest.model_config == {}, (
            f"HelloRequest.model_config is no longer empty: {HelloRequest.model_config!r}. "
            f"An override has been added — confirm it is intentional and that the "
            f"behavioural pin above still passes."
        )


class TestHandlersAreCoroutines:
    """All four route handlers are coroutine functions (``async def``).

    ``app/main.py`` declares ``async def health_check(...)``,
    ``async def get_version(...)``, ``async def hello_world(...)``,
    and ``async def hello_name(...)``. FastAPI dispatches sync handlers
    differently — running them in a threadpool to keep the event loop
    unblocked. A regression that drops ``async`` from any of these
    handlers would silently change their ASGI scheduling profile, adding
    threadpool overhead to every request to that endpoint.

    No existing test inspects ``inspect.iscoroutinefunction`` for any
    handler — verified by grep across ``tests/``.
    """

    @pytest.mark.parametrize(
        "handler",
        [health_check, get_version, hello_world, hello_name],
        ids=["health_check", "get_version", "hello_world", "hello_name"],
    )
    def test_handler_is_coroutine_function(self, handler: object) -> None:
        """Handler is declared with ``async def`` (not a sync function)."""
        assert inspect.iscoroutinefunction(handler), (
            f"{getattr(handler, '__name__', repr(handler))!r} is no longer "
            f"a coroutine function. FastAPI will now dispatch it via threadpool, "
            f"changing the scheduling profile. If this is intentional, update "
            f"this pin; otherwise restore the ``async def`` declaration."
        )


class TestPackageModuleDocstring:
    """Pin the ``app`` package's module docstring.

    ``TestRegressionPackageStructure`` confirms ``__version__`` is
    exposed at the package level. It does not pin the package's
    ``__doc__``. The docstring on ``app/__init__.py`` is what shows up
    in any tooling that introspects the package (sphinx-autodoc,
    pydoc, IDE hovers) — a deletion would silently strip the project
    description from those surfaces.
    """

    def test_app_package_has_expected_docstring(self) -> None:
        """``app.__doc__`` equals the documented package summary."""
        import app as app_pkg

        assert app_pkg.__doc__ == "Software Factory Backend API.", (
            f"app/__init__.py docstring regressed: got {app_pkg.__doc__!r}, "
            f"expected 'Software Factory Backend API.'"
        )
