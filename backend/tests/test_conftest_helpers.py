"""Unit tests for the shared test helpers in ``conftest.py``.

The perf/e2e suites lean on ``conftest.percentile`` to turn a sorted latency
list into a p50/p95/p99 value. That helper encodes a specific convention —
nearest-rank indexing (``int(len * pct)``) clamped to the final element — that
several latency assertions now depend on. This module pins that contract so a
future "cleanup" of the helper cannot silently shift every percentile-based
guard (e.g. by switching to interpolation or forgetting the clamp) without a
test going red.

The sanitizer suites lean on ``conftest.strict_json_loads`` / ``first_error`` to
re-parse a 422 body *strictly* — proving no bare ``NaN``/``Infinity`` token
leaked — and to pull out ``detail[0]``. Five files each carried a private copy of
that ``parse_constant`` hook before it was consolidated, so its
reject-on-non-standard-token contract is pinned here too: a regression that made
the parser lenient again would let a leaked token pass silently through every
caller.

Only the extracted helpers carrying real logic are tested here; the trivial
one-line wrappers (``timed_get``/``timed_post``) are exercised end-to-end by
the perf suites that call them.
"""

from __future__ import annotations

import pytest

from .conftest import first_error, percentile, strict_json_loads


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


class TestStrictJsonLoads:
    """``strict_json_loads`` parses valid JSON but rejects non-standard tokens."""

    def test_parses_ordinary_json_object(self) -> None:
        """A standard JSON object round-trips to the equivalent Python dict."""
        assert strict_json_loads('{"a": 1, "b": [2, 3]}') == {"a": 1, "b": [2, 3]}

    @pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
    def test_bare_non_finite_token_raises_assertionerror(self, token: str) -> None:
        """A bare ``NaN``/``Infinity``/``-Infinity`` scalar fails loudly, not silently.

        ``json.loads`` would decode these to ``float('nan')`` etc. by default — the
        very leniency the sanitizer suites re-parse strictly to catch. The message
        names the offending token so a leak is self-describing.
        """
        with pytest.raises(AssertionError, match="non-standard JSON token"):
            strict_json_loads(token)

    def test_non_finite_token_nested_in_container_raises(self) -> None:
        """A non-standard token buried inside a container is still rejected."""
        with pytest.raises(AssertionError, match="non-standard JSON token"):
            strict_json_loads('{"detail": [{"input": NaN}]}')

    def test_quoted_nan_string_is_accepted(self) -> None:
        """The *sanitized* form ``"nan"`` is an ordinary string and parses cleanly.

        This is the exact shape a correctly-sanitized 422 body carries, so the
        helper must accept it — only *bare* (unquoted) tokens are the failure.
        """
        assert strict_json_loads('{"input": "nan"}') == {"input": "nan"}


class TestFirstError:
    """``first_error`` returns ``detail[0]`` from a strictly-parsed 422 body."""

    def test_returns_first_detail_entry(self) -> None:
        """The first element of the ``detail`` list is returned verbatim."""
        body = '{"detail": [{"loc": ["body"], "input": "nan"}, {"loc": ["body", "x"]}]}'
        assert first_error(body) == {"loc": ["body"], "input": "nan"}

    def test_rejects_body_with_leaked_non_finite_token(self) -> None:
        """Extraction fails if a bare non-finite token survived into the body.

        This is why the sanitizer suites route ``detail[0]`` access through this
        helper rather than a plain ``json.loads`` — the strict parse turns a leaked
        token into a failure *at the point of extraction*.
        """
        with pytest.raises(AssertionError, match="non-standard JSON token"):
            first_error('{"detail": [{"input": Infinity}]}')

    def test_non_object_body_raises(self) -> None:
        """A body that is not a JSON object fails with a descriptive message."""
        with pytest.raises(AssertionError, match="not a JSON object"):
            first_error("[1, 2, 3]")

    def test_empty_detail_list_raises(self) -> None:
        """A body whose ``detail`` list is empty has no first error to return."""
        with pytest.raises(AssertionError, match="no detail list"):
            first_error('{"detail": []}')

    def test_non_object_first_detail_entry_raises(self) -> None:
        """``detail[0]`` that is not a JSON object fails, not silently returned."""
        with pytest.raises(AssertionError, match="detail\\[0\\] is not an object"):
            first_error('{"detail": ["oops"]}')
