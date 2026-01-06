# Claude Software Factory Template

> Transform any repository into an autonomous software factory powered by Claude AI agents.

**Your AI development team, ready in 5 minutes.**

## What Is This?

This template sets up a complete **autonomous development workflow** where AI agents:

- **Triage** incoming issues automatically (classify, detect duplicates, prioritize)
- **Fix bugs** and implement features via PRs (with tests!)
- **Monitor production** and auto-create incidents
- **Improve test coverage** nightly
- **Manage dependencies** and security updates
- **Update documentation** on releases

**Human intervention becomes the exception, not the rule.**

### Key Features

| Feature | Description |
|---------|-------------|
| **8 Specialized Agents** | Triage, Code, Principal Engineer, QA, Release, DevOps, Marketing, CI Monitor |
| **Opus Model** | Code Agent and PE use Claude Opus for superior reasoning |
| **Self-Healing** | CI failures auto-create issues, agents auto-fix them |
| **Log Analysis** | Agents analyze actual logs before implementing fixes |
| **Decision Autonomy** | Agents DECIDE technical matters, only escalate for security/business |
| **Progress Visibility** | Checkbox-based progress tracking on all issues |

---

## Quick Start (5 minutes)

### 1. Create Your Repository

```bash
# Option A: Use as template (recommended)
# Click "Use this template" on GitHub, then clone

# Option B: Clone directly
git clone https://github.com/YOUR_USERNAME/claude-software-factory-template.git my-project
cd my-project
```

### 2. Run the Automated Setup

```bash
./scripts/setup-factory.sh
```

This wizard handles everything:
- ✅ Creates all required GitHub labels
- ✅ Collects and stores secrets (GitHub PAT, Anthropic key, Slack tokens)
- ✅ Sets up GitHub repository secrets
- ✅ Deploys Slack bot to Railway (optional)
- ✅ Validates the complete setup

**Or run individual steps:**
```bash
./scripts/setup-factory.sh        # Full interactive setup
./scripts/validate-factory.sh     # Validate existing setup
```

### 3. Create a Slack App (30 seconds)

Use the included manifest for instant app creation:

1. Go to https://api.slack.com/apps
2. Click **"Create New App"** → **"From an app manifest"**
3. Paste contents of `services/slack-bot/slack-app-manifest.yaml`
4. Install to workspace

The manifest pre-configures all scopes, events, and settings automatically.

### 4. Test It!

```bash
# Validate your setup
./scripts/validate-factory.sh

# Create test issues to exercise the agents
./test-project/scripts/create-test-issues.sh

# Or manually create a test issue
gh issue create --title "Test: Verify agent setup" \
  --body "Test issue for factory validation" \
  --label "ai-ready" --label "bug"
```

Then check the **Actions tab** - you should see agents running!

---

## Included Hello World Apps

This template includes working starter applications to get you productive immediately:

### Backend (FastAPI + Python)

```bash
cd backend
uv sync                                    # Install dependencies
uv run uvicorn app.main:app --reload       # Start server
open http://localhost:8000/docs            # API documentation
```

**Endpoints:**
- `GET /health` - Health check (used by DevOps monitoring)
- `GET /api/version` - API version info
- `GET /api/hello` - Hello World
- `POST /api/hello` - Personalized greeting

### Frontend (Next.js + TypeScript)

```bash
cd frontend
npm install                                # Install dependencies
npm run dev                                # Start dev server
open http://localhost:3000                 # Open in browser
```

**Features:**
- Connects to backend API
- Shows API health status
- Dark/light mode
- TypeScript + React Testing Library

### Running Both Together

```bash
# Terminal 1: Backend
cd backend && uv run uvicorn app.main:app --reload

# Terminal 2: Frontend
cd frontend && npm run dev

# Visit http://localhost:3000
```

---

## Slack Bot Integration (Optional)

Want a Claude Code-like experience in Slack? This template includes a Slack bot that:

- **Conversational AI** - Chat naturally about your codebase
- **Agent Dispatch** - Send tasks to agents via Slack (`dispatch code fix the login bug`)
- **Status Updates** - Receive progress notifications in Slack threads
- **Intervention Help** - Collaborate when workflows need human input

### Quick Setup

```bash
./scripts/setup-slack.sh
```

This wizard guides you through creating a Slack app and configuring secrets.

### How It Works

The Slack bot is a "meta-agent" that sits on top of your GitHub-based workflow:

1. You chat with Claude in Slack (like Claude Code, but in Slack)
2. When you need an agent to take action, dispatch to GitHub: `dispatch code <task>`
3. The bot creates a GitHub issue with appropriate labels
4. Agent workflows run on GitHub (as usual)
5. Status updates post back to your Slack thread

> **Note**: The agents themselves still work via GitHub Actions. The Slack bot is your collaboration layer, not a replacement for the GitHub workflow.

See [`services/slack-bot/README.md`](./services/slack-bot/README.md) for full documentation.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Issue Created                            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Triage Agent                               │
│  • Classifies as bug/enhancement                                │
│  • Checks for duplicates                                        │
│  • Adds priority label (P0/P1/P2)                               │
│  • Adds ai-ready label → triggers Code Agent                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Code Agent                                 │
│  • Analyzes logs from previous failures                         │
│  • Implements fix with tests                                    │
│  • Creates PR and monitors CI                                   │
│  • Auto-merges on success                                       │
│  • Retries up to 3x on failure                                  │
│  • Escalates to PE if stuck                                     │
└─────────────────────────────────────────────────────────────────┘
                              │
              (on 3x failure or timeout)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Principal Engineer                             │
│  • Called when Code Agent gets stuck                            │
│  • Downloads and analyzes E2E artifacts                         │
│  • Identifies root cause (code vs infra vs workflow)            │
│  • Fixes the issue AND improves factory                         │
│  • Escalates to human only if truly stuck                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                         CI/CD                                   │
│  • Runs tests on all PRs                                        │
│  • If fails on main → CI Monitor creates ai-ready issue         │
│  • If passes → Deploy to production                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      DevOps Agent                               │
│  • Smoke tests every 5 minutes                                  │
│  • Auto-creates incident on failure                             │
│  • Code Agent attempts to fix                                   │
└─────────────────────────────────────────────────────────────────┘

Background Agents (scheduled):
┌─────────────────────────────────────────────────────────────────┐
│ QA Agent (2am UTC)        │ Improves test coverage              │
│ Release Eng (3am UTC)     │ Security audits, dep updates        │
│ Marketing (on release)    │ Updates docs and changelog          │
└─────────────────────────────────────────────────────────────────┘
```

---

## Agent Reference

| Agent | Trigger | Purpose | Workflow |
|-------|---------|---------|----------|
| **Triage** | Issue opened | Classify, dedupe, prioritize, label | `triage.yml` |
| **Code** | `ai-ready` label | Fix bugs, implement features | `bug-fix.yml` |
| **Principal Engineer** | `needs-principal-engineer` label | Holistic debugging when Code Agent stuck | `principal-engineer.yml` |
| **CI Monitor** | CI failure on main | Auto-create `ai-ready` issues | `ci-failure-monitor.yml` |
| **DevOps** | Every 5 minutes | Production health checks | `devops.yml` |
| **QA** | 2am UTC daily | Improve test coverage | `qa.yml` |
| **Release Eng** | 3am UTC daily | Security audits, dependencies | `release-eng.yml` |
| **Marketing** | On release | Update changelog, docs | `marketing.yml` |

### Interacting with Agents

**Comment-driven interaction:** Comment `@claude` on any issue with `ai-ready` label.

**Status labels:**
| Label | Meaning | Who Acts |
|-------|---------|----------|
| `status:bot-working` | Agent is working | Wait |
| `status:awaiting-human` | Agent needs input | You respond |
| `status:awaiting-bot` | You commented | Wait |

---

## Customization

### Modify Tech Stack

1. **Change backend language**: Replace `backend/` with your stack, update `bug-fix.yml` and `qa.yml`
2. **Change frontend framework**: Replace `frontend/` with your choice, update workflows
3. **Add database**: Add to `backend/`, update CI with service containers

### Add E2E Tests

1. Add Playwright to frontend: `npm install -D @playwright/test`
2. Uncomment E2E job in `.github/workflows/ci.yml`
3. Add E2E tests in `frontend/e2e/`

### Deploy to Railway

1. Create Railway project with backend + frontend services
2. Add `RAILWAY_TOKEN_SW_FACTORY` secret
3. Uncomment deploy steps in `ci.yml`

**Backend service configuration:**
```bash
# Build command
cd backend && pip install uv && uv sync

# Start command
cd backend && uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

**Frontend service configuration:**
```bash
# Build command
cd frontend && npm ci && npm run build

# Start command
cd frontend && npm start
```

---

## Test Project

The template includes a **test project** for validating your factory setup:

```bash
cd test-project
npm install
npm test          # Some tests intentionally fail (bugs for agents to fix!)
```

### What's Included

- **Simple calculator** with intentional bugs (division by zero, negative sqrt)
- **Tests** that expose the bugs
- **Issue creation script** to exercise agents

### Testing Your Factory

```bash
# Create test issues that trigger agents
./test-project/scripts/create-test-issues.sh

# This creates:
# 1. A bug issue (division by zero) - triggers Code Agent
# 2. An enhancement issue (add modulo) - triggers Code Agent
# 3. A QA issue (improve coverage) - triggers QA Agent
```

Watch the factory work:
1. Issues appear with `ai-ready` label
2. Code Agent picks them up
3. PRs get created with fixes
4. Tests pass, PRs merge
5. Issues close automatically

---

## Project Structure

```
.
├── .claude/
│   └── agents/              # Agent instruction files
├── .github/
│   └── workflows/           # GitHub Actions workflows
├── backend/                 # FastAPI backend (Hello World)
│   ├── app/
│   ├── tests/
│   └── pyproject.toml
├── frontend/                # Next.js frontend (Hello World)
│   ├── src/app/
│   ├── __tests__/
│   └── package.json
├── services/
│   └── slack-bot/           # Factory improvement bot
│       ├── src/
│       ├── slack-app-manifest.yaml  # One-click Slack app setup
│       └── package.json
├── test-project/            # Validation project with intentional bugs
│   ├── src/calculator.ts
│   ├── tests/
│   └── scripts/create-test-issues.sh
├── scripts/
│   ├── setup-factory.sh     # Automated factory setup
│   └── validate-factory.sh  # Validate setup
├── CLAUDE.md                # Agent instructions & philosophy
└── README.md                # This file
```

---

## Troubleshooting

<details>
<summary>Agents not triggering</summary>

1. **Check secrets**: Ensure `ANTHROPIC_API_KEY` and `PAT_WITH_WORKFLOW_ACCESS` are set
2. **Check permissions**: Verify Actions permissions allow write access
3. **Check labels**: Run `./scripts/setup.sh --labels-only` to create missing labels

</details>

<details>
<summary>Code Agent not creating PRs</summary>

1. Check the workflow logs in Actions tab
2. Ensure the issue has both `ai-ready` AND (`bug` OR `enhancement`) labels
3. Verify PAT has write access

</details>

<details>
<summary>CI Monitor not creating issues</summary>

1. Your CI workflow must be named "CI/CD" (or update `ci-failure-monitor.yml`)
2. It only triggers on failures on the `main` branch

</details>

<details>
<summary>DevOps showing failures</summary>

1. Verify `PRODUCTION_BACKEND_URL` and `PRODUCTION_FRONTEND_URL` are correct
2. Ensure health endpoint returns 200: `curl $PRODUCTION_BACKEND_URL/health`
3. Check if auth endpoint matches expected API structure

</details>

---

## Philosophy

> **Human intervention = factory bug**

If you need to step in, that's a bug in the factory itself. When intervening:
1. Fix the immediate issue
2. Update the relevant agent workflow to handle this autonomously next time
3. Document the improvement

See [CLAUDE.md](./CLAUDE.md) for the full philosophy and agent instructions.

---

## Contributing

Improvements to the template are welcome! Please:
1. Fork this repository
2. Make your changes
3. Create a PR back to the main template

---

## License

MIT License - feel free to use this template for your projects.

---

**Built with [Claude Code](https://github.com/anthropics/claude-code) and the [Claude Code Action](https://github.com/anthropics/claude-code-action)**
