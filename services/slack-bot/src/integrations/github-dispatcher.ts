/**
 * GitHub integration for dispatching tasks to agents
 */

import { config } from '../config.js';
import logger from '../utils/logger.js';
import type { AgentType, SlackSession } from '../types.js';

interface CreateIssueOptions {
  title: string;
  body: string;
  labels: string[];
  assignees?: string[];
}

interface IssueResult {
  success: boolean;
  issueNumber?: number;
  issueUrl?: string;
  error?: string;
}

/**
 * Create a GitHub issue to trigger an agent
 */
export async function createIssue(options: CreateIssueOptions): Promise<IssueResult> {
  if (!config.github.token || !config.github.repository) {
    logger.error('GitHub not configured', {
      hasToken: !!config.github.token,
      hasRepo: !!config.github.repository,
    });
    return {
      success: false,
      error: 'GitHub integration is not configured. Please set GITHUB_TOKEN and GITHUB_REPOSITORY.',
    };
  }

  const [owner, repo] = config.github.repository.split('/');

  try {
    const response = await fetch(
      `https://api.github.com/repos/${owner}/${repo}/issues`,
      {
        method: 'POST',
        headers: {
          Authorization: `token ${config.github.token}`,
          Accept: 'application/vnd.github.v3+json',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          title: options.title,
          body: options.body,
          labels: options.labels,
          assignees: options.assignees,
        }),
      }
    );

    if (!response.ok) {
      const error = await response.text();
      logger.error('Failed to create GitHub issue', { status: response.status, error });
      return {
        success: false,
        error: `GitHub API error: ${response.status}`,
      };
    }

    const issue = await response.json() as { number: number; html_url: string };

    logger.info('Created GitHub issue', {
      issueNumber: issue.number,
      labels: options.labels,
    });

    return {
      success: true,
      issueNumber: issue.number,
      issueUrl: issue.html_url,
    };
  } catch (error) {
    logger.error('Error creating GitHub issue', { error });
    return {
      success: false,
      error: 'Failed to connect to GitHub API',
    };
  }
}

/**
 * Dispatch a task to an agent
 */
export async function dispatchToAgent(
  agent: AgentType,
  task: string,
  session: SlackSession,
  additionalContext?: string
): Promise<IssueResult> {
  // Build the issue body with Slack context
  const slackContext = `## Slack Context

- **Channel:** <#${session.channelId}>
- **Thread:** ${session.threadTs}
- **Requested by:** <@${session.userId}>
- **Working Directory:** ${session.workingDirectory}

## Request

${task}`;

  const fullBody = additionalContext
    ? `${slackContext}\n\n## Additional Context\n\n${additionalContext}`
    : slackContext;

  // Determine labels based on agent type
  const labels = getLabelsForAgent(agent);

  // Create the issue title
  const title = generateIssueTitle(agent, task);

  const result = await createIssue({
    title,
    body: fullBody,
    labels,
  });

  if (result.success && result.issueNumber) {
    // Add ai-ready label in a separate call to trigger the agent
    await addLabel(result.issueNumber, 'ai-ready');
  }

  return result;
}

/**
 * Get appropriate labels for an agent type
 */
function getLabelsForAgent(agent: AgentType): string[] {
  switch (agent) {
    case 'triage':
      return ['needs-triage'];
    case 'code':
      return ['bug']; // Will get ai-ready added separately
    case 'qa':
      return ['qa-agent', 'enhancement'];
    case 'devops':
      return ['production-incident', 'priority-high'];
    case 'release':
      return ['enhancement'];
    case 'principal-engineer':
      return ['needs-principal-engineer'];
    default:
      return ['enhancement'];
  }
}

/**
 * Generate an issue title based on agent and task
 */
function generateIssueTitle(agent: AgentType, task: string): string {
  // Truncate task for title
  const shortTask = task.length > 60 ? task.substring(0, 57) + '...' : task;

  switch (agent) {
    case 'code':
      return `fix: ${shortTask}`;
    case 'qa':
      return `test: ${shortTask}`;
    case 'devops':
      return `ops: ${shortTask}`;
    case 'release':
      return `release: ${shortTask}`;
    default:
      return shortTask;
  }
}

/**
 * Add a label to an issue
 */
async function addLabel(issueNumber: number, label: string): Promise<boolean> {
  if (!config.github.token || !config.github.repository) {
    return false;
  }

  const [owner, repo] = config.github.repository.split('/');

  try {
    const response = await fetch(
      `https://api.github.com/repos/${owner}/${repo}/issues/${issueNumber}/labels`,
      {
        method: 'POST',
        headers: {
          Authorization: `token ${config.github.token}`,
          Accept: 'application/vnd.github.v3+json',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ labels: [label] }),
      }
    );

    return response.ok;
  } catch (error) {
    logger.error('Error adding label to issue', { error, issueNumber, label });
    return false;
  }
}

/**
 * Get issue status
 */
export async function getIssueStatus(issueNumber: number): Promise<{
  state: string;
  labels: string[];
  linkedPR?: number;
} | null> {
  if (!config.github.token || !config.github.repository) {
    return null;
  }

  const [owner, repo] = config.github.repository.split('/');

  try {
    const response = await fetch(
      `https://api.github.com/repos/${owner}/${repo}/issues/${issueNumber}`,
      {
        headers: {
          Authorization: `token ${config.github.token}`,
          Accept: 'application/vnd.github.v3+json',
        },
      }
    );

    if (!response.ok) {
      return null;
    }

    const issue = await response.json() as {
      state: string;
      labels: Array<{ name: string }>;
      pull_request?: { number: number };
    };

    return {
      state: issue.state,
      labels: issue.labels.map((l) => l.name),
      linkedPR: issue.pull_request?.number,
    };
  } catch (error) {
    logger.error('Error getting issue status', { error, issueNumber });
    return null;
  }
}

/**
 * Add a comment to an issue
 */
export async function addIssueComment(
  issueNumber: number,
  comment: string
): Promise<boolean> {
  if (!config.github.token || !config.github.repository) {
    return false;
  }

  const [owner, repo] = config.github.repository.split('/');

  try {
    const response = await fetch(
      `https://api.github.com/repos/${owner}/${repo}/issues/${issueNumber}/comments`,
      {
        method: 'POST',
        headers: {
          Authorization: `token ${config.github.token}`,
          Accept: 'application/vnd.github.v3+json',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ body: comment }),
      }
    );

    return response.ok;
  } catch (error) {
    logger.error('Error adding comment to issue', { error, issueNumber });
    return false;
  }
}

export default {
  createIssue,
  dispatchToAgent,
  getIssueStatus,
  addIssueComment,
};
