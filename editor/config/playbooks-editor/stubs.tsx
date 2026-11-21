// Light stand-ins for desktop-only modules the shared playbooks editor imports.
import claudeLogo from '../../../skills/coding/assets/brands/claude-official.png.b64?raw'
import openAiLogo from '../../../skills/coding/assets/brands/openai-official-white.svg?raw'
import antigravityLogo from '../../../skills/coding/assets/brands/antigravity-official.svg?raw'

/** `@/i18n/i18n`: the page follows the browser language (Portuguese or English). */
export const i18n = {
  language: navigator.language.toLowerCase().startsWith('pt') ? 'pt' : 'en'
}

/** `@/i18n/i18n` getIntlLocale: dates follow the page language. */
export function getIntlLocale(): string {
  return i18n.language === 'pt' ? 'pt-BR' : 'en-US'
}

/** `@/i18n/use-ui-language-revision`: the page language never changes while it is open. */
export function useUiLanguageRevision(): number {
  return 0
}

/** `sonner`: save notices go to the page title briefly. */
export const toast = (title: string, _options?: { description?: string }): void => {
  const previous = document.title
  document.title = title
  window.setTimeout(() => {
    document.title = previous
  }, 2500)
}

const svgSource = (svg: string): string => `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`
const LOGOS: Record<string, string> = {
  claude: `data:image/png;base64,${claudeLogo.trim()}`,
  codex: svgSource(openAiLogo),
  agy: svgSource(antigravityLogo),
  antigravity: svgSource(antigravityLogo)
}

/** `@/lib/agent-catalog`: brand marks the skill already ships, or the agent's initial. */
export function AgentIcon({
  agent,
  size = 14
}: {
  agent: string | null | undefined
  size?: number
}): React.JSX.Element {
  const src = agent ? LOGOS[agent] : undefined
  if (src) {
    return (
      <img
        src={src}
        data-brand={agent}
        width={size}
        height={size}
        alt=""
        aria-hidden
        style={{ borderRadius: 2 }}
      />
    )
  }
  return (
    <span
      aria-hidden
      style={{
        display: 'inline-flex',
        width: size,
        height: size,
        alignItems: 'center',
        justifyContent: 'center',
        borderRadius: 3,
        background: 'var(--muted)',
        color: 'var(--foreground)',
        fontSize: Math.max(8, size - 5),
        fontWeight: 600
      }}
    >
      {(agent ?? '?').slice(0, 1).toUpperCase()}
    </span>
  )
}
