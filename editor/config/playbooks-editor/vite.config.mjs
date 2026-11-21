import { copyFileSync, readFileSync, writeFileSync, readdirSync, rmSync } from 'node:fs'
import { join, resolve } from 'node:path'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const here = import.meta.dirname
const renderer = resolve(here, '../../src/renderer/src')
const stubs = resolve(here, 'stubs.tsx')
const outDir = resolve(here, '../../out')
const skillPage = resolve(here, '../../../skills/coding/assets/editor.html')

/** Folds the built script and stylesheet into index.html, so the skill ships one self-contained page. */
function inlineIntoSingleFile() {
  return {
    name: 'inline-into-single-file',
    closeBundle() {
      const htmlPath = join(outDir, 'index.html')
      let html = readFileSync(htmlPath, 'utf8')
      const assets = join(outDir, 'assets')
      for (const file of readdirSync(assets)) {
        const content = readFileSync(join(assets, file), 'utf8').replaceAll(
          '</script',
          '<\\/script'
        )
        if (file.endsWith('.js')) {
          html = html.replace(
            new RegExp(`<script type="module" crossorigin src="[^"]*${file}"></script>`),
            () => `<script type="module">${content}</script>`
          )
        } else if (file.endsWith('.css')) {
          html = html.replace(
            new RegExp(`<link rel="stylesheet" crossorigin href="[^"]*${file}">`),
            () => `<style>${content}</style>`
          )
        }
      }
      const startupShader = readFileSync(join(here, 'startup-shaders.ts'), 'utf8')
      const license = /^\/\*!([\s\S]*?)\*\//.exec(startupShader)?.[1]
      if (license) {
        html = html.replace('</head>', `<!--${license}-->\n</head>`)
      }
      writeFileSync(join(outDir, 'editor.html'), html)
      rmSync(assets, { recursive: true, force: true })
      rmSync(htmlPath)
      // The skill serves this page from its assets folder (orchestrate.py editor).
      if (process.env.CODING_OPUS_EDITOR_NO_COPY !== '1') {
        copyFileSync(join(outDir, 'editor.html'), skillPage)
      }
    }
  }
}

export default defineConfig({
  root: here,
  base: './',
  plugins: [react(), inlineIntoSingleFile()],
  resolve: {
    alias: [
      { find: '@/i18n/i18n', replacement: stubs },
      { find: '@/i18n/use-ui-language-revision', replacement: stubs },
      { find: '@/lib/agent-catalog', replacement: stubs },
      { find: /^sonner$/, replacement: stubs },
      { find: '@', replacement: renderer }
    ]
  },
  build: {
    outDir,
    emptyOutDir: true,
    assetsInlineLimit: 100_000_000,
    cssCodeSplit: false,
    rollupOptions: { output: { inlineDynamicImports: true } }
  }
})
