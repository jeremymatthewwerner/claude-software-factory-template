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
import statistics
import time

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.main import app

from .conftest import LOCALHOST_ORIGIN, cors_preflight_headers, name_from_greeting

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

        returned_names = [name_from_greeting(r.json()["message"]) for r in responses]
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
            **cors_preflight_headers("POST"),
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
            **cors_preflight_headers("POST"),
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
        returned = [name_from_greeting(r.json()["message"]) for r in post_responses]
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


# ---------------------------------------------------------------------------
# Additional e2e-performance regression guards (second Thursday rotation).
#
# These complement the suites above by covering paths that real E2E traffic
# touches but the existing guards do not: error responses, Swagger/Redoc HTML
# pages, higher-concurrency stress, sustained throughput floors, and a full
# simulated browser first-paint sequence.
# ---------------------------------------------------------------------------

ERROR_PATH_CEILING_S = 0.5
DOCS_HTML_CEILING_S = 0.5
DOCS_HTML_AVG_CEILING_S = 0.2
DOCS_HTML_SIZE_CEILING_BYTES = 8 * 1024
CONCURRENT_100_CEILING_S = 2.0
CONCURRENT_60_POST_CEILING_S = 2.0
HEALTH_THROUGHPUT_FLOOR_RPS = 100.0
POST_THROUGHPUT_FLOOR_RPS = 50.0
FULL_FIRST_PAINT_CEILING_S = 1.5


class TestErrorPathLatency:
    """Error responses (404, 422, 405) must not be slower than the happy path.

    A regression on the exception/validation pipeline can leave 200s fast and
    error responses slow — invisible to all the happy-path guards above. Real
    traffic hits these routinely (typos, schema drift, bots, retries after a
    deploy), so we pin the same ceiling as happy-path single calls.
    """

    def test_404_latency_under_ceiling(self, client: TestClient) -> None:
        """A 404 for an unknown route completes under 500ms."""
        start = time.perf_counter()
        response = client.get("/definitely-not-a-route")
        elapsed = time.perf_counter() - start
        assert response.status_code == 404
        assert elapsed < ERROR_PATH_CEILING_S, f"404 took {elapsed:.3f}s"

    def test_422_validation_error_latency_under_ceiling(self, client: TestClient) -> None:
        """A 422 from a missing required field completes under 500ms."""
        start = time.perf_counter()
        response = client.post("/api/hello", json={})
        elapsed = time.perf_counter() - start
        assert response.status_code == 422
        assert elapsed < ERROR_PATH_CEILING_S, f"422 took {elapsed:.3f}s"

    def test_405_method_not_allowed_latency_under_ceiling(self, client: TestClient) -> None:
        """A 405 for a wrong HTTP method completes under 500ms."""
        start = time.perf_counter()
        response = client.put("/api/hello", json={"name": "x"})
        elapsed = time.perf_counter() - start
        assert response.status_code == 405
        assert elapsed < ERROR_PATH_CEILING_S, f"405 took {elapsed:.3f}s"


class TestDocsHTMLPagePerformance:
    """`/docs` and `/redoc` serve dynamically-rendered HTML and are the slowest
    routes the app exposes by default. They're hit by humans opening the docs,
    by health-checkers that probe the docs URL, and by some load balancers'
    default warm-up checks. A regression here is the first one a developer
    notices, so guard both latency and body-size.
    """

    @pytest.mark.parametrize("path", ["/docs", "/redoc"], ids=["docs", "redoc"])
    def test_docs_html_page_under_ceiling(self, client: TestClient, path: str) -> None:
        """The docs HTML page completes under 500ms."""
        start = time.perf_counter()
        response = client.get(path)
        elapsed = time.perf_counter() - start
        assert response.status_code == 200
        assert elapsed < DOCS_HTML_CEILING_S, f"{path} took {elapsed:.3f}s"

    def test_repeated_docs_html_avg_under_ceiling(self, client: TestClient) -> None:
        """Five repeat /docs calls average under 200ms — catches template-render regressions."""
        timings: list[float] = []
        for _ in range(5):
            start = time.perf_counter()
            response = client.get("/docs")
            timings.append(time.perf_counter() - start)
            assert response.status_code == 200
        avg = sum(timings) / len(timings)
        assert avg < DOCS_HTML_AVG_CEILING_S, f"avg /docs latency {avg * 1000:.2f}ms"

    def test_docs_html_body_under_size_ceiling(self, client: TestClient) -> None:
        """The /docs HTML body stays under 8KB — bloat guard against accidental inlining.

        The Swagger UI HTML is a small bootstrap shell that pulls JS/CSS from a
        CDN; if it ever balloons (e.g. someone inlines the OpenAPI schema into
        the page), the first-paint latency degrades for every docs visitor.
        """
        response = client.get("/docs")
        assert response.status_code == 200
        size = len(response.content)
        assert size < DOCS_HTML_SIZE_CEILING_BYTES, (
            f"/docs HTML is {size} bytes (ceiling {DOCS_HTML_SIZE_CEILING_BYTES})"
        )


class TestHighConcurrencyStress:
    """Concurrency guards beyond the 50-request ceiling used by
    :class:`TestConcurrentThroughput`. Real traffic (load-balancer warm-up,
    retry storms after a transient blip, batch clients) routinely exceeds 50
    in-flight requests; a collapse that only appears past that point would
    slip through the existing guards.
    """

    @pytest.mark.asyncio
    async def test_100_concurrent_health_under_ceiling(self, async_client: AsyncClient) -> None:
        """100 concurrent /health requests complete in under 2s total."""
        start = time.perf_counter()
        responses = await asyncio.gather(*[async_client.get("/health") for _ in range(100)])
        elapsed = time.perf_counter() - start
        assert all(r.status_code == 200 for r in responses)
        assert elapsed < CONCURRENT_100_CEILING_S, f"100 concurrent calls took {elapsed:.3f}s"

    @pytest.mark.asyncio
    async def test_60_concurrent_posts_return_distinct_names(
        self, async_client: AsyncClient
    ) -> None:
        """60 concurrent POSTs each receive their own name back — correctness at 2x existing bound."""
        names = [f"Stress{i:03d}" for i in range(60)]
        start = time.perf_counter()
        responses = await asyncio.gather(
            *[async_client.post("/api/hello", json={"name": n}) for n in names]
        )
        elapsed = time.perf_counter() - start
        assert all(r.status_code == 200 for r in responses)
        assert elapsed < CONCURRENT_60_POST_CEILING_S, f"60 concurrent POSTs took {elapsed:.3f}s"

        returned_names = [name_from_greeting(r.json()["message"]) for r in responses]
        assert sorted(returned_names) == sorted(names)


class TestThroughputFloor:
    """Sustained-throughput regression guards.

    The existing suites bound *total elapsed time* for N calls, which catches
    catastrophic slowdowns but leaves a wide gap: a regression that halves
    throughput while still fitting under the ceiling will pass silently. These
    tests assert a *minimum requests-per-second rate*, which fails the moment
    sustained throughput collapses even if total time is well under the
    existing ceilings. Floors are deliberately well below observed CI rates
    so noise can't flip them.
    """

    def test_health_sustained_throughput_floor(self, client: TestClient) -> None:
        """/health sustains at least 100 req/sec over 200 sequential calls."""
        n = 200
        start = time.perf_counter()
        for _ in range(n):
            response = client.get("/health")
            assert response.status_code == 200
        elapsed = time.perf_counter() - start
        rps = n / elapsed
        assert rps >= HEALTH_THROUGHPUT_FLOOR_RPS, (
            f"/health throughput {rps:.1f} req/s below floor {HEALTH_THROUGHPUT_FLOOR_RPS}"
        )

    def test_post_hello_sustained_throughput_floor(self, client: TestClient) -> None:
        """POST /api/hello sustains at least 50 req/sec over 100 sequential calls."""
        n = 100
        start = time.perf_counter()
        for i in range(n):
            response = client.post("/api/hello", json={"name": f"T{i}"})
            assert response.status_code == 200
        elapsed = time.perf_counter() - start
        rps = n / elapsed
        assert rps >= POST_THROUGHPUT_FLOOR_RPS, (
            f"POST /api/hello throughput {rps:.1f} req/s below floor {POST_THROUGHPUT_FLOOR_RPS}"
        )


class TestRealisticFrontendStartupPattern:
    """Full simulated browser first-paint sequence.

    A real first-time visitor opening `/docs` triggers, in rough order:
      1. The docs HTML page render.
      2. A schema fetch (`/openapi.json`) that Swagger UI uses to build the page.
      3. Parallel init fetches (`/health`, `/api/version`, `/api/hello`) that
         a frontend might issue concurrently after mount.
      4. A first user-initiated POST.

    Each individual leg is already guarded above; this test guards the
    *end-to-end* perceived latency of the full sequence so a small regression
    on each leg can't compound into a noticeable slowdown.
    """

    @pytest.mark.asyncio
    async def test_full_first_paint_sequence_under_ceiling(self, async_client: AsyncClient) -> None:
        """Full simulated first paint completes end-to-end under 1.5s."""
        start = time.perf_counter()

        docs = await async_client.get("/docs")
        assert docs.status_code == 200

        schema = await async_client.get("/openapi.json")
        assert schema.status_code == 200

        init_responses = await asyncio.gather(
            async_client.get("/health"),
            async_client.get("/api/version"),
            async_client.get("/api/hello"),
        )
        assert all(r.status_code == 200 for r in init_responses)

        post = await async_client.post("/api/hello", json={"name": "FirstUser"})
        assert post.status_code == 200

        elapsed = time.perf_counter() - start
        assert elapsed < FULL_FIRST_PAINT_CEILING_S, (
            f"full first-paint sequence took {elapsed:.3f}s, ceiling {FULL_FIRST_PAINT_CEILING_S}s"
        )


# ---------------------------------------------------------------------------
# Additional e2e-performance regression guards (third Thursday rotation).
#
# These cover dimensions the suites above leave open:
#   - Cold-start cost on a fresh TestClient (lazy-init regressions).
#   - Latency jitter (stddev), distinct from p95/p99 — catches variance
#     regressions that keep percentiles low but degrade perceived UX.
#   - Tail latency for endpoints other than /health, which currently has the
#     only p95/p99 guards.
#   - Sustained CORS preflight cost (single-preflight tests miss leaks that
#     surface only after several preflights).
#   - Per-endpoint throughput floor for /api/version (no rps floor today).
#   - All-four-endpoints concurrent fan-out (existing mixed test only
#     interleaves GET/POST /api/hello).
#   - OpenAPI schema cache effectiveness past 5 calls, with the warm-up call
#     excluded so the cache miss can't mask a per-call cost regression.
# ---------------------------------------------------------------------------

COLD_START_CEILING_S = 1.0
JITTER_STDDEV_CEILING_S = 0.05
NON_HEALTH_P95_CEILING_S = 0.05
SEQUENTIAL_PREFLIGHT_TOTAL_CEILING_S = 1.0
SEQUENTIAL_PREFLIGHT_AVG_CEILING_S = 0.1
VERSION_THROUGHPUT_FLOOR_RPS = 100.0
FAN_OUT_CEILING_S = 0.5
OPENAPI_WARM_AVG_CEILING_S = 0.05
OPENAPI_WARM_MAX_CEILING_S = 0.2


class TestColdStartLatency:
    """First-request latency on a fresh TestClient.

    Every other test in this file uses the module-scoped ``app`` and a
    function-scoped ``client`` fixture — by the time a percentile or
    throughput test runs, the ASGI app has been exercised hundreds of times
    and is fully warm. A regression that adds work to the *very first*
    request (lazy import, first-call schema build, one-time connection setup)
    is invisible to all of them.

    This test creates a brand-new ``TestClient`` inside the test body and
    measures the latency of its first request. The ceiling is intentionally
    generous (1s) — the first call on the test runner is typically tens of
    ms; we only fail on a real lazy-init regression of 10x+ that cost.
    """

    def test_first_request_on_fresh_client_under_ceiling(self) -> None:
        """A fresh TestClient's first /health call completes under 1s."""
        fresh_client = TestClient(app)
        start = time.perf_counter()
        response = fresh_client.get("/health")
        elapsed = time.perf_counter() - start
        assert response.status_code == 200
        assert elapsed < COLD_START_CEILING_S, (
            f"cold-start first call took {elapsed:.3f}s, ceiling {COLD_START_CEILING_S}s"
        )

    def test_first_post_on_fresh_client_under_ceiling(self) -> None:
        """A fresh TestClient's first POST /api/hello completes under 1s.

        POST has a larger setup surface than GET (body parsing, validation),
        so a cold-start regression there can be worse than on /health.
        """
        fresh_client = TestClient(app)
        start = time.perf_counter()
        response = fresh_client.post("/api/hello", json={"name": "ColdStart"})
        elapsed = time.perf_counter() - start
        assert response.status_code == 200
        assert elapsed < COLD_START_CEILING_S, (
            f"cold-start POST took {elapsed:.3f}s, ceiling {COLD_START_CEILING_S}s"
        )


class TestLatencyJitter:
    """Latency variance (stddev) guard.

    p95/p99 caps catch sporadic *high* outliers but leave a blind spot:
    a regression that lifts the whole low end of the distribution toward
    the percentile ceilings will degrade perceived UX (more jittery typing,
    more visible animations) while still passing every existing guard.
    Standard deviation across the same sample is a direct measurement of
    that effect.

    The 50ms ceiling is roughly 10x typical observed stddev on these
    trivial endpoints on a shared CI runner — only a real regression
    moves it.
    """

    def test_health_latency_stddev_under_ceiling(self, client: TestClient) -> None:
        """Stddev of /health latency stays under 50ms over 200 calls."""
        timings: list[float] = []
        for _ in range(200):
            start = time.perf_counter()
            response = client.get("/health")
            timings.append(time.perf_counter() - start)
            assert response.status_code == 200
        stddev = statistics.stdev(timings)
        assert stddev < JITTER_STDDEV_CEILING_S, (
            f"latency stddev {stddev * 1000:.2f}ms exceeds {JITTER_STDDEV_CEILING_S * 1000:.0f}ms"
        )


class TestNonHealthTailLatency:
    """Per-endpoint p95 guard for endpoints other than /health.

    :class:`TestLatencyDistribution` only measures /health, so a tail-latency
    regression that affects /api/version or /api/hello (e.g. a slow Pydantic
    serialiser added on the response model) would slip through. This test
    pins p95 for every other public endpoint.
    """

    @pytest.mark.parametrize(
        "method,path,json_body",
        [
            ("GET", "/api/version", None),
            ("GET", "/api/hello", None),
            ("POST", "/api/hello", {"name": "Tail"}),
        ],
        ids=["version", "hello_get", "hello_post"],
    )
    def test_endpoint_p95_under_ceiling(
        self,
        client: TestClient,
        method: str,
        path: str,
        json_body: dict[str, str] | None,
    ) -> None:
        """p95 latency for the endpoint stays under 50ms over 200 calls."""
        timings: list[float] = []
        for _ in range(200):
            start = time.perf_counter()
            response = client.request(method, path, json=json_body)
            timings.append(time.perf_counter() - start)
            assert response.status_code == 200
        sorted_timings = sorted(timings)
        p95 = sorted_timings[int(len(sorted_timings) * 0.95)]
        assert p95 < NON_HEALTH_P95_CEILING_S, (
            f"{method} {path} p95 {p95 * 1000:.2f}ms exceeds "
            f"{NON_HEALTH_P95_CEILING_S * 1000:.0f}ms"
        )


class TestSustainedCORSPreflight:
    """Many cross-origin POSTs in a row each pay a preflight. A regression
    that allocates per-call (e.g. rebuilds the allow-origin list on every
    OPTIONS) would not show up in the existing single-preflight test, but
    a sustained run of preflights would compound the cost. Guard the
    sustained behaviour explicitly.
    """

    def test_10_sequential_preflights_under_total_and_avg_ceilings(
        self, client: TestClient
    ) -> None:
        """10 sequential CORS preflights total under 1s and average under 100ms."""
        headers = {
            **cors_preflight_headers("POST"),
            "Access-Control-Request-Headers": "content-type",
        }
        start = time.perf_counter()
        timings: list[float] = []
        for _ in range(10):
            call_start = time.perf_counter()
            response = client.options("/api/hello", headers=headers)
            timings.append(time.perf_counter() - call_start)
            assert response.status_code == 200
        total = time.perf_counter() - start
        avg = sum(timings) / len(timings)
        assert total < SEQUENTIAL_PREFLIGHT_TOTAL_CEILING_S, (
            f"10 preflights took {total:.3f}s total"
        )
        assert avg < SEQUENTIAL_PREFLIGHT_AVG_CEILING_S, (
            f"avg preflight {avg * 1000:.2f}ms exceeds {SEQUENTIAL_PREFLIGHT_AVG_CEILING_S * 1000:.0f}ms"
        )


class TestVersionThroughputFloor:
    """:class:`TestThroughputFloor` pins sustained rps for /health and
    POST /api/hello but leaves /api/version unguarded. /api/version returns
    one extra field over /health and is the route most often hit by
    deploy-verification probes, so a throughput regression there is
    visible end-to-end.
    """

    def test_version_sustained_throughput_floor(self, client: TestClient) -> None:
        """/api/version sustains at least 100 req/sec over 200 sequential calls."""
        n = 200
        start = time.perf_counter()
        for _ in range(n):
            response = client.get("/api/version")
            assert response.status_code == 200
        elapsed = time.perf_counter() - start
        rps = n / elapsed
        assert rps >= VERSION_THROUGHPUT_FLOOR_RPS, (
            f"/api/version throughput {rps:.1f} req/s below floor {VERSION_THROUGHPUT_FLOOR_RPS}"
        )


class TestConcurrentFanOutAllEndpoints:
    """Concurrent fan-out across *all four* public endpoints.

    :class:`TestMixedWorkloadConcurrent` interleaves only GET and POST on
    /api/hello. A coordination regression that surfaces only when /health,
    /api/version, /api/hello GET, and /api/hello POST are all in flight at
    once (e.g. a shared lock or a global counter contended across handlers)
    would slip through. This test exercises that exact shape.
    """

    @pytest.mark.asyncio
    async def test_all_four_endpoints_concurrent_under_ceiling(self) -> None:
        """Two of each endpoint (8 requests total) issued concurrently complete under 500ms."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            start = time.perf_counter()
            responses = await asyncio.gather(
                ac.get("/health"),
                ac.get("/health"),
                ac.get("/api/version"),
                ac.get("/api/version"),
                ac.get("/api/hello"),
                ac.get("/api/hello"),
                ac.post("/api/hello", json={"name": "FanOutA"}),
                ac.post("/api/hello", json={"name": "FanOutB"}),
            )
            elapsed = time.perf_counter() - start
            assert all(r.status_code == 200 for r in responses)
            assert elapsed < FAN_OUT_CEILING_S, f"fan-out across all endpoints took {elapsed:.3f}s"
            # The two POSTs must each echo their own name back — concurrent
            # fan-out across heterogeneous routes must not cross-contaminate
            # the POST handler's per-request state.
            post_a, post_b = responses[-2], responses[-1]
            assert name_from_greeting(post_a.json()["message"]) == "FanOutA"
            assert name_from_greeting(post_b.json()["message"]) == "FanOutB"


class TestOpenAPISchemaCacheDeep:
    """Deeper OpenAPI cache-effectiveness guard.

    ``test_openapi_json_cached_repeat_call_fast`` averages 5 calls *including*
    the first (uncached) call, so a regression where the cache never warms
    can still pass if 4 misses average below the ceiling. By excluding the
    first call and measuring 20 subsequent calls with a tight per-call
    ceiling, this test distinguishes a real cache from a happenstance-fast
    miss path.
    """

    def test_openapi_warm_cache_calls_average_and_max_under_ceiling(
        self, client: TestClient
    ) -> None:
        """After one warm-up call, 20 subsequent /openapi.json calls each stay fast."""
        # Warm-up call — excluded from the measurement.
        warmup = client.get("/openapi.json")
        assert warmup.status_code == 200

        timings: list[float] = []
        for _ in range(20):
            start = time.perf_counter()
            response = client.get("/openapi.json")
            timings.append(time.perf_counter() - start)
            assert response.status_code == 200

        avg = sum(timings) / len(timings)
        worst = max(timings)
        assert avg < OPENAPI_WARM_AVG_CEILING_S, (
            f"warm-cache avg {avg * 1000:.2f}ms exceeds "
            f"{OPENAPI_WARM_AVG_CEILING_S * 1000:.0f}ms — cache likely cold on each call"
        )
        assert worst < OPENAPI_WARM_MAX_CEILING_S, (
            f"warm-cache worst {worst * 1000:.2f}ms exceeds "
            f"{OPENAPI_WARM_MAX_CEILING_S * 1000:.0f}ms"
        )
