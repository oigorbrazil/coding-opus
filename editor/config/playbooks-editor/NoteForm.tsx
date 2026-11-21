import { useState, type FormEvent } from 'react'
import { localize as t, type LibraryGroup, type NoteDetail } from './knowledge-model'
import { libraryCall } from './skill-server-api'
import styles from './Knowledge.module.css'

export function NoteForm({
  groups,
  initialGroup,
  draft,
  onCancel,
  onSaved
}: {
  groups: LibraryGroup[]
  initialGroup: string
  draft?: { title: string; text: string; sourceConversation: string }
  onCancel: () => void
  onSaved: (note: NoteDetail, group: string) => void
}) {
  const [group, setGroup] = useState(
    groups.some((item) => item.id === initialGroup) ? initialGroup : (groups[0]?.id ?? '')
  )
  const [title, setTitle] = useState(draft?.title ?? '')
  const [type, setType] = useState(draft ? 'decisao' : 'nota')
  const [body, setBody] = useState(draft?.text ?? '')
  const [tags, setTags] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (saving) {
      return
    }
    setSaving(true)
    setError('')
    try {
      const note = await libraryCall<NoteDetail>({
        kind: 'notes',
        action: 'record',
        group,
        title,
        type,
        text: body,
        tags,
        sourceConversation: draft?.sourceConversation
      })
      onSaved(note, group)
    } catch (failure) {
      setError(String(failure))
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <h2>{draft ? t('Salvar como decisão', 'Save as decision') : t('Nova nota', 'New note')}</h2>
      <form className={styles.noteForm} onSubmit={(event) => void save(event)}>
        <label>
          {t('Título', 'Title')}
          <input
            required
            maxLength={180}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
        </label>
        <div className={styles.formRow}>
          <label>
            {t('Seção', 'Section')}
            <select required value={group} onChange={(event) => setGroup(event.target.value)}>
              {groups.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t('Tipo', 'Type')}
            <select
              value={type}
              onChange={(event) => setType(event.target.value)}
              disabled={Boolean(draft)}
            >
              <option value="nota">{t('Nota', 'Note')}</option>
              <option value="decisao">{t('Decisão', 'Decision')}</option>
              <option value="estudo">{t('Estudo', 'Study')}</option>
              <option value="ideia">{t('Ideia', 'Idea')}</option>
              <option value="meeting">{t('Reunião', 'Meeting')}</option>
            </select>
          </label>
        </div>
        <label>
          {t('Tags (separadas por vírgulas)', 'Tags (comma-separated)')}
          <input maxLength={400} value={tags} onChange={(event) => setTags(event.target.value)} />
        </label>
        <label>
          {t('Conteúdo', 'Content')}
          <textarea
            required
            rows={9}
            maxLength={40000}
            value={body}
            onChange={(event) => setBody(event.target.value)}
          />
        </label>
        {error ? (
          <p className={styles.error} role="alert">
            {error}
          </p>
        ) : null}
        <div className={styles.actions}>
          <button
            type="submit"
            className={styles.primary}
            disabled={
              saving ||
              !group ||
              !title.trim() ||
              !body.trim() ||
              body.trim() === draft?.text.trim()
            }
          >
            {saving ? t('Salvando…', 'Saving…') : t('Salvar nota', 'Save note')}
          </button>
          <button type="button" className={styles.button} onClick={onCancel} disabled={saving}>
            {t('Cancelar', 'Cancel')}
          </button>
        </div>
      </form>
    </>
  )
}
