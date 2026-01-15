/**
 * Claude Software Factory - Slack Bot
 *
 * A conversational meta-agent that provides a Slack interface for interacting
 * with the Claude-powered software factory. This bot:
 *
 * 1. Provides Claude Code-like conversational AI experience in Slack
 * 2. Dispatches tasks to GitHub-based agents (triage, code, QA, etc.)
 * 3. Receives status updates from agent workflows and posts to Slack
 * 4. Helps humans monitor and intervene when workflows have issues
 *
 * The actual agents (triage, code, QA, devops, etc.) continue to work
 * via GitHub Actions - this bot is the human collaboration layer.
 */

import bolt from '@slack/bolt';
const { App, LogLevel } = bolt;
import slackWebApi from '@slack/web-api';
const { WebClient } = slackWebApi;
import express from 'express';
import { config, validateConfig } from './config.js';
import { registerEventHandlers } from './handlers/slack-events.js';
import { createWebhookRouter } from './handlers/webhook-handler.js';
import { executeWithClaudeCode } from './integrations/claude-code.js';
import logger from './utils/logger.js';
import sessionManager from './state/session-manager.js';
import { setupRepository, getRepoPath } from './utils/repo-manager.js';

// Store repo path globally for use in sessions
let repoPath = process.cwd();

/**
 * Get the repository path for Claude Code sessions
 */
export function getWorkingDirectory(): string {
  return repoPath;
}

/**
 * Initialize and start the Slack bot
 */
async function main(): Promise<void> {
  logger.info('Starting Claude Software Factory Slack Bot...');

  // Clone/update the repository for git operations
  const repoSetup = await setupRepository();
  if (repoSetup.success) {
    repoPath = repoSetup.path;
    logger.info('Repository ready for git operations', { path: repoPath });
  } else {
    logger.warn('Repository not available - git operations limited', { error: repoSetup.error });
  }

  // Validate configuration
  const configErrors = validateConfig();
  if (configErrors.length > 0) {
    logger.error('Configuration errors:', { errors: configErrors });
    process.exit(1);
  }

  // Create Slack app with error handling
  const app = new App({
    token: config.slack.botToken,
    signingSecret: config.slack.signingSecret,
    appToken: config.slack.appToken,
    socketMode: true,
    logLevel: config.logLevel === 'debug' ? LogLevel.DEBUG : LogLevel.INFO,
  });

  // Handle Slack app errors to prevent crashes
  app.error(async (error) => {
    logger.error('Slack app error', {
      message: error.message,
      code: (error as any).code,
      stack: error.stack,
    });
    // Don't crash - just log the error
  });

  // Create Slack web client for webhook handler
  const slackClient = new WebClient(config.slack.botToken);

  // Register Slack event handlers
  registerEventHandlers(app);

  // Create Express app for webhooks
  const expressApp = express();
  expressApp.use(express.json());

  // Mount webhook router
  const webhookRouter = createWebhookRouter(slackClient);
  expressApp.use('/webhooks', webhookRouter);

  // Health check on root and /health
  const healthResponse = (req: express.Request, res: express.Response) => {
    res.json({
      service: 'claude-software-factory-slack-bot',
      status: 'running',
      version: '1.0.0',
      timestamp: new Date().toISOString(),
    });
  };
  expressApp.get('/', healthResponse);
  expressApp.get('/health', healthResponse);

  // Test endpoint for Claude Code SDK debugging
  // POST /test-claude-code { "prompt": "list files" }
  // Protected by a simple secret check
  expressApp.post('/test-claude-code', async (req, res) => {
    const testSecret = req.headers['x-test-secret'];
    if (testSecret !== config.server.webhookSecret) {
      res.status(401).json({ error: 'Unauthorized' });
      return;
    }

    const { prompt } = req.body;
    if (!prompt) {
      res.status(400).json({ error: 'Missing prompt' });
      return;
    }

    logger.info('Test endpoint called', { prompt: prompt.substring(0, 50) });

    try {
      const result = await executeWithClaudeCode(
        prompt,
        'test-user',
        'test-thread',
        { workingDirectory: process.cwd() }
      );
      res.json({
        success: !result.error,
        content: result.content,
        toolsUsed: result.toolsUsed,
        error: result.error,
      });
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      logger.error('Test endpoint error', { error: errorMessage });
      res.status(500).json({ error: errorMessage });
    }
  });

  // Start webhook server - use PORT from Railway, fallback to webhookPort
  const port = process.env.PORT || config.server.webhookPort;
  const webhookServer = expressApp.listen(port, () => {
    logger.info(`Webhook server listening on port ${port}`);
  });

  // Start Slack app in socket mode
  await app.start();
  logger.info('Slack bot started in socket mode');

  // Log startup info
  logger.info('Claude Software Factory Slack Bot is ready!', {
    webhookPort: config.server.webhookPort,
    githubRepo: config.github.repository,
    hasAnthropicKey: !!config.anthropic.apiKey,
  });

  // Cleanup on shutdown
  const shutdown = async () => {
    logger.info('Shutting down...');

    // Close webhook server
    webhookServer.close();

    // Stop Slack app
    await app.stop();

    // Final cleanup
    sessionManager.cleanup();

    logger.info('Shutdown complete');
    process.exit(0);
  };

  process.on('SIGTERM', shutdown);
  process.on('SIGINT', shutdown);
}

// Global error handlers to prevent crashes from socket-mode edge cases
process.on('uncaughtException', (error) => {
  logger.error('Uncaught exception', {
    message: error.message,
    stack: error.stack,
  });
  // Don't exit - the socket-mode client will reconnect
  // Only exit on truly fatal errors
  if (error.message.includes('EADDRINUSE') || error.message.includes('EACCES')) {
    process.exit(1);
  }
});

process.on('unhandledRejection', (reason, promise) => {
  logger.error('Unhandled rejection', {
    reason: reason instanceof Error ? reason.message : String(reason),
    stack: reason instanceof Error ? reason.stack : undefined,
  });
  // Don't exit - let the app continue
});

// Run the bot
main().catch((error) => {
  logger.error('Fatal error starting bot', { error });
  process.exit(1);
});
