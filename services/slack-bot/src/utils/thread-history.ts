/**
 * Fetch and manage Slack thread history
 *
 * This module fetches the full thread history from Slack's API,
 * which is essential for maintaining context across bot restarts
 * and when joining existing threads.
 */

import logger from './logger.js';

// Use a generic type for Slack client to avoid version conflicts
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type SlackClient = any;

export interface ThreadMessage {
  role: 'user' | 'assistant';
  content: string;
  userId?: string;
  timestamp: string;
  slackTs: string;
}

export interface ThreadHistory {
  messages: ThreadMessage[];
  totalMessages: number;
  truncated: boolean;
  oldestIncluded: string;
}

// Configuration for context management
const MAX_MESSAGES = 50;  // Max messages to include in context
const MAX_CHARS = 100000; // Max total characters (~25k tokens)
const SUMMARY_THRESHOLD = 30; // Summarize if more than this many messages

/**
 * Fetch full thread history from Slack
 */
export async function fetchThreadHistory(
  client: SlackClient,
  channelId: string,
  threadTs: string,
  botUserId?: string
): Promise<ThreadHistory> {
  try {
    // Fetch all replies in the thread
    const result = await client.conversations.replies({
      channel: channelId,
      ts: threadTs,
      limit: 200, // Slack's max per request
    });

    if (!result.messages || result.messages.length === 0) {
      return {
        messages: [],
        totalMessages: 0,
        truncated: false,
        oldestIncluded: threadTs,
      };
    }

    const allMessages = result.messages;
    const totalMessages = allMessages.length;

    // Convert Slack messages to our format
    const threadMessages: ThreadMessage[] = [];

    for (const msg of allMessages) {
      // Skip messages without text
      if (!msg.text) continue;

      // Determine if this is from the bot or a user
      const isBot = msg.bot_id !== undefined || (botUserId && msg.user === botUserId);

      // Clean up the message text
      let content = msg.text;

      // Remove bot mentions from user messages
      content = content.replace(/<@[A-Z0-9]+>/g, '').trim();

      // Skip empty messages after cleanup
      if (!content) continue;

      // Skip the "Starting..." or "Thinking..." placeholder messages
      if (content === '_Starting..._' || content === '_Thinking..._') continue;

      // Skip messages that are just "...working..."
      if (content.endsWith('_...working..._')) {
        content = content.replace(/\n\n_\.\.\.working\.\.\._$/, '');
      }

      threadMessages.push({
        role: isBot ? 'assistant' : 'user',
        content,
        userId: msg.user,
        timestamp: msg.ts ? new Date(parseFloat(msg.ts) * 1000).toISOString() : new Date().toISOString(),
        slackTs: msg.ts || '',
      });
    }

    // Apply context management if thread is too long
    const managed = manageContext(threadMessages);

    logger.info('Fetched thread history', {
      channelId,
      threadTs,
      totalMessages,
      includedMessages: managed.messages.length,
      truncated: managed.truncated,
    });

    return managed;
  } catch (error) {
    logger.error('Failed to fetch thread history', { error, channelId, threadTs });
    return {
      messages: [],
      totalMessages: 0,
      truncated: false,
      oldestIncluded: threadTs,
    };
  }
}

/**
 * Manage context for long threads
 *
 * Strategy:
 * 1. Always keep recent messages (most relevant)
 * 2. For very long threads, summarize older messages
 * 3. Respect character limits to avoid token overflow
 */
function manageContext(messages: ThreadMessage[]): ThreadHistory {
  if (messages.length === 0) {
    return {
      messages: [],
      totalMessages: 0,
      truncated: false,
      oldestIncluded: '',
    };
  }

  const totalMessages = messages.length;

  // If within limits, return all
  if (messages.length <= MAX_MESSAGES) {
    const totalChars = messages.reduce((sum, m) => sum + m.content.length, 0);
    if (totalChars <= MAX_CHARS) {
      return {
        messages,
        totalMessages,
        truncated: false,
        oldestIncluded: messages[0].slackTs,
      };
    }
  }

  // Need to truncate - keep most recent messages
  let included: ThreadMessage[] = [];
  let totalChars = 0;

  // Work backwards from most recent
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i];
    const msgChars = msg.content.length;

    // Check if adding this message would exceed limits
    if (included.length >= MAX_MESSAGES || totalChars + msgChars > MAX_CHARS) {
      break;
    }

    included.unshift(msg);
    totalChars += msgChars;
  }

  // If we truncated, add a context note at the beginning
  if (included.length < messages.length) {
    const truncatedCount = messages.length - included.length;
    const contextNote: ThreadMessage = {
      role: 'assistant',
      content: `[Note: ${truncatedCount} earlier messages in this thread are not shown. The conversation continues from here.]`,
      timestamp: included[0]?.timestamp || new Date().toISOString(),
      slackTs: 'context-note',
    };
    included.unshift(contextNote);
  }

  return {
    messages: included,
    totalMessages,
    truncated: messages.length > included.length,
    oldestIncluded: included.length > 1 ? included[1].slackTs : included[0]?.slackTs || '',
  };
}

/**
 * Format thread history for Claude prompt
 */
export function formatHistoryForPrompt(
  history: ThreadHistory
): Array<{ role: 'user' | 'assistant'; content: string }> {
  return history.messages.map((msg) => ({
    role: msg.role,
    content: msg.content,
  }));
}

/**
 * Check if we should fetch fresh history
 * (e.g., if cached history is stale or session was just created)
 */
export function shouldRefreshHistory(
  cachedMessageCount: number,
  lastFetchTime?: Date
): boolean {
  // Always fetch if we have no cached messages
  if (cachedMessageCount === 0) return true;

  // Refresh if last fetch was more than 5 minutes ago
  if (lastFetchTime) {
    const age = Date.now() - lastFetchTime.getTime();
    if (age > 5 * 60 * 1000) return true;
  }

  return false;
}

export default {
  fetchThreadHistory,
  formatHistoryForPrompt,
  shouldRefreshHistory,
};
