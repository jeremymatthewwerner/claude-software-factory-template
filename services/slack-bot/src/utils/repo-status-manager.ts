/**
 * Repository Status Manager - Updates Slack bot profile to reflect current working repository
 */

import { WebClient } from '@slack/web-api';
import logger from './logger.js';
import { config } from '../config.js';

interface RepoStatusConfig {
  repoName: string;
  branch?: string;
  emoji?: string;
  customText?: string;
}

interface StatusCache {
  lastRepo?: string;
  lastText?: string;
  lastEmoji?: string;
  lastUpdate?: Date;
}

export class RepositoryStatusManager {
  private client: WebClient;
  private cache: StatusCache = {};
  private readonly minUpdateInterval = 5 * 60 * 1000; // 5 minutes minimum between updates
  private readonly statusEmojis = {
    'claude-software-factory-template': '🏭',
    'backend': '⚙️',
    'frontend': '🎨',
    'mobile': '📱',
    'api': '🔌',
    'docs': '📚',
    'deployment': '🚀',
    'default': '💻'
  } as const;

  constructor(botToken: string) {
    this.client = new WebClient(botToken);
  }

  /**
   * Update bot status to reflect current repository
   */
  async updateRepoStatus(repoConfig: RepoStatusConfig): Promise<boolean> {
    try {
      const { repoName, branch = 'main', emoji, customText } = repoConfig;

      // Check if we need to update (rate limiting and avoid redundant updates)
      if (this.shouldSkipUpdate(repoName, customText, emoji)) {
        logger.debug('Skipping status update - no change or too recent', { repoName, branch });
        return false;
      }

      const statusEmoji = emoji || this.getEmojiForRepo(repoName);
      const statusText = customText || this.generateStatusText(repoName, branch);

      const response = await this.client.users.profile.set({
        profile: {
          status_text: statusText,
          status_emoji: statusEmoji,
          status_expiration: 0 // No expiration
        }
      });

      if (response.ok) {
        this.updateCache(repoName, statusText, statusEmoji);
        logger.info('Updated bot status for repository', {
          repoName,
          branch,
          statusText,
          statusEmoji
        });
        return true;
      } else {
        logger.warn('Failed to update bot status', {
          repoName,
          error: response.error
        });
        return false;
      }

    } catch (error) {
      logger.error('Error updating repository status', {
        error: error instanceof Error ? error.message : String(error),
        repoConfig
      });
      return false;
    }
  }

  /**
   * Update status based on session working directory
   */
  async updateFromWorkingDirectory(workingDirectory: string, branch?: string): Promise<boolean> {
    const repoName = this.extractRepoName(workingDirectory);
    if (!repoName) {
      logger.debug('No repository name found in working directory', { workingDirectory });
      return false;
    }

    return this.updateRepoStatus({ repoName, branch });
  }

  /**
   * Clear bot status (set to empty)
   */
  async clearStatus(): Promise<boolean> {
    try {
      const response = await this.client.users.profile.set({
        profile: {
          status_text: '',
          status_emoji: '',
          status_expiration: 0
        }
      });

      if (response.ok) {
        this.cache = {};
        logger.info('Cleared bot status');
        return true;
      }

      return false;
    } catch (error) {
      logger.error('Error clearing status', { error });
      return false;
    }
  }

  /**
   * Set custom status for special states (e.g., "Factory Analysis", "Multi-repo session")
   */
  async setCustomStatus(text: string, emoji = '🤖', expiration?: number): Promise<boolean> {
    try {
      const response = await this.client.users.profile.set({
        profile: {
          status_text: text,
          status_emoji: emoji,
          status_expiration: expiration || 0
        }
      });

      if (response.ok) {
        this.updateCache(text, text, emoji);
        logger.info('Set custom bot status', { text, emoji, expiration });
        return true;
      }

      return false;
    } catch (error) {
      logger.error('Error setting custom status', { error, text, emoji });
      return false;
    }
  }

  private shouldSkipUpdate(repoName: string, customText?: string, emoji?: string): boolean {
    const now = new Date();

    // Check minimum update interval
    if (this.cache.lastUpdate &&
        (now.getTime() - this.cache.lastUpdate.getTime()) < this.minUpdateInterval) {
      return true;
    }

    // Check if content actually changed
    const newText = customText || this.generateStatusText(repoName);
    const newEmoji = emoji || this.getEmojiForRepo(repoName);

    return (this.cache.lastRepo === repoName &&
            this.cache.lastText === newText &&
            this.cache.lastEmoji === newEmoji);
  }

  private updateCache(repo: string, text: string, emoji: string): void {
    this.cache = {
      lastRepo: repo,
      lastText: text,
      lastEmoji: emoji,
      lastUpdate: new Date()
    };
  }

  private extractRepoName(workingDirectory: string): string | null {
    // Extract repo name from paths like:
    // /repos/claude-software-factory-template
    // /tmp/repo
    // /path/to/my-project
    const pathParts = workingDirectory.split('/');

    // Look for meaningful repo names (skip common directories)
    const skipDirs = ['repos', 'tmp', 'repo', 'src', 'projects', 'workspace'];

    for (let i = pathParts.length - 1; i >= 0; i--) {
      const part = pathParts[i];
      if (part && !skipDirs.includes(part) && part !== '') {
        return part;
      }
    }

    return null;
  }

  private getEmojiForRepo(repoName: string): string {
    // Check for specific repo patterns
    for (const [pattern, emoji] of Object.entries(this.statusEmojis)) {
      if (pattern !== 'default' && repoName.toLowerCase().includes(pattern.toLowerCase())) {
        return emoji;
      }
    }

    // Check for common patterns
    if (repoName.includes('api') || repoName.includes('server')) return '🔌';
    if (repoName.includes('web') || repoName.includes('frontend')) return '🎨';
    if (repoName.includes('mobile') || repoName.includes('ios') || repoName.includes('android')) return '📱';
    if (repoName.includes('docs') || repoName.includes('documentation')) return '📚';
    if (repoName.includes('deploy') || repoName.includes('infra')) return '🚀';
    if (repoName.includes('factory') || repoName.includes('template')) return '🏭';

    return this.statusEmojis.default;
  }

  private generateStatusText(repoName: string, branch = 'main'): string {
    // Keep it concise for status text (100 char limit)
    const truncatedRepo = repoName.length > 30 ? `${repoName.slice(0, 27)}...` : repoName;

    if (branch && branch !== 'main' && branch !== 'master') {
      const truncatedBranch = branch.length > 20 ? `${branch.slice(0, 17)}...` : branch;
      return `Working in ${truncatedRepo}:${truncatedBranch}`;
    }

    return `Working in ${truncatedRepo}`;
  }

  /**
   * Get current status info for debugging
   */
  getStatusInfo(): { cache: StatusCache; config: { minUpdateInterval: number } } {
    return {
      cache: { ...this.cache },
      config: {
        minUpdateInterval: this.minUpdateInterval
      }
    };
  }
}

/**
 * Global repository status manager instance
 */
export const repoStatusManager = new RepositoryStatusManager(config.slack.botToken);

/**
 * Convenience function to update status from session
 */
export async function updateStatusFromSession(workingDirectory: string, branch?: string): Promise<boolean> {
  return repoStatusManager.updateFromWorkingDirectory(workingDirectory, branch);
}

/**
 * Convenience function to set custom status
 */
export async function setCustomStatus(text: string, emoji?: string, expiration?: number): Promise<boolean> {
  return repoStatusManager.setCustomStatus(text, emoji, expiration);
}

export default repoStatusManager;