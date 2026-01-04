/**
 * Rate limiting for API requests
 */

import { config } from '../config.js';
import logger from './logger.js';

interface RateLimitEntry {
  count: number;
  tokens: number;
  windowStart: number;
}

class RateLimiter {
  private limits: Map<string, RateLimitEntry> = new Map();
  private readonly windowMs = 60 * 1000; // 1 minute window
  private readonly tokenWindowMs = 60 * 60 * 1000; // 1 hour window for tokens

  /**
   * Check if a user is within rate limits
   */
  checkLimit(userId: string): { allowed: boolean; retryAfter?: number } {
    const now = Date.now();
    const entry = this.limits.get(userId);

    if (!entry) {
      this.limits.set(userId, {
        count: 1,
        tokens: 0,
        windowStart: now,
      });
      return { allowed: true };
    }

    // Reset window if expired
    if (now - entry.windowStart > this.windowMs) {
      entry.count = 1;
      entry.windowStart = now;
      return { allowed: true };
    }

    // Check request count
    if (entry.count >= config.rateLimit.maxRequestsPerMinute) {
      const retryAfter = Math.ceil((entry.windowStart + this.windowMs - now) / 1000);
      logger.warn('Rate limit exceeded', { userId, count: entry.count, retryAfter });
      return { allowed: false, retryAfter };
    }

    entry.count++;
    return { allowed: true };
  }

  /**
   * Track token usage for a user
   */
  addTokens(userId: string, tokens: number): void {
    const entry = this.limits.get(userId);
    if (entry) {
      entry.tokens += tokens;
    }
  }

  /**
   * Check if user has token budget remaining
   */
  checkTokenBudget(userId: string): { allowed: boolean; remaining: number } {
    const entry = this.limits.get(userId);
    if (!entry) {
      return { allowed: true, remaining: config.rateLimit.maxTokensPerHour };
    }

    const remaining = config.rateLimit.maxTokensPerHour - entry.tokens;
    return {
      allowed: remaining > 0,
      remaining: Math.max(0, remaining),
    };
  }

  /**
   * Clean up old entries periodically
   */
  cleanup(): void {
    const now = Date.now();
    for (const [userId, entry] of this.limits.entries()) {
      if (now - entry.windowStart > this.tokenWindowMs) {
        this.limits.delete(userId);
      }
    }
  }
}

export const rateLimiter = new RateLimiter();

// Run cleanup every 10 minutes
setInterval(() => rateLimiter.cleanup(), 10 * 60 * 1000);

export default rateLimiter;
