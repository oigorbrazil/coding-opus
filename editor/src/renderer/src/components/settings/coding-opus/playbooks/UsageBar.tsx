import { useEffect, useLayoutEffect, useRef, useState } from 'react'

import { ROUTES } from '@/lib/coding-opus-playbooks/catalog'
import { windowLabel } from '@/lib/coding-opus-playbooks/labels'
import { usageFromSnapshot } from '@/lib/coding-opus-playbooks/liveUsage'
import {
  lowProviders,
  presetUsage,
  providerLabel,
  quotaNow,
  spareOf,
  windowsOf
} from '@/lib/coding-opus-playbooks/state'
import { usePlaybooks } from './context'
import { UsageReading } from './UsageReading'
import { UsageSimulation } from './UsageSimulation'
import styles from './Playbooks.module.css'
import { ProviderMark } from './ProviderMark'

// The installed agent CLIs, read once per page: detection runs every CLI's --version.
let installedCache: Promise<Set<string> | null> | null = null

function readInstalled(): Promise<Set<string> | null> {
  const api = window.api?.codingOpus
  if (typeof api?.detectClis !== 'function') {
    return Promise.resolve(null)
  }
  installedCache ??= api
    .detectClis()
    .then((result) =>
      result.ok ? new Set(result.clis.filter((cli) => cli.installed).map((cli) => cli.id)) : null
    )
    .catch(() => null)
  return installedCache
}

/** Providers to show in the usage bar: the configured ones that are installed on this computer.
 * Until detection answers, or if it cannot, every configured provider is shown. */
function useShownProviders(providers: string[]): string[] {
  const [installed, setInstalled] = useState<Set<string> | null>(null)
  useEffect(() => {
    let live = true
    void readInstalled().then((value) => {
      if (live) {
        setInstalled(value)
      }
    })
    return () => {
      live = false
    }
  }, [])
  const shown = installed ? providers.filter((id) => installed.has(id)) : providers
  return shown.length ? shown : providers
}

export function UsageBar({
  onChange,
  onRefresh,
  load
}: {
  onChange: () => void
  onRefresh: () => void
  load: 'loading' | 'ready' | 'error'
}) {
  const { s, t, select } = usePlaybooks()
  const shown = useShownProviders(s.providers)
  const [open, setOpen] = useState<string | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const q = quotaNow(s)
  const low = lowProviders(s)
  const actual = usageFromSnapshot(s.liveUsageSnapshot ?? { providers: {} }, s.liveUsageReadAt ?? 0)

  useLayoutEffect(() => {
    if (!open || !rootRef.current || !panelRef.current) {
      return
    }
    const update = () => {
      const root = rootRef.current
      const panel = panelRef.current
      if (!root || !panel) {
        return
      }
      const anchor = root.getBoundingClientRect()
      const bounds = panel.getBoundingClientRect()
      const left = Math.max(
        16,
        Math.min(anchor.right - bounds.width, window.innerWidth - bounds.width - 16)
      )
      const top = Math.max(16, Math.min(anchor.bottom + 7, window.innerHeight - bounds.height - 16))
      panel.style.left = `${left - anchor.left}px`
      panel.style.top = `${top - anchor.top}px`
    }
    update()
    const observer = new ResizeObserver(update)
    observer.observe(panelRef.current)
    window.addEventListener('resize', update)
    return () => {
      observer.disconnect()
      window.removeEventListener('resize', update)
    }
  }, [open])

  useEffect(() => {
    if (!open) {
      return
    }
    const close = (event: PointerEvent) => {
      // oxlint-disable-next-line typescript/consistent-type-assertions -- SAFETY: the listener sits on an element, so the event target is a DOM node.
      const target = event.target as Element | null
      if (rootRef.current?.contains(target)) {
        return
      }
      if (target?.closest('[data-coding-agent-dropdown-menu]')) {
        return
      }
      setOpen(null)
    }
    document.addEventListener('pointerdown', close)
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(null)
      }
    }
    document.addEventListener('keydown', keydown)
    return () => {
      document.removeEventListener('pointerdown', close)
      document.removeEventListener('keydown', keydown)
    }
  }, [open])

  const tone = (value: number) =>
    value >= q.criticalThreshold ? 'danger' : value >= q.criticalThreshold - 20 ? 'warn' : 'normal'
  const current = open && shown.includes(open) ? open : null
  const def = current ? s.catalog[current] : null
  const useRealUsage = () => {
    s.usageMode = 'live'
    s.usage = presetUsage(s, 'now')
    onChange()
  }

  return (
    <div ref={rootRef} className={styles.usage}>
      {shown.map((id) => {
        const values = s.usageMode === 'simulation' ? s.usage[id] : actual[id]
        const main = windowsOf(s, id)
          .filter((w) => w.main)
          .map((w) => values?.[w.key])
          .filter((value): value is number => typeof value === 'number')
        const percent = main.length ? Math.max(...main) : null
        const detail = windowsOf(s, id)
          .filter((w) => w.main)
          .map(
            (w) =>
              `${windowLabel(t, w)} ${values?.[w.key] ?? '—'}${typeof values?.[w.key] === 'number' ? '%' : ''}`
          )
          .join(', ')
        const title =
          s.usageMode === 'simulation'
            ? t('playbooks.usageSimulatedTitle', { provider: providerLabel(s, id), detail })
            : percent !== null
              ? t('playbooks.usagePillTitle', { provider: providerLabel(s, id), detail })
              : t('playbooks.usageUnavailableTitle', { provider: providerLabel(s, id) })
        return (
          <button
            key={id}
            type="button"
            className={percent !== null ? styles.usagePill : `${styles.usagePill} ${styles.unread}`}
            data-tone={percent !== null ? tone(percent) : 'normal'}
            title={title}
            aria-label={title}
            aria-pressed={open === id}
            onClick={() => {
              setOpen(open === id ? null : id)
              if (open !== id) {
                onRefresh()
              }
            }}
          >
            <ProviderMark id={id} size={13} />
            {percent === null ? '—' : `${percent}%`}
            {percent !== null && spareOf(s, id) ? (
              <span className={styles.dot} data-tone="on" />
            ) : percent !== null && low.includes(id) ? (
              <span className={styles.dot} data-tone="danger" />
            ) : null}
          </button>
        )
      })}
      {Object.entries(s.routes).map(([rid, route]) => {
        const label = ROUTES[rid]?.label ?? rid
        const title = route.running
          ? t('playbooks.routeRunning', { route: label, port: String(route.port ?? '') })
          : t('playbooks.routeStopped', { route: label })
        return (
          <button
            key={rid}
            type="button"
            className={`${styles.usagePill} ${styles.routePill}`}
            title={title}
            aria-label={title}
            onClick={() => select(`route:${rid}`)}
          >
            <ProviderMark id={rid} size={13} />
            {route.running ? t('playbooks.on') : t('playbooks.off')}
          </button>
        )
      })}
      {s.usageMode === 'simulation' ? (
        <span className={styles.usageMode}>{t('playbooks.usageSimulationActive')}</span>
      ) : null}
      {current && def ? (
        <div
          ref={panelRef}
          className={styles.popover}
          role="dialog"
          aria-label={t('playbooks.usageTitle')}
        >
          <div className={styles.popoverTitle}>
            {t('playbooks.usageReal')}
            <span className={styles.tabs}>
              {shown.map((id) => (
                <button
                  key={id}
                  type="button"
                  aria-label={providerLabel(s, id)}
                  aria-pressed={id === current}
                  onClick={() => setOpen(id)}
                >
                  <ProviderMark id={id} size={13} />
                </button>
              ))}
            </span>
          </div>
          <div className={styles.popoverProvider}>
            <ProviderMark id={current} size={13} />
            {def.label}
          </div>
          <UsageReading provider={current} load={load} />
          <div className={styles.actions}>
            <button
              type="button"
              className={styles.button}
              disabled={load === 'loading'}
              onClick={onRefresh}
            >
              {t('playbooks.usageRefresh')}
            </button>
            {s.usageMode === 'simulation' ? (
              <button type="button" className={styles.button} onClick={useRealUsage}>
                {t('playbooks.usageExitSimulation')}
              </button>
            ) : null}
          </div>
          {s.usageMode === 'simulation' ? (
            <p className={styles.usageNotice} role="status">
              {t('playbooks.usageSimulationNotice')}
            </p>
          ) : null}
          <UsageSimulation provider={current} onChange={onChange} />
        </div>
      ) : null}
    </div>
  )
}
