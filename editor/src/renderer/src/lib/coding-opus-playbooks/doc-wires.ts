import { type DocNode, type DocPort, type FlowDoc, nodeSize, portPoint } from './flowDoc'
import type { Point2 } from './graph'

function edgePoints(from: DocNode, port: DocPort, to: DocNode, laneX: () => number): Point2[] {
  const p1 = portPoint(from, port)
  const { w, h } = nodeSize(to)
  const top: Point2 = [to.x + w / 2, to.y]
  const side = port === 'yes' || port === 'fail' ? 'right' : 'bottom'
  const fromCx = from.x + nodeSize(from).w / 2
  if (to.kind === 'end' && to.y > p1[1] && Math.abs(fromCx - top[0]) > 1) {
    const lane = laneX()
    const right: Point2 = [to.x + w, to.y + h / 2]
    return side === 'right'
      ? [p1, [lane, p1[1]], [lane, right[1]], right]
      : [p1, [p1[0], p1[1] + 26], [lane, p1[1] + 26], [lane, right[1]], right]
  }
  if (to.y >= p1[1] + 16) {
    if (side === 'right') {
      if (top[0] > p1[0] + 16) {
        return [p1, [top[0], p1[1]], top]
      }
      return [p1, [p1[0] + 18, p1[1]], [p1[0] + 18, top[1] - 34], [top[0], top[1] - 34], top]
    }
    if (Math.abs(p1[0] - top[0]) < 1) {
      return [p1, top]
    }
    return [p1, [p1[0], top[1] - 34], [top[0], top[1] - 34], top]
  }
  const left: Point2 = [to.x, to.y + h / 2]
  if (side === 'right' && to.x >= p1[0] + 16) {
    if (Math.abs(p1[1] - left[1]) < 1) {
      return [p1, left]
    }
    const mid = (p1[0] + left[0]) / 2
    return [p1, [mid, p1[1]], [mid, left[1]], left]
  }
  const corridor = Math.min(to.y, from.y) - 22
  const out = side === 'right' ? p1[0] + 18 : from.x + nodeSize(from).w + 18
  return side === 'right'
    ? [p1, [out, p1[1]], [out, corridor], [top[0], corridor], top]
    : [p1, [p1[0], p1[1] + 18], [out, p1[1] + 18], [out, corridor], [top[0], corridor], top]
}

export function docWires(doc: FlowDoc) {
  const byId = new Map(doc.nodes.map((n) => [n.id, n]))
  const right = Math.max(...doc.nodes.map((n) => n.x + nodeSize(n).w))
  let lanes = 0
  return doc.edges.map((edge) => {
    const from = byId.get(edge.from)
    const to = byId.get(edge.to)
    return from && to ? edgePoints(from, edge.port, to, () => right + 40 + lanes++ * 14) : []
  })
}
