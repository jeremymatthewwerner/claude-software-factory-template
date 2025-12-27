# Claude Software Factory Template

A template repository for setting up an autonomous software factory powered by Claude Code agents.

## Key Features

- 🤖 **8 Specialized AI Agents** - Triage, Code, Principal Engineer, QA, Release, DevOps, Marketing, CI Monitor
- 🧠 **Opus Model** - Code Agent and PE use claude-opus-4-5 for superior reasoning
- 🔄 **Self-Healing** - CI failures auto-create issues, agents auto-fix them
- 📊 **Log Analysis Protocol** - Agents analyze logs before implementing fixes (not guessing!)
- 🎯 **Decision-Making Autonomy** - Agents DECIDE technical matters, only escalate for security/business decisions
- 🔧 **Principal Engineer Escalation** - When Code Agent gets stuck, PE takes a holistic factory-fixing approach
- 📝 **Progress Visibility** - Checkbox-based progress tracking on all issues
- 🔁 **Smart Retries** - Up to 3 attempts with increasing context from failure logs

## What Is This?

This template sets up a complete autonomous development workflow where AI agents:
- **Triage** incoming issues automatically
- **Fix bugs** and implement features via PRs
- **Monitor production** and auto-create incidents
- **Improve test coverage** nightly
- **Manage dependencies** and security updates
- **Update documentation** on releases

**Human intervention becomes the exception, not the rule.**

## Quick Start

### 1. Create Your Repository

**Option A: Use as Template (Recommended)**
1. Click "Use this template" → "Create a new repository"
2. Name your repo and set visibility
3. Clone your new repo locally

**Option B: Fork**
1. Fork this repository
2. Clone your fork locally

### 2. Required GitHub Configuration

#### 2.1 Create Required Labels

Run these commands to create the necessary labels:

```bash
# Navigate to your repo
cd your-repo

# Create labels (replace OWNER/REPO with your repo)
gh label create "ai-ready" --color "0E8A16" --description "Ready for autonomous agent"
gh label create "needs-principal-engineer" --color "7057FF" --description "Escalated to PE (Code Agent stuck)"
gh label create "needs-human" --color "D93F0B" --description "Requires human intervention (PE escalated)"
gh label create "qa-agent" --color "0052CC" --description "QA Agent tracking"
gh label create "automation" --color "BFDADC" --description "Automated by agents"
gh label create "ci-failure" --color "B60205" --description "CI failure issues"
gh label create "production-incident" --color "B60205" --description "Production incidents"
gh label create "status:bot-working" --color "7057FF" --description "Bot is actively working"
gh label create "status:awaiting-human" --color "D93F0B" --description "Blocked waiting for human"
gh label create "status:awaiting-bot" --color "0E8A16" --description "Human commented, bot will respond"
gh label create "bug" --color "d73a4a" --description "Something isn't working"
gh label create "enhancement" --color "a2eeef" --description "New feature or request"
gh label create "priority-high" --color "B60205" --description "High priority"
gh label create "priority-medium" --color "FBCA04" --description "Medium priority"
gh label create "priority-low" --color "0E8A16" --description "Low priority"
gh label create "P0" --color "B60205" --description "Critical - system down"
gh label create "P1" --color "D93F0B" --description "High - blocks functionality"
gh label create "P2" --color "FBCA04" --description "Medium - optimization/cleanup"
```

#### 2.2 Configure Repository Secrets

Go to **Settings → Secrets and variables → Actions** and add:

| Secret Name | Required | Description |
|-------------|----------|-------------|
| `ANTHROPIC_API_KEY` | ✅ Yes | Your Anthropic API key for Claude |
| `PAT_WITH_WORKFLOW_ACCESS` | ✅ Yes | GitHub PAT with `repo` + `workflow` scopes (see below) |
| `RAILWAY_TOKEN_SW_FACTORY` | For Railway | Railway API token for deployments |
| `PRODUCTION_BACKEND_URL` | For monitoring | Your production backend URL (e.g., `https://api.example.com`) |
| `PRODUCTION_FRONTEND_URL` | For monitoring | Your production frontend URL (e.g., `https://example.com`) |

##### Creating the PAT (Personal Access Token)

1. Go to GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens
2. Click "Generate new token"
3. Set:
   - **Token name**: `claude-software-factory`
   - **Expiration**: 90 days (or custom)
   - **Repository access**: Only select repositories → select your repo
   - **Permissions**:
     - Contents: Read and write
     - Issues: Read and write
     - Pull requests: Read and write
     - Workflows: Read and write
     - Actions: Read
4. Generate token and add as `PAT_WITH_WORKFLOW_ACCESS` secret

> **Why a PAT?** The default `GITHUB_TOKEN` cannot trigger workflows or modify workflow files. A PAT enables full autonomous operation.

#### 2.3 Configure Actions Permissions

Go to **Settings → Actions → General**:

1. **Actions permissions**: Allow all actions
2. **Workflow permissions**:
   - Select "Read and write permissions"
   - ✅ Check "Allow GitHub Actions to create and approve pull requests"

### 3. Railway Deployment Setup (Optional)

If deploying to Railway:

#### 3.1 Create Railway Project

1. Sign up at [railway.app](https://railway.app)
2. Create a new project
3. Add services:
   - **Backend**: Connect to your repo's `backend/` directory
   - **Frontend**: Connect to your repo's `frontend/` directory
   - **PostgreSQL**: Add from Railway's database templates

#### 3.2 Configure Railway Services

**Backend service:**
```bash
# Build command
cd backend && pip install uv && uv sync

# Start command
cd backend && uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT

# Environment variables
DATABASE_URL=<from PostgreSQL service>
ANTHROPIC_API_KEY=<your key>
```

**Frontend service:**
```bash
# Build command
cd frontend && npm ci && npm run build

# Start command
cd frontend && npm start

# Environment variables
NEXT_PUBLIC_API_URL=<backend service URL>
NEXT_PUBLIC_WS_URL=<backend WebSocket URL>
```

#### 3.3 Get Railway Token

1. Go to Railway Dashboard → Account Settings → Tokens
2. Create a new token
3. Add as `RAILWAY_TOKEN_SW_FACTORY` secret in GitHub

### 4. Customize for Your Project

#### 4.1 Update CLAUDE.md

Edit `CLAUDE.md` to reflect your project:
- Project name and description
- Your production domain
- Your GitHub username (for escalations)
- Your tech stack
- Your quality gate commands

#### 4.2 Update Workflow Files

The workflows assume a `frontend/` + `backend/` structure. Modify these files if your structure differs:

- `.github/workflows/bug-fix.yml` - Dependency installation steps
- `.github/workflows/qa.yml` - Test commands and coverage paths
- `.github/workflows/release-eng.yml` - Audit and lint commands
- `.github/workflows/devops.yml` - Health check endpoints

#### 4.3 Create CI/CD Workflow

Create `.github/workflows/ci.yml` for your project. The `ci-failure-monitor.yml` workflow watches for failures in a workflow named "CI/CD".

Example minimal CI workflow:

```yaml
name: CI/CD

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      # Add your test steps here
      - name: Run tests
        run: npm test  # Customize for your project
```

### 5. Verify Setup

After completing setup:

1. **Create a test issue:**
   ```bash
   gh issue create --title "Test: Verify agent setup" --body "This is a test issue to verify the autonomous agents are working."
   ```

2. **Watch the Triage Agent:**
   - Go to Actions tab
   - You should see "Triage Agent" workflow start
   - It will label and classify your issue

3. **Check DevOps monitoring:**
   - If you configured production URLs, go to Actions → DevOps Agent
   - Manually trigger to verify health checks work

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Issue Created                            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Triage Agent                               │
│  - Classifies as bug/enhancement                                │
│  - Checks for duplicates                                        │
│  - Adds priority label                                          │
│  - Adds ai-ready label (triggers Code Agent)                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Code Agent                                 │
│  - Analyzes logs from previous failures                         │
│  - Checks for existing PRs/branches                             │
│  - Implements fix with tests                                    │
│  - Creates PR and monitors CI                                   │
│  - Auto-merges on success                                       │
│  - Retries up to 3x on failure                                  │
│  - Escalates to PE if stuck                                     │
└─────────────────────────────────────────────────────────────────┘
                              │
              (on 3x failure or timeout)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Principal Engineer                             │
│  - Called when Code Agent gets stuck                            │
│  - Downloads and analyzes E2E artifacts                         │
│  - Identifies root cause (code vs infra vs workflow)            │
│  - Fixes the issue AND improves factory                         │
│  - Escalates to human only if truly stuck                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                         CI/CD                                   │
│  - Runs tests                                                   │
│  - If fails on main → CI Monitor creates issue                  │
│  - If passes → Deploy to production                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      DevOps Agent                               │
│  - Smoke tests every 5 minutes                                  │
│  - Auto-creates incident on failure                             │
│  - Code Agent attempts to fix                                   │
└─────────────────────────────────────────────────────────────────┘

Background Agents (scheduled):
┌─────────────────────────────────────────────────────────────────┐
│ QA Agent (2am UTC)        │ Improves test coverage              │
│ Release Eng (3am UTC)     │ Security audits, dep updates        │
│ Marketing (on release)    │ Updates docs and changelog          │
└─────────────────────────────────────────────────────────────────┘
```

## Workflow Files

| File | Purpose |
|------|---------|
| `bug-fix.yml` | Code Agent - fixes bugs and implements features |
| `triage.yml` | Triage Agent - classifies and labels issues |
| `ci-failure-monitor.yml` | Creates issues when CI fails on main |
| `devops.yml` | Production monitoring and incident response |
| `qa.yml` | Nightly test quality improvement |
| `release-eng.yml` | Daily dependency and security maintenance |
| `marketing.yml` | Documentation updates on releases |

## Agent Definition Files

Located in `.claude/agents/`:

| File | Agent |
|------|-------|
| `bug-fixer.md` | Instructions for the Code Agent |
| `triage-product.md` | Instructions for the Triage Agent |
| `qa-improver.md` | Instructions for the QA Agent |
| `devops-sre.md` | Instructions for the DevOps Agent |
| `release-engineer.md` | Instructions for the Release Eng Agent |
| `marketing-docs.md` | Instructions for the Marketing Agent |

## Troubleshooting

### Agents not triggering

1. **Check secrets**: Ensure `ANTHROPIC_API_KEY` and `PAT_WITH_WORKFLOW_ACCESS` are set
2. **Check permissions**: Verify Actions permissions allow write access
3. **Check labels**: Ensure all required labels exist

### CI Monitor not creating issues

1. Your CI workflow must be named "CI/CD" (or update `ci-failure-monitor.yml`)
2. It only triggers on failures on the `main` branch

### Code Agent not auto-merging

1. Check branch protection rules - agents may not have permission
2. Verify PAT has write access to the repository
3. Check if the PR requires approval from a human reviewer

### DevOps monitoring shows failures

1. Verify `PRODUCTION_BACKEND_URL` and `PRODUCTION_FRONTEND_URL` are correct
2. Ensure your health endpoint returns 200 OK
3. Check if your auth endpoint matches the expected API structure

## Contributing

This is a template repository. To contribute improvements:

1. Fork this repository
2. Make your changes
3. Create a PR back to the main template

## License

MIT License - feel free to use this template for your projects.

---

**Built with [Claude Code](https://github.com/anthropics/claude-code) and the [Claude Code Action](https://github.com/anthropics/claude-code-action)**

