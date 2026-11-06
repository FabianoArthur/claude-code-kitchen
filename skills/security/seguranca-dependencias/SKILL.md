---
name: seguranca-dependencias
description: Use quando for instalar, atualizar ou auditar dependência (npm, pip/uv), gerar SBOM, reagir a alerta de pacote comprometido, ou avaliar plugin, servidor MCP ou skill de terceiro antes de instalar no Claude Code. Sintomas de que precisa: npm install em CI em vez de npm ci, postinstall rodando sem ninguém ver, alerta de "pacote X comprometido" e ninguém sabe se o projeto usa, osv-scanner dizendo nada (exit 128), npx/uvx sem versão fixa, Action do GitHub por tag, plugin enorme com hooks e daemon que alguém quer instalar "para testar".
---

# Dependências e supply chain

## Visão geral

OWASP Top 10:2025 trouxe **A03:2025 Software Supply Chain Failures**, e 2025–2026 mostrou por quê: sequestro de chalk/debug (set/2025, conta de mantenedor tomada por phishing), worm Shai-Hulud (set/2025, mais de 500 pacotes; versão 2.0 em nov/2025 rodando em **pre-install**), nova onda da mesma família em ago/2026 (keyv, flat-cache, file-entry-cache; mais de 1.300 versões), e a **própria ferramenta de segurança** comprometida: Trivy v0.69.4 e as tags do `trivy-action` reescritas em mar/2026 para roubar segredos de CI.

Três defesas cobrem a maior parte:

1. **Lockfile + instalação reprodutível** (`npm ci`, `uv sync --locked`).
2. **Script de instalação não roda por padrão** (`--ignore-scripts`; o npm 12 já bloqueia, mas o Mac está no npm 10.9.4).
3. **Varredura contínua** do lockfile contra a base OSV, e SBOM para responder rápido "a gente usa isso?".

## 1. Varrer vulnerabilidade conhecida

```bash
osv-scanner scan source -r <repo>
echo "exit=$?"
```

| exit | significa |
|---|---|
| `0` | achou pacotes, **nenhuma** vulnerabilidade |
| `1` | há vulnerabilidade (tabela com OSV URL, CVSS, pacote, versão, versão corrigida) |
| `128` | **"No package sources found": não varreu nada.** Não é "limpo" |

Prova (2026-09-23, osv-scanner 2.6.0): fixture com `requests==2.19.0`, `jinja2==2.10` e `lodash 4.17.15` → `Total 5 packages affected by 28 known vulnerabilities (0 Critical, 11 High, 17 Medium…)`, exit 1. Um repo sem manifesto → exit **128**.

Ignorar com prazo e motivo, nunca para sempre: `osv-scanner.toml` ao lado do lockfile:

```toml
[[IgnoredVulns]]
id = "GHSA-xxxx-xxxx-xxxx"
ignoreUntil = 2026-12-31
reason = "caminho vulnerável não é chamado; revisar em dezembro"
```

Por ecossistema:

```bash
npm audit --omit=dev --audit-level=high      # só o que vai para produção; exit≠0 se ≥ high
pip-audit -r requirements.txt                 # exit 1 = vulnerabilidade
osv-scanner scan source -L uv.lock            # pip-audit não lê uv.lock; osv-scanner lê
```

Prova: na mesma fixture, `npm audit --omit=dev --audit-level=high` → `1 high severity vulnerability`, exit 1.
`npm audit fix --force` pode subir major: rode `npm audit fix --dry-run --json` antes e revise.

## 2. SBOM: responder "a gente usa isso?" em minutos

```bash
syft dir:<repo> -o cyclonedx-json=sbom.cdx.json
osv-scanner scan source -L sbom.cdx.json      # ou: grype sbom:./sbom.cdx.json --fail-on high  (exit 2, não 1)
jq -r '.components[] | .name + "@" + .version' sbom.cdx.json | grep -E '^(flat-cache|keyv)@'
```

Prova: syft 1.52.0 num repo sem manifesto → 33 componentes (todos do `.venv` de um worktree) → osv-scanner `No issues found`. Na fixture → 3 pacotes, 15 vulnerabilidades, exit 1.

**Triagem de alerta de pacote comprometido** (exemplo real, alerta CSA AD-2026-009 de 06/08/2026):

```bash
npm ls flat-cache file-entry-cache keyv --all | grep -E 'flat-cache@|file-entry-cache@|keyv@' | sort -u
npm view flat-cache time --json | jq -r '.["4.0.1"]'     # data de publicação da versão instalada
```

Em 2026-09-23, três projetos Node auditados tinham `flat-cache@4.0.1`, `file-entry-cache@8.0.0` e `keyv@4.5.4`, publicadas em 2023–2024, **antes** da onda maliciosa: o lockfile segurou versões limpas. Se a versão instalada estiver na lista do alerta: tratar a máquina e o CI que instalaram como comprometidos, **rotacionar todas as credenciais que eles tocaram** (ver `seguranca-segredos` §7) e reconstruir.

## 3. Instalação que não executa código de terceiro

```bash
npm ci --ignore-scripts              # CI e reprodução: exige lock, nunca reescreve lock
npm config get ignore-scripts        # esperado no Mac: true (hoje: false)
grep -s ignore-scripts .npmrc        # por projeto
```

- `npm ci` falha se `package.json` e lock divergem, em vez de "consertar" em silêncio. **`npm install` em CI é achado.**
- Pacote com binário nativo (`bcrypt`, `sharp`) quebra com `ignore-scripts`: rode `npm rebuild <pacote>` só para ele, depois de olhar o script.
- npm 12 (jul/2026): scripts de dependência bloqueados por padrão (`allowScripts` + `npm install-scripts approve`); dependência de git/tarball remoto desligada por padrão. Até atualizar o npm, `ignore-scripts` é a defesa.
- Ver os scripts antes de aprovar: `npm view <pacote>@<versão> scripts`. **Esperado:** sem `preinstall`/`install`/`postinstall`, ou um script que você leu e entende (compilar binário nativo); script que baixa e executa algo (`curl`, `node -e` com código ofuscado) = não instalar.

Python: `uv sync --locked` (falha se o lock está desatualizado) e `uv pip install --require-hashes -r requirements.txt` quando o arquivo traz hashes.

## 4. `npx`/`uvx`, Actions e hooks: fixar versão

```bash
grep -rnE '"command": *"(npx|uvx|bunx)"' ~/.claude.json .mcp.json 2>/dev/null     # MCP rodando pacote sem versão?
grep -rnE 'uses: [^@]+@(v?[0-9]+(\.[0-9]+)*|main|master)$' .github/workflows/     # Action por tag/branch
```

**Esperado:** `npx pacote@1.2.3` (versão exata), nunca `npx pacote` nem `@latest`: sem versão, cada execução pode trazer código novo (rug pull). Action fixada por **SHA completo**. O GitHub diz que é "the only way to use an action as an immutable release"; o caso trivy-action de mar/2026 é a prova. Hook de pre-commit: `rev:` com versão exata.

Medido em 2026-09-23 em três repos: todos os `uses:` (14 a 20 por repo) estavam por tag, inclusive uma action de conta pessoal (`<usuario>/setup-kustomize@v1`) no mesmo job que carrega credencial AWS.

## 5. Plugin, servidor MCP ou skill de terceiro: antes de instalar

A doc do Claude Code: plugins "can execute arbitrary code on your machine with your user privileges", e a Anthropic não controla nem verifica o que eles incluem. Servidor MCP: a Anthropic "does not security-audit or manage any MCP server". O `allowed-tools` de uma skill **não depende** do workspace trust.

Checklist completo e comandos em `references/avaliar-plugin-terceiro.md` (nascido do caso de um plugin enorme, com hooks, daemon e dezenas de dependências). O resumo:

| # | pergunta | como provar |
|---|---|---|
| 1 | Quem publica? Nome confere (typosquatting)? | repo, org, idade, issues |
| 2 | **O que ele instala?** Hooks, MCP, agentes, skills, `allowed-tools` | `claude plugin details <plugin>`; ler `hooks/hooks.json`, `.mcp.json`, `skills/*/SKILL.md` |
| 3 | Roda em que eventos? (`UserPromptSubmit`/`PostToolUse` veem **todo** prompt e resultado) | `jq '.hooks \| keys' hooks/hooks.json` |
| 4 | Sobe daemon, persiste, fala com a rede? | grep por `launchctl`, `crontab`, `nohup`, `curl`, `wget`, `fetch(`, `requests.` |
| 5 | Dependências têm vulnerabilidade? | `osv-scanner scan source -r <dir-do-plugin>` |
| 6 | Versão fixa? | `sha` no marketplace; `npx pacote@x.y.z` |
| 7 | Descrição de tool com instrução escondida (tool poisoning)? | ler as descrições das tools do MCP, não só o README |
| 8 | Precisa de token? Qual escopo? | token dedicado e mínimo por servidor |
| 9 | Dá para testar isolado? | container/VM descartável, sem credencial montada |

Prova de uso (2026-09-23, só leitura) no plugin instalado `warp@claude-code-warp` 2.1.0: 6 hooks (`SessionStart`, `Stop`, `Notification`, `PermissionRequest`, `UserPromptSubmit`, `PostToolUse`), 0 `.mcp.json`, 0 chamada de rede ou persistência nos scripts. Superfície: hooks locais de notificação. Aprovado, sabendo que ele vê todo prompt.

Plugin que falha no item 2 ou 4 sem justificativa (hooks demais, daemon, rede) **não se instala "para testar" no Mac de trabalho**: vai para container descartável, ou não vai.

## Anti-padrões → correção

| anti-padrão | correção |
|---|---|
| `npm install` no CI | `npm ci --ignore-scripts` |
| osv-scanner exit 128 lido como "limpo" | conferir que o lockfile foi achado (`-L <lock>`) |
| `npm audit fix --force` às cegas | `--dry-run --json` e revisão |
| alerta de pacote comprometido → "acho que não usamos" | `npm ls <pkg> --all` + data da versão, ou SBOM |
| `npx server-x` no `.mcp.json` | `npx server-x@1.4.2` |
| `uses: acao@v3` | `uses: acao@<sha-completo>  # v3.x.y` |
| instalar plugin grande "para ver" | checklist + container descartável |
| ignorar vulnerabilidade sem prazo | `ignoreUntil` + `reason` |

## Checklist de PR que mexe em dependência

- [ ] lockfile commitado e coerente (`npm ci` passa)
- [ ] `osv-scanner scan source -r .` sem vulnerabilidade nova (exit 0), ou ignorada com prazo
- [ ] pacote novo: autor, idade, downloads, `npm view <pkg> scripts` lido
- [ ] nada de `npx`/Action/hook sem versão fixa

Fontes com data de acesso: `references/fontes.md`.
