import { useCallback, useEffect, useRef, useState } from 'react'
import { BookOpen, Layers, MessagesSquare, Radio, Zap } from 'lucide-react'
import { PlaybooksPage } from '../../src/renderer/src/components/settings/coding-opus/playbooks/PlaybooksPage'
import { KnowledgePage } from './KnowledgePage'
import { AutomationsPage } from './AutomationsPage'
import { StartupSplash } from './StartupSplash'
import { localize as t } from './knowledge-model'
import { RemotePage } from './RemotePage'
import { useUpdateCheck } from './UpdateCheck'
import styles from './Knowledge.module.css'

const STAMP_POLL_MS = 3000
const APP_VIEWS = [
  { view: 'playbooks', name: 'Playbooks', icon: Layers },
  { view: 'notes', name: 'Second Brain', icon: BookOpen },
  { view: 'memory', name: t('Memória', 'Memory'), icon: MessagesSquare },
  { view: 'automations', name: t('Automações', 'Automations'), icon: Zap },
  { view: 'remote', name: t('Controle remoto', 'Remote control'), icon: Radio }
] as const

const stampApi = () =>
  // oxlint-disable-next-line typescript/consistent-type-assertions -- SAFETY: the standalone page installs the desktop api shape the shared editor reads.
  (window as unknown as { api: { codingOpus: { playbooksStamp: () => Promise<number> } } }).api
    .codingOpus

/** Full-window editor; reloads when the file changes elsewhere (the Coding Agent, an agent, by hand). */
export function CodingOpusEditorApp(): React.JSX.Element {
  const [view, setView] = useState(() => {
    const requested = new URLSearchParams(window.location.hash.slice(1)).get('view')
    return APP_VIEWS.find((item) => item.view === requested)?.view ?? 'playbooks'
  })
  const [librarySelection, setLibrarySelection] = useState(() =>
    new URLSearchParams(window.location.hash.slice(1)).get('item')
  )
  const [generation, setGeneration] = useState(0)
  const [startupReady, setStartupReady] = useState(false)
  const [showStartup, setShowStartup] = useState(true)
  const onLoadSettled = useCallback(() => setStartupReady(true), [])
  const onStartupComplete = useCallback(() => setShowStartup(false), [])
  const [outsideChange, setOutsideChange] = useState(false)
  const editedRef = useRef(false)
  const stampRef = useRef<number | null>(null)
  // Set while this editor's own save is landing, so the stamp it moves does not remount the editor.
  const selfSaveRef = useRef(false)
  const pt = navigator.language.toLowerCase().startsWith('pt')
  const updates = useUpdateCheck()

  const navigate = (next: typeof view, item: string | null = null) => {
    const params = new URLSearchParams(window.location.hash.slice(1))
    if (next === 'playbooks') {
      params.delete('view')
    } else {
      params.set('view', next)
    }
    if (item) {
      params.set('item', item)
    } else {
      params.delete('item')
    }
    window.history.replaceState(null, '', `#${params}`)
    setLibrarySelection(item)
    setView(next)
  }

  const onEditedChange = useCallback((edited: boolean) => {
    editedRef.current = edited
    if (!edited) {
      setOutsideChange(false)
    }
  }, [])

  const onSaved = useCallback(() => {
    selfSaveRef.current = true
    void stampApi()
      .playbooksStamp()
      .then((stamp) => {
        stampRef.current = stamp
      })
      .catch(() => undefined)
      .finally(() => {
        selfSaveRef.current = false
      })
  }, [])

  useEffect(() => {
    const api = stampApi()
    let live = true
    const check = async (): Promise<void> => {
      const stamp = await api.playbooksStamp().catch(() => null)
      if (!live || stamp === null) {
        return
      }
      const previous = stampRef.current
      stampRef.current = stamp
      if (previous === null || previous === stamp) {
        return
      }
      if (selfSaveRef.current) {
        return
      }
      if (editedRef.current) {
        setOutsideChange(true)
      } else {
        setGeneration((value) => value + 1)
      }
    }
    void check()
    const timer = window.setInterval(() => void check(), STAMP_POLL_MS)
    return () => {
      live = false
      window.clearInterval(timer)
    }
  }, [])

  return (
    <div className="ca1-playbook-tokens editor-shell">
      <div className="editor-content" inert={showStartup}>
        <nav
          className={styles.navigation}
          aria-label={t('Áreas da Coding Opus', 'Coding Opus areas')}
        >
          {APP_VIEWS.map(({ view: target, name, icon: Icon }) => (
            <button
              key={target}
              type="button"
              aria-current={view === target ? 'page' : undefined}
              onClick={() => navigate(target)}
            >
              <Icon size={15} /> {name}
            </button>
          ))}
          {updates.button}
        </nav>
        {updates.notice}
        {outsideChange && view === 'playbooks' ? (
          <div className="editor-notice">
            {pt
              ? 'O arquivo de playbooks também mudou fora desta página; a edição que você está fazendo aqui o substitui ao salvar.'
              : 'The playbooks file also changed outside this page; the edit you are making here replaces it when it saves.'}
          </div>
        ) : null}
        <div className="editor-body" hidden={view !== 'playbooks'}>
          <PlaybooksPage
            key={generation}
            onEditedChange={onEditedChange}
            onSaved={onSaved}
            onLoadSettled={view === 'playbooks' && showStartup ? onLoadSettled : undefined}
          />
        </div>
        {view === 'automations' ? <AutomationsPage onLoadSettled={onLoadSettled} /> : null}
        {view === 'remote' ? <RemotePage onLoadSettled={onLoadSettled} /> : null}
        {view === 'notes' || view === 'memory' ? (
          <KnowledgePage
            key={view}
            kind={view}
            initialSelection={librarySelection}
            onNavigate={navigate}
            onLoadSettled={onLoadSettled}
          />
        ) : null}
      </div>
      {showStartup ? <StartupSplash ready={startupReady} onComplete={onStartupComplete} /> : null}
    </div>
  )
}
