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

# Latency bounds — generous to avoid flakiness on shared CI runners.
# Single-call ceilings: 500 ms is ~100x typical observed latency for these
# trivial endpoints (~5 ms). A regression that crosses this is real.
SINGLE_CALL_CEILING_S = 0.5
INIT_SEQUENCE_CEILING_S = 0.5
SEQUENTIAL_100_CEILING_S = 2.0
CONCURRENT_50_CEILING_S = 1.0


class TestSingleCallLatency:
    """Each endpoint must respond well under SINGLE_CALL_CEILING_S."""

    def test_health_responds_under_ceiling(self, client: TestClient) -> None:
        """GET /health completes in under 500ms (regression guard)."""
        start = time.perf_counter()
        response = client.get("/health")
        elapsed = time.perf_counter() - start
        assert response.status_code == 200
        assert elapsed < SINGLE_CALL_CEILING_S, f"/health took {elapsed:.3f}s"

    def test_version_responds_under_ceiling(self, client: TestClient) -> None:
        """GET /api/version completes in under 500ms (regression guard)."""
        start = time.perf_counter()
        response = client.get("/api/version")
        elapsed = time.perf_counter() - start
        assert response.status_code == 200
        assert elapsed < SINGLE_CALL_CEILING_S, f"/api/version took {elapsed:.3f}s"

    def test_hello_get_responds_under_ceiling(self, client: TestClient) -> None:
        """GET /api/hello completes in under 500ms (regression guard)."""
        start = time.perf_counter()
        response = client.get("/api/hello")
        elapsed = time.perf_counter() - start
        assert response.status_code == 200
        assert elapsed < SINGLE_CALL_CEILING_S, f"GET /api/hello took {elapsed:.3f}s"

    def test_hello_post_responds_under_ceiling(self, client: TestClient) -> None:
        """POST /api/hello completes in under 500ms (regression guard)."""
        start = time.perf_counter()
        response = client.post("/api/hello", json={"name": "Perf"})
        elapsed = time.perf_counter() - start
        assert response.status_code == 200
        assert elapsed < SINGLE_CALL_CEILING_S, f"POST /api/hello took {elapsed:.3f}s"


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
