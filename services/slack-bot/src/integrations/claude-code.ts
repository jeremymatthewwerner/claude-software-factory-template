/**
 * Claude Code integration for the Slack bot
 *
 * This module provides full Claude Code capabilities via the Claude Agent SDK,
 * giving the Slack bot access to:
 * - File system operations (Read, Write, Edit, Glob, Grep)
 * - Terminal/bash execution
 * - Git operations
 * - Web search and fetch
 *
 * This is the "Claude Code in Slack" experience.
 */

import { query, type SDKMessage } from '@anthropic-ai/claude-code';
import { execSync } from 'child_process';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';
import { config } from '../config.js';
import logger from '../utils/logger.js';
import { rateLimiter } from '../utils/rate-limiter.js';

// Get absolute path to node executable - critical for Railway containers
const nodeExecutablePath = process.execPath;
logger.info('Node executable path', { nodeExecutablePath });

// Find the Claude Code CLI path
const claudeCodeCliPath = join(
  dirname(fileURLToPath(import.meta.resolve('@anthropic-ai/claude-code'))),
  'cli.js'
);
logger.info('Claude Code CLI path', { claudeCodeCliPath });

/**
 * Session state for multi-turn conversations
 */
interface ClaudeCodeSession {
  sessionId?: string;
  workingDirectory: string;
  lastActivity: Date;
}

// Track sessions by Slack thread
const sessions = new Map<string, ClaudeCodeSession>();

/**
 * System prompt for Claude Code in Slack
 */
const SYSTEM_PROMPT = `You are Claude Code, running inside a Slack bot for the Claude Software Factory.

## Your Capabilities
You have FULL Claude Code capabilities:
- Read, Write, Edit files in the codebase
- Run bash/terminal commands
- Git operations (status, diff, commit, push, branch)
- Search code with Glob and Grep
- Web search and fetch

## Context
You're working on a software factory template repository. The codebase includes:
- GitHub Actions workflows for autonomous agents
- A Slack bot (this service) at services/slack-bot/
- Backend (FastAPI/Python) and Frontend (Next.js/TypeScript) starters
- Documentation in CLAUDE.md, README.md, REQUIREMENTS.md

## Deployment (Railway)
This Slack bot is deployed on Railway with auto-deploy from git.

### Railway Management Script
Use the railway.sh script for deployment operations:
\`\`\`bash
# Check current deployment status
./services/slack-bot/scripts/railway.sh status

# View deployment logs
./services/slack-bot/scripts/railway.sh logs 100

# List recent deployments (for rollback reference)
./services/slack-bot/scripts/railway.sh deployments 10

# Trigger manual redeploy
./services/slack-bot/scripts/railway.sh redeploy

# Rollback to a previous deployment
./services/slack-bot/scripts/railway.sh rollback <deployment-id>

# Get service info
./services/slack-bot/scripts/railway.sh info
\`\`\`

### Deploy Code Changes
To deploy new code changes:
1. Make the code changes
2. Run \`npm run build\` in services/slack-bot/ to verify TypeScript compiles
3. Commit with a descriptive message: \`git add -A && git commit -m "fix: description"\`
4. Push to trigger auto-deploy: \`git push\`
5. Verify with: \`./services/slack-bot/scripts/railway.sh status\`

### Quick Reference
- **Health check:** \`curl https://claude-software-factory-template-production.up.railway.app/health\`
- **Test endpoint:** POST /test-claude-code (requires x-test-secret header)
- Railway auto-deploys within 1-2 minutes of push

## Working Style
- Be concise in Slack (it's chat, not a document)
- Be direct and professional - avoid filler words like "Perfect!", "Excellent!", "Great!"
- Don't narrate your process excessively - just do the work and report results
- Show file paths when making changes
- For complex tasks, break them into steps
- Commit frequently when making changes
- Always check CI status after pushing

## CRITICAL: Git Operations
When doing git operations, you MUST:
1. ALWAYS show the actual output of git commands (git status, git push, etc.)
2. NEVER claim you pushed code without showing the actual push output
3. If a git command fails, report the error - don't pretend it succeeded
4. Verify the working directory is correct before git operations: \`pwd\` and \`git remote -v\`
5. After pushing, verify with: \`git log origin/main -1 --oneline\` or check GitHub

Example of what NOT to do:
❌ "I've pushed the changes to main"  (no proof)

Example of what TO do:
✅ Show actual output:
\`\`\`
$ git push origin main
Enumerating objects: 5, done.
To https://github.com/owner/repo.git
   abc123..def456  main -> main
\`\`\`

## Factory Philosophy
- Human intervention = factory bug
- Fix the factory, not just the symptom
- Document improvements in CLAUDE.md

You have the same power as the CLI - use it wisely.`;

/**
 * Get or create a session for a Slack thread
 */
function getSession(threadKey: string, workingDirectory: string): ClaudeCodeSession {
  let session = sessions.get(threadKey);

  if (!session) {
    session = {
      workingDirectory,
      lastActivity: new Date(),
    };
    sessions.set(threadKey, session);
    logger.debug('Created new Claude Code session', { threadKey });
  } else {
    session.lastActivity = new Date();
  }

  return session;
}

/**
 * Execute a prompt with full Claude Code capabilities
 */
export async function executeWithClaudeCode(
  prompt: string,
  userId: string,
  threadKey: string,
  options: {
    workingDirectory?: string;
    onProgress?: (text: string) => void;
    onToolUse?: (tool: string, input: string) => void;
    conversationHistory?: Array<{ role: 'user' | 'assistant'; content: string }>;
  } = {}
): Promise<{
  content: string;
  toolsUsed: string[];
  error?: string;
}> {
  // Check rate limits
  const limitCheck = rateLimiter.checkLimit(userId);
  if (!limitCheck.allowed) {
    return {
      content: `⏳ Rate limit reached. Please wait ${limitCheck.retryAfter} seconds.`,
      toolsUsed: [],
      error: 'rate_limit',
    };
  }

  // Use process.cwd() as default - config.repo.basePath (/repos) may not exist in Railway containers
  // which causes spawn to fail with ENOENT (confusingly reported as "node" not found)
  const workingDir = options.workingDirectory || process.cwd();
  const session = getSession(threadKey, workingDir);
  const toolsUsed: string[] = [];

  // CRITICAL: Modify parent process PATH so spawn() can find node
  // The env option only affects the child process AFTER spawn, not the spawn lookup itself
  // Declare outside try so it's accessible in catch for cleanup
  const originalPath = process.env.PATH;
  const nodeBinDir = dirname(nodeExecutablePath);
  process.env.PATH = `${nodeBinDir}:${originalPath || '/usr/local/bin:/usr/bin:/bin'}`;

  // Collect stderr for error reporting
  let stderrOutput = '';

  try {
    // Build conversation context by prepending history to the prompt
    // The SDK only accepts a single prompt string, not a messages array
    const history = options.conversationHistory || [];
    let fullPrompt = prompt;

    if (history.length > 0) {
      // Build context from previous conversation turns
      const contextParts = ['<conversation_history>'];
      for (const msg of history) {
        const role = msg.role === 'user' ? 'Human' : 'Assistant';
        contextParts.push(`${role}: ${msg.content}`);
      }
      contextParts.push('</conversation_history>');
      contextParts.push('');
      contextParts.push('Continue the conversation. Here is the latest message from the user:');
      contextParts.push('');
      contextParts.push(prompt);
      fullPrompt = contextParts.join('\n');
    }

    logger.info('Executing Claude Code query', {
      userId,
      threadKey,
      workingDirectory: workingDir,
      promptLength: prompt.length,
      historyLength: history.length,
      fullPromptLength: fullPrompt.length,
      nodeBinDir,
      modifiedPath: process.env.PATH,
    });

    let fullContent = '';

    // Execute with Claude Code SDK
    // Note: We explicitly set executable to 'node' and provide the path for Railway containers
    // The SDK defaults env to {...process.env}, which will include our modified PATH
    for await (const message of query({
      prompt: fullPrompt,
      options: {
        model: config.anthropic.model || 'claude-sonnet-4-20250514',
        allowedTools: [
          'Read',
          'Write',
          'Edit',
          'Bash',
          'Glob',
          'Grep',
          'WebFetch',
          'WebSearch',
        ],
        cwd: workingDir,
        appendSystemPrompt: SYSTEM_PROMPT,
        maxTurns: 50, // Reasonable limit for Slack interactions
        // Note: 'bypassPermissions' can't be used when running as root (Railway)
        // 'acceptEdits' auto-accepts file edits
        permissionMode: 'acceptEdits',
        // Use absolute paths to avoid ENOENT errors in containers
        pathToClaudeCodeExecutable: claudeCodeCliPath,
        executable: 'node',
        // Capture stderr for debugging and error reporting
        stderr: (data: string) => {
          stderrOutput += data;
          logger.error('Claude Code stderr', { stderr: data });
        },
        // Environment setup for containers
        env: {
          ...process.env,
          // Ensure HOME is set (required by Claude Code CLI for config)
          HOME: process.env.HOME || '/tmp',
          // Enable debug mode to see what's happening
          DEBUG: '1',
        },
      },
    })) {
      // Handle different message types
      switch (message.type) {
        case 'assistant':
          // Extract text from assistant message
          for (const block of message.message.content) {
            if ('text' in block && block.text) {
              // Add newline separator if we already have content
              // This ensures multi-turn responses are properly formatted
              if (fullContent && !fullContent.endsWith('\n')) {
                fullContent += '\n\n';
                options.onProgress?.('\n\n');
              }
              fullContent += block.text;
              options.onProgress?.(block.text);
            }
          }
          break;

        case 'user':
          // Tool results come back as user messages
          if (message.message.content) {
            for (const block of message.message.content) {
              if (block.type === 'tool_result' && 'tool_use_id' in block) {
                // Tool completed
                logger.debug('Tool result received', {
                  toolUseId: block.tool_use_id,
                });
              }
            }
          }
          break;

        case 'result':
          // Query completed
          logger.info('Claude Code query completed', {
            subtype: message.subtype,
            threadKey,
          });

          // Save session ID if available
          if ('session_id' in message && message.session_id) {
            session.sessionId = message.session_id as string;
          }
          break;
      }
    }

    // Restore original PATH
    process.env.PATH = originalPath;

    // Track approximate token usage (we don't get exact counts from query())
    rateLimiter.addTokens(userId, Math.ceil(fullContent.length / 4));

    return {
      content: fullContent || 'Task completed.',
      toolsUsed,
    };
  } catch (error) {
    // Restore original PATH even on error
    process.env.PATH = originalPath;

    logger.error('Error executing Claude Code', { error, userId, threadKey });

    // Extract detailed error info
    let errorMessage = 'Unknown error';
    let errorDetails = '';

    if (error instanceof Error) {
      errorMessage = error.message;
      // Check for common issues
      if (error.message.includes('exited with code 1')) {
        // Include stderr output if available for more context
        const stderrInfo = stderrOutput ? `\n\nStderr output:\n${stderrOutput.slice(-500)}` : '';

        errorDetails = '\n\nPossible causes:\n' +
          '• ANTHROPIC_API_KEY not set or invalid\n' +
          '• Missing required environment variables\n' +
          '• Claude Code CLI initialization failed' +
          stderrInfo;

        // Log environment for debugging (without sensitive values)
        logger.error('Claude Code env check', {
          hasAnthropicKey: !!process.env.ANTHROPIC_API_KEY,
          anthropicKeyPrefix: process.env.ANTHROPIC_API_KEY?.substring(0, 10) + '...',
          cwd: workingDir,
          nodeExecutable: nodeExecutablePath,
          stderrOutput: stderrOutput.slice(-1000),
        });
      }
      if (error.stack) {
        logger.error('Claude Code stack trace', { stack: error.stack });
      }
    }

    return {
      content: `❌ Error: ${errorMessage}${errorDetails}`,
      toolsUsed,
      error: errorMessage,
    };
  }
}

/**
 * Check if Claude Code is available (SDK installed and configured)
 */
export function isClaudeCodeAvailable(): boolean {
  try {
    // The SDK should be available if the import succeeded
    return typeof query === 'function';
  } catch {
    return false;
  }
}

/**
 * Validate the ANTHROPIC_API_KEY by making a test API call
 * Call this at startup to fail fast if the key is invalid
 */
export async function validateApiKey(): Promise<{
  valid: boolean;
  error?: string;
  keyPrefix?: string;
}> {
  const apiKey = process.env.ANTHROPIC_API_KEY;

  if (!apiKey) {
    return {
      valid: false,
      error: 'ANTHROPIC_API_KEY environment variable is not set',
    };
  }

  const keyPrefix = apiKey.substring(0, 10) + '...';

  try {
    // Make a minimal API call to validate the key
    const response = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01',
        'content-type': 'application/json',
      },
      body: JSON.stringify({
        model: 'claude-sonnet-4-20250514',
        max_tokens: 1,
        messages: [{ role: 'user', content: 'Hi' }],
      }),
    });

    if (response.ok) {
      logger.info('ANTHROPIC_API_KEY validated successfully', { keyPrefix });
      return { valid: true, keyPrefix };
    }

    const errorData = await response.json().catch(() => ({})) as { error?: { message?: string } };
    const errorMessage = errorData.error?.message || `HTTP ${response.status}`;

    logger.error('ANTHROPIC_API_KEY validation failed', {
      keyPrefix,
      status: response.status,
      error: errorMessage
    });

    return {
      valid: false,
      error: `API key validation failed: ${errorMessage}`,
      keyPrefix,
    };
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : 'Unknown error';
    logger.error('ANTHROPIC_API_KEY validation error', { keyPrefix, error: errorMessage });

    return {
      valid: false,
      error: `Failed to validate API key: ${errorMessage}`,
      keyPrefix,
    };
  }
}

/**
 * Cleanup old sessions (call periodically)
 */
export function cleanupSessions(maxAgeMs: number = 3600000): void {
  const now = new Date();
  let cleaned = 0;

  for (const [key, session] of sessions.entries()) {
    const age = now.getTime() - session.lastActivity.getTime();
    if (age > maxAgeMs) {
      sessions.delete(key);
      cleaned++;
    }
  }

  if (cleaned > 0) {
    logger.debug('Cleaned up old Claude Code sessions', { count: cleaned });
  }
}

export default {
  executeWithClaudeCode,
  isClaudeCodeAvailable,
  validateApiKey,
  cleanupSessions,
};
