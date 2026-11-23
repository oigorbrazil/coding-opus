import type {
  CodingOpusAccountProvider,
  CodingOpusAccountAction,
  CodingOpusAccountManagerResult,
  CodingOpusAccountsResult,
  CodingOpusCommandResult,
  CodingOpusGeneratedPlaybook,
  CodingOpusGenerationRequest,
  CodingOpusModelCatalogResult,
  CodingOpusPlaybooks,
  CodingOpusPlaybooksSaveResult,
  CodingOpusUsageSnapshot
} from '../../src/shared/coding-opus'
import type { LibraryKind } from './knowledge-model'
import type { DetectedCli } from '../../src/renderer/src/lib/coding-opus-playbooks/cliDetection'

// The page is served by `orchestrate.py editor` on 127.0.0.1 with a one-time token in the hash.
const token = new URLSearchParams(window.location.hash.slice(1)).get('token') ?? ''

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', 'X-Coding-Opus-Token': token }
  })
  // oxlint-disable-next-line typescript/consistent-type-assertions -- SAFETY: the skill's local editor server answers with this JSON shape.
  const body = (await response.json()) as T & { error?: string }
  if (!response.ok) {
    throw new Error(body.error ?? `HTTP ${response.status}`)
  }
  return body
}

export async function libraryCall<T>(
  request: { kind: LibraryKind | 'review' | 'reminders'; action: string; [key: string]: unknown },
  signal?: AbortSignal
): Promise<T> {
  const result = await call<CodingOpusCommandResult<T>>('/api/library', {
    method: 'POST',
    body: JSON.stringify(request),
    signal
  })
  if (!result.ok) {
    throw new Error(result.error)
  }
  return result.value
}

export const readEditorPlaybooks = (signal = AbortSignal.timeout(15000)) =>
  call<CodingOpusPlaybooks>('/api/playbooks', { signal })

export async function openRemotePanel() {
  const result = await call<{ status: 'opened' | 'setup-required' | 'unavailable' }>(
    '/api/remote/open',
    { method: 'POST', body: '{}' }
  )
  return result.status
}

export type RemoteDevice = {
  id: string
  name: string
  kind: 'pc' | 'phone'
  created: string
  paired_by: string | null
}

export type TailscaleInfo = {
  installed: boolean
  running?: boolean
  host?: string | null
  serve_path?: string | null
  suggested?: string | null
  command?: string | null
}

export type RemoteStatus = {
  configured: boolean
  running: boolean
  current: boolean
  port?: number
  panel_url: string
  devices: RemoteDevice[]
  allow_write: boolean
  panel: boolean
  projects: { key: string; path: string; exists: boolean }[]
}

type RemoteResult = { ok: true; remote: RemoteStatus } | { ok: false; error: string }

export const readRemote = () => call<RemoteResult>('/api/remote')

export const remoteAction = (body: {
  action: 'start' | 'stop' | 'restart' | 'add' | 'remove' | 'write' | 'revoke' | 'panel'
  path?: string
  key?: string
  id?: string
  address?: string
  allowWrite?: boolean
}) => call<RemoteResult>('/api/remote', { method: 'POST', body: JSON.stringify(body) })

export const detectTailscale = () =>
  call<{ ok: true; tailscale: TailscaleInfo } | { ok: false; error: string }>('/api/remote', {
    method: 'POST',
    body: JSON.stringify({ action: 'detect' })
  })

/** The `window.api.codingOpus` surface the editor reads, served by the skill's local server. */
export function createCodingOpusApi() {
  return {
    readPlaybooks: readEditorPlaybooks,
    savePlaybooks: (text: string) =>
      call<CodingOpusPlaybooksSaveResult>('/api/playbooks', {
        method: 'POST',
        body: JSON.stringify({ text })
      }).catch((error: unknown): CodingOpusPlaybooksSaveResult => ({
        ok: false,
        error: error instanceof Error ? error.message : String(error)
      })),
    playbooksStamp: () => call<{ stamp: number }>('/api/stamp').then((body) => body.stamp),
    modelCatalog: () =>
      call<CodingOpusModelCatalogResult>('/api/models').catch(
        (error: unknown): CodingOpusModelCatalogResult => ({ ok: false, error: String(error) })
      ),
    detectClis: () =>
      call<{ ok: true; clis: DetectedCli[] } | { ok: false; error: string }>('/api/clis').catch(
        (error: unknown) => ({ ok: false as const, error: String(error) })
      ),
    readAccounts: () =>
      call<CodingOpusAccountsResult>('/api/accounts').catch(
        (error: unknown): CodingOpusAccountsResult => ({ ok: false, error: String(error) })
      ),
    manageAccounts: (request: CodingOpusAccountAction) =>
      call<CodingOpusAccountManagerResult>('/api/accounts/manage', {
        method: 'POST',
        body: JSON.stringify(request)
      }),
    readUsage: () => call<CodingOpusCommandResult<CodingOpusUsageSnapshot>>('/api/usage'),
    generatePlaybook: (request: CodingOpusGenerationRequest) =>
      call<CodingOpusCommandResult<CodingOpusGeneratedPlaybook>>('/api/playbooks/generate', {
        method: 'POST',
        body: JSON.stringify(request)
      }),
    orderAccounts: (provider: CodingOpusAccountProvider, names: string[]) =>
      call<CodingOpusAccountsResult>('/api/accounts/order', {
        method: 'POST',
        body: JSON.stringify({ provider, names })
      }).catch((error: unknown): CodingOpusAccountsResult => ({ ok: false, error: String(error) }))
  }
}

export type CodingOpusApi = ReturnType<typeof createCodingOpusApi>

/** Gives the editor its `window.api.codingOpus`, backed by the skill's local server. */
export function installSkillServerApi(): void {
  window.api = { codingOpus: createCodingOpusApi() }
  // Tell the server the page is still open; it shuts down a while after the last ping.
  window.setInterval(() => void call('/api/ping').catch(() => undefined), 20_000)
}

export type AutomationPreset = 'hourly' | 'daily' | 'weekdays' | 'weekly' | 'cron'

export type AutomationRun = {
  id: string
  automation_id: string
  trigger: 'schedule' | 'manual'
  scheduled_for: string | null
  created: string
  status: string
  task_id: string | null
  detail: string | null
  result?: string | null
}

export type Automation = {
  id: string
  name: string
  prompt: string
  agent: 'claude' | 'codex'
  project: string
  mode: 'read-only' | 'write'
  model: string | null
  playbook: string | null
  isolate: boolean
  preset: AutomationPreset
  cron: string
  hour?: number
  minute?: number
  weekday?: number
  enabled: boolean
  precheck: string | null
  precheck_timeout: number
  grace_minutes: number
  reuse_session: boolean
  next_run: string | null
  last_run: string | null
  schedule: string
  last: AutomationRun | null
}

export type AutomationDraft = {
  name: string
  prompt: string
  agent: 'claude' | 'codex'
  project: string
  mode: 'read-only' | 'write'
  model: string
  isolate: boolean
  preset: AutomationPreset
  hour: number
  minute: number
  weekday: number
  cron: string
  enabled: boolean
  precheck: string
  precheck_timeout: number
  grace_minutes: number
  reuse_session: boolean
}

export type AutomationsState = {
  automations: Automation[]
  running: boolean
  allowWrite: boolean
  projects: string[]
}

type AutomationsResult = ({ ok: true } & AutomationsState) | { ok: false; error: string }

export const readAutomations = () => call<AutomationsResult>('/api/automations')

export const automationAction = (body: {
  action: 'create' | 'edit' | 'remove' | 'run'
  id?: string
  data?: Partial<AutomationDraft>
}) => call<AutomationsResult>('/api/automations', { method: 'POST', body: JSON.stringify(body) })

export const automationRuns = (id: string) =>
  call<{ ok: true; runs: AutomationRun[] } | { ok: false; error: string }>('/api/automations', {
    method: 'POST',
    body: JSON.stringify({ action: 'runs', id })
  })

export type UpdateReport = {
  upToDate: boolean
  version: string | null
  latest: { commit: string; date: string; title: string }
  changed: string[]
  missing: string[]
  howto: string
  /** false for a Claude Code plugin copy or a git checkout: those update with their own tools. */
  canApply: boolean
}

export const checkUpdates = () =>
  call<({ ok: true } & UpdateReport) | { ok: false; error: string }>('/api/updates', {
    signal: AbortSignal.timeout(30000)
  })

export type AppliedUpdate = {
  updated: string[]
  version: string | null
  latest: UpdateReport['latest']
}

export const applyUpdate = () =>
  call<({ ok: true } & AppliedUpdate) | { ok: false; error: string }>('/api/updates', {
    method: 'POST',
    body: JSON.stringify({ action: 'apply' }),
    signal: AbortSignal.timeout(120000)
  })
