/**
 * Webhook handler for agent status updates
 *
 * GitHub workflows call this endpoint to post status updates to Slack threads
 */

import express from 'express';
import type { WebClient } from '@slack/web-api';
import type { AgentStatusPayload, AgentStatus } from '../types.js';
import sessionManager from '../state/session-manager.js';
import { markdownToSlack } from '../utils/markdown-to-slack.js';
import logger from '../utils/logger.js';
import { config } from '../config.js';

/**
 * Create webhook router
 */
export function createWebhookRouter(slackClient: WebClient): express.Router {
  const router = express.Router();

  // Health check endpoint
  router.get('/health', (req: express.Request, res: express.Response) => {
    res.json({
      status: 'ok',
      timestamp: new Date().toISOString(),
      service: 'slack-bot',
    });
  });

  // Agent status update endpoint
  router.post('/agent-status', async (req: express.Request, res: express.Response) => {
    try {
      // Verify webhook secret
      const authHeader = req.headers.authorization;
      if (config.webhookSecret && authHeader !== `Bearer ${config.webhookSecret}`) {
        logger.warn('Invalid webhook secret');
        res.status(401).json({ error: 'Unauthorized' });
        return;
      }

      const payload = req.body as AgentStatusPayload;

      // Validate required fields
      if (!payload.agent || !payload.status || !payload.slackChannelId || !payload.slackThreadTs) {
        res.status(400).json({ error: 'Missing required fields' });
        return;
      }

      logger.info('Received agent status update', {
        agent: payload.agent,
        status: payload.status,
        issueNumber: payload.issueNumber,
      });

      // Format and send message to Slack
      const message = formatStatusMessage(payload);

      await slackClient.chat.postMessage({
        channel: payload.slackChannelId,
        thread_ts: payload.slackThreadTs,
        text: message,
        unfurl_links: false,
      });

      // Update session if there's an issue number
      if (payload.issueNumber) {
        const session = sessionManager.get(payload.slackChannelId, payload.slackThreadTs);
        if (session) {
          sessionManager.linkIssue(payload.slackChannelId, payload.slackThreadTs, payload.issueNumber);

          if (payload.prNumber) {
            sessionManager.linkPR(payload.slackChannelId, payload.slackThreadTs, payload.prNumber);
          }
        }
      }

      res.json({ success: true });
    } catch (error) {
      logger.error('Error processing agent status webhook', { error });
      res.status(500).json({ error: 'Internal server error' });
    }
  });

  // CI status update endpoint
  router.post('/ci-status', async (req: express.Request, res: express.Response) => {
    try {
      const authHeader = req.headers.authorization;
      if (config.webhookSecret && authHeader !== `Bearer ${config.webhookSecret}`) {
        res.status(401).json({ error: 'Unauthorized' });
        return;
      }

      const { prNumber, status, workflowName, runUrl, slackChannelId, slackThreadTs } = req.body;

      if (!prNumber || !status || !slackChannelId || !slackThreadTs) {
        res.status(400).json({ error: 'Missing required fields' });
        return;
      }

      const emoji = status === 'success' ? '✅' : status === 'failure' ? '❌' : '⏳';
      const message = `${emoji} *CI ${status.toUpperCase()}* for PR #${prNumber}\n` +
        (workflowName ? `Workflow: ${workflowName}\n` : '') +
        (runUrl ? `<${runUrl}|View Run>` : '');

      await slackClient.chat.postMessage({
        channel: slackChannelId,
        thread_ts: slackThreadTs,
        text: message,
        unfurl_links: false,
      });

      res.json({ success: true });
    } catch (error) {
      logger.error('Error processing CI status webhook', { error });
      res.status(500).json({ error: 'Internal server error' });
    }
  });

  // Session info endpoint (for debugging)
  router.get('/session/:channelId/:threadTs', (req: express.Request, res: express.Response) => {
    const { channelId, threadTs } = req.params;
    const session = sessionManager.get(channelId, threadTs);

    if (!session) {
      res.status(404).json({ error: 'Session not found' });
      return;
    }

    res.json({
      channelId: session.channelId,
      threadTs: session.threadTs,
      status: session.status,
      linkedIssue: session.linkedIssue,
      linkedPR: session.linkedPR,
      activeAgent: session.activeAgent,
      messageCount: session.conversationHistory.length,
      createdAt: session.createdAt,
      updatedAt: session.updatedAt,
    });
  });

  // Stats endpoint
  router.get('/stats', (req: express.Request, res: express.Response) => {
    const stats = sessionManager.getStats();
    res.json({
      ...stats,
      timestamp: new Date().toISOString(),
    });
  });

  return router;
}

/**
 * Format status message for Slack
 */
function formatStatusMessage(payload: AgentStatusPayload): string {
  const emoji = getStatusEmoji(payload.status);
  const agentName = formatAgentName(payload.agent);

  const parts: string[] = [
    `${emoji} *${agentName}* - ${formatStatus(payload.status)}`,
  ];

  if (payload.message) {
    parts.push(markdownToSlack(payload.message));
  }

  if (payload.issueNumber) {
    parts.push(`Issue: #${payload.issueNumber}`);
  }

  if (payload.prNumber) {
    parts.push(`PR: #${payload.prNumber}`);
  }

  if (payload.links) {
    const linkParts: string[] = [];
    if (payload.links.issue) {
      linkParts.push(`<${payload.links.issue}|View Issue>`);
    }
    if (payload.links.pr) {
      linkParts.push(`<${payload.links.pr}|View PR>`);
    }
    if (payload.links.run) {
      linkParts.push(`<${payload.links.run}|View Run>`);
    }
    if (linkParts.length > 0) {
      parts.push(linkParts.join(' | '));
    }
  }

  return parts.join('\n');
}

/**
 * Get emoji for status
 */
function getStatusEmoji(status: AgentStatus): string {
  switch (status) {
    case 'started':
      return '🚀';
    case 'progress':
      return '⏳';
    case 'completed':
      return '✅';
    case 'failed':
      return '❌';
    default:
      return '📋';
  }
}

/**
 * Format agent name for display
 */
function formatAgentName(agent: string): string {
  const names: Record<string, string> = {
    'triage': 'Triage Agent',
    'code': 'Code Agent',
    'qa': 'QA Agent',
    'devops': 'DevOps Agent',
    'release': 'Release Engineer',
    'principal-engineer': 'Principal Engineer',
    'marketing': 'Marketing Agent',
    'ci-monitor': 'CI Monitor',
  };
  return names[agent] || agent;
}

/**
 * Format status for display
 */
function formatStatus(status: AgentStatus): string {
  switch (status) {
    case 'started':
      return 'Started working';
    case 'progress':
      return 'In progress';
    case 'completed':
      return 'Completed';
    case 'failed':
      return 'Failed';
    default:
      return status;
  }
}

export default {
  createWebhookRouter,
};
