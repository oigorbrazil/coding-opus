import { describe, expect, it } from 'vitest'
import { usageFromSnapshot } from './liveUsage'

const NOW = Date.parse('2026-11-19T12:00:00Z')

describe('recorded quota used by the playbooks preview', () => {
  it('retains known zero usage when the provider does not report a reset time', () => {
    expect(
      usageFromSnapshot(
        {
          providers: {
            codex: {
              observedAt: '2026-11-19T11:55:00Z',
              source: 'codex-app-server',
              windows: { week: { usedPercent: 0, resetsAt: null } }
            }
          }
        },
        NOW
      )
    ).toEqual({ codex: { week: 0, reset: null, expires: null } })
  })
  it('uses recorded windows without inventing values for another provider', () => {
    expect(
      usageFromSnapshot(
        {
          providers: {
            claude: {
              observedAt: '2026-11-19T11:55:00Z',
              source: 'stream-json',
              windows: {
                '5h': { usedPercent: 21.6, resetsAt: '2026-11-19T13:00:00Z' },
                week: { usedPercent: 38, resetsAt: '2026-11-20T12:00:00Z' }
              }
            }
          }
        },
        NOW
      )
    ).toEqual({ claude: { short: 22, week: 38, reset: 24, expires: null } })
  })

  it('does not treat an expired window as a new zero-percent reading', () => {
    expect(
      usageFromSnapshot(
        {
          providers: {
            codex: {
              observedAt: '2026-11-19T11:55:00Z',
              source: null,
              windows: {
                '5h': { usedPercent: 98, resetsAt: '2026-11-19T11:59:00Z' },
                week: { usedPercent: 17, resetsAt: '2026-11-20T12:00:00Z' }
              }
            }
          }
        },
        NOW
      )
    ).toEqual({ codex: { week: 17, reset: 24, expires: null } })
  })

  it('keeps old readings out of decisions even when their window has not expired', () => {
    expect(
      usageFromSnapshot(
        {
          providers: {
            claude: {
              observedAt: '2026-11-18T12:00:00Z',
              source: 'stream-json',
              windows: {
                week: { usedPercent: 98, resetsAt: '2026-11-20T12:00:00Z' }
              }
            }
          }
        },
        NOW
      )
    ).toEqual({})
  })

  it('keeps the weekly reset when a provider also reports a monthly window', () => {
    expect(
      usageFromSnapshot(
        {
          providers: {
            kimi: {
              observedAt: '2026-11-19T11:55:00Z',
              source: null,
              windows: {
                week: { usedPercent: 17, resetsAt: '2026-11-20T12:00:00Z' },
                month: { usedPercent: 42, resetsAt: '2026-12-19T12:00:00Z' }
              }
            }
          }
        },
        NOW
      )
    ).toEqual({ kimi: { week: 17, month: 42, reset: 24, expires: null } })
  })
})
