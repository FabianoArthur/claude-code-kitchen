# Fontes — seguranca-agentes

Acesso de todas: **2026-09-23**. Claude Code local na data: **2.1.281**.

## Claude Code (docs oficiais)

| fonte | o que sustenta |
|---|---|
| [Permissions](https://code.claude.com/docs/en/permissions) | ordem deny → ask → allow; "if a tool is denied at any level, no other level can allow it"; precedência dos níveis; listas combinadas; `disableBypassPermissionsMode`/`disableAutoMode`; prompt/CLAUDE.md não impõem nada |
| [Permissions — Bash rule limits](https://code.claude.com/docs/en/permissions#bash-rule-limits) | regra de Bash "isn't a security boundary around the program"; `/bin/rm`, `bash -c`, `git -C . push` escapam; runners (`npx`, `docker exec`) não são removidos antes do casamento; deny de Read não pega subprocesso Python/Node |
| [Permission modes](https://code.claude.com/docs/en/permission-modes) | modos default/acceptEdits/plan/auto/dontAsk/bypassPermissions; `--dangerously-skip-permissions` = bypass; "offers no protection against prompt injection"; não roda como root; o classificador não vê resultados de ferramenta; lista padrão de bloqueios do auto mode (inclui lançar agente autônomo com skip-permissions) |
| [Hooks](https://code.claude.com/docs/en/hooks) | PreToolUse exit 2 bloqueia, antes das regras; JSON `allow` não desfaz o exit 2; outros exit codes não bloqueiam; `permissionDecision` allow/deny/ask/defer; hooks rodam com as credenciais do usuário |
| [Sandboxing](https://code.claude.com/docs/en/sandboxing) | Seatbelt/bubblewrap; leitura do disco inteiro por padrão (`~/.ssh`, `~/.aws`); rede sem domínio liberado; `allowUnsandboxedCommands`, `failIfUnavailable`, `denyRead`, `credentials`; docker.sock = host; `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB`; "not a complete isolation boundary" |
| [Devcontainer](https://code.claude.com/docs/en/devcontainer) | container não impede exfiltrar o que está dentro, credenciais do Claude incluídas; só repo confiável |
| [MCP](https://code.claude.com/docs/en/mcp) | servidor que busca conteúdo externo traz risco de prompt injection; `allowedMcpServers`/`deniedMcpServers` |
| [Security](https://code.claude.com/docs/en/security) | Anthropic "does not security-audit or manage any MCP server"; verificação de confiança desligada com `-p`; WebFetch em contexto separado; boas práticas contra injection |
| [Settings](https://code.claude.com/docs/en/settings) | arquivos e níveis de settings |

## OWASP e pesquisa

| fonte | o que sustenta |
|---|---|
| [OWASP Top 10 for LLM Applications 2025](https://genai.owasp.org/llm-top-10/) | LLM01 Prompt Injection … LLM06 Excessive Agency … LLM10 Unbounded Consumption |
| [OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/) | publicado em 09/12/2025. Os códigos ASI01–ASI10 (Agent Goal Hijack, Tool Misuse, Identity & Privilege Abuse, Agentic Supply Chain, Unexpected Code Execution, Memory & Context Poisoning, Insecure Inter-Agent Communication, Cascading Failures, Human-Agent Trust Exploitation, Rogue Agents) vieram de fontes secundárias concordantes ([auth0](https://auth0.com/blog/owasp-top-10-agentic-applications-lessons/), [modulos](https://docs.modulos.ai/frameworks/owasp-top-10-agentic)); a skill não cita os códigos por isso |
| [Simon Willison — The lethal trifecta](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/) | dado privado + conteúdo não confiável + comunicação externa |
| [Invariant Labs — GitHub MCP](https://invariantlabs.ai/blog/mcp-github-vulnerability) | issue pública → vazamento de repo privado via PR; problema de arquitetura; um repo por sessão |

## Repositórios de referência (lidos, nada copiado)

| repo | ideia aproveitada |
|---|---|
| [GitArika/agents-orchestrator](https://github.com/GitArika/agents-orchestrator) (`docs/seguranca.md`, `hooks/cerca.sh`) | cerca como PreToolUse com exit 2; bateria bloqueia/passa; "uma cerca com defeito é pior do que nenhuma"; relato do deny via `--settings` que perdeu na 2.1.252 |
| [ClipboardHealth/groundcrew](https://github.com/ClipboardHealth/groundcrew) (`docs/runners.md`, `docs/credentials.md`, `docs/setup-hooks.md`) | worktree por tarefa; sandbox por padrão; egress por allowlist; segredo de build apagado antes do agente; ambiente filtrado |

O `references/cerca/cerca.py` foi escrito do zero para este pacote (Python, regex + parse de argumentos do push), testado com `teste.sh` (19 casos, 0 falhas). A contraprova `cerca_ingenua.py` (regra por prefixo) deixa passar 13 dos 14 casos de bloqueio. A primeira versão da cerca deixava passar 5 formas de push (`+main`, `+HEAD:x`, `-uf`, `refs/heads/main`, `HEAD:refs/heads/main`), apontadas pelo review independente; foram para a bateria antes da correção (vermelho → verde).

## Medições locais (2026-09-23, só leitura)

- Num `~/.claude/settings.json` de desenvolvimento: `skipDangerousModePermissionPrompt: true`; nenhum `disable*Mode`; sem `sandbox`; 3 hooks PreToolUse (um deles reescrevia comandos).
- Ambiente de uma sessão tmux de agente: variáveis de chave de outros provedores de IA presentes (só os nomes foram lidos): é o que `seguranca-agentes` manda filtrar.

## Não confirmado

- Se o exit 2 do PreToolUse bloqueia também em `bypassPermissions`: a doc diz "before permission rules are evaluated", mas não traz frase explícita sobre o bypass. Teste sugerido numa sessão descartável, dentro de container.
- O conflito entre a doc (deny vence em qualquer nível) e o relato do agents-orchestrator (deny via `--settings` perdeu na 2.1.252) não foi reproduzido aqui: reproduzir exigiria alterar o `~/.claude` real, o que a pesquisa não fez.
