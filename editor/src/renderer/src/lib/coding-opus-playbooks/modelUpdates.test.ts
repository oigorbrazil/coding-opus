import { parse } from 'yaml'
import { describe, expect, it } from 'vitest'
import { applyModelUpdates, modelFamily, planModelUpdates } from './modelUpdates'

const PLAYBOOKS = `version: 1
models:
  codex: [gpt-6-sol, gpt-6.1-sol, gpt-6-astra, gpt-5.6-luna]
  claude: [claude-sonnet-5, claude-opus-5-5]
tiers:
  cheap:
    codex: { model: gpt-5.6-luna }
  standard:
    codex: { model: gpt-6-sol, effort: medium }
    claude: { model: claude-sonnet-5 }
  strong:
    codex: { model: gpt-6-astra }
    claude: { model: claude-opus-5-5 }
routing:
  roles:
    - { name: builder, agent: codex, model: gpt-6-sol }
`

const CATALOG = {
  providers: {
    codex: [
      { id: 'gpt-6.1-sol', source: 'cli' as const, description: 'Latest workhorse model.' },
      { id: 'gpt-6-astra', source: 'cli' as const },
      { id: 'gpt-6-luna', source: 'cli' as const, description: 'Fast and affordable.' },
      { id: 'gpt-6.1-terra', source: 'cli' as const },
      { id: 'gpt-5.6-luna', source: 'cli' as const, upgrade: 'gpt-6-luna' }
    ],
    claude: [
      { id: 'claude-sonnet-5-5', source: 'prices' as const },
      { id: 'claude-haiku-4-5-20251001', source: 'prices' as const }
    ]
  }
}

describe('modelFamily', () => {
  it('splits a model id into its family and version', () => {
    expect(modelFamily('gpt-6.1-sol')).toEqual({ key: 'gpt-#-sol', version: [6, 1] })
    expect(modelFamily('claude-opus-5-5')).toEqual({ key: 'claude-opus-#', version: [5, 5] })
    expect(modelFamily('claude-sonnet-5')).toEqual({ key: 'claude-sonnet-#', version: [5] })
    expect(modelFamily('claude-haiku-4-5-20251001')?.key).toBe('claude-haiku-#-20251001')
    expect(modelFamily('sonnet')).toBeNull()
  })
})

describe('planModelUpdates', () => {
  it('suggests the newest model of the same family for every model the playbooks use', () => {
    const plan = planModelUpdates(PLAYBOOKS, CATALOG)
    expect(
      plan.upgrades.map(({ provider, from, to, uses, cliSays }) => [
        provider,
        from,
        to,
        uses,
        cliSays
      ])
    ).toEqual([
      ['codex', 'gpt-6-sol', 'gpt-6.1-sol', 2, false],
      ['codex', 'gpt-5.6-luna', 'gpt-6-luna', 1, true],
      ['claude', 'claude-sonnet-5', 'claude-sonnet-5-5', 1, false]
    ])
    expect(plan.additions.map((addition) => addition.model)).toEqual([
      'gpt-6-luna',
      'gpt-6.1-terra'
    ])
  })
})

describe('applyModelUpdates', () => {
  it('switches the uses, keeps the older models listed and adds the chosen new ones', () => {
    const plan = planModelUpdates(PLAYBOOKS, CATALOG)
    const doc = parse(
      applyModelUpdates(PLAYBOOKS, plan.upgrades.slice(0, 1), plan.additions.slice(1))
    )
    expect(doc.tiers.standard.codex).toEqual({ model: 'gpt-6.1-sol', effort: 'medium' })
    expect(doc.routing.roles[0].model).toBe('gpt-6.1-sol')
    expect(doc.tiers.cheap.codex.model).toBe('gpt-5.6-luna')
    expect(doc.models.codex).toEqual([
      'gpt-6-sol',
      'gpt-6.1-sol',
      'gpt-6-astra',
      'gpt-5.6-luna',
      'gpt-6.1-terra'
    ])
  })
})
