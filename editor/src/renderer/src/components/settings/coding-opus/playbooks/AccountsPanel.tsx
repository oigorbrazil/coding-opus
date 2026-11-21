import { ArrowDown, ArrowUp } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import type {
  CodingOpusAccountAction,
  CodingOpusAccountLogin,
  CodingOpusAccountManagerResult,
  CodingOpusAccountProvider,
  CodingOpusAccountRow,
  CodingOpusAccounts
} from '../../../../../../shared/coding-opus'
import { usePlaybooks } from './context'
import { Hint, PanelHead, Section } from './fields'
import { ProviderMark } from './ProviderMark'
import { AccountRowActions, AccountSignInControls } from './AccountSignInControls'
import styles from './Playbooks.module.css'
import { getIntlLocale } from '@/i18n/i18n'

export const ACCOUNT_PROVIDERS: readonly CodingOpusAccountProvider[] = ['codex', 'claude']

type Load =
  | { state: 'loading' }
  | { state: 'error'; error: string }
  | { state: 'ready'; accounts: CodingOpusAccounts }

function accountsApi() {
  // The desktop app and the skill's local server both expose this surface; older hosts lack it.
  const api = window.api?.codingOpus
  return typeof api?.readAccounts === 'function' && typeof api.orderAccounts === 'function'
    ? api
    : null
}

function resetText(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString(getIntlLocale(), { weekday: 'short', hour: '2-digit', minute: '2-digit' })
}

function QuotaLine({ row }: { row: CodingOpusAccountRow }) {
  const { t } = usePlaybooks()
  const quota = row.quota
  if (!quota) {
    return <p className={styles.line}>{t('playbooks.accountNoQuota')}</p>
  }
  const tone = quota.blocked ? styles.danger : quota.low ? styles.warn : styles.ok
  return (
    <p className={styles.line}>
      <span className={tone}>
        {t('playbooks.accountQuota', {
          percent: Math.round(quota.usedPercent),
          window: quota.window,
          time: resetText(quota.resetsAt)
        })}
      </span>
      {quota.blocked ? ` · ${t('playbooks.accountBlocked')}` : ''}
      {quota.stale ? ` · ${t('playbooks.accountStale')}` : ''}
    </p>
  )
}

export function AccountsPanel({ provider }: { provider: CodingOpusAccountProvider }) {
  const { t, s } = usePlaybooks()
  const [load, setLoad] = useState<Load>({ state: 'loading' })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [logins, setLogins] = useState<CodingOpusAccountLogin[]>([])
  const lastSelection = useRef<string | null>(null)
  const managed = typeof window.api?.codingOpus?.manageAccounts === 'function'
  const label = s.catalog[provider]?.label ?? provider

  const receive = useCallback(
    (result: CodingOpusAccountManagerResult) => {
      if (!result.ok) {
        const errors: Record<string, string> = {
          'account-exists': 'accountExists',
          'invalid-name': 'accountInvalidName',
          'login-busy': 'accountLoginBusy',
          'account-not-ready': 'accountNotReady',
          'system-account': 'accountInvalidName'
        }
        const key = errors[result.error]
        setError(t(`playbooks.${key ?? 'accountUpdateFailed'}`))
        return false
      }
      setError(null)
      setLoad({ state: 'ready', accounts: result.accounts })
      setLogins(result.logins)
      const selection =
        JSON.stringify(result.selected) +
        JSON.stringify(result.logins.filter((job) => job.state === 'complete').map((job) => job.id))
      if (lastSelection.current !== null && lastSelection.current !== selection) {
        window.dispatchEvent(new Event('coding-opus-accounts-changed'))
      }
      lastSelection.current = selection
      return true
    },
    [t]
  )

  const refresh = useCallback(async () => {
    const api = accountsApi()
    if (!api) {
      setLoad({ state: 'error', error: t('playbooks.accountsUnsupported') })
      return
    }
    try {
      if (api.manageAccounts) {
        receive(await api.manageAccounts({ action: 'state' }))
        return
      }
      const result = await api.readAccounts()
      setLoad(
        result.ok
          ? { state: 'ready', accounts: result.accounts }
          : { state: 'error', error: result.error }
      )
    } catch {
      setError(t('playbooks.accountUpdateFailed'))
    }
  }, [t, receive])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const login = logins.find((job) => job.provider === provider)
  const pending = login?.state === 'pending'
  useEffect(() => {
    if (!pending) {
      return
    }
    const timer = window.setInterval(() => void refresh(), 1000)
    return () => window.clearInterval(timer)
  }, [pending, refresh])

  const act = async (request: CodingOpusAccountAction) => {
    const manage = accountsApi()?.manageAccounts
    if (!manage) {
      return false
    }
    setSaving(true)
    try {
      return receive(await manage({ ...request, provider }))
    } catch {
      setError(t('playbooks.accountUpdateFailed'))
      return false
    } finally {
      setSaving(false)
    }
  }

  const rows = load.state === 'ready' ? load.accounts.providers[provider] : []
  const rotation = rows.filter((row) => row.inRotation)

  const move = async (index: number, step: number) => {
    const api = accountsApi()
    const to = index + step
    if (!api || to < 0 || to >= rotation.length) {
      return
    }
    const names = rotation.map((row) => row.name)
    ;[names[index], names[to]] = [names[to], names[index]]
    if (api.manageAccounts) {
      await act({ action: 'order', names })
      return
    }
    setSaving(true)
    try {
      const result = await api.orderAccounts(provider, names)
      setLoad(
        result.ok
          ? { state: 'ready', accounts: result.accounts }
          : { state: 'error', error: result.error }
      )
      if (result.ok) {
        await refresh()
        window.dispatchEvent(new Event('coding-opus-accounts-changed'))
      }
    } catch {
      setError(t('playbooks.accountUpdateFailed'))
    } finally {
      setSaving(false)
    }
  }

  const origin = (row: CodingOpusAccountRow): string =>
    row.from === 'cli'
      ? t('playbooks.accountFromCli')
      : row.from === 'coding-agent'
        ? t('playbooks.accountFromAgent')
        : t('playbooks.accountFromOpus')

  return (
    <>
      <PanelHead
        kind={t('playbooks.kindAccounts')}
        title={t('playbooks.accountsTitle', { provider: label })}
        mark={<ProviderMark id={provider} size={16} />}
      />
      <Hint>{t('playbooks.accountsHint')}</Hint>
      {error ? (
        <p className={`${styles.line} ${styles.danger}`} role="alert">
          {error}
        </p>
      ) : null}
      {managed ? (
        <AccountSignInControls key={provider} login={login} busy={saving} act={act} />
      ) : null}
      {load.state === 'loading' ? <Hint>{t('playbooks.accountsLoading')}</Hint> : null}
      {load.state === 'error' ? (
        <p className={`${styles.line} ${styles.danger}`}>{load.error}</p>
      ) : null}
      {load.state === 'ready' ? (
        <Section title={t('playbooks.accountsOrder')}>
          <div className={styles.cards}>
            {rows.map((row) => {
              const index = rotation.indexOf(row)
              return (
                <div key={row.name} className={styles.card}>
                  <header>
                    <b>
                      {index !== -1 ? `${index + 1}. ` : ''}
                      {row.from === 'cli'
                        ? t('playbooks.accountDefault', { provider: label })
                        : row.name}
                    </b>
                    {index !== -1 && rotation.length > 1 ? (
                      <span className={styles.mini}>
                        <button
                          type="button"
                          aria-label={t('playbooks.earlier')}
                          title={t('playbooks.earlier')}
                          disabled={saving || index === 0}
                          onClick={() => void move(index, -1)}
                        >
                          <ArrowUp size={12} />
                        </button>
                        <button
                          type="button"
                          aria-label={t('playbooks.later')}
                          title={t('playbooks.later')}
                          disabled={saving || index === rotation.length - 1}
                          onClick={() => void move(index, 1)}
                        >
                          <ArrowDown size={12} />
                        </button>
                      </span>
                    ) : null}
                  </header>
                  <p className={styles.line}>
                    {origin(row)}
                    {row.email ? ` · ${row.email}` : ''}
                    {row.activeInCodingAgent ? ` · ${t('playbooks.accountActive')}` : ''}
                  </p>
                  {row.ready ? (
                    <QuotaLine row={row} />
                  ) : (
                    <p className={`${styles.line} ${styles.warn}`}>
                      {t('playbooks.accountNotReady')}
                    </p>
                  )}
                  {managed ? (
                    <AccountRowActions row={row} busy={saving || pending} act={act} />
                  ) : null}
                </div>
              )
            })}
          </div>
          {rows.length <= 1 ? <Hint>{t('playbooks.accountsOnlyDefault')}</Hint> : null}
        </Section>
      ) : null}
      <Section title={t('playbooks.accountsManageTitle')}>
        <Hint>{t(managed ? 'playbooks.accountsManagedHere' : 'playbooks.accountsManage')}</Hint>
        <div className={styles.actions}>
          <button type="button" className={styles.button} onClick={() => void refresh()}>
            {t('playbooks.accountsRefresh')}
          </button>
        </div>
      </Section>
    </>
  )
}
