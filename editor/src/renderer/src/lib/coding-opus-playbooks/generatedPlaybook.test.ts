import { describe, expect, it } from 'vitest'
import { appendGeneratedPlaybook, generatedPlaybook } from './generatedPlaybook'
import { createPlaybooksState } from './state'

const initial = {
  version: 1,
  providers: ['codex'],
  tiers: { standard: { codex: { model: 'gpt-6.2-sol' } } },
  profiles: { base: {} },
  profile: 'base',
  playbooks: {
    existing: { name: 'Original', phases: [{ id: 'build', role: 'builder', tier: 'standard' }] }
  }
}
const proposal = {
  id: 'generated',
  text: JSON.stringify({
    ...initial,
    playbooks: {
      ...initial.playbooks,
      generated: {
        name: 'Generated review',
        goal: 'Review the change',
        phases: [{ id: 'review', role: 'reviewer', tier: 'standard', readOnly: true }]
      }
    }
  })
}

describe('generated playbook application', () => {
  it('merges only the new playbook and preserves edits made while generating', () => {
    const current = createPlaybooksState(JSON.stringify(initial))
    const existing = current.workflows['playbook:existing']
    if (existing.kind !== 'playbook') {
      throw new Error('Missing fixture playbook')
    }
    existing.pb.name = 'Edited during generation'
    current.profile = 'current-profile'
    const added = appendGeneratedPlaybook(current, proposal)
    expect(existing.pb.name).toBe('Edited during generation')
    expect(current.profile).toBe('current-profile')
    expect(added.pb.name).toBe('Generated review')
    expect(added.pb.phases[0]).toMatchObject({ id: 'review', role: 'reviewer', readOnly: true })
    expect(added.problems ?? []).toEqual([])
  })

  it('creates distinct playbooks when the same draft is added twice', () => {
    const current = createPlaybooksState(JSON.stringify(initial))
    const first = appendGeneratedPlaybook(current, proposal)
    const second = appendGeneratedPlaybook(current, proposal)
    expect(second.id).not.toBe(first.id)
    expect(Object.keys(current.workflows).filter((id) => id.startsWith('playbook:'))).toHaveLength(
      3
    )
  })

  it('rejects missing proposals and graph errors before applying', () => {
    expect(() => generatedPlaybook({ ...proposal, id: 'missing' })).toThrow('invalid-result')
    expect(() =>
      generatedPlaybook({
        id: 'generated',
        text: JSON.stringify({
          ...initial,
          playbooks: {
            generated: { name: 'Broken', phases: [{ id: 'one', after: 'missing' }] }
          }
        })
      })
    ).toThrow()
  })

  it('rejects drafts when graph conversion would silently drop a phase', () => {
    expect(() =>
      generatedPlaybook({
        id: 'generated',
        text: JSON.stringify({
          ...initial,
          playbooks: {
            generated: {
              name: 'Hidden reviewer',
              phases: [
                { id: 'build', role: 'builder' },
                { id: 'review', role: 'reviewer', after: 'build', readOnly: true }
              ]
            }
          }
        })
      })
    ).toThrow('invalid-result')
  })
})
