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
 */
const SYSTEM_PROMPT = `You are Claude, an AI assistant integrated into a Slack workspace as part of a Claude Software Factory.

## Your Role
You help developers with coding tasks, answer questions, debug issues, and can dispatch work to specialized agents when needed.

## Context
- You're chatting in Slack, so keep responses concise and well-formatted for Slack
- You have access to the codebase and can read files, search code, and understand the project
- For complex tasks requiring code changes, you can dispatch to specialized agents (Code Agent, QA Agent, etc.)
- The user can also work with you in claude.ai/code for more complex IDE-like sessions

## Available Commands
Users can ask you to:
- Answer coding questions directly
- Explain code or concepts
- Debug issues
- "fix bug #123" - Dispatch to Code Agent
- "deploy to staging" - Dispatch to DevOps Agent
- "run tests" - Dispatch to QA Agent
- "status" - Show current agent activity
- "cwd" or "pwd" - Show current working directory
- "set directory <path>" - Change working directory

## Response Format
- Use Slack formatting: *bold*, _italic_, \`code\`, \`\`\`code blocks\`\`\`
- Keep responses focused and actionable
- For long code, consider if it should be a file edit via agent instead
- Offer to dispatch to agents for tasks that need code changes

## Important
- Be helpful but concise (Slack is for quick interactions)
- If a task is complex, suggest using an agent or claude.ai/code
- Always be honest about what you can and cannot do directly
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
