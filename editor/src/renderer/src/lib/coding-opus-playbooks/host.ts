import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import type { CodingOpusPlaybooks } from '../../../../shared/coding-opus'
import type { Theme } from './types'

// Coding Agent 2's side of what the playbooks editor read from Coding Agent 1's Tauri host.
export type SkillPlaybooks = CodingOpusPlaybooks

function codingOpusApi(): NonNullable<typeof window.api.codingOpus> {
  const api = window.api.codingOpus
  if (!api) {
    throw new Error('Playbooks need the desktop app.')
  }
  return api
}

export function orchestratorPlaybooks(): Promise<SkillPlaybooks> {
  return codingOpusApi().readPlaybooks()
}

export async function orchestratorSavePlaybooks(text: string): Promise<SkillPlaybooks> {
  const result = await codingOpusApi().savePlaybooks(text)
  if (!result.ok) {
    throw new Error(result.error)
  }
  return result.playbooks
}

const STORAGE_PREFIX = 'coding-agent-2:playbooks:'

export function readScopedStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(STORAGE_PREFIX + key)
  } catch {
    return null
  }
}

export function writeScopedStorage(key: string, value: string): void {
  try {
    window.localStorage.setItem(STORAGE_PREFIX + key, value)
  } catch {
    // Layout memory is a convenience; a blocked storage keeps the default layout.
  }
}

function documentIsDark(): boolean {
  return document.documentElement.classList.contains('dark')
}

/** The app's applied theme as the editor's icons expect it: 'light' or 'dark'. */
export function useAppliedTheme(): Theme {
  const [dark, setDark] = useState(documentIsDark)
  useEffect(() => {
    const observer = new MutationObserver(() => setDark(documentIsDark()))
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
    return () => observer.disconnect()
  }, [])
  return dark ? 'dark' : 'light'
}

export function isLightTheme(theme: Theme): boolean {
  return theme === 'light'
}

export function pushToast({ title, body }: { title: string; body?: string }): void {
  toast(title, body ? { description: body } : undefined)
}

/** Provider accent for flow edges; falls back to the app foreground when no agent color exists. */
export function agentAccentVar(id: string): string {
  return `var(--agent-${id}, var(--foreground))`
}
