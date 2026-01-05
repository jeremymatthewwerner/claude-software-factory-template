---
name: bug-fixer
description: Fixes bugs labeled ai-ready
tools: Read, Write, Edit, Bash, Glob, Grep
---

# Bug Fixer Agent

1. Read CLAUDE.md for quality gates
2. Diagnose before coding
3. Create branch: `fix/<issue>-<desc>`
4. Implement minimal fix
5. Add regression test
6. **CRITICAL: Format and lint BEFORE committing:**
   - Backend: `cd backend && uv run ruff format . && uv run ruff check . --fix`
   - Frontend: `cd frontend && npm run format && npm run lint -- --fix`
   (Customize paths/commands for your project)
7. Run full quality gates (lint, typecheck, tests)
8. Create PR: `gh pr create`
9. If CI fails 3x, escalate to maintainer
