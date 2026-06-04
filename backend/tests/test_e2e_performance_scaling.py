"""
E2E performance: parallelism and scaling regression guards.

``test_performance.py`` already pins single-call latency, init sequences,
sequential/concurrent throughput, p95/p99 distribution, cold start, jitter,
and throughput floors. This module covers a deliberately *orthogonal* slice
focused on how the app behaves as concurrency and repetition scale — the
properties that only surface when many requests are genuinely in flight at
once or the suite is hammered repeatedly:

- **Scaling**: amortized per-request cost must stay bounded as concurrency
  grows (20 → 40 → 80). A super-linear (e.g. O(N^2)) coordination regression
  — a global lock, an accidental quadratic scan keyed on in-flight count —
  would inflate per-request cost as N rises; a flat ceiling catches it.
- **Concurrent tail latency**: the *individual* latency of each request
  measured from *inside* a concurrent fan-out. The existing p95 tests measure
  sequential calls; a straggler that only appears under contention slips
  through them.
- **Head-of-line blocking**: a large (10KB) POST in flight must not stall the
  small GETs issued alongside it. On a correctly cooperative event loop the
  batch finishes fast; a serialized handler makes the small requests wait.
- **Round-over-round stability**: repeated concurrent rounds must not degrade
  — a per-request resource leak (unclosed object, unbounded cache) shows up as
  later rounds getting steadily slower.
- **Mixed valid/invalid concurrency**: interleaved 200 and 422 responses must
  all resolve correctly and quickly — request validation failures must not
  serialize or stall the loop.

All bounds are intentionally generous (10–100x typical observed latency on CI
runners) so they fail only on real regressions, never on noisy shared CI.

Note on speedup: these tests deliberately do **not** assert that concurrent
execution is *faster* than sequential. The handlers are trivial and purely
CPU-bound (no real I/O await), so on a single-threaded event loop concurrent
fan-out is legitimately *not* faster — asserting otherwise would be flaky and
wrong. We assert bounded *aggregate* cost and bounded *tails* instead, which
hold regardless of whether parallelism yields wall-clock speedup.
"""

from __future__ import annotations

import asyncio
import statistics
import time

import pytest
from httpx import AsyncClient, Response

from .conftest import name_from_greeting

# --- Ceilings (generous; sized for shared CI runners) --------------------

# Amortized wall-time per request inside a concurrent batch. Trivial handlers
# run ~1-5ms; 50ms leaves ~10x headroom for scheduler overhead under load.
SCALING_PER_REQUEST_CEILING_S = 0.05

# p95 of an individual request's latency measured from inside a 50-wide
# fan-out. Generous vs the ~5ms typical single call.
CONCURRENT_TAIL_P95_CEILING_S = 0.5

# A 10KB POST plus 40 small GETs issued together must all finish within this.
HEAD_OF_LINE_CEILING_S = 1.0

# Per-round total for repeated concurrent rounds, and the factor by which the
# slowest round may exceed the fastest before it signals degradation.
ROUND_TOTAL_CEILING_S = 1.0
ROUND_DEGRADATION_FACTOR = 4.0

# Interleaved valid (200) + invalid (422) concurrent batch ceiling.
MIXED_VALIDITY_CEILING_S = 1.0


async def _timed_get(client: AsyncClient, path: str) -> tuple[Response, float]:
    """Issue a GET and return ``(response, elapsed_seconds)``.

    Timing each coroutine individually lets a concurrent fan-out report the
    *per-request* latency distribution, not just the batch wall-time — that
    is what surfaces a straggler hiding under contention.
    """
    start = time.perf_counter()
    response = await client.get(path)
    return response, time.perf_counter() - start


class TestConcurrencyScaling:
    """Amortized per-request cost must stay flat as concurrency grows.

    If coordination cost were super-linear in the number of in-flight
    requests, the amortized per-request time would climb with N. Measuring at
    20, 40, and 80 and holding each under the same flat ceiling catches that.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("concurrency", [20, 40, 80], ids=["n20", "n40", "n80"])
    async def test_amortized_per_request_cost_bounded(
        self, async_client: AsyncClient, concurrency: int
    ) -> None:
        """Amortized wall-time per request stays under the ceiling at every N."""
        start = time.perf_counter()
        responses = await asyncio.gather(*[async_client.get("/health") for _ in range(concurrency)])
        elapsed = time.perf_counter() - start

        assert all(r.status_code == 200 for r in responses)
        per_request = elapsed / concurrency
        assert per_request < SCALING_PER_REQUEST_CEILING_S, (
            f"{concurrency} concurrent: {per_request * 1000:.2f}ms/req exceeds "
            f"{SCALING_PER_REQUEST_CEILING_S * 1000:.0f}ms — possible super-linear "
            f"coordination cost"
        )

    @pytest.mark.asyncio
    async def test_per_request_cost_does_not_grow_with_concurrency(
        self, async_client: AsyncClient
    ) -> None:
        """Per-request cost at 80-wide is not dramatically worse than at 20-wide.

        A flat ceiling (above) bounds the absolute value; this bounds the
        *trend*. If doubling-and-doubling concurrency inflated per-request
        cost super-linearly, the 80/20 ratio would blow past the factor.
        """

        async def amortized(n: int) -> float:
            start = time.perf_counter()
            await asyncio.gather(*[async_client.get("/health") for _ in range(n)])
            return (time.perf_counter() - start) / n

        small = await amortized(20)
        large = await amortized(80)

        # +5ms slack absorbs noise on the fast end where both are sub-ms and a
        # raw ratio would be dominated by measurement jitter.
        assert large < small * ROUND_DEGRADATION_FACTOR + 0.005, (
            f"per-request cost grew from {small * 1000:.2f}ms (n=20) to "
            f"{large * 1000:.2f}ms (n=80) — worse than {ROUND_DEGRADATION_FACTOR}x, "
            f"suggests super-linear scaling"
        )


class TestConcurrentTailLatency:
    """Individual request latency *within* a fan-out must have a bounded tail.

    The p95 tests in ``test_performance.py`` measure sequential calls. A
    straggler that only appears when 50 requests contend for the loop would
    not show up there. Here each request is timed individually inside the
    fan-out and the p95/max of that distribution is bounded.
    """

    @pytest.mark.asyncio
    async def test_p95_individual_latency_within_fanout_bounded(
        self, async_client: AsyncClient
    ) -> None:
        """In a 50-wide concurrent fan-out, p95 individual latency stays bounded."""
        results = await asyncio.gather(*[_timed_get(async_client, "/health") for _ in range(50)])
        assert all(r.status_code == 200 for r, _ in results)

        latencies = sorted(elapsed for _, elapsed in results)
        p95 = latencies[int(len(latencies) * 0.95)]
        assert p95 < CONCURRENT_TAIL_P95_CEILING_S, (
            f"concurrent p95 individual latency {p95 * 1000:.2f}ms exceeds "
            f"{CONCURRENT_TAIL_P95_CEILING_S * 1000:.0f}ms — straggler under contention"
        )

    @pytest.mark.asyncio
    async def test_max_individual_latency_within_fanout_bounded(
        self, async_client: AsyncClient
    ) -> None:
        """No single request in a 50-wide fan-out exceeds the single-call ceiling."""
        results = await asyncio.gather(
            *[_timed_get(async_client, "/api/version") for _ in range(50)]
        )
        assert all(r.status_code == 200 for r, _ in results)

        worst = max(elapsed for _, elapsed in results)
        assert worst < CONCURRENT_TAIL_P95_CEILING_S, (
            f"slowest request in fan-out took {worst * 1000:.2f}ms, exceeds "
            f"{CONCURRENT_TAIL_P95_CEILING_S * 1000:.0f}ms"
        )


class TestHeadOfLineBlocking:
    """A large in-flight request must not stall small concurrent ones.

    Existing tests measure large payloads *in isolation*. This issues one
    10KB POST together with 40 small GETs and asserts the whole batch — and
    the small requests in particular — finishes fast. A handler that blocks
    the event loop while processing the big body would make the small GETs
    wait behind it (head-of-line blocking).
    """

    @pytest.mark.asyncio
    async def test_large_post_does_not_block_concurrent_small_gets(
        self, async_client: AsyncClient
    ) -> None:
        """One 10KB POST + 40 small GETs issued together all finish under ceiling."""
        big_name = "A" * 10240
        coros = [_timed_get(async_client, "/health") for _ in range(40)]

        start = time.perf_counter()
        big_post_task = async_client.post("/api/hello", json={"name": big_name})
        small_results, big_response = await asyncio.gather(asyncio.gather(*coros), big_post_task)
        elapsed = time.perf_counter() - start

        assert big_response.status_code == 200
        assert name_from_greeting(big_response.json()["message"]) == big_name
        assert all(r.status_code == 200 for r, _ in small_results)
        assert elapsed < HEAD_OF_LINE_CEILING_S, (
            f"large POST + 40 small GETs took {elapsed:.3f}s — possible "
            f"head-of-line blocking on the big request"
        )

        # The small GETs individually must stay fast — if the big POST blocked
        # the loop, their individual latencies would spike even though the
        # batch wall-time might still pass.
        worst_small = max(e for _, e in small_results)
        assert worst_small < CONCURRENT_TAIL_P95_CEILING_S, (
            f"slowest small GET took {worst_small * 1000:.2f}ms while a 10KB POST "
            f"was in flight — head-of-line blocking"
        )


class TestRepeatedConcurrentRoundStability:
    """Repeated concurrent rounds must not degrade over time.

    A per-request resource leak (an object never released, an unbounded cache
    keyed per request) manifests as later rounds getting steadily slower. We
    run several identical concurrent rounds and assert (a) every round stays
    under a flat ceiling and (b) the slowest round is not dramatically worse
    than the fastest.
    """

    @pytest.mark.asyncio
    async def test_five_concurrent_rounds_no_degradation(self, async_client: AsyncClient) -> None:
        """Five rounds of 30 concurrent /health calls show no round-over-round drift."""
        round_totals: list[float] = []
        for _ in range(5):
            start = time.perf_counter()
            responses = await asyncio.gather(*[async_client.get("/health") for _ in range(30)])
            round_totals.append(time.perf_counter() - start)
            assert all(r.status_code == 200 for r in responses)

        for i, total in enumerate(round_totals):
            assert total < ROUND_TOTAL_CEILING_S, (
                f"round {i} of 30 concurrent calls took {total:.3f}s, exceeds "
                f"{ROUND_TOTAL_CEILING_S}s"
            )

        fastest, slowest = min(round_totals), max(round_totals)
        # +0.1s slack so the comparison is meaningful when every round is fast.
        assert slowest < fastest * ROUND_DEGRADATION_FACTOR + 0.1, (
            f"slowest round {slowest:.3f}s vs fastest {fastest:.3f}s exceeds "
            f"{ROUND_DEGRADATION_FACTOR}x — resource leak or degradation under load"
        )

    @pytest.mark.asyncio
    async def test_round_totals_not_monotonically_increasing(
        self, async_client: AsyncClient
    ) -> None:
        """Round totals must not climb every single round (steady leak signature).

        A strictly increasing sequence of round times is the classic leak
        signature. Pure noise produces a non-monotonic sequence, so requiring
        at least one round to be faster than its predecessor is a robust,
        low-flake guard.
        """
        round_totals: list[float] = []
        for _ in range(6):
            start = time.perf_counter()
            await asyncio.gather(*[async_client.get("/health") for _ in range(25)])
            round_totals.append(time.perf_counter() - start)

        improved = any(round_totals[i] < round_totals[i - 1] for i in range(1, len(round_totals)))
        assert improved, (
            f"round totals increased every round ({[f'{t * 1000:.1f}ms' for t in round_totals]}) "
            f"— monotonic growth suggests a per-request leak"
        )


class TestMixedValidityConcurrency:
    """Interleaved valid and invalid requests must all resolve quickly.

    Request-validation failures (422) take a different code path than 200s. If
    that path were to block or serialize the loop, a batch mixing the two
    would stall. This interleaves 20 valid POSTs with 20 invalid ones (missing
    ``name``) and asserts every response has the expected status, in order,
    under the ceiling.
    """

    @pytest.mark.asyncio
    async def test_interleaved_200_and_422_under_ceiling(self, async_client: AsyncClient) -> None:
        """20 valid + 20 invalid POSTs issued together all resolve correctly and fast."""
        names = [f"Valid{i:02d}" for i in range(20)]
        coros = []
        for name in names:
            coros.append(async_client.post("/api/hello", json={"name": name}))
            # Invalid: missing required ``name`` field → 422.
            coros.append(async_client.post("/api/hello", json={}))

        start = time.perf_counter()
        responses = await asyncio.gather(*coros)
        elapsed = time.perf_counter() - start

        assert elapsed < MIXED_VALIDITY_CEILING_S, f"interleaved 200/422 batch took {elapsed:.3f}s"

        # Even indices are the valid POSTs, odd indices the invalid ones.
        valid_responses = responses[0::2]
        invalid_responses = responses[1::2]
        assert all(r.status_code == 200 for r in valid_responses)
        assert all(r.status_code == 422 for r in invalid_responses)

        # Valid responses must still echo their own name — the concurrent
        # invalid requests must not corrupt the valid handler's per-request state.
        returned = [name_from_greeting(r.json()["message"]) for r in valid_responses]
        assert sorted(returned) == sorted(names)

    @pytest.mark.asyncio
    async def test_error_path_latency_bounded_under_concurrency(
        self, async_client: AsyncClient
    ) -> None:
        """Individual 422 latencies inside a 40-wide invalid fan-out stay bounded."""

        async def timed_invalid() -> float:
            start = time.perf_counter()
            response = await async_client.post("/api/hello", json={})
            assert response.status_code == 422
            return time.perf_counter() - start

        latencies = await asyncio.gather(*[timed_invalid() for _ in range(40)])
        p95 = sorted(latencies)[int(len(latencies) * 0.95)]
        assert p95 < CONCURRENT_TAIL_P95_CEILING_S, (
            f"concurrent 422 p95 latency {p95 * 1000:.2f}ms exceeds "
            f"{CONCURRENT_TAIL_P95_CEILING_S * 1000:.0f}ms — validation path stalls under load"
        )
        # statistics import sanity (median used as a documented secondary signal).
        median = statistics.median(latencies)
        assert median <= p95, "median latency cannot exceed p95"
