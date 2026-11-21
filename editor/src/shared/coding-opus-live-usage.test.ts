import { describe, expect, it } from 'vitest'
import { codingOpusLiveUsage } from './coding-opus-live-usage'
import type { ProviderRateLimits, RateLimitState } from './rate-limit-types'

const state: RateLimitState = {
  claude: null,
  codex: null,
  gemini: null,
  opencodeGo: null,
  minimax: null,
  minimaxCookieConfigured: false,
  minimaxApiKeyConfigured: false,
  opencodeGoApiKeyConfigured: false,
  claudeTarget: { runtime: 'host', wslDistro: null },
  codexTarget: { runtime: 'host', wslDistro: null },
  inactiveClaudeAccounts: [],
  inactiveCodexAccounts: []
}
const limits: ProviderRateLimits = {
  provider: 'codex',
  status: 'ok',
  error: null,
  updatedAt: 1795089600000,
  session: null,
  weekly: { usedPercent: 0, windowMinutes: 10080, resetsAt: null, resetDescription: null }
}

describe('native quota readings for Coding Opus', () => {
  it('preserves a real zero, missing reset and original observation time', () => {
    expect(codingOpusLiveUsage({ ...state, codex: limits }).providers).toEqual({
      codex: {
        observedAt: '2026-11-19T12:00:00.000Z',
        source: 'coding-agent-2',
        windows: { week: { usedPercent: 0, resetsAt: null } }
      }
    })
  })

  it('does not turn failed cached readings into a successful observation', () => {
    const result = codingOpusLiveUsage({
      ...state,
      codex: {
        ...limits,
        status: 'error',
        usageMetadata: { failureKind: 'rate-limited', retryAtMs: 1795093200000 }
      }
    })
    expect(result.providers).toEqual({})
    expect(result.statuses).toEqual({
      codex: {
        state: 'error',
        reason: 'rate-limited',
        retryAt: '2026-11-19T13:00:00.000Z'
      }
    })
  })
})
