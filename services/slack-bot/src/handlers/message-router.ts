/**
 * Message router - routes all messages to Claude Code
 *
 * This bot uses Claude Code for ALL interactions, giving full capabilities:
 * - Read, Write, Edit files
 * - Run bash/terminal commands
 * - Git operations
 * - Search with Glob/Grep
 *
 * Special command: `dispatch <agent> <task>` creates GitHub issues for agents
 */

import type { AgentType, SlackSession, MessageIntent, IntentType } from '../types.js';
import { dispatchToAgent } from '../integrations/github-dispatcher.js';
import { executeWithClaudeCode, isClaudeCodeAvailable } from '../integrations/claude-code.js';
import sessionManager from '../state/session-manager.js';
import logger from '../utils/logger.js';

/**
 * Keywords that suggest agent dispatch
 */
const AGENT_KEYWORDS: Record<AgentType, string[]> = {
  triage: ['triage', 'classify', 'categorize', 'sort'],
  code: ['fix', 'implement', 'bug', 'feature', 'code', 'build', 'create'],
  qa: ['test', 'coverage', 'quality', 'qa'],
  devops: ['deploy', 'production', 'incident', 'monitor', 'health'],
  release: ['release', 'version', 'changelog', 'dependencies', 'security audit'],
  'principal-engineer': ['stuck', 'escalate', 'complex', 'architecture'],
};

/**
 * Parse message to determine intent
 */
export function parseIntent(message: string): MessageIntent {
  const lowerMessage = message.toLowerCase();

  // Check for dispatch commands (explicit agent dispatch)
  if (lowerMessage.startsWith('dispatch ')) {
    const parts = message.substring(9).trim().split(/\s+/);
    const agentName = parts[0]?.toLowerCase();

    const agentTypes: AgentType[] = ['triage', 'code', 'qa', 'devops', 'release', 'principal-engineer'];
    if (agentTypes.includes(agentName as AgentType)) {
      return {
        type: 'dispatch' as IntentType,
        agent: agentName as AgentType,
        extractedTask: parts.slice(1).join(' '),
        confidence: 1.0,
      };
    }
  }

  // Check for help
  if (lowerMessage === 'help' || lowerMessage === '?') {
    return {
      type: 'help' as IntentType,
      confidence: 1.0,
    };
  }

  // Everything else goes to Claude Code
  return {
    type: 'conversation' as IntentType,
    confidence: 1.0,
  };
}

/**
 * Route message to appropriate handler
 */
export async function routeMessage(
  message: string,
  session: SlackSession,
  onChunk?: (chunk: string) => void
): Promise<{
  response: string;
  dispatchedAgent?: AgentType;
  issueUrl?: string;
}> {
  const intent = parseIntent(message);
  const threadKey = `${session.channelId}:${session.threadTs}`;

  logger.info('Routing message', {
    intentType: intent.type,
    confidence: intent.confidence,
  });

  // Check Claude Code availability
  if (!isClaudeCodeAvailable()) {
    return {
      response: '❌ Claude Code SDK is not available. Please check the installation.',
    };
  }

  switch (intent.type) {
    // Dispatch to GitHub agents (creates issues)
    case 'dispatch':
      return handleDispatch(intent.agent!, intent.extractedTask || message, session);

    case 'help':
      return { response: getHelpMessage() };

    case 'conversation':
    default:
      // All messages go to Claude Code
      return handleClaudeCodeConversation(message, session, onChunk);
  }
}

/**
 * Handle agent dispatch (creates GitHub issue)
 */
async function handleDispatch(
  agent: AgentType,
  task: string,
  session: SlackSession
): Promise<{
  response: string;
  dispatchedAgent: AgentType;
  issueUrl?: string;
}> {
  logger.info('Dispatching to agent', { agent, task: task.substring(0, 100) });

  const result = await dispatchToAgent(agent, task, session);

  if (result.success && result.issueUrl) {
    return {
      response: `✅ Created issue #${result.issueNumber} for the *${agent}* agent.\n\n` +
        `*Task:* ${task.substring(0, 100)}${task.length > 100 ? '...' : ''}\n` +
        `*Issue:* ${result.issueUrl}\n\n` +
        `The agent will work on this autonomously. I'll update you on progress.`,
      dispatchedAgent: agent,
      issueUrl: result.issueUrl,
    };
  }

  return {
    response: `❌ Couldn't dispatch to ${agent} agent: ${result.error}\n\n` +
      `Check that GitHub integration is configured.`,
    dispatchedAgent: agent,
  };
}

/**
 * Handle conversation with Claude Code
 */
async function handleClaudeCodeConversation(
  message: string,
  session: SlackSession,
  onChunk?: (chunk: string) => void
): Promise<{
  response: string;
}> {
  const threadKey = `${session.channelId}:${session.threadTs}`;

  // Get conversation history for context
  const conversationHistory = sessionManager.getHistoryForClaude(
    session.channelId,
    session.threadTs
  );

  logger.debug('Fetched conversation history', {
    threadKey,
    historyLength: conversationHistory.length,
  });

  try {
    const result = await executeWithClaudeCode(
      message,
      session.userId,
      threadKey,
      {
        workingDirectory: session.workingDirectory,
        onProgress: onChunk,
        conversationHistory, // Pass history for multi-turn context
      }
    );

    if (result.error) {
      logger.error('Claude Code execution error', { error: result.error, threadKey });
    }

    return { response: result.content };
  } catch (error) {
    logger.error('Error in Claude Code conversation', { error, threadKey });
    return {
      response: '❌ Error executing Claude Code. Please try again.',
    };
  }
}

/**
 * Get help message
 */
function getHelpMessage(): string {
  return `*🤖 Claude Code Bot*

I have full Claude Code capabilities:
• *Files:* Read, Write, Edit any file
• *Search:* Glob patterns, Grep content
• *Terminal:* Run bash commands
• *Git:* status, diff, commit, push, branch
• *Web:* Search and fetch

*Examples:*
• "What files are in this directory?"
• "Show me the README"
• "Run git status"
• "Search for TODO comments"

*Dispatch to GitHub Agents:*
• \`dispatch code <task>\` - Create issue for Code Agent
• \`dispatch qa <task>\` - Create issue for QA Agent
• \`dispatch devops <task>\` - Create issue for DevOps Agent

Just ask me anything - I'll use the right tools automatically.`;
}

export default {
  parseIntent,
  routeMessage,
};
