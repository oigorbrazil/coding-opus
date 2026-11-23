import { CircleCheck, CloudDownload, Download, LoaderCircle, X } from 'lucide-react'
import { useState } from 'react'
import { localize as t } from './knowledge-model'
import { applyUpdate, checkUpdates, type AppliedUpdate, type UpdateReport } from './skill-server-api'
import styles from './Knowledge.module.css'

type State =
  | { kind: 'idle' }
  | { kind: 'checking' }
  | { kind: 'done'; report: UpdateReport }
  | { kind: 'applying'; report: UpdateReport }
  | { kind: 'applied'; result: AppliedUpdate }
  | { kind: 'error'; error: string }

function day(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleString(undefined, { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

const describe = (latest: UpdateReport['latest']) => `${latest.commit} · ${day(latest.date)} · “${latest.title}”`

/** "Check for updates": compares the installed skill with GitHub, and updates it in place on request. */
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

  const install = async (report: UpdateReport) => {
    setState({ kind: 'applying', report })
    try {
      const result = await applyUpdate()
      setState(result.ok ? { kind: 'applied', result } : { kind: 'error', error: result.error })
    } catch (reason) {
      setState({ kind: 'error', error: String(reason) })
    }
  }

  const busy = state.kind === 'checking' || state.kind === 'applying'
  const button = (
    <button
      type="button"
      className={styles.updateButton}
      disabled={busy}
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
  } else if (state.kind === 'applied') {
    const { result } = state
    const count = result.updated.length
    text = (
      <span>
        <CircleCheck size={14} aria-hidden="true" className={styles.updateOk} />{' '}
        <strong>{t('Coding Opus atualizada.', 'Coding Opus updated.')}</strong>{' '}
        {t(
          `${count} ${count === 1 ? 'arquivo substituído' : 'arquivos substituídos'}, agora igual a ${describe(result.latest)}. Feche e abra o editor de novo para usar a versão nova; os chats novos já a usam.`,
          `${count} ${count === 1 ? 'file replaced' : 'files replaced'}, now the same as ${describe(result.latest)}. Close and reopen the editor to use the new version; new chats already use it.`
        )}
      </span>
    )
  } else if (state.kind === 'done' || state.kind === 'applying') {
    const { report } = state
    const latest = describe(report.latest)
    const count = report.changed.length + report.missing.length
    text = report.upToDate ? (
      <span>
        <CircleCheck size={14} aria-hidden="true" className={styles.updateOk} />{' '}
        {t(
          `A Coding Opus está atualizada${report.version ? ` (versão ${report.version})` : ''}: igual à última do GitHub, ${latest}.`,
          `Coding Opus is up to date${report.version ? ` (version ${report.version})` : ''}: same as the latest on GitHub, ${latest}.`
        )}
      </span>
    ) : report.canApply ? (
      <span className={styles.updateAvailable}>
        <span>
          <strong>{t('Há uma atualização.', 'An update is available.')}</strong>{' '}
          {t(
            `${count} ${count === 1 ? 'arquivo difere' : 'arquivos diferem'} da última versão do GitHub (${latest}).`,
            `${count} ${count === 1 ? 'file differs' : 'files differ'} from the latest GitHub version (${latest}).`
          )}
        </span>
        <button
          type="button"
          className={styles.updateButton}
          disabled={state.kind === 'applying'}
          onClick={() => void install(report)}
        >
          {state.kind === 'applying' ? (
            <LoaderCircle size={15} className={styles.spin} aria-hidden="true" />
          ) : (
            <Download size={15} aria-hidden="true" />
          )}
          {state.kind === 'applying' ? t('Atualizando…', 'Updating…') : t('Atualizar agora', 'Update now')}
        </button>
      </span>
    ) : (
      <span>
        <strong>{t('Há uma atualização.', 'An update is available.')}</strong>{' '}
        {t(
          `${count} ${count === 1 ? 'arquivo difere' : 'arquivos diferem'} da versão do GitHub (${latest}). Esta cópia é o plugin do Claude Code ou um repositório git: atualize o marketplace em /plugin, ou rode git pull.`,
          `${count} ${count === 1 ? 'file differs' : 'files differ'} from the GitHub version (${latest}). This copy is the Claude Code plugin or a git checkout: update the marketplace in /plugin, or run git pull.`
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
          disabled={state.kind === 'applying'}
          onClick={() => setState({ kind: 'idle' })}
        >
          <X size={14} />
        </button>
      </div>
    ) : null

  return { button, notice }
}
