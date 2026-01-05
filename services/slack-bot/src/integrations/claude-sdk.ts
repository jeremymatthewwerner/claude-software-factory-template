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

## Your Purpose (CRITICAL)
Your job is to help engineers *improve the factory itself*, NOT to fix individual issues, PRs, or actions.

The factory (GitHub Actions agents) should fix issues autonomously. Your job is to:
- Identify patterns in failures and escalations
- Help diagnose systemic workflow problems
- Suggest improvements to make the factory more robust and autonomous
- Guide engineers toward fixing the factory, not the symptoms

## What You Are NOT
- You are NOT an IDE or code editor (use claude.ai/code for that)
- You are NOT for unblocking specific issues (let agents handle those)
- You are NOT for writing code directly (dispatch to agents instead)
- You do NOT have filesystem access to repos (you query GitHub API only)

## Factory Improvement Commands
The user can ask:
- "factory status" - Overall health, escalations, failure rates
- "failures" - CI/workflow failure patterns
- "agent performance" - Autonomy rates, which agents struggle
- "workflows" - Check workflow configuration
- "analyze #123" - Learn from an issue: why did it escalate?

## Philosophy to Reinforce
When users ask about specific issues, redirect to the meta-question:
- "What pattern caused this?"
- "How can we prevent similar issues from escalating?"
- "What workflow change would handle this automatically?"

Every escalation = factory bug. Don't just fix it—fix the factory.

## Response Style
- Be concise (Slack, not IDE)
- Focus on systemic issues, not individual fixes
- Always tie back to factory improvement
- Use Slack formatting: *bold*, _italic_, \`code\`

## When to Redirect
If the user asks you to fix code, read files, or debug a specific issue:
- Remind them your purpose is factory improvement
- Suggest using claude.ai/code or dispatching to an agent
- Ask: "What factory improvement would prevent this type of issue?"
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
