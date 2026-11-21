// Official 9router favicon: https://github.com/decolua/9router/blob/master/public/favicon.svg
import router9Logo from './router9-official.svg'
import { ROUTES } from '@/lib/coding-opus-playbooks/catalog'
import { AgentIcon } from '@/lib/agent-catalog'
import { usePlaybooks } from './context'
import styles from './Playbooks.module.css'

export function ProviderMark({ id, size = 13 }: { id: string; size?: number }) {
  const { s } = usePlaybooks()
  if (ROUTES[id]) {
    return <img src={router9Logo} alt="" width={size} height={size} draggable={false} />
  }
  return <AgentIcon agent={s.catalog[id]?.agent ?? id} size={size} />
}

export function SvgProviderMark({
  id,
  x,
  y,
  size,
  faded
}: {
  id: string
  x: number
  y: number
  size: number
  faded?: boolean
}) {
  return (
    <foreignObject x={x} y={y} width={size} height={size} opacity={faded ? 0.45 : 1}>
      <div className={styles.svgMark}>
        <ProviderMark id={id} size={size} />
      </div>
    </foreignObject>
  )
}
