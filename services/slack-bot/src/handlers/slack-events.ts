/**
 * Slack event handlers
 */

import type { App, MessageEvent, AppMentionEvent } from '@slack/bolt';
import { routeMessage } from './message-router.js';
import sessionManager from '../state/session-manager.js';
import { markdownToSlack } from '../utils/markdown-to-slack.js';
import { rateLimiter } from '../utils/rate-limiter.js';
import logger from '../utils/logger.js';
import { config } from '../config.js';
import StatusAnimator from '../utils/status-animator.js';
import ProgressiveMessenger from '../utils/progressive-messenger.js';

/**
 * Register all Slack event handlers
 */
export function registerEventHandlers(app: App): void {
  // Handle direct messages
  app.message(async ({ message, client, say }) => {
    const msg = message as MessageEvent & { text?: string; user?: string; thread_ts?: string; bot_id?: string; channel_type?: string };

    // Ignore bot messages and messages without text
    if (msg.subtype === 'bot_message' || !msg.text || !msg.user) {
      return;
    }

    // Ignore messages from the bot itself
    if (msg.bot_id) {
      return;
    }

    // Ignore @mentions in channels - those are handled by app_mention event
    // Only process DMs (channel_type === 'im') or non-mention messages
    if (msg.channel_type !== 'im' && msg.text.includes('<@')) {
      return;
    }

    await handleMessage(
      msg.text,
      msg.user,
      msg.channel,
      msg.thread_ts || msg.ts,
      msg.ts,
      client,
      say
    );
  });

  // Handle @mentions in channels
  app.event('app_mention', async ({ event, client, say }) => {
    const mention = event as AppMentionEvent;

    // Remove the bot mention from the message
    const text = mention.text.replace(/<@[A-Z0-9]+>/g, '').trim();

    if (!text) {
      await say({
        text: "Hi! How can I help? Say `help` to see what I can do.",
        thread_ts: mention.thread_ts || mention.ts,
      });
      return;
    }

    await handleMessage(
      text,
      mention.user || 'unknown',
      mention.channel,
      mention.thread_ts || mention.ts,
      mention.ts,
      client,
      say
    );
  });

  // Handle reactions (for quick feedback)
  app.event('reaction_added', async ({ event, client }) => {
    const { reaction, user, item } = event;

    // Only handle reactions to bot messages
    if (item.type !== 'message') {
      return;
    }

    logger.info('Reaction added', { reaction, user, channel: item.channel });

    // Map reactions to actions
    const reactionActions: Record<string, string> = {
      'white_check_mark': 'approved',
      'x': 'rejected',
      'eyes': 'reviewing',
      'rocket': 'deploy',
      'bug': 'bug_report',
    };

    const action = reactionActions[reaction];
    if (action) {
      logger.info('Reaction action detected', { action, reaction });
      // Future: trigger workflow based on reaction
    }
  });

  // Handle slash commands
  app.command('/claude', async ({ command, ack, respond }) => {
    await ack();

    const { text, user_id, channel_id, trigger_id } = command;

    if (!text || text === 'help') {
      await respond({
        response_type: 'ephemeral',
        text: getSlashCommandHelp(),
      });
      return;
    }

    // Handle dispatch commands
    if (text.startsWith('dispatch ')) {
      await respond({
        response_type: 'in_channel',
        text: `Processing dispatch request...`,
      });

      // Create a pseudo thread for tracking
      const session = sessionManager.getOrCreate(
        channel_id,
        `slash-${trigger_id}`,
        user_id
      );

      const result = await routeMessage(text, session);

      await respond({
        response_type: 'in_channel',
        text: markdownToSlack(result.response),
      });
      return;
    }

    // Default: start conversation in thread
    // Use the same dynamic status system as regular messages
    await handleMessage(
      text,
      user_id,
      channel_id,
      trigger_id, // Use trigger_id as thread_ts for slash commands
      trigger_id, // Use trigger_id as message_ts for slash commands
      app.client,
      async (response: any) => {
        await respond({
          response_type: 'in_channel',
          ...response
        });
      }
    );
  });

  logger.info('Slack event handlers registered');
}

/**
 * Determine operation type based on message content
 */
function getOperationType(text: string): keyof typeof StatusAnimator.DEFAULT_PHASES {
  const lowerText = text.toLowerCase();

  // Check for dispatch commands
  if (lowerText.includes('dispatch ') || lowerText.startsWith('/dispatch')) {
    return 'dispatch';
  }

  // Check for factory commands
  if (lowerText.includes('factory') || lowerText.includes('failures') ||
      lowerText.includes('agent performance') || lowerText.includes('workflows') ||
      lowerText.includes('analyze #')) {
    return 'factory_analysis';
  }

  // Default to conversation
  return 'conversation';
}

/**
 * Get initial phase description based on operation type
 */
function getInitialPhase(operationType: string): string {
  const phaseMap: Record<string, string> = {
    dispatch: 'Analyzing dispatch request',
    factory_analysis: 'Gathering factory metrics',
    conversation: 'Processing your message',
    code_analysis: 'Examining codebase'
  };

  return phaseMap[operationType] || 'Starting to work';
}

/**
 * Find natural break points in streaming content
 */
interface BreakPoint {
  position: number;
  type?: 'analysis' | 'result' | 'progress' | 'error';
}

function findNaturalBreaks(content: string, startPosition: number): BreakPoint[] {
  const breaks: BreakPoint[] = [];
  const searchContent = content.substring(startPosition);

  // Look for sentence endings first
  const sentencePattern = /[.!?]+\s+/g;
  let match;
  while ((match = sentencePattern.exec(searchContent)) !== null) {
    const position = startPosition + match.index + match[0].length;
    breaks.push({
      position,
      type: inferContentType(content.substring(Math.max(0, position - 200), position))
    });
  }

  // Look for paragraph breaks
  const paragraphPattern = /\n\s*\n/g;
  while ((match = paragraphPattern.exec(searchContent)) !== null) {
    const position = startPosition + match.index + match[0].length;
    breaks.push({
      position,
      type: inferContentType(content.substring(Math.max(0, position - 200), position))
    });
  }

  // Look for list items or bullet points
  const listPattern = /\n\s*[-*•]\s+/g;
  while ((match = listPattern.exec(searchContent)) !== null) {
    const position = startPosition + match.index;
    breaks.push({
      position,
      type: 'progress'
    });
  }

  // Sort by position and return unique positions
  const uniqueBreaks = Array.from(new Map(
    breaks.map(b => [b.position, b])
  ).values()).sort((a, b) => a.position - b.position);

  return uniqueBreaks;
}

/**
 * Infer content type from text context
 */
function inferContentType(text: string): 'analysis' | 'result' | 'progress' | 'error' {
  const lowerText = text.toLowerCase();

  if (lowerText.includes('error') || lowerText.includes('failed')) {
    return 'error';
  }

  if (lowerText.includes('found') || lowerText.includes('analyzing') || lowerText.includes('examining')) {
    return 'analysis';
  }

  if (lowerText.includes('✅') || lowerText.includes('completed') || lowerText.includes('result')) {
    return 'result';
  }

  return 'progress';
}

/**
 * Extract meaningful content from streaming updates
 */
function extractMeaningfulUpdate(content: string): string {
  // Remove excessive whitespace and clean up formatting
  let cleaned = content.trim();

  // Skip very short updates
  if (cleaned.length < 50) {
    return '';
  }

  // Extract complete sentences or meaningful chunks
  const sentences = cleaned.split(/[.!?]+/);
  const meaningfulSentences = sentences.filter(s => s.trim().length > 20);

  if (meaningfulSentences.length > 0) {
    return meaningfulSentences.slice(0, 2).join('. ').trim() + '.';
  }

  // Fallback: return first 150 chars if no complete sentences
  return cleaned.substring(0, 150) + (cleaned.length > 150 ? '...' : '');
}

/**
 * Determine update type based on content and position
 */
function determineUpdateType(content: string, updateNumber: number): 'thinking' | 'analysis' | 'result' | 'error' | 'progress' {
  const lowerContent = content.toLowerCase();

  if (lowerContent.includes('error') || lowerContent.includes('failed')) {
    return 'error';
  }

  if (updateNumber === 1) {
    return 'analysis';
  }

  if (lowerContent.includes('found') || lowerContent.includes('discovered') || lowerContent.includes('analyzing')) {
    return 'analysis';
  }

  return 'progress';
}

/**
 * Get phase description for update based on operation and step
 */
function getPhaseForUpdate(operationType: string, updateNumber: number): string {
  const phasesByType: Record<string, string[]> = {
    dispatch: ['Parsing request', 'Creating issue', 'Setting up workflow'],
    factory_analysis: ['Collecting metrics', 'Analyzing patterns', 'Generating insights'],
    conversation: ['Understanding context', 'Researching solution', 'Formulating response'],
    code_analysis: ['Scanning codebase', 'Identifying patterns', 'Proposing solution']
  };

  const phases = phasesByType[operationType] || phasesByType.conversation;
  const phaseIndex = Math.min(updateNumber - 1, phases.length - 1);

  return phases[phaseIndex] || 'Processing';
}

/**
 * Handle an incoming message
 */
async function handleMessage(
  text: string,
  userId: string,
  channelId: string,
  threadTs: string,
  messageTs: string,
  client: any,
  say: any
): Promise<void> {
  // Rate limiting
  if (!rateLimiter.check(userId)) {
    await say({
      text: "You're sending messages too quickly. Please wait a moment.",
      thread_ts: threadTs,
    });
    return;
  }

  logger.info('Processing message', {
    userId,
    channelId,
    threadTs,
    textLength: text.length,
  });

  // Get or create session
  const session = sessionManager.getOrCreate(channelId, threadTs, userId);

  try {
    // Determine operation type for initial phase
    const operationType = getOperationType(text);
    const initialPhase = getInitialPhase(operationType);

    // Start progressive messaging session
    const sessionKey = await ProgressiveMessenger.startSession(
      channelId,
      threadTs,
      client,
      initialPhase
    );

    try {
      // Track intermediate updates
      let updateCount = 0;
      let lastChunkLength = 0;
      const chunkThreshold = 200; // Minimum chars for an update

      // Set up intelligent streaming buffer
      let streamBuffer = '';
      let lastSentPosition = 0;
      const minChunkSize = 100; // Smaller threshold for more frequent updates

      const result = await routeMessage(text, session, async (chunk) => {
        // Add new chunk to buffer
        streamBuffer += chunk;

        // Look for natural break points in the buffer
        const breakPoints = findNaturalBreaks(streamBuffer, lastSentPosition);

        for (const breakPoint of breakPoints) {
          if (breakPoint.position > lastSentPosition + minChunkSize) {
            updateCount++;

            // Extract content from last position to break point
            const content = streamBuffer.substring(lastSentPosition, breakPoint.position).trim();

            if (content.length > 20) { // Ensure meaningful content
              await ProgressiveMessenger.postUpdate(sessionKey, {
                id: `update-${updateCount}`,
                type: breakPoint.type || determineUpdateType(content, updateCount),
                content: content,
                metadata: {
                  step: updateCount,
                  phase: getPhaseForUpdate(operationType, updateCount),
                  timestamp: Date.now()
                }
              });

              lastSentPosition = breakPoint.position;

              // Add small delay between updates for better UX
              await new Promise(resolve => setTimeout(resolve, 1000));
            }
          }
        }
      });

      // Complete the session with final result
      await ProgressiveMessenger.completeSession(
        sessionKey,
        result.response,
        {
          success: !result.response.includes('error'),
          summary: result.dispatchedAgent ? `Dispatched to ${result.dispatchedAgent} agent` : 'Conversation completed'
        }
      );

      // Track the response in session
      sessionManager.addMessage(channelId, threadTs, 'assistant', result.response, undefined);

      // If an agent was dispatched, track it
      if (result.dispatchedAgent && result.issueUrl) {
        const issueNumber = parseInt(result.issueUrl.split('/').pop() || '0');
        if (issueNumber) {
          sessionManager.linkIssue(channelId, threadTs, issueNumber);
        }
      }

      logger.info('Message processed successfully', {
        channelId,
        threadTs,
        dispatchedAgent: result.dispatchedAgent,
        totalUpdates: updateCount
      });
    } catch (processingError) {
      // If processing fails, complete with error
      await ProgressiveMessenger.completeSession(
        sessionKey,
        "I encountered an error processing your message. Please try again.",
        { success: false }
      );

      throw processingError;
    }
  } catch (error) {
    logger.error('Error processing message', { error, channelId, threadTs });

    await say({
      text: "I encountered an error processing your message. Please try again.",
      thread_ts: threadTs,
    });
  }
}

/**
 * Get slash command help text
 */
function getSlashCommandHelp(): string {
  return `*Claude Software Factory Bot - Slash Commands*

\`/claude help\` - Show this help message
\`/claude dispatch code <task>\` - Dispatch task to Code Agent
\`/claude dispatch qa <task>\` - Dispatch task to QA Agent
\`/claude dispatch devops <task>\` - Dispatch task to DevOps Agent
\`/claude dispatch release <task>\` - Dispatch task to Release Agent
\`/claude <question>\` - Start a conversation in channel

For in-depth conversations, mention me in a thread: @Claude <your question>`;
}

export default {
  registerEventHandlers,
};
