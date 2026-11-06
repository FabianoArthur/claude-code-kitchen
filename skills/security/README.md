# Pacote de skills de segurança defensiva

> **Idioma:** este pacote está em **português (pt-BR)**, o idioma em que foi escrito e
> testado. Traduzir ~1.900 linhas de checagens com comandos e saídas esperadas arrisca
> mudar o que cada comando prova, então a versão em inglês fica para quem a mantiver com
> teste. Os nomes das skills, os comandos e o código são os mesmos em qualquer idioma;
> o Claude responde no idioma da sua conversa mesmo lendo estas instruções em português.

Oito skills do Claude Code, ancoradas numa stack comum (NestJS + MongoDB, FastAPI,
React + Vite, Docker, GitHub Actions, bots Discord, agentes Claude Code) e em incidentes
reais, **anonimizados** nesta cópia pública. Cada checagem traz **o comando que prova** e o
resultado esperado. Só detecção, prevenção e resposta: nada ofensivo.

Pesquisa e medições de **2026-09-23**. Cada skill tem `references/fontes.md` com fonte
primária, data de acesso, versão conferida das ferramentas e o que ficou sem confirmação.

## Índice

| skill | quando usar | material executável |
|---|---|---|
| [`seguranca-segredos`](seguranca-segredos/SKILL.md) | `.env`, token, chave, vazamento, pre-commit, `gh` com 401 | `references/gitleaks.toml` (regras extras), `references/resposta-a-vazamento.md` |
| [`seguranca-dependencias`](seguranca-dependencias/SKILL.md) | npm/pip/uv, SBOM, alerta de pacote comprometido, **plugin/MCP/skill de terceiro** | `references/avaliar-plugin-terceiro.md` |
| [`seguranca-agentes`](seguranca-agentes/SKILL.md) | agente autônomo, bypass, auto mode, hooks, sandbox, MCP, prompt injection | `references/cerca/` (hook PreToolUse + bateria de casos + contraprova ingênua) |
| [`seguranca-api`](seguranca-api/SKILL.md) | auditoria de API NestJS/FastAPI (OWASP API Top 10 2023) | — |
| [`seguranca-infra`](seguranca-infra/SKILL.md) | Dockerfile, compose, GitHub (rulesets, Actions), MongoDB/Atlas, TLS | — |
| [`seguranca-web-front`](seguranca-web-front/SKILL.md) | XSS, CSP, headers, token no browser, `VITE_*`, source map | — |
| [`seguranca-dados-lgpd`](seguranca-dados-lgpd/SKILL.md) | dado pessoal (equipe, posição, e-mail), logs, retenção, prazo da ANPD | `references/pii_scan.py` (+ testes) |
| [`seguranca-bots-webhooks`](seguranca-bots-webhooks/SKILL.md) | bot Discord, ClickUp, webhook de saída e de entrada | `references/verificar_webhook.py` (+ testes) |

A `security-review` embutida do Claude Code revisa o diff em geral; estas skills dão os
comandos específicos da stack. Se você já tem uma skill de design de APIs, `seguranca-api`
a complementa: audita, não repete contrato, paginação nem idempotência.

## Incidentes → onde estão cobertos

Os casos abaixo aconteceram em projetos reais; nomes de empresa, repositório e provedor
foram removidos, a lição ficou.

| incidente | skill → seção |
|---|---|
| `.env` do backend aponta para produção; scripts sobem o `AppModule` com todos os crons | `seguranca-segredos` §3 |
| chave de provedor hardcoded no env-schema, rotação pendente | `seguranca-segredos` §4 (+ §7) |
| `GH_TOKEN` inválido sombreando o keyring do `gh` (401 em tudo) | `seguranca-segredos` §5 |
| token de bot quase colado no chat | `seguranca-bots-webhooks` §1 (+ `seguranca-segredos` §6) |
| URL de webhook tratada como segredo | `seguranca-bots-webhooks` §1 e §3; regra `discord-webhook-url` em `seguranca-segredos` |
| agente com bypass de permissões; classificador do auto mode bloqueando "Create Unsafe Agents" | `seguranca-agentes` §1 (+ §3 cerca, §4 sandbox) |
| avaliação de um plugin enorme de terceiro antes de instalar | `seguranca-dependencias` §5 + `references/avaliar-plugin-terceiro.md` |

## Testes do material executável

Offline, sem rede e sem tocar em `~/.claude`:

```bash
python3 skills/security/seguranca-bots-webhooks/references/teste_verificar_webhook.py
python3 skills/security/seguranca-dados-lgpd/references/teste_pii_scan.py
(cd skills/security/seguranca-agentes/references/cerca && ./teste.sh ./cerca.py)
```

A suíte do repo (`pytest`) roda os três.

## Instalação (opcional)

O pacote **não** é instalado por padrão. Do clone do kitchen:

```bash
./install.sh --with-security            # as 8 skills de segurança, junto com as do kitchen
./install.sh --with-security --dry-run  # só mostra o que faria
./install.sh --uninstall                # remove também esses links (só os que apontam para este repo)
```

As mesmas regras do `install.sh` valem aqui: link simbólico (um `git pull` atualiza as
skills), nada é apagado, uma skill de mesmo nome já existente vai para
`<nome>.bak-<timestamp>` só depois da sua confirmação. Numa sessão nova, `/skills` lista as
oito `seguranca-*`.

## Ferramentas citadas (versões conferidas em 2026-09-23)

Executadas nas provas (binário oficial, sha256 conferido contra o checksums da release):
gitleaks 8.30.1 · trufflehog 3.97.8 · osv-scanner 2.6.0 · syft 1.52.0 · npm 10.9.4.
Citadas pela documentação, **não executadas**: semgrep 1.178.0 · trivy 0.74.0 (evite
0.69.4–0.69.6) · grype 0.119.0 · pip-audit 2.10.1 · hadolint 2.15.1 · zizmor 1.30.1 ·
actionlint 1.7.12 · testssl.sh 3.2.4 · scorecard 5.5.0 · docker scout 1.24.0.

No macOS: `brew install gitleaks trufflehog osv-scanner syft` (confira a versão com
`<ferramenta> --version`).

## Origem e escopo

Tudo aqui foi escrito do zero a partir das fontes primárias listadas em cada `fontes.md`;
nada foi copiado de outros repositórios. Não é aconselhamento jurídico: o que a skill de LGPD
chama de "decisão jurídica" fica com quem responde legalmente pela empresa.
