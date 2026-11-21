import { Trash2 } from 'lucide-react'
import { useId, useRef, useState } from 'react'
import { localize as t, type ConversationDetail } from './knowledge-model'
import { libraryCall } from './skill-server-api'
import styles from './Knowledge.module.css'

export function DeleteMemoryConversation({
  conversation,
  onDeleted
}: {
  conversation: ConversationDetail
  onDeleted: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const cancel = useRef<HTMLButtonElement>(null)
  const titleId = useId()
  const descriptionId = useId()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const remove = async () => {
    if (busy) {
      return
    }
    setBusy(true)
    setError('')
    try {
      await libraryCall<null>({
        kind: 'memory',
        action: 'delete',
        id: conversation.id,
        confirm: true
      })
      dialog.current?.close()
      onDeleted()
    } catch (failure) {
      setError(String(failure))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <button
        className={styles.button}
        type="button"
        onClick={() => {
          setError('')
          dialog.current?.showModal()
          cancel.current?.focus()
        }}
      >
        <Trash2 size={14} aria-hidden="true" />
        {t('Excluir', 'Delete')}
      </button>
      <dialog
        ref={dialog}
        className={styles.deleteDialog}
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        onCancel={(event) => {
          if (busy) {
            event.preventDefault()
          }
        }}
      >
        <form
          onSubmit={(event) => {
            event.preventDefault()
            void remove()
          }}
        >
          <h3 id={titleId}>{t('Excluir da Memória?', 'Delete from Memory?')}</h3>
          <p id={descriptionId}>
            {t('Você vai apagar a cópia de', 'This will delete the copy of')}{' '}
            <strong>{conversation.title}</strong>{' '}
            {t(
              'guardada no Opus, incluindo mensagens e checkpoints de todas as pastas associadas.',
              'stored in Opus, including messages and checkpoints from all linked folders.'
            )}
          </p>
          {error ? (
            <p className={styles.error} role="alert">
              {error}
            </p>
          ) : null}
          <div className={styles.actions}>
            <button
              ref={cancel}
              className={styles.button}
              type="button"
              disabled={busy}
              onClick={() => dialog.current?.close()}
            >
              {t('Cancelar', 'Cancel')}
            </button>
            <button
              className={`${styles.primary} ${styles.deleteConfirm}`}
              type="submit"
              disabled={busy}
            >
              {busy ? t('Excluindo…', 'Deleting…') : t('Excluir da Memória', 'Delete from Memory')}
            </button>
          </div>
        </form>
      </dialog>
    </>
  )
}
