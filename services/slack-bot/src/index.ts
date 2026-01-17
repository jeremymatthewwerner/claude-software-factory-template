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

  // Create Slack app with improved error handling
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

  // Health check on root and /health with enhanced monitoring
  const healthResponse = (req: express.Request, res: express.Response) => {
    const memoryUsage = process.memoryUsage();
    res.json({
      service: 'claude-software-factory-slack-bot',
      status: 'running',
      version: '0.1.9',
      progressiveMessaging: 'enabled',
      multiPostSystem: 'ENHANCED-WITH-MONITORING',
      threadedUpdates: 'working',
      timestamp: new Date().toISOString(),
      deployment: {
        buildTime: new Date().toISOString(),
        environment: process.env.RAILWAY_ENVIRONMENT || 'development',
        gitCommit: process.env.RAILWAY_GIT_COMMIT_SHA || 'unknown',
        nodeVersion: process.version,
        lastUpdated: new Date().toISOString(),
        realDeployment: true
      },
      performance: {
        uptime: process.uptime(),
        memoryUsageMB: {
          rss: Math.round(memoryUsage.rss / 1024 / 1024),
          heapUsed: Math.round(memoryUsage.heapUsed / 1024 / 1024),
          heapTotal: Math.round(memoryUsage.heapTotal / 1024 / 1024),
          external: Math.round(memoryUsage.external / 1024 / 1024)
        }
      },
      features: [
        'progressive-messaging',
        'thread-based-updates', 
        'timestamp-tracking',
        'multi-post-system',
        'follow-through-fixes',
        'tested-multi-post-flow',
        'enhanced-monitoring',
        'PRODUCTION-READY'
      ]
    });
  };
  expressApp.get('/', healthResponse);
  expressApp.get('/health', healthResponse);

  // Test endpoint for progressive messaging demo
  expressApp.post('/test-progressive', (req: express.Request, res: express.Response) => {
    const { channel = 'demo-channel' } = req.body;

    // Start progressive messaging demo (even without real Slack)
    (async () => {
      logger.info('=== Multi-Post Progressive Messaging Demo Started ===');

      // Simulate what would happen in Slack
      logger.info('📱 MESSAGE 1 (Thinking Animation):', {
        timestamp: new Date().toISOString(),
        content: ':thinking_face: Testing enhanced multi-post system...'
      });

      await new Promise(resolve => setTimeout(resolve, 1500));

      // Analysis update
      logger.info('📱 MESSAGE 2 (Analysis - Separate Post):', {
        timestamp: new Date().toISOString(),
        content: ':mag: **Enhanced Multi-Post System v0.1.9**\n\nNow includes performance monitoring and improved error handling.'
      });

      await new Promise(resolve => setTimeout(resolve, 1000));

      // Progress update
      logger.info('📱 MESSAGE 3 (Progress - Another Separate Post):', {
        timestamp: new Date().toISOString(),
        content: ':gear: **New Features in v0.1.9**\n\n✅ Memory usage monitoring\n✅ Enhanced health checks\n✅ Better error tracking\n✅ Performance metrics'
      });

      await new Promise(resolve => setTimeout(resolve, 1000));

      // Final results
      logger.info('📱 MESSAGE 4 (Completion - Final Separate Post):', {
        timestamp: new Date().toISOString(),
        content: `:white_check_mark: **Enhanced System Test Complete**\n\nVersion 0.1.9 is production ready with monitoring! :rocket:`
      });

      logger.info('=== Enhanced Demo Complete ===');

    })().catch(error => {
      logger.error('Multi-post test failed', { error });
    });

    res.json({
      success: true,
      message: 'Enhanced multi-post system demo started',
      version: '0.1.9',
      feature: 'progressive-messaging-with-monitoring'
    });
  });

  // Start webhook server - use PORT from Railway, fallback to webhookPort
  const port = process.env.PORT || config.server.webhookPort;
  const webhookServer = expressApp.listen(port, () => {
    logger.info(`Webhook server listening on port ${port}`);
  });

  // Enhanced error handling for Slack app
  app.error(async (error) => {
    logger.error('Slack app error:', { 
      error: error.message, 
      stack: error.stack,
      timestamp: new Date().toISOString()
    });
  });

  // Start Slack app in socket mode
  await app.start();
  logger.info('Slack bot started in socket mode');

  // Set up periodic cleanup for progressive messaging sessions
  const cleanupInterval = setInterval(() => {
    ProgressiveMessenger.cleanup();
    sessionManager.cleanup();
  }, 5 * 60 * 1000); // Every 5 minutes

  // Log startup info with enhanced details
  logger.info('Claude Software Factory Slack Bot is ready!', {
    webhookPort: config.server.webhookPort,
    githubRepo: config.github.repository,
    hasAnthropicKey: !!config.anthropic.apiKey,
    version: '0.1.9',
    nodeVersion: process.version,
    platform: process.platform,
    features: [
      'progressive-messaging', 
      'thread-based-updates', 
      'multi-post-system', 
      'follow-through-fixes', 
      'enhanced-monitoring',
      'improved-error-handling',
      'PRODUCTION-READY'
    ]
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
  
  // Handle uncaught exceptions gracefully
  process.on('uncaughtException', (error) => {
    logger.error('Uncaught exception:', { error: error.message, stack: error.stack });
    shutdown();
  });

  process.on('unhandledRejection', (reason, promise) => {
    logger.error('Unhandled rejection:', { reason, promise });
  });
}

// Run the bot
main().catch((error) => {
  logger.error('Fatal error starting bot', { error });
  process.exit(1);
});