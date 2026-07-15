# Test Plan

Documents test coverage, test descriptions, and quality improvements.

---

## 2026-07-14 — QA Agent: flaky-hunt session (issue #404)

Line/branch coverage is already **100%** on `app/` (76 stmts, 12 branches), so this
Tuesday **flaky-hunt** run chases order-dependent flakiness risk rather than
coverage. The suite runs under `pytest-randomly`, so file/test order changes every
run. Empirically the suite is stable — full suite 5× and `test_performance.py` 20×
produced **0 failures** across randomized orderings — so the value here is closing a
*latent* flakiness hole, not chasing an active flake.

### Gap found — shared mutable conftest constants had no immutability guard

`conftest.py` exports `JSON_HEADERS` (a dict) and `GET_PATHS` (a list) that dozens of
suites import directly. The conftest comment instructs callers to "Treat it as
immutable — spread it (`{**JSON_HEADERS, ...}`) rather than mutating it in place," but
**nothing enforced that**. Existing tests only guard that the *sanitizer helpers*
don't mutate their *inputs*. Under `pytest-randomly`, a test that mutated one of these
shared containers in place would corrupt only the tests that ran *after* it — a
failure that appears or vanishes with the random seed, i.e. an order-dependent flake.

### Backend — `backend/tests/conftest.py` (new session-scoped guard)

Added `_guard_shared_constant_immutability`, a `scope="session"`, `autouse=True`
fixture that deep-copies `JSON_HEADERS`/`GET_PATHS` before the first test and
re-compares them (reading the *current* module globals, so both in-place mutation and
rebinding are caught) after the last. A real leak becomes one deterministic,
seed-independent failure naming the culprit constant, instead of a downstream flake.
Verified by temporarily injecting a mutating test: the session failed at teardown with
the expected message.

### Backend — `backend/tests/test_shared_constant_immutability.py` (new — 3 classes, 13 tests)

| Test class | What it validates |
|------------|-------------------|
| `TestSharedConstantCanonicalValues` (6 tests) | Pins the exact value/type of `JSON_HEADERS`, `GET_PATHS` (order + no duplicates), `GREETING_TEMPLATE`, and the three CORS origin constants. |
| `TestSpreadIdiomLeavesSharedConstantIntact` (4 tests) | Proves the prescribed `{**JSON_HEADERS, ...}` spread idiom yields a distinct object, preserves the original contents, doesn't leak copy-writes back, and that slice-copying `GET_PATHS` never mutates it. |
| `TestGuardDetectionLogic` (3 tests) | Exercises the deep-copy-then-compare mechanism the session guard uses — snapshot diverges after in-place dict/list mutation, stays equal when the source is untouched (guard does not misfire). |

### Verification

- New tests pass **3×** with no flakiness; new file runs in ~0.03s.
- Full backend suite: **1049 pass** (was 1036; +13 new tests), verified 3× under
  `pytest-randomly` with no order-dependent failures.
- `ruff format` + `ruff check` clean; `mypy` clean; 100% line + branch coverage
  maintained on `app/`.

---

## 2026-07-13 — QA Agent: coverage-sprint session (issue #400)

Line/branch coverage is already **100%** on both stacks (backend `app/`: 1033
tests; frontend `src/`: 96 tests) — the reported "12" starting figure was stale.
This Monday **coverage-sprint** run therefore chases an unpinned *behaviour* in an
already-100% area rather than padding lines: the combined request-body sanitizer
composition `_replace_lone_surrogates(_replace_non_finite(...))`.

### Gap found — a nested **list** under a field was never driven over HTTP

`test_combined_sanitizer_composition.py` drives the handler with bodies carrying
**both** defect kinds (a non-finite float *and* a lone UTF-16 surrogate), but the
sanitizers' `list`-recursion branch is exercised at the HTTP boundary only via a
**top-level array root** (`[NaN, "\uD83D"]`). The one nested case
(`test_nested_dict_under_name_with_both_defects`) recurses through a **dict**, never
a nested list. So the shape `{"name": [<non-finite>, "<surrogate>"]}` — where
Pydantic echoes the offending **array** as the `body.name` error's `input`, one
level deep — was unpinned. A regression that walked lists only at the document root
(or special-cased the root container's type) would 500 on this body while the entire
existing suite stayed green.

### Tests added — `tests/test_combined_sanitizer_composition.py` (+1 test, 3 cases)

Added to `TestBothDefectsInOneRequestBodyYieldCleanResponse`:

| Test | What it validates |
|------|-------------------|
| `test_nested_list_under_name_with_both_defects` (3 params: NaN/Infinity/-Infinity) | Body `{"name": [<non-finite>, "\uD83D"]}` yields a clean 422 whose `body.name` error echoes the sanitized list `["<repr>", "\ud83d"]` — proving both sanitizers recurse through a **list nested beneath a field**, distinct from the root-array and nested-dict cases. |

### Verification

- New test passes 3× with no flakiness (3 parametrized cases each run).
- Full backend suite: **1036 pass** (was 1033; +3 parametrized cases).
- `ruff format` + `ruff check` clean; 100% line + branch coverage maintained on `app/`.
- **No production code changed** — this run adds a regression pin only.

---

## 2026-07-11 — QA Agent: edge-cases session (issue #394)

Line/branch coverage of `app/main.py` is already **100%** (1006 tests), so this
Saturday **edge-cases** run chases *behaviour*, not lines. It closes a gap in the
`POST /api/hello` name-echo contract.

### Gap found — format/template metacharacters in `name` were never pinned

`TestSecurityInputs` (test_main.py) pins that SQL-injection, emoji, RTL and
zero-width names echo verbatim; `TestNameEchoBoundaries` (test_edge_cases.py) pins
length/whitespace/control-char boundaries. Neither pins the adversarial class most
coupled to *how the greeting is built* — **format-string / template metacharacters**
in the name: Python `str.format` fields (`{}`, `{0}`, `{name}`, `{0.__class__}`),
`printf`/`%` conversions (`%s`, `%d`, `%(name)s`), shell/JS template literals
(`${name}`, `$name`), and unbalanced braces (`{`, `}`).

The handler builds the greeting with an f-string (value substitution), so all of
these must echo back **verbatim** with a 200. The pins guard against a refactor to
`GREETING_TEMPLATE.format(request.name)` or `template % name` (interpolating the
*user value* as a format template), under which `{0}`/`%s` would raise → **500**, a
lone `{`/`}` would raise → **500**, and `{0.__class__}` could **leak internals** —
the classic Python format-string information-disclosure vector.

### Tests added — `tests/test_name_format_string_injection.py` (19 tests)

#### `TestFormatStringMetacharactersEchoVerbatim` (1 logical test, 17 cases)

| Test | What it validates |
|------|-------------------|
| `test_metacharacter_name_round_trips_exactly` (17 params) | Each format/template metacharacter name — `str.format` fields, `printf` conversions, shell/JS template literals, and unbalanced braces — yields 200 and the **exact** `expected_greeting(name)`, proving the name is an opaque value, not a format template. |

#### `TestFStringDoesNotReInterpolateName` (2 tests)

| Test | What it validates |
|------|-------------------|
| `test_literal_name_field_token_is_not_expanded` | A name of exactly `{name}` (the greeting template's own replacement field) echoes verbatim — a double-`format` regression would consume or re-substitute it. |
| `test_attribute_traversal_field_does_not_leak_internals` | `{0.__class__}` echoes verbatim and the response contains no resolved class repr — pins that no attribute traversal / info-leak occurs. |

### Verification

- New tests pass 3× with no flakiness; full backend suite: **1025 pass** (was 1006; +19 new tests).
- `ruff format` + `ruff check` + `mypy` clean; 100% line + branch coverage maintained on `app/`.
- **No production code changed** — this run adds regression pins only.

## 2026-07-10 — QA Agent: test-refactoring session (issue #391)

Line/branch coverage of `app/main.py` is already **100%** (995 tests), so this
Friday **test-refactoring** run targets **duplication** rather than coverage:
five sanitizer suites each carried a near-identical private copy of a "strict
JSON parse that rejects the non-standard `NaN`/`Infinity`/`-Infinity` tokens"
`parse_constant` hook.

### Duplication found — the strict-JSON re-parse hook, copied five times

The sanitizer suites re-parse a 422 response body *strictly* to prove no bare
non-finite token leaked onto the wire — `json.loads(..., parse_constant=<raise>)`,
equivalent to a browser's `JSON.parse`. Each suite had re-declared that hook
under its own name, and two suites also re-declared a `_strict_json_loads`
wrapper and a `_first_error*` accessor:

| File | Private copy removed |
|------|----------------------|
| `test_nonfinite_toplevel_body.py` | `_strict_json_loads` + `_first_error` |
| `test_regression_nonfinite_sanitization.py` | `_strict_json_loads` (+ `_first_error_input` now a one-liner) |
| `test_combined_sanitizer_composition.py` | `_reject_nonstandard_token` |
| `test_e2e_sanitized_error_path_performance.py` | `_reject_nonstandard_constant` |
| `test_numeric_overflow_nonfinite.py` | `_reject_constant` |

### Consolidation — two shared helpers in `conftest.py`

Added `strict_json_loads(text)` (the single strict parser, rejecting non-standard
tokens) and `first_error(response_text)` (strict-parse a 422 body and return
`detail[0]`, with descriptive assertions). All nine private copies now import
these instead, and the three files whose only remaining `json.` use was the
deleted hook dropped their now-unused `import json`.

### Backend — `backend/tests/test_conftest_helpers.py` (2 new classes, 9 tests)

New shared logic must be pinned, so the consolidated helpers get focused
contract tests — a regression that made the parser lenient again (letting a
leaked `NaN`/`Infinity` token decode silently) would fail here at the source
instead of going unnoticed across every caller.

| Class / test | Pins |
|--------------|------|
| `TestStrictJsonLoads::test_parses_ordinary_json_object` | Ordinary JSON round-trips to the equivalent Python value. |
| `TestStrictJsonLoads::test_bare_non_finite_token_raises_assertionerror` | Bare `NaN`/`Infinity`/`-Infinity` scalars each raise `AssertionError` (parametrized). |
| `TestStrictJsonLoads::test_non_finite_token_nested_in_container_raises` | A non-standard token buried inside a container is still rejected. |
| `TestStrictJsonLoads::test_quoted_nan_string_is_accepted` | The *sanitized* form `"nan"` (a quoted string) parses cleanly — only bare tokens fail. |
| `TestFirstError::test_returns_first_detail_entry` | `detail[0]` is returned verbatim. |
| `TestFirstError::test_rejects_body_with_leaked_non_finite_token` | Extraction fails if a bare non-finite token survived — the reason callers route through this helper. |
| `TestFirstError::test_non_object_body_raises` | A non-object body fails with a descriptive message. |
| `TestFirstError::test_empty_detail_list_raises` | An empty `detail` list has no first error to return. |
| `TestFirstError::test_non_object_first_detail_entry_raises` | A non-object `detail[0]` fails rather than being returned. |

Net effect: 9 duplicated helper copies removed, 2 shared helpers added, suite
grows 995 → 1006 tests, backend coverage stays **100%**, and the full suite
passes 3× with no flakiness.

---

## 2026-07-08 — QA Agent: integration-gaps session (issue #384)

Line/branch coverage of `app/main.py` is already **100%** (987 tests). This
Wednesday integration-gaps session closes a *cross-component* gap line coverage
can't see: whether the CORS middleware still wraps the response built by the
validation handler's **sanitized rebuild path**.

### Gap found — CORS untested on the `except ValueError` rebuild response

`validation_exception_handler` (`backend/app/main.py`) has two paths. The
**default path** delegates to FastAPI's `request_validation_exception_handler`.
The **sanitized rebuild path** (`except ValueError`) builds a *brand-new*
`JSONResponse(status_code=422, ...)` when the offending input can't be
JSON-encoded — a non-finite `float` (`NaN`/`Infinity`) or a string holding a lone
UTF-16 surrogate. `TestCORSOnErrorResponses` (test_integration_gaps.py) pins CORS
survival on 404 / 405 / missing-field `json={}` 422 — all the **default** path.
Nothing asserted that CORS headers survive on the *freshly-constructed* response
from the rebuild branch. A regression that registered the handler outside the
`CORSMiddleware` chain, or hand-set `headers=` on the rebuilt response, would
strip CORS from exactly this path — leaving a browser unable to read the
sanitized validation error while every existing test stayed green.

### Backend — `backend/tests/test_cors_on_sanitized_error_path.py` (new, 1 class, 8 tests)

| Class / test | Pins |
|--------------|------|
| `TestCORSOnSanitizedErrorPath::test_allowlisted_origin_gets_acao_and_vary_on_rebuilt_422` | Both allow-listed origins (`localhost:3000`, `127.0.0.1:3000`) × both sanitizer inputs (non-finite float, lone surrogate) get `Access-Control-Allow-Origin` echo + `Vary: Origin` on the rebuilt 422. |
| `TestCORSOnSanitizedErrorPath::test_disallowed_origin_omits_acao_on_rebuilt_422` | A disallowed origin gets **no** `ACAO` header on the rebuild path (× both inputs) — no origin leak. |
| `TestCORSOnSanitizedErrorPath::test_rebuilt_422_carries_cors_over_real_asgi_transport` | The allow-listed case keeps CORS integration over the real-ASGI `AsyncClient` transport too, not just in-process `TestClient` (× both inputs). |

Each test is **self-validating**: it re-asserts the sanitized marker (`"nan"` /
`"\ud83d"`) in the echoed `detail[].input`, so if a future change routed these
inputs through the default path instead, the guard fails rather than silently
pinning the wrong path.

### Verification

- New tests pass **3×** under `pytest-randomly` with no flakiness; full backend
  suite **987 pass** (was 979); 100% coverage held; `ruff format` + `ruff check`
  clean.
- No production code changed — pure integration-contract pins.

---

## 2026-07-07 — QA Agent: flaky-hunt session (issue #381)

The suite is stable today: the full backend suite (972 tests) ran **5×** under
`pytest-randomly` with distinct seeds (1–5) and the seven timing-sensitive
suites ran **8×** back-to-back — **zero flakes**. There was no live flake to
chase, so this Tuesday flaky-hunt pins a *previously-unguarded latent-flakiness
source* instead.

### Gap found — the shared perf timing helpers had no contract test

`conftest.timed_get` / `timed_post` produce the per-request `elapsed` values that
**every** p50/p95/p99 and fairness-ratio assertion across the five perf/e2e
suites sorts and bounds. Yet `test_conftest_helpers.py` deliberately pins only
`percentile`, stating the timing helpers are merely "exercised end-to-end." The
helpers time with the *monotonic* `time.perf_counter()`; a refactor to a wall
clock (`time.time()`, **non-monotonic** — steppable by NTP or a manual clock
change) would keep the perf suites passing on most runs but occasionally emit a
**negative** `elapsed`, which sorts below every real sample and silently shifts
the percentile index. That is a textbook "passes locally, flakes in CI"
regression, and nothing caught it at the helper level.

### Backend — `backend/tests/test_timing_helper_contract.py` (new, 2 classes, 7 tests)

| Class / test | Pins |
|--------------|------|
| `TestTimedGetContract::test_returns_response_and_nonnegative_finite_elapsed` | `timed_get` returns a `(Response, float)` 2-tuple with a finite, non-negative `elapsed`. |
| `TestTimedGetContract::test_returns_the_actual_response_for_the_requested_path` | The response in the tuple is the one for the path requested (tuple not transposed) — `/health` returns `healthy`. |
| `TestTimedGetContract::test_elapsed_never_negative_across_many_calls` | Across 100 GETs no `elapsed` is ever negative/non-finite — the guard that fires if `perf_counter` is swapped for a non-monotonic clock. |
| `TestTimedPostContract::test_returns_triple_with_nonnegative_elapsed_and_echoed_name` | `timed_post` returns `(Response, float, str)`; elapsed ≥ 0; the threaded name is echoed by the response body. |
| `TestTimedPostContract::test_threads_special_character_name_through_unchanged` | A unicode/whitespace/punctuation name survives the tuple and the POST echo unchanged (the correctness key the concurrent write-path tests depend on). |
| `TestTimedPostContract::test_elapsed_never_negative_across_many_calls` | Across 100 POSTs no `elapsed` is ever negative/non-finite. |
| `TestTimedPostContract::test_each_call_threads_its_own_distinct_name` | 20 distinct names each thread back to their own call — no cross-wiring in the helper. |

### Verification

- New tests pass **3×** with no flakiness; full backend suite **979 pass** (was
  972) under `pytest-randomly`; `ruff format` + `ruff check` clean.
- No production code changed — pure test-infrastructure hardening.

---

## 2026-07-05 — QA Agent: regression-prevention session (issue #374)

Backend `app/main.py` was already at **100% line + branch coverage** (960 tests
before this run counted the new ones; the "12" the workflow reported is the
module's *branch count*, not a percentage), so this Sunday regression-prevention
pass reviewed the most recent bug fix — **#372 (`3c81af3`)**, which stopped a
lone UTF-16 surrogate from crashing the server with a 500 — and found a **live,
un-pinned hole in that very fix**. Like #372, this run **fixes production code**,
not just tests.

### Defect — a lone surrogate in a JSON *object key* still crashed the server (HTTP 500)

Fix #372 guarded the `name` *value* (via a `field_validator`) and sanitized
surrogate *string values* echoed in the 422 error body (via
`_replace_lone_surrogates`). But `_replace_lone_surrogates` recursed into dict
**values** while rebuilding dict **keys** untouched
(`{k: _replace_lone_surrogates(v) ...}`). A lone surrogate can also arrive as a
JSON object **key** — e.g. a `{"\uD83D": "x"}` body with no `name` field.
Pydantic reports a `missing` error whose `input` is the *whole body dict*,
surrogate key and all; JSON object keys are UTF-8-encoded exactly like values,
so the un-sanitized key re-triggered the same `UnicodeEncodeError` in
`JSONResponse.render()` → **500**. This is the identical DoS-shaped defect #372
set out to eliminate, reached through the key path.

**Confirmed reproduction (before fix):** `POST /api/hello` with body
`{"\uD83D": "x"}` → `500 Internal Server Error`.

### Fix — `backend/app/main.py`

`_replace_lone_surrogates` now sanitizes dict **keys** as well as values
(`{_replace_lone_surrogates(k): _replace_lone_surrogates(v) ...}`). Non-string
keys pass through unchanged; valid keys (including legal astral characters) are
untouched. All surrogate-key variants now return a clean **422**.

### New tests — `backend/tests/test_regression_surrogate_object_keys.py` (new — 2 classes, 11 tests)

| Class | Pins |
|-------|------|
| `TestLoneSurrogateInObjectKeyReturns422` | A lone surrogate in an object key returns a clean 422 (never 5xx) across four body shapes — extra key with `name` missing, wrong-type `name` with a sibling surrogate key, a nested surrogate key, and two distinct surrogate keys; the 422 body's raw bytes are UTF-8-decodable and re-parse to the standard FastAPI error envelope. |
| `TestReplaceLoneSurrogatesSanitizesKeys` | Direct pins on the sanitizer's key handling: a lone-surrogate key is backslash-transcribed, every sanitized key is UTF-8-encodable, nested surrogate keys recurse, valid keys (incl. astral chars) pass through unchanged, and non-string keys survive untouched. |

### Verification

- New tests pass **3×** with no flakiness; verified to **fail (7/11)** against
  the pre-fix code and **pass (11/11)** after — genuine regression coverage.
- Full backend suite: **960 pass** (was 949); `ruff format` + `ruff check` +
  `mypy` clean; 100% line + branch coverage maintained on `app/`.
- **Production code touched** — `app/main.py` fixes a latent 500 → clean 422.

---

## 2026-07-03 — QA Agent: test-refactoring session (issue #368)

Backend is at **100% line + branch coverage** with 909 passing tests, so this
Friday **test-refactoring** run removes cross-file duplication rather than
chasing coverage. (The "6" the workflow reported is `app/main.py`'s branch
count, not a percentage.)

**Duplication removed — per-request timing + percentile arithmetic:**
- `_timed_get(client, path)` was re-declared **byte-for-byte in two suites**
  (`test_e2e_performance_scaling.py`, `test_e2e_write_path_tail_latency.py`).
- `_timed_post(client, name)` lived only in the write-path suite but is the
  natural partner of the GET helper.
- `_percentile(sorted, pct)` existed in the write-path suite, while
  `test_performance.py` re-derived the same nearest-rank index math **inline**
  (`sorted[int(len*0.95)]`, `[int(len*0.99)]`, `[len//2]`), and
  `test_e2e_performance_scaling.py` / `test_e2e_journey_performance.py` each
  inlined their own `[int(len*0.95)]` copies.

All three helpers now live once in `conftest.py` (`timed_get`, `timed_post`,
`percentile`) and are imported by the five perf/e2e suites that used them. The
nested fairness wrappers in the write-path suite were renamed
`timed_get`/`timed_post` → `sample_get`/`sample_post` to avoid shadowing the
now-imported helpers. No test behaviour changed: `percentile` reproduces the
exact clamped nearest-rank index the suites always used (`int(len*pct)` capped
at the last element), so every p50/p95/p99 value is identical.

### Backend — `backend/tests/test_conftest_helpers.py` (new, 1 class, 8 tests)

New shared logic must be pinned, so `conftest.percentile` gets a focused
contract test:

| Test | Pins |
|------|------|
| `TestPercentile::test_matches_inline_nearest_rank_index` | Result equals the `sorted[int(len*pct)]` idiom it replaced, across pct ∈ {0, .5, .9, .95, .99} — proves the refactor shifted no percentile value |
| `TestPercentile::test_p50_is_the_upper_median_of_even_length` | p50 lands on index `len//2`, matching the old `median` idiom |
| `TestPercentile::test_pct_one_is_clamped_to_last_element` | `pct == 1.0` returns the max instead of an `IndexError` |
| `TestPercentile::test_pct_above_one_still_clamps_to_last_element` | An over-unity `pct` cannot walk off the end |
| `TestPercentile::test_pct_zero_returns_first_element` | The 0th percentile is index 0 |
| `TestPercentile::test_single_element_list_returns_that_element_for_any_pct` | A one-sample list has one value at every percentile |
| `TestPercentile::test_empty_list_raises_valueerror` | An empty distribution raises `ValueError`, not `IndexError` |
| `TestPercentile::test_index_never_out_of_range_across_sizes` | For sizes {1,2,10,40,100,200} p95 ≤ p99 ≤ p100 == max, in range — guards the clamp against every fan-out width the suites use |

**Net:** +8 test methods (13 cases counting the parametrized one; 909 → 922
passing incl. the 5 refactored suites), three duplicated helpers collapsed into
one shared, tested home. Coverage unchanged at 100%; full suite green 3× under
`-p no:randomly`.

---

## 2026-07-02 — QA Agent: e2e-performance session (issue #365)

The backend is at **100% line + branch coverage** (`app/main.py`: 54 stmts, 6
branches) with 905 passing tests, so this Thursday e2e-performance run pins a
*new orthogonal perf property* rather than chasing coverage. (The "6" the
workflow reported is the branch count, not a percentage.)

**Gap found:** the **write path (`POST /api/hello`) under concurrent contention**
was unguarded for tail latency. Auditing the four perf suites:
- `test_performance.py::TestNonHealthTailLatency` pins POST p95, but over 200
  **sequential** calls — no request ever contends with another.
- `test_e2e_performance_scaling.py::TestConcurrentTailLatency` times each request
  individually *inside* a fan-out, but **GET-only** (`/health`, `/api/version`) —
  never the body-read → JSON-decode → Pydantic-validate → format pipeline.
- `test_e2e_journey_performance.py::TestCrossEndpointFairness` fans out
  `GET_PATHS` **only**; POST is excluded, so write-path starvation under mixed
  load is unpinned.
- No concurrent suite pins **p99** of an in-fan-out latency distribution (they
  stop at p95/max).

A write-path tail regression that only manifests under concurrency (validation
or body decode contending on the event loop when many POSTs are in flight)
slips past all of them.

### Backend — `backend/tests/test_e2e_write_path_tail_latency.py` (new, 2 classes, 4 tests)

| Test | Pins |
|------|------|
| `TestConcurrentWritePathTailLatency::test_concurrent_post_p95_individual_latency_bounded` | In a 100-wide concurrent POST fan-out, the p95 of individual write-path latencies stays under the ceiling; every response echoes its own name (no cross-talk) |
| `TestConcurrentWritePathTailLatency::test_concurrent_post_p99_individual_latency_bounded` | Same fan-out, bounds **p99** — a deeper tail than any existing concurrent guard, catching a rare-but-severe straggler p95 smooths over |
| `TestConcurrentWritePathTailLatency::test_no_single_concurrent_post_exceeds_p99_ceiling` | No single POST in the fan-out exceeds the p99 ceiling — catches one badly-stalled request that healthy percentiles would hide |
| `TestWritePathFairnessUnderMixedContention::test_post_p95_within_factor_of_get_p95_in_mixed_fanout` | In an interleaved GET+POST fan-out, POST p95 stays within a bounded factor of GET p95 — catches a regression that serialised only the write path (lock/blocking validator) while GET-only tail guards still pass |

Every test also asserts each POST echoes its own name, so a latency win can
never be bought by garbling or skipping validation. Bounds are generous (100x+
typical observed latency) so they fail only on real regressions. Verified
passing 3× in isolation and within the full suite (**909 passed, 2 xfailed**).

---

## 2026-06-30 — QA Agent: flaky-hunt session (issue #359)

The backend (`app/main.py`) and frontend are both at **100% line + branch
coverage**, and the full backend suite ran **five times back-to-back under
`pytest-randomly` (reshuffling order each run) with zero flakes** — the suite is
stable today. This Tuesday flaky-hunt therefore pins a *previously-unguarded
source* of cross-process flakiness rather than chasing a live flake.

**Gap found:** `test_process_isolation_flakiness.py` already pins cross-process
`PYTHONHASHSEED` determinism for the OpenAPI schema and the **success**
responses (`/health`, `POST /api/hello`, `/api/version`), and
`test_flakiness_guards.py::TestErrorResponseBodyDeterminism` pins the 404/405/422
**error** bodies — but only *in-process*, under the single hash seed the test
process happened to launch with. The **422 validation-error body across distinct
hash seeds was entirely unpinned**. That body is the most hash-order-sensitive
output in the app: unlike the model-declared success responses, the 422 `detail`
is assembled at runtime from `exc.errors()` (a list of plain `dict`s) and, for
non-finite inputs, rebuilt key-by-key by `_replace_non_finite` +
`jsonable_encoder` — the only non-trivial application logic in the service. A
regression that let `str`/`bytes` hash randomization leak iteration order into
those bytes would pass every in-process guard (they share one seed) and surface
only as an intermittent diff between two CI runs that drew different seeds.

### Backend — `backend/tests/test_process_isolation_flakiness.py` (1 class, 2 tests added)

| Test | Pins |
|------|------|
| `TestHashSeedErrorResponseStability::test_missing_field_422_body_identical_across_hash_seeds` | `POST /api/hello` with an empty body (`{}`) — built by FastAPI's *default* validation handler — serializes to one byte-identical 422 body under hash seeds `0`/`1`/`65535` |
| `TestHashSeedErrorResponseStability::test_nonfinite_422_body_identical_across_hash_seeds` | `POST /api/hello` with `[{"k": -Infinity}, NaN]` forces the app's *custom* `except ValueError` branch, recursing `_replace_non_finite` through a nested `dict`+`list` (echoed as `[{"k": "-inf"}, "nan"]`); the serialized 422 body is byte-identical across the same three seeds |

Both tests reuse the existing concurrent subprocess harness (`_run_in_subprocesses`
+ `_hash_seed_jobs`), so they add no new infrastructure and run in ~1.1s total.
Verified passing 3× in isolation and within the full reshuffled suite
(**901 passed, 2 xfailed**).

---

## 2026-06-29 — QA Agent: coverage-sprint session (issue #355)

Backend `app/main.py` and the frontend are both already at **100% line + branch
coverage** (892 passed before this run), so this Monday coverage-sprint targets a
*behavioral contract gap* rather than padding line coverage. Reviewing the
non-finite-float sanitizer (`_replace_non_finite` / `validation_exception_handler`,
shipped in #328) surfaced one: every existing pin
(`test_regression_nonfinite_sanitization.py`, `test_numeric_overflow_nonfinite.py`,
`test_edge_cases_error_paths.py`) drives the sanitizer through the **`{"name":
<non-finite>}` object shape only** — the non-finite value nested under a field, with
validation `loc == ["body", "name"]`. The **top-level body shape was entirely
unpinned**: a bare scalar body (`NaN`/`Infinity`/`-Infinity`) where the non-finite
value *is* `detail[0].input` at the document root (`loc == ["body"]`), and a
top-level JSON array (`[1, NaN, Infinity]`) where the list-recursion branch runs at
the root. A regression that only walked dict-valued inputs (or special-cased the
`"name"` field) would 500 on a bare top-level `NaN` body while the entire existing
suite stayed green.

### Backend — `backend/tests/test_nonfinite_toplevel_body.py` (new, 2 classes, 7 tests)

| Class | Tests | Pins |
|-------|-------|------|
| `TestTopLevelBareNonFiniteBody` | 4 | a bare top-level `NaN`/`Infinity`/`-Infinity` body returns a clean **422** (not 500) with the scalar stringified to `nan`/`inf`/`-inf` directly at `detail[0].input`; the validation error `loc` is `["body"]` (document root), distinguishing it from the nested `["body", "name"]` shape |
| `TestTopLevelNonFiniteArrayBody` | 3 | a top-level array `[1, NaN, Infinity]` echoes as `[1, "nan", "inf"]` (finite int preserved); a container nested inside the root array (`[{"k": -Infinity}, NaN]` → `[{"k": "-inf"}, "nan"]`) is walked; a top-level non-finite body leaks **no** bare `NaN`/`Infinity` token (re-parsed with a strict `parse_constant`, i.e. browser `JSON.parse` semantics) |

### Why this gap?

The sanitizer's nested-field behavior is exhaustively pinned, but the top-level body
is a genuinely distinct validation-error shape: the rejected `input` sits at the root
of `detail[0]` instead of inside a dict under a key. This is the one path the
`{"name": ...}` suites structurally cannot reach.

### Verification

- New suite passes **3×** (`pytest tests/test_nonfinite_toplevel_body.py`).
- **Mutation check:** disabled the `_replace_non_finite(...)` call in the handler
  (re-introducing the raw-encode 500) and confirmed all 7 tests fail with
  `ValueError: Out of range float values are not JSON compliant` — the pins genuinely
  catch the regression, not just the current good state.
- Full backend suite: **899 passed**, 2 xfailed (+7). `app/` stays 100% line+branch.
- `ruff format`/`ruff check` clean. Test-only change; no production code touched.

---

## 2026-06-28 — QA Agent: regression-prevention session (issue #352)

Backend `app/main.py` is already at **100% line + branch coverage** (885 passed
before this run), so this Sunday regression-prevention pass targets a *recently
fixed bug with no test guarding the fix*. Reviewing recent `fix(` commits surfaced
**#309 — `fix(backend): move curl install before HEALTHCHECK in Dockerfile`**: the
container `HEALTHCHECK` shells out to `curl -f http://localhost:8000/health`, but
the `RUN apt-get install ... curl` layer originally sat *after* the `HEALTHCHECK`
directive, so the probe referenced a binary the image had not yet provided. The fix
reordered the install ahead of the directive — but **nothing pinned that ordering**.
A future Dockerfile edit could silently reintroduce the bug, and it would only
surface as a container that never reports healthy (the production smoke/canary path),
invisible to the entire Python suite.

### Backend — `backend/tests/test_regression_dockerfile_healthcheck.py` (new, 3 classes, 7 tests)

Parses the Dockerfile into *logical* instructions (joining `\`-continued lines) so a
cosmetic reformat does not flap; only a real reorder or dropped install trips them.

| Class | Tests | Pins |
|-------|-------|------|
| `TestHealthcheckExistsAndUsesCurlAgainstHealth` | 3 | exactly one `HEALTHCHECK`; it invokes `curl`; it targets `/health` |
| `TestCurlInstalledBeforeHealthcheck` | 3 | a single `apt-get install curl` layer exists; it appears **before** the `HEALTHCHECK` (the exact #309 invariant, by first-physical-line position); it cleans apt lists (`rm -rf /var/lib/apt/lists/*`) |
| `TestDockerfileBaseImageProvidesNoCurl` | 1 | base image stays a `python:*-slim` variant (which omits curl) — a fat-base swap surfaces here so the curl pins can be re-evaluated deliberately |

### Why this gap?

Every other recent fix is already pinned: the non-finite-float 500 (#328) and its
RFC-valid overflow door (#350) are covered across `test_edge_cases_error_paths.py`,
`test_regression_nonfinite_sanitization.py`, and `test_numeric_overflow_nonfinite.py`.
The Dockerfile fix was the one production-breaking change with **zero** regression
coverage — and the most likely to silently regress, since image build/runtime
behaviour is outside the unit suite's reach.

### Verification

- New suite passes **3×** (`pytest tests/test_regression_dockerfile_healthcheck.py`).
- **Negative check:** reconstructed the pre-#309 (curl-after-HEALTHCHECK) Dockerfile
  in-memory and confirmed `test_curl_install_appears_before_healthcheck` fails on it —
  the pin genuinely catches the regression, not just the current good state.
- Full backend suite: **892 passed**, 2 xfailed (+7). `app/` stays 100% line+branch.
- `ruff format`/`ruff check`/`mypy` clean. Test-only change; no production code touched.

---

## 2026-06-26 — QA Agent: test-refactoring session (issue #346)

Backend `app/main.py` is already at **100% line and branch coverage** (873
passed, 2 xfailed), so Friday's test-refactoring focus targets **duplication**,
not new coverage. Audit found the JSON request header
`{"Content-Type": "application/json"}` — attached to every body-parsing /
validation `POST /api/hello` test — hard-coded **33 times across 8 files**, and
worse, independently re-declared as a *module-level constant under two
different names*: `JSON_CT` (in `test_body_decode_error_contract.py`,
`test_request_body_encoding_edges.py`) and `JSON_HEADERS` (in
`test_edge_cases_error_paths.py`, `test_regression_nonfinite_sanitization.py`).
One idea, three spellings — a Content-Type change would have meant hunting down
every copy.

### Refactor — single source of truth for the JSON request header

Added `JSON_HEADERS` to `backend/tests/conftest.py` as the one canonical
constant (with a docstring noting it must be treated as immutable — spread it,
`{**JSON_HEADERS, "Origin": ...}`, rather than mutate). All eight files now
import it; the four divergent local declarations are gone.

| File | Before | After |
|------|--------|-------|
| `conftest.py` | (no shared constant) | **new** `JSON_HEADERS` constant |
| `test_body_decode_error_contract.py` | local `JSON_CT = {...}` | imports `JSON_HEADERS`; 3 usages renamed |
| `test_request_body_encoding_edges.py` | local `JSON_CT = {...}` | imports `JSON_HEADERS`; 6 usages renamed |
| `test_edge_cases_error_paths.py` | local `JSON_HEADERS = {...}` | imports from conftest |
| `test_regression_nonfinite_sanitization.py` | local `JSON_HEADERS = {...}` | imports from conftest |
| `test_edge_cases.py` | 16 inline literals | imports `JSON_HEADERS` |
| `test_main.py` | 3 inline literals (one multi-key) | imports `JSON_HEADERS`; multi-key uses `{**JSON_HEADERS, "Content-Length": "0"}` |
| `test_integration.py` | 1 inline literal | imports `JSON_HEADERS` |
| `test_request_body_contract_gaps.py` | 7 inline literals | imports `JSON_HEADERS` |

Intentional Content-Type *variants* (`application/json; charset=utf-8`,
`Application/JSON` mixed-case) were deliberately **not** folded into the
constant — they pin distinct parser behaviours and must stay as literals.

### Verification

- **No new tests, no behaviour change** — a pure refactor. The header dict is
  byte-identical, so every one of the 873 assertions is unchanged.
- Full backend suite **873 passed, 2 xfailed** run **3×** with no flakiness.
- Coverage unchanged at **100%** line + branch.
- `ruff format`, `ruff check`, and `mypy` all clean.
- No production code touched.

---

## 2026-06-25 — QA Agent: e2e-performance session (issue #343)

Backend `app/main.py` is already at **100% line and branch coverage** (873
passed, 2 xfailed), so Thursday's e2e-performance focus has no coverage gap to
close. Instead this run targets the suite's **wall-clock time**: profiling
(`pytest --durations`) showed every one of the ~10 slowest tests living in
`backend/tests/test_process_isolation_flakiness.py`, which launches 2–4 fresh
interpreters per test (each paying the ~0.4–1.0s FastAPI import cost)
**sequentially** inside dict/set comprehensions — making that one file ~12s of
the ~30s suite.

### Backend — `backend/tests/test_process_isolation_flakiness.py` (optimized, 0 tests added)

The 7 multi-subprocess guards now spawn their per-environment interpreters
**concurrently** through a new shared `_run_in_subprocesses(snippet, jobs)`
helper backed by a `ThreadPoolExecutor`. Each `subprocess.run` blocks its
worker purely on I/O (process spawn + the child's own import), so overlapping
them gives a near-Nx speedup. Two small helpers (`_hash_seed_jobs`,
`_locale_jobs`) build the per-job env-override maps so call sites read as one
line. **No assertion changed** — each guard still compares exactly one output
per seed/locale, keyed identically, preserving every per-key diagnostic message.

| Change | Effect |
|------|------|
| Add `_run_in_subprocesses` thread-pool helper + `_hash_seed_jobs`/`_locale_jobs` | Launches the same snippet under all perturbed envs concurrently instead of serially |
| Rewrite 3 `TestHashSeedSchemaStability` + 3 `TestHashSeedResponseStability` tests | Parallel hash-seed spawns; identical byte/set/value comparisons |
| Rewrite 3 `TestLocaleIndependence` multi-locale tests | Parallel locale spawns; identical UTC-offset/message/byte comparisons |

### Verification

- File wall-clock: **~12s → ~5.5s** (cold); full suite **30.2s → 23.7s** (~22% faster), **15.9s** warm.
- File passes **3×** under `pytest-randomly` with no flakiness; full backend suite **873 passed, 2 xfailed** 3×.
- Coverage unchanged at **100%** line + branch.
- `ruff format`, `ruff check`, and `mypy` all clean.
- No production code touched — test-suite performance optimization only; all assertions byte-for-byte preserved.

---

## 2026-06-24 — QA Agent: integration-gaps session (issue #340)

Backend `app/main.py` is already at **100% line and branch coverage** (817
tests). The integration gap closed here is a *contract* gap line coverage can't
see: the **`Allow` header on 405 Method Not Allowed responses**. RFC 7231 §6.5.5
requires a 405 to enumerate the supported methods, and the app delegates this
entirely to Starlette's router — making the header's contents an emergent
property of how FastAPI registers routes. Before this session only the **HEAD**
case (`HEAD /health` → `Allow: GET`) was pinned; the ordinary disallowed verbs
(`DELETE`/`PUT`/`PATCH`), bare `OPTIONS`, the GET-only meta routes, and the
multi-method `/api/hello` path were all unverified.

**Headline finding:** `DELETE /api/hello` returns `Allow: GET` — **not**
`GET, POST` — even though both verbs are registered. FastAPI creates a separate
`APIRoute` per decorator and Starlette reports only the first path-matching
route's methods on a method mismatch (no sibling aggregation). This surprising,
upgrade-fragile behaviour is now pinned in both directions.

### Backend — `backend/tests/test_method_not_allowed_allow_header.py` (new, 8 classes + 1 guard, 56 tests)

Suite grows 817 → 873 backend tests. Passes **3×** under `pytest-randomly`
(~0.17s/run) with no flakiness. Coverage held at **100%**.

| Class / test | Pins |
|------|------|
| `TestAllowHeaderPresentOnEvery405` | Every 405 from a real route (DELETE/PUT/PATCH × `/health`,`/api/version`,`/api/hello`) carries an `Allow` header that is present, non-empty, and contains only valid uppercase HTTP method tokens. |
| `TestAllowHeaderAdvertisesGet` | All three app routes are GET-registered, so each 405 `Allow` includes `GET` (the client's recovery hint). |
| `TestApiHelloAllowHeaderDoesNotAggregate` | The dual-method `/api/hello` 405 advertises exactly `{GET}`, never `POST` — pinning the no-sibling-aggregation behaviour. |
| `TestBareOptionsAllowHeader` | A bare `OPTIONS` (no preflight headers) falls through CORS to the router → 405 with `Allow: GET`. |
| `TestMetaRouteAllowHeader` | `/openapi.json`, `/docs`, `/redoc` 405s on non-GET verbs advertise `GET`. |
| `TestAllowHeaderDeterminism` | 50× `DELETE /api/hello` yields one distinct `Allow` value (no mutable routing-state leak). |
| `TestAllowHeaderCorsParityOnError` | A 405 from an allow-listed origin carries *both* the router's `Allow` and the middleware's `Access-Control-Allow-Origin` — neither layer clobbers the other. |
| `TestAllowHeaderAsyncTransportParity` | The `{GET}`-only `Allow` on `DELETE /api/hello` holds over the real ASGI transport, not just the in-process `TestClient`. |
| `test_no_app_route_registers_a_405_disallowed_verb` | Structural guard: fails loudly if a future route registers DELETE/PUT/PATCH, invalidating the suite's "disallowed verb" premise. |

No production code touched — integration-contract pins only.

---

## 2026-06-23 — QA Agent: flaky-hunt session (issue #337)

**No flaky test was found.** Both suites are at **100% coverage** (backend 815
tests, frontend 96) and the hunt was exhaustive:

- Full backend suite run **5×** under `pytest-randomly` (fresh order/seed each
  run) — zero flakes.
- The timing/perf and e2e-throughput suites (the only wall-clock-sensitive
  tests) stress-run **dozens of times under 2× CPU oversubscription** (8 busy
  loops on 4 cores) — zero flakes.
- Margin analysis of the tightest ratio guard
  (`test_max_latency_within_50x_median`): the `median*50` term is **45–200 ms**
  because TestClient keeps the `/health` median at ~1–4 ms, so the 5 ms floor
  never binds — worst-call headroom stays **>44 ms** even under heavy load. The
  guard is robust, not fragile (an initial hypothesis that it was the flakiest
  test was empirically disproved).

The existing flakiness-guard coverage is unusually complete — schema/message/
timestamp determinism, async **and** true-thread concurrency, client isolation,
GC, RNG-seed, `TZ`, `LC_ALL`/locale, and `PYTHONHASHSEED` (cross-process) are
all already pinned. The single genuine gap: the cold-cache OpenAPI-schema race
is only exercised under **`asyncio`** (`TestOpenAPISchemaUnderConcurrency`),
which interleaves builders cooperatively on one core and can never run two
builders on two cores at the same instant — the same limitation that motivated
`TestThreadedConcurrencyDeterminism` for the handler path.

### Backend — `backend/tests/test_flakiness_guards.py` (+1 class, +2 tests)

Suite grows 815 → 817 backend tests. Passes **3×** (and **10×** under 2× CPU
oversubscription) with no flakiness (~0.3s/run). Coverage held at **100%**.

| Class | Pins |
|------|------|
| `TestThreadedColdCacheSchemaDeterminism` | Cold-cache OpenAPI generation must agree under **true OS-thread** parallelism — the one execution model no existing guard reaches. `test_threaded_single_cold_fetch_all_agree`: one cache reset, then 32 threads each fetch `/openapi.json` once; every parsed schema equals the first. `test_threaded_reset_and_fetch_race_all_agree`: each thread clears `app.openapi_schema` immediately before its own fetch, so builders race for the whole run (not just the opening wave); all parsed schemas identical. Schemas compared as parsed dicts (parallel builders may serialise keys in different orders); the original cache value is restored in `finally` so the shared-`app` reset cannot leak into adjacent tests. |

No production code touched — flakiness-guard pins only.

---

## 2026-06-21 — QA Agent: regression-prevention session (issue #330)

**Backend line/branch coverage is already 100%** (54 stmts, 6 branches, 790
tests before this run), so this Sunday regression-prevention pass targets
*unpinned behaviour from the past week's commits*, not coverage.

Reviewing the week, the only **real defect fix** was #328 (`fix NaN/Infinity
500`), which added `app.main.validation_exception_handler` plus the recursive
pure helper `app.main._replace_non_finite`. The Saturday edge-cases suite
(`test_edge_cases_error_paths.py`) pins that fix only for the **top-level**
`{"name": NaN}` shape. The parts most likely to silently regress under a future
refactor of the helper — its **recursion** through nested containers and its
**selectivity** (finite values pass through untouched) — were left unpinned.

### Backend — `backend/tests/test_regression_nonfinite_sanitization.py` (new, 3 classes, 23 tests)

Suite grows 790 → 813 backend tests (+23). Passes **3×** with no flakiness
(~0.05s/run). Coverage held at **100%** line + branch.

| Class | Pins |
|------|------|
| `TestNonFiniteSanitizationRecursesThroughContainers` | A `name` field that is a *container* of mixed non-finite/finite values echoes back through `detail[0].input` with **only** the `NaN`/`Infinity`/`-Infinity` floats stringified and every finite sibling, key, and structure preserved — through lists (`[NaN,1,Infinity]`→`["nan",1,"inf"]`), nested dicts (`{"x":NaN,"y":2}`→`{"x":"nan","y":2}`), and deep dict→list→dict alternation. A nested non-finite value leaks **no** bare `NaN`/`Infinity` token (verified by re-parsing the body with a strict `parse_constant` that rejects those tokens, i.e. browser `JSON.parse` semantics). |
| `TestFiniteValuesAreNeverStringified` | The common-case 422 stays byte-identical to FastAPI's default: a finite `int` input (`123`) echoes as the int `123` (not `"123"`) and a finite `float` (`1.5`) as the float `1.5` — the fix did not broaden sanitization to finite values, so the `input` type SDK error models branch on is unchanged. |
| `TestReplaceNonFiniteHelperContract` | Direct unit pins on the pure `_replace_non_finite`: each non-finite scalar becomes its `str()` repr (`nan`/`inf`/`-inf`); every finite/non-float scalar (incl. `bool`, `None`, `0.0`, the literal string `"nan"`) passes through identically by value *and* type; a deeply nested mixed structure is walked correctly; and the helper does **not** mutate its input (builds new containers). |

### Why these specific gaps?

- The edge-cases suite proved the fix stops the 500 for the simplest input shape,
  but `_replace_non_finite` is *recursive* — its dict/list branches and its
  "leave finite values alone" guard are exercised by 100% line coverage yet
  pinned by **no behavioural assertion**. A refactor that flattened the helper to
  the top level, or special-cased only `dict`, would keep 100% coverage while
  reintroducing the 500 (or leaking a bare nested `NaN` token to strict clients).
- Pinning that finite values are **not** stringified documents the deliberately
  narrow scope of the fix (only the crash-causing inputs are altered), so a future
  "just sanitize everything" simplification fails loudly instead of silently
  changing the wire type of every validation error's `input` field.

### Verification

- New suite passes **3×** (`pytest tests/test_regression_nonfinite_sanitization.py`).
- Full backend suite: **813 passed, 2 xfailed**, no flakes.
- Coverage held at **100%** line + branch.
- `ruff format`, `ruff check`, and `mypy` all clean.

---

## 2026-06-20 — QA Agent: edge-cases session (issue #327)

**Backend line/branch coverage is already 100%**, so this Saturday edge-cases
run targets *error-path behaviour*, not coverage. While analysing how the API
handles non-standard request bodies it surfaced a **real defect**: posting a
JSON body containing the non-standard constants `NaN`, `Infinity` or
`-Infinity` (which Python's `json` parser accepts even though RFC 8259 §6
forbids them) returned a **500 Internal Server Error**. The token parses to a
non-finite `float`; Pydantic rejects it, but the rejected value is echoed back
inside the 422 `detail[].input` field, and `JSONResponse` serializes with
`allow_nan=False`, so encoding the non-finite float raised and the request
crashed. A 500 on a *parseable* request is a denial-of-service-shaped bug — any
client library that emits `Infinity` for an overflowed number could take the
endpoint down.

### Fix — `backend/app/main.py` (`validation_exception_handler`)

Added a `RequestValidationError` handler that **delegates to FastAPI's default
handler** (so the response is byte-identical for the overwhelmingly common
case) and only deviates when the default would crash on a non-finite float — in
which case it rebuilds the same 422 payload with those values stringified
(`"nan"`/`"inf"`/`"-inf"`). No existing behaviour changes; the discriminator
(`type`/`loc`/`msg`) clients branch on is preserved.

### Backend — `backend/tests/test_edge_cases_error_paths.py` (new, 4 classes, 17 tests)

Suite grows 773 → 790 backend tests (+17). Confirmed to pass **3×** with no
flakiness (~0.1s/run).

| Class | Pins |
|------|------|
| `TestNonStandardJSONConstantsDoNotCrash` | `NaN`/`Infinity`/`-Infinity` — as a field value and as the whole body — return a well-formed 422 (not a 500); the field-value case keeps its `string_type` discriminator; the echoed `input` is stringified so the response stays RFC-8259-valid JSON (no bare `NaN` token leaks to strict client parsers) |
| `TestWhitespaceOnlyBodyIsMalformed` | A whitespace-only body (spaces/tabs/CRLF/mixed) is `json_invalid` — a third branch distinct from the tolerated *trailing* whitespace and the zero-byte `missing` case |
| `TestPythonJSONExtensionsRejected` | Single-quoted strings, a trailing comma, and a leading-zero number are each `json_invalid` — guarding against a swap to a lenient (`json5`/`demjson`/YAML) parser |
| `TestRequestContentEncodingIgnored` | The server does **not** decode `Content-Encoding` on requests: a `gzip`-declared *plain* JSON body succeeds (200), while *actually* gzipped bytes are a 4xx (never transparently inflated to 200) |

### Why these specific gaps?

- The existing `test_edge_cases.py` pins the *decoded-JSON* contract and strict
  parsing (comments, concatenated objects, extra brace) exhaustively, but never
  the non-standard numeric constants — the one input class that round-trips
  *into* the parser yet *out of* a strict encoder, which is exactly why it
  crashed.
- Whitespace-only and the three dialect features are realistic client mistakes
  (Python `str(dict)`, copy-pasted JS literals, C-style octal) that a lenient
  parser would silently accept.
- Request-side `Content-Encoding` was wholly unpinned; pinning both directions
  documents that decompression is the edge/proxy's job, so a future
  request-decompression middleware can't silently change the wire contract.

### Verification

- New suite passes **3×** (`pytest tests/test_edge_cases_error_paths.py`).
- Full backend suite: **790 passed, 2 xfailed**, 3× consecutively, no flakes.
- Coverage held at **100%** line + branch (new handler branches covered).
- `ruff format`, `ruff check`, and `mypy` all clean.

---

## 2026-06-18 — QA Agent: e2e-performance session (issue #321)

**Backend line/branch coverage is already 100%** and there is no Playwright
`waitForTimeout` E2E suite to optimize (the frontend `test:e2e` script is a
stub), so this session adds **server-side end-to-end performance regression
guards**. The three existing perf suites (`test_performance.py`,
`test_e2e_performance_scaling.py`, `test_e2e_payload_and_throughput.py`) already
pin single-call latency, p95/p99/jitter, cold start, head-of-line blocking,
mixed validity, payload-size scaling, round-*ratio* stability, and both
sequential and single-shot concurrent throughput floors. This session targets
three slices none of them cover, each modelling how a *real frontend* drives the
API (a sequence across endpoints, many sessions at once) rather than hammering
one endpoint in isolation.

### Backend — `backend/tests/test_e2e_journey_performance.py` (new, 3 classes, 7 tests)

Suite grows 762 → 769 backend tests (+7). Every bound is 10–100× typical
observed latency on a shared CI runner, so the tests fail only on a real
regression. Confirmed to pass **3×** with no flakiness (~0.4s/run).

| Class | Pins |
|------|------|
| `TestConcurrentUserJourneys` | 25 users each run the full sequential journey (health → version → GET hello → POST hello) *concurrently*; bounds every journey's end-to-end wall-time, the cross-journey p95, and that each user's POST echoes **that user's own** name — no per-request state bleed between concurrent sessions |
| `TestCrossEndpointFairness` | In a heterogeneous fan-out mixing all GET endpoints, groups latency *by endpoint* and bounds both the slowest/fastest p95 **ratio** (relative starvation) and each endpoint's **absolute** p95 (everything-slow-together starvation) |
| `TestPerRoundConcurrentThroughputFloor` | A minimum concurrent rps must hold on **every** round of a repeated fan-out (health-only, and mixed GET+POST), not just once; catches a post-warm-up collapse or steady downward drift that the single-shot floor and round-*ratio* guards both miss. Mixed round verifies every POST echo to prove throughput isn't bought by garbling responses |

### Why these specific gaps?

- Every existing concurrent test fans out *identical* calls. None model a
  multi-endpoint **user journey** run by many concurrent sessions, so a
  regression that serialized sessions or leaked state between them was unpinned.
- Mixed-workload tests bound *total* batch time, which a regression can satisfy
  while **starving one route**; a per-endpoint p95 fairness ratio catches that.
- The concurrent rps floor is measured *once* and round stability bounds the
  *ratio* of totals; neither floors **per-round** sustained rps, so a collapse
  appearing only after warm-up slipped through.

### Verification

- New file passes **3×** with no flakiness (~0.4s/run).
- Full backend suite: **769 passed, 2 xfailed**; coverage stays **100%**.
- `ruff format`, `ruff check`, and `mypy` all clean on the new file.
- No production code touched — performance regression guards only.

---

## 2026-06-17 — QA Agent: integration-gaps session (issue #318)

**Backend line/branch coverage is already 100%**, so this session targets a
*behavioural* integration gap rather than a line-coverage one. The application
routes (`/health`, `/api/version`, `/api/hello`) are pinned exhaustively, but
the three endpoints FastAPI mounts automatically — `/openapi.json`, `/docs`
(Swagger UI), and `/redoc` — are part of the live HTTP surface yet were only
asserted to return `200` (`test_main`) and honour the CORS allow-list
(`test_edge_cases`). Their HTTP *contract* was otherwise unpinned.

**Key finding — a real asymmetry now pinned:** the app's `@app.get` routes
return **405 for `HEAD`** (Starlette does not auto-append HEAD to a FastAPI
`APIRoute`'s method set), but the three meta-endpoints are plain Starlette
routes that **auto-handle `HEAD` (200)** and advertise `Allow: GET, HEAD` on
their 405s. Both halves of the divergence are now pinned so a FastAPI upgrade or
a `docs_url`/`openapi_url` change that flips it is caught deliberately.

### Backend — `backend/tests/test_meta_endpoint_http_contract.py` (new, 5 classes, 36 tests)

Suite grows 726 → 762 backend tests (+36). Every behaviour was confirmed over
both the sync `TestClient` and the real-ASGI `AsyncClient` before writing.

| Class | Pins |
|------|------|
| `TestMetaEndpointContentType` | `/openapi.json` serves `application/json`; `/docs` and `/redoc` serve `text/html; charset=utf-8` (charset explicitly asserted) |
| `TestMetaEndpointMethodRejection` | `POST`/`PUT`/`DELETE`/`PATCH` on each meta-path return `405`; the 405 `Allow` header is exactly `{GET, HEAD}` |
| `TestMetaEndpointHeadIsAutoHandled` | `HEAD` on each meta-path is `200` with an empty body; contrast pin that `HEAD` on the app's GET routes stays `405` |
| `TestServedOpenAPIJsonBodyContract` | Served `/openapi.json` parses as JSON, declares an OpenAPI `3.x` version, and its `info.title` matches `app.title` |
| `TestMetaEndpointAsyncTransportParity` | Over async ASGI: `GET` status + Content-Type, `POST` → `405`, and `/openapi.json` echoes ACAO for an allow-listed origin |

### Verification

- New file passes **3×** with no flakiness (~0.1s/run).
- Full backend suite: **762 passed, 2 xfailed**.
- `ruff format`, `ruff check`, and `mypy` all clean on the new file.
- No production code touched — integration-contract pins only.

---

## 2026-06-16 — QA Agent: flaky-hunt session (issue #315)

**The suite is stable.** The full backend suite ran **5×** under
`pytest-randomly` (order reshuffled each run): `716 passed, 2 xfailed` every
time. The frontend suite ran **3×**: `96 passed` every time. Zero flakes
observed.

The contribution closes a gap in the flakiness *guard* coverage, not in the
product. Every guard in `test_flakiness_guards.py` pins determinism **within a
single Python process** — but the two most common *cross-process* sources of
"passes locally, flakes in CI" are unguarded, because both are read once at
interpreter/C-library start and cannot be perturbed in-process:

- **`PYTHONHASHSEED`** — randomizes `set`/`dict` iteration order per process.
  The OpenAPI schema is built from sets/dicts; an order-leak into its bytes
  would be invisible to every same-process guard (they share one seed) and
  would only flake between CI runs that drew different seeds. `pytest-randomly`
  re-seeds `PYTHONHASHSEED` across runs, so this is a live risk for this suite.
- **`LC_ALL` / `LANG`** — the locale sibling of the existing `TZ` guard
  (`TestTZEnvironmentVariableIndependence`). A handler that ever used
  locale-sensitive formatting would pass on `C`/UTF-8 runners and flake only on
  differently-configured machines.

### Backend — `backend/tests/test_process_isolation_flakiness.py` (new, 3 classes, 10 tests)

Each test launches the app in a fresh interpreter via `sys.executable` with a
deliberately-perturbed environment, then compares the output across
environments. Suite grows 716 → 726 backend tests (+10).

| Class / Test | Pins |
|------|------|
| `TestHashSeedSchemaStability::test_openapi_json_identical_across_hash_seeds` | `app.openapi()` serializes to identical bytes under hash seeds `0`/`1`/`65535` |
| `TestHashSeedSchemaStability::test_openapi_paths_set_identical_across_hash_seeds` | Declared path set is identical across seeds (diagnostic split from the byte check) |
| `TestHashSeedSchemaStability::test_components_schema_set_identical_across_hash_seeds` | Declared component-schema name set is identical across seeds |
| `TestHashSeedResponseStability::test_health_status_identical_across_hash_seeds` | `/health` `status` is the constant `healthy` under every seed |
| `TestHashSeedResponseStability::test_post_hello_message_identical_across_hash_seeds` | `POST /api/hello` returns one `message` across seeds |
| `TestHashSeedResponseStability::test_version_body_identical_across_hash_seeds` | Timestamp-free `/api/version` body is byte-identical across seeds |
| `TestLocaleIndependence::test_health_timestamp_is_utc_under_each_locale` | `/health` timestamp has a zero UTC offset under every installed locale |
| `TestLocaleIndependence::test_post_hello_message_identical_across_locales` | `POST /api/hello` `message` is identical across locales |
| `TestLocaleIndependence::test_version_body_identical_across_locales` | `/api/version` body is byte-identical across locales |
| `TestLocaleIndependence::test_openapi_schema_identical_across_locales` | `/openapi.json` is byte-identical across locales |

Locale tests skip (rather than fail) when fewer than two candidate locales are
installed, so the module stays green on minimal images.

### Verification

- New file passes **3×** with no flakiness (~11s/run; subprocess-bound).
- Full backend suite: **726 passed, 2 xfailed** under `pytest-randomly`.
- `ruff format`, `ruff check`, and `mypy` all clean on the new file.
- No production code touched — flakiness-guard pins only.

---

## 2026-06-15 — QA Agent: coverage-sprint session (issue #311)

**Both suites are already at 100% line + branch coverage** (716 backend, 92
frontend tests), so Monday's coverage-sprint has no uncovered line to chase.
Instead this run pins a genuine **behavioural contract that line coverage masks**:
in `frontend/src/app/page.tsx`, the mount-time API check only gates on
`res.ok` for the `/health` fetch. The `/api/version` and `/api/hello` GETs are
**not** `.ok`-checked — a non-200 response with a parseable JSON body still keeps
the UI "Connected" and renders the returned values. Existing tests only covered
network *rejections* mid-sequence (`mid-sequence API failure edge cases`); none
exercised a non-ok HTTP *status* that still parses, nor a `json()` parse failure
on the version/hello GETs. Suite grows 92 → 96 passing (+4); coverage stays 100%.

### Frontend — `frontend/__tests__/page.test.tsx`, new describe `coverage-sprint: only /health gates the healthy state` (4 tests)

| Test | Pins |
|------|------|
| `stays Connected when /api/version returns a non-ok status with valid JSON` | A version GET HTTP 500 whose body still parses does NOT flip to Disconnected, and its `version` value is still rendered — proving only `/health` gates health state |
| `stays Connected when /api/hello GET returns a non-ok status with valid JSON` | A hello GET HTTP 503 whose body still parses stays Connected and renders `Backend says: …` — the hello GET is intentionally not `.ok`-gated |
| `flips to Disconnected when /api/version body fails to parse as JSON` | An `ok:true` version response whose `json()` rejects (truncated/HTML body) is caught and flips to unhealthy — the parse lives inside the mount try-block |
| `flips to Disconnected when /api/hello GET body fails to parse as JSON` | Same parse-failure contract for the hello GET leg of the mount sequence |

### Verification

- New describe passes 3× with no flakiness; full frontend suite 96 tests pass.
- `prettier --write` and `next lint` clean on changed files.
- No production code touched — behavioural pins only.

---

## 2026-06-14 — QA Agent: regression-prevention session (issue #306)

**Backend is already at 100% line + branch coverage** (701 tests), so this
Sunday regression-prevention run adds **behavioural pins**, not coverage
padding. Reviewing the past week's commits (#292–#304), the newest territory is
the **request-body byte-decode error path** opened by #304
(`test_request_body_encoding_edges.py`). That commit pinned only the *status*
(400) and that `detail` is a *string*; the rest of the 400 decode-error response
contract — its content-type, CORS headers, length, exact message, and hygiene —
was left unpinned. The 400 is a *structurally distinct* path (raised while
reading the body, before the router dispatches) from the 404/405/422 responses
whose CORS/hygiene contracts are already pinned. Suite grows 701 → 716 passing
(+15); coverage stays 100%.

### Backend — `backend/tests/test_body_decode_error_contract.py` (new, 4 classes, 15 tests)

#### `TestBodyDecodeErrorBaseContract`
- `test_decode_error_content_type_is_json` — the 400 declares
  `Content-Type: application/json` (not `text/plain`); a regression to a
  plain-text error envelope would still satisfy #304's "detail is a string"
  pin yet break every JSON consumer of `error.detail`.
- `test_decode_error_detail_is_exact_documented_string` — the body is exactly
  `{"detail": "There was an error parsing the body"}`; #304 pinned only the
  *type*, SDK error renderers match on the *value*.
- `test_decode_error_content_length_matches_body` — `Content-Length` equals the
  body byte length; error-path symmetry with
  `TestErrorResponseContentLengthMatchesBody` (which covers 422/404/405, not
  this 400).
- `test_decode_error_omits_forbidden_header[set-cookie|x-powered-by|strict-transport-security|x-frame-options|server]`
  — the four-header (+`server`) hygiene contract holds on the body-decode path.

#### `TestBodyDecodeErrorCarriesCORSFromAllowlistedOrigin`
- `test_decode_error_echoes_allowlisted_origin` — the 400 from
  `http://localhost:3000` echoes it in `Access-Control-Allow-Origin`. The
  headline gap: `TestCORSOnErrorResponses` pins this for 404/405/422 (raised
  *inside* CORSMiddleware), but the 400 is raised one layer up; dropping CORS
  there makes the browser hide the real 400 from the frontend JS as an opaque
  CORS error.
- `test_decode_error_carries_vary_origin` — the 400 carries `Vary: Origin`
  (shared-cache correctness).
- `test_decode_error_carries_allow_credentials` — the 400 carries
  `Access-Control-Allow-Credentials: true` (the app is `allow_credentials=True`;
  a credentialed `fetch` needs it even on the error).

#### `TestBodyDecodeErrorOmitsCORSFromNonAllowlistedOrigin`
- `test_decode_error_from_disallowed_origin_has_no_acao` — no ACAO from
  `https://evil.example.com`.
- `test_decode_error_with_no_origin_has_no_acao` — no ACAO when no `Origin`
  header is sent. The negative half of the CORS contract on this path.

#### `TestBodyDecodeErrorOverAsyncTransport`
- `test_async_decode_error_status_content_type_and_detail` — status/content-type/
  detail hold over the real-ASGI `AsyncClient` (where the body-read-and-decode
  step actually lives).
- `test_async_decode_error_carries_cors_from_allowlisted_origin` — ACAO + Vary +
  Allow-Credentials hold over async ASGI too.

### Why these specific gaps?
The CORS-on-error and content-length pins enumerate 404/405/422 because those
are emitted by FastAPI/Starlette's exception handlers. The 400 body-decode error
is raised by the body-reading layer *before* the router runs — a regression that
mounted a body-size guard or error-formatter *outside* CORSMiddleware would drop
CORS/hygiene on the 400 while leaving every existing pin green. Pinning the 400's
full contract closes that blind spot.

### Verification
- New file run 3× back-to-back: 15 passed each time (stable).
- Full suite run 3×: **716 passed, 2 xfailed**, `app/main.py` 100% line + branch.
- `ruff format` + `ruff check` + `mypy` clean on the new file.
- No production code touched.

---

## 2026-06-13 — QA Agent: edge-cases session (issue #303)

**Backend is already at 100% line + branch coverage** (693 tests), so this
Saturday edge-cases run adds **behavioural pins**, not coverage padding. It
targets a layer no existing test touched: what happens to the raw request
**bytes** *before* the decoded JSON reaches the value parser. Suite grows
693 → 701 passing (+8) plus 2 documented `xfail`s; coverage stays 100%.

### Backend — `backend/tests/test_request_body_encoding_edges.py` (new, 3 classes, 10 tests)

#### `TestUndecodableBodyBytesReturn400`
- `test_undecodable_bytes_return_400[latin1_e_acute|truncated_multibyte|stray_continuation]`
  — illegal-UTF-8 bytes (`0xE9` Latin-1, truncated `0xC3` lead byte, stray
  `0x80` continuation) inside a JSON skeleton return **`400`**, the
  byte-decode error path — distinct from the `422` `json_invalid` path that
  fires for decodable-but-malformed JSON.
- `test_undecodable_body_detail_is_a_bare_string_not_a_list` — the `400`
  response's `detail` is a **string** (`"There was an error parsing the
  body"`), whereas the `422` path's `detail` is a **list** of error items.
  Pins the response-shape split that clients branch on.
- `test_undecodable_body_is_400_while_decodable_garbage_is_422` — asserts
  both halves of the contrast in one test: undecodable bytes → `400`/string,
  decodable non-JSON → `422`/list.

#### `TestBodyEncodingAutoDetection`
- `test_wide_encoding_body_round_trips[utf16_bom|utf32_bom|utf16be_no_bom]`
  — UTF-16 (BOM), UTF-32 (BOM), and UTF-16-BE (no BOM, null-byte sniffed)
  bodies are transparently decoded by `json.loads` (RFC 4627 §3 encoding
  detection) and return **`200`** with the name echoed. Characterization
  pins: a refactor to `body.decode("utf-8")` before parsing would flip
  these to `400` and otherwise ship silently.

#### `TestMalformedInputNeverCrashesServer`
- `test_lone_surrogate_escape_does_not_return_5xx[lone_high_surrogate|lone_low_surrogate]`
  — **`xfail(strict=True)`** documenting a latent defect: a lone surrogate
  escape (`\uD83D` / `\uDE00`) decodes into a Python `str` that then fails
  UTF-8 re-encoding during *response* serialization, surfacing as `500`.
  The test asserts the desired contract (`status < 500` — malformed input
  must never crash the server); `strict` mode flips it to a hard failure
  (xpass) the day the crash is fixed, prompting removal of the marker.

### Why these specific gaps?
`test_edge_cases.py` already pins the *decoded-JSON* contract exhaustively
(top-level non-objects, escape decoding, trailing garbage, the `422`
discriminators). None of it reaches the **byte-decode** step beneath the
JSON parser, where the `400`-vs-`422` split, the wide-encoding
auto-detection, and the lone-surrogate crash all live — exactly the error
paths a "edge-cases" focus should cover.

### Verification
- New file run 3× back-to-back: 8 passed, 2 xfailed each time (stable).
- Full suite: **701 passed, 2 xfailed**, `app/main.py` 100% line + branch.
- `ruff format` + `ruff check` clean.

---

## 2026-06-12 — QA Agent: test-refactoring session (issue #300)

**Backend coverage is already 100% line + 100% branch on `app/main.py`** (693
tests), so this Friday test-refactoring run adds **no new tests** — it removes
duplication instead. An audit found the canonical GET-route list
`["/health", "/api/version", "/api/hello"]` repeated as **five separate
literals** across the suite under three different names (`GET_PATHS`,
`CANONICAL_GET_PATHS`, `ALL_ROUTE_PATHS`) plus two anonymous inline copies.
Adding a fourth GET route would have meant finding and editing every copy — a
silent-drift hazard where some suites parametrize over the new route and others
don't.

### Refactor — single source of truth for the GET-route list

Added `GET_PATHS` to `backend/tests/conftest.py` as the one canonical list, with
a docstring noting the three former local names it replaces. Updated every
former copy to import it:

| File | Before | After |
|------|--------|-------|
| `conftest.py` | (no shared constant) | **new** `GET_PATHS` constant |
| `test_request_body_contract_gaps.py` | local `GET_PATHS = [...]` | imports `GET_PATHS` from conftest |
| `test_routing_integration_gaps.py` | local `CANONICAL_GET_PATHS = [...]` | imports `GET_PATHS` (parametrize sites updated) |
| `test_regression_prevention.py` | local `ALL_ROUTE_PATHS = [...]` literal | `ALL_ROUTE_PATHS = GET_PATHS` (descriptive alias kept, literal removed) |
| `test_main.py` | inline `["/health", "/api/version", "/api/hello"]` in `@parametrize` | `@parametrize("path", GET_PATHS)` |
| `test_integration.py` | inline `("/health", "/api/version", "/api/hello")` loop | `for path in GET_PATHS:` |

### Refactor — removed a duplicated `DISALLOWED_ORIGIN`

`test_routing_integration_gaps.py` re-declared `DISALLOWED_ORIGIN =
"https://evil.example.com"` locally even though conftest already exports the
identical constant (used by `test_edge_cases`, `test_flakiness_guards`,
`test_integration_gaps`, `test_main`). Now imported from conftest, so the
disallowed-origin value lives in exactly one place.

### Verification

- Full backend suite: **693 tests pass 3×** (unchanged count — pure refactor, no
  tests added or removed).
- `ruff format`, `ruff check`, and `mypy` all pass clean on changed files.
- No production code touched; behaviour is byte-for-byte identical (the list
  contents and ordering are unchanged, only their definition site moved).

---

## 2026-06-11 — QA Agent: e2e-performance session (issue #297)

**Backend coverage is already 100% line + 100% branch on `app/main.py`** (684
tests before this session) and there are no Playwright/E2E tests in `frontend/`
(`test:e2e` is a placeholder), so this Thursday e2e-performance run adds backend
perf **regression guards** that exercise real frontend-facing request paths
rather than coverage padding. An audit of the two existing perf suites
(`test_performance.py`, `test_e2e_performance_scaling.py`) found two slices left
open: **(1)** POST latency is pinned only at fixed sizes (1KB, 10KB) against
absolute ceilings — nothing asserts latency grows *linearly* (not
quadratically) with payload size; **(2)** every throughput *floor* is measured
sequentially — no floor on concurrent requests-per-second.

### Backend — `backend/tests/test_e2e_payload_and_throughput.py` (new, 3 classes, 9 tests)

#### `TestPayloadSizeScaling`
Samples POST latency across a 64B → 64KB body-size range (median of 7 reps per
size) and asserts the curve is not quadratic:
- `test_each_payload_size_under_largest_ceiling` (parametrized over 64B/1KB/16KB/64KB)
  — median POST latency at every size stays under a generous 1s absolute ceiling.
- `test_latency_grows_sub_quadratically_with_payload` — `median(64KB)/median(64B)`
  stays under 50x. A linear handler's ratio is small (fixed overhead dominates);
  a quadratic regression pushes it toward the square of the 1024x size ratio.
- `test_marginal_cost_per_byte_does_not_increase_with_size` — amortized per-byte
  cost at 64KB is within 4x the per-byte cost at 16KB (compares the two *largest*
  sizes where marginal cost dominates, so an O(N²) term shows up directly).

#### `TestConcurrentThroughputFloor`
Asserts a minimum sustained requests-per-second computed from a concurrent
fan-out — a guard distinct from the existing total-elapsed-time ceilings:
- `test_concurrent_health_throughput_floor` — a 100-wide concurrent `/health`
  fan-out sustains ≥ 50 req/s.
- `test_concurrent_post_throughput_floor` — a 60-wide concurrent POST fan-out
  sustains ≥ 30 req/s and every response echoes its own name (throughput not
  bought by dropping/garbling responses).

#### `TestReadWriteLatencyParity`
- `test_small_post_median_within_factor_of_get_median` — median small-body POST
  latency stays within 8x median GET latency, catching a regression that puts
  synchronous work on the write path (blocking validator, sync log flush) that
  the happy-path single-call ceilings would miss.

All bounds are deliberately generous (≈half the sequential floors / 50x the
quadratic separation) so they fail only on a real regression, never on shared-CI
noise. Verified 3x with no flakiness; full suite: **693 passed**.

---

## 2026-06-10 — QA Agent: integration-gaps session (issue #294)

**Backend coverage is already 100% line + 100% branch on `app/main.py`** (666
tests before this session), so this Wednesday integration-gaps run targets
genuine HTTP-contract gaps — behaviors that are exercisable but never pinned —
rather than coverage padding. A `grep` audit found the POST request-body
contract exhaustively pinned (`requestBody.required: true`, a `422` response, the
required `name` field) while its **inverse** had no test at all.

### Backend — `backend/tests/test_request_body_contract_gaps.py` (new, 3 classes, 18 tests)

#### `TestGetRoutesDeclareNoBodyContract`
Pins the inverse of the POST body contract at the OpenAPI level:
- `test_get_operation_declares_no_request_body` (parametrized over the 3 GET
  routes) — no GET operation carries a `requestBody`.
- `test_get_operation_declares_no_422_response` (parametrized) — no GET operation
  declares a `422`, since GET validates no input.
- `test_post_hello_is_the_sole_body_bearing_operation` — exactly one operation in
  the whole schema (`POST /api/hello`) declares a `requestBody`, catching any new
  body-bearing route slipping in.

#### `TestGetRequestsIgnoreAttachedBody`
Pins the runtime behavior that a body wrongly attached to a GET is ignored:
- `test_get_with_attached_body_returns_200_with_canonical_shape` (parametrized) —
  each GET returns 200 with its documented marker key when a JSON body is sent.
- `test_get_hello_with_body_does_not_become_a_greeting` — a `{"name": ...}` body
  does not personalise (or leak into) the static welcome message.
- `test_get_hello_does_not_validate_attached_body` — a body that POST rejects with
  422 (`{"name": 123}`) is still 200 on GET; the 422-on-POST asymmetry is pinned
  inline.
- `test_get_with_body_matches_bodiless_response_shape` (parametrized) — attaching a
  body never changes the GET response's JSON key set.
- `test_get_with_body_still_emits_valid_utc_timestamp` — the handler runs
  end-to-end (valid UTC ISO 8601 timestamp) despite the stray body.

#### `TestGetWithBodyIgnoredViaAsyncTransport`
Re-pins the GET-ignores-body contract over the real-ASGI `AsyncClient` transport:
- `test_get_hello_with_body_returns_200_via_async_client`
- `test_get_health_with_invalid_body_returns_200_via_async_client`

### Why these specific gaps?
A regression that added a validated query parameter (or body model) to a GET route
would inject a `422`/`requestBody` into its OpenAPI operation — silently changing
every generated SDK — with no failing test. Likewise, clients, proxies, and
retried requests sometimes attach a body to a GET; a change that wired body
parsing onto a GET handler, or a middleware that rejected GET bodies with a 400,
would currently go uncaught. Both behaviors were confirmed empirically over both
transports before the tests were written.

### Verification
Full backend suite: **684 tests pass** (666 → 684). New module passed 3 consecutive
runs under `pytest-randomly` with no flakiness. `ruff format`, `ruff check`, and
`mypy` all clean.

---

## 2026-06-04 — QA Agent: e2e-performance session (issue #274)

**Backend coverage is already 100% line + 100% branch on `app/main.py`** (607
tests before this session), and there is no Playwright E2E suite in this template
(`frontend` `test:e2e` is a stub). The backend `tests/test_performance.py` serves
as the perf/E2E suite — it exercises the same request sequences the frontend
issues and pins latency/throughput contracts. Thursday's e2e-performance focus
therefore targets the **parallelism and scaling** properties that only surface
when many requests are genuinely in flight at once or the suite is hammered
repeatedly — a slice deliberately orthogonal to the ~30 existing perf classes
(which measure single-call latency, sequential/concurrent throughput,
*sequential* p95/p99, cold start, jitter, and throughput floors).

Full backend suite after the change: **618 backend tests pass three consecutive
runs** (previous baseline: 607).

### Test classes added to `backend/tests/test_e2e_performance_scaling.py` (new file)

| Class | Tests | What it pins / why it matters |
|---|---|---|
| `TestConcurrencyScaling` | 2 (+3 parametrized = 4) | Amortized wall-time **per request** inside a concurrent `asyncio.gather` batch must stay under a flat ceiling at N = 20, 40, 80 (`test_amortized_per_request_cost_bounded`), and the per-request cost at 80-wide must not exceed ~4× the cost at 20-wide (`test_per_request_cost_does_not_grow_with_concurrency`). Existing tests bound *total* concurrent time at a single fixed N; neither pins the **trend**. A super-linear (O(N²)) coordination regression — a global lock, a scan keyed on the in-flight count — inflates amortized cost as N rises and is invisible to a fixed-N total-time bound. |
| `TestConcurrentTailLatency` | 2 | Each request's **individual** latency is timed from *inside* a 50-wide fan-out; the p95 (`test_p95_individual_latency_within_fanout_bounded`) and the max (`test_max_individual_latency_within_fanout_bounded`) of that distribution must stay bounded. The existing p95/p99 tests measure *sequential* calls, so a straggler that only appears under genuine contention slips through them entirely. |
| `TestHeadOfLineBlocking` | 1 | One 10KB POST is issued *together with* 40 small GETs; the whole batch — and the small GETs' individual latencies in particular — must finish fast (`test_large_post_does_not_block_concurrent_small_gets`). Existing large-payload tests measure the big request *in isolation*; this catches a handler that blocks the event loop while processing a large body, making the small requests wait behind it (head-of-line blocking). |
| `TestRepeatedConcurrentRoundStability` | 2 | Five/six repeated rounds of 25–30 concurrent calls must show no round-over-round degradation: every round under a flat ceiling and the slowest round within ~4× the fastest (`test_five_concurrent_rounds_no_degradation`), and the round totals must not increase *every* round (`test_round_totals_not_monotonically_increasing`). A per-request resource leak (unclosed object, unbounded per-request cache) manifests as later rounds getting steadily slower — a signature no single-round test can see. |
| `TestMixedValidityConcurrency` | 2 | 20 valid (200) POSTs interleaved with 20 invalid (422, missing `name`) POSTs issued together must all resolve with the correct status, in order, under ceiling, with valid responses still echoing their own name (`test_interleaved_200_and_422_under_ceiling`); and individual 422 latencies inside a 40-wide invalid fan-out must have a bounded p95 (`test_error_path_latency_bounded_under_concurrency`). Validation failures take a different code path than 200s; this guards that the error path does not serialize or stall the loop under concurrent load.|

### Why these are robust (not flaky)

The handlers are trivial and purely CPU-bound (no real I/O `await`), so on a
single-threaded event loop a concurrent fan-out is legitimately **not** faster
than sequential. The tests therefore deliberately **avoid** any "concurrent must
be faster than sequential" assertion (which would be flaky and wrong) and instead
bound *aggregate* per-request cost and *tail* latency — properties that hold
regardless of whether parallelism yields wall-clock speedup. All ceilings are
10–100× typical observed latency (~1–5 ms) on shared CI runners, and every ratio
comparison carries an additive slack term so sub-millisecond measurement jitter on
the fast end cannot trip it. The new file passed three consecutive isolated runs
(11 tests, ~0.33 s each) and three consecutive full-suite runs.

---

## 2026-06-03 — QA Agent: integration-gaps session (issue #271)

**Backend coverage is already 100% line + 100% branch on `app/main.py`** (588
tests before this session). Wednesday's integration-gaps focus therefore targets
**router/ASGI integration behaviours** that are exercised in production but pinned
nowhere in the suite. A `grep` sweep confirmed zero existing coverage of either
behaviour added here. Both were verified empirically over the in-process
`TestClient` **and** the real-ASGI `AsyncClient` transport before tests were
written.

Full backend suite after the change: **607 backend tests pass three consecutive
runs** (previous baseline: 588).

### Test classes added to `backend/tests/test_routing_integration_gaps.py` (new file)

| Class | Tests | What it pins / why it matters |
|---|---|---|
| `TestTrailingSlashRedirectIntegration` | 5 (+3 parametrized = 8) | The router runs with `redirect_slashes=True`, so `GET /health/`, `/api/version/`, `/api/hello/` each return a `307` whose `Location` is the canonical slash-free path. Every existing test only ever hits the canonical paths, so a one-line regression flipping `redirect_slashes=False` (turning every trailing-slash request into a `404`) would be completely silent. The class pins: the `307` status and canonical `Location` for all three GET paths; that `POST /api/hello/` uses `307` (method-preserving) **not** `302`/`308`, and that *following* it replays the JSON body to reach the handler and return the real greeting; that the redirect itself carries `Access-Control-Allow-Origin` + `Vary: Origin` for an allow-listed origin (a browser sees the redirect before following it) and omits ACAO for a disallowed origin; that the redirect body is empty; that `/api/missing/` is a `404` (the redirect logic must not fabricate targets for unknown paths); and a direct `app.router.redirect_slashes is True` instance assertion documenting the mechanism. |
| `TestHeadMethodReturns405` | 4 (+3 parametrized = 5) | `@app.get(...)` registers a FastAPI `APIRoute` whose method set is exactly `{"GET"}` — FastAPI, unlike bare Starlette `Route`, does **not** auto-append `HEAD`. So `HEAD /health`, `/api/version`, `/api/hello` all return `405` (not `200`, and not a body). This is surprising (many assume HEAD piggybacks on GET) and pinned nowhere. The class pins: `405` for all three GET paths; that the `405` advertises `Allow: GET`; that the response body is empty (HEAD must never carry a body, even on the error path); that the `405` still carries CORS headers for an allow-listed origin so a `fetch(..., {method:'HEAD'})` can read the status; and that `HEAD /api/missing` is a `404` (no route), distinct from the `405` (route exists, method disallowed) case. |
| `TestRoutingGapsAsyncTransportParity` | 2 | Repeats the two headline pins (trailing-slash `307`, `HEAD` `405`) over the `httpx.AsyncClient` + `ASGITransport` pair. The in-process `TestClient` and the real-ASGI transport drive different request/response framing code; this guards against a regression that only manifests under uvicorn (the production transport) where the in-process client would stay green. |

### Why this matters

The two behaviours sit at the **router boundary**, below the application handlers
that the existing 588 tests exhaustively cover. They are exactly the kind of
"framework default I never thought about" contracts that break silently:

1. **Trailing-slash redirects** are load-bearing for real clients — link
   shorteners, hand-typed URLs, and SDKs that naively join a base URL with a
   `/`-prefixed path all rely on the `307`. The `307`-not-`302` distinction is
   subtle but critical: a `302` would silently downgrade a redirected `POST` to a
   `GET`, dropping the body and turning a working request into a `405`. No
   existing test would catch a regression here because none uses a trailing slash.
2. **HEAD → 405** is a surprising FastAPI default worth pinning in *both*
   directions: a future change that "helpfully" added HEAD support (changing the
   `405` to a `200`) and a change that broke the `405` framing would each be
   caught. Monitoring tools and proxies routinely send `HEAD` probes, so the
   contract matters operationally.

Pinning CORS-on-redirect and CORS-on-405 also extends the suite's strong CORS
coverage (previously focused on `2xx`, `404`, `405`-from-DELETE, and preflight
responses) to the redirect and HEAD-405 paths, where a browser likewise needs the
`Access-Control-Allow-Origin` header to read the response.

The 11 new test functions (19 with parametrization) add **+19 tests** at a
wall-clock cost of <0.1 s per run. Three consecutive runs of the new file and
three consecutive full-suite runs confirm zero flake introduced.

---

## 2026-06-02 — QA Agent: flaky-hunt session (issue #268)

**Suite is fully stable.** Five back-to-back full backend runs (567 tests
each) and three frontend runs (91 tests each) produced zero flakes.
Backend coverage stays at 100% line + 100% branch on `app/main.py`.

With no observed flake to chase, Tuesday's flaky-hunt focus instead
extends the **regression-prevention surface** in `tests/test_flakiness_guards.py`
along five flakiness *sources* that no existing guard pins. Each new
class targets a distinct way a future change could introduce
intermittent CI noise, so that the regression fails *deterministically*
in this guard suite rather than surfacing as a 1-in-N flake weeks
later.

Full backend suite after the change: **588 backend tests pass three
consecutive runs** (previous baseline: 567).

### Test classes added to `backend/tests/test_flakiness_guards.py`

| Class | Tests | What it pins / why it matters |
|---|---|---|
| `TestTZEnvironmentVariableIndependence` | 3 (+8 parametrized = 9) | Toggles the `TZ` environment variable to `America/New_York`, `Asia/Tokyo`, `Europe/Berlin`, `Pacific/Auckland` via `os.environ` + `time.tzset()` and asserts handler timestamps still carry a `+00:00` UTC offset. This is the canonical real-world flake source: a regression that swapped `datetime.now(UTC)` → `datetime.now()` (naive, local-tz) passes on a developer's UTC machine and most CI runners, but silently fails — and *only sometimes* — on runners whose `TZ` is set to a non-UTC zone. The rapid-flip variant additionally interleaves `TZ` changes between calls to catch an import-time-cached timezone. Original `TZ` is restored in a `finally` block so the test cannot leak. |
| `TestTimestampIsoFormatRoundTrip` | 3 | Asserts every emitted timestamp survives `isoformat → fromisoformat → isoformat` byte-for-byte across 50 sequential calls per endpoint, and that every `/health` timestamp ends with the canonical `+00:00` UTC marker (rather than the alternative `Z` form, both of which parse identically). A regression that emits a non-canonical form (truncated sub-second precision when microseconds happen to be zero, `Z` suffix in some calls but not others) would still *parse* — every existing `fromisoformat`-based test would pass — but would break downstream consumers that compare timestamps byte-for-byte (log aggregators, cache keys, signed payloads). |
| `TestOpenAPIParityHTTPVsDirectCall` | 3 | Asserts the OpenAPI schema reached via `client.get("/openapi.json").json()` deep-equals the dict returned by `app.openapi()`, and that the path set and component-schema name set agree between the two transports. A future middleware that mutates the response body (injecting a per-request trace ID into the schema bytes, normalising key order differently per transport) would diverge silently — every test that uses *only* the HTTP path would still see a deterministic response, and every test that uses *only* the direct path would too, but the two would no longer agree. Clients that fetch via HTTP would then see a different schema than tools that import `app` directly. |
| `TestRepeatedSequentialColdCache` | 2 | Sequentially clears `app.openapi_schema = None` and refetches `/openapi.json` 30 times, asserting all 30 cycles produce byte-identical bodies; a second test asserts the component count is identical across 20 cold rebuilds. `TestOpenAPISchemaUnderConcurrency` clears the cache *once* and fires parallel rebuilds. This class catches a different regression class: a generator with a *cumulative* per-rebuild side effect (e.g. appending operations to a module-level list on every rebuild). A single cold-reset would not surface that — 30 sequential resets would visibly grow the output. Original cache value restored in `finally`. |
| `TestErrorResponseBodyDeterminism` | 4 | Pins that 50 consecutive `GET /no-such-path` (404), `DELETE /api/hello` (405), and `POST /api/hello` with empty JSON (422) responses each share exactly one body hash. A fourth test asserts the 404 body is identical regardless of `Origin` header (allow-listed, disallowed, absent). These responses come from Starlette's default exception handlers, not application code — but clients that compare error bodies byte-for-byte (log aggregators, fuzz-test oracles, cache keys) would still see intermittent diffs if a future change wired the error handler to include a per-request trace ID, or varied the body by origin. |

### Why this matters

The factory's CI run-time is set by the *slowest* test, but the
factory's perceived reliability is set by the *flakiest* test. A 1%
flake on a 588-test suite produces a red CI ~99.7% of the time over a
week's runs — even though every individual run has a 99% chance of
passing. The expected cost of a missed flake source is therefore not
"weeks until it surfaces" but "weeks until a human stops trusting the
red lights".

Existing classes in this file pin many *symptoms* (response bodies that
already vary, schemas that already mutate, timestamps that already
regress). The five new classes pin distinct *sources* of flake before
any symptom has appeared:

1. Environment-variable dependence (`TZ`) is the single most common
   real-world cause of "passes on my machine, fails on the runner"
   non-determinism in date-handling code.
2. Round-trip lossiness is the canonical way an upgrade to a JSON
   serializer or a `pydantic` version bump introduces a hard-to-debug
   format diff.
3. HTTP-vs-direct parity is the only test in the suite that proves the
   *two code paths* to the schema dict agree — without it, the existing
   30+ schema tests collectively pin only one path.
4. Sequential cold-cache resilience extends the single-shot guard from
   `TestOpenAPISchemaUnderConcurrency` to the cumulative-state case
   that single-shot tests structurally cannot catch.
5. Error-response determinism extends the suite's "every 200 response is
   stable" coverage to the 4xx error path that no current test pins.

Together the 15 new test functions (21 with parametrization) add **+21
tests** to the suite at a wall-clock cost of <0.7 s per run. The
suite-wide stability sample (3 consecutive full-suite runs after the
addition, plus 3 consecutive runs of just the new tests) confirms zero
flake introduced by the new guards.

---

## 2026-06-01 — QA Agent: coverage-sprint session (issue #264)

**Backend coverage stays at 100% line + 100% branch on `app/main.py`.**
Monday's coverage-sprint focus has nothing left to chase on Python
statements, so this run extends the *behavioural* coverage along the one
auto-derived surface the existing 532-test backend suite had not yet
pinned: the **per-operation OpenAPI metadata** that FastAPI generates
from each route's docstring, decorator kwargs, and parameter types. A
docstring rewrite, a stray `deprecated=True` kwarg, or a copy-paste
mistake on `response_model=` ships green today; every typed-SDK client
and the `/docs` UI sees the change. The 35 new tests below close that
gap.

Full backend suite after the change: **567 backend tests pass three
consecutive runs** (previous baseline: 532).

### Test classes added to `backend/tests/test_route_operation_metadata.py`

| Class | Tests | What it pins / why it matters |
|---|---|---|
| `TestPerOperationDescriptionMatchesHandlerDocstring` | 4 | Each `paths[path][method].description` equals `inspect.cleandoc(handler.__doc__)` — the rendered body text of every `/docs` operation panel and the method docstring of every typed-SDK client. The existing suite already pins `summary` (auto-derived from function name), `operationId`, `tags`, and the **info-level** `description`, but not the per-operation `description`. A "just tightened the wording" docstring rewrite would silently churn every consumer's generated documentation today; pinned per-route here so the rewrite surfaces at test time. |
| `TestEndpointsDeclareNoQueryOrPathParameters` | 4 | No route declares a `parameters` array today (no query / path / header params on any handler). The first time a handler grows `q: str \| None = None`, a `parameters` entry appears — and every typed SDK gains a new optional method argument. Pinning the absence makes the addition loud rather than backwards-compatible-by-accident. |
| `TestEndpointsAreNotDeprecated` | 4 | No operation has `deprecated: true` (absent or falsy). The decorator kwarg flips Swagger UI strikethrough rendering and SDK `@deprecated` annotations. Pinning the absence catches an accidental `@app.get("/health", deprecated=True)` that would broadcast a "please migrate" hint to every consumer. |
| `TestEndpointsHaveNoSecurityRequirement` | 4 | No operation declares a `security` requirement. Adding `Depends(oauth2_scheme)` (or a global security override) introduces an auth contract every client must satisfy — a major public-surface change that no other test pins as absent. |
| `TestSuccess200DescriptionIsFastAPIDefault` | 4 | Each `responses["200"].description` is the FastAPI default string `"Successful Response"`. A change indicates a per-route `responses={200: {"description": ...}}` override on the decorator — deliberate but consumer-visible (response section copy in `/docs`, SDK response docstrings). |
| `TestSuccess200ResponseDeclaresOnlyApplicationJSON` | 4 | Each 200 response declares exactly one content type, `application/json`. A regression that flipped a handler to `response_class=HTMLResponse` or that listed an alternative media type via `responses=` would silently expand the content-negotiation surface; nothing else in the suite pinned this. |
| `TestPostHelloRequestBodyIsRequiredJSON` | 2 | POST /api/hello declares `requestBody.required: true` **and** lists exactly `application/json` as the body content type. `required` controls whether typed SDKs mark the body parameter required (a `HelloRequest \| None = None` regression would silently flip it). The content-type list controls whether `application/x-www-form-urlencoded` or multipart becomes acceptable — pinning catches a future `Form()` / `UploadFile` mix-in. |
| `TestGetEndpointsDeclareOnly200` | 3 | GET endpoints document **exactly** `{200}`. Adding a documented 4xx via `responses={500: {...}}` on the decorator would expand the SDK error-handling surface (new exception classes). Pinning the singleton catches the addition. |
| `TestPostHelloDeclaresExactly200And422` | 1 | POST /api/hello documents **exactly** `{200, 422}`. A third documented code (404 from a path param, 500 from a custom `responses=`) changes the SDK exception surface; dropping 422 via `include_in_schema=False` shrinks it. Both regressions land here. |
| `TestRequestBodyReferencesHelloRequestComponent` | 1 | POST /api/hello's `requestBody.content["application/json"].schema` is exactly `{"$ref": "#/components/schemas/HelloRequest"}`. The existing integration suite resolves the ref and asserts properties of the target component but does not pin **which** component is referenced. A handler change that swapped the parameter type to `dict[str, str]` or a new `HelloInput` model would drop the `$ref` (or point it at a different component) — silently breaking every SDK that imports `HelloRequest`. |
| `TestSuccess200ResponseReferencesExpectedComponent` | 4 | Each 200 response's body schema is a `$ref` to the documented component (`HealthResponse`, `VersionResponse`, `HelloResponse`, `HelloResponse`). `TestOpenAPIComponentInventoryPinned` pins the **inventory**; nothing pins **which** component each route's 200 response points to. A copy-paste mistake that wired `response_model=HealthResponse` onto `/api/version` would still pass every other test in the suite while breaking SDK clients that decode the body against the wrong type. |

### Why this matters

Every assertion above verifies a behaviour that is **not** asserted
elsewhere in `tests/`; the gaps were identified by inspecting each
per-operation metadata slot (`description`, `parameters`, `deprecated`,
`security`, `responses[...].description`, `responses[...].content`,
`requestBody.required`, `requestBody.content`, the `responses` key set,
and the `$ref` targets) against the existing test inventory before
adding the corresponding pin.

The new file mirrors the existing convention from
`test_openapi_schema_metadata.py` and `test_regression_prevention.py`:
each class targets a single auto-derived slot, each test names the
specific regression that would slip past the existing suite, and the
parametrize ids match the project-wide `"METHOD /path"` format used by
the integration and main suites.

This run does **not** modify `app/main.py`. The change is additive in
`backend/tests/` only.

---

## 2026-05-30 — QA Agent: edge-cases session (issue #257)

**Backend coverage 100% / frontend coverage unchanged.** Saturday's focus is
edge-case behavioural pins — `app/main.py` is already at 100% line + branch,
so this run adds **37 new tests across 7 orthogonal regression classes** that
pin behaviours no existing test asserts. All 491 backend tests pass three
consecutive runs after the change (previous baseline: 454).

### Test classes added to `backend/tests/test_edge_cases.py`

| Class | Tests | What it pins / why it matters |
|---|---|---|
| `TestNameValueJSONEscapeSequences` | 4 | Server-side JSON decoding fidelity. The existing suite always passes `name` as a Python string via `json={"name": ...}`, which is encoded on the *client* side. These tests POST raw bytes containing `\uXXXX` escapes and surrogate pairs, pinning that the **server** decodes them before the handler runs. Covers a BMP escape (`A` → `A`), a surrogate-pair emoji (`😀` → `U+1F600`), mixed escape+literal (`AéB` → `AéB`), and the named tab escape (`\t`). Guards against a parser swap that handles raw bytes or only the numeric escape form. |
| `TestCORSOriginExactMatchRequiresByteIdenticalString` | 5 | The CORS allow-list match is byte-exact. `TestRegressionCORSAllowListBoundary` already pinned three near-miss origins (wrong scheme, drifted port, missing port). These pin the **remaining** realistic variants: uppercase host (`http://LOCALHOST:3000`), uppercase scheme (`HTTP://localhost:3000`), trailing slash (`http://localhost:3000/`), IPv6 loopback (`http://[::1]:3000`), and subdomain (`http://app.localhost:3000`). Each maps to a known deployment-mistake class that a "let's accept these too" regression would silently allow. |
| `TestMethodOnUndefinedPathReturns404NotMethodNotAllowed` | 4 | The 404-vs-405 distinction on **non-existent** paths. `TestHTTPMethodNotAllowed` pins 405 for unsupported methods on defined routes; this pins the complement — POST/PUT/DELETE/PATCH on `/unknown-path` must return 404, not 405. A router swap that builds a method-allow map per *path prefix* could silently start returning 405 (falsely advertising the path as real). |
| `TestResponseHeaderHygiene` | 4 | The **absence** of identifying / cookie / framing-policy headers on successful responses. `TestServerHeaderNotEmitted` already pinned the `Server` header; this extends the hygiene contract to `Set-Cookie` (stateless contract), `X-Powered-By` (framework fingerprint), `Strict-Transport-Security` (HSTS belongs at the edge, not the app), and `X-Frame-Options` (framing policy belongs at the edge). Guards against a default-cookie / fingerprint / security-header middleware addition. |
| `TestDocumentationEndpointMethodRestrictions` | 12 | Only GET is registered on `/docs`, `/redoc`, and `/openapi.json`. The existing tests pin 200 on GET, but no test pins that non-GET methods are rejected. A future `_dispatch` or "schema upload" handler on the schema URL would silently expand the surface and could expose the schema to mutation. Each docs URL is parameterised over POST/PUT/DELETE/PATCH. |
| `TestSchemaAndDocsCORSBehaviour` | 3 | The CORS allow-list applies uniformly across the auto-generated `/openapi.json` and `/docs` URLs. A regression that moved CORS from the global middleware to a per-router decorator (and missed the implicit docs / schema routers) would silently drop CORS on these endpoints — a common cross-origin target for frontend dev environments that auto-generate API clients on startup. |
| `TestContentLengthMatchesResponseBody` | 5 | The announced `Content-Length` header equals `len(response.content)` for every public route. No existing test compares the header to the actual body byte length — the byte-stability suite asserts the body itself is stable but not that the announced length matches it. A regression that wraps responses in a gzip/middleware that inflates the body without updating the header would break strict HTTP/1.1 clients that count bytes, and would not be caught by the existing byte-stability tests. Parameterised over `/health`, `/api/version`, GET `/api/hello`, POST `/api/hello`, and `/openapi.json`. |

### Why this matters

Each class is **orthogonal**: a regression in any one area lands on a single
dedicated test class rather than scattering noise across many. The
documentation in each class header points at the *category of regression*
each pin guards against — parser swap, CORS policy drift, framework
fingerprint leak, schema-URL surface expansion, header/body length
divergence — so a future maintainer reading a failure immediately knows
both what changed and why someone thought it mattered.

The previous Saturday runs (2026-05-09, 2026-05-02, 2026-04-25) accreted a
dense behavioural surface; this run extends along axes that those did not
touch:

* **Decoder fidelity** rather than encoder strictness — JSON `\u` escapes are
  the only test path that exercises the server-side `json.loads` decode of
  escape sequences in `name` values.
* **CORS exact-match** rather than near-miss policy — case-folding,
  trailing-slash tolerance, IPv4↔IPv6 equivalence, and subdomain implication
  are each their own regression class, distinct from the scheme/port
  near-misses already pinned.
* **404 vs 405 on undefined paths** — the existing 405 tests cover defined
  paths; the 404-on-undefined-path contract was unpinned and would let a
  router swap silently misrepresent the route inventory.
* **Header-absence hygiene** beyond `Server` — extends an existing one-header
  pin to a family of four headers a future middleware could plausibly emit.
* **Schema/docs URL method narrowness and CORS uniformity** — the docs URLs
  were treated as boilerplate by the route inventory tests; these pins make
  them first-class assertion targets.
* **Header/body length consistency** — independent of body byte stability;
  a new failure mode (length divergence) requiring its own pin.

---

## 2026-05-29 — QA Agent: test-refactoring session (issue #254)

**Backend coverage 100% / frontend coverage 100% (unchanged).** This Friday
refactor is purely structural: it removes duplicated CORS-preflight header
literals and a hard-coded frontend-origin string across five backend test
files by pointing each call site at the existing helpers in
`backend/tests/conftest.py`. No tests were added, removed, or renamed; no
assertions changed. All 454 backend tests pass three consecutive runs after
the refactor.

### What changed

The shared helpers in `conftest.py` already exist and were already used by
the most-recently-written tests (`test_main.py`, `test_performance.py`).
Older tests built the same header dicts inline, missing the helper. This
session unifies all call sites.

| Helper (in `conftest.py`) | Files now using it | Sites consolidated |
|---|---|---|
| `cors_preflight_headers(method, origin=LOCALHOST_ORIGIN)` — returns `{"Origin": ..., "Access-Control-Request-Method": ...}` | `test_integration_gaps.py`, `test_edge_cases.py`, `test_flakiness_guards.py`, `test_regression_prevention.py` | 10 inline preflight-header dicts |
| `LOCALHOST_ORIGIN` constant | `test_integration.py` | 3 hard-coded `"http://localhost:3000"` literals (one local variable, two inline header dicts) |

### Why each refactor is behaviour-preserving

- `cors_preflight_headers(method)` returns exactly
  `{"Origin": LOCALHOST_ORIGIN, "Access-Control-Request-Method": method}` —
  byte-identical to the inline dict it replaces.
- For the one call site that previously passed `Origin: "null"`
  (`test_edge_cases.py::test_preflight_with_null_origin_is_rejected`), the
  refactor uses the helper's existing `origin=` keyword override:
  `cors_preflight_headers("POST", origin="null")`.
- Where the inline dict carried an *extra* header
  (`Access-Control-Request-Headers`) — three sites in
  `test_flakiness_guards.py` and `test_regression_prevention.py` — the
  refactor spreads the helper's return into a larger dict literal
  (`{**cors_preflight_headers("POST"), "Access-Control-Request-Headers": ...}`),
  preserving every byte of the original request.
- `LOCALHOST_ORIGIN` is the literal `"http://localhost:3000"` — substitution
  is a textual identity.

### Why this matters

The helpers exist precisely so a future change to the CORS request shape
(e.g. ACRM renamed by a Starlette version bump, an extra preflight header
the browser now sends) touches exactly one constant in `conftest.py`
instead of a dozen literal dicts scattered across the suite. The
refactored sites are now positioned to benefit from that.

### Files touched

- `backend/tests/test_integration_gaps.py` — added `cors_preflight_headers`
  to the conftest import; consolidated 6 inline preflight-header literals
  (3 in `TestCORSPreflightOnNonExistentPath`, 1 in `TestExposeHeadersAbsentByDefault`,
  2 in `TestCORSPreflightACRMIsCaseSensitive`).
- `backend/tests/test_edge_cases.py` — added `cors_preflight_headers` to
  the conftest import; consolidated 1 inline preflight-header literal in
  `TestNullOriginHeaderRejected::test_preflight_with_null_origin_is_rejected`
  using the helper's `origin=` override.
- `backend/tests/test_flakiness_guards.py` — added `cors_preflight_headers`
  to the conftest import; consolidated the inline preflight-header literal in
  `TestCORSPreflightByteDeterminism._do_preflight` via dict-spread (extra
  ACRH header preserved).
- `backend/tests/test_regression_prevention.py` — replaced `LOCALHOST_ORIGIN`
  with `cors_preflight_headers` in the conftest import (it became unused
  after the refactor); consolidated 2 inline preflight-header literals in
  `TestCORSPreflightAllowHeadersOpen` via dict-spread.
- `backend/tests/test_integration.py` — added `LOCALHOST_ORIGIN` to the
  conftest import; replaced 3 hard-coded `"http://localhost:3000"` strings
  in `TestCORSFrontendOriginInitSequence` with the constant.

### Verification

- `uv run pytest --cov=app --cov-report=term-missing` → **454 passed, 100% line + branch coverage** for `app/__init__.py` and `app/main.py`.
- Same suite ran three more times back-to-back, all green (`6.83s / 6.78s / 7.01s`).
- `uv run ruff format .` → no files changed.
- `uv run ruff check . --fix` → all checks passed.

---

## 2026-05-28 — QA Agent: e2e-performance session (issue #251)

**Backend coverage 100% / frontend coverage 100% (unchanged).** This Thursday
top-up extends `backend/tests/test_performance.py` with seven new test classes
(10 new tests, 444 → 454 in the suite) targeting e2e-performance regression
vectors that the existing 17 performance classes do **not** cover. Each gap was
verified absent by reading the existing 712-line file before being added — none
duplicate existing assertions.

| Class | Test | Pins |
|-------|------|------|
| `TestColdStartLatency` | `test_first_request_on_fresh_client_under_ceiling` | A brand-new `TestClient`'s first `/health` call completes under 1s — catches lazy-init regressions (import-on-first-call, one-time connection setup) that are invisible to every other test because they all reuse a warm client. |
| `TestColdStartLatency` | `test_first_post_on_fresh_client_under_ceiling` | A brand-new `TestClient`'s first `POST /api/hello` completes under 1s — POST has a larger setup surface than GET (body parsing, validation), so a cold-start regression there can be worse. |
| `TestLatencyJitter` | `test_health_latency_stddev_under_ceiling` | Stddev of 200 `/health` calls stays under 50ms — distinct from p95/p99, which catch *high outliers*; stddev catches a regression that lifts the whole low end of the distribution while keeping percentiles below ceiling. |
| `TestNonHealthTailLatency` | `test_endpoint_p95_under_ceiling[version]` | p95 latency of 200 `GET /api/version` calls stays under 50ms — closes the gap left by `TestLatencyDistribution`, which only measures `/health`. |
| `TestNonHealthTailLatency` | `test_endpoint_p95_under_ceiling[hello_get]` | p95 latency of 200 `GET /api/hello` calls stays under 50ms. |
| `TestNonHealthTailLatency` | `test_endpoint_p95_under_ceiling[hello_post]` | p95 latency of 200 `POST /api/hello` calls stays under 50ms — POST has a wider regression surface (body parsing, validation) than the GETs. |
| `TestSustainedCORSPreflight` | `test_10_sequential_preflights_under_total_and_avg_ceilings` | 10 sequential CORS preflights complete in under 1s total and average under 100ms — catches a per-call allocation leak in the OPTIONS handler that the existing single-preflight test cannot see. |
| `TestVersionThroughputFloor` | `test_version_sustained_throughput_floor` | `/api/version` sustains at least 100 req/sec over 200 sequential calls — closes the gap left by `TestThroughputFloor`, which only pins `/health` and POST `/api/hello`. |
| `TestConcurrentFanOutAllEndpoints` | `test_all_four_endpoints_concurrent_under_ceiling` | Two of each of the four public endpoints issued concurrently (8 requests) complete in under 500ms, and both POSTs echo their own distinct names — catches coordination bugs that surface only when all four routes are in flight at once. |
| `TestOpenAPISchemaCacheDeep` | `test_openapi_warm_cache_calls_average_and_max_under_ceiling` | After one warm-up call (excluded), 20 subsequent `/openapi.json` calls each average under 50ms and worst-case stay under 200ms — distinguishes a real cache from a happenstance-fast miss path. The existing 5-call cache test includes the cold miss, so a never-warming cache can still pass it. |

### Why these specific edges?

Each new class targets a regression vector that existing performance guards
do **not** reach:

- **Cold-start cost on a fresh client.** Every other test in
  `test_performance.py` uses the module-scoped `app` and a function-scoped
  `client` fixture. By the time a percentile or throughput test runs, the
  ASGI app has been exercised hundreds of times and is fully warm. A
  regression that adds work to the *very first* request (lazy import,
  first-call schema build, one-time connection setup) is invisible to all of
  them. Creating a brand-new `TestClient` inside the test body and measuring
  the very first request closes that gap.
- **Latency jitter (stddev), distinct from p95/p99.** p95/p99 caps catch
  sporadic *high outliers* but leave a blind spot: a regression that lifts
  the whole low end of the distribution toward the percentile ceilings will
  degrade perceived UX (more visible animations, jitter in the chat input
  echo) while still passing every existing guard. Standard deviation across
  the same sample is a direct measurement of that effect.
- **Tail latency for non-`/health` endpoints.** `TestLatencyDistribution`
  only measures `/health`, so a tail-latency regression that affects
  `/api/version` (extra serializer field) or `/api/hello` (a slow Pydantic
  serializer added on the response model) would slip through.
- **Sustained CORS preflight cost.** `TestCORSPreflightPerformance`
  exercises a single preflight; a regression that only manifests on the
  10th-or-later preflight (e.g. per-call header allocation in CORSMiddleware,
  a regex compile leaked into the OPTIONS path) would not show up there but
  *would* show up under a sustained run of preflights — the shape real
  cross-origin frontends exhibit.
- **Per-endpoint throughput floor for `/api/version`.** `TestThroughputFloor`
  pins sustained rps for `/health` and `POST /api/hello` but leaves
  `/api/version` unguarded. `/api/version` returns one extra field over
  `/health` and is the route most often hit by deploy-verification probes,
  so a throughput regression there is visible end-to-end.
- **Concurrent fan-out across all four endpoints.** `TestMixedWorkloadConcurrent`
  interleaves only `GET` and `POST` on `/api/hello`. A coordination
  regression that surfaces only when `/health`, `/api/version`, `/api/hello`
  GET, and `/api/hello` POST are all in flight at once (e.g. a shared lock
  or a global counter contended across handlers) would slip through. This
  test exercises that exact shape and verifies the two POSTs in the fan-out
  do not cross-contaminate.
- **Deep OpenAPI cache effectiveness.** `test_openapi_json_cached_repeat_call_fast`
  averages 5 calls *including* the first uncached call, so a regression
  where the cache never warms can still pass if the 4 misses happen to
  average below the ceiling. Excluding the warm-up call and measuring 20
  subsequent calls with a tight per-call ceiling (50ms avg, 200ms worst)
  distinguishes a real cache from a happenstance-fast miss path.

### Verification

- 454 backend tests (444 → 454) pass 3× in sequence with no flakiness
  (~2.4s per isolated `test_performance.py` run, ~7.8s full-suite run).
- The 10 new tests were also run 3× in isolation to confirm they themselves
  are not flaky before the full-suite run.
- Backend line and branch coverage stays at 100% (36/36 statements + branches,
  no production code touched).
- 91 frontend tests still pass (no frontend changes this run).
- Bounds are deliberately generous (≥10× typical observed CI latency) so
  they fail only on real regressions.

---

## 2026-05-27 — QA Agent: integration-gaps session (issue #248)

**Coverage was already 100% backend / 100% frontend.** This Wednesday top-up
extends `backend/tests/test_integration_gaps.py` with eight new test classes
(23 new tests, 421 → 444 in the suite) targeting cross-component integration
behaviours that no existing test pins. Every gap was verified absent by
`grep` before being added — none duplicate existing assertions in
`test_integration.py`, `test_main.py`, or `test_edge_cases.py`.

| Class | Test | Pins |
|-------|------|------|
| `TestCORSPreflightShortCircuitsBeforeRouting` | `test_preflight_on_nonexistent_path_returns_200` | A real preflight (Origin + ACRM) on `/api/missing` returns 200 — CORSMiddleware short-circuits *before* the router so 404 paths still pass preflight. |
| `TestCORSPreflightShortCircuitsBeforeRouting` | `test_preflight_on_nonexistent_path_carries_acao` | The short-circuited preflight still echoes the allow-listed origin. |
| `TestCORSPreflightShortCircuitsBeforeRouting` | `test_preflight_on_nonexistent_path_advertises_allow_methods` | The short-circuited preflight advertises `Access-Control-Allow-Methods` with the requested method. |
| `TestOPTIONSWithOriginButNoACRMFallsThrough` | `test_options_with_origin_only_returns_405` | OPTIONS with `Origin` but no `Access-Control-Request-Method` is *not* a preflight — falls through to the router and 405s. |
| `TestOPTIONSWithOriginButNoACRMFallsThrough` | `test_options_with_origin_only_still_carries_acao` | The fall-through 405 still carries the allow-listed CORS headers so the browser can read the status. |
| `TestOPTIONSWithOriginButNoACRMFallsThrough` | `test_options_with_disallowed_origin_only_omits_acao` | The fall-through 405 from a disallowed origin omits `Access-Control-Allow-Origin`. |
| `TestOpenAPIPathsDoNotDeclareOptionsOrHead` | `test_no_path_declares_an_options_operation` | No documented path declares an `options` operation — CORSMiddleware handles OPTIONS, not the router. |
| `TestOpenAPIPathsDoNotDeclareOptionsOrHead` | `test_no_path_declares_a_head_operation` | No documented path declares a `head` operation — FastAPI auto-handles HEAD via GET. |
| `TestAsyncClientErrorPathParity` | `test_404_via_async_client_has_documented_shape` | A 404 via the real ASGI transport (AsyncClient) returns `{"detail": "Not Found"}` with `application/json`. |
| `TestAsyncClientErrorPathParity` | `test_405_via_async_client_has_documented_shape` | A 405 via the real ASGI transport returns `{"detail": "Method Not Allowed"}` with `application/json`. |
| `TestOpenAPIByteEquivalentAcrossTransports` | `test_openapi_bytes_are_identical_via_both_transports` | `/openapi.json` body bytes are identical between TestClient and AsyncClient — catches a transport-specific framing regression. |
| `TestNoExposeHeadersAdvertised` | `test_get_response_does_not_advertise_expose_headers` | GET responses do not advertise `Access-Control-Expose-Headers` — guards against accidental information disclosure to JS. |
| `TestNoExposeHeadersAdvertised` | `test_post_response_does_not_advertise_expose_headers` | POST responses do not advertise `Access-Control-Expose-Headers`. |
| `TestNoExposeHeadersAdvertised` | `test_preflight_response_does_not_advertise_expose_headers` | Preflight responses do not advertise `Access-Control-Expose-Headers`. |
| `TestSequentialReuseAcrossPersistentAsyncClient` | `test_sequential_posts_through_one_client_isolate_names` | Five sequential POSTs through one persistent AsyncClient each echo their own name — handler isolation under connection reuse (different code path from `asyncio.gather`). |
| `TestSequentialReuseAcrossPersistentAsyncClient` | `test_sequential_get_then_post_through_one_client` | GET then POST through one persistent AsyncClient each return their endpoint-specific shape. |
| `TestCORSPreflightACRMIsCaseSensitive` | `test_uppercase_acrm_succeeds[POST]` | Uppercase ACRM `POST` passes preflight (200). |
| `TestCORSPreflightACRMIsCaseSensitive` | `test_uppercase_acrm_succeeds[GET]` | Uppercase ACRM `GET` passes preflight (200). |
| `TestCORSPreflightACRMIsCaseSensitive` | `test_uppercase_acrm_succeeds[PUT]` | Uppercase ACRM `PUT` passes preflight (200). |
| `TestCORSPreflightACRMIsCaseSensitive` | `test_uppercase_acrm_succeeds[DELETE]` | Uppercase ACRM `DELETE` passes preflight (200). |
| `TestCORSPreflightACRMIsCaseSensitive` | `test_non_uppercase_acrm_returns_400[lowercase]` | Lowercase ACRM `post` is rejected with 400 `Disallowed CORS method` — pins Starlette's case-sensitive comparison. |
| `TestCORSPreflightACRMIsCaseSensitive` | `test_non_uppercase_acrm_returns_400[titlecase]` | Title-case ACRM `Post` is rejected with 400. |
| `TestCORSPreflightACRMIsCaseSensitive` | `test_non_uppercase_acrm_returns_400[mixedcase]` | Mixed-case ACRM `pOST` is rejected with 400. |

**Why these specifically.** Backend line coverage is already 100%, and the
prior `test_integration_gaps.py` already pinned the obvious integration
points (CORS on error responses, lifespan, docs HTML wiring, AsyncClient
schema contract, `Vary: Origin` on real responses, bare OPTIONS, interleaved
allow-listed origins). The gaps remaining are subtler middleware-vs-router
interactions and transport-vs-transport parity:

- **Middleware ordering** (the preflight-short-circuit and Origin-only-OPTIONS
  cases) is invisible to single-endpoint tests because both succeed by
  *bypassing* the route they target.
- **OpenAPI surface negatives** (no OPTIONS / HEAD operations) catch an
  accidental `methods=[...]` decorator that the existing inventory pin
  in `TestAPIRouteInventoryPin` doesn't surface (that test only enumerates
  documented methods on documented paths).
- **AsyncClient error-path parity** complements the existing 422-only
  AsyncClient test by pinning 404 and 405, so a regression that broke error
  framing only on the real ASGI transport surfaces before production.
- **Cross-transport byte equality** for `/openapi.json` extends the existing
  intra-transport byte-stability guards.
- **`expose_headers` negative** pins a configuration boundary that has no
  positive assertion anywhere — silently adding `expose_headers=[...]` would
  go unnoticed.
- **Sequential persistent-client reuse** exercises a different code path
  from `asyncio.gather`-based concurrency tests: the ASGI transport is kept
  alive across calls, which is how real SDKs use a single client for many
  requests.
- **Case-sensitive ACRM** pins a real Starlette behavior (browsers always
  send uppercase, but a "permissive" regression would mask malformed
  clients).

**Verification:** All 444 backend tests pass 3× in sequence with no
flakiness (full-suite runs: 9.16s, 9.79s, 9.71s). Backend coverage stays
at 100% line / 100% branch (36/36 statements).

---

## Backend Tests (`backend/tests/test_main.py`)

### `TestHealthEndpoint`
| Test | Description |
|------|-------------|
| `test_health_response` | Health check returns 200, healthy status, and non-empty timestamp |
| `test_health_timestamp_is_iso_format` | Timestamp parses as valid ISO 8601 datetime |

### `TestVersionEndpoint`
| Test | Description |
|------|-------------|
| `test_version_response` | Version endpoint returns 200 with correct name, version matching `__version__`, and environment field |

### `TestHelloWorldEndpoint`
| Test | Description |
|------|-------------|
| `test_hello_response` | GET /api/hello returns 200 with "Hello World" in message and a timestamp |

### `TestHelloNameEndpoint`
| Test | Description |
|------|-------------|
| `test_hello_name_includes_name_in_greeting[Alice/Bob/Dr. Smith-Jones/O'Brien/李明]` | POST /api/hello includes the name in the response (parametrized over ASCII, special chars, and Unicode) |
| `test_hello_name_requires_name_field` | POST /api/hello returns 422 when name field is absent |
| `test_hello_name_rejects_invalid_json` | POST /api/hello returns 422 when body is not valid JSON |
| `test_hello_name_response_includes_timestamp` | POST /api/hello response includes a timestamp field |

### `TestHelloNameEdgeCases`
| Test | Description |
|------|-------------|
| `test_hello_name_empty_string` | POST /api/hello with empty string name returns 200 (FastAPI allows empty strings) |
| `test_hello_name_whitespace_only` | POST /api/hello with whitespace-only name returns 200 with message and timestamp |
| `test_hello_name_very_long` | POST /api/hello with 1000-char name returns 200 and includes full name in message |
| `test_hello_name_newline_chars` | POST /api/hello with newline characters in name returns 200 and includes the name |
| `test_hello_name_html_chars` | POST /api/hello with HTML-like characters does not sanitize the name |
| `test_hello_name_extra_fields_ignored` | POST /api/hello ignores unknown extra JSON fields |
| `test_hello_name_null_name_rejected` | POST /api/hello returns 422 when name is null |
| `test_hello_name_integer_name_rejected` | POST /api/hello returns 422 when name is an integer |
| `test_hello_response_content_type_is_json` | POST /api/hello Content-Type is application/json |
| `test_hello_get_response_content_type_is_json` | GET /api/hello Content-Type is application/json |

### `TestHealthEdgeCases`
| Test | Description |
|------|-------------|
| `test_health_response_content_type_is_json` | GET /health Content-Type is application/json |
| `test_health_status_field_is_string` | GET /health status field is a string (not number or boolean) |
| `test_health_response_has_only_known_fields` | GET /health response has exactly `status` and `timestamp` fields |

### `TestVersionEdgeCases`
| Test | Description |
|------|-------------|
| `test_version_response_content_type_is_json` | GET /api/version Content-Type is application/json |
| `test_version_all_fields_are_strings` | GET /api/version all three fields are strings |
| `test_version_response_has_only_known_fields` | GET /api/version response has exactly `version`, `name`, `environment` fields |
| `test_version_string_is_semver_like` | GET /api/version version string follows semver format with numeric parts |

### `TestOpenAPIDocumentation`
| Test | Description |
|------|-------------|
| `test_openapi_schema_has_required_structure` | GET /openapi.json returns 200 with `openapi` and `paths` keys |
| `test_documentation_endpoints_available[/docs]` | Swagger UI returns 200 |
| `test_documentation_endpoints_available[/redoc]` | ReDoc returns 200 |

### `TestRegressionAsyncClient`
| Test | Description |
|------|-------------|
| `test_health_endpoint_via_async_client` | Async client reaches /health and receives healthy status (exercises async_client fixture) |
| `test_hello_world_via_async_client` | Async client reaches GET /api/hello and receives World greeting |
| `test_hello_post_via_async_client` | Async client POSTs to /api/hello and receives name back in greeting |
| `test_concurrent_health_requests` | Three concurrent health requests all return 200 (exercises async_client concurrency) |
| `test_invalid_post_body_returns_422_via_async_client` | Async client correctly receives 422 for null name |

### `TestRegressionUTCTimestamps`
| Test | Description |
|------|-------------|
| `test_response_timestamp_is_utc_iso8601[health/hello_get/hello_post]` | Each timestamped endpoint returns a timezone-aware ISO 8601 UTC timestamp (zero offset). Parametrized over (method, path, body) and shares the `assert_utc_iso8601` helper from `conftest.py` so the tz-aware + zero-offset invariant is checked in one place |

### `TestRegressionPackageStructure`
| Test | Description |
|------|-------------|
| `test_app_package_is_importable` | The app package imports without errors (validates hatch build config) |
| `test_app_version_is_a_non_empty_string` | app.__version__ is a non-empty string (validates package integrity) |
| `test_app_main_exposes_fastapi_instance` | app.main.app is a FastAPI instance (validates submodule discovery) |

### `TestCORSMiddleware`
| Test | Description |
|------|-------------|
| `test_cors_preflight_returns_ok_for_allowed_origin` | OPTIONS preflight for localhost:3000 returns 200 with CORS headers |
| `test_cors_get_response_includes_allow_origin_for_allowed_origin` | GET /health with localhost:3000 Origin returns Access-Control-Allow-Origin: http://localhost:3000 |
| `test_cors_get_response_includes_allow_origin_for_127_origin` | GET /health with 127.0.0.1:3000 Origin returns the correct CORS header |
| `test_cors_preflight_allows_post_method` | OPTIONS preflight for POST on /api/hello returns 200 with CORS headers |

### `TestHTTPMethodNotAllowed`
| Test | Description |
|------|-------------|
| `test_unsupported_method_returns_405[…]` | Parametrized over (method, path) — covers DELETE/PUT/PATCH against every defined route (`/health`, `/api/version`, `/api/hello`). Single test body replaces the previous 8 separate methods (5 in this class + 3 in `TestPATCHMethodNotAllowed`) |

### `TestTimestampOrdering`
| Test | Description |
|------|-------------|
| `test_successive_timestamps_are_non_decreasing[health/hello_get]` | Two successive calls to a timestamped GET endpoint return timestamps where the second is not earlier than the first (catches clock drift or response caching). Parametrized over `/health` and `/api/hello` |
| `test_hello_post_timestamp_within_request_window` | POST /api/hello timestamp falls strictly between the request start time and response receipt time (catches stale clocks) |
| `test_health_timestamps_monotone_across_10_sequential_calls` | Ten sequential /health calls produce a non-decreasing timestamp sequence — extends the two-call ordering test to catch rare timestamp caching or coarse-granularity regressions that the two-call test might miss |

### `TestRequestIsolation`
| Test | Description |
|------|-------------|
| `test_hello_name_responses_are_independent` | Two POST /api/hello calls with different names return fully independent responses with no cross-contamination |
| `test_concurrent_hello_posts_are_independent` | Three concurrent async POST /api/hello calls each receive only their own name in the response (catches shared mutable state) |

### `TestLargeScaleConcurrency`
| Test | Description |
|------|-------------|
| `test_20_concurrent_health_requests_all_return_200` | 20 simultaneous GET /health requests all return 200 with healthy status — amplifies any resource exhaustion or scheduling non-determinism that only manifests under higher load than the 3-request concurrent tests |
| `test_20_concurrent_hello_posts_have_no_name_crosscontamination` | 20 concurrent POST /api/hello calls each receive only their own name — at this scale, any global mutable state that could cause cross-contamination becomes far more likely to trigger |

### `TestNotFoundRoutes`
| Test | Description |
|------|-------------|
| `test_unknown_api_route_returns_404` | GET to an undefined route under /api/ returns 404 |
| `test_unknown_route_404_response_has_detail_key` | FastAPI 404 response includes a JSON body with a `detail` key |
| `test_root_path_returns_404` | GET / returns 404 since no route is registered at the root |

### `TestCORSDisallowedOrigin`
| Test | Description |
|------|-------------|
| `test_cors_get_does_not_expose_allow_origin_for_disallowed_origin` | GET /health from an origin not in the allowlist does NOT receive the Access-Control-Allow-Origin header (security boundary) |
| `test_cors_preflight_does_not_expose_allow_origin_for_disallowed_origin` | OPTIONS preflight from a disallowed origin does NOT expose Access-Control-Allow-Origin |

### `TestHEADMethod`
| Test | Description |
|------|-------------|
| `test_head_returns_405[/health,/api/version,/api/hello]` | HEAD on any defined route returns 405 — Starlette 1.0 does NOT auto-register HEAD for GET routes (documents potential gotcha for clients expecting auto-HEAD). Parametrized over every defined path |
| `test_head_health_response_has_no_body` | HEAD /health response body is empty even for 405 (HTTP HEAD semantics require no body regardless of status) |

### `TestRegressionMessageFormat`
| Test | Description |
|------|-------------|
| `test_get_hello_exact_message` | GET /api/hello message is exactly "Hello, World! Welcome to your Software Factory." — pins the full string so a template change is caught immediately |
| `test_post_hello_exact_message_format` | POST /api/hello with name "Alice" returns exactly "Hello, Alice! Welcome to your Software Factory." — pins the surrounding template text |
| `test_version_environment_is_development` | GET /api/version environment field equals "development" — catches a hard-coded "staging" or "production" slip (field presence tested elsewhere) |
| `test_openapi_title_is_software_factory_api` | OpenAPI title is exactly "Software Factory API" — prevents accidental renames propagating to generated clients |
| `test_openapi_version_matches_app_version` | OpenAPI version matches `__version__` — ensures the FastAPI `version=__version__` wiring is never removed or overridden |

### `TestHelloNameTypeValidation` (added 2026-05-09 — edge cases)
| Test | Description |
|------|-------------|
| `test_hello_name_wrong_type_returns_422[bool_true/bool_false/float/array/object]` | POST /api/hello returns 422 when `name` is a bool, float, JSON array, or JSON object — pins the strict-string contract for the remaining JSON value categories not covered by the existing null/int tests |
| `test_hello_top_level_array_body_returns_422` | POST /api/hello with a top-level JSON array (e.g. `["Alice"]`) returns 422 — exercises body-shape validation rather than per-field type validation |

### `TestHelloNameSpecialCharacters` (added 2026-05-09 — edge cases)
| Test | Description |
|------|-------------|
| `test_hello_name_special_char_echoed_verbatim[tab_only]` | Tab `\t` name echoed verbatim in greeting (no whitespace stripping) |
| `test_hello_name_special_char_echoed_verbatim[carriage_return_only]` | Bare CR `\r` (without LF) name echoed verbatim |
| `test_hello_name_special_char_echoed_verbatim[null_byte_in_middle]` | Embedded NUL byte `\x00` does not truncate the name |
| `test_hello_name_special_char_echoed_verbatim[astral_plane]` | Astral-plane (4-byte UTF-8) code point `𝓐` round-trips correctly |
| `test_hello_name_special_char_echoed_verbatim[combining_accent]` | Decomposed combining accent (`a` + U+0301 ◌́) preserved without normalization |

### `TestPathRouting` (added 2026-05-09 — edge cases)
| Test | Description |
|------|-------------|
| `test_path_is_case_sensitive[/Health//HEALTH//api/Hello//API/version]` | Mixed-case path variants return 404 — pins case-sensitive routing as part of the public URL contract |
| `test_health_with_trailing_slash_succeeds` | `GET /health/` returns 200 — trailing-slash convenience pinned for clients that join URLs with a trailing slash |
| `test_hello_get_query_string_is_ignored` | `GET /api/hello?name=Alice` returns the generic greeting — guards against the GET handler accidentally reading `name` from the query string |

### `TestHTTPMethodEdgeCases` (added 2026-05-09 — edge cases)
| Test | Description |
|------|-------------|
| `test_trace_method_returns_405` | TRACE on a defined route returns 405 — fills the gap left by `TestHTTPMethodNotAllowed` (DELETE/PUT/PATCH) and `TestHEADMethod` |
| `test_options_without_origin_returns_405` | Bare OPTIONS (no `Origin` header) returns 405 — CORS middleware doesn't intercept; falls through to method-not-allowed |
| `test_options_with_origin_but_no_request_method_returns_405` | OPTIONS with `Origin` but no `Access-Control-Request-Method` is not a valid preflight → 405 |
| `test_post_hello_with_zero_length_body_returns_422` | POST /api/hello with empty body and `Content-Length: 0` returns 422 — exercises FastAPI's empty-body branch (distinct from invalid JSON) |

### `TestCORSCacheCorrectness` (added 2026-05-09 — edge cases)
| Test | Description |
|------|-------------|
| `test_allowed_origin_response_includes_vary_origin` | Allowed-origin response carries `Vary: Origin` so caches don't serve a response from one origin to a different origin |
| `test_preflight_response_includes_vary_origin` | Preflight response carries `Vary: Origin` so caches store per-origin preflights |
| `test_disallowed_origin_response_does_not_set_vary` | Disallowed-origin response does NOT add `Vary: Origin` — middleware only emits Vary when it emits Allow-Origin |
| `test_allowed_origin_response_includes_allow_credentials` | `Access-Control-Allow-Credentials: true` accompanies Allow-Origin — pins `allow_credentials=True` so any frontend relying on credentialed requests doesn't silently break |

### `TestErrorResponseShape` (added 2026-05-09 — edge cases)
| Test | Description |
|------|-------------|
| `test_404_detail_is_a_string` | 404 responses have `detail` as a string ("Not Found") — distinct from the list-of-objects shape used for 422; pinned so generic clients that `str()` the value continue to work |
| `test_405_detail_is_a_string` | 405 responses have `detail` as the string "Method Not Allowed" — same shape as 404, distinct from 422 |

### `TestExactGreetingFormat` (added 2026-05-09 — edge cases)
| Test | Description |
|------|-------------|
| `test_empty_name_message_format` | `{"name": ""}` returns exactly `"Hello, ! Welcome..."` — no trimming or "anonymous" fallback |
| `test_whitespace_name_message_format` | `{"name": "   "}` returns exactly `"Hello,    ! Welcome..."` — whitespace preserved verbatim, not collapsed |
| `test_tab_name_message_format` | `{"name": "\t"}` returns exactly `"Hello, \t! Welcome..."` — tab preserved verbatim |
| `test_duplicate_name_keys_last_wins` | Duplicate `name` keys in the JSON body resolve last-wins — pins FastAPI/Starlette/`json.loads` behavior so a parser swap is detected |

### `TestRegressionOpenAPIRouteMetadata` (added 2026-05-10 — regression-prevention)
| Test | Description |
|------|-------------|
| `test_route_has_expected_tag[get-/health-System/get-/api/version-System/get-/api/hello-Hello World/post-/api/hello-Hello World]` | Each route's OpenAPI `tags` field equals the documented value (`["System"]` or `["Hello World"]`). Pinned because SDK generators and the `/docs` UI group operations by tag — a removed/renamed tag silently re-groups operations for downstream consumers |
| `test_route_operation_id_pinned[get-/health-…/get-/api/version-…/get-/api/hello-…/post-/api/hello-…]` | Each route's auto-generated `operationId` (e.g. `health_check_health_get`) matches the documented value. Pinned because generators like `openapi-typescript` and `swagger-codegen` use operationIds as method names — a function rename silently changes the public SDK API |

### `TestRegressionFastAPIDescription` (added 2026-05-10 — regression-prevention)
| Test | Description |
|------|-------------|
| `test_openapi_description_is_pinned` | OpenAPI `info.description` equals exactly `"Backend API powered by Claude Software Factory"` — `TestRegressionMessageFormat` already pinned `info.title` and `info.version`; this fills the third member of the publicly visible `info` block (rendered on `/docs` and consumed by SDK generators emitting module docstrings) |

### `TestRegressionDocumentationURLs` (added 2026-05-10 — regression-prevention)
| Test | Description |
|------|-------------|
| `test_docs_url_is_exactly_slash_docs` | Swagger UI is served at exactly `/docs` (200) and not at alternative paths like `/documentation` or `/api/docs` (404). Pins the URL contract — `TestOpenAPIDocumentation` only verified the canonical path returns 200, not that nothing else does |
| `test_redoc_url_is_exactly_slash_redoc` | ReDoc is served at exactly `/redoc` (200) and not at `/api/redoc` (404). Same rationale — relocating the docs UI is a breaking change for bookmarks and internal documentation |

### `TestRegressionCORSPreflightContents` (added 2026-05-10 — regression-prevention)
| Test | Description |
|------|-------------|
| `test_preflight_advertises_post_in_allow_methods` | The CORS preflight response includes `POST` in `Access-Control-Allow-Methods`. Pinned because the wildcard `allow_methods=["*"]` configuration produces this; if a future change tightens to `allow_methods=["GET"]`, every browser-side POST silently fails with a CORS error and existing tests still pass |
| `test_preflight_advertises_get_in_allow_methods` | The preflight response includes `GET` in `Access-Control-Allow-Methods`. Complementary regression guard for the init sequence (`/health`, `/api/version`, `/api/hello` GETs) |
| `test_preflight_max_age_is_present_and_positive` | The preflight response advertises a positive integer `Access-Control-Max-Age` (Starlette default: 600s). Without a positive max-age, browsers re-issue the preflight on every cross-origin request — a silent perf regression. Asserts presence + positivity rather than exact value so deliberate tuning doesn't require a test edit |

**Coverage:** 100% (36/36 statements, 128 tests)

---

## Backend Performance Tests (`backend/tests/test_performance.py`)

Performance regression guards. Bounds are deliberately generous (10–100× typical observed latency) so they only fail on real regressions, not on noisy CI runners. These act as the perf side of an E2E suite for the e2e-performance focus.

### `TestSingleCallLatency`
| Test | Description |
|------|-------------|
| `test_endpoint_responds_under_ceiling[health/version/hello_get/hello_post]` | Each endpoint completes in under 500ms (regression guard). Parametrized over (method, path, body) — single test body replaces 4 separate methods |

### `TestInitSequenceLatency`
| Test | Description |
|------|-------------|
| `test_full_init_sequence_under_ceiling` | Frontend init (health → version → hello GET) completes under 500ms total |
| `test_init_sequence_then_post_under_one_second` | Init sequence followed by a user POST stays under 1s — full first-interaction budget |

### `TestSustainedSequentialLoad`
| Test | Description |
|------|-------------|
| `test_100_sequential_health_calls_under_ceiling` | 100 sequential /health calls complete in under 2s total |
| `test_no_per_call_latency_drift_across_50_calls` | Last 10 of 50 sequential calls are not >10× slower than first 10 (drift guard) |
| `test_30_sequential_posts_each_under_100ms` | Each of 30 sequential POSTs completes in <100ms — per-call regression guard |

### `TestConcurrentThroughput`
| Test | Description |
|------|-------------|
| `test_50_concurrent_health_under_ceiling` | 50 concurrent /health requests complete in under 1s total |
| `test_30_concurrent_posts_return_distinct_names` | 30 concurrent POSTs each receive their own name back (no cross-contamination, <1s) |
| `test_concurrent_not_slower_than_sequential_x2` | 30 concurrent calls finish faster than 2× sequential — catches accidental serialization of the event loop |

### `TestLargePayloadPerformance`
| Test | Description |
|------|-------------|
| `test_1kb_name_post_under_ceiling` | POST with 1KB name completes under 500ms |
| `test_10kb_name_post_under_one_second` | POST with 10KB name completes under 1s — guards against quadratic blowup |

### `TestCORSPreflightPerformance` (added 2026-05-14 — e2e-performance)
| Test | Description |
|------|-------------|
| `test_single_preflight_under_ceiling` | One CORS preflight (OPTIONS) for POST /api/hello completes under 100ms — every cross-origin POST pays this round-trip |
| `test_preflight_then_post_under_single_call_ceiling` | Preflight + the POST it gates complete together under 500ms — guards user-perceived POST latency in a real browser |

### `TestLatencyDistribution` (added 2026-05-14 — e2e-performance)
| Test | Description |
|------|-------------|
| `test_p95_latency_under_ceiling` | p95 /health latency stays under 50ms over 200 calls — tail-latency regression guard |
| `test_p99_latency_under_ceiling` | p99 /health latency stays under 100ms over 200 calls — catches sporadic slow responses the median hides |
| `test_max_latency_within_50x_median` | Worst single call never exceeds 50× median over 100 calls — outlier guard for stalls (lock contention, sync I/O on hot path) |

### `TestParallelInitSequence` (added 2026-05-14 — e2e-performance)
| Test | Description |
|------|-------------|
| `test_parallel_init_under_ceiling` | Health + version + hello fetched in parallel (matches real browser behavior) complete under 300ms |
| `test_parallel_init_not_slower_than_sequential` | Parallel init never exceeds 2× sequential time — catches accidental serialization of async handlers |

### `TestMixedWorkloadConcurrent` (added 2026-05-14 — e2e-performance)
| Test | Description |
|------|-------------|
| `test_15_reads_and_15_writes_interleaved_under_ceiling` | 15 GETs interleaved with 15 POSTs complete concurrently under 1s with no cross-contamination — realistic mixed E2E traffic pattern |

### `TestOpenAPISchemaPerformance` (added 2026-05-14 — e2e-performance)
| Test | Description |
|------|-------------|
| `test_openapi_json_under_ceiling` | GET /openapi.json completes under 500ms — schema generation cost regression guard |
| `test_openapi_json_cached_repeat_call_fast` | Five repeat /openapi.json calls average under 200ms — FastAPI schema cache regression guard |

### `TestResponsePayloadSize` (added 2026-05-14 — e2e-performance)
| Test | Description |
|------|-------------|
| `test_response_body_under_size_ceiling[health/version/hello_get/hello_post]` | Each endpoint response body stays under its pinned ceiling — bandwidth/parse-cost regression guard against accidental bloat (debug fields, leaked metadata). Parametrized over (method, path, body, ceiling_bytes) |

### `TestBurstThenIdlePattern` (added 2026-05-14 — e2e-performance)
| Test | Description |
|------|-------------|
| `test_three_bursts_each_under_ceiling` | Three back-to-back bursts of 10 concurrent requests each stay under 300ms with the third not more than 3× the first — catches per-burst resource leaks across idle gaps |

---

## Frontend Tests (`frontend/__tests__/page.test.tsx`)

### Initial Render
| Test | Description |
|------|-------------|
| `renders the title` | "Software Factory" heading is present on load |
| `renders the subtitle` | Subtitle text is present on load |
| `renders the API status section` | "API Status" section is present |
| `renders the form` | Name input and "Say Hello" button are present |

### API Status Check
| Test | Description |
|------|-------------|
| `shows connected status when API is healthy` | "Connected" badge appears after successful health check |
| `shows version when API is healthy` | Version number appears after successful API calls |
| `shows disconnected when API fails` | "Disconnected" badge appears when health check throws |
| `shows error message when API fails` | "Could not connect to backend API" message appears on failure |

### Greeting Form
| Test | Description |
|------|-------------|
| `allows typing a name` | Input accepts and holds typed value |
| `submits the form and shows greeting` | Clicking button calls POST /api/hello and renders response |
| `shows error message when POST /api/hello fails` | Network error on form submit shows "Error connecting to API" (covers `page.tsx:70`) |
| `disables input when API is disconnected` | Input is disabled when API is unhealthy |
| `disables button when API is disconnected` | Button is disabled when API is unhealthy |

### Info Cards
| Test | Description |
|------|-------------|
| `renders Getting Started section` | Getting Started heading is present |
| `renders Claude Code card` | Claude Code card is present |
| `renders API Docs card` | API Docs card is present |

### Footer
| Test | Description |
|------|-------------|
| `renders footer with technology links` | Footer contains Next.js, FastAPI, and Claude links |

### Test Isolation Guardrail
| Test | Description |
|------|-------------|
| `fetch mock has no prior calls before this test begins` | Verifies `jest.clearAllMocks()` in the outer `beforeEach` resets the mock call history before every test — if this ever fails, mock call-count assertions in subsequent tests will produce misleading results |

### Edge Cases
| Test | Description |
|------|-------------|
| `shows disconnected when health check returns non-ok status` | Mock health returning `ok: false` triggers unhealthy state (covers `page.tsx:30` branch) |
| `shows error message when health check returns non-ok status` | "Could not connect to backend API" message shown when health returns non-ok |
| `does not call POST /api/hello when name is empty` | Empty name submit triggers early return without fetch (covers `page.tsx:58` branch) |
| `does not call POST /api/hello when name is whitespace only` | Whitespace-only name trimmed to empty, no POST made |
| `shows checking status before API resolves` | "Checking..." badge shown while initial API calls are pending |
| `does not show version badge while API is checking` | Version section hidden during initial API check |
| `shows loading state during form submission` | Button shows "Sending..." and is disabled while POST is in-flight |
| `renders the View Source card` | View Source card is present in the info cards section |
| `unmounts cleanly before fetch resolves without React state update warnings` | Mounts the component with perpetually-pending fetches, then unmounts immediately — verifies no `useEffect` state updates fire on an unmounted instance, which would log React warnings and could cause test interference |

### Flakiness Prevention
| Test | Description |
|------|-------------|
| `fetches health, version, and hello in that order on mount` | Verifies the component calls /health → /api/version → /api/hello in that exact order on mount (prevents order-dependent mock regressions) |
| `clears loading state after successful submission` | After a successful POST, the button is no longer disabled and "Sending..." is not shown (catches loading-state leaks) |
| `button is disabled during submission preventing double-submit` | While a POST is in-flight, the submit button is disabled; re-enables after resolution (prevents double-submit race conditions) |
| `clears loading state after failed submission` | After a failed POST, loading state is cleared and the button re-enables (ensures finally{} cleanup path is exercised) |

### Behavioral Tests
| Test | Description |
|------|-------------|
| `shows "Backend says:" prefix when API is healthy` | When API is healthy the message paragraph contains the "Backend says:" prefix text |
| `does not show "Backend says:" prefix when API is unhealthy` | When API is unhealthy the "Backend says:" prefix is not rendered |
| `submits the form on Enter key in the name input` | Submitting the form element (keyboard Enter) calls POST /api/hello and shows the greeting |
| `sends the correct JSON body in POST /api/hello` | POST /api/hello is called with `{"name": "..."}` as the JSON body, verifying correct request construction |

**Coverage:** 100% statements, 100% branches, 100% functions, 100% lines (75 tests)

### Mid-Sequence API Failure Edge Cases (added 2026-05-02)
| Test | Description |
|------|-------------|
| `shows unhealthy when version fetch fails after health succeeds` | If /health OK but /api/version rejects, the catch block runs and shows Disconnected — tests the mid-sequence failure path not covered by the health-only failure tests |
| `shows unhealthy when hello GET fetch fails after health and version succeed` | If /health and /api/version OK but GET /api/hello rejects, shows Disconnected — tests the third position in the init sequence failing |

### Form State Edge Cases (added 2026-05-02)
| Test | Description |
|------|-------------|
| `name input retains value after successful greeting` | After a successful POST, the name input retains its typed value (component does not clear it) |
| `name input retains value after a failed submission` | After a failed POST, the name input retains its typed value |
| `second submission overwrites previous greeting` | Submitting a second time replaces the first greeting with the new one (state is replaced, not accumulated) |
| `error message is replaced by successful greeting on retry` | After an error, a successful retry replaces the error message with the greeting |

### Version Badge Edge Cases (added 2026-05-02)
| Test | Description |
|------|-------------|
| `does not show version badge when version field is absent from version response` | If /api/version returns JSON without a `version` key, `versionData.version` is undefined (falsy) and the version badge is not rendered |
| `does not show version badge when version field is an empty string` | If `version` is an empty string (falsy), the `{apiStatus.version && ...}` conditional is false and the badge is hidden |

### Regression-Prevention Tests (added 2026-05-03)
| Test | Description |
|------|-------------|
| `fetches from the correct full URLs on mount` | Verifies that the three mount-time fetches use exactly `http://localhost:8000/health`, `http://localhost:8000/api/version`, and `http://localhost:8000/api/hello` — catches endpoint path renames silently breaking the init sequence |
| `POST /api/hello is called with the correct full URL` | Verifies the form submit handler POSTs to `http://localhost:8000/api/hello` — catches a copy-paste typo in the POST URL that would break greetings while leaving the init sequence healthy |
| `every fetch on mount uses the same base URL (no mixed origins)` | Verifies that all mount-time fetch calls start with `http://localhost:8000/` — guards against one call accidentally using a different host or protocol |

### API Contract Integration Tests (added 2026-04-29)
| Test | Description |
|------|-------------|
| `shows error message when POST /api/hello returns HTTP 422` | HTTP 422 from POST (backend validation error) shows "Error connecting to API" — validates the `res.ok` check added to the POST handler (bug fix) |
| `shows error message when POST /api/hello returns HTTP 500` | HTTP 500 from POST shows "Error connecting to API" — confirms non-ok responses are handled, not just network rejections |
| `displays version from version response (not name or environment fields)` | Frontend reads only `versionData.version`; other fields (`name`, `environment`) are ignored and not rendered |
| `displays message from hello response (not timestamp field)` | Frontend reads only `helloData.message`; the `timestamp` field is not rendered as visible text |
| `handles API responses with extra unexpected fields gracefully` | Frontend tolerates extra unknown fields (uptime, build, requestId, etc.) in all three API responses — validates forward compatibility |

### Fetch Efficiency / e2e-performance (added 2026-05-07)
| Test | Description |
|------|-------------|
| `makes exactly 3 fetch calls on mount (health, version, hello)` | The init useEffect issues exactly three fetches with the expected paths — guards against a regression that adds a redundant fetch |
| `does not re-fetch when re-rendering with the same props` | Two `rerender()` calls do not re-trigger the init effect — guards against a missing/empty deps array regression |
| `issues exactly one POST per submit click (no fetch storms)` | Submitting the form fires exactly one POST, not several — catches double-binding or duplicate handler regressions |
| `rapid double-clicks during in-flight submit do not multiply POSTs` | Three rapid clicks while a submit is in flight result in one POST because the button is disabled during loading — verifies the loading-disabled contract |
| `does not fetch when submit is clicked with empty/whitespace name` | Empty and whitespace-only names short-circuit `handleSubmit` via `!name.trim()` — guards against wasted requests |
| `init sequence finishes within Jest waitFor default (1s)` | "Connected" reaches the DOM in under 1000ms — catches a regression that would otherwise impose a 1s tax on every test in this file |
| `loading state clears after submit completes (no stuck "Sending...")` | Button label flips back from "Sending..." to "Say Hello" after the POST resolves — regression guard against a missing `finally` |
| `makes init fetches without "undefined" segments (env var sanity)` | Every fetch URL begins with `http(s)://` and contains neither "undefined" nor "null" — guards against malformed URLs from a missing env var fallback |

### Whitespace-Only Submit Edge Cases (added 2026-05-09 — edge cases)
| Test | Description |
|------|-------------|
| `does not call POST /api/hello when name is tab-only` | Tab `\t` characters satisfy `String.prototype.trim()` and so must short-circuit `handleSubmit` (existing test only covered space-only) |
| `does not call POST /api/hello when name is newline-only` | Newline `\n` characters short-circuit `handleSubmit` |
| `does not call POST /api/hello when name is mixed whitespace` | Mixed whitespace ` \t\n ` short-circuits `handleSubmit` — covers the realistic "user copy-pasted" case |

### Non-BMP Greeting Rendering (added 2026-05-09 — edge cases)
| Test | Description |
|------|-------------|
| `renders an astral-plane (4-byte UTF-8) greeting from the backend as text` | Mathematical script capital A (U+1D4D0) — a JavaScript surrogate pair — renders as a single text node, not a split or escaped sequence |
| `renders an emoji greeting from the backend as text` | Emoji greeting "Hello, 🎉🤖!" renders correctly — pins the contract that the backend's verbatim echo is rendered safely |

### Form Attribute Regression Guards (added 2026-05-09 — edge cases)
| Test | Description |
|------|-------------|
| `the name input has type="text"` | Pins `<input type="text">` so a flip to `type="number"` or `type="email"` (which silently changes browser-side validation) is caught |
| `the submit button has type="submit"` | Pins button `type="submit"` so Enter-to-submit semantics keep working — the existing "submit on Enter" test passes only because of this attribute |
| `the form contains both the input and the submit button` | Pins the structural relationship — submit button must live inside the same `<form>` as the input for Enter-to-submit |

### Backend Error Response Handling (added 2026-05-09 — edge cases)
| Test | Description |
|------|-------------|
| `clears the loading state when POST returns a non-JSON body` | Even when `res.json()` rejects (e.g. backend returned HTML), the `finally` block clears `loading` and the button returns from "Sending..." — guards against a missing `finally` leaving the button stuck forever |

### POST Request Shape (added 2026-05-10 — regression-prevention)
| Test | Description |
|------|-------------|
| `POST /api/hello sends Content-Type: application/json header` | Pins the `Content-Type: application/json` header on the submit POST. Existing tests pin the body shape but never the header — a regression that drops the header would still match the body in mocks while breaking real backend negotiation (which would return 422 for a request without a JSON content-type) |
| `POST /api/hello uses uppercase method string "POST"` | The `method` option is exactly the string `'POST'` (uppercase). Existing tests filter calls by `opts.method === 'POST'`, so a regression that submitted with `'post'` would silently match no calls in those filters and the assertions would pass vacuously. This pin asserts the value positively |

### Pre-Healthy Form State (added 2026-05-10 — regression-prevention)
| Test | Description |
|------|-------------|
| `input is disabled while apiStatus.health is "checking" (initial render)` | The init fetch is left perpetually pending so the component stays in `'checking'`; the input must be disabled. Existing tests cover the `'unhealthy'` case; this fills the `'checking'` window where users are most likely to interact (slow backend) — pins the disabled condition `apiStatus.health !== 'healthy'` so a regression to `=== 'unhealthy'` is loud |
| `button is disabled while apiStatus.health is "checking" (initial render)` | Complementary pin for the submit button — same rationale as the input |

### apiUrl Fallback Default (added 2026-05-10 — regression-prevention)
| Test | Description |
|------|-------------|
| `every fetch URL has the expected base "http://localhost:8000" when NEXT_PUBLIC_API_URL is unset` | Verifies `process.env.NEXT_PUBLIC_API_URL` is unset in the test environment, then asserts every fetch URL begins with the literal fallback `http://localhost:8000/`. Without this test, a regression that drops/typos the `||` fallback would still pass every other test (mocks match by path) while silently breaking `npm run dev` |

---

## Backend Integration Tests (`backend/tests/test_integration.py`)

### `TestFullWorkflow`
| Test | Description |
|------|-------------|
| `test_full_page_load_sequence` | Simulates the frontend initialization sequence: GET /health → GET /api/version → GET /api/hello all succeed in order |
| `test_full_user_interaction_flow` | Full user session: page load init sequence followed by POST /api/hello with a name |
| `test_multiple_users_get_distinct_greetings` | Two POST /api/hello calls with different names return correctly personalized, distinct responses |
| `test_health_check_after_hello_calls` | /health remains 200 healthy after handling multiple /api/hello requests (checks no side effects) |

### `TestAPIContractHealth`
| Test | Description |
|------|-------------|
| `test_health_response_has_status_field` | /health response JSON contains a `status` key (frontend contract) |
| `test_health_status_field_is_string` | `status` is a string, not a boolean or number |
| `test_health_response_is_200` | /health returns HTTP 200 (frontend uses `response.ok`) |
| `test_health_response_has_timestamp` | /health response includes a non-empty `timestamp` string |

### `TestAPIContractVersion`
| Test | Description |
|------|-------------|
| `test_version_response_has_version_field` | /api/version response contains the `version` key read by the frontend |
| `test_version_field_is_non_empty_string` | `version` is a non-empty string suitable for display |
| `test_version_response_contains_extra_fields` | /api/version returns `name` and `environment` alongside `version` — extra fields do not displace the required one |
| `test_version_response_is_200` | /api/version returns HTTP 200 |

### `TestAPIContractHello`
| Test | Description |
|------|-------------|
| `test_get_hello_response_has_message_field` | GET /api/hello response contains the `message` key read by the frontend |
| `test_get_hello_message_is_non_empty_string` | GET hello `message` is a non-empty string |
| `test_post_hello_response_has_message_field` | POST /api/hello response contains the `message` key read by the frontend |
| `test_post_hello_message_is_non_empty_string` | POST hello `message` is a non-empty string |
| `test_post_hello_message_contains_submitted_name` | POST hello `message` includes the submitted name (frontend displays this verbatim) |
| `test_get_hello_response_has_timestamp` | GET /api/hello includes a `timestamp` field (observability; not displayed) |
| `test_post_hello_response_has_timestamp` | POST /api/hello includes a `timestamp` field (observability; not displayed) |

### `TestValidationErrorFormat`
| Test | Description |
|------|-------------|
| `test_missing_name_field_returns_422` | POST /api/hello without `name` returns HTTP 422 |
| `test_422_response_has_detail_key` | 422 response body has top-level `detail` key (FastAPI standard) |
| `test_422_detail_is_a_list` | `detail` is a non-empty list of error objects |
| `test_422_each_error_has_loc_msg_type` | Each error object has `loc`, `msg`, and `type` fields |
| `test_422_loc_points_to_name_field` | Validation error location includes `name` when the `name` field is missing |
| `test_invalid_json_body_returns_422` | Non-JSON body returns 422 (not 500) |
| `test_null_name_returns_422` | `name: null` returns 422 |
| `test_integer_name_returns_422` | `name: 42` returns 422 |

### `TestOpenAPISchemaContract`
| Test | Description |
|------|-------------|
| `test_openapi_documents_all_defined_routes` | Every defined route+method (GET /health, GET /api/version, GET+POST /api/hello) appears in /openapi.json paths — catches routes accidentally hidden via include_in_schema=False or missed by FastAPI introspection |
| `test_openapi_post_hello_request_body_requires_name_string` | OpenAPI POST /api/hello body schema marks `name` as required and declares its type as `string` — pins the contract consumed by frontend TypeScript types and SDK generators |
| `test_openapi_response_schema_matches_actual_response[health/version/hello_get/hello_post]` | OpenAPI 200-response schema fields equal the fields actually emitted by each handler — parametrized over all four endpoints. Catches drift in either direction (handler emits a field not in the model, or model declares a field the handler never emits). Refactored 2026-05-15 from four near-identical methods into one parametrized test that resolves `$ref` via the shared `openapi_component_for_response` helper |

### `TestCrossEndpointContract`
| Test | Description |
|------|-------------|
| `test_all_success_responses_are_json` | All four 200 responses (/health, /api/version, GET+POST /api/hello) emit Content-Type: application/json — catches a future endpoint that mistakenly returns a non-JSON content-type |
| `test_all_endpoint_timestamps_share_utc_iso8601_format` | Timestamps from /health, GET /api/hello, and POST /api/hello are all timezone-aware ISO 8601 with zero UTC offset — catches a future endpoint emitting a naive or non-UTC timestamp |
| `test_all_4xx_responses_have_detail_key` | 404 (unknown route), 405 (wrong method on /health and /api/hello), and 422 (missing/invalid name) all include a top-level `detail` key — catches a custom handler that bypasses FastAPI's error envelope |

### `TestFrontendInitSequenceCORS`
| Test | Description |
|------|-------------|
| `test_init_sequence_all_responses_carry_cors_for_localhost_3000` | All three init endpoints (/health, /api/version, /api/hello) return Access-Control-Allow-Origin: http://localhost:3000 when the request includes that Origin — catches CORS misconfiguration on any single init endpoint that would freeze the frontend on "Checking..." |
| `test_post_hello_response_carries_cors_for_localhost_3000` | POST /api/hello returns Access-Control-Allow-Origin for localhost:3000 — catches a regression where the form submission succeeds server-side but the browser blocks the response from JavaScript |

### `TestRegressionCORSAllowListBoundary` (added 2026-05-10 — regression-prevention)
| Test | Description |
|------|-------------|
| `test_get_does_not_expose_allow_origin_for_near_miss[https://localhost:3000-scheme flipped to https]` | HTTPS variant of the allowed origin does NOT receive `Access-Control-Allow-Origin` — pins origin equality as a tuple match, not a host-only or fuzzy match |
| `test_get_does_not_expose_allow_origin_for_near_miss[http://localhost:3001-port drifted to 3001]` | A port one digit away from the allow-listed `:3000` is NOT accepted — pins port-strictness in origin matching |
| `test_get_does_not_expose_allow_origin_for_near_miss[http://localhost-port omitted (defaults to 80)]` | An origin without an explicit port (defaults to 80, distinct from `:3000` per RFC 6454) is NOT accepted — guards against a regression that strips the port before comparison |

**Backend total:** 183 tests (128 unit + 41 integration + 14 performance), 100% coverage

---

## Slack Bot Tests (`services/slack-bot/__tests__/`)

### `message-router.test.ts`
Tests for `parseIntent()` function covering dispatch, status, help, and conversation intents with agent suggestion logic.

### `session-manager.test.ts`
Tests for `SessionManager` covering session creation, retrieval, message history, issue/PR linking, agent state, Claude history format, and statistics.

### `utils.test.ts`
Tests for `markdownToSlack` (bold, italic, code, links, headers, strikethrough, blockquotes), `slackToMarkdown`, and `rateLimiter` (check, reset, remaining tokens).

### `repo-status-manager.test.ts`
Tests for `RepositoryStatusManager` covering repo name extraction, emoji selection, status text generation, skip-update logic, and Slack API calls for setting/clearing status.

---

## Refactoring History

### 2026-05-10 — QA Agent: regression-prevention session (issue #191)
**Behavior-pin tests added (both suites already at 100% line/branch coverage; gap was uncovered observable contracts that could regress without any failing test):**

**Backend — five new classes across `test_main.py` and `test_integration.py` (17 tests):**

`TestRegressionOpenAPIRouteMetadata` (8 tests, two parametrized over four routes each) — Pins the per-operation OpenAPI metadata that downstream consumers silently depend on:
- `tags` — `["System"]` for `/health` and `/api/version`; `["Hello World"]` for both `/api/hello` methods. Tags drive the `/docs` UI grouping and SDK generators that filter operations by tag.
- `operationId` — auto-derived from handler function names (`health_check_health_get`, `get_version_api_version_get`, `hello_world_api_hello_get`, `hello_name_api_hello_post`). Generators like `openapi-typescript` and `swagger-codegen` use them as method names; a function rename therefore silently changes the public SDK surface.

`TestRegressionFastAPIDescription` (1 test) — Pins `info.description` to exactly `"Backend API powered by Claude Software Factory"`. `TestRegressionMessageFormat` already pinned `info.title` and `info.version`; this fills the third member of the public `info` block.

`TestRegressionDocumentationURLs` (2 tests) — Pins that Swagger UI is at exactly `/docs` (not `/documentation` or `/api/docs`) and ReDoc is at exactly `/redoc` (not `/api/redoc`). `TestOpenAPIDocumentation` only verified the canonical paths return 200, not that nothing else does.

`TestRegressionCORSPreflightContents` (3 tests) — Pins the CORS preflight payload that `TestCORSMiddleware` and `TestCORSCacheCorrectness` did not cover: `Access-Control-Allow-Methods` includes both `POST` and `GET` (driven by `allow_methods=["*"]`), and `Access-Control-Max-Age` is a positive integer (Starlette default 600s). Without these, a tightening of `allow_methods` or a drop of `max-age` would silently regress browser-side behavior with no failing test.

`TestRegressionCORSAllowListBoundary` (3 parametrized tests, in `test_integration.py`) — Pins that three realistic near-miss origins are NOT accepted: `https://localhost:3000` (scheme flipped), `http://localhost:3001` (port drifted), `http://localhost` (port omitted). Existing tests covered the allowed boundary and one obviously-wrong origin (`evil.example.com`); these guard against a relaxation of origin matching to a fuzzy/prefix/host-only comparison.

**Frontend — three new describe blocks in `frontend/__tests__/page.test.tsx` (5 tests):**

`regression-prevention: POST request shape` (2 tests) — Pins the `Content-Type: application/json` header (existing tests pinned the body shape but not the header) and asserts the request `method` is positively the uppercase string `'POST'` (existing tests filter on `opts.method === 'POST'`, which would silently match nothing if a regression lowercased the method).

`regression-prevention: pre-healthy form state` (2 tests) — Pins that both the input and submit button are disabled while `apiStatus.health === 'checking'` (initial render, fetch perpetually pending). Existing tests covered the `'unhealthy'` case; this fills the more user-facing `'checking'` window. The disabled condition is `apiStatus.health !== 'healthy'`, which must remain truthy for both states — a regression to `=== 'unhealthy'` is the kind of bug this catches.

`regression-prevention: apiUrl fallback default` (1 test) — Asserts that every fetch URL begins with the literal fallback `http://localhost:8000/` (after first verifying `process.env.NEXT_PUBLIC_API_URL` is undefined in the test environment). Without this test, a regression that drops or typos the `|| 'http://localhost:8000'` fallback would still pass every other test (mocks match by path) while silently breaking `npm run dev`.

**Coverage change:** 100% → 100% (maintained); backend 166 tests → 183 tests; frontend 70 tests → 75 tests. Each new test verified to pass 3× consecutively with no flakiness.

### 2026-05-09 — QA Agent: edge-cases session (issue #188)
**Behavioral edge-case coverage added (both suites already at 100% line/branch; gap was behavioral contract, not coverage):**

**Backend — seven new classes in `backend/tests/test_main.py` (22 tests):**

`TestHelloNameTypeValidation` (6 tests, parametrized) — Pins the strict-string contract for the JSON value categories not covered by the existing null/int tests: `bool` (both true/false), `float`, JSON array, JSON object, plus a top-level array body. Each must be rejected with 422; a future change that loosens the type to `str | int | float` would silently start coercing values.

`TestHelloNameSpecialCharacters` (5 tests, parametrized) — Pins verbatim echo for character classes that routinely break naive string handling: tab `\t`, bare CR `\r`, embedded NUL `\x00`, astral-plane (4-byte UTF-8) `𝓐`, and decomposed combining accents (`a` + U+0301). Catches a regression that introduces stripping, normalization, or NUL-truncation.

`TestPathRouting` (6 tests, including 4 parametrized) — Pins case-sensitive routing (`/Health` → 404), trailing-slash convenience (`/health/` → 200), and that GET handlers ignore query strings (`?name=Alice` doesn't leak into the generic greeting). All three are part of the public URL contract.

`TestHTTPMethodEdgeCases` (4 tests) — Fills the gaps left by `TestHTTPMethodNotAllowed` (DELETE/PUT/PATCH) and `TestHEADMethod`: TRACE → 405, bare OPTIONS → 405, OPTIONS-with-Origin-but-no-request-method → 405, and POST with `Content-Length: 0` → 422 (distinct from invalid-JSON).

`TestCORSCacheCorrectness` (4 tests) — Pins the cache-correctness contract for the CORS middleware: allowed-origin GET and preflight both include `Vary: Origin` (so caches don't serve responses across origins), disallowed origin does NOT add Vary (negative case), and `Access-Control-Allow-Credentials: true` accompanies the Allow-Origin header.

`TestErrorResponseShape` (2 tests) — Pins that 404/405 detail is a string ("Not Found"/"Method Not Allowed"), not the list-of-objects shape used for 422. Generic clients that `str()` the value depend on this distinction.

`TestExactGreetingFormat` (4 tests) — Pins the EXACT greeting string for empty, whitespace, tab, and duplicate-key inputs. Existing tests check the substring is present; these lock the full template so a regression that adds trimming, collapsing, or fallbacks fails loudly. Duplicate-key test pins last-wins parser behavior.

**Frontend — four new describe blocks in `frontend/__tests__/page.test.tsx` (9 tests):**

`whitespace-only submit edge cases` (3 tests, parametrized) — The existing "no submit on whitespace" test only covers space-only. These cover tab-only, newline-only, and mixed whitespace — all of which satisfy `String.prototype.trim()` and so must short-circuit `handleSubmit`.

`non-BMP greeting rendering` (2 tests) — Mathematical script capital A (U+1D4D0, a JS surrogate pair) and emoji greetings render as single text nodes. The backend echoes 4-byte UTF-8 verbatim; the frontend must render it without splitting or escaping.

`form attribute regression guards` (3 tests) — Pin `<input type="text">`, `<button type="submit">`, and the structural relationship (button inside same `<form>` as input). The existing "submits on Enter" test passes only because of these attributes; a regression that flips them is silent without explicit pinning.

`backend error response handling` (1 test) — When `res.json()` rejects (e.g., backend returned HTML), the `finally` block still clears `loading` and the button reverts from "Sending..." to "Say Hello". Guards against a missing `finally` leaving the button stuck forever.

**Coverage change:** 100% → 100% (maintained); backend 144 tests → 166 tests; frontend 61 tests → 70 tests. Each new test verified to pass 3× consecutively with no flakiness.

### 2026-05-08 — QA Agent: test-refactoring session (issue #185)
**Backend test-suite refactor (no behavior change; both suites stay at 100% coverage):**

- **`conftest.py`** — Added `LOCALHOST_ORIGIN` constant (`"http://localhost:3000"`) and `assert_utc_iso8601(timestamp)` helper. The helper checks both timezone-awareness and zero UTC offset in one call, replacing 4 inline open-coded variants of the same check across `test_main.py`.
- **`test_main.py`** — Hoisted `from datetime import datetime` to module level (removed 5 inline imports inside individual test bodies). Replaced `"http://localhost:3000"` magic strings in CORS tests with the new constant.
- **`TestRegressionUTCTimestamps`** (4 tests → 1 parametrized over 3 cases): Two `/health`-only sub-tests (`test_health_timestamp_is_timezone_aware`, `test_health_timestamp_utc_offset_is_zero`) checked one half each of the same invariant. The new helper checks both invariants in one call, so the cases are covered by a single parametrized `test_response_timestamp_is_utc_iso8601` over `(GET /health, GET /api/hello, POST /api/hello)`.
- **`TestHTTPMethodNotAllowed` + `TestPATCHMethodNotAllowed`** (5 + 3 tests → 1 parametrized over 8 cases): Two classes with identical 405 assertions per (method, path) tuple merged into a single parametrized `test_unsupported_method_returns_405` covering DELETE/PUT/PATCH against every defined route.
- **`TestHEADMethod`** (3 of 4 tests → 1 parametrized over 3 paths): The three "HEAD on a path returns 405" tests collapse to a single parametrized `test_head_returns_405`. The distinct `test_head_health_response_has_no_body` (different assertion) is kept.
- **`TestTimestampOrdering`** (2 tests → 1 parametrized over 2 cases): `test_health_timestamps_are_non_decreasing` and `test_hello_get_timestamps_are_non_decreasing` had identical bodies modulo path; merged into parametrized `test_successive_timestamps_are_non_decreasing`.
- **`test_performance.py` `TestSingleCallLatency`** (4 tests → 1 parametrized over 4 cases): All four "GET/POST /path completes under 500ms" tests merged into parametrized `test_endpoint_responds_under_ceiling` over (method, path, body).

**Coverage change:** 100% → 100% (maintained); backend 136 tests → 135 tests (the one removed case was a redundant `/health` tzinfo check whose assertion is fully subsumed by the new helper-based parametrized case). Each refactored test verified to pass 3× consecutively with no flakiness.

### 2026-05-07 — QA Agent: e2e-performance session (issue #182)
**Performance regression coverage added (both suites already at 100% line/branch; gap was performance, not coverage):**

**Backend — new `backend/tests/test_performance.py` (5 classes, 14 tests):**

`TestSingleCallLatency` (4 tests) — Each endpoint must respond well under 500ms. Bound is ~100× typical observed latency (~5ms), generous to avoid noise but tight enough to catch real regressions like a sync sleep accidentally added to a handler.

`TestInitSequenceLatency` (2 tests) — The full frontend init sequence (health → version → hello GET) finishes under 500ms; sequence + first POST under 1s. Pins the user's first-interaction budget.

`TestSustainedSequentialLoad` (3 tests) — 100 sequential /health calls under 2s; per-call latency drift across 50 sequential calls bounded; each of 30 sequential POSTs under 100ms. Catches state accumulation, leaks, and per-call slowdowns.

`TestConcurrentThroughput` (3 tests) — 50 concurrent /health under 1s; 30 concurrent POSTs return distinct names (no cross-contamination); concurrent never slower than 2× sequential — the last bound catches the case where a synchronous lock accidentally serialises the event loop.

`TestLargePayloadPerformance` (2 tests) — 1KB POST under 500ms; 10KB POST under 1s. Catches O(n²) regressions in JSON serialization or model validation.

**Frontend — new `fetch efficiency (e2e-performance)` describe block in `frontend/__tests__/page.test.tsx` (8 tests):**

- Exactly 3 fetches on mount (regression guard for the init useEffect)
- No re-fetch on `rerender()` with the same props (deps-array regression guard)
- Exactly one POST per submit click; rapid double-clicks during in-flight submit do not multiply POSTs (loading-disabled contract)
- No fetch when name is empty/whitespace-only (`!name.trim()` guard)
- Init "Connected" reaches DOM in <1s (otherwise every other test pays a 1s waitFor tax)
- Loading state clears after submit (missing-finally regression guard)
- All fetch URLs begin with `http(s)://` and contain neither "undefined" nor "null" (env-var malformation guard)

**Coverage change:** 100% → 100% (maintained); backend 122 tests → 136 tests; frontend 53 tests → 61 tests. Each new test verified to pass 3× consecutively with no flakiness.

### 2026-05-06 — QA Agent: integration-gaps session (issue #179)
**Contract-level integration tests added (both backend and frontend at 100% coverage; this session targets API-wide contracts not previously validated):**

**Backend — three new classes in `backend/tests/test_integration.py` (11 tests):**

`TestOpenAPISchemaContract` (6 tests) — Catches drift between the OpenAPI schema and the actual response shapes. Without these, a field added/removed on either side silently desynchronises code generators, the `/docs` UI, and external SDKs:
- `test_openapi_documents_all_defined_routes`: All four defined route+method combinations appear in /openapi.json
- `test_openapi_post_hello_request_body_requires_name_string`: POST body schema pins `name` as required/string (frontend type + SDK contract)
- `test_openapi_{health,version,get_hello,post_hello}_response_schema_matches_actual_response` (4 tests): For each endpoint, the OpenAPI component fields equal the actual response fields — catches drift in either direction

`TestCrossEndpointContract` (3 tests) — Treats the API as a single contract; per-endpoint tests would not catch a new endpoint added without the conventions:
- `test_all_success_responses_are_json`: All four 200 responses emit `application/json`
- `test_all_endpoint_timestamps_share_utc_iso8601_format`: Timestamps from /health, GET /api/hello, POST /api/hello are all UTC ISO-8601 (timezone-aware, zero offset)
- `test_all_4xx_responses_have_detail_key`: 404/405/422 responses across endpoints all include `detail`

`TestFrontendInitSequenceCORS` (2 tests) — Combines the multi-call init flow with the real-browser Origin header (existing CORS tests check one endpoint at a time, existing workflow tests omit Origin):
- `test_init_sequence_all_responses_carry_cors_for_localhost_3000`: All three init endpoints return `Access-Control-Allow-Origin: http://localhost:3000` — a single missing header would freeze the frontend on "Checking..."
- `test_post_hello_response_carries_cors_for_localhost_3000`: POST response also carries the CORS header — catches a regression where submission succeeds server-side but the browser blocks the response

**Coverage change:** 100% → 100% (maintained); backend 111 tests → 122 tests; frontend 53 tests (unchanged)

### 2026-05-05 — QA Agent: flaky-hunt session (issue #176)
**No flaky tests found across 10 runs (5 default order + 5 randomized seed). Suite is stable. New hardening tests added for latent flakiness risks:**

**Backend — new `TestLargeScaleConcurrency` class + extended `TestTimestampOrdering` (3 tests):**

`TestLargeScaleConcurrency` (2 async tests):
- `test_20_concurrent_health_requests_all_return_200`: 20 simultaneous GET /health requests all return 200. Amplifies any resource exhaustion or scheduling non-determinism invisible at the 3-request scale used by existing concurrent tests.
- `test_20_concurrent_hello_posts_have_no_name_crosscontamination`: 20 concurrent POST /api/hello calls each receive only their own name with no cross-contamination. At this scale, any global mutable state causing response leakage becomes far more likely to trigger than at 3 requests.

`TestTimestampOrdering` (1 new test):
- `test_health_timestamps_monotone_across_10_sequential_calls`: 10 sequential /health calls produce a non-decreasing timestamp sequence. Extends the existing 2-call ordering test to catch cached or coarsely-rounded timestamp implementations that the 2-call test might miss.

**Frontend — new `test isolation guardrail` describe block + 1 edge case test (2 tests):**
- `fetch mock has no prior calls before this test begins`: Verifies `jest.clearAllMocks()` in the outer `beforeEach` resets mock call history before every test. If this ever fails, other mock-count assertions will produce misleading results silently.
- `unmounts cleanly before fetch resolves without React state update warnings`: Mounts the component with perpetually-pending fetches, then unmounts immediately. Verifies no `useEffect` state updates fire on an unmounted instance (which would log React warnings and could cause test pollution).

**Coverage change:** 100% → 100% (maintained); backend 108 tests → 111 tests; frontend 51 tests → 53 tests

### 2026-05-04 — QA Agent: coverage-sprint session (issue #172)
**Security and contract tests added (both backend and frontend at 100% coverage; this session adds behavioral confidence for adversarial inputs and security-relevant properties):**

**Backend — two new classes in `backend/tests/test_main.py` (6 tests):**

`TestSecurityInputs` (4 tests):
- `test_sql_injection_in_name_returned_verbatim`: SQL injection string `'; DROP TABLE users; --` is echoed back in JSON unchanged — documents the echo contract and confirms no unintended sanitisation
- `test_emoji_in_name_round_trips_correctly`: Emoji (🎉🤖) in name are correctly serialised/deserialised through JSON; catches encoding regressions
- `test_rtl_unicode_in_name_round_trips_correctly`: Arabic right-to-left text returned correctly; guards against codec issues in HTTP body handling
- `test_zero_width_chars_in_name_returned_verbatim`: Zero-width Unicode characters (U+200B, U+200C) echo verbatim; edge case for invisible characters that could cause display discrepancies

`TestContentTypeNegotiation` (2 tests):
- `test_post_hello_with_form_encoded_body_returns_422`: `application/x-www-form-urlencoded` body returns 422 — FastAPI only parses JSON; documents the API is JSON-only
- `test_post_hello_with_text_plain_body_returns_422`: `text/plain` body returns 422 for the same reason

**Frontend — new `security` describe block in `frontend/__tests__/page.test.tsx` (2 tests):**
- `renders XSS payload in greeting as escaped text, not as a DOM script element`: If the backend returns a message containing `<script>alert('xss')</script>`, React's JSX renders it as an escaped text node inside a `<p>` element — verifies the element tagName is `P`, not `SCRIPT`
- `external links have rel="noopener noreferrer" to prevent tab-nabbing`: All `target="_blank"` anchor elements must have both `noopener` and `noreferrer` in their `rel` attribute to prevent the opener from navigating the parent tab

**Coverage change:** 100% → 100% (maintained); backend 102 tests → 108 tests; frontend 49 tests → 51 tests

### 2026-05-03 — QA Agent: regression-prevention session (issue #168)
**Regression-prevention tests added (both backend and frontend at 100% coverage; this session pins exact content that existing tests only check at substring/presence level):**

**Backend — new `TestRegressionMessageFormat` class in `backend/tests/test_main.py` (5 tests):**
- `test_get_hello_exact_message`: Pins the exact GET /api/hello message "Hello, World! Welcome to your Software Factory." — existing test only checks `"Hello" in message` and `"World" in message`
- `test_post_hello_exact_message_format`: Pins the exact POST /api/hello template "Hello, {name}! Welcome to your Software Factory." — existing test only checks name is present in message
- `test_version_environment_is_development`: Pins the environment value to "development" — existing test only checks the field exists (not its value)
- `test_openapi_title_is_software_factory_api`: Pins the OpenAPI title "Software Factory API" — no prior test verified this
- `test_openapi_version_matches_app_version`: Verifies OpenAPI version == `__version__` — no prior test verified the FastAPI `version=__version__` wiring

**Frontend — new `regression-prevention` describe block in `frontend/__tests__/page.test.tsx` (3 tests):**
- `fetches from the correct full URLs on mount`: Verifies the three init fetches use `/health`, `/api/version`, `/api/hello` paths — existing tests rely on mock matching these paths but never assert the URLs explicitly
- `POST /api/hello is called with the correct full URL`: Verifies the submit handler POSTs to the correct URL — catches a copy-paste typo in the POST URL
- `every fetch on mount uses the same base URL (no mixed origins)`: Verifies all mount-time fetches start with `http://localhost:8000/` — guards against one call accidentally using a different host

**Coverage change:** 100% → 100% (maintained); backend 97 tests → 102 tests; frontend 46 tests → 49 tests

### 2026-05-02 — QA Agent: edge-cases session (issue #165)
**Edge case tests added (coverage maintained at 100%; tests improve behavioral confidence in untested scenarios):**

**Backend — new test classes in `backend/tests/test_main.py` (12 tests):**
- `TestPATCHMethodNotAllowed`: 3 tests verifying PATCH returns 405 on /health, /api/version, and /api/hello (completes method coverage alongside existing DELETE/PUT tests)
- `TestNotFoundRoutes`: 3 tests verifying unknown routes return 404 with a JSON body containing a `detail` key
- `TestCORSDisallowedOrigin`: 2 tests verifying that GET requests and OPTIONS preflights from origins NOT in the allowlist do NOT receive the Access-Control-Allow-Origin header (security boundary)
- `TestHEADMethod`: 4 tests documenting that Starlette 1.0 returns 405 for HEAD on GET-only routes (no auto-HEAD support); also verifies HEAD responses have no body per HTTP semantics

**Frontend — new describe blocks in `frontend/__tests__/page.test.tsx` (8 tests):**
- `mid-sequence API failure edge cases`: 2 tests — version fetch fails after health OK (catch block exercised mid-sequence), hello GET fails after health+version OK (third init call failing)
- `form state edge cases`: 4 tests — input retains value after success, input retains value after error, second submission replaces first greeting, error replaced by successful retry
- `version badge edge cases`: 2 tests — version badge absent when version field missing from response (undefined is falsy), version badge absent when version is empty string (also falsy)

**Coverage change:** 100% → 100% (maintained); backend 85 tests → 97 tests; frontend 38 tests → 46 tests

### 2026-04-29 — QA Agent: integration-gaps session (issue #156)
**Integration gap tests added (both backend and frontend at 100% unit coverage; this session adds integration layer):**

**Bug fixed:**
- `frontend/src/app/page.tsx`: POST handler now checks `res.ok` before reading `data.message`. Previously, HTTP 422/500 responses would silently set greeting to `undefined`.

**Backend — new file `backend/tests/test_integration.py` (27 tests):**
- `TestFullWorkflow`: 4 tests simulating the frontend's full page-load and user-interaction API call sequences
- `TestAPIContractHealth`: 4 tests verifying /health returns HTTP 200 with `status` (string) and `timestamp` fields
- `TestAPIContractVersion`: 4 tests verifying /api/version returns HTTP 200 with `version` (non-empty string)
- `TestAPIContractHello`: 7 tests verifying GET and POST /api/hello return `message` (non-empty string) containing submitted name
- `TestValidationErrorFormat`: 8 tests verifying FastAPI's 422 response has `detail` list with `loc`/`msg`/`type` per error

**Frontend — `TestAPIContractIntegration` describe block (5 tests):**
- HTTP 422 from POST shows error message (validates `res.ok` bug fix)
- HTTP 500 from POST shows error message
- Frontend reads only `version` from version response (ignores `name`/`environment`)
- Frontend reads only `message` from hello response (ignores `timestamp`)
- Frontend handles extra unknown fields in API responses gracefully (forward compatibility)

**Coverage change:** 100% → 100% (maintained); backend 58 tests → 85 tests; frontend 33 tests → 38 tests

### 2026-04-28 — QA Agent: flaky-hunt session (issue #153)
**Flakiness prevention tests added (no flaky tests found; suite stable across 5 runs):**

**Backend (53 → 58 tests):**
- `TestTimestampOrdering`: 3 tests verifying timestamps are non-decreasing across successive calls and that POST timestamps fall within the request window. Catches accidental caching of timestamps or clock drift.
- `TestRequestIsolation`: 2 tests — one verifying sequential POSTs with different names return independent responses, one verifying three concurrent async POSTs don't cross-contaminate each other's messages.

**Frontend (29 → 33 tests):**
- `flakiness prevention` describe block: 4 tests — fetch call order on mount (health→version→hello), loading state clears after success, button disabled during in-flight POST to prevent double-submit, and loading state clears after failed POST.

**Coverage change:** 100% → 100% (maintained; backend 53 tests → 58 tests; frontend 29 tests → 33 tests)

### 2026-04-27 — QA Agent: coverage-sprint session (issue #149)
**Behavioral gap tests added (coverage already at 100%; tests improve behavioral confidence):**

**Backend:**
- `TestCORSMiddleware`: 4 tests verifying CORS middleware is wired up correctly — OPTIONS preflight returns 200, GET with allowed Origin returns `Access-Control-Allow-Origin` header for both localhost:3000 and 127.0.0.1:3000, POST method allowed in preflight.
- `TestHTTPMethodNotAllowed`: 5 tests verifying unsupported methods (DELETE, PUT) return 405 on /health, /api/version, and /api/hello.

**Frontend:**
- "Backend says:" prefix rendered when API is healthy (verifies the ternary in the JSX `apiMessage` paragraph)
- "Backend says:" prefix absent when API is unhealthy
- Enter-key (form submit event) triggers POST /api/hello and renders greeting
- POST body contains correct `{"name": "..."}` JSON (verifies `JSON.stringify({name})` in handleSubmit)

**Coverage change:** 100% → 100% (maintained; backend 44 tests → 53 tests; frontend 25 tests → 29 tests)

### 2026-04-26 — QA Agent: regression-prevention session (issue #145)
**Regression tests added targeting three recent bug fixes in commit eab5c18:**

- `TestRegressionAsyncClient`: 5 tests using the `async_client` fixture from conftest.py, which had its return type corrected but was never exercised by any test. Now catches regressions in both fixture setup and async endpoint behaviour, including concurrent request handling.
- `TestRegressionUTCTimestamps`: 4 tests verifying that all timestamp fields returned by the API are timezone-aware datetimes with a UTC offset of exactly zero. Prevents regression of the `datetime.UTC` alias fix (previously used `timezone.utc`).
- `TestRegressionPackageStructure`: 3 tests verifying the `app` package is importable, `__version__` is a non-empty string, and `app.main` exposes a FastAPI instance. Prevents regression of the hatch build config fix that added `packages = ["app"]`.

**Coverage change:** 100% → 100% (maintained; 32 tests → 44 tests)

### 2026-04-25 — QA Agent: edge-cases session (issue #142)
**Backend edge cases added:**
- `TestHelloNameEdgeCases`: 10 tests covering empty string, whitespace-only, very long name (1000 chars), newlines, HTML characters, extra fields ignored, null/integer name rejection, and Content-Type validation
- `TestHealthEdgeCases`: 3 tests covering Content-Type, status field type, and exact response field set
- `TestVersionEdgeCases`: 4 tests covering Content-Type, field types, exact field set, and semver format

**Frontend edge cases added (closed 2 missing branches):**
- Non-ok health response triggers unhealthy state (line 30 branch)
- Empty name form submit triggers early return without POST (line 58 branch)
- Whitespace-only name also triggers early return
- "Checking..." initial state before API resolves
- "Sending..." loading state during form submission
- View Source card render test

**Coverage change:** Backend 100% (unchanged, +17 tests); Frontend 90.47% → 100% branches (all metrics now 100%)

### 2026-04-24 — QA Agent: test-refactoring session (issue #139)
**Backend refactoring:**
- Combined single-assertion micro-tests into cohesive tests per behavior
- Added `pytest.mark.parametrize` for hello name test covering ASCII, special characters, and Unicode inputs
- Added ISO 8601 timestamp validation test with `datetime.fromisoformat`

**Frontend refactoring:**
- Extracted repeated `mockFetch({...})` setup into a `HEALTHY_RESPONSES` constant and `beforeEach` hooks per `describe` block
- Added missing test for POST /api/hello network failure error path (covers `page.tsx:70`)
- Frontend line coverage: 96.66% → 100%

### 2026-05-11 — QA Agent: coverage-sprint session (issue #195)

**Coverage gap closed:** `frontend/src/app/layout.tsx` was previously excluded from coverage via `!src/**/layout.tsx` in `jest.config.js`. It is now included and tested.

**Frontend — new `frontend/__tests__/layout.test.tsx` (8 tests):**

| Test | Description |
|------|-------------|
| `metadata export › has the exact title "Software Factory"` | Pins `metadata.title` — the value that renders in the browser tab. |
| `metadata export › has the exact description used by SEO/social embeds` | Pins `metadata.description` — the value used by SEO/social cards. |
| `RootLayout component › returns an <html> root element` | Verifies layout returns a React element with `type === 'html'`. |
| `RootLayout component › sets lang="en" on the <html> element` | Pins the `lang` attribute for accessibility/SEO. |
| `RootLayout component › wraps children inside a <body> element` | Verifies the html → body structural contract. |
| `RootLayout component › passes children through into <body> unchanged` | Asserts referential identity — children are not cloned, wrapped, or re-keyed. |
| `RootLayout component › renders <body> as the only direct child of <html>` | Pins single-child structure (no sibling head/script/style nodes inserted at the layout level). |
| `RootLayout component › is exported as the default export and is callable` | Pins the default-export contract so layout cannot accidentally become a non-function export. |

**Test design choice:** RootLayout is tested as a pure function call (inspecting the returned React element tree) rather than via `@testing-library/react.render()`. This avoids the jsdom warning about nested `<html>` tags and keeps the assertions focused on the component's structural contract rather than DOM rendering side-effects.

**Coverage change:** Frontend coverage now reports `layout.tsx` at 100% (previously excluded — effectively 0% safety net). All files: 100% statements / branches / functions / lines. Test count: 75 → 83.

### 2026-05-12 — QA Agent: flaky-hunt session (issue #199)

**Flakiness root cause identified.** Running `npx jest` emitted **47 React `act()` warnings** to stderr — all originating from `frontend/__tests__/page.test.tsx`. ~14 "renders X" tests mounted `Home`, asserted synchronously, and returned before the init `useEffect` settled. The `setApiStatus` call (page.tsx:40) then fired on the microtask queue *outside* any `act()` scope, meaning the state update was free to leak into the next test's render depending on microtask scheduling. The suite passed 5/5 today but was sitting on the edge of non-determinism — Jest test-ordering changes, RTL version upgrades, or stricter React `act()` enforcement could turn the warnings into intermittent failures.

**Backend:** 5/5 runs clean, 183/183 stable. No backend flakes.

**Fix:**

1. **New regression guard** in `frontend/__tests__/page.test.tsx`: a top-level `beforeEach`/`afterEach` pair installs a `console.error` spy that captures any "not wrapped in act()" warning. The `afterEach` then flushes pending microtasks **outside** `act()` (via `setTimeout(_, 0)` — yields a macrotask boundary that drains the microtask queue) so leaked state updates emit their warnings *before* the assertion runs. Any captured warning fails the test with an actionable error message ("Use `await waitFor`, `await screen.findBy*`, or `await flushInitEffect()`"). Verified by intentionally removing the fix on one test — the guard fires correctly.

2. **New helper** `flushInitEffect()`: wraps `await Promise.resolve()` in `act(async () => {})` to flush the init `useEffect` chain inside the test's `act()` scope. One-line call sites for the synchronous render-and-assert pattern.

3. **Sync test fixes (13 tests):** converted each of the following to `async` and added `await flushInitEffect()` after the synchronous assertion. The assertion still observes the initial render — only the post-test cleanup is now inside `act()`:
   - `Home Page › initial render`: `renders the title`, `renders the subtitle`, `renders the API status section`, `renders the form`
   - `Home Page › edge cases`: `renders the View Source card`
   - `Home Page › info cards`: `renders Getting Started section`, `renders Claude Code card`, `renders API Docs card`
   - `Home Page › footer`: `renders footer with technology links`
   - `Home Page › security`: `external links have rel="noopener noreferrer" to prevent tab-nabbing`
   - `Home Page › form attribute regression guards`: `the name input has type="text"`, `the submit button has type="submit"`, `the form contains both the input and the submit button`

4. **One additional fix:** the `shows loading state during form submission` test resolved the post promise but didn't await the resulting state cleanup — the loading-cleared `setState` then fired after the test ended. Now awaits `screen.getByText('Hello, Alice!')` so the cleanup settles inside the test.

**Verification:** suite runs 5/5 clean (`npx jest --silent`), zero `act()` warnings (`grep -c "wrapped in act"` returns 0). Coverage maintained at 100% statements / branches / functions / lines. Test count unchanged at 83 — this session hardens existing tests rather than adding new ones.

**Why no flaky tests were "fixed" in the traditional sense:** none were intermittently failing today. But the act() warnings indicated 13 tests one microtask-ordering quirk away from flaking. The regression guard ensures future tests cannot reintroduce this class of bug silently.

### 2026-05-13 — QA Agent: integration-gaps session (issue #202)

**Coverage was already 100% backend / 100% frontend.** The focus for this run is *integration-level behaviour the existing tests do not yet pin*, not unreached lines. The existing tests verify each endpoint in isolation plus a few flow contracts; what was missing was cross-endpoint state isolation, idempotence, the OpenAPI-vs-actual error-body contract, and concurrent multi-endpoint behaviour.

**Tests added (21 new in `backend/tests/test_integration.py`, 183 → 203 in the suite):**

| Class | Test | Description |
|-------|------|-------------|
| `TestStatelessUserFlow` | `test_get_hello_unchanged_after_post_with_name` | After `POST /api/hello {name: "LeakProbe"}`, a subsequent `GET /api/hello` is byte-identical to the baseline GET — no state leak. |
| `TestStatelessUserFlow` | `test_post_does_not_leak_previous_post_name` | A POST with name `Bob` does not contain the earlier POSTed name `Alice` — handler state isolation across calls. |
| `TestStatelessUserFlow` | `test_health_response_status_unchanged_by_prior_traffic` | `/health.status` stays `"healthy"` after a mix of GET/POST/422 traffic — pin against accidental request-counted health logic. |
| `TestPostIdempotenceContract` | `test_repeated_post_same_name_returns_identical_message` | Five POSTs with the same name yield exactly one unique `message` value — endpoint is a pure function of input. |
| `TestPostIdempotenceContract` | `test_repeated_post_same_name_timestamps_differ_or_match_but_format_stable` | Across repeated POSTs, every emitted timestamp is a valid timezone-aware UTC ISO 8601 string. |
| `TestPostIdempotenceContract` | `test_get_hello_message_is_constant_across_calls` | Five `GET /api/hello` calls produce one unique `message` value. |
| `TestOpenAPI422SchemaMatchesActual422Body` | `test_post_hello_openapi_declares_422_response` | `/openapi.json` declares a `422` response for `POST /api/hello`. |
| `TestOpenAPI422SchemaMatchesActual422Body` | `test_422_body_top_level_matches_http_validation_error_schema` | The top-level keys of an actual 422 body equal the declared `HTTPValidationError.properties` set. |
| `TestOpenAPI422SchemaMatchesActual422Body` | `test_422_detail_item_has_required_validation_error_fields` | Every item in `detail` includes every field marked `required` by the `ValidationError` component. |
| `TestOpenAPI422SchemaMatchesActual422Body` | `test_422_detail_loc_is_list_per_documented_schema` | Each `detail[i].loc` is a list — the documented array type, not a joined string. |
| `TestAsyncConcurrentInitSequence` | `test_init_sequence_fired_concurrently_all_succeed` | `health + version + hello` fired concurrently via `asyncio.gather` all return 200. |
| `TestAsyncConcurrentInitSequence` | `test_init_sequence_fired_concurrently_each_returns_its_own_shape` | Each concurrent init response has the endpoint-specific fields and *not* fields of its siblings. |
| `TestMixedEndpointAsyncConcurrency` | `test_mixed_concurrent_endpoints_each_return_correct_shape` | Concurrent mixed `GET /health + GET /version + GET /hello + POST /hello` each return their own correct shape. |
| `TestMixedEndpointAsyncConcurrency` | `test_concurrent_posts_with_different_names_have_no_cross_contamination` | Ten concurrent POSTs with ten distinct names each receive their own name in their response. |
| `TestCrossEndpointTimestampOrderingInUserFlow` | `test_user_flow_timestamps_are_monotonic_across_endpoints` | Timestamps from `/health → GET /api/hello → POST /api/hello` are non-decreasing — catches a handler accidentally using a cached or naive clock. |
| `TestCrossEndpointTimestampOrderingInUserFlow` | `test_repeated_user_flow_timestamps_progress_forward` | Two passes of the user flow produce timestamps that move forward across passes. |
| `TestAPIRouteInventoryPin` | `test_openapi_paths_match_expected_route_inventory` | `/openapi.json` declares exactly the `{(GET, /health), (GET, /api/version), (GET, /api/hello), (POST, /api/hello)}` user-facing route set — any addition/removal must update this pin. |
| `TestAPIRouteInventoryPin` | `test_no_undeclared_route_returns_200` | Common candidate paths (`/`, `/api`, `/admin`, `/metrics`, `/debug`, …) do not return 200 — catches an accidental catch-all router. |
| `TestFullUserFlowRepeatability` | `test_full_flow_run_twice_returns_identical_shapes` | Running the full init+POST flow twice through one `TestClient` yields identical response *key sets* per endpoint. |
| `TestFullUserFlowRepeatability` | `test_full_flow_run_twice_status_codes_stable` | All status codes (including the 422 path) are identical across two flow passes. |

**Why these specifically.** The existing integration test file (`test_integration.py`) covers per-endpoint contract (`TestAPIContractHealth/Version/Hello`), the full sequential workflow (`TestFullWorkflow`), the validation-error response shape (`TestValidationErrorFormat`), the OpenAPI 200-response schemas (`TestOpenAPISchemaContract`), cross-endpoint shared conventions (`TestCrossEndpointContract`), and CORS for the init sequence. What was missing — and what this session adds — is:
- **Statelessness as an explicit contract** (a regression where a handler stored last-greeted state would have passed every existing test).
- **POST/GET idempotence pinning** (existing tests check single calls; nothing pins that two identical calls produce identical bodies).
- **The error-side of OpenAPI** (`TestOpenAPISchemaContract` only validated 200 schemas).
- **True asyncio concurrency across endpoints** (existing concurrent tests fire one endpoint N times; nothing mixes endpoints in one `gather`).
- **Cross-endpoint timestamp monotonicity inside one user flow** (existing tests check ordering inside one endpoint).
- **A pin on the entire route surface** (existing tests only assert known routes are present, not the *complete* set).
- **Two-pass flow stability** (every existing test runs against a fresh `TestClient`).

**Verification:** all 203 tests pass 3× in sequence with no flakiness. Backend coverage stays at 100% (36/36 statements).

---

## Friday 2026-05-15 — test-refactoring (no new tests; deduplication only)

This session reduced duplication in the existing 218-test backend suite without
changing test coverage or removing test cases. The four near-identical OpenAPI
schema-match methods were collapsed into one parametrized test (still four cases
via `@pytest.mark.parametrize` ids), and shared helpers were added to
`conftest.py` so format-parsing logic lives in one place.

### Helpers added to `backend/tests/conftest.py`

| Helper | Replaces |
|--------|----------|
| `name_from_greeting(message)` | Two inline `message.split("Hello, ", 1)[1].split("!", 1)[0]` chains in `test_performance.py` (`test_30_concurrent_posts_return_distinct_names`, `test_15_reads_and_15_writes_interleaved_under_ceiling`). |
| `openapi_component_for_response(schema, path, method, status="200")` | Five inline `ref.rsplit("/", 1)[-1]` + `schema["components"]["schemas"][name]` lookups across `TestOpenAPISchemaContract`. Resolves the `$ref` and returns the component dict in one call. |

### Refactor summary

| File | Change |
|------|--------|
| `tests/test_integration.py` | Moved 4 in-function `from datetime import datetime` imports to module top. |
| `tests/test_integration.py` | Replaced 3 inline UTC-offset parse blocks (`TestCrossEndpointContract.test_all_endpoint_timestamps_share_utc_iso8601_format`, `TestPostIdempotenceContract.test_repeated_post_same_name_timestamps_differ_or_match_but_format_stable`) with calls to the existing `assert_utc_iso8601` helper. |
| `tests/test_integration.py` | Collapsed `TestOpenAPISchemaContract`'s four `test_openapi_*_response_schema_matches_actual_response` methods into one parametrized `test_openapi_response_schema_matches_actual_response` test with `health`/`version`/`hello_get`/`hello_post` ids. Net test count unchanged (4 parametrized cases). |
| `tests/test_performance.py` | Two inline name-extraction chains use the new `name_from_greeting` helper. |

**Verification:** 218 backend tests + 83 frontend tests still pass, all 3× in sequence with no flakiness. Backend coverage stays at 100%.

---

## Saturday 2026-05-16 — edge-cases (behavioural pins, no coverage change)

This session adds **27 new tests** (21 backend, 6 frontend) that pin
behaviours the live server and the live UI exhibit today but that no
existing test asserted. Both surfaces sit at 100% line + branch coverage
already, so the lever here is *behaviour pinning*: a regression that
silently flipped any of these — for example, a middleware swap that
started accepting non-JSON Content-Types, a Starlette upgrade that
changed BOM handling, or a "defensive" refactor of the React init effect
that started validating the `/health` response body — would fail one of
these tests first instead of shipping to production.

### Backend — `backend/tests/test_edge_cases.py` (21 new tests)

| Suite | Test | Pins |
|-------|------|------|
| `TestTopLevelNonObjectBodyReturns422` | `test_top_level_null_body_returns_422` | Body literal `null` returns 422 — distinct from "name is null inside an object" (already pinned). |
| `TestTopLevelNonObjectBodyReturns422` | `test_top_level_boolean_body_returns_422` | Body literal `true` returns 422 (top-level scalar body rejected). |
| `TestTopLevelNonObjectBodyReturns422` | `test_top_level_number_body_returns_422` | Body literal `42` returns 422 (top-level scalar body rejected). |
| `TestTopLevelNonObjectBodyReturns422` | `test_top_level_string_body_returns_422` | Body literal `"Alice"` returns 422 — guards against silently treating a bare-string body as the name. |
| `TestRequestContentTypePermissiveness` | `test_content_type_with_charset_parameter_is_accepted` | `application/json; charset=utf-8` returns 200 — MIME parameters are tolerated per RFC 9110. |
| `TestRequestContentTypePermissiveness` | `test_content_type_mixed_case_is_accepted` | `Application/JSON` returns 200 — media-type comparison is case-insensitive. |
| `TestRequestContentTypeStrictness` | `test_post_without_content_type_header_returns_422` | POST with a body but no `Content-Type` header returns 422 — pins that the JSON branch requires a declared type. |
| `TestRequestContentTypeStrictness` | `test_post_with_application_xml_content_type_returns_422` | `application/xml` returns 422 — complement to `text/plain`/`form-encoded` (already pinned). |
| `TestJSONBodyParsingEdges` | `test_utf8_bom_prefix_on_body_is_accepted` | A leading UTF-8 BOM (`EF BB BF`) before the JSON object is tolerated (200). |
| `TestJSONBodyParsingEdges` | `test_trailing_whitespace_after_json_object_is_accepted` | Trailing ASCII whitespace after `}` is tolerated (200). |
| `TestJSONBodyParsingEdges` | `test_trailing_garbage_after_json_object_returns_422` | Non-whitespace bytes after `}` cause a 422 — strict about *content*, lenient about *whitespace*. |
| `TestPathRoutingEdges` | `test_double_slash_prefix_does_not_route_to_health` | `GET //health` returns 404 — the leading double slash is not collapsed. |
| `TestPathRoutingEdges` | `test_percent_encoded_path_segment_resolves_to_canonical_route` | `GET /he%61lth` returns 200 — Starlette percent-decodes path segments before routing. |
| `TestNameEchoBoundaries` | `test_single_character_name_echoed_verbatim` | A one-character name produces the exact greeting — pins no minimum-length validator. |
| `TestNameEchoBoundaries` | `test_fifty_thousand_character_name_round_trips_verbatim` | A 50K-character name is echoed verbatim with the exact length preserved (perf tests stop at 10K). |
| `TestNameEchoBoundaries` | `test_pure_whitespace_name_echoed_verbatim` | `"\t\r\n "` is echoed verbatim — the handler does not call `.strip()`. |
| `TestNameEchoBoundaries` | `test_ascii_bel_character_in_name_echoed_verbatim` | ASCII BEL (`\x07`) is echoed verbatim — no C0-control sanitisation. |
| `TestNameEchoBoundaries` | `test_unicode_noncharacter_in_name_echoed_verbatim` | U+FFFE noncharacter is echoed verbatim — no NFC normalisation on the request body. |
| `TestResponseContentTypePinned` | `test_health_response_content_type_is_exactly_application_json` | `/health` returns `Content-Type: application/json` (no charset parameter). |
| `TestResponseContentTypePinned` | `test_post_hello_response_content_type_is_exactly_application_json` | `POST /api/hello` returns `Content-Type: application/json` (no parameters). |
| `TestResponseContentTypePinned` | `test_version_response_content_type_is_exactly_application_json` | `/api/version` returns `Content-Type: application/json` (no parameters). |

### Frontend — `frontend/__tests__/page.test.tsx` (6 new tests)

| Suite | Test | Pins |
|-------|------|------|
| `edge cases: falsy greeting render guard` | `does not render greeting paragraph when POST returns an empty-string message` | The `{greeting && ...}` guard suppresses the paragraph for `message: ""` — no empty `<p>` rendered. |
| `edge cases: falsy greeting render guard` | `does not render greeting paragraph when POST returns message: null` | Same guard contract for `message: null`. |
| `edge cases: falsy greeting render guard` | `clears loading state when POST returns 200 with no message field` | The `finally` branch clears `loading` even when `data.message` is `undefined` — button is not stuck on "Sending...". |
| `edge cases: health-check body shape` | `flips to Connected when /health responds ok=true with no status field` | The init effect only reads `healthRes.ok`, never the body — guards against a "defensive" refactor that starts parsing `status`. |
| `edge cases: submit input boundaries` | `does not POST when name is a Unicode no-break space only` | `name.trim()` strips U+00A0 NBSP per ECMAScript — pins suppression for the Unicode-whitespace case (ASCII is already covered). |
| `edge cases: submit input boundaries` | `round-trips a 5000-character name through the form and renders it as the greeting` | The controlled input retains 5000 chars, the POST body carries them intact, and the greeting renders them verbatim — no client-side truncation. |

**Why these specifically.** The existing suites already cover the well-trodden edge cases (empty/whitespace names, common Unicode, SQL/XSS payloads, CORS preflight, 404/405, repeated submits). What was *unpinned* before this session — and what these tests fix — is:

- **Top-level body shape vs. per-field type.** Existing tests pinned wrong types for `name` *inside* the object; nothing rejected a bare `null`/`true`/`42`/`"Alice"` at the body root.
- **Request `Content-Type` permissiveness on the positive side.** Existing tests pinned that `text/plain` and `form-encoded` are rejected; the *lenient* behaviours (MIME parameters, mixed-case media type) were unpinned, so a stricter parser swap would silently break clients.
- **JSON-body framing edges.** Trailing whitespace tolerance, trailing-garbage rejection, and UTF-8 BOM tolerance were all unpinned — three independent regression vectors.
- **Routing edges.** `//health` 404 vs. percent-decoded `%61` 200 both depend on Starlette's resolver — any router-middleware swap could flip either.
- **Echo verbatim at boundaries.** Single-char, 50K-char, BEL, and U+FFFE all round-tripped verbatim today but were unpinned — sanitiser/normaliser middleware would silently strip them.
- **Response `Content-Type` shape.** No test asserted that the bare `application/json` (no `; charset=utf-8`) is what clients see — a `UJSONResponse` swap could silently change this.
- **Frontend render-guard for falsy greeting.** `{greeting && ...}` suppresses the paragraph for `''`/`null`; a regression to `{greeting !== undefined && ...}` would render an empty paragraph for these payloads.
- **Frontend health-body permissiveness.** The init effect never reads the `/health` body — a "defensive" refactor that starts validating `status === 'healthy'` would silently break the page against backends that return `{}`.
- **Frontend Unicode-whitespace `trim()` reliance.** ECMAScript `.trim()` strips U+00A0; a byte-only re-implementation would start POSTing NBSP-only submissions.
- **Frontend long-input round-trip.** Existing form tests use short names; a `maxLength` attribute or controlled-input truncation would pass every other test.

**Verification:** 239 backend tests (218 → 239) + 89 frontend tests (83 → 89) all pass, 3× in sequence with no flakiness. Backend coverage stays at 100% (36/36 statements + branches). Frontend coverage stays at 100% (layout.tsx + page.tsx).

---

## Sunday 2026-05-17 — regression-prevention (behavioural pins, no coverage change)

This session adds **29 new tests** (27 backend, 2 frontend) protecting
public-contract behaviours that existing tests don't pin. Both surfaces
already sit at 100% line + branch coverage (266 / 91 tests after this
session), so the lever continues to be *behaviour pinning* — a
regression that silently flips any of these would land green today.

### Backend — `backend/tests/test_regression_prevention.py` (new file, 27 tests)

| Suite | Test | Pins |
|-------|------|------|
| `TestOpenAPIURLIsCanonical` | `test_canonical_openapi_url_returns_200` | `/openapi.json` returns 200 — pins FastAPI's default `openapi_url` rather than relying on incidental coverage. |
| `TestOpenAPIURLIsCanonical` | `test_common_aliases_are_not_routed[/openapi]` | `/openapi` returns 404 — only the canonical URL serves the schema. |
| `TestOpenAPIURLIsCanonical` | `test_common_aliases_are_not_routed[/openapi.yaml]` | `/openapi.yaml` returns 404 — pins absence of a YAML alias. |
| `TestOpenAPIURLIsCanonical` | `test_common_aliases_are_not_routed[/swagger.json]` | `/swagger.json` returns 404 — pins absence of a Swagger alias. |
| `TestOpenAPIURLIsCanonical` | `test_common_aliases_are_not_routed[/api/openapi.json]` | `/api/openapi.json` returns 404 — pins the schema is not double-mounted under `/api`. |
| `TestOpenAPIURLIsCanonical` | `test_common_aliases_are_not_routed[/api-docs.json]` | `/api-docs.json` returns 404 — pins absence of a Swagger-codegen-style alias. |
| `TestOpenAPIComponentInventoryPinned` | `test_component_inventory_is_exactly_the_expected_set` | OpenAPI components are exactly `{HealthResponse, VersionResponse, HelloRequest, HelloResponse, HTTPValidationError, ValidationError}` — a Pydantic model rename would fail here before silently breaking every SDK generator's emitted type names. |
| `TestUnusedErrorResponseNotExposedInOpenAPI` | `test_error_response_class_is_still_importable` | `ErrorResponse` is importable from `app.main` and instantiable with the documented fields — the base symbol still exists. |
| `TestUnusedErrorResponseNotExposedInOpenAPI` | `test_error_response_is_not_in_openapi_components` | `ErrorResponse` is **not** in OpenAPI components — pins the model's currently-unused status so any future endpoint wiring it via `response_model=` becomes a visible test failure. |
| `TestNoCacheControlOnTimestampedEndpoints` | `test_response_has_no_cache_control_header[health]` | `/health` does not set `Cache-Control` — a cached response would freeze the embedded timestamp and break the DevOps agent's liveness signal. |
| `TestNoCacheControlOnTimestampedEndpoints` | `test_response_has_no_cache_control_header[version]` | `/api/version` does not set `Cache-Control`. |
| `TestNoCacheControlOnTimestampedEndpoints` | `test_response_has_no_cache_control_header[hello_get]` | `GET /api/hello` does not set `Cache-Control`. |
| `TestNoCacheControlOnTimestampedEndpoints` | `test_response_has_no_cache_control_header[hello_post]` | `POST /api/hello` does not set `Cache-Control`. |
| `TestNoCacheControlOnTimestampedEndpoints` | `test_response_has_no_etag_or_expires_header[health]` | `/health` does not set `ETag` / `Expires` — both imply cacheability of a freshly-stamped response. |
| `TestNoCacheControlOnTimestampedEndpoints` | `test_response_has_no_etag_or_expires_header[version]` | `/api/version` does not set `ETag` / `Expires`. |
| `TestNoCacheControlOnTimestampedEndpoints` | `test_response_has_no_etag_or_expires_header[hello_get]` | `GET /api/hello` does not set `ETag` / `Expires`. |
| `TestNoCacheControlOnTimestampedEndpoints` | `test_response_has_no_etag_or_expires_header[hello_post]` | `POST /api/hello` does not set `ETag` / `Expires`. |
| `TestCORSPreflightReflectsRequestedHeaders` | `test_preflight_reflects_custom_request_header_back` | A preflight with `Access-Control-Request-Headers: x-custom-header,content-type` mirrors both back in `Access-Control-Allow-Headers` — pins the `allow_headers=["*"]` config. |
| `TestCORSPreflightReflectsRequestedHeaders` | `test_preflight_reflects_auth_style_header` | A preflight with `Access-Control-Request-Headers: authorization` mirrors it back — pins that a future auth header lands without needing a CORS config change. |
| `TestEveryRouteUses200ResponseModelComponentRef` | `test_route_200_response_is_component_ref[get-/health]` | The 200 schema for `GET /health` is a `$ref` to a local component — pins that `response_model=HealthResponse` is still wired on the decorator. |
| `TestEveryRouteUses200ResponseModelComponentRef` | `test_route_200_response_is_component_ref[get-/api/version]` | Same pin for `GET /api/version`. |
| `TestEveryRouteUses200ResponseModelComponentRef` | `test_route_200_response_is_component_ref[get-/api/hello]` | Same pin for `GET /api/hello`. |
| `TestEveryRouteUses200ResponseModelComponentRef` | `test_route_200_response_is_component_ref[post-/api/hello]` | Same pin for `POST /api/hello`. |
| `TestHelloRequestNameHasNoConstraints` | `test_name_property_has_no_length_constraints` | `HelloRequest.name` has no `minLength` / `maxLength` — protects the empty-string and 50K-char contracts other tests deliberately exercise. |
| `TestHelloRequestNameHasNoConstraints` | `test_name_property_has_no_pattern_constraint` | `HelloRequest.name` has no `pattern` constraint and remains plain `string` — protects the verbatim-echo contract for adversarial / Unicode inputs. |
| `TestPostHello422IsHTTPValidationErrorRef` | `test_422_response_uses_http_validation_error_ref` | `POST /api/hello` 422 schema is exactly `{"$ref": "#/components/schemas/HTTPValidationError"}` — pins the canonical FastAPI 422 declaration so SDK 422-parsing stays stable. |
| `TestOpenAPISpecVersionPinned` | `test_openapi_field_is_3_1_family` | OpenAPI document's `openapi` field starts with `3.1.` — pins the OpenAPI spec family so a FastAPI upgrade that bumps the family is visible. |

### Frontend — `frontend/__tests__/page.test.tsx` (2 new tests in `regression-prevention: form submit preventDefault`)

| Test | Pins |
|------|------|
| `preventDefault is called on submit when name is populated` | A real `submit` event dispatched on the form returns with `defaultPrevented === true` — removing `e.preventDefault()` from `handleSubmit` would let the browser navigate away on submit (full-page reload, SPA state destroyed). Existing `fireEvent.click` tests would still pass because the click handler still fires; this test inspects the dispatched event directly. |
| `preventDefault is called on submit even when name is empty (no navigation)` | `defaultPrevented === true` even when the input is empty — pins the order of operations in `handleSubmit`: `e.preventDefault()` runs *before* the `if (!name.trim()) return` early-exit. A refactor that reordered the early-return above the `preventDefault` call would let empty submits reload the page. Also asserts no POST is issued, confirming the early-return path took effect. |

**Why these specifically.** Recent sessions have pinned the API and UI surface so densely (exact messages, OpenAPI metadata, CORS allow-list, content-type strictness, 422 schema shape, p95/p99 latency, frontend act() warnings, etc.) that the remaining regression vectors are subtle: SDK-generator-visible OpenAPI structure (component names, `$ref` vs inline, canonical schema URL), cacheability of timestamp-bearing responses, the open `allow_headers` config, the absence of Pydantic constraints on the echo field, and frontend-event-default behaviour that click-based tests don't observe. Each new test corresponds to a specific "regression that current tests would miss":

- **OpenAPI URL aliasing:** every test reads `/openapi.json` incidentally, so an `openapi_url=None` regression would surface confusingly across multiple unrelated tests; pinning the canonical URL (and the absence of common aliases) makes that failure mode loud and singular.
- **Component name renames:** SDK generators emit each Pydantic class name as a generated TypeScript / Python / Go type — silently changing them would break every downstream consumer.
- **Unused `ErrorResponse`:** the model is one `response_model=ErrorResponse` annotation away from becoming part of the public OpenAPI surface; pinning its absence today documents the design choice.
- **Caching dynamic responses:** any future "perf" middleware that added `Cache-Control: public, max-age=3600` would freeze `/health`'s timestamp and let stale liveness signals slip past DevOps monitoring; the pin keeps the negative contract visible.
- **CORS `allow_headers=["*"]`:** a "tighten the allow-list" change would silently break any frontend that adds a header (`Authorization`, `X-Trace-Id`); pinning the open behaviour means such a change requires explicit acknowledgement.
- **`response_model=` on every route:** an endpoint that forgets `response_model=` falls back to an "anything goes" schema; SDK generators emit `unknown` / `any` and silently lose type safety. The `$ref` check is the visible signal.
- **`HelloRequest.name` constraints:** several tests in the suite exercise empty strings, 50K-char strings, and adversarial Unicode — a `Field(min_length=1)` or `pattern=` regression would break all of them at once with confusing per-test failures. Pinning the absence here gives a single, named failure.
- **422 schema reference:** `TestOpenAPI422SchemaMatchesActual422Body` only pins that *some* 422 is declared and its body shape matches; it doesn't pin **how** the 422 is declared. A regression that inlined the schema or pointed it at a renamed component would slip past existing tests.
- **OpenAPI spec family:** 3.0.x vs 3.1.x differ materially in nullable / oneOf handling; pinning the major.minor lets patch bumps through while making family changes loud.
- **Frontend `preventDefault`:** every existing submit test fires `fireEvent.click(button)` and asserts on UI side-effects — none ever inspect the dispatched submit event's `defaultPrevented`. A regression that dropped `e.preventDefault()` from `handleSubmit` would still pass every click test (the click handler still fires) but would cause the browser to reload the page in real use.

**Verification:** 266 backend tests (239 → 266) + 91 frontend tests (89 → 91) all pass, 3× in sequence with no flakiness. Backend coverage stays at 100% (36/36 statements + branches). Frontend coverage stays at 100% (layout.tsx + page.tsx).

## Monday 2026-05-18 — coverage-sprint (behavioural pins; line coverage already at 100%)

The Monday focus is officially "pick the lowest-coverage file and raise it
by 15%+". Both surfaces already sit at the ceiling — `pytest --cov=app`
reports 100% statement + branch on `app/__init__.py` and `app/main.py`,
and `jest --coverage` reports 100% statements + branches + functions +
lines on `layout.tsx` and `page.tsx`. The literal goal is mathematically
unachievable, so this session pivots to the contract surface that
`--cov` cannot measure: FastAPI/Pydantic auto-derive substantial OpenAPI
metadata through metaprogramming (model docstrings → schema
descriptions, function names → operation summaries, model class names →
inner `title` fields, default `required: [...]` arrays). None of those
fields are pinned anywhere in the existing suite — verified by grepping
`tests/` for each candidate string — so a docstring rewrite or a
handler-function rename would ship green today even though every SDK
generator and the `/docs` UI sees the change.

### Backend — `backend/tests/test_openapi_schema_metadata.py` (new file, 26 tests)

| Suite | Test | Pins |
|-------|------|------|
| `TestOpenAPIInfoBlockInventory` | `test_info_block_keys_are_exactly_expected` | The `info` block exposes exactly `{title, version, description}` — a future `FastAPI(terms_of_service=...)` argument adding `info.termsOfService` would surface here before silently appearing in every generated SDK's documentation header. |
| `TestOpenAPIInfoBlockInventory` | `test_info_version_equals_app_dunder_version` | `info.version` equals `app.__version__` — pins the wiring (not just the literal) so a future split that hard-codes the version string into the FastAPI constructor fails loudly. |
| `TestComponentSchemaDescriptionsPinned` | `test_component_description_matches_model_docstring[HealthResponse-Health check response.]` | `HealthResponse` schema `description` matches its Pydantic docstring — pins that SDK-generated JSDoc/Python docstrings on the emitted type stay stable. |
| `TestComponentSchemaDescriptionsPinned` | `test_component_description_matches_model_docstring[VersionResponse-Version information response.]` | Same pin for `VersionResponse`. |
| `TestComponentSchemaDescriptionsPinned` | `test_component_description_matches_model_docstring[HelloRequest-Request model for personalized greeting.]` | Same pin for `HelloRequest` — input-side type doc comment stability. |
| `TestComponentSchemaDescriptionsPinned` | `test_component_description_matches_model_docstring[HelloResponse-Response model for greeting.]` | Same pin for `HelloResponse`. |
| `TestComponentSchemaTitlesPinned` | `test_component_inner_title_matches_class_name[HealthResponse-HealthResponse]` | `HealthResponse.title` (the inner field, distinct from the components-dict key) equals the class name — catches `model_config = {"title": "Greeting"}` overrides that would change the emitted SDK type name without altering the components-dict key. |
| `TestComponentSchemaTitlesPinned` | `test_component_inner_title_matches_class_name[VersionResponse-VersionResponse]` | Same pin for `VersionResponse`. |
| `TestComponentSchemaTitlesPinned` | `test_component_inner_title_matches_class_name[HelloRequest-HelloRequest]` | Same pin for `HelloRequest`. |
| `TestComponentSchemaTitlesPinned` | `test_component_inner_title_matches_class_name[HelloResponse-HelloResponse]` | Same pin for `HelloResponse`. |
| `TestComponentSchemaRequiredFieldsPinned` | `test_component_required_array_is_exact[HealthResponse-...]` | `HealthResponse.required` is exactly `{status, timestamp}` — a `timestamp: str = ""` default would silently drop `timestamp` from the required array while the cross-endpoint contract test in `TestOpenAPISchemaContract` still passes (the handler still emits the field). |
| `TestComponentSchemaRequiredFieldsPinned` | `test_component_required_array_is_exact[VersionResponse-...]` | `VersionResponse.required` is exactly `{version, name, environment}`. |
| `TestComponentSchemaRequiredFieldsPinned` | `test_component_required_array_is_exact[HelloRequest-...]` | `HelloRequest.required` is exactly `{name}` — catches an `Optional[str]` change that would flip the request field optional without rejecting empty-body POSTs (which is currently asserted elsewhere). |
| `TestComponentSchemaRequiredFieldsPinned` | `test_component_required_array_is_exact[HelloResponse-...]` | `HelloResponse.required` is exactly `{message, timestamp}`. |
| `TestComponentSchemaPropertyTitlesPinned` | `test_property_title_matches_pydantic_default[HealthResponse.status]` | The auto-derived property `title` for `HealthResponse.status` is `"Status"` (Pydantic's Title Case default). Catches a `Field(..., title="Operational Status")` override on the field. |
| `TestComponentSchemaPropertyTitlesPinned` | `test_property_title_matches_pydantic_default[HealthResponse.timestamp]` | Same pin for `HealthResponse.timestamp` → `"Timestamp"`. |
| `TestComponentSchemaPropertyTitlesPinned` | `test_property_title_matches_pydantic_default[VersionResponse.version]` | Same pin for `VersionResponse.version` → `"Version"`. |
| `TestComponentSchemaPropertyTitlesPinned` | `test_property_title_matches_pydantic_default[VersionResponse.name]` | Same pin for `VersionResponse.name` → `"Name"`. |
| `TestComponentSchemaPropertyTitlesPinned` | `test_property_title_matches_pydantic_default[VersionResponse.environment]` | Same pin for `VersionResponse.environment` → `"Environment"`. |
| `TestComponentSchemaPropertyTitlesPinned` | `test_property_title_matches_pydantic_default[HelloRequest.name]` | Same pin for `HelloRequest.name` → `"Name"`. |
| `TestComponentSchemaPropertyTitlesPinned` | `test_property_title_matches_pydantic_default[HelloResponse.message]` | Same pin for `HelloResponse.message` → `"Message"`. |
| `TestComponentSchemaPropertyTitlesPinned` | `test_property_title_matches_pydantic_default[HelloResponse.timestamp]` | Same pin for `HelloResponse.timestamp` → `"Timestamp"`. |
| `TestPathOperationSummariesPinned` | `test_operation_summary_matches_handler_name[GET /health]` | `GET /health` operation `summary` is `"Health Check"` (FastAPI's Title-Cased rendering of `health_check`). Catches a function rename even if an `operation_id=` decorator kwarg keeps `operationId` stable — every existing `operationId` test would still pass while the `/docs` UI header silently drifted. |
| `TestPathOperationSummariesPinned` | `test_operation_summary_matches_handler_name[GET /api/version]` | Same pin for `GET /api/version` → `"Get Version"`. |
| `TestPathOperationSummariesPinned` | `test_operation_summary_matches_handler_name[GET /api/hello]` | Same pin for `GET /api/hello` → `"Hello World"`. |
| `TestPathOperationSummariesPinned` | `test_operation_summary_matches_handler_name[POST /api/hello]` | Same pin for `POST /api/hello` → `"Hello Name"`. |

**Why these specifically.** Each new test corresponds to a regression vector that line coverage *cannot* detect because FastAPI/Pydantic emit the surface via metaprogramming — no Python statement in `app/main.py` produces these strings, so `pytest --cov` reports 100% even after the field is mutated.

- **`info` inventory:** title/version/description are individually pinned by `TestRegressionMessageFormat` and `TestRegressionFastAPIDescription`, but the **set of keys** is not. A future `FastAPI(terms_of_service=..., contact=...)` argument would expose new fields on every SDK doc header.
- **Component descriptions:** `TestOpenAPIComponentInventoryPinned` pins component names; `TestOpenAPISchemaContract` pins fields-vs-handler output; neither reads the schema `description`. SDK generators that emit JSDoc from this field (e.g. `openapi-typescript-codegen`) would silently churn.
- **Component inner `title`:** distinct from the components-dict key — Pydantic exposes both. A `model_config = {"title": "Greeting"}` override would leave the dict key stable while changing the emitted SDK type name.
- **`required: [...]` arrays:** an `Optional[str]` change drops the field from required without removing it from the response — the cross-endpoint match test still passes; consumers flip to optional and lose exhaustiveness checks.
- **Property `title` defaults:** any `Field(..., title=...)` override is invisible to every other test in the suite.
- **Operation summaries:** Pinned `operationId` encodes the function name *and* the path, but FastAPI users sometimes add `operation_id=` to stabilise the wire-level ID while renaming the handler for clarity. `operationId` stays green; `summary` (rendered as the `/docs` heading and used by some generators as the JSDoc title) drifts.

**Verification:** 292 backend tests (266 → 292) + 91 frontend tests pass, 3× in sequence with no flakiness (~3.0s per backend run). Backend coverage stays at 100% (36/36 statements + branches). Frontend coverage unchanged (this session adds no frontend tests — the existing 91 frontend tests already saturate the 100% target).

## Tuesday 2026-05-19 — flaky-hunt (behavioural pins, no coverage change)

**Goal.** Hunt for flaky tests and, finding none, pin the *sources* of stability so future regressions that would re-introduce flakiness fail loudly rather than appearing as intermittent CI failures weeks later.

**Method.**
1. Ran the full backend suite 5× back-to-back under `pytest-randomly` (different seed per run). All 292 tests passed every time, ~1.7s per run.
2. Ran the full frontend Jest suite 5× back-to-back. All 91 tests passed every time, ~2.5s per run.
3. With zero flakes found, designed a new file of *flakiness regression guards* — tests that target known sources of flakiness (non-deterministic handlers, lazy state, clock regressions, header mutation, lazy route registration) so a future change that re-introduces them fails on the first run rather than the hundredth.

### Backend — `backend/tests/test_flakiness_guards.py` (new file, 22 tests)

| Suite | Test | Pins |
|-------|------|------|
| `TestOpenAPISchemaByteStability` | `test_repeated_openapi_json_responses_are_byte_identical` | 20 back-to-back `GET /openapi.json` responses share one body hash — catches a future `app.openapi_schema = None` (regenerate-on-fetch) regression that would silently churn the schema and break clients that hash it for compatibility. |
| `TestOpenAPISchemaByteStability` | `test_openapi_schema_dict_equal_across_repeated_calls` | Parsed schema dicts are deeply equal across 10 calls — catches *semantic* schema drift even if a future stable-but-reordered serialisation makes the bytes change. |
| `TestHighIterationMessageDeterminism` | `test_post_hello_message_is_byte_identical_across_200_calls` | 200 identical POSTs return exactly one distinct `message` value — extends the existing 5-call idempotence check by 40× so a 1%-probability flake (e.g. accidentally appending a uuid suffix on some code path) trips here with ~86% confidence per run. |
| `TestHighIterationMessageDeterminism` | `test_get_hello_message_is_byte_identical_across_200_calls` | Same pin for `GET /api/hello`. |
| `TestHighIterationMessageDeterminism` | `test_health_status_field_is_byte_identical_across_200_calls` | The `status` literal value is exactly `"healthy"` across 200 calls — catches accidental locale leaks or per-request status mutation. |
| `TestHighIterationMessageDeterminism` | `test_version_response_body_is_byte_identical_across_200_calls` | `/api/version` has no timestamp field, so the *entire* body must be byte-identical across 200 calls — a divergence means a non-deterministic field was added. |
| `TestConcurrentIdenticalInputDeterminism` | `test_100_concurrent_identical_posts_return_one_message` | 100 concurrent POSTs with the same name return one distinct `message` — complements the existing distinct-name concurrency tests by checking the *opposite* property (pure-function semantics survive interleaving). |
| `TestConcurrentIdenticalInputDeterminism` | `test_100_concurrent_health_calls_return_one_status` | 100 concurrent `/health` calls all return `status="healthy"` — guards against shared mutable state in the health handler that only surfaces under concurrency. |
| `TestConcurrentIdenticalInputDeterminism` | `test_concurrent_identical_timestamps_are_all_valid_utc` | Every timestamp from 50 concurrent POSTs parses as UTC ISO 8601 — catches race conditions on shared timestamp state that produce malformed strings under interleaving. |
| `TestMultipleTestClientIsolation` | `test_two_clients_against_same_app_return_identical_health` | Two independent `TestClient` instances see the same `/health` response — pins the parallel-test-runner model. |
| `TestMultipleTestClientIsolation` | `test_ten_clients_serially_each_return_200` | Creating and tearing down 10 `TestClient` instances each succeeds — catches per-instance teardown side effects. |
| `TestMultipleTestClientIsolation` | `test_new_client_after_post_does_not_inherit_prior_post_state` | A POST on one client doesn't leak into another — pins the stateless contract across the TestClient boundary, not just within one instance. |
| `TestAppSingletonInvariant` | `test_repeated_imports_return_same_object` | `from app.main import app` always returns the same identity — catches an accidental refactor that moves `FastAPI()` construction inside a function (which would silently double-register middleware on re-import). |
| `TestAppSingletonInvariant` | `test_app_routes_set_is_stable_across_repeated_access` | The `app.routes` inventory is identical on three repeated reads — catches lazy route registration that only surfaces under specific request orderings. |
| `TestStressMonotonicTimestamps` | `test_500_sequential_health_timestamps_are_non_decreasing` | 500 sequential `/health` timestamps are monotonically non-decreasing — extends the existing 10-call check by 50× so a coarsely-rounded or cached clock that passes 10 calls fails here. |
| `TestStressMonotonicTimestamps` | `test_500_sequential_post_timestamps_are_non_decreasing` | Same stress pin for `POST /api/hello` timestamps. |
| `TestCORSPreflightByteDeterminism` | `test_repeated_preflight_returns_identical_cors_headers` | 20 preflights yield one distinct set of CORS headers (allow-origin/methods/headers/credentials/max-age) — catches a future change that binds CORS headers to a per-request random value, which would silently invalidate browser caches and double every cross-origin POST. |
| `TestCORSPreflightByteDeterminism` | `test_preflight_followed_by_post_preflight_unchanged` | A POST between two preflights doesn't alter the preflight response — catches accidental per-origin or per-request state mutation in CORS middleware. |
| `TestRouteInventoryStability` | `test_openapi_paths_set_is_identical_across_repeated_calls` | The set of declared paths in `/openapi.json` is identical across 10 calls — guards against lazy route registration visible only via the schema, not via direct `app.routes` access. |
| `TestRouteInventoryStability` | `test_openapi_components_schemas_set_is_identical_across_repeated_calls` | The set of declared component-schema names is identical across 10 calls — guards against lazy Pydantic-model registration. |
| `TestAsyncClientReuseDeterminism` | `test_50_sequential_calls_on_one_async_client_return_one_message` | 50 sequential POSTs on a *single* reused `AsyncClient` yield exactly one distinct `message` — catches httpx/Starlette connection-level state leaking into response bodies on reuse. |
| `TestAsyncClientReuseDeterminism` | `test_alternating_get_post_on_one_async_client_each_correct` | Alternating GET and POST on the same `AsyncClient` each return their own correct shape across 20 cycles — catches shared-client request-level state mutation (e.g. headers carrying over). |

**Why these specifically.** Each test targets a *source* of flakiness that the existing suite does not pin, picked from the flaky-test taxonomy commonly seen in async-Python services:

- **Non-deterministic schema generation:** FastAPI's `app.openapi_schema` cache is implicit; a future handler that calls `app.openapi_schema = None` (or any code path that re-enters generation) would silently churn the schema. Byte-identity over 20 calls catches it.
- **Low-probability handler randomness:** The existing 3–5-call idempotence checks would miss a 1%-per-call regression. 200 calls bring the detection probability to ~86% per run; over a few CI runs the probability of detection approaches 1.
- **Concurrent state corruption under identical input:** All existing concurrency tests use *distinct* inputs (to catch name-leak bugs). 100 concurrent identical POSTs check the *opposite* property — pure-function semantics under interleaving — and would catch a shared mutable buffer that only manifests when two requests happen to hit the same instant.
- **TestClient instance isolation:** Parallelism models (`pytest-xdist`, etc.) instantiate many clients per process. Pinning that the app is stateless across `TestClient` boundaries makes any future per-client-instance state regression fail loudly.
- **App singleton invariant:** A future refactor that moves the `FastAPI()` constructor inside a function would cause every re-import to re-register middleware, producing weird double-CORS-headers flakes only on test runs that happen to trigger the re-import. The identity check catches it at the source.
- **Clock regressions at scale:** A clock implementation that returns the same coarsely-rounded value most of the time but occasionally goes backwards (e.g. an accidental `time.time()` instead of `datetime.now(UTC)` on Windows) would pass the existing 10-call monotonicity test. 500 calls catch the failure window.
- **CORS preflight mutation:** A future change that bound CORS allow-headers to a per-request hash would silently invalidate the browser CORS cache, doubling every cross-origin POST. Repeat-preflight byte-identity catches it.
- **Lazy route/schema registration:** The OpenAPI route/component inventory can lag the actual `app.routes` inventory if FastAPI ever introduces request-driven schema generation. Repeat-fetch stability pins both views.
- **Shared async-client state:** Reusing an `AsyncClient` across many calls or alternating verbs is the common test-fixture pattern. If httpx/Starlette ever leaked request-level state across calls on the same client, every async test would silently start coupling — these guards make that visible.

**Verification:** 314 backend tests (292 → 314) + 91 frontend tests pass, 3× in sequence with no flakiness (~2.2s per `test_flakiness_guards.py` run, ~6.8s full backend suite). Backend coverage stays at 100% (36/36 statements + branches). Frontend coverage unchanged (this session adds backend-only tests). Pre-PR, the new file was run 3× in sequence to confirm the guards themselves are not flaky.

---

## QA Run: Wednesday 2026-05-20 — Integration Gaps (issue #225)

### Backend — `backend/tests/test_integration_gaps.py` (new file, 19 tests)

Line coverage was already at 100% for both backend and frontend before this run, so the
focus is on **cross-component integration gaps** that the existing 314 tests do not pin —
behaviours that all pass today but for which no test would fail if a regression silently
broke them.

| Suite | Test | Pins |
|-------|------|------|
| `TestCORSOnErrorResponses` | `test_404_from_allowlisted_origin_carries_acao_and_vary` | A 404 from an allow-listed origin still carries `Access-Control-Allow-Origin` and `Vary: Origin`. Existing CORS tests only assert behaviour on 200s; a regression that registers an exception handler outside the CORSMiddleware chain would leave the browser unable to read the 404 body. |
| `TestCORSOnErrorResponses` | `test_405_from_allowlisted_origin_carries_acao_and_vary` | Same pin for 405 (method-not-allowed) responses. |
| `TestCORSOnErrorResponses` | `test_422_from_allowlisted_origin_carries_acao_and_vary` | Same pin for 422 (validation-error) responses — the most common error a CORS client will hit. |
| `TestCORSOnErrorResponses` | `test_404_from_disallowed_origin_omits_acao` | A 404 from a non-allow-listed origin must not leak any `Access-Control-Allow-Origin` header. Catches a regression that would echo every requesting origin on error paths. |
| `TestCORSOnErrorResponses` | `test_422_from_disallowed_origin_omits_acao` | Same pin for 422 — the path that's most likely to leak headers because FastAPI's validation-error handler runs before route-level config. |
| `TestASGILifespanIntegration` | `test_app_serves_requests_inside_lifespan_window` | Entering `app.router.lifespan_context(app)` directly, a request inside the window returns 200 and exit doesn't raise. Catches a future startup hook that throws under uvicorn but never runs under `TestClient` because `TestClient` short-circuits lifespan unless told otherwise. |
| `TestASGILifespanIntegration` | `test_lifespan_can_be_entered_and_exited_repeatedly` | Three back-to-back lifespan cycles all succeed. Catches a stuck startup-state regression where a one-shot initializer leaves global state behind. |
| `TestDocsHTMLWiring` | `test_docs_html_references_canonical_openapi_url` | Swagger UI HTML payload contains `/openapi.json`. Existing tests only check the status code — they would still pass if `openapi_url=None` (no schema served), but the docs page would render empty. |
| `TestDocsHTMLWiring` | `test_docs_html_embeds_app_title` | Swagger UI HTML embeds `Software Factory API` (the configured app title). Catches a regression that decouples the page title from the FastAPI metadata. |
| `TestDocsHTMLWiring` | `test_redoc_html_references_canonical_openapi_url` | Same pin for ReDoc — both UIs depend on `/openapi.json` and both would silently break together. |
| `TestDocsHTMLWiring` | `test_redoc_html_embeds_app_title` | Same title-pin for ReDoc. |
| `TestAsyncClientSchemaContract` | `test_documented_get_routes_response_keys_match_schema` | Every documented GET 200 route, fetched via real `httpx.AsyncClient` + `ASGITransport`, returns a body whose top-level keys match the documented response component. `TestOpenAPISchemaContract` covers this via `TestClient` only; the async ASGI transport path was untested. |
| `TestAsyncClientSchemaContract` | `test_documented_post_hello_response_keys_match_schema` | Same pin for the documented POST 200 on `/api/hello`. |
| `TestCORSVaryOnRealRequest` | `test_allowlisted_get_response_includes_vary_origin` | A real (non-preflight) allow-listed GET still carries `Vary: Origin`. Existing tests pin Vary on preflights only; shared caches (CDN, browser disk cache) also need it on the actual response to keep per-origin entries safe. |
| `TestCORSVaryOnRealRequest` | `test_allowlisted_post_response_includes_vary_origin` | Same pin for the actual POST response — the path that's most likely to be cached incorrectly if Vary is missing. |
| `TestOPTIONSWithoutCORSHeaders` | `test_options_without_cors_headers_on_api_hello_returns_405` | Bare `OPTIONS /api/hello` (no `Origin`, no `Access-Control-Request-Method`) returns 405, not a synthesized 200. Catches a regression where CORSMiddleware starts answering 200 to any OPTIONS, which would mask a real CORS misconfiguration in integration tests. |
| `TestOPTIONSWithoutCORSHeaders` | `test_options_without_cors_headers_on_health_returns_405` | Same pin for `/health`. |
| `TestMultipleAllowListedOriginsInterleaved` | `test_acao_is_echoed_per_request_across_allowlisted_origins` | Interleaved GETs from `http://localhost:3000` and `http://127.0.0.1:3000` each receive their own origin echoed back. Catches a regression where the matched origin gets cached at module-import time (e.g. via `functools.cache`), making ACAO "stick" to whichever origin called first. |
| `TestMultipleAllowListedOriginsInterleaved` | `test_acao_is_echoed_per_request_for_post` | Same per-request echo pin for POST requests. |

**Why these specifically.** Each test targets an **integration boundary** that the existing
suite does not pin, picked from where two components meet in `app/main.py`:

- **CORSMiddleware × FastAPI exception handlers.** FastAPI's 404/405/422 responses are
  generated by exception handlers, not by route handlers. Whether CORSMiddleware wraps
  them depends on middleware ordering — a regression that registers a handler outside
  the middleware chain would silently break cross-origin error reporting. The five
  `TestCORSOnErrorResponses` tests pin this boundary for the three error status codes
  on both allow-listed and disallowed origins.
- **FastAPI × ASGI lifespan.** The `TestClient` and `AsyncClient` fixtures both run a
  lifespan but never assert anything about it. Directly entering
  `app.router.lifespan_context(app)` is the closest test-side mirror of how uvicorn
  hosts the app in production, so a thrown startup hook fails *here* before it ships.
- **FastAPI metadata × `/docs` and `/redoc` HTML.** The Swagger UI and ReDoc HTML pages
  are generated by FastAPI at request time from the configured `title` and
  `openapi_url`. A regression that nulls `openapi_url` or changes the title would still
  pass the existing status-only tests but break both docs UIs in practice.
- **AsyncClient × ASGITransport × Pydantic response model.** The full async response
  path (httpx serialisation → ASGI framing → Starlette response → Pydantic dump) is
  exercised by existing tests for status codes and field values, but the documented
  schema vs. live response *keys* parity is only pinned on the sync `TestClient` path.
- **Shared cache (CDN/browser) × CORSMiddleware.** `Vary: Origin` is pinned on preflights
  only. The actual GET/POST response also needs it, otherwise a cached response served
  to origin A could be replayed for origin B with the wrong ACAO header.
- **CORSMiddleware OPTIONS handling × router.** Existing tests cover OPTIONS with
  malformed CORS headers but not the bare-OPTIONS case. A middleware that synthesizes
  200 for *any* OPTIONS would mask a real CORS misconfiguration in browser-style
  integration tests.
- **Per-request middleware state.** The two allow-listed origins
  (`http://localhost:3000` and `http://127.0.0.1:3000`) interleaved 3× catches any
  origin-matching cache that would make ACAO stick to the first caller.

**Verification:** 333 backend tests (314 → 333) + 91 frontend tests pass, 3× in
sequence with no flakiness (~0.07s per `test_integration_gaps.py` run, ~6.4s full
backend suite). Backend coverage stays at 100% (36/36 statements + branches). Frontend
coverage unchanged (this session adds backend-only tests).

## QA Run: Thursday 2026-05-21 — E2E Performance (issue #228)

### Backend — `backend/tests/test_performance.py` (12 new tests across 5 new classes)

Line coverage is already at 100% on both backend (`app/main.py`) and frontend
(`page.tsx`, `layout.tsx`), so this rotation widens the e2e-performance regression
surface itself. The existing 12 classes guard happy-path latency, latency distribution,
parallel/concurrent throughput, payload size, and burst patterns; the 5 new classes
cover paths that real E2E traffic touches but the prior guards do not.

#### `TestErrorPathLatency` (3 tests)
| Test | Description |
|------|-------------|
| `test_404_latency_under_ceiling` | A 404 for an unknown route completes under 500ms — error paths must not be slower than the happy path |
| `test_422_validation_error_latency_under_ceiling` | A 422 from a missing required field on POST /api/hello completes under 500ms |
| `test_405_method_not_allowed_latency_under_ceiling` | A 405 for PUT on /api/hello completes under 500ms |

#### `TestDocsHTMLPagePerformance` (4 tests)
| Test | Description |
|------|-------------|
| `test_docs_html_page_under_ceiling[docs]` | GET /docs (Swagger UI HTML) completes under 500ms |
| `test_docs_html_page_under_ceiling[redoc]` | GET /redoc (ReDoc HTML) completes under 500ms |
| `test_repeated_docs_html_avg_under_ceiling` | Five repeat /docs calls average under 200ms — catches template-render regressions |
| `test_docs_html_body_under_size_ceiling` | /docs HTML body stays under 8KB — bloat guard against accidentally inlining the OpenAPI schema |

#### `TestHighConcurrencyStress` (2 tests)
| Test | Description |
|------|-------------|
| `test_100_concurrent_health_under_ceiling` | 100 concurrent /health requests complete under 2s (2× the existing 50-request guard) |
| `test_60_concurrent_posts_return_distinct_names` | 60 concurrent POSTs each receive their own name back — correctness at 2× the existing concurrent-POST bound |

#### `TestThroughputFloor` (2 tests)
| Test | Description |
|------|-------------|
| `test_health_sustained_throughput_floor` | /health sustains at least 100 req/sec over 200 sequential calls — catches throughput regressions that fit within existing total-time ceilings |
| `test_post_hello_sustained_throughput_floor` | POST /api/hello sustains at least 50 req/sec over 100 sequential calls |

#### `TestRealisticFrontendStartupPattern` (1 test)
| Test | Description |
|------|-------------|
| `test_full_first_paint_sequence_under_ceiling` | Full simulated browser first paint (docs HTML → openapi.json → parallel init triad → user POST) completes end-to-end under 1.5s |

**Why these specific cross-cuts:**

- **Error pipeline × user-perceived latency.** Existing guards bound happy-path
  latency only; a regression in FastAPI's exception/validation machinery (custom
  `RequestValidationError` handler added on a hot path, a sync log call wired into
  the 404 path) would leave 200s fast and error responses slow. Real traffic hits
  these routinely — typos, schema drift between frontend and backend, retried POSTs
  after a deploy, bots — so error-path latency is part of the user-perceived budget.
- **Swagger/Redoc HTML × developer perception.** The docs HTML pages are the
  largest dynamically-rendered HTML responses the app serves by default and are the
  first surface a developer or operator notices a slowdown on. A regression here
  (template change, accidental schema inlining) would not surface in any of the
  JSON-endpoint guards.
- **Concurrency stress past the 50-request line.** The existing
  `TestConcurrentThroughput` caps concurrency at 50; a collapse that only appears
  past that point (lock contention surfacing at higher fan-out, accidental
  per-request resource hoarding) would slip through. 100 concurrent GETs and 60
  concurrent POSTs with correctness verification close that gap.
- **Throughput floor vs. total-time ceiling.** Every existing perf guard bounds
  *total elapsed time* for N calls, which catches catastrophic slowdowns but leaves
  a wide gap: a regression that halves throughput while still fitting under the
  ceiling will pass silently. Asserting a minimum req/sec floor on `/health` (100
  req/s) and POST `/api/hello` (50 req/s) fails the moment sustained throughput
  collapses by half, even when total time stays within the existing budget.
- **Full first-paint sequence × compounded regression.** Each individual leg
  (docs HTML, openapi.json, parallel init triad, first POST) is already guarded in
  isolation, but no test asserts the end-to-end perceived latency of the full
  sequence. A small regression on each leg can compound into a noticeable slowdown
  that none of the per-leg guards trips. The 1.5s end-to-end ceiling closes that gap.

**Verification:** 345 backend tests (333 → 345) + 91 frontend tests pass, 3× in
sequence with no flakiness (~1.3s per `test_performance.py` run, ~4.0s full backend
suite). Backend and frontend line coverage stay at 100%. Bounds are deliberately
generous (≥10× typical observed CI latency) so they fail only on real regressions.

---

## QA Run: Friday 2026-05-22 — Test Refactoring (issue #231)

**Focus:** test-refactoring — reduce duplication and tighten readability without
changing test behaviour or coverage. The backend suite has grown to 4,728 lines
across 9 files and several literal patterns are now repeated dozens of times,
making any future contract change a multi-file edit.

**No new tests added.** All 345 backend tests pass unchanged at 100% line and
branch coverage, 3× in a row.

### Helpers and constants added to `backend/tests/conftest.py`

| Name | Replaces |
|------|----------|
| `GREETING_TEMPLATE` constant | The literal `"Hello, {name}! Welcome to your Software Factory."` previously inlined in 8 assertion sites across `test_main.py` and `test_edge_cases.py`. |
| `expected_greeting(name)` helper | Eight inline `"Hello, X! Welcome to your Software Factory."` literals in test assertions. Pinning the template now touches one constant. |
| `DISALLOWED_ORIGIN` constant | Three inline `"https://evil.example.com"` literals in `test_main.py` (replaced) — a single source for negative-CORS tests so an origin rename is a one-line change. |
| `cors_preflight_headers(method, origin=LOCALHOST_ORIGIN)` helper | Twelve inline two-key header dicts of the form `{"Origin": LOCALHOST_ORIGIN, "Access-Control-Request-Method": "..."}` across `test_main.py`, `test_regression_prevention.py`, and `test_performance.py`. Performance tests that need an extra `Access-Control-Request-Headers` use `{**cors_preflight_headers("POST"), "Access-Control-Request-Headers": "content-type"}`. |
| `get_openapi_schema(client)` helper | Thirty-three inline `client.get("/openapi.json").json()` fetches across `test_main.py`, `test_integration.py`, `test_flakiness_guards.py`, `test_openapi_schema_metadata.py`, `test_integration_gaps.py`, and `test_regression_prevention.py`. Performance tests that intentionally measure the raw response timing keep the explicit `client.get(...)` so the timing window is unambiguous. |

### Duplication count, before → after

| Pattern | Before | After (excluding conftest.py canonical source) |
|---------|--------|------------------------------------------------|
| `"Hello, {name}! Welcome to your Software Factory."` literal in assertions | 11 | 2 (docstring references only) |
| `client.get("/openapi.json").json()` | 35 | 0 (2 remaining call sites in `test_performance.py` intentionally measure raw response timing) |
| `"Access-Control-Request-Method": "..."` header dict | 16 | 4 (each with extra `Access-Control-Request-Headers` and therefore an intentional non-default preflight) |
| `"https://evil.example.com"` literal | 4 | 0 (the one match in `test_integration_gaps.py` is a local `"http://evil.example"` constant; intentionally not unified to avoid changing test behaviour) |

### Refactor summary

| File | Change |
|------|--------|
| `tests/conftest.py` | Added `GREETING_TEMPLATE`, `DISALLOWED_ORIGIN`, `expected_greeting()`, `cors_preflight_headers()`, and `get_openapi_schema()`. |
| `tests/test_main.py` | Replaced 6 greeting literals with `expected_greeting()`, 4 preflight dicts with `cors_preflight_headers()`, 5 openapi.json fetches with `get_openapi_schema()`, and 2 evil-origin literals with `DISALLOWED_ORIGIN`. |
| `tests/test_edge_cases.py` | Replaced 2 greeting literals with `expected_greeting()`. |
| `tests/test_integration.py` | Replaced 7 openapi.json fetches with `get_openapi_schema()`. |
| `tests/test_flakiness_guards.py` | Replaced 4 openapi.json fetches with `get_openapi_schema()`. |
| `tests/test_openapi_schema_metadata.py` | Replaced 4 openapi.json fetches with `get_openapi_schema()` (including both module-level helpers). |
| `tests/test_integration_gaps.py` | Replaced 2 openapi.json fetches with `get_openapi_schema()`. |
| `tests/test_regression_prevention.py` | Replaced 7 openapi.json fetches with `get_openapi_schema()`; switched 2 inline `"http://localhost:3000"` literals to `LOCALHOST_ORIGIN`. |
| `tests/test_performance.py` | Replaced 2 preflight dicts with `{**cors_preflight_headers("POST"), "Access-Control-Request-Headers": "content-type"}`. |

**Why this matters:** A future single-character edit to the greeting template now
touches one constant in `conftest.py` instead of 11 assertion sites in three
files. The named `get_openapi_schema(client)` call documents intent at each call
site (the raw `client.get("/openapi.json").json()` chain reads as a generic HTTP
fetch). The `cors_preflight_headers(method)` helper makes the *intent* of each
OPTIONS call visible — without it, the two-key dict can read as "any header
dict" rather than specifically "this is a CORS preflight."

**Behavioural guarantee:** every assertion is preserved byte-for-byte; only the
*source* of the constant and the *construction* of the request dict moved.

**Verification:** 345 backend tests pass 3× in sequence (~4.1s each). Backend
line and branch coverage stay at 100%. `ruff format`, `ruff check --fix`, and
`mypy` all pass clean.

---

## Saturday Edge-Case Pins (test_edge_cases.py extension)

**Focus:** edge-case behaviour pins. Both backend and frontend are already at
100% line + branch coverage, so this run targets the *unpinned-behaviour* gap
rather than the *uncovered-line* gap. Each new test asserts a concrete HTTP
contract behaviour that the live server exhibits today but that no existing
test guards — a future regression would fail one of these first.

### New test classes in `tests/test_edge_cases.py`

| Class | Tests | What it pins |
|-------|-------|--------------|
| `TestAcceptHeaderIgnored` | 4 | Server ignores the request `Accept` header and always returns `application/json`. Covers `text/html`, `application/xml`, `application/json;q=0, text/html` (JSON explicitly excluded), and `*/*`. Guards against a regression that adds a content-negotiation middleware emitting HTML/XML or a 406. |
| `TestNullOriginNotAllowlisted` | 2 | The literal Origin string `"null"` (sandboxed iframes, `file://` pages) is not allow-listed. Pins both the real-request side (no `Access-Control-Allow-Origin` echoed back on `GET /health`) and the preflight side (OPTIONS preflight from `Origin: null` carries no allow-origin header). Guards against accidental `null` allow-listing — a common CORS misconfiguration. |
| `TestRequestBodyJSONStrictness` | 4 | Strict JSON request parsing. Pins 422 for: mixed-case field name (`{"Name":"Alice"}`); a JS-style comment inside the object; multiple concatenated valid JSON objects in one body; a single extra trailing `}` after a valid object. Each case targets a different lenient-parser regression (alias generators, JSON5, NDJSON, balanced-brace counting). |
| `TestTrailingSlashOnAllEndpoints` | 3 | Trailing-slash tolerance for `GET /api/version/`, `GET /api/hello/`, and `POST /api/hello/`. Extends the existing `/health/` pin to every public route so a future `redirect_slashes=False` (or a custom router) cannot silently flip a subset of paths to 404/307. |
| `TestSpuriousURLsReturn404` | 3 | `GET /openapi.yaml`, `GET /favicon.ico`, and `GET /he%20alth` all return 404. Guards against a future YAML schema flag, a static-files middleware serving a default favicon, and a URL-normalisation middleware that collapses whitespace inside path segments. |
| `TestPostQueryStringIgnored` | 1 | `POST /api/hello?name=Bob` with body `{"name":"Alice"}` greets `Alice`. Complements the GET-side query-string-ignored pin; guards against a future `Query()` parameter on the POST handler that would silently override or merge with the body. |

### Why these specific edges?

The pre-existing `test_edge_cases.py` already pinned: top-level non-object
bodies, Content-Type permissiveness/strictness, BOM and trailing-whitespace
tolerance, double-slash and percent-encoded paths, length/character-class
boundaries, and exact response Content-Type. This run extended that list along
the **request-header axis** (`Accept`, `Origin: null`), the **JSON-strictness
axis** (mixed-case key, comments, multi-object, extra brace), the **path-shape
axis** (trailing slash on every endpoint, spurious convention names,
whitespace-in-segment), and the **URL/body interaction axis** (POST query
string).

### Verification

- 362 backend tests pass 3× in sequence (~7.6s each).
- Backend line and branch coverage stay at 100% (no production code touched).
- All 14 new tests use only existing fixtures and helpers (`client`,
  `expected_greeting`) — no new test infrastructure.
- `ruff format`, `ruff check --fix`, and `mypy` all pass clean.

---

## QA Run: Sunday 2026-05-24 — Regression Prevention (issue #237)

**Focus:** behavioural regression pins for HTTP-contract edges exercised but
not asserted by the past week of commits. Both surfaces stay at 100% line +
branch coverage; the lever is **behaviour pinning**, not coverage. Each new
test asserts a concrete behaviour the live server exhibits today that no
existing test guards — a future regression would fail one of these first.

### Backend — `backend/tests/test_regression_prevention.py` (10 new classes, 26 new tests)

| Class | Tests | What it pins |
|-------|-------|--------------|
| `TestOperationIdsAreGloballyUnique` | 1 | Every OpenAPI `operationId` appears at most once across paths × methods. SDK generators emit one function per operationId — a collision silently drops a route from the SDK. Existing tests pin each value individually but not the *distinctness* contract. |
| `TestOpenAPITopLevelKeysPinned` | 7 | Required top-level keys (`openapi`, `info`, `paths`, `components`) are present; six optional keys (`servers`, `security`, `externalDocs`, `webhooks`, `tags`, `jsonSchemaDialect`) are absent. Adding e.g. `servers=` to `FastAPI(...)` would silently rewrite every SDK's base URL — this pin makes that loud. |
| `TestResponseBodyHasNoTrailingNewline` | 4 | The last byte of every 200 body is `}` (no trailing `\n` / whitespace). Pinning the byte-shape catches a swap to a pretty-printing response class (`ORJSONResponse(..., indent=2)`, or a manual `Response` with `"\n"` concatenated) before it inflates Content-Length and confuses byte-exact comparisons elsewhere. |
| `TestServerHeaderNotEmitted` | 4 | No `Server` header on any 200 response. Pins that server-software fingerprinting stays disabled and that no future "Powered-By" middleware silently leaks framework identity to clients. |
| `TestAcceptHeaderIgnoredOnPost` | 3 | Content negotiation is disabled on the POST path too. Saturday's `TestAcceptHeaderIgnored` covered `GET /health` only; this class pins `POST /api/hello` with `Accept: text/html`, `application/xml`, and the `application/json;q=0, text/html` (JSON explicitly excluded) cases. |
| `TestNullOriginOnPostNotAllowlisted` | 1 | `Origin: null` is rejected on the real POST path. Saturday's `TestNullOriginNotAllowlisted` covered the GET path and the OPTIONS preflight; this class pins the security-relevant POST case so a custom middleware that allow-lists `"null"` for the "real" path would fail loudly. |
| `TestAdditionalSpuriousURLsReturn404` | 5 | `/robots.txt`, `/sitemap.xml`, `/`, `/api`, and `/api/` all return 404. Extends Saturday's `TestSpuriousURLsReturn404` (which covered `/openapi.yaml`, `/favicon.ico`, `/he%20alth`) to SEO conventions and common-prefix "directory" URLs that some routers would silently 200 on. |
| `TestPostQueryStringWithoutBodyIs422` | 1 | `POST /api/hello?name=Bob` with **no body** returns 422. Saturday's `TestPostQueryStringIgnored` pinned the body-present case; this pins the complementary case so a regression that introduced a `Query()` parameter named `name` on the POST handler fails here. |
| `TestHelloRequestNameLiteralNullIs422` | 1 | `POST /api/hello` with `{"name": null}` returns 422 — Pydantic does not coerce `None` to `"None"`. Pins that `HelloRequest.name` stays typed `str` (not `Optional[str]`), guarding against a silent type-widening that would render `"Hello, None!"` to clients passing null on accident. |
| `TestHealthTrailingSlashReturnsSameShape` | 1 | `GET /health/` returns the same key set and the same `status` value as `GET /health` (timestamps differ by design). Saturday's `TestTrailingSlashOnAllEndpoints` pinned **status codes**; this pins **body shape** so a hand-rolled fallback handler for the trailing-slash form cannot return a different shape (HTML redirect notice, stripped response) while keeping the 200. |

### Why these specific edges?

The previous five Sunday + Saturday runs accreted a dense behavioural surface:
exact greeting strings, OpenAPI title/version/description/operationIds/tags,
CORS allow-list and near-miss origins, preflight contents, content-type
strictness/permissiveness, BOM/trailing-byte parsing, path routing edges, 50K
echo, 422 schema shape, p95/p99 latency, response_model coverage, schema $ref
shape, openapi component inventory, cache-control absence, allow-headers echo.

This run targets four orthogonal axes the existing pins do not cover:

* **OpenAPI structural integrity** — operationId uniqueness and the absence of
  optional top-level keys (`servers`, `security`, `externalDocs`, etc.). Both
  are SDK-generation contracts that no existing test asserts.
* **Response byte shape** — `Server` header absence and trailing-byte shape.
  These pin "how" the response is framed, complementing the existing "what
  the response contains" pins.
* **Cross-axis extensions of last week's edge-case work** — Saturday pinned
  Accept/Origin behaviours on GET only; this run extends them to POST and adds
  the `/robots.txt`/`/sitemap.xml`/`/`/`/api` URL fan-out.
* **Type-system contracts** — `name: null` returns 422 (not coerced), and
  `/health/` returns the same body shape as `/health` (not just the same
  status). Both guard against silent type-widening or fallback-handler drift.

### Verification

- 390 backend tests pass 3× in sequence (~3.0s each).
- Backend line and branch coverage stay at 100% (no production code touched).
- 91 frontend tests still pass (no frontend changes this run).
- All 26 new tests use only existing fixtures (`client`) and the
  `get_openapi_schema` conftest helper — no new test infrastructure.
- `ruff format`, `ruff check --fix`, and `mypy` all pass clean.

## QA Run: Monday 2026-05-25 — coverage-sprint (issue #241)

**Goal.** The Monday focus is officially "pick the lowest-coverage file and
raise it by 15%+." Both surfaces have been saturated for several weeks — `pytest --cov=app`
reports 100% statement + branch on `app/__init__.py` and `app/main.py`, and
`jest --coverage` reports 100% statements + branches + functions + lines on `layout.tsx` and
`page.tsx` (390 backend + 91 frontend tests passing pre-run). The literal goal is
mathematically unachievable, so this session continues the pivot established by the
2026-05-18 run: add behavioural pins that fail on real regressions the existing
coverage-blind tests would silently miss.

The 2026-05-18 run already pinned the OpenAPI metadata layer (`info` block inventory,
component descriptions/titles, `required` arrays, property titles, operation
summaries). This run targets the next layer up — the **Python attributes on the
`FastAPI` app instance**, the **constructor kwargs of the installed CORS middleware**,
the **`app.openapi()` caching invariant**, the **`__version__` string shape**, the
**Pydantic v2 `extra` policy** on request models, the **`async`-ness of every
handler**, and the **package module docstring**. Every pin in this run targets a
regression class that would not be caught by `--cov` because the behaviour is derived
by a third-party library (FastAPI / Starlette / Pydantic) from the source we ship — no
Python statement in `app/main.py` produces these values, so `--cov` reports 100% even
after they mutate.

### Backend — `backend/tests/test_app_instance_invariants.py` (new file, 22 tests)

| Suite | Test | Pins |
|-------|------|------|
| `TestAppInstancePythonAttributes` | `test_app_is_a_fastapi_instance` | `type(app) is FastAPI` (not a subclass / not wrapped in `Starlette(routes=[Mount('/', app)])`). A wrapper refactor changes the public route surface silently. |
| `TestAppInstancePythonAttributes` | `test_app_title_attribute_pinned` | `app.title == "Software Factory API"` read off the Python attribute (the OpenAPI `info.title` is pinned elsewhere; this catches a post-construction `app.title = ...` reassignment that flows through a different code path). |
| `TestAppInstancePythonAttributes` | `test_app_description_attribute_pinned` | `app.description == "Backend API powered by Claude Software Factory"` — Python attribute. |
| `TestAppInstancePythonAttributes` | `test_app_version_attribute_equals_dunder_version` | `app.version == __version__` directly via the attribute, pinning the wiring at the Python level (a regression that hard-codes `version="0.1.0"` in the constructor while changing `__version__` would still pass the OpenAPI-side wiring test if both happened together; this attribute pin keeps the link inspectable). |
| `TestAppInstancePythonAttributes` | `test_app_docs_url_attribute_pinned` | `app.docs_url == "/docs"`. |
| `TestAppInstancePythonAttributes` | `test_app_redoc_url_attribute_pinned` | `app.redoc_url == "/redoc"`. |
| `TestAppInstancePythonAttributes` | `test_app_openapi_url_attribute_is_default` | `app.openapi_url == "/openapi.json"` — FastAPI default. A future override that moves the schema endpoint (e.g. to `/api/openapi.json`) is loud here. |
| `TestAppInstancePythonAttributes` | `test_app_root_path_is_empty` | `app.root_path == ""` — no ASGI sub-mount prefix; a non-empty `root_path` would alter the URLs in the OpenAPI `servers` block. |
| `TestCORSMiddlewareInstanceConfiguration` | `test_exactly_one_cors_middleware_installed` | Exactly one `CORSMiddleware` is registered in `app.user_middleware` — guards against an accidental duplicate `add_middleware(CORSMiddleware, ...)` call that would apply CORS twice and duplicate `Vary: Origin` headers. |
| `TestCORSMiddlewareInstanceConfiguration` | `test_cors_middleware_kwargs_match_documented_config` | The CORS middleware's kwargs `{allow_origins, allow_credentials, allow_methods, allow_headers}` equal the documented values exactly — pins the **source** of the response-header contract that downstream tests pin via observed headers. |
| `TestCORSMiddlewareInstanceConfiguration` | `test_cors_allow_origins_excludes_wildcard` | `allow_origins` does not contain `'*'` — the CORS spec **forbids** the combination of `allow_credentials=True` and `allow_origins=['*']`; browsers reject every credentialed request silently. A future "open up CORS" change would silently break production. |
| `TestOpenAPISchemaCached` | `test_openapi_returns_same_object_across_calls` | `app.openapi() is app.openapi()` — pins the FastAPI schema-cache invariant. A regression that disables the cache multiplies schema-generation work on every `/openapi.json` request. |
| `TestOpenAPISchemaCached` | `test_openapi_schema_attribute_is_populated_after_call` | `app.openapi_schema is not None` after the first `app.openapi()` call — pins the underlying mechanism (the `openapi_schema` attribute) that backs the caching invariant above. |
| `TestVersionStringShape` | `test_version_is_a_nonempty_string` | `__version__` is a non-empty `str`. |
| `TestVersionStringShape` | `test_version_matches_three_part_dotted_shape` | `__version__` matches `\d+\.\d+\.\d+` (PEP 440 `MAJOR.MINOR.MICRO`). A regression that drops to `"dev"` or `""` would silently break client `packaging.version.parse(...)` logic. |
| `TestHelloRequestExtraFieldsPolicy` | `test_hello_request_extra_field_is_dropped_silently` | `HelloRequest(name='Alice', surprise='ignored')` doesn't raise and `model_dump()` excludes `surprise` (Pydantic v2 default `extra='ignore'`). Pins the public API tolerance for extra fields — tightening to `extra='forbid'` would start returning 422 to clients silently. |
| `TestHelloRequestExtraFieldsPolicy` | `test_hello_request_model_config_is_empty` | `HelloRequest.model_config == {}` — pins the **cause** of the behaviour above so a regression that adds an override flags this test at the source. |
| `TestHandlersAreCoroutines` | `test_handler_is_coroutine_function[health_check]` | `inspect.iscoroutinefunction(health_check)` — pins that the handler is `async def`. A regression dropping `async` would silently route the handler through FastAPI's threadpool, changing ASGI scheduling profile and adding threadpool overhead per request. |
| `TestHandlersAreCoroutines` | `test_handler_is_coroutine_function[get_version]` | Same pin for `get_version`. |
| `TestHandlersAreCoroutines` | `test_handler_is_coroutine_function[hello_world]` | Same pin for `hello_world`. |
| `TestHandlersAreCoroutines` | `test_handler_is_coroutine_function[hello_name]` | Same pin for `hello_name`. |
| `TestPackageModuleDocstring` | `test_app_package_has_expected_docstring` | `app.__doc__ == "Software Factory Backend API."` — pins the package-level docstring that shows in `pydoc`, sphinx-autodoc, and IDE hovers. |

### Why these specifically

Each pin targets a regression vector that line + branch coverage **cannot** detect:

- **App-instance attributes** (`title`, `description`, `version`, `docs_url`,
  `redoc_url`, `openapi_url`, `root_path`): set via constructor kwargs; FastAPI reads
  them lazily when serving routes. Existing tests pin the OpenAPI `info` block and the
  HTTP 200 status of `/docs` / `/redoc` — but not the Python attribute that backs
  them. A future programmatic reassignment (`app.title = configured_title`) flowing
  through a different code path would change OpenAPI without touching constructor kwargs.

- **CORS middleware kwargs**: `TestCORSMiddleware`, `TestCORSCacheCorrectness`,
  `TestRegressionCORSPreflightContents` pin observed response headers. None inspect
  the live middleware kwargs. The wildcard-with-credentials pin is particularly
  load-bearing — it's the kind of "tighten" regression that ships green if you only
  test the response header path (header is still present), but breaks every browser.

- **`app.openapi()` caching**: every existing test fetches the schema via
  `client.get("/openapi.json").json()` which deserialises a fresh dict each call.
  None assert identity. A cache-disabling regression multiplies schema-generation cost
  on every request.

- **`__version__` shape**: existing tests pin the literal **value** (`"0.1.0"`) but
  not the **shape**. A change to `"dev"` would still satisfy the equality assertions
  in `TestRegressionMessageFormat` (after updating the literal there) but break
  client-side `packaging.version.parse(...)` comparisons silently.

- **`HelloRequest` extra-fields policy**: tightening Pydantic's default
  `extra='ignore'` to `extra='forbid'` is a small one-line change with public-API
  consequences (clients passing forward-compatible extra fields start getting 422s).
  Both the behaviour and the cause (empty `model_config`) are pinned so the change is
  visible no matter which path a future edit takes.

- **Handler coroutine-ness**: dropping `async` from a handler changes FastAPI's
  dispatch path to a threadpool. Every existing test still passes (the response is
  identical), but the scheduling profile changes. No prior test calls
  `inspect.iscoroutinefunction` on any handler.

- **Package docstring**: shows up in `pydoc`, sphinx, IDE hovers — but invisible to
  every other test in the suite.

### Verification

- 412 backend tests (390 → 412) pass 3× in sequence with no flakiness (~0.04s per
  isolated run, ~7.7s full-suite run).
- Backend line and branch coverage stay at 100% (36/36 statements + branches, no
  production code touched).
- 91 frontend tests still pass (no frontend changes this run).
- All 22 new tests use direct imports from `app` and `app.main` — no new conftest
  helpers or fixtures.
- `ruff format`, `ruff check --fix`, and `mypy` all pass clean.

## QA Run: Tuesday 2026-05-26 — flaky-hunt (issue #245)

**Focus:** Tuesday flaky-hunt. Five back-to-back runs of the full backend suite
(412 tests) and five frontend runs (91 tests) produced zero flakes — the suite
is already deterministic at the assertion level. This session extends the
flakiness *regression surface* by pinning four classes of stability that the
existing `test_flakiness_guards.py` does not yet cover.

### Backend — `backend/tests/test_flakiness_guards.py` (4 new classes, 9 new tests)

| Class | Test | What it validates |
|-------|------|-------------------|
| `TestOpenAPISchemaUnderConcurrency` | `test_50_concurrent_openapi_fetches_return_one_body` | 50 concurrent `GET /openapi.json` fetches yield exactly one body hash. The existing byte-identity guard exercises only the cached read path; this exercises the *hot-cache* concurrent path. |
| `TestOpenAPISchemaUnderConcurrency` | `test_concurrent_cold_cache_openapi_fetches_return_one_body` | With `app.openapi_schema` reset to `None`, 30 concurrent fetches must each regenerate and agree on one parsed schema. Forces the cache-fill race path that the hot-cache test cannot reach. State is restored in `finally` so it cannot leak. |
| `TestMixedMethodConcurrentDeterminism` | `test_interleaved_mixed_calls_each_return_correct_shape` | 40 concurrent calls mixing `GET /health`, `GET /api/hello`, `POST /api/hello`, `GET /api/version`, and `GET /openapi.json` each return a body matching their own route (health → `status: healthy` + UTC timestamp; POST → echoes its `Mixed{i}` name; etc.). Catches cross-handler state leakage that identical-input fan-out cannot. |
| `TestGCInvariance` | `test_health_body_byte_identical_across_forced_gc_cycles` | `gc.collect()` fired before and after each of 20 `/health` calls; status field is always `"healthy"`. Catches any future cache keyed on `id()` that the garbage collector could disturb. |
| `TestGCInvariance` | `test_post_hello_message_byte_identical_across_forced_gc_cycles` | Same gc-bracketed protocol for 20 `POST /api/hello` calls; the `message` field is byte-identical. |
| `TestGCInvariance` | `test_openapi_body_byte_identical_across_forced_gc_cycles` | Same gc-bracketed protocol for 10 `/openapi.json` calls; the response bytes are identical. Catches schema-cache invalidation triggered by gc. |
| `TestGlobalRandomSeedIndependence` | `test_health_unchanged_across_random_seeds` | The global `random` module is seeded with values 0–29 before each `/health` call; status field is invariant under seed choice. Restores RNG state in `finally`. Catches any future accidental `random.*` call inside a handler that would produce per-session variance. |
| `TestGlobalRandomSeedIndependence` | `test_post_hello_message_unchanged_across_random_seeds` | Same protocol for 30 `POST /api/hello` calls; the `message` field is invariant under seed choice. |
| `TestGlobalRandomSeedIndependence` | `test_version_body_unchanged_across_random_seeds` | Same protocol for 30 `GET /api/version` calls; the *entire* body is byte-identical under seed choice. `/api/version` has no timestamp field, so any accidental random injection anywhere in the body would surface here first. |

### Why these specific edges?

Each new class targets a regression vector that existing flakiness guards do
**not** reach:

- **Concurrent schema fetch (hot + cold cache)** — `TestOpenAPISchemaByteStability`
  pins sequential reads of the cached schema. Neither the hot-cache concurrent
  path (could a future change wire schema generation to per-request state?) nor
  the cold-cache path (the first wave of requests after a deploy regenerates
  the schema in parallel) is covered. A non-deterministic generator would only
  surface intermittently and only during the cold-cache window — exactly the
  kind of bug that "passes in CI, fails in prod first hour after deploy".

- **Mixed-method concurrent fan-out** — `TestConcurrentIdenticalInputDeterminism`
  interleaves a handler with itself. That catches per-handler races but not
  cross-handler ones. A regression that mutated a module-level dict in one
  handler and read it in another would pass every existing test but trip this.

- **GC-bracketed invariance** — CPython's garbage collector fires on allocation
  thresholds that depend on the order in which prior tests ran. Any handler
  that ever stored an `id(obj)`-keyed cache would produce different responses
  across runs depending on when gc fired — a textbook intermittent failure.
  Forcing `gc.collect()` between calls turns this from "Heisenbug" into
  "deterministic test failure".

- **Global RNG seed independence** — `pytest-randomly` (already enabled in
  this project) reseeds `random` on every session. If a handler ever consults
  the global RNG, two runs of the same test produce different outputs and the
  test goes flaky. Seeding `random` explicitly inside the test bracket lets us
  *prove* the handler doesn't consult it.

### Verification

- 421 backend tests (412 → 421) pass 3× in sequence with no flakiness
  (~2.4s per isolated `test_flakiness_guards.py` run, ~7.5s full-suite run).
- The 9 new tests were run 3× in isolation to confirm they themselves are not
  flaky before the full-suite run.
- Backend line and branch coverage stays at 100% (36/36 statements + branches,
  no production code touched).
- 91 frontend tests still pass (no frontend changes this run).
- `ruff format`, `ruff check --fix`, and `mypy` all pass clean.

---

## 2026-06-07 — QA Agent: regression-prevention session (issue #283)

**Backend at 100% line + branch coverage (36/36).** Sunday's focus is
behavioural pinning of a contract this week's commits (#265–#281) exercise but
leave unasserted. A grep audit of the 630-test suite found the `405`
`Allow`-header surface under-pinned: Wednesday's HEAD→405 pin
(`test_routing_integration_gaps.py`) only does a substring check —
`"GET" in allow` — on `/health`. Adds **1 new test class (32 parametrised
tests) to `backend/tests/test_regression_prevention.py`** pinning the exact
`Allow`-header value across the whole route surface. Backend tests 630 → 662,
green on 3 consecutive runs (~6.3s each); coverage stays 100%.

### Test class added

| Class | Tests | What it pins / why it matters |
|---|---|---|
| `TestMethodNotAllowedAllowHeaderExactSurface` | 32 | The 405 `Allow` header equals **exactly** `GET` for every disallowed method (DELETE/PUT/PATCH) on every route — and, crucially, `/api/hello` advertises only `GET` even though its `POST` is a valid 200. `@app.get`/`@app.post` register `/api/hello` as two separate `APIRoute` objects, so Starlette builds `Allow` from the first path-matching route and silently drops `POST`. Wednesday's substring `"GET" in allow` pin on `/health` would survive a stray extra method, a per-route value change, or this surprising `POST` omission flipping to the union `GET, POST` under a Starlette upgrade. Also pins: `Allow` is always present on a 405 (RFC 7231 §7.4.1 MUST), never leaks onto a 2xx response, is absent on a 404 (keeping "wrong method" vs "no resource" machine-distinguishable), is request-method-independent (describes the route, not the request), and holds the exact `Allow: GET` value over the real ASGI transport. |

### Why this gap?

The `Allow` header is the wire-level, machine-readable advertisement of a
route's method surface — read by HTTP clients deciding a fallback request, by
API-diff tooling, and by OpenAPI-vs-runtime auditors. The existing suite pins
its presence (substring, one route) but never its **exact value route-wide**
nor the **`POST` omission on `/api/hello`** that makes it a genuine framework
gotcha. Pinning both directions means a Starlette upgrade that aggregates
partial matches into `GET, POST`, or a refactor merging the two handlers into
one multi-method route, fails the most distinctive test rather than silently
changing the advertised surface.

### Verification

- 662 backend tests (630 → 662) pass 3× in sequence (~6.3s each).
- `app/main.py` line + branch coverage stays at 100% (36/36) — no source change.
- `ruff format` / `ruff check --fix` / `mypy` all clean.

## 2026-05-31 — QA Agent: regression-prevention session (issue #260)

**Backend and frontend already at 100% line + branch coverage.** Sunday's focus
is behavioural pinning of contracts that this week's commits (#242–#258)
exercise but leave unasserted. Adds **7 new test classes (41 parametrised
tests) to `backend/tests/test_regression_prevention.py`** targeting orthogonal
gaps surfaced by a grep audit of the existing 491-test suite. All 532 backend
tests pass three consecutive runs (~13.0s each) after the change.

### Test classes added

| Class | Tests | What it pins / why it matters |
|---|---|---|
| `TestHelloResponseKeysAreExactlyDocumentedSet` | 3 | The GET and POST `/api/hello` JSON body key set is **exactly** `{"message", "timestamp"}`, and a stowaway field on the request body (`{"name":"Alice","stowaway":"X"}`) does not leak into the response body or text. `test_hello_name_extra_fields_ignored` only checks that `"Alice" in message` — never the response key set. A refactor like `return {**request.model_dump(), ...}` would pass the existing extras-ignored test today (because `response_model=HelloResponse` filters the output) but slip through if `response_model=` were ever dropped. |
| `TestResponseHeaderHygieneAcrossAllRoutes` | 16 | Extends Saturday's four-header hygiene contract (`Set-Cookie`, `X-Powered-By`, `Strict-Transport-Security`, `X-Frame-Options`) from `GET /health`-only to `GET /api/version`, `GET /api/hello`, `POST /api/hello`, and `GET /openapi.json` — every non-`/health` 200 surface. Catches a regression in which a middleware adds a header on API routes (or only on the schema URL) while leaving `/health` alone. |
| `TestOptionsWithOriginOnlyOmitsExposeHeaders` | 1 | The Wednesday Expose-Headers pin covers GET / POST / *real* preflight (Origin + ACRM). The fourth CORS response shape — OPTIONS with Origin only, no ACRM, classified as a non-preflight, routed to 405, then CORS-wrapped on the way out — is structurally distinct and never checks Expose-Headers. Pins the absence on that wrap-on-the-way-out path. |
| `TestErrorResponseContentLengthMatchesBody` | 3 | `Content-Length` equals `len(response.content)` on the 422 (POST `/api/hello` no body), 404 (spurious URL), and 405 (DELETE `/health`) error responses. Saturday's match test enumerates five 200 routes only; FastAPI / Starlette emit error responses through *separate* handlers, so a future custom error envelope could drift on the header without touching success paths. |
| `TestErrorResponsesAlsoOmitForbiddenHeaders` | 12 | The Saturday four-header hygiene list applies on 422 / 404 / 405 too. An error-formatting middleware that emitted `Set-Cookie: trace_id=...` for debug visibility would be invisible to every 200-only pin and would surface only when an external monitor inspected the error path. |
| `TestSpuriousURL404IsJSON` | 5 | The Sunday-pinned spurious URLs (`/robots.txt`, `/sitemap.xml`, `/`, `/api`, `/api/`) return JSON `{"detail": "Not Found"}` with `Content-Type: application/json`, not HTML. The existing pin only checks `status == 404`; a static-files middleware mounting a friendly `404.html` would still pass status but break every JSON consumer that introspects `error.detail`. |
| `TestCORSPreflightContentLengthMatchesBody` | 1 | The 200 preflight response declares `Content-Length` equal to body byte length. Saturday's length-match test deliberately enumerates five non-OPTIONS routes; the preflight has its own (empty) body and its own Content-Length header, generated by `CORSMiddleware` rather than a route handler — a different code path that could drift independently. |

### Why these specific gaps?

Each gap was located by a two-step audit:

1. Read the past week's seven merged PRs (Mon #242 → Sat #258), noting the
   surface each one extended.
2. For each new pin, identify an orthogonal axis the PR left uncovered (a
   different route, a different status code, a different response shape).

The result is seven classes that each pin **the same kind of behaviour the
parent PR pinned, applied to the surface that PR didn't reach.** This is the
highest-yield regression-prevention pattern: it doesn't reinvent contracts, it
generalises proven ones — so when a future refactor touches the underlying
mechanism, the pin fails at the most distinctive call site rather than five
unrelated tests "going weird" simultaneously.

### Verification

- 532 backend tests (491 → 532) pass 3× in sequence:
  13.37s, 12.79s, 12.93s — no flakiness.
- The 41 new tests were run in isolation under `-v` first to confirm they
  produce the expected pass and identify each parametrisation by id.
- Backend line + branch coverage stays at 100% (36/36; no production code
  touched).
- 91 frontend tests still pass (no frontend changes this run).
- `ruff format`, `ruff check --fix`, and `mypy` all pass clean.

## QA Run: Friday 2026-06-05 — test-refactoring (issue #277)

**Focus:** test-refactoring — establish a single source of truth for the
backend's CORS *origin* constants. The suite has grown to 618 tests across 13
files; the allow-listed loopback origin and several disallowed-origin literals
were still inlined or redefined per-file, so an origin change would be a
multi-file edit and the constants could silently drift apart.

**No new tests added.** All 618 backend tests pass unchanged at 100% line and
branch coverage, 3× in a row (9.95s / 9.96s / 10.57s).

### Constant centralised in `backend/tests/conftest.py`

| Name | Replaces |
|------|----------|
| `LOOPBACK_ORIGIN = "http://127.0.0.1:3000"` | The second allow-listed CORS origin, previously defined as a file-local constant in `test_integration_gaps.py` and inlined as a string literal twice in `test_main.py`. Now imported from conftest so both allow-listed origins live beside `LOCALHOST_ORIGIN`. |

### Duplication / drift removed

| Pattern | Before | After |
|---------|--------|-------|
| `LOOPBACK_ORIGIN` definition | 1 file-local def (`test_integration_gaps.py`) + 2 inline `"http://127.0.0.1:3000"` literals (`test_main.py`) | 1 canonical def in `conftest.py`, imported everywhere |
| File-local `DISALLOWED_ORIGIN = "http://evil.example"` shadowing conftest's `"https://evil.example.com"` | 1 (`test_integration_gaps.py`) | 0 — now imports the conftest constant. Both values are disallowed, so the negative-CORS assertions (no `access-control-allow-origin` header) are unchanged; verified green 3×. This completes the unification the 2026-05-22 refactor deliberately deferred. |
| Inline `"http://localhost:3000"` / `"https://evil.example.com"` literals in `test_edge_cases.py` CORS-on-`/openapi.json`-and-`/docs` tests | 3 | 0 — use `LOCALHOST_ORIGIN` / `DISALLOWED_ORIGIN` |

**Intentionally left literal:** `test_app_instance_invariants.py::EXPECTED_CORS_KWARGS`
keeps its hard-coded `["http://localhost:3000", "http://127.0.0.1:3000"]` allow-list.
That test is an independent invariant pin on the app's middleware configuration; deriving
it from the same shared constant it guards would defeat the pin's purpose.

### Verification

- 618 backend tests pass 3× in sequence (9.95s / 9.96s / 10.57s) — no flakiness.
- Backend line + branch coverage stays at 100% (36/36; no production code touched).
- `ruff format`, `ruff check --fix`, and `mypy` all pass clean.

---

## QA Run: Saturday 2026-06-06 — edge-cases (issue #280)

`app/main.py` is already at 100% line + branch coverage, so this run targets a
*behavioural* error-path gap: the precise **Pydantic-v2 validation-error
discriminators** returned in 422 `detail` items. Existing tests pin the 422
status, the `detail` list shape, and the *presence* of `loc`/`msg`/`type` keys —
but nothing pinned their **values**, which are the machine-readable contract that
generated clients branch on to distinguish "required field" from "wrong type"
from "malformed JSON" and to map an error back to the offending input.

### Backend — `backend/tests/test_edge_cases.py` (1 new class, 12 new tests)

#### `TestValidationErrorDiscriminators`

| Test | Pins |
|------|------|
| `test_missing_name_discriminator_is_missing` | Absent `name` → `type=="missing"`, `loc==["body","name"]`, exactly one error |
| `test_wrong_type_name_discriminator_is_string_type` (7 params: null, int, float, bool×2, array, object) | Every non-string `name` → `type=="string_type"`, `loc==["body","name"]` |
| `test_top_level_array_body_discriminator_is_model_attributes_type` | JSON-array body → `type=="model_attributes_type"`, `loc==["body"]` (bare, no field suffix) |
| `test_top_level_null_body_discriminator_is_missing` | Literal `null` body → `type=="missing"`, `loc==["body"]` (whole body absent, distinct from empty-object) |
| `test_malformed_json_discriminator_is_json_invalid` | Non-JSON bytes → `type=="json_invalid"`, `loc` rooted at `"body"` |
| `test_every_detail_item_carries_a_nonempty_msg_string` | Across categories, every `detail` item has a non-empty `str` `msg` |

### Why these specific edges?

The `type` discriminator and `loc` path are the only stable, machine-readable
parts of a 422 body — a client cannot reliably switch on `msg` (prose Pydantic
revises between minor versions, so `msg` is asserted non-empty but not pinned).
A Pydantic major upgrade, a swap of the request model, or an accidental
`str | int` widening of `name` would flip a discriminator while keeping the
status at 422 and the key-presence tests green, silently breaking every client
that branches on `error["type"]`. These tests fail first.

### Verification

- 12 new tests pass 3× in sequence — no flakiness.
- Full backend suite: 630 tests pass 3× (≈14s each).
- Backend line + branch coverage stays at 100% (36/36; no production code touched).
- `ruff format`, `ruff check`, and `mypy` all pass clean.

---

## QA Session — 2026-06-08 (Monday: coverage-sprint)

### Frontend — `frontend/__tests__/page.test.tsx` (1 new test)

#### `edge cases: submit input boundaries`

| Test | Pins |
|------|------|
| `POSTs the surrounding whitespace verbatim for a padded name (no client-side trim)` | Submitting `"  Bob  "` sends `{ name: "  Bob  " }` in the POST body — leading/trailing spaces intact, NOT `name.trim()` |

### Why this specific edge?

Both frontends modules are already at **100% line/branch/function coverage**, so a
pure coverage-by-count sprint had nothing to add. The real gap was a **behavioral
path that line coverage marked covered but no assertion pinned**.

`handleSubmit` in `page.tsx` uses `name.trim()` *only* for the empty-guard
(`if (!name.trim()) return;`) but transmits the **raw, untrimmed** state in the
request body (`JSON.stringify({ name })`). Every pre-existing POST-body test used an
already-trimmed name (`'Alice'`, `'TestUser'`, `'A'.repeat(5000)`), so a "cleanup"
regression to `{ name: name.trim() }` would silently change the wire contract and
**all of them would still pass**. The backend is the single source of truth for name
normalization (see `test_whitespace_name_message_format`); the client must send
exactly what the user typed. This test fails first.

### Verification

- New test passes 3× in sequence — no flakiness.
- Mutation check: flipping the body to `{ name: name.trim() }` makes this test (and only this test) fail — confirming it has teeth.
- Full frontend suite: 92 tests pass (was 91).
- `prettier`, `eslint`, and `tsc --noEmit` all pass clean.
- No production code touched; coverage stays at 100%.

---

## QA Session — 2026-06-09 (Tuesday: flaky-hunt)

### Empirical flakiness audit (no flakes found)

Ran the full suites and the timing-sensitive subsets repeatedly, including under
deliberate CPU contention (`yes` load generators), to surface latent flakiness:

| Configuration | Runs | Result |
|---------------|------|--------|
| Full backend suite (`pytest-randomly` reorders each run) | 5× | 662/662 pass |
| Full frontend suite | 5× | 92/92 pass |
| `test_performance.py` under 4-core saturation | 12× | 51/51 pass |
| Tightest perf tests (jitter/p95/p99/throughput/preflight) under 8× oversubscription | 15× | 12/12 pass |
| `test_e2e_performance_scaling.py` under 6× load | 8× | 11/11 pass |

**Conclusion:** the suite is exceptionally well-hardened — timing tests use
outlier-tolerant aggregates (p95/p99, throughput floors, median-with-clamp) with
generous ceilings, so none flake even under heavy contention.

### Fix — hardened the one genuinely flaky *construction*

`backend/tests/test_performance.py`

| Before | After |
|--------|-------|
| `test_30_sequential_posts_each_under_100ms` — asserted `elapsed < 0.1` **inside** the loop, giving 30 independent chances for a single GC/scheduler pause to fail the whole test (canonical flaky multiplier) | `test_30_sequential_posts_per_call_latency_bounded` — collects all 30 timings, tolerates ≤1 outlier over the 100ms per-call ceiling, and bounds the **median** under 50ms |

This **preserves regression-detection power** (a real per-call slowdown lifts
*every* call over the ceiling → fails the outlier check; a bulk regression moves
the median → fails the median check) while removing the single-outlier flake. Net
rigor increases — a median bound is added where there was none.

### New tests — `backend/tests/test_flakiness_guards.py` (4 new)

#### `TestThreadedConcurrencyDeterminism`

Every pre-existing concurrency guard fans out with `asyncio.gather` on a
single-threaded event loop (cooperative interleaving, never two cores at once).
These exercise a genuinely different model — Starlette's sync `TestClient` driven
from a `ThreadPoolExecutor`, so handlers can run **simultaneously** on multiple
cores — which is the only way to surface a shared-mutable-state race whose window
depends on OS thread scheduling.

| Test | Pins |
|------|------|
| `test_threaded_posts_each_receive_their_own_name` | 32 distinct POSTs across a thread pool each echo their own name — no cross-contamination under true parallelism |
| `test_threaded_identical_posts_return_one_message` | 32 identical threaded POSTs collapse to exactly one `message` (no clock/counter/RNG baked into the body) |
| `test_threaded_health_all_healthy` | 32 threaded `/health` calls all report `healthy` (no cross-handler state leak) |
| `test_threaded_mixed_get_post_each_correct_shape` | Interleaved GET/POST on parallel threads each return their own route's shape |

### Verification

- Hardened test passes 10× under 6× CPU load — no flakiness.
- New threaded guards pass 8× under 6× CPU load — no flakiness.
- Full backend suite: 666 tests pass 3× (was 662; +4 threaded, 1 rename).
- `ruff format`, `ruff check`, and `mypy` all pass clean on changed files.
- No production code touched.

## QA Run: Friday 2026-06-19 — test-refactoring (issue #324)

**Focus:** reduce duplication & strengthen assertions in timestamp-ordering tests.

### Refactor — centralise the `fromisoformat(resp.json()["timestamp"])` idiom

Twelve timestamp-ordering/window tests across `test_main.py` and
`test_integration.py` each re-implemented the same two-step idiom: pull the
`timestamp` field out of a JSON response and `datetime.fromisoformat` it. Bare
`fromisoformat` *silently accepts naive (non-UTC) timestamps*, so none of those
ordering tests actually defended the UTC contract they implicitly assumed.

**New conftest helper** — `response_timestamp(response) -> datetime`:
routes every extraction through the existing `assert_utc_iso8601`, so each call
site now additionally asserts the timestamp is a zero-offset UTC ISO 8601 string
and returns the parsed `datetime` for the ordering/window comparisons that
followed. Net: −12 duplicated literals, +12 UTC assertions, zero behaviour lost.

| File | Sites refactored |
|------|------------------|
| `tests/test_main.py` | 4 (`test_health_timestamp_is_iso_format`, successive-timestamp pair, POST request-window, 10-call monotonic) |
| `tests/test_integration.py` | 8 (cross-endpoint user-flow + repeated-flow timestamp tests) |

Also dropped the now-unused `from datetime import datetime` import in
`test_integration.py`.

### New tests — `TestResponseTimestampHelper` (`test_main.py`, 4 new)

Pins the helper's own contract so a regression surfaces with a clear name rather
than as a confusing failure inside an unrelated ordering test. Uses a
`_StubResponse` to test the pure parsing path with no HTTP round-trip.

| Test | Pins |
|------|------|
| `test_returns_parsed_utc_datetime_for_live_response` | Against real `/health`, returns a zero-offset UTC datetime equal to an independent parse of the same string |
| `test_accepts_z_suffixed_utc_timestamp` | `Z`/Zulu suffix parsed as zero-offset (equivalent to `+00:00`) |
| `test_rejects_naive_timestamp` | Naive timestamp raises `AssertionError` — the guarantee the refactor buys for free |
| `test_rejects_non_utc_offset_timestamp` | Aware-but-non-UTC offset (`+05:00`) raises — zero offset enforced, not mere awareness |

### Verification

- New helper tests pass; full backend suite: 773 tests pass 3× (was 769; +4 helper-contract tests).
- `ruff format`, `ruff check`, and `mypy` all pass clean on changed files.
- No production code touched.

---

## Monday (coverage-sprint): Preflight `Access-Control-Allow-Credentials` contract

**Context.** Both backend (`app/main.py`, 100% line+branch, 813 passing) and frontend
(100%) are already fully line-covered, so this sprint targets a *behavioral* gap rather
than line padding. The app sets `allow_credentials=True`, and the CORS **preflight**
(OPTIONS) response carries `Access-Control-Allow-Credentials: true` — but no test asserted
that value on the preflight. `TestCORSCacheCorrectness` pins it only on real GET/POST
responses; `TestCORSPreflightByteDeterminism` reads it off the preflight but asserts only
*determinism* (the value is unchanging), not that it equals `true`. A regression to
`allow_credentials=False` would silently drop the header from the preflight — breaking every
credentialed cross-origin request — while every existing CORS test stayed green.

### New tests — `TestRegressionCORSPreflightContents` (`test_main.py`, 2 new)

| Test | Pins |
|------|------|
| `test_preflight_echoes_allow_credentials_true` | The allow-listed-origin preflight returns 200 and `Access-Control-Allow-Credentials: true` (exact lowercase string per the Fetch standard). Guards against `allow_credentials=False` slipping through with the existing preflight tests still passing. |
| `test_preflight_from_disallowed_origin_is_rejected_without_allow_origin` | A disallowed-origin preflight short-circuits with HTTP 400 and **omits** `Access-Control-Allow-Origin`. Since Starlette emits `Allow-Credentials: true` on every preflight unconditionally, the real cross-origin safety net is the *withheld* `Allow-Origin` (browsers ignore credentials when origin is absent). Guards against loosened origin matching echoing an attacker's origin alongside the always-present credentials grant. |

The class docstring was updated to record exactly which preflight headers are (and were not)
pinned, so the boundary stays explicit for future contributors.

### Verification

- New tests pass 3× with no flakiness; full backend suite: 815 pass, 2 xfailed (was 813+2; +2).
- `ruff format` + `ruff check` clean; 100% line+branch coverage maintained on `app/`.
- No production code touched — test-only change.

## QA Run: Saturday 2026-06-27 — edge-cases (issue #349)

**Context.** Backend `app/main.py` is at 100% line+branch coverage (54 stmts, 6 branches),
so this pass chases a *behavioural* error-path edge, not lines. The non-finite-float
sanitizer (`app.main._replace_non_finite`, shipped #328) is already heavily pinned — but
**every** existing test (`test_edge_cases_error_paths.py::TestNonStandardJSONConstantsDoNotCrash`
and the whole `test_regression_nonfinite_sanitization.py` suite) reaches it through the
**non-standard JSON tokens** `NaN` / `Infinity` / `-Infinity` (RFC 8259 §6 forbids these).
`json.loads` *also* yields a non-finite `float` from an **RFC-8259-valid number literal** that
overflows the IEEE-754 `double` range — `json.loads("1e400") == inf`. That value reaches the
same crash-prone code path (echoed into the 422 `detail[].input`, which a pre-#328
`allow_nan=False` encoder could not serialize → 500) through a **different, syntactically-valid
door**. No test pinned the overflow door; a regression that sanitized only the token path would
ship a silent 500/token-leak for overflowed numbers.

### New tests — `backend/tests/test_numeric_overflow_nonfinite.py` (5 new classes, 12 new tests)

#### `TestOverflowNumberDoesNotCrash`
| Test | Pins |
|------|------|
| `test_overflow_number_returns_clean_422_with_stringified_input` (4 params: `1e400`, `-1e400`, `1e999`, `1E400`) | An overflowing number returns a well-formed 422 (never a 500) and the echoed `input` is the stringified `inf`/`-inf` repr. |

#### `TestOverflowNumberIsValidJSONSyntax`
| Test | Pins |
|------|------|
| `test_overflow_number_is_wrong_type_not_parse_error` | `{"name": 1e400}` is `type=='string_type'` at `loc==['body','name']` — a *validation* failure (it parsed and reached Pydantic), explicitly **not** `json_invalid`. This is the load-bearing distinction from the `Infinity` *token*, which lives in the parse-error bucket. |
| `test_overflow_body_is_genuinely_rfc_valid_json` | Anchors the premise at the parser level: `json.loads("1e400")` succeeds and yields a non-finite `inf` — valid syntax, not a dialect extension. |

#### `TestFiniteHugeNumberBoundaryPreserved`
| Test | Pins |
|------|------|
| `test_finite_huge_number_echoed_as_number_not_string` | The complementary boundary: `1e308` (below `float` max ~1.8e308) stays a finite JSON *number* in the echoed `input` — the sanitizer never over-reaches past the finite/non-finite line by stringifying large-but-finite magnitudes. |

#### `TestNestedOverflowRecursesLikeTokenPath`
| Test | Pins |
|------|------|
| `test_overflow_inside_array_is_selectively_stringified` | `{"name": [1e400, 1.5]}` echoes `["inf", 1.5]` — overflow feeds the same recursive walk as the token path; finite siblings survive. |
| `test_overflow_inside_nested_dict_is_selectively_stringified` | `{"name": {"big": -1e400, "ok": 2}}` echoes `{"big": "-inf", "ok": 2}` — dict recursion over an overflowed value; keys and finite siblings preserved. |

#### `TestOverflowResponseLeaksNoNonStandardTokens`
| Test | Pins |
|------|------|
| `test_response_is_strict_json_with_no_bare_nonfinite_token` (3 params: scalar +/-, nested) | The 422 body carries no bare `Infinity`/`NaN` token and round-trips through a strict `json.loads(..., parse_constant=...)` decoder — so a strict client parser (`JSON.parse`) accepts it. |

### Why this specific edge?

The overflow path is a *realistic* client mistake (a hand-rolled serializer or template emitting
a huge magnitude) and an RFC-8259-valid one, unlike the `Infinity` token that every existing test
uses. It exercises the same 500-prone sanitizer code through a syntactically-valid entry point, so
a regression that special-cased only the named tokens — or that drew the finite/non-finite line in
the wrong place — would slip past the entire existing non-finite suite. The finite-boundary pin
(`1e308`) gives the overflow pins their meaning by drawing the line exactly at IEEE-754 max.

### Verification

- New tests pass 3× across randomized seeds with no flakiness; full backend suite: 885 pass, 2 xfailed (was 873+2; +12).
- `ruff format` + `ruff check` clean; `mypy` clean; 100% line+branch coverage maintained on `app/`.
- No production code touched — test-only change.

---

## QA Run: Wednesday 2026-07-01 — integration-gaps (issue #362)

Backend line + branch coverage of `app/main.py` was already **100%**, so this run targeted an
*integration* gap: a behaviour spanning **two independently-served endpoints** that no existing
test pinned.

### Gap — runtime cross-endpoint version consistency

A client can learn the API version two ways: the runtime endpoint `GET /api/version` (`.version`)
and the served contract `GET /openapi.json` (`.info.version`). Both derive from `app.__version__`
today, but that shared origin is an implementation detail — from a black-box client's perspective
they are two separate responses from two separate code paths (a hand-written handler vs. FastAPI's
schema generator). Existing coverage pinned each surface *in isolation*: `test_openapi_schema_metadata`
ties `info.version` to the `__version__` **source constant**, and `TestAPIContractVersion` pins the
`/api/version` response *shape*. Nothing compared the two **runtime responses** to each other, nor
across the sync/async transports. A future change that hardcoded a version in one path would drift
the documented API version from the served one, undetected.

### New tests — `backend/tests/test_version_consistency_integration.py` (1 new class, 4 new tests)

#### `TestRuntimeVersionConsistencyAcrossEndpoints`
| Test | Pins |
|------|------|
| `test_api_version_matches_served_openapi_info_version` | The core black-box guarantee: `GET /api/version` `.version` is byte-identical to `GET /openapi.json` `.info.version`. No `__version__` import — pins the contract a real client observes. |
| `test_version_consistency_is_stable_across_repeated_requests` | Both surfaces report a single, unchanging version across 5 interleaved calls each — guards against a per-request version (timestamp/PID/random), making the agreement a stable property rather than a one-shot coincidence. |
| `test_api_version_matches_openapi_over_async_transport` | The same cross-endpoint agreement holds over the async ASGI transport, whose call machinery differs from `TestClient`. |
| `test_version_agrees_across_both_endpoints_and_both_transports` | The strongest form: all four (endpoint × transport) reads collapse to a single value — transport choice never leaks into the advertised version and the two endpoints never diverge on either transport. |

### Why this gap

Version drift between a running service and its advertised contract is a classic, silent
integration failure: unit tests pass because each endpoint is correct alone, yet a client trusting
the OpenAPI schema to know the deployed version is misled. These black-box pins catch that class of
regression at the HTTP boundary — the layer a real consumer sees.

### Verification

- New tests pass 3× with no flakiness; full backend suite: 905 pass, 2 xfailed (was 901 + 2; +4).
- `ruff format` + `ruff check` clean; 100% line + branch coverage maintained on `app/`.
- No production code touched — test-only change.

---

## QA Run: Saturday 2026-07-04 — edge-cases (issue #371)

Backend line + branch coverage of `app/main.py` was already **100%**, so this run hunted an
*unpinned error-path behaviour* — and surfaced a genuine **latent `500` defect** the suite had
itself flagged with an `xfail(strict=True)`. Unlike prior edge-case runs, this one **fixes
production code**, not just tests.

### Defect — lone UTF-16 surrogate escapes crashed the server (HTTP 500)

A request body such as `{"name":"\uD83D"}` (a high surrogate with no paired low surrogate) is
accepted by the JSON *decoder* into a Python `str` holding an unpaired surrogate. That value
satisfies the `name: str` annotation, so it flowed through the handler unchecked and only failed
when the *response* was serialized: a lone surrogate cannot be UTF-8-encoded, so `JSONResponse`
raised an unhandled `UnicodeEncodeError` → **500**. A 500 on parseable client input is a
DoS-shaped defect — any client that emits an unpaired surrogate could take the endpoint down.
`tests/test_request_body_encoding_edges.py` had documented the desired contract (status < 500)
under `xfail(strict=True)`, waiting for a fix.

### Fix — `backend/app/main.py`

1. **Reject at validation time.** `HelloRequest` gains a `field_validator` that rejects any `name`
   holding an unpaired surrogate (keyed off UTF-8 encodability), converting the latent 500 into a
   clean **422** *before* the handler builds a response it cannot encode. Legal surrogate *pairs*
   (which decode to real astral characters like `😀` and are UTF-8-encodable) are unaffected.
2. **Sanitize the error echo.** `_replace_lone_surrogates` rewrites any lone surrogate that the
   validation-error payload would otherwise echo back in `detail[].input` to its ASCII
   `backslashreplace` form — because that echo would itself re-trigger the same encode failure and
   turn the 422 back into a 500. This mirrors the existing `_replace_non_finite` sanitizer for
   non-finite floats.

### New / changed tests

#### `backend/tests/test_lone_surrogate_rejection.py` (new — 3 classes, 25 tests)
| Class | Pins |
|-------|------|
| `TestLoneSurrogateBodyReturns422` | Every unpaired-surrogate shape (min/max high & low surrogate, embedded between ASCII, reversed pair) returns a well-formed 422; the discriminator is `value_error` at `loc==['body','name']`; the 422 body re-parses and its echoed `input` carries no raw surrogate code point. |
| `TestLegalSurrogatePairStillAccepted` | Legal surrogate pairs and raw-UTF-8 astral characters still round-trip with 200 — the validator does not over-reject. |
| `TestReplaceLoneSurrogatesUnit` | Direct pins on the pure `_replace_lone_surrogates` recursion: scalar backslash-escaping, passthrough of encodable/non-string values, nested dict/list recursion, and input-not-mutated. |

#### `backend/tests/test_request_body_encoding_edges.py` (changed)
`TestMalformedInputNeverCrashesServer` — the `xfail(strict=True)` marker was **removed** now that
the fix is in place, and `test_lone_surrogate_escape_does_not_return_5xx` was renamed to
`test_lone_surrogate_escape_returns_clean_422` and strengthened to pin the exact 422 status, the
`detail` list shape, and the sanitized string `input`.

### Verification

- New tests pass 3× with no flakiness; full backend suite: **949 pass, 0 xfailed** (was 922 pass +
  2 xfailed; the 2 xfails flipped to real passes and 25 new tests were added).
- `ruff format` + `ruff check` clean; `mypy` clean; 100% line + branch coverage maintained on `app/`
  (now covering the new validator and sanitizer).
- **Production code touched** — `app/main.py` fixes a latent 500 → clean 422.

---

## QA Run: Monday 2026-07-06 — coverage-sprint (issue #377)

### Context — coverage already saturated, so this sprint closes a *behavioral* gap

Backend `app/main.py` and the frontend already sit at **100% line + branch coverage** (960 backend
tests, 96 frontend tests before this run; the workflow's "current coverage: 12" is a stale
hardcoded default, not a measurement). Padding line coverage would add no value. Instead this run
pins an untested **interaction** between two existing sanitizers.

### Gap — the two request-body sanitizers were never exercised *together*

`app.main.validation_exception_handler` rebuilds an un-encodable 422 payload through a chain of
two sanitizers:

```python
_replace_lone_surrogates(_replace_non_finite(jsonable_encoder(exc.errors())))
```

Each fixes a distinct crash: `_replace_non_finite` stringifies `NaN`/`Infinity`/`-Infinity` (which
a strict `allow_nan=False` encoder rejects), and `_replace_lone_surrogates` rewrites lone UTF-16
surrogates (which cannot be UTF-8-encoded). Every existing suite sends **exactly one** defect kind
per request — `test_nonfinite_toplevel_body.py` only non-finite floats, `test_lone_surrogate_
rejection.py` only lone surrogates. **No test sent a body carrying both**, so the *composition* —
required whenever one malformed payload holds both a non-finite float and a lone surrogate — was
unverified. A regression that ran only one sanitizer, short-circuited on the first defect, or let
one pass clobber the other's output would 500 on such a body while the whole existing single-defect
suite stayed green.

### New tests — `backend/tests/test_combined_sanitizer_composition.py` (2 classes, 12 tests)

#### `TestBothDefectsInOneRequestBodyYieldCleanResponse` (7 tests)

Drives the handler over HTTP with bodies that carry **both** defect kinds at once; each asserts a
clean 422 whose response body is both strict-JSON (no `NaN`/`Infinity` token survives a
`parse_constant` decoder) *and* UTF-8-encodable (no raw surrogate survives).

| Test | What it validates |
|------|-------------------|
| `test_top_level_array_root_with_both_defects` (3 params: NaN/Infinity/-Infinity) | Body `[<non-finite>, "\uD83D"]` — a top-level array is echoed whole as `input`, exercising the **list-recursion** branch of both sanitizers on one value. |
| `test_missing_name_object_with_both_defects_in_values` (3 params) | Body `{"a": <non-finite>, "b": "\uD83D"}` (no `name`) — the whole dict is echoed, exercising the **dict-value** branch a "walk only lists / special-case name" sanitizer would miss. |
| `test_nested_dict_under_name_with_both_defects` | Body `{"name": {"deep": NaN, "s": "\uD83D"}}` — both defects one level deep inside a field's echoed input. |
| `test_lone_surrogate_in_object_key_alongside_nonfinite_value` | Body `{"\uD83D": Infinity}` — the one shape needing surrogate-sanitization on a dict **key** and non-finite-sanitization on the paired value simultaneously. |

#### `TestSanitizerCompositionIsSerializable` (5 tests)

Pure-function pins on `_replace_lone_surrogates ∘ _replace_non_finite` over a payload holding both
defect kinds at several nesting depths.

| Test | What it validates |
|------|-------------------|
| `test_composition_output_is_json_response_encodable` | The chained output survives the exact encoding `JSONResponse` performs — `json.dumps(..., allow_nan=False, ensure_ascii=False).encode("utf-8")` — and re-parses under a strict decoder. |
| `test_composition_removes_both_defect_kinds` | No non-finite float and no raw surrogate code point remain anywhere in the result. |
| `test_composition_is_order_independent` | Applying the two sanitizers in either order yields the same result — their domains are disjoint, so neither can clobber the other's fix. |
| `test_composition_does_not_mutate_input` | Both passes build new containers; the caller's original payload still holds the raw defect values (no in-place corruption of the echoed errors). |

### Why this gap matters

The composition is what actually runs in production for any single malformed body that trips both
encoders at once. A mutation sanity check confirms the guard bites: bypassing `_replace_lone_
surrogates` makes `POST /api/hello` with body `[NaN, "\uD83D"]` return **500**, which these tests
turn into a loud failure.

### Verification

- New tests pass 3× with no flakiness; full backend suite: **972 pass** (was 960; +12 new tests).
- `ruff format` + `ruff check` clean; 100% line + branch coverage maintained on `app/`.
- **No production code changed** — this run adds regression pins only.

---

## QA Session — 2026-07-09 (Thursday: e2e-performance)

### New tests — `backend/tests/test_e2e_sanitized_error_path_performance.py` (3 classes, 8 tests)

Focus: **e2e-performance**. `app/` is already at 100% line + branch coverage, so this run closes a
*behavioral* perf gap rather than padding coverage. Five perf suites already pin a broad surface, and
the error path is *partially* covered (`test_performance.py` sequential 422/404/405 latency;
`test_e2e_performance_scaling.py` interleaved 200/422 batch + concurrent 422 p95). But every one of
those error-path guards triggers the **plain** validation path (missing field / wrong type), whose
echoed `input` is already JSON-safe — so FastAPI's default handler succeeds and the handler's
`except ValueError` **rebuild branch never runs**. That branch
(`_replace_lone_surrogates(_replace_non_finite(jsonable_encoder(exc.errors())))`) runs the two
**recursive** sanitizers that exist to stop malformed, attacker-controlled input from 500-ing the
server. No perf test measured its latency, its scaling, or its fairness — a quadratic/blocking
regression there would be a DoS vector invisible to the whole suite.

#### `TestSanitizedRebuildBranchTailLatency` (3 tests)

Fires branch-forcing bodies concurrently and bounds the 422 tail. Each response passes a correctness
gate (`_assert_clean_sanitized_422`): status 422 **and** the raw response bytes re-parse under a
strict decoder that rejects `NaN`/`Infinity` — so a fast pass can't be bought by crashing or by
leaking a bare non-standard token on the wire.

| Test | What it validates |
|------|-------------------|
| `test_concurrent_nonfinite_422_p95_bounded` | 100-wide concurrent `{"name": [NaN, 1, Infinity, -Infinity]}` fan-out — p95 of the `_replace_non_finite` rebuild path stays under ceiling. |
| `test_concurrent_nonfinite_422_p99_bounded` | Same fan-out, p99 — a deeper tail than any existing error-path guard (which stop at p95). |
| `test_concurrent_surrogate_422_p95_bounded` | 100-wide concurrent lone-surrogate (`["\uD83D", ...]`) fan-out — drives the *second* recursive sanitizer, `_replace_lone_surrogates`, under the same load. |

#### `TestSanitizerScalesWithStructureSize` (2 logical tests, 4 cases)

The recursive sanitizers walk the entire echoed structure, so their cost is an attacker-controlled
knob. Scales a single non-finite array across 10 → 2000 elements (200x) and pins the curve's shape.

| Test | What it validates |
|------|-------------------|
| `test_each_structure_size_under_largest_ceiling` (3 params: 10/200/2000 elems) | Median rebuild-branch latency at every sampled size stays under the absolute ceiling. |
| `test_latency_grows_sub_quadratically_with_structure_size` | median(2000 elems) / median(10 elems) stays below a 60x cap — separates a linear recursive walk from an O(N²) regression (which would push the ratio toward the ~40000x square of the size ratio). |

#### `TestRebuildBranchFairnessVsPlainPath` (1 test)

| Test | What it validates |
|------|-------------------|
| `test_rebuild_p95_within_factor_of_plain_p95_in_mixed_fanout` | Interleaves rebuild-branch 422s (non-finite body) and plain missing-field 422s in one fan-out; the rebuild p95 must stay within 10x the plain p95 — isolating the *extra* cost of the rebuild branch, so a regression that made only that branch block the loop fails here while every plain-path guard still passes. |

### Why this gap matters

The rebuild branch is the exact code written to keep malformed input from crashing the server; a
perf regression in its recursive sanitizers is a denial-of-service vector. Mutation checks confirm
the correctness gate bites: neutering `_replace_non_finite` makes the concurrent non-finite test
fail with `ValueError: Out of range float values are not JSON compliant`, and neutering
`_replace_lone_surrogates` makes the surrogate test fail with `UnicodeEncodeError` — both a 500 the
gate turns into a loud failure.

### Verification

- New tests pass 3× with no flakiness; full backend suite: **995 pass** (was 987; +8 new tests).
- `ruff format` + `ruff check` + `mypy` clean; 100% line + branch coverage maintained on `app/`.
- **No production code changed** — this run adds regression pins only.

## QA Run: Sunday 2026-07-12 — regression-prevention (issue #397)

### Context — coverage saturated; this run closes a *boundary* gap on a recent fix

`app/main.py` is already at 100% line + branch coverage, so this regression-prevention run
targets a behavioral boundary rather than an uncovered line. Reviewing recent fix commits,
`3c81af3` (#372) added the `HelloRequest.name` `field_validator` that rejects unpaired UTF-16
surrogates while keeping legal surrogate *pairs* accepted, and `c0a816a` (#375) extended the
echo sanitizer to object keys.

### Gap — the accept-side of #372 was pinned only at a mid-range code point

The **reject-side** of #372 is pinned exhaustively (`test_lone_surrogate_rejection.py`,
`test_regression_surrogate_object_keys.py`, `test_combined_sanitizer_composition.py`). The
**accept-side** — legal astral characters must NOT be rejected — was pinned at a single
mid-range scalar (😀 / U+1F600). The **boundaries** of the valid astral range were untested:
U+10000 (first astral, UTF-16 `𐀀` — min high + min low surrogate) and **U+10FFFF**
(the *maximum* valid Unicode scalar, UTF-16 `􏿿` — max high + max low surrogate).

### New tests — `backend/tests/test_regression_astral_boundary_names.py` (3 classes, 8 tests)

| Test | What it validates |
|------|-------------------|
| `TestBoundaryAstralPairAcceptedViaEscape::test_boundary_pair_round_trips_200` (2 params: U+10000, U+10FFFF) | A boundary surrogate-pair `\uXXXX` escape decodes to its scalar and echoes with 200; pins the accept-side all the way to the maximum valid code point. |
| `TestBoundaryAstralPairAcceptedViaEscape::test_200_body_bytes_are_utf8_clean` (2 params) | The raw 200 response bytes UTF-8-decode and contain the literal astral scalar — no lone surrogate leaks into the success path. |
| `TestBoundaryAstralAcceptedViaRawUtf8::test_raw_utf8_boundary_char_round_trips_200` (2 params) | The same boundary scalars sent as native UTF-8 bytes (the real-client path via `httpx json=`) are accepted and echoed (200). |
| `TestLoneSurrogateRejectionContractStable::test_unpaired_surrogate_still_rejected_with_stable_contract` | A lone `\uD83D` still yields 422 with the stable client-facing contract: `type=='value_error'`, `loc==['body','name']`, and the exact `msg` string. |
| `TestLoneSurrogateRejectionContractStable::test_rejection_message_does_not_leak_the_offending_value` | The rejection `msg` is static and carries no raw surrogate code point — a future message that interpolated the value would re-introduce the #372 encode crash via `msg`. |

### Why this gap matters

U+10FFFF is the maximum valid Unicode scalar — a boundary the mid-range emoji test can never
reach. A plausible over-correction of #372 (e.g. keying off the UTF-16 representation and
rejecting anything needing a surrogate pair, or clamping below U+10FFFF) would wrongly 422
legitimate astral input while the mid-range 😀 test stayed green. A mutation check confirms the
teeth: replacing the validator's UTF-8-encodability check with a UTF-16 surrogate-unit scan
makes 7 of the 8 new tests fail (the reject-contract test correctly still passes).

### Verification

- New tests pass 3× with no flakiness; full backend suite: **1033 pass** (was 1025; +8 new tests).
- `ruff format` + `ruff check` + `mypy` clean; 100% line + branch coverage maintained on `app/`.
- **No production code changed** — this run adds regression pins only.

## QA Run: Wednesday 2026-07-15 — integration-gaps (issue #407)

### Context — coverage saturated; this run closes a request→response *behavior* gap

`app/main.py` is at 100% line + branch coverage, so the integration-gaps focus targets an
untested *integration behavior* rather than an uncovered line. The app registers **no** caching
or compression middleware, yet real clients (browsers, CDNs, generated SDKs) routinely attach
conditional-request and content-negotiation headers to every GET.

### Gap — the *behavioral* neutrality of conditional/negotiation request headers was unpinned

`test_regression_prevention.py` pins the **absence** of `Cache-Control` / `ETag` / `Expires`
*response* headers (the emission side). What was never pinned is the request-side *behavior*
those absent headers imply:

- No test sent `If-None-Match` / `If-Modified-Since`, so nothing guaranteed the server never
  short-circuits to a `304 Not Modified` — which would starve clients of the fresh per-request
  `timestamp` these dynamic endpoints exist to serve.
- No test sent `Accept-Encoding: gzip`, so nothing guaranteed no compression layer silently
  compresses the body or adds `Vary: Accept-Encoding`. A `GZipMiddleware` regression would slip
  past every existing ETag/Cache-Control assertion because GZip emits **neither** of those.

### New tests — `backend/tests/test_content_negotiation_integration_gaps.py` (6 classes, 33 tests)

| Test | What it validates |
|------|-------------------|
| `TestConditionalRequestNeverReturns304::test_if_none_match_wildcard_returns_200` (×3 paths) | `If-None-Match: *` on every GET route yields a full `200`, never `304`. |
| `TestConditionalRequestNeverReturns304::test_if_none_match_specific_etag_returns_200` (×3) | A concrete ETag the app never minted still yields `200`. |
| `TestConditionalRequestNeverReturns304::test_if_modified_since_future_returns_200` (×3) | A far-future `If-Modified-Since` yields `200` (no `Last-Modified` to beat). |
| `TestConditionalRequestNeverReturns304::test_all_conditional_headers_combined_returns_200` (×3) | `If-None-Match` + `If-Modified-Since` together still yield `200`. |
| `TestConditionalRequestServesFreshBody::*` (4 tests) | Conditional GETs return the *full, fresh* body (healthy status, 3-field version payload, greeting) with a live UTC timestamp; two back-to-back conditional GETs are *both* full `200`s (rules out warm-on-first/304-on-second). |
| `TestConditionalRequestDoesNotBlockWrites::*` (2 tests) | Conditional headers on `POST /api/hello` never suppress body processing — the greeting is still returned. |
| `TestAcceptEncodingDoesNotCompress::*` (4 tests ×3 paths) | A gzip-accepting GET returns no `Content-Encoding` header, a body that parses as plain JSON, a `Content-Length` equal to the uncompressed body, and no `Accept-Encoding` token in `Vary`. |
| `TestAcceptEncodingNeutralityOnPost::test_post_hello_gzip_accept_yields_uncompressed_greeting` | `POST /api/hello` with `Accept-Encoding: gzip` returns the plain, uncompressed greeting. |
| `TestContentNegotiationAsyncTransportParity::*` (2 tests) | Conditional-GET-returns-200 and gzip-request-uncompressed both hold over the real-ASGI async transport. |

### Why this gap matters

A `304`-shaped caching regression or a `GZipMiddleware` addition are both plausible future
changes that current assertions would miss: GZip emits neither `ETag` nor `Cache-Control`, so
the existing emission-side pins are blind to it. These behavioral pins fail loudly if either
appears, while the async-transport parity tests catch a middleware that behaves differently on
the async path.

### Verification

- New tests pass 3× with no flakiness; full backend suite: **1082 pass** (was 1049; +33 new tests).
- `ruff format` + `ruff check` + `mypy` clean; 100% line + branch coverage maintained on `app/`.
- **No production code changed** — this run adds integration-behavior pins only.
