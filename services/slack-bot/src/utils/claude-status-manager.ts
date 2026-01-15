/**
 * Status management for Claude Code sessions in Slack
 * Implements live status updates with spinning animations
 */

import { SpinnerAnimation, LiveStatusProtocol } from './spinner-animation.js';

export interface TaskPhase {
  name: string;
  description: string;
  estimatedDuration?: number;
}

export class ClaudeStatusManager {
  private protocol: LiveStatusProtocol;
  private currentPhase = 0;
  private phases: TaskPhase[] = [];
  private lastMessage = '';

  constructor(private updateCallback: (message: string) => Promise<void>) {
    this.protocol = new LiveStatusProtocol();
  }

  /**
   * Initialize a multi-phase task
   */
  async startTask(phases: TaskPhase[]): Promise<void> {
    this.phases = phases;
    this.currentPhase = 0;
    SpinnerAnimation.reset();

    const message = SpinnerAnimation.formatStatus(
      `Starting ${phases.length}-phase task...`,
      { current: 1, total: phases.length }
    );

    await this.sendUpdate(message);
  }

  /**
   * Update status for current operation
   */
  async updateStatus(message: string, forceUpdate = false): Promise<void> {
    if (forceUpdate || this.protocol.recordOperation()) {
      const phaseInfo = this.phases.length > 1 ? {
        current: this.currentPhase + 1,
        total: this.phases.length
      } : undefined;

      const formattedMessage = SpinnerAnimation.formatStatus(message, phaseInfo);
      await this.sendUpdate(formattedMessage);
    }
  }

  /**
   * Complete current phase and move to next
   */
  async completePhase(message?: string): Promise<void> {
    const phaseInfo = this.phases.length > 1 ? {
      current: this.currentPhase + 1,
      total: this.phases.length
    } : undefined;

    const completionMessage = SpinnerAnimation.formatComplete(
      message || this.phases[this.currentPhase]?.name || 'Phase completed',
      phaseInfo
    );

    await this.sendUpdate(completionMessage);

    this.currentPhase++;
    this.protocol.forceUpdate();
  }

  /**
   * Complete entire task
   */
  async completeTask(message = 'All phases complete!'): Promise<void> {
    const finalMessage = `✅ _${message}_ 🎉`;
    await this.sendUpdate(finalMessage);
  }

  /**
   * Handle errors with appropriate status
   */
  async reportError(error: string, isRecoverable = true): Promise<void> {
    const icon = isRecoverable ? '⚠️' : '❌';
    const message = `${icon} _Error:_ ${error}`;
    await this.sendUpdate(message);
  }

  private async sendUpdate(message: string): Promise<void> {
    if (message !== this.lastMessage) {
      this.lastMessage = message;
      await this.updateCallback(message);
    }
  }

  /**
   * Get current phase info for external use
   */
  getCurrentPhase(): { index: number; phase: TaskPhase | undefined; total: number } {
    return {
      index: this.currentPhase,
      phase: this.phases[this.currentPhase],
      total: this.phases.length
    };
  }
}

/**
 * Factory function to create status manager for Claude Code sessions
 */
export function createClaudeStatusManager(
  updateCallback: (message: string) => Promise<void>
): ClaudeStatusManager {
  return new ClaudeStatusManager(updateCallback);
}

/**
 * Common task phases for Claude Code operations
 */
export const COMMON_PHASES = {
  ANALYZE: { name: 'Analyzing requirements', description: 'Understanding the task and requirements' },
  SEARCH: { name: 'Searching codebase', description: 'Finding relevant files and understanding context' },
  IMPLEMENT: { name: 'Implementing changes', description: 'Writing code and making modifications' },
  TEST: { name: 'Testing and validation', description: 'Running tests and quality checks' },
  DEPLOY: { name: 'Deploying changes', description: 'Committing, pushing, and deploying' }
} as const;