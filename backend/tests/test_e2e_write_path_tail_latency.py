"""
E2E performance: write-path (``POST /api/hello``) tail latency under concurrency.

Focus: e2e-performance. Four perf suites already pin a broad surface, but every
one of them leaves the *write path under concurrent contention* uncovered:

- ``test_performance.py`` — ``TestNonHealthTailLatency`` pins ``POST`` p95, but
  measured over 200 **sequential** calls, so no request ever contends with
  another. A tail that only appears when many bodies are parsed/validated at
  once cannot show up there.
- ``test_e2e_performance_scaling.py`` — ``TestConcurrentTailLatency`` *does*
  time each request individually inside a fan-out, but exercises **GET only**
  (``/health``, ``/api/version``). Those handlers never touch the body-read →
  JSON-decode → Pydantic-validate → f-string-format pipeline the POST handler
  runs, so a write-path-specific straggler slips through.
- ``test_e2e_journey_performance.py`` — ``TestCrossEndpointFairness`` bounds
  per-endpoint p95 fairness, but fans out ``GET_PATHS`` **only**; POST is
  excluded, so relative starvation of the write path under mixed load is
  unguarded.
- No concurrent suite pins **p99** of an in-fan-out latency distribution — the
  existing concurrent-tail guards stop at p95 and max.

This module closes exactly that gap. It measures the POST handler's individual
latency from *inside* a concurrent fan-out and pins:

- **p95 under contention** — the tail of the write path when many POSTs are
  genuinely in flight together, not one-at-a-time.
- **p99 under contention** — a deeper tail than any existing concurrent test,
  so a rare-but-severe write-path straggler is caught.
- **Write-path fairness vs the read path** — POST and GET latencies gathered
  from the *same* interleaved fan-out; the POST p95 must stay within a bounded
  factor of the GET p95. A regression that serialised only the write path (a
  lock around body handling, a validator that blocks the loop) would inflate
  the POST tail relative to the GETs sharing the loop, failing here while every
  GET-only tail guard passes.

Every test also asserts each POST echoes *its own* name, so a latency/throughput
win can never be bought by garbling or dropping validation of responses.

Bounds are deliberately generous (10x+ typical observed latency on shared CI
runners) so these fail only on real regressions, not on runner noise.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Coroutine

import pytest
from httpx import AsyncClient, Response

from .conftest import name_from_greeting

# --- Ceilings (generous; sized for shared CI runners) --------------------

# Individual POST latency measured from inside a concurrent fan-out. A trivial
# write handler runs ~1-5ms; 0.5s leaves ~100x headroom for scheduler overhead
# under contention. Matches the GET-side CONCURRENT_TAIL_P95_CEILING_S so the
# read and write paths are held to the same absolute standard.
WRITE_TAIL_P95_CEILING_S = 0.5

# p99 is a deeper tail than p95, so it gets slightly more slack — a single slow
# request among a hundred should not fail the guard on a noisy runner.
WRITE_TAIL_P99_CEILING_S = 0.75

# Width of the pure-POST fan-out used for the p95/p99 distribution tests. 100
# requests makes the p99 index (99) land on a real sample rather than rounding.
POST_FANOUT = 100

# Per-endpoint calls in the interleaved GET+POST fairness fan-out.
FAIRNESS_CALLS_PER_ENDPOINT = 40

# The POST p95 may exceed the GET p95 by at most this factor in a mixed fan-out
# before it signals the write path is being starved relative to the read path.
WRITE_VS_READ_P95_RATIO_CEILING = 6.0

# Floor applied to the GET p95 before forming the fairness ratio. When every
# call is sub-millisecond, dividing by a near-zero denominator would explode a
# harmless timing wobble into a spurious failure; flooring keeps the ratio
# meaningful. Mirrors FAIRNESS_P95_FLOOR_S in test_e2e_journey_performance.py.
FAIRNESS_P95_FLOOR_S = 0.002


async def _timed_post(client: AsyncClient, name: str) -> tuple[Response, float, str]:
    """Issue a personalized POST and return ``(response, elapsed_seconds, name)``.

    Timing each coroutine individually lets a concurrent fan-out report the
    *per-request* write-path latency distribution, not just the batch
    wall-time — that is what surfaces a straggler hiding under contention. The
    name is threaded through so the caller can verify each response echoed the
    exact name it was called with.
    """
    start = time.perf_counter()
    response = await client.post("/api/hello", json={"name": name})
    return response, time.perf_counter() - start, name


async def _timed_get(client: AsyncClient, path: str) -> tuple[Response, float]:
    """Issue a GET and return ``(response, elapsed_seconds)``."""
    start = time.perf_counter()
    response = await client.get(path)
    return response, time.perf_counter() - start


def _percentile(sorted_latencies: list[float], pct: float) -> float:
    """Return the ``pct`` (0-1) percentile of an already-sorted latency list."""
    idx = min(int(len(sorted_latencies) * pct), len(sorted_latencies) - 1)
    return sorted_latencies[idx]


class TestConcurrentWritePathTailLatency:
    """The POST write path must have a bounded tail *under contention*.

    Sequential POST p95 is pinned elsewhere; this fires ``POST_FANOUT`` POSTs
    concurrently and bounds the p95 and p99 of their individual latencies, so a
    write-path straggler that only appears when many bodies are parsed and
    validated at once is caught. Every echo is verified so the tail cannot be
    trimmed by dropping validation.
    """

    @pytest.mark.asyncio
    async def test_concurrent_post_p95_individual_latency_bounded(
        self, async_client: AsyncClient
    ) -> None:
        """In a 100-wide concurrent POST fan-out, p95 individual latency stays bounded."""
        names = [f"P95U{i:03d}" for i in range(POST_FANOUT)]
        results = await asyncio.gather(*[_timed_post(async_client, n) for n in names])

        assert all(r.status_code == 200 for r, _, _ in results)
        # Each response must echo its own name — no cross-talk under contention.
        for response, _, name in results:
            assert name_from_greeting(response.json()["message"]) == name, (
                f"POST for {name!r} echoed a different name — concurrent write-path "
                f"state corruption"
            )

        latencies = sorted(elapsed for _, elapsed, _ in results)
        p95 = _percentile(latencies, 0.95)
        assert p95 < WRITE_TAIL_P95_CEILING_S, (
            f"concurrent POST p95 individual latency {p95 * 1000:.2f}ms exceeds "
            f"{WRITE_TAIL_P95_CEILING_S * 1000:.0f}ms — write-path straggler under contention"
        )

    @pytest.mark.asyncio
    async def test_concurrent_post_p99_individual_latency_bounded(
        self, async_client: AsyncClient
    ) -> None:
        """In a 100-wide concurrent POST fan-out, p99 individual latency stays bounded.

        p99 is a deeper tail than any existing concurrent guard (which stop at
        p95/max), so a rare-but-severe write-path straggler that p95 smooths
        over is surfaced here.
        """
        names = [f"P99U{i:03d}" for i in range(POST_FANOUT)]
        results = await asyncio.gather(*[_timed_post(async_client, n) for n in names])

        assert all(r.status_code == 200 for r, _, _ in results)
        for response, _, name in results:
            assert name_from_greeting(response.json()["message"]) == name

        latencies = sorted(elapsed for _, elapsed, _ in results)
        p99 = _percentile(latencies, 0.99)
        assert p99 < WRITE_TAIL_P99_CEILING_S, (
            f"concurrent POST p99 individual latency {p99 * 1000:.2f}ms exceeds "
            f"{WRITE_TAIL_P99_CEILING_S * 1000:.0f}ms — deep write-path tail under contention"
        )

    @pytest.mark.asyncio
    async def test_no_single_concurrent_post_exceeds_p99_ceiling(
        self, async_client: AsyncClient
    ) -> None:
        """No individual POST in the fan-out exceeds the p99 ceiling.

        The p95/p99 tests bound the distribution; this bounds the single worst
        request. A lone POST that stalls badly under contention (while the rest
        stay fast, so percentiles look healthy) is caught here.
        """
        names = [f"MAXU{i:03d}" for i in range(POST_FANOUT)]
        results = await asyncio.gather(*[_timed_post(async_client, n) for n in names])

        assert all(r.status_code == 200 for r, _, _ in results)
        worst_response, worst_latency, worst_name = max(results, key=lambda r: r[1])
        assert name_from_greeting(worst_response.json()["message"]) == worst_name
        assert worst_latency < WRITE_TAIL_P99_CEILING_S, (
            f"slowest concurrent POST ({worst_name!r}) took {worst_latency * 1000:.2f}ms, "
            f"exceeds {WRITE_TAIL_P99_CEILING_S * 1000:.0f}ms — write-path straggler"
        )


class TestWritePathFairnessUnderMixedContention:
    """The write path must not be starved relative to the read path.

    ``TestCrossEndpointFairness`` fans out GET endpoints only; this interleaves
    GETs and POSTs in one fan-out and bounds the POST p95 to within a factor of
    the GET p95. A regression that serialised only the write path — a lock
    around body handling, a validator that blocks the loop — inflates the POST
    tail relative to the GETs sharing the same loop, failing here while every
    GET-only tail guard still passes.
    """

    @pytest.mark.asyncio
    async def test_post_p95_within_factor_of_get_p95_in_mixed_fanout(
        self, async_client: AsyncClient
    ) -> None:
        """POST p95 stays within a bounded factor of GET p95 in an interleaved fan-out."""
        names = [f"FAIR{i:03d}" for i in range(FAIRNESS_CALLS_PER_ENDPOINT)]

        async def timed_get(path: str) -> tuple[str, float]:
            _, elapsed = await _timed_get(async_client, path)
            return "GET", elapsed

        async def timed_post(name: str) -> tuple[str, float]:
            response, elapsed, echoed = await _timed_post(async_client, name)
            # Correctness gate: fairness must not be met by garbling responses.
            assert response.status_code == 200
            assert name_from_greeting(response.json()["message"]) == echoed
            return "POST", elapsed

        # Interleave so reads and writes genuinely contend for the same loop
        # rather than running as two back-to-back blocks.
        coros: list[Coroutine[object, object, tuple[str, float]]] = []
        for name in names:
            coros.append(timed_get("/health"))
            coros.append(timed_post(name))
        samples = await asyncio.gather(*coros)

        get_lat = sorted(e for kind, e in samples if kind == "GET")
        post_lat = sorted(e for kind, e in samples if kind == "POST")
        get_p95 = max(_percentile(get_lat, 0.95), FAIRNESS_P95_FLOOR_S)
        post_p95 = _percentile(post_lat, 0.95)

        ratio = post_p95 / get_p95
        assert ratio < WRITE_VS_READ_P95_RATIO_CEILING, (
            f"POST p95 {post_p95 * 1000:.1f}ms is {ratio:.1f}x the GET p95 "
            f"{get_p95 * 1000:.1f}ms in a mixed fan-out — write path starved under "
            f"contention (ceiling {WRITE_VS_READ_P95_RATIO_CEILING}x)"
        )
