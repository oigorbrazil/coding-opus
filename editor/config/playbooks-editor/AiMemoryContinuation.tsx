import { Check, Copy } from 'lucide-react'
import { useRef, useState } from 'react'
import { localize as t } from './knowledge-model'
import styles from './Knowledge.module.css'

export function AiMemoryContinuation({ project }: { project: string }) {
  const preview = useRef<HTMLTextAreaElement>(null)
  const [clipboard, setClipboard] = useState<{ command: string; copied: boolean } | null>(null)

  const windows = /^[a-z]:[\\/]/i.test(project)
  if ((!windows && !project.startsWith('/')) || /[\r\n]/.test(project) || project.includes('\0')) {
    return null
  }

  const command = windows
    ? `Push-Location -LiteralPath '${project.replace(/['‘’‚‛]/g, '$&$&')}' -ErrorAction Stop; try { ai-memory resume } finally { Pop-Location }`
    : `cd -- '${project.replaceAll("'", "'\\''")}' && ai-memory resume`
  const result = clipboard?.command === command ? clipboard : null

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command)
      setClipboard({ command, copied: true })
    } catch {
      preview.current?.focus()
      preview.current?.select()
      setClipboard({ command, copied: false })
    }
  }

  return (
    <details className={styles.aiMemoryContinuation}>
      <summary>{t('Usar ai-memory no terminal', 'Use ai-memory in the terminal')}</summary>
      <div>
        <p className={styles.muted}>
          {t(
            'Se este projeto já usa ai-memory, abra a lista de trabalhos salvos e escolha qual retomar no Claude Code ou no Codex.',
            'If this project already uses ai-memory, open its list of saved workstreams and choose which one to resume in Claude Code or Codex.'
          )}
        </p>
        <label>
          {windows
            ? t('Comando para PowerShell', 'PowerShell command')
            : t('Comando para Bash', 'Bash command')}
          <textarea ref={preview} value={command} rows={3} readOnly spellCheck={false} />
        </label>
        <div className={styles.actions}>
          <button type="button" className={styles.button} onClick={() => void copy()}>
            {result?.copied ? (
              <Check size={14} aria-hidden="true" />
            ) : (
              <Copy size={14} aria-hidden="true" />
            )}
            {result?.copied ? t('Copiado', 'Copied') : t('Copiar comando', 'Copy command')}
          </button>
          <span className={styles.muted} role="status">
            {result?.copied === false
              ? t(
                  'Texto selecionado. Use o comando de copiar.',
                  'Text selected. Use the copy command.'
                )
              : t('Cole no terminal.', 'Paste into your terminal.')}
          </span>
        </div>
      </div>
    </details>
  )
}
