# Fontes — seguranca-dependencias

Acesso de todas: **2026-09-23**. Versões lidas na página/API de releases do GitHub nessa data.

## Ferramentas

| ferramenta | versão | fonte |
|---|---|---|
| osv-scanner | **2.6.0** (2026-09-14): executado nas provas, sha256 conferido | [releases](https://github.com/google/osv-scanner/releases) · [scan source](https://github.com/google/osv-scanner/blob/main/docs/scan-source.md) · [output e exit codes](https://github.com/google/osv-scanner/blob/main/docs/output.md) (0/1/127/128) · [lockfiles suportados](https://github.com/google/osv-scanner/blob/main/docs/supported_languages_and_lockfiles.md) (inclui `uv.lock`) · [configuração](https://google.github.io/osv-scanner/configuration/) (`IgnoredVulns`, `ignoreUntil`) |
| syft | **1.52.0** (2026-09-17): executado | [releases](https://github.com/anchore/syft/releases) · [README](https://github.com/anchore/syft/blob/main/README.md) |
| grype | 0.119.0 (2026-09-17) | [releases](https://github.com/anchore/grype/releases) · [CLI](https://oss.anchore.com/docs/reference/grype/cli/) (`--fail-on` → exit 2) |
| pip-audit | 2.10.1 (2026-06-10) | [releases](https://github.com/pypa/pip-audit/releases) · [README](https://github.com/pypa/pip-audit/blob/main/README.md) (exit 0/1; não lê `uv.lock`) |
| cdxgen | 13.2.0 (2026-09-22) | [README](https://github.com/CycloneDX/cdxgen/blob/master/README.md) |
| OpenSSF Scorecard | 5.5.0 (2026-04-23) | [README](https://github.com/ossf/scorecard/blob/main/README.md) |
| npm | 12.1.0 é a atual; Mac local: **10.9.4** (executado) | [releases](https://github.com/npm/cli/releases) · [v12.0.0](https://github.com/npm/cli/releases/tag/v12.0.0) (scripts bloqueados por padrão) · [npm audit](https://github.com/npm/cli/blob/latest/docs/lib/content/commands/npm-audit.md) · [npm ci](https://github.com/npm/cli/blob/latest/docs/lib/content/commands/npm-ci.md) · [install-scripts](https://github.com/npm/cli/blob/latest/docs/lib/content/commands/npm-install-scripts.md) · [config `ignore-scripts`](https://github.com/npm/cli/blob/latest/workspaces/config/lib/definitions/definitions.js) · [provenance](https://docs.npmjs.com/generating-provenance-statements) |
| uv | 0.12.18 é a atual; Mac local 0.11.18 | [releases](https://github.com/astral-sh/uv/releases) · [CLI](https://docs.astral.sh/uv/reference/cli/) |

## Padrões e casos

| fonte | o que sustenta |
|---|---|
| [OWASP Top 10:2025 — A03](https://top10.owasp.org/2025/A03_2025-Software_Supply_Chain_Failures) | "A03:2025 Software Supply Chain Failures" e prevenção |
| [SLSA v1.2](https://slsa.dev/spec/) · [Build track](https://slsa.dev/spec/v1.2/build-track-basics) | níveis de proveniência |
| [debug-js/debug#1005](https://github.com/debug-js/debug/issues/1005) | debug 4.4.2 comprometido, 2025-09-08 (fonte primária do caso chalk/debug) |
| [Wiz — chalk/debug](https://www.wiz.io/blog/widespread-npm-supply-chain-attack-breaking-down-impact-scope-across-debug-chalk) (secundária) | phishing imitando o npm |
| [CISA — Shai-Hulud, 23/09/2025](https://www.cisa.gov/news-events/alerts/2025/09/23/widespread-supply-chain-compromise-impacting-npm-ecosystem) | mais de 500 pacotes; rotacionar credenciais |
| [Unit 42 — Shai-Hulud 2.0](https://unit42.paloaltonetworks.com/npm-supply-chain-attack/) | execução em pre-install |
| [CSA Singapura AD-2026-009](https://www.csa.gov.sg/alerts-and-advisories/advisories/ad-2026-009/) | ago/2026: keyv, flat-cache, file-entry-cache; mais de 1.300 versões |
| [Trivy GHSA-69fq-xp46-6x23](https://github.com/aquasecurity/trivy/security/advisories/GHSA-69fq-xp46-6x23) | v0.69.4 malicioso; tags de `trivy-action` reescritas; rotacionar segredos de pipeline |
| [GitHub — Secure use of Actions](https://docs.github.com/en/actions/reference/security/secure-use) | SHA completo é "the only way to use an action as an immutable release" |

## Claude Code, MCP e plugins

Ver a seção Fontes de `avaliar-plugin-terceiro.md` (docs de plugins, marketplaces, skills, MCP e security do Claude Code; OWASP MCP Top 10 beta; OWASP MCP Security Cheat Sheet; Invariant Labs; spec MCP).

## Medições locais (2026-09-23)

- Fixture (`requests==2.19.0`, `jinja2==2.10`, `lodash@4.17.15`): osv-scanner → 5 pacotes, 28 vulnerabilidades (11 High), exit 1; `npm audit --omit=dev --audit-level=high` → 1 high, exit 1; syft → CycloneDX → osv-scanner `-L` → 3 pacotes, 15 vulnerabilidades, exit 1.
- Repo sem manifesto: osv-scanner exit 128 ("No package sources found"); SBOM do syft com 33 componentes (do `.venv` de um worktree) → `No issues found`.
- `npm ls` em três projetos Node: `flat-cache@4.0.1` (publicada 2024-03-02), `file-entry-cache@8.0.0` (2023-12-18), `keyv@4.5.4` (2023-10-07): versões anteriores à onda de ago/2026. `npm view` consultou só o registry público.
- `npm config get ignore-scripts` → `false`; nenhum dos três tem `.npmrc` com `ignore-scripts`.
- Actions por tag: 14 a 20 por repo nos três projetos auditados.
- Plugin `warp@claude-code-warp` 2.1.0 avaliado com o checklist; o padrão de rede foi corrigido depois de dar falso positivo em `jq -nc`.

## Não confirmado

- Se `uv audit` já saiu de preview na 0.12.x (por isso a skill usa osv-scanner para `uv.lock`).
- Em que versão do npm entrou `min-release-age`.
- Detalhes do phishing de chalk/debug por fonte primária do npm/GitHub.
