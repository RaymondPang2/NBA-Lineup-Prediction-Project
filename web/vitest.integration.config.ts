import { defineConfig } from 'vitest/config'

// Live frontend-backend integration: runs the app's own API client against a running FastAPI server.
//   API_BASE_URL defaults to http://127.0.0.1:8000/api/v1
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.integration.test.ts'],
    testTimeout: 30_000,
  },
})
