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
 * Create a progressive messenger that posts separate messages for each update
 * This gives users timestamps, links, and the ability to forward individual updates
 */
function createProgressiveMessenger(
  client: any,
  channelId: string,
  threadTs: string,
) {
  let thinkingTs: string | null = null;
  let lastPostTime = 0;
  let pendingContent = '';
  let animationFrame = 0;
  let animationInterval: NodeJS.Timeout | null = null;
  const minPostInterval = 3000; // Minimum 3 seconds between posts to avoid spam

  // Animation frames for the thinking indicator
  const thinkingFrames = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];

  // Start the thinking animation
  const startThinking = async () => {
    const frame = thinkingFrames[0];
    const result = await client.chat.postMessage({
      channel: channelId,
      thread_ts: threadTs,
      text: `${frame} _thinking..._`,
    });
    thinkingTs = result.ts;

    // Animate the thinking indicator
    animationInterval = setInterval(async () => {
      if (!thinkingTs) return;
      animationFrame++;
      const frame = thinkingFrames[animationFrame % thinkingFrames.length];
      try {
        await client.chat.update({
          channel: channelId,
          ts: thinkingTs,
          text: `${frame} _working..._`,
        });
      } catch (e) {
        // Ignore update errors
      }
    }, 500);
  };

  // Stop the thinking animation and delete the thinking message
  const stopThinking = async () => {
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
        // If we can't delete, just update it to be minimal
        try {
          await client.chat.update({
            channel: channelId,
            ts: thinkingTs,
            text: '✓',
          });
        } catch (e2) {
          // Ignore
        }
      }
      thinkingTs = null;
    }
  };

  // Post a new message with content
  const postUpdate = async (content: string) => {
    if (!content.trim()) return;

    await stopThinking();

    await client.chat.postMessage({
      channel: channelId,
      thread_ts: threadTs,
      text: markdownToSlack(content),
    });
    lastPostTime = Date.now();
  };

  // Initialize
  startThinking();

  return {
    /**
     * Add content - will be batched and posted as separate messages
     */
    addChunk: (chunk: string) => {
      pendingContent += chunk;

      // Check if we have enough content and enough time has passed
      const now = Date.now();
      const timeSinceLastPost = now - lastPostTime;

      // Look for natural break points (double newline, end of sentence after 200+ chars)
      const hasBreakPoint = pendingContent.includes('\n\n') ||
        (pendingContent.length > 200 && /[.!?]\s*$/.test(pendingContent));

      if (hasBreakPoint && timeSinceLastPost >= minPostInterval && pendingContent.length > 50) {
        const content = pendingContent;
        pendingContent = '';
        postUpdate(content);
        startThinking(); // Show thinking again while waiting for more
      }
    },

    /**
     * Get accumulated content
     */
    getContent: () => pendingContent,

    /**
     * Finalize - post any remaining content and clean up
     */
    finalize: async (finalContent?: string) => {
      await stopThinking();

      const content = finalContent ?? pendingContent;
      if (content.trim()) {
        await client.chat.postMessage({
          channel: channelId,
          thread_ts: threadTs,
          text: markdownToSlack(content),
        });
      }
    },

    /**
     * Cancel and clean up
     */
    cancel: async () => {
      await stopThinking();
    },
  };
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

  try {
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

    // Create progressive messenger - posts separate messages for each update
    const messenger = createProgressiveMessenger(client as any, channelId, threadTs);

    // Process the message with progressive updates and full thread history
    const result = await routeMessage(text, session, {
      onChunk: (chunk) => {
        messenger.addChunk(chunk);
      },
      conversationHistory,
    });

    // Finalize with any remaining content
    await messenger.finalize(result.response);

    // Track both user message and assistant response in session history
    // (also update in-memory for faster access within same deploy)
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
