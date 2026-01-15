/**
 * Spinning emoji animation system for Claude Code status updates
 * Provides continuous visual feedback during long operations
 */

export class SpinnerAnimation {
  private static readonly SPINNER_FRAMES = ['◐', '◓', '◑', '◒'];
  private static frameIndex = 0;

  /**
   * Get the next frame in the spinner animation
   */
  static getNextFrame(): string {
    const frame = this.SPINNER_FRAMES[this.frameIndex];
    this.frameIndex = (this.frameIndex + 1) % this.SPINNER_FRAMES.length;
    return frame;
  }

  /**
   * Format a status message with spinning animation
   */
  static formatStatus(message: string, phase?: { current: number; total: number }): string {
    const spinner = this.getNextFrame();
    const phaseInfo = phase ? `Phase ${phase.current}/${phase.total}: ` : '';
    return `${spinner} _${phaseInfo}${message}_`;
  }

  /**
   * Format a completion message
   */
  static formatComplete(message: string, phase?: { current: number; total: number }): string {
    const phaseInfo = phase ? `Phase ${phase.current}/${phase.total} complete!` : 'Complete!';
    return `✅ _${phaseInfo}_ ${message}`;
  }

  /**
   * Reset animation to start from first frame
   */
  static reset(): void {
    this.frameIndex = 0;
  }
}

/**
 * Live status update protocols for Claude Code sessions
 */
export class LiveStatusProtocol {
  private static readonly MAX_SILENT_OPERATIONS = 2;
  private static readonly UPDATE_INTERVAL_MS = 500; // 0.5 seconds

  private operationCount = 0;
  private lastUpdateTime = Date.now();

  /**
   * Check if a status update is needed
   */
  shouldUpdate(): boolean {
    const timeSinceUpdate = Date.now() - this.lastUpdateTime;
    return (
      this.operationCount >= LiveStatusProtocol.MAX_SILENT_OPERATIONS ||
      timeSinceUpdate >= LiveStatusProtocol.UPDATE_INTERVAL_MS
    );
  }

  /**
   * Record an operation and update timestamp if needed
   */
  recordOperation(): boolean {
    this.operationCount++;

    if (this.shouldUpdate()) {
      this.operationCount = 0;
      this.lastUpdateTime = Date.now();
      return true; // Should send update
    }

    return false; // No update needed
  }

  /**
   * Force an update (for phase transitions)
   */
  forceUpdate(): void {
    this.operationCount = 0;
    this.lastUpdateTime = Date.now();
  }
}