import { useEffect, useState } from 'react'

import { useT } from '@/lib/coding-opus-playbooks/i18n'
import { attachDocs } from '@/lib/coding-opus-playbooks/flowView'
import { createPlaybooksState, type PlaybooksState } from '@/lib/coding-opus-playbooks/state'
import { orchestratorPlaybooks, type SkillPlaybooks } from '@/lib/coding-opus-playbooks/host'
import styles from './Playbooks.module.css'
import { PlaybooksEditor } from './PlaybooksEditor'

type Loaded = { file: SkillPlaybooks; state: PlaybooksState; generation: number }

const errorText = (error: unknown) => (error instanceof Error ? error.message : String(error))

export function PlaybooksPage({
  onEditedChange,
  onSaved,
  onLoadSettled
}: {
  onEditedChange?: (edited: boolean) => void
  /** Called after this editor writes the file, so the host does not reload its own save. */
  onSaved?: () => void
  onLoadSettled?: () => void
} = {}) {
  const t = useT()
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [generation, setGeneration] = useState(0)

  useEffect(() => {
    let live = true
    orchestratorPlaybooks()
      .then((file) => {
        if (!live) {
          return
        }
        try {
          const state = createPlaybooksState(file.text)
          attachDocs(state)
          setLoaded({ file, state, generation })
          setError(null)
        } catch (failure) {
          setError(errorText(failure))
        }
      })
      .catch((failure: unknown) => {
        if (live) {
          setError(errorText(failure))
        }
      })
    return () => {
      live = false
    }
  }, [generation])

  useEffect(() => {
    if (loaded || error) {
      onLoadSettled?.()
    }
  }, [loaded, error, onLoadSettled])

  const reload = () => setGeneration((value) => value + 1)

  if (error) {
    return (
      <div className={styles.status} role="alert">
        <p>{t('playbooks.loadFailed', { error })}</p>
        <button type="button" className={styles.button} onClick={reload}>
          {t('playbooks.retry')}
        </button>
      </div>
    )
  }
  if (!loaded) {
    return <div className={styles.status}>{t('playbooks.loading')}</div>
  }
  return (
    <PlaybooksEditor
      key={loaded.generation}
      file={loaded.file}
      initial={loaded.state}
      onSaved={(file) => {
        setLoaded((current) => (current ? { ...current, file } : current))
        onSaved?.()
      }}
      onDiscard={reload}
      onEditedChange={onEditedChange}
    />
  )
}
