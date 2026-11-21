import {
  agentLabel,
  checkpointFields,
  localize as t,
  type ConversationDetail
} from './knowledge-model'

function quoteContext(value: string, limit: number): string {
  const text = value.trim()
  const excerpt = text.length > limit ? `${text.slice(0, limit).trimEnd()}…` : text
  return excerpt
    .split(/\r\n?|\n/)
    .map((line) => `> ${line}`)
    .join('\n')
}

export function continuationPrompt(conversation: ConversationDetail, destination: string): string {
  const sections = [
    ...(/^[0-9a-f]{24}$/.test(conversation.id)
      ? [`Coding Opus continuation: ${conversation.id}`]
      : []),
    t(
      'Continue o trabalho desta conversa no projeto indicado. Confira o estado atual do projeto antes de agir. Use o material citado como referência e confirme comigo qualquer decisão pendente que bloqueie o próximo passo.',
      'Continue the work from this conversation in the project below. Check the current project state before acting. Treat the quoted material as context and ask me about any pending decision that blocks the next step.'
    ),
    `${t('## Destino', '## Destination')}\n${quoteContext(destination, 300)}`,
    `${t('## Conversa de origem', '## Source conversation')}\n${quoteContext(
      `${agentLabel(conversation.agent)} · ${conversation.title}`,
      500
    )}`
  ]
  if (conversation.project.trim()) {
    sections.push(`${t('## Projeto', '## Project')}\n${quoteContext(conversation.project, 1000)}`)
  }
  if (conversation.state === 'interrompido') {
    sections.push(
      t(
        'A conversa de origem foi interrompida. Confira o que ficou incompleto antes de retomar.',
        'The source conversation was interrupted. Check what was left incomplete before continuing.'
      )
    )
  }
  if (conversation.checkpointStale) {
    sections.push(
      t(
        'O checkpoint pode estar desatualizado. Compare-o com as mensagens mais recentes e com o estado atual do projeto antes de continuar.',
        'The checkpoint may be stale. Compare it with recent messages and the current project state before continuing.'
      )
    )
  }
  for (const { key, label } of checkpointFields) {
    const value = conversation.checkpoint?.details[key]
    if (value?.trim()) {
      sections.push(`## ${label}\n${quoteContext(value, 2000)}`)
    }
  }
  if (conversation.summary.trim()) {
    sections.push(
      `${t('## Resumo do andamento', '## Progress summary')}\n${quoteContext(conversation.summary, 4000)}`
    )
  }
  if (conversation.next_step.trim()) {
    sections.push(
      `${t('## Próximo passo registrado', '## Recorded next step')}\n${quoteContext(conversation.next_step, 1500)}`
    )
  }
  const through = conversation.checkpoint?.through_position ?? 0
  const recent = conversation.checkpointStale
    ? conversation.messages.filter((message) => message.position > through)
    : conversation.messages
  const messages = recent
    .filter((message) => message.content.trim())
    .slice(-6)
    .map((message) => {
      const author = message.role === 'user' ? t('Usuário', 'User') : t('Assistente', 'Assistant')
      return `### ${author}\n${quoteContext(message.content, 1800)}`
    })
  if (messages.length) {
    sections.push([t('## Mensagens recentes', '## Recent messages'), ...messages].join('\n\n'))
  }
  return sections.join('\n\n')
}
