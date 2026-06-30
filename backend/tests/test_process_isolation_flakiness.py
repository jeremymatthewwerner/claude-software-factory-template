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
fresh (~0.3-0.4s) and prints a single line, buying coverage of a flakiness class
no in-process test can reach. Because every guard launches the *same* snippet
under several environments and only compares the outputs, the per-test spawns
are run concurrently through :func:`_run_in_subprocesses` (a thread pool): each
``subprocess.run`` blocks its worker purely on I/O, so overlapping them cuts this
file — previously the slowest in the suite — to roughly the cost of a single
spawn without changing a single assertion.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

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


def _run_in_subprocesses(snippet: str, jobs: dict[str, dict[str, str]]) -> dict[str, str]:
    """Run ``snippet`` in a fresh interpreter for each job, all concurrently.

    ``jobs`` maps a caller-chosen key (a hash seed or locale name) to the
    environment overrides for that child; the return value maps the same keys
    to each child's stdout.

    Every guard in this module needs to launch the *same* snippet under several
    perturbed environments and then compare the outputs. Doing that with a
    sequential comprehension serialized N fresh-interpreter spawns (each paying
    the ~0.4–1.0s FastAPI import cost), making this the slowest file in the
    suite. Each :func:`_run_in_subprocess` call blocks its worker purely on I/O
    (process spawn + the child's own import), so a thread pool overlaps those
    waits for a near-Nx wall-clock speedup with **zero** change to what is
    asserted — the comparison still sees one output per job, keyed identically.
    Returning a dict (not a bare set) preserves each caller's per-key
    diagnostic messages.
    """
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        keyed = pool.map(
            lambda item: (item[0], _run_in_subprocess(snippet, item[1])),
            jobs.items(),
        )
        return dict(keyed)


def _hash_seed_jobs() -> dict[str, dict[str, str]]:
    """Map each pinned hash seed to its ``PYTHONHASHSEED`` env override."""
    return {seed: {"PYTHONHASHSEED": seed} for seed in HASH_SEEDS}


def _locale_jobs(locales: list[str]) -> dict[str, dict[str, str]]:
    """Map each locale name to its ``LC_ALL``/``LANG`` env override."""
    return {loc: {"LC_ALL": loc, "LANG": loc} for loc in locales}


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
        outputs = _run_in_subprocesses(_OPENAPI_SNIPPET, _hash_seed_jobs())
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
        outputs = _run_in_subprocesses(_OPENAPI_SNIPPET, _hash_seed_jobs())
        path_sets = {tuple(sorted(json.loads(out)["paths"].keys())) for out in outputs.values()}
        assert len(path_sets) == 1, f"OpenAPI path set varied across hash seeds: {path_sets!r}"

    def test_components_schema_set_identical_across_hash_seeds(self) -> None:
        """The declared component-schema name set is identical under distinct seeds.

        Component schemas are keyed by model name in a dict; this guards the
        specific case where a hash-order leak reorders or drops a component
        only under certain seeds.
        """
        outputs = _run_in_subprocesses(_OPENAPI_SNIPPET, _hash_seed_jobs())
        component_sets = {
            tuple(sorted(json.loads(out)["components"]["schemas"].keys()))
            for out in outputs.values()
        }
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
        statuses = set(_run_in_subprocesses(snippet, _hash_seed_jobs()).values())
        assert statuses == {"healthy"}, (
            f"/health status varied across PYTHONHASHSEED values: {statuses!r}"
        )

    def test_post_hello_message_identical_across_hash_seeds(self) -> None:
        """``POST /api/hello`` returns one ``message`` across distinct hash seeds."""
        snippet = _REQUEST_SNIPPET_TEMPLATE.format(
            extract="c.post('/api/hello', json={'name': 'HashSeed'}).json()['message']"
        )
        messages = set(_run_in_subprocesses(snippet, _hash_seed_jobs()).values())
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
        bodies = set(_run_in_subprocesses(snippet, _hash_seed_jobs()).values())
        assert len(bodies) == 1, (
            f"/api/version body varied across PYTHONHASHSEED values ({len(bodies)} distinct)"
        )


class TestHashSeedErrorResponseStability:
    """The 422 validation-error body must not depend on ``PYTHONHASHSEED``.

    This is the cross-process complement to
    :class:`tests.test_flakiness_guards.TestErrorResponseBodyDeterminism`, which
    fires 50 identical requests but can only ever observe the *one* hash seed
    the test process was launched under. The error body is the most hash-order-
    sensitive output in the whole app: unlike the success responses (whose
    fields are declared by Pydantic models in a fixed order), the 422 ``detail``
    is assembled at runtime from ``exc.errors()`` — a list of plain ``dict``\\ s —
    and, for non-finite inputs, rebuilt key-by-key by :func:`app.main._replace_non_finite`
    and :func:`fastapi.encoders.jsonable_encoder`. That dict-of-dicts assembly is
    exactly where ``str``/``bytes`` hash randomization would leak iteration order
    into the serialized bytes. A regression that did so would pass every in-
    process guard (they all share the parent's single seed) and surface only as
    an intermittent diff between two CI runs that happened to draw different
    seeds — the canonical "passes locally, flakes in CI" failure. Pinning it
    across distinct seeds makes such a regression fail here, deterministically.

    Two payloads are exercised because they travel different code paths:

    * The **missing-field** body (``POST {}``) is built entirely by FastAPI's
      *default* validation handler — the common case for every malformed
      request the app sees.
    * The **non-finite** body (``[{"k": -Infinity}, NaN]``) forces the app's
      *custom* ``except ValueError`` branch in ``validation_exception_handler``,
      recursing :func:`app.main._replace_non_finite` through a nested ``dict``
      and ``list``. This is the only non-trivial application logic in the
      service, so guarding its cross-seed byte-stability is the highest-value
      probe in this file.
    """

    def test_missing_field_422_body_identical_across_hash_seeds(self) -> None:
        """``POST /api/hello`` with an empty body yields one 422 across seeds."""
        snippet = _REQUEST_SNIPPET_TEMPLATE.format(extract="c.post('/api/hello', json={}).text")
        bodies = set(_run_in_subprocesses(snippet, _hash_seed_jobs()).values())
        assert len(bodies) == 1, (
            "missing-field 422 body varied across PYTHONHASHSEED values "
            f"({len(bodies)} distinct): {bodies!r}"
        )

    def test_nonfinite_422_body_identical_across_hash_seeds(self) -> None:
        """The non-finite-sanitized 422 body is byte-identical across hash seeds.

        ``[{"k": -Infinity}, NaN]`` is rejected by Pydantic and echoed back
        through ``_replace_non_finite`` as ``[{"k": "-inf"}, "nan"]``. The
        nested ``dict`` makes this the most ordering-sensitive payload the app
        can produce; the serialized bytes must agree under every seed.
        """
        extract = (
            "c.post('/api/hello', content=b'[{\"k\": -Infinity}, NaN]', "
            "headers={'Content-Type': 'application/json'}).text"
        )
        snippet = _REQUEST_SNIPPET_TEMPLATE.format(extract=extract)
        bodies = set(_run_in_subprocesses(snippet, _hash_seed_jobs()).values())
        assert len(bodies) == 1, (
            "non-finite-sanitized 422 body varied across PYTHONHASHSEED values "
            f"({len(bodies)} distinct): {bodies!r}"
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
        offsets = _run_in_subprocesses(snippet, _locale_jobs(present))
        for loc, offset in offsets.items():
            assert offset == "0", (
                f"/health timestamp had non-UTC offset {offset}s under locale {loc!r}"
            )

    def test_post_hello_message_identical_across_locales(self) -> None:
        """``POST /api/hello`` returns the same ``message`` under every locale."""
        present = self._present_locales()
        snippet = _REQUEST_SNIPPET_TEMPLATE.format(
            extract="c.post('/api/hello', json={'name': 'Locale'}).json()['message']"
        )
        messages = set(_run_in_subprocesses(snippet, _locale_jobs(present)).values())
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
        bodies = set(_run_in_subprocesses(snippet, _locale_jobs(present)).values())
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
        outputs = _run_in_subprocesses(_OPENAPI_SNIPPET, _locale_jobs(present))
        assert len(set(outputs.values())) == 1, (
            "app.openapi() serialized to different bytes across locales: "
            f"{{ {', '.join(f'{loc}: {len(o)}' for loc, o in outputs.items())} }}"
        )
