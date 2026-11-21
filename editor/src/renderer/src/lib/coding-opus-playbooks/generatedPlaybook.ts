import type { CodingOpusGeneratedPlaybook } from '../../../../shared/coding-opus'
import { attachDocs, duplicatePlaybook } from './flowView'
import { createPlaybooksState, type PlaybooksState, type PlaybookWorkflow } from './state'

export function generatedPlaybook(proposal: CodingOpusGeneratedPlaybook): PlaybookWorkflow {
  const preview = createPlaybooksState(proposal.text)
  const workflow = preview.workflows[`playbook:${proposal.id}`]
  const expectedIds =
    workflow?.kind === 'playbook' ? workflow.pb.phases.map((phase) => phase.id) : []
  attachDocs(preview)
  if (
    !workflow ||
    workflow.kind !== 'playbook' ||
    !workflow.pb.phases.length ||
    workflow.problems?.length ||
    expectedIds.some((id) => !workflow.pb.phases.some((phase) => phase.id === id))
  ) {
    throw new Error('invalid-result')
  }
  return workflow
}

export function appendGeneratedPlaybook(s: PlaybooksState, proposal: CodingOpusGeneratedPlaybook) {
  const workflow = generatedPlaybook(proposal)
  return duplicatePlaybook(s, workflow, workflow.pb.name)
}
