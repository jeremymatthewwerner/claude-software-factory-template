/**
 * Tests for utility functions
 */

import { markdownToSlack, slackToMarkdown } from '../src/utils/markdown-to-slack.js';
import { rateLimiter } from '../src/utils/rate-limiter.js';

describe('markdownToSlack', () => {
  describe('bold formatting', () => {
    it('should convert markdown bold to Slack bold', () => {
      expect(markdownToSlack('**bold text**')).toBe('*bold text*');
    });

    it('should handle multiple bold sections', () => {
      expect(markdownToSlack('**one** and **two**')).toBe('*one* and *two*');
    });
  });

  describe('italic formatting', () => {
    it('should convert markdown italic to Slack italic', () => {
      expect(markdownToSlack('*italic text*')).toBe('_italic text_');
    });

    it('should convert underscore italic to Slack italic', () => {
      expect(markdownToSlack('_italic text_')).toBe('_italic text_');
    });
  });

  describe('code formatting', () => {
    it('should preserve inline code', () => {
      expect(markdownToSlack('Use `code` here')).toBe('Use `code` here');
    });

    it('should preserve code blocks', () => {
      const input = '```\ncode block\n```';
      expect(markdownToSlack(input)).toBe('```\ncode block\n```');
    });

    it('should convert fenced code with language', () => {
      const input = '```javascript\nconst x = 1;\n```';
      const result = markdownToSlack(input);
      expect(result).toContain('const x = 1;');
    });
  });

  describe('links', () => {
    it('should convert markdown links to Slack format', () => {
      expect(markdownToSlack('[link text](https://example.com)'))
        .toBe('<https://example.com|link text>');
    });

    it('should handle multiple links', () => {
      const input = '[one](https://one.com) and [two](https://two.com)';
      const result = markdownToSlack(input);
      expect(result).toContain('<https://one.com|one>');
      expect(result).toContain('<https://two.com|two>');
    });
  });

  describe('headers', () => {
    it('should convert h1 to bold', () => {
      expect(markdownToSlack('# Header One')).toBe('*Header One*');
    });

    it('should convert h2 to bold', () => {
      expect(markdownToSlack('## Header Two')).toBe('*Header Two*');
    });

    it('should convert h3 to bold', () => {
      expect(markdownToSlack('### Header Three')).toBe('*Header Three*');
    });
  });

  describe('strikethrough', () => {
    it('should preserve strikethrough', () => {
      expect(markdownToSlack('~~strikethrough~~')).toBe('~strikethrough~');
    });
  });

  describe('blockquotes', () => {
    it('should convert blockquotes', () => {
      expect(markdownToSlack('> quoted text')).toBe('> quoted text');
    });
  });
});

describe('slackToMarkdown', () => {
  it('should convert Slack bold to markdown', () => {
    expect(slackToMarkdown('*bold*')).toBe('**bold**');
  });

  it('should convert Slack italic to markdown', () => {
    expect(slackToMarkdown('_italic_')).toBe('*italic*');
  });

  it('should convert Slack links to markdown', () => {
    expect(slackToMarkdown('<https://example.com|link>'))
      .toBe('[link](https://example.com)');
  });

  it('should handle plain URLs', () => {
    expect(slackToMarkdown('<https://example.com>'))
      .toBe('[https://example.com](https://example.com)');
  });
});

describe('rateLimiter', () => {
  beforeEach(() => {
    // Reset the limiter between tests
    rateLimiter.reset();
  });

  describe('check', () => {
    it('should allow first request', () => {
      expect(rateLimiter.check('user1')).toBe(true);
    });

    it('should allow multiple requests within limit', () => {
      for (let i = 0; i < 10; i++) {
        expect(rateLimiter.check('user2')).toBe(true);
      }
    });

    it('should track different users separately', () => {
      // Each user gets their own limit
      for (let i = 0; i < 20; i++) {
        rateLimiter.check('userA');
      }
      expect(rateLimiter.check('userB')).toBe(true);
    });
  });

  describe('reset', () => {
    it('should clear all rate limit data', () => {
      rateLimiter.check('user1');
      rateLimiter.check('user1');
      rateLimiter.reset();

      // After reset, should be allowed again
      expect(rateLimiter.check('user1')).toBe(true);
    });
  });

  describe('getRemainingTokens', () => {
    it('should return max tokens for new user', () => {
      const remaining = rateLimiter.getRemainingTokens('newuser');
      expect(remaining).toBeGreaterThan(0);
    });

    it('should decrease after requests', () => {
      const before = rateLimiter.getRemainingTokens('user3');
      rateLimiter.check('user3');
      rateLimiter.check('user3');
      const after = rateLimiter.getRemainingTokens('user3');

      expect(after).toBeLessThan(before);
    });
  });
});
