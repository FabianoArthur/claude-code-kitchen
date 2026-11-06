---
name: seguranca-agentes
description: Use quando for configurar, despachar ou revisar agentes de IA com autonomia — Claude Code em sessão tmux, --dangerously-skip-permissions, auto mode, hooks, regras allow/deny, sandbox, MCP de terceiro, agente que lê issue/página/resultado de ferramenta. Sintomas de que precisa: agente rodando em bypass fora de container, regra deny que "não pegou" um comando, hook que ninguém testou, classificador do auto mode bloqueando "Create Unsafe Agents", credencial ao alcance do agente, MCP instalado sem ler, agente com dado privado + conteúdo externo + canal de saída na mesma sessão.
---

# Segurança de agentes — Claude Code e afins

## Visão geral

Um agente autônomo tem três coisas perigosas: **ferramentas** (shell, git, rede), **credenciais herdadas** (as suas) e **entrada não confiável** (issue, página web, resultado de ferramenta, arquivo de dependência). Prompt injection não se resolve no prompt. Resolve-se tirando do alcance do agente o que ele não pode estragar. Referências: OWASP Top 10 for LLM Applications 2025 (LLM01 Prompt Injection, LLM02 Sensitive Information Disclosure, LLM06 Excessive Agency) e OWASP Top 10 for Agentic Applications 2026 (publicado em 09/12/2025).

**Modelo mental: a trifeta letal** (Simon Willison, 16/06/2025). Dado privado + conteúdo não confiável + capacidade de mandar dado para fora, **na mesma sessão**, é exfiltração esperando acontecer. O caso GitHub MCP da Invariant Labs (26/05/2025) é exatamente isso: uma issue pública instruiu o agente a copiar dados de repo privado para um PR público. A mitigação deles: **um repo por sessão**. Antes de despachar, pergunte quais dos três esta sessão tem e corte pelo menos um.

## Camadas, da mais fraca para a mais forte

| camada | o que garante | limite |
|---|---|---|
| prompt / `CLAUDE.md` / `.kitchen/prompt.md` | orienta o modelo | **nada é imposto**: "shape what Claude tries to do, but they don't change what Claude Code allows" |
| regras `permissions.allow/ask/deny` | o Claude Code recusa a chamada que casa | regra de Bash **não é fronteira de segurança**: `Bash(rm *)` não pega `/bin/rm` nem `bash -c 'rm …'`; `Bash(git push *)` não pega `git -C . push` |
| hook `PreToolUse` | vê o comando inteiro; **exit 2 bloqueia antes das regras**, e nem um JSON `allow` desfaz | roda com as suas credenciais; **qualquer outro exit code deixa passar** (hook quebrado = porta aberta) |
| sandbox (`/sandbox`, Seatbelt/bubblewrap) | limite do SO para escrita e rede do Bash | **lê o disco inteiro por padrão** (inclusive `~/.ssh`, `~/.aws`); só cobre Bash |
| container/VM descartável, sem credencial montada | contém código hostil | o que estiver dentro pode sair (credenciais do Claude incluídas) |

Regra: **quanto mais autonomia, mais para baixo na tabela.** `--dangerously-skip-permissions` só na última linha: a doc diz que `bypassPermissions` "offers no protection against prompt injection" e manda usá-lo só em container/VM.

## Checagens (comando → resultado esperado)

### 1. Modo de permissão e bypass

```bash
jq '{defaultMode: .permissions.defaultMode,
     bypassDesligado: .permissions.disableBypassPermissionsMode,
     autoDesligado: .permissions.disableAutoMode,
     pulaAvisoBypass: .skipDangerousModePermissionPrompt}' ~/.claude/settings.json
grep -rn -- '--dangerously-skip-permissions\|bypassPermissions' ~/.claude/skills/*/SKILL.md ~/.claude/skills/*/*.md 2>/dev/null
```

**Esperado:** bypass só aparece em despacho que roda dentro de sandbox/container. Máquina onde agente nenhum deve usar bypass: `"disableBypassPermissionsMode": "disable"` (a doc recomenda pôr em managed settings, onde não dá para sobrescrever). `skipDangerousModePermissionPrompt: true` tira o último aviso: confira se foi decisão consciente. (Conferido em 2026-09-23 num Mac de desenvolvimento: estava `true`.)

**Incidente real:** o despacho da cozinha usava `--dangerously-skip-permissions` e o **classificador do auto mode bloqueou** com "Create Unsafe Agents". Isso é o sistema funcionando: a lista padrão do auto mode bloqueia "lançar loop de agente autônomo com `--dangerously-skip-permissions`". A saída **não** é contornar o classificador. É dar ao agente uma cerca (hook) e/ou um sandbox, e aí rodar em modo que o classificador aceite (auto, ou default com allowlist). Epic `rig-v2`: `rig-cerca`, `rig-sandbox-safehouse`.

### 2. Regras deny: o que elas pegam de verdade

```bash
jq -r '.permissions.deny[]?' ~/.claude/settings.json .claude/settings.json .claude/settings.local.json 2>/dev/null
```

**Esperado:** deny por nome de ferramenta inteira (`"WebFetch"`, `"mcp__x"`) ou por caminho (`Read(./.env)`, `Read(./secrets/**)`), onde a regra é robusta. Deny de Bash por argumento (`Bash(git push origin main)`) **não é garantia**: vale só como primeira linha.

Precedência, segundo a doc atual: avaliação deny → ask → allow; "if a tool is denied at any level, no other level can allow it"; níveis managed > `--settings`/CLI > `.claude/settings.local.json` > `.claude/settings.json` > `~/.claude/settings.json`; as listas **se somam** entre níveis.

> **Conflito conhecido:** o `GitArika/agents-orchestrator` relata que, no Claude Code 2.1.252 (02/09/2026), um deny `Bash(git push:*)` passado por `--settings` **perdeu** para um allow idêntico do usuário. Isso contradiz a doc. Pode ter sido bug da versão ou efeito da sintaxe legada `:*`. Não dependa de nenhuma das duas leituras: **o controle que importa vai no hook**, que é determinístico.

Deny de `Read`/`Edit` cobre as ferramentas nativas e `cat`/`sed`/redirecionamento, **não** um `python -c` ou `node -e` que abre o arquivo: para isso, sandbox (`sandbox.filesystem.denyRead`).

### 3. Hook `PreToolUse`: a cerca

Exemplo testado em `references/cerca/` (`cerca.py` + `teste.sh` + `casos.tsv`). Barra `gh pr merge`, `sudo`, `curl … | sh`, leitura de `~/.ssh`/`~/.aws`/`.claude.json`/arquivo de token do tracker, push forçado e push direto em base.

```bash
cd skills/security/seguranca-agentes/references/cerca && ./teste.sh ./cerca.py
```

**Esperado:** `falhas: 0`. A bateria tem 19 casos: 14 que **precisam bloquear**, em formas espertas (`cd .. && git push origin main`, `git -C repo push --force`, `bash -c "gh pr merge 12"`, `env X=1 git push origin release`, `git push origin +main`, `git push -uf …`, `HEAD:refs/heads/main`), e 5 que **precisam passar** (push da própria branch, `gh pr create --base main`). Contraprova reproduzível: `./teste.sh ./cerca_ingenua.py` (a regra por prefixo) deixa passar **13 dos 14** casos de bloqueio. A primeira versão da própria cerca deixava passar `+main`, `-uf` e `refs/heads/main`; o review pegou, e esses casos entraram na bateria.

Regras de ouro do hook:

- **Falhe fechado.** JSON ilegível, campo faltando, exceção → `exit 2`. O exemplo faz isso; a prova é `echo nao-json | ./cerca.py; echo $?` → `2`.
- **Teste antes de confiar:** "uma cerca com defeito é pior do que nenhuma" (a primeira cerca do agents-orchestrator ficava inerte por erro de parse).
- Registre o hash do hook no despacho (`shasum -a 256 cerca.py`) para notar adulteração.
- Carregue só onde precisa: `claude --settings <json-da-cozinha>` soma hooks sem afetar as sessões normais.

Limites honestos do exemplo: não resolve variável (`B=main; git push origin $B`), alias do git, nem script que chama `git` por dentro; `git push` **sem argumentos** estando na base passa (o hook não sabe a branch atual); e `gh api -X PUT repos/…/pulls/N/merge` contorna a regra de `gh pr merge`. Ele reduz o estrago de um agente que erra; **não contém agente hostil**. Para isso, sandbox ou container.

Hooks de terceiros também são superfície: um `PreToolUse` que reescreve comandos (ex.: um hook de compressão de saída, como o `rtk hook claude`) vê e altera **todo** comando. Liste o que está instalado:

```bash
jq -c '.hooks | to_entries[] | {evento: .key, cmds: [.value[].hooks[].command | .[0:80]]}' ~/.claude/settings.json
```

**Esperado:** cada comando listado tem dono conhecido e foi lido; nenhum hook de origem desconhecida em `PreToolUse`/`UserPromptSubmit`/`PostToolUse` (os eventos que veem ou alteram tudo). Hooks de plugin não aparecem aqui: veja `claude plugin details <plugin>`.

### 4. Sandbox

```bash
jq '.sandbox' ~/.claude/settings.json .claude/settings.json 2>/dev/null
```

**Esperado para sessão autônoma:** `"enabled": true`, `"allowUnsandboxedCommands": false` (senão o modelo pode refazer o comando com `dangerouslyDisableSandbox`), `"failIfUnavailable": true` (senão, sem sandbox, só aparece um aviso e roda assim mesmo), `filesystem.denyRead` cobrindo `~/.ssh`, `~/.aws`, `~/.config/gh`, o arquivo de token do tracker (ex.: `~/.config/claude-code-kitchen/clickup_token`), e rede com `allowedDomains` curto. Evite domínio amplo (`github.com` inteiro abre caminho para exfiltração) e **nunca** libere `/var/run/docker.sock` (equivale a dar o host). Limpar credenciais do ambiente dos subprocessos: `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB`.

Referência de desenho: `ClipboardHealth/groundcrew` (um worktree por tarefa, sandbox por padrão, egress por allowlist via proxy, segredo de build num arquivo `0600` apagado **antes** de o agente subir, ambiente filtrado por allowlist).

### 5. Credenciais ao alcance do agente

```bash
env | cut -d= -f1 | grep -iE 'token|key|secret|pass|auth' | sort    # nomes, nunca valores
jq -r '.env | keys[]?' ~/.claude/settings.json
find ~/.config ~/.claude -maxdepth 2 -type f -perm -004 \( -name '*.env' -o -name '*token*' -o -name '*secret*' \) 2>/dev/null   # segredo legível por todos?
```

**Esperado:** o agente não herda token que a tarefa não usa; o `find` volta vazio. Medido em 2026-09-23: a sessão tmux desta própria tarefa herdou `GEMINI_API_KEY`, `GROK_API_KEY` e `XAI_API_KEY` (chaves de provedores do tipo que o `claude-council` consome), que ela não usa. É o caso típico: a chave entra no ambiente do shell uma vez e passa a valer para todo agente. Segredo em arquivo `600` (`stat -f '%Lp %N' <arquivo>` → `600`). Chave em `settings.json > env` vai para **todo** processo que o Claude Code sobe. Incidente real: `GH_TOKEN` inválido no ambiente sombreando o keyring (ver `seguranca-segredos`).

### 6. MCP de terceiro

```bash
jq '.mcpServers | keys' ~/.claude.json .mcp.json 2>/dev/null
claude mcp list
```

**Esperado:** cada servidor tem dono conhecido e foi lido antes (checklist em `seguranca-dependencias` → "Plugin/MCP/skill de terceiro"). A Anthropic "does not security-audit or manage any MCP server". Servidor que busca conteúdo externo traz prompt injection junto. Com `-p` (não interativo), a verificação de confiança é **desligada**. Em máquina gerenciada: `allowedMcpServers`/`deniedMcpServers`.

### 7. Entrada não confiável

- Não canalize conteúdo externo direto para o agente (`gh issue view 12 | claude -p …` é a trifeta montada).
- Agente que lê issue/PR de repo público não tem token com escrita em repo privado.
- Resultado de ferramenta é dado, não instrução. No auto mode, o classificador **não vê** resultados de ferramenta (de propósito) e uma sonda no servidor os examina à parte. Mesmo assim, conte com o hook e o sandbox, não com o classificador.

## Anti-padrões → correção

| anti-padrão | correção |
|---|---|
| "está no prompt que ele não pode dar push na main" | hook `PreToolUse` com exit 2 + bateria de teste |
| `Bash(git push origin main)` no deny como única trava | hook que analisa o comando inteiro |
| hook que dá `exit 1` em erro | falha fechada: `exit 2` |
| `--dangerously-skip-permissions` no Mac, fora de container | sandbox estrito ou container sem credencial; ou auto mode |
| contornar o bloqueio do classificador | tratar o bloqueio como alarme e pôr cerca/sandbox |
| MCP instalado pelo nome bonito | checklist de terceiro antes; um MCP por necessidade |
| um agente com repo privado + issues públicas + PR | um repo por sessão; cortar uma perna da trifeta |
| token em `settings.json > env` | só na sessão que precisa, via arquivo `600` lido na hora |

## Checklist antes de despachar um agente autônomo

- [ ] Qual perna da trifeta está cortada? (dado privado / conteúdo externo / saída)
- [ ] Modo: default/auto com allowlist, **ou** bypass só dentro de sandbox/container
- [ ] Cerca carregada (`--settings`), bateria verde, hash registrado
- [ ] Sandbox: `allowUnsandboxedCommands: false`, `failIfUnavailable: true`, `denyRead` nas credenciais
- [ ] Ambiente sem token desnecessário
- [ ] MCPs da sessão lidos e necessários
- [ ] Worktree próprio; nada fora dele sem pedido

Fontes com data de acesso: `references/fontes.md`.
