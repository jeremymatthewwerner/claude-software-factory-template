"""Unit tests for the shared test helpers in ``conftest.py``.

The perf/e2e suites lean on ``conftest.percentile`` to turn a sorted latency
list into a p50/p95/p99 value. That helper encodes a specific convention —
nearest-rank indexing (``int(len * pct)``) clamped to the final element — that
several latency assertions now depend on. This module pins that contract so a
future "cleanup" of the helper cannot silently shift every percentile-based
guard (e.g. by switching to interpolation or forgetting the clamp) without a
test going red.

Only the extracted helper carrying real logic is tested here; the trivial
one-line wrappers (``timed_get``/``timed_post``) are exercised end-to-end by
the perf suites that call them.
"""

from __future__ import annotations

import pytest

from .conftest import percentile


class TestPercentile:
    """``percentile`` uses clamped nearest-rank indexing on a sorted list."""

    def test_matches_inline_nearest_rank_index(self) -> None:
        """Result equals the ``sorted[int(len * pct)]`` idiom it replaced.

        This is the exact expression the perf suites inlined before the helper
        was extracted, so reproducing it guarantees the refactor changed no
        percentile value anywhere.
        """
        values = [float(i) for i in range(100)]  # 0.0 .. 99.0, already sorted
        for pct in (0.0, 0.5, 0.90, 0.95, 0.99):
            assert percentile(values, pct) == values[int(len(values) * pct)]

    def test_p50_is_the_upper_median_of_even_length(self) -> None:
        """p50 lands on index ``len // 2`` — matching the old ``median`` idiom."""
        values = [1.0, 2.0, 3.0, 4.0]
        assert percentile(values, 0.5) == values[len(values) // 2] == 3.0

    def test_pct_one_is_clamped_to_last_element(self) -> None:
        """``pct == 1.0`` returns the max instead of indexing out of range.

        Raw ``int(len * 1.0)`` would be ``len`` — an ``IndexError``. The clamp
        is what lets callers ask for the 100th percentile safely.
        """
        values = [10.0, 20.0, 30.0]
        assert percentile(values, 1.0) == 30.0

    def test_pct_above_one_still_clamps_to_last_element(self) -> None:
        """Even an over-unity ``pct`` cannot walk off the end of the list."""
        values = [10.0, 20.0, 30.0]
        assert percentile(values, 1.5) == 30.0

    def test_pct_zero_returns_first_element(self) -> None:
        """The 0th percentile is the smallest value (index 0)."""
        values = [5.0, 6.0, 7.0]
        assert percentile(values, 0.0) == 5.0

    def test_single_element_list_returns_that_element_for_any_pct(self) -> None:
        """A one-sample list has the same value at every percentile."""
        for pct in (0.0, 0.5, 0.95, 1.0):
            assert percentile([42.0], pct) == 42.0

    def test_empty_list_raises_valueerror(self) -> None:
        """An empty distribution has no percentile and must raise, not IndexError."""
        with pytest.raises(ValueError, match="non-empty"):
            percentile([], 0.95)

    @pytest.mark.parametrize("size", [1, 2, 10, 40, 100, 200])
    def test_index_never_out_of_range_across_sizes(self, size: int) -> None:
        """For any list size, p95/p99/p100 stay within bounds and are monotonic.

        The fan-out widths used across the perf suites vary (40, 50, 100, 200);
        this guards the clamp against every one of them at once.
        """
        values = [float(i) for i in range(size)]
        p95 = percentile(values, 0.95)
        p99 = percentile(values, 0.99)
        p100 = percentile(values, 1.0)
        assert values[0] <= p95 <= p99 <= p100 == values[-1]
