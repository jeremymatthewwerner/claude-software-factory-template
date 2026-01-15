/**
 * Dynamic status animator for Slack bot - similar to Claude Code's status updates
 */

import logger from './logger.js';

export interface StatusPhase {
  name: string;
  emoji: string;
  message: string;
  animationType?: 'thinking' | 'analyzing' | 'working' | 'creating' | 'processing';
  estimatedDuration?: number; // milliseconds
}

export interface StatusAnimatorConfig {
  channel: string;
  threadTs: string;
  client: any;
  phases: StatusPhase[];
  animationInterval?: number; // milliseconds between spinner updates
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

  // Cool emoji animation frames
  private static readonly ANIMATION_FRAMES = {
    thinking: ['🤔', '💭', '🧠', '⚡', '✨', '🎯'],
    analyzing: ['🔍', '📊', '📈', '🔎', '🧮', '📋'],
    working: ['⚙️', '🔧', '⚡', '🛠️', '💫', '🎪'],
    creating: ['📝', '✏️', '📄', '📋', '✍️', '📃'],
    processing: ['🔄', '⚡', '🚀', '💫', '⭐', '🎯']
  };

  // Claude Code-style dynamic verbs that rotate with animation frames
  private static readonly CLAUDE_VERBS = {
    thinking: ['cogitating', 'pondering', 'contemplating', 'ruminating', 'deliberating', 'reflecting'],
    analyzing: ['examining', 'scrutinizing', 'investigating', 'parsing', 'dissecting', 'evaluating'],
    working: ['processing', 'computing', 'calculating', 'synthesizing', 'organizing', 'structuring'],
    creating: ['composing', 'crafting', 'generating', 'formulating', 'constructing', 'building'],
    processing: ['orchestrating', 'coordinating', 'executing', 'performing', 'operating', 'finalizing']
  };

  // Default phases for different operations
  static readonly DEFAULT_PHASES: Record<string, StatusPhase[]> = {
    conversation: [
      { name: 'analyzing', emoji: '🧠', message: 'Analyzing your message', animationType: 'analyzing', estimatedDuration: 3000 },
      { name: 'thinking', emoji: '💭', message: 'Thinking through the problem', animationType: 'thinking', estimatedDuration: 4000 },
      { name: 'formulating', emoji: '📝', message: 'Formulating response', animationType: 'creating', estimatedDuration: 3000 },
      { name: 'finalizing', emoji: '✨', message: 'Finalizing answer', animationType: 'processing', estimatedDuration: 2000 }
    ],
    dispatch: [
      { name: 'parsing', emoji: '🔍', message: 'Parsing dispatch request', animationType: 'analyzing', estimatedDuration: 2000 },
      { name: 'routing', emoji: '🎯', message: 'Routing to appropriate agent', animationType: 'processing', estimatedDuration: 3000 },
      { name: 'creating', emoji: '📋', message: 'Creating GitHub issue', animationType: 'creating', estimatedDuration: 4000 },
      { name: 'confirming', emoji: '✅', message: 'Confirming agent assignment', animationType: 'working', estimatedDuration: 2000 }
    ],
    factory_analysis: [
      { name: 'collecting', emoji: '📊', message: 'Collecting factory data', animationType: 'working', estimatedDuration: 3500 },
      { name: 'analyzing', emoji: '🔍', message: 'Analyzing patterns', animationType: 'analyzing', estimatedDuration: 5000 },
      { name: 'correlating', emoji: '🧮', message: 'Correlating metrics', animationType: 'processing', estimatedDuration: 3000 },
      { name: 'summarizing', emoji: '📋', message: 'Preparing summary', animationType: 'creating', estimatedDuration: 2000 }
    ]
  };

  static async start(config: StatusAnimatorConfig): Promise<string> {
    const { channel, threadTs, client, phases, animationInterval = 1500 } = config;
    const key = `${channel}-${threadTs}`;

    // Stop any existing animator for this thread
    this.stop(key);

    try {
      // Post initial status message
      const response = await client.chat.postMessage({
        channel,
        thread_ts: threadTs,
        text: this.formatStatusMessage(phases[0], 0, 0, phases.length),
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

      // Start animation loop
      tracker.intervalId = setInterval(async () => {
        await this.updateAnimation(key, client, channel, phases);
      }, animationInterval);

      // Schedule phase transitions
      this.schedulePhaseTransition(key, client, channel, phases);

      logger.debug('Status animator started', { key, phases: phases.length });

      return response.ts;
    } catch (error) {
      logger.error('Failed to start status animator', { error, key });
      throw error;
    }
  }

  static async updatePhase(key: string, phaseIndex: number, client: any, channel: string, phases: StatusPhase[]): Promise<void> {
    const tracker = this.instances.get(key);
    if (!tracker || tracker.isCompleted) return;

    tracker.currentPhase = Math.min(phaseIndex, phases.length - 1);
    tracker.animationFrame = 0; // Reset animation for new phase

    try {
      await client.chat.update({
        channel,
        ts: tracker.messageTs,
        text: this.formatStatusMessage(phases[tracker.currentPhase], tracker.currentPhase, tracker.animationFrame, phases.length),
      });

      // Schedule next phase transition if not at the end
      if (tracker.currentPhase < phases.length - 1) {
        this.schedulePhaseTransition(key, client, channel, phases);
      }

      logger.debug('Status phase updated', { key, phase: tracker.currentPhase });
    } catch (error) {
      logger.error('Failed to update status phase', { error, key, phaseIndex });
    }
  }

  static async update(key: string, partialMessage: string, client: any, channel: string): Promise<void> {
    const tracker = this.instances.get(key);
    if (!tracker || tracker.isCompleted) return;

    try {
      // Update message with partial content while keeping status animation
      const currentPhase = tracker.currentPhase;
      const phases = StatusAnimator.DEFAULT_PHASES.message || [];
      const phase = phases[Math.min(currentPhase, phases.length - 1)];

      if (phase) {
        const statusMessage = this.formatStatusMessage(phase, currentPhase, tracker.animationFrame, phases.length);
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
      // Replace status message with final response
      await client.chat.update({
        channel,
        ts: tracker.messageTs,
        text: finalMessage,
      });

      logger.debug('Status animator completed', { key });
    } catch (error) {
      logger.error('Failed to complete status animator', { error, key });
      // Fallback: post final message as new message
      try {
        await client.chat.postMessage({
          channel,
          thread_ts: key.split('-')[1], // Extract threadTs from key
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

  private static async updateAnimation(key: string, client: any, channel: string, phases: StatusPhase[]): Promise<void> {
    const tracker = this.instances.get(key);
    if (!tracker || tracker.isCompleted) return;

    const currentPhase = phases[tracker.currentPhase];
    const animationType = currentPhase.animationType || 'thinking';
    const animationFrames = this.ANIMATION_FRAMES[animationType];

    // Advance animation frame
    tracker.animationFrame = (tracker.animationFrame + 1) % animationFrames.length;

    try {
      // Update message with new animation frame
      await client.chat.update({
        channel,
        ts: tracker.messageTs,
        text: this.formatStatusMessage(phases[tracker.currentPhase], tracker.currentPhase, tracker.animationFrame, phases.length),
      });

      logger.debug('Animation frame updated', { key, phase: tracker.currentPhase, frame: tracker.animationFrame });
    } catch (error) {
      logger.error('Failed to update animation frame', { error, key, phase: tracker.currentPhase });

      // If we get a rate limit error, slow down
      if (error && typeof error === 'object' && 'data' in error &&
          (error as any).data?.error === 'rate_limited') {
        logger.warn('Rate limited - stopping animation for this thread', { key });
        this.stop(key);
      }
    }
  }

  private static schedulePhaseTransition(key: string, client: any, channel: string, phases: StatusPhase[]): void {
    const tracker = this.instances.get(key);
    if (!tracker || tracker.isCompleted) return;

    const currentPhase = phases[tracker.currentPhase];
    const duration = currentPhase.estimatedDuration || 3000;

    // Clear existing timeout
    if (tracker.phaseTimeoutId) {
      clearTimeout(tracker.phaseTimeoutId);
    }

    // Schedule next phase transition
    if (tracker.currentPhase < phases.length - 1) {
      tracker.phaseTimeoutId = setTimeout(() => {
        this.updatePhase(key, tracker.currentPhase + 1, client, channel, phases);
      }, duration);
    }
  }


  private static formatStatusMessage(phase: StatusPhase, phaseIndex: number, animationFrame: number, totalPhases: number): string {
    const animationType = phase.animationType || 'thinking';
    const animationFrames = this.ANIMATION_FRAMES[animationType];
    const animatedEmoji = animationFrames[animationFrame % animationFrames.length];

    // Get dynamic Claude-style verb that rotates with animation frame
    const verbList = this.CLAUDE_VERBS[animationType] || this.CLAUDE_VERBS.thinking;
    const dynamicVerb = verbList[animationFrame % verbList.length];

    const progress = `[${phaseIndex + 1}/${totalPhases}]`;

    // Format like Claude Code: "cogitating... ◐"
    return `${dynamicVerb}... ${animatedEmoji} ${progress}`;
  }

  // Utility method to get default phases for an operation type
  static getPhasesForOperation(operation: keyof typeof StatusAnimator.DEFAULT_PHASES): StatusPhase[] {
    return this.DEFAULT_PHASES[operation] || this.DEFAULT_PHASES.conversation;
  }
}

export default StatusAnimator;