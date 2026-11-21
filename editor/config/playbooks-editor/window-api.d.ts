import type { RateLimitState } from '../../src/shared/rate-limit-types'
import type { CodingOpusApi } from './skill-server-api'

declare global {
  interface Window {
    /**
     * Installed by installSkillServerApi before the editor renders. The shared editor code also
     * checks for desktop-only pieces (account management through the app, native rate limits);
     * the standalone page never installs `rateLimits`, and `manageAccounts` stays optional there.
     */
    api: {
      codingOpus?: Omit<CodingOpusApi, 'manageAccounts'> &
        Partial<Pick<CodingOpusApi, 'manageAccounts'>>
      rateLimits?: { get(): Promise<RateLimitState>; refresh(): Promise<RateLimitState> }
    }
  }
}

export {}
