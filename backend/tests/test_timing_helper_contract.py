"""Contract guards for the shared perf timing helpers in ``conftest.py``.

Focus: flaky-hunt (Tuesday). The full backend suite ran five times under
``pytest-randomly`` (distinct seeds) and the seven timing-sensitive suites ran
eight times back-to-back — zero flakes. The suite is stable today. This module
pins the *source* of that stability for the one shared helper pair that no test
currently guards.

``conftest.timed_get`` and ``conftest.timed_post`` are the foundation of every
latency distribution in the perf/e2e suites: each p50/p95/p99 and fairness-ratio
assertion in ``test_performance.py``, ``test_e2e_performance_scaling.py``,
``test_e2e_journey_performance.py``, ``test_e2e_payload_and_throughput.py`` and
``test_e2e_write_path_tail_latency.py`` sorts the per-request ``elapsed`` values
these helpers return. Yet ``test_conftest_helpers.py`` deliberately tests only
``percentile`` — it states the timing helpers are "exercised end-to-end by the
perf suites that call them" and leaves their contract unpinned.

That is a latent-flakiness gap. The helpers time each request with the
*monotonic* ``time.perf_counter()``. A refactor that swapped in a wall clock
(``time.time()``, which is **non-monotonic** — it can step backward on an NTP
adjustment or a manual clock change) would keep the perf suites *passing on most
runs* but occasionally emit a **negative** ``elapsed``. A negative latency sorts
below every real sample, silently shifting the percentile index and corrupting
the very tail measurements the perf suites exist to bound — a textbook
"passes locally, flakes in CI" regression that no existing test would catch.

These guards pin the observable contract a non-monotonic-clock or
garbled-return-tuple regression would break:

* the return *shape* (2-tuple for GET, 3-tuple for POST),
* ``elapsed`` is always a finite, **non-negative** float — across a single call
  and across 100 repeated calls (the window in which a non-monotonic clock would
  produce a negative),
* the returned response is the *actual* response for the path requested (the
  tuple is not transposed), and
* ``timed_post`` threads the ``name`` back through the tuple **unchanged** — even
  for special-character and maximum-length inputs — because that name is the
  correctness key the concurrent write-path tests use to detect cross-talk.
"""

from __future__ import annotations

import math

import pytest
from httpx import AsyncClient, Response

from .conftest import expected_greeting, name_from_greeting, timed_get, timed_post

# Repeated-call count for the non-negativity stress. 100 keeps the module
# sub-second (the handlers are sub-millisecond) while giving a non-monotonic
# clock regression 100 independent chances to emit a backward step.
REPEAT_COUNT = 100

# A name that stresses the round-trip: unicode, whitespace, and punctuation that
# a naive helper implementation might normalise, truncate, or drop. If the name
# survives the tuple unchanged *and* is echoed by the response, the helper is
# faithfully threading its correctness key.
TRICKY_NAME = "Ada 😀 O'Reilly-\tÜmlaut"


class TestTimedGetContract:
    """``timed_get`` returns ``(response, elapsed)`` with a sane, non-negative time."""

    @pytest.mark.asyncio
    async def test_returns_response_and_nonnegative_finite_elapsed(
        self, async_client: AsyncClient
    ) -> None:
        """The 2-tuple is ``(Response, float)`` and ``elapsed`` is finite and ``>= 0``."""
        result = await timed_get(async_client, "/health")
        assert isinstance(result, tuple) and len(result) == 2, (
            f"timed_get must return a 2-tuple, got {result!r}"
        )
        response, elapsed = result
        assert isinstance(response, Response)
        assert isinstance(elapsed, float)
        assert math.isfinite(elapsed), f"elapsed is not finite: {elapsed!r}"
        assert elapsed >= 0.0, (
            f"timed_get elapsed is negative ({elapsed}) — a non-monotonic clock "
            f"regression would corrupt every downstream latency percentile"
        )

    @pytest.mark.asyncio
    async def test_returns_the_actual_response_for_the_requested_path(
        self, async_client: AsyncClient
    ) -> None:
        """The response in the tuple is the one for the path asked for — tuple not transposed."""
        response, _ = await timed_get(async_client, "/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy", (
            "timed_get did not return the /health response — its return tuple is garbled"
        )

    @pytest.mark.asyncio
    async def test_elapsed_never_negative_across_many_calls(
        self, async_client: AsyncClient
    ) -> None:
        """Across 100 GETs, no ``elapsed`` is ever negative.

        This is the guard that fires if a future edit swaps the monotonic
        ``time.perf_counter()`` for a non-monotonic wall clock: the perf suites
        would keep passing on lucky runs, but a single backward clock step in
        100 timings would sort below every real sample and shift the percentile
        index. Pin non-negativity so that regression fails here, deterministically.
        """
        elapseds = [(await timed_get(async_client, "/health"))[1] for _ in range(REPEAT_COUNT)]
        negatives = [e for e in elapseds if e < 0.0 or not math.isfinite(e)]
        assert not negatives, (
            f"{len(negatives)} of {REPEAT_COUNT} timed_get elapsed values were "
            f"negative or non-finite: {negatives[:5]!r}"
        )


class TestTimedPostContract:
    """``timed_post`` returns ``(response, elapsed, name)`` with the name threaded through."""

    @pytest.mark.asyncio
    async def test_returns_triple_with_nonnegative_elapsed_and_echoed_name(
        self, async_client: AsyncClient
    ) -> None:
        """The 3-tuple is ``(Response, float, str)``; elapsed ``>= 0``; name echoed by the body."""
        result = await timed_post(async_client, "ContractName")
        assert isinstance(result, tuple) and len(result) == 3, (
            f"timed_post must return a 3-tuple, got {result!r}"
        )
        response, elapsed, name = result
        assert isinstance(response, Response)
        assert isinstance(elapsed, float)
        assert math.isfinite(elapsed) and elapsed >= 0.0, (
            f"timed_post elapsed is negative or non-finite ({elapsed})"
        )
        # The name is threaded back so callers can verify each response echoed
        # the exact name it was called with. Both the returned name and the
        # response body must reflect the input.
        assert name == "ContractName", f"timed_post did not thread the name back: {name!r}"
        assert response.status_code == 200
        assert response.json()["message"] == expected_greeting("ContractName")
        assert name_from_greeting(response.json()["message"]) == name

    @pytest.mark.asyncio
    async def test_threads_special_character_name_through_unchanged(
        self, async_client: AsyncClient
    ) -> None:
        """A unicode/whitespace/punctuation name survives the tuple and the echo unchanged.

        The concurrent write-path tests rely on ``timed_post`` returning the
        *exact* name so they can detect cross-talk. A helper that normalised or
        truncated the name would make those correctness gates silently vacuous.
        """
        response, _, name = await timed_post(async_client, TRICKY_NAME)
        assert name == TRICKY_NAME, f"timed_post mutated the threaded name: {name!r}"
        assert response.status_code == 200
        assert name_from_greeting(response.json()["message"]) == TRICKY_NAME, (
            "the tricky name did not round-trip through the POST echo"
        )

    @pytest.mark.asyncio
    async def test_elapsed_never_negative_across_many_calls(
        self, async_client: AsyncClient
    ) -> None:
        """Across 100 POSTs, no ``elapsed`` is ever negative (non-monotonic-clock guard)."""
        elapseds = [
            (await timed_post(async_client, f"Repeat{i:03d}"))[1] for i in range(REPEAT_COUNT)
        ]
        negatives = [e for e in elapseds if e < 0.0 or not math.isfinite(e)]
        assert not negatives, (
            f"{len(negatives)} of {REPEAT_COUNT} timed_post elapsed values were "
            f"negative or non-finite: {negatives[:5]!r}"
        )

    @pytest.mark.asyncio
    async def test_each_call_threads_its_own_distinct_name(self, async_client: AsyncClient) -> None:
        """Distinct names each thread back to their own call — no cross-wiring in the helper."""
        names = [f"Distinct{i:03d}" for i in range(20)]
        for sent in names:
            response, _, got = await timed_post(async_client, sent)
            assert got == sent, f"timed_post returned name {got!r} for input {sent!r}"
            assert name_from_greeting(response.json()["message"]) == sent
