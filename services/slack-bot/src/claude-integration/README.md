# Claude Code Integration for Slack Bot

This directory contains utilities and protocols for Claude Code sessions running in the Slack bot environment.

## Live Status System

All Claude Code sessions should use the live status system to provide continuous feedback:

```typescript
import { createClaudeStatusManager, COMMON_PHASES } from '../utils/claude-status-manager.js';

// Create status manager with update callback
const statusManager = createClaudeStatusManager(async (message) => {
  // Update Slack message with new status
  await updateSlackMessage(message);
});

// Start multi-phase task
await statusManager.startTask([
  COMMON_PHASES.ANALYZE,
  COMMON_PHASES.IMPLEMENT,
  COMMON_PHASES.TEST
]);

// Provide frequent updates
await statusManager.updateStatus('Reading configuration files...');
await statusManager.updateStatus('Found 3 relevant components');

// Complete phases
await statusManager.completePhase('Requirements understood');
await statusManager.completeTask();
```

## Key Principles

### 1. Spinning Status Indicators
- Use `◐ ◓ ◑ ◒` spinner animation for continuous visual feedback
- Never show static "working..." for more than 2 operations
- Always indicate active processing

### 2. Phase-Based Progress
- Break complex tasks into 3-5 clear phases
- Show progress as "Phase 2/4: Implementing changes"
- Complete phases explicitly with checkmarks

### 3. Frequent Updates (1-2 Second Rule)
- Update status every 1-2 tool operations maximum
- Show specific actions: "Reading file X" not "processing"
- Never leave users wondering what's happening

### 4. TodoWrite Integration
- Use TodoWrite for all multi-step tasks (3+ operations)
- Track progress in real-time
- Mark phases complete immediately

## Anti-Stuck Protocols

### Time-Boxing Rules
- **5-minute rule**: Commit working version before debugging peripheral issues
- **10-minute rule**: If stuck on a decision, make a reasonable choice and document why
- **Emergency protocol**: Return to TodoList and deliver simpler version

### Commit-Early Pattern
- Commit minimum viable solution first
- Iterate and improve in subsequent commits
- Never let perfectionism block delivery

### Escalation Triggers
- Stuck >30 minutes → escalate to human
- CI fails 3x on same issue → escalate
- Architecture decision needed → escalate

## Usage Examples

### Simple Task (No Status Manager)
```typescript
// For simple 1-2 operation tasks, just use spinner directly
import { SpinnerAnimation } from '../utils/spinner-animation.js';

console.log(SpinnerAnimation.formatStatus('Checking file...'));
// File operations...
console.log(SpinnerAnimation.formatComplete('File updated!'));
```

### Complex Task (Full Status Manager)
```typescript
const phases = [
  { name: 'Understanding requirements', description: 'Analyzing the user request' },
  { name: 'Finding relevant files', description: 'Searching codebase for components' },
  { name: 'Implementing changes', description: 'Writing and testing code' },
  { name: 'Validating solution', description: 'Running tests and checks' }
];

await statusManager.startTask(phases);

// Phase 1
await statusManager.updateStatus('Reading user requirements...');
await statusManager.updateStatus('Identifying key components needed');
await statusManager.completePhase();

// Phase 2
await statusManager.updateStatus('Searching for React components...');
await statusManager.updateStatus('Found 5 relevant files');
await statusManager.completePhase();

// Continue for all phases...
await statusManager.completeTask('Feature implementation complete!');
```

## Integration Points

This system integrates with:
- **Slack message updates**: Status changes update the Slack thread in real-time
- **TodoWrite system**: Progress tracking syncs with todo completion
- **Error handling**: Recoverable vs non-recoverable error reporting
- **CI integration**: Status updates during build/test phases

## Testing

Run the self-test to validate adherence to protocols:

```bash
npm run claude-self-test
```

This validates:
- Proper TodoWrite usage patterns
- Commit timing compliance
- Time-boxing adherence
- Status update frequency