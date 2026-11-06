# Resposta a vazamento de credencial — passo a passo

Ordem das fontes primárias (GitHub "Remediating a leaked secret", GitHub "Removing sensitive data", OWASP Secrets Management §9.2): **revogar/rotacionar → avaliar e auditar uso → limpar histórico (se valer a pena) → documentar.** O GitHub avisa que scanners automáticos acham segredo público em minutos e que ele pode ser explorado em horas. Por isso a primeira ação é no provedor, não no git.

## 0. Não piore

- Não cole o valor no chat, em issue nem em mensagem "para confirmar". Refira-se por nome, arquivo e commit.
- Não rode varredura sem `--redact`.
- Não faça `git push --force` para "apagar". Não resolve (clones, forks, caches) e, aqui, é proibido ao agente.

## 1. Revogar/rotacionar (minuto 0–5)

| credencial | onde revogar | prova de que morreu |
|---|---|---|
| token de bot Discord | Developer Portal → Bot → **Reset Token** | bot desconecta; chamada com o token antigo → 401 |
| URL de webhook Discord | Canal → Integrações → Webhooks → apagar (não há "regenerar") | `POST` na URL antiga → 404 |
| token pessoal ClickUp `pk_` | Settings → Apps → API Token → **Regenerate** | `curl -s -o /dev/null -w '%{http_code}' -H "Authorization: <antigo>" https://api.clickup.com/api/v2/user` → 401 |
| PAT GitHub | Settings → Developer settings → tokens → Revoke | `gh api user` com o antigo → 401 |
| usuário MongoDB/Atlas | Atlas → Database Access → editar senha (ou apagar usuário) | conexão com a senha antiga falha |
| chave de API de terceiro (ex.: chave de um provedor de telemetria) | painel do provedor; se precisar de deploy, **deploy com a nova e depois revogar a antiga** | chamada com a antiga → 401/403 |

Sem downtime (GitHub): gere a nova com as mesmas permissões, troque na aplicação, **depois** revogue a antiga.

Onde a credencial vive em env de produção sem painel (caso de plataformas que não permitem criar variável nova), rotacionar exige deploy. Registre isso como bloqueio com dono e data, e trate a chave como vazada até o deploy.

## 2. Mapear a exposição (minuto 5–15)

```bash
gitleaks git --no-banner --redact --log-opts="--all" -c skills/security/seguranca-segredos/references/gitleaks.toml \
  --report-format json --report-path /tmp/vaz.json <repo>
jq -r '.[] | [.RuleID, .File, .Commit[0:8], .Date] | @tsv' /tmp/vaz.json
git log --all -S '<prefixo curto, nunca o valor inteiro>' --format='%h %ad %an %s' --date=short   # quem/quando
```

Também: logs da aplicação, transcripts de agente (`~/.claude/projects/**.jsonl`), CI (logs de Actions), canais de chat.
Repo **público**? Considere o segredo lido por terceiros; o GitHub pode ter avisado o provedor (partner program).

## 3. Auditar uso (minuto 15–25)

- GitHub: audit log da org; para PAT, "último uso" na página do token.
- Atlas: Database Access History / logs de acesso, na janela entre o commit e a revogação.
- Discord: Audit Log do servidor (ações do bot).
- ClickUp: atividade do workspace.
Pergunta a responder: **houve uso fora do padrão entre a exposição e a revogação?** Se houve, é incidente de segurança, não só higiene. Se houve dado pessoal envolvido, ver `seguranca-dados-lgpd` (prazo da ANPD: 3 dias úteis).

## 4. Registrar (minuto 25–30)

Arquivo em `docs/tasks/<data>-vazamento-<o-que>.md`: o quê (nome da credencial, nunca o valor), onde (arquivo, commit, canal), janela de exposição, quando foi rotacionado, uso anômalo sim/não, o que falta.

## 5. Limpar histórico (só se valer a pena)

O GitHub diz que rotacionar **pode bastar**. Limpar faz sentido quando o repo vai ficar público, ou quando o segredo não pode ser rotacionado.

Requer `git-filter-repo` ≥ 2.47 com `--sensitive-data-removal`:

```bash
# num clone novo e espelhado, nunca no checkout de trabalho
git clone --mirror <url> repo-limpeza && cd repo-limpeza
git-filter-repo --sensitive-data-removal --invert-paths --path caminho/do/arquivo   # remove o arquivo
# ou troca o texto: arquivo com uma expressão por linha (literal:/regex:, "==>SUBST" opcional)
git-filter-repo --sensitive-data-removal --replace-text ../expressoes.txt
```

Publicar exige `git push --force --mirror origin`. **O agente não executa isso.** Ele entrega o comando e a lista de consequências ao humano:

- todos os hashes mudam; PRs abertos e assinaturas quebram;
- clones e forks continuam com o segredo; um `git pull` + `git push` de um clone velho **traz de volta**;
- a divergência de histórico aponta para onde está o segredo;
- views em cache e refs de PR: só o GitHub Support remove, e só quando rotacionar não resolve.

## Fontes

- <https://docs.github.com/en/code-security/secret-scanning/working-with-secret-scanning-and-push-protection/remediating-a-leaked-secret> (2026-09-23)
- <https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository> (2026-09-23)
- <https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html> (2026-09-23)
- <https://github.com/newren/git-filter-repo/blob/main/Documentation/git-filter-repo.txt> (2026-09-23)
- <https://developer.clickup.com/docs/authentication> (2026-09-23)
- <https://docs.discord.com/developers/resources/webhook> (2026-09-23)
