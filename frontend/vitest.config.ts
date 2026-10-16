import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

export default defineConfig({
  plugins: [react()],
  test: {
    pool: 'forks',
    maxWorkers: 1,
    fileParallelism: false,
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    testTimeout: 15000,
  },
  resolve: {
    alias: { '@': path.resolve(path.dirname(fileURLToPath(import.meta.url)), './src') },
  },
})
