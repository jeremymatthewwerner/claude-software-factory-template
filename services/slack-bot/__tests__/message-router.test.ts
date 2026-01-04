/**
 * Tests for message router
 */

import { parseIntent } from '../src/handlers/message-router.js';

describe('parseIntent', () => {
  describe('dispatch commands', () => {
    it('should parse explicit dispatch command with slash', () => {
      const intent = parseIntent('/dispatch code fix the login bug');
      expect(intent.type).toBe('dispatch');
      expect(intent.agent).toBe('code');
      expect(intent.confidence).toBe(1.0);
      expect(intent.extractedTask).toBe('fix the login bug');
    });

    it('should parse dispatch command without slash', () => {
      const intent = parseIntent('dispatch qa improve test coverage');
      expect(intent.type).toBe('dispatch');
      expect(intent.agent).toBe('qa');
      expect(intent.extractedTask).toBe('improve test coverage');
    });

    it('should parse dispatch to devops agent', () => {
      const intent = parseIntent('dispatch devops check production health');
      expect(intent.type).toBe('dispatch');
      expect(intent.agent).toBe('devops');
    });

    it('should parse dispatch to release agent', () => {
      const intent = parseIntent('dispatch release update dependencies');
      expect(intent.type).toBe('dispatch');
      expect(intent.agent).toBe('release');
    });

    it('should parse dispatch to triage agent', () => {
      const intent = parseIntent('dispatch triage classify this issue');
      expect(intent.type).toBe('dispatch');
      expect(intent.agent).toBe('triage');
    });

    it('should parse dispatch to principal-engineer', () => {
      const intent = parseIntent('dispatch principal-engineer investigate the bug');
      expect(intent.type).toBe('dispatch');
      expect(intent.agent).toBe('principal-engineer');
    });
  });

  describe('status commands', () => {
    it('should parse status request', () => {
      const intent = parseIntent('status');
      expect(intent.type).toBe('status');
      expect(intent.confidence).toBeGreaterThan(0.5);
    });

    it('should parse "what are you working on"', () => {
      const intent = parseIntent('what are you working on?');
      expect(intent.type).toBe('status');
    });

    it('should parse "what\'s happening"', () => {
      const intent = parseIntent("what's happening with my issue?");
      expect(intent.type).toBe('status');
    });
  });

  describe('help commands', () => {
    it('should parse help request', () => {
      const intent = parseIntent('help');
      expect(intent.type).toBe('help');
      expect(intent.confidence).toBe(1.0);
    });

    it('should parse "what can you do"', () => {
      const intent = parseIntent('what can you do?');
      expect(intent.type).toBe('help');
    });
  });

  describe('conversation with suggestions', () => {
    it('should suggest code agent for bug-related message', () => {
      const intent = parseIntent('I found a bug in the login system');
      expect(intent.type).toBe('conversation');
      expect(intent.suggestedAgent).toBe('code');
    });

    it('should suggest code agent for fix request', () => {
      const intent = parseIntent('Can you fix the header alignment?');
      expect(intent.type).toBe('conversation');
      expect(intent.suggestedAgent).toBe('code');
    });

    it('should suggest qa agent for test-related message', () => {
      const intent = parseIntent('We need more test coverage');
      expect(intent.type).toBe('conversation');
      expect(intent.suggestedAgent).toBe('qa');
    });

    it('should suggest devops for deploy-related message', () => {
      const intent = parseIntent('Can you deploy the latest changes?');
      expect(intent.type).toBe('conversation');
      expect(intent.suggestedAgent).toBe('devops');
    });

    it('should suggest release for dependency message', () => {
      const intent = parseIntent('We need to update our dependencies');
      expect(intent.type).toBe('conversation');
      expect(intent.suggestedAgent).toBe('release');
    });
  });

  describe('plain conversation', () => {
    it('should parse generic message as conversation', () => {
      const intent = parseIntent('How does the authentication system work?');
      expect(intent.type).toBe('conversation');
      expect(intent.confidence).toBe(1.0);
      expect(intent.suggestedAgent).toBeUndefined();
    });

    it('should parse greeting as conversation', () => {
      const intent = parseIntent('Hello, I have a question');
      expect(intent.type).toBe('conversation');
    });
  });
});
