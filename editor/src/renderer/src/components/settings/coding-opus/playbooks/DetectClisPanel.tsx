import { useCallback, useEffect, useState } from 'react'
import {
  addProvider,
  cliStatus,
  type CliStatus,
  type DetectedCli
} from '@/lib/coding-opus-playbooks/cliDetection'
import { toYaml } from '@/lib/coding-opus-playbooks/state'
import { usePlaybooks } from './context'
import { Hint, PanelHead, Section } from './fields'
import styles from './Playbooks.module.css'

export const DETECT_CLIS_ID = 'detect-clis'

type Load =
  | { state: 'loading' }
  | { state: 'error'; error: string }
  | { state: 'ready'; clis: DetectedCli[] }

const STATUS_KEYS: Record<CliStatus, string> = {
  configured: 'playbooks.clisConfigured',
  addable: 'playbooks.clisAddable',
  'needs-adapter': 'playbooks.clisNeedsAdapter'
}

/** Lists the agent CLIs installed on this computer and adds the chosen ones to the providers. */
export function DetectClisPanel() {
  const { s, t, replaceYaml } = usePlaybooks()
  const [load, setLoad] = useState<Load>({ state: 'loading' })
  const [added, setAdded] = useState<string[]>([])

  const detect = useCallback(async () => {
    const api = window.api?.codingOpus
    if (typeof api?.detectClis !== 'function') {
      setLoad({ state: 'error', error: t('playbooks.clisUnsupported') })
      return
    }
    setLoad({ state: 'loading' })
    const result = await api.detectClis()
    setLoad(result.ok ? { state: 'ready', clis: result.clis } : { state: 'error', error: result.error })
  }, [t])

  useEffect(() => {
    void detect()
    // Detect once per opening; the button below detects again on demand.
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const add = (cli: DetectedCli) => {
    replaceYaml(addProvider(toYaml(s), cli.id))
    setAdded((list) => [...list, cli.label])
  }

  const text = toYaml(s)
  const installed = load.state === 'ready' ? load.clis.filter((cli) => cli.installed) : []
  const missing = load.state === 'ready' ? load.clis.filter((cli) => !cli.installed) : []
  const login = (cli: DetectedCli) =>
    cli.loggedIn === true
      ? t('playbooks.clisLoggedIn')
      : cli.loggedIn === false
        ? t('playbooks.clisLoggedOut')
        : t('playbooks.clisLoginUnknown')

  return (
    <>
      <PanelHead kind={t('playbooks.groupProviders')} title={t('playbooks.clisTitle')} />
      <Hint>{t('playbooks.clisHint')}</Hint>
      {load.state === 'loading' ? <Hint>{t('playbooks.clisChecking')}</Hint> : null}
      {load.state === 'error' ? (
        <p className={`${styles.line} ${styles.danger}`}>{load.error}</p>
      ) : null}
      {added.length > 0 ? (
        <p className={`${styles.line} ${styles.ok}`}>
          {t('playbooks.clisAdded', { names: added.join(', ') })}
        </p>
      ) : null}
      {load.state === 'ready' ? (
        <>
          <Section title={t('playbooks.clisInstalled')}>
            {installed.map((cli) => {
              const status = cliStatus(text, cli)
              return (
                <div key={cli.id} className={styles.cliRow}>
                  <div className={styles.cliText}>
                    <strong>{cli.label}</strong>
                    <span className={styles.cliMeta}>
                      {[cli.version, login(cli)].filter(Boolean).join(' · ')}
                    </span>
                    <span
                      className={`${styles.cliMeta} ${status === 'needs-adapter' ? styles.warn : ''}`}
                    >
                      {t(STATUS_KEYS[status])}
                    </span>
                  </div>
                  {status === 'addable' ? (
                    <button
                      type="button"
                      className={`${styles.button} ${styles.primary}`}
                      onClick={() => add(cli)}
                    >
                      {t('playbooks.clisAdd')}
                    </button>
                  ) : null}
                </div>
              )
            })}
          </Section>
          {missing.length > 0 ? (
            <Hint>
              {t('playbooks.clisMissing', { names: missing.map((cli) => cli.label).join(', ') })}
            </Hint>
          ) : null}
          <Hint>{t('playbooks.clisAddHint')}</Hint>
          <div className={styles.actions}>
            <button type="button" className={styles.button} onClick={() => void detect()}>
              {t('playbooks.clisRecheck')}
            </button>
          </div>
        </>
      ) : null}
    </>
  )
}
