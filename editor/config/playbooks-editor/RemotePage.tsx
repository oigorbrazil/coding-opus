import { ExternalLink, FolderPlus, Power, Radio, RotateCw, Save, Search, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { localize as t } from './knowledge-model'
import {
  detectTailscale,
  openRemotePanel,
  readRemote,
  remoteAction,
  type RemoteStatus,
  type TailscaleInfo
} from './skill-server-api'
import styles from './Knowledge.module.css'

function TailscaleReport({ info }: { info: TailscaleInfo }): React.JSX.Element {
  if (!info.installed) {
    return (
      <p className={styles.error}>
        {t('Tailscale não encontrado neste computador.', 'Tailscale was not found on this computer.')}
      </p>
    )
  }
  if (!info.host) {
    return (
      <p className={styles.error}>
        {t(
          'O Tailscale não está conectado. Entre na sua conta pelo app do Tailscale.',
          'Tailscale is not connected. Sign in through the Tailscale app.'
        )}
      </p>
    )
  }
  return (
    <div className={styles.remoteWarning} role="status">
      <p>
        {t('Este computador:', 'This computer:')} <code>{info.host}</code>
      </p>
      {info.serve_path ? (
        <p>
          {t(
            `O Tailscale Serve já publica o painel em ${info.serve_path}.`,
            `Tailscale Serve already publishes the panel at ${info.serve_path}.`
          )}
        </p>
      ) : (
        <p>
          {t(
            'O Tailscale Serve ainda não publica o painel. Rode no terminal deste computador:',
            'Tailscale Serve does not publish the panel yet. Run in a terminal on this computer:'
          )}{' '}
          <code>{info.command}</code>
        </p>
      )}
    </div>
  )
}

/** Remote control on this computer: service, panel, projects and permission. */
export function RemotePage({ onLoadSettled }: { onLoadSettled?: () => void }): React.JSX.Element {
  const [status, setStatus] = useState<RemoteStatus | null>(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [path, setPath] = useState('')
  const [address, setAddress] = useState('')
  const [tailscale, setTailscale] = useState<TailscaleInfo | null>(null)

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

  const detect = async () => {
    setBusy(true)
    setMessage('')
    try {
      const result = await detectTailscale()
      if (result.ok) {
        setTailscale(result.tailscale)
        if (result.tailscale.suggested) {
          setAddress(result.tailscale.suggested)
        }
        setError('')
      } else {
        setError(result.error)
      }
    } catch (reason) {
      setError(String(reason))
    } finally {
      setBusy(false)
    }
  }

  const saveAddress = async (event: FormEvent) => {
    event.preventDefault()
    if (await act({ action: 'panel', address: address.trim() }, t('Endereço salvo.', 'Address saved.'))) {
      setAddress('')
      setTailscale(null)
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
              {status.running && !status.current ? (
                <div className={styles.remoteWarning} role="status">
                  <p>
                    {t(
                      'O serviço ligado é de uma versão anterior da Coding Opus. Reinicie para usar a atual.',
                      'The running service is from an earlier Coding Opus version. Restart it to use the current one.'
                    )}
                  </p>
                  <button
                    className={styles.button}
                    type="button"
                    disabled={busy}
                    onClick={() => void act({ action: 'restart' }, t('Serviço reiniciado.', 'Service restarted.'))}
                  >
                    <RotateCw size={15} /> {t('Reiniciar', 'Restart')}
                  </button>
                </div>
              ) : null}
            </section>
            <section className={styles.remoteSection} aria-labelledby="remoteAddress">
              <h2 id="remoteAddress">{t('Endereço para o celular', 'Address for the phone')}</h2>
              <p className={styles.muted}>
                {t(
                  'O QR do celular abre este endereço do Tailscale. O celular precisa do Tailscale ligado, na mesma conta.',
                  'The phone QR opens this Tailscale address. The phone needs Tailscale on, in the same account.'
                )}
              </p>
              <p>
                {status.panel_url ? (
                  <code>{status.panel_url}</code>
                ) : (
                  <span className={styles.error}>{t('Ainda não definido.', 'Not set yet.')}</span>
                )}
              </p>
              <button className={styles.button} type="button" disabled={busy} onClick={() => void detect()}>
                <Search size={15} /> {t('Detectar pelo Tailscale', 'Detect from Tailscale')}
              </button>
              {tailscale ? <TailscaleReport info={tailscale} /> : null}
              <form className={styles.remoteAdd} onSubmit={(event) => void saveAddress(event)}>
                <label htmlFor="remoteAddressInput">{t('Endereço HTTPS do painel', 'Panel HTTPS address')}</label>
                <div>
                  <input
                    id="remoteAddressInput"
                    value={address}
                    onChange={(event) => setAddress(event.target.value)}
                    placeholder="https://meu-pc.minha-rede.ts.net/coding-opus/"
                    spellCheck={false}
                  />
                  <button className={styles.primary} type="submit" disabled={busy || !address.trim()}>
                    <Save size={15} /> {t('Salvar', 'Save')}
                  </button>
                </div>
              </form>
            </section>
            <section className={styles.remoteSection} aria-labelledby="remoteDevices">
              <h2 id="remoteDevices">{t('Aparelhos conectados', 'Connected devices')}</h2>
              <p className={styles.muted}>
                {t(
                  'Para incluir um celular, abra o painel neste computador e use “Gerar QR para o celular”.',
                  'To add a phone, open the panel on this computer and use “Generate QR for the phone”.'
                )}
              </p>
              <ul className={styles.remoteProjects}>
                {status.devices.map((device) => (
                  <li key={device.id}>
                    <div>
                      <strong>{device.name}</strong>
                      <small className={styles.muted}>
                        {device.kind === 'pc' ? t('Computador', 'Computer') : t('Celular', 'Phone')} ·{' '}
                        {t('desde', 'since')} {new Date(device.created).toLocaleDateString()}
                      </small>
                    </div>
                    <button
                      className={styles.button}
                      type="button"
                      disabled={busy}
                      onClick={() => {
                        const extra =
                          device.kind === 'pc'
                            ? t(' Os celulares pareados por ele também saem.', ' Phones it paired are removed too.')
                            : ''
                        if (
                          window.confirm(
                            t(
                              `Revogar ${device.name}? Ele precisará de um novo QR para voltar.`,
                              `Revoke ${device.name}? It will need a new QR to come back.`
                            ) + extra
                          )
                        ) {
                          void act({ action: 'revoke', id: device.id }, t('Aparelho revogado.', 'Device revoked.'))
                        }
                      }}
                    >
                      <Trash2 size={15} /> {t('Revogar', 'Revoke')}
                    </button>
                  </li>
                ))}
                {!status.devices.length ? (
                  <li className={styles.muted}>{t('Nenhum aparelho pareado.', 'No paired device.')}</li>
                ) : null}
              </ul>
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
