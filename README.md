# Coding Opus

Uma skill global para Claude Code e Codex que melhora a performance e a economia da IA com dois pilares:

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

Requer Python 3.9+. Node.js só é necessário para o MCP opcional.

**Como skill global:** copie `skills/coding` para `~/.claude/skills/` (Claude Code) ou `~/.agents/skills/` (Codex).

```sh
npx skills add oigorbrazil/coding-opus --skill coding -g
```

**Como plugin** (Claude Code, ativa também o hook do modo passivo):

```sh
/plugin marketplace add oigorbrazil/coding-opus
/plugin install coding@coding
```

Depois, em qualquer sessão:

```text
/coding install
```

A instalação:

- cria `second brain` dentro da sua pasta Documentos (a real, mesmo redirecionada pelo OneDrive), com pastas numeradas, `HOME.md` e templates. **Se a pasta já existe, ela é usada como está e nada é criado dentro dela**;
- grava as regras de consulta no bloco `coding-opus` de `~/.claude/CLAUDE.md` e de `~/.codex/AGENTS.md`, preservando o resto dos arquivos;
- registra opcionalmente o MCP `second-brain` em escopo de usuário.

Nada é escrito nos seus projetos. Para usar outro local, defina `CODING_OPUS_BRAIN` ou passe `--brain`.

Instale só uma forma e remova as skills `alethe`, `obsidian`, `obsidian-second-brain`, `alethe-second-brain` ou `coding-opus` separadas, se existirem: esta as substitui.

## Comandos

| Pedido | O que faz |
| --- | --- |
| `/coding install` | cria ou reaproveita o second brain e as regras globais |
| `/coding onde` | mostra onde está o second brain |
| `/coding consultar <termos>` | busca notas e cita os caminhos |
| `/coding <tarefa>` | orquestra a tarefa usando a memória |
| `/coding registrar` | grava a orquestração atual como nota, depois da prévia |
| `/coding report` | o que a orquestração fez e custou |
| `/coding setup` | checa provedores e a política da orquestração e faz o onboarding |

No Codex, use `$coding`. Como plugin, o Claude Code mostra a skill com o prefixo do plugin (`/coding:coding`).

Os outros comandos curtos da orquestração (`status`, `usage`, `stop`, `mode on`, `save`, `max`...) continuam valendo.

## Estrutura

```text
skills/coding/
├── SKILL.md                 os dois pilares e como se unem (pt-BR)
├── references/
│   ├── memoria.md           pilar 1: instalação global, consulta e escrita
│   ├── obsidian-mcp.md      MCP second-brain em escopo de usuário
│   ├── orquestracao.md      pilar 2: orquestração inteligente (pt-BR)
│   └── ...                  referências de playbooks, rotas, provedores e operações
├── scripts/
│   ├── brain.py             memória: where, install, find, record
│   ├── orchestrate.py       orquestração
│   ├── hook.py, diagram.py
├── playbooks.yaml, prices.json, schemas/, assets/
└── licenses/                licenças MIT dos projetos de origem
```

```sh
py scripts/brain.py where
py scripts/brain.py install --dry-run
py scripts/brain.py find mindloom exportacao --route 30-Projetos
py scripts/brain.py record --title "Auditoria final" --folder 30-Projetos --write
```

## Estado da orquestração

Política, playbooks, preços, cota e histórico ficam em `%APPDATA%\CodingOpus` (Windows) ou `~/.config/coding-opus`. Se você usava a Alethe, a primeira execução copia `%APPDATA%\Alethe` para lá e renomeia os arquivos `alethe-*` para `coding-opus-*`, sem apagar a pasta antiga.

## Créditos e licença

Baseado em [Kc1t/alethe-orchestrate-skill](https://github.com/Kc1t/alethe-orchestrate-skill) (commit `ab81104`, MIT, © 2026 Kauã Miguel) e [n1systempc/obsidian-second-brain](https://github.com/n1systempc/obsidian-second-brain) (commit `4f43c49`, MIT, © 2026 Obsidian Second Brain contributors). As licenças originais estão em `skills/coding/licenses/`. O restante segue a licença [MIT](LICENSE).
