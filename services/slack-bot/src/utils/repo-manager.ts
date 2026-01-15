/**
 * Repository manager for cloning and managing the git repository
 *
 * On Railway, the bot runs in a container with just the deployed app files.
 * To enable git operations, we need to clone the actual repository.
 */

import { execSync, exec } from 'child_process';
import { existsSync, mkdirSync } from 'fs';
import { promisify } from 'util';
import { config } from '../config.js';
import logger from './logger.js';

const execAsync = promisify(exec);

// Default repo path - use /tmp since it's writable in containers
const REPO_PATH = process.env.REPO_PATH || '/tmp/repo';

/**
 * Check if git is available
 */
function isGitAvailable(): boolean {
  try {
    execSync('git --version', { stdio: 'pipe' });
    return true;
  } catch {
    return false;
  }
}

/**
 * Clone or update the repository
 */
export async function setupRepository(): Promise<{
  success: boolean;
  path: string;
  error?: string;
}> {
  const repoUrl = config.github.repository;
  const token = config.github.token;

  if (!repoUrl) {
    logger.warn('GITHUB_REPOSITORY not configured - git operations disabled');
    return {
      success: false,
      path: process.cwd(),
      error: 'GITHUB_REPOSITORY not configured',
    };
  }

  if (!token) {
    logger.warn('GITHUB_TOKEN not configured - git operations disabled');
    return {
      success: false,
      path: process.cwd(),
      error: 'GITHUB_TOKEN not configured',
    };
  }

  if (!isGitAvailable()) {
    logger.warn('Git not available in this environment');
    return {
      success: false,
      path: process.cwd(),
      error: 'Git not installed',
    };
  }

  try {
    // Build authenticated URL
    const owner = config.github.owner || repoUrl.split('/')[0];
    const repo = repoUrl.includes('/') ? repoUrl.split('/')[1] : repoUrl;
    const authUrl = `https://x-access-token:${token}@github.com/${owner}/${repo}.git`;

    if (existsSync(`${REPO_PATH}/.git`)) {
      // Repo exists - fetch and reset to latest
      logger.info('Updating existing repository', { path: REPO_PATH });

      await execAsync(`git fetch origin`, { cwd: REPO_PATH });
      await execAsync(`git reset --hard origin/main || git reset --hard origin/master`, {
        cwd: REPO_PATH,
      });

      logger.info('Repository updated successfully');
    } else {
      // Clone fresh
      logger.info('Cloning repository', { repo: `${owner}/${repo}`, path: REPO_PATH });

      // Ensure parent directory exists
      mkdirSync(REPO_PATH, { recursive: true });

      // Clone with depth for speed (but enough history for rebasing)
      await execAsync(`git clone --depth 50 ${authUrl} ${REPO_PATH}`);

      // Configure git user for commits
      await execAsync(`git config user.email "bot@claude-factory.ai"`, { cwd: REPO_PATH });
      await execAsync(`git config user.name "Claude Factory Bot"`, { cwd: REPO_PATH });

      // Verify the remote URL has auth embedded (for push)
      const { stdout: remoteUrl } = await execAsync(`git remote get-url origin`, { cwd: REPO_PATH });
      if (!remoteUrl.includes('x-access-token')) {
        logger.warn('Remote URL may not have push credentials embedded');
      }

      logger.info('Repository cloned successfully', {
        path: REPO_PATH,
        hasAuth: remoteUrl.includes('x-access-token'),
      });
    }

    return {
      success: true,
      path: REPO_PATH,
    };
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : 'Unknown error';
    logger.error('Failed to setup repository', { error: errorMessage });

    return {
      success: false,
      path: process.cwd(),
      error: errorMessage,
    };
  }
}

/**
 * Get the repository path (or cwd if not available)
 */
export function getRepoPath(): string {
  if (existsSync(`${REPO_PATH}/.git`)) {
    return REPO_PATH;
  }
  return process.cwd();
}

/**
 * Check if repository is available
 */
export function isRepoAvailable(): boolean {
  return existsSync(`${REPO_PATH}/.git`);
}

export default {
  setupRepository,
  getRepoPath,
  isRepoAvailable,
};
