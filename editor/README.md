# Coding Opus editor

Source of the page that `orchestrate.py editor` serves: the playbooks editor (flowchart, inspector,
usage, accounts), Second Brain, Memory and Reminders. The build folds everything into one
self-contained file, `skills/coding/assets/editor.html`, so the skill itself never needs Node.

The code came from Coding Agent 2, where it also ran inside the desktop app. It keeps that layout
so the history stays readable:

| Path | What it is |
| --- | --- |
| `config/playbooks-editor/` | The standalone page: entry (`main.tsx`), tabs, the local server client (`skill-server-api.ts`), stand-ins for desktop-only modules (`stubs.tsx`) and the build config |
| `src/renderer/src/components/settings/coding-opus/playbooks/` | The playbooks editor's React components |
| `src/renderer/src/lib/coding-opus-playbooks/` | Its state, flow layout, YAML, labels and translations (`messages.en.json`, `messages.pt.json`), with tests |
| `src/shared/` | Types shared with the server payloads |

Brand marks and `prices.json` come from `skills/coding/`, so the page and the skill never drift.

## Build and check

Node 20 or later. From this folder:

```text
npm install
npm test           # vitest
npm run typecheck  # tsc
npm run build      # writes out/editor.html and copies it to skills/coding/assets/editor.html
```

Set `CODING_OPUS_EDITOR_NO_COPY=1` to build into `out/` without touching the skill. After a build,
check the page with `orchestrate.py editor` and copy the skill to wherever it is installed.
