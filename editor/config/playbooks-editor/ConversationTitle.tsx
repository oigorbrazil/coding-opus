import { Pencil } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { DeleteMemoryConversation } from './DeleteMemoryConversation'
import { localize as t, type ConversationDetail } from './knowledge-model'
import { libraryCall } from './skill-server-api'
import styles from './Knowledge.module.css'

export function ConversationTitle({
  conversation,
  onSaved,
  onDeleted
}: {
  conversation: ConversationDetail
  onSaved: (detail: ConversationDetail) => void
  onDeleted: () => void
}) {
  const [draft, setDraft] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const input = useRef<HTMLInputElement>(null)
  const editing = draft !== null

  useEffect(() => {
    if (editing) {
      input.current?.focus()
      input.current?.select()
    }
  }, [editing])

  const save = async (title: string | null) => {
    if (saving) {
      return
    }
    setSaving(true)
    setError('')
    try {
      const updated = await libraryCall<ConversationDetail>({
        kind: 'memory',
        action: 'rename',
        id: conversation.id,
        title
      })
      onSaved(updated)
      setDraft(null)
    } catch (failure) {
      setError(String(failure))
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <div className={styles.conversationTitle}>
        <h2>{conversation.title}</h2>
        {editing ? null : (
          <div className={styles.actions}>
            <button
              className={styles.button}
              type="button"
              onClick={() => {
                setError('')
                setDraft(conversation.title)
              }}
            >
              <Pencil size={14} aria-hidden="true" />
              {t('Renomear', 'Rename')}
            </button>
            <DeleteMemoryConversation conversation={conversation} onDeleted={onDeleted} />
          </div>
        )}
      </div>
      {editing ? (
        <form
          className={`${styles.noteForm} ${styles.renameConversation}`}
          onSubmit={(event) => {
            event.preventDefault()
            if (draft.trim() && draft.trim() !== conversation.title) {
              void save(draft.trim())
            }
          }}
        >
          <label>
            {t('Nome na Memória', 'Name in Memory')}
            <input
              ref={input}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              maxLength={240}
              required
              disabled={saving}
            />
          </label>
          {error ? (
            <p className={styles.error} role="alert">
              {error}
            </p>
          ) : null}
          <div className={styles.actions}>
            <button
              className={styles.primary}
              type="submit"
              disabled={saving || !draft.trim() || draft.trim() === conversation.title}
            >
              {saving ? t('Salvando…', 'Saving…') : t('Salvar nome', 'Save name')}
            </button>
            {conversation.customTitle ? (
              <button
                className={styles.button}
                type="button"
                disabled={saving}
                onClick={() => void save(null)}
              >
                {t('Voltar ao nome automático', 'Use automatic name')}
              </button>
            ) : null}
            <button
              className={styles.button}
              type="button"
              disabled={saving}
              onClick={() => setDraft(null)}
            >
              {t('Cancelar', 'Cancel')}
            </button>
          </div>
        </form>
      ) : null}
    </>
  )
}
