---
name: seguranca-infra
description: Use quando for escrever ou revisar Dockerfile, docker-compose, workflow do GitHub Actions, proteção de branch/ruleset, configuração de MongoDB (local ou Atlas) ou TLS de um domínio. Sintomas de que precisa: container rodando como root, porta publicada em 0.0.0.0 (banco na 5432/27017 exposto), segredo em ENV/ARG do Dockerfile, docker.sock montado, workflow sem permissions, Action por tag, pull_request_target com checkout do PR, branch de deploy sem regra, Mongo sem auth ou Atlas aberto para 0.0.0.0/0, backup que nunca foi restaurado.
---

# Infra — Docker, GitHub, MongoDB, TLS

## Visão geral

Infra falha em silêncio: o container sobe, o deploy passa, e ninguém nota que o Postgres está aberto para a rede do escritório ou que qualquer um com write pode dar force push na branch de produção. Cada item abaixo tem o comando que **mostra** o estado real.

Lição de 2026 que abre a skill: **a ferramenta de segurança também é vetor.** Em mar/2026 o binário do Trivy v0.69.4 saiu malicioso e as tags do `aquasecurity/trivy-action` anteriores à 0.35.0 foram reescritas para roubar segredos de CI (GHSA-69fq-xp46-6x23). Em mar/2025 foi o `tj-actions/changed-files` (CVE-2025-30066). Fixe por SHA, confira checksum do binário e rotacione segredos quando uma Action que você usa for comprometida.

## 1. Dockerfile

> Os comandos desta skill usam `grep -r --include='…'` em vez de glob solto (`docker-compose*.yml`): no zsh, glob sem correspondência aborta o comando com `no matches found` antes de o grep rodar, e a checagem parece limpa sem ter olhado nada (medido pelo review).

```bash
for f in $(find . -name 'Dockerfile*' -not -path '*/node_modules/*'); do
  printf '%s USER=%s HEALTHCHECK=%s ADD=%s\n' "$f" "$(grep -c '^USER' $f)" "$(grep -c '^HEALTHCHECK' $f)" "$(grep -c '^ADD ' $f)"
done
grep -rnE --include='Dockerfile*' --exclude-dir=node_modules --exclude-dir=.git '^(ENV|ARG) +[A-Z_]*(TOKEN|SECRET|PASSWORD|PASS|KEY|CREDENTIAL)' . | sed -E 's/((ENV|ARG) +[A-Z_]+)[ =].*/\1 <omitido>/'
```

**Esperado:** `USER` ≥ 1 no estágio final (usuário não-root; na imagem `node:*-alpine` já existe `node`); `HEALTHCHECK` presente; `COPY` em vez de `ADD`; **nenhum** segredo em `ENV`/`ARG`. A doc do Docker é explícita: build args e env "persist in the final image" e aparecem no `docker history`. Segredo de build vai por `RUN --mount=type=secret,id=<id>` (arquivo em `/run/secrets/<id>`) com `docker build --secret id=<id>,src=<arquivo>`.

Achado comum: Dockerfiles sem `USER` nem `HEALTHCHECK`, rodando como root sobre `node:20-alpine`. Um front que passa `VITE_GOOGLE_MAPS_API_KEY` por `ARG`/`ENV` no build é aceitável **só** porque chave do Maps é pública por natureza (vai para o bundle; ver `seguranca-web-front`), e ela precisa estar restrita por referrer no console do Google.

Conferir uma imagem pronta: `docker history --no-trunc <imagem> | grep -iE 'token|secret|password|key'` → vazio.

## 2. Compose e portas

```bash
grep -rnE --include='docker-compose*.y*ml' --include='compose*.y*ml' --exclude-dir=node_modules --exclude-dir=.git '^[[:space:]]*-[[:space:]]*"?[0-9]+:[0-9]+' .   # publicada em todas as interfaces
grep -rnE --include='docker-compose*.y*ml' --include='compose*.y*ml' --exclude-dir=node_modules --exclude-dir=.git 'docker\.sock|privileged: *true|network_mode: *host|cap_add' .
```

**Esperado:** porta de banco/cache **sem** linha no primeiro grep: ou não publicada (serviço fala pela rede interna do compose), ou `"127.0.0.1:5432:5432"`. O Docker publica em `0.0.0.0` por padrão e **passa por cima do ufw/firewall do host** (a doc diz que os pacotes são roteados antes das regras do firewall). Segundo grep vazio: montar `docker.sock` equivale a dar root do host ao container.

Achado comum: `docker-compose.yml` que publica `5432:5432` (Postgres) ou `27017:27017` (Mongo) em todas as interfaces. Em máquina de dev numa rede confiável é conveniência; em qualquer VPS/servidor é banco exposto. Troque por `127.0.0.1:`.

Segredo no compose: `secrets:` (arquivo montado em `/run/secrets/<nome>`) em vez de `environment:`. A doc do compose lembra que variável de ambiente "can also be printed in logs". `POSTGRES_PASSWORD` literal no `docker-compose.yml` versionado → mover para `.env` fora do git ou `secrets:`.

Varredura de imagem e de config (escolha uma; confira a versão e o checksum antes, por causa do caso Trivy):

```bash
docker scout cves --only-severity critical,high <imagem>
trivy image --severity HIGH,CRITICAL <imagem>            # trivy ≥ 0.69.3; evite 0.69.4–0.69.6
trivy config .                                             # Dockerfile e compose: misconfig
hadolint Dockerfile
```

**Esperado:** scout/trivy sem CVE `CRITICAL`/`HIGH` com correção disponível (as sem correção vão para uma lista com prazo); `trivy config` sem achado HIGH; `hadolint` sem `error` (os `warning`/`info` são revisados um a um: `DL3002` = último `USER` é root).

## 3. GitHub: branches, Actions, segredos

**Regras efetivas por branch** (leitura; inclui rulesets da organização):

```bash
R=<org>/<repo>
for b in main staging release production; do printf '%s: ' $b; gh api repos/$R/rules/branches/$b --jq '[.[].type] | unique | join(",")'; done
gh api repos/$R/rulesets --jq '.[] | [.name, .enforcement, .source_type] | @tsv'
```

**Esperado:** cada branch **de deploy e de base de PR** com pelo menos `pull_request`, `non_fast_forward` e `deletion`. Armadilha comum: a regra da org cobre só `main`, enquanto as branches que realmente fazem deploy (`staging`, `production`) voltam vazias. Rulesets se somam (vale a regra mais restritiva); branch protection clássica é uma por branch.

**Workflows:**

```bash
grep -rLE --include='*.y*ml' '^permissions:' .github/workflows                        # workflow sem permissions no topo
grep -rnE --include='*.y*ml' 'uses: [^@]+@(v?[0-9]+(\.[0-9]+)*|main|master)$' .github/workflows   # Action por tag/branch
grep -rnE --include='*.y*ml' 'pull_request_target|workflow_run' .github/workflows
grep -nE '\$\{\{ *github\.event\.(issue|pull_request|comment|review|head_commit)\.[a-z_.]*(title|body|message|name|ref)' --include='*.y*ml' -r .github/workflows
```

**Esperado:**

1. todo workflow com `permissions:` no topo (`contents: read`, ou `{}` e liberar por job). Especificar uma permissão zera as não citadas. Num levantamento típico, a maioria dos workflows não declara `permissions:`.
2. Action de terceiro fixada por **SHA de 40 caracteres** (`uses: org/acao@<sha>  # v1.2.3`), com Dependabot `package-ecosystem: github-actions` para atualizar. Medido: todas por tag nos três repos auditados, inclusive uma action de conta pessoal (`<usuario>/setup-kustomize@v1`) no job que recebe credencial AWS.
3. `pull_request_target` **sem** checkout do código do PR. A combinação é o "pwn request" do GitHub Security Lab. Separar em `pull_request` sem privilégio + `workflow_run` com privilégio.
4. Texto controlado por terceiro (`title`, `body`, `head_ref`) **nunca** interpolado direto em `run:`. Passe por `env:` intermediária.

Linters: `zizmor .github/workflows` (v1.30.1) e `actionlint`. Scorecard: `scorecard --repo=github.com/$R --checks Token-Permissions,Pinned-Dependencies,Dangerous-Workflow,Branch-Protection`.

**Segredos de Actions:** segredo de produção em **environment** com required reviewers. O job só recebe o segredo depois da aprovação. Credencial de nuvem via OIDC (`aws-actions/configure-aws-credentials` com `role-to-assume`) em vez de chave de acesso de longa duração. `gh secret list -R $R` (nomes) para inventário.

## 4. MongoDB

Local/compose:

```bash
grep -rnE --include='mongod.conf' --include='docker-compose*.y*ml' --include='compose*.y*ml' --exclude-dir=node_modules --exclude-dir=.git 'bindIp|bind_ip|--auth|authorization' .
```

**Esperado:** auth ligada **antes** de qualquer bind fora de localhost (`security.authorization: enabled`); `bindIp` restrito (o padrão desde a 3.6 é só localhost, e `--bind_ip_all` desfaz isso); porta 27017 não publicada em `0.0.0.0` (ver §2).

Atlas (painel ou `atlas` CLI):

- **Network Access:** sem `0.0.0.0/0`. Só os IPs de saída do deploy; entrada temporária (até 7 dias) para acesso pontual. Remover uma entrada não derruba na hora as conexões já abertas.
- **Database Access:** um usuário **por ambiente e por aplicação**, com role mínima (`readWrite` no banco dele, nunca `atlasAdmin` para a aplicação); rotação periódica.
- **Backup:** Cloud Backup existe a partir do Flex (não no M0). Backup que nunca foi restaurado não é backup: restaure num cluster de teste e registre a data.
- Script de leitura: `mongodump --uri=<uri-de-leitura> --archive=/tmp/x.gz --gzip` com usuário **read-only**. Nunca o `.env` do projeto se ele aponta para produção (ver `seguranca-segredos` §3).

Checklist oficial: auth, menor privilégio, TLS, rede confiável/firewall, criptografia em repouso, `--noscripting` quando não usa JS no servidor, rotação de usuários.

## 5. TLS e headers do domínio

```bash
curl -sI https://<host> | grep -iE '^(strict-transport-security|x-content-type-options|content-security-policy|referrer-policy|server|x-powered-by)'
docker run --rm ghcr.io/testssl/testssl.sh --quiet --severity HIGH https://<host>   # testssl.sh 3.2.4
```

**Esperado:** HSTS presente; sem `x-powered-by`; `server` sem versão; testssl sem achado HIGH/CRITICAL. Configuração de referência: perfil **Intermediate** (TLS 1.2 e 1.3) do TLSRef Configurator. O antigo Mozilla SSL Configuration Generator mudou para `configurator.tlsref.org`, e o guideline 6.0 removeu o perfil "Old". SSL Labs: marque "Do not show the results on the boards".

**Nunca** rode scanner ativo (testssl, nuclei, zap) contra produção ou homologação sem combinar antes: é tráfego que parece ataque. Header com `curl -sI` é inofensivo.

## Anti-padrões → correção

| anti-padrão | correção |
|---|---|
| container sem `USER` | usuário não-root no estágio final |
| `ENV API_KEY=…` / `ARG TOKEN` | `RUN --mount=type=secret` / `secrets:` do compose |
| `"5432:5432"` em servidor | sem porta publicada, ou `127.0.0.1:5432:5432` |
| `docker.sock` montado | não montar; se for inevitável, proxy de socket com allowlist |
| workflow sem `permissions:` | `permissions: contents: read` no topo |
| `uses: terceiro/acao@v1` | SHA completo + Dependabot |
| `pull_request_target` + checkout do PR | `pull_request` + `workflow_run` |
| `${{ github.event.pull_request.title }}` em `run:` | `env:` intermediária |
| regra só na `main`, deploy sai de `production` | ruleset nas branches reais |
| Atlas `0.0.0.0/0` | IPs de saída; entrada temporária |
| backup nunca restaurado | restauração de teste com data registrada |

## Checklist de PR de infra

- [ ] Dockerfile: `USER`, `HEALTHCHECK`, sem segredo em `ENV`/`ARG`
- [ ] compose: nenhuma porta de banco em `0.0.0.0`; sem `docker.sock`/`privileged`
- [ ] workflow: `permissions:`, Actions por SHA, sem `pull_request_target` com checkout, sem interpolação de texto de terceiro
- [ ] segredo de produção em environment com revisão
- [ ] Mongo: auth + bind restrito; Atlas sem `0.0.0.0/0`

Fontes com data de acesso: `references/fontes.md`.
