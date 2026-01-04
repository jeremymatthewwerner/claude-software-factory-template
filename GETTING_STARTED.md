# Getting Started with Claude Software Factory

This guide will walk you through setting up your autonomous software factory in 5 minutes.

## Prerequisites

Before you begin, make sure you have:

- [ ] A GitHub account
- [ ] [GitHub CLI](https://cli.github.com/) installed and authenticated (`gh auth login`)
- [ ] An [Anthropic API key](https://console.anthropic.com/)
- [ ] [Node.js 20+](https://nodejs.org/) (for frontend)
- [ ] [Python 3.11+](https://www.python.org/) and [uv](https://docs.astral.sh/uv/) (for backend)

## Step 1: Create Your Repository

### Option A: Use GitHub Template (Recommended)

1. Go to the [template repository](https://github.com/YOUR_ORG/claude-software-factory-template)
2. Click **"Use this template"** → **"Create a new repository"**
3. Name your repo and choose visibility
4. Clone your new repo:

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git
cd YOUR_REPO
```

### Option B: Clone Directly

```bash
git clone https://github.com/YOUR_ORG/claude-software-factory-template.git my-project
cd my-project
rm -rf .git
git init
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
```

## Step 2: Run the Setup Wizard

The setup wizard handles most of the configuration automatically:

```bash
./scripts/setup.sh
```

The wizard will:
1. Check prerequisites (gh, git, node, python)
2. Ask for your project details
3. Create all required GitHub labels
4. Update CLAUDE.md with your info
5. Activate the CI workflow

**If you prefer manual setup**, see the [Manual Setup](#manual-setup) section below.

## Step 3: Configure GitHub Secrets

Go to **Settings → Secrets and variables → Actions** in your repo:

### Required Secrets

| Secret | How to Get It |
|--------|---------------|
| `ANTHROPIC_API_KEY` | [Anthropic Console](https://console.anthropic.com/) → API Keys |
| `PAT_WITH_WORKFLOW_ACCESS` | See instructions below |

### Creating the GitHub PAT

1. Go to [GitHub Settings → Developer settings → Personal access tokens → Fine-grained tokens](https://github.com/settings/tokens?type=beta)
2. Click **"Generate new token"**
3. Configure:
   - **Token name**: `claude-software-factory`
   - **Expiration**: 90 days (set a calendar reminder!)
   - **Repository access**: Select your repo only
   - **Permissions**:
     - Contents: Read and write
     - Issues: Read and write
     - Pull requests: Read and write
     - Workflows: Read and write
     - Actions: Read
4. Click **"Generate token"** and copy it
5. Add as `PAT_WITH_WORKFLOW_ACCESS` secret in your repo

### Optional Secrets (for production monitoring)

| Secret | Purpose |
|--------|---------|
| `PRODUCTION_BACKEND_URL` | DevOps agent health checks |
| `PRODUCTION_FRONTEND_URL` | DevOps agent health checks |
| `RAILWAY_TOKEN_SW_FACTORY` | Automated Railway deployments |

## Step 4: Enable GitHub Actions Permissions

Go to **Settings → Actions → General**:

1. Under **Actions permissions**: Select **"Allow all actions and reusable workflows"**
2. Under **Workflow permissions**:
   - Select **"Read and write permissions"**
   - Check **"Allow GitHub Actions to create and approve pull requests"**
3. Click **Save**

## Step 5: Verify Everything Works

### Test the Starter Apps Locally

```bash
# Terminal 1: Start backend
cd backend
uv sync
uv run uvicorn app.main:app --reload

# Terminal 2: Start frontend
cd frontend
npm install
npm run dev

# Visit http://localhost:3000
```

### Test the Triage Agent

```bash
# Create a test issue
gh issue create \
  --title "Test: Verify software factory setup" \
  --body "This is a test issue to verify the autonomous agents work correctly."

# Watch the Actions tab - Triage Agent should run
gh run list --limit 5
```

You should see:
1. **Triage Agent** workflow triggers
2. Issue gets labeled (`bug` or `enhancement`, priority, `ai-ready`)
3. **Code Agent** workflow triggers (if `ai-ready` + `bug`/`enhancement`)

## Step 6: Start Building!

Now you're ready to build your actual application. The Hello World apps are just starters.

### Replacing the Backend

1. Delete/modify `backend/app/main.py`
2. Add your models, routes, services
3. Update tests in `backend/tests/`
4. Run locally: `uv run uvicorn app.main:app --reload`

### Replacing the Frontend

1. Modify `frontend/src/app/page.tsx`
2. Add components in `frontend/src/components/`
3. Update tests in `frontend/__tests__/`
4. Run locally: `npm run dev`

### Creating Issues for AI to Fix

The magic happens when you create issues:

```bash
# Feature request
gh issue create \
  --title "Add user authentication with JWT" \
  --body "Implement user registration and login endpoints..."

# Bug report
gh issue create \
  --title "API returns 500 when name is empty" \
  --body "Steps to reproduce: POST /api/hello with empty name..."
```

The Triage Agent will classify and label, then the Code Agent takes over!

---

## Manual Setup

If you prefer not to use the wizard, here are the manual steps:

### Create Labels

```bash
# Core labels
gh label create "ai-ready" --color "0E8A16" --description "Ready for autonomous agent"
gh label create "needs-principal-engineer" --color "7057FF" --description "Escalated to PE"
gh label create "needs-human" --color "D93F0B" --description "Requires human intervention"
gh label create "bug" --color "d73a4a" --description "Something isn't working"
gh label create "enhancement" --color "a2eeef" --description "New feature"

# Priority labels
gh label create "P0" --color "B60205" --description "Critical"
gh label create "P1" --color "D93F0B" --description "High"
gh label create "P2" --color "FBCA04" --description "Medium"

# Status labels
gh label create "status:bot-working" --color "7057FF" --description "Bot is working"
gh label create "status:awaiting-human" --color "D93F0B" --description "Waiting for human"
gh label create "status:awaiting-bot" --color "0E8A16" --description "Waiting for bot"

# Monitoring labels
gh label create "ci-failure" --color "B60205" --description "CI failure"
gh label create "production-incident" --color "B60205" --description "Production incident"
gh label create "qa-agent" --color "0052CC" --description "QA tracking"
gh label create "automation" --color "BFDADC" --description "Automated"
```

### Update CLAUDE.md

Edit `CLAUDE.md` and replace:
- `[Your Project Name]` → Your project name
- `[Your project description]` → Your description
- `@[your-github-username]` → Your GitHub username

### Activate CI

```bash
# CI workflow is already included as ci.yml
git add .github/workflows/ci.yml
git commit -m "chore: activate CI workflow"
git push
```

---

## Troubleshooting

### "Triage Agent didn't run"

1. Check if the workflow is enabled: **Actions → Triage Agent → Enable**
2. Verify `ANTHROPIC_API_KEY` secret is set
3. Check workflow logs for errors

### "Code Agent not creating PRs"

1. Issue needs BOTH `ai-ready` AND (`bug` OR `enhancement`) labels
2. Verify `PAT_WITH_WORKFLOW_ACCESS` is set correctly
3. Check if the issue is already assigned to a PR

### "Tests failing in CI"

```bash
# Run tests locally first
cd backend && uv run pytest
cd frontend && npm test

# Check coverage
cd backend && uv run pytest --cov=app
cd frontend && npm run test:coverage
```

### "Permission denied on setup.sh"

```bash
chmod +x scripts/setup.sh
./scripts/setup.sh
```

---

## Next Steps

1. **Read the Philosophy**: See `CLAUDE.md` for how agents think and operate
2. **Customize Agents**: Modify `.claude/agents/*.md` for your domain
3. **Add E2E Tests**: Uncomment E2E job in `ci.yml` and add Playwright tests
4. **Deploy**: Configure Railway or your preferred platform
5. **Monitor**: Set up production URLs for DevOps monitoring

---

## Getting Help

- **Documentation**: See `README.md` and `CLAUDE.md`
- **Issues**: Create an issue in the template repo
- **Claude Code**: https://github.com/anthropics/claude-code

Happy building! 🏭
