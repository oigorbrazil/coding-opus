import { describe, expect, it } from 'vitest'
import { buildGraph, type FlowNode, type Point2 } from './graph'
import { createPlaybooksState } from './state'

const state = createPlaybooksState(`version: 1
providers: [claude, codex]
playbooks:
  direct:
    name: Direct
    phases:
      - id: work
        provider: claude
`)

const routings = Object.values(state.workflows).filter((wf) => wf.kind === 'routing')

/** The middle of a node, away from its edges and ports, where no wire should ever pass. */
function core(node: FlowNode) {
  const mx = node.w / 4
  const my = node.h / 4
  return { x1: node.x + mx, x2: node.x + node.w - mx, y1: node.y + my, y2: node.y + node.h - my }
}

function crosses([a, b]: [Point2, Point2], box: ReturnType<typeof core>) {
  const [x1, x2] = [Math.min(a[0], b[0]), Math.max(a[0], b[0])]
  const [y1, y2] = [Math.min(a[1], b[1]), Math.max(a[1], b[1])]
  return x1 < box.x2 && x2 > box.x1 && y1 < box.y2 && y2 > box.y1
}

describe('task routing layout', () => {
  it('has the built-in routings', () => {
    expect(routings.map((wf) => wf.key).sort()).toEqual(['balanced', 'economy', 'performance'])
  })

  for (const wf of routings) {
    it(`${wf.key}: no wire runs through a question or a card`, () => {
      const graph = buildGraph(state, (key) => key, wf)
      const solid = graph.nodes.filter((node) => node.type === 'decision' || node.type === 'role')
      const through = graph.wires.flatMap((wire, index) =>
        wire.slice(1).flatMap((point, i) => {
          const segment: [Point2, Point2] = [wire[i], point]
          return solid
            .filter((node) => crosses(segment, core(node)))
            .map((node) => `${graph.edges[index].from}->${graph.edges[index].to} through ${node.id}`)
        })
      )
      expect(through).toEqual([])
    })

    it(`${wf.key}: alternative models sit beside their card, clear of other nodes`, () => {
      const graph = buildGraph(state, (key) => key, wf)
      const ghosts = graph.nodes.filter((node) => node.type === 'ghost')
      const covered = ghosts.flatMap((ghost) =>
        graph.nodes
          .filter(
            (node) =>
              node !== ghost &&
              ghost.x < node.x + node.w &&
              node.x < ghost.x + ghost.w &&
              ghost.y < node.y + node.h &&
              node.y < ghost.y + ghost.h
          )
          .map((node) => `${ghost.id} over ${node.id}`)
      )
      expect(covered).toEqual([])
    })
  }
})
