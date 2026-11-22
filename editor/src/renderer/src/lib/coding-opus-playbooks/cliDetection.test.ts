import { describe, expect, it } from 'vitest'
import { addProvider, cliStatus, type DetectedCli } from './cliDetection'
import { parsePlaybooksYaml } from './yaml'

const TEXT = `version: 1
setup:
  notes:
    - "Built-in: codex 0.167, claude 2.1.321, agy 1.5.3 (login not confirmed by doctor), kimi 2.4.1 (no model list)."
providers: [claude, codex]
profiles:
  base:
    name: Base
    order: [codex, claude]
  savings:
    name: Savings
adapters:
  opencode:
    command: opencode
    args: [run, --format, json]
    promptTransport: argument
    outputFormat: jsonl
playbooks: {}
`

const cli = (id: string, kind: DetectedCli['kind']): DetectedCli => ({
  id, label: id, kind, installed: true, version: '1.0', executable: `/bin/${id}`, loggedIn: null
})

describe('cliStatus', () => {
  it('separates configured, addable and adapter-less CLIs', () => {
    expect(cliStatus(TEXT, cli('claude', 'builtin'))).toBe('configured')
    expect(cliStatus(TEXT, cli('kimi', 'builtin'))).toBe('addable')
    expect(cliStatus(TEXT, cli('opencode', 'custom'))).toBe('addable')
    expect(cliStatus(TEXT, cli('gemini', 'custom'))).toBe('needs-adapter')
  })
})

describe('addProvider', () => {
  it('appends the provider and keeps the rest readable', () => {
    // oxlint-disable-next-line typescript/consistent-type-assertions -- SAFETY: the test builds this document.
    const doc = parsePlaybooksYaml(addProvider(TEXT, 'kimi')) as {
      providers: string[]
      profiles: Record<string, { order?: string[] }>
      setup: { notes: string[] }
      adapters: Record<string, unknown>
    }
    expect(doc.providers).toEqual(['claude', 'codex', 'kimi'])
    // Tried last in every profile that has its own order; a profile without one keeps none.
    expect(doc.profiles.base.order).toEqual(['codex', 'claude', 'kimi'])
    expect(doc.profiles.savings.order).toBeUndefined()
    expect(doc.setup.notes[0]).toContain('kimi 2.4.1')
    expect(Object.keys(doc.adapters)).toEqual(['opencode'])
  })

  it('leaves the text alone when the provider is already there', () => {
    expect(addProvider(TEXT, 'codex')).toBe(TEXT)
  })
})
