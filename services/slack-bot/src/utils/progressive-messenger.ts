/**
 * Progressive Messenger - Claude Code style updates for Slack
 * Provides dynamic status updates with rich animation and Claude-style phases
 */

import logger from './logger.js';
import { markdownToSlack } from './markdown-to-slack.js';
import StatusAnimator, { StatusPhase } from './status-animator.js';

export interface ProgressiveUpdate {
  id: string;
  type: 'thinking' | 'analysis' | 'result' | 'error' | 'progress';
  content: string;
  metadata?: {
    phase?: string;
    step?: number;
    totalSteps?: number;
    timestamp?: number;
    operationType?: 'conversation' | 'dispatch' | 'factory_analysis' | 'code_analysis';
  };
}

export interface ProgressiveSession {
  channelId: string;
  threadTs: string;
  client: any;
  statusAnimatorKey?: string;
  updateCount: number;
  lastUpdateTime: number;
  operationType: string;
}

export class ProgressiveMessenger {
  private static sessions = new Map<string, ProgressiveSession>();
  private static readonly MIN_UPDATE_INTERVAL = 1500; // Faster updates for more responsive feel

  /**
   * Start a progressive session with Claude Code style status animation
   */
  static async startSession(
    channelId: string,
    threadTs: string,
    client: any,
    operationType: 'conversation' | 'dispatch' | 'factory_analysis' | 'code_analysis' = 'conversation'
  ): Promise<string> {
    const sessionKey = `${channelId}-${threadTs}`;

    try {
      // Get appropriate phases for this operation
      const phases = StatusAnimator.getPhasesForOperation(operationType);

      // Start the Claude Code style status animation
      const statusAnimatorKey = await StatusAnimator.start({
        channel: channelId,
        threadTs: threadTs,
        client: client,
        phases: phases,
        animationInterval: 1600 // Lively animation
      });

      const session: ProgressiveSession = {
        channelId,
        threadTs,
        client,
        statusAnimatorKey,
        updateCount: 0,
        lastUpdateTime: Date.now(),
        operationType
      };

      this.sessions.set(sessionKey, session);

      logger.info('Progressive session started with Claude style animation', { 
        sessionKey, 
        operationType, 
        phases: phases.length 
      });
      return sessionKey;
    } catch (error) {
      logger.error('Failed to start progressive session', { error, channelId, threadTs });
      throw error;
    }
  }

  /**
   * Post intermediate update while maintaining status animation
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
      // For intermediate updates, post as new messages while animation continues
      const formattedMessage = this.formatUpdate(update);
      const slackMessage = markdownToSlack(formattedMessage);

      // Post as new message in thread 
      await session.client.chat.postMessage({
        channel: session.channelId,
        thread_ts: session.threadTs,
        text: slackMessage,
        unfurl_links: false,
        unfurl_media: false
      });

      session.updateCount++;
      session.lastUpdateTime = now;

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
   * Complete the session with final result, replacing the status animation
   */
  static async completeSession(
    sessionKey: string,
    finalResult: string,
    metadata?: { success?: boolean; summary?: string }
  ): Promise<void> {
    const session = this.sessions.get(sessionKey);
    if (!session) return;

    try {
      // Complete the status animation by replacing it with the final result
      if (session.statusAnimatorKey) {
        const slackMessage = markdownToSlack(finalResult);
        
        await StatusAnimator.complete(
          session.statusAnimatorKey,
          slackMessage,
          session.client,
          session.channelId
        );
      } else {
        // Fallback: post as new message
        const slackMessage = markdownToSlack(finalResult);
        await session.client.chat.postMessage({
          channel: session.channelId,
          thread_ts: session.threadTs,
          text: slackMessage,
          unfurl_links: false,
          unfurl_media: false
        });
      }

      logger.info('Progressive session completed', {
        sessionKey,
        totalUpdates: session.updateCount,
        operationType: session.operationType
      });
    } catch (error) {
      logger.error('Failed to complete progressive session', { error, sessionKey });
    } finally {
      this.sessions.delete(sessionKey);
    }
  }

  /**
   * Force advance to next phase of the status animation
   */
  static async advanceToPhase(
    sessionKey: string,
    phaseIndex: number
  ): Promise<void> {
    const session = this.sessions.get(sessionKey);
    if (!session || !session.statusAnimatorKey) return;

    const phases = StatusAnimator.getPhasesForOperation(session.operationType as any);
    
    await StatusAnimator.updatePhase(
      session.statusAnimatorKey,
      phaseIndex,
      session.client,
      session.channelId,
      phases
    );
  }

  /**
   * Stream partial content updates (like Claude Code's streaming)
   */
  static async streamUpdate(
    sessionKey: string,
    partialContent: string
  ): Promise<void> {
    const session = this.sessions.get(sessionKey);
    if (!session || !session.statusAnimatorKey) return;

    // Update the status message with partial content
    await StatusAnimator.update(
      session.statusAnimatorKey,
      partialContent,
      session.client,
      session.channelId
    );
  }

  /**
   * Cancel session and clean up
   */
  static async cancelSession(sessionKey: string): Promise<void> {
    const session = this.sessions.get(sessionKey);
    if (!session) return;

    try {
      if (session.statusAnimatorKey) {
        StatusAnimator.stop(session.statusAnimatorKey);
      }
      
      logger.info('Progressive session cancelled', { sessionKey });
    } catch (error) {
      logger.error('Failed to cancel progressive session', { error, sessionKey });
    } finally {
      this.sessions.delete(sessionKey);
    }
  }

  /**
   * Format an update with enhanced styling based on type
   */
  private static formatUpdate(update: ProgressiveUpdate): string {
    const { content, metadata = {} } = update;

    // Enhanced prefixes with emojis
    let prefix = '';
    switch (update.type) {
      case 'error':
        prefix = '❌ **Error:** ';
        break;
      case 'result':
        prefix = '✅ **Result:** ';
        break;
      case 'analysis':
        prefix = '🔍 **Analysis:** ';
        break;
      case 'progress':
        prefix = '⚡ **Progress:** ';
        break;
      case 'thinking':
        prefix = '💭 **Note:** ';
        break;
      default:
        prefix = '';
    }

    // Add step info if available
    let stepInfo = '';
    if (metadata.step && metadata.totalSteps) {
      const progressBar = this.createMiniProgressBar(metadata.step, metadata.totalSteps);
      stepInfo = `\n${progressBar}`;
    }

    // Add timestamp for context
    const timestamp = metadata.timestamp ? 
      `_${new Date(metadata.timestamp).toLocaleTimeString()}_` : '';

    return `${prefix}${content}${stepInfo}${timestamp ? `\n\n${timestamp}` : ''}`;
  }

  /**
   * Create a mini progress bar for step updates
   */
  private static createMiniProgressBar(current: number, total: number): string {
    const width = 12;
    const filled = Math.floor((current / total) * width);
    const empty = width - filled;
    const percentage = Math.round((current / total) * 100);

    const filledBar = '█'.repeat(filled);
    const emptyBar = '░'.repeat(empty);

    return `\`${filledBar}${emptyBar}\` ${percentage}% (${current}/${total})`;
  }

  /**
   * Get session info for debugging
   */
  static getSessionInfo(sessionKey: string): ProgressiveSession | undefined {
    return this.sessions.get(sessionKey);
  }

  /**
   * Clean up abandoned sessions
   */
  static cleanup(): void {
    const now = Date.now();
    const maxAge = 30 * 60 * 1000; // 30 minutes

    for (const [key, session] of this.sessions.entries()) {
      if (now - session.lastUpdateTime > maxAge) {
        // Clean up status animator
        if (session.statusAnimatorKey) {
          StatusAnimator.stop(session.statusAnimatorKey);
        }
        
        this.sessions.delete(key);
        logger.info('Cleaned up abandoned session', { sessionKey: key });
      }
    }
  }

  /**
   * Get operation type from message content
   */
  static inferOperationType(message: string): 'conversation' | 'dispatch' | 'factory_analysis' | 'code_analysis' {
    const lowerMessage = message.toLowerCase();
    
    if (lowerMessage.startsWith('dispatch ')) {
      return 'dispatch';
    }
    
    if (lowerMessage.includes('factory') || lowerMessage.includes('status') || lowerMessage.includes('health')) {
      return 'factory_analysis';
    }
    
    if (lowerMessage.includes('code') || lowerMessage.includes('bug') || lowerMessage.includes('implement')) {
      return 'code_analysis';
    }
    
    return 'conversation';
  }
}

export default ProgressiveMessenger;