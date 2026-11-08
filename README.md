# Coding Opus

A skill do [Coding Agent](https://github.com/oigorbrazil/coding-agent) para Claude Code e Codex que melhora a performance e a economia da IA com dois pilares:

| Pilar | O que faz |
| --- | --- |
| **1. Memória** | Um *second brain* global em `Documentos/second brain`, com decisões, estudos e notas que a IA consulta antes de responder. Ela para de redescobrir o que já sabe e de contradizer o que já foi decidido. |
| **2. Orquestração inteligente** | Recriada a partir da [Alethe](https://github.com/Kc1t/alethe-orchestrate-skill): planeja, entrega unidades limitadas para os workers mais baratos e capazes (Codex, Claude Code, Antigravity, Kimi ou qualquer CLI), vigia a cota e relata o que cada worker fez e custou. |

## Como os pilares trabalham juntos

1. **Lembrar antes de agir.** Em todo pedido substantivo, a skill busca no second brain pelo frontmatter e lê no máximo cinco notas.
2. **Planejar com o que já foi decidido.** Numa orquestração, as decisões que valem para o projeto viram restrições do plano.
3. **Workers enxutos.** Cada worker recebe só os caminhos das notas que valem para a sua unidade, nunca a conversa inteira, e não escreve no second brain.
4. **Registrar o que aprendeu.** No fim, a skill oferece salvar o resumo e o relatório de custo como nota. Ela mostra uma prévia e só grava com o seu ok.

## Instalação

A Coding Opus é distribuída **dentro do [Coding Agent](https://github.com/oigorbrazil/coding-agent)**: o app instala a skill `coding` no Claude Code e no Codex pela aba *Preferências ▸ Skills* e mantém a versão em dia a cada release. Dentro do app, a skill planeja e lembra, e o app executa os workers no quadro de orquestração ([`references/modo-app.md`](skills/coding/references/modo-app.md)).

Requer Python 3.9+. Node.js só é necessário para o MCP opcional.

Este repositório é a fonte da skill: o Coding Agent a copia com `npm run skill:sync`. Para testar uma alteração sem o app, copie `skills/coding` para `~/.claude/skills/` (Claude Code) ou `~/.agents/skills/` (Codex).

Depois, em qualquer sessão:

```text
/coding install
```

A instalação:

- cria `second brain` dentro da sua pasta Documentos (a real, mesmo redirecionada pelo OneDrive), com pastas numeradas, `HOME.md` e templates. **Se a pasta já existe, ela é usada como está e nada é criado dentro dela**;
- grava as regras de consulta no bloco `coding-opus` de `~/.claude/CLAUDE.md` e de `~/.codex/AGENTS.md`, preservando o resto dos arquivos;
- registra opcionalmente o MCP `second-brain` em escopo de usuário.

Nada é escrito nos seus projetos. Para usar outro local, defina `CODING_OPUS_BRAIN` ou passe `--brain`.

Remova as skills `alethe`, `obsidian`, `obsidian-second-brain`, `alethe-second-brain` ou `coding-opus` separadas, se existirem: esta as substitui.

## Comandos

| Pedido | O que faz |
| --- | --- |
| `/coding install` | cria ou reaproveita o second brain e as regras globais |
| `/coding onde` | mostra onde está o second brain |
| `/coding consultar <termos>` | busca notas e cita os caminhos |
| `/coding <tarefa>` | orquestra a tarefa: memória, playbook e workers no quadro do Coding Agent |
| `/coding registrar` | grava uma decisão como nota, depois da prévia |
| `/coding playbooks` | mostra qual playbook vale para cada tipo de tarefa |

No Codex, use `$coding`. Editar playbooks, papéis e limites, ver cota e custo e guardar um lote
concluído são telas do Coding Agent, não comandos da skill.

## Estrutura

```text
skills/coding/
├── SKILL.md                 os dois pilares e como se unem (pt-BR)
├── references/
│   ├── memoria.md           pilar 1: instalação global, consulta e escrita
│   ├── obsidian-mcp.md      MCP second-brain em escopo de usuário
│   ├── orquestracao.md      pilar 2: a skill decide, o Coding Agent executa
│   ├── playbooks.md         campos do playbooks.yaml
│   └── briefs.md            como escrever briefs e revisar
├── scripts/
│   ├── brain.py             memória: where, install, find, record
│   └── playbook.py          estratégia: --pick, <nome>, --path, --check
├── playbooks.yaml, prices.json
└── licenses/                licenças MIT dos projetos de origem
```

```sh
py scripts/brain.py where
py scripts/brain.py find mindloom exportacao --route 30-Projetos
py scripts/brain.py record --title "Auditoria final" --folder 30-Projetos --summary "..." --write
py scripts/playbook.py --pick
py scripts/playbook.py plan-execute
```

Os playbooks do usuário ficam em `%APPDATA%\CodingOpus\coding-opus-playbooks.yaml` (Windows) ou
`~/.config/coding-opus/`, o mesmo arquivo que *Preferências ▸ Playbooks* edita. Se você usava a
Alethe, a primeira execução copia `%APPDATA%\Alethe` para lá, sem apagar a pasta antiga.

## Créditos e licença

Baseado em [Kc1t/alethe-orchestrate-skill](https://github.com/Kc1t/alethe-orchestrate-skill) (commit `ab81104`, MIT, © 2026 Kauã Miguel) e [n1systempc/obsidian-second-brain](https://github.com/n1systempc/obsidian-second-brain) (commit `4f43c49`, MIT, © 2026 Obsidian Second Brain contributors). As licenças originais estão em `skills/coding/licenses/`. O restante segue a licença [MIT](LICENSE).
