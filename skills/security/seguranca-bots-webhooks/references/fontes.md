# Fontes — seguranca-bots-webhooks

Acesso de todas: **2026-09-23**.

## Discord

| fonte | o que sustenta |
|---|---|
| [Gateway — Intents](https://docs.discord.com/developers/events/gateway) | intents por bitfield; privilegiados GUILD_MEMBERS (1<<1), GUILD_PRESENCES (1<<8), MESSAGE_CONTENT (1<<15); o que chega vazio sem MESSAGE_CONTENT |
| [discord.py — Intents](https://discordpy.readthedocs.io/en/stable/intents.html) | `Intents.none()`/`default()`; ligar no portal **e** no código |
| [OAuth2](https://docs.discord.com/developers/topics/oauth2) | URL de convite com `scope=bot` e `permissions=` |
| [Permissions](https://docs.discord.com/developers/topics/permissions) | ADMINISTRATOR 0x8, VIEW_CHANNEL 0x400, SEND_MESSAGES 0x800, READ_MESSAGE_HISTORY 0x10000, MANAGE_WEBHOOKS 0x20000000 |
| [Webhook resource](https://docs.discord.com/developers/resources/webhook) | URL com id+token; executar sem autenticação; `DELETE /webhooks/{id}/{token}`; `allowed_mentions` |
| [Interactions overview](https://docs.discord.com/developers/interactions/overview) | Ed25519 com `X-Signature-Ed25519`/`X-Signature-Timestamp`; 401 se falhar; checagens automáticas com assinatura inválida |
| [GitHub — padrões de secret scanning](https://docs.github.com/en/code-security/secret-scanning/introduction/supported-secret-scanning-patterns) | `discord_bot_token` com partner alert e push protection |
| [GitHub changelog — validity checks Discord](https://github.blog/changelog/2023-10-13-secret-scanning-supports-validity-checks-for-discord-tokens/) | GitHub checa validade de token Discord |
| [GitGuardian — remediation Discord bot token](https://www.gitguardian.com/remediation/discord-bot-token) | Reset Token no portal |

## ClickUp

| fonte | o que sustenta |
|---|---|
| [Webhook signature](https://developer.clickup.com/docs/webhooksignature) | `X-Signature` = HMAC-SHA256 hex do corpo com o `secret` do webhook |
| [Authentication](https://developer.clickup.com/docs/authentication) | token pessoal começa com `pk_`, "never expire", header sem Bearer; Regenerate; OAuth2 para apps de terceiros |

## GitHub e padrões genéricos

| fonte | o que sustenta |
|---|---|
| [Validating webhook deliveries](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries) | `X-Hub-Signature-256`, `compare_digest`/`timingSafeEqual`, vetor de teste (`It's a Secret to Everybody` / `Hello, World!` → `sha256=7571…3e17`) |
| [Best practices for webhooks](https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks) | `X-GitHub-Delivery` contra replay; responder 2xx em até 10 s |
| [Standard Webhooks spec](https://github.com/standard-webhooks/standard-webhooks/blob/main/spec/standard-webhooks.md) | `webhook-id`/`webhook-timestamp`/`webhook-signature`; `id.timestamp.payload`; comparação em tempo constante; id como chave de idempotência |
| [Stripe — Webhooks](https://docs.stripe.com/webhooks) | tolerância padrão de 5 min, nunca 0; corpo bruto; dedupe de eventos; 2xx rápido e fila |

## Medições locais (2026-09-23)

- `references/teste_verificar_webhook.py`: 6/6 ok (inclui o vetor oficial do GitHub).
- Regras padrão de gitleaks 8.30.1 e trufflehog 3.97.8 não detectaram URL de webhook do Discord (ids de 18 e 19 dígitos, domínios discord.com e discordapp.com); a regra `discord-webhook-url` detectou 3/3. Detalhe em `seguranca-segredos`.
- `grep` da seção 1 contra um repo limpo: rc=1 (nada); contra fixture com webhook, token de bot e `pk_` falsos: 5/5 arquivos.
- `read -rs '?Token: '` no zsh e `umask 077` → arquivo `600`: conferidos em diretório temporário.

## Não confirmado

- Formato oficial do token de bot do Discord: a regex da seção 1 é heurística (três partes separadas por ponto, a primeira começando por M/N/O), montada pelo formato observado; o Discord não publica o formato.
- Se o Discord invalida sozinho o token recebido via partner alert do GitHub: só há evidência de comunidade. A skill manda resetar sempre.
- Janela de timestamp das interactions do Discord: a doc não define; a skill aplica a tolerância genérica de ~5 min.
