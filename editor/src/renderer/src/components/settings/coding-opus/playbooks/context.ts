import { createContext, useContext } from 'react'

import type { TFunction } from '@/lib/coding-opus-playbooks/i18n'
import type { PlaybooksState } from '@/lib/coding-opus-playbooks/state'
import type { Theme } from '@/lib/coding-opus-playbooks/types'

export type PlaybooksEditorContext = {
  s: PlaybooksState
  t: TFunction
  theme: Theme
  lightTheme: boolean
  touch: (global?: boolean) => void
  redraw: () => void
  select: (id: string | null) => void
  /** Replaces the whole playbooks with this YAML as one undoable edit (used by "Update models"). */
  replaceYaml: (text: string) => void
  selectedId: string | null
}

export const PlaybooksContext = createContext<PlaybooksEditorContext | null>(null)

export function usePlaybooks(): PlaybooksEditorContext {
  const value = useContext(PlaybooksContext)
  if (!value) {
    throw new Error('usePlaybooks outside the playbooks editor')
  }
  return value
}
