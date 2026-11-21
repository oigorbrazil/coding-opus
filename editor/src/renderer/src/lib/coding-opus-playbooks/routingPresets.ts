import type { OrchestrationRole, RoutingRule } from './types'

/** The routing presets the playbooks editor ships as starting points. */
export type StaticRoutingPresetId = 'economy' | 'balanced' | 'performance'

/** A preset ships the roles its rules point at plus the rules themselves (ids minted on apply). */
export type RoutingPreset = {
  roles: OrchestrationRole[]
  rules: Omit<RoutingRule, 'id'>[]
}

const role = (
  name: string,
  agent: OrchestrationRole['agent'],
  model: string | null,
  effort: string | null,
  readOnly: boolean,
  fallback?: string
): OrchestrationRole => ({
  name,
  agent,
  model,
  effort,
  readOnly,
  timeoutSeconds: null,
  ...(fallback ? { fallback } : {})
})

export const ROUTING_PRESETS: Record<StaticRoutingPresetId, RoutingPreset> = {
  economy: {
    roles: [
      role('scout', 'claude', 'haiku', 'low', false, 'handyman'),
      role('handyman', 'codex', null, 'low', true),
      role('builder', 'codex', null, 'medium', false, 'scout')
    ],
    rules: [
      {
        enabled: true,
        kinds: ['research', 'scrap', 'docs'],
        efforts: [],
        gates: [],
        role: 'scout'
      },
      { enabled: true, kinds: [], efforts: ['light'], gates: [], role: 'scout' },
      { enabled: true, kinds: ['review'], efforts: [], gates: [], role: 'handyman' },
      { enabled: true, kinds: [], efforts: ['standard', 'deep'], gates: [], role: 'builder' }
    ]
  },
  balanced: {
    roles: [
      role('scout', 'claude', 'haiku', 'low', false, 'handyman'),
      role('handyman', 'codex', null, 'low', true),
      role('builder', 'claude', 'sonnet', 'medium', false, 'codex-builder'),
      role('codex-builder', 'codex', null, 'medium', false),
      role('expert', 'claude', 'opus', 'high', false, 'builder')
    ],
    rules: [
      {
        enabled: true,
        kinds: ['research', 'scrap', 'docs'],
        efforts: [],
        gates: [],
        role: 'scout'
      },
      { enabled: true, kinds: [], efforts: ['light'], gates: [], role: 'scout' },
      { enabled: true, kinds: ['review'], efforts: [], gates: [], role: 'handyman' },
      {
        enabled: true,
        kinds: [],
        efforts: ['deep'],
        gates: [{ agent: 'claude', window: 'opus', below: 50 }],
        role: 'expert'
      },
      { enabled: true, kinds: [], efforts: [], gates: [], role: 'builder' }
    ]
  },
  performance: {
    roles: [
      role('builder', 'claude', 'sonnet', 'medium', false, 'codex-builder'),
      role('codex-builder', 'codex', null, 'medium', false),
      role('expert', 'claude', 'opus', 'high', false, 'builder')
    ],
    rules: [
      { enabled: true, kinds: [], efforts: ['light'], gates: [], role: 'builder' },
      {
        enabled: true,
        kinds: [],
        efforts: ['deep'],
        gates: [{ agent: 'claude', window: 'opus', below: 80 }],
        role: 'expert'
      },
      { enabled: true, kinds: [], efforts: [], gates: [], role: 'builder' }
    ]
  }
}

// oxlint-disable-next-line typescript/consistent-type-assertions -- SAFETY: Object.keys of a literal record returns exactly its own keys.
export const ROUTING_PRESET_IDS = Object.keys(ROUTING_PRESETS) as StaticRoutingPresetId[]
