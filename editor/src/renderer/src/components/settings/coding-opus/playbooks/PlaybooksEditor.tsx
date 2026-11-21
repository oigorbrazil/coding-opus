/* oxlint-disable max-lines -- ported as-is from Coding Agent 1; split when this editor is next reworked. */
import {
  ChevronDown,
  FileCode,
  GitBranch,
  ListTree,
  PanelRight,
  Plus,
  Redo2,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Undo2,
  WandSparkles
} from 'lucide-react'
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'

import codingOpusLogo from '@/assets/coding-opus.png?inline'
import { type MessageKey, useT } from '@/lib/coding-opus-playbooks/i18n'
import {
  BUDGETS,
  CHECKS,
  ON_BOTH_CRITICAL,
  ROUTES,
  SPENT_STEPS,
  type TaskId,
  TASKS
} from '@/lib/coding-opus-playbooks/catalog'
import { type DocPort, removeEdge, removeNode } from '@/lib/coding-opus-playbooks/flowDoc'
import {
  addPlaybook,
  applyDoc,
  attachDocs,
  buildDocView,
  hasProblems,
  saveLayout
} from '@/lib/coding-opus-playbooks/flowView'
import { buildGraph } from '@/lib/coding-opus-playbooks/graph'
import { usageFromSnapshot } from '@/lib/coding-opus-playbooks/liveUsage'
import { codingOpusLiveUsage } from '../../../../../../shared/coding-opus-live-usage'
import { formatUsd } from '@/lib/coding-opus-playbooks/prices'
import {
  activeOrder,
  applyLiveUsage,
  context,
  createPlaybooksState,
  evalToken,
  isEdited,
  playbooksForProvider,
  type PlaybooksState,
  providerLabel,
  routedVia,
  selectPlaybookProvider,
  toYaml,
  type Workflow,
  workflowNow
} from '@/lib/coding-opus-playbooks/state'
import {
  isLightTheme,
  orchestratorSavePlaybooks,
  pushToast,
  type SkillPlaybooks,
  useAppliedTheme
} from '@/lib/coding-opus-playbooks/host'
import { PlaybooksContext } from './context'
import { Select } from './fields'
import { FlowCanvas } from './FlowCanvas'
import { ACCOUNT_PROVIDERS } from './AccountsPanel'
import { MODEL_UPDATES_ID } from './ModelUpdatesPanel'
import { CHECK_KEYS, Inspector, routingName, taskLabel } from './Inspector'
import { NodeCanvas } from './NodeCanvas'
import styles from './Playbooks.module.css'
import { ProviderMark } from './ProviderMark'
import { UsageBar } from './UsageBar'
import { GENERATOR_ID, PlaybookGeneratorPanel } from './PlaybookGeneratorPanel'
import { appendGeneratedPlaybook } from '@/lib/coding-opus-playbooks/generatedPlaybook'

/** Quiet time after the last edit before the file is written; both editors then reload it. */
const AUTOSAVE_MS = 800
const COMPACT_EDITOR_WIDTH = 760

const searchableName = (name: string) => name.toLowerCase().normalize('NFD').replace(/\p{M}/gu, '')

const BUDGET_KEYS: Record<string, MessageKey> = {
  ok: 'playbooks.budget.ok',
  low: 'playbooks.budget.low'
}
const BOTH_KEYS: Record<string, MessageKey> = {
  ask: 'playbooks.both.ask',
  'run-cheapest': 'playbooks.both.runCheapest',
  block: 'playbooks.both.block'
}

export function PlaybooksEditor({
  file,
  initial,
  onSaved,
  onDiscard,
  onEditedChange
}: {
  file: SkillPlaybooks
  initial: PlaybooksState
  onSaved: (file: SkillPlaybooks) => void
  /** Drops the edits that cannot be saved because the playbooks have problems. */
  onDiscard: () => void
  /** Lets the host hold off reloading outside edits while there are unsaved changes. */
  onEditedChange?: (edited: boolean) => void
}) {
  const t = useT()
  const appliedTheme = useAppliedTheme()
  const [s] = useState(() => {
    const provider = activeOrder(initial)[0]
    if (provider) {
      selectPlaybookProvider(initial, provider)
    }
    return initial
  })
  const [usageLoad, setUsageLoad] = useState<'loading' | 'ready' | 'error'>('loading')
  const usageRequest = useRef(0)
  const nativeUsageRefreshAt = useRef(0)
  const [, setVersion] = useState(0)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [info, setInfo] = useState(false)
  const editorRef = useRef<HTMLDivElement>(null)
  const navRef = useRef<HTMLElement>(null)
  const navToggle = useRef<HTMLButtonElement>(null)
  const navId = useId()
  const scenarioId = useId()
  const [compact, setCompact] = useState(false)
  const [navOverride, setNavOverride] = useState<boolean | null>(null)
  const [search, setSearch] = useState('')
  const [scenarioOpen, setScenarioOpen] = useState(false)
  const navOpen = navOverride ?? !compact
  useLayoutEffect(() => {
    const element = editorRef.current
    if (!element || typeof ResizeObserver === 'undefined') {
      return
    }
    let previous = false
    const resize = () => {
      const narrow = element.clientWidth > 0 && element.clientWidth <= COMPACT_EDITOR_WIDTH
      if (narrow !== previous) {
        previous = narrow
        setCompact(narrow)
        setNavOverride(null)
      }
    }
    resize()
    const observer = new ResizeObserver(resize)
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  useLayoutEffect(() => {
    if (compact && navOpen) {
      navRef.current?.focus()
    }
  }, [compact, navOpen])
  const closeNavigation = () => {
    setNavOverride(false)
    navToggle.current?.focus()
  }
  const showInspector = (id: string) => {
    setSelectedId(id)
    if (compact && navOpen) {
      closeNavigation()
    }
  }
  const [yamlOpen, setYamlOpen] = useState(false)
  const [pulse, setPulse] = useState(0)
  const [saving, setSaving] = useState(false)
  const [copied, setCopied] = useState(false)
  // Every edit bumps the revision; a save clears the edited flags only if nothing changed meanwhile.
  const [revision, setRevision] = useState(0)
  const revisionRef = useRef(0)
  useEffect(() => {
    revisionRef.current = revision
  }, [revision])
  const [failedRevision, setFailedRevision] = useState<number | null>(null)
  // What the file holds as far as this editor knows, in the form this editor writes it.
  const [loadedText] = useState(() => toYaml(initial))
  const savedTextRef = useRef(loadedText)
  const snapshot = () => ({ yaml: toYaml(s), workflows: structuredClone(s.workflows) })
  const [history] = useState(() => ({ entries: [snapshot()], index: 0 }))
  const record = () => {
    const next = snapshot()
    const previous = history.entries[history.index]
    if (
      next.yaml === previous.yaml &&
      JSON.stringify(next.workflows) === JSON.stringify(previous.workflows)
    ) {
      return
    }
    history.entries.splice(history.index + 1)
    history.entries.push(next)
    if (history.entries.length > 100) {
      history.entries.shift()
    }
    history.index = history.entries.length - 1
  }
  const revise = () => {
    revisionRef.current += 1
    setRevision(revisionRef.current)
  }
  const restoreSnapshot = (entry: ReturnType<typeof snapshot>) => {
    const restored = createPlaybooksState(entry.yaml)
    restored.workflows = structuredClone(entry.workflows)
    restored.wf = restored.workflows[s.wf] ? s.wf : restored.wf
    const provider =
      s.previewProvider && restored.providers.includes(s.previewProvider)
        ? s.previewProvider
        : activeOrder(restored)[0]
    if (provider) {
      restored.previewProvider = provider
      if (restored.workflows[restored.wf]?.kind === 'playbook') {
        selectPlaybookProvider(restored, provider)
      }
    }
    Object.assign(s, restored, {
      task: s.task,
      usage: s.usage,
      liveUsage: s.liveUsage,
      liveUsageSnapshot: s.liveUsageSnapshot,
      liveUsageReadAt: s.liveUsageReadAt,
      usageMode: s.usageMode,
      checks: s.checks,
      budget: s.budget,
      spent: s.spent,
      globalEdited: true
    })
    setSelectedId(null)
    revise()
    bump()
  }
  const travel = (direction: number) => {
    const index = history.index + direction
    if (index < 0 || index >= history.entries.length) {
      return
    }
    restoreSnapshot(history.entries[index])
    history.index = index
  }
  const restoreBackup = () => {
    if (!file.backupText || saving) {
      return
    }
    try {
      const restored = createPlaybooksState(file.backupText)
      attachDocs(restored)
      restoreSnapshot({ yaml: toYaml(restored), workflows: restored.workflows })
      record()
    } catch (error) {
      pushToast({ title: t('playbooks.restoreFailed'), body: String(error) })
    }
  }

  const replaceYaml = (text: string) => {
    const replaced = createPlaybooksState(text)
    attachDocs(replaced)
    restoreSnapshot({ yaml: toYaml(replaced), workflows: replaced.workflows })
    record()
  }

  const bump = () => setVersion((value) => value + 1)
  const animate = () => setPulse((value) => value + 1)
  const touch = (global = false) => {
    const current = workflowNow(s)
    if (global) {
      s.globalEdited = true
    } else {
      current.edited = true
    }
    if (current.kind === 'playbook') {
      applyDoc(current)
    }
    record()
    revise()
    bump()
  }

  const refreshUsage = useCallback(async () => {
    const request = ++usageRequest.current
    setUsageLoad('loading')
    try {
      const read = window.api?.codingOpus?.readUsage
      const live = window.api?.codingOpus?.manageAccounts ? undefined : window.api?.rateLimits
      let nativeState = live ? await live.get() : null
      if (live && nativeState && Date.now() - nativeUsageRefreshAt.current >= 5 * 60_000) {
        const blocked = [
          nativeState.claude,
          nativeState.codex,
          nativeState.gemini,
          nativeState.opencodeGo,
          nativeState.minimax
        ].some((value) => (value?.usageMetadata?.retryAtMs ?? 0) > Date.now())
        if (!blocked) {
          nativeUsageRefreshAt.current = Date.now()
          nativeState = await live.refresh()
        }
      }
      const result = nativeState
        ? { ok: true as const, value: codingOpusLiveUsage(nativeState) }
        : read
          ? await read()
          : { ok: true as const, value: { providers: {} } }
      if (request !== usageRequest.current) {
        return
      }
      s.liveUsageReadAt = Date.now()
      if (result.ok) {
        s.liveUsageSnapshot = result.value
        applyLiveUsage(s, usageFromSnapshot(result.value, s.liveUsageReadAt))
        setUsageLoad('ready')
        setVersion((value) => value + 1)
      } else {
        setUsageLoad('error')
      }
    } catch {
      if (request === usageRequest.current) {
        setUsageLoad('error')
      }
    }
  }, [s])

  useEffect(() => {
    void refreshUsage()
    const update = () => {
      if (!document.hidden) {
        void refreshUsage()
      }
    }
    const timer = window.setInterval(update, 5 * 60_000)
    const accountsChanged = () => {
      s.liveUsageSnapshot = { providers: {} }
      applyLiveUsage(s, {})
      void refreshUsage()
    }
    document.addEventListener('visibilitychange', update)
    window.addEventListener('focus', update)
    window.addEventListener('coding-opus-accounts-changed', accountsChanged)
    return () => {
      usageRequest.current += 1
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', update)
      window.removeEventListener('focus', update)
      window.removeEventListener('coding-opus-accounts-changed', accountsChanged)
    }
  }, [refreshUsage, s])

  useEffect(() => {
    if (!copied) {
      return
    }
    const timer = setTimeout(() => setCopied(false), 1500)
    return () => clearTimeout(timer)
  }, [copied])

  const wf = workflowNow(s)
  const docView = wf.kind === 'playbook' && wf.doc ? buildDocView(s, t, wf) : null
  const graph = docView ?? buildGraph(s, t, wf)
  const edited = isEdited(s)
  useEffect(() => {
    onEditedChange?.(edited)
  }, [edited, onEditedChange])
  const blocked = hasProblems(s)
  const problems = wf.kind === 'playbook' ? (wf.problems ?? []) : []
  const playbooks = playbooksForProvider(s, s.previewProvider)
  const routing = Object.values(s.workflows).filter((w) => w.kind === 'routing')
  const title =
    wf.kind === 'playbook'
      ? wf.pb.name
      : t('playbooks.routingName', { name: routingName(t, wf.key) })
  const panelOpen = Boolean(selectedId) || info

  const openWorkflow = (w: Workflow) => {
    s.wf = w.id
    if (w.kind === 'routing') {
      s.routingWf = w.id
      touch(true)
    }
    setSelectedId(null)
    if (compact) {
      closeNavigation()
    }
    animate()
    bump()
  }

  const setScenario = <K extends 'task' | 'checks' | 'budget' | 'spent'>(
    key: K,
    value: PlaybooksState[K]
  ) => {
    s[key] = value
    animate()
    bump()
  }

  const removeSelection = () => {
    if (wf.kind !== 'playbook' || !wf.doc || !selectedId) {
      return
    }
    if (selectedId.startsWith('edge:')) {
      const [from, port, to] = selectedId.slice(5).split('|')
      // oxlint-disable-next-line typescript/consistent-type-assertions -- SAFETY: data-from/data-port are written by this canvas from node ids and DocPort values.
      removeEdge(wf.doc, { from, port: port as DocPort, to })
    } else {
      const node = wf.doc.nodes.find((n) => n.id === selectedId)
      if (!node || node.kind === 'start' || node.kind === 'end') {
        return
      }
      removeNode(wf.doc, node.id)
    }
    setSelectedId(null)
    touch()
  }

  const save = async () => {
    const at = revisionRef.current
    const text = toYaml(s)
    const markSaved = () => {
      if (revisionRef.current !== at) {
        return
      }
      Object.values(s.workflows).forEach((w) => {
        w.edited = false
        if (w.kind === 'playbook') {
          saveLayout(w)
        }
      })
      s.globalEdited = false
    }
    // Layout-only changes (a new canvas position, say) produce the same file; skip the write.
    if (text === savedTextRef.current) {
      markSaved()
      bump()
      return
    }
    setSaving(true)
    try {
      const saved = await orchestratorSavePlaybooks(text)
      savedTextRef.current = text
      markSaved()
      setFailedRevision(null)
      onSaved(saved)
      bump()
    } catch (error) {
      setFailedRevision(at)
      pushToast({ title: t('playbooks.saveFailed'), body: String(error) })
    } finally {
      setSaving(false)
    }
  }
  const saveRef = useRef(save)
  useEffect(() => {
    saveRef.current = save
  })

  useEffect(() => {
    if (!edited || blocked || saving || failedRevision === revision) {
      return
    }
    const timer = setTimeout(() => void saveRef.current(), AUTOSAVE_MS)
    return () => clearTimeout(timer)
  }, [revision, edited, blocked, saving, failedRevision])

  const workflowButton = (w: Workflow) => {
    const name = w.kind === 'playbook' ? w.pb.name : routingName(t, w.key)
    const count = w.kind === 'playbook' ? w.pb.phases.length : w.rules.length
    return (
      <button
        key={w.id}
        type="button"
        className={styles.wf}
        title={(w.kind === 'playbook' ? w.pb.pickWhen : undefined) ?? name}
        aria-current={w.id === s.wf}
        onClick={() => openWorkflow(w)}
      >
        <span className={styles.ico}>
          {w.kind === 'routing' ? <GitBranch size={15} /> : <ListTree size={15} />}
        </span>
        <span className={styles.wfName}>{name}</span>
        {w.edited ? <span className={styles.editedDot} /> : null}
        <span className={styles.wfCount}>{count}</span>
      </button>
    )
  }

  const allLow = evalToken(s, 'all-low', context(s)) === true
  const scenarioModified =
    s.task !== 'all' || s.checks !== 'pass' || s.budget !== 'ok' || s.spent !== 0
  const profileName = (key: string) => s.profiles[key]?.name ?? key
  const query = searchableName(search.trim())
  const filteredPlaybooks = playbooks.filter((w) => searchableName(w.pb.name).includes(query))
  const filteredRouting = routing.filter((w) =>
    searchableName(routingName(t, w.key)).includes(query)
  )

  return (
    <PlaybooksContext.Provider
      // oxlint-disable-next-line react/jsx-no-constructed-context-values -- the editor re-renders on every edit through bump(); consumers read the live state each render.
      value={{
        s,
        t,
        theme: appliedTheme,
        lightTheme: isLightTheme(appliedTheme),
        touch,
        redraw: bump,
        select: setSelectedId,
        replaceYaml,
        selectedId
      }}
    >
      <div
        ref={editorRef}
        className={styles.editor}
        data-compact={compact}
        onKeyDownCapture={(event) => {
          if (event.key === 'Escape' && compact && navOpen) {
            event.preventDefault()
            event.stopPropagation()
            closeNavigation()
            return
          }
          const modifier = navigator.userAgent.includes('Mac') ? event.metaKey : event.ctrlKey
          if (
            !modifier ||
            event.altKey ||
            event.nativeEvent.isComposing ||
            (event.target instanceof Element &&
              event.target.closest('input, textarea, [contenteditable="true"]')) ||
            event.key.toLowerCase() !== 'z'
          ) {
            return
          }
          event.preventDefault()
          event.stopPropagation()
          travel(event.shiftKey ? 1 : -1)
        }}
      >
        <header className={styles.toolbar}>
          <div className={styles.toolbarIdentity}>
            <button
              ref={navToggle}
              type="button"
              className={`${styles.toolbarButton} ${styles.toolbarIcon}`}
              aria-label={t('playbooks.toggleNavigation')}
              title={t('playbooks.toggleNavigation')}
              aria-expanded={navOpen}
              aria-controls={navId}
              onClick={() => setNavOverride(!navOpen)}
            >
              <span
                className={styles.brandMark}
                aria-hidden="true"
                style={{ maskImage: `url("${codingOpusLogo}")` }}
              />
            </button>
            <span className={styles.brand}>
              <span className={styles.brandName}>Coding Opus</span>
            </span>
            <span className={styles.divider} aria-hidden="true" />
            {s.previewProvider ? (
              <Select
                className={styles.providerSelect}
                ariaLabel={t('playbooks.previewProvider')}
                value={s.previewProvider}
                options={activeOrder(s).map((id) => ({
                  value: id,
                  label: (
                    <span className={styles.providerOption}>
                      <ProviderMark id={id} size={14} />
                      <span>{providerLabel(s, id)}</span>
                    </span>
                  )
                }))}
                onChange={(provider) => {
                  selectPlaybookProvider(s, provider)
                  setSelectedId(null)
                  if (!navOpen) {
                    setNavOverride(true)
                  }
                  animate()
                  bump()
                }}
              />
            ) : null}
            <h1 className={styles.crumbCurrent} title={title}>
              {title}
            </h1>
            {edited ? <span className={styles.editedDot} title={t('playbooks.edited')} /> : null}
          </div>
          <div className={styles.toolbarSettings}>
            <div className={styles.profilePicker}>
              <span>{t('playbooks.profileLabel')}</span>
              <Select
                className={styles.profileSelect}
                value={s.profile}
                ariaLabel={t('playbooks.profileLabel')}
                options={Object.keys(s.profiles).map((key) => ({
                  value: key,
                  label: profileName(key)
                }))}
                onChange={(value) => {
                  s.profile = value
                  animate()
                  touch(true)
                }}
              />
            </div>
            <div className={styles.toolbarUsage}>
              <span>{t('playbooks.usageTitle')}</span>
              <UsageBar
                load={usageLoad}
                onRefresh={() => void refreshUsage()}
                onChange={() => {
                  animate()
                  bump()
                }}
              />
            </div>
          </div>
          <div className={styles.toolbarActions}>
            <button
              type="button"
              className={`${styles.toolbarButton} ${styles.toolbarIcon}`}
              aria-label={t('playbooks.undo')}
              title={t('playbooks.undo')}
              disabled={history.index === 0}
              onClick={() => travel(-1)}
            >
              <Undo2 size={15} />
            </button>
            <button
              type="button"
              className={`${styles.toolbarButton} ${styles.toolbarIcon}`}
              aria-label={t('playbooks.redo')}
              title={t('playbooks.redo')}
              disabled={history.index === history.entries.length - 1}
              onClick={() => travel(1)}
            >
              <Redo2 size={15} />
            </button>
            <span className={styles.divider} aria-hidden="true" />
            <button
              type="button"
              className={styles.toolbarButton}
              aria-expanded={scenarioOpen}
              aria-controls={scenarioId}
              onClick={() => setScenarioOpen(!scenarioOpen)}
            >
              <SlidersHorizontal size={14} />
              {t('playbooks.scenarioTitle')}
              {scenarioModified ? (
                <span className={styles.editedDot} title={t('playbooks.scenarioModified')} />
              ) : null}
            </button>
            <button
              type="button"
              className={styles.toolbarButton}
              aria-pressed={selectedId === GENERATOR_ID}
              onClick={() => showInspector(GENERATOR_ID)}
            >
              <WandSparkles size={14} />
              {t('playbooks.generateTitle')}
            </button>
            <button
              type="button"
              className={styles.toolbarButton}
              aria-pressed={info && !selectedId}
              onClick={() => {
                setInfo(!(info && !selectedId))
                setSelectedId(null)
                if (compact && navOpen) {
                  closeNavigation()
                }
              }}
            >
              <PanelRight size={14} />
              {t('playbooks.details')}
            </button>
          </div>
        </header>

        <nav
          id={navId}
          ref={navRef}
          tabIndex={-1}
          hidden={!navOpen}
          className={styles.sidebar}
          aria-label={t('playbooks.sidebarTitle')}
        >
          <div className={styles.sideHeader}>
            <span className={styles.sideLabel}>{t('playbooks.sidebarTitle')}</span>
            <span className={styles.count}>{playbooks.length + routing.length}</span>
          </div>
          <label className={styles.sideSearch}>
            <Search size={15} aria-hidden="true" />
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              aria-label={t('playbooks.searchFlows')}
              placeholder={t('playbooks.searchFlows')}
            />
          </label>
          <div className={styles.sideList}>
            {query && !filteredPlaybooks.length && !filteredRouting.length ? (
              <p className={styles.noFlows} role="status">
                {t('playbooks.noFlows')}
              </p>
            ) : null}
            <section
              className={styles.group}
              aria-label={t('playbooks.groupStrategies')}
              hidden={Boolean(query) && !filteredPlaybooks.length}
            >
              <div className={styles.groupTitle}>
                {t('playbooks.groupStrategies')}
                <button
                  type="button"
                  className={styles.groupAdd}
                  aria-label={t('playbooks.newPlaybook')}
                  title={t('playbooks.newPlaybook')}
                  onClick={() => {
                    const family = s.previewProvider === 'claude' ? 'claude' : 'other'
                    const added = addPlaybook(s, t('playbooks.newPlaybookName'), family)
                    s.wf = added.id
                    setSearch('')
                    setSelectedId(null)
                    setInfo(true)
                    if (compact) {
                      closeNavigation()
                    }
                    animate()
                    touch(true)
                  }}
                >
                  <Plus size={12} />
                </button>
              </div>
              {filteredPlaybooks.map(workflowButton)}
            </section>
            <div className={styles.group} hidden={Boolean(query) && !filteredRouting.length}>
              <div className={styles.groupTitle}>{t('playbooks.groupRouting')}</div>
              {filteredRouting.map(workflowButton)}
            </div>
            <div className={styles.group} hidden={Boolean(query)}>
              <div className={styles.groupTitle}>
                {t('playbooks.groupProviders')}
                <span className={styles.groupNote}>{profileName(s.profile)}</span>
              </div>
              {activeOrder(s).map((id, i) => {
                const via = routedVia(s, id)
                return (
                  <button
                    key={id}
                    type="button"
                    className={styles.wf}
                    aria-current={selectedId === `provider:${id}`}
                    onClick={() => showInspector(`provider:${id}`)}
                  >
                    <span className={styles.ico}>
                      <ProviderMark id={id} size={13} />
                    </span>
                    <span className={styles.wfName}>{providerLabel(s, id)}</span>
                    {via ? (
                      <span
                        className={styles.via}
                        title={t('playbooks.throughRoute', { route: ROUTES[via]?.label ?? via })}
                      >
                        <ProviderMark id={via} size={11} />
                      </span>
                    ) : null}
                    <span className={styles.wfCount}>{i + 1}</span>
                  </button>
                )
              })}
              {Object.entries(s.routes).map(([rid, route]) => (
                <button
                  key={rid}
                  type="button"
                  className={styles.wf}
                  aria-current={selectedId === `route:${rid}`}
                  onClick={() => showInspector(`route:${rid}`)}
                >
                  <span className={styles.ico}>
                    <ProviderMark id={rid} size={13} />
                  </span>
                  <span className={styles.wfName}>{ROUTES[rid]?.label ?? rid}</span>
                  <span className={styles.wfCount}>
                    {route.running ? t('playbooks.on') : t('playbooks.off')}
                  </span>
                </button>
              ))}
            </div>
            <div className={styles.group} hidden={Boolean(query)}>
              <div className={styles.groupTitle}>{t('playbooks.groupAccounts')}</div>
              {ACCOUNT_PROVIDERS.map((id) => (
                <button
                  key={id}
                  type="button"
                  className={styles.wf}
                  aria-current={selectedId === `accounts:${id}`}
                  onClick={() => showInspector(`accounts:${id}`)}
                >
                  <span className={styles.ico}>
                    <ProviderMark id={id} size={13} />
                  </span>
                  <span className={styles.wfName}>{providerLabel(s, id)}</span>
                </button>
              ))}
            </div>
          </div>
          <div className={styles.sideFooter}>
            <details className={styles.fileTools}>
              <summary>
                <FileCode size={15} />
                {t('playbooks.fileTools')}
                <ChevronDown size={14} />
              </summary>
              <div className={styles.fileActions}>
                <div className={styles.footerRow}>
                  <span className={styles.footerLabel}>{t('playbooks.fileLabel')}</span>
                  <button
                    type="button"
                    className={styles.toolbarButton}
                    aria-pressed={yamlOpen}
                    onClick={() => {
                      setSelectedId(null)
                      setInfo(false)
                      setYamlOpen(!yamlOpen)
                      if (compact) {
                        closeNavigation()
                      }
                    }}
                  >
                    coding-opus-playbooks.yaml
                  </button>
                </div>
                <p className={styles.fileNote} title={file.path}>
                  {file.custom ? t('playbooks.sourceCustom') : t('playbooks.sourceBundled')}
                </p>
                <button
                  type="button"
                  className={styles.button}
                  aria-pressed={selectedId === MODEL_UPDATES_ID}
                  onClick={() => showInspector(MODEL_UPDATES_ID)}
                >
                  <RefreshCw size={12} />
                  {t('playbooks.modelsUpdateButton')}
                </button>
                <button
                  type="button"
                  className={styles.button}
                  disabled={!file.backupText || saving}
                  onClick={() => {
                    restoreBackup()
                    if (compact) {
                      closeNavigation()
                    }
                  }}
                >
                  {t('playbooks.restoreBackup')}
                </button>
              </div>
            </details>
            <div className={styles.saveRow} role="status">
              <span className={styles.fileNote}>
                {saving
                  ? t('playbooks.saving')
                  : edited && blocked
                    ? t('playbooks.saveBlocked')
                    : edited && failedRevision === revision
                      ? t('playbooks.saveFailed')
                      : edited
                        ? t('playbooks.autoSavePending')
                        : t('playbooks.autoSaved')}
              </span>
              {edited && (blocked || failedRevision === revision) ? (
                <>
                  {failedRevision === revision && !blocked ? (
                    <button type="button" className={styles.button} onClick={() => void save()}>
                      {t('playbooks.retry')}
                    </button>
                  ) : null}
                  <button type="button" className={styles.button} onClick={onDiscard}>
                    {t('playbooks.discard')}
                  </button>
                </>
              ) : null}
            </div>
          </div>
        </nav>

        {compact && navOpen ? (
          <button
            type="button"
            className={styles.navBackdrop}
            tabIndex={-1}
            aria-label={t('common.close')}
            onClick={closeNavigation}
          />
        ) : null}
        <section className={styles.stage} inert={compact && navOpen}>
          <div id={scenarioId} className={styles.scenarioBar} hidden={!scenarioOpen}>
            <span className={styles.scenarioCaption}>{t('playbooks.scenarioPreview')}</span>
            <label className={styles.scenarioItem}>
              <span>{t('playbooks.scenarioTask')}</span>
              <Select
                className={styles.scenarioSelect}
                value={s.task}
                ariaLabel={t('playbooks.scenarioTask')}
                // oxlint-disable-next-line typescript/consistent-type-assertions -- SAFETY: Object.keys of a literal record returns exactly its own keys.
                options={(Object.keys(TASKS) as TaskId[]).map((task) => ({
                  value: task,
                  label: taskLabel(t, task)
                }))}
                onChange={(value) =>
                  // oxlint-disable-next-line typescript/consistent-type-assertions -- SAFETY: the Select only offers options built from this union.
                  setScenario('task', value as TaskId)
                }
              />
            </label>
            <span className={styles.divider} />
            <label className={styles.scenarioItem}>
              <span>{t('playbooks.scenarioChecks')}</span>
              <Select
                className={styles.scenarioSelect}
                value={s.checks}
                ariaLabel={t('playbooks.scenarioChecks')}
                options={CHECKS.map((check) => ({ value: check, label: t(CHECK_KEYS[check]) }))}
                onChange={(value) =>
                  // oxlint-disable-next-line typescript/consistent-type-assertions -- SAFETY: the Select only offers options built from this union.
                  setScenario('checks', value as PlaybooksState['checks'])
                }
              />
            </label>
            <span className={styles.divider} />
            <label className={styles.scenarioItem}>
              <span>{t('playbooks.scenarioBudget')}</span>
              <Select
                className={styles.scenarioSelect}
                value={s.budget}
                ariaLabel={t('playbooks.scenarioBudget')}
                options={BUDGETS.map((budget) => ({
                  value: budget,
                  label: t(BUDGET_KEYS[budget])
                }))}
                onChange={(value) =>
                  // oxlint-disable-next-line typescript/consistent-type-assertions -- SAFETY: the Select only offers options built from this union.
                  setScenario('budget', value as PlaybooksState['budget'])
                }
              />
            </label>
            <span className={styles.divider} />
            <label className={styles.scenarioItem}>
              <span>{t('playbooks.scenarioSpent')}</span>
              <Select
                className={styles.scenarioSelect}
                value={String(s.spent)}
                ariaLabel={t('playbooks.scenarioSpent')}
                options={SPENT_STEPS.map((amount) => ({
                  value: String(amount),
                  label: formatUsd(amount)
                }))}
                onChange={(value) => setScenario('spent', Number(value))}
              />
            </label>
            {allLow ? (
              <>
                <span className={styles.divider} />
                <label className={styles.scenarioItem}>
                  <span>{t('playbooks.scenarioAllLow')}</span>
                  <Select
                    className={styles.scenarioSelect}
                    value={s.quota.onBothCritical}
                    ariaLabel={t('playbooks.scenarioAllLow')}
                    options={ON_BOTH_CRITICAL.map((value) => ({
                      value,
                      label: t(BOTH_KEYS[value])
                    }))}
                    onChange={(value) => {
                      s.quota.onBothCritical = value
                      touch(true)
                    }}
                  />
                </label>
              </>
            ) : null}
            {scenarioModified ? (
              <button
                type="button"
                className={styles.toolbarButton}
                onClick={() => {
                  Object.assign(s, { task: 'all', checks: 'pass', budget: 'ok', spent: 0 })
                  animate()
                  bump()
                }}
              >
                {t('playbooks.scenarioReset')}
              </button>
            ) : null}
          </div>
          <div className={styles.canvasRegion}>
            {wf.kind === 'playbook' && docView ? (
              <NodeCanvas
                key={wf.id}
                wf={wf}
                view={docView}
                pulse={pulse}
                compact={compact}
                reserved={yamlOpen}
                onStructure={() => touch()}
              />
            ) : (
              <FlowCanvas
                graph={graph}
                fitKey={s.wf}
                pulse={pulse}
                compact={compact}
                reserved={yamlOpen}
                onMove={(id, position) => {
                  wf.positions[id] = position
                  bump()
                }}
              />
            )}
            {problems.length ? (
              <button
                type="button"
                className={styles.problemBanner}
                onClick={() => setSelectedId(problems[0].node)}
              >
                {t('playbooks.problemBanner', { count: problems.length })}
              </button>
            ) : null}
          </div>
          {yamlOpen ? (
            <div className={styles.drawer}>
              <header>
                <b>coding-opus-playbooks.yaml</b>
                <span>{t('playbooks.drawerHint')}</span>
                <span className={styles.spacer} />
                <button
                  type="button"
                  className={styles.button}
                  onClick={() => {
                    void navigator.clipboard?.writeText(toYaml(s)).then(() => setCopied(true))
                  }}
                >
                  {copied ? t('playbooks.copied') : t('playbooks.copy')}
                </button>
              </header>
              <pre>{toYaml(s)}</pre>
            </div>
          ) : null}
          <PlaybookGeneratorPanel
            open={selectedId === GENERATOR_ID}
            onClose={() => {
              setSelectedId(null)
              setInfo(false)
            }}
            onApply={(proposal) => {
              const added = appendGeneratedPlaybook(s, proposal)
              s.wf = added.id
              const provider = [s.previewProvider, ...activeOrder(s)].find(
                (id) => id && playbooksForProvider(s, id).some((w) => w.id === added.id)
              )
              if (provider) {
                selectPlaybookProvider(s, provider)
              }
              setSelectedId(null)
              setInfo(false)
              animate()
              touch(true)
            }}
          />
          {panelOpen && selectedId !== GENERATOR_ID ? (
            <Inspector
              graph={graph}
              onDelete={removeSelection}
              onClose={() => {
                setSelectedId(null)
                setInfo(false)
              }}
            />
          ) : null}
        </section>
      </div>
    </PlaybooksContext.Provider>
  )
}
