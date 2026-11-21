/* oxlint-disable max-lines -- ported as-is from Coding Agent 1; split when this editor is next reworked. */
import { Maximize2, Minus, Plus } from 'lucide-react'
import { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from 'react'

import type { TFunction } from '@/lib/coding-opus-playbooks/i18n'
import {
  fromEnd,
  arrowHead,
  type DecisionNode,
  type EndNode,
  type EntryNode,
  fitView,
  type FlowEdge,
  type FlowGraph,
  ghostActive,
  type GhostNode,
  type Point2,
  type RoleNode,
  roleStatus,
  rounded,
  type View,
  zoomAt
} from '@/lib/coding-opus-playbooks/graph'
import { condShortText } from '@/lib/coding-opus-playbooks/labels'
import { formatUsd, modelPrice } from '@/lib/coding-opus-playbooks/prices'
import {
  isProblemCond,
  isSpareCond,
  providerLabel,
  type ResolvedUse,
  type PlaybooksState,
  type Point
} from '@/lib/coding-opus-playbooks/state'
import { usePlaybooks } from './context'
import styles from './Playbooks.module.css'
import { SvgProviderMark } from './ProviderMark'

const modelSubtitle = (s: PlaybooksState, use: ResolvedUse) =>
  [providerLabel(s, use.provider), use.model, use.effort].filter(Boolean).join(' · ')

type Tone = 'idle' | 'on' | 'warn' | 'danger' | 'border' | 'selected'

const trunc = (text: string, n: number) => (text.length > n ? `${text.slice(0, n - 1)}…` : text)

function wrapLines(text: string, width: number): string[] {
  const lines: string[] = []
  let current = ''
  text
    .trim()
    .split(/\s+/)
    .forEach((word) => {
      const next = trunc(word, width)
      if (current && current.length + next.length + 1 > width) {
        lines.push(current)
        current = next
      } else {
        current = current ? `${current} ${next}` : next
      }
    })
  if (current.trim()) {
    lines.push(current.trim())
  }
  return lines
}

function Edge({
  edge,
  on,
  graph,
  wire
}: {
  edge: FlowEdge
  on: boolean
  graph: FlowGraph
  wire: Point2[]
}) {
  const { t } = usePlaybooks()
  const points = [...wire]
  const end = fromEnd(points, 1)
  const prev = fromEnd(points, 2)
  const len = Math.hypot(end[0] - prev[0], end[1] - prev[1]) || 1
  points[points.length - 1] = [
    end[0] - ((end[0] - prev[0]) / len) * 2,
    end[1] - ((end[1] - prev[1]) / len) * 2
  ]
  const to = graph.byId[edge.to]
  const blocked = on && graph.sim.blocked && (to.type === 'role' ? !to.lead : to.type === 'end')
  const special = edge.kind === 'fail' || edge.kind === 'recheck'
  const tone: Tone = !on ? 'idle' : blocked ? 'danger' : special ? 'warn' : 'on'
  return (
    <g className={styles.edge} data-tone={tone}>
      <path
        d={rounded(points)}
        fill="none"
        strokeWidth={on ? 1.8 : 1.2}
        strokeDasharray={on && !blocked ? undefined : '5 5'}
        strokeLinejoin="round"
      />
      <path className={styles.arrow} d={arrowHead(points)} />
      {edge.label === 'recheck' ? (
        <text
          className={on ? styles.edgeLabel : styles.svgMuted}
          x={(points[1][0] + points[2][0]) / 2}
          y={points[1][1] - 7}
          fontSize={12}
          textAnchor="middle"
        >
          {t('playbooks.recheck')}
        </text>
      ) : null}
    </g>
  )
}

export function Role({ n, graph }: { n: RoleNode; graph: FlowGraph }) {
  const { s, t, selectedId } = usePlaybooks()
  const sim = graph.sim
  const status = roleStatus(n, sim)
  const reached = sim.reached.has(n.id)
  const selected = selectedId === n.id
  const tone: Tone = selected
    ? 'selected'
    : status === 'blocked'
      ? 'danger'
      : status === 'warn'
        ? 'warn'
        : status === 'spare'
          ? 'on'
          : 'border'
  const { switched, stuck, chosen } = n.resolved
  const planned = n.resolved.planned
  const fallbackOn =
    reached &&
    (switched || Boolean(n.resolved.spent) || Boolean(chosen && isProblemCond(s, chosen.cond)))
  const price = n.lead ? null : modelPrice(planned.provider, planned.model)
  let note = ''
  if (reached && stuck) {
    note = t(
      n.resolved.previewUnsupported ? 'playbooks.previewUnsupported' : 'playbooks.noProviderLeft'
    )
  } else if (reached && chosen && !isProblemCond(s, chosen.cond)) {
    note = condShortText(s, t, chosen.cond)
  }
  return (
    <>
      <g className={styles.node} data-node={n.id} data-reached={reached}>
        <rect
          className={styles.shape}
          data-tone={tone}
          x={n.x}
          y={n.y}
          width={n.w}
          height={n.h}
          rx={4}
          strokeWidth={selected ? 2 : 1.3}
        />
        <SvgProviderMark
          id={planned.provider}
          x={n.x + 13}
          y={n.y + 19}
          size={16}
          faded={fallbackOn}
        />
        {planned.via ? (
          <SvgProviderMark
            id={planned.via}
            x={n.x + 25}
            y={n.y + 31}
            size={11}
            faded={fallbackOn}
          />
        ) : null}
        <text className={styles.svgText} x={n.x + 40} y={n.y + 24} fontSize={14} fontWeight={600}>
          {trunc(n.title, 20)}
        </text>
        {n.lead || n.workers > 1 ? (
          <text
            className={styles.svgMuted}
            x={n.x + n.w - 10}
            y={n.y + 22}
            fontSize={12}
            textAnchor="end"
          >
            {n.lead ? t('playbooks.you') : `×${n.workers}`}
          </text>
        ) : null}
        <text
          className={`${styles.svgMuted} ${styles.mono}`}
          x={n.x + 40}
          y={n.y + 41}
          fontSize={12}
          textDecoration={fallbackOn ? 'line-through' : undefined}
        >
          <title>{modelSubtitle(s, planned)}</title>
          {trunc(modelSubtitle(s, planned), 30)}
        </text>
        {price ? (
          <text
            className={`${styles.svgMuted} ${styles.mono}`}
            x={n.x + n.w - 10}
            y={n.y + n.h - 10}
            fontSize={11}
            textAnchor="end"
          >
            <title>{t('playbooks.priceTitle')}</title>
            {`${formatUsd(price.input)}/${formatUsd(price.output)}`}
          </text>
        ) : null}
      </g>
      {note ? (
        <text
          className={stuck ? styles.svgWarn : styles.svgMuted}
          x={n.cx + 10}
          y={n.y + n.h + 15}
          fontSize={12}
        >
          {note}
        </text>
      ) : null}
    </>
  )
}

export function ghostParts(
  n: GhostNode,
  graph: FlowGraph,
  s: PlaybooksState,
  t: TFunction
): [ReactNode, ReactNode] {
  // oxlint-disable-next-line typescript/consistent-type-assertions -- SAFETY: ids come from edges of the same flow, so the node exists.
  const parent = graph.byId[n.parent] as RoleNode
  const reached = graph.sim.reached.has(parent.id)
  const r = parent.resolved
  const active = ghostActive(n, parent, graph.sim)
  const tone: Tone = n.alt.spare || isSpareCond(n.alt.cond) ? 'on' : 'warn'
  const opacity = active ? 1 : reached ? 0.85 : 0.65
  const points: Point2[] = []
  if (n.side === 'top' || n.side === 'bottom') {
    const rail = parent.x + parent.w - 4
    points.push(
      [rail, n.side === 'top' ? parent.y : parent.y + parent.h],
      [rail, n.cy],
      [n.x + n.w, n.cy]
    )
  } else {
    const px = n.side === 'left' ? parent.x : parent.x + parent.w
    const gx = n.side === 'left' ? n.x + n.w : n.x
    const mid = (px + gx) / 2
    points.push([px, parent.cy], [mid, parent.cy], [mid, n.cy], [gx, n.cy])
  }
  const use =
    active && (n.alt.spare || n.alt.implicit || n.alt.key === 'fallback') ? r.final : n.alt.use
  const link = (
    <path
      key={`${n.id}-link`}
      className={styles.edge}
      data-tone={active ? tone : 'idle'}
      d={rounded(points, 12)}
      fill="none"
      strokeWidth={active ? 1.6 : 1.1}
      strokeDasharray={active ? undefined : '3 4'}
      opacity={opacity}
    />
  )
  const card = (
    <g key={n.id} className={styles.node} data-node={parent.id}>
      <rect
        className={`${styles.shape} ${styles.fallbackCard}`}
        data-tone={active ? tone : 'border'}
        x={n.x}
        y={n.y}
        width={n.w}
        height={n.h}
        rx={4}
        strokeWidth={active ? 1.6 : 1}
      />
      <text className={styles.fallbackLabel} x={n.x + 10} y={n.y + 15} fontSize={12}>
        <title>{t('playbooks.ifCondition', { condition: condShortText(s, t, n.alt.cond) })}</title>
        {trunc(t('playbooks.ifCondition', { condition: condShortText(s, t, n.alt.cond) }), 30)}
      </text>
      <SvgProviderMark id={use.provider} x={n.x + 10} y={n.y + 21} size={13} />
      <text className={`${styles.svgText} ${styles.mono}`} x={n.x + 29} y={n.y + 32} fontSize={12}>
        <title>
          {modelSubtitle(s, use)}
          {n.alt.as ? ` · ${n.alt.as}` : ''}
        </title>
        {trunc(modelSubtitle(s, use), 30)}
      </text>
    </g>
  )
  return [link, card]
}

export function Decision({ n, graph }: { n: DecisionNode; graph: FlowGraph }) {
  const { t, selectedId } = usePlaybooks()
  const reached = graph.sim.reached.has(n.id)
  const selected = selectedId === n.id
  const lines = wrapLines(n.text, 17)
  const shown =
    lines.length > 3 ? [...lines.slice(0, 2), trunc(lines.slice(2).join(' '), 17)] : lines
  const open = graph.sim.openOf[n.id] ?? new Set<number>()
  return (
    <>
      <g className={styles.node} data-node={n.id} data-reached={reached}>
        <title>{n.text}</title>
        <path
          className={styles.shape}
          data-tone={selected ? 'selected' : 'border'}
          d={`M${n.cx} ${n.y} L${n.x + n.w} ${n.cy} L${n.cx} ${n.y + n.h} L${n.x} ${n.cy} Z`}
          strokeWidth={selected ? 2 : 1.3}
          strokeLinejoin="round"
        />
        {shown.map((line, i) => (
          <text
            key={i}
            className={styles.svgText}
            x={n.cx}
            y={n.cy + 4 + (i - (shown.length - 1) / 2) * 14}
            fontSize={12}
            textAnchor="middle"
            fontWeight={i === 0 ? 600 : 400}
          >
            {line}
          </text>
        ))}
      </g>
      {([0, 1] as const).map((i) => {
        const isOpen = reached && open.has(i)
        const className = isOpen
          ? n.gate && i === 1
            ? styles.svgWarn
            : styles.svgOn
          : styles.svgMuted
        const [x, y] = i === 0 ? [n.cx + 7, n.y + n.h + 15] : [n.x + n.w + 7, n.cy - 7]
        return (
          <text key={i} className={className} x={x} y={y} fontSize={12} opacity={isOpen ? 1 : 0.8}>
            {t(n.labels[i] === 'yes' ? 'playbooks.yes' : 'playbooks.no')}
          </text>
        )
      })}
    </>
  )
}

function Entry({ n }: { n: EntryNode }) {
  const { t, selectedId } = usePlaybooks()
  return (
    <g className={styles.node} data-node={n.id}>
      <rect
        className={styles.shape}
        data-tone={selectedId === n.id ? 'selected' : 'border'}
        x={n.x}
        y={n.y}
        width={n.w}
        height={n.h}
        rx={4}
        strokeWidth={1.3}
      />
      <text className={styles.svgText} x={n.x + 16} y={n.y + 23} fontSize={13.5} fontWeight={700}>
        {t('playbooks.planner')}
      </text>
      <text
        className={styles.svgMuted}
        x={n.x + n.w - 10}
        y={n.y + 22}
        fontSize={12}
        textAnchor="end"
      >
        {t('playbooks.you')}
      </text>
      <text className={styles.svgMuted} x={n.x + 16} y={n.y + 41} fontSize={12}>
        {t('playbooks.plannerHint')}
      </text>
    </g>
  )
}

export function End({ n, graph }: { n: EndNode; graph: FlowGraph }) {
  const { t } = usePlaybooks()
  const reached = graph.sim.reached.has(n.id)
  const blocked = graph.sim.blocked && reached
  const sub = blocked
    ? t('playbooks.blockedHint')
    : n.next
      ? t('playbooks.thenNext', { next: n.next })
      : null
  return (
    <>
      <g className={styles.node} data-node={n.id} data-reached={reached}>
        <rect
          className={styles.shape}
          data-tone={blocked ? 'danger' : 'border'}
          x={n.x}
          y={n.y}
          width={n.w}
          height={n.h}
          rx={n.h / 2}
          strokeWidth={1.3}
        />
        <text
          className={blocked ? styles.svgDanger : styles.svgText}
          x={n.cx}
          y={n.cy + 4.5}
          fontSize={13}
          fontWeight={700}
          textAnchor="middle"
        >
          {blocked ? t('playbooks.blocked') : t('playbooks.result')}
        </text>
      </g>
      {sub ? (
        <text
          className={blocked ? styles.svgDanger : styles.svgMuted}
          x={n.cx}
          y={n.y + n.h + 16}
          fontSize={12}
          textAnchor="middle"
        >
          {sub}
        </text>
      ) : null}
    </>
  )
}

type Drag =
  | { kind: 'pan'; sx: number; sy: number; vx: number; vy: number; moved: boolean }
  | { kind: 'node'; id: string; ox: number; oy: number; sx: number; sy: number; moved: boolean }

export function FlowCanvas({
  graph,
  fitKey,
  pulse,
  compact,
  reserved,
  onMove
}: {
  graph: FlowGraph
  fitKey: string
  pulse: number
  compact: boolean
  reserved: boolean
  onMove: (id: string, position: Point) => void
}) {
  const { s, t, select } = usePlaybooks()
  const svgRef = useRef<SVGSVGElement>(null)
  const graphRef = useRef(graph)
  useLayoutEffect(() => {
    graphRef.current = graph
  })
  const [view, setView] = useState<View | null>(null)
  const viewRef = useRef(view)
  useLayoutEffect(() => {
    viewRef.current = view
  })
  const drag = useRef<Drag | null>(null)
  const [panning, setPanning] = useState(false)

  useLayoutEffect(() => {
    const svg = svgRef.current
    if (!svg) {
      return
    }
    const fit = () => {
      const rect = svg.getBoundingClientRect()
      if (rect.width && rect.height) {
        const current = graphRef.current
        setView(
          fitView(
            current,
            rect.width,
            rect.height,
            reserved ? rect.height * 0.45 : 0,
            compact ? current.byId.entry : undefined
          )
        )
      }
    }
    fit()
    if (typeof ResizeObserver === 'undefined') {
      return
    }
    const observer = new ResizeObserver(fit)
    observer.observe(svg)
    return () => observer.disconnect()
  }, [fitKey, compact, reserved])

  useEffect(() => {
    const svg = svgRef.current
    if (!svg) {
      return
    }
    const onWheel = (event: WheelEvent) => {
      const current = viewRef.current
      if (!current) {
        return
      }
      event.preventDefault()
      const rect = svg.getBoundingClientRect()
      setView(
        zoomAt(
          current,
          event.clientX - rect.left,
          event.clientY - rect.top,
          current.k * Math.exp(-event.deltaY * 0.0015)
        )
      )
    }
    svg.addEventListener('wheel', onWheel, { passive: false })
    return () => svg.removeEventListener('wheel', onWheel)
  }, [])

  const toWorld = (clientX: number, clientY: number): [number, number] => {
    const rect = svgRef.current?.getBoundingClientRect()
    const current = viewRef.current
    if (!rect || !current) {
      return [0, 0]
    }
    return [
      (clientX - rect.left - current.x) / current.k,
      (clientY - rect.top - current.y) / current.k
    ]
  }

  const zoomBy = (factor: number) => {
    const rect = svgRef.current?.getBoundingClientRect()
    if (!rect || !view) {
      return
    }
    setView(zoomAt(view, rect.width / 2, rect.height / 2, view.k * factor))
  }

  const links: ReactNode[] = []
  const nodes: ReactNode[] = []
  graph.nodes.forEach((n) => {
    if (n.type === 'role') {
      nodes.push(<Role key={n.id} n={n} graph={graph} />)
    } else if (n.type === 'ghost') {
      const [link, card] = ghostParts(n, graph, s, t)
      links.push(link)
      nodes.push(card)
    } else if (n.type === 'decision') {
      nodes.push(<Decision key={n.id} n={n} graph={graph} />)
    } else if (n.type === 'entry') {
      nodes.push(<Entry key={n.id} n={n} />)
    } else if (n.type === 'end') {
      nodes.push(<End key={n.id} n={n} graph={graph} />)
    }
  })

  return (
    <>
      <svg
        ref={svgRef}
        className={panning ? `${styles.canvas} ${styles.panning}` : styles.canvas}
        role="img"
        aria-label={t('playbooks.canvasLabel')}
        onPointerDown={(event) => {
          event.currentTarget.setPointerCapture(event.pointerId)
          // oxlint-disable-next-line typescript/consistent-type-assertions -- SAFETY: the listener sits on an element, so the event target is a DOM node.
          const target = (event.target as Element).closest('[data-node]')
          const id = target?.getAttribute('data-node')
          const node = id ? graph.byId[id] : null
          if (node) {
            const [wx, wy] = toWorld(event.clientX, event.clientY)
            drag.current = {
              kind: 'node',
              id: node.id,
              ox: wx - node.x,
              oy: wy - node.y,
              sx: event.clientX,
              sy: event.clientY,
              moved: false
            }
          } else if (view) {
            drag.current = {
              kind: 'pan',
              sx: event.clientX,
              sy: event.clientY,
              vx: view.x,
              vy: view.y,
              moved: false
            }
            setPanning(true)
          }
        }}
        onPointerMove={(event) => {
          const current = drag.current
          if (!current) {
            return
          }
          if (Math.hypot(event.clientX - current.sx, event.clientY - current.sy) > 3) {
            current.moved = true
          }
          if (!current.moved) {
            return
          }
          if (current.kind === 'pan') {
            const { vx, vy, sx, sy } = current
            setView((previous) =>
              previous
                ? { ...previous, x: vx + event.clientX - sx, y: vy + event.clientY - sy }
                : previous
            )
          } else {
            const [wx, wy] = toWorld(event.clientX, event.clientY)
            onMove(current.id, {
              x: Math.round((wx - current.ox) / 10) * 10,
              y: Math.round((wy - current.oy) / 10) * 10
            })
          }
        }}
        onPointerUp={() => {
          const current = drag.current
          if (current && !current.moved) {
            select(current.kind === 'node' ? current.id : null)
          }
          drag.current = null
          setPanning(false)
        }}
      >
        {view ? (
          <g key={pulse} transform={`translate(${view.x} ${view.y}) scale(${view.k})`}>
            <g>
              {graph.edges.map((edge, i) =>
                edge.from === 'start' ? null : (
                  <Edge
                    key={i}
                    edge={edge}
                    on={graph.sim.edgeOn.has(i)}
                    graph={graph}
                    wire={graph.wires[i]}
                  />
                )
              )}
            </g>
            <g>{links}</g>
            <g className={styles.nodes}>{nodes}</g>
          </g>
        ) : null}
      </svg>
      <div className={styles.zoom}>
        <button
          type="button"
          aria-label={t('playbooks.zoomIn')}
          title={t('playbooks.zoomIn')}
          onClick={() => zoomBy(1.2)}
        >
          <Plus size={13} />
        </button>
        <button
          type="button"
          aria-label={t('playbooks.zoomOut')}
          title={t('playbooks.zoomOut')}
          onClick={() => zoomBy(1 / 1.2)}
        >
          <Minus size={13} />
        </button>
        <button
          type="button"
          aria-label={t('playbooks.fit')}
          title={t('playbooks.fit')}
          onClick={() => {
            const rect = svgRef.current?.getBoundingClientRect()
            if (rect) {
              setView(fitView(graph, rect.width, rect.height, reserved ? rect.height * 0.45 : 0))
            }
          }}
        >
          <Maximize2 size={12} />
        </button>
      </div>
    </>
  )
}
