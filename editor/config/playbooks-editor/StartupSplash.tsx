import { useEffect, useRef, useState } from 'react'
import logo from '../../src/renderer/src/assets/coding-opus.png?inline'
import { localize } from './knowledge-model'
import { playStartupGlass } from './startup-glass'
import styles from './StartupSplash.module.css'

const REVEAL_MS = 1350
const FADE_MS = 180

export function StartupSplash({ ready, onComplete }: { ready: boolean; onComplete: () => void }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const [started] = useState(() => performance.now())
  const [reduced] = useState(
    () =>
      window.matchMedia('(prefers-reduced-motion: reduce), (prefers-reduced-transparency: reduce)')
        .matches
  )
  const [animated, setAnimated] = useState(false)
  const [closing, setClosing] = useState(false)

  useEffect(() => {
    if (!reduced && canvas.current) {
      return playStartupGlass(canvas.current, logo, setAnimated)
    }
    return undefined
  }, [reduced])

  useEffect(() => {
    if (!ready) {
      return
    }
    const delay = reduced ? 0 : Math.max(0, REVEAL_MS - (performance.now() - started))
    const fade = window.setTimeout(() => setClosing(true), delay)
    const finish = window.setTimeout(onComplete, delay + (reduced ? 0 : FADE_MS))
    return () => {
      window.clearTimeout(fade)
      window.clearTimeout(finish)
    }
  }, [ready, reduced, started, onComplete])

  return (
    <div className={styles.splash} role="status" data-startup-splash="" data-closing={closing}>
      <div className={styles.art} aria-hidden="true" data-animated={animated}>
        <div className={styles.fallback}>
          <span className={styles.mark} style={{ maskImage: `url("${logo}")` }} />
        </div>
        {!reduced ? <canvas ref={canvas} /> : null}
      </div>
      <span className={styles.message}>{localize('Abrindo o editor…', 'Opening the editor…')}</span>
    </div>
  )
}
