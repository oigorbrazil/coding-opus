import { ChevronDown, Folder, FolderPlus, Pencil, Play, Plus, Power, Trash2, X, Zap } from 'lucide-react'
import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { localize as t } from './knowledge-model'
import {
  automationAction,
  automationRuns,
  pickFolder,
  readAutomations,
  remoteAction,
  type Automation,
  type AutomationDraft,
  type AutomationPreset,
  type AutomationRun,
  type AutomationsState
} from './skill-server-api'
import styles from './Knowledge.module.css'

const FREQUENCIES: { value: AutomationPreset; label: string }[] = [
  { value: 'daily', label: t('Todo dia', 'Every day') },
  { value: 'weekdays', label: t('Dias úteis', 'Weekdays') },
  { value: 'weekly', label: t('Uma vez por semana', 'Once a week') },
  { value: 'hourly', label: t('De hora em hora', 'Every hour') },
  { value: 'cron', label: t('Personalizado', 'Custom') }
]

const WEEKDAYS = [
  t('Domingo', 'Sunday'),
  t('Segunda', 'Monday'),
  t('Terça', 'Tuesday'),
  t('Quarta', 'Wednesday'),
  t('Quinta', 'Thursday'),
  t('Sexta', 'Friday'),
  t('Sábado', 'Saturday')
]
const WEEKDAYS_SHORT = WEEKDAYS.map((day) => day.slice(0, 3))

type Tone = 'ok' | 'busy' | 'bad' | 'idle'

const STATUS: Record<string, { label: string; tone: Tone }> = {
  queued: { label: t('Na fila', 'Queued'), tone: 'busy' },
  dispatching: { label: t('Iniciando', 'Starting'), tone: 'busy' },
  dispatched: { label: t('Iniciada', 'Started'), tone: 'busy' },
  running: { label: t('Rodando agora', 'Running now'), tone: 'busy' },
  needs_input: { label: t('Esperando sua resposta', 'Waiting for you'), tone: 'busy' },
  completed: { label: t('Concluída', 'Completed'), tone: 'ok' },
  failed: { label: t('Falhou', 'Failed'), tone: 'bad' },
  stopped: { label: t('Interrompida', 'Stopped'), tone: 'idle' },
  dispatch_failed: { label: t('Não conseguiu iniciar', 'Could not start'), tone: 'bad' },
  skipped_precheck: { label: t('Pulada: a condição não foi atendida', 'Skipped: condition not met'), tone: 'idle' },
  skipped_missed: { label: t('Perdida: o serviço estava desligado', 'Missed: the service was off'), tone: 'bad' },
  skipped_unavailable: { label: t('Pulada: projeto indisponível', 'Skipped: project unavailable'), tone: 'bad' }
}

type Template = { label: string; description: string; draft: Partial<AutomationDraft> }

const TEMPLATES: Template[] = [
  {
    label: t('Documentar no Second Brain', 'Document in Second Brain'),
    description: t(
      'Toda sexta às 18h, resume a semana do projeto numa nota.',
      'Every Friday at 6 pm, sums up the project’s week in a note.'
    ),
    draft: {
      name: t('Documentar no Second Brain', 'Document in Second Brain'),
      prompt: t(
        'Veja o que mudou neste projeto nos últimos 7 dias (git log e diffs) e registre no second brain, com a skill coding, uma nota curta em 00-Inbox com as decisões e o que ficou pendente. Não altere o código.',
        'Look at what changed in this project over the last 7 days (git log and diffs) and save a short note to the second brain inbox with the coding skill: decisions and what is still open. Do not change code.'
      ),
      preset: 'weekly',
      weekday: 5,
      hour: 18,
      minute: 0
    }
  },
  {
    label: t('Revisar mudanças abertas', 'Review open changes'),
    description: t(
      'Dias úteis às 9h, aponta bugs prováveis sem mexer nos arquivos.',
      'Weekdays at 9 am, points out likely bugs without touching files.'
    ),
    draft: {
      name: t('Revisar mudanças abertas', 'Review open changes'),
      prompt: t(
        'Revise as mudanças ainda não commitadas e os commits de ontem. Aponte bugs prováveis e testes que faltam, sem alterar arquivos.',
        'Review uncommitted changes and yesterday’s commits. Point out likely bugs and missing tests without changing files.'
      ),
      preset: 'weekdays',
      hour: 9,
      minute: 0
    }
  }
]

function blank(): AutomationDraft {
  return {
    name: '',
    prompt: '',
    agent: 'claude',
    projects: [],
    mode: 'read-only',
    model: '',
    isolate: false,
    preset: 'daily',
    hour: 9,
    minute: 0,
    weekday: 1,
    cron: '0 9 * * 1-5',
    enabled: true,
    precheck: '',
    precheck_timeout: 60,
    grace_minutes: 60,
    reuse_session: false
  }
}

function fromAutomation(item: Automation): AutomationDraft {
  return {
    name: item.name,
    prompt: item.prompt,
    agent: item.agent,
    projects: item.projects?.length ? item.projects : [item.project],
    mode: item.mode,
    model: item.model ?? '',
    isolate: item.isolate,
    preset: item.preset,
    hour: item.hour ?? 9,
    minute: item.minute ?? 0,
    weekday: item.weekday ?? 1,
    cron: item.cron,
    enabled: item.enabled,
    precheck: item.precheck ?? '',
    precheck_timeout: item.precheck_timeout,
    grace_minutes: item.grace_minutes,
    reuse_session: item.reuse_session
  }
}

const clock = (hour: number, minute: number) => `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`

function scheduleSentence(draft: Pick<AutomationDraft, 'preset' | 'hour' | 'minute' | 'weekday' | 'cron'>): string {
  const at = clock(draft.hour, draft.minute)
  switch (draft.preset) {
    case 'daily':
      return t(`Todo dia às ${at}`, `Every day at ${at}`)
    case 'weekdays':
      return t(`De segunda a sexta às ${at}`, `Monday to Friday at ${at}`)
    case 'weekly':
      return t(`Toda ${WEEKDAYS[draft.weekday]?.toLowerCase()} às ${at}`, `Every ${WEEKDAYS[draft.weekday]} at ${at}`)
    case 'hourly':
      return t(`De hora em hora, aos ${String(draft.minute).padStart(2, '0')} minutos`, `Every hour at :${String(draft.minute).padStart(2, '0')}`)
    default:
      return t(`Agenda personalizada (${draft.cron})`, `Custom schedule (${draft.cron})`)
  }
}

/** "hoje às 09:00", "amanhã às 18:00", "sex às 18:00", or a date further out. */
function upcoming(value: string | null): string {
  if (!value) {
    return ''
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  const at = clock(date.getHours(), date.getMinutes())
  const start = new Date()
  start.setHours(0, 0, 0, 0)
  const days = Math.round((new Date(date).setHours(0, 0, 0, 0) - start.getTime()) / 86400000)
  if (days === 0) {
    return t(`hoje às ${at}`, `today at ${at}`)
  }
  if (days === 1) {
    return t(`amanhã às ${at}`, `tomorrow at ${at}`)
  }
  if (days > 1 && days < 7) {
    return t(`${WEEKDAYS[date.getDay()]?.toLowerCase()} às ${at}`, `${WEEKDAYS[date.getDay()]} at ${at}`)
  }
  return date.toLocaleString(undefined, { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

/** "há 5 min", "há 3 h", or the date. */
function ago(value: string | null): string {
  if (!value) {
    return ''
  }
  const date = new Date(value)
  const minutes = Math.round((Date.now() - date.getTime()) / 60000)
  if (Number.isNaN(minutes)) {
    return value
  }
  if (minutes < 1) {
    return t('agora há pouco', 'just now')
  }
  if (minutes < 60) {
    return t(`há ${minutes} min`, `${minutes} min ago`)
  }
  if (minutes < 24 * 60) {
    return t(`há ${Math.round(minutes / 60)} h`, `${Math.round(minutes / 60)} h ago`)
  }
  return date.toLocaleString(undefined, { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function Status({ run }: { run: AutomationRun }) {
  const status = STATUS[run.status] ?? { label: run.status, tone: 'idle' as Tone }
  return (
    <span className={styles.automationStatus} data-tone={status.tone}>
      {status.label}
    </span>
  )
}

function RunHistory({ id }: { id: string }) {
  const [runs, setRuns] = useState<AutomationRun[] | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    void automationRuns(id)
      .then((result) => (result.ok ? setRuns(result.runs) : setError(result.error)))
      .catch((reason: unknown) => setError(String(reason)))
  }, [id])
  if (error) {
    return <p className={styles.error}>{error}</p>
  }
  if (!runs) {
    return <p className={styles.muted}>{t('Carregando…', 'Loading…')}</p>
  }
  if (!runs.length) {
    return (
      <p className={`${styles.muted} ${styles.automationRunsEmpty}`}>
        {t('Ainda não rodou. Use “Rodar agora” para testar.', 'Has not run yet. Use “Run now” to try it.')}
      </p>
    )
  }
  return (
    <ul className={styles.automationRuns}>
      {runs.map((run) => (
        <li key={run.id}>
          <div>
            <Status run={run} />
            <small className={styles.muted}>
              {run.project ? (
                <>
                  <strong title={run.project}>{folderName(run.project)}</strong> ·{' '}
                </>
              ) : null}
              {ago(run.created)} · {run.trigger === 'manual' ? t('você pediu', 'you asked') : t('no horário', 'on schedule')}
            </small>
          </div>
          {run.detail ? <small>{run.detail}</small> : null}
          {run.result ? <pre>{run.result}</pre> : null}
        </li>
      ))}
    </ul>
  )
}

function Choice<T extends string | number>({
  name,
  value,
  options,
  onChange
}: {
  name: string
  value: T
  options: { value: T; label: string; disabled?: boolean }[]
  onChange: (value: T) => void
}) {
  return (
    <div className={styles.automationChoice} role="radiogroup">
      {options.map((option) => (
        <label key={String(option.value)} data-checked={option.value === value} data-disabled={option.disabled}>
          <input
            type="radio"
            name={name}
            checked={option.value === value}
            disabled={option.disabled}
            onChange={() => onChange(option.value)}
          />
          {option.label}
        </label>
      ))}
    </div>
  )
}

/** "app", "app e site", "app, site e api". */
function listed(names: string[]): string {
  if (names.length <= 1) {
    return names[0] ?? '…'
  }
  return `${names.slice(0, -1).join(', ')} ${t('e', 'and')} ${names[names.length - 1]}`
}

/** The folder's own name: "site" for C:\…\projetos\site. Older automations saved a project name instead. */
function folderName(entry: string): string {
  const parts = entry.split(/[\\/]+/).filter(Boolean)
  return parts[parts.length - 1] ?? entry
}

/** The automation's folders: chosen in the system's folder dialog, independent of remote control. */
function FolderField({
  folders,
  paths,
  onChange
}: {
  folders: string[]
  paths?: Record<string, string>
  onChange: (folders: string[]) => void
}) {
  const [working, setWorking] = useState(false)
  const [problem, setProblem] = useState('')
  const [typed, setTyped] = useState<string | null>(null)

  const add = (folder: string) => {
    setProblem('')
    if (!folders.includes(folder)) {
      onChange([...folders, folder])
    }
  }

  const choose = async () => {
    setWorking(true)
    setProblem('')
    try {
      const result = await pickFolder(folders[folders.length - 1])
      if (!result.ok) {
        setProblem(result.error)
        setTyped('') // the dialog could not open here: let the path be pasted instead
      } else if (result.path) {
        add(result.path)
      }
    } catch (reason) {
      setProblem(String(reason))
      setTyped('')
    } finally {
      setWorking(false)
    }
  }

  return (
    <div className={styles.automationProjects}>
      <span>
        {t('Pastas', 'Folders')}{' '}
        <small className={styles.muted}>
          {t('uma ou mais; cada uma recebe a sua tarefa', 'one or more; each gets its own task')}
        </small>
      </span>
      {folders.length ? (
        <ul className={styles.automationFolders}>
          {folders.map((folder) => (
            <li key={folder} title={paths?.[folder] ?? folder}>
              <Folder size={14} aria-hidden="true" />
              <span>{folderName(folder)}</span>
              <button
                type="button"
                className={styles.iconButton}
                aria-label={t(`Remover ${folderName(folder)}`, `Remove ${folderName(folder)}`)}
                title={t('Remover', 'Remove')}
                onClick={() => onChange(folders.filter((entry) => entry !== folder))}
              >
                <X size={13} />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <button type="button" className={styles.button} disabled={working} onClick={() => void choose()}>
        <FolderPlus size={15} />{' '}
        {working ? t('Escolha a pasta na janela aberta…', 'Pick the folder in the open window…') : t('Escolher pasta', 'Choose folder')}
      </button>
      {problem ? <p className={styles.error}>{problem}</p> : null}
      {typed !== null ? (
        <div className={styles.automationAllow}>
          <label>
            {t('Caminho completo da pasta', 'Full folder path')}
            <input
              autoFocus
              value={typed}
              placeholder={t('Ex.: C:\\Users\\voce\\projetos\\site', 'E.g. /Users/you/projects/site')}
              onChange={(event) => setTyped(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && typed.trim()) {
                  event.preventDefault()
                  add(typed.trim())
                  setTyped(null)
                }
              }}
            />
          </label>
          <div className={styles.actions}>
            <button
              type="button"
              className={styles.primary}
              disabled={!typed.trim()}
              onClick={() => {
                add(typed.trim())
                setTyped(null)
              }}
            >
              {t('Adicionar', 'Add')}
            </button>
            <button type="button" className={styles.button} onClick={() => setTyped(null)}>
              {t('Cancelar', 'Cancel')}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  )
}

export function AutomationsPage({ onLoadSettled }: { onLoadSettled?: () => void }): React.JSX.Element {
  const [state, setState] = useState<AutomationsState | null>(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [draft, setDraft] = useState<AutomationDraft | null>(null)
  const [editing, setEditing] = useState<string | null>(null)
  const [history, setHistory] = useState<string | null>(null)

  const load = useCallback(async () => {
    const result = await readAutomations().catch((reason: unknown) => ({ ok: false as const, error: String(reason) }))
    if (result.ok) {
      setState(result)
      setError('')
    } else {
      setError(result.error)
    }
    onLoadSettled?.()
  }, [onLoadSettled])

  useEffect(() => {
    void load()
    const timer = window.setInterval(() => void load(), 15000)
    return () => window.clearInterval(timer)
  }, [load])

  const act = async (body: Parameters<typeof automationAction>[0], done: string) => {
    setBusy(true)
    setMessage('')
    try {
      const result = await automationAction(body)
      if (!result.ok) {
        setError(result.error)
        return false
      }
      setState(result)
      setError('')
      setMessage(done)
      return true
    } catch (reason) {
      setError(String(reason))
      return false
    } finally {
      setBusy(false)
    }
  }

  const startService = async () => {
    setBusy(true)
    try {
      const result = await remoteAction({ action: 'start' })
      if (!result.ok) {
        setError(result.error)
      } else {
        setMessage(t('Serviço ligado. As automações já rodam no horário.', 'Service started. Automations now run on schedule.'))
      }
      await load()
    } catch (reason) {
      setError(String(reason))
    } finally {
      setBusy(false)
    }
  }

  const save = async (event: FormEvent) => {
    event.preventDefault()
    if (!draft) {
      return
    }
    const data = { ...draft, isolate: draft.mode === 'write' && draft.isolate }
    const ok = editing
      ? await act({ action: 'edit', id: editing, data }, t('Automação salva.', 'Automation saved.'))
      : await act({ action: 'create', data }, t('Automação criada.', 'Automation created.'))
    if (ok) {
      setDraft(null)
      setEditing(null)
    }
  }

  const start = (template?: Template) => {
    if (!state) {
      return
    }
    setEditing(null)
    setMessage('')
    setDraft({ ...blank(), ...template?.draft })
  }

  const close = () => {
    setDraft(null)
    setEditing(null)
  }

  const set = (patch: Partial<AutomationDraft>) => setDraft((current) => (current ? { ...current, ...patch } : current))
  const agentName = (agent: string) => (agent === 'codex' ? 'Codex' : 'Claude')

  return (
    <main className={styles.library}>
      <header className={styles.header}>
        <div className={styles.identity}>
          <Zap size={19} aria-hidden="true" />
          <div>
            <h1>{t('Automações', 'Automations')}</h1>
            <p className={styles.muted}>
              {t(
                'Pedidos que um agente executa sozinho, no horário que você escolher.',
                'Requests an agent carries out on its own, at the time you choose.'
              )}
            </p>
          </div>
        </div>
        {draft ? null : (
          <button
            className={styles.primary}
            type="button"
            disabled={!state || busy}
            onClick={() => start()}
          >
            <Plus size={15} /> {t('Nova automação', 'New automation')}
          </button>
        )}
      </header>
      <div className={styles.remindersPane} aria-busy={busy}>
        {error ? (
          <p className={styles.error} role="alert">
            {error}
          </p>
        ) : null}
        {message ? (
          <p className={styles.automationMessage} role="status">
            {message}
          </p>
        ) : null}
        {!state && !error ? <p className={styles.muted}>{t('Carregando…', 'Loading…')}</p> : null}
        {state && state.configured === false ? (
          <div className={styles.remoteWarning} role="status">
            <p>
              {t(
                'As automações rodam no horário pelo serviço do controle remoto, que ainda não foi configurado. Configure na aba Controle remoto; as pastas das automações continuam sendo só delas.',
                'Automations run on schedule through the remote-control service, which is not set up yet. Set it up in the Remote control tab; automation folders stay their own.'
              )}
            </p>
          </div>
        ) : null}
        {state && state.configured && !state.running ? (
          <div className={styles.remoteWarning} role="status">
            <p>
              {t(
                'O serviço que executa as automações está desligado, então nada roda no horário.',
                'The service that runs automations is off, so nothing runs on schedule.'
              )}
            </p>
            <button className={styles.button} type="button" disabled={busy} onClick={() => void startService()}>
              <Power size={15} /> {t('Ligar o serviço', 'Start the service')}
            </button>
          </div>
        ) : null}

        {draft && state ? (
          <form className={styles.automationForm} onSubmit={(event) => void save(event)}>
            <h2>{editing ? t('Editar automação', 'Edit automation') : t('Nova automação', 'New automation')}</h2>
            {!editing ? (
              <div className={styles.automationTemplates}>
                <span className={styles.muted}>{t('Começar de um modelo:', 'Start from a template:')}</span>
                {TEMPLATES.map((template) => (
                  <button key={template.label} type="button" className={styles.button} onClick={() => set(template.draft)}>
                    {template.label}
                  </button>
                ))}
              </div>
            ) : null}

            <fieldset className={styles.automationStep}>
              <legend>{t('O que o agente deve fazer', 'What the agent should do')}</legend>
              <label>
                {t('Nome', 'Name')}
                <input
                  required
                  maxLength={120}
                  value={draft.name}
                  placeholder={t('Ex.: Revisão da manhã', 'E.g. Morning review')}
                  onChange={(event) => set({ name: event.target.value })}
                />
              </label>
              <label>
                {t('Pedido', 'Request')}
                <textarea
                  required
                  rows={4}
                  maxLength={50000}
                  value={draft.prompt}
                  placeholder={t(
                    'Escreva como se fosse pedir ao agente no chat.',
                    'Write it as you would ask the agent in chat.'
                  )}
                  onChange={(event) => set({ prompt: event.target.value })}
                />
              </label>
              <div className={styles.formRow}>
                <label>
                  {t('Agente', 'Agent')}
                  <select
                    value={draft.agent}
                    onChange={(event) => set({ agent: event.target.value === 'codex' ? 'codex' : 'claude' })}
                  >
                    <option value="claude">Claude</option>
                    <option value="codex">Codex</option>
                  </select>
                </label>
              </div>
              <FolderField
                folders={draft.projects}
                paths={state.projectPaths}
                onChange={(projects) =>
                  set({ projects, ...(projects.length > 1 ? { reuse_session: false } : {}) })
                }
              />
            </fieldset>

            <fieldset className={styles.automationStep}>
              <legend>{t('Quando rodar', 'When to run')}</legend>
              <Choice
                name="frequency"
                value={draft.preset}
                options={FREQUENCIES}
                onChange={(preset) => set({ preset })}
              />
              {draft.preset === 'weekly' ? (
                <Choice
                  name="weekday"
                  value={draft.weekday}
                  options={WEEKDAYS_SHORT.map((label, value) => ({ value, label }))}
                  onChange={(weekday) => set({ weekday })}
                />
              ) : null}
              {draft.preset === 'cron' ? (
                <label>
                  {t('Expressão cron', 'Cron expression')}
                  <input value={draft.cron} spellCheck={false} onChange={(event) => set({ cron: event.target.value })} />
                  <small className={styles.muted}>
                    {t(
                      'Cinco campos: minuto, hora, dia do mês, mês e dia da semana. Ex.: 30 8 * * 1-5 = dias úteis às 8:30.',
                      'Five fields: minute, hour, day of month, month and weekday. E.g. 30 8 * * 1-5 = weekdays at 8:30.'
                    )}
                  </small>
                </label>
              ) : draft.preset === 'hourly' ? (
                <label className={styles.automationInline}>
                  {t('No minuto', 'At minute')}
                  <input
                    type="number"
                    min={0}
                    max={59}
                    value={draft.minute}
                    onChange={(event) => set({ minute: Math.max(0, Math.min(59, Number(event.target.value) || 0)) })}
                  />
                </label>
              ) : (
                <label className={styles.automationInline}>
                  {t('Horário', 'Time')}
                  <input
                    type="time"
                    required
                    value={clock(draft.hour, draft.minute)}
                    onChange={(event) => {
                      const [hour, minute] = event.target.value.split(':').map(Number)
                      set({ hour: hour || 0, minute: minute || 0 })
                    }}
                  />
                </label>
              )}
            </fieldset>

            <fieldset className={styles.automationStep}>
              <legend>{t('O que o agente pode fazer', 'What the agent may do')}</legend>
              <Choice
                name="mode"
                value={draft.mode}
                options={[
                  { value: 'read-only', label: t('Só ler e responder', 'Only read and answer') },
                  { value: 'write', label: t('Também alterar arquivos', 'Also change files'), disabled: !state.allowWrite }
                ]}
                onChange={(mode) => set({ mode, isolate: mode === 'write' && draft.isolate })}
              />
              {!state.allowWrite ? (
                <small className={styles.muted}>
                  {t(
                    'Alterar arquivos está desligado. Para liberar, marque a opção de escrita na aba Controle remoto.',
                    'Changing files is off. To allow it, turn on writing in the Remote control tab.'
                  )}
                </small>
              ) : null}
            </fieldset>

            <details className={styles.automationAdvanced}>
              <summary>{t('Opções avançadas', 'Advanced options')}</summary>
              <label>
                {t('Rodar só quando este comando der certo (opcional)', 'Only run when this command succeeds (optional)')}
                <input
                  value={draft.precheck}
                  spellCheck={false}
                  onChange={(event) => set({ precheck: event.target.value })}
                />
                <small className={styles.muted}>
                  {t(
                    'Roda na pasta do projeto antes de cada horário. Se ele falhar, a execução é pulada e não gasta seu limite. “Rodar agora” ignora esta condição.',
                    'Runs in the project folder before each scheduled time. If it fails, the run is skipped and spends no quota. “Run now” ignores it.'
                  )}
                </small>
              </label>
              <div className={styles.formRow}>
                <label>
                  {t('Tempo máximo do comando (segundos)', 'Command time limit (seconds)')}
                  <input
                    type="number"
                    min={1}
                    max={600}
                    value={draft.precheck_timeout}
                    onChange={(event) => set({ precheck_timeout: Number(event.target.value) || 60 })}
                  />
                </label>
                <label>
                  {t('Se o serviço estava desligado, rodar ao voltar até (min)', 'If the service was off, run when back within (min)')}
                  <input
                    type="number"
                    min={0}
                    max={1440}
                    value={draft.grace_minutes}
                    onChange={(event) => set({ grace_minutes: Number(event.target.value) })}
                  />
                </label>
              </div>
              <label>
                {t('Modelo (vazio = o padrão do agente)', 'Model (empty = the agent’s default)')}
                <input value={draft.model} maxLength={120} onChange={(event) => set({ model: event.target.value })} />
              </label>
              <label className={styles.remoteCheck}>
                <input
                  type="checkbox"
                  checked={draft.mode === 'write' && draft.isolate}
                  disabled={draft.mode !== 'write'}
                  onChange={(event) => set({ isolate: event.target.checked, reuse_session: false })}
                />
                {t(
                  'Trabalhar numa cópia separada do projeto a cada vez (worktree)',
                  'Work in a separate copy of the project each time (worktree)'
                )}
              </label>
              <label className={styles.remoteCheck}>
                <input
                  type="checkbox"
                  checked={draft.reuse_session && draft.projects.length <= 1}
                  disabled={(draft.mode === 'write' && draft.isolate) || draft.projects.length > 1}
                  onChange={(event) => set({ reuse_session: event.target.checked })}
                />
                {t(
                  'Continuar a conversa da vez anterior, em vez de começar do zero',
                  'Continue the previous conversation instead of starting fresh'
                )}
                {draft.projects.length > 1 ? (
                  <small className={styles.muted}>{t(' (só com um projeto)', ' (one project only)')}</small>
                ) : null}
              </label>
            </details>

            <div className={styles.automationSummary}>
              <p>
                <strong>{scheduleSentence(draft)}</strong>
                {t(
                  `, o ${agentName(draft.agent)} vai ${draft.mode === 'write' ? 'trabalhar' : 'ler e responder, sem alterar arquivos,'} em ${listed(draft.projects.map(folderName))}${draft.projects.length > 1 ? ', uma tarefa em cada' : ''}.`,
                  `, ${agentName(draft.agent)} will ${draft.mode === 'write' ? 'work' : 'read and answer, without changing files,'} in ${listed(draft.projects.map(folderName))}${draft.projects.length > 1 ? ', one task each' : ''}.`
                )}
              </p>
              <label className={styles.remoteCheck}>
                <input type="checkbox" checked={draft.enabled} onChange={(event) => set({ enabled: event.target.checked })} />
                {t('Ativar já', 'Turn on now')}
              </label>
            </div>
            <div className={styles.actions}>
              <button type="submit" className={styles.primary} disabled={busy}>
                {editing ? t('Salvar alterações', 'Save changes') : t('Criar automação', 'Create automation')}
              </button>
              <button type="button" className={styles.button} disabled={busy} onClick={close}>
                {t('Cancelar', 'Cancel')}
              </button>
            </div>
          </form>
        ) : null}

        {state && !draft && state.automations.length ? (
          <ul className={styles.automationList}>
            {state.automations.map((item) => (
              <li key={item.id} className={styles.automationRow} data-paused={!item.enabled}>
                <div className={styles.automationHead}>
                  <label className={styles.automationSwitch} title={item.enabled ? t('Pausar', 'Pause') : t('Ativar', 'Turn on')}>
                    <input
                      type="checkbox"
                      role="switch"
                      checked={item.enabled}
                      disabled={busy}
                      aria-label={`${item.enabled ? t('Pausar', 'Pause') : t('Ativar', 'Turn on')} ${item.name}`}
                      onChange={() =>
                        void act(
                          { action: 'edit', id: item.id, data: { enabled: !item.enabled } },
                          item.enabled
                            ? t(`“${item.name}” pausada.`, `“${item.name}” paused.`)
                            : t(`“${item.name}” ativada.`, `“${item.name}” turned on.`)
                        )
                      }
                    />
                    <span aria-hidden="true" />
                  </label>
                  <div className={styles.reminderInfo}>
                    <strong>{item.name}</strong>
                    <span className={styles.muted}>
                      {scheduleSentence({
                        preset: item.preset,
                        hour: item.hour ?? 0,
                        minute: item.minute ?? 0,
                        weekday: item.weekday ?? 1,
                        cron: item.cron
                      })}{' '}
                      · {agentName(item.agent)} · {listed((item.projects?.length ? item.projects : [item.project]).map(folderName))}
                      {item.mode === 'write' ? ` · ${t('altera arquivos', 'changes files')}` : ''}
                    </span>
                    <span className={styles.automationMeta}>
                      {item.enabled
                        ? t(`Próxima: ${upcoming(item.next_run)}`, `Next: ${upcoming(item.next_run)}`) +
                          (state.running ? '' : t(', se o serviço estiver ligado', ', if the service is on'))
                        : t('Pausada', 'Paused')}
                      {item.last ? (
                        <>
                          <span aria-hidden="true"> · </span>
                          {t('Última:', 'Last:')} <Status run={item.last} />{' '}
                          <span className={styles.muted}>{ago(item.last.created)}</span>
                        </>
                      ) : null}
                    </span>
                  </div>
                  <div className={styles.actions}>
                    <button
                      className={styles.button}
                      type="button"
                      disabled={busy}
                      title={t('Roda uma vez agora, ignorando a condição', 'Runs once now, ignoring the condition')}
                      onClick={() =>
                        void act(
                          { action: 'run', id: item.id },
                          t(
                            `“${item.name}” vai começar em alguns segundos.`,
                            `“${item.name}” will start in a few seconds.`
                          )
                        ).then((ok) => ok && setHistory(item.id))
                      }
                    >
                      <Play size={15} /> {t('Rodar agora', 'Run now')}
                    </button>
                    <button
                      className={styles.button}
                      type="button"
                      aria-expanded={history === item.id}
                      onClick={() => setHistory((current) => (current === item.id ? null : item.id))}
                    >
                      {t('Histórico', 'History')}
                      <ChevronDown size={15} className={styles.automationChevron} aria-hidden="true" />
                    </button>
                    <button
                      className={styles.iconButton}
                      type="button"
                      disabled={busy}
                      aria-label={`${t('Editar', 'Edit')} ${item.name}`}
                      title={t('Editar', 'Edit')}
                      onClick={() => {
                        setEditing(item.id)
                        setMessage('')
                        setDraft(fromAutomation(item))
                      }}
                    >
                      <Pencil size={15} />
                    </button>
                    <button
                      className={styles.iconButton}
                      type="button"
                      disabled={busy}
                      aria-label={`${t('Excluir', 'Delete')} ${item.name}`}
                      title={t('Excluir', 'Delete')}
                      onClick={() => {
                        if (
                          window.confirm(
                            t(
                              `Excluir “${item.name}”? O histórico de execuções também é apagado.`,
                              `Delete “${item.name}”? Its run history is deleted too.`
                            )
                          )
                        ) {
                          void act({ action: 'remove', id: item.id }, t('Automação excluída.', 'Automation deleted.'))
                        }
                      }}
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                </div>
                {history === item.id ? <RunHistory key={item.last?.id ?? 'none'} id={item.id} /> : null}
              </li>
            ))}
          </ul>
        ) : null}

        {state && !draft && !state.automations.length ? (
          <section className={styles.automationEmpty} aria-labelledby="automationsEmpty">
            <h2 id="automationsEmpty">{t('Deixe um agente cuidar das tarefas repetidas', 'Let an agent handle repeated tasks')}</h2>
            <p className={styles.muted}>
              {t(
                'Escolha o pedido, o projeto e o horário. O serviço do controle remoto chama o agente na hora certa e guarda o resultado no histórico.',
                'Pick the request, the project and the time. The remote-control service calls the agent at the right time and keeps the result in the history.'
              )}
            </p>
            <ul>
              {TEMPLATES.map((template) => (
                <li key={template.label}>
                  <button type="button" onClick={() => start(template)}>
                    <strong>{template.label}</strong>
                    <span className={styles.muted}>{template.description}</span>
                  </button>
                </li>
              ))}
              <li>
                <button type="button" onClick={() => start()}>
                  <strong>{t('Começar do zero', 'Start from scratch')}</strong>
                  <span className={styles.muted}>{t('Escreva o seu próprio pedido.', 'Write your own request.')}</span>
                </button>
              </li>
            </ul>
          </section>
        ) : null}
      </div>
    </main>
  )
}
