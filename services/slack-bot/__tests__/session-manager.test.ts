/**
 * Tests for session manager
 */

import sessionManager from '../src/state/session-manager.js';

describe('SessionManager', () => {
  const testChannel = 'C12345678';
  const testThread = '1234567890.123456';
  const testUser = 'U12345678';

  beforeEach(() => {
    // Clean up any existing sessions
    sessionManager.cleanup();
  });

  describe('getOrCreate', () => {
    it('should create a new session if none exists', () => {
      const session = sessionManager.getOrCreate(testChannel, testThread, testUser);

      expect(session).toBeDefined();
      expect(session.channelId).toBe(testChannel);
      expect(session.threadTs).toBe(testThread);
      expect(session.userId).toBe(testUser);
      expect(session.conversationHistory).toHaveLength(0);
      expect(session.status).toBe('active');
    });

    it('should return existing session if one exists', () => {
      const session1 = sessionManager.getOrCreate(testChannel, testThread, testUser);
      session1.linkedIssue = 42;

      const session2 = sessionManager.getOrCreate(testChannel, testThread, testUser);

      expect(session2.linkedIssue).toBe(42);
    });

    it('should create separate sessions for different threads', () => {
      const session1 = sessionManager.getOrCreate(testChannel, '111.111', testUser);
      const session2 = sessionManager.getOrCreate(testChannel, '222.222', testUser);

      session1.linkedIssue = 1;
      session2.linkedIssue = 2;

      expect(session1.linkedIssue).toBe(1);
      expect(session2.linkedIssue).toBe(2);
    });
  });

  describe('get', () => {
    it('should return undefined if session does not exist', () => {
      const session = sessionManager.get('nonexistent', 'thread');
      expect(session).toBeUndefined();
    });

    it('should return existing session', () => {
      sessionManager.getOrCreate(testChannel, testThread, testUser);
      const session = sessionManager.get(testChannel, testThread);

      expect(session).toBeDefined();
      expect(session?.channelId).toBe(testChannel);
    });
  });

  describe('addMessage', () => {
    it('should add user message to history', () => {
      sessionManager.getOrCreate(testChannel, testThread, testUser);
      sessionManager.addMessage(testChannel, testThread, 'user', 'Hello');

      const session = sessionManager.get(testChannel, testThread);
      expect(session?.conversationHistory).toHaveLength(1);
      expect(session?.conversationHistory[0].role).toBe('user');
      expect(session?.conversationHistory[0].content).toBe('Hello');
    });

    it('should add assistant message to history', () => {
      sessionManager.getOrCreate(testChannel, testThread, testUser);
      sessionManager.addMessage(testChannel, testThread, 'assistant', 'Hi there!', 'msg123');

      const session = sessionManager.get(testChannel, testThread);
      expect(session?.conversationHistory).toHaveLength(1);
      expect(session?.conversationHistory[0].role).toBe('assistant');
      expect(session?.conversationHistory[0].slackMessageTs).toBe('msg123');
    });

    it('should trim history when it exceeds max length', () => {
      sessionManager.getOrCreate(testChannel, testThread, testUser);

      // Add 60 messages (more than default max of 50)
      for (let i = 0; i < 60; i++) {
        sessionManager.addMessage(testChannel, testThread, 'user', `Message ${i}`);
      }

      const session = sessionManager.get(testChannel, testThread);
      expect(session?.conversationHistory.length).toBeLessThanOrEqual(50);
    });

    it('should update session timestamp', () => {
      sessionManager.getOrCreate(testChannel, testThread, testUser);
      const before = sessionManager.get(testChannel, testThread)?.updatedAt;

      // Small delay to ensure timestamp changes
      sessionManager.addMessage(testChannel, testThread, 'user', 'New message');

      const after = sessionManager.get(testChannel, testThread)?.updatedAt;
      expect(after).toBeDefined();
      expect(before).toBeDefined();
    });
  });

  describe('linkIssue', () => {
    it('should link issue to session', () => {
      sessionManager.getOrCreate(testChannel, testThread, testUser);
      sessionManager.linkIssue(testChannel, testThread, 42);

      const session = sessionManager.get(testChannel, testThread);
      expect(session?.linkedIssue).toBe(42);
    });
  });

  describe('linkPR', () => {
    it('should link PR to session', () => {
      sessionManager.getOrCreate(testChannel, testThread, testUser);
      sessionManager.linkPR(testChannel, testThread, 123);

      const session = sessionManager.get(testChannel, testThread);
      expect(session?.linkedPR).toBe(123);
    });
  });

  describe('setActiveAgent', () => {
    it('should set active agent', () => {
      sessionManager.getOrCreate(testChannel, testThread, testUser);
      sessionManager.setActiveAgent(testChannel, testThread, 'code');

      const session = sessionManager.get(testChannel, testThread);
      expect(session?.activeAgent).toBe('code');
    });

    it('should clear active agent when null passed', () => {
      sessionManager.getOrCreate(testChannel, testThread, testUser);
      sessionManager.setActiveAgent(testChannel, testThread, 'code');
      sessionManager.setActiveAgent(testChannel, testThread, null);

      const session = sessionManager.get(testChannel, testThread);
      expect(session?.activeAgent).toBeUndefined();
    });
  });

  describe('getHistoryForClaude', () => {
    it('should convert history to Claude message format', () => {
      sessionManager.getOrCreate(testChannel, testThread, testUser);
      sessionManager.addMessage(testChannel, testThread, 'user', 'Hello');
      sessionManager.addMessage(testChannel, testThread, 'assistant', 'Hi!');
      sessionManager.addMessage(testChannel, testThread, 'user', 'How are you?');

      const history = sessionManager.getHistoryForClaude(testChannel, testThread);

      expect(history).toHaveLength(3);
      expect(history[0]).toEqual({ role: 'user', content: 'Hello' });
      expect(history[1]).toEqual({ role: 'assistant', content: 'Hi!' });
      expect(history[2]).toEqual({ role: 'user', content: 'How are you?' });
    });

    it('should return empty array if session does not exist', () => {
      const history = sessionManager.getHistoryForClaude('nonexistent', 'thread');
      expect(history).toEqual([]);
    });
  });

  describe('getStats', () => {
    it('should return session statistics', () => {
      sessionManager.getOrCreate('C1', 'T1', 'U1');
      sessionManager.getOrCreate('C2', 'T2', 'U2');

      const stats = sessionManager.getStats();

      expect(stats.activeSessions).toBe(2);
      expect(stats.totalMessages).toBe(0);
    });

    it('should count total messages', () => {
      sessionManager.getOrCreate(testChannel, testThread, testUser);
      sessionManager.addMessage(testChannel, testThread, 'user', 'Msg 1');
      sessionManager.addMessage(testChannel, testThread, 'user', 'Msg 2');

      const stats = sessionManager.getStats();

      expect(stats.totalMessages).toBe(2);
    });
  });
});
