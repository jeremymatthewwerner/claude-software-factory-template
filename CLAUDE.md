# CLAUDE.md - Autonomous Software Factory

This repository is configured to run as an autonomous software factory using Claude Code agents.

## Project Overview

- **Name**: [Your Project Name]
- **Description**: [Your project description]
- **Domain**: [Your production URL]
- **Hosting**: Railway (or your preferred platform)
- **Maintainer**: @[your-github-username]

## Setup Steps

See README.md for complete setup instructions including:
- GitHub repository configuration
- Required secrets and tokens
- Label creation
- Deployment setup

## Autonomous Software Factory Philosophy

**This repo is designed to run as an autonomous software factory.** The goal is for AI agents to handle routine development tasks without human intervention.

**Key Principles:**
- **Human intervention = factory bug** - If a human needs to step in, that's a bug in the factory itself
- **Fix the factory, not the symptom** - When intervening, always ask: "How can I prevent needing to intervene for this type of issue again?"
- **Visibility enables autonomy** - Agents must post progress updates to issues so humans can monitor without intervening
- **Self-healing over manual fixes** - CI failures auto-create issues, agents auto-fix them

**When you (human or Claude) intervene:**
1. Fix the immediate issue
2. Update the relevant agent workflow to handle this case autonomously next time
3. Document the improvement in this file

## Decision-Making Autonomy (CRITICAL)

**Agents are empowered to make technical decisions.** Don't ask "Should I do A, B, or C?" - DECIDE.

### When to Decide Autonomously (DO THIS):
- **Implementation approach** - Pick the cleanest solution
- **Test strategy** - Decide what tests are needed
- **Timeout/retry values** - Use reasonable defaults (30s timeout, 3 retries)
- **Dependency versions** - Pin to latest stable
- **Code style** - Follow existing patterns
- **PR merge strategy** - Wait for CI, don't merge with failures
- **Branch management** - Always use feature branches, never push to main

### When to Actually Escalate to Human (RARE):
- **Security decisions** - Credentials, auth changes, API keys
- **Breaking changes** - Public API changes affecting users
- **Business logic** - Product decisions, not technical ones
- **Architecture** - Major system redesign (not refactoring)
- **Cost implications** - New services, paid APIs

### The 10-Minute Rule
If you've been stuck on a DECISION (not implementation) for 10 minutes, MAKE A CHOICE.
Document your reasoning. A reasonable choice made quickly > perfect choice never made.

## IMPORTANT Rules

- ALWAYS write tests alongside code (unit, integration, E2E)
- NEVER commit code without tests - minimum 70% coverage (goal: 85%)
- Commit and push frequently at logical checkpoints
- **ALWAYS check things yourself before asking the user** - Use available tools to verify state
- **ALWAYS check CI results after every push** - Use `gh run list` and `gh run view <id> --log-failed`
- **When resuming work, ALWAYS check CI first** - There may be failed runs from a previous session
- **ALWAYS check open issues at session start** - Work from highest priority (P0 → P1 → P2)

## Tech Stack

Customize this section for your project:

- **Frontend**: Next.js (TypeScript strict mode)
- **Backend**: Python / FastAPI
- **Database**: PostgreSQL
- **Real-time**: WebSockets
- **Deployment**: Railway

## Quality Gates

```bash
# Backend (customize for your project)
cd backend
uv run pytest                    # run tests
uv run pytest --cov=app          # run tests with coverage
uv run ruff check .              # lint
uv run ruff format .             # format
uv run mypy .                    # type check

# Frontend (customize for your project)
cd frontend
npm test                         # jest tests
npm run lint                     # eslint
npm run typecheck                # tsc
npx playwright test              # e2e tests

# Full test suite
./scripts/test-all.sh
```

## Development Workflow (MANDATORY)

At every meaningful milestone:

1. **Run all unit tests**
2. **Run E2E tests** (with backend running)
3. **Local user testing** - Have user manually test the feature
4. **Fix any issues** - Repeat steps 1-3 until passing
5. **Commit and push** - Only after E2E and manual testing pass

**When E2E tests hang or timeout (CRITICAL)**:
- **DO NOT assume it's a test or framework issue** - E2E tests exercise real code paths
- **ASSUME a real regression** - Something in recent changes broke the functionality
- **Investigate recent commits** - Look at what changed since tests last passed
- **Avoid piling on fixes** - Don't keep adjusting test timeouts; find and fix the root cause

### Log Analysis Protocol (MANDATORY for agents)

**BEFORE implementing any fix, agents MUST analyze logs.** Don't guess - READ THE ACTUAL ERRORS!

```bash
# Step 1: Check issue comments for "❌ CI Failed" - contains actual logs
gh issue view <ISSUE_NUMBER> --comments

# Step 2: Get workflow logs
gh run list --workflow=ci.yml --limit 5 --json databaseId,headBranch,conclusion
gh run view <RUN_ID> --log-failed

# Step 3: Download E2E artifacts (if available)
gh run download <RUN_ID> --name e2e-debug-logs --dir /tmp/e2e-logs
cat /tmp/e2e-logs/backend.log | tail -200
```

**Agents must document what logs showed BEFORE implementing a fix.**

## Git Workflow

**Claude Code sessions use feature branches:**
1. Create branch: `claude/<description>-<session-id>` (branch name is auto-assigned)
2. Commit changes with issue references (`Relates to #N` in commit messages)
3. Push to feature branch and create PR
4. CI runs on PR - must pass before merge
5. Merge PR (squash) - triggers deploy
6. Issues auto-close when PR merges

**CRITICAL: Issue Reference Rules (prevents premature closure)**
- **In commit messages:** Use `Relates to #N` (NOT `Fixes #N`)
- **In PR descriptions:** Use `Fixes #N` (closes issue when PR merges)
- **NEVER push directly to main** - Always use a feature branch + PR
- **Why:** GitHub auto-closes issues when commits on main contain "Fixes #N"

## Commit Format

`<type>(<scope>): <description>` where type is feat|fix|docs|test|chore|ci

## Task & Bug Tracking with GitHub Issues

All bugs AND tasks must be tracked via GitHub Issues for audit history.

### Issue Priority (MANDATORY)

- **P0** - Blocks most or all functionality (critical bugs, system down)
- **P1** - Blocks some functionality, OR new feature requests
- **P2** - Optimizations, cleanup, refactoring, minor improvements

### Issue Labels

- `bug` - Something isn't working
- `enhancement` - New feature request
- `ai-ready` - Ready for autonomous agent
- `needs-principal-engineer` - Escalated to PE (Code Agent stuck)
- `needs-human` - Requires human intervention (PE escalated)
- `priority-high`, `priority-medium`, `priority-low`

## Autonomous Agents

This repo uses 8 AI-powered GitHub Actions agents:

| Agent | Trigger | Purpose |
|-------|---------|---------|
| **Triage** | Issue opened | Classifies issues, detects duplicates, adds labels |
| **Code Agent** | `ai-ready` + `bug`/`enhancement` | Diagnoses and fixes issues, creates PRs |
| **Principal Engineer** | `needs-principal-engineer` label | Holistic debugging, fixes factory not just symptoms |
| **QA** | Nightly 2am UTC | Test quality improvement with daily focus rotation |
| **Release Eng** | Daily 3am UTC | Security audits, dependency updates, CI optimization |
| **DevOps** | Every 5 minutes | Health checks, incident response |
| **Marketing** | On release | Updates changelog, docs |
| **CI Monitor** | On CI failure (main) | Auto-creates `ai-ready` issues for failed builds |

### Escalation Flow

When Code Agent gets stuck (timeout, 3x CI failure), it adds `needs-principal-engineer` label which triggers the **Principal Engineer**:

```
Code Agent stuck → adds needs-principal-engineer → Principal Engineer investigates
                                                           ↓
                                       Analyzes root cause (code? infra? workflow?)
                                                           ↓
                                       Downloads E2E artifacts, reads backend logs
                                                           ↓
                                       Fixes issue AND updates factory to prevent recurrence
                                                           ↓
                                       If truly stuck → adds needs-human → Human reviews
```

**Principal Engineer responsibilities:**
- Take holistic view - fix the factory, not just the symptom
- Download and analyze E2E artifacts (`gh run download`)
- Can modify workflows, CLAUDE.md, agent prompts
- Document learnings to prevent similar issues

### Agent Visibility (IMPORTANT)

All agents MUST post progress updates to their issues using the **checkbox progress pattern**:

```markdown
## 🤖 Progress Tracker

- [x] 📖 Reading issue and understanding requirements
- [x] 🔍 Analyzing codebase and finding affected files
- [ ] 🛠️ Implementing fix
- [ ] ✅ Running tests and quality checks
- [ ] 📝 Creating PR
- [ ] 🚀 Waiting for CI

**Status:** Implementing fix...
```

### Interacting with the Code Agent

**Comment-driven interaction:** Comment on any issue with `@claude` to ask questions or provide suggestions.

**Status labels indicate who should act next:**
| Label | Meaning | Who Acts |
|-------|---------|----------|
| `status:bot-working` | Bot is actively working | Wait for bot |
| `status:awaiting-human` | Bot needs your input | You respond |
| `status:awaiting-bot` | You commented, bot will respond | Wait for bot |
| (no status label) | No active work | Add `ai-ready` to trigger |

## Default Policies (for autonomous decisions)

When agents encounter these situations, apply these defaults:

**Coverage threshold unreachable:**
- If coverage is >10% below required, lower threshold to (current + 5%)
- Create tracking issue for incremental improvement

**Test flakiness:**
- If a test fails intermittently, disable with `@pytest.mark.skip(reason="flaky - issue #N")`
- Create issue to investigate root cause

**Dependency conflicts:**
- Pin to last known working version
- Create issue for proper resolution
- Don't spend >30min on dependency issues

**Transient CI failures (502, 503, timeouts):**
- Add retry logic with exponential backoff (3 attempts, 5s → 10s → 20s)
- Distinguish transient errors (retry) from real errors (fail fast)
- Add stability waits after deployment before running API tests
- Don't let infrastructure blips block PRs for hours

## Observability & DevOps Hygiene

**Every production system needs visibility.** Agents should always consider:

### Health Endpoints
- **Basic** (`/health`): Returns 200 if process is alive
- **Deep** (`/health/ready`): Verifies DB, cache, external APIs - returns 503 if degraded

### The Four Golden Signals
1. **Latency** - Request duration (p50, p95, p99)
2. **Traffic** - Requests per second
3. **Errors** - Error rate by endpoint
4. **Saturation** - CPU, memory, connection pools

### When Adding Features
Before shipping, verify:
- [ ] Health endpoint updated if new dependencies added
- [ ] Key operations logged (INFO level)
- [ ] Errors logged with context
- [ ] Metrics added for new endpoints
- [ ] Failure scenarios have alerts

### DevOps Agent Responsibilities
- Monitor health endpoints every 5 minutes
- Create issues for anomalies
- Pull logs and diagnose failures
- Restart services (max 2 attempts, then escalate)
- Weekly audit of monitoring effectiveness

### Railway Observability
Railway provides built-in dashboards for CPU, memory, network. For custom metrics:
- Use OpenTelemetry collector
- Export to Grafana/Datadog if needed
- See: https://docs.railway.app/guides/observability

## Escalation

Assign to maintainer when:
- Stuck >30min
- CI fails 3x on same issue
- Needs architecture decision
- Security concern
