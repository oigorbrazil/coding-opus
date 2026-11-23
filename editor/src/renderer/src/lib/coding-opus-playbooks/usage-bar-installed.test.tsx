// @vitest-environment happy-dom
import { act, cleanup, render } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { PlaybooksEditor } from '../../components/settings/coding-opus/playbooks/PlaybooksEditor'
import { attachDocs } from './flowView'
import { createPlaybooksState } from './state'

vi.mock('./host', () => ({
  orchestratorSavePlaybooks: vi.fn(),
  getClaudeUsage: undefined,
  getCachedCodexUsage: undefined,
  useAppliedTheme: () => 'dark',
  isLightTheme: () => false,
  readScopedStorage: () => null,
  writeScopedStorage: () => undefined,
  agentAccentVar: () => 'var(--foreground)',
  pushToast: vi.fn()
}))
vi.mock('./i18n', () => ({ useT: () => (key: string) => key }))
vi.mock('@/lib/agent-catalog', () => ({ AgentIcon: () => null }))

const text = `version: 1
providers: [claude, codex, agy, kimi]
playbooks:
  direct:
    name: Direct
    phases:
      - id: work
        provider: claude
`

const cli = (id: string, installed: boolean) => ({
  id,
  label: id,
  kind: 'builtin' as const,
  installed,
  version: installed ? '1.0' : null,
  executable: installed ? `/bin/${id}` : null,
  loggedIn: null
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

/** The usage pills: one button per provider, titled by the usage messages. */
const pills = (container: HTMLElement) =>
  [...container.querySelectorAll('button[title^="playbooks.usage"]')].length

it('shows only the providers installed on this computer in the usage bar', async () => {
  let answer!: (value: unknown) => void
  const detectClis = vi.fn(() => new Promise((resolve) => (answer = resolve)))
  vi.stubGlobal('api', { codingOpus: { detectClis } })
  const initial = createPlaybooksState(text)
  attachDocs(initial)
  const { container } = render(
    <PlaybooksEditor
      file={{ text, path: '/playbooks.yaml', custom: true }}
      initial={initial}
      onSaved={() => undefined}
      onDiscard={() => undefined}
    />
  )
  // Until detection answers, every configured provider is shown.
  expect(pills(container)).toBe(4)
  await act(async () => {
    answer({
      ok: true,
      clis: [cli('claude', true), cli('codex', true), cli('agy', false), cli('kimi', false)]
    })
  })
  expect(pills(container)).toBe(2)
  expect(detectClis).toHaveBeenCalledTimes(1)
})
