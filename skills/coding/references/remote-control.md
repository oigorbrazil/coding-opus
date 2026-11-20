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
Todas as ferramentas exigem `Authorization: Bearer <chave>`. A página inicial é pública e não
mostra informações dos projetos antes de autenticar. O painel conserva a chave só na memória
da aba. Host e Origin são verificados, sem CORS aberto.

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

## Operação e limites

start roda em segundo plano, sem abrir ou focar janelas. É preciso iniciá-lo novamente depois
de reiniciar o computador. O comando stop para o servidor, enquanto as tarefas têm ciclo de
vida próprio. Interrompa-as individualmente antes se também quiser encerrar as execuções.
Nenhum agendamento de inicialização é instalado sem pedido do usuário.

O painel oferece conversas novas, acompanhamento, interrupção, retomada ociosa e troca de IA.
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
