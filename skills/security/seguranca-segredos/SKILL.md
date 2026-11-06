---
name: seguranca-segredos
description: Use quando for lidar com credencial — .env, token, chave de API, URI de banco, URL de webhook — ou suspeitar que uma vazou; antes de rodar script que lê .env; ao configurar pre-commit/CI de segredos; ao ver gh devolvendo 401. Sintomas de que precisa: chave hardcoded em config/env-schema, .env apontando para produção sem ninguém saber, script "read-only" que sobe o AppModule inteiro, token colado no chat ou no log, segredo que foi commitado e depois apagado, GH_TOKEN no ambiente sombreando o login do gh, varredura que diz "no leaks found" sem ter olhado o histórico.
---

# Segredos — achar, guardar, rotacionar, responder

## Visão geral

Três verdades que guiam tudo aqui:

1. **Apagar do código não desvaza.** O segredo continua no histórico do git, em clones, forks e caches. O que desvaza é **revogar/rotacionar**.
2. **"No leaks found" só vale para o que foi olhado.** `gitleaks dir` não vê histórico; as regras padrão não conhecem os seus formatos. Numa fixture de 2026-09-23, as regras padrão do gitleaks 8.30.1 pegaram **1 de 7** segredos plantados (URL de webhook do Discord, `pk_` do ClickUp e URI do Mongo com senha passaram); com `references/gitleaks.toml` pegaram **7 de 7**.
3. **O agente nunca vê o valor.** Toda varredura roda com `--redact`; todo comando de conferência imprime nome, host ou contagem, nunca o segredo.

GitHub secret scanning e push protection **não cobrem repo privado** sem GitHub Secret Protection (pago). Em repo privado, a proteção real é gitleaks/trufflehog local + pre-commit + CI.

## 1. Varredura: árvore **e** histórico

```bash
C=skills/security/seguranca-segredos/references/gitleaks.toml     # regras extras (webhook Discord, pk_ ClickUp, URI Mongo)
# histórico de todas as refs
gitleaks git --no-banner --redact -c $C --log-opts="--all" --report-format json --report-path /tmp/gl-git.json <repo>
# árvore atual, inclusive o que não está versionado (.env, worktrees)
gitleaks dir --no-banner --redact -c $C --report-format json --report-path /tmp/gl-dir.json <repo>
jq -r '.[] | [.RuleID, .File, (.Commit // "" | .[0:8])] | @tsv' /tmp/gl-git.json /tmp/gl-dir.json
```

**Esperado:** relatório vazio (`[]`) e a linha `no leaks found`. Exit `0` = limpo; exit `1` = **vazamento ou erro**, por isso leia o JSON em vez de confiar só no exit code. `detect`/`protect` foram depreciados na v8.19.0: use `git`, `dir`, `stdin`.

Segunda opinião, com detectores diferentes:

```bash
trufflehog git file://<repo> --no-update --no-verification --json 2>/dev/null \
  | jq -r '[.DetectorName, .SourceMetadata.Data.Git.file, .SourceMetadata.Data.Git.commit[0:8]] | @tsv'
```

**Esperado:** nenhuma linha; no stderr, `"verified_secrets":0,"unverified_secrets":0`. O filtro do `jq` descarta o campo `Raw`, que traz o segredo em claro. Sem `--no-verification`, o trufflehog **testa o segredo contra a API do provedor**: use a verificação no seu repo (ela diz o que ainda está vivo) e desligue ao varrer código de terceiros. `--only-verified` virou flag oculta; o atual é `--results=verified,unknown`. Com `--fail`, achado dá exit **183**.

Prova de que a varredura de histórico importa (fixture: `ghp_` commitado e depois apagado): `gitleaks dir` → 0 achados; `gitleaks git` → 1 (`github-pat`, no commit antigo).

## 2. Pre-commit (antes de virar histórico)

`.pre-commit-config.yaml` do repo:

```yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.30.1          # o README do gitleaks ainda mostra uma versão antiga; fixe a atual
    hooks:
      - id: gitleaks      # roda: gitleaks git --pre-commit --redact --staged --verbose
```

```bash
pre-commit install && pre-commit run --all-files
```

**Esperado:** `gitleaks....Passed`. Prova de que o hook morde: stage um arquivo com um token **falso em formato realista** (não use a chave de exemplo da documentação da AWS nem outras "de exemplo", que as ferramentas ignoram de propósito) → `Failed`. Para a config extra valer no hook, copie `references/gitleaks.toml` para `<repo>/.gitleaks.toml`.

CI (GitHub Actions): mesma chamada `gitleaks git --redact` em PR, com a Action **fixada por SHA** (ver `seguranca-infra`).

## 3. `.env`: para onde ele aponta, e quem o lê

**Incidente real (anonimizado):** o `.env` de um backend NestJS tinha o `MONGODB_URI` de **produção** ativo (staging e local comentados), e 4 scripts em `scripts/` subiam `NestFactory.createApplicationContext(AppModule)`, que liga todos os `@Cron` (13 arquivos com `@Cron`). Um dry-run "read-only" ligaria os coletores contra produção.

Antes de rodar **qualquer** script ou teste que carregue `.env`:

```bash
# só nome -> esquema://host das URLs ATIVAS (linhas comentadas ignoradas; usuário, senha e caminho removidos)
grep -E '^[[:space:]]*(export[[:space:]]+)?[A-Z0-9_]+=["'\'']?[a-z][a-z0-9+.-]*://' .env \
  | sed -E 's/^[[:space:]]*(export[[:space:]]+)?([A-Z0-9_]+)=["'\'']?([a-z][a-z0-9+.-]*):\/\/([^@\/]*@)?([^\/?"'\'']*).*/\2 -> \3:\/\/\5/'
```

**Esperado:** `MONGODB_URI -> mongodb://localhost:27017` (ou um host de staging que você reconhece). Host com `prod` → **pare**. A saída nunca contém usuário nem senha (conferido em fixture).

```bash
# scripts que sobem a aplicação inteira (e com ela os crons)
grep -rlE 'createApplicationContext\(AppModule|NestFactory\.create\(AppModule' scripts
```

**Esperado:** vazio; se não estiver, leitura pontual vai num script mínimo com o driver direto, e a flag que desliga os coletores (ex.: `COLLECTOR_ENABLED=false`, e equivalentes) na linha de comando.

Regras:

- `.env` de dev aponta para **local/staging por padrão**; produção só num arquivo separado (`.env.production`), carregado de propósito.
- `.env` no `.gitignore`: `git check-ignore -v .env` → mostra a regra. `git ls-files | grep -E '(^|/)\.env($|\.)' | grep -v example` → vazio.
- `.env.example` com placeholders, nunca valores.

## 4. Chave hardcoded e rotação pendente

**Incidente real (anonimizado):** um fallback no `env-schema.ts` do backend trazia `apiKey` embutida (a plataforma de produção não permitia criar variável nova). A chave de um provedor de telemetria ficou no histórico desde um commit antigo: **trocar a variável não rotaciona**, só um deploy com a chave nova e a antiga revogada no provedor.

Achar o padrão (fallback com valor literal num schema de env):

```bash
grep -rnE "(apiKey|api_key|secret|token|password)[\"']?[[:space:]]*[:=][[:space:]]*[\"'][A-Za-z0-9_-]{16,}[\"']" --include='*.ts' --include='*.py' src backend app 2>/dev/null \
  | sed -E "s/([\"'])[A-Za-z0-9_-]{16,}([\"'])/\1****\2/g"
```

**Esperado:** vazio. A `sed` mascara todo valor entre aspas com 16+ caracteres, **inclusive quando a chave também está entre aspas** (`"token": '…'`). Duas armadilhas medidas em fixture: com `\s`, o `sed` do macOS não casa e o valor sai em claro; ancorar a máscara no primeiro `:` pega o `arquivo:linha:` do grep, mascara a chave e deixa o valor em claro (achado do review).

O grep acima só vê a branch atual. Chave que vive em **outra branch** (caso real: o fallback existia nas branches de produção e staging e em dezenas de refs remotas, mas não na branch de integração) só aparece varrendo as refs:

```bash
P="(apiKey|api_key|secret|token|password)[\"']?[[:space:]]*[:=][[:space:]]*[\"'][A-Za-z0-9_-]{16,}[\"']"
git grep -nE "$P" $(git for-each-ref --format='%(refname:short)' refs/remotes/origin | grep -v HEAD) -- src \
  | sed -E "s/([\"'])[A-Za-z0-9_-]{16,}([\"'])/\1****\2/g" | sort -u -t: -k2,3
```

Medido em 2026-09-23 nesse backend (checkout na branch de integração): o grep da árvore voltou vazio; o `git grep` nas refs achou `env-schema.ts:27: apiKey: "****"`.

Dívida de rotação vira registro com data, não memória: arquivo em `docs/tasks/` com "o quê, onde está exposto (commit), quem pode rotacionar, o que precisa de deploy". Enquanto não rotaciona, **trate a chave como vazada**.

## 5. Credencial em variável de ambiente

**Incidente real:** um `GH_TOKEN` inválido no ambiente **sombreava** o login válido do keyring: todo `gh` dava 401, e `gh auth login` não resolvia (o token novo ia para o keyring, e a variável continuava ganhando). Precedência do `gh`: `GH_TOKEN` > `GITHUB_TOKEN` > keyring.

```bash
gh auth status 2>&1 | grep -E 'Logged in|Failed|Active account'
env | cut -d= -f1 | grep -E '^(GH|GITHUB)_(ENTERPRISE_)?TOKEN$'
```

**Esperado:** `Logged in to github.com account <você> (keyring)` e `Active account: true`; nenhuma variável `GH_TOKEN`/`GITHUB_TOKEN` no shell interativo. O que está entre parênteses diz de onde veio o token. Nunca `gh auth status --show-token` em sessão de agente. Contorno pontual: `env -u GH_TOKEN gh …`; conserto: achar quem exporta (`grep -rn GH_TOKEN ~/.zshrc ~/.zshenv ~/.zprofile ~/.claude/settings.json`) e remover.

Mesma lógica para qualquer chave: variável de ambiente vaza para **todo** subprocesso (inclusive agentes; ver `seguranca-agentes`, checagem 5).

## 6. Guardar e ler sem vazar

- **Nunca pelo chat.** O agente entrega o comando; o humano roda no próprio terminal. Receitas (zsh `read -rs '?Token: '`, `pbpaste` + `umask 077`, Keychain `security add-generic-password … -w` com `-w` por último) em `seguranca-bots-webhooks` §1.
- Arquivo de segredo: `600`, diretório `700`, fora de repo. Conferência: `stat -f '%Lp %N' <arquivo>` → `600`.
- Nunca: segredo como argumento de linha de comando (vai para `ps` e histórico), em URL de query string, em `settings.json > env`, em log (`logger.info(config)`), em mensagem de erro.
- Log: mascarar na origem. `grep -rnE 'log.*(token|secret|password|apiKey)' --include='*.ts' --include='*.py' src backend` → cada ocorrência revisada.

## 7. Vazou: os primeiros 30 minutos

Ordem das fontes primárias (GitHub, OWASP): **revogar/rotacionar → auditar uso → só então limpar histórico.** Detalhe passo a passo em `references/resposta-a-vazamento.md`. Resumo:

| minuto | ação | prova |
|---|---|---|
| 0–5 | **Revogar/rotacionar no provedor** (Discord Reset Token, ClickUp Regenerate, GitHub revoke PAT, Atlas trocar senha do usuário). Se derrubar produção, gere a nova, troque, e **então** revogue a antiga | chamada com o valor antigo → 401 |
| 5–15 | Achar todo lugar onde o valor esteve: `gitleaks git --redact` no repo, logs, chat, CI | lista de lugares |
| 15–25 | Auditar uso: logs de acesso do provedor (Atlas access log, audit log do GitHub, último uso do PAT) na janela da exposição | uso anômalo sim/não |
| 25–30 | Registrar em `docs/tasks/` (o quê, quando, onde, rotacionado quando, o que falta) | arquivo criado |
| depois | Limpar histórico **só se valer a pena**: exige `git push --force --mirror`, o que **o agente nunca executa**: entrega o comando ao humano | — |

Dado pessoal no vazamento? Prazo da ANPD em `seguranca-dados-lgpd`.

## Anti-padrões → correção

| anti-padrão | correção |
|---|---|
| apagar o segredo num commit novo e seguir | rotacionar; o histórico continua com ele |
| `gitleaks dir` e "tá limpo" | `gitleaks git --log-opts=--all` + config extra |
| varredura sem `--redact` em sessão de agente | sempre `--redact`; trufflehog filtrado por `jq` |
| `.env` de dev com a URI de produção ativa | local/staging por padrão; produção em arquivo separado |
| script de manutenção que sobe o `AppModule` | script mínimo com o driver; crons desligados por variável |
| fallback com chave literal no schema | variável obrigatória; se não der, dívida registrada e tratada como vazada |
| `gh auth login` para consertar 401 | `gh auth status`: ver se é `GH_TOKEN` sombreando |
| "cola o token aqui" | comando entregue ao humano; arquivo `600` |

## Checklist

- [ ] `gitleaks git` (histórico, todas as refs, config extra) e `gitleaks dir` sem achados
- [ ] pre-commit com gitleaks fixado na versão atual, testado com token falso realista
- [ ] `.env` apontando para local/staging (conferido pelo comando da §3)
- [ ] nenhum script de manutenção subindo a app inteira contra `.env` real
- [ ] nenhuma chave literal em config; dívidas de rotação registradas
- [ ] `gh auth status` com fonte `keyring`
- [ ] segredos em arquivos `600` fora de repo

Fontes com data de acesso: `references/fontes.md`.
