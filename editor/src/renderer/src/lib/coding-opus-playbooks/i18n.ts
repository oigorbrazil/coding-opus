import { i18n } from '@/i18n/i18n'
import { useUiLanguageRevision } from '@/i18n/use-ui-language-revision'
import { PLAYBOOK_MESSAGES_EN, PLAYBOOK_MESSAGES_PT } from './messages'

// The editor keeps Coding Agent 1's keys and `{name}` params; the app's UI language picks the table.
export type MessageKey = string
export type Params = Record<string, string | number>
export type TFunction = (key: MessageKey, params?: Params) => string

function activeMessages(): Record<string, string> {
  return i18n.language?.startsWith('pt') ? PLAYBOOK_MESSAGES_PT : PLAYBOOK_MESSAGES_EN
}

export function translatePlaybooks(key: MessageKey, params?: Params): string {
  const message = activeMessages()[key] ?? PLAYBOOK_MESSAGES_EN[key] ?? key
  if (!params) {
    return message
  }
  return message.replace(/\{(\w+)\}/g, (match, name: string) =>
    params[name] === undefined ? match : String(params[name])
  )
}

export function useT(): TFunction {
  // Re-render when the UI language changes.
  useUiLanguageRevision()
  return translatePlaybooks
}
