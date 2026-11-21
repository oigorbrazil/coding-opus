import { createRoot } from 'react-dom/client'
import '../../src/renderer/src/components/settings/coding-opus/playbooks/playbook-tokens.css'
import './standalone.css'
import { installSkillServerApi } from './skill-server-api'
import { CodingOpusEditorApp } from './CodingOpusEditorApp'

// The Coding Opus skill's own playbooks editor: Coding Agent 2's editor, talking to the skill's
// local server (orchestrate.py editor) instead of the desktop app's main process.
installSkillServerApi()
const root = document.getElementById('root')
if (root) {
  createRoot(root).render(<CodingOpusEditorApp />)
}
