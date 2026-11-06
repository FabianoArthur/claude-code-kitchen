# claude-code-kitchen

**Rode vários agentes do Claude Code em paralelo, cada um na sua tarefa, cada um terminando
num pull request — enquanto a sua sessão principal continua livre para conversar com você.**

[English](README.md) · [Documentação (em inglês)](docs/) · [Changelog](CHANGELOG.md)

O claude-code-kitchen é um conjunto de [skills do Claude Code](https://docs.claude.com/en/docs/claude-code/skills)
com alguns scripts Python pequenos, que só usam a biblioteca padrão. Ele transforma uma
sessão do Claude Code num **garçom**, que anota os seus pedidos, e um grupo de sessões tmux
em segundo plano numa **cozinha**, que prepara esses pedidos: um worktree e um PR por
pedido. Tudo com estado que não se perde, gates determinísticos e nenhum token gasto com
espera.

É um template, não uma plataforma: tudo o que é específico do projeto fica num pequeno
arquivo de adapter em cada repositório, e as regras ficam em Markdown puro, que você pode
ler e alterar.

---

## Equivalência de nomes: português → inglês

As skills e os comandos estão em inglês. Se você já usava a versão original do fluxo, em
português, a correspondência é esta:

| português | inglês | o que faz |
|---|---|---|
| garçom | waiter | a sessão principal; anota, despacha, serve; nunca cozinha |
| cozinha | kitchen | uma sessão tmux por pedido, no próprio worktree, até o PR |
| pedido | order | um doc de tarefa (uma unidade de trabalho) |
| comanda / manifesto | ticket / manifest | o registro durável do que está em andamento |
| servir | serve | avisar que o prato ficou pronto (PR), empacou (precisa de você) ou foi descartado (abortado) |
| `/plan` | `/plan` | brainstorm → docs de tarefa; `--problema` → `--problem` |
| `/dotask` | `/dotask` | uma tarefa → cozinha → vigiada até o PR abrir |
| `/orquestrar` | `/orchestrate` | várias tarefas → roteamento, colisões, manifesto, despacho |
| `/executar` | `/execute` | o motor de uma unidade (o que a cozinha roda) |
| `/qa` | `/qa` | rodada de QA com orçamento: fatos → matriz → gates → veredito |
| `/colher` | `/harvest` | depois do merge: limpa o que foi mergeado de fato |
| `/salvar` | `/save` | fim da sessão: grava estado, pendências e uma entrada de log no doc da tarefa (só local) |
| `/retomar` | `/resume` | começo da sessão: lê o doc, o manifesto e o git; diz estado · feito · pendente · UM próximo passo |
| `/sync-clickup` | `/sync` | passo explícito: empurra os docs salvos (`sync_pending`) para o tracker, com plano em dry-run antes |
| `seguranca-*` | `seguranca-*` | pacote opcional de 8 skills de segurança (só com `install.sh --with-security`); já escritas em português |
| `NUCLEO.md` | `CORE.md` | as regras que todas as skills seguem |
| `.claude/orquestrador.md` | `.claude/orchestrator.md` | o adapter do repositório |
| Raio de alcance | blast radius | os arquivos que o plano declara que vai tocar |
| regra do desvio | detour rule | bug encontrado no meio do caminho vira registro, não conserto |
| recurso escasso | scarce resource | o que duas tarefas não podem usar ao mesmo tempo |
| `.orq/`, `orq-<ID>` | `.kitchen/`, `kitchen-<ID>` | pasta de despacho e nome da sessão tmux |
| `--autoteste` | `--selftest` | teste embutido de cada script |

## O problema

Uma única sessão do Claude Code fazendo trabalho de verdade esbarra em três gargalos:

1. **Ela fica ocupada.** Enquanto implementa a tarefa A, você não consegue perguntar nada
   sobre a tarefa B.
2. **Ela esquece.** Um `/clear`, um crash ou um terminal fechado e lá se vai o que estava em
   andamento.
3. **Ela pergunta.** "Posso seguir com o plano?" transforma uma tarefa de 40 minutos num dia
   inteiro de pingue-pongue.

Rodar várias sessões à mão resolve o (1) e piora o (2): ninguém sabe qual terminal estava
fazendo o quê, em qual branch, nem se terminou.

## Como a cozinha funciona

```mermaid
flowchart LR
    voce([Você]) <-- "pedidos e respostas" --> garcom["Garçom<br/>(sessão principal do Claude Code)<br/>nunca cozinha"]
    garcom -- "doc de tarefa + linha do manifesto" --> comanda[("Manifesto<br/>(comanda durável)")]
    garcom -- "worktree + sessão tmux" --> k1["Cozinha: pedido A<br/>tmux kitchen-A<br/>worktree .worktrees/A"]
    garcom -- "worktree + sessão tmux" --> k2["Cozinha: pedido B<br/>tmux kitchen-B<br/>worktree .worktrees/B"]
    k1 -- "estado 🔄 → ✅ / ⏳ / 🚫" --> comanda
    k2 -- "estado 🔄 → ✅ / ⏳ / 🚫" --> comanda
    vigia["watch.py<br/>(0 tokens)"] -. lê .-> comanda
    vigia -. "acorda o garçom" .-> garcom
    k1 -- "PR" --> gh[(GitHub)]
    k2 -- "PR" --> gh
    voce -- "revisa e mergeia" --> gh
    voce -- "/harvest" --> garcom
```

- **Garçom** — a sua sessão principal. Anota o pedido, manda para a cozinha e volta na hora
  para você. Nunca mexe em código.
- **Cozinha** — uma sessão tmux em segundo plano por pedido (`kitchen-<id>`), com um Claude
  Code interativo rodando no próprio worktree e trabalhando até o PR abrir. Você pode entrar
  em qualquer cozinha e conversar com ela.
- **Comanda (manifesto)** — uma tabela em Markdown com uma linha por pedido e o estado de
  cada um (`⏸ na fila · 🔄 rodando · ⏳ aguarda humano · ✅ PR · 🚫 abortado`). Sobrevive a
  `/clear`, crash e terminal fechado; se a máquina reiniciar, é com ela que você confere o
  que ficou pela metade.
- **Servir** — o garçom avisa, com o link do PR, quando o prato fica pronto (PR aberto),
  quando empaca (precisa de você) ou quando é descartado (abortado).
- **Colher** — depois do merge, o `/harvest` remove os worktrees e as branches cujo merge
  ele consegue comprovar, e mais nada.

O que cada cozinha faz, nesta ordem: filtros de elegibilidade (a tarefa está aberta, é da
camada deste repositório, não está bloqueada e **ainda não foi feita**?) → plano com o
**raio de alcance** declarado → revisão independente do plano nas tarefas grandes (sem
parar para esperar ninguém) → TDD na lógica → gates determinísticos → commit → PR com um
relatório de gates honesto e uma seção `## Not verified` obrigatória.

## Início rápido

Você vai precisar de: [Claude Code](https://docs.claude.com/en/docs/claude-code), `git`,
`tmux`, `python3` (3.10+) e o [GitHub CLI](https://cli.github.com/) (`gh`) com login feito.

1. Clone: `git clone https://github.com/FabianoArthur/claude-code-kitchen.git`
2. Veja o que a instalação faria: `./claude-code-kitchen/install.sh --dry-run`
3. Instale (symlinks em `~/.claude/skills`). Se você já tem uma skill com o mesmo nome
   (`plan`, `qa`…), o instalador pergunta antes de mover a sua para `<nome>.bak-<data>`:
   `./claude-code-kitchen/install.sh`
4. No seu projeto, copie o adapter: `mkdir -p .claude && cp <kitchen>/examples/adapter.md .claude/orchestrator.md` e depois edite o arquivo.
5. Tire os arquivos da cozinha dos seus diffs: `printf '.kitchen/\n.worktrees/\n' >> .git/info/exclude`
6. Confira a máquina: `python3 ~/.claude/skills/orchestrate/scripts/doctor.py .`
7. Escreva uma tarefa: `/plan adicionar rate limit no endpoint de login` (ou copie `examples/task.md`).
8. Mande para a cozinha: `/dotask <slug>` — e siga conversando com o garçom; ele avisa
   quando o PR subir.
9. Depois do merge: `/harvest`.

Entre sessões: `/save` grava onde você parou no doc da tarefa (local, sem chamar tracker);
`/resume` lê de volta, junto com o manifesto e o git, e diz o único próximo passo.
`/sync` é o passo separado e explícito que empurra os docs salvos para o seu tracker.

Opcional: `./claude-code-kitchen/install.sh --with-security` instala também o
[pacote de segurança defensiva](skills/security/README.md) (8 skills, já em português).

Quer experimentar antes de mexer num repositório de verdade? Siga o
[`examples/demo-project`](examples/demo-project/README.md) (em inglês).

## Comandos

| comando | o que faz |
|---|---|
| `/plan` | brainstorm → docs de tarefa (What · Why · Acceptance criteria · Technical notes); `--problem` registra um bug sem parar ninguém |
| `/dotask <slug>` | uma tarefa → cozinha → vigiada até o PR abrir |
| `/orchestrate <ids>` | várias tarefas → roteamento, colisões, estimativa, manifesto, despacho (com limite) |
| `/execute <id>` | o motor de uma unidade (o que a sessão da cozinha roda) |
| `/qa <alvo>` | rodada de QA com orçamento: fatos → matriz de casos → gates → veredito com evidência |
| `/harvest` | depois do merge: limpa só o que comprovadamente foi mergeado |
| `/save [id]` | fim da sessão: grava estado, pendências e uma entrada de log no doc da tarefa — só local, marca `sync_pending` |
| `/resume [id]` | começo da sessão: lê o doc da tarefa, o manifesto e o git; diz estado · feito · pendente · **um** próximo passo; não começa a trabalhar |
| `/sync [id]` | empurra os docs salvos (`sync_pending: true`) para o tracker — plano em dry-run primeiro, aplica só depois do seu OK; ClickUp é o primeiro adaptador e o token nunca entra no repo |
| `seguranca-*` (8, opcionais) | o [pacote de segurança](skills/security/README.md): segredos, dependências, agentes, API, infra, front web, dados pessoais (LGPD), bots e webhooks. Só com `install.sh --with-security`; **escrito em português** (o README do pacote explica por quê) |

## Conceitos

| conceito | em uma linha | mais |
|---|---|---|
| **Adapter** | `.claude/orchestrator.md` em cada repositório: branch base, comandos de teste, camadas, padrões proibidos, limites. As skills nunca deixam valor de projeto hardcoded. | [docs/adapter.md](docs/adapter.md) |
| **Recurso escasso** | o que duas tarefas não podem usar ao mesmo tempo (porta do dev server, um dispositivo, os seus olhos). Tarefa que depende dele roda inline, com você presente, uma de cada vez. | [docs/architecture.md](docs/architecture.md) |
| **Raio de alcance** | todo plano lista, por camada, os arquivos que vai tocar; o diff real é conferido com essa lista antes do commit. | [docs/gates.md](docs/gates.md) |
| **Gates** | `forbidden_in_diff` (só linhas adicionadas, ignorando comentários) · revisão independente do plano · conferência do raio de alcance · relatório de gates honesto. | [docs/gates.md](docs/gates.md) |
| **Manifesto** | a comanda durável; cada cozinha escreve só a própria linha. | [docs/manifest.md](docs/manifest.md) |
| **Regra do desvio** | bug encontrado no meio da tarefa é registrado com `/plan --problem`, não consertado; a tarefa segue. | [docs/architecture.md](docs/architecture.md) |
| **Hibernação** | a cozinha que terminou grava o id da sessão em `.kitchen/done`; dá para encerrá-la para liberar RAM e retomá-la depois com `claude --resume`. | [docs/manifest.md](docs/manifest.md) |

## Segurança: `--dangerously-skip-permissions`

**Leia isto antes de mandar qualquer coisa para a cozinha.** A sessão da cozinha roda em
segundo plano, então não tem ninguém lá para aprovar prompt de permissão; qualquer prompt
desses a deixaria travada sem avisar. Por isso a cozinha inicia o Claude Code com
`--dangerously-skip-permissions`. Na prática, **o agente pode rodar qualquer comando que o
seu usuário do sistema possa rodar**, sem perguntar.

O que isso significa:

- Tudo o que o seu shell alcança, o agente alcança: seus arquivos, suas chaves SSH, suas
  credenciais de nuvem, o token do `gh`, toda variável de ambiente.
- O agente lê docs de tarefa, código, saída de comando e páginas web. **Qualquer uma dessas
  coisas pode trazer instruções** (prompt injection). Um doc de tarefa copiado de uma issue
  em que você não confia é superfície de ataque.
- Os campos de comando do adapter (`prepare_worktree`, `post_commit`, `status_push`, `gh`,
  `tests.allowed`) são executados pelo agente. Revise mudanças no `.claude/orchestrator.md`
  como código: um PR que mexe nele mexe no que as suas cozinhas executam.
- As skills são symlinks para o seu clone deste repositório, então um `git pull` muda as
  instruções que um agente sem supervisão segue. Atualize com calma: faça checkout de uma
  tag de release e leia o diff antes.

Mitigações, da mais forte para a mais fraca:

1. **Rode a cozinha dentro de um sandbox** — um dev container ou uma VM que tenha só o
   repositório e um token de escopo mínimo. É a única mitigação que segura um agente
   comprometido.
2. **Credenciais de menor privilégio.** Dê ao `gh` um token fine-grained limitado aos
   repositórios que você orquestra, sem escopo de admin. Deixe credencial de produção fora
   do ambiente que a cozinha herda.
3. **Proteção de branch no remoto.** Exija revisão de PR nas branches base e proíba
   force-push. As skills nunca fazem push na base nem force-push, mas quem garante isso de
   verdade é o remoto.
4. **Nenhum servidor MCP por padrão** — as cozinhas sobem com `--strict-mcp-config`, então um
   servidor MCP de terceiro só chega nelas se você o declarar para aquela unidade.
5. **Só entrada confiável.** Escreva os docs de tarefa você mesmo (ou com `/plan`); não cole
   texto de issue sem revisar. Com o backlog `github-issues` num repositório público, só
   despache issues abertas por colaboradores de confiança — veja
   [integrations.md](docs/integrations.md#github-issues).
6. **Revise todo PR.** A cozinha abre o PR; o merge é sempre seu.

Se nada disso for viável no seu ambiente, use `/execute --inline`: o mesmo fluxo, na
sessão principal, com os prompts de permissão de sempre.

## Widget na barra de menu (macOS)

O `menubar/kitchen.30s.py` é um plugin do [SwiftBar](https://github.com/swiftbar/SwiftBar)
que deixa uma chama e `▸2 !1` (rodando, aguardando você) na sua barra de menu: unidades por estado, um menu com o que cada
agente está fazendo agora (Abrir PR · Anexar · Copiar o comando de attach) e as
**divergências** — sessão viva sem linha no manifesto, linha `🔄` cuja sessão morreu sem
marcador `done` (um crash), sessão já encerrada que ainda segura RAM. Não gasta token: só lê
os manifestos e o `tmux`. Instalação e configuração: [docs/menubar.md](docs/menubar.md)
(em inglês).

### App nativo (macOS 26+)

O `macos/` gera o **Kitchen.app**, um app de barra de menu em SwiftUI com painel em Liquid
Glass: as mesmas unidades e divergências (ele roda o plugin com `--json`, então só existe um
parser) e mais **quanto do seu plano do Claude você já usou** na semana e na janela atual de
cinco horas. O `make -C macos install` compila sem abrir o Xcode. Detalhes, estados e
capturas de tela: [docs/macos-app.md](docs/macos-app.md) (em inglês).

**Ele lê o seu token do Claude Code.** Os números de uso vêm do mesmo endpoint que o próprio
Claude Code usa (`GET https://api.anthropic.com/api/oauth/usage`), que exige o token OAuth que
o Claude Code guarda no seu keychain de login. O app lê esse token pelo `/usr/bin/security`
(o macOS pede permissão uma vez) só para enviá-lo a esse único host. Ele nunca renova o token,
nunca o grava em lugar nenhum (disco, logs, preferências) e consulta no máximo a cada 5
minutos. Se o token expirou, ele pede para você abrir o Claude Code. Não quer isso? Desligue
*Show Claude usage* nas configurações do app e ele nunca toca no keychain; ou fique com o
plugin do SwiftBar, que não lê credencial nenhuma.

## Perguntas frequentes

**É um projeto oficial da Anthropic?** Não. É um template da comunidade feito em cima de
recursos públicos do Claude Code (skills, `--resume`, `--strict-mcp-config`).

**Por que tmux e não a ferramenta nativa de subagentes?** Uma sessão tmux sobrevive a
`/clear` e a terminal fechado, deixa você entrar nela e conversar, e aguenta horas rodando
sozinha. A ferramenta nativa de subagentes só entra em consultas curtas (os revisores do
plano e do pré-PR), quando o que você quer é só a resposta.

**Quantas cozinhas rodam ao mesmo tempo?** Quantas a sua máquina e o rate limit da sua conta
aguentarem. Defina `max_parallel` no adapter e o dispatcher mantém no máximo essa
quantidade rodando, subindo a próxima quando uma termina.

**Funciona sem GitHub?** O ciclo termina num PR, então essa etapa precisa do `gh`. Sem ele, a
cozinha para no push e entrega a URL de comparação do GitHub.

**Precisa de um gerenciador de tarefas (Jira, Linear, ClickUp…)?** Não. O backlog padrão é
uma pasta de docs de tarefa em Markdown. A integração com gerenciadores é opcional; veja
[docs/integrations.md](docs/integrations.md).

**Quanto custa uma cozinha?** Cada cozinha é uma sessão completa do Claude Code. O
`model_by_size` do adapter manda tarefa pequena para um modelo mais barato; o watcher e o
dispatcher não gastam nenhum token.

**A minha cozinha travou no primeiro comando de shell.** Veja
[docs/troubleshooting.md](docs/troubleshooting.md) — quase sempre é alguma integração do
terminal se metendo no shell não interativo.

**Funciona no Windows?** Não de forma nativa (por causa do tmux). No WSL2 deve funcionar,
mas ninguém testou ainda.

## Opcional: o kit de ferramentas

O kitchen só precisa dos requisitos acima. Isto é o que se usa com ele na prática: opcional,
feito por terceiros (o kitchen não instala nada disso). Detalhes, comandos de instalação e
links (em inglês): [docs/toolkit.md](docs/toolkit.md).

- **Economizar tokens e contexto** (N cozinhas dividem a cota de um plano, e cada token lido
  por uma sessão é relido em toda chamada seguinte): [RTK](https://www.rtk-ai.app/), um proxy
  de CLI que enxuga a saída dos comandos; [graphify](https://github.com/Graphify-Labs/graphify),
  um grafo de código consultável; [context7](https://github.com/upstash/context7), docs de
  bibliotecas sob demanda.
- **Plugins do Claude Code:** superpowers, code-review, code-simplifier, feature-dev,
  claude-md-management, skill-creator, frontend-design, github, discord, e, de terceiros,
  claude-council e ui-ux-pro-max.
- **Acompanhar o uso:** claude-monitor, mais o widget da barra de menu e o Kitchen.app deste
  repositório.
- **Gates:** pytest, ruff, shellcheck, gitleaks, markdownlint-cli2, lychee.
- **Base:** tmux, git worktree, `gh`, uv e `caffeinate`, para o Mac não dormir no meio de uma
  cozinha.

## Estrutura do repositório

```
skills/            as nove skills (a orchestrate guarda o CORE.md, as regras comuns)
  sync/scripts/         sync_tracker.py (só stdlib, testado offline)
  security/             pacote opcional: 8 skills `seguranca-*` com material executável
  orchestrate/scripts/  dispatcher.py · doctor.py · gate_diff.py · watch.py
  qa/scripts/           qa_preflight · qa_matrix · qa_budget · qa_report · qa_filter · qa_mutation · qa_watcher
menubar/           plugin do SwiftBar: a cozinha na barra de menu do macOS
macos/             app nativo de barra de menu (SwiftUI, Liquid Glass) com o uso do Claude
shell/             proteção opcional do zsh para shells que não são de humanos
examples/          adapter, adapter de QA, doc de tarefa (antes e depois do /save), projeto de demonstração
docs/              arquitetura, adapter, manifesto, gates, QA, integrações, toolkit, barra de menu, solução de problemas
tests/             testes com pytest (rodam também o --selftest de cada script)
install.sh         instalador por symlink (--dry-run, --uninstall, --yes, --with-security)
```

## Contribuindo

Issues e PRs são bem-vindos — veja o [CONTRIBUTING.md](CONTRIBUTING.md). Para reportar
uma vulnerabilidade: [SECURITY.md](SECURITY.md).

## Licença

[MIT](LICENSE) © 2026 Fabiano Arthur
