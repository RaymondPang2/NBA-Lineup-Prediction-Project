/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Dev and preview both serve on 5173, the origin the API allows by default (NBA_API_CORS_ORIGINS).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, strictPort: true },
  preview: { port: 5173, strictPort: true },
  build: {
    rollupOptions: {
      output: { manualChunks: (id) => (id.includes('node_modules/recharts') || id.includes('node_modules/d3-') ? 'charts' : undefined) },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    exclude: ['src/**/*.integration.test.ts', 'node_modules/**'],
    css: false,
  },
})
