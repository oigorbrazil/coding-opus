import { ArrowLeft, Bell, Check, FileText, Pencil, Plus, RotateCcw } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { NoteForm } from './NoteForm'
import {
  formatDate,
  localize as t,
  type LibraryIndex,
  type Reminder,
  type ReminderList
} from './knowledge-model'
import { libraryCall } from './skill-server-api'
import styles from './Knowledge.module.css'

type ReminderDraft = { id?: string; title: string; due: string }
type ReminderAction =
  | ({ action: 'save' } & ReminderDraft)
  | { action: 'complete' | 'reopen'; id: string }

function localDay(): string {
  const date = new Date()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

function reminderTitle(item: Reminder): string {
  return (
    item.title ||
    ({
      document: t('Documentar no Second Brain', 'Document in Second Brain'),
      memory: t('Revisar conversas', 'Review conversations'),
      review: t('Revisar Second Brain', 'Review Second Brain')
    }[item.shortcut] ??
      t('Lembrete', 'Reminder'))
  )
}

function DocumentReminder({ onCancel, onSaved }: { onCancel: () => void; onSaved: () => void }) {
  const [catalog, setCatalog] = useState<LibraryIndex | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    void libraryCall<LibraryIndex>({ kind: 'notes', action: 'list' }, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) {
          setCatalog(result)
        }
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted) {
          setError(String(failure))
        }
      })
    return () => controller.abort()
  }, [])

  if (error) {
    return (
      <p className={styles.error} role="alert">
        {error}
      </p>
    )
  }
  if (!catalog) {
    return (
      <p className={styles.muted} role="status">
        {t('Carregando seções…', 'Loading sections…')}
      </p>
    )
  }
  if (!catalog.exists || !catalog.groups.length) {
    return (
      <p role="status">
        {t(
          'Configure a pasta do Second Brain para salvar uma nota.',
          'Set up the Second Brain folder to save a note.'
        )}
      </p>
    )
  }
  return (
    <NoteForm
      groups={catalog.groups}
      initialGroup="00-Inbox"
      onCancel={onCancel}
      onSaved={onSaved}
    />
  )
}

export function RemindersPage({ onLoadSettled }: { onLoadSettled: () => void }) {
  const [agenda, setAgenda] = useState<ReminderList | null>(null)
  const [reload, setReload] = useState(0)
  const [draft, setDraft] = useState<ReminderDraft | null>(null)
  const [documenting, setDocumenting] = useState<string | null>(null)
  const [savedDocument, setSavedDocument] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    void libraryCall<ReminderList>(
      { kind: 'reminders', action: 'list', today: localDay() },
      AbortSignal.any([controller.signal, AbortSignal.timeout(15000)])
    )
      .then((result) => {
        if (!controller.signal.aborted) {
          setAgenda(result)
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
          onLoadSettled()
        }
      })
    return () => controller.abort()
  }, [onLoadSettled, reload])

  const act = async (action: ReminderAction) => {
    setBusy(true)
    setError('')
    try {
      setAgenda(
        await libraryCall<ReminderList>({ kind: 'reminders', today: localDay(), ...action })
      )
      if (action.action === 'save') {
        setDraft(null)
      }
      if (action.action === 'complete') {
        setSavedDocument((current) => (current === action.id ? null : current))
      }
    } catch (failure) {
      setError(String(failure))
    } finally {
      setBusy(false)
    }
  }

  const save = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (draft && !busy) {
      void act({ action: 'save', ...draft })
    }
  }

  return (
    <main className={styles.library}>
      <header className={styles.header}>
        <div className={styles.identity}>
          <Bell size={19} aria-hidden="true" />
          <h1>{t('Lembretes', 'Reminders')}</h1>
        </div>
        {documenting ? (
          <button className={styles.button} type="button" onClick={() => setDocumenting(null)}>
            <ArrowLeft size={15} /> {t('Voltar aos lembretes', 'Back to reminders')}
          </button>
        ) : (
          <button
            className={styles.primary}
            type="button"
            disabled={!agenda || busy || Boolean(draft)}
            onClick={() => setDraft({ title: '', due: localDay() })}
          >
            <Plus size={15} /> {t('Novo lembrete', 'New reminder')}
          </button>
        )}
      </header>
      <div className={styles.remindersPane} aria-busy={busy}>
        {error ? (
          <p className={styles.error} role="alert">
            {error}
          </p>
        ) : null}
        {!agenda && !error ? (
          <p className={styles.muted} role="status">
            {t('Carregando…', 'Loading…')}
          </p>
        ) : null}
        {!agenda && error ? (
          <button
            className={styles.button}
            type="button"
            onClick={() => {
              setError('')
              setReload((previous) => previous + 1)
            }}
          >
            {t('Tentar novamente', 'Try again')}
          </button>
        ) : null}
        {documenting ? (
          <DocumentReminder
            onCancel={() => setDocumenting(null)}
            onSaved={() => {
              setSavedDocument(documenting)
              setDocumenting(null)
              void act({ action: 'complete', id: documenting })
            }}
          />
        ) : (
          <>
            {draft ? (
              <form className={`${styles.noteForm} ${styles.reminderForm}`} onSubmit={save}>
                <h2>
                  {draft.id
                    ? t('Editar lembrete', 'Edit reminder')
                    : t('Novo lembrete', 'New reminder')}
                </h2>
                <div className={styles.reminderFields}>
                  <label>
                    {t('Título', 'Title')}
                    <input
                      required
                      maxLength={120}
                      disabled={busy}
                      value={draft.title}
                      onChange={(event) => setDraft({ ...draft, title: event.target.value })}
                    />
                  </label>
                  <label>
                    {t('Data', 'Date')}
                    <input
                      required
                      type="date"
                      min="0001-01-01"
                      max="9999-12-31"
                      disabled={busy}
                      value={draft.due}
                      onChange={(event) => setDraft({ ...draft, due: event.target.value })}
                    />
                  </label>
                </div>
                <div className={styles.actions}>
                  <button
                    type="submit"
                    className={styles.primary}
                    disabled={busy || !draft.title.trim() || !draft.due}
                  >
                    {t('Salvar lembrete', 'Save reminder')}
                  </button>
                  <button
                    type="button"
                    className={styles.button}
                    disabled={busy}
                    onClick={() => setDraft(null)}
                  >
                    {t('Cancelar', 'Cancel')}
                  </button>
                </div>
              </form>
            ) : null}
            <ul className={styles.reminderList}>
              {agenda
                ? agenda.items.map((item) => {
                    const title = reminderTitle(item)
                    const document = item.shortcut === 'document' && savedDocument !== item.id
                    return (
                      <li key={item.id} className={styles.reminderRow}>
                        <div className={styles.reminderInfo}>
                          <strong>{title}</strong>
                          <span className={styles.muted}>
                            <time dateTime={item.due}>{formatDate(item.due)}</time>
                            {item.completed ? ` · ${t('Concluído', 'Completed')}` : null}
                            {!item.completed && item.due < agenda.today
                              ? ` · ${t('Atrasado', 'Overdue')}`
                              : null}
                          </span>
                        </div>
                        <div className={styles.actions}>
                          {item.completed ? (
                            <button
                              className={styles.button}
                              type="button"
                              disabled={busy}
                              onClick={() => void act({ action: 'reopen', id: item.id })}
                            >
                              <RotateCcw size={15} /> {t('Reabrir', 'Reopen')}
                            </button>
                          ) : (
                            <>
                              <button
                                className={styles.iconButton}
                                type="button"
                                disabled={busy || Boolean(draft)}
                                aria-label={`${t('Editar', 'Edit')} ${title}`}
                                onClick={() => setDraft({ id: item.id, title, due: item.due })}
                              >
                                <Pencil size={15} />
                              </button>
                              <button
                                className={styles.button}
                                type="button"
                                disabled={busy || Boolean(draft)}
                                onClick={() =>
                                  document
                                    ? setDocumenting(item.id)
                                    : void act({ action: 'complete', id: item.id })
                                }
                              >
                                {document ? <FileText size={15} /> : <Check size={15} />}
                                {document ? t('Documentar', 'Document') : t('Concluir', 'Complete')}
                              </button>
                            </>
                          )}
                        </div>
                      </li>
                    )
                  })
                : null}
            </ul>
          </>
        )}
      </div>
    </main>
  )
}
