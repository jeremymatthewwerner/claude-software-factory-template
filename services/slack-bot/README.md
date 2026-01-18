# Claude Software Factory - Slack Bot

A conversational meta-agent that provides a Slack interface for interacting with your Claude-powered software factory.

## What This Bot Does

This bot gives you a **Claude Code-like experience in Slack**:

1. **Conversational AI** - Chat naturally about your codebase
2. **Agent Dispatch** - Send tasks to GitHub-based agents (triage, code, QA, etc.)
3. **Status Updates** - Receive progress notifications in Slack threads
4. **Intervention Help** - Collaborate when workflows need human input

> **Important**: The actual agents (triage, code, QA, devops) still work via GitHub Actions. This bot is your collaboration layer on top of that system.

## Quick Start

### 1. Run the Setup Wizard

```bash
./scripts/setup-slack.sh
```

This guides you through:
- Creating a Slack app with correct permissions
- Enabling Socket Mode for real-time events
- Setting up GitHub secrets

### 2. Deploy the Bot

**Option A: Railway**

Add a new service in your Railway project pointing to `services/slack-bot/`.

**Option B: Local Development**

```bash
cd services/slack-bot
cp .env.example .env
# Edit .env with your values
npm install
npm run dev
```

### 3. Invite to a Channel

```
/invite @Claude Factory
```

Then start chatting:
```
@Claude Factory What's the status of the project?
```

## Features

### Conversational Mode

Just chat naturally:

```
@Claude Factory How does the authentication system work?

@Claude Factory Can you explain the API error handling?
```

### Dispatch to Agents

Create GitHub issues for agents to handle:

```
@Claude Factory dispatch code fix the login timeout bug

@Claude Factory dispatch qa improve test coverage for auth module

@Claude Factory dispatch devops check why staging is slow
```

This creates a GitHub issue with appropriate labels, and the corresponding agent workflow picks it up.

### Status Updates

When agents complete work, they post updates back to your Slack thread:

```
🚀 Code Agent - Started working
⏳ Code Agent - In progress
   Analyzing codebase for affected files...
✅ Code Agent - Completed
   PR: #42 | View PR
```

### Slash Commands

```
/claude help                     - Show help
/claude dispatch code <task>     - Dispatch to Code Agent
/claude status                   - Show current status
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                       Slack Workspace                        │
│  ┌─────────────────┐      ┌────────────────────────────┐   │
│  │  User in #dev   │──────│  Claude Factory Bot        │   │
│  └─────────────────┘      │  (Socket Mode)             │   │
│                           └────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Slack Bot Service                         │
│  ┌──────────────┐  ┌────────────────┐  ┌──────────────┐    │
│  │ Message      │  │ Claude SDK     │  │ GitHub       │    │
│  │ Router       │──│ Integration    │  │ Dispatcher   │    │
│  └──────────────┘  └────────────────┘  └──────────────┘    │
│                                                              │
│  ┌──────────────┐  ┌────────────────┐                      │
│  │ Webhook      │  │ Session        │                      │
│  │ Handler      │  │ Manager        │                      │
│  └──────────────┘  └────────────────┘                      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      GitHub Repository                       │
│                                                              │
│  Issues ──────────────────▶ Agent Workflows                 │
│    │                           │                            │
│    └── ai-ready + bug ────────▶ bug-fix.yml                │
│    └── needs-pe ───────────────▶ principal-engineer.yml    │
│    └── ... etc                                              │
│                                                              │
│  Agent Workflows ──webhook──▶ Slack Bot (status updates)   │
└─────────────────────────────────────────────────────────────┘
```

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SLACK_BOT_TOKEN` | Yes | Bot User OAuth Token (xoxb-...) |
| `SLACK_APP_TOKEN` | Yes | App-Level Token (xapp-...) |
| `SLACK_SIGNING_SECRET` | Yes | Signing Secret from app settings |
| `ANTHROPIC_API_KEY` | Yes | Your Anthropic API key |
| `GITHUB_TOKEN` | Yes | GitHub PAT for creating issues |
| `GITHUB_REPOSITORY` | Yes | owner/repo format |
| `REPO_BASE_PATH` | No | Base path for repositories |
| `WEBHOOK_PORT` | No | Port for webhook server (default: 3001) |
| `WEBHOOK_SECRET` | No | Secret for validating webhooks |
| `LOG_LEVEL` | No | Logging level (default: info) |
| `RAILWAY_TOKEN` | No | Railway API token (for deployment management) |
| `RAILWAY_SERVICE_ID` | No | Railway service ID |
| `RAILWAY_ENVIRONMENT_ID` | No | Railway environment ID |

### Railway Configuration (Optional)

To enable the bot to manage its own deployments (view logs, rollback, redeploy):

1. **Get Railway Token:**
   - Go to [Railway Account Settings](https://railway.app/account/tokens)
   - Create a new token with full access

2. **Get Service & Environment IDs:**
   ```bash
   # Using Railway CLI
   railway whoami
   railway status

   # Or from Railway dashboard URL:
   # https://railway.app/project/<PROJECT_ID>/service/<SERVICE_ID>
   ```

3. **Add to Railway environment variables:**
   ```
   RAILWAY_TOKEN=<your-token>
   RAILWAY_SERVICE_ID=<service-id>
   RAILWAY_ENVIRONMENT_ID=<environment-id>
   ```

4. **Test the integration:**
   ```bash
   # In Slack, ask the bot:
   @Claude Factory check deployment status
   @Claude Factory show me the deployment logs
   ```

### MCP Servers

The bot uses MCP servers for extended capabilities:

- **Filesystem** - Read/write repository files
- **GitHub** - GitHub API access
- **Bash** - Shell command execution

Configure in `mcp-servers.json`.

## Webhook Endpoints

The bot exposes webhooks for agent workflows:

### Health Check
```
GET /webhooks/health
```

### Agent Status Update
```
POST /webhooks/agent-status
Authorization: Bearer <WEBHOOK_SECRET>

{
  "agent": "code",
  "status": "progress",
  "issueNumber": 42,
  "slackChannelId": "C1234567",
  "slackThreadTs": "1234567890.123456",
  "message": "Analyzing affected files...",
  "links": {
    "issue": "https://github.com/owner/repo/issues/42",
    "pr": "https://github.com/owner/repo/pull/43"
  }
}
```

### CI Status Update
```
POST /webhooks/ci-status
Authorization: Bearer <WEBHOOK_SECRET>

{
  "prNumber": 43,
  "status": "success",
  "workflowName": "CI/CD",
  "runUrl": "https://github.com/...",
  "slackChannelId": "C1234567",
  "slackThreadTs": "1234567890.123456"
}
```

## Development

```bash
# Install dependencies
npm install

# Run in development mode (with hot reload)
npm run dev

# Build for production
npm run build

# Run production build
npm start

# Lint
npm run lint

# Type check
npm run typecheck
```

## Troubleshooting

### Bot not responding

1. Check Socket Mode is enabled in Slack app settings
2. Verify `SLACK_APP_TOKEN` is the App-Level token (xapp-...)
3. Check logs for connection errors

### Agent dispatch failing

1. Verify `GITHUB_TOKEN` has repo write access
2. Check `GITHUB_REPOSITORY` format (owner/repo)
3. Ensure issue labels exist in the repository

### Status updates not appearing

1. Verify webhook secret matches between workflow and bot
2. Check webhook endpoint is accessible (Railway provides public URL)
3. Review workflow logs for HTTP errors

## Contributing

When improving this bot:

1. Follow the existing code patterns
2. Add tests for new functionality
3. Update this README for new features
4. The bot should remain a "meta-agent" - don't move agent logic here

<!-- Test deployment trigger - 2025-01-17 23:26 -->