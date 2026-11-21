import type { CodingOpusUsageSnapshot } from './coding-opus'
import type { ProviderRateLimits, RateLimitState } from './rate-limit-types'

export function codingOpusLiveUsage(state: RateLimitState): CodingOpusUsageSnapshot {
  const statuses: NonNullable<CodingOpusUsageSnapshot['statuses']> = {}
  const snapshot: CodingOpusUsageSnapshot = { providers: {}, statuses }
  const providers: [string, ProviderRateLimits | null][] = [
    ['claude', state.claude],
    ['codex', state.codex],
    ['gemini', state.gemini],
    ['opencode', state.opencodeGo],
    ['minimax', state.minimax]
  ]
  for (const [provider, limits] of providers) {
    if (!limits) {
      continue
    }
    statuses[provider] = {
      state: limits.status === 'ok' ? 'ok' : 'error',
      reason:
        limits.status === 'ok' ? null : (limits.usageMetadata?.failureKind ?? 'usage-unavailable'),
      retryAt: limits.usageMetadata?.retryAtMs
        ? new Date(limits.usageMetadata.retryAtMs).toISOString()
        : null
    }
    if (limits.status !== 'ok' || !Number.isFinite(limits.updatedAt) || limits.updatedAt <= 0) {
      continue
    }
    const windows: CodingOpusUsageSnapshot['providers'][string]['windows'] = {}
    for (const value of [limits.session, limits.weekly, limits.monthly]) {
      if (
        !value ||
        !Number.isFinite(value.usedPercent) ||
        value.usedPercent < 0 ||
        value.usedPercent > 100
      ) {
        continue
      }
      const name = new Map([
        [300, '5h'],
        [10080, 'week'],
        [43200, 'month'],
        [1440, 'day']
      ]).get(value.windowMinutes)
      if (name) {
        windows[name] = {
          usedPercent: value.usedPercent,
          resetsAt:
            value.resetsAt !== null && Number.isFinite(value.resetsAt)
              ? new Date(value.resetsAt).toISOString()
              : null
        }
      }
    }
    if (Object.keys(windows).length) {
      snapshot.providers[provider] = {
        observedAt: new Date(limits.updatedAt).toISOString(),
        source: 'coding-agent-2',
        windows
      }
    }
  }
  return snapshot
}
