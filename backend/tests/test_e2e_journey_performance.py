"""
E2E performance: full user-journey budgets, cross-endpoint fairness, and
per-round concurrent throughput stability.

Focus: e2e-performance. Three perf suites already pin a broad surface —
``test_performance.py`` (single-call latency, p95/p99, jitter, cold start,
sequential floors, CORS/OpenAPI/docs timing), ``test_e2e_performance_scaling.py``
(concurrency scaling, concurrent tail latency, head-of-line blocking, round
*ratio* stability, mixed validity) and ``test_e2e_payload_and_throughput.py``
(payload-size scaling, single concurrent rps floor, read/write parity).

This module covers three slices those suites deliberately leave open, each
chosen because it models how a *real frontend* exercises the API rather than
hammering one endpoint in isolation:

- **Concurrent user-journey budget**: every existing concurrent test fans out
  *identical* calls. A real session is a *sequence* across endpoints
  (health → version → GET hello → POST hello), and many users run that sequence
  *at the same time*. This simulates N concurrent users each running the full
  sequential journey and bounds (a) every journey's end-to-end wall-time, (b)
  the p95 across journeys, and — critically — (c) that each user's personalized
  POST echoes *that user's own* name, so concurrent sessions never cross-talk.
  A regression that serialized journeys, or that leaked per-request state
  between concurrent sessions, fails here while the identical-fan-out tests pass.

- **Cross-endpoint fairness / no starvation**: the mixed-workload tests bound
  *total* elapsed time for a heterogeneous batch, which a regression can satisfy
  while still starving one route (e.g. the POST validator hogs the loop and GETs
  wait). This issues a single fan-out mixing all endpoint types, groups the
  individual latencies *by endpoint*, and asserts no endpoint's p95 dwarfs the
  others — a fairness ratio, not just an aggregate ceiling.

- **Per-round concurrent throughput floor**: the concurrent rps floor is
  measured *once*; round stability bounds the *ratio* of round totals. Neither
  asserts that a minimum sustained rps holds on *every* round of a repeated
  concurrent workload — a throughput collapse that only appears after warm-up,
  or that drifts down round over round while each round still beats the *ratio*
  guard, slips through both. Pinning an absolute rps floor on each of several
  rounds is the distinct guard.

All bounds are intentionally generous (10–100x typical observed latency on a
shared CI runner) so they fail only on a real regression, never on noise. As in
the sibling suites we do **not** assert concurrent execution is *faster* than
sequential — the handlers are trivial and CPU-bound, so on a single-threaded
event loop concurrent fan-out is legitimately not faster. We bound end-to-end
budgets, fairness, and sustained floors, which hold regardless.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from httpx import AsyncClient, Response

from .conftest import GET_PATHS, name_from_greeting

# --- Concurrent user-journey budget --------------------------------------

# Number of simulated users running the journey concurrently, and the steps of
# a single journey. The journey mirrors a real first-load: health probe, version
# fetch, the default greeting, then a personalized POST.
JOURNEY_USERS = 25

# Wall-time ceiling for a *single* user's full sequential journey, measured
# end-to-end while JOURNEY_USERS journeys run concurrently. Four trivial calls
# in sequence run in low single-digit ms; 1s leaves ~100x headroom for
# contention on a shared runner.
JOURNEY_CEILING_S = 1.0

# p95 across all per-journey completion times — bounds the tail so a single
# straggling session under contention is caught even if the mean passes.
JOURNEY_P95_CEILING_S = 0.75

# --- Cross-endpoint fairness ---------------------------------------------

# Per endpoint, how many calls go into the heterogeneous fairness fan-out.
FAIRNESS_CALLS_PER_ENDPOINT = 30

# Max ratio of the slowest endpoint's p95 to the fastest endpoint's p95 in the
# mixed fan-out. All four handlers are trivial, so a fair loop keeps their p95s
# within a small factor; a starved endpoint (one route hogging the loop) pushes
# the ratio up. 25x is far above fair jitter, far below real starvation.
FAIRNESS_P95_RATIO_CEILING = 25.0

# Floor on the fast-endpoint p95 used as the ratio denominator, so a sub-ms
# fastest endpoint on a quick runner can't manufacture a spurious ratio.
FAIRNESS_P95_FLOOR_S = 0.002

# Absolute ceiling each endpoint's p95 must independently stay under in the
# mixed fan-out — the fairness ratio guards *relative* starvation, this guards
# *absolute* starvation (everything slow together).
FAIRNESS_ABS_P95_CEILING_S = 0.5

# --- Per-round concurrent throughput floor -------------------------------

# Rounds of a repeated concurrent fan-out, the fan-out width per round, and the
# minimum sustained rps each round must independently clear. The floor is set
# well below typical observed concurrent rps so only a real collapse trips it.
THROUGHPUT_ROUNDS = 5
THROUGHPUT_FANOUT = 60
THROUGHPUT_FLOOR_RPS = 40.0


async def _run_user_journey(client: AsyncClient, user_id: int) -> tuple[float, str]:
    """Run one user's full sequential journey; return ``(elapsed_s, echoed_name)``.

    The journey is health → version → GET hello → POST hello, exactly the
    shape a freshly-loaded frontend issues. Timing wraps the whole sequence so
    the result is the user's perceived end-to-end latency. The POST sends a
    per-user name and the echoed name is returned so the caller can verify no
    cross-session corruption occurred while many journeys ran at once.
    """
    name = f"User{user_id:03d}"
    start = time.perf_counter()
    health = await client.get("/health")
    version = await client.get("/api/version")
    hello_get = await client.get("/api/hello")
    hello_post = await client.post("/api/hello", json={"name": name})
    elapsed = time.perf_counter() - start

    assert health.status_code == 200
    assert version.status_code == 200
    assert hello_get.status_code == 200
    assert hello_post.status_code == 200
    return elapsed, name_from_greeting(hello_post.json()["message"])


class TestConcurrentUserJourneys:
    """Many users running the full journey at once must each finish on budget.

    Existing concurrent tests fan out identical calls; this fans out *journeys*.
    A regression that serialized sessions, or that leaked per-request state
    between concurrent POSTs, surfaces here and nowhere else.
    """

    @pytest.mark.asyncio
    async def test_every_concurrent_journey_under_budget(self, async_client: AsyncClient) -> None:
        """All JOURNEY_USERS concurrent journeys complete under the per-journey ceiling."""
        results = await asyncio.gather(
            *[_run_user_journey(async_client, i) for i in range(JOURNEY_USERS)]
        )
        worst = max(elapsed for elapsed, _ in results)
        assert worst < JOURNEY_CEILING_S, (
            f"slowest of {JOURNEY_USERS} concurrent user journeys took {worst:.3f}s, "
            f"exceeds {JOURNEY_CEILING_S}s — sessions may be serializing under load"
        )

    @pytest.mark.asyncio
    async def test_concurrent_journey_p95_bounded(self, async_client: AsyncClient) -> None:
        """p95 of per-journey completion time across concurrent users stays bounded."""
        results = await asyncio.gather(
            *[_run_user_journey(async_client, i) for i in range(JOURNEY_USERS)]
        )
        latencies = sorted(elapsed for elapsed, _ in results)
        p95 = latencies[int(len(latencies) * 0.95)]
        assert p95 < JOURNEY_P95_CEILING_S, (
            f"concurrent journey p95 {p95 * 1000:.1f}ms exceeds "
            f"{JOURNEY_P95_CEILING_S * 1000:.0f}ms — straggling session under contention"
        )

    @pytest.mark.asyncio
    async def test_concurrent_journeys_do_not_cross_talk(self, async_client: AsyncClient) -> None:
        """Each concurrent user's POST echoes that user's own name — no session bleed.

        This is the correctness half of the journey guard: throughput is
        worthless if concurrent sessions corrupt each other's per-request state.
        Every user sends a distinct name; the set of echoed names must exactly
        equal the set sent, with no duplicates or losses.
        """
        results = await asyncio.gather(
            *[_run_user_journey(async_client, i) for i in range(JOURNEY_USERS)]
        )
        echoed = sorted(name for _, name in results)
        expected = sorted(f"User{i:03d}" for i in range(JOURNEY_USERS))
        assert echoed == expected, (
            "concurrent journeys cross-talked: echoed names did not match the "
            "distinct names sent — per-request state bled between sessions"
        )


class TestCrossEndpointFairness:
    """No single endpoint may be starved in a heterogeneous concurrent fan-out.

    The mixed-workload tests bound the *total* time of a mixed batch; a
    regression can meet that while one route hogs the loop and the others wait.
    Grouping per-request latency by endpoint and bounding the p95 *ratio* across
    endpoints catches relative starvation that an aggregate ceiling cannot.
    """

    @pytest.mark.asyncio
    async def test_no_endpoint_starved_in_mixed_fanout(self, async_client: AsyncClient) -> None:
        """In a mixed fan-out, the slowest endpoint's p95 stays within a factor of the fastest."""

        async def timed(path: str) -> tuple[str, float]:
            start = time.perf_counter()
            response = await async_client.get(path)
            assert response.status_code == 200
            return path, time.perf_counter() - start

        # Build one big interleaved fan-out covering all GET endpoints equally.
        coros = [timed(path) for path in GET_PATHS for _ in range(FAIRNESS_CALLS_PER_ENDPOINT)]
        samples = await asyncio.gather(*coros)

        # Group latencies per endpoint and compute each endpoint's p95.
        per_endpoint_p95: dict[str, float] = {}
        for path in GET_PATHS:
            lat = sorted(e for p, e in samples if p == path)
            per_endpoint_p95[path] = lat[int(len(lat) * 0.95)]

        slowest = max(per_endpoint_p95.values())
        fastest = max(min(per_endpoint_p95.values()), FAIRNESS_P95_FLOOR_S)
        ratio = slowest / fastest
        assert ratio < FAIRNESS_P95_RATIO_CEILING, (
            f"endpoint p95 fairness ratio {ratio:.1f}x exceeds "
            f"{FAIRNESS_P95_RATIO_CEILING}x — one endpoint starved under mixed load "
            f"(per-endpoint p95: "
            f"{ {p: f'{v * 1000:.1f}ms' for p, v in per_endpoint_p95.items()} })"
        )

    @pytest.mark.asyncio
    async def test_every_endpoint_p95_under_absolute_ceiling(
        self, async_client: AsyncClient
    ) -> None:
        """Each endpoint's p95 in the mixed fan-out independently clears an absolute ceiling.

        The ratio test catches *relative* starvation; this catches the case
        where every endpoint is slow together (the ratio would look fair while
        all routes stall). Both must hold.
        """

        async def timed(path: str) -> tuple[str, float]:
            start = time.perf_counter()
            response = await async_client.get(path)
            assert response.status_code == 200
            return path, time.perf_counter() - start

        coros = [timed(path) for path in GET_PATHS for _ in range(FAIRNESS_CALLS_PER_ENDPOINT)]
        samples = await asyncio.gather(*coros)

        for path in GET_PATHS:
            lat = sorted(e for p, e in samples if p == path)
            p95 = lat[int(len(lat) * 0.95)]
            assert p95 < FAIRNESS_ABS_P95_CEILING_S, (
                f"{path} p95 {p95 * 1000:.1f}ms in mixed fan-out exceeds "
                f"{FAIRNESS_ABS_P95_CEILING_S * 1000:.0f}ms — absolute starvation"
            )


class TestPerRoundConcurrentThroughputFloor:
    """A minimum concurrent rps must hold on *every* round, not just once.

    The single concurrent rps floor measures one fan-out; round stability bounds
    the *ratio* of round totals. A throughput collapse that only appears after
    warm-up, or a steady downward drift that still satisfies the ratio guard,
    passes both — but fails an absolute rps floor enforced per round.
    """

    @pytest.mark.asyncio
    async def test_each_round_clears_throughput_floor(self, async_client: AsyncClient) -> None:
        """Every one of THROUGHPUT_ROUNDS concurrent rounds sustains the rps floor."""
        round_rps: list[float] = []
        for round_idx in range(THROUGHPUT_ROUNDS):
            start = time.perf_counter()
            responses = await asyncio.gather(
                *[async_client.get("/health") for _ in range(THROUGHPUT_FANOUT)]
            )
            elapsed = time.perf_counter() - start
            assert all(r.status_code == 200 for r in responses)

            rps = THROUGHPUT_FANOUT / elapsed
            round_rps.append(rps)
            assert rps >= THROUGHPUT_FLOOR_RPS, (
                f"round {round_idx}: concurrent throughput {rps:.1f} req/s below floor "
                f"{THROUGHPUT_FLOOR_RPS} — sustained concurrent throughput collapse"
            )

        # Secondary signal: the worst round's rps must not be a tiny fraction of
        # the best round's — a steep round-over-round decline even while every
        # round clears the absolute floor still signals degradation.
        best, worst = max(round_rps), min(round_rps)
        assert worst >= best / 5.0, (
            f"rps fell from {best:.1f} (best round) to {worst:.1f} (worst round) — "
            f">5x decline suggests throughput degradation under repetition"
        )

    @pytest.mark.asyncio
    async def test_mixed_read_write_round_throughput_floor(self, async_client: AsyncClient) -> None:
        """A repeated mixed GET+POST concurrent round sustains the rps floor and stays correct.

        Health-only rounds (above) exercise the read path; this round mixes
        reads and personalized writes so a write-path throughput regression is
        also floored. Correctness of every POST echo is verified so throughput
        cannot be bought by garbling responses.
        """
        for round_idx in range(THROUGHPUT_ROUNDS):
            names = [f"R{round_idx}U{i:03d}" for i in range(THROUGHPUT_FANOUT // 2)]
            start = time.perf_counter()
            coros: list[Any] = []
            for n in names:
                coros.append(async_client.get("/health"))
                coros.append(async_client.post("/api/hello", json={"name": n}))
            responses: list[Response] = await asyncio.gather(*coros)
            elapsed = time.perf_counter() - start

            assert all(r.status_code == 200 for r in responses)
            rps = len(coros) / elapsed
            assert rps >= THROUGHPUT_FLOOR_RPS, (
                f"round {round_idx}: mixed read/write throughput {rps:.1f} req/s below "
                f"floor {THROUGHPUT_FLOOR_RPS} — concurrent mixed throughput collapse"
            )

            # POSTs are the odd indices; each must echo its own name.
            echoed = sorted(name_from_greeting(r.json()["message"]) for r in responses[1::2])
            assert echoed == sorted(names), (
                f"round {round_idx}: POST echoes did not match names sent — "
                f"mixed concurrent round corrupted per-request state"
            )
