/**
 * Message router - parses intent and routes to appropriate handler
 */

import type { AgentType, SlackSession, MessageIntent, IntentType } from '../types.js';
import { dispatchToAgent } from '../integrations/github-dispatcher.js';
import { chat, streamChat } from '../integrations/claude-sdk.js';
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

  // Check for status commands
  if (
    lowerMessage.includes('status') ||
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
  return `*Claude Software Factory Bot*

I'm your AI development assistant! Here's what I can do:

*Conversation*
Just chat with me naturally. I have context about your codebase and can help with:
- Code questions and explanations
- Debugging help
- Architecture discussions
- Documentation

*Dispatch to Agents*
Say "dispatch <agent> <task>" to create a GitHub issue for an agent:

- \`dispatch code fix the login bug\` - Code Agent fixes bugs/implements features
- \`dispatch qa improve test coverage\` - QA Agent improves testing
- \`dispatch devops check production health\` - DevOps Agent monitors systems
- \`dispatch release update dependencies\` - Release Engineer handles updates
- \`dispatch triage classify this issue\` - Triage Agent categorizes issues

*Commands*
- \`status\` - See current session status
- \`help\` - Show this message

*Tips*
- Start a thread for focused conversations
- I'll post updates when agents complete tasks
- Use reactions for quick feedback`;
}

export default {
  parseIntent,
  routeMessage,
};
