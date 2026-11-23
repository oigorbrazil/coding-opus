import {
  ArrowLeft,
  BookOpen,
  FileText,
  Folder,
  FolderOpen,
  MessagesSquare,
  Plus,
  RefreshCw,
  Search
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { ConversationReading, NoteReading } from './KnowledgeDetails'
import { KnowledgePager } from './KnowledgePager'
import { NoteForm } from './NoteForm'
import {
  agentLabel,
  formatDate,
  localize as t,
  type LibraryDetail,
  type LibraryIndex,
  type LibraryKind
} from './knowledge-model'
import { libraryCall } from './skill-server-api'
import { useKnowledgeRevision } from './use-knowledge-revision'
import styles from './Knowledge.module.css'

export function KnowledgePage({
  kind,
  initialSelection = null,
  initialCreate = false,
  onNavigate,
  onLoadSettled
}: {
  kind: LibraryKind
  initialSelection?: string | null
  initialCreate?: boolean
  onNavigate: (kind: LibraryKind, item: string) => void
  onLoadSettled?: () => void
}) {
  const notes = kind === 'notes'
  const title = notes ? 'Second Brain' : t('Memória', 'Memory')
  const Icon = notes ? BookOpen : MessagesSquare
  const [catalog, setCatalog] = useState<LibraryIndex | null>(null)
  const [group, setGroup] = useState('')
  const [draft, setDraft] = useState('')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(0)
  const [revision, setRevision] = useKnowledgeRevision(kind)
  const [selected, setSelected] = useState(initialSelection)
  const [detail, setDetail] = useState<LibraryDetail | null>(null)
  const [creating, setCreating] = useState(initialCreate)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const [detailError, setDetailError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    void libraryCall<LibraryIndex>({ kind, action: 'list', group, query, page }, controller.signal)
      .then((payload) => {
        if (!controller.signal.aborted) {
          setCatalog(payload)
          setError('')
        }
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted) {
          setError(String(failure))
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setBusy(false)
          onLoadSettled?.()
        }
      })
    return () => controller.abort()
  }, [kind, group, query, page, revision, onLoadSettled])

  useEffect(() => {
    if (!selected) {
      return
    }
    const controller = new AbortController()
    void libraryCall<LibraryDetail>({ kind, action: 'read', id: selected }, controller.signal)
      .then((payload) => {
        if (!controller.signal.aborted) {
          setDetail(payload)
          setDetailError('')
        }
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted) {
          setDetailError(String(failure))
        }
      })
    return () => controller.abort()
  }, [kind, selected, revision])

  const refresh = () => {
    setBusy(true)
    setRevision((current) => current + 1)
  }
  const [switching, setSwitching] = useState(false)
  const [switchNote, setSwitchNote] = useState('')
  const memoryOn = Boolean(catalog?.enabled)
  const switchMemory = async () => {
    setSwitching(true)
    setSwitchNote('')
    try {
      await libraryCall({ kind: 'memory', action: 'switch', enabled: !memoryOn })
      setError('')
      setSwitchNote(
        memoryOn
          ? t(
              'Memória desligada: os novos chats não são mais registrados. O histórico continua aqui.',
              'Memory off: new chats are no longer recorded. The history stays here.'
            )
          : t(
              'Memória ligada: os novos chats do Claude Code e do Codex passam a ser registrados. No Codex, aprove os novos hooks em /hooks.',
              'Memory on: new Claude Code and Codex chats are recorded from now on. In Codex, approve the new hooks in /hooks.'
            )
      )
      refresh()
    } catch (failure) {
      setError(String(failure))
    } finally {
      setSwitching(false)
    }
  }
  const clearDetail = () => {
    setSelected(null)
    setDetail(null)
    setDetailError('')
    setCreating(false)
  }
  const openDetail = (id: string) => {
    if (selected !== id || creating) {
      clearDetail()
      setSelected(id)
    }
  }
  const selectGroup = (id: string) => {
    if (id !== group || page) {
      setBusy(true)
      setGroup(id)
      setPage(0)
      clearDetail()
    }
  }
  const search = (value: string) => {
    const next = value.trim()
    if (next !== query || page) {
      setBusy(true)
      setQuery(next)
      setPage(0)
      clearDetail()
    }
  }
  const reveal = () => {
    void libraryCall({ kind, action: 'reveal' }).catch((failure: unknown) =>
      setError(String(failure))
    )
  }

  const available = Boolean(catalog?.exists && catalog.enabled)
  const pages = catalog ? Math.ceil(catalog.total / catalog.pageSize) : 0
  const groups = catalog?.groups ?? []
  const showNoteForm = creating && available && groups.length > 0
  const currentGroup = groups.find((section) => section.id === group)
  const allLabel = notes
    ? t('Todas as notas', 'All notes')
    : t('Todas as conversas', 'All conversations')
  const hasDetail = Boolean(selected || showNoteForm)

  return (
    <main className={styles.library} data-detail={hasDetail}>
      <header className={styles.header}>
        <div className={styles.identity}>
          <Icon size={19} aria-hidden="true" />
          <div>
            <h1>{title}</h1>
            {catalog ? (
              <div className={styles.path} title={catalog.path}>
                {catalog.path}
              </div>
            ) : null}
          </div>
        </div>
        <div className={styles.actions}>
          {!notes && catalog?.exists ? (
            <label
              className={styles.memorySwitch}
              title={t(
                'Registra os pedidos e respostas dos chats no Second Brain',
                'Records chat requests and answers in the Second Brain'
              )}
            >
              <span className={styles.automationSwitch}>
                <input
                  type="checkbox"
                  role="switch"
                  checked={memoryOn}
                  disabled={switching || busy}
                  onChange={() => void switchMemory()}
                />
                <span aria-hidden="true" />
              </span>
              {memoryOn ? t('Memória ligada', 'Memory on') : t('Memória desligada', 'Memory off')}
            </label>
          ) : null}
          {available ? (
            <button className={styles.button} type="button" onClick={reveal}>
              <FolderOpen size={15} /> {t('Abrir pasta', 'Open folder')}
            </button>
          ) : null}
          <button className={styles.button} type="button" onClick={refresh} disabled={busy}>
            <RefreshCw size={15} /> {t('Atualizar', 'Refresh')}
          </button>
          {notes && available && groups.length > 0 ? (
            <button
              className={styles.primary}
              type="button"
              onClick={() => {
                clearDetail()
                setCreating(true)
              }}
            >
              <Plus size={15} /> {t('Nova nota', 'New note')}
            </button>
          ) : null}
        </div>
      </header>
      {error ? (
        <p className={styles.alert} role="alert">
          {error}
        </p>
      ) : null}
      {switchNote ? (
        <p className={styles.alert} role="status">
          {switchNote}
        </p>
      ) : null}
      {catalog && !available && !switchNote ? (
        <p className={styles.alert} role="status">
          {!catalog.exists
            ? t('Pasta Second Brain ausente.', 'Second Brain folder is missing.')
            : t(
                'A memória de chats está desligada. Ligue no interruptor acima para registrar as conversas.',
                'Chat memory is off. Turn it on with the switch above to record conversations.'
              )}
        </p>
      ) : null}
      <div
        className={styles.sections}
        aria-label={notes ? t('Seções', 'Sections') : t('Projetos', 'Projects')}
      >
        <h2>{notes ? t('Seções', 'Sections') : t('Projetos', 'Projects')}</h2>
        <button type="button" aria-pressed={group === ''} onClick={() => selectGroup('')}>
          <Icon size={15} />
          <span>{allLabel}</span>
          <small>{catalog?.count ?? 0}</small>
        </button>
        {groups.map((section) => (
          <button
            key={section.id}
            type="button"
            title={section.path ?? section.id}
            aria-pressed={group === section.id}
            onClick={() => selectGroup(section.id)}
          >
            <Folder size={15} />
            <span>{section.label}</span>
            <small>{section.count}</small>
          </button>
        ))}
      </div>
      <section
        className={styles.entries}
        aria-label={notes ? t('Notas', 'Notes') : t('Conversas', 'Conversations')}
        aria-busy={busy}
      >
        <div className={styles.listHead}>
          <h2>{currentGroup?.label ?? allLabel}</h2>
          <form
            className={styles.search}
            onSubmit={(event) => {
              event.preventDefault()
              search(draft)
            }}
          >
            <input
              type="search"
              value={draft}
              maxLength={300}
              disabled={!available}
              placeholder={
                notes
                  ? t('Buscar título, tag ou alias', 'Search title, tag or alias')
                  : t('Buscar por título ou mensagem', 'Search by title or message')
              }
              aria-label={
                notes
                  ? t('Buscar notas', 'Search notes')
                  : t('Buscar conversas', 'Search conversations')
              }
              onChange={(event) => {
                setDraft(event.target.value)
                if (!event.target.value) {
                  search('')
                }
              }}
            />
            <button
              type="submit"
              className={styles.iconButton}
              disabled={!available}
              aria-label={t('Buscar', 'Search')}
            >
              <Search size={15} />
            </button>
          </form>
        </div>
        {busy && !catalog ? (
          <p className={styles.listStatus} role="status">
            {t('Carregando…', 'Loading…')}
          </p>
        ) : null}
        {available && !busy && catalog?.entries.length === 0 ? (
          <p className={styles.listStatus}>
            {query
              ? t('Nenhum resultado para esta busca.', 'Nothing matches this search.')
              : notes
                ? t('Nenhuma nota nesta seção.', 'No notes in this section.')
                : t('Nenhuma conversa capturada.', 'No conversations captured.')}
          </p>
        ) : null}
        <ul className={styles.list}>
          {catalog?.entries.map((entry) => (
            <li key={entry.id}>
              <button
                type="button"
                aria-current={selected === entry.id ? 'true' : undefined}
                onClick={() => openDetail(entry.id)}
              >
                {notes ? <FileText size={16} /> : <MessagesSquare size={16} />}
                <span>
                  <strong title={notes ? undefined : entry.title}>{entry.title}</strong>
                  <small>
                    {[
                      entry.agent ? agentLabel(entry.agent) : entry.type,
                      notes
                        ? groups.find((section) => section.id === entry.group)?.label
                        : entry.group,
                      formatDate(entry.updated)
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </small>
                </span>
              </button>
            </li>
          ))}
        </ul>
        <KnowledgePager
          page={page}
          pages={pages}
          busy={busy}
          onPage={(next) => {
            setBusy(true)
            setPage(next)
          }}
        />
      </section>
      <article className={styles.detail}>
        {hasDetail ? (
          <button className={styles.back} type="button" onClick={clearDetail}>
            <ArrowLeft size={15} />{' '}
            {notes
              ? t('Voltar às notas', 'Back to notes')
              : t('Voltar às conversas', 'Back to conversations')}
          </button>
        ) : null}
        {showNoteForm ? (
          <NoteForm
            groups={groups}
            initialGroup={group}
            onCancel={clearDetail}
            onSaved={(note, section) => {
              setCreating(false)
              setGroup(section)
              setQuery('')
              setDraft('')
              setPage(0)
              setSelected(note.id)
              setDetail(null)
              refresh()
            }}
          />
        ) : null}
        {detailError ? (
          <p className={styles.error} role="alert">
            {detailError}
          </p>
        ) : null}
        {detail ? (
          'messages' in detail ? (
            <ConversationReading
              key={detail.id}
              conversation={detail}
              onOpen={openDetail}
              onSaved={(next) => {
                setDetail((current) => (current?.id === next.id ? next : current))
                refresh()
              }}
              onOpenNote={(id) => onNavigate('notes', id)}
              onDeleted={() => {
                clearDetail()
                setPage(0)
                refresh()
              }}
            />
          ) : (
            <NoteReading note={detail} onOpenSource={(id) => onNavigate('memory', id)} />
          )
        ) : null}
        {selected && !detail && !detailError ? (
          <p className={styles.muted} role="status">
            {t('Carregando…', 'Loading…')}
          </p>
        ) : null}
        {!hasDetail && available ? (
          <div className={styles.placeholder}>
            <Icon size={23} />
            <p>
              {notes
                ? t('Selecione uma nota para ler.', 'Select a note to read it.')
                : t('Selecione uma conversa para ler.', 'Select a conversation to read it.')}
            </p>
          </div>
        ) : null}
      </article>
    </main>
  )
}
