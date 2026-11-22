import { ExternalLink, FolderPlus, Power, Radio, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { localize as t } from './knowledge-model'
import { openRemotePanel, readRemote, remoteAction, type RemoteStatus } from './skill-server-api'
import styles from './Knowledge.module.css'

/** Remote control on this computer: service, panel, projects and permission. */
export function RemotePage({ onLoadSettled }: { onLoadSettled?: () => void }): React.JSX.Element {
  const [status, setStatus] = useState<RemoteStatus | null>(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [path, setPath] = useState('')

  const load = useCallback(async () => {
    const result = await readRemote().catch((reason: unknown) => ({ ok: false as const, error: String(reason) }))
    if (result.ok) {
      setStatus(result.remote)
      setError('')
    } else {
      setError(result.error)
    }
    onLoadSettled?.()
  }, [onLoadSettled])

  useEffect(() => {
    void load()
  }, [load])

  const act = async (body: Parameters<typeof remoteAction>[0], done: string) => {
    setBusy(true)
    setMessage('')
    try {
      const result = await remoteAction(body)
      if (result.ok) {
        setStatus(result.remote)
        setError('')
        setMessage(done)
        return true
      }
      setError(result.error)
      return false
    } catch (reason) {
      setError(String(reason))
      return false
    } finally {
      setBusy(false)
    }
  }

  const open = async () => {
    setBusy(true)
    setMessage('')
    try {
      const result = await openRemotePanel().catch(() => 'unavailable')
      if (result === 'opened') {
        setMessage(t('Painel aberto no navegador, já conectado.', 'Panel opened in your browser, already connected.'))
      } else if (result === 'setup-required') {
        setError(t('Libere um projeto abaixo para configurar o controle remoto.', 'Allow a project below to set up remote control.'))
      } else {
        setError(t('Não foi possível abrir o painel.', 'Could not open the panel.'))
      }
      await load()
    } finally {
      setBusy(false)
    }
  }

  const add = async (event: FormEvent) => {
    event.preventDefault()
    if (await act({ action: 'add', path: path.trim() }, t('Projeto liberado.', 'Project allowed.'))) {
      setPath('')
    }
  }

  const missing = status?.projects.filter((project) => !project.exists) ?? []

  return (
    <main className={styles.library}>
      <header className={styles.header}>
        <div className={styles.identity}>
          <Radio size={19} aria-hidden="true" />
          <div>
            <h1>{t('Controle remoto', 'Remote control')}</h1>
            <p className={styles.muted}>
              {t(
                'Acompanhe e inicie tarefas dos agentes pelo celular, pelo Tailscale.',
                'Follow and start agent tasks from your phone, through Tailscale.'
              )}
            </p>
          </div>
        </div>
        <button className={styles.primary} type="button" disabled={busy || !status?.projects.length} onClick={() => void open()}>
          <ExternalLink size={15} /> {t('Abrir painel neste computador', 'Open panel on this computer')}
        </button>
      </header>
      <div className={styles.remindersPane} aria-busy={busy}>
        {error ? (
          <p className={styles.error} role="alert">
            {error}
          </p>
        ) : null}
        {message ? (
          <p className={styles.muted} role="status">
            {message}
          </p>
        ) : null}
        {!status && !error ? <p className={styles.muted}>{t('Carregando…', 'Loading…')}</p> : null}
        {status ? (
          <>
            <section className={styles.remoteSection} aria-labelledby="remoteService">
              <h2 id="remoteService">{t('Serviço', 'Service')}</h2>
              <p>
                {!status.configured
                  ? t('Ainda não configurado. Libere um projeto abaixo para começar.', 'Not set up yet. Allow a project below to start.')
                  : status.running
                    ? t(`Ligado na porta ${status.port}.`, `Running on port ${status.port}.`)
                    : t('Desligado.', 'Stopped.')}
              </p>
              {status.configured ? (
                <button
                  className={styles.button}
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    void act(
                      { action: status.running ? 'stop' : 'start' },
                      status.running ? t('Serviço desligado.', 'Service stopped.') : t('Serviço ligado.', 'Service started.')
                    )
                  }
                >
                  <Power size={15} /> {status.running ? t('Desligar', 'Stop') : t('Ligar', 'Start')}
                </button>
              ) : null}
              <p className={styles.muted}>
                {status.panel
                  ? t(
                      'Para o celular: abra o painel neste computador e use “Gerar QR para o celular”. Cada aparelho ganha sua chave, que dá para revogar no próprio painel.',
                      'For your phone: open the panel on this computer and use “Generate QR for the phone”. Each device gets its own key, revocable in the panel.'
                    )
                  : t(
                      'O celular precisa do endereço do Tailscale Serve: configure com remote_control.py setup --origin https://<pc>.ts.net.',
                      'Your phone needs the Tailscale Serve address: set it with remote_control.py setup --origin https://<pc>.ts.net.'
                    )}
              </p>
            </section>
            <section className={styles.remoteSection} aria-labelledby="remoteProjects">
              <h2 id="remoteProjects">{t('Projetos liberados', 'Allowed projects')}</h2>
              <p className={styles.muted}>
                {t(
                  'Só estas pastas aparecem no celular. Mudanças aqui reiniciam o serviço.',
                  'Only these folders show on the phone. Changes here restart the service.'
                )}
              </p>
              {missing.length ? (
                <p className={styles.error} role="alert">
                  {t(
                    `Pasta não encontrada: ${missing.map((project) => project.key).join(', ')}. Remova ou recrie a pasta.`,
                    `Folder not found: ${missing.map((project) => project.key).join(', ')}. Remove it or recreate the folder.`
                  )}
                </p>
              ) : null}
              <ul className={styles.remoteProjects}>
                {status.projects.map((project) => (
                  <li key={project.key}>
                    <div>
                      <strong>{project.key}</strong>
                      <small className={project.exists ? styles.muted : styles.error}>{project.path}</small>
                    </div>
                    <button
                      className={styles.button}
                      type="button"
                      disabled={busy}
                      aria-label={t(`Remover ${project.key}`, `Remove ${project.key}`)}
                      onClick={() => void act({ action: 'remove', key: project.key }, t('Projeto removido.', 'Project removed.'))}
                    >
                      <Trash2 size={15} /> {t('Remover', 'Remove')}
                    </button>
                  </li>
                ))}
                {!status.projects.length ? <li className={styles.muted}>{t('Nenhum projeto liberado.', 'No project allowed.')}</li> : null}
              </ul>
              <form className={styles.remoteAdd} onSubmit={(event) => void add(event)}>
                <label htmlFor="remotePath">{t('Liberar pasta (caminho completo)', 'Allow folder (full path)')}</label>
                <div>
                  <input
                    id="remotePath"
                    value={path}
                    onChange={(event) => setPath(event.target.value)}
                    placeholder="C:\Users\...\meu-projeto"
                    spellCheck={false}
                  />
                  <button className={styles.primary} type="submit" disabled={busy || !path.trim()}>
                    <FolderPlus size={15} /> {t('Liberar', 'Allow')}
                  </button>
                </div>
              </form>
              <label className={styles.remoteCheck}>
                <input
                  type="checkbox"
                  checked={status.allow_write}
                  disabled={busy || !status.configured}
                  onChange={(event) =>
                    void act(
                      { action: 'write', allowWrite: event.target.checked },
                      event.target.checked
                        ? t('Tarefas remotas podem alterar arquivos.', 'Remote tasks may change files.')
                        : t('Tarefas remotas só leem.', 'Remote tasks only read.')
                    )
                  }
                />
                {t(
                  'Permitir que tarefas iniciadas pelo celular alterem arquivos',
                  'Allow tasks started from the phone to change files'
                )}
              </label>
            </section>
          </>
        ) : null}
      </div>
    </main>
  )
}
