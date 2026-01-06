/**
 * Manage Slack conversation sessions
 */

import { v4 as uuidv4 } from 'uuid';
import type { SlackSession, ConversationMessage } from '../types.js';
import logger from '../utils/logger.js';
import { config } from '../config.js';

class SessionManager {
  private sessions: Map<string, SlackSession> = new Map();
  private readonly maxHistoryLength = 20;
  private readonly sessionTimeoutMs = 2 * 60 * 60 * 1000; // 2 hours

  /**
   * Get session key from channel and thread
   */
  private getKey(channelId: string, threadTs: string): string {
    return `${channelId}-${threadTs}`;
  }

  /**
   * Get or create a session for a thread
   */
  getOrCreate(channelId: string, threadTs: string, userId: string): SlackSession {
    const key = this.getKey(channelId, threadTs);
    let session = this.sessions.get(key);

    if (!session) {
      session = {
        channelId,
        threadTs,
        workingDirectory: config.repo.defaultRepo
          ? `${config.repo.basePath}/${config.repo.defaultRepo}`
          : config.repo.basePath,
        claudeSessionId: uuidv4(),
        status: 'active',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        userId,
        conversationHistory: [],
      };
      this.sessions.set(key, session);
      logger.info('Created new session', { channelId, threadTs, userId });
    }

    return session;
  }

  /**
   * Get existing session
   */
  get(channelId: string, threadTs: string): SlackSession | undefined {
    return this.sessions.get(this.getKey(channelId, threadTs));
  }

  /**
   * Add message to session history
   */
  addMessage(
    channelId: string,
    threadTs: string,
    role: 'user' | 'assistant',
    content: string,
    slackTs?: string
  ): void {
    const session = this.get(channelId, threadTs);
    if (!session) {
      logger.warn('Attempted to add message to non-existent session', { channelId, threadTs });
      return;
    }

    session.conversationHistory.push({
      role,
      content,
      timestamp: new Date().toISOString(),
      slackTs,
    });

    // Trim history if too long
    if (session.conversationHistory.length > this.maxHistoryLength) {
      session.conversationHistory = session.conversationHistory.slice(-this.maxHistoryLength);
    }

    session.updatedAt = new Date().toISOString();
  }

  /**
   * Get conversation history formatted for Claude
   */
  getHistoryForClaude(
    channelId: string,
    threadTs: string
  ): Array<{ role: 'user' | 'assistant'; content: string }> {
    const session = this.get(channelId, threadTs);
    if (!session) {
      return [];
    }

    return session.conversationHistory.map((msg) => ({
      role: msg.role,
      content: msg.content,
    }));
  }

  /**
   * Link session to a GitHub issue
   */
  linkIssue(channelId: string, threadTs: string, issueNumber: number): void {
    const session = this.get(channelId, threadTs);
    if (session) {
      session.linkedIssue = issueNumber;
      session.updatedAt = new Date().toISOString();
      logger.info('Linked session to issue', { channelId, threadTs, issueNumber });
    }
  }

  /**
   * Link session to a GitHub PR
   */
  linkPR(channelId: string, threadTs: string, prNumber: number): void {
    const session = this.get(channelId, threadTs);
    if (session) {
      session.linkedPR = prNumber;
      session.updatedAt = new Date().toISOString();
      logger.info('Linked session to PR', { channelId, threadTs, prNumber });
    }
  }

  /**
   * Update working directory for session
   */
  setWorkingDirectory(channelId: string, threadTs: string, directory: string): void {
    const session = this.get(channelId, threadTs);
    if (session) {
      session.workingDirectory = directory;
      session.updatedAt = new Date().toISOString();
      logger.info('Updated working directory', { channelId, threadTs, directory });
    }
  }

  /**
   * Mark session as completed
   */
  complete(channelId: string, threadTs: string): void {
    const session = this.get(channelId, threadTs);
    if (session) {
      session.status = 'completed';
      session.updatedAt = new Date().toISOString();
    }
  }

  /**
   * Find session by linked issue
   */
  findByIssue(issueNumber: number): SlackSession | undefined {
    for (const session of this.sessions.values()) {
      if (session.linkedIssue === issueNumber) {
        return session;
      }
    }
    return undefined;
  }

  /**
   * Clean up old sessions
   */
  cleanup(): void {
    const now = Date.now();
    let cleaned = 0;

    for (const [key, session] of this.sessions.entries()) {
      const updatedAt = new Date(session.updatedAt).getTime();
      if (now - updatedAt > this.sessionTimeoutMs) {
        this.sessions.delete(key);
        cleaned++;
      }
    }

    if (cleaned > 0) {
      logger.info('Cleaned up expired sessions', { count: cleaned });
    }
  }

  /**
   * Get session statistics
   */
  getStats(): { total: number; active: number; completed: number } {
    let active = 0;
    let completed = 0;

    for (const session of this.sessions.values()) {
      if (session.status === 'active') {
        active++;
      } else if (session.status === 'completed') {
        completed++;
      }
    }

    return {
      total: this.sessions.size,
      active,
      completed,
    };
  }
}

export const sessionManager = new SessionManager();

// Run cleanup every 30 minutes
setInterval(() => sessionManager.cleanup(), 30 * 60 * 1000);

export default sessionManager;
