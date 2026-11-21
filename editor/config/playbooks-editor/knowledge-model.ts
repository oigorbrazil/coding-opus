export type LibraryKind = 'notes' | 'memory'

export type LibraryGroup = {
  id: string
  label: string
  path?: string
  count: number
}

export type LibraryEntry = {
  id: string
  title: string
  group: string
  updated: string
  type?: string
  tags?: string[]
  agent?: string
  messages?: number
}

export type LibraryIndex = {
  path: string
  exists: boolean
  enabled: boolean
  total: number
  count: number
  pageSize: number
  groups: LibraryGroup[]
  entries: LibraryEntry[]
}

export type NoteDetail = {
  id: string
  title: string
  text: string
  revision: string
  sourceConversation?: string | null
}

export type Reminder = {
  id: string
  title: string
  due: string
  shortcut: string
  completed: string | null
}

export type ReminderList = { today: string; items: Reminder[] }

export type CheckpointDetails = { objective?: string; attempts?: string; checks?: string }
export type MemoryCheckpoint = {
  id: number
  created: string
  through_position: number
  summary: string
  next_step: string
  details: CheckpointDetails
}
export type ConversationRef = { id: string; title: string; agent: string }

export type ConversationDetail = {
  id: string
  title: string
  customTitle?: string | null
  agent: string
  project: string
  projects?: string[]
  updated: string
  state?: string
  summary: string
  next_step: string
  checkpoint?: MemoryCheckpoint | null
  checkpointStale?: boolean
  checkpointHistory?: MemoryCheckpoint[]
  previous?: ConversationRef[]
  continuations?: ConversationRef[]
  count: number
  hasOlder: boolean
  messages: {
    position: number
    role: string
    content: string
    timestamp: string
    project?: string
  }[]
}

export type LibraryDetail = NoteDetail | ConversationDetail

export const localize = (pt: string, en: string): string =>
  navigator.language.toLowerCase().startsWith('pt') ? pt : en

export const checkpointFields = [
  { key: 'objective', label: localize('Objetivo', 'Goal') },
  { key: 'attempts', label: localize('Tentativas e bloqueios', 'Attempts and blockers') },
  { key: 'checks', label: localize('Verificações', 'Checks') }
] as const

export function formatDate(value: string): string {
  const date = new Date(value.length === 10 ? `${value}T00:00:00` : value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

export function agentLabel(agent: string): string {
  if (agent === 'claude') {
    return 'Claude'
  }
  if (agent === 'codex') {
    return 'Codex'
  }
  return agent
}
