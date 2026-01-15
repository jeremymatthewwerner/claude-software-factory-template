/**
 * MCP Server for Slack Bot
 *
 * Exposes Slack reading capabilities to Claude Code via MCP protocol.
 * This allows Claude to read Slack threads directly for debugging/context.
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';
import { WebClient } from '@slack/web-api';
import logger from '../utils/logger.js';

// Initialize Slack client
const slackClient = new WebClient(process.env.SLACK_BOT_TOKEN);

/**
 * Create and configure the MCP server
 */
export function createMcpServer(): Server {
  const server = new Server(
    {
      name: 'slack-mcp',
      version: '1.0.0',
    },
    {
      capabilities: {
        tools: {},
      },
    }
  );

  // Register tool listing
  server.setRequestHandler(ListToolsRequestSchema, async () => {
    return {
      tools: [
        {
          name: 'slack_read_thread',
          description: 'Read all messages in a Slack thread. Returns the full conversation history.',
          inputSchema: {
            type: 'object',
            properties: {
              channel: {
                type: 'string',
                description: 'Channel ID (e.g., C01234567)',
              },
              thread_ts: {
                type: 'string',
                description: 'Thread timestamp (e.g., 1234567890.123456)',
              },
              limit: {
                type: 'number',
                description: 'Max messages to fetch (default: 100)',
              },
            },
            required: ['channel', 'thread_ts'],
          },
        },
        {
          name: 'slack_list_channels',
          description: 'List available Slack channels the bot has access to.',
          inputSchema: {
            type: 'object',
            properties: {
              limit: {
                type: 'number',
                description: 'Max channels to return (default: 50)',
              },
            },
          },
        },
        {
          name: 'slack_read_channel',
          description: 'Read recent messages from a Slack channel.',
          inputSchema: {
            type: 'object',
            properties: {
              channel: {
                type: 'string',
                description: 'Channel ID (e.g., C01234567)',
              },
              limit: {
                type: 'number',
                description: 'Max messages to fetch (default: 50)',
              },
            },
            required: ['channel'],
          },
        },
        {
          name: 'slack_search_messages',
          description: 'Search for messages in Slack.',
          inputSchema: {
            type: 'object',
            properties: {
              query: {
                type: 'string',
                description: 'Search query',
              },
              limit: {
                type: 'number',
                description: 'Max results (default: 20)',
              },
            },
            required: ['query'],
          },
        },
      ],
    };
  });

  // Register tool execution
  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args } = request.params;

    try {
      switch (name) {
        case 'slack_read_thread':
          return await readThread(args as { channel: string; thread_ts: string; limit?: number });

        case 'slack_list_channels':
          return await listChannels(args as { limit?: number });

        case 'slack_read_channel':
          return await readChannel(args as { channel: string; limit?: number });

        case 'slack_search_messages':
          return await searchMessages(args as { query: string; limit?: number });

        default:
          return {
            content: [{ type: 'text', text: `Unknown tool: ${name}` }],
            isError: true,
          };
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      logger.error('MCP tool error', { tool: name, error: errorMessage });
      return {
        content: [{ type: 'text', text: `Error: ${errorMessage}` }],
        isError: true,
      };
    }
  });

  return server;
}

/**
 * Read all messages in a thread
 */
async function readThread(args: { channel: string; thread_ts: string; limit?: number }) {
  const result = await slackClient.conversations.replies({
    channel: args.channel,
    ts: args.thread_ts,
    limit: args.limit || 100,
  });

  if (!result.messages || result.messages.length === 0) {
    return {
      content: [{ type: 'text', text: 'No messages found in thread.' }],
    };
  }

  // Format messages for readability
  const formatted = result.messages.map((msg) => {
    const time = msg.ts ? new Date(parseFloat(msg.ts) * 1000).toISOString() : 'unknown';
    const user = msg.user || msg.bot_id || 'unknown';
    const isBot = !!msg.bot_id;
    return `[${time}] ${isBot ? '🤖' : '👤'} ${user}:\n${msg.text}\n`;
  }).join('\n---\n');

  return {
    content: [{
      type: 'text',
      text: `Thread in ${args.channel} (${result.messages.length} messages):\n\n${formatted}`,
    }],
  };
}

/**
 * List available channels
 */
async function listChannels(args: { limit?: number }) {
  const result = await slackClient.conversations.list({
    limit: args.limit || 50,
    types: 'public_channel,private_channel',
  });

  if (!result.channels || result.channels.length === 0) {
    return {
      content: [{ type: 'text', text: 'No channels found.' }],
    };
  }

  const formatted = result.channels.map((ch) => {
    const memberCount = ch.num_members || 0;
    const isPrivate = ch.is_private ? '🔒' : '📢';
    return `${isPrivate} ${ch.name} (${ch.id}) - ${memberCount} members`;
  }).join('\n');

  return {
    content: [{
      type: 'text',
      text: `Available channels:\n\n${formatted}`,
    }],
  };
}

/**
 * Read recent messages from a channel
 */
async function readChannel(args: { channel: string; limit?: number }) {
  const result = await slackClient.conversations.history({
    channel: args.channel,
    limit: args.limit || 50,
  });

  if (!result.messages || result.messages.length === 0) {
    return {
      content: [{ type: 'text', text: 'No messages found in channel.' }],
    };
  }

  // Messages come newest-first, reverse for chronological order
  const messages = [...result.messages].reverse();

  const formatted = messages.map((msg) => {
    const time = msg.ts ? new Date(parseFloat(msg.ts) * 1000).toISOString() : 'unknown';
    const user = msg.user || msg.bot_id || 'unknown';
    const isBot = !!msg.bot_id;
    const hasThread = msg.thread_ts && msg.reply_count ? ` [${msg.reply_count} replies]` : '';
    return `[${time}] ${isBot ? '🤖' : '👤'} ${user}${hasThread}:\n${msg.text}\n`;
  }).join('\n---\n');

  return {
    content: [{
      type: 'text',
      text: `Recent messages in ${args.channel}:\n\n${formatted}`,
    }],
  };
}

/**
 * Search for messages
 */
async function searchMessages(args: { query: string; limit?: number }) {
  const result = await slackClient.search.messages({
    query: args.query,
    count: args.limit || 20,
  });

  if (!result.messages?.matches || result.messages.matches.length === 0) {
    return {
      content: [{ type: 'text', text: `No messages found for query: ${args.query}` }],
    };
  }

  const formatted = result.messages.matches.map((match) => {
    const time = match.ts ? new Date(parseFloat(match.ts) * 1000).toISOString() : 'unknown';
    const channel = match.channel?.name || 'unknown';
    return `[${time}] #${channel} - ${match.username || 'unknown'}:\n${match.text}\n`;
  }).join('\n---\n');

  return {
    content: [{
      type: 'text',
      text: `Search results for "${args.query}" (${result.messages.matches.length} matches):\n\n${formatted}`,
    }],
  };
}

/**
 * Run the MCP server (standalone mode)
 */
export async function runMcpServer(): Promise<void> {
  const server = createMcpServer();
  const transport = new StdioServerTransport();

  await server.connect(transport);
  logger.info('Slack MCP server started');

  // Handle shutdown
  process.on('SIGINT', async () => {
    await server.close();
    process.exit(0);
  });
}

// If run directly, start the server
if (import.meta.url === `file://${process.argv[1]}`) {
  runMcpServer().catch(console.error);
}
