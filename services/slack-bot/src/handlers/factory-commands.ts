/**
 * Factory Commands - Meta-tools for improving the software factory
 *
 * IMPORTANT: This bot's job is NOT to unblock specific issues, PRs, or actions.
 * Its job is to help engineers identify patterns, diagnose systemic issues,
 * and improve the factory workflows to be more robust, autonomous, and general.
 *
 * The factory should fix issues. This bot helps fix the factory.
 */

import { config } from '../config.js';
import logger from '../utils/logger.js';

interface GitHubIssue {
  number: number;
  title: string;
  state: string;
  labels: Array<{ name: string }>;
  created_at: string;
  updated_at: string;
  html_url: string;
  body?: string;
  assignee?: { login: string } | null;
}

interface GitHubWorkflowRun {
  id: number;
  name: string;
  status: string;
  conclusion: string | null;
  html_url: string;
  created_at: string;
  head_branch: string;
  event: string;
}

interface GitHubComment {
  body: string;
  created_at: string;
  user: { login: string };
}

const GITHUB_API = 'https://api.github.com';

/**
 * Make authenticated GitHub API request
 */
async function githubFetch<T>(endpoint: string): Promise<T> {
  const url = endpoint.startsWith('http') ? endpoint : `${GITHUB_API}${endpoint}`;
  const response = await fetch(url, {
    headers: {
      'Authorization': `Bearer ${config.github.token}`,
      'Accept': 'application/vnd.github.v3+json',
      'User-Agent': 'claude-software-factory-bot',
    },
  });

  if (!response.ok) {
    throw new Error(`GitHub API error: ${response.status} ${response.statusText}`);
  }

  return response.json() as Promise<T>;
}

/**
 * Get repository path for API calls
 */
function getRepoPath(): string {
  if (config.github.repository) {
    return config.github.repository.includes('/')
      ? config.github.repository
      : `${config.github.owner}/${config.github.repository}`;
  }
  return `${config.github.owner}/${config.github.repository}`;
}

/**
 * FACTORY STATUS - Overview of factory health with focus on systemic issues
 */
export async function getFactoryStatus(): Promise<string> {
  const repo = getRepoPath();

  try {
    // Fetch data in parallel
    const [issues, runs] = await Promise.all([
      githubFetch<GitHubIssue[]>(`/repos/${repo}/issues?state=open&per_page=100`),
      githubFetch<{ workflow_runs: GitHubWorkflowRun[] }>(`/repos/${repo}/actions/runs?per_page=20`),
    ]);

    // Categorize issues by label patterns
    const escalated = issues.filter(i =>
      i.labels.some(l => l.name === 'needs-principal-engineer' || l.name === 'needs-human')
    );
    const stuck = issues.filter(i =>
      i.labels.some(l => l.name === 'status:bot-working') &&
      new Date(i.updated_at) < new Date(Date.now() - 30 * 60 * 1000) // 30min stale
    );
    const aiReady = issues.filter(i => i.labels.some(l => l.name === 'ai-ready'));
    const byPriority = {
      p0: issues.filter(i => i.labels.some(l => l.name === 'priority-high' || l.name === 'P0')),
      p1: issues.filter(i => i.labels.some(l => l.name === 'priority-medium' || l.name === 'P1')),
      p2: issues.filter(i => i.labels.some(l => l.name === 'priority-low' || l.name === 'P2')),
    };

    // Analyze workflow runs
    const recentRuns = runs.workflow_runs || [];
    const failedRuns = recentRuns.filter(r => r.conclusion === 'failure');
    const failureRate = recentRuns.length > 0
      ? Math.round((failedRuns.length / recentRuns.length) * 100)
      : 0;

    // Identify patterns in failures
    const failuresByWorkflow: Record<string, number> = {};
    failedRuns.forEach(r => {
      failuresByWorkflow[r.name] = (failuresByWorkflow[r.name] || 0) + 1;
    });

    // Build status report focused on factory health
    const lines: string[] = [
      `*🏭 Factory Health Report*`,
      ``,
      `*Autonomy Indicators:*`,
      `• Escalated to humans: ${escalated.length} ${escalated.length > 0 ? '⚠️' : '✅'}`,
      `• Stuck agents (>30min): ${stuck.length} ${stuck.length > 0 ? '⚠️' : '✅'}`,
      `• CI failure rate: ${failureRate}% ${failureRate > 20 ? '⚠️' : '✅'}`,
      ``,
      `*Queue Status:*`,
      `• P0 (critical): ${byPriority.p0.length}`,
      `• P1 (important): ${byPriority.p1.length}`,
      `• P2 (minor): ${byPriority.p2.length}`,
      `• Awaiting agents: ${aiReady.length}`,
      ``,
    ];

    // Highlight systemic issues
    if (escalated.length > 0) {
      lines.push(`*🚨 Escalations (factory couldn't handle):*`);
      escalated.slice(0, 5).forEach(i => {
        lines.push(`• <${i.html_url}|#${i.number}> ${i.title}`);
      });
      lines.push(`_→ Each escalation is a factory bug. What pattern caused these?_`);
      lines.push(``);
    }

    if (Object.keys(failuresByWorkflow).length > 0) {
      lines.push(`*🔴 Workflow Failures (last 20 runs):*`);
      Object.entries(failuresByWorkflow)
        .sort((a, b) => b[1] - a[1])
        .forEach(([name, count]) => {
          lines.push(`• ${name}: ${count} failures`);
        });
      lines.push(`_→ Repeated failures indicate brittle workflows. Which need hardening?_`);
      lines.push(``);
    }

    if (stuck.length > 0) {
      lines.push(`*⏰ Stuck Work (agent not progressing):*`);
      stuck.slice(0, 5).forEach(i => {
        lines.push(`• <${i.html_url}|#${i.number}> ${i.title}`);
      });
      lines.push(`_→ Why did agents stall? Timeout? Missing capability?_`);
      lines.push(``);
    }

    lines.push(`*Your job:* Don't fix individual issues—fix the factory so it handles them autonomously.`);

    return lines.join('\n');
  } catch (error) {
    logger.error('Error fetching factory status', { error });
    return `❌ Error fetching factory status: ${error instanceof Error ? error.message : 'Unknown error'}`;
  }
}

/**
 * ANALYZE ISSUE - Learn from an issue to improve the factory
 */
export async function analyzeIssue(issueNumber: number): Promise<string> {
  const repo = getRepoPath();

  try {
    const [issue, comments, events] = await Promise.all([
      githubFetch<GitHubIssue>(`/repos/${repo}/issues/${issueNumber}`),
      githubFetch<GitHubComment[]>(`/repos/${repo}/issues/${issueNumber}/comments`),
      githubFetch<Array<{ event: string; created_at: string; actor?: { login: string }; label?: { name: string } }>>(
        `/repos/${repo}/issues/${issueNumber}/events`
      ),
    ]);

    const labels = issue.labels.map(l => l.name);
    const wasEscalated = labels.includes('needs-principal-engineer') || labels.includes('needs-human');
    const isResolved = issue.state === 'closed';

    // Analyze timeline
    const labelEvents = events.filter(e => e.event === 'labeled' || e.event === 'unlabeled');
    const botComments = comments.filter(c =>
      c.user.login.includes('bot') || c.user.login.includes('github-actions')
    );

    const lines: string[] = [
      `*🔍 Issue Analysis: #${issueNumber}*`,
      ``,
      `*${issue.title}*`,
      `Status: ${issue.state} | Labels: ${labels.join(', ') || 'none'}`,
      `<${issue.html_url}|View on GitHub>`,
      ``,
      `*Factory Learning Questions:*`,
    ];

    if (wasEscalated) {
      lines.push(`⚠️ *This issue was escalated.* Why couldn't the factory handle it?`);
      lines.push(`• Was it missing information?`);
      lines.push(`• Did an agent hit a capability limit?`);
      lines.push(`• Was the task too ambiguous?`);
      lines.push(`_→ Fix the factory so similar issues don't escalate._`);
      lines.push(``);
    }

    if (!isResolved && labels.includes('ai-ready')) {
      const ageHours = Math.round((Date.now() - new Date(issue.created_at).getTime()) / (1000 * 60 * 60));
      if (ageHours > 24) {
        lines.push(`⏰ *Open for ${ageHours}h with ai-ready label.* Why no progress?`);
        lines.push(`• Is an agent picking it up?`);
        lines.push(`• Is the workflow triggering correctly?`);
        lines.push(`• Is the issue missing required labels?`);
        lines.push(``);
      }
    }

    // Show agent activity
    if (botComments.length > 0) {
      lines.push(`*Agent Activity (${botComments.length} comments):*`);
      const lastComment = botComments[botComments.length - 1];
      const preview = lastComment.body.slice(0, 200).replace(/\n/g, ' ');
      lines.push(`Last update: "${preview}${lastComment.body.length > 200 ? '...' : ''}"`);
      lines.push(``);
    } else {
      lines.push(`*No agent activity found.* Check if workflows are configured correctly.`);
      lines.push(``);
    }

    // Label history for debugging workflow
    if (labelEvents.length > 0) {
      lines.push(`*Label History:*`);
      labelEvents.slice(-5).forEach(e => {
        const action = e.event === 'labeled' ? '+' : '-';
        lines.push(`• ${action}${e.label?.name} (${e.actor?.login})`);
      });
      lines.push(``);
    }

    lines.push(`*Remember:* Your goal is to improve the factory, not to fix this issue directly.`);
    lines.push(`Ask: "What change to workflows/prompts/CLAUDE.md would prevent this?"`);

    return lines.join('\n');
  } catch (error) {
    logger.error('Error analyzing issue', { error, issueNumber });
    return `❌ Error analyzing issue #${issueNumber}: ${error instanceof Error ? error.message : 'Unknown error'}`;
  }
}

/**
 * FAILURE PATTERNS - Identify systemic CI/workflow issues
 */
export async function getFailurePatterns(): Promise<string> {
  const repo = getRepoPath();

  try {
    const runs = await githubFetch<{ workflow_runs: GitHubWorkflowRun[] }>(
      `/repos/${repo}/actions/runs?per_page=50&status=failure`
    );

    const failedRuns = runs.workflow_runs || [];

    if (failedRuns.length === 0) {
      return `✅ *No recent failures!* The factory is running smoothly.\n\nKeep monitoring for patterns as issues come through.`;
    }

    // Group by workflow name
    const byWorkflow: Record<string, GitHubWorkflowRun[]> = {};
    failedRuns.forEach(run => {
      if (!byWorkflow[run.name]) byWorkflow[run.name] = [];
      byWorkflow[run.name].push(run);
    });

    // Group by branch
    const byBranch: Record<string, number> = {};
    failedRuns.forEach(run => {
      byBranch[run.head_branch] = (byBranch[run.head_branch] || 0) + 1;
    });

    // Group by trigger event
    const byEvent: Record<string, number> = {};
    failedRuns.forEach(run => {
      byEvent[run.event] = (byEvent[run.event] || 0) + 1;
    });

    const lines: string[] = [
      `*🔴 Failure Pattern Analysis (last 50 failures)*`,
      ``,
      `*By Workflow:*`,
    ];

    Object.entries(byWorkflow)
      .sort((a, b) => b[1].length - a[1].length)
      .forEach(([name, workflowRuns]) => {
        lines.push(`• *${name}*: ${workflowRuns.length} failures`);
        // Show most recent failure link
        if (workflowRuns[0]) {
          lines.push(`  <${workflowRuns[0].html_url}|View latest failure>`);
        }
      });

    lines.push(``);
    lines.push(`*By Trigger:*`);
    Object.entries(byEvent)
      .sort((a, b) => b[1] - a[1])
      .forEach(([event, count]) => {
        lines.push(`• ${event}: ${count}`);
      });

    lines.push(``);
    lines.push(`*By Branch:*`);
    Object.entries(byBranch)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5)
      .forEach(([branch, count]) => {
        lines.push(`• ${branch}: ${count}`);
      });

    lines.push(``);
    lines.push(`*Factory Improvement Questions:*`);
    lines.push(`• Are certain workflows flaky? Add retries or better error handling.`);
    lines.push(`• Failures on specific branches? Check agent branch naming.`);
    lines.push(`• Failures on certain triggers? Review workflow trigger conditions.`);
    lines.push(``);
    lines.push(`_Don't just fix the failures—make the workflows resilient._`);

    return lines.join('\n');
  } catch (error) {
    logger.error('Error fetching failure patterns', { error });
    return `❌ Error fetching failures: ${error instanceof Error ? error.message : 'Unknown error'}`;
  }
}

/**
 * AGENT PERFORMANCE - Identify which agents/workflows need improvement
 */
export async function getAgentPerformance(): Promise<string> {
  const repo = getRepoPath();

  try {
    // Get closed issues to analyze resolution patterns
    const [closedIssues, openIssues] = await Promise.all([
      githubFetch<GitHubIssue[]>(`/repos/${repo}/issues?state=closed&per_page=50`),
      githubFetch<GitHubIssue[]>(`/repos/${repo}/issues?state=open&per_page=100`),
    ]);

    // Categorize by how they were handled
    const autoResolved = closedIssues.filter(i =>
      !i.labels.some(l => l.name === 'needs-human' || l.name === 'needs-principal-engineer')
    );
    const escalatedToPE = closedIssues.filter(i =>
      i.labels.some(l => l.name === 'needs-principal-engineer')
    );
    const escalatedToHuman = closedIssues.filter(i =>
      i.labels.some(l => l.name === 'needs-human')
    );

    // Current escalations
    const currentEscalations = openIssues.filter(i =>
      i.labels.some(l => l.name === 'needs-principal-engineer' || l.name === 'needs-human')
    );

    // Calculate autonomy rate
    const totalResolved = closedIssues.length;
    const autonomyRate = totalResolved > 0
      ? Math.round((autoResolved.length / totalResolved) * 100)
      : 0;

    const lines: string[] = [
      `*🤖 Agent Performance Report*`,
      ``,
      `*Autonomy Metrics (last 50 closed issues):*`,
      `• Auto-resolved: ${autoResolved.length} (${autonomyRate}%)`,
      `• Escalated to PE: ${escalatedToPE.length}`,
      `• Escalated to human: ${escalatedToHuman.length}`,
      ``,
      `*Current State:*`,
      `• Open issues: ${openIssues.length}`,
      `• Active escalations: ${currentEscalations.length}`,
      ``,
    ];

    if (autonomyRate < 70) {
      lines.push(`⚠️ *Autonomy rate is ${autonomyRate}%* (target: >70%)`);
      lines.push(`Too many issues need human intervention.`);
      lines.push(``);
    } else if (autonomyRate >= 90) {
      lines.push(`✅ *Excellent autonomy rate: ${autonomyRate}%*`);
      lines.push(``);
    }

    // Analyze escalation patterns
    if (escalatedToPE.length > 0 || escalatedToHuman.length > 0) {
      lines.push(`*Escalation Patterns:*`);

      // Look at labels on escalated issues to find patterns
      const escalationLabels: Record<string, number> = {};
      [...escalatedToPE, ...escalatedToHuman].forEach(i => {
        i.labels.forEach(l => {
          if (!['needs-principal-engineer', 'needs-human', 'ai-ready'].includes(l.name)) {
            escalationLabels[l.name] = (escalationLabels[l.name] || 0) + 1;
          }
        });
      });

      if (Object.keys(escalationLabels).length > 0) {
        lines.push(`Labels commonly on escalated issues:`);
        Object.entries(escalationLabels)
          .sort((a, b) => b[1] - a[1])
          .slice(0, 5)
          .forEach(([label, count]) => {
            lines.push(`• ${label}: ${count}`);
          });
        lines.push(``);
      }
    }

    lines.push(`*Factory Improvement Focus:*`);
    if (escalatedToHuman.length > escalatedToPE.length) {
      lines.push(`• Many issues skip PE and go straight to human—strengthen PE workflow`);
    }
    if (currentEscalations.length > 3) {
      lines.push(`• ${currentEscalations.length} active escalations—review why agents are stuck`);
    }
    lines.push(`• Each escalation = factory bug. Find the pattern and fix the workflow.`);

    return lines.join('\n');
  } catch (error) {
    logger.error('Error fetching agent performance', { error });
    return `❌ Error fetching agent performance: ${error instanceof Error ? error.message : 'Unknown error'}`;
  }
}

/**
 * WORKFLOW HEALTH - Check if workflows are configured and running
 */
export async function getWorkflowHealth(): Promise<string> {
  const repo = getRepoPath();

  try {
    const workflows = await githubFetch<{ workflows: Array<{ id: number; name: string; state: string; path: string }> }>(
      `/repos/${repo}/actions/workflows`
    );

    const lines: string[] = [
      `*⚙️ Workflow Configuration*`,
      ``,
    ];

    const activeWorkflows = workflows.workflows.filter(w => w.state === 'active');
    const disabledWorkflows = workflows.workflows.filter(w => w.state !== 'active');

    lines.push(`*Active Workflows (${activeWorkflows.length}):*`);
    activeWorkflows.forEach(w => {
      lines.push(`• ✅ ${w.name} (\`${w.path}\`)`);
    });

    if (disabledWorkflows.length > 0) {
      lines.push(``);
      lines.push(`*Disabled Workflows (${disabledWorkflows.length}):*`);
      disabledWorkflows.forEach(w => {
        lines.push(`• ❌ ${w.name} (\`${w.path}\`)`);
      });
    }

    // Check for expected factory workflows
    const expectedWorkflows = [
      'triage', 'bug-fix', 'code', 'qa', 'devops', 'release', 'ci'
    ];
    const workflowNames = workflows.workflows.map(w => w.name.toLowerCase());
    const missing = expectedWorkflows.filter(e =>
      !workflowNames.some(n => n.includes(e))
    );

    if (missing.length > 0) {
      lines.push(``);
      lines.push(`*⚠️ Potentially Missing Workflows:*`);
      missing.forEach(m => {
        lines.push(`• ${m}`);
      });
      lines.push(`_Check if these are named differently or need to be added._`);
    }

    return lines.join('\n');
  } catch (error) {
    logger.error('Error fetching workflow health', { error });
    return `❌ Error fetching workflows: ${error instanceof Error ? error.message : 'Unknown error'}`;
  }
}

export default {
  getFactoryStatus,
  analyzeIssue,
  getFailurePatterns,
  getAgentPerformance,
  getWorkflowHealth,
};
