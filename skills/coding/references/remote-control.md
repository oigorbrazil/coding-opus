# Controle remoto da Coding Opus

Use quando o usuário quiser iniciar ou acompanhar Claude Code/Codex pelo celular ou por
outro computador. A Coding Opus fornece um servidor MCP Streamable HTTP e um painel web.
Ele usa os CLIs já instalados e seus logins, permissões, limites e cotas. Python 3.9+, stdlib.

## Preparação no computador que executa os agentes

Resolva uma vez o Python e esta cópia da skill. Execute doctor para conferir os provedores
sem iniciar inferência. Cota velha/desconhecida ou cobrança por API exige a autorização prevista
na orquestração antes de iniciar tarefas reais. Teste servidor e painel com tarefas simuladas.

```text
python scripts/remote_control.py setup --project meu-projeto=/pasta/do/projeto --origin https://nome-do-computador.exemplo
python scripts/remote_control.py start
python scripts/remote_control.py status
python scripts/remote_control.py stop
```

O diretório padrão é remote-control ao lado da política da Coding Opus. `--home <pasta>` antes
do subcomando seleciona outro diretório. setup gera config.json com uma chave de acesso de alta
entropia e projetos autorizados. Não imprima a chave em logs, chat, URL, QR público ou arquivos
do second brain. O usuário pode copiá-la do config.json no próprio computador. Preserve a chave
em reconfigurações. `--allow-write` habilita tarefas que alteram os projetos. Cada pedido ainda
precisa selecionar o modo write. O painel inicia em somente leitura.

O servidor escuta somente em 127.0.0.1, padrão porta 8769. O painel fica em /, o MCP em /mcp.
Todas as ferramentas exigem `Authorization: Bearer <chave>`: a chave mestra do config.json ou
uma chave de aparelho. A página inicial é pública e não mostra informações dos projetos antes de
autenticar. Host e Origin são verificados, sem CORS aberto.

### Pareamento e aparelhos

O usuário não precisa copiar a chave mestra. Na aba **Controle remoto** do editor da Coding Opus
(`orchestrate.py editor`), **Abrir painel neste computador** liga o serviço, gera um código de
pareamento de computador e abre `http://127.0.0.1:<porta>/#pair=<código>`. O painel troca o
código por uma chave própria do aparelho, guardada no navegador, e remove o código da URL.

- Códigos têm 8 caracteres, valem 5 minutos e só uma vez. Depois de 20 códigos errados em 10
  minutos o pareamento bloqueia por 10 minutos (HTTP 429).
- Chaves de aparelho ficam só como hash sha256 em `devices.json`. Tipos: `pc` (pode gerar QR
  para celulares, listar e revogar aparelhos) e `phone` (só usa o painel e o MCP).
- No painel do computador, **Gerar QR para o celular** mostra um QR de `<panel_url>#pair=<código>`.
  Revogar um computador revoga os celulares pareados por ele. Uma chave revogada recebe 401 e o
  painel pede um novo QR.
- Rotas: `POST /pair` (sem autenticação, `{code, name}`), `POST /pair/new` (`{kind}`),
  `GET /devices` e `POST /devices/revoke` (`{id}`), as três últimas com chave mestra ou `pc`.

A mesma aba lista os projetos liberados, avisa pasta inexistente, adiciona pasta pelo caminho
completo, remove projetos, liga a escrita e liga/desliga o serviço. Mudanças reiniciam o serviço
se ele estiver ligado. Faça essas mudanças só a pedido do usuário.

A aba também mostra:

- **Versão do serviço:** `/health` informa um resumo do código em execução (`code`). Se o serviço
  ligado for de uma versão anterior, a aba avisa e oferece **Reiniciar**.
- **Endereço para o celular:** **Detectar pelo Tailscale** lê `tailscale status --json` e
  `tailscale serve status --json` (só leitura), mostra o nome do computador, se o Serve já publica
  a porta do painel e o endereço sugerido. Se não publicar, mostra o comando `tailscale serve`
  para o usuário rodar, com uma rota que não sobrescreve outra já publicada. **Salvar** grava
  `panel_url` e inclui a origem HTTPS em `origins`.
- **Aparelhos conectados:** lista e revoga aparelhos; com o serviço ligado, a revogação passa
  pelo servidor, que guarda os aparelhos em memória.

## Acesso pelo celular e outro computador

Prefira uma rede privada já disponível, como Tailscale. No dispositivo remoto, conecte-se à
mesma rede e abra a URL HTTPS do computador. Para uma configuração sem serviço anterior,
Tailscale Serve pode publicar o servidor local em uma rota própria

```text
tailscale serve --bg --set-path /coding-opus http://127.0.0.1:8769
```

Isso resulta em `https://nome-do-computador.sua-rede.ts.net/coding-opus/` para o painel e
`.../coding-opus/mcp` para o MCP. Antes de alterar Serve, leia seu status e preserve as rotas
existentes. Adicione o origin HTTPS exato ao setup. Se o tailnet exigir habilitar Serve na
administração, informe o link de aprovação ao usuário e mantenha o servidor pronto localmente.
Não abra portas do roteador, habilite Funnel público, altere ACLs ou publique na internet sem pedido.

No painel do computador, **Gerar QR para o celular** mostra os passos e um QR de uso único que
já conecta o celular, sem digitar chave. Se houver um único origin HTTPS do
Tailscale, o endereço padrão termina em `/coding-opus/`. Para outra rota ou mais de um origin,
passe a URL HTTPS completa, sem query, fragmento ou chave, em `setup --panel-url <url>` e inclua
sua origem em `--origin`.

O celular precisa de Tailscale conectado, ou de outra conexão privada configurada. Um conector
MCP que rode na nuvem do ChatGPT/Claude não acessa automaticamente a rede privada do usuário.
Este servidor usa Bearer e não implementa OAuth para conectores de nuvem. O painel no navegador
funciona diretamente pela rede privada. O computador precisa estar ligado e disponível.

## Ferramentas MCP

- projects lista os projetos cadastrados no computador.
- start_agent recebe project, agent (claude/codex), prompt e request_id. mode é read-only por
  padrão. model é opcional e deve existir no provedor escolhido.
- list_sessions e get_task consultam sessões, resultados e saída limitada. A sessão é retomável
  quando o provedor deixou seu identificador nativo.
- send_message retoma uma sessão ociosa. Enquanto houver tarefa em andamento no projeto,
  o servidor recusa sobreposição. Espere terminar ou use stop_task e consulte o resultado.
- stop_task solicita interrupção pelo runner, verificando identidades de processos.
- continue_with inicia outra IA com um contexto limitado da sessão anterior e o pedido atual.

Use um request_id novo por pedido e reutilize-o em retries de rede. Repetir o mesmo ID com
outro conteúdo é recusado. A conexão HTTP não fica bloqueada esperando inferência. Consulte
get_task enquanto a tarefa roda. A perda de conexão não cancela o pedido.

Os registros ficam em jobs.sqlite3 e tasks/ no diretório do serviço. O servidor reutiliza
orchestrate.py e não altera a orquestração atual do lead, a política de trust ou o MCP dos workers.
Os workers não delegam nem iniciam outros workers. O servidor grava pedidos e resultados na
função memory quando habilitada e mantém o último checkpoint para continuação entre IAs.
Não interprete status succeeded como prova de testes ou de conclusão de todos os objetivos.

## Automações

Modeladas nas automações do Orca. Uma automação roda um pedido com um agente (`claude` ou
`codex`) em uma ou mais pastas, no horário: `hourly`, `daily`, `weekdays`, `weekly` ou cron de
5 campos (hora local). As pastas são da automação, independentes dos projetos liberados no
controle remoto: no editor, **Escolher pasta** abre a janela de pastas do sistema (Explorer,
Finder, zenity ou kdialog; se não abrir, cola-se o caminho). O serviço do controle remoto é só o
anfitrião: confere a agenda a cada 15 s enquanto está ligado e inicia cada execução pelo mesmo
executor das tarefas do painel. Dados em `automations.sqlite3`, ao lado do config.json.

- **Pastas fora da lista do controle remoto:** a tarefa roda, mas o celular e o painel não a veem
  nem a continuam; o resultado aparece no histórico da automação. O modo de escrita é o da
  automação, não o interruptor de escrita do controle remoto. Automações antigas, salvas pelo nome
  do projeto, continuam funcionando e passam a guardar o caminho na próxima edição.
- **Pré-checagem:** comando de uma linha rodado na pasta antes das execuções agendadas. Código 0
  segue; outro código, erro ou tempo esgotado (padrão 60 s, até 600) registra `skipped_precheck`.
  **Rodar agora** ignora a pré-checagem.
- **Execução perdida:** se o serviço estava desligado no horário, roda uma vez ao voltar dentro
  da tolerância (padrão 60 min, até 1440); fora dela registra `skipped_missed`.
- **Indisponível:** pasta inexistente ou outra tarefa em andamento na pasta registram
  `skipped_unavailable`; erro ao iniciar registra `dispatch_failed`.
- **Várias pastas:** cada horário inicia uma tarefa por pasta, com uma linha própria no
  histórico; uma pasta ocupada ou indisponível pula só ela.
- **Opções:** modo só leitura ou escrita, modelo, playbook, worktree nova por execução (só
  escrita) ou continuar a sessão da execução anterior (só com uma pasta; cai para sessão nova se
  ela sumiu).
- **Histórico:** `queued`, `dispatching`, depois o estado da tarefa (`running`, `needs_input`,
  `completed`, `failed`, `stopped`) ou o motivo do pulo. Guarda as 200 últimas por automação;
  excluir a automação apaga o histórico.

```text
python scripts/automations.py create --name "Revisão" --prompt "Revise as mudanças" --agent codex --project C:/projetos/app --project C:/projetos/site --trigger weekdays --time 09:00
python scripts/automations.py list
python scripts/automations.py run <id>        # na fila; o serviço inicia em até 15 s
python scripts/automations.py runs --id <id>
```

O celular não cria nem altera automações. Crie, altere ou rode automações apenas a pedido do
usuário.

## Operação e limites

start roda em segundo plano, sem abrir ou focar janelas. É preciso iniciá-lo novamente depois
de reiniciar o computador. O comando stop para o servidor, enquanto as tarefas têm ciclo de
vida próprio. Interrompa-as individualmente antes se também quiser encerrar as execuções.
Nenhum agendamento de inicialização é instalado sem pedido do usuário.

O painel abre na lista de tarefas, com checagens pendentes e tarefas em execução antes das
recentes. **Nova tarefa** abre o formulário. Toque numa tarefa para acompanhar o status, ver a
resposta ou continuar a conversa. A saída técnica fica em uma seção recolhível.
O topo mostra a conexão e o horário da última leitura. Na reconexão, o painel atualiza a
tarefa aberta e preserva o pedido que estiver sendo escrito.
O painel exibe tarefas de projetos autorizados no servidor. Quando uma execução aguarda checagem, a tela
mostra a pergunta e permite registrar o resultado. Tarefas de escrita respeitam `allow_write` e
podem começar numa worktree separada quando o projeto usa Git.

Com a aba aberta e conectada, o painel avisa sobre conclusões e checagens pendentes, inclusive
em outra sessão. **Ativar notificações** permite mostrar esses avisos também pelo navegador quando
o dispositivo oferece suporte. O navegador precisa autorizar as notificações. Os avisos não
funcionam como push com o painel fechado.

A versão atual executa turnos limitados pelo runner. Ela não encaminha mensagens de steering
para um turno em execução nem abre a janela gráfica do aplicativo remoto. Codex app-server pode
ser uma evolução para sessões interativas contínuas. Não use codex mcp-server, removido nas
versões atuais do Codex, como base desta função.

Protocolos e ferramentas dos provedores

- [Transporte MCP](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
- [Claude programático](https://code.claude.com/docs/en/headless)
- [Codex App Server](https://learn.chatgpt.com/docs/app-server)
