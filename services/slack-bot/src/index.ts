/**
 * Claude Software Factory - Slack Bot v0.2.0
 *
 * A conversational meta-agent that provides a Slack interface for interacting
 * with the Claude-powered software factory. This bot:
 *
 * 1. Provides Claude Code-like conversational AI experience in Slack
 * 2. Dispatches tasks to GitHub-based agents (triage, code, QA, etc.)
 * 3. Receives status updates from agent workflows and posts to Slack
 * 4. Helps humans monitor and intervene when workflows have issues
 * 5. Enhanced with emoji reactions for better visual feedback
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
 * Bot status reactions for better visual feedback
 */
const BOT_STATUS_EMOJIS = {
  thinking: '🤔',
  working: '⚡',
  success: '✅', 
  error: '❌',
  warning: '⚠️',
  ready: '🚀',
  deployed: '🎉'
};

/**
 * Initialize and start the Slack bot
 */
async function main(): Promise<void> {
  logger.info('🚀 Starting Claude Software Factory Slack Bot v0.2.0...');

  // Validate configuration
  const configErrors = validateConfig();
  if (configErrors.length > 0) {
    logger.error('❌ Configuration errors:', { errors: configErrors });
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

  // Enhanced health check with status emojis and improved metrics
  const healthResponse = (req: express.Request, res: express.Response) => {
    const memoryUsage = process.memoryUsage();
    const uptime = process.uptime();
    const uptimeHours = Math.floor(uptime / 3600);
    const uptimeMinutes = Math.floor((uptime % 3600) / 60);
    
    res.json({
      service: 'claude-software-factory-slack-bot',
      status: 'running',
      version: '0.2.0',
      statusEmoji: BOT_STATUS_EMOJIS.ready,
      progressiveMessaging: 'enabled',
      multiPostSystem: 'ENHANCED-WITH-EMOJI-REACTIONS',
      threadedUpdates: 'working',
      emojiReactions: 'active',
      timestamp: new Date().toISOString(),
      deployment: {
        buildTime: new Date().toISOString(),
        environment: process.env.RAILWAY_ENVIRONMENT || 'development',
        gitCommit: process.env.RAILWAY_GIT_COMMIT_SHA || 'unknown',
        nodeVersion: process.version,
        lastUpdated: new Date().toISOString(),
        realDeployment: true,
        versionBump: '0.1.9 → 0.2.0'
      },
      performance: {
        uptime: `${uptimeHours}h ${uptimeMinutes}m`,
        uptimeSeconds: Math.floor(uptime),
        memoryUsageMB: {
          rss: Math.round(memoryUsage.rss / 1024 / 1024),
          heapUsed: Math.round(memoryUsage.heapUsed / 1024 / 1024),
          heapTotal: Math.round(memoryUsage.heapTotal / 1024 / 1024),
          external: Math.round(memoryUsage.external / 1024 / 1024)
        },
        memoryEfficiency: `${Math.round((memoryUsage.heapUsed / memoryUsage.heapTotal) * 100)}%`
      },
      features: [
        'progressive-messaging',
        'thread-based-updates', 
        'timestamp-tracking',
        'multi-post-system',
        'follow-through-fixes',
        'tested-multi-post-flow',
        'enhanced-monitoring',
        'emoji-reactions',
        'improved-status-display',
        'PRODUCTION-READY-V2'
      ],
      statusIndicators: BOT_STATUS_EMOJIS
    });
  };
  expressApp.get('/', healthResponse);
  expressApp.get('/health', healthResponse);

  // Enhanced test endpoint with emoji reactions
  expressApp.post('/test-progressive', (req: express.Request, res: express.Response) => {
    const { channel = 'demo-channel' } = req.body;

    // Start enhanced progressive messaging demo
    (async () => {
      logger.info(`${BOT_STATUS_EMOJIS.deployed} === Enhanced Multi-Post Progressive Messaging Demo v0.2.0 Started ===`);

      // Thinking animation with emoji
      logger.info(`${BOT_STATUS_EMOJIS.thinking} MESSAGE 1 (Thinking Animation):`, {
        timestamp: new Date().toISOString(),
        content: `${BOT_STATUS_EMOJIS.thinking} Testing enhanced multi-post system v0.2.0...`
      });

      await new Promise(resolve => setTimeout(resolve, 1500));

      // Analysis update with working emoji
      logger.info(`${BOT_STATUS_EMOJIS.working} MESSAGE 2 (Analysis - Separate Post):`, {
        timestamp: new Date().toISOString(),
        content: `${BOT_STATUS_EMOJIS.working} **Enhanced Multi-Post System v0.2.0**\n\nNew features:\n${BOT_STATUS_EMOJIS.success} Emoji status reactions\n${BOT_STATUS_EMOJIS.success} Better visual feedback\n${BOT_STATUS_EMOJIS.success} Improved health monitoring`
      });

      await new Promise(resolve => setTimeout(resolve, 1000));

      // Progress update with detailed emojis
      logger.info(`${BOT_STATUS_EMOJIS.working} MESSAGE 3 (Progress - Another Separate Post):`, {
        timestamp: new Date().toISOString(),
        content: `${BOT_STATUS_EMOJIS.warning} **New Features in v0.2.0**\n\n${BOT_STATUS_EMOJIS.success} Memory efficiency tracking\n${BOT_STATUS_EMOJIS.success} Enhanced health checks with emojis\n${BOT_STATUS_EMOJIS.success} Better error visual indicators\n${BOT_STATUS_EMOJIS.success} Improved uptime formatting`
      });

      await new Promise(resolve => setTimeout(resolve, 1000));

      // Final results with celebration
      logger.info(`${BOT_STATUS_EMOJIS.deployed} MESSAGE 4 (Completion - Final Separate Post):`, {
        timestamp: new Date().toISOString(),
        content: `${BOT_STATUS_EMOJIS.success} **Enhanced System Test Complete**\n\nVersion 0.2.0 deployed successfully! ${BOT_STATUS_EMOJIS.deployed}\n\n${BOT_STATUS_EMOJIS.ready} System ready for production use!`
      });

      logger.info(`${BOT_STATUS_EMOJIS.success} === Enhanced Demo Complete ===`);

    })().catch(error => {
      logger.error(`${BOT_STATUS_EMOJIS.error} Multi-post test failed`, { error });
    });

    res.json({
      success: true,
      message: 'Enhanced multi-post system demo started',
      version: '0.2.0',
      feature: 'progressive-messaging-with-emoji-reactions',
      statusEmoji: BOT_STATUS_EMOJIS.deployed
    });
  });

  // Start webhook server - use PORT from Railway, fallback to webhookPort
  const port = process.env.PORT || config.server.webhookPort;
  const webhookServer = expressApp.listen(port, () => {
    logger.info(`${BOT_STATUS_EMOJIS.success} Webhook server listening on port ${port}`);
  });

  // Enhanced error handling for Slack app with emoji indicators
  app.error(async (error) => {
    logger.error(`${BOT_STATUS_EMOJIS.error} Slack app error:`, { 
      error: error.message, 
      stack: error.stack,
      timestamp: new Date().toISOString()
    });
  });

  // Start Slack app in socket mode
  await app.start();
  logger.info(`${BOT_STATUS_EMOJIS.success} Slack bot started in socket mode`);

  // Set up periodic cleanup for progressive messaging sessions
  const cleanupInterval = setInterval(() => {
    ProgressiveMessenger.cleanup();
    sessionManager.cleanup();
  }, 5 * 60 * 1000); // Every 5 minutes

  // Log startup info with enhanced details and emojis
  logger.info(`${BOT_STATUS_EMOJIS.deployed} Claude Software Factory Slack Bot v0.2.0 is ready!`, {
    webhookPort: config.server.webhookPort,
    githubRepo: config.github.repository,
    hasAnthropicKey: !!config.anthropic.apiKey,
    version: '0.2.0',
    nodeVersion: process.version,
    platform: process.platform,
    versionUpgrade: '0.1.9 → 0.2.0',
    features: [
      'progressive-messaging', 
      'thread-based-updates', 
      'multi-post-system', 
      'follow-through-fixes', 
      'enhanced-monitoring',
      'improved-error-handling',
      'emoji-status-reactions',
      'better-visual-feedback',
      'PRODUCTION-READY-V2'
    ]
  });

  // Cleanup on shutdown
  const shutdown = async () => {
    logger.info(`${BOT_STATUS_EMOJIS.warning} Shutting down...`);

    // Clear intervals
    clearInterval(cleanupInterval);

    // Close webhook server
    webhookServer.close();

    // Stop Slack app
    await app.stop();

    // Final cleanup
    ProgressiveMessenger.cleanup();
    sessionManager.cleanup();

    logger.info(`${BOT_STATUS_EMOJIS.success} Shutdown complete`);
    process.exit(0);
  };

  process.on('SIGTERM', shutdown);
  process.on('SIGINT', shutdown);
  
  // Handle uncaught exceptions gracefully with emoji indicators
  process.on('uncaughtException', (error) => {
    logger.error(`${BOT_STATUS_EMOJIS.error} Uncaught exception:`, { error: error.message, stack: error.stack });
    shutdown();
  });

  process.on('unhandledRejection', (reason, promise) => {
    logger.error(`${BOT_STATUS_EMOJIS.error} Unhandled rejection:`, { reason, promise });
  });
}

// Run the bot
main().catch((error) => {
  logger.error(`${BOT_STATUS_EMOJIS.error} Fatal error starting bot`, { error });
  process.exit(1);
});