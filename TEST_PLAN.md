# Test Plan

Documents test coverage, test descriptions, and quality improvements.

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
| `test_openapi_health_response_schema_matches_actual_response` | OpenAPI HealthResponse fields equal the fields actually emitted by /health — catches drift if a field is added to the response but not the model (or vice versa) |
| `test_openapi_version_response_schema_matches_actual_response` | OpenAPI VersionResponse fields equal the fields actually emitted by /api/version |
| `test_openapi_get_hello_response_schema_matches_actual_response` | OpenAPI HelloResponse fields equal the fields actually emitted by GET /api/hello |
| `test_openapi_post_hello_response_schema_matches_actual_response` | OpenAPI HelloResponse fields equal the fields actually emitted by POST /api/hello |

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
