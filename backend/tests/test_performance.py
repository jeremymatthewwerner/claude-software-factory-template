"""
Performance regression tests.

These tests guard against silent latency regressions that would otherwise pass
CI unnoticed. The bounds are deliberately generous (10–100x typical observed
latency on CI runners) so they only fail on real regressions, not on noisy
environments.

Focus: e2e-performance. These act as the perf side of an E2E suite — they
exercise the same call sequence the frontend uses on init, and assert that
the contract holds under repeated and concurrent load.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

from .conftest import LOCALHOST_ORIGIN

# Latency bounds — generous to avoid flakiness on shared CI runners.
# Single-call ceilings: 500 ms is ~100x typical observed latency for these
# trivial endpoints (~5 ms). A regression that crosses this is real.
SINGLE_CALL_CEILING_S = 0.5
INIT_SEQUENCE_CEILING_S = 0.5
SEQUENTIAL_100_CEILING_S = 2.0
CONCURRENT_50_CEILING_S = 1.0


class TestSingleCallLatency:
    """Each endpoint must respond well under SINGLE_CALL_CEILING_S."""

    @pytest.mark.parametrize(
        "method,path,json_body",
        [
            ("GET", "/health", None),
            ("GET", "/api/version", None),
            ("GET", "/api/hello", None),
            ("POST", "/api/hello", {"name": "Perf"}),
        ],
        ids=["health", "version", "hello_get", "hello_post"],
    )
    def test_endpoint_responds_under_ceiling(
        self,
        client: TestClient,
        method: str,
        path: str,
        json_body: dict[str, str] | None,
    ) -> None:
        """Endpoint completes in under 500ms (regression guard)."""
        start = time.perf_counter()
        response = client.request(method, path, json=json_body)
        elapsed = time.perf_counter() - start
        assert response.status_code == 200
        assert elapsed < SINGLE_CALL_CEILING_S, f"{method} {path} took {elapsed:.3f}s"


class TestInitSequenceLatency:
    """The frontend's mount-time init sequence must complete quickly end-to-end."""

    def test_full_init_sequence_under_ceiling(self, client: TestClient) -> None:
        """Frontend init: health → version → hello (GET) under 500ms total."""
        start = time.perf_counter()
        assert client.get("/health").status_code == 200
        assert client.get("/api/version").status_code == 200
        assert client.get("/api/hello").status_code == 200
        elapsed = time.perf_counter() - start
        assert elapsed < INIT_SEQUENCE_CEILING_S, (
            f"init sequence took {elapsed:.3f}s, ceiling {INIT_SEQUENCE_CEILING_S}s"
        )

    def test_init_sequence_then_post_under_one_second(self, client: TestClient) -> None:
        """Init sequence followed by a user POST stays under 1s — full first-interaction budget."""
        start = time.perf_counter()
        client.get("/health")
        client.get("/api/version")
        client.get("/api/hello")
        client.post("/api/hello", json={"name": "Alice"})
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0, f"init+POST took {elapsed:.3f}s"


class TestSustainedSequentialLoad:
    """Sustained sequential traffic must not degrade per-call latency."""

    def test_100_sequential_health_calls_under_ceiling(self, client: TestClient) -> None:
        """100 sequential /health calls complete in under 2s total (~20ms/call avg)."""
        start = time.perf_counter()
        for _ in range(100):
            response = client.get("/health")
            assert response.status_code == 200
        elapsed = time.perf_counter() - start
        assert elapsed < SEQUENTIAL_100_CEILING_S, f"100 sequential calls took {elapsed:.3f}s"

    def test_no_per_call_latency_drift_across_50_calls(self, client: TestClient) -> None:
        """Last 10 calls aren't dramatically slower than first 10 (drift guard)."""
        timings: list[float] = []
        for _ in range(50):
            start = time.perf_counter()
            client.get("/health")
            timings.append(time.perf_counter() - start)

        first_10_avg = sum(timings[:10]) / 10
        last_10_avg = sum(timings[-10:]) / 10
        # last 10 should not be more than 10x slower than first 10 (very loose)
        assert last_10_avg < max(first_10_avg * 10, 0.05), (
            f"latency drift: first10 avg {first_10_avg * 1000:.2f}ms, "
            f"last10 avg {last_10_avg * 1000:.2f}ms"
        )

    def test_30_sequential_posts_each_under_100ms(self, client: TestClient) -> None:
        """Each of 30 sequential POSTs completes in <100ms (per-call regression guard)."""
        for i in range(30):
            start = time.perf_counter()
            response = client.post("/api/hello", json={"name": f"User{i}"})
            elapsed = time.perf_counter() - start
            assert response.status_code == 200
            assert elapsed < 0.1, f"POST #{i} took {elapsed:.3f}s"


class TestConcurrentThroughput:
    """Concurrent traffic must complete within bounded time and stay correct."""

    @pytest.mark.asyncio
    async def test_50_concurrent_health_under_ceiling(self, async_client: AsyncClient) -> None:
        """50 concurrent /health requests complete in under 1s total."""
        start = time.perf_counter()
        responses = await asyncio.gather(*[async_client.get("/health") for _ in range(50)])
        elapsed = time.perf_counter() - start
        assert all(r.status_code == 200 for r in responses)
        assert elapsed < CONCURRENT_50_CEILING_S, f"50 concurrent calls took {elapsed:.3f}s"

    @pytest.mark.asyncio
    async def test_30_concurrent_posts_return_distinct_names(
        self, async_client: AsyncClient
    ) -> None:
        """30 concurrent POSTs each receive their own name back — no cross-contamination."""
        names = [f"User{i:03d}" for i in range(30)]
        start = time.perf_counter()
        responses = await asyncio.gather(
            *[async_client.post("/api/hello", json={"name": n}) for n in names]
        )
        elapsed = time.perf_counter() - start
        assert all(r.status_code == 200 for r in responses)
        assert elapsed < 1.0, f"30 concurrent POSTs took {elapsed:.3f}s"

        returned_names = [
            r.json()["message"].split("Hello, ", 1)[1].split("!", 1)[0] for r in responses
        ]
        assert sorted(returned_names) == sorted(names)

    @pytest.mark.asyncio
    async def test_concurrent_not_slower_than_sequential_x2(
        self, async_client: AsyncClient
    ) -> None:
        """30 concurrent calls finish faster than 2x the time of 30 sequential calls.

        This is a very loose bound (concurrent should be MUCH faster than
        sequential), but it catches the case where the event loop has been
        accidentally serialized (e.g. a synchronous lock added to the handler).
        """
        # Sequential baseline
        seq_start = time.perf_counter()
        for _ in range(30):
            await async_client.get("/health")
        seq_elapsed = time.perf_counter() - seq_start

        # Concurrent
        conc_start = time.perf_counter()
        await asyncio.gather(*[async_client.get("/health") for _ in range(30)])
        conc_elapsed = time.perf_counter() - conc_start

        # Concurrent should never take MORE than 2x the sequential time —
        # if it does, something is seriously wrong with async behavior.
        assert conc_elapsed < seq_elapsed * 2 + 0.5, (
            f"concurrent ({conc_elapsed:.3f}s) > 2x sequential "
            f"({seq_elapsed:.3f}s) — possible serialization regression"
        )


class TestLargePayloadPerformance:
    """Large but realistic payloads must not blow up latency."""

    def test_1kb_name_post_under_ceiling(self, client: TestClient) -> None:
        """POST /api/hello with a 1KB name completes under 500ms."""
        big_name = "A" * 1024
        start = time.perf_counter()
        response = client.post("/api/hello", json={"name": big_name})
        elapsed = time.perf_counter() - start
        assert response.status_code == 200
        assert elapsed < SINGLE_CALL_CEILING_S, f"1KB POST took {elapsed:.3f}s"

    def test_10kb_name_post_under_one_second(self, client: TestClient) -> None:
        """POST /api/hello with a 10KB name completes under 1s (no quadratic blowup)."""
        bigger_name = "A" * 10240
        start = time.perf_counter()
        response = client.post("/api/hello", json={"name": bigger_name})
        elapsed = time.perf_counter() - start
        assert response.status_code == 200
        assert elapsed < 1.0, f"10KB POST took {elapsed:.3f}s"


# ---------------------------------------------------------------------------
# Additional e2e-performance regression guards.
#
# These exercise paths a real frontend hits during normal use (CORS preflight,
# parallel init fetches, mixed read+write traffic, doc-schema fetches) and add
# distributional bounds (p95/p99) so tail-latency regressions cannot hide
# behind well-behaved averages. Ceilings are intentionally generous on shared
# CI runners — they fail only on real regressions.
# ---------------------------------------------------------------------------

PREFLIGHT_CEILING_S = 0.1
P95_CEILING_S = 0.05
P99_CEILING_S = 0.1
PARALLEL_INIT_CEILING_S = 0.3
MIXED_WORKLOAD_CEILING_S = 1.0
OPENAPI_CEILING_S = 0.5
BURST_CEILING_S = 0.3


class TestCORSPreflightPerformance:
    """A real frontend pays a CORS preflight (OPTIONS) round-trip before every
    cross-origin POST. If the middleware ever degrades, every user-facing POST
    pays double — so we guard preflight latency, not just preflight correctness.
    """

    def test_single_preflight_under_ceiling(self, client: TestClient) -> None:
        """One CORS preflight for POST /api/hello completes under 100ms."""
        headers = {
            "Origin": LOCALHOST_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        }
        start = time.perf_counter()
        response = client.options("/api/hello", headers=headers)
        elapsed = time.perf_counter() - start
        assert response.status_code == 200
        assert elapsed < PREFLIGHT_CEILING_S, f"CORS preflight took {elapsed:.3f}s"

    def test_preflight_then_post_under_single_call_ceiling(self, client: TestClient) -> None:
        """Preflight + the POST it gates complete together under SINGLE_CALL_CEILING_S.

        Real browsers serialize these: preflight first, then the actual request.
        If their combined latency crosses the single-call ceiling, the user
        perceives a slow POST even when each leg looks fine in isolation.
        """
        headers = {
            "Origin": LOCALHOST_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        }
        start = time.perf_counter()
        pre = client.options("/api/hello", headers=headers)
        post = client.post(
            "/api/hello", json={"name": "Alice"}, headers={"Origin": LOCALHOST_ORIGIN}
        )
        elapsed = time.perf_counter() - start
        assert pre.status_code == 200
        assert post.status_code == 200
        assert elapsed < SINGLE_CALL_CEILING_S, f"preflight+POST took {elapsed:.3f}s"


class TestLatencyDistribution:
    """Tail-latency regression guards.

    The existing first-10/last-10 drift check is loose by design and only
    flags monotonic degradation. p95/p99 caps catch a different class of
    regression: sporadic slow responses from e.g. an accidental sync I/O
    call or a lock-contention issue.
    """

    def _measure_health(self, client: TestClient, n: int) -> list[float]:
        timings: list[float] = []
        for _ in range(n):
            start = time.perf_counter()
            response = client.get("/health")
            timings.append(time.perf_counter() - start)
            assert response.status_code == 200
        return sorted(timings)

    def test_p95_latency_under_ceiling(self, client: TestClient) -> None:
        """95th-percentile /health latency stays under 50ms over 200 calls."""
        sorted_timings = self._measure_health(client, 200)
        p95 = sorted_timings[int(len(sorted_timings) * 0.95)]
        assert p95 < P95_CEILING_S, (
            f"p95 latency {p95 * 1000:.2f}ms exceeds {P95_CEILING_S * 1000:.0f}ms"
        )

    def test_p99_latency_under_ceiling(self, client: TestClient) -> None:
        """99th-percentile /health latency stays under 100ms over 200 calls.

        Catches sporadic slow responses that would degrade real-user latency
        even when the median looks fine.
        """
        sorted_timings = self._measure_health(client, 200)
        p99 = sorted_timings[int(len(sorted_timings) * 0.99)]
        assert p99 < P99_CEILING_S, (
            f"p99 latency {p99 * 1000:.2f}ms exceeds {P99_CEILING_S * 1000:.0f}ms"
        )

    def test_max_latency_within_50x_median(self, client: TestClient) -> None:
        """The slowest call is never more than 50x the median (outlier guard).

        A 50x ratio is extremely loose — this only fires when a single call
        is dramatically slower than the typical one, indicating a real stall
        (lock contention, GC pause, sync I/O on a hot path).
        """
        sorted_timings = self._measure_health(client, 100)
        median = sorted_timings[len(sorted_timings) // 2]
        worst = sorted_timings[-1]
        # 5ms floor handles the case where median is essentially zero on a
        # very fast runner — without it, a 1µs median would make any real
        # value look like an outlier.
        assert worst < max(median * 50, 0.005), (
            f"worst call {worst * 1000:.2f}ms vs median {median * 1000:.2f}ms"
        )


class TestParallelInitSequence:
    """Real browsers issue independent init fetches in parallel, not serially.
    The existing init test is sequential; this one matches actual browser
    behavior and asserts that parallel init is meaningfully faster.
    """

    @pytest.mark.asyncio
    async def test_parallel_init_under_ceiling(self, async_client: AsyncClient) -> None:
        """Health + version + hello fetched in parallel complete under 300ms."""
        start = time.perf_counter()
        responses = await asyncio.gather(
            async_client.get("/health"),
            async_client.get("/api/version"),
            async_client.get("/api/hello"),
        )
        elapsed = time.perf_counter() - start
        assert all(r.status_code == 200 for r in responses)
        assert elapsed < PARALLEL_INIT_CEILING_S, f"parallel init took {elapsed:.3f}s"

    @pytest.mark.asyncio
    async def test_parallel_init_not_slower_than_sequential(
        self, async_client: AsyncClient
    ) -> None:
        """Parallel init never exceeds 2x the time of a sequential init.

        If async handling is accidentally serialized (e.g. a sync DB driver
        added on a hot path, or a global lock), parallel fetches can become
        slower than sequential — this catches that regression.
        """
        seq_start = time.perf_counter()
        await async_client.get("/health")
        await async_client.get("/api/version")
        await async_client.get("/api/hello")
        seq_elapsed = time.perf_counter() - seq_start

        par_start = time.perf_counter()
        await asyncio.gather(
            async_client.get("/health"),
            async_client.get("/api/version"),
            async_client.get("/api/hello"),
        )
        par_elapsed = time.perf_counter() - par_start

        # 100ms slack handles measurement noise on the fast end where both
        # are sub-millisecond.
        assert par_elapsed < seq_elapsed * 2 + 0.1, (
            f"parallel init ({par_elapsed * 1000:.2f}ms) > 2x sequential "
            f"({seq_elapsed * 1000:.2f}ms) — possible serialization regression"
        )


class TestMixedWorkloadConcurrent:
    """Realistic concurrent traffic is mixed reads + writes, not one or the
    other. This guards the case where interleaving the two surfaces a
    coordination bug (shared state, serialized handler) that pure-read or
    pure-write tests miss.
    """

    @pytest.mark.asyncio
    async def test_15_reads_and_15_writes_interleaved_under_ceiling(
        self, async_client: AsyncClient
    ) -> None:
        """15 GETs + 15 POSTs issued together complete under 1s and stay correct."""
        names = [f"Mixed{i:02d}" for i in range(15)]
        coros = []
        for name in names:
            # Interleave: alternate GET and POST so neither path dominates.
            coros.append(async_client.get("/api/hello"))
            coros.append(async_client.post("/api/hello", json={"name": name}))
        start = time.perf_counter()
        responses = await asyncio.gather(*coros)
        elapsed = time.perf_counter() - start

        assert all(r.status_code == 200 for r in responses)
        assert elapsed < MIXED_WORKLOAD_CEILING_S, f"mixed workload took {elapsed:.3f}s"

        # POSTs are at odd indices — each should echo its own name unchanged
        # (no cross-contamination from concurrent GETs sharing event-loop state).
        post_responses = responses[1::2]
        returned = [
            r.json()["message"].split("Hello, ", 1)[1].split("!", 1)[0] for r in post_responses
        ]
        assert sorted(returned) == sorted(names)


class TestOpenAPISchemaPerformance:
    """`/openapi.json` is served by Swagger UI and is occasionally hit by
    health probes. Schema generation can balloon silently as routes grow —
    guard the latency now so a regression surfaces visibly.
    """

    def test_openapi_json_under_ceiling(self, client: TestClient) -> None:
        """GET /openapi.json completes under 500ms."""
        start = time.perf_counter()
        response = client.get("/openapi.json")
        elapsed = time.perf_counter() - start
        assert response.status_code == 200
        assert elapsed < OPENAPI_CEILING_S, f"/openapi.json took {elapsed:.3f}s"

    def test_openapi_json_cached_repeat_call_fast(self, client: TestClient) -> None:
        """Five repeat /openapi.json calls average under 200ms.

        FastAPI caches the schema after first generation. If that cache
        ever stops working, this average would balloon by Nx the first-call
        cost.
        """
        timings: list[float] = []
        for _ in range(5):
            start = time.perf_counter()
            response = client.get("/openapi.json")
            timings.append(time.perf_counter() - start)
            assert response.status_code == 200
        avg = sum(timings) / len(timings)
        assert avg < 0.2, f"avg /openapi.json latency {avg * 1000:.2f}ms"


class TestResponsePayloadSize:
    """Response-body size is a hidden perf lever: accidental bloat (debug
    fields, leaked metadata) degrades real-user latency via bandwidth and
    parsing cost even when handler timing looks fine. Pin a generous ceiling
    so a real bloat (e.g. 10x growth) surfaces as a test failure.
    """

    @pytest.mark.parametrize(
        "method,path,json_body,ceiling_bytes",
        [
            ("GET", "/health", None, 200),
            ("GET", "/api/version", None, 200),
            ("GET", "/api/hello", None, 300),
            ("POST", "/api/hello", {"name": "Alice"}, 300),
        ],
        ids=["health", "version", "hello_get", "hello_post"],
    )
    def test_response_body_under_size_ceiling(
        self,
        client: TestClient,
        method: str,
        path: str,
        json_body: dict[str, str] | None,
        ceiling_bytes: int,
    ) -> None:
        """Response body stays under the pinned ceiling (regression guard against bloat)."""
        response = client.request(method, path, json=json_body)
        assert response.status_code == 200
        size = len(response.content)
        assert size < ceiling_bytes, (
            f"{method} {path} response is {size} bytes (ceiling {ceiling_bytes})"
        )


class TestBurstThenIdlePattern:
    """Real users send bursts of activity separated by idle gaps. Sustained
    load tests miss the case where a per-request resource (connection, task)
    leaks across bursts and degrades the second/third burst.
    """

    @pytest.mark.asyncio
    async def test_three_bursts_each_under_ceiling(self, async_client: AsyncClient) -> None:
        """Three back-to-back bursts of 10 concurrent requests each stay under 300ms.

        Critically, the third burst must not be meaningfully slower than the
        first — that would indicate a per-burst resource leak.
        """
        bursts: list[float] = []
        for _ in range(3):
            start = time.perf_counter()
            responses = await asyncio.gather(*[async_client.get("/health") for _ in range(10)])
            bursts.append(time.perf_counter() - start)
            assert all(r.status_code == 200 for r in responses)
            # Tiny idle gap between bursts — enough for any cleanup to run.
            await asyncio.sleep(0.01)

        for i, elapsed in enumerate(bursts):
            assert elapsed < BURST_CEILING_S, f"burst {i} took {elapsed:.3f}s"

        # The third burst should not be more than 3x the first (loose bound:
        # catches gross degradation, ignores normal noise on a sub-millisecond
        # baseline). 50ms floor for fast-runner noise.
        assert bursts[-1] < max(bursts[0] * 3, 0.05), (
            f"burst regression: first={bursts[0] * 1000:.2f}ms, last={bursts[-1] * 1000:.2f}ms"
        )
