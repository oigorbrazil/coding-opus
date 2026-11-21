import { useEffect, useState, type FormEvent } from 'react'
import {
  checkpointFields,
  localize as t,
  type CheckpointDetails,
  type ConversationDetail,
  type LibraryIndex,
  type NoteDetail
} from './knowledge-model'
import { NoteForm } from './NoteForm'
import { libraryCall } from './skill-server-api'
import styles from './Knowledge.module.css'

function CheckpointForm({
  conversation,
  onSave,
  onCancel
}: {
  conversation: ConversationDetail
  onSave: (detail: ConversationDetail) => void
  onCancel: () => void
}) {
  const [details, setDetails] = useState<CheckpointDetails>(conversation.checkpoint?.details ?? {})
  const [summary, setSummary] = useState(conversation.summary)
  const [next, setNext] = useState(conversation.next_step)
  const [through] = useState(conversation.messages.at(-1)?.position ?? 0)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (saving) {
      return
    }
    setSaving(true)
    setError('')
    try {
      const updated = await libraryCall<ConversationDetail>({
        kind: 'memory',
        action: 'checkpoint',
        id: conversation.id,
        details,
        summary,
        next_step: next,
        through_position: through
      })
      onSave(updated)
    } catch (failure) {
      setError(String(failure))
    } finally {
      setSaving(false)
    }
  }

  return (
    <form className={styles.noteForm} onSubmit={(event) => void save(event)}>
      <label>
        {checkpointFields[0].label}
        <textarea
          rows={2}
          maxLength={4000}
          value={details.objective ?? ''}
          onChange={(event) => setDetails({ ...details, objective: event.target.value })}
        />
      </label>
      <label>
        {t('O que foi feito', 'What was done')}
        <textarea
          required
          rows={4}
          maxLength={8000}
          value={summary}
          onChange={(event) => setSummary(event.target.value)}
        />
      </label>
      {checkpointFields.slice(1).map(({ key, label }) => (
        <label key={key}>
          {label}
          <textarea
            rows={2}
            maxLength={4000}
            value={details[key] ?? ''}
            onChange={(event) => setDetails({ ...details, [key]: event.target.value })}
          />
        </label>
      ))}
      <label>
        {t('Próximo passo', 'Next step')}
        <textarea
          rows={2}
          maxLength={4000}
          value={next}
          onChange={(event) => setNext(event.target.value)}
        />
      </label>
      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
      <div className={styles.actions}>
        <button className={styles.primary} type="submit" disabled={saving || !summary.trim()}>
          {saving ? t('Salvando…', 'Saving…') : t('Salvar checkpoint', 'Save checkpoint')}
        </button>
        <button className={styles.button} type="button" disabled={saving} onClick={onCancel}>
          {t('Cancelar', 'Cancel')}
        </button>
      </div>
    </form>
  )
}

function DecisionDraft({
  conversation,
  onCancel,
  onSaved
}: {
  conversation: ConversationDetail
  onCancel: () => void
  onSaved: (note: NoteDetail) => void
}) {
  const [result, setResult] = useState<LibraryIndex | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    void libraryCall<LibraryIndex>({ kind: 'notes', action: 'list' }, controller.signal)
      .then(setResult)
      .catch((failure: unknown) => {
        if (!controller.signal.aborted) {
          setError(String(failure))
        }
      })
    return () => controller.abort()
  }, [])

  if (!result?.groups.length) {
    return (
      <div className={styles.actions}>
        <span className={error ? styles.error : styles.muted} role="status">
          {error ||
            (result
              ? t(
                  'Nenhuma seção disponível no Second Brain.',
                  'No Second Brain sections available.'
                )
              : t('Carregando seções…', 'Loading sections…'))}
        </span>
        <button className={styles.button} type="button" onClick={onCancel}>
          {t('Voltar', 'Back')}
        </button>
      </div>
    )
  }
  return (
    <NoteForm
      groups={result.groups}
      initialGroup="00-Inbox"
      onCancel={onCancel}
      onSaved={onSaved}
      draft={{
        title: conversation.title.slice(0, 180),
        text: [
          t('## Contexto', '## Context'),
          conversation.checkpoint?.details.objective ?? conversation.summary,
          t('## Decisão', '## Decision'),
          '',
          t('## Motivo', '## Reason')
        ].join('\n\n'),
        sourceConversation: conversation.id
      }}
    />
  )
}

export function ConversationSummary({
  conversation,
  onSaved,
  onOpenNote
}: {
  conversation: ConversationDetail
  onSaved: (detail: ConversationDetail) => void
  onOpenNote: (id: string) => void
}) {
  const [mode, setMode] = useState<'read' | 'checkpoint' | 'decision'>('read')
  const [savedNote, setSavedNote] = useState<NoteDetail | null>(null)
  if (mode === 'checkpoint') {
    return (
      <CheckpointForm
        conversation={conversation}
        onCancel={() => setMode('read')}
        onSave={(detail) => {
          onSaved(detail)
          setMode('read')
        }}
      />
    )
  }
  if (mode === 'decision') {
    return (
      <DecisionDraft
        conversation={conversation}
        onCancel={() => setMode('read')}
        onSaved={(note) => {
          setSavedNote(note)
          setMode('read')
        }}
      />
    )
  }
  const details = conversation.checkpoint?.details ?? {}
  const fields = [
    { label: checkpointFields[0].label, value: details.objective },
    { label: t('O que foi feito', 'What was done'), value: conversation.summary },
    { label: checkpointFields[1].label, value: details.attempts },
    { label: checkpointFields[2].label, value: details.checks },
    { label: t('Próximo passo', 'Next step'), value: conversation.next_step }
  ].filter(({ value }) => value)
  return (
    <>
      <div className={styles.actions}>
        <button type="button" className={styles.button} onClick={() => setMode('checkpoint')}>
          {conversation.summary
            ? t('Atualizar checkpoint', 'Update checkpoint')
            : t('Criar checkpoint', 'Create checkpoint')}
        </button>
        <button type="button" className={styles.button} onClick={() => setMode('decision')}>
          {t('Salvar como decisão', 'Save as decision')}
        </button>
      </div>
      {savedNote ? (
        <div className={styles.actions}>
          <span className={styles.muted} role="status">
            {t('Decisão salva no Second Brain.', 'Decision saved in Second Brain.')}
          </span>
          <button className={styles.button} type="button" onClick={() => onOpenNote(savedNote.id)}>
            {t('Abrir decisão', 'Open decision')}
          </button>
        </div>
      ) : null}
      {conversation.checkpoint?.created ? (
        <p className={styles.detailMeta}>
          {t('Checkpoint salvo', 'Checkpoint saved')} ·{' '}
          {new Date(conversation.checkpoint.created).toLocaleString()}
        </p>
      ) : null}
      {conversation.checkpointStale ? (
        <p className={styles.muted}>
          {conversation.checkpoint?.created
            ? t(
                'Há mensagens mais recentes que este checkpoint.',
                'There are messages newer than this checkpoint.'
              )
            : t(
                'Checkpoint sem data. Confira as mensagens recentes antes de retomar.',
                'Undated checkpoint. Check recent messages before continuing.'
              )}
        </p>
      ) : null}
      {fields.length ? (
        fields.map(({ label, value }) => (
          <section className={styles.nextStep} key={label}>
            <h3>{label}</h3>
            <div className={styles.text}>{value}</div>
          </section>
        ))
      ) : (
        <p className={styles.muted}>{t('Nenhum checkpoint salvo.', 'No checkpoint saved.')}</p>
      )}
      {conversation.checkpointHistory?.length ? (
        <details className={styles.nextStep}>
          <summary>{t('Checkpoints anteriores', 'Previous checkpoints')}</summary>
          <ol className={styles.transcript}>
            {conversation.checkpointHistory.map((checkpoint) => (
              <li key={checkpoint.id}>
                <div className={styles.detailMeta}>
                  {checkpoint.created
                    ? new Date(checkpoint.created).toLocaleString()
                    : t('Sem data', 'Undated')}
                </div>
                <div className={styles.text}>{checkpoint.summary}</div>
                {checkpointFields.map(({ key, label }) =>
                  checkpoint.details[key] ? (
                    <div key={key} className={styles.text}>
                      {label} · {checkpoint.details[key]}
                    </div>
                  ) : null
                )}
                {checkpoint.next_step ? (
                  <div className={styles.text}>
                    {t('Próximo passo', 'Next step')} · {checkpoint.next_step}
                  </div>
                ) : null}
              </li>
            ))}
          </ol>
        </details>
      ) : null}
    </>
  )
}
