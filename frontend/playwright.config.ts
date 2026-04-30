import { defineConfig, devices } from '@playwright/test';

/**
 * E2E test configuration optimized for performance:
 * - fullyParallel: all tests run concurrently across workers
 * - No retries: tests must be deterministic; flakes are bugs
 * - Short global timeout: forces event-based waiting over polling
 * - Route interception: tests mock the backend — no server startup delay
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI ? 'github' : 'list',
  timeout: 10000,
  use: {
    baseURL: 'http://localhost:3000',
    trace: 'on-first-retry',
    // Never use waitForTimeout — rely on Playwright auto-waiting
    actionTimeout: 5000,
    navigationTimeout: 10000,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:3000',
    reuseExistingServer: !process.env.CI,
    timeout: 30000,
  },
});
