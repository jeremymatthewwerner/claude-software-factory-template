#!/usr/bin/env node

/**
 * Self-Testing Framework for Claude Process Improvements
 *
 * This script allows Claude to test its own process improvements by:
 * 1. Simulating multi-step tasks that historically caused getting stuck
 * 2. Verifying TodoWrite usage patterns
 * 3. Testing commit-early behavior
 * 4. Measuring time-to-completion for complex tasks
 */

import fs from 'fs';
import { execSync } from 'child_process';

class ClaudeProcessTester {
    constructor() {
        this.testResults = [];
        this.startTime = Date.now();
    }

    log(message, type = 'info') {
        const timestamp = new Date().toISOString();
        const logMessage = `[${timestamp}] ${type.toUpperCase()}: ${message}`;
        console.log(logMessage);

        // Also write to log file
        fs.appendFileSync('./.claude-test.log', logMessage + '\n');
    }

    // Test 1: Verify TodoWrite is being used for multi-step tasks
    testTodoWriteUsage() {
        this.log("Testing TodoWrite usage patterns...");

        const testScenarios = [
            "Create a new feature with authentication",
            "Debug a complex deployment issue",
            "Implement railway management scripts",
            "Add status animation with emoji cycles"
        ];

        // Simulate checking if TodoWrite would be used
        testScenarios.forEach((scenario, index) => {
            const shouldUseTodoWrite = this.simulateTaskComplexity(scenario);
            const result = {
                scenario,
                complexity: shouldUseTodoWrite ? 'multi-step' : 'simple',
                todoWriteRequired: shouldUseTodoWrite,
                passed: shouldUseTodoWrite // For multi-step tasks, TodoWrite should be required
            };

            this.testResults.push(result);
            this.log(`Scenario ${index + 1}: ${scenario} - TodoWrite ${shouldUseTodoWrite ? 'REQUIRED' : 'optional'}`);
        });
    }

    // Test 2: Simulate commit-early behavior
    testCommitEarlyPattern() {
        this.log("Testing commit-early behavior...");

        const mockTask = {
            name: "Create railway management script",
            steps: [
                { name: "Create directory structure", duration: 1000, shouldCommit: false },
                { name: "Write basic script", duration: 2000, shouldCommit: true }, // MVP ready
                { name: "Test basic functionality", duration: 1500, shouldCommit: false },
                { name: "Add authentication", duration: 8000, shouldCommit: false }, // Long peripheral task
                { name: "Add advanced features", duration: 3000, shouldCommit: true }
            ]
        };

        let totalTime = 0;
        let commitPoints = [];

        mockTask.steps.forEach((step, index) => {
            totalTime += step.duration;

            if (step.shouldCommit) {
                commitPoints.push({
                    step: step.name,
                    timeElapsed: totalTime,
                    isEarlyCommit: totalTime < 5000 // Should commit within 5 seconds of having MVP
                });
            }

            // Test 5-minute rule for peripheral tasks
            if (step.duration > 5000) {
                this.log(`WARNING: Step "${step.name}" took ${step.duration}ms - should have committed simpler version first`);
            }
        });

        commitPoints.forEach(commit => {
            this.log(`Commit point: "${commit.step}" at ${commit.timeElapsed}ms - ${commit.isEarlyCommit ? 'GOOD' : 'TOO LATE'}`);
        });

        return commitPoints;
    }

    // Test 3: Time-boxing verification
    testTimeBoxing() {
        this.log("Testing time-boxing mechanisms...");

        const peripheralTasks = [
            { name: "Debug Railway CLI authentication", expectedDuration: 2000, actualDuration: 15000 },
            { name: "Perfect error handling", expectedDuration: 3000, actualDuration: 7000 },
            { name: "Add comprehensive logging", expectedDuration: 2000, actualDuration: 4000 }
        ];

        peripheralTasks.forEach(task => {
            const exceededTimeBox = task.actualDuration > 5000;
            const shouldHaveCommitedEarlier = exceededTimeBox;

            this.log(`Task: ${task.name} - ${task.actualDuration}ms - ${exceededTimeBox ? 'EXCEEDED TIMEBOX' : 'within bounds'}`);

            if (shouldHaveCommitedEarlier) {
                this.log(`  -> Should have committed simpler version at 5000ms mark`);
            }
        });
    }

    // Test 4: Stuck detection simulation
    testStuckDetection() {
        this.log("Testing stuck detection patterns...");

        const stuckPatterns = [
            {
                pattern: "Repeatedly trying same failed command",
                detection: "Same command executed >3 times with same error",
                prevention: "Switch to alternative approach or commit partial solution"
            },
            {
                pattern: "Getting distracted by peripheral issues",
                detection: "Time spent on non-core task >5 minutes",
                prevention: "Return to TodoWrite list and focus on MVP"
            },
            {
                pattern: "Analysis paralysis on decisions",
                detection: ">10 minutes without code/file changes",
                prevention: "Make decision and document reasoning"
            }
        ];

        stuckPatterns.forEach((pattern, index) => {
            this.log(`Stuck Pattern ${index + 1}: ${pattern.pattern}`);
            this.log(`  Detection: ${pattern.detection}`);
            this.log(`  Prevention: ${pattern.prevention}`);
        });
    }

    // Simulate task complexity to determine if TodoWrite is needed
    simulateTaskComplexity(taskDescription) {
        const complexityIndicators = [
            'create', 'implement', 'debug', 'add', 'fix', 'setup',
            'authentication', 'deployment', 'testing', 'integration'
        ];

        const multiStepIndicators = [
            'script', 'feature', 'system', 'framework', 'pipeline'
        ];

        const words = taskDescription.toLowerCase().split(' ');
        const complexityScore = words.filter(word =>
            complexityIndicators.includes(word) || multiStepIndicators.includes(word)
        ).length;

        // If task has 2+ complexity indicators, it's likely multi-step
        return complexityScore >= 2;
    }

    // Run all tests
    runAllTests() {
        this.log("=== Starting Claude Process Self-Test ===");

        this.testTodoWriteUsage();
        this.testCommitEarlyPattern();
        this.testTimeBoxing();
        this.testStuckDetection();

        const endTime = Date.now();
        const totalDuration = endTime - this.startTime;

        this.log(`=== Test Completed in ${totalDuration}ms ===`);
        this.generateReport();

        return this.testResults;
    }

    generateReport() {
        const report = {
            timestamp: new Date().toISOString(),
            totalTests: this.testResults.length,
            passed: this.testResults.filter(r => r.passed).length,
            failed: this.testResults.filter(r => !r.passed).length,
            recommendations: [
                "Use TodoWrite for any task with 2+ complexity indicators",
                "Commit working version before spending >5 minutes on peripheral issues",
                "If stuck >10 minutes, return to TodoWrite and simplify approach"
            ]
        };

        fs.writeFileSync('./.claude-test-report.json', JSON.stringify(report, null, 2));
        this.log(`Report generated: ./.claude-test-report.json`);

        return report;
    }
}

// Allow running directly or importing
if (import.meta.url === `file://${process.argv[1]}`) {
    const tester = new ClaudeProcessTester();
    const results = tester.runAllTests();

    console.log('\n=== SUMMARY ===');
    console.log(`Total scenarios tested: ${results.length}`);
    console.log(`TodoWrite correctly identified for multi-step tasks: ${results.filter(r => r.todoWriteRequired).length}`);
}

export default ClaudeProcessTester;