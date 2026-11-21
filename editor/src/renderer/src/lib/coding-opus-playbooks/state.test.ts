import { describe, expect, it } from 'vitest'
import {
  context,
  createPlaybooksState,
  phaseAlts,
  phaseBase,
  type Phase,
  type PlaybookWorkflow,
  playbookLock,
  playbookTwin,
  resolvePhase,
  selectPlaybookProvider,
  playbooksForProvider,
  toYaml
} from './state'

const TEXT = `version: 1
providers: [claude, codex]
tiers:
  strong:
    claude: { model: opus }
    codex: { model: gpt-6.1-sol, effort: high }
playbooks:
  direct:
    name: Direct
    phases:
      - id: plan
        role: planner
        who: lead
        tier: strong
`

describe('phaseBase for a lead phase', () => {
  const s = createPlaybooksState(TEXT)

  it('uses the first provider when the phase pins none', () => {
    const p: Phase = { id: 'plan', who: 'lead', tier: 'strong' }
    expect(phaseBase(s, p).provider).toBe('claude')
  })

  it('honors the provider the lead phase pins', () => {
    const p: Phase = { id: 'plan', who: 'lead', tier: 'strong', provider: 'codex' }
    expect(phaseBase(s, p).provider).toBe('codex')
  })

  it('drops a model that belongs to another provider', () => {
    const p: Phase = { id: 'plan', who: 'lead', tier: 'strong', provider: 'codex', model: 'opus' }
    expect(phaseBase(s, p).model).toBeNull()
  })
})

it('keeps worker simulation in the selected playbook family', () => {
  const s = createPlaybooksState(`version: 1
providers: [claude, agy, codex]
quota: { whenLow: switch-provider }
tiers:
  standard:
    claude: { model: sonnet }
    agy: { model: claude-opus-4-6-thinking }
    codex: { model: gpt-6.1-sol }
  strong:
    agy: { model: claude-opus-4-6-thinking }
playbooks:
  review-claude:
    name: Review gate
    family: claude
    phases: [{ id: review, tier: standard }]
  review-other:
    name: Review gate
    family: other
    phases: [{ id: review, tier: standard }]
`)
  const claude = s.workflows['playbook:review-claude'] as PlaybookWorkflow
  const other = s.workflows['playbook:review-other'] as PlaybookWorkflow
  const current = context(s)
  expect(playbookTwin(s, claude.pb)?.key).toBe('review-other')
  expect(resolvePhase(s, claude.pb.phases[0], { ...current, low: ['claude'] })).toMatchObject({
    stuck: true,
    final: { provider: 'claude' }
  })
  expect(
    resolvePhase(s, other.pb.phases[0], { ...current, spare: ['claude', 'agy'] })
  ).toMatchObject({
    stuck: false,
    final: { provider: 'codex' }
  })
  expect(phaseAlts(s, other.pb.phases[0])).toEqual([])
})

it('selects the same strategy and previews only the chosen provider without saving the choice', () => {
  const state = createPlaybooksState(`version: 1
providers: [claude, codex, agy, kimi]
quota: { whenLow: switch-provider, whenSpare: prefer }
tiers:
  standard:
    claude: { model: sonnet }
    codex: { model: gpt-6.1-sol }
    agy: { model: gemini-3.8-flash-high }
playbooks:
  review-claude:
    name: Review gate
    family: claude
    phases: [{ id: review, tier: standard, readOnly: true }]
  review-other:
    name: Review gate
    family: other
    phases: [{ id: review, tier: standard, readOnly: true, provider: codex }]
`)
  const saved = toYaml(state)
  const checkProvider = (
    provider: string,
    playbook: string,
    model: string | null,
    unavailable = false
  ) => {
    selectPlaybookProvider(state, provider)
    const visible = playbooksForProvider(state, provider)
    expect(visible.map((w) => w.key)).toEqual([playbook])
    expect(state.wf).toBe(visible[0].id)
    const phase = visible[0].pb.phases[0]
    expect(
      resolvePhase(state, phase, { ...context(state), spare: ['claude', 'codex', 'agy'] })
    ).toMatchObject({
      final: { provider, model },
      switched: false,
      stuck: unavailable,
      previewUnsupported: unavailable
    })
    expect(phaseAlts(state, phase)).toEqual([])
  }
  checkProvider('claude', 'review-claude', 'sonnet')
  checkProvider('codex', 'review-other', 'gpt-6.1-sol')
  checkProvider('agy', 'review-other', 'gemini-3.8-flash-high')
  checkProvider('kimi', 'review-other', null, true)
  expect(toYaml(state)).toBe(saved)
})

const TEAMS = `version: 1
providers: [claude, codex]
quota: { whenLow: switch-provider }
tiers:
  standard:
    claude: { model: sonnet }
    codex: { model: gpt-6.1-sol }
playbooks:
  claude-team:
    name: Claude team
    phases:
      - { id: plan, who: lead, tier: strong }
      - { id: build, tier: standard, provider: claude }
  gpt-team:
    name: GPT team
    phases:
      - { id: plan, who: lead, tier: strong }
      - { id: build, tier: standard, provider: codex }
  mixed:
    name: Mixed
    phases:
      - { id: plan, who: lead, tier: strong }
      - { id: build, tier: standard }
`

describe('single-provider playbooks', () => {
  const s = createPlaybooksState(TEAMS)
  const book = (key: string) =>
    Object.values(s.workflows).find(
      (w): w is PlaybookWorkflow => w.kind === 'playbook' && w.key === key
    )!
  const build = (key: string) => book(key).pb.phases.find((p) => p.id === 'build')!
  const claudeLow = { ...context(s), low: ['claude'] }

  it('knows which playbooks run on one provider, and their twins', () => {
    expect(playbookLock(book('claude-team').pb)).toBe('claude')
    expect(playbookLock(book('gpt-team').pb)).toBe('codex')
    expect(playbookLock(book('mixed').pb)).toBeNull()
    expect(playbookTwin(s, book('claude-team').pb)?.key).toBe('gpt-team')
    expect(playbookTwin(s, book('mixed').pb)).toBeNull()
  })

  it('draws no quota switch to another provider for a locked playbook', () => {
    expect(phaseAlts(s, build('claude-team')).some((alt) => alt.implicit)).toBe(false)
    expect(phaseAlts(s, build('mixed')).some((alt) => alt.implicit)).toBe(true)
  })

  it('treats a recompiled copy of a phase as part of the open playbook', () => {
    const open = (key: string) => ({ ...s, wf: book(key).id })
    expect(
      phaseAlts(open('claude-team'), { ...build('claude-team') }).some((alt) => alt.implicit)
    ).toBe(false)
    expect(phaseAlts(open('mixed'), { ...build('mixed') }).some((alt) => alt.implicit)).toBe(true)
  })

  it('stops instead of switching when the locked provider is low', () => {
    const locked = resolvePhase(s, build('claude-team'), claudeLow)
    expect([locked.switched, locked.stuck, locked.locked, locked.final.provider]).toEqual([
      false,
      true,
      'claude',
      'claude'
    ])
    const mixed = resolvePhase(s, build('mixed'), claudeLow)
    expect([mixed.switched, mixed.locked, mixed.final.provider]).toEqual([true, null, 'codex'])
  })
})
