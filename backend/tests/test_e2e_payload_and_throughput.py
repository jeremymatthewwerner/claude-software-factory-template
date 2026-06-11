"""
E2E performance: payload-size scaling and concurrent throughput floors.

Focus: e2e-performance. The two existing perf suites
(``test_performance.py`` and ``test_e2e_performance_scaling.py``) already pin a
broad surface — single-call latency, init sequences, sequential/concurrent
throughput *ceilings*, p95/p99, jitter, cold start, head-of-line blocking,
mixed validity, round/burst stability, and *sequential* throughput floors.

This module covers two slices those suites deliberately leave open:

- **Payload-size scaling**: POST latency is pinned today only at fixed sizes
  (1KB, 10KB) against absolute ceilings. Neither suite asserts that latency
  grows roughly *linearly* with the request body. A regression that makes body
  handling quadratic — an accidental ``O(N^2)`` string concatenation in a
  middleware, a validator that re-scans the whole payload per character — can
  still slip under a fixed 10KB ceiling if 10KB happens to be fast, yet blow up
  for the larger names real users occasionally submit. Measuring across a 64B →
  64KB range and bounding the *ratio* of large-to-small latency catches the
  quadratic curve while a linear handler passes trivially.

- **Concurrent throughput floor**: every throughput *floor* today is measured
  with sequential calls. The concurrent suites bound *total elapsed time*, which
  catches a catastrophic stall but not a regression that merely halves
  sustained concurrent throughput while still fitting under the time ceiling.
  Asserting a minimum requests-per-second computed from a concurrent fan-out is
  a distinct guard: it fails the moment concurrent rps collapses.

All bounds are intentionally generous (well beyond typical observed values on a
shared CI runner) so they fail only on a real regression, never on noise.
"""

from __future__ import annotations

import asyncio
import statistics
import time

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

from .conftest import name_from_greeting

# --- Payload-size scaling ------------------------------------------------

# Name lengths (bytes) spanning three orders of magnitude. The smallest is the
# fixed-overhead baseline; the largest is ~64KB, far past anything the existing
# suites measure.
PAYLOAD_SCALING_SIZES = [64, 1024, 16384, 65536]

# Repetitions per size — the median over these is the regression signal,
# immune to a single GC/scheduler outlier on a shared runner.
PAYLOAD_SCALING_REPS = 7

# Absolute ceiling for the *largest* (64KB) payload. A linear handler serves
# 64KB in low single-digit ms; 1s leaves ~100x headroom.
LARGEST_PAYLOAD_CEILING_S = 1.0

# Max allowed ratio of median(largest) / median(smallest). The largest payload
# carries 1024x the bytes of the smallest, but per-request fixed overhead
# dominates both, so a linear handler's ratio is small (typically <10x). A
# quadratic regression would push the ratio toward the *square* of the size
# ratio (~10^6x), so a 50x cap separates linear from quadratic with wide margin.
PAYLOAD_QUADRATIC_GUARD_RATIO = 50.0

# Floor on the smaller median used in the ratio, so a near-zero denominator on a
# very fast runner can't manufacture a spurious ratio blow-up.
PAYLOAD_RATIO_MEDIAN_FLOOR_S = 0.001

# --- Concurrent throughput floors ----------------------------------------

# Requests issued in a single concurrent fan-out for the throughput-floor
# measurement, and the minimum sustained rps each must clear. Floors are set at
# roughly half the *sequential* floors in ``test_performance.py`` so they stay
# safely above CI noise while still failing on a real throughput collapse.
CONCURRENT_HEALTH_FANOUT = 100
CONCURRENT_HEALTH_FLOOR_RPS = 50.0
CONCURRENT_POST_FANOUT = 60
CONCURRENT_POST_FLOOR_RPS = 30.0

# --- Read/write latency parity -------------------------------------------

# How many calls to sample for each of GET and POST when comparing their median
# latency, and the factor by which POST's median may exceed GET's. POST does
# strictly more work (body read, JSON parse, validation), so it is legitimately
# a little slower; 8x + slack flags only a gross regression that puts real sync
# work on the write path.
PARITY_SAMPLE_CALLS = 80
PARITY_POST_OVER_GET_FACTOR = 8.0
PARITY_SLACK_S = 0.005


def _median_post_latency(client: TestClient, name: str, reps: int) -> float:
    """Return the median wall-time of ``reps`` POSTs of ``name`` to /api/hello.

    The median (not the mean) is used so a single outlier — a GC pause or
    scheduler preemption on a shared runner — cannot move the reported value.
    Each response is verified to echo the submitted name so a correctness
    regression at large payload sizes cannot masquerade as a fast pass.
    """
    timings: list[float] = []
    for _ in range(reps):
        start = time.perf_counter()
        response = client.post("/api/hello", json={"name": name})
        timings.append(time.perf_counter() - start)
        assert response.status_code == 200
        assert name_from_greeting(response.json()["message"]) == name
    return statistics.median(timings)


class TestPayloadSizeScaling:
    """POST latency must scale roughly linearly with request-body size.

    A fixed-size ceiling (the existing 1KB/10KB guards) bounds the absolute
    cost at one point; it cannot see the *shape* of the curve. These tests
    sample the curve across 64B → 64KB and assert it is not quadratic.
    """

    @pytest.mark.parametrize("size", PAYLOAD_SCALING_SIZES, ids=lambda s: f"{s}B")
    def test_each_payload_size_under_largest_ceiling(self, client: TestClient, size: int) -> None:
        """Median POST latency at every sampled size stays under the 64KB ceiling.

        Bounding even the small sizes by the same generous ceiling keeps this a
        pure absolute-cost guard; the ratio test below adds the shape guard.
        """
        median = _median_post_latency(client, "N" * size, PAYLOAD_SCALING_REPS)
        assert median < LARGEST_PAYLOAD_CEILING_S, (
            f"median POST latency for a {size}B name is {median * 1000:.2f}ms, "
            f"exceeds {LARGEST_PAYLOAD_CEILING_S * 1000:.0f}ms"
        )

    def test_latency_grows_sub_quadratically_with_payload(self, client: TestClient) -> None:
        """median(64KB) / median(64B) stays well below the quadratic threshold.

        A 1024x increase in body size produces only a modest latency increase
        for a linear handler (fixed per-request overhead dominates). A quadratic
        regression would inflate the ratio toward the square of the size ratio;
        the 50x cap sits far above any linear curve and far below any quadratic
        one.
        """
        smallest = "N" * PAYLOAD_SCALING_SIZES[0]
        largest = "N" * PAYLOAD_SCALING_SIZES[-1]
        median_small = _median_post_latency(client, smallest, PAYLOAD_SCALING_REPS)
        median_large = _median_post_latency(client, largest, PAYLOAD_SCALING_REPS)

        ratio = median_large / max(median_small, PAYLOAD_RATIO_MEDIAN_FLOOR_S)
        assert ratio < PAYLOAD_QUADRATIC_GUARD_RATIO, (
            f"POST latency ratio {ratio:.1f}x from {PAYLOAD_SCALING_SIZES[0]}B "
            f"({median_small * 1000:.2f}ms) to {PAYLOAD_SCALING_SIZES[-1]}B "
            f"({median_large * 1000:.2f}ms) exceeds {PAYLOAD_QUADRATIC_GUARD_RATIO}x "
            f"— possible super-linear body handling"
        )

    def test_marginal_cost_per_byte_does_not_increase_with_size(self, client: TestClient) -> None:
        """Amortized per-byte cost at 64KB is not dramatically worse than at 16KB.

        The ratio test above compares the largest size to the smallest, where
        fixed overhead dominates the denominator. This compares the two
        *largest* sizes — where marginal (per-byte) cost dominates — so a
        quadratic term shows up directly: under O(N^2) the per-byte cost rises
        with N, under O(N) it stays flat. A generous 4x cap (plus a small floor)
        tolerates measurement noise while catching a real super-linear term.
        """
        mid_size, big_size = PAYLOAD_SCALING_SIZES[-2], PAYLOAD_SCALING_SIZES[-1]
        median_mid = _median_post_latency(client, "N" * mid_size, PAYLOAD_SCALING_REPS)
        median_big = _median_post_latency(client, "N" * big_size, PAYLOAD_SCALING_REPS)

        per_byte_mid = median_mid / mid_size
        per_byte_big = median_big / big_size
        # +1µs/byte floor keeps the comparison stable when both medians are tiny
        # on a fast runner (sub-millisecond for 16KB).
        assert per_byte_big < per_byte_mid * 4.0 + 1e-6, (
            f"per-byte cost rose from {per_byte_mid * 1e6:.3f}µs/B at {mid_size}B "
            f"to {per_byte_big * 1e6:.3f}µs/B at {big_size}B — super-linear body handling"
        )


class TestConcurrentThroughputFloor:
    """Sustained throughput under concurrency must clear a minimum rps.

    The existing concurrent guards bound total elapsed time; the existing
    throughput floors are sequential. A regression that halves concurrent rps
    while still finishing under the time ceiling passes both — but fails an
    explicit concurrent rps floor.
    """

    @pytest.mark.asyncio
    async def test_concurrent_health_throughput_floor(self, async_client: AsyncClient) -> None:
        """A 100-wide concurrent /health fan-out sustains at least 50 req/sec."""
        start = time.perf_counter()
        responses = await asyncio.gather(
            *[async_client.get("/health") for _ in range(CONCURRENT_HEALTH_FANOUT)]
        )
        elapsed = time.perf_counter() - start
        assert all(r.status_code == 200 for r in responses)

        rps = CONCURRENT_HEALTH_FANOUT / elapsed
        assert rps >= CONCURRENT_HEALTH_FLOOR_RPS, (
            f"concurrent /health throughput {rps:.1f} req/s below floor "
            f"{CONCURRENT_HEALTH_FLOOR_RPS} — concurrent throughput collapse"
        )

    @pytest.mark.asyncio
    async def test_concurrent_post_throughput_floor(self, async_client: AsyncClient) -> None:
        """A 60-wide concurrent POST fan-out sustains at least 30 req/sec and stays correct."""
        names = [f"Tput{i:03d}" for i in range(CONCURRENT_POST_FANOUT)]
        start = time.perf_counter()
        responses = await asyncio.gather(
            *[async_client.post("/api/hello", json={"name": n}) for n in names]
        )
        elapsed = time.perf_counter() - start
        assert all(r.status_code == 200 for r in responses)

        rps = CONCURRENT_POST_FANOUT / elapsed
        assert rps >= CONCURRENT_POST_FLOOR_RPS, (
            f"concurrent POST throughput {rps:.1f} req/s below floor "
            f"{CONCURRENT_POST_FLOOR_RPS} — concurrent write throughput collapse"
        )
        # Throughput must not have been bought by dropping/garbling responses.
        returned = [name_from_greeting(r.json()["message"]) for r in responses]
        assert sorted(returned) == sorted(names)


class TestReadWriteLatencyParity:
    """A small-body POST must not be dramatically slower than a GET.

    GET and POST on /api/hello return the same trivial payload; POST does
    strictly more work (read body, parse JSON, validate the model), so it is
    legitimately a touch slower. But the gap must stay small — a regression that
    puts genuine synchronous work on the write path (a blocking validator, a
    sync log flush) would widen it. Comparing medians isolates that from the
    happy-path single-call ceilings, which would pass even if POST were 5x GET.
    """

    def test_small_post_median_within_factor_of_get_median(self, client: TestClient) -> None:
        """median POST(small body) latency stays within 8x median GET latency."""
        get_timings: list[float] = []
        for _ in range(PARITY_SAMPLE_CALLS):
            start = time.perf_counter()
            response = client.get("/api/hello")
            get_timings.append(time.perf_counter() - start)
            assert response.status_code == 200

        post_timings: list[float] = []
        for _ in range(PARITY_SAMPLE_CALLS):
            start = time.perf_counter()
            response = client.post("/api/hello", json={"name": "Parity"})
            post_timings.append(time.perf_counter() - start)
            assert response.status_code == 200

        get_median = statistics.median(get_timings)
        post_median = statistics.median(post_timings)
        assert post_median < get_median * PARITY_POST_OVER_GET_FACTOR + PARITY_SLACK_S, (
            f"POST median {post_median * 1000:.2f}ms exceeds {PARITY_POST_OVER_GET_FACTOR}x "
            f"GET median {get_median * 1000:.2f}ms — sync work on the write path?"
        )
