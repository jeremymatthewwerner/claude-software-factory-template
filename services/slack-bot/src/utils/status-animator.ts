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
    thinking: ['💭', '🤔', '💡', '🧠', '✨', '⭐', '🌟', '💫', '🎯', '🔮', '🎨', '🧩'],
    analyzing: ['🔍', '🔎', '📊', '📈', '🧮', '📋', '🔬', '📉', '🎯', '🧪', '⚗️', '🔭'],
    working: ['⚙️', '🔧', '🛠️', '⚡', '⚖️', '🔩', '🎪', '🚀', '💫', '🎭', '🎯', '⭐'],
    creating: ['📝', '✏️', '🖊️', '📄', '📋', '✍️', '🎨', '🖼️', '📐', '📓', '🎪', '🌟'],
    processing: ['🔄', '💫', '⚡', '🚀', '⭐', '🎯', '⚗️', '🌊', '🔋', '📡', '🎪', '🌟'],
    reasoning: ['🧠', '💭', '🤔', '💡', '🎯', '✨', '🔮', '🧩', '⚖️', '🌟', '🎨', '⭐'],
    researching: ['🔍', '🕵️', '📚', '🔎', '📊', '🗂️', '🔬', '🎯', '🧭', '📡', '🗃️', '🎪'],
    optimizing: ['⚡', '🚀', '⚗️', '🔧', '⚙️', '🎯', '💫', '🔋', '📈', '🌟', '⭐', '🎪']
  };

  // Expanded Claude-style verbs for dynamic status messages - now with many more fun words!
  private static readonly CLAUDE_VERBS = {
    thinking: [
      // Original professional words
      'cogitating', 'pondering', 'contemplating', 'ruminating', 'deliberating', 'reflecting',
      'reasoning', 'mulling', 'meditating', 'considering', 'introspecting', 'philosophizing',
      'brainstorming', 'conceptualizing', 'theorizing', 'strategizing', 'envisioning', 'imagining',
      // More cute additions
      'daydreaming', 'wondering', 'musing', 'dreaming', 'puzzling', 'brewing ideas',
      'having thoughts', 'mind-wandering', 'brain-storming', 'idea-cooking', 'thought-juggling',
      'neural-networking', 'synapses-firing', 'creativity-flowing', 'wisdom-gathering', 'insight-hunting',
      // Extra fun ones
      'cloud-gazing', 'star-wishing', 'mind-melding', 'soul-searching', 'brain-dancing',
      'thought-swimming', 'idea-surfing', 'wisdom-fishing', 'inspiration-catching', 'eureka-seeking',
      'lightbulb-chasing', 'aha-moment-hunting', 'genius-brewing', 'brilliance-cooking', 'insight-baking'
    ],
    analyzing: [
      // Original professional words  
      'examining', 'scrutinizing', 'investigating', 'parsing', 'dissecting', 'evaluating',
      'inspecting', 'auditing', 'diagnosing', 'profiling', 'surveying', 'assessing',
      'reviewing', 'studying', 'exploring', 'decoding', 'deciphering', 'interpreting',
      // More cute additions
      'detective-working', 'puzzle-solving', 'pattern-hunting', 'clue-gathering', 'mystery-unraveling',
      'data-diving', 'info-sifting', 'detail-chasing', 'fact-finding', 'logic-weaving',
      'code-sleuthing', 'bug-hunting', 'pixel-peeping', 'byte-browsing', 'algorithm-auditing',
      // Extra fun ones
      'magnifying-glass-wielding', 'sherlock-holmesing', 'csi-investigating', 'truth-detecting',
      'evidence-collecting', 'case-cracking', 'riddle-solving', 'secret-uncovering',
      'microscope-peering', 'x-ray-visioning', 'radar-scanning', 'sonar-pinging'
    ],
    working: [
      // Original professional words
      'processing', 'computing', 'calculating', 'synthesizing', 'organizing', 'structuring',
      'optimizing', 'refining', 'transforming', 'assembling', 'orchestrating', 'coordinating',
      'implementing', 'executing', 'compiling', 'configuring', 'calibrating', 'fine-tuning',
      // More cute additions
      'busy-beeing', 'magic-making', 'gear-turning', 'wheel-spinning', 'engine-humming',
      'circuit-buzzing', 'byte-crunching', 'pixel-pushing', 'code-crafting', 'data-dancing',
      'algorithm-weaving', 'function-flowing', 'variable-vibe-ing', 'loop-looping', 'stack-stacking',
      // Extra fun ones
      'hamster-wheel-running', 'coffee-machine-brewing', 'factory-line-moving', 'clockwork-ticking',
      'workshop-hammering', 'forge-smithing', 'laboratory-experimenting', 'kitchen-cooking',
      'assembly-line-rolling', 'conveyor-belt-moving', 'industrial-strength-working', 'turbo-charging'
    ],
    creating: [
      // Original professional words
      'composing', 'crafting', 'generating', 'formulating', 'constructing', 'building',
      'designing', 'architecting', 'developing', 'producing', 'fabricating', 'manufacturing',
      'authoring', 'drafting', 'sketching', 'modeling', 'prototyping', 'innovating',
      // More cute additions
      'art-making', 'masterpiece-crafting', 'magic-weaving', 'dream-building', 'story-spinning',
      'word-painting', 'idea-sculpting', 'creativity-flowing', 'inspiration-channeling', 'beauty-brewing',
      'code-poetry-writing', 'digital-art-creating', 'syntax-singing', 'logic-painting', 'function-flowering',
      // Extra fun ones
      'rainbow-painting', 'unicorn-summoning', 'fairy-tale-writing', 'castle-building', 'garden-growing',
      'symphony-composing', 'sculpture-chiseling', 'tapestry-weaving', 'origami-folding', 'mosaic-placing',
      'stained-glass-making', 'pottery-throwing', 'jewelry-crafting', 'song-humming', 'dance-choreographing'
    ],
    processing: [
      // Original professional words
      'orchestrating', 'coordinating', 'executing', 'performing', 'operating', 'finalizing',
      'compiling', 'rendering', 'encoding', 'transforming', 'streaming', 'buffering',
      'indexing', 'sorting', 'filtering', 'aggregating', 'consolidating', 'reconciling',
      // More cute additions
      'data-dancing', 'bit-ballet', 'byte-boogie', 'algorithm-aerobics', 'code-choreography',
      'digital-disco', 'cyber-spinning', 'tech-tap-dancing', 'silicon-salsa', 'binary-breakdancing',
      'packet-prancing', 'signal-swaying', 'frequency-flowing', 'wave-waltzing', 'stream-streaming',
      // Extra fun ones
      'cpu-conga-lining', 'ram-rumba-ing', 'gpu-grooving', 'ssd-swing-dancing', 'usb-upbeat-ing',
      'wifi-waving', 'bluetooth-bebop-ing', 'ethernet-electric-sliding', 'fiber-optic-funking'
    ],
    reasoning: [
      // Original professional words
      'deducing', 'inferring', 'concluding', 'deriving', 'extrapolating', 'correlating',
      'connecting', 'linking', 'associating', 'synthesizing', 'integrating', 'consolidating',
      'cross-referencing', 'triangulating', 'validating', 'verifying', 'confirming', 'substantiating',
      // More cute additions
      'puzzle-piecing', 'dot-connecting', 'thread-following', 'logic-linking', 'pattern-matching',
      'clue-connecting', 'mystery-solving', 'riddle-unraveling', 'brain-bridging', 'insight-weaving',
      'thought-threading', 'idea-intertwining', 'concept-coupling', 'wisdom-weaving', 'truth-tracking',
      // Extra fun ones
      'sherlock-deducing', 'einstein-theorizing', 'aristotle-philosophizing', 'socrates-questioning',
      'da-vinci-connecting', 'tesla-inventing', 'newton-discovering', 'galileo-observing'
    ],
    researching: [
      // Original professional words
      'investigating', 'exploring', 'discovering', 'uncovering', 'mining', 'extracting',
      'gathering', 'collecting', 'sourcing', 'retrieving', 'indexing', 'cataloging',
      'curating', 'surveying', 'mapping', 'documenting', 'chronicling', 'archiving',
      // More cute additions
      'treasure-hunting', 'knowledge-seeking', 'fact-fishing', 'info-adventuring', 'data-diving',
      'wisdom-wandering', 'curiosity-following', 'discovery-dancing', 'learning-leaping', 'insight-seeking',
      'truth-tracking', 'evidence-exploring', 'clue-chasing', 'answer-hunting', 'secret-searching',
      // Extra fun ones
      'library-spelunking', 'archive-archeology-ing', 'database-deep-diving', 'internet-archaeology',
      'knowledge-base-spelunking', 'fact-fossil-hunting', 'info-expedition-leading', 'data-safari-guiding'
    ],
    optimizing: [
      // Original professional words
      'refining', 'enhancing', 'improving', 'streamlining', 'perfecting', 'polishing',
      'tuning', 'calibrating', 'adjusting', 'tweaking', 'fine-tuning', 'balancing',
      'harmonizing', 'stabilizing', 'maximizing', 'minimizing', 'accelerating', 'upgrading',
      // More cute additions
      'sparkle-adding', 'shine-boosting', 'perfection-pursuing', 'beauty-buffing', 'elegance-enhancing',
      'smoothness-sculpting', 'efficiency-elevating', 'performance-pampering', 'speed-sprucing', 'quality-quilting',
      'precision-polishing', 'excellence-editing', 'flawless-finishing', 'magic-maximizing', 'awesome-amplifying',
      // Extra fun ones
      'diamond-polishing', 'gold-refining', 'silk-smoothing', 'butter-softening', 'honey-sweetening',
      'rainbow-brightening', 'star-shining', 'crystal-clarifying', 'pearl-lustening', 'gem-gleaming'
    ]
  };

  // Progress completion messages with style
  private static readonly COMPLETION_MESSAGES = [
    '✨ All done!',
    '🎉 Complete!', 
    '🚀 Finished!',
    '⭐ Ready!',
    '🎯 Success!',
    '💫 Perfect!',
    '🌟 Brilliant!',
    '🎪 Ta-da!',
    '🏆 Nailed it!',
    '💎 Flawless!'
  ];

  // Default phases for different operations
  static readonly DEFAULT_PHASES: Record<string, StatusPhase[]> = {
    conversation: [
      { name: 'analyzing', emoji: '🔍', message: 'Reading your message and understanding context', animationType: 'analyzing', estimatedDuration: 2500 },
      { name: 'reasoning', emoji: '🧠', message: 'Thinking through the problem space', animationType: 'reasoning', estimatedDuration: 3500 },
      { name: 'researching', emoji: '🕵️', message: 'Gathering relevant information and tools', animationType: 'researching', estimatedDuration: 3000 },
      { name: 'creating', emoji: '📝', message: 'Crafting the perfect response', animationType: 'creating', estimatedDuration: 2000 },
      { name: 'optimizing', emoji: '⚡', message: 'Adding final touches and polish', animationType: 'optimizing', estimatedDuration: 1500 }
    ],
    dispatch: [
      { name: 'parsing', emoji: '🔍', message: 'Understanding your dispatch requirements', animationType: 'analyzing', estimatedDuration: 1500 },
      { name: 'reasoning', emoji: '🧩', message: 'Selecting the best agent for this task', animationType: 'reasoning', estimatedDuration: 2500 },
      { name: 'creating', emoji: '📋', message: 'Creating GitHub issue with full context', animationType: 'creating', estimatedDuration: 3500 },
      { name: 'optimizing', emoji: '🎯', message: 'Setting up optimal agent workflow', animationType: 'optimizing', estimatedDuration: 1500 }
    ],
    factory_analysis: [
      { name: 'researching', emoji: '📊', message: 'Scanning factory metrics and health data', animationType: 'researching', estimatedDuration: 3000 },
      { name: 'analyzing', emoji: '🔬', message: 'Deep-diving into system performance', animationType: 'analyzing', estimatedDuration: 4000 },
      { name: 'reasoning', emoji: '🧠', message: 'Identifying patterns and correlations', animationType: 'reasoning', estimatedDuration: 2500 },
      { name: 'creating', emoji: '📋', message: 'Compiling comprehensive status report', animationType: 'creating', estimatedDuration: 2000 }
    ],
    code_analysis: [
      { name: 'researching', emoji: '🕵️', message: 'Exploring codebase structure and files', animationType: 'researching', estimatedDuration: 3500 },
      { name: 'analyzing', emoji: '🔬', message: 'Reviewing code quality and patterns', animationType: 'analyzing', estimatedDuration: 4500 },
      { name: 'reasoning', emoji: '🧩', message: 'Determining optimal solutions', animationType: 'reasoning', estimatedDuration: 3000 },
      { name: 'creating', emoji: '🛠️', message: 'Building implementation strategy', animationType: 'creating', estimatedDuration: 2500 }
    ]
  };

  static async start(config: StatusAnimatorConfig): Promise<string> {
    const { channel, threadTs, client, phases, animationInterval = 1800 } = config; // Faster updates for more dynamic feel
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

      // Start animation loop - faster for more lively feel
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
      const phases = StatusAnimator.DEFAULT_PHASES.conversation || [];
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

    // Progress bar like Claude Code with Unicode block characters
    const progressBar = this.createProgressBar(phaseIndex, totalPhases);

    // Random completion message if at final phase
    const isLastPhase = phaseIndex === totalPhases - 1;
    const completionMessage = isLastPhase ? 
      this.COMPLETION_MESSAGES[animationFrame % this.COMPLETION_MESSAGES.length] : 
      '';

    // Format like Claude Code with clean structure
    return `${animatedEmoji} **${dynamicVerb}...** ${progress}

${progressBar}

${isLastPhase ? `${completionMessage} ` : ''}_${phase.message}_`;
  }

  private static createProgressBar(current: number, total: number): string {
    const width = 24; // Slightly wider for better visual
    const filled = Math.floor(((current + 1) / total) * width);
    const empty = width - filled;

    // Use different Unicode characters for a more polished look
    const filledBar = '█'.repeat(filled);
    const partialBar = current + 1 < total && filled < width ? '▓' : '';
    const emptyBar = '░'.repeat(Math.max(0, empty - (partialBar ? 1 : 0)));
    const percentage = Math.round(((current + 1) / total) * 100);

    return `\`${filledBar}${partialBar}${emptyBar}\` ${percentage}%`;
  }

  // Utility method to get default phases for an operation type
  static getPhasesForOperation(operation: keyof typeof StatusAnimator.DEFAULT_PHASES): StatusPhase[] {
    return this.DEFAULT_PHASES[operation] || this.DEFAULT_PHASES.conversation;
  }
}

export default StatusAnimator;