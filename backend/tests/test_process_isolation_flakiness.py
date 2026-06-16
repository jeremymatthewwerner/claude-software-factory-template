"""
Cross-process flakiness regression guards.

Focus: flaky-hunt (Tuesday). The full backend suite ran five times back-to-back
under ``pytest-randomly`` (reshuffling order each run) with zero flakes, and the
frontend suite ran three times with zero flakes — the code is stable today.

Every guard in :mod:`tests.test_flakiness_guards` pins determinism *within a
single Python process*. That leaves two canonical *cross-process* sources of
intermittent CI failure unguarded — they can only be exercised by launching a
fresh interpreter, because the variable they depend on is read once at process
start and cannot be changed in-process:

* ``PYTHONHASHSEED`` — CPython randomizes ``str``/``bytes`` hashing per process,
  which randomizes ``set`` and (pre-insertion-order) ``dict`` iteration order.
  The OpenAPI schema is assembled from sets and dicts; if its serialized bytes
  ever became iteration-order-dependent, the regression would be invisible to
  every in-process guard (they all share one seed) and would surface only as an
  intermittent diff between two CI runs that happened to draw different seeds.
  ``pytest-randomly`` itself re-seeds ``PYTHONHASHSEED`` across runs, so this is
  a live risk for this very suite.

* ``LC_ALL`` / ``LANG`` — the locale sibling of the existing ``TZ`` guard in
  :class:`tests.test_flakiness_guards.TestTZEnvironmentVariableIndependence`.
  The C library reads the locale at process start. A handler that ever used
  locale-sensitive formatting (number grouping, month names, decimal commas)
  would pass on ``C``/UTF-8 runners and flake on a runner configured with a
  different ``LANG`` — and, like the ``TZ`` case, the flake would only appear
  on the *subset* of CI machines whose locale differs.

Both classes run the app in a subprocess via ``sys.executable`` so the child
inherits a deliberately-perturbed environment. Each subprocess imports FastAPI
fresh (~0.3-0.4s) and prints a single line, so the module trades a one-off
~10s of wall-clock for coverage of a flakiness class no in-process test can
reach. Seed and locale counts are kept small for exactly this reason.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

# Hash seeds chosen to be maximally different from one another so any
# ordering-dependent serialization has the best chance of diverging. "0"
# disables hash randomization entirely; the others enable it with distinct
# seeds. ``pytest-randomly`` draws arbitrary seeds, so pinning several fixed
# ones gives a deterministic, reproducible failure signature if the invariant
# ever breaks. Three seeds keep the subprocess wall-clock modest while still
# making it overwhelmingly likely that an order-dependent serialization differs
# between at least one pair (a genuine ordering leak diverges across *most* seed
# pairs, not a rare few).
HASH_SEEDS = ("0", "1", "65535")

# Locales to exercise. ``C`` is the byte-deterministic baseline; ``C.utf8`` and
# ``en_US.utf8`` are the UTF-8 forms most CI images ship. Each is verified to
# exist on the host before use (see ``_available_locales``) so the test skips
# rather than fails on a minimal image that lacks them.
CANDIDATE_LOCALES = ("C", "C.utf8", "en_US.utf8", "POSIX")


def _run_in_subprocess(snippet: str, env_overrides: dict[str, str]) -> str:
    """Execute ``snippet`` in a fresh interpreter and return its stdout.

    The child inherits the current environment with ``env_overrides`` applied,
    runs from the backend package root (so ``from app.main import app``
    resolves), and is expected to print exactly the value under test on stdout.
    Raises ``AssertionError`` with captured stderr if the child exits non-zero.
    """
    env = dict(os.environ)
    env.update(env_overrides)
    # ``cwd`` is the backend directory: this file lives at
    # ``backend/tests/test_process_isolation_flakiness.py``, so two levels up is
    # ``backend``, where ``app`` is importable.
    backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    result = subprocess.run(
        [sys.executable, "-c", snippet],
        capture_output=True,
        text=True,
        env=env,
        cwd=backend_root,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"subprocess exited {result.returncode} with env {env_overrides!r}; "
        f"stderr:\n{result.stderr}"
    )
    return result.stdout.strip()


def _available_locales() -> set[str]:
    """Return the set of locale names installed on the host (``locale -a``)."""
    try:
        out = subprocess.run(["locale", "-a"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return set()
    if out.returncode != 0:
        return set()
    return {line.strip() for line in out.stdout.splitlines() if line.strip()}


# Snippet that prints the OpenAPI schema as a canonical JSON string. ``app`` is
# imported fresh in the child, so its schema is built under the child's hash
# seed. ``sort_keys=False`` is intentional: we want to detect ordering that
# *would* differ if a regression made iteration order leak into the output;
# sorting keys would mask exactly the bug we are hunting.
_OPENAPI_SNIPPET = (
    "import json; from app.main import app; print(json.dumps(app.openapi(), sort_keys=False))"
)

# Snippet that drives a real request through the ASGI app via TestClient and
# prints one field. Parameterized by the python expression that extracts the
# field from the parsed response.
_REQUEST_SNIPPET_TEMPLATE = (
    "from fastapi.testclient import TestClient; from app.main import app; "
    "c = TestClient(app); print({extract})"
)


class TestHashSeedSchemaStability:
    """The OpenAPI schema must be byte-identical across ``PYTHONHASHSEED`` values.

    This is the cross-process complement to
    :class:`tests.test_flakiness_guards.TestOpenAPISchemaByteStability`, which
    can only ever observe one seed (the one the test process was launched with).
    By rebuilding the schema in subprocesses under several distinct seeds and
    asserting the serialized bytes agree, we catch any future change that lets
    set/dict iteration order leak into ``/openapi.json`` — the single most
    common cause of "passes locally, flakes in CI" schema diffs.
    """

    def test_openapi_json_identical_across_hash_seeds(self) -> None:
        """Serialized ``app.openapi()`` is identical under each distinct hash seed."""
        outputs = {
            seed: _run_in_subprocess(_OPENAPI_SNIPPET, {"PYTHONHASHSEED": seed})
            for seed in HASH_SEEDS
        }
        distinct = set(outputs.values())
        assert len(distinct) == 1, (
            "app.openapi() serialized to different bytes across PYTHONHASHSEED "
            f"values: {{seed: len}} = "
            f"{{ {', '.join(f'{s}: {len(o)}' for s, o in outputs.items())} }}"
        )

    def test_openapi_paths_set_identical_across_hash_seeds(self) -> None:
        """The declared path set is identical under distinct hash seeds.

        A weaker, more diagnostic check than full byte-identity: if the byte
        test ever fails, this pinpoints whether the *set of routes* drifted
        (a registration-order leak) versus a deeper serialization change.
        """
        path_sets = set()
        for seed in HASH_SEEDS:
            out = _run_in_subprocess(_OPENAPI_SNIPPET, {"PYTHONHASHSEED": seed})
            path_sets.add(tuple(sorted(json.loads(out)["paths"].keys())))
        assert len(path_sets) == 1, f"OpenAPI path set varied across hash seeds: {path_sets!r}"

    def test_components_schema_set_identical_across_hash_seeds(self) -> None:
        """The declared component-schema name set is identical under distinct seeds.

        Component schemas are keyed by model name in a dict; this guards the
        specific case where a hash-order leak reorders or drops a component
        only under certain seeds.
        """
        component_sets = set()
        for seed in HASH_SEEDS:
            out = _run_in_subprocess(_OPENAPI_SNIPPET, {"PYTHONHASHSEED": seed})
            component_sets.add(tuple(sorted(json.loads(out)["components"]["schemas"].keys())))
        assert len(component_sets) == 1, (
            f"OpenAPI component-schema set varied across hash seeds: {component_sets!r}"
        )


class TestHashSeedResponseStability:
    """Handler response payloads must not depend on ``PYTHONHASHSEED``.

    Pydantic serializes responses field-by-field; field ordering is declared,
    not hash-derived, so this should always hold. Pinning it means that a future
    regression which built a response from an *unordered* container (e.g.
    ``return dict(some_set_comprehension)``) fails here deterministically rather
    than flaking between CI runs that drew different seeds.
    """

    def test_health_status_identical_across_hash_seeds(self) -> None:
        """``/health`` ``status`` is the constant ``healthy`` under every hash seed."""
        snippet = _REQUEST_SNIPPET_TEMPLATE.format(extract="c.get('/health').json()['status']")
        statuses = {_run_in_subprocess(snippet, {"PYTHONHASHSEED": seed}) for seed in HASH_SEEDS}
        assert statuses == {"healthy"}, (
            f"/health status varied across PYTHONHASHSEED values: {statuses!r}"
        )

    def test_post_hello_message_identical_across_hash_seeds(self) -> None:
        """``POST /api/hello`` returns one ``message`` across distinct hash seeds."""
        snippet = _REQUEST_SNIPPET_TEMPLATE.format(
            extract="c.post('/api/hello', json={'name': 'HashSeed'}).json()['message']"
        )
        messages = {_run_in_subprocess(snippet, {"PYTHONHASHSEED": seed}) for seed in HASH_SEEDS}
        assert messages == {"Hello, HashSeed! Welcome to your Software Factory."}, (
            f"POST /api/hello message varied across PYTHONHASHSEED values: {messages!r}"
        )

    def test_version_body_identical_across_hash_seeds(self) -> None:
        """``/api/version`` (no timestamp field) is byte-identical across seeds.

        With no timestamp to vary, the *entire* serialized body must be
        constant — making this the most sensitive probe for an accidental
        hash-order-dependent field anywhere in the version response.
        """
        snippet = _REQUEST_SNIPPET_TEMPLATE.format(extract="c.get('/api/version').text")
        bodies = {_run_in_subprocess(snippet, {"PYTHONHASHSEED": seed}) for seed in HASH_SEEDS}
        assert len(bodies) == 1, (
            f"/api/version body varied across PYTHONHASHSEED values ({len(bodies)} distinct)"
        )


class TestLocaleIndependence:
    """Handler output must not depend on the process ``LC_ALL`` / ``LANG`` locale.

    The locale sibling of
    :class:`tests.test_flakiness_guards.TestTZEnvironmentVariableIndependence`.
    Because the C library binds the locale at process start, the only faithful
    way to exercise it is in a subprocess launched with the locale env vars set.
    A handler that ever introduced locale-sensitive formatting would pass on the
    default ``C``/UTF-8 CI image and flake only on differently-configured
    runners — exactly the kind of partial, hard-to-reproduce CI flake these
    guards exist to eliminate.

    Tests skip (rather than fail) any locale not installed on the host, so the
    module stays green on minimal images.
    """

    def _present_locales(self) -> list[str]:
        installed = _available_locales()
        present = [loc for loc in CANDIDATE_LOCALES if loc in installed]
        if len(present) < 2:
            pytest.skip(
                "fewer than two candidate locales installed; cannot compare "
                f"across locales (installed candidates: {present!r})"
            )
        return present

    def test_health_timestamp_is_utc_under_each_locale(self) -> None:
        """``/health`` emits a zero-offset UTC ISO 8601 timestamp under every locale."""
        present = self._present_locales()
        # Child parses its own timestamp and prints the UTC offset in seconds;
        # a locale-sensitive clock regression would surface as a non-zero offset
        # or an unparseable string (non-zero exit) under some locale.
        snippet = (
            "from datetime import datetime; from fastapi.testclient import TestClient; "
            "from app.main import app; c = TestClient(app); "
            "ts = c.get('/health').json()['timestamp']; "
            "off = datetime.fromisoformat(ts).utcoffset().total_seconds(); "
            "print(int(off))"
        )
        for loc in present:
            offset = _run_in_subprocess(snippet, {"LC_ALL": loc, "LANG": loc})
            assert offset == "0", (
                f"/health timestamp had non-UTC offset {offset}s under locale {loc!r}"
            )

    def test_post_hello_message_identical_across_locales(self) -> None:
        """``POST /api/hello`` returns the same ``message`` under every locale."""
        present = self._present_locales()
        snippet = _REQUEST_SNIPPET_TEMPLATE.format(
            extract="c.post('/api/hello', json={'name': 'Locale'}).json()['message']"
        )
        messages = {_run_in_subprocess(snippet, {"LC_ALL": loc, "LANG": loc}) for loc in present}
        assert messages == {"Hello, Locale! Welcome to your Software Factory."}, (
            f"POST /api/hello message varied across locales: {messages!r}"
        )

    def test_version_body_identical_across_locales(self) -> None:
        """``/api/version`` serializes to identical bytes under every locale.

        The version body has no timestamp, so any locale-driven difference
        (e.g. a number formatted with a locale-specific separator) would make
        the whole body diverge — the most sensitive available probe.
        """
        present = self._present_locales()
        snippet = _REQUEST_SNIPPET_TEMPLATE.format(extract="c.get('/api/version').text")
        bodies = {_run_in_subprocess(snippet, {"LC_ALL": loc, "LANG": loc}) for loc in present}
        assert len(bodies) == 1, (
            f"/api/version body varied across locales ({len(bodies)} distinct): {present!r}"
        )

    def test_openapi_schema_identical_across_locales(self) -> None:
        """``/openapi.json`` serializes to identical bytes under every locale.

        Descriptions and titles in the schema are static strings, but a future
        change that interpolated a locale-formatted value into the schema (a
        version number, a date) would diverge here. Pin the invariant.
        """
        present = self._present_locales()
        outputs = {
            loc: _run_in_subprocess(_OPENAPI_SNIPPET, {"LC_ALL": loc, "LANG": loc})
            for loc in present
        }
        assert len(set(outputs.values())) == 1, (
            "app.openapi() serialized to different bytes across locales: "
            f"{{ {', '.join(f'{loc}: {len(o)}' for loc, o in outputs.items())} }}"
        )
