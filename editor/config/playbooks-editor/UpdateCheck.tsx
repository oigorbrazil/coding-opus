import { CircleCheck, CloudDownload, LoaderCircle, X } from 'lucide-react'
import { useState } from 'react'
import { localize as t } from './knowledge-model'
import { checkUpdates, type UpdateReport } from './skill-server-api'
import styles from './Knowledge.module.css'

type State = { kind: 'idle' } | { kind: 'checking' } | { kind: 'done'; report: UpdateReport } | { kind: 'error'; error: string }

function day(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleString(undefined, { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

/** "Check for updates": compares the installed skill with GitHub, read-only. */
export function useUpdateCheck() {
  const [state, setState] = useState<State>({ kind: 'idle' })

  const run = async () => {
    setState({ kind: 'checking' })
    try {
      const result = await checkUpdates()
      setState(result.ok ? { kind: 'done', report: result } : { kind: 'error', error: result.error })
    } catch (reason) {
      setState({ kind: 'error', error: String(reason) })
    }
  }

  const button = (
    <button
      type="button"
      className={styles.updateButton}
      disabled={state.kind === 'checking'}
      title={t('Compara a Coding Opus instalada com a do GitHub', 'Compares the installed Coding Opus with GitHub')}
      onClick={() => void run()}
    >
      {state.kind === 'checking' ? (
        <LoaderCircle size={15} className={styles.spin} aria-hidden="true" />
      ) : (
        <CloudDownload size={15} aria-hidden="true" />
      )}
      {state.kind === 'checking'
        ? t('Verificando…', 'Checking…')
        : t('Verificar atualizações', 'Check for updates')}
    </button>
  )

  let text: React.ReactNode = null
  if (state.kind === 'error') {
    text = <span className={styles.error}>{state.error}</span>
  } else if (state.kind === 'done') {
    const { report } = state
    const latest = `${report.latest.commit} · ${day(report.latest.date)} · “${report.latest.title}”`
    const count = report.changed.length + report.missing.length
    text = report.upToDate ? (
      <span>
        <CircleCheck size={14} aria-hidden="true" className={styles.updateOk} />{' '}
        {t(
          `A Coding Opus está atualizada${report.version ? ` (versão ${report.version})` : ''}: igual à última do GitHub, ${latest}.`,
          `Coding Opus is up to date${report.version ? ` (version ${report.version})` : ''}: same as the latest on GitHub, ${latest}.`
        )}
      </span>
    ) : (
      <span>
        <strong>{t('Há uma atualização.', 'An update is available.')}</strong>{' '}
        {t(
          `${count} ${count === 1 ? 'arquivo da sua cópia difere' : 'arquivos da sua cópia diferem'} da versão do GitHub (${latest}). Para atualizar, rode de novo `,
          `${count} ${count === 1 ? 'file in your copy differs' : 'files in your copy differ'} from the GitHub version (${latest}). To update, run `
        )}
        <code>npx skills add oigorbrazil/coding-opus --skill coding -g</code>
        {t(
          '; com o plugin do Claude Code, atualize o marketplace em /plugin.',
          ' again; with the Claude Code plugin, update the marketplace in /plugin.'
        )}
      </span>
    )
  }

  const notice =
    text !== null ? (
      <div className={`editor-notice ${styles.updateNotice}`} role="status">
        {text}
        <button
          type="button"
          className={styles.iconButton}
          aria-label={t('Fechar', 'Close')}
          title={t('Fechar', 'Close')}
          onClick={() => setState({ kind: 'idle' })}
        >
          <X size={14} />
        </button>
      </div>
    ) : null

  return { button, notice }
}
