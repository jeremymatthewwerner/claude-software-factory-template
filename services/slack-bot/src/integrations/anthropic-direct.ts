/**
 * Direct Anthropic SDK integration
 *
 * This bypasses the Claude Code CLI (which crashes in Railway containers)
 * and uses the Anthropic SDK directly with tool definitions.
 */

import Anthropic from '@anthropic-ai/sdk';
import { execSync } from 'child_process';
import { readFileSync, writeFileSync, existsSync, readdirSync, statSync } from 'fs';
import { join, dirname } from 'path';
import { config } from '../config.js';
import logger from '../utils/logger.js';

const client = new Anthropic({
  apiKey: config.anthropic.apiKey,
});

// Tool definitions for Claude
const tools: Anthropic.Tool[] = [
  {
    name: 'read_file',
    description: 'Read the contents of a file at the specified path',
    input_schema: {
      type: 'object' as const,
      properties: {
        path: { type: 'string', description: 'The file path to read' },
      },
      required: ['path'],
    },
  },
  {
    name: 'write_file',
    description: 'Write content to a file at the specified path',
    input_schema: {
      type: 'object' as const,
      properties: {
        path: { type: 'string', description: 'The file path to write to' },
        content: { type: 'string', description: 'The content to write' },
      },
      required: ['path', 'content'],
    },
  },
  {
    name: 'list_files',
    description: 'List files and directories at the specified path',
    input_schema: {
      type: 'object' as const,
      properties: {
        path: { type: 'string', description: 'The directory path to list' },
      },
      required: ['path'],
    },
  },
  {
    name: 'run_bash',
    description: 'Execute a bash command and return the output. Use for git operations, npm commands, etc.',
    input_schema: {
      type: 'object' as const,
      properties: {
        command: { type: 'string', description: 'The bash command to execute' },
      },
      required: ['command'],
    },
  },
  {
    name: 'search_files',
    description: 'Search for files matching a pattern using glob',
    input_schema: {
      type: 'object' as const,
      properties: {
        pattern: { type: 'string', description: 'The glob pattern to search for (e.g., "*.ts", "**/*.js")' },
        path: { type: 'string', description: 'The directory to search in' },
      },
      required: ['pattern', 'path'],
    },
  },
  {
    name: 'grep',
    description: 'Search for text patterns in files',
    input_schema: {
      type: 'object' as const,
      properties: {
        pattern: { type: 'string', description: 'The regex pattern to search for' },
        path: { type: 'string', description: 'The file or directory to search in' },
      },
      required: ['pattern', 'path'],
    },
  },
];

// Execute a tool and return the result
function executeTool(name: string, input: Record<string, unknown>, workingDir: string): string {
  try {
    switch (name) {
      case 'read_file': {
        const filePath = join(workingDir, input.path as string);
        if (!existsSync(filePath)) {
          return `Error: File not found: ${input.path}`;
        }
        return readFileSync(filePath, 'utf-8');
      }

      case 'write_file': {
        const filePath = join(workingDir, input.path as string);
        const dir = dirname(filePath);
        if (!existsSync(dir)) {
          execSync(`mkdir -p "${dir}"`, { cwd: workingDir });
        }
        writeFileSync(filePath, input.content as string, 'utf-8');
        return `Successfully wrote to ${input.path}`;
      }

      case 'list_files': {
        const dirPath = join(workingDir, input.path as string);
        if (!existsSync(dirPath)) {
          return `Error: Directory not found: ${input.path}`;
        }
        const entries = readdirSync(dirPath);
        return entries.map(entry => {
          const fullPath = join(dirPath, entry);
          const stat = statSync(fullPath);
          return `${stat.isDirectory() ? '[DIR]' : '[FILE]'} ${entry}`;
        }).join('\n');
      }

      case 'run_bash': {
        const command = input.command as string;
        // Security: block dangerous commands
        const dangerous = ['rm -rf /', 'dd if=', ':(){ :|:& };:', 'mkfs'];
        if (dangerous.some(d => command.includes(d))) {
          return 'Error: Command blocked for safety reasons';
        }
        try {
          // Use stdio: 'pipe' and capture both stdout and stderr
          const result = execSync(command, {
            cwd: workingDir,
            encoding: 'utf-8',
            timeout: 120000, // 2 minute timeout for git operations
            maxBuffer: 1024 * 1024, // 1MB output limit
            stdio: ['pipe', 'pipe', 'pipe'], // capture stderr separately
          });
          return result || '(no output)';
        } catch (error: unknown) {
          const execError = error as {
            stdout?: string;
            stderr?: string;
            message?: string;
            status?: number;
          };
          // For git commands, stderr often contains useful info even on success
          // Combine all available output for debugging
          const parts: string[] = [];
          if (execError.stdout) parts.push(`stdout: ${execError.stdout}`);
          if (execError.stderr) parts.push(`stderr: ${execError.stderr}`);
          if (execError.status !== undefined) parts.push(`exit code: ${execError.status}`);
          if (parts.length === 0) parts.push(execError.message || 'Unknown error');
          return `Error executing command:\n${parts.join('\n')}`;
        }
      }

      case 'search_files': {
        try {
          const output = execSync(
            `find "${input.path}" -name "${input.pattern}" 2>/dev/null | head -50`,
            { cwd: workingDir, encoding: 'utf-8' }
          );
          return output || 'No files found';
        } catch {
          return 'No files found';
        }
      }

      case 'grep': {
        try {
          const output = execSync(
            `grep -rn "${input.pattern}" "${input.path}" 2>/dev/null | head -50`,
            { cwd: workingDir, encoding: 'utf-8' }
          );
          return output || 'No matches found';
        } catch {
          return 'No matches found';
        }
      }

      default:
        return `Unknown tool: ${name}`;
    }
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : 'Unknown error';
    logger.error('Tool execution error', { tool: name, error: errorMessage });
    return `Error: ${errorMessage}`;
  }
}

// System prompt for the bot
const SYSTEM_PROMPT = `You are Claude, a helpful AI assistant running in a Slack bot for the Claude Software Factory.

You have access to tools for file operations and bash commands. Use them to help users with their requests.

## Working Directory
\`/tmp/repo\` - a clone of the GitHub repository:
- \`services/slack-bot/\` - This Slack bot (TypeScript/Node.js)
- \`.github/workflows/\` - GitHub Actions for CI/CD
- \`CLAUDE.md\`, \`README.md\` - Documentation

## Response Formatting
Keep responses SHORT and scannable for Slack:
- Use bullet points for lists
- Use \`code\` for file paths and commands
- Keep explanations brief - 1-2 sentences max
- Don't repeat tool outputs verbatim

## Git Operations (CRITICAL)
When deploying code changes:
1. Make changes with write_file
2. Build: \`cd services/slack-bot && npm run build\`
3. Commit: \`git add -A && git commit -m "message"\`
4. Push to main: \`git push origin main\`
5. Verify: \`git log origin/main -1 --oneline\`

**ALWAYS push to \`main\` branch - Railway deploys from main.**
**Show the actual git push output. If it fails, report the error clearly.**

The git remote is pre-configured with authentication.`;

/**
 * Execute a conversation with Claude using direct SDK
 */
export async function executeWithDirectSDK(
  prompt: string,
  userId: string,
  threadKey: string,
  options: {
    workingDirectory?: string;
    onProgress?: (text: string) => void;
    conversationHistory?: Array<{ role: 'user' | 'assistant'; content: string }>;
  } = {}
): Promise<{
  content: string;
  toolsUsed: string[];
  error?: string;
}> {
  const workingDir = options.workingDirectory || process.cwd();
  const toolsUsed: string[] = [];

  // Build messages array
  const messages: Anthropic.MessageParam[] = [];

  // Add conversation history
  if (options.conversationHistory) {
    for (const msg of options.conversationHistory) {
      messages.push({
        role: msg.role,
        content: msg.content,
      });
    }
  }

  // Add current prompt
  messages.push({
    role: 'user',
    content: prompt,
  });

  logger.info('Starting direct SDK conversation', {
    userId,
    threadKey,
    workingDir,
    historyLength: options.conversationHistory?.length || 0,
  });

  try {
    let response = await client.messages.create({
      model: config.anthropic.model || 'claude-sonnet-4-20250514',
      max_tokens: 8192,
      system: SYSTEM_PROMPT,
      tools,
      messages,
    });

    let fullContent = '';
    let iterations = 0;
    const maxIterations = 20; // Prevent infinite loops

    // Process response and handle tool calls
    while (iterations < maxIterations) {
      iterations++;

      // Extract text content
      for (const block of response.content) {
        if (block.type === 'text') {
          fullContent += block.text;
          options.onProgress?.(block.text);
        }
      }

      // Check if we need to handle tool calls
      if (response.stop_reason !== 'tool_use') {
        break;
      }

      // Handle tool calls
      const toolUseBlocks = response.content.filter(
        (block): block is Anthropic.ToolUseBlock => block.type === 'tool_use'
      );

      if (toolUseBlocks.length === 0) {
        break;
      }

      // Execute tools and collect results
      const toolResults: Anthropic.ToolResultBlockParam[] = [];

      for (const toolUse of toolUseBlocks) {
        logger.info('Executing tool', { tool: toolUse.name, input: toolUse.input });
        toolsUsed.push(toolUse.name);

        const input = toolUse.input as Record<string, unknown>;

        const result = executeTool(
          toolUse.name,
          input,
          workingDir
        );

        // Format tool invocation + result for display
        let toolDisplay = '';
        const resultPreview = result.length > 200 ? result.slice(0, 200) + '...' : result;

        switch (toolUse.name) {
          case 'run_bash': {
            const cmd = (input.command as string).length > 60
              ? (input.command as string).slice(0, 60) + '...'
              : input.command;
            if (result.startsWith('Error')) {
              toolDisplay = `❌ \`$ ${cmd}\`\n\`\`\`\n${resultPreview}\n\`\`\``;
            } else {
              toolDisplay = `✅ \`$ ${cmd}\``;
              // Only show output if it's meaningful
              if (result && result !== '(no output)' && result.length > 0) {
                toolDisplay += `\n\`\`\`\n${resultPreview}\n\`\`\``;
              }
            }
            break;
          }
          case 'read_file':
            toolDisplay = `📄 Read \`${input.path}\``;
            break;
          case 'write_file':
            toolDisplay = `✅ Wrote \`${input.path}\``;
            break;
          case 'list_files':
            toolDisplay = `📁 Listed \`${input.path}\``;
            break;
          case 'search_files':
            toolDisplay = `🔍 Found files matching \`${input.pattern}\``;
            break;
          case 'grep':
            toolDisplay = `🔎 Searched \`${input.pattern}\``;
            break;
          default:
            toolDisplay = `[${toolUse.name}]`;
        }

        // Notify progress with useful context
        options.onProgress?.(`\n${toolDisplay}\n`);

        toolResults.push({
          type: 'tool_result',
          tool_use_id: toolUse.id,
          content: result,
        });
      }

      // Continue conversation with tool results
      messages.push({
        role: 'assistant',
        content: response.content,
      });

      messages.push({
        role: 'user',
        content: toolResults,
      });

      // Get next response
      response = await client.messages.create({
        model: config.anthropic.model || 'claude-sonnet-4-20250514',
        max_tokens: 8192,
        system: SYSTEM_PROMPT,
        tools,
        messages,
      });
    }

    logger.info('Direct SDK conversation completed', {
      userId,
      threadKey,
      iterations,
      toolsUsed,
    });

    return {
      content: fullContent || 'Task completed.',
      toolsUsed,
    };
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : 'Unknown error';
    logger.error('Direct SDK error', { error: errorMessage, userId, threadKey });

    return {
      content: `❌ Error: ${errorMessage}`,
      toolsUsed,
      error: errorMessage,
    };
  }
}

export default {
  executeWithDirectSDK,
};
