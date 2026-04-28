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
| `test_health_timestamp_is_timezone_aware` | Health timestamp parses as a timezone-aware datetime (not naive) |
| `test_health_timestamp_utc_offset_is_zero` | Health timestamp UTC offset is exactly zero seconds (true UTC) |
| `test_hello_get_timestamp_is_utc_aware` | GET /api/hello timestamp is timezone-aware with zero UTC offset |
| `test_hello_post_timestamp_is_utc_aware` | POST /api/hello timestamp is timezone-aware with zero UTC offset |

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
| `test_delete_health_returns_405` | DELETE /health returns 405 Method Not Allowed |
| `test_put_health_returns_405` | PUT /health returns 405 Method Not Allowed |
| `test_delete_api_version_returns_405` | DELETE /api/version returns 405 Method Not Allowed |
| `test_put_api_hello_returns_405` | PUT /api/hello returns 405 (only GET and POST are defined) |
| `test_delete_api_hello_returns_405` | DELETE /api/hello returns 405 Method Not Allowed |

### `TestTimestampOrdering`
| Test | Description |
|------|-------------|
| `test_health_timestamps_are_non_decreasing` | Two successive /health calls return timestamps where the second is not earlier than the first (catches clock drift or response caching) |
| `test_hello_get_timestamps_are_non_decreasing` | Two successive GET /api/hello calls return non-decreasing timestamps |
| `test_hello_post_timestamp_within_request_window` | POST /api/hello timestamp falls strictly between the request start time and response receipt time (catches stale clocks) |

### `TestRequestIsolation`
| Test | Description |
|------|-------------|
| `test_hello_name_responses_are_independent` | Two POST /api/hello calls with different names return fully independent responses with no cross-contamination |
| `test_concurrent_hello_posts_are_independent` | Three concurrent async POST /api/hello calls each receive only their own name in the response (catches shared mutable state) |

**Coverage:** 100% (36/36 statements, 58 tests)

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

**Coverage:** 100% statements, 100% branches, 100% functions, 100% lines (33 tests)

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
