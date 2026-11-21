import { getIntlLocale } from '@/i18n/i18n'
import { usageReadingIsStale } from '@/lib/coding-opus-playbooks/liveUsage'
import { providerLabel, windowsOf } from '@/lib/coding-opus-playbooks/state'
import { windowLabel } from '@/lib/coding-opus-playbooks/labels'
import { usePlaybooks } from './context'
import styles from './Playbooks.module.css'

export function UsageReading({
  provider,
  load
}: {
  provider: string
  load: 'loading' | 'ready' | 'error'
}) {
  const { s, t } = usePlaybooks()
  const reading = s.liveUsageSnapshot?.providers[provider]
  const status = s.liveUsageSnapshot?.statuses?.[provider]
  const reason = status?.reason
  const needsLogin =
    reason &&
    [
      'sign-in-required',
      'missing-credentials',
      'stale-token',
      'refreshable-credentials-without-token',
      'delegated-refresh-required',
      'keychain-unavailable',
      'missing-scope'
    ].includes(reason)
  const reasonKey = needsLogin
    ? 'signIn'
    : reason === 'rate-limited'
      ? 'rateLimited'
      : reason === 'cli-unavailable'
        ? 'cliMissing'
        : reason === 'not-supported'
          ? 'unsupported'
          : reason === 'usage-unavailable' || reason === 'no-subscription'
            ? 'unavailable'
            : reason
              ? 'failed'
              : null
  const liveSource =
    reading &&
    [
      'codex-app-server',
      'claude-oauth',
      'antigravity-cli',
      'kimi-cli',
      'opencode-api',
      'coding-agent-2'
    ].includes(reading.source ?? '')
  const observed = reading ? Date.parse(reading.observedAt) : Number.NaN
  const known = reading && Number.isFinite(observed) && Object.keys(reading.windows).length > 0
  const now = s.liveUsageReadAt ?? 0
  const expired =
    reading &&
    Object.values(reading.windows).some((w) => w.resetsAt !== null && Date.parse(w.resetsAt) <= now)
  return (
    <div aria-live="polite">
      {load === 'loading' ? <p className={styles.foot}>{t('playbooks.usageLoading')}</p> : null}
      {load === 'error' ? <p className={styles.foot}>{t('playbooks.usageReadError')}</p> : null}
      {reasonKey && load !== 'loading' ? (
        <p className={styles.usageNotice} role="status">
          {t(`playbooks.usageReason.${reasonKey}`, { provider: providerLabel(s, provider) })}
        </p>
      ) : null}
      {known ? (
        <>
          <p className={styles.usageOrigin}>
            {t(liveSource ? 'playbooks.usageSourceLive' : 'playbooks.usageSource', {
              provider: providerLabel(s, provider)
            })}
          </p>
          <p className={styles.usageOrigin}>
            {reading.account
              ? `${t('playbooks.usageSelectedAccount', { name: reading.account })} · `
              : ''}
            {t('playbooks.usageObserved')}{' '}
            <time dateTime={reading.observedAt}>
              {new Date(observed).toLocaleString(getIntlLocale(), {
                dateStyle: 'short',
                timeStyle: 'short'
              })}
            </time>
          </p>
          {usageReadingIsStale(reading, now) || expired ? (
            <p className={styles.usageNotice}>{t('playbooks.usageStale')}</p>
          ) : null}
          <dl className={styles.usageReadings}>
            {windowsOf(s, provider)
              .filter((w) => reading.windows[w.key === 'short' ? '5h' : w.key])
              .map((w) => {
                const window = reading.windows[w.key === 'short' ? '5h' : w.key]
                return (
                  <div key={w.key}>
                    <dt>{windowLabel(t, w)}</dt>
                    <dd>{window ? `${Math.round(window.usedPercent)}%` : '—'}</dd>
                  </div>
                )
              })}
          </dl>
        </>
      ) : load !== 'loading' ? (
        <>
          <p className={styles.usageEmpty}>{t('playbooks.usageNoData')}</p>
          {!reasonKey ? <p className={styles.foot}>{t('playbooks.usageNoDataHint')}</p> : null}
        </>
      ) : null}
    </div>
  )
}
