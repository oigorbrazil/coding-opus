import { Check, Copy } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import {
  createPlaybooksState,
  modelsOf
} from '../../src/renderer/src/lib/coding-opus-playbooks/state'
import { AiMemoryContinuation } from './AiMemoryContinuation'
import { continuationPrompt } from './continuation-prompt'
import { localize as t, type ConversationDetail } from './knowledge-model'
import { readEditorPlaybooks } from './skill-server-api'
import styles from './Knowledge.module.css'

type DestinationGroup = { id: string; label: string; models: string[] }

export function ConversationContinuation({
  id,
  conversation
}: {
  id: string
  conversation: ConversationDetail
}) {
  const [groups, setGroups] = useState<DestinationGroup[]>([])
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
          setGroups(
            Object.entries(catalog.catalog)
              .map(([provider, definition]) => ({
                id: provider,
                label: definition.label,
                models: modelsOf(catalog, provider)
              }))
              .filter((group) => group.models.length)
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
      <label>
        <span id={`${id}-destination`}>{t('Modelo de destino', 'Destination model')}</span>
        <select
          aria-labelledby={`${id}-destination`}
          value={selected}
          onChange={(event) => setSelected(event.target.value)}
        >
          <option value="" disabled>
            {catalogState === 'loading'
              ? t('Carregando modelos…', 'Loading models…')
              : t('Selecione um modelo', 'Choose a model')}
          </option>
          {groups.map((group) => (
            <optgroup key={group.id} label={group.label}>
              {group.models.map((model) => (
                <option key={model} value={`${group.label} · ${model}`}>
                  {group.label} · {model}
                </option>
              ))}
            </optgroup>
          ))}
          <option value="custom">{t('Outro modelo…', 'Other model…')}</option>
        </select>
      </label>
      {catalogState === 'unavailable' && selected !== 'custom' ? (
        <p className={styles.muted}>
          {t(
            'A lista de modelos está indisponível. Use Outro modelo para digitar o nome.',
            'The model list is unavailable. Choose Other model to enter a name.'
          )}
        </p>
      ) : null}
      {selected === 'custom' ? (
        <label>
          {t('Nome do modelo', 'Model name')}
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
                    'Cole no chat com o modelo escolhido.',
                    'Paste into a chat with the chosen model.'
                  )}
            </span>
          </div>
        </>
      ) : null}
      <AiMemoryContinuation project={conversation.project} />
    </section>
  )
}
