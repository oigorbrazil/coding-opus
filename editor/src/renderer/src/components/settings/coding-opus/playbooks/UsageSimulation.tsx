import { useState } from 'react'
import { PLAN_DAYS, RESET_HOURS } from '@/lib/coding-opus-playbooks/catalog'
import {
  hoursText,
  spareWhy,
  usagePresetLabel,
  windowLabel
} from '@/lib/coding-opus-playbooks/labels'
import {
  expiresOf,
  longWindow,
  presetUsage,
  quotaNow,
  resetOf,
  spareOf,
  usageKey,
  usageOf,
  usagePresetIds,
  windowsOf
} from '@/lib/coding-opus-playbooks/state'
import { usePlaybooks } from './context'
import { Select } from './fields'
import styles from './Playbooks.module.css'

const withCurrent = (list: number[], value: number | null) =>
  value === null || list.includes(value) ? list : [...list, value].sort((a, b) => a - b)

function Range({
  label,
  value,
  hot,
  onCommit
}: {
  label: string
  value: number
  hot: number
  onCommit: (value: number) => void
}) {
  const [draft, setDraft] = useState(value)
  return (
    <label className={styles.usageLine}>
      <span>{label}</span>
      <input
        type="range"
        min={0}
        max={100}
        step={1}
        value={draft}
        onChange={(event) => setDraft(Number(event.target.value))}
        onPointerUp={() => onCommit(draft)}
        onKeyUp={() => onCommit(draft)}
      />
      <span className={draft >= hot ? `${styles.usageValue} ${styles.hot}` : styles.usageValue}>
        {draft}%
      </span>
    </label>
  )
}

export function UsageSimulation({
  provider,
  onChange
}: {
  provider: string
  onChange: () => void
}) {
  const { s, t } = usePlaybooks()
  const q = quotaNow(s)
  const spare = spareOf(s, provider)
  const set = (key: string, value: number | null) => {
    s.usageMode = 'simulation'
    s.usage[provider][key] = value
    onChange()
  }
  return (
    <details className={styles.usageSimulation}>
      <summary>{t('playbooks.usageSimulate')}</summary>
      <p className={styles.foot}>{t('playbooks.usageSimulationHint')}</p>
      <div className={styles.presets}>
        {usagePresetIds(s)
          .filter((key) => key !== 'now')
          .map((key) => (
            <button
              key={key}
              type="button"
              aria-pressed={s.usageMode === 'simulation' && key === usageKey(s)}
              onClick={() => {
                s.usageMode = 'simulation'
                s.usage = presetUsage(s, key)
                onChange()
              }}
            >
              {usagePresetLabel(t, key)}
            </button>
          ))}
      </div>
      {windowsOf(s, provider).map((w) => (
        <Range
          key={`${provider}:${w.key}:${usageOf(s, provider, w.key)}`}
          label={windowLabel(t, w)}
          value={usageOf(s, provider, w.key)}
          hot={q.criticalThreshold}
          onCommit={(value) => set(w.key, value)}
        />
      ))}
      {longWindow(s, provider) ? (
        <>
          <div className={styles.usageMeta}>
            <span>{t('playbooks.resets')}</span>
            <Select
              value={String(resetOf(s, provider) ?? 168)}
              ariaLabel={t('playbooks.resets')}
              options={withCurrent(RESET_HOURS, resetOf(s, provider) ?? 168).map((hours) => ({
                value: String(hours),
                label: t('playbooks.inTime', { time: hoursText(t, hours) })
              }))}
              onChange={(value) => set('reset', Number(value))}
            />
          </div>
          <div className={styles.usageMeta}>
            <span>{t('playbooks.plan')}</span>
            <Select
              value={expiresOf(s, provider) === null ? 'renews' : String(expiresOf(s, provider))}
              ariaLabel={t('playbooks.plan')}
              options={[
                { value: 'renews', label: t('playbooks.renews') },
                ...withCurrent(PLAN_DAYS, expiresOf(s, provider)).map((days) => ({
                  value: String(days),
                  label: t('playbooks.endsIn', { time: hoursText(t, days * 24) })
                }))
              ]}
              onChange={(value) => set('expires', value === 'renews' ? null : Number(value))}
            />
          </div>
        </>
      ) : null}
      {spare ? (
        <p className={styles.why}>
          {t('playbooks.spareLine', { why: spareWhy(t, spare), percent: spare.left })}
        </p>
      ) : null}
      <p className={styles.foot}>
        {t('playbooks.usageFoot', {
          low: q.criticalThreshold,
          stop: q.stopAt,
          spare: q.spareMinLeft,
          hours: q.spareWithinHours
        })}
      </p>
    </details>
  )
}
