import { ArrowLeft, ArrowRight } from 'lucide-react'
import { localize as t } from './knowledge-model'
import styles from './Knowledge.module.css'

export function KnowledgePager({
  page,
  pages,
  busy,
  onPage
}: {
  page: number
  pages: number
  busy: boolean
  onPage: (page: number) => void
}) {
  if (pages <= 1) {
    return null
  }

  return (
    <div className={styles.pager}>
      <button
        className={styles.iconButton}
        type="button"
        disabled={busy || page === 0}
        aria-label={t('Página anterior', 'Previous page')}
        onClick={() => onPage(page - 1)}
      >
        <ArrowLeft size={15} />
      </button>
      <span>
        {page + 1} / {pages}
      </span>
      <button
        className={styles.iconButton}
        type="button"
        disabled={busy || page + 1 >= pages}
        aria-label={t('Próxima página', 'Next page')}
        onClick={() => onPage(page + 1)}
      >
        <ArrowRight size={15} />
      </button>
    </div>
  )
}
