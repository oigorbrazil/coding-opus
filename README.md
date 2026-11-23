# Coding Opus
![skill](https://img.shields.io/badge/skill-v37-1f6feb) ![license](https://img.shields.io/badge/license-MIT-555)

Uma skill global para Claude Code e Codex que faz a IA lembrar do que já foi decidido e gastar
menos para entregar o mesmo trabalho.

- **Memória.** Um *second brain* em `Documentos/second brain` com decisões, estudos e notas. A IA
  consulta antes de responder, em vez de redescobrir o que já sabe ou contradizer o que já foi
  decidido.
- **Orquestração.** Planeja, entrega partes limitadas do trabalho para o worker mais barato que dá
  conta (Codex, Claude Code, Antigravity, Kimi ou outro CLI), vigia a cota de cada conta e relata o
  que cada worker fez e custou.

## Como funciona

1. **Lembra antes de agir.** Em todo pedido substantivo, busca no second brain pelo frontmatter e
   lê no máximo cinco notas.
2. **Planeja com o que já foi decidido.** As decisões que valem para o projeto viram restrições do
   plano.
3. **Workers enxutos.** Cada worker recebe só a sua parte e as notas que valem para ela, nunca a
   conversa inteira, e não escreve no second brain.
4. **Registra o que aprendeu.** No fim, oferece salvar o resumo e o custo como nota. Mostra uma
   prévia e só grava com o seu ok.

## Instalação

Requer Python 3.9 ou mais novo.

**Como plugin do Claude Code** (inclui os hooks):

```sh
/plugin marketplace add oigorbrazil/coding-opus
/plugin install coding@coding
```

**Como skill** (Claude Code ou Codex):

```sh
npx skills add oigorbrazil/coding-opus --skill coding -g
```

Ou copie `skills/coding` para `~/.claude/skills/` (Claude Code) ou `~/.agents/skills/` (Codex).

### Primeiro uso

Não há comando de instalação. No primeiro pedido depois de instalar o plugin, ou no primeiro
`/coding` quando instalada como skill, a Coding Opus se configura e avisa em uma linha:

- cria `second brain` na sua pasta Documentos (a real, mesmo redirecionada pelo OneDrive), com
  pastas numeradas, `HOME.md` e templates. **Se a pasta já existe, ela é usada como está e nada é
  criado dentro dela**;
- grava as regras de consulta num bloco `coding-opus` de `~/.claude/CLAUDE.md` e de
  `~/.codex/AGENTS.md`, preservando o resto dos arquivos.

Nada é escrito nos seus projetos.

| Para | Faça |
| --- | --- |
| usar outro local para o second brain | defina `CODING_OPUS_BRAIN` antes do primeiro uso |
| não configurar sozinha | defina `CODING_OPUS_AUTO_SETUP=0` |
| refazer a configuração ou registrar o MCP `second-brain` (requer Node.js) | peça em texto, por exemplo "refaça a configuração da Coding Opus" |

## Editor de Playbooks

`/coding editor` abre o editor visual, que roda só no seu computador (`127.0.0.1`). No Windows ele
vira um aplicativo com atalho no menu Iniciar; no macOS e no Linux, um atalho que abre numa janela
própria do Chrome, Edge, Chromium ou Brave. Abas:

| Aba | O que faz |
| --- | --- |
| **Playbooks** | desenha e edita as estratégias de orquestração e o roteamento de tarefas, com prévia por provedor e simulação de cota |
| **Second Brain** | navega, busca e cria notas |
| **Memória** | conversas registradas entre IAs, com checkpoints e o prompt para continuar em outro provedor |
| **Automações** | pedidos que um agente executa sozinho no horário escolhido, com histórico de cada execução |
| **Controle remoto** | serviço para acompanhar e iniciar tarefas pelo celular, pela sua rede do Tailscale |

## Comandos

| Pedido | O que faz |
| --- | --- |
| `/coding <tarefa>` | orquestra a tarefa usando a memória |
| `/coding consultar <termos>` | busca notas e cita os caminhos |
| `/coding registrar` | grava a orquestração atual como nota, depois da prévia |
| `/coding onde` | mostra onde está o second brain |
| `/coding report` | o que a orquestração fez e custou |
| `/coding handoff <tarefa>` | inicia um worker numa branch e worktree próprias, sem esperar integração |
| `/coding editor` | abre o editor de Playbooks |
| `/coding setup` | confere provedores e política e guia a configuração da orquestração |
| `/coding doctor` | registra a cópia do runner e o Python da sessão |
| `/coding guide [fase]` | lista ou imprime a referência de uma fase |

No Codex, use `$coding`. Como plugin, o Claude Code mostra a skill como `/coding:coding`. Os
comandos curtos da orquestração (`status`, `usage`, `stop`, `save`, `max`, `passive`...) também
valem.

Cada worker abre por padrão um terminal que só acompanha o log dele. `/coding terminals on|off` muda
esse padrão, `run --terminals` e `--no-terminals` valem só para uma rodada, e
`CODING_OPUS_TERMINALS=0` desliga todos.

## Onde ficam os dados

| O quê | Onde |
| --- | --- |
| notas | `Documentos/second brain` (ou `CODING_OPUS_BRAIN`) |
| política, playbooks, preços, cota, histórico, automações e controle remoto | `%USERPROFILE%\.coding-opus` no Windows, fora do AppData, que o app Claude para Windows virtualiza; `~/.config/coding-opus` no macOS e no Linux |

## Estrutura

```text
skills/coding/
├── SKILL.md            ponto de entrada da skill (pt-BR)
├── references/         guias carregados só quando a tarefa precisa: memória, orquestração,
│                       playbooks, roteamento, provedores, controle remoto, operações...
├── scripts/
│   ├── brain.py        memória: where, install, find, record
│   ├── orchestrate.py  orquestração e editor
│   └── ...             hook, controle remoto, automações, memória de chats
├── assets/             editor, painel do celular e aplicativo do Windows
├── playbooks.yaml, prices.json, schemas/
└── licenses/           avisos de licença de terceiros
```

```sh
py scripts/brain.py where
py scripts/brain.py find exportacao csv --route 30-Projetos
py scripts/brain.py record --title "Auditoria final" --folder 30-Projetos --write
```

## Licença

[MIT](LICENSE). Partes de código de terceiros, também sob MIT, mantêm os avisos de copyright
originais em `skills/coding/licenses/`.
