/**
 * Dynamic status animator for Slack bot - similar to Claude Code's status updates
 */

import logger from './logger.js';

export interface StatusPhase {
  name: string;
  emoji: string;
  message: string;
  animationType?: 'thinking' | 'analyzing' | 'working' | 'creating' | 'processing' | 'reasoning' | 'researching' | 'optimizing';
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

  // Diverse emoji animation frames inspired by modern AI tools
  private static readonly ANIMATION_FRAMES = {
    thinking: ['🤔', '💭', '🧠', '⚡', '✨', '🎯', '💡', '🌟', '🔮', '🎨', '🧩', '⭐'],
    analyzing: ['🔍', '📊', '📈', '🔎', '🧮', '📋', '🎯', '🔬', '📉', '🎪', '🔍', '📝'],
    working: ['⚙️', '🔧', '⚡', '🛠️', '💫', '🎪', '🚀', '⚗️', '🎭', '🎯', '🔩', '⚖️'],
    creating: ['📝', '✏️', '📄', '📋', '✍️', '📃', '🎨', '🖊️', '📐', '🎪', '📓', '🖼️'],
    processing: ['🔄', '⚡', '🚀', '💫', '⭐', '🎯', '⚗️', '🎪', '🌊', '🔋', '📡', '⚡'],
    reasoning: ['🧠', '💭', '🤔', '💡', '🎯', '✨', '🔮', '🧩', '⚖️', '🎪', '🌟', '🎨'],
    researching: ['🔍', '🕵️', '📚', '🔎', '📊', '🗂️', '🔬', '🎯', '🧭', '📡', '🎪', '🗃️'],
    optimizing: ['⚡', '🚀', '⚗️', '🔧', '⚙️', '🎯', '💫', '🎪', '🔋', '📈', '🌟', '⭐']
  };

  // Comprehensive dynamic verbs inspired by Claude Code, ChatGPT, Gemini, and OpenAI - now with more cute words!
  private static readonly CLAUDE_VERBS = {
    thinking: [
      // Original professional words
      'cogitating', 'pondering', 'contemplating', 'ruminating', 'deliberating', 'reflecting',
      'reasoning', 'mulling', 'meditating', 'considering', 'introspecting', 'philosophizing',
      'brainstorming', 'conceptualizing', 'theorizing', 'strategizing', 'envisioning', 'imagining',
      // New cute additions
      'daydreaming', 'wondering', 'musing', 'dreaming', 'puzzling', 'brewing ideas',
      'having thoughts', 'mind-wandering', 'brain-storming', 'idea-cooking', 'thought-juggling',
      'neural-networking', 'synapses-firing', 'creativity-flowing', 'wisdom-gathering', 'insight-hunting'
    ],
    analyzing: [
      // Original professional words  
      'examining', 'scrutinizing', 'investigating', 'parsing', 'dissecting', 'evaluating',
      'inspecting', 'auditing', 'diagnosing', 'profiling', 'surveying', 'assessing',
      'reviewing', 'studying', 'exploring', 'decoding', 'deciphering', 'interpreting',
      // New cute additions
      'detective-working', 'puzzle-solving', 'pattern-hunting', 'clue-gathering', 'mystery-unraveling',
      'data-diving', 'info-sifting', 'detail-chasing', 'fact-finding', 'logic-weaving',
      'code-sleuthing', 'bug-hunting', 'pixel-peeping', 'byte-browsing', 'algorithm-auditing'
    ],
    working: [
      // Original professional words
      'processing', 'computing', 'calculating', 'synthesizing', 'organizing', 'structuring',
      'optimizing', 'refining', 'transforming', 'assembling', 'orchestrating', 'coordinating',
      'implementing', 'executing', 'compiling', 'configuring', 'calibrating', 'fine-tuning',
      // New cute additions
      'busy-beeing', 'magic-making', 'gear-turning', 'wheel-spinning', 'engine-humming',
      'circuit-buzzing', 'byte-crunching', 'pixel-pushing', 'code-crafting', 'data-dancing',
      'algorithm-weaving', 'function-flowing', 'variable-vibe-ing', 'loop-looping', 'stack-stacking'
    ],
    creating: [
      // Original professional words
      'composing', 'crafting', 'generating', 'formulating', 'constructing', 'building',
      'designing', 'architecting', 'developing', 'producing', 'fabricating', 'manufacturing',
      'authoring', 'drafting', 'sketching', 'modeling', 'prototyping', 'innovating',
      // New cute additions
      'art-making', 'masterpiece-crafting', 'magic-weaving', 'dream-building', 'story-spinning',
      'word-painting', 'idea-sculpting', 'creativity-flowing', 'inspiration-channeling', 'beauty-brewing',
      'code-poetry-writing', 'digital-art-creating', 'syntax-singing', 'logic-painting', 'function-flowering'
    ],
    processing: [
      // Original professional words
      'orchestrating', 'coordinating', 'executing', 'performing', 'operating', 'finalizing',
      'compiling', 'rendering', 'encoding', 'transforming', 'streaming', 'buffering',
      'indexing', 'sorting', 'filtering', 'aggregating', 'consolidating', 'reconciling',
      // New cute additions
      'data-dancing', 'bit-ballet', 'byte-boogie', 'algorithm-aerobics', 'code-choreography',
      'digital-disco', 'cyber-spinning', 'tech-tap-dancing', 'silicon-salsa', 'binary-breakdancing',
      'packet-prancing', 'signal-swaying', 'frequency-flowing', 'wave-waltzing', 'stream-streaming'
    ],
    reasoning: [
      // Original professional words
      'deducing', 'inferring', 'concluding', 'deriving', 'extrapolating', 'correlating',
      'connecting', 'linking', 'associating', 'synthesizing', 'integrating', 'consolidating',
      'cross-referencing', 'triangulating', 'validating', 'verifying', 'confirming', 'substantiating',
      // New cute additions
      'puzzle-piecing', 'dot-connecting', 'thread-following', 'logic-linking', 'pattern-matching',
      'clue-connecting', 'mystery-solving', 'riddle-unraveling', 'brain-bridging', 'insight-weaving',
      'thought-threading', 'idea-intertwining', 'concept-coupling', 'wisdom-weaving', 'truth-tracking'
    ],
    researching: [
      // Original professional words
      'investigating', 'exploring', 'discovering', 'uncovering', 'mining', 'extracting',
      'gathering', 'collecting', 'sourcing', 'retrieving', 'indexing', 'cataloging',
      'curating', 'surveying', 'mapping', 'documenting', 'chronicling', 'archiving',
      // New cute additions
      'treasure-hunting', 'knowledge-seeking', 'fact-fishing', 'info-adventuring', 'data-diving',
      'wisdom-wandering', 'curiosity-following', 'discovery-dancing', 'learning-leaping', 'insight-seeking',
      'truth-tracking', 'evidence-exploring', 'clue-chasing', 'answer-hunting', 'secret-searching'
    ],
    optimizing: [
      // Original professional words
      'refining', 'enhancing', 'improving', 'streamlining', 'perfecting', 'polishing',
      'tuning', 'calibrating', 'adjusting', 'tweaking', 'fine-tuning', 'balancing',
      'harmonizing', 'stabilizing', 'maximizing', 'minimizing', 'accelerating', 'upgrading',
      // New cute additions
      'sparkle-adding', 'shine-boosting', 'perfection-pursuing', 'beauty-buffing', 'elegance-enhancing',
      'smoothness-sculpting', 'efficiency-elevating', 'performance-pampering', 'speed-sprucing', 'quality-quilting',
      'precision-polishing', 'excellence-editing', 'flawless-finishing', 'magic-maximizing', 'awesome-amplifying'
    ]
  };

  // Default phases for different operations
  static readonly DEFAULT_PHASES: Record<string, StatusPhase[]> = {
    conversation: [
      { name: 'analyzing', emoji: '🔍', message: 'Analyzing your message for context and intent', animationType: 'analyzing', estimatedDuration: 3000 },
      { name: 'reasoning', emoji: '🧠', message: 'Reasoning through the problem space', animationType: 'reasoning', estimatedDuration: 4000 },
      { name: 'researching', emoji: '🕵️', message: 'Researching relevant information', animationType: 'researching', estimatedDuration: 3500 },
      { name: 'creating', emoji: '📝', message: 'Crafting comprehensive response', animationType: 'creating', estimatedDuration: 3000 },
      { name: 'optimizing', emoji: '⚡', message: 'Optimizing for clarity and accuracy', animationType: 'optimizing', estimatedDuration: 2000 }
    ],
    dispatch: [
      { name: 'parsing', emoji: '🔍', message: 'Parsing dispatch request and requirements', animationType: 'analyzing', estimatedDuration: 2000 },
      { name: 'reasoning', emoji: '🧩', message: 'Reasoning about best agent assignment', animationType: 'reasoning', estimatedDuration: 3000 },
      { name: 'creating', emoji: '📋', message: 'Creating GitHub issue with full context', animationType: 'creating', estimatedDuration: 4000 },
      { name: 'optimizing', emoji: '🎯', message: 'Optimizing agent workflow setup', animationType: 'optimizing', estimatedDuration: 2000 }
    ],
    factory_analysis: [
      { name: 'researching', emoji: '📊', message: 'Researching factory metrics and patterns', animationType: 'researching', estimatedDuration: 3500 },
      { name: 'analyzing', emoji: '🔬', message: 'Analyzing system health indicators', animationType: 'analyzing', estimatedDuration: 5000 },
      { name: 'reasoning', emoji: '🧠', message: 'Reasoning about correlations and trends', animationType: 'reasoning', estimatedDuration: 3000 },
      { name: 'creating', emoji: '📋', message: 'Creating comprehensive status report', animationType: 'creating', estimatedDuration: 2000 }
    ],
    code_analysis: [
      { name: 'researching', emoji: '🕵️', message: 'Researching codebase structure and patterns', animationType: 'researching', estimatedDuration: 4000 },
      { name: 'analyzing', emoji: '🔬', message: 'Analyzing code quality and architecture', animationType: 'analyzing', estimatedDuration: 5000 },
      { name: 'reasoning', emoji: '🧩', message: 'Reasoning about optimal solutions', animationType: 'reasoning', estimatedDuration: 3500 },
      { name: 'creating', emoji: '🛠️', message: 'Creating implementation plan', animationType: 'creating', estimatedDuration: 3000 }
    ]
  };

  static async start(config: StatusAnimatorConfig): Promise<string> {
    const { channel, threadTs, client, phases, animationInterval = 2000 } = config; // Changed to 2000ms (2 seconds)
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

      // Start animation loop - now every 2 seconds for word changes
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

    // Progress bar (like Claude Code)
    const progressBar = this.createProgressBar(phaseIndex, totalPhases);

    // Format like Claude Code with structured output
    return `${animatedEmoji} *${dynamicVerb}...* ${progress}

${progressBar}

_${phase.message}_`;
  }

  private static createProgressBar(current: number, total: number): string {
    const width = 20;
    const filled = Math.floor((current / total) * width);
    const empty = width - filled;

    const filledBar = '█'.repeat(filled);
    const emptyBar = '░'.repeat(empty);
    const percentage = Math.round(((current + 1) / total) * 100);

    return `\`${filledBar}${emptyBar}\` ${percentage}%`;
  }

  // Utility method to get default phases for an operation type
  static getPhasesForOperation(operation: keyof typeof StatusAnimator.DEFAULT_PHASES): StatusPhase[] {
    return this.DEFAULT_PHASES[operation] || this.DEFAULT_PHASES.conversation;
  }
}

export default StatusAnimator;