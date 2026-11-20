# Handoff: entregar uma tarefa em outra branch

Use quando o usuário disser “deixa o Codex fazendo isso em outra branch”, “entrega ao Claude”
ou pedir um handoff sem esperar resultado. Uma revisão que deve voltar ao lead é uma
orquestração normal, mesmo quando o lead tem subagentes próprios.

Com o Python e o runner fixados pelo `doctor`, execute:

```text
orchestrate.py handoff "Implemente a exportação e rode os testes" --provider codex --model MODELO --effort medium
```

`orchestrate.py` representa o mesmo caminho absoluto usado no `doctor`, com o mesmo Python e
`--session-id`. O provedor padrão é Codex; um provedor nomeado pelo usuário vence o padrão.
Passe um brief com objetivo, arquivos, restrições e verificações, como em `guide briefs`.
Não execute o exemplo literalmente com `MODELO`: selecione um modelo disponível.

O comando lança um worker em segundo plano numa worktree com branch própria e retorna JSON com
`folder`, `runDir`, `pid`, `provider`, `branch`, `worktree`, `result` e `diff`. Ele espera apenas a
preparação da worktree, não a conclusão da tarefa. Informe os caminhos ao usuário e encerre o
handoff: não chame `wait`, não integre e não faça merge. A orquestração atual do lead é preservada.

- `--branch nome`: cria uma branch nova; uma branch existente causa erro, sem reutilização silenciosa.
- `--cwd pasta`: checkout do projeto; aplicam-se as mesmas raízes permitidas do runner.
- `--seed-path caminho` (repetível): copia somente alterações locais explicitamente necessárias.
  Sem isso, a worktree parte do HEAD e não inclui mudanças ainda não commitadas do lead.
- `--timeout-seconds N`: limite do worker, padrão 1200 segundos.
- `--policy arquivo`, `--model` e `--effort`: mesmas escolhas explícitas de uma execução normal.
- Para um adaptador próprio: `--provider custom --command executavel --arg=argumento`.

O contrato do worker, a trava de recursão, a cota, os limites da política e as proteções de
execução continuam valendo. Handoff não autoriza cobrança por API, uso de cota baixa, commit,
push ou publicação. Use `--allow-low-quota` somente quando o usuário tiver autorizado isso.

Se o usuário pedir depois, `status <folder>`, `report <folder>` e `stop <folder>` continuam
disponíveis. A branch, a worktree e os resultados ficam para o usuário revisar; não os apague.
