import { Check, Copy, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import {
  activeOrder,
  createPlaybooksState
} from '../../src/renderer/src/lib/coding-opus-playbooks/state'
import { AiMemoryContinuation } from './AiMemoryContinuation'
import { continuationPrompt } from './continuation-prompt'
import { localize as t, type ConversationDetail } from './knowledge-model'
import { readEditorPlaybooks } from './skill-server-api'
import styles from './Knowledge.module.css'

type Destination = { id: string; label: string }

export function ConversationContinuation({
  id,
  conversation,
  onClose
}: {
  id: string
  conversation: ConversationDetail
  onClose: () => void
}) {
  const [providers, setProviders] = useState<Destination[]>([])
  const [catalogState, setCatalogState] = useState<'loading' | 'ready' | 'unavailable'>('loading')
  const [selected, setSelected] = useState('')
  const [custom, setCustom] = useState('')
  const [clipboard, setClipboard] = useState<{ prompt: string; copied: boolean } | null>(null)
  const preview = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    const controller = new AbortController()
    const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(15000)])
    void readEditorPlaybooks(signal)
      .then(({ text }) => {
        const catalog = createPlaybooksState(text)
        if (!controller.signal.aborted) {
          // The providers set up in the playbooks, in the active profile's order.
          setProviders(
            activeOrder(catalog).map((provider) => ({
              id: provider,
              label: catalog.catalog[provider]?.label ?? provider
            }))
          )
          setCatalogState('ready')
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setCatalogState('unavailable')
        }
      })
    return () => controller.abort()
  }, [])

  const destination = selected === 'custom' ? custom.trim() : selected
  const prompt = destination ? continuationPrompt(conversation, destination) : ''
  const result = clipboard?.prompt === prompt ? clipboard : null

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(prompt)
      setClipboard({ prompt, copied: true })
    } catch {
      preview.current?.focus()
      preview.current?.select()
      setClipboard({ prompt, copied: false })
    }
  }

  return (
    <section
      id={id}
      className={`${styles.noteForm} ${styles.continuation}`}
      aria-label={t('Continuar em', 'Continue in')}
    >
      <div className={styles.continuationHead}>
        <h2>{t('Continuar em outra IA', 'Continue in another AI')}</h2>
        <button
          type="button"
          className={styles.iconButton}
          aria-label={t('Fechar', 'Close')}
          title={t('Fechar', 'Close')}
          onClick={onClose}
        >
          <X size={15} />
        </button>
      </div>
      <label>
        <span id={`${id}-destination`}>{t('IA de destino', 'Destination AI')}</span>
        <select
          aria-labelledby={`${id}-destination`}
          value={selected}
          onChange={(event) => setSelected(event.target.value)}
        >
          <option value="" disabled>
            {catalogState === 'loading'
              ? t('Carregando provedores…', 'Loading providers…')
              : t('Escolha um provedor', 'Choose a provider')}
          </option>
          {providers.map((provider) => (
            <option key={provider.id} value={provider.label}>
              {provider.label}
            </option>
          ))}
          <option value="custom">{t('Outra IA…', 'Other AI…')}</option>
        </select>
      </label>
      {catalogState === 'unavailable' && selected !== 'custom' ? (
        <p className={styles.muted}>
          {t(
            'A lista de provedores está indisponível. Use Outra IA para digitar o nome.',
            'The provider list is unavailable. Choose Other AI to enter a name.'
          )}
        </p>
      ) : null}
      {selected === 'custom' ? (
        <label>
          {t('Nome da IA', 'AI name')}
          <input
            value={custom}
            maxLength={160}
            onChange={(event) => setCustom(event.target.value)}
          />
        </label>
      ) : null}
      {prompt ? (
        <>
          {conversation.checkpointStale ? (
            <p className={styles.muted}>
              {conversation.checkpoint?.created
                ? t(
                    'A prévia inclui mensagens posteriores ao ponto salvo.',
                    'The preview includes messages captured after the checkpoint.'
                  )
                : t(
                    'Use as mensagens recentes para conferir o checkpoint antigo.',
                    'Use the recent messages to check the older checkpoint.'
                  )}
            </p>
          ) : null}
          <label>
            {t('Prompt para continuar', 'Continuation prompt')}
            <textarea ref={preview} value={prompt} rows={8} readOnly />
          </label>
          <div className={styles.actions}>
            <button type="button" className={styles.primary} onClick={() => void copy()}>
              {result?.copied ? <Check size={14} /> : <Copy size={14} />}
              {result?.copied ? t('Copiado', 'Copied') : t('Copiar prompt', 'Copy prompt')}
            </button>
            <span className={styles.muted} role="status">
              {result?.copied === false
                ? t(
                    'Texto selecionado. Use o comando de copiar.',
                    'Text selected. Use the copy command.'
                  )
                : t(
                    'Cole num chat da IA escolhida.',
                    'Paste into a chat with the chosen AI.'
                  )}
            </span>
          </div>
        </>
      ) : null}
      <AiMemoryContinuation project={conversation.project} />
    </section>
  )
}
