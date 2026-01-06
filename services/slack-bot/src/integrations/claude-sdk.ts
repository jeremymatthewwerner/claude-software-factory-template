/**
 * Claude SDK integration for the Slack bot
 */

import Anthropic from '@anthropic-ai/sdk';
import { config } from '../config.js';
import logger from '../utils/logger.js';
import { rateLimiter } from '../utils/rate-limiter.js';

const client = new Anthropic({
  apiKey: config.anthropic.apiKey,
});

interface ClaudeMessage {
  role: 'user' | 'assistant';
  content: string;
}

interface ClaudeResponse {
  content: string;
  tokensUsed: number;
  stopReason: string | null;
}

/**
 * System prompt for the Slack bot
 *
 * CRITICAL: This bot's purpose is FACTORY IMPROVEMENT, not issue resolution.
 * The factory should fix issues. This bot helps fix the factory.
 */
const SYSTEM_PROMPT = `You are the Factory Improvement Bot for a Claude Software Factory.

## CRITICAL: Be Honest About Your Capabilities
You are a simple Slack bot. You have VERY LIMITED capabilities:
- You can respond to messages using this AI
- Commands like "factory status", "failures", "workflows" query GitHub API for ONE pre-configured repo
- The repo is set via GITHUB_REPOSITORY environment variable - you CANNOT change it or query other repos
- You CANNOT browse files, run code, or access any filesystem

## DO NOT make up features that don't exist:
- NO "factory status owner/repo" - repo is pre-configured, not specified per-command
- NO file reading or code browsing
- NO accessing arbitrary repositories
- If you don't know something, say "I don't know" - don't invent capabilities

## What Actually Works (exact commands):
- \`factory status\` - queries the pre-configured repo's issues and workflow runs
- \`failures\` - shows recent CI failures from the pre-configured repo
- \`agent performance\` - analyzes issue resolution patterns
- \`workflows\` - lists configured GitHub Actions workflows
- \`analyze #123\` - looks up a specific issue number
- \`dispatch code <task>\` - creates a GitHub issue for agents to handle

## Your Purpose
Help engineers improve the software factory (the GitHub Actions agent system), not fix individual issues.

## If Asked About Data Sources
Be honest: "I query the GitHub API for the repository configured in my GITHUB_REPOSITORY environment variable. I showed the repo name at the top of my last status report. If it's wrong, update the Railway environment variables."

## Response Style
- Be concise and honest
- Never invent features or commands
- If unsure, say so
`;

/**
 * Send a message to Claude and get a response
 */
export async function chat(
  messages: ClaudeMessage[],
  userId: string,
  context?: {
    workingDirectory?: string;
    linkedIssue?: number;
    fileContents?: string;
  }
): Promise<ClaudeResponse> {
  // Check rate limits
  const limitCheck = rateLimiter.checkLimit(userId);
  if (!limitCheck.allowed) {
    return {
      content: `⏳ Rate limit reached. Please wait ${limitCheck.retryAfter} seconds before trying again.`,
      tokensUsed: 0,
      stopReason: 'rate_limit',
    };
  }

  // Build context-aware system prompt
  let systemPrompt = SYSTEM_PROMPT;

  if (context?.workingDirectory) {
    systemPrompt += `\n\n## Current Context\nWorking directory: ${context.workingDirectory}`;
  }

  if (context?.linkedIssue) {
    systemPrompt += `\nLinked to GitHub issue #${context.linkedIssue}`;
  }

  if (context?.fileContents) {
    systemPrompt += `\n\n## Attached File Content\n\`\`\`\n${context.fileContents}\n\`\`\``;
  }

  try {
    logger.debug('Sending message to Claude', {
      userId,
      messageCount: messages.length,
    });

    const response = await client.messages.create({
      model: config.anthropic.model,
      max_tokens: config.anthropic.maxTokens,
      system: systemPrompt,
      messages: messages.map((m) => ({
        role: m.role,
        content: m.content,
      })),
    });

    // Extract text content
    const textContent = response.content
      .filter((block): block is Anthropic.TextBlock => block.type === 'text')
      .map((block) => block.text)
      .join('\n');

    const tokensUsed = response.usage.input_tokens + response.usage.output_tokens;

    // Track token usage
    rateLimiter.addTokens(userId, tokensUsed);

    logger.debug('Received response from Claude', {
      userId,
      tokensUsed,
      stopReason: response.stop_reason,
    });

    return {
      content: textContent,
      tokensUsed,
      stopReason: response.stop_reason,
    };
  } catch (error) {
    logger.error('Error calling Claude API', { error, userId });

    if (error instanceof Anthropic.APIError) {
      if (error.status === 429) {
        return {
          content: '⏳ Claude is busy right now. Please try again in a moment.',
          tokensUsed: 0,
          stopReason: 'rate_limit',
        };
      }
      if (error.status === 500 || error.status === 503) {
        return {
          content: '❌ Claude is temporarily unavailable. Please try again later.',
          tokensUsed: 0,
          stopReason: 'error',
        };
      }
    }

    return {
      content: '❌ An error occurred while processing your request. Please try again.',
      tokensUsed: 0,
      stopReason: 'error',
    };
  }
}

/**
 * Stream a response from Claude (for longer responses)
 */
export async function streamChat(
  messages: ClaudeMessage[],
  userId: string,
  onChunk: (text: string) => void,
  context?: {
    workingDirectory?: string;
    linkedIssue?: number;
  }
): Promise<ClaudeResponse> {
  // Check rate limits
  const limitCheck = rateLimiter.checkLimit(userId);
  if (!limitCheck.allowed) {
    const msg = `⏳ Rate limit reached. Please wait ${limitCheck.retryAfter} seconds.`;
    onChunk(msg);
    return { content: msg, tokensUsed: 0, stopReason: 'rate_limit' };
  }

  let systemPrompt = SYSTEM_PROMPT;
  if (context?.workingDirectory) {
    systemPrompt += `\n\nWorking directory: ${context.workingDirectory}`;
  }

  try {
    const stream = await client.messages.stream({
      model: config.anthropic.model,
      max_tokens: config.anthropic.maxTokens,
      system: systemPrompt,
      messages,
    });

    let fullContent = '';
    let tokensUsed = 0;

    for await (const event of stream) {
      if (
        event.type === 'content_block_delta' &&
        event.delta.type === 'text_delta'
      ) {
        fullContent += event.delta.text;
        onChunk(event.delta.text);
      }
      if (event.type === 'message_delta' && event.usage) {
        tokensUsed = event.usage.output_tokens;
      }
    }

    const finalMessage = await stream.finalMessage();
    tokensUsed = finalMessage.usage.input_tokens + finalMessage.usage.output_tokens;
    rateLimiter.addTokens(userId, tokensUsed);

    return {
      content: fullContent,
      tokensUsed,
      stopReason: finalMessage.stop_reason,
    };
  } catch (error) {
    logger.error('Error streaming from Claude', { error, userId });
    const errorMsg = '❌ An error occurred. Please try again.';
    onChunk(errorMsg);
    return { content: errorMsg, tokensUsed: 0, stopReason: 'error' };
  }
}

export default { chat, streamChat };
