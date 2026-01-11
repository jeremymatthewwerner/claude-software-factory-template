/**
 * Message router - parses intent and routes to appropriate handler
 *
 * This bot provides TWO modes:
 * 1. Factory Commands: Quick status checks and agent dispatch
 * 2. Claude Code Mode: Full Claude Code capabilities (read, write, bash, git)
 *
 * Use "code mode" or "claude code" to enable full capabilities.
 * Use "factory mode" to return to quick commands.
 */

import type { AgentType, SlackSession, MessageIntent, IntentType } from '../types.js';
import { dispatchToAgent } from '../integrations/github-dispatcher.js';
import { chat, streamChat } from '../integrations/claude-sdk.js';
import { executeWithClaudeCode, isClaudeCodeAvailable } from '../integrations/claude-code.js';
import {
  getFactoryStatus,
  analyzeIssue,
  getFailurePatterns,
  getAgentPerformance,
  getWorkflowHealth,
} from './factory-commands.js';
import sessionManager from '../state/session-manager.js';
import logger from '../utils/logger.js';

// Track which threads are in "code mode" (full Claude Code capabilities)
const codeModeSessions = new Set<string>();

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
 * Factory command patterns
 */
const FACTORY_COMMANDS = {
  status: ['factory status', 'factory health', 'how is the factory', 'factory report'],
  analyze: ['analyze #', 'analyze issue', 'learn from #', 'what happened with #'],
  failures: ['failures', 'failure patterns', 'why is ci failing', 'what\'s failing', 'show failures'],
  agents: ['agent performance', 'how are agents', 'agent stats', 'autonomy rate'],
  workflows: ['workflow health', 'workflows', 'workflow status', 'check workflows'],
};

/**
 * Check if a thread is in code mode
 */
export function isCodeMode(threadKey: string): boolean {
  return codeModeSessions.has(threadKey);
}

/**
 * Enable code mode for a thread
 */
export function enableCodeMode(threadKey: string): void {
  codeModeSessions.add(threadKey);
  logger.info('Code mode enabled', { threadKey });
}

/**
 * Disable code mode for a thread
 */
export function disableCodeMode(threadKey: string): void {
  codeModeSessions.delete(threadKey);
  logger.info('Code mode disabled', { threadKey });
}

/**
 * Parse message to determine intent
 */
export function parseIntent(message: string): MessageIntent {
  const lowerMessage = message.toLowerCase();

  // Check for mode switching commands
  if (
    lowerMessage === 'code mode' ||
    lowerMessage === 'claude code' ||
    lowerMessage === 'enable code mode' ||
    lowerMessage.includes('switch to code mode')
  ) {
    return {
      type: 'enable-code-mode' as IntentType,
      confidence: 1.0,
    };
  }

  if (
    lowerMessage === 'factory mode' ||
    lowerMessage === 'disable code mode' ||
    lowerMessage.includes('switch to factory mode')
  ) {
    return {
      type: 'disable-code-mode' as IntentType,
      confidence: 1.0,
    };
  }

  // Check for factory commands first (these are the primary purpose)
  // Factory status
  if (FACTORY_COMMANDS.status.some(cmd => lowerMessage.includes(cmd))) {
    return {
      type: 'factory-status' as IntentType,
      confidence: 1.0,
    };
  }

  // Analyze issue
  const issueMatch = lowerMessage.match(/(?:analyze|learn from|what happened with)\s*#?(\d+)/i);
  if (issueMatch) {
    return {
      type: 'factory-analyze' as IntentType,
      confidence: 1.0,
      extractedTask: issueMatch[1], // issue number
    };
  }

  // Failure patterns
  if (FACTORY_COMMANDS.failures.some(cmd => lowerMessage.includes(cmd))) {
    return {
      type: 'factory-failures' as IntentType,
      confidence: 1.0,
    };
  }

  // Agent performance
  if (FACTORY_COMMANDS.agents.some(cmd => lowerMessage.includes(cmd))) {
    return {
      type: 'factory-agents' as IntentType,
      confidence: 1.0,
    };
  }

  // Workflow health
  if (FACTORY_COMMANDS.workflows.some(cmd => lowerMessage.includes(cmd))) {
    return {
      type: 'factory-workflows' as IntentType,
      confidence: 1.0,
    };
  }

  // Check for explicit dispatch commands
  if (lowerMessage.startsWith('/dispatch ') || lowerMessage.startsWith('dispatch ')) {
    const agentMatch = lowerMessage.match(/dispatch\s+(\w+)/);
    if (agentMatch) {
      const agent = agentMatch[1] as AgentType;
      if (Object.keys(AGENT_KEYWORDS).includes(agent)) {
        return {
          type: 'dispatch' as IntentType,
          agent,
          confidence: 1.0,
          extractedTask: message.replace(/\/?(dispatch\s+\w+\s*)/i, '').trim(),
        };
      }
    }
  }

  // Check for status commands (session status, not factory)
  if (
    lowerMessage === 'status' ||
    lowerMessage.includes('what are you working on') ||
    lowerMessage.includes("what's happening")
  ) {
    return {
      type: 'status' as IntentType,
      confidence: 0.8,
    };
  }

  // Check for help commands
  if (
    lowerMessage === 'help' ||
    lowerMessage.startsWith('help ') ||
    lowerMessage.includes('what can you do')
  ) {
    return {
      type: 'help' as IntentType,
      confidence: 1.0,
    };
  }

  // Check for agent keywords to suggest dispatch
  for (const [agent, keywords] of Object.entries(AGENT_KEYWORDS)) {
    for (const keyword of keywords) {
      if (lowerMessage.includes(keyword)) {
        // Don't auto-dispatch, but note the suggestion
        return {
          type: 'conversation' as IntentType,
          suggestedAgent: agent as AgentType,
          confidence: 0.6,
        };
      }
    }
  }

  // Default to conversation
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
    suggestedAgent: intent.suggestedAgent,
    codeMode: isCodeMode(threadKey),
  });

  // Handle mode switching first
  switch (intent.type) {
    case 'enable-code-mode':
      if (!isClaudeCodeAvailable()) {
        return {
          response: '❌ Claude Code SDK is not available. Please check the installation.',
        };
      }
      enableCodeMode(threadKey);
      return {
        response: `🚀 *Code Mode Enabled*

You now have full Claude Code capabilities:
• Read, Write, Edit files
• Run bash/terminal commands
• Git operations (status, diff, commit, push)
• Search code with Glob/Grep

Just tell me what you want to do. I'll use the same tools as the Claude Code CLI.

Say \`factory mode\` to return to quick commands.`,
      };

    case 'disable-code-mode':
      disableCodeMode(threadKey);
      return {
        response: `🏭 *Factory Mode Enabled*

Back to quick factory commands:
• \`factory status\` - Health overview
• \`failures\` - CI failure patterns
• \`dispatch code <task>\` - Send to Code Agent

Say \`code mode\` to get full Claude Code capabilities.`,
      };
  }

  // If in code mode, route ALL messages to Claude Code (except explicit factory commands)
  if (isCodeMode(threadKey)) {
    // Still allow factory commands in code mode
    if (intent.type.startsWith('factory-')) {
      // Fall through to handle factory commands
    } else if (intent.type === 'dispatch') {
      return handleDispatch(intent.agent!, intent.extractedTask || message, session);
    } else if (intent.type === 'help') {
      return { response: getCodeModeHelpMessage() };
    } else {
      // Execute with full Claude Code capabilities
      return handleClaudeCodeConversation(message, session, onChunk);
    }
  }

  switch (intent.type) {
    // Factory improvement commands (primary purpose)
    case 'factory-status':
      return { response: await getFactoryStatus() };

    case 'factory-analyze':
      return { response: await analyzeIssue(parseInt(intent.extractedTask || '0', 10)) };

    case 'factory-failures':
      return { response: await getFailurePatterns() };

    case 'factory-agents':
      return { response: await getAgentPerformance() };

    case 'factory-workflows':
      return { response: await getWorkflowHealth() };

    // Dispatch to agents (for creating work, not fixing it yourself)
    case 'dispatch':
      return handleDispatch(intent.agent!, intent.extractedTask || message, session);

    case 'status':
      return handleStatusRequest(session);

    case 'help':
      return {
        response: getHelpMessage(),
      };

    case 'conversation':
    default:
      return handleConversation(message, session, intent.suggestedAgent, onChunk);
  }
}

/**
 * Handle agent dispatch
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
      response: `I've created issue #${result.issueNumber} for the ${agent} agent to handle.\n\n` +
        `*Task:* ${task.substring(0, 100)}${task.length > 100 ? '...' : ''}\n` +
        `*Issue:* ${result.issueUrl}\n\n` +
        `I'll keep you updated on progress in this thread.`,
      dispatchedAgent: agent,
      issueUrl: result.issueUrl,
    };
  }

  return {
    response: `I wasn't able to dispatch to the ${agent} agent: ${result.error}\n\n` +
      `Please check that GitHub integration is configured correctly.`,
    dispatchedAgent: agent,
  };
}

/**
 * Handle status request
 */
async function handleStatusRequest(session: SlackSession): Promise<{
  response: string;
}> {
  const parts: string[] = ['*Current Status*\n'];

  if (session.linkedIssue) {
    parts.push(`*Linked Issue:* #${session.linkedIssue}`);
  }

  if (session.linkedPR) {
    parts.push(`*Linked PR:* #${session.linkedPR}`);
  }

  if (session.activeAgent) {
    parts.push(`*Active Agent:* ${session.activeAgent}`);
  }

  parts.push(`*Working Directory:* \`${session.workingDirectory}\``);
  parts.push(`*Session Status:* ${session.status}`);

  if (parts.length === 1) {
    parts.push('No active tasks. Start a conversation or dispatch to an agent!');
  }

  return {
    response: parts.join('\n'),
  };
}

/**
 * Handle conversation with Claude
 */
async function handleConversation(
  message: string,
  session: SlackSession,
  suggestedAgent: AgentType | undefined,
  onChunk?: (chunk: string) => void
): Promise<{
  response: string;
}> {
  // Add user message to history
  sessionManager.addMessage(session.channelId, session.threadTs, 'user', message);

  // Get conversation history for Claude
  const history = sessionManager.getHistoryForClaude(session.channelId, session.threadTs);

  // Build context
  const context = {
    workingDirectory: session.workingDirectory,
    linkedIssue: session.linkedIssue,
    linkedPR: session.linkedPR,
    activeAgent: session.activeAgent,
  };

  let response: string;

  try {
    if (onChunk) {
      // Streaming response
      const result = await streamChat(history, session.userId, onChunk, context);
      response = result.content;
    } else {
      // Non-streaming response
      const result = await chat(history, session.userId, context);
      response = result.content;
    }

    // Add suggestion if we detected an agent might help
    if (suggestedAgent && !response.includes('dispatch')) {
      response += `\n\n_Tip: If you'd like me to take action, say "dispatch ${suggestedAgent}" followed by what you'd like done._`;
    }

    // Add assistant response to history
    sessionManager.addMessage(session.channelId, session.threadTs, 'assistant', response);

    return { response };
  } catch (error) {
    logger.error('Error in conversation', { error });
    return {
      response: 'I encountered an error processing your message. Please try again.',
    };
  }
}

/**
 * Handle conversation with full Claude Code capabilities
 */
async function handleClaudeCodeConversation(
  message: string,
  session: SlackSession,
  onChunk?: (chunk: string) => void
): Promise<{
  response: string;
}> {
  const threadKey = `${session.channelId}:${session.threadTs}`;

  try {
    const result = await executeWithClaudeCode(
      message,
      session.userId,
      threadKey,
      {
        workingDirectory: session.workingDirectory,
        onProgress: onChunk,
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
 * Get help message for factory mode
 */
function getHelpMessage(): string {
  return `*🏭 Factory Bot - Two Modes*

*Current: Factory Mode* (quick commands)

*Factory Diagnostics:*
• \`factory status\` - Overall factory health
• \`failures\` - CI/workflow failure patterns
• \`agent performance\` - Agent metrics
• \`analyze #123\` - Learn from an issue

*Dispatch to Agents:*
• \`dispatch code <task>\` - Code Agent
• \`dispatch qa <task>\` - QA Agent
• \`dispatch devops <task>\` - DevOps Agent

*Switch Modes:*
• \`code mode\` - Enable full Claude Code capabilities (files, git, bash)
• \`factory mode\` - Return to quick commands (current)

_Say \`code mode\` to get Claude Code capabilities directly in Slack!_`;
}

/**
 * Get help message for code mode
 */
function getCodeModeHelpMessage(): string {
  return `*🚀 Code Mode Active*

You have full Claude Code capabilities:
• *Files:* Read, Write, Edit any file
• *Search:* Glob patterns, Grep content
• *Terminal:* Run bash commands
• *Git:* status, diff, commit, push, branch
• *Web:* Search and fetch

*Examples:*
• "Show me the main config file"
• "What's in the latest commit?"
• "Run the tests"
• "Create a new feature branch"
• "Search for TODO comments"

*Factory commands still work:*
• \`factory status\`, \`failures\`, \`dispatch code <task>\`

*Switch back:*
• \`factory mode\` - Return to quick commands`;
}

export default {
  parseIntent,
  routeMessage,
  isCodeMode,
  enableCodeMode,
  disableCodeMode,
};
