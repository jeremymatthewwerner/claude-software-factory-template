/**
 * Message router - parses intent and routes to appropriate handler
 *
 * IMPORTANT: This bot's job is NOT to unblock specific issues, PRs, or actions.
 * Its job is to help engineers identify patterns, diagnose systemic issues,
 * and improve the factory workflows to be more robust, autonomous, and general.
 *
 * The factory should fix issues. This bot helps fix the factory.
 */

import type { AgentType, SlackSession, MessageIntent, IntentType } from '../types.js';
import { dispatchToAgent } from '../integrations/github-dispatcher.js';
import { chat, streamChat } from '../integrations/claude-sdk.js';
import {
  getFactoryStatus,
  analyzeIssue,
  getFailurePatterns,
  getAgentPerformance,
  getWorkflowHealth,
  getRepositoryStatus,
  setFactoryStatus,
} from './factory-commands.js';
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
 * Factory command patterns
 */
const FACTORY_COMMANDS = {
  status: ['factory status', 'factory health', 'how is the factory', 'factory report'],
  analyze: ['analyze #', 'analyze issue', 'learn from #', 'what happened with #'],
  failures: ['failures', 'failure patterns', 'why is ci failing', 'what\'s failing', 'show failures'],
  agents: ['agent performance', 'how are agents', 'agent stats', 'autonomy rate'],
  workflows: ['workflow health', 'workflows', 'workflow status', 'check workflows'],
  repos: ['repo status', 'repository status', 'current repo', 'working on', 'bot status'],
  setStatus: ['set status', 'update status', 'factory status to'],
};

/**
 * Parse message to determine intent
 */
export function parseIntent(message: string): MessageIntent {
  const lowerMessage = message.toLowerCase();

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

  // Repository status
  if (FACTORY_COMMANDS.repos.some(cmd => lowerMessage.includes(cmd))) {
    return {
      type: 'repo-status' as IntentType,
      confidence: 1.0,
    };
  }

  // Set status
  const setStatusMatch = lowerMessage.match(/(?:set status|update status|factory status to)\s+(.+)/i);
  if (setStatusMatch || FACTORY_COMMANDS.setStatus.some(cmd => lowerMessage.includes(cmd))) {
    return {
      type: 'set-status' as IntentType,
      confidence: 1.0,
      extractedTask: setStatusMatch ? setStatusMatch[1] : undefined,
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

  logger.info('Routing message', {
    intentType: intent.type,
    confidence: intent.confidence,
    suggestedAgent: intent.suggestedAgent,
  });

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

    case 'repo-status':
      return { response: await getRepositoryStatus() };

    case 'set-status':
      const statusText = intent.extractedTask || 'idle';
      return { response: await setFactoryStatus(statusText) };

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
 * Get help message
 */
function getHelpMessage(): string {
  return `*🏭 Factory Improvement Bot*

My job is to help you *improve the factory*, not fix individual issues.
The factory should fix issues. I help you fix the factory.

*Factory Diagnostics (my primary purpose):*
- \`factory status\` - Overall factory health & autonomy metrics
- \`failures\` - CI/workflow failure patterns (what's brittle?)
- \`agent performance\` - Which agents need improvement?
- \`workflows\` - Check workflow configuration
- \`analyze #123\` - Learn from an issue (why did it escalate?)

*Repository & Status Management:*
- \`repo status\` - Show current working repositories and bot status
- \`set status <text>\` - Manually update bot status message

*Dispatch Work (create issues for agents):*
- \`dispatch code <task>\` - Code Agent
- \`dispatch qa <task>\` - QA Agent
- \`dispatch devops <task>\` - DevOps Agent

*Philosophy:*
• Each escalation = factory bug. Find the pattern, fix the workflow.
• Don't unblock issues—make the factory handle them autonomously.
• Low autonomy rate? Improve agent prompts/workflows.
• High failure rate? Harden the brittle workflows.

*For direct code work:* Use claude.ai/code or the CLI.
I'm your factory control panel, not an IDE.`;
}

export default {
  parseIntent,
  routeMessage,
};
