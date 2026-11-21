import { useCallback, useEffect, useState } from 'react'
import type { CodingOpusModelCatalog } from '../../../../../../shared/coding-opus'
import {
  applyModelUpdates,
  planModelUpdates,
  type ModelUpdatePlan
} from '@/lib/coding-opus-playbooks/modelUpdates'
import { providerLabel, toYaml } from '@/lib/coding-opus-playbooks/state'
import { usePlaybooks } from './context'
import { Check, Checks, Hint, PanelHead, Section } from './fields'
import styles from './Playbooks.module.css'
import { getIntlLocale } from '@/i18n/i18n'

/** Time of the last model check, in the app UI language. */
function formatCheckedTime(date: Date): string {
  return date.toLocaleTimeString(getIntlLocale())
}

export const MODEL_UPDATES_ID = 'model-updates'

type Load =
  | { state: 'loading' }
  | { state: 'error'; error: string }
  | { state: 'ready'; catalog: CodingOpusModelCatalog; plan: ModelUpdatePlan }

const upgradeKey = (provider: string, from: string) => `up:${provider}:${from}`
const additionKey = (provider: string, model: string) => `add:${provider}:${model}`

/** Compares the models the playbooks pick with what each CLI offers now and applies the chosen swaps. */
export function ModelUpdatesPanel() {
  const { s, t, replaceYaml } = usePlaybooks()
  const [load, setLoad] = useState<Load>({ state: 'loading' })
  const [chosen, setChosen] = useState<Set<string>>(new Set())
  const [applied, setApplied] = useState(false)
  const [checkedAt, setCheckedAt] = useState<Date | null>(null)

  const check = useCallback(async () => {
    const api = window.api?.codingOpus
    if (typeof api?.modelCatalog !== 'function') {
      setLoad({ state: 'error', error: t('playbooks.modelsUpdateUnsupported') })
      return
    }
    // Show the check happening even when the answer comes back the same.
    setLoad({ state: 'loading' })
    setApplied(false)
    const result = await api.modelCatalog()
    setCheckedAt(new Date())
    if (!result.ok) {
      setLoad({ state: 'error', error: result.error })
      return
    }
    const plan = planModelUpdates(toYaml(s), result.catalog)
    setLoad({ state: 'ready', catalog: result.catalog, plan })
    // Swaps start selected; additions only widen the list, so they wait for a click.
    setChosen(new Set(plan.upgrades.map((upgrade) => upgradeKey(upgrade.provider, upgrade.from))))
  }, [s, t])

  useEffect(() => {
    void check()
    // Check once per opening; the button below checks again on demand.
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const toggle = (key: string, on: boolean) => {
    const next = new Set(chosen)
    if (on) {
      next.add(key)
    } else {
      next.delete(key)
    }
    setChosen(next)
  }

  const apply = () => {
    if (load.state !== 'ready') {
      return
    }
    const upgrades = load.plan.upgrades.filter((u) => chosen.has(upgradeKey(u.provider, u.from)))
    const additions = load.plan.additions.filter((a) =>
      chosen.has(additionKey(a.provider, a.model))
    )
    replaceYaml(applyModelUpdates(toYaml(s), upgrades, additions))
    setApplied(true)
    setLoad({
      state: 'ready',
      catalog: load.catalog,
      plan: planModelUpdates(toYaml(s), load.catalog)
    })
    setChosen(new Set())
  }

  const priceOnly =
    load.state === 'ready'
      ? Object.entries(load.catalog.providers)
          .filter(([, models]) => models.length > 0 && !models.some((m) => m.source === 'cli'))
          .map(([id]) => providerLabel(s, id))
      : []

  return (
    <>
      <PanelHead kind={t('playbooks.kindModels')} title={t('playbooks.modelsUpdateTitle')} />
      <Hint>{t('playbooks.modelsUpdateHint')}</Hint>
      {load.state === 'loading' ? <Hint>{t('playbooks.modelsUpdateChecking')}</Hint> : null}
      {load.state === 'error' ? (
        <p className={`${styles.line} ${styles.danger}`}>{load.error}</p>
      ) : null}
      {load.state === 'ready' ? (
        <>
          {applied ? (
            <p className={`${styles.line} ${styles.ok}`}>{t('playbooks.modelsUpdateApplied')}</p>
          ) : null}
          {load.plan.upgrades.length === 0 && load.plan.additions.length === 0 ? (
            <p className={`${styles.line} ${styles.ok}`}>{t('playbooks.modelsUpdateNone')}</p>
          ) : null}
          {checkedAt ? (
            <p className={styles.line}>
              {t('playbooks.modelsUpdateCheckedAt', {
                time: formatCheckedTime(checkedAt),
                count: Object.values(load.catalog.providers).reduce(
                  (total, models) => total + models.length,
                  0
                )
              })}
            </p>
          ) : null}
          {load.plan.upgrades.length > 0 ? (
            <Section title={t('playbooks.modelsUpdateSwaps')}>
              <Checks>
                {load.plan.upgrades.map((upgrade) => (
                  <Check
                    key={upgradeKey(upgrade.provider, upgrade.from)}
                    label={t(
                      upgrade.cliSays
                        ? 'playbooks.modelsUpdateSwapCli'
                        : 'playbooks.modelsUpdateSwap',
                      {
                        provider: providerLabel(s, upgrade.provider),
                        from: upgrade.from,
                        to: upgrade.to,
                        uses: upgrade.uses
                      }
                    )}
                    checked={chosen.has(upgradeKey(upgrade.provider, upgrade.from))}
                    onChange={(on) => toggle(upgradeKey(upgrade.provider, upgrade.from), on)}
                  />
                ))}
              </Checks>
            </Section>
          ) : null}
          {load.plan.additions.length > 0 ? (
            <Section title={t('playbooks.modelsUpdateAdditions')}>
              <Checks>
                {load.plan.additions.map((addition) => (
                  <Check
                    key={additionKey(addition.provider, addition.model)}
                    label={`${providerLabel(s, addition.provider)} · ${addition.model}${addition.description ? ` — ${addition.description}` : ''}`}
                    checked={chosen.has(additionKey(addition.provider, addition.model))}
                    onChange={(on) => toggle(additionKey(addition.provider, addition.model), on)}
                  />
                ))}
              </Checks>
              <Hint>{t('playbooks.modelsUpdateAdditionsHint')}</Hint>
            </Section>
          ) : null}
          {priceOnly.length > 0 ? (
            <Hint>{t('playbooks.modelsUpdatePriceOnly', { providers: priceOnly.join(', ') })}</Hint>
          ) : null}
          <div className={styles.actions}>
            <button
              type="button"
              className={`${styles.button} ${styles.primary}`}
              disabled={chosen.size === 0}
              onClick={apply}
            >
              {t('playbooks.modelsUpdateApply', { count: chosen.size })}
            </button>
            <button type="button" className={styles.button} onClick={() => void check()}>
              {t('playbooks.modelsUpdateRecheck')}
            </button>
          </div>
        </>
      ) : null}
    </>
  )
}
