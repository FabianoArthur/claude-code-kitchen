# Fontes — seguranca-segredos

Acesso de todas: **2026-09-23**. Versões lidas na página/API de releases do GitHub nessa data.

## Ferramentas

| ferramenta | versão conferida | fonte |
|---|---|---|
| gitleaks | **8.30.1** (2026-03-21) — binário executado nas provas, sha256 conferido | [releases](https://github.com/gitleaks/gitleaks/releases) · [README](https://github.com/gitleaks/gitleaks/blob/master/README.md) (comandos `git`/`dir`/`stdin`; `detect`/`protect` depreciados na v8.19.0; exit 0/1/126; `--redact`; `[extend] useDefault`; baseline) · [.pre-commit-hooks.yaml](https://github.com/gitleaks/gitleaks/blob/master/.pre-commit-hooks.yaml) (`gitleaks git --pre-commit --redact --staged --verbose`) · [config padrão](https://github.com/gitleaks/gitleaks/blob/master/config/gitleaks.toml) (regras Discord dependem da palavra `discord`) |
| trufflehog | **3.97.8** (2026-09-23; sai versão quase todo dia) — executado | [releases](https://github.com/trufflesecurity/trufflehog/releases) · [README](https://github.com/trufflesecurity/trufflehog/blob/main/README.md) (`--results`, `--fail` → 183, verificação = login no provedor) · [main.go](https://github.com/trufflesecurity/trufflehog/blob/main/main.go) (`--only-verified` oculto) · [PreCommit.md](https://github.com/trufflesecurity/trufflehog/blob/main/PreCommit.md) |
| pre-commit | 4.6.2 (2026-08-10) | [releases](https://github.com/pre-commit/pre-commit/releases) · [pre-commit.com](https://pre-commit.com/) |
| git-filter-repo | 2.47.0 (2024-12-04), mínimo para `--sensitive-data-removal` | [releases](https://github.com/newren/git-filter-repo/releases) · [manual](https://github.com/newren/git-filter-repo/blob/main/Documentation/git-filter-repo.txt) |
| gh | 2.101.0 é a atual (Mac local: 2.92.0) | [releases](https://github.com/cli/cli/releases) |

## Resposta a vazamento e GitHub

| fonte | o que sustenta |
|---|---|
| [GitHub — Remediating a leaked secret](https://docs.github.com/en/code-security/secret-scanning/working-with-secret-scanning-and-push-protection/remediating-a-leaked-secret) | "The most important remediation step is revoking the secret with the secret's provider"; apagar do código não impede exploração; explorado em horas; rotação sem downtime |
| [GitHub — Removing sensitive data](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository) | revogar/rotacionar primeiro e "may be sufficient"; git-filter-repo ≥ 2.47; `push --force --mirror`; limites (clones, forks, recontaminação) |
| [OWASP Secrets Management CS](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html) | §9.2: revogação imediata do que foi exposto; rotação rápida |
| [GitHub — About secret scanning](https://docs.github.com/en/code-security/secret-scanning/introduction/about-secret-scanning) | gratuito só em repo público; privado de org exige Secret Protection |
| [GitHub — About push protection](https://docs.github.com/en/code-security/secret-scanning/introduction/about-push-protection) | push protection de usuário só para repo público |
| [GitHub — About GitHub Advanced Security](https://docs.github.com/en/get-started/learning-about-github/about-github-advanced-security) | tabela: privado sem Secret Protection = sem scanning e sem push protection |
| [GitHub — padrões suportados](https://docs.github.com/en/code-security/secret-scanning/introduction/supported-secret-scanning-patterns) | `discord_bot_token` coberto |
| [GitHub — About authentication](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-authentication-to-github) | prefixos `ghp_`, `github_pat_`, `gho_`, `ghu_`, `ghs_`, `ghr_`; `ghs_` em formato novo sem tamanho fixo desde 2026-04-27 |

## gh, Keychain, shell

| fonte | o que sustenta |
|---|---|
| [gh help environment](https://cli.github.com/manual/gh_help_environment) | `GH_TOKEN`/`GITHUB_TOKEN` "takes precedence over previously stored credentials" |
| [go-gh auth.go](https://github.com/cli/go-gh/blob/trunk/pkg/auth/auth.go) | ordem no código: `GH_TOKEN`, depois `GITHUB_TOKEN` |
| [gh auth status](https://cli.github.com/manual/gh_auth_status) · [status.go](https://github.com/cli/cli/blob/trunk/pkg/cmd/auth/status/status.go) | `Logged in to <host> account <login> (<fonte>)` |
| `man security` (macOS 27.0 local) | `-w` por último = prompt (recomendado) |
| [zsh — builtins](https://zsh.sourceforge.io/Doc/Release/Shell-Builtin-Commands.html) | `read -s` sem eco; prompt com `?`, `-p` é coprocesso |

## Medições locais (2026-09-23)

- Fixture `ghp_` commitado e apagado: `gitleaks dir` 0 · `gitleaks git` 1 (`github-pat`) · `trufflehog git` 1 (`Github`).
- Fixture com 7 segredos (3 URLs de webhook Discord, 1 token de bot, 1 `pk_`, 2 URIs Mongo com senha em `.env`): regras padrão do gitleaks 1/7 (só `generic-api-key` no token de bot); com `references/gitleaks.toml` 7/7. trufflehog 3.97.8 também não pegou as URLs de webhook.
- Atenção: o gitleaks lê sozinho um `.gitleaks.toml` na raiz do alvo (precedência nº 4). Um teste "com regras padrão" numa pasta que já tem esse arquivo não é padrão.
- Repo limpo de teste: `gitleaks git`, `gitleaks dir` (com e sem config extra) e `trufflehog git` → 0 achados.
- `sed -E` do macOS não entende `\s`: a máscara da §4 com `\s` deixou o valor em claro na fixture; com `[[:space:]]`, mascarou.
- Backend NestJS real (checkout numa branch de integração): grep da árvore sem achados; `git grep` nas refs remotas achou a chave literal num `env-schema.ts` (presente nas branches de produção e staging e em dezenas de refs no total). Saída mascarada; o valor não foi exibido.
- Comando da §3 (URL ativa → host) conferido em fixture: ignora linha comentada e não imprime usuário/senha. **Não** foi rodado contra um `.env` real.

## Incidentes (fonte interna, anonimizados)

- `.env` apontando para produção + scripts que sobem o `AppModule`: observado em 2026-08 num backend NestJS (4 scripts, 13 arquivos com `@Cron`).
- Chave hardcoded em fallback de env-schema: observado em 2026-08; conferido com o `git grep` acima.
- `GH_TOKEN` no ambiente sombreando o keyring do `gh`: observado em 2026-07; `gh auth status` mostra `(keyring)` quando não há `GH_TOKEN` no ambiente.

## Não confirmado

- `pre-commit autoupdate --freeze` (fixar hooks por SHA): citado na doc, comportamento não lido.
- Formato oficial do token de bot do Discord.
