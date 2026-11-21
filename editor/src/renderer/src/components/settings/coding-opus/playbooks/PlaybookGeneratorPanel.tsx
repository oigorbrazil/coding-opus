import { Loader2, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { CodingOpusGeneratedPlaybook } from '../../../../../../shared/coding-opus'
import { generatedPlaybook } from '@/lib/coding-opus-playbooks/generatedPlaybook'
import type { MessageKey } from '@/lib/coding-opus-playbooks/i18n'
import { condText } from '@/lib/coding-opus-playbooks/labels'
import {
  finalize,
  phaseBase,
  providerLabel,
  toYaml,
  workflowNow
} from '@/lib/coding-opus-playbooks/state'
import { usePlaybooks } from './context'
import { Field, Select } from './fields'
import styles from './Playbooks.module.css'

export const GENERATOR_ID = 'generate-playbook'

const ERRORS: Record<string, MessageKey> = {
  'invalid-instructions': 'playbooks.generateInvalidInstructions',
  'invalid-playbooks': 'playbooks.generateInvalidPlaybooks',
  'invalid-result': 'playbooks.generateInvalidResult',
  'quota-exhausted': 'playbooks.generateQuotaExhausted',
  'sign-in-required': 'playbooks.generateSignIn',
  'subscription-required': 'playbooks.generateSubscription',
  'cli-update-required': 'playbooks.generateUpdateCli',
  'invalid-provider': 'playbooks.generateNoProvider',
  busy: 'playbooks.generateBusy',
  timeout: 'playbooks.generateTimeout'
}

export function PlaybookGeneratorPanel({
  open,
  onClose,
  onApply
}: {
  open: boolean
  onClose: () => void
  onApply: (proposal: CodingOpusGeneratedPlaybook) => void
}) {
  const { s, t } = usePlaybooks()
  const [instructions, setInstructions] = useState('')
  const [provider, setProvider] = useState<'codex' | 'claude'>('codex')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [proposal, setProposal] = useState<CodingOpusGeneratedPlaybook | null>(null)
  const request = useRef(0)
  useEffect(
    () => () => {
      request.current += 1
    },
    []
  )
  const providers = s.providers.filter((id) => id === 'codex' || id === 'claude')
  const selectedProvider = providers.includes(provider) ? provider : (providers[0] ?? '')
  const preview = proposal ? generatedPlaybook(proposal) : null
  const current = workflowNow(s)

  const generate = async () => {
    const generatePlaybook = window.api?.codingOpus?.generatePlaybook
    if (!generatePlaybook || !['codex', 'claude'].includes(selectedProvider)) {
      setError('invalid-provider')
      return
    }
    if (selectedProvider !== 'codex' && selectedProvider !== 'claude') {
      return
    }
    const id = ++request.current
    setBusy(true)
    setError(null)
    setProposal(null)
    try {
      const result = await generatePlaybook({
        provider: selectedProvider,
        instructions: instructions.trim(),
        text: toYaml(s)
      })
      if (id !== request.current) {
        return
      }
      if (!result.ok) {
        setError(result.error)
      } else {
        try {
          generatedPlaybook(result.value)
          setProposal(result.value)
        } catch {
          setError('invalid-result')
        }
      }
    } catch {
      if (id === request.current) {
        setError('generation-failed')
      }
    } finally {
      if (id === request.current) {
        setBusy(false)
      }
    }
  }

  if (!open) {
    return null
  }
  return (
    <aside
      className={styles.panel}
      aria-label={t('playbooks.generateTitle')}
      onKeyDown={(event) => {
        if (event.key === 'Escape') {
          event.stopPropagation()
          onClose()
        }
      }}
    >
      <div className={styles.panelHead}>
        <span className={styles.sideLabel}>{t('playbooks.generateTitle')}</span>
        <button
          type="button"
          className={styles.iconButton}
          aria-label={t('common.close')}
          onClick={onClose}
        >
          <X size={14} />
        </button>
      </div>
      <div className={styles.panelBody}>
        <p className={styles.hint}>{t('playbooks.generateIntro')}</p>
        <label className={styles.field}>
          <span>{t('playbooks.generateInstructions')}</span>
          <textarea
            className={`${styles.input} ${styles.generationInstructions}`}
            value={instructions}
            maxLength={8000}
            placeholder={t('playbooks.generatePlaceholder')}
            readOnly={busy}
            onChange={(event) => {
              setInstructions(event.target.value)
              setProposal(null)
              setError(null)
            }}
          />
        </label>
        <div className={styles.actions}>
          <button
            type="button"
            className={styles.button}
            disabled={busy || current.kind !== 'playbook'}
            onClick={() => {
              if (current.kind !== 'playbook') {
                return
              }
              setInstructions(
                [
                  current.pb.name,
                  current.pb.goal,
                  current.pb.pickWhen,
                  current.pb.saves,
                  current.pb.avoidWhen
                ]
                  .filter(Boolean)
                  .join('\n\n')
              )
              setProposal(null)
              setError(null)
            }}
          >
            {t('playbooks.generateUseCurrent')}
          </button>
        </div>
        <Field label={t('playbooks.generateProvider')}>
          <Select
            value={selectedProvider}
            options={providers.map((id) => ({ value: id, label: providerLabel(s, id) }))}
            ariaLabel={t('playbooks.generateProvider')}
            disabled={busy || !providers.length}
            onChange={(value) => {
              if (value !== 'codex' && value !== 'claude') {
                return
              }
              setProvider(value)
              setProposal(null)
              setError(null)
            }}
          />
        </Field>
        <p className={styles.foot}>{t('playbooks.generateCost')}</p>
        {!providers.length ? (
          <p className={styles.hint} role="alert">
            {t('playbooks.generateNoProvider')}
          </p>
        ) : null}
        <div className={styles.actions}>
          <button
            type="button"
            className={`${styles.button} ${styles.primary}`}
            disabled={busy || instructions.trim().length < 10 || !providers.length}
            onClick={() => void generate()}
          >
            {busy ? (
              <Loader2 size={12} className="animate-spin motion-reduce:animate-none" />
            ) : null}
            {t(busy ? 'playbooks.generating' : 'playbooks.generateTitle')}
          </button>
        </div>
        {busy ? (
          <p className={styles.hint} role="status">
            {t('playbooks.generateProgress')}
          </p>
        ) : null}
        {error ? (
          <p className={styles.hint} role="alert">
            {t(ERRORS[error] ?? 'playbooks.generateFailed')}
          </p>
        ) : null}
        {preview ? (
          <section className={styles.section} aria-label={t('playbooks.generatePreview')}>
            <h3 className={styles.panelTitle}>{preview.pb.name}</h3>
            <p className={styles.hint}>{preview.pb.goal}</p>
            <ol className={styles.generationSteps}>
              {preview.pb.phases.map((phase) => {
                const use = finalize(s, phaseBase(s, phase))
                return (
                  <li key={phase.id}>
                    <b>
                      {phase.role ?? phase.id}
                      {(phase.workers ?? 1) > 1 ? ` ×${phase.workers}` : ''}
                    </b>
                    <p className={styles.hint}>{phase.does}</p>
                    <p className={styles.foot}>
                      {t('playbooks.generatePlannedModel', {
                        model: `${providerLabel(s, use.provider)} · ${use.model ?? use.tier}`
                      })}
                    </p>
                    {phase.readOnly ? (
                      <p className={styles.foot}>{t('playbooks.generateReadOnly')}</p>
                    ) : null}
                    {phase.if ? (
                      <p className={styles.foot}>
                        {t('playbooks.generateCondition', { condition: condText(s, t, phase.if) })}
                      </p>
                    ) : null}
                    {phase.gate ? <p className={styles.foot}>{phase.gate}</p> : null}
                  </li>
                )
              })}
            </ol>
            <p className={styles.hint}>{t('playbooks.generateApplyHint')}</p>
            <button
              type="button"
              className={`${styles.button} ${styles.primary}`}
              onClick={() => {
                if (!proposal) {
                  return
                }
                try {
                  onApply(proposal)
                  setProposal(null)
                } catch {
                  setError('invalid-result')
                }
              }}
            >
              {t('playbooks.generateApply')}
            </button>
          </section>
        ) : null}
      </div>
    </aside>
  )
}
