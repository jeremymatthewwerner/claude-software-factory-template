/**
 * Simplified status animator - no fake progress bars
 */

import logger from './logger.js';

export interface StatusPhase {
  name: string;
  emoji: string;
  message: string;
  animationType?: 'thinking' | 'analyzing' | 'working' | 'creating' | 'processing' | 'reasoning' | 'researching' | 'optimizing';
  estimatedDuration?: number;
}

export interface StatusAnimatorConfig {
  channel: string;
  threadTs: string;
  client: any;
  phases: StatusPhase[];
  animationInterval?: number;
}

export interface ActiveStatusTracker {
  messageTs: string;
  currentPhase: number;
  animationFrame: number;
  intervalId: NodeJS.Timeout | null;
  phaseTimeoutId: NodeJS.Timeout | null;
  isCompleted: boolean;
}

export class StatusAnimator {
  private static instances = new Map<string, ActiveStatusTracker>();

  // Simple status messages without fake progress bars
  static readonly DEFAULT_PHASES: Record<string, StatusPhase[]> = {
    conversation: [
      { name: 'processing', emoji: '🤖', message: 'Processing your message...', animationType: 'thinking', estimatedDuration: 1000 }
    ],
    dispatch: [
      { name: 'dispatching', emoji: '🚀', message: 'Dispatching to agent...', animationType: 'working', estimatedDuration: 1000 }
    ],
    factory_analysis: [
      { name: 'analyzing', emoji: '📊', message: 'Analyzing factory status...', animationType: 'analyzing', estimatedDuration: 1000 }
    ],
    code_analysis: [
      { name: 'reviewing', emoji: '🔍', message: 'Reviewing code...', animationType: 'analyzing', estimatedDuration: 1000 }
    ]
  };

  static async start(config: StatusAnimatorConfig): Promise<string> {
    const { channel, threadTs, client, phases } = config;
    const key = `${channel}-${threadTs}`;

    // Stop any existing animator for this thread
    this.stop(key);

    try {
      // Post simple status message
      const currentPhase = phases[0] || { name: 'processing', emoji: '🤖', message: 'Processing...' };
      const response = await client.chat.postMessage({
        channel,
        thread_ts: threadTs,
        text: `${currentPhase.emoji} ${currentPhase.message}`,
      });

      const tracker: ActiveStatusTracker = {
        messageTs: response.ts,
        currentPhase: 0,
        animationFrame: 0,
        intervalId: null,
        phaseTimeoutId: null,
        isCompleted: false,
      };

      this.instances.set(key, tracker);
      logger.debug('Simple status animator started', { key });
      return key;
    } catch (error) {
      logger.error('Failed to start status animator', { error, key });
      throw error;
    }
  }

  static async updatePhase(key: string, phaseIndex: number, client: any, channel: string, phases: StatusPhase[]): Promise<void> {
    const tracker = this.instances.get(key);
    if (!tracker || tracker.isCompleted) return;

    tracker.currentPhase = Math.min(phaseIndex, phases.length - 1);
    const currentPhase = phases[tracker.currentPhase];

    try {
      await client.chat.update({
        channel,
        ts: tracker.messageTs,
        text: `${currentPhase.emoji} ${currentPhase.message}`,
      });
      logger.debug('Status phase updated', { key, phase: tracker.currentPhase });
    } catch (error) {
      logger.error('Failed to update status phase', { error, key, phaseIndex });
    }
  }

  static async update(key: string, partialMessage: string, client: any, channel: string): Promise<void> {
    const tracker = this.instances.get(key);
    if (!tracker || tracker.isCompleted) return;

    try {
      const phases = StatusAnimator.DEFAULT_PHASES.conversation || [];
      const phase = phases[Math.min(tracker.currentPhase, phases.length - 1)];
      
      if (phase) {
        const statusMessage = `${phase.emoji} ${phase.message}`;
        const combinedMessage = `${statusMessage}\n\n${partialMessage}`;

        await client.chat.update({
          channel: channel,
          ts: tracker.messageTs,
          text: combinedMessage
        });
      }
    } catch (error) {
      logger.warn('Failed to update streaming message', { error: error instanceof Error ? error.message : String(error), key });
    }
  }

  static async complete(key: string, finalMessage: string, client: any, channel: string): Promise<void> {
    const tracker = this.instances.get(key);
    if (!tracker) return;

    tracker.isCompleted = true;

    // Clear intervals
    if (tracker.intervalId) {
      clearInterval(tracker.intervalId);
    }
    if (tracker.phaseTimeoutId) {
      clearTimeout(tracker.phaseTimeoutId);
    }

    try {
      // Post final result as NEW message
      const hyphenIndex = key.indexOf('-');
      const threadTs = hyphenIndex > 0 ? key.substring(hyphenIndex + 1) : key;
      
      await client.chat.postMessage({
        channel,
        thread_ts: threadTs,
        text: finalMessage,
        unfurl_links: false,
        unfurl_media: false
      });

      logger.debug('Status animator completed with new message', { key });
    } catch (error) {
      logger.error('Failed to complete status animator', { error, key });
      
      // Fallback: try updating the original message if posting fails
      try {
        await client.chat.update({
          channel,
          ts: tracker.messageTs,
          text: finalMessage,
        });
      } catch (fallbackError) {
        logger.error('Failed to post fallback message', { fallbackError, key });
      }
    } finally {
      this.instances.delete(key);
    }
  }

  static stop(key: string): void {
    const tracker = this.instances.get(key);
    if (!tracker) return;

    tracker.isCompleted = true;

    if (tracker.intervalId) {
      clearInterval(tracker.intervalId);
    }
    if (tracker.phaseTimeoutId) {
      clearTimeout(tracker.phaseTimeoutId);
    }

    this.instances.delete(key);
    logger.debug('Status animator stopped', { key });
  }

  // Utility method to get default phases for an operation type
  static getPhasesForOperation(operation: keyof typeof StatusAnimator.DEFAULT_PHASES): StatusPhase[] {
    return this.DEFAULT_PHASES[operation] || this.DEFAULT_PHASES.conversation;
  }
}

export default StatusAnimator;