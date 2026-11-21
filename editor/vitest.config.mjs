import { resolve } from 'node:path'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const here = import.meta.dirname
const stubs = resolve(here, 'config/playbooks-editor/stubs.tsx')

// Same aliases as the build: desktop-only modules resolve to the standalone stubs.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: [
      { find: '@/i18n/i18n', replacement: stubs },
      { find: '@/i18n/use-ui-language-revision', replacement: stubs },
      { find: '@/lib/agent-catalog', replacement: stubs },
      { find: /^sonner$/, replacement: stubs },
      { find: '@', replacement: resolve(here, 'src/renderer/src') }
    ]
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx']
  }
})
