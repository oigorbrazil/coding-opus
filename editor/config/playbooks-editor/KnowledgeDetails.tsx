import { ArrowUpRight } from 'lucide-react'
import { useId, useRef, useState } from 'react'
import { ConversationContinuation } from './ConversationContinuation'
import { ConversationSummary } from './ConversationSummary'
import { ConversationTitle } from './ConversationTitle'
import {
  agentLabel,
  formatDate,
  localize as t,
  type ConversationDetail,
  type NoteDetail
} from './knowledge-model'
import { libraryCall } from './skill-server-api'
import styles from './Knowledge.module.css'

export function NoteReading({
  note,
  onOpenSource
}: {
  note: NoteDetail
  onOpenSource: (id: string) => void
}) {
  const source = note.sourceConversation
  return (
    <>
      <div className={styles.detailMeta}>{note.id}</div>
      <h2>{note.title}</h2>
      {source ? (
        <div className={styles.actions}>
          <button type="button" className={styles.button} onClick={() => onOpenSource(source)}>
            {t('Abrir conversa de origem', 'Open source conversation')}
          </button>
        </div>
      ) : null}
      <div className={styles.text}>{note.text}</div>
    </>
  )
}

export function ConversationReading({
  conversation,
  onOpen,
  onSaved,
  onOpenNote,
  onDeleted
}: {
  conversation: ConversationDetail
  onOpen: (id: string) => void
  onSaved: (detail: ConversationDetail) => void
  onOpenNote: (id: string) => void
  onDeleted: () => void
}) {
  const [view, setView] = useState<'summary' | 'messages'>('summary')
  const continueButton = useRef<HTMLButtonElement>(null)
  const [olderPages, setOlderPages] = useState<{
    head: number
    page: number
    hasOlder: boolean
    messages: ConversationDetail['messages']
  } | null>(null)
  const head = conversation.messages.at(-1)?.position ?? 0
  const paged = olderPages?.head === head ? olderPages : null
  const archive = [...(paged?.messages ?? []), ...conversation.messages]
  const hasOlder = paged?.hasOlder ?? conversation.hasOlder
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [continuing, setContinuing] = useState(false)
  const continuationId = useId()
  const links = [
    { label: t('Continuação de', 'Continuation of'), refs: conversation.previous },
    { label: t('Continuações', 'Follow-up chats'), refs: conversation.continuations }
  ]

  const older = async () => {
    setLoading(true)
    setError('')
    const page = (paged?.page ?? 0) + 1
    try {
      const next = await libraryCall<ConversationDetail>({
        kind: 'memory',
        action: 'read',
        id: conversation.id,
        page
      })
      setOlderPages({
        head,
        page,
        hasOlder: next.hasOlder,
        messages: [
          ...next.messages.filter(
            (message) => !archive.some((existing) => existing.position === message.position)
          ),
          ...(paged?.messages ?? [])
        ]
      })
    } catch (failure) {
      setError(String(failure))
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <div className={styles.detailMeta} title={conversation.project}>
        {agentLabel(conversation.agent)} · {formatDate(conversation.updated)}
        {conversation.state === 'interrompido' ? ` · ${t('Interrompida', 'Interrupted')}` : null}
      </div>
      <ConversationTitle conversation={conversation} onSaved={onSaved} onDeleted={onDeleted} />
      {conversation.projects && conversation.projects.length > 1 ? (
        <details className={styles.detailMeta}>
          <summary>
            {t('Pastas usadas', 'Folders used')} · {conversation.projects.length}
          </summary>
          <ul>
            {conversation.projects.map((project) => (
              <li key={project}>{project}</li>
            ))}
          </ul>
        </details>
      ) : null}
      {links.map(({ label, refs }) =>
        refs?.length ? (
          <div key={label} className={`${styles.actions} ${styles.detailMeta}`}>
            <span>{label}</span>
            {refs.map((ref) => (
              <button
                key={ref.id}
                className={`${styles.button} ${styles.conversationLink}`}
                type="button"
                onClick={() => onOpen(ref.id)}
              >
                {agentLabel(ref.agent)} · {ref.title}
              </button>
            ))}
          </div>
        ) : null
      )}
      <div className={styles.conversationActions}>
        <div
          className={styles.detailTabs}
          aria-label={t('Seções da conversa', 'Conversation sections')}
        >
          <button
            type="button"
            aria-pressed={view === 'summary'}
            onClick={() => setView('summary')}
          >
            {t('Resumo', 'Summary')}
          </button>
          <button
            type="button"
            aria-pressed={view === 'messages'}
            onClick={() => setView('messages')}
          >
            {t('Mensagens', 'Messages')} <span>{conversation.count}</span>
          </button>
        </div>
        <button
          ref={continueButton}
          type="button"
          className={styles.button}
          aria-expanded={continuing}
          aria-controls={continuing ? continuationId : undefined}
          onClick={() => setContinuing((value) => !value)}
        >
          <ArrowUpRight size={15} aria-hidden="true" />
          {t('Continuar em', 'Continue in')}
        </button>
      </div>
      {continuing ? (
        <ConversationContinuation
          id={continuationId}
          conversation={conversation}
          onClose={() => {
            setContinuing(false)
            continueButton.current?.focus()
          }}
        />
      ) : null}
      {view === 'summary' ? (
        <ConversationSummary
          conversation={conversation}
          onSaved={onSaved}
          onOpenNote={onOpenNote}
        />
      ) : (
        <>
          {hasOlder ? (
            <button
              className={styles.button}
              type="button"
              onClick={() => void older()}
              disabled={loading}
            >
              {loading
                ? t('Carregando…', 'Loading…')
                : t('Carregar mensagens anteriores', 'Load earlier messages')}
            </button>
          ) : null}
          {error ? (
            <p className={styles.error} role="alert">
              {error}
            </p>
          ) : null}
          {archive.length ? (
            <ol className={styles.transcript}>
              {archive.map((message) => (
                <li key={message.position}>
                  <div className={styles.messageTitle}>
                    <strong>
                      {message.role === 'user' ? t('Você', 'You') : agentLabel(conversation.agent)}
                    </strong>
                    <time dateTime={message.timestamp}>{formatDate(message.timestamp)}</time>
                  </div>
                  {conversation.projects && conversation.projects.length > 1 && message.project ? (
                    <div className={styles.detailMeta}>{message.project}</div>
                  ) : null}
                  <div className={styles.text}>{message.content}</div>
                </li>
              ))}
            </ol>
          ) : (
            <p className={styles.muted}>
              {t('Nenhuma mensagem capturada.', 'No captured messages.')}
            </p>
          )}
        </>
      )}
    </>
  )
}
