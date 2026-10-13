import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'node:path'
const root = path.resolve(import.meta.dirname, '..')
export default defineConfig({
  root,
  plugins: [react()],
  resolve: { alias: { '@': path.resolve(root, 'src') } },
  test: { environment: 'jsdom', globals: true, setupFiles: [path.resolve(root, 'src/test/setup.ts')],
    include: ['validation/portal-flow.integration.tsx'], testTimeout: 60000 },
})
