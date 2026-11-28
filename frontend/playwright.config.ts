import { defineConfig, devices } from '@playwright/test';

import { stack } from './tests/browser/support/stack.ts';

// The browser journeys run against the disposable stack that the global setup starts: a
// PostgreSQL container of its own, the real API and the built application (tests/browser/support).
// They never use the owner's database (D-015).
export default defineConfig({
  testDir: './tests/browser',
  testMatch: '**/*.spec.ts',
  outputDir: './test-results',
  globalSetup: './tests/browser/support/global-setup.ts',
  // One stack and one mailbox serve every journey, so the journeys run one after another.
  fullyParallel: false,
  workers: 1,
  forbidOnly: true,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 10_000 },
  reporter: [['list']],
  use: {
    baseURL: stack.webOrigin,
    locale: 'en-US',
    timezoneId: 'UTC',
    colorScheme: 'light',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'firefox', use: { ...devices['Desktop Firefox'] } },
  ],
});
