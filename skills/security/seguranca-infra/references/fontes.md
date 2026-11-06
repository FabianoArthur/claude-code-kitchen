# Fontes — seguranca-infra

Acesso de todas: **2026-09-23**. Versões lidas na API de releases do GitHub nessa data.

## Docker

| fonte | o que sustenta |
|---|---|
| [CIS Docker Benchmark](https://www.cisecurity.org/benchmark/docker) | versão atual 1.8.0 (jul/2025); PDF exige cadastro e **não foi lido**. A skill cita controles pelo título, não pelo número |
| [docker-bench-security — imagens](https://github.com/docker/docker-bench-security/blob/master/tests/4_container_images.sh) · [runtime](https://github.com/docker/docker-bench-security/blob/master/tests/5_container_runtime.sh) | títulos dos controles (usuário no container, HEALTHCHECK, COPY em vez de ADD, segredo fora do Dockerfile, sem privileged, bind em interface específica, sem docker.sock); baseado no CIS 1.6.0 |
| [OWASP Docker Security CS](https://cheatsheetseries.owasp.org/cheatsheets/Docker_Security_Cheat_Sheet.html) | docker.sock = root; usuário não-root; sem `--privileged`; `no-new-privileges`; Docker ignora o UFW, bind em 127.0.0.1; read-only; Docker Secrets |
| [Docker — Build secrets](https://docs.docker.com/build/building/secrets/) | ARG/ENV "persist in the final image"; `RUN --mount=type=secret`; `/run/secrets/<id>` |
| [Dockerfile reference](https://docs.docker.com/reference/dockerfile/) | ARG visível em `docker history`; `HEALTHCHECK`, `USER` |
| [Compose — secrets](https://docs.docker.com/compose/how-tos/use-secrets/) | env pode sair em log; secret montado em `/run/secrets/<nome>` |
| [Port publishing](https://docs.docker.com/engine/network/port-publishing/) | publica em `0.0.0.0` e `[::]` por padrão; `127.0.0.1:` restringe ao host |
| [Packet filtering and firewalls](https://docs.docker.com/engine/network/packet-filtering-firewalls/) | pacotes roteados antes do firewall (ufw ignorado) |
| [docker scout cves](https://docs.docker.com/reference/cli/docker/scout/cves/) | `--only-severity`, `--only-fixed`, SARIF; scout-cli 1.24.0 |
| [Trivy — misconfiguration](https://trivy.dev/latest/docs/scanner/misconfiguration/) | `trivy config`; Dockerfile e compose suportados; trivy **0.74.0** (2026-08-14) |
| [Trivy GHSA-69fq-xp46-6x23](https://github.com/aquasecurity/trivy/security/advisories/GHSA-69fq-xp46-6x23) | 0.69.4 malicioso (19/03/2026); imagens 0.69.5/0.69.6; trivy-action < 0.35.0 e setup-trivy reescritos; pin por SHA; rotacionar segredos |
| [hadolint releases](https://github.com/hadolint/hadolint/releases) | 2.15.1 (2026-07-31) |

## GitHub

| fonte | o que sustenta |
|---|---|
| [About rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets) | vários rulesets se somam; uma branch protection por branch; leitura visível a quem tem read |
| [REST — rules](https://docs.github.com/en/rest/repos/rules) | `GET /repos/{o}/{r}/rulesets`, `GET /repos/{o}/{r}/rules/branches/{branch}` |
| [Environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments) | segredos só depois das regras (required reviewers) |
| [Secure use of Actions](https://docs.github.com/en/actions/reference/security/secure-use) | SHA completo = única versão imutável; GITHUB_TOKEN read-only; `pull_request_target` sem checkout de código não confiável; `env:` intermediária contra injeção |
| [Workflow syntax — permissions](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax) | `permissions: contents: read`; `{}`; as não citadas viram `none` |
| [Actions settings do repo](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository) | GITHUB_TOKEN read-only em repo novo; opção "Require actions to be pinned to a full-length commit SHA" |
| [GitHub Security Lab — pwn requests](https://securitylab.github.com/resources/github-actions-preventing-pwn-requests/) | `pull_request_target` + checkout do PR = comprometimento |
| [CISA — tj-actions/changed-files](https://www.cisa.gov/news-events/alerts/2025/03/18/supply-chain-compromise-third-party-tj-actionschanged-files-cve-2025-30066-and-reviewdogaction) | CVE-2025-30066, 12–15/03/2025 |
| [Dependabot para Actions](https://docs.github.com/en/code-security/dependabot/working-with-dependabot/keeping-your-actions-up-to-date-with-dependabot) | `package-ecosystem: github-actions` |
| [zizmor](https://docs.zizmor.sh/usage/) | 1.30.1 (2026-09-09) |
| [actionlint releases](https://github.com/rhysd/actionlint/releases) | 1.7.12 (2026-03-30) |
| [OpenSSF Scorecard](https://github.com/ossf/scorecard) | 5.5.0; checks Token-Permissions, Pinned-Dependencies, Dangerous-Workflow, Branch-Protection |

## MongoDB

| fonte | o que sustenta |
|---|---|
| [Security Checklist](https://www.mongodb.com/docs/manual/administration/security-checklist/) | auth, menor privilégio, TLS, rede confiável, criptografia em repouso, `--noscripting`, rotação de usuários |
| [Security configuration (bindIp)](https://www.mongodb.com/docs/manual/core/security-mongodb-configuration/) | bind só em localhost desde a 3.6; auth antes de abrir o bind |
| [Atlas IP Access List](https://www.mongodb.com/docs/atlas/security/ip-access-list/) | só IPs da lista conectam; entrada temporária até 7 dias; remoção não derruba conexões abertas na hora |
| [mongodump](https://www.mongodb.com/docs/database-tools/mongodump/) | `--uri`, `--archive --gzip`, `--oplog` |
| [Atlas Cloud Backup](https://www.mongodb.com/docs/atlas/backup/cloud-backup/overview/) | disponível a partir do Flex; não no M0 |

## TLS

| fonte | o que sustenta |
|---|---|
| [ssl-config.mozilla.org](https://ssl-config.mozilla.org/) → [TLSRef Configurator](https://configurator.tlsref.org/) · [guideline 6.0](https://docs.tlsref.org/server-side-tls.html) | mudança de endereço; Intermediate = TLS 1.2+1.3; "Old" removido |
| [testssl.sh](https://github.com/testssl/testssl.sh) | 3.2.4 (2026-07-12); imagem `ghcr.io/testssl/testssl.sh` |
| [SSL Labs](https://www.ssllabs.com/ssltest/) | opção de não publicar o resultado |

## Medições locais (2026-09-23, só leitura)

- Os achados citados na skill (Dockerfile sem `USER`/`HEALTHCHECK`, portas de banco em `0.0.0.0`, workflows sem `permissions:`) são padrões vistos em auditorias de projetos reais; os nomes dos projetos foram removidos desta cópia pública.
- `actions/permissions/workflow` e `branches/<b>/protection` dão 404 sem permissão de admin; `gh api .../rules/branches/<b>` funciona com conta comum.
- `curl -sI https://github.com`: comando da §5 validado (HSTS, nosniff, CSP, referrer-policy presentes).

## Não confirmado

- Texto do CIS Docker Benchmark 1.8.0 (numeração dos controles).
- `docker scout cves --exit-code`; exemplos literais de `hadolint`/`actionlint`/`trivy image` (a skill usa a forma básica documentada nos READMEs).
- Se o Dependabot atualiza Actions fixadas por SHA (a skill recomenda o comentário `# vX.Y.Z` ao lado, que é o padrão que ele reconhece; não verificado nesta pesquisa).
- Aviso literal do Atlas contra `0.0.0.0/0`; "usuário por ambiente" é derivado do menor privilégio do checklist.
- A contradição entre a memória "staging protegida por ruleset" e a API (ver o problema registrado).
