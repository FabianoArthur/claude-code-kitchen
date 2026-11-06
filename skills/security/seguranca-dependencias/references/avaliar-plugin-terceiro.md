# Avaliar plugin, servidor MCP ou skill de terceiro — antes de instalar

Nasceu de um caso real: um plugin enorme (hooks, daemon, dezenas de dependências) que alguém quis instalar "para testar". Instalar um plugin do Claude Code é rodar código de terceiro **com os seus privilégios**, com acesso às suas credenciais e vendo cada prompt. O custo de ler antes é de minutos; o custo de desinstalar depois é não saber o que ele já fez.

Tudo aqui é **leitura**: clone o repo para um diretório temporário e inspecione. Nada é executado.

```bash
T=$(mktemp -d) && git clone --depth 1 <url-do-repo> "$T/p" && cd "$T/p"
```

## 1. Origem e nome

- Marketplace oficial/comunidade (revisado e fixado por SHA) > repo de org conhecida > conta anônima recente.
- Typosquatting: o nome bate letra por letra com o que você procurou? Compare org, estrelas, idade, data do último commit.
- `gh repo view <org>/<repo> --json createdAt,pushedAt,stargazerCount,licenseInfo,isArchived`
- Licença compatível com o uso (AGPL num plugin que você vai modificar e distribuir é problema).

## 2. Inventário: o que ele instala

```bash
claude plugin details <plugin>                  # se já estiver num marketplace adicionado: o "Will install"
cat .claude-plugin/plugin.json
find . -name hooks.json -not -path '*/node_modules/*' -print -exec jq -c '.hooks | to_entries[] | {evento: .key, cmds: [.value[].hooks[].command]}' {} \;
find . -name .mcp.json -not -path '*/node_modules/*' -print -exec jq '.mcpServers | to_entries[] | {nome: .key, cmd: .value.command, args: .value.args, env: (.value.env // {} | keys)}' {} \;
grep -rn '^allowed-tools:' --include=SKILL.md .           # skill que se autoconcede ferramenta
find . -path '*/agents/*.md' -o -path '*/commands/*.md' | head -50
```

Sinal de alerta:

- hook em `UserPromptSubmit`, `PostToolUse` ou `PreToolUse`: ele vê **todo** prompt, resultado ou comando (e o `PreToolUse` pode reescrever o comando);
- hook em `SessionStart` que baixa ou instala algo;
- `allowed-tools` com `Bash` amplo;
- MCP com `npx`/`uvx` sem versão;
- `env` pedindo token com escopo largo.

## 3. Rede, persistência, execução dinâmica

```bash
grep -rnE '\b(curl|wget)\b|(^|[[:space:];|&])(nc|ncat|socat)[[:space:]]|fetch\(|axios|requests\.(get|post)|urllib|http\.client' \
  --include='*.sh' --include='*.js' --include='*.ts' --include='*.py' --exclude-dir=node_modules . | head -40
grep -rnE 'launchctl|LaunchAgents|crontab|systemctl|nohup|disown|setsid|\&\s*$' \
  --include='*.sh' --include='*.js' --include='*.ts' --include='*.py' --exclude-dir=node_modules . | head
grep -rnE '\beval\b|base64 (-d|--decode)|atob\(|exec\(|child_process|subprocess|os\.system' \
  --include='*.sh' --include='*.js' --include='*.ts' --include='*.py' --exclude-dir=node_modules . | head -40
grep -rnE '~/\.ssh|\.aws|\.config/gh|\.claude\.json|keychain|security find-' --exclude-dir=node_modules . | head
```

Cada linha pede uma explicação plausível. **Daemon ou persistência** (LaunchAgent, crontab, processo em background que sobrevive à sessão) em plugin de produtividade é motivo para não instalar no Mac de trabalho. Cuidado com falso positivo: `jq -nc --arg` casa com `nc` e até com `\bnc -` (medido nos dois casos); por isso o padrão acima exige espaço ou separador de shell **antes** do `nc`.

## 4. Dependências do plugin

```bash
osv-scanner scan source -r .          # exit 0 limpo · 1 vulnerável · 128 sem lockfile (= não fixa versão!)
jq -r '.scripts // {} | to_entries[] | select(.key|test("install")) | "\(.key): \(.value)"' package.json 2>/dev/null
scorecard --repo=github.com/<org>/<repo> --checks Maintained,Pinned-Dependencies,Token-Permissions,Code-Review --show-details   # precisa de GITHUB_AUTH_TOKEN
```

Sem lockfile = cada instalação resolve versões novas. `postinstall`/`preinstall` = código rodando na instalação (foi o vetor do Shai-Hulud 2.0).

## 5. Tool poisoning e rug pull (MCP)

- Leia as **descrições das tools** e os schemas no código do servidor, não o README: instrução escondida na descrição é invisível para você e visível para o modelo (Invariant Labs, abr/2025).
- Rug pull: o servidor muda a descrição **depois** de aprovado. Fixe a versão exata do pacote, registre um hash das definições e reavalie a cada atualização (OWASP MCP Security Cheat Sheet).
- Servidor que busca conteúdo externo (web, issues, e-mail) traz prompt injection junto: ver `seguranca-agentes`, trifeta letal.

## 6. Credenciais

- Token dedicado **por servidor**, escopo mínimo, guardado em arquivo `600` ou Keychain. Nunca num `.mcp.json` commitado.
- Preferir transporte `stdio` a servidor HTTP local sem autenticação.

## 7. Fixar versão

- Marketplace: `sha` de 40 caracteres na fonte do plugin (o `sha` vence o `ref`).
- MCP: `npx pacote@x.y.z`, `uvx pacote==x.y.z`.
- Desligar auto-update do plugin quando der; reavaliar a cada atualização.

## 8. Testar isolado

Se passou nos itens 1–7 e ainda assim é grande: primeiro num **container ou VM descartável**, sem credencial montada, com rede restrita. Só depois no Mac.

## 9. Depois de instalar

```bash
claude plugin list
jq -c '.hooks | to_entries[] | {evento: .key, n: (.value | length)}' ~/.claude/settings.json
```

Em sessão: `/permissions` e `/mcp`. Anote na tarefa: versão, SHA, o que ele instala, por que foi aprovado.

## Veredito (escreva um destes)

- **Aprovado**: superfície entendida e compatível com o uso.
- **Aprovado isolado**: só em container/VM.
- **Reprovado**: motivo em uma linha (ex.: "daemon persistente + hooks em todos os eventos + 180 dependências sem lock").

## Prova de uso (2026-09-23, só leitura)

`warp@claude-code-warp` 2.1.0, já instalado: manifesto do autor Warp (`github.com/warpdotdev/claude-code-warp`); 6 hooks (`SessionStart`, `Stop`, `Notification`, `PermissionRequest`, `UserPromptSubmit`, `PostToolUse`); 0 `.mcp.json`; 0 rede/persistência nos scripts. O único "achado" do grep frouxo de rede foi `jq -nc`, um falso positivo. **Aprovado**, com a nota de que ele vê todo prompt e todo resultado de ferramenta.

## Fontes (acesso 2026-09-23)

- <https://code.claude.com/docs/en/discover-plugins>: plugins executam código arbitrário com os privilégios do usuário; "Will install"
- <https://code.claude.com/docs/en/plugin-marketplaces>: `sha` de 40 caracteres fixa a versão
- <https://code.claude.com/docs/en/plugins>: plugins aprovados fixados por SHA no marketplace da comunidade
- <https://code.claude.com/docs/en/skills>: `allowed-tools` não depende do workspace trust
- <https://code.claude.com/docs/en/mcp> · <https://code.claude.com/docs/en/security>: confiar antes de conectar; a Anthropic não audita MCP
- <https://owasp.org/www-project-mcp-top-10/>: OWASP MCP Top 10 (beta): MCP03 Tool Poisoning, MCP04 Supply Chain
- <https://cheatsheetseries.owasp.org/cheatsheets/MCP_Security_Cheat_Sheet.html>: hash das definições de tool; credencial por servidor
- <https://invariantlabs.ai/blog/mcp-security-notification-tool-poisoning-attacks>: tool poisoning, rug pull, shadowing
- <https://modelcontextprotocol.io/specification/draft/basic/security_best_practices>: servidor local roda com os privilégios do cliente
- <https://unit42.paloaltonetworks.com/npm-supply-chain-attack/>: Shai-Hulud 2.0 em pre-install
