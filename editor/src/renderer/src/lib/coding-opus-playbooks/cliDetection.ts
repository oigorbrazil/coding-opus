import { emitPlaybooksYaml, parsePlaybooksYaml } from './yaml'

/** One agent CLI found by `orchestrate.py probe --all` (the skill server's /api/clis). */
export type DetectedCli = {
  id: string
  label: string
  kind: 'builtin' | 'custom'
  installed: boolean
  version: string | null
  executable: string | null
  loggedIn: boolean | null
}

/**
 * - configured: already in `providers`
 * - addable: a built-in provider, or a custom CLI whose adapter is already recorded
 * - needs-adapter: a custom CLI without an adapter; the skill records one only after a person checks
 *   the CLI's non-interactive mode, so the editor never guesses its flags
 */
export type CliStatus = 'configured' | 'addable' | 'needs-adapter'

const isMap = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

function readDoc(text: string): Record<string, unknown> {
  const doc = parsePlaybooksYaml(text)
  return isMap(doc) ? doc : {}
}

export function cliStatus(text: string, cli: DetectedCli): CliStatus {
  const doc = readDoc(text)
  const providers = Array.isArray(doc.providers) ? doc.providers : []
  if (providers.includes(cli.id)) {
    return 'configured'
  }
  if (cli.kind === 'builtin') {
    return 'addable'
  }
  return isMap(doc.adapters) && isMap(doc.adapters[cli.id]) ? 'addable' : 'needs-adapter'
}

/**
 * Adds a provider at the end of `providers` and of every profile's `order` (a profile order must
 * list each provider once), so it is tried last everywhere. Playbooks, phases and families are left
 * alone.
 */
export function addProvider(text: string, id: string): string {
  const doc = readDoc(text)
  const providers = Array.isArray(doc.providers) ? doc.providers : []
  if (providers.includes(id)) {
    return text
  }
  const profiles = isMap(doc.profiles)
    ? Object.fromEntries(
        Object.entries(doc.profiles).map(([key, profile]) => [
          key,
          isMap(profile) && Array.isArray(profile.order) && !profile.order.includes(id)
            ? { ...profile, order: [...profile.order, id] }
            : profile
        ])
      )
    : doc.profiles
  return emitPlaybooksYaml({
    ...doc,
    providers: [...providers, id],
    ...(profiles === undefined ? {} : { profiles })
  })
}
