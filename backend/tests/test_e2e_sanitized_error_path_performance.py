"""
E2E performance: the *sanitized* 422 rebuild branch under load and at scale.

Focus: e2e-performance. Five perf suites already pin a broad surface, and the
error path is *partially* covered:

- ``test_performance.py`` — ``TestErrorPathLatency`` pins a single sequential
  422/404/405 latency ceiling.
- ``test_e2e_performance_scaling.py`` — bounds an interleaved 200/422 batch and
  the concurrent p95 of a 40-wide *invalid* fan-out.

Every one of those error-path guards, however, triggers the **plain** validation
path: a missing required field or a wrong-typed scalar. The echoed
``detail[].input`` for those cases is already JSON-encodable, so FastAPI's
default ``request_validation_exception_handler`` succeeds and the handler's
``except ValueError`` **rebuild branch never executes**. That branch is the one
piece of error-path code no perf test exercises, and it is by far the most
expensive and the most attacker-reachable:

    sanitized = _replace_lone_surrogates(_replace_non_finite(jsonable_encoder(exc.errors())))

Both ``_replace_non_finite`` and ``_replace_lone_surrogates`` **recurse over the
entire echoed payload**. They exist specifically to stop malformed
(attacker-controlled) request bodies — non-finite ``NaN``/``Infinity`` tokens and
unpaired UTF-16 surrogates — from turning a clean 422 into a 500. A performance
regression there (an accidental ``O(N^2)`` walk, a validator that blocks the
loop while rebuilding) would be a denial-of-service vector that the plain-path
error guards cannot see, because they never enter the branch.

This module closes exactly that gap with three slices, each distinct from the
plain-path coverage above:

- **Rebuild-branch latency under concurrency** — fan out bodies that *force* the
  branch (non-finite floats and lone surrogates) and bound the p95/p99 of the
  422 latency, with a correctness gate that the response is a clean, leak-free
  422 so a "fast" pass can't be bought by crashing or by leaking a bare ``NaN``.
- **Sanitizer scaling with structure size** — the recursive sanitizers walk the
  whole echoed structure, so their cost scales with how much malformed data the
  client sends. Sending an increasingly large invalid structure and bounding the
  large/small latency *ratio* catches a super-linear regression in ``_replace_*``
  while a linear walk passes trivially.
- **Rebuild-branch fairness vs the plain-422 path** — interleave rebuild-branch
  422s and plain missing-field 422s in one fan-out and bound the rebuild p95 to
  within a factor of the plain p95. This isolates the *extra* cost the branch
  adds over the plain path; a regression that made only the rebuild branch block
  the loop inflates the ratio while every plain-path guard still passes.

All bounds are intentionally generous (10-100x typical observed latency on a
shared CI runner) so they fail only on a real regression, never on noise. As in
the sibling suites we do not assert concurrent execution is *faster* than
sequential — the handlers are trivial and CPU-bound. We bound tail latency,
scaling shape, and cross-path fairness, which hold regardless.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from collections.abc import Coroutine

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient, Response

from .conftest import JSON_HEADERS, percentile

# --- Payloads that force the sanitized rebuild branch --------------------

# A body whose echoed ``input`` carries a non-finite float triggers the
# ``_replace_non_finite`` half of the rebuild branch. A body whose echoed input
# carries an unpaired UTF-16 surrogate triggers the ``_replace_lone_surrogates``
# half. Both are sent as raw ``content`` (not ``json=``) because httpx/json would
# refuse to serialise these non-standard tokens — the point is to feed the server
# exactly what a hostile client can put on the wire.
NONFINITE_BODY = b'{"name": [NaN, 1, Infinity, -Infinity]}'
SURROGATE_BODY = b'{"name": ["\\uD83D", "ok"]}'

# The plain-path 422 comparator: a missing required field. Its echoed input is
# already JSON-safe, so it takes the fast default handler and never enters the
# rebuild branch — the baseline the rebuild branch is measured against.
PLAIN_MISSING_BODY = b"{}"

# --- Concurrency / tail-latency bounds -----------------------------------

# Width of the concurrent rebuild-branch fan-out. 100 makes the p99 index (99)
# land on a real sample rather than rounding.
REBUILD_FANOUT = 100

# The rebuild branch does strictly more work than the happy path (encode the
# error list, recurse twice, re-serialise), but it is still trivial in absolute
# terms — low single-digit ms. 0.5s/0.75s leave ~100x headroom for scheduler
# overhead under contention. Mirrors the write-path tail ceilings so the error
# path is held to the same absolute standard as the write path.
REBUILD_TAIL_P95_CEILING_S = 0.5
REBUILD_TAIL_P99_CEILING_S = 0.75

# --- Sanitizer scaling bounds --------------------------------------------

# Element counts for the "large malformed structure" the recursive sanitizers
# must walk. The smallest is the fixed-overhead baseline; the largest sends 2000
# non-finite tokens in one array, all of which ``_replace_non_finite`` recurses
# over. Spanning 200x lets a quadratic term show up as a ~40000x latency blow-up.
SANITIZER_SCALING_SIZES = [10, 200, 2000]

# Repetitions per size — the median is the regression signal, immune to a single
# GC/scheduler outlier on a shared runner.
SANITIZER_SCALING_REPS = 7

# Absolute ceiling for the *largest* malformed structure. A linear recursive
# walk of 2000 elements runs in a few ms; 1s leaves ~100x headroom.
SANITIZER_LARGEST_CEILING_S = 1.0

# Max allowed ratio of median(largest) / median(smallest). The largest structure
# carries 200x the elements of the smallest, but per-request fixed overhead
# dominates both, so a linear sanitizer's ratio stays small (typically <20x). A
# quadratic regression pushes the ratio toward the *square* of the size ratio
# (~40000x), so a 60x cap separates linear from quadratic with wide margin.
SANITIZER_QUADRATIC_GUARD_RATIO = 60.0

# Floor on the smaller median used in the ratio, so a near-zero denominator on a
# very fast runner can't manufacture a spurious ratio blow-up.
SANITIZER_RATIO_MEDIAN_FLOOR_S = 0.001

# --- Fairness bounds -----------------------------------------------------

# Per-branch calls in the interleaved rebuild-vs-plain fan-out.
FAIRNESS_CALLS_PER_BRANCH = 40

# The rebuild-branch p95 may exceed the plain-path p95 by at most this factor
# before it signals the rebuild branch is disproportionately expensive under
# contention. The branch legitimately does more work, so the factor is generous.
REBUILD_VS_PLAIN_P95_RATIO_CEILING = 10.0

# Floor applied to the plain-path p95 before forming the fairness ratio, so a
# sub-millisecond denominator on a fast runner can't explode a harmless wobble
# into a spurious failure. Mirrors FAIRNESS_P95_FLOOR_S in the sibling suites.
FAIRNESS_P95_FLOOR_S = 0.002


def _assert_clean_sanitized_422(response: Response) -> None:
    """Assert ``response`` is a clean 422 from the sanitized rebuild branch.

    Two correctness gates so a latency/throughput win can never be bought by
    crashing or by leaking a raw non-standard token:

    - status is 422 (the branch turned malformed input into a clean validation
      error, not a 500), and
    - the response body is strict JSON — re-parsing it with a decoder that
      *rejects* the non-standard ``NaN``/``Infinity`` constants must succeed,
      proving no bare non-finite token survived into the wire payload.

    The body is read as raw bytes and UTF-8-decoded first: if a lone surrogate
    had leaked, ``response.text`` / ``.json()`` would already have decoded it, so
    asserting the raw bytes are valid UTF-8 is what actually pins the
    surrogate-sanitization guarantee.
    """
    assert response.status_code == 422, (
        f"sanitized error path returned {response.status_code}, not 422 — "
        f"the rebuild branch failed to turn malformed input into a clean 422"
    )
    raw = response.content
    # Raw bytes must be valid UTF-8 (no leaked lone surrogate on the wire).
    text = raw.decode("utf-8")
    # Strict re-parse: reject NaN/Infinity so a leaked non-finite token fails loudly.
    json.loads(text, parse_constant=_reject_nonstandard_constant)


def _reject_nonstandard_constant(token: str) -> object:
    """``parse_constant`` hook that fails if a bare ``NaN``/``Infinity`` survived."""
    raise AssertionError(f"non-standard JSON constant {token!r} leaked into the response body")


def _median_rebuild_latency(client: TestClient, body: bytes, reps: int) -> float:
    """Return the median wall-time of ``reps`` POSTs of raw ``body`` to /api/hello.

    Each response is asserted to be a clean sanitized 422 so a correctness
    regression at large structure sizes cannot masquerade as a fast pass. The
    median (not the mean) is used so a single scheduler/GC outlier on a shared
    runner cannot move the reported value.
    """
    timings: list[float] = []
    for _ in range(reps):
        start = time.perf_counter()
        response = client.post("/api/hello", content=body, headers=JSON_HEADERS)
        timings.append(time.perf_counter() - start)
        _assert_clean_sanitized_422(response)
    return statistics.median(timings)


def _nonfinite_array_body(n: int) -> bytes:
    """Return a ``{"name": [NaN, NaN, ...]}`` body carrying ``n`` non-finite tokens.

    The whole array is echoed back as the failing field's ``input``, so
    ``_replace_non_finite`` recurses over all ``n`` elements — making ``n`` a
    direct knob on the recursive sanitizer's workload.
    """
    return b'{"name": [' + b",".join([b"NaN"] * n) + b"]}"


class TestSanitizedRebuildBranchTailLatency:
    """The sanitized 422 rebuild branch must have a bounded tail *under contention*.

    The plain-path error guards never enter this branch. This fires
    ``REBUILD_FANOUT`` branch-forcing POSTs concurrently and bounds the p95/p99
    of their individual 422 latencies, so a straggler that only appears when many
    malformed bodies are sanitized at once is caught. Every response is gated as
    a clean, leak-free 422.
    """

    @pytest.mark.asyncio
    async def test_concurrent_nonfinite_422_p95_bounded(self, async_client: AsyncClient) -> None:
        """A 100-wide concurrent non-finite fan-out keeps rebuild-branch p95 bounded."""

        async def timed() -> float:
            start = time.perf_counter()
            response = await async_client.post(
                "/api/hello", content=NONFINITE_BODY, headers=JSON_HEADERS
            )
            elapsed = time.perf_counter() - start
            _assert_clean_sanitized_422(response)
            return elapsed

        latencies = sorted(await asyncio.gather(*[timed() for _ in range(REBUILD_FANOUT)]))
        p95 = percentile(latencies, 0.95)
        assert p95 < REBUILD_TAIL_P95_CEILING_S, (
            f"concurrent non-finite 422 p95 {p95 * 1000:.2f}ms exceeds "
            f"{REBUILD_TAIL_P95_CEILING_S * 1000:.0f}ms — rebuild branch stalls under contention"
        )

    @pytest.mark.asyncio
    async def test_concurrent_nonfinite_422_p99_bounded(self, async_client: AsyncClient) -> None:
        """A 100-wide concurrent non-finite fan-out keeps rebuild-branch p99 bounded.

        p99 is a deeper tail than any existing error-path guard (which stop at
        p95), so a rare-but-severe rebuild-branch straggler that p95 smooths over
        is surfaced here.
        """

        async def timed() -> float:
            start = time.perf_counter()
            response = await async_client.post(
                "/api/hello", content=NONFINITE_BODY, headers=JSON_HEADERS
            )
            elapsed = time.perf_counter() - start
            _assert_clean_sanitized_422(response)
            return elapsed

        latencies = sorted(await asyncio.gather(*[timed() for _ in range(REBUILD_FANOUT)]))
        p99 = percentile(latencies, 0.99)
        assert p99 < REBUILD_TAIL_P99_CEILING_S, (
            f"concurrent non-finite 422 p99 {p99 * 1000:.2f}ms exceeds "
            f"{REBUILD_TAIL_P99_CEILING_S * 1000:.0f}ms — deep rebuild-branch tail under contention"
        )

    @pytest.mark.asyncio
    async def test_concurrent_surrogate_422_p95_bounded(self, async_client: AsyncClient) -> None:
        """A 100-wide concurrent lone-surrogate fan-out keeps the *other* sanitizer bounded.

        The non-finite tests above exercise ``_replace_non_finite``; this drives
        ``_replace_lone_surrogates`` — the second recursive sanitizer in the
        branch — under the same concurrent load, so a straggler specific to
        surrogate transcription is caught too.
        """

        async def timed() -> float:
            start = time.perf_counter()
            response = await async_client.post(
                "/api/hello", content=SURROGATE_BODY, headers=JSON_HEADERS
            )
            elapsed = time.perf_counter() - start
            _assert_clean_sanitized_422(response)
            return elapsed

        latencies = sorted(await asyncio.gather(*[timed() for _ in range(REBUILD_FANOUT)]))
        p95 = percentile(latencies, 0.95)
        assert p95 < REBUILD_TAIL_P95_CEILING_S, (
            f"concurrent lone-surrogate 422 p95 {p95 * 1000:.2f}ms exceeds "
            f"{REBUILD_TAIL_P95_CEILING_S * 1000:.0f}ms — surrogate sanitizer stalls under load"
        )


class TestSanitizerScalesWithStructureSize:
    """Rebuild-branch latency must scale roughly linearly with the malformed structure.

    ``_replace_non_finite`` recurses over the entire echoed payload, so its cost
    grows with how much malformed data the client sends — an attacker-controlled
    knob. A fixed-size error-path ceiling cannot see the *shape* of that curve.
    These tests sample it across a 200x element range and assert it is not
    quadratic, directly guarding the recursive sanitizer against an O(N^2)
    regression.
    """

    @pytest.mark.parametrize("size", SANITIZER_SCALING_SIZES, ids=lambda s: f"{s}elems")
    def test_each_structure_size_under_largest_ceiling(self, client: TestClient, size: int) -> None:
        """Median rebuild-branch latency at every sampled size stays under the ceiling.

        Bounding even the small sizes by the same generous ceiling keeps this a
        pure absolute-cost guard; the ratio test below adds the shape guard.
        """
        median = _median_rebuild_latency(
            client, _nonfinite_array_body(size), SANITIZER_SCALING_REPS
        )
        assert median < SANITIZER_LARGEST_CEILING_S, (
            f"median rebuild-branch latency for a {size}-element non-finite array is "
            f"{median * 1000:.2f}ms, exceeds {SANITIZER_LARGEST_CEILING_S * 1000:.0f}ms"
        )

    def test_latency_grows_sub_quadratically_with_structure_size(self, client: TestClient) -> None:
        """median(2000 elems) / median(10 elems) stays well below the quadratic threshold.

        A 200x increase in element count produces only a modest latency increase
        for a linear recursive walk (fixed per-request overhead dominates the
        denominator). A quadratic regression in ``_replace_non_finite`` would
        inflate the ratio toward the square of the size ratio; the 60x cap sits
        far above any linear curve and far below any quadratic one.
        """
        smallest = _nonfinite_array_body(SANITIZER_SCALING_SIZES[0])
        largest = _nonfinite_array_body(SANITIZER_SCALING_SIZES[-1])
        median_small = _median_rebuild_latency(client, smallest, SANITIZER_SCALING_REPS)
        median_large = _median_rebuild_latency(client, largest, SANITIZER_SCALING_REPS)

        ratio = median_large / max(median_small, SANITIZER_RATIO_MEDIAN_FLOOR_S)
        assert ratio < SANITIZER_QUADRATIC_GUARD_RATIO, (
            f"rebuild-branch latency ratio {ratio:.1f}x from {SANITIZER_SCALING_SIZES[0]} elems "
            f"({median_small * 1000:.2f}ms) to {SANITIZER_SCALING_SIZES[-1]} elems "
            f"({median_large * 1000:.2f}ms) exceeds {SANITIZER_QUADRATIC_GUARD_RATIO}x — "
            f"possible super-linear sanitizer recursion"
        )


class TestRebuildBranchFairnessVsPlainPath:
    """The rebuild branch must not be disproportionately expensive vs the plain 422 path.

    The plain-path guards bound the fast default handler; this interleaves
    rebuild-branch 422s (non-finite body) and plain missing-field 422s in one
    fan-out and bounds the rebuild p95 to within a factor of the plain p95. That
    isolates the *extra* cost the branch adds: a regression that made only the
    rebuild branch block the loop inflates this ratio while every plain-path
    error guard still passes.
    """

    @pytest.mark.asyncio
    async def test_rebuild_p95_within_factor_of_plain_p95_in_mixed_fanout(
        self, async_client: AsyncClient
    ) -> None:
        """Rebuild-branch p95 stays within a bounded factor of plain-422 p95 when interleaved."""

        async def sample_rebuild() -> tuple[str, float]:
            start = time.perf_counter()
            response = await async_client.post(
                "/api/hello", content=NONFINITE_BODY, headers=JSON_HEADERS
            )
            elapsed = time.perf_counter() - start
            _assert_clean_sanitized_422(response)
            return "REBUILD", elapsed

        async def sample_plain() -> tuple[str, float]:
            start = time.perf_counter()
            response = await async_client.post(
                "/api/hello", content=PLAIN_MISSING_BODY, headers=JSON_HEADERS
            )
            elapsed = time.perf_counter() - start
            # Plain path: a clean 422 that never enters the rebuild branch.
            assert response.status_code == 422
            return "PLAIN", elapsed

        # Interleave so the two paths genuinely contend for the same event loop
        # rather than running as two back-to-back blocks.
        coros: list[Coroutine[object, object, tuple[str, float]]] = []
        for _ in range(FAIRNESS_CALLS_PER_BRANCH):
            coros.append(sample_rebuild())
            coros.append(sample_plain())
        samples = await asyncio.gather(*coros)

        rebuild_lat = sorted(e for kind, e in samples if kind == "REBUILD")
        plain_lat = sorted(e for kind, e in samples if kind == "PLAIN")
        plain_p95 = max(percentile(plain_lat, 0.95), FAIRNESS_P95_FLOOR_S)
        rebuild_p95 = percentile(rebuild_lat, 0.95)

        ratio = rebuild_p95 / plain_p95
        assert ratio < REBUILD_VS_PLAIN_P95_RATIO_CEILING, (
            f"rebuild-branch p95 {rebuild_p95 * 1000:.1f}ms is {ratio:.1f}x the plain-422 p95 "
            f"{plain_p95 * 1000:.1f}ms in a mixed fan-out — the sanitized error path is "
            f"disproportionately expensive under contention (ceiling "
            f"{REBUILD_VS_PLAIN_P95_RATIO_CEILING}x)"
        )
