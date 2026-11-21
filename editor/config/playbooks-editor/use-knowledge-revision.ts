import { useEffect, useState } from 'react'
import type { LibraryKind } from './knowledge-model'

export function useKnowledgeRevision(kind: LibraryKind) {
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    if (kind !== 'memory') {
      return
    }
    let frame = 0
    const refreshOnReturn = () => {
      if (document.visibilityState === 'visible') {
        window.cancelAnimationFrame(frame)
        frame = window.requestAnimationFrame(() => setRevision((current) => current + 1))
      }
    }
    window.addEventListener('focus', refreshOnReturn)
    document.addEventListener('visibilitychange', refreshOnReturn)
    return () => {
      window.removeEventListener('focus', refreshOnReturn)
      document.removeEventListener('visibilitychange', refreshOnReturn)
      window.cancelAnimationFrame(frame)
    }
  }, [kind])

  return [revision, setRevision] as const
}
