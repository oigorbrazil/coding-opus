// @vitest-environment happy-dom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { PlaybooksEditor } from '../../components/settings/coding-opus/playbooks/PlaybooksEditor'
import { attachDocs } from './flowView'
import { createPlaybooksState } from './state'
import { parsePlaybooksYaml } from './yaml'

const { save } = vi.hoisted(() => ({ save: vi.fn() }))
vi.mock('./host', () => ({
  orchestratorSavePlaybooks: save,
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
providers: [claude, codex]
profile: base
profiles:
  base: { name: Base }
  savings: { name: Savings }
  aggressive: { name: Aggressive }
playbooks:
  direct:
    name: Direct
    phases:
      - id: plan
        who: lead
        tier: strong
`

function mount(backupText?: string) {
  vi.useFakeTimers()
  save.mockReset().mockImplementation(async (yaml: string) => ({
    text: yaml,
    path: '/playbooks.yaml',
    custom: true
  }))
  const initial = createPlaybooksState(text)
  attachDocs(initial)
  return render(
    <PlaybooksEditor
      file={{ text, path: '/playbooks.yaml', custom: true, backupText }}
      initial={initial}
      onSaved={() => undefined}
      onDiscard={() => undefined}
    />
  )
}
const click = (name: string) => fireEvent.click(screen.getByRole('button', { name }))
const chooseProfile = (name: string) => {
  click('playbooks.profileLabel')
  fireEvent.click(screen.getByRole('option', { name }))
}
const flushSave = () =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(1000)
  })
const savedProfile = () =>
  // oxlint-disable-next-line typescript/consistent-type-assertions -- SAFETY: test reads a known fixture shape.
  (parsePlaybooksYaml(save.mock.lastCall![0]) as { profile: string }).profile

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

it('persists undo during an in-flight save, then redoes the edit', async () => {
  const { container } = mount()
  let finish!: (value: unknown) => void
  save.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve
      })
  )
  chooseProfile('Savings')
  await flushSave()
  fireEvent.keyDown(container.querySelector('button')!, { key: 'z', ctrlKey: true })
  await act(async () => {
    finish({ text: '', path: '/playbooks.yaml', custom: true })
  })
  await flushSave()
  expect(savedProfile()).toBe('base')
  fireEvent.keyDown(container.querySelector('button')!, { key: 'Z', ctrlKey: true, shiftKey: true })
  await flushSave()
  expect(savedProfile()).toBe('savings')
})

it('drops the redo branch when a new edit follows undo', async () => {
  mount()
  chooseProfile('Savings')
  click('playbooks.undo')
  chooseProfile('Aggressive')
  expect(
    // oxlint-disable-next-line typescript/consistent-type-assertions -- SAFETY: test reads a known fixture shape.
    (screen.getByRole('button', { name: 'playbooks.redo' }) as HTMLButtonElement).disabled
  ).toBe(true)
  await flushSave()
  expect(savedProfile()).toBe('aggressive')
})

it('restores the backup through autosave and can undo the restoration', async () => {
  mount(text.replace('profile: base', 'profile: savings'))
  fireEvent.click(screen.getByText('playbooks.fileTools'))
  click('playbooks.restoreBackup')
  await flushSave()
  expect(savedProfile()).toBe('savings')
  click('playbooks.undo')
  await flushSave()
  expect(savedProfile()).toBe('base')
})
