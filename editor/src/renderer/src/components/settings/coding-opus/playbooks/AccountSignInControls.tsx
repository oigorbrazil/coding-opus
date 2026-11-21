import { ExternalLink } from 'lucide-react'
import { useState } from 'react'
import type {
  CodingOpusAccountAction,
  CodingOpusAccountLogin,
  CodingOpusAccountRow
} from '../../../../../../shared/coding-opus'
import { usePlaybooks } from './context'
import { Check, Hint, Section } from './fields'
import styles from './Playbooks.module.css'

export type AccountAction = (request: CodingOpusAccountAction) => Promise<boolean>

export function AccountSignInControls({
  login,
  busy,
  act
}: {
  login?: CodingOpusAccountLogin
  busy: boolean
  act: AccountAction
}) {
  const { t } = usePlaybooks()
  const [name, setName] = useState('')
  const [code, setCode] = useState('')
  const pending = login?.state === 'pending'
  return (
    <Section title={t(pending ? 'playbooks.accountSignInTitle' : 'playbooks.accountAddTitle')}>
      {pending ? (
        <div className={styles.accountFlow}>
          <p className={styles.line} role="status">
            {t(login.url ? 'playbooks.accountAuthorize' : 'playbooks.accountPreparing', {
              name: login.name
            })}
          </p>
          {login.userCode ? (
            <p className={styles.line}>
              {t('playbooks.accountDeviceCode')} <code>{login.userCode}</code>
            </p>
          ) : null}
          {login.url ? (
            <a
              className={`${styles.button} ${styles.primary}`}
              href={login.url}
              target="_blank"
              rel="noreferrer"
            >
              <ExternalLink size={12} />
              {t('playbooks.accountOpenLogin')}
            </a>
          ) : null}
          {login.needsCode ? (
            <form
              className={styles.accountFlow}
              onSubmit={(event) => {
                event.preventDefault()
                void act({ action: 'input', loginId: login.id, code }).then((ok) => {
                  if (ok) {
                    setCode('')
                  }
                })
              }}
            >
              <label className={styles.field}>
                <span>{t('playbooks.accountPasteCode')}</span>
                <input
                  className={styles.input}
                  type="password"
                  autoComplete="off"
                  value={code}
                  maxLength={4096}
                  onChange={(event) => setCode(event.target.value)}
                  disabled={busy}
                />
              </label>
              <button className={styles.button} type="submit" disabled={busy || !code.trim()}>
                {t('playbooks.accountSendCode')}
              </button>
            </form>
          ) : null}
          <Hint>{t('playbooks.accountWaiting')}</Hint>
          <button
            type="button"
            className={styles.button}
            disabled={busy}
            onClick={() => void act({ action: 'cancel', loginId: login.id })}
          >
            {t('common.cancel')}
          </button>
        </div>
      ) : (
        <>
          {login?.state === 'complete' ? (
            <p className={`${styles.line} ${styles.ok}`} role="status">
              {t('playbooks.accountAdded', { name: login.name })}
            </p>
          ) : null}
          {login?.state === 'cancelled' ? (
            <p className={styles.line} role="status">
              {t('playbooks.accountCancelled')}
            </p>
          ) : null}
          {login?.state === 'error' ? (
            <p className={`${styles.line} ${styles.danger}`} role="alert">
              {t(
                login.error === 'login-timeout'
                  ? 'playbooks.accountLoginTimeout'
                  : 'playbooks.accountLoginFailed'
              )}
            </p>
          ) : null}
          <Hint>{t('playbooks.accountIndependent')}</Hint>
          <form
            className={styles.accountFlow}
            onSubmit={(event) => {
              event.preventDefault()
              void act({ action: 'add', name: name.trim() }).then((ok) => {
                if (ok) {
                  setName('')
                }
              })
            }}
          >
            <label className={styles.field}>
              <span>{t('playbooks.accountName')}</span>
              <input
                className={styles.input}
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={t('playbooks.accountNamePlaceholder')}
                pattern="[a-z0-9][a-z0-9_-]{0,31}"
                maxLength={32}
                required
                spellCheck={false}
                autoComplete="off"
                disabled={busy}
              />
            </label>
            <button
              type="submit"
              className={`${styles.button} ${styles.primary}`}
              disabled={busy || !name.trim()}
            >
              {t('playbooks.accountAdd')}
            </button>
          </form>
        </>
      )}
    </Section>
  )
}

export function AccountRowActions({
  row,
  busy,
  act
}: {
  row: CodingOpusAccountRow
  busy: boolean
  act: AccountAction
}) {
  const { t } = usePlaybooks()
  const [confirm, setConfirm] = useState(false)
  const [deleteData, setDeleteData] = useState(false)
  if (confirm) {
    return (
      <div className={styles.accountFlow}>
        <p className={styles.line}>{t('playbooks.accountRemoveConfirm', { name: row.name })}</p>
        <Check
          label={t('playbooks.accountDeleteData')}
          checked={deleteData}
          onChange={setDeleteData}
        />
        <Hint>
          {t(deleteData ? 'playbooks.accountDeleteWarning' : 'playbooks.accountKeepData')}
        </Hint>
        <div className={styles.actions}>
          <button
            type="button"
            className={`${styles.button} ${styles.dangerButton}`}
            disabled={busy}
            onClick={() =>
              void act({ action: 'remove', name: row.name, deleteData }).then((ok) => {
                if (ok) {
                  setConfirm(false)
                }
              })
            }
          >
            {t('playbooks.accountConfirmRemove')}
          </button>
          <button
            type="button"
            className={styles.button}
            disabled={busy}
            onClick={() => setConfirm(false)}
          >
            {t('common.cancel')}
          </button>
        </div>
      </div>
    )
  }
  return (
    <div className={styles.actions}>
      {row.selected ? (
        <span className={`${styles.line} ${styles.ok}`}>{t('playbooks.accountSelected')}</span>
      ) : (
        <button
          type="button"
          className={styles.button}
          disabled={busy || !row.ready}
          onClick={() => void act({ action: 'select', name: row.name })}
        >
          {t('playbooks.accountUse')}
        </button>
      )}
      {row.manageable ? (
        <>
          <button
            type="button"
            className={styles.button}
            disabled={busy}
            onClick={() => void act({ action: 'login', name: row.name })}
          >
            {t('playbooks.accountLoginAgain')}
          </button>
          <button
            type="button"
            className={`${styles.button} ${styles.dangerButton}`}
            disabled={busy}
            onClick={() => setConfirm(true)}
          >
            {t('playbooks.accountRemove')}
          </button>
        </>
      ) : null}
    </div>
  )
}
