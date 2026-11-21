import type {
  CodingOpusUsageReading,
  CodingOpusUsageSnapshot
} from '../../../../shared/coding-opus'
import type { ProviderUsage, Usage } from './catalog'

export function usageReadingIsStale(reading: CodingOpusUsageReading, now = Date.now()): boolean {
  const observed = Date.parse(reading.observedAt)
  return !Number.isFinite(observed) || now - observed > 30 * 60_000
}

export function usageFromSnapshot(snapshot: CodingOpusUsageSnapshot, now = Date.now()): Usage {
  const usage: Usage = {}
  for (const [provider, reading] of Object.entries(snapshot.providers)) {
    if (usageReadingIsStale(reading, now)) {
      continue
    }
    const values: ProviderUsage = { reset: null, expires: null }
    for (const [key, window] of Object.entries(reading.windows)) {
      const resetsAt = window.resetsAt === null ? null : Date.parse(window.resetsAt)
      if (
        !Number.isFinite(window.usedPercent) ||
        window.usedPercent < 0 ||
        window.usedPercent > 100 ||
        (resetsAt !== null && (!Number.isFinite(resetsAt) || resetsAt <= now))
      ) {
        continue
      }
      values[key === '5h' ? 'short' : key] = Math.round(window.usedPercent)
      if (resetsAt !== null && (key === 'week' || (key === 'month' && !reading.windows.week))) {
        values.reset = Math.max(1, Math.ceil((resetsAt - now) / 3_600_000))
      }
    }
    if (Object.keys(values).some((key) => key !== 'reset' && key !== 'expires')) {
      usage[provider] = values
    }
  }
  return usage
}
