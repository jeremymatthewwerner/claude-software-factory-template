/**
 * Progressive Messenger - Simple, clean updates for Slack
 * Provides better UX with minimal decoration and readable formatting
 */

import logger from './logger.js';
import { markdownToSlack } from './markdown-to-slack.js';

export interface ProgressiveUpdate {
  id: string;
  type: 'thinking' | 'analysis' | 'result' | 'error' | 'progress';
  content: string;
  metadata?: {
    phase?: string;
    step?: number;
    totalSteps?: number;
    timestamp?: number;
  };
}

export interface ProgressiveSession {
  channelId: string;
  threadTs: string;
  client: any;
  thinkingMessageTs?: string;
  updateCount: number;
  lastUpdateTime: number;
}

export class ProgressiveMessenger {
  private static sessions = new Map<string, ProgressiveSession>();
  private static readonly MIN_UPDATE_INTERVAL = 2000; // 2 seconds between updates

  /**
   * Start a progressive session with thinking animation
   */
  static async startSession(
    channelId: string,
    threadTs: string,
    client: any,
    initialPhase = 'Working'
  ): Promise<string> {
    const sessionKey = `${channelId}-${threadTs}`;

    try {
      // Show initial thinking message
      const thinkingMessage = await this.postThinking(channelId, threadTs, client, initialPhase);

      const session: ProgressiveSession = {
        channelId,
        threadTs,
        client,
        thinkingMessageTs: thinkingMessage,
        updateCount: 0,
        lastUpdateTime: Date.now()
      };

      this.sessions.set(sessionKey, session);

      logger.info('Progressive session started', { sessionKey, initialPhase });
      return sessionKey;
    } catch (error) {
      logger.error('Failed to start progressive session', { error, channelId, threadTs });
      throw error;
    }
  }

  /**
   * Post a substantive update as a new message
   */
  static async postUpdate(
    sessionKey: string,
    update: ProgressiveUpdate
  ): Promise<void> {
    const session = this.sessions.get(sessionKey);
    if (!session) {
      logger.warn('No session found for update', { sessionKey });
      return;
    }

    const now = Date.now();
    const timeSinceLastUpdate = now - session.lastUpdateTime;

    // Rate limit updates to avoid spam
    if (timeSinceLastUpdate < this.MIN_UPDATE_INTERVAL && session.updateCount > 0) {
      logger.debug('Update throttled', { sessionKey, timeSinceLastUpdate });
      return;
    }

    try {
      // Clear thinking message if it exists
      if (session.thinkingMessageTs && update.type !== 'thinking') {
        await this.clearThinking(session);
      }

      // Format and post the update - simple and clean
      const formattedMessage = this.formatUpdate(update);
      const slackMessage = markdownToSlack(formattedMessage);

      await session.client.chat.postMessage({
        channel: session.channelId,
        thread_ts: session.threadTs,
        text: slackMessage,
        unfurl_links: false,
        unfurl_media: false
      });

      session.updateCount++;
      session.lastUpdateTime = now;

      // Show new thinking message if this wasn't a final result
      if (update.type !== 'result' && update.type !== 'error') {
        const nextPhase = this.getNextPhase(update);
        if (nextPhase) {
          session.thinkingMessageTs = await this.postThinking(
            session.channelId,
            session.threadTs,
            session.client,
            nextPhase
          );
        }
      }

      logger.info('Progressive update posted', {
        sessionKey,
        type: update.type,
        updateCount: session.updateCount
      });
    } catch (error) {
      logger.error('Failed to post progressive update', { error, sessionKey, updateType: update.type });
    }
  }

  /**
   * Complete the session with final result
   */
  static async completeSession(
    sessionKey: string,
    finalResult: string,
    metadata?: { success?: boolean; summary?: string }
  ): Promise<void> {
    const session = this.sessions.get(sessionKey);
    if (!session) return;

    try {
      // Clear any remaining thinking message
      if (session.thinkingMessageTs) {
        await this.clearThinking(session);
      }

      // Post completion update - simple formatting
      const slackMessage = markdownToSlack(finalResult);

      await session.client.chat.postMessage({
        channel: session.channelId,
        thread_ts: session.threadTs,
        text: slackMessage,
        unfurl_links: false,
        unfurl_media: false
      });

      logger.info('Progressive session completed', {
        sessionKey,
        totalUpdates: session.updateCount
      });
    } catch (error) {
      logger.error('Failed to complete progressive session', { error, sessionKey });
    } finally {
      this.sessions.delete(sessionKey);
    }
  }

  /**
   * Post thinking/working animation message - minimal
   */
  private static async postThinking(
    channelId: string,
    threadTs: string,
    client: any,
    phase: string
  ): Promise<string> {
    const message = `_${phase}..._`;

    const response = await client.chat.postMessage({
      channel: channelId,
      thread_ts: threadTs,
      text: message,
      unfurl_links: false,
      unfurl_media: false
    });

    return response.ts;
  }

  /**
   * Clear the thinking message
   */
  private static async clearThinking(session: ProgressiveSession): Promise<void> {
    if (!session.thinkingMessageTs) return;

    try {
      await session.client.chat.delete({
        channel: session.channelId,
        ts: session.thinkingMessageTs
      });
    } catch (error) {
      logger.warn('Failed to clear thinking message', { error });
      // Fallback: update to indicate completion
      try {
        await session.client.chat.update({
          channel: session.channelId,
          ts: session.thinkingMessageTs,
          text: '_Complete_'
        });
      } catch (fallbackError) {
        logger.warn('Failed to update thinking message', { fallbackError });
      }
    }

    session.thinkingMessageTs = undefined;
  }

  /**
   * Format an update with minimal styling
   */
  private static formatUpdate(update: ProgressiveUpdate): string {
    const { content, metadata = {} } = update;

    // Simple prefix based on type
    let prefix = '';
    switch (update.type) {
      case 'error':
        prefix = 'Error: ';
        break;
      case 'result':
        prefix = '';  // No prefix for results
        break;
      default:
        prefix = '';  // Clean, no decoration for most updates
    }

    // Add step info if available
    let stepInfo = '';
    if (metadata.step && metadata.totalSteps) {
      stepInfo = ` (${metadata.step}/${metadata.totalSteps})`;
    }

    return `${prefix}${content}${stepInfo}`;
  }

  /**
   * Determine next phase based on current update
   */
  private static getNextPhase(update: ProgressiveUpdate): string | null {
    const phaseMap: Record<string, string> = {
      thinking: 'Analyzing',
      analysis: 'Implementing',
      progress: 'Finishing'
    };

    return phaseMap[update.type] || null;
  }

  /**
   * Clean up abandoned sessions
   */
  static cleanup(): void {
    const now = Date.now();
    const maxAge = 30 * 60 * 1000; // 30 minutes

    for (const [key, session] of this.sessions.entries()) {
      if (now - session.lastUpdateTime > maxAge) {
        this.sessions.delete(key);
        logger.info('Cleaned up abandoned session', { sessionKey: key });
      }
    }
  }
}

export default ProgressiveMessenger;