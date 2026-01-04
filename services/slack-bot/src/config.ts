/**
 * Configuration for the Claude Factory Slack Bot
 */

import dotenv from 'dotenv';

dotenv.config();

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}

function optionalEnv(name: string, defaultValue: string = ''): string {
  return process.env[name] || defaultValue;
}

export const config = {
  // Slack Configuration
  slack: {
    botToken: requireEnv('SLACK_BOT_TOKEN'),
    appToken: requireEnv('SLACK_APP_TOKEN'),
    signingSecret: requireEnv('SLACK_SIGNING_SECRET'),
  },

  // Anthropic Configuration
  anthropic: {
    apiKey: requireEnv('ANTHROPIC_API_KEY'),
    model: optionalEnv('CLAUDE_MODEL', 'claude-sonnet-4-20250514'),
    maxTokens: parseInt(optionalEnv('CLAUDE_MAX_TOKENS', '8192'), 10),
  },

  // GitHub Configuration
  github: {
    token: optionalEnv('GITHUB_TOKEN'),
    repository: optionalEnv('GITHUB_REPOSITORY'),
    owner: optionalEnv('GITHUB_OWNER'),
  },

  // Server Configuration
  server: {
    port: parseInt(optionalEnv('PORT', '3000'), 10),
    webhookSecret: optionalEnv('WEBHOOK_SECRET'),
  },

  // Repository Configuration
  repo: {
    basePath: optionalEnv('REPO_BASE_PATH', '/repos'),
    defaultRepo: optionalEnv('DEFAULT_REPO', ''),
  },

  // Feature Flags
  features: {
    agentDispatch: optionalEnv('ENABLE_AGENT_DISPATCH', 'true') === 'true',
    fileUploads: optionalEnv('ENABLE_FILE_UPLOADS', 'true') === 'true',
    interactiveButtons: optionalEnv('ENABLE_INTERACTIVE_BUTTONS', 'true') === 'true',
  },

  // Rate Limiting
  rateLimit: {
    maxRequestsPerMinute: parseInt(optionalEnv('RATE_LIMIT_PER_MINUTE', '30'), 10),
    maxTokensPerHour: parseInt(optionalEnv('RATE_LIMIT_TOKENS_PER_HOUR', '100000'), 10),
  },
} as const;

export type Config = typeof config;
