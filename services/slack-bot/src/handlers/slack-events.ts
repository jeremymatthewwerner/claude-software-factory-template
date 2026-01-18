/**
 * Slack event handlers - Simple progressive messaging
 * Posts SEPARATE messages for each update to preserve full audit log
 */

import type { App, MessageEvent, AppMentionEvent } from '@slack/bolt';
import { routeMessage } from './message-router.js';
import sessionManager from '../state/session-manager.js';
import { markdownToSlack } from '../utils/markdown-to-slack.js';
import { rateLimiter } from '../utils/rate-limiter.js';
import logger from '../utils/logger.js';
import { config } from '../config.js';
import { fetchThreadHistory, formatHistoryForPrompt } from '../utils/thread-history.js';

// Use a generic type for Slack client to avoid version conflicts between @slack/bolt and @slack/web-api
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type SlackClient = any;

// Cache the bot's user ID for identifying bot messages
let botUserId: string | undefined;

/**
 * Register all Slack event handlers
 */
export function registerEventHandlers(app: App): void {
  // Handle direct messages and thread replies where bot is participating
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

    // Skip messages with @mentions - let app_mention handler deal with those
    // This prevents duplicate responses when bot is mentioned in a thread it's already in
    if (msg.text.includes('<@') && msg.channel_type !== 'im') {
      return;
    }

    // DMs - always respond
    if (msg.channel_type === 'im') {
      await handleMessage(
        msg.text,
        msg.user,
        msg.channel,
        msg.thread_ts || msg.ts,
        msg.ts,
        client,
        say
      );
      return;
    }

    // In channels: Only respond in threads where bot is already participating
    // (i.e., there's an existing session for this thread)
    if (msg.thread_ts) {
      const existingSession = sessionManager.get(msg.channel, msg.thread_ts);
      if (existingSession) {
        // Bot is participating in this thread - respond automatically
        await handleMessage(
          msg.text,
          msg.user,
          msg.channel,
          msg.thread_ts,
          msg.ts,
          client,
          say
        );
        return;
      }
    }

    // In channels without a thread, or in threads where bot isn't participating:
    // Don't respond - require @mention (handled by app_mention event)
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
    await respond({
      response_type: 'in_channel',
      text: `<@${user_id}> asked: ${text}\n\n_Starting conversation..._`,
    });
  });

  logger.info('Slack event handlers registered');
}

/**
 * Create simple progressive messenger that posts SEPARATE messages
 * Each meaningful update becomes its own Slack message for full audit trail
 */
function createProgressiveMessenger(
  client: any,
  channelId: string,
  threadTs: string
) {
  let thinkingTs: string | null = null;
  let animationFrame = 0;
  let animationInterval: NodeJS.Timeout | null = null;
  let isCompleted = false;

  // Simple spinner frames
  const spinnerFrames = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];

  // Post a new "working" message with spinner animation
  const startThinking = async () => {
    if (animationInterval) {
      clearInterval(animationInterval);
      animationInterval = null;
    }

    try {
      const result = await client.chat.postMessage({
        channel: channelId,
        thread_ts: threadTs,
        text: `${spinnerFrames[0]} _working..._`,
      });
      thinkingTs = result.ts;
      animationFrame = 0;

      // Animate the spinner
      animationInterval = setInterval(async () => {
        if (!thinkingTs || isCompleted) {
          if (animationInterval) clearInterval(animationInterval);
          return;
        }
        animationFrame++;
        const frame = spinnerFrames[animationFrame % spinnerFrames.length];
        try {
          await client.chat.update({
            channel: channelId,
            ts: thinkingTs,
            text: `${frame} _working..._`,
          });
        } catch (e) {
          // Ignore update errors
        }
      }, 400);
    } catch (error) {
      logger.error('Failed to start thinking message', { error });
    }
  };

  // Convert current thinking message to permanent content, then start new thinking
  const convertAndContinue = async (content: string) => {
    if (animationInterval) {
      clearInterval(animationInterval);
      animationInterval = null;
    }

    if (thinkingTs && content.trim()) {
      try {
        // Update the thinking message with actual content (makes it permanent)
        await client.chat.update({
          channel: channelId,
          ts: thinkingTs,
          text: markdownToSlack(content),
        });
        thinkingTs = null;

        // Start a NEW thinking message for the next update
        if (!isCompleted) {
          await startThinking();
        }
      } catch (error) {
        logger.error('Failed to convert thinking message', { error });
      }
    }
  };

  // Delete the thinking message (for cancel/cleanup)
  const deleteThinking = async () => {
    if (animationInterval) {
      clearInterval(animationInterval);
      animationInterval = null;
    }
    if (thinkingTs) {
      try {
        await client.chat.delete({
          channel: channelId,
          ts: thinkingTs,
        });
      } catch (e) {
        // Ignore delete errors
      }
      thinkingTs = null;
    }
  };

  // Queue for sequential processing
  let updateQueue: Promise<void> = Promise.resolve();
  let pendingContent = '';

  return {
    start: async () => {
      await startThinking();
    },

    addChunk: (chunk: string) => {
      if (isCompleted) return;

      pendingContent += chunk;

      // Check for natural break points (double newline or sufficient length)
      const hasBreakPoint = pendingContent.includes('\n\n') || pendingContent.length > 300;

      if (hasBreakPoint && pendingContent.trim().length > 30) {
        const content = pendingContent;
        pendingContent = '';

        // Queue the update for sequential processing
        updateQueue = updateQueue.then(async () => {
          if (!isCompleted) {
            await convertAndContinue(content);
          }
        }).catch(err => {
          logger.error('Error in update queue', { error: err });
        });
      }
    },

    finalize: async (finalContent: string) => {
      isCompleted = true;

      // Wait for any pending updates
      await updateQueue;

      if (animationInterval) {
        clearInterval(animationInterval);
        animationInterval = null;
      }

      // If there's pending content, include it with final
      const fullContent = pendingContent.trim()
        ? pendingContent + '\n\n' + finalContent
        : finalContent;

      logger.info('Finalizing message', {
        hasPendingContent: !!pendingContent.trim(),
        hasThinkingTs: !!thinkingTs,
        contentLength: fullContent.length,
      });

      // Always post something
      const contentToPost = fullContent.trim() || 'Done.';

      if (thinkingTs) {
        try {
          await client.chat.update({
            channel: channelId,
            ts: thinkingTs,
            text: markdownToSlack(contentToPost),
          });
        } catch (error) {
          logger.error('Failed to update thinking message, posting new', { error });
          try {
            await client.chat.postMessage({
              channel: channelId,
              thread_ts: threadTs,
              text: markdownToSlack(contentToPost),
            });
          } catch (e) {
            logger.error('Failed to post final message', { error: e });
          }
        }
      } else {
        // No thinking message, just post
        try {
          await client.chat.postMessage({
            channel: channelId,
            thread_ts: threadTs,
            text: markdownToSlack(contentToPost),
          });
        } catch (error) {
          logger.error('Failed to post final message', { error });
        }
      }
    },

    cancel: async () => {
      isCompleted = true;
      await deleteThinking();
    },
  };
}

/**
 * Handle an incoming message - posts separate messages for audit trail
 */
async function handleMessage(
  text: string,
  userId: string,
  channelId: string,
  threadTs: string,
  messageTs: string,
  client: SlackClient,
  say: SlackClient
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

  // Create simple progressive messenger (posts separate messages)
  const messenger = createProgressiveMessenger(client, channelId, threadTs);

  try {
    // Start with a thinking animation
    await messenger.start();

    // Get bot's user ID if not cached (needed to identify bot messages in history)
    if (!botUserId) {
      try {
        const authResult = await client.auth.test();
        botUserId = authResult.user_id as string;
        logger.info('Cached bot user ID', { botUserId });
      } catch (error) {
        logger.warn('Could not get bot user ID', { error });
      }
    }

    // Fetch full thread history from Slack (not just in-memory)
    const threadHistory = await fetchThreadHistory(
      client,
      channelId,
      threadTs,
      botUserId
    );

    // Format history for Claude
    const conversationHistory = formatHistoryForPrompt(threadHistory);

    logger.info('Fetched thread history from Slack', {
      channelId,
      threadTs,
      totalMessages: threadHistory.totalMessages,
      includedMessages: conversationHistory.length,
      truncated: threadHistory.truncated,
    });

    // Process the message - chunks trigger separate posts at natural breaks
    const result = await routeMessage(text, session, {
      onChunk: (chunk) => {
        messenger.addChunk(chunk);
      },
      conversationHistory,
    });

    // Finalize with the response
    await messenger.finalize(result.response);

    // Track both user message and assistant response in session history
    sessionManager.addMessage(channelId, threadTs, 'user', text, messageTs);
    sessionManager.addMessage(channelId, threadTs, 'assistant', result.response, Date.now().toString());

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
    });
  } catch (error) {
    logger.error('Error processing message', { error, channelId, threadTs });

    // Cancel the status animation and show error
    await messenger.cancel();
    
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