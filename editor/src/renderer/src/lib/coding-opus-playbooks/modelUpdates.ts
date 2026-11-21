import { parse, stringify } from 'yaml'
import type { CodingOpusModelCatalog } from '../../../../shared/coding-opus'

/** Replace `from` with `to` wherever the playbooks pick a model (tiers, profiles, roles, phases). */
export type ModelUpgrade = {
  provider: string
  from: string
  to: string
  uses: number
  cliSays: boolean
}
/** A model the CLI lists that the playbooks' `models:` list does not have yet. */
export type ModelAddition = { provider: string; model: string; description: string | null }
export type ModelUpdatePlan = { upgrades: ModelUpgrade[]; additions: ModelAddition[] }

type Family = { key: string; version: number[] }

/**
 * `gpt-6.1-sol` → family `gpt-#-sol` version [6, 1]; `claude-opus-5-5` → `claude-opus-#-#` [5, 5].
 * Models in one family differ only in their version numbers, so the highest version is the newest.
 */
export function modelFamily(id: string): Family | null {
  const version: number[] = []
  const key: string[] = []
  for (const part of id.split('-')) {
    // A date stamp (claude-haiku-4-5-20251001) pins a snapshot; it is not a newer version.
    if (/^\d+(\.\d+)*$/.test(part) && part.length < 8) {
      version.push(...part.split('.').map(Number))
      // `claude-sonnet-5` and `claude-sonnet-5-5` share a family: one run of numbers is one version.
      if (key.at(-1) !== '#') {
        key.push('#')
      }
    } else {
      key.push(part)
    }
  }
  return version.length > 0 ? { key: key.join('-'), version } : null
}

function newer(left: number[], right: number[]): boolean {
  for (let i = 0; i < Math.max(left.length, right.length); i++) {
    const a = left[i] ?? 0
    const b = right[i] ?? 0
    if (a !== b) {
      return a > b
    }
  }
  return false
}

function isMap(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function modelId(entry: unknown): string | null {
  if (typeof entry === 'string') {
    return entry
  }
  return isMap(entry) && typeof entry.id === 'string' ? entry.id : null
}

/** How many times each string appears outside the root `models:` list, i.e. where the playbooks pick a model. */
function usageCounts(doc: Record<string, unknown>): Map<string, number> {
  const counts = new Map<string, number>()
  const walk = (value: unknown): void => {
    if (typeof value === 'string') {
      counts.set(value, (counts.get(value) ?? 0) + 1)
    } else if (Array.isArray(value)) {
      value.forEach(walk)
    } else if (isMap(value)) {
      Object.values(value).forEach(walk)
    }
  }
  for (const [key, value] of Object.entries(doc)) {
    if (key !== 'models') {
      walk(value)
    }
  }
  return counts
}

function listedModels(doc: Record<string, unknown>): Record<string, string[]> {
  const models = isMap(doc.models) ? doc.models : {}
  const listed: Record<string, string[]> = {}
  for (const [provider, entries] of Object.entries(models)) {
    listed[provider] = (Array.isArray(entries) ? entries : [])
      .map(modelId)
      .filter((id): id is string => id !== null)
  }
  return listed
}

export function planModelUpdates(text: string, catalog: CodingOpusModelCatalog): ModelUpdatePlan {
  // oxlint-disable-next-line typescript/consistent-type-assertions -- SAFETY: YAML from the user's playbooks file; the skill validates its shape.
  const doc = parse(text) as unknown
  if (!isMap(doc)) {
    return { upgrades: [], additions: [] }
  }
  const counts = usageCounts(doc)
  const listed = listedModels(doc)
  const upgrades: ModelUpgrade[] = []
  const additions: ModelAddition[] = []
  for (const provider of new Set([...Object.keys(listed), ...Object.keys(catalog.providers)])) {
    const all = catalog.providers[provider] ?? []
    // The CLI's own list is what the account can run today; the price table only stands in without one.
    const offered = all.some((model) => model.source === 'cli')
      ? all.filter((model) => model.source === 'cli')
      : all
    const known = [...new Set([...(listed[provider] ?? []), ...offered.map((model) => model.id)])]
    for (const current of listed[provider] ?? []) {
      const uses = counts.get(current) ?? 0
      if (uses === 0) {
        continue
      }
      const told = offered.find((model) => model.id === current)?.upgrade
      let best: string | null = told && told !== current ? told : null
      const family = modelFamily(current)
      if (!best && family) {
        for (const candidate of known) {
          const other = modelFamily(candidate)
          if (
            other?.key === family.key &&
            newer(other.version, (modelFamily(best ?? current) ?? family).version)
          ) {
            best = candidate
          }
        }
      }
      if (best) {
        upgrades.push({ provider, from: current, to: best, uses, cliSays: best === told })
      }
    }
    for (const model of offered) {
      if (model.source === 'cli' && !(listed[provider] ?? []).includes(model.id)) {
        additions.push({ provider, model: model.id, description: model.description ?? null })
      }
    }
  }
  return { upgrades, additions }
}

/** Applies the chosen changes to the playbooks text; formatting is redone by the editor afterwards. */
export function applyModelUpdates(
  text: string,
  upgrades: readonly ModelUpgrade[],
  additions: readonly ModelAddition[]
): string {
  // oxlint-disable-next-line typescript/consistent-type-assertions -- SAFETY: YAML from the user's playbooks file; the skill validates its shape.
  const doc = parse(text) as Record<string, unknown>
  const swap = new Map(upgrades.map((upgrade) => [upgrade.from, upgrade.to]))
  const replace = (value: unknown): unknown => {
    if (typeof value === 'string') {
      return swap.get(value) ?? value
    }
    if (Array.isArray(value)) {
      return value.map(replace)
    }
    if (isMap(value)) {
      return Object.fromEntries(Object.entries(value).map(([key, inner]) => [key, replace(inner)]))
    }
    return value
  }
  // The `models:` list keeps the older models, so they stay selectable; only the places that pick one change.
  const next = Object.fromEntries(
    Object.entries(doc).map(([key, value]) => [key, key === 'models' ? value : replace(value)])
  )
  const models: Record<string, unknown> = isMap(next.models) ? { ...next.models } : {}
  for (const upgrade of upgrades) {
    const list = Array.isArray(models[upgrade.provider])
      ? // oxlint-disable-next-line typescript/consistent-type-assertions -- SAFETY: guarded by the Array.isArray check on this ternary.
        (models[upgrade.provider] as unknown[])
      : []
    if (!list.some((entry) => modelId(entry) === upgrade.to)) {
      models[upgrade.provider] = [...list, upgrade.to]
    }
  }
  for (const { provider, model } of additions) {
    // oxlint-disable-next-line typescript/consistent-type-assertions -- SAFETY: checked with Array.isArray on the same expression.
    const list = Array.isArray(models[provider]) ? (models[provider] as unknown[]) : []
    models[provider] = [...list, model]
  }
  for (const [provider, list] of Object.entries(models)) {
    if (!Array.isArray(list)) {
      continue
    }
    const seen = new Set<string>()
    models[provider] = list.filter((entry) => {
      const id = modelId(entry)
      if (id === null || seen.has(id)) {
        return id === null
      }
      seen.add(id)
      return true
    })
  }
  if (Object.keys(models).length > 0) {
    next.models = models
  }
  return stringify(next)
}
