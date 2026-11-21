/** Agents the Coding Opus skill installs into, following the bundled-skill roots. */
export type CodingOpusSkillTarget = 'claude' | 'codex'

export type CodingOpusSkillTargetStatus = {
  target: CodingOpusSkillTarget
  /** Folder the skill lives in for this agent. */
  path: string
  /** `metadata.version` of the installed SKILL.md, or null when absent. */
  installedVersion: string | null
  /** Installed by this app (sidecar present) rather than by hand or another tool. */
  managed: boolean
}

export type CodingOpusSkillStatus = {
  bundledVersion: string
  bundledCommit: string
  targets: CodingOpusSkillTargetStatus[]
}

export type CodingOpusPlaybooks = {
  backupText?: string | null
  text: string
  path: string
  /** False while the bundled playbooks stand in for a file the person never saved. */
  custom: boolean
}

export type CodingOpusPlaybooksSaveResult =
  | { ok: true; playbooks: CodingOpusPlaybooks }
  | { ok: false; error: string }

export type CodingOpusGenerationRequest = {
  provider: 'codex' | 'claude'
  instructions: string
  text: string
}

export type CodingOpusGeneratedPlaybook = { id: string; text: string }

export type CodingOpusAccountProvider = 'codex' | 'claude'

/** One account a Coding Opus worker can run on; the same shape comes from orchestrate.py `accounts_summary`. */
export type CodingOpusAccountRow = {
  selected?: boolean
  manageable?: boolean
  authenticated?: boolean | null
  /** `default` is the CLI's own login; other names come from `account add` or a Coding Agent 2 email. */
  name: string
  from: 'cli' | 'coding-agent' | 'coding-opus'
  email: string | null
  /** False for a Coding Agent 2 Claude account whose folder is prepared on its first use there. */
  ready: boolean
  inRotation: boolean
  activeInCodingAgent: boolean
  /** The fullest main window (5h or week), or null with no reading. */
  quota: {
    window: string
    usedPercent: number
    resetsAt: string
    low: boolean
    blocked: boolean
    stale: boolean
  } | null
}

export type CodingOpusAccounts = {
  providers: Record<CodingOpusAccountProvider, CodingOpusAccountRow[]>
}

export type CodingOpusAccountsResult =
  | { ok: true; accounts: CodingOpusAccounts }
  | { ok: false; error: string }

export type CodingOpusAccountLogin = {
  id: string
  provider: CodingOpusAccountProvider
  name: string
  state: 'pending' | 'complete' | 'cancelled' | 'error'
  url: string | null
  userCode: string | null
  needsCode: boolean | null
  error: string | null
}

export type CodingOpusAccountAction = {
  action: 'state' | 'add' | 'login' | 'cancel' | 'input' | 'select' | 'remove' | 'order'
  provider?: CodingOpusAccountProvider
  name?: string
  loginId?: string
  code?: string
  deleteData?: boolean
  names?: string[]
}

export type CodingOpusAccountManagerResult =
  | {
      ok: true
      accounts: CodingOpusAccounts
      selected: Record<CodingOpusAccountProvider, string>
      logins: CodingOpusAccountLogin[]
    }
  | { ok: false; error: string }

/** A model a provider offers today: from the CLI's own model list, or from the skill's price table. */
export type CodingOpusCatalogModel = {
  id: string
  source: 'cli' | 'prices'
  description?: string | null
  /** The model the CLI itself recommends moving to, when it names one. */
  upgrade?: string | null
}

/** The same shape comes from orchestrate.py `model_catalog`. */
export type CodingOpusModelCatalog = {
  providers: Record<string, CodingOpusCatalogModel[]>
}

export type CodingOpusModelCatalogResult =
  | { ok: true; catalog: CodingOpusModelCatalog }
  | { ok: false; error: string }

export type CodingOpusUsageReading = {
  account?: string | null
  observedAt: string
  source: string | null
  windows: Record<string, { usedPercent: number; resetsAt: string | null }>
}

export type CodingOpusUsageSnapshot = {
  providers: Record<string, CodingOpusUsageReading>
  statuses?: Record<
    string,
    {
      state: 'ok' | 'error'
      reason: string | null
      retryAt?: string | null
    }
  >
}

export type SecondBrainWhere = {
  secondBrain: string
  exists: boolean
  documents: string | null
}

export type SecondBrainNoteSummary = {
  /** Path relative to the second brain root, with forward slashes. */
  path: string
  title: string
  type: string | null
  status: string | null
  tags: string[]
  updated: string | null
  modifiedMs: number
}

export type SecondBrainFolder = {
  name: string
  notes: number
}

export type SecondBrainOverview = {
  where: SecondBrainWhere
  folders: SecondBrainFolder[]
  recent: SecondBrainNoteSummary[]
  totalNotes: number
}

export type SecondBrainFindHit = {
  path: string
  title: string
  type: string | null
  status: string | null
  updated: string | null
  tags: string[]
  /** Where brain.py matched the terms: title, tags, alias or body. */
  match: string | null
}

export type SecondBrainNote = {
  path: string
  text: string
}

export type SecondBrainNoteType = 'nota' | 'decisao' | 'estudo' | 'ideia' | 'meeting'

export type SecondBrainRecordRequest = {
  title: string
  folder: string
  type: SecondBrainNoteType
  summary: string
  tags: string[]
}

/** Where a skill goes: the agents' global skill folders, or one project's. */
export type SkillCatalogScope = { kind: 'global' } | { kind: 'project'; projectPath: string }

export type SkillCatalogEntry = {
  name: string
  title: string
  description: string
  version: string | null
  /** `library`: loaded by the person from a folder on disk. */
  origin: 'coding-opus' | 'app' | 'library'
}

export type SkillCatalogInstall = {
  name: string
  target: CodingOpusSkillTarget
  path: string
  /** `managed`: installed by this app; `external`: same name put there by hand or another tool. */
  state: 'missing' | 'managed' | 'external'
  version: string | null
}

export type SkillCatalogStatus = {
  scope: SkillCatalogScope
  entries: SkillCatalogEntry[]
  installs: SkillCatalogInstall[]
}

export type CodingOpusCommandResult<T> = { ok: true; value: T } | { ok: false; error: string }
