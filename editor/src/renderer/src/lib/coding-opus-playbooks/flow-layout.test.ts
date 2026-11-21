import { expect, it } from 'vitest'
import { attachDocs, buildDocView } from './flowView'
import { createPlaybooksState } from './state'

it('keeps a repair step’s alternate model clear of the next decision and step', () => {
  const state = createPlaybooksState(`version: 1
providers: [claude, codex]
quota: { whenLow: switch-provider }
playbooks:
  cascade:
    name: Cascade
    phases:
      - id: first
        provider: claude
        gate: First check passes
      - id: retry
        provider: claude
        after: first
        gate: Second check passes
      - id: final
        provider: auto
        after: retry
        then: done
`)
  attachDocs(state)
  const cascade = state.workflows['playbook:cascade']
  if (cascade.kind !== 'playbook') {
    throw new Error('Expected the cascade playbook')
  }

  const view = buildDocView(state, (key) => key, cascade)
  const alternate = view.nodes.find(
    (node) => node.type === 'ghost' && node.parent === 'phase:retry'
  )
  if (alternate?.type !== 'ghost') {
    throw new Error('Expected a fallback for the retry step')
  }
  expect(alternate.alt.use.provider).toBe('codex')
  const covering = view.nodes.filter(
    (node) =>
      node.id !== alternate.id &&
      alternate.x < node.x + node.w &&
      node.x < alternate.x + alternate.w &&
      alternate.y < node.y + node.h &&
      node.y < alternate.y + alternate.h
  )
  expect(covering.map((node) => node.id)).toEqual([])
})
