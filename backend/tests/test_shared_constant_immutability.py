"""Immutability contract for the shared, module-level constants in ``conftest``.

Focus area: **flaky-hunt**.

``conftest`` exposes a handful of constants that dozens of suites import directly:
``JSON_HEADERS`` (a dict), ``GET_PATHS`` (a list), ``GREETING_TEMPLATE`` and the
CORS origin strings. The dict/list ones are shared *mutable* objects, and the
conftest comment explicitly instructs callers to "Treat it as immutable — spread
it (``{**JSON_HEADERS, ...}``) rather than mutating it in place."

Nothing enforced that contract. Because the suite runs under ``pytest-randomly``,
the file/test execution order changes every run, so a test that mutated one of
these containers in place would corrupt only the tests that happened to run
*after* it — passing or failing purely as a function of the random seed. That is
the exact shape of an order-dependent flaky test.

Two complementary safety nets live here:

1. A session-scoped autouse guard in ``conftest`` (``_guard_shared_constant_immutability``)
   snapshots the mutable constants before the first test and re-checks them after
   the last, converting any real leak into one deterministic, seed-independent
   failure.
2. The unit tests below pin the canonical *values* of the shared constants and
   prove that the prescribed spread idiom does not disturb the shared object —
   documenting and locking in the safe usage pattern.
"""

import copy

from tests.conftest import (
    DISALLOWED_ORIGIN,
    GET_PATHS,
    GREETING_TEMPLATE,
    JSON_HEADERS,
    LOCALHOST_ORIGIN,
    LOOPBACK_ORIGIN,
)


class TestSharedConstantCanonicalValues:
    """The shared constants have a fixed, documented value.

    Pinning the exact value means an accidental edit (or an in-place mutation
    that survived to import time) is caught immediately, not diagnosed later as
    a mystery failure in some unrelated suite.
    """

    def test_json_headers_is_exactly_the_json_content_type(self) -> None:
        """``JSON_HEADERS`` marks a body as JSON and carries nothing else."""
        assert JSON_HEADERS == {"Content-Type": "application/json"}

    def test_json_headers_is_a_plain_dict(self) -> None:
        """A plain ``dict`` — not a frozen/proxy type — so the spread idiom works."""
        assert type(JSON_HEADERS) is dict

    def test_get_paths_are_the_three_canonical_get_routes_in_order(self) -> None:
        """``GET_PATHS`` lists exactly the slash-free GET routes, order preserved."""
        assert GET_PATHS == ["/health", "/api/version", "/api/hello"]

    def test_get_paths_has_no_duplicates(self) -> None:
        """Duplicate entries would silently double-count in parametrized suites."""
        assert len(GET_PATHS) == len(set(GET_PATHS))

    def test_greeting_template_is_canonical(self) -> None:
        """The greeting template pins the exact ``str`` the /api/hello routes emit."""
        assert GREETING_TEMPLATE == "Hello, {name}! Welcome to your Software Factory."

    def test_cors_origins_are_the_expected_literals(self) -> None:
        """The three CORS origin constants keep their documented values."""
        assert LOCALHOST_ORIGIN == "http://localhost:3000"
        assert LOOPBACK_ORIGIN == "http://127.0.0.1:3000"
        assert DISALLOWED_ORIGIN == "https://evil.example.com"


class TestSpreadIdiomLeavesSharedConstantIntact:
    """The prescribed ``{**JSON_HEADERS, ...}`` idiom must not touch the shared dict.

    This is the exact pattern the conftest comment tells tests to use when they
    need extra headers. These tests prove it is genuinely non-mutating, so no
    later test can inherit a polluted ``JSON_HEADERS``.
    """

    def test_spread_produces_a_new_object(self) -> None:
        """Spreading yields a distinct dict, never an alias of the shared one."""
        extended = {**JSON_HEADERS, "Origin": LOCALHOST_ORIGIN}
        assert extended is not JSON_HEADERS

    def test_spread_preserves_original_contents(self) -> None:
        """After building a spread copy the shared dict is byte-for-byte unchanged."""
        before = dict(JSON_HEADERS)
        _ = {**JSON_HEADERS, "Origin": LOCALHOST_ORIGIN, "X-Extra": "1"}
        assert before == JSON_HEADERS

    def test_mutating_the_spread_copy_does_not_leak_into_the_shared_dict(self) -> None:
        """Writing to the *copy* must not reach back into the shared constant."""
        copy_headers = {**JSON_HEADERS}
        copy_headers["Content-Type"] = "text/plain"
        copy_headers["Origin"] = "https://mutated.example"
        assert JSON_HEADERS == {"Content-Type": "application/json"}
        assert "Origin" not in JSON_HEADERS

    def test_list_slice_copy_leaves_get_paths_intact(self) -> None:
        """The safe way to extend ``GET_PATHS`` (slice + append) never mutates it."""
        before = list(GET_PATHS)
        extended = [*GET_PATHS, "/api/new-route"]
        extended.append("/api/another")
        assert before == GET_PATHS
        assert "/api/new-route" not in GET_PATHS


class TestGuardDetectionLogic:
    """The session guard's comparison logic actually detects a mutated snapshot.

    We can't easily trigger the real session-teardown assertion from within a
    test, so we exercise the same deep-copy-then-compare mechanism the guard
    uses. This documents *why* the guard works: a deep copy diverges from its
    source the moment the source is mutated in place, and stays equal otherwise.
    """

    def test_deepcopy_snapshot_diverges_after_in_place_dict_mutation(self) -> None:
        """A deep-copy snapshot no longer equals a dict that was mutated in place."""
        live = {"Content-Type": "application/json"}
        snapshot = copy.deepcopy(live)
        assert live == snapshot
        live["Content-Type"] = "text/plain"  # simulate an errant in-place write
        assert live != snapshot

    def test_deepcopy_snapshot_diverges_after_in_place_list_mutation(self) -> None:
        """A deep-copy snapshot no longer equals a list that gained an element."""
        live = ["/health", "/api/version"]
        snapshot = copy.deepcopy(live)
        assert live == snapshot
        live.append("/api/leaked")  # simulate an errant in-place append
        assert live != snapshot

    def test_deepcopy_snapshot_stays_equal_when_source_is_untouched(self) -> None:
        """No mutation → snapshot and source remain equal (guard does not misfire)."""
        live = {"Content-Type": "application/json"}
        snapshot = copy.deepcopy(live)
        # A read-only spread must not perturb the source.
        _ = {**live, "Origin": LOCALHOST_ORIGIN}
        assert live == snapshot
