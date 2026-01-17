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
import logger from './utils/logger.js';
import sessionManager from './state/session-manager.js';
import ProgressiveMessenger from './utils/progressive-messenger.js';

/**
 * Initialize and start the Slack bot
 */
async function main(): Promise<void> {
  logger.info('Starting Claude Software Factory Slack Bot...');

  // Validate configuration
  const configErrors = validateConfig();
  if (configErrors.length > 0) {
    logger.error('Configuration errors:', { errors: configErrors });
    process.exit(1);
  }

  // Create Slack app
  const app = new App({
    token: config.slack.botToken,
    signingSecret: config.slack.signingSecret,
    appToken: config.slack.appToken,
    socketMode: true,
    logLevel: config.logLevel === 'debug' ? LogLevel.DEBUG : LogLevel.INFO,
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
      testDeployment: 'TESTING-DEPLOYMENT-2026-01-17',
      status: 'running',
      version: '0.1.2',
      timestamp: new Date().toISOString(),
      deployment: {
        buildTime: new Date().toISOString(),
        environment: process.env.RAILWAY_ENVIRONMENT || 'development',
        gitCommit: process.env.RAILWAY_GIT_COMMIT_SHA || 'unknown',
        nodeVersion: process.version,
      },
      uptime: process.uptime(),
    });
  };
  expressApp.get('/', healthResponse);
  expressApp.get('/health', healthResponse);

  // Test endpoint for progressive messaging demo
  expressApp.post('/test-progressive', (req: express.Request, res: express.Response) => {
    const { channel } = req.body;

    if (!channel) {
      return res.status(400).json({ error: 'Missing channel ID' });
    }

    // Start progressive messaging demo
    (async () => {
      // Use a fake thread timestamp for demo
      const threadTs = Date.now().toString();
      const sessionKey = await ProgressiveMessenger.startSession(
        channel,
        threadTs,
        slackClient,
        'Testing enhanced messaging system...'
      );

      await new Promise(resolve => setTimeout(resolve, 2000));

      // Analysis update
      await ProgressiveMessenger.postUpdate(sessionKey, {
        id: `analysis-${Date.now()}`,
        type: 'analysis',
        content: ':mag: **Analysis Complete**\n\nI\'ll demonstrate the progressive messaging system with visual separation and timestamps.'
      });
      await new Promise(resolve => setTimeout(resolve, 1500));

      // Progress update
      await ProgressiveMessenger.postUpdate(sessionKey, {
        id: `progress-${Date.now()}`,
        type: 'progress',
        content: ':gear: **Processing Request**\n\nBreaking down your text into meaningful chunks for better readability...'
      });
      await new Promise(resolve => setTimeout(resolve, 2000));

      // Complete session with final results
      await ProgressiveMessenger.completeSession(
        sessionKey,
        `:white_check_mark: **Results**\n\n${'═'.repeat(50)}\n\n:sparkles: **Enhanced Visual Formatting Active!**\n\n• Progressive updates with timestamps\n• Visual separators between content blocks\n• Color-coded emojis for different update types\n• Forwardable message chunks\n• Auto-clearing thinking animations\n\n${'═'.repeat(50)}\n\n*This completes the progressive messaging demo*`,
        { success: true, summary: 'Progressive messaging demo completed' }
      );

    })().catch(error => {
      logger.error('Progressive messaging test failed', { error });
    });

    res.json({ success: true, message: 'Progressive messaging demo started' });
  });

  // Start webhook server - use PORT from Railway, fallback to webhookPort
  const port = process.env.PORT || config.server.webhookPort;
  const webhookServer = expressApp.listen(port, () => {
    logger.info(`Webhook server listening on port ${port}`);
  });

  // Start Slack app in socket mode
  await app.start();
  logger.info('Slack bot started in socket mode');

  // Set up periodic cleanup for progressive messaging sessions
  const cleanupInterval = setInterval(() => {
    ProgressiveMessenger.cleanup();
    sessionManager.cleanup();
  }, 5 * 60 * 1000); // Every 5 minutes

  // Log startup info
  logger.info('Claude Software Factory Slack Bot is ready!', {
    webhookPort: config.server.webhookPort,
    githubRepo: config.github.repository,
    hasAnthropicKey: !!config.anthropic.apiKey,
  });

  // Cleanup on shutdown
  const shutdown = async () => {
    logger.info('Shutting down...');

    // Clear intervals
    clearInterval(cleanupInterval);

    // Close webhook server
    webhookServer.close();

    // Stop Slack app
    await app.stop();

    // Final cleanup
    ProgressiveMessenger.cleanup();
    sessionManager.cleanup();

    logger.info('Shutdown complete');
    process.exit(0);
  };

  process.on('SIGTERM', shutdown);
  process.on('SIGINT', shutdown);
}

// Run the bot
main().catch((error) => {
  logger.error('Fatal error starting bot', { error });
  process.exit(1);
});
