import { defineConfig, devices } from '@playwright/test'

/**
 * End-to-end: a real browser against the Vite app and the LIVE FastAPI service (+ PostgreSQL).
 *   Start the API first (.venv/bin/uvicorn nba_lineups.api.main:app), then: npm run test:e2e
 * The dev server is started automatically unless one is already running on :5173.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 45_000,
  expect: { timeout: 15_000 },
  fullyParallel: true,
  reporter: [['list']],
  use: { baseURL: 'http://localhost:5173', trace: 'retain-on-failure' },
  webServer: { command: 'npm run dev', url: 'http://localhost:5173', reuseExistingServer: true, timeout: 60_000 },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } }, testIgnore: /responsive\.spec\.ts/ },
    { name: 'mobile', use: { ...devices['Pixel 7'] }, testMatch: /responsive\.spec\.ts/ },
  ],
})
