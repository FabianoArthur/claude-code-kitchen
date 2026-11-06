---
name: seguranca-bots-webhooks
description: Use quando for criar, configurar ou revisar bot do Discord, integração com ClickUp/GitHub, webhook de saída (mandar aviso num canal) ou endpoint que recebe webhook. Sintomas de que precisa: token de bot prestes a ser colado no chat, URL de webhook no código ou no log, bot com Administrator, intent MESSAGE_CONTENT ligado sem precisar, endpoint de webhook que não confere assinatura, comparação de assinatura com ==, corpo re-serializado antes de verificar HMAC, token pk_ do ClickUp que nunca expira, bot "temporário" com admin que ficou.
---

# Bots e webhooks — Discord, ClickUp, GitHub

## Visão geral

Três credenciais diferentes, três erros diferentes:

- **Token de bot** (Discord) / **token pessoal** (ClickUp `pk_`, que **nunca expira**): quem tem, age como o bot/você.
- **URL de webhook de saída** (Discord): **a URL é a credencial**. Ela carrega id e token (`/api/webhooks/{id}/{token}`); executar "does not require authentication". Quem tem a URL posta no canal como o webhook.
- **Segredo de webhook de entrada** (GitHub, ClickUp, Stripe): é o que prova que a chamada veio do provedor. Endpoint sem verificação aceita evento forjado de qualquer um.

## 1. Gravar token sem passar pelo chat, log ou histórico

**Incidente real:** tokens de bot quase colados no chat do agente. Qualquer texto colado no chat vai para o transcript (`~/.claude/projects/**.jsonl`), para o contexto do modelo e para quem ler a sessão depois. **Token nunca passa pelo chat.** O agente entrega o comando; o humano roda no próprio terminal (no Claude Code, com `! <comando>` a saída cai na conversa, então **não** use `!` para isto: abra outro terminal).

```bash
# zsh: pede sem eco; o prompt vai como '?texto' (no zsh, -p NÃO é prompt)
mkdir -p ~/.config/<app> && chmod 700 ~/.config/<app>
( umask 077; read -rs '?Token: ' T; printf 'DISCORD_TOKEN=%s\n' "$T" > ~/.config/<app>/.env; unset T )
# ou, se o token já está na área de transferência:
( umask 077; printf 'DISCORD_TOKEN=%s\n' "$(pbpaste)" > ~/.config/<app>/.env ); pbcopy < /dev/null
stat -f '%Lp %N' ~/.config/<app>/.env
```

**Esperado:** `600 …/.env`. O arquivo fica **fora de qualquer repo**, e o repo tem `*.env` no `.gitignore` (confira que tem). Alternativa no Mac: Keychain, `security add-generic-password -a "$USER" -s <app> -w` (com `-w` como **último** argumento o comando pergunta o valor, e ele não fica no histórico); leitura com `security find-generic-password -s <app> -w`.

**Prova de que não vazou:**

```bash
grep -rnE 'discord(app)?\.com/api/(v[0-9]+/)?webhooks/[0-9]+/|[MNO][A-Za-z0-9_-]{23,}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}|pk_[0-9]+_[A-Z0-9]{20,}' \
  --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=.venv . ; echo "rc=$?"
```

**Esperado:** `rc=1` (nada casou). Para o histórico do git, use `gitleaks git` com a regra `discord-webhook-url` da `seguranca-segredos`: **as regras padrão do gitleaks 8.30.1 e do trufflehog 3.97.8 não pegaram URL de webhook do Discord** num teste com ids de 18 e 19 dígitos; a regra própria pegou 3 de 3.

## 2. Bot do Discord: mínimo privilégio

**Intents.** Privilegiados: `GUILD_MEMBERS` (1<<1), `GUILD_PRESENCES` (1<<8), `MESSAGE_CONTENT` (1<<15), ligados no Developer Portal **e** no código. Sem `MESSAGE_CONTENT`, `content`/`embeds`/`attachments` chegam vazios, **exceto** em DM, menção ao bot e mensagens do próprio app. Bot de slash command não precisa dele.

```bash
grep -rnE 'Intents\.(all|default)\(\)|message_content *= *True|members *= *True|presences *= *True' --include='*.py' .
```

**Esperado:** `discord.Intents.none()` + só o necessário (ex.: `intents.guilds = True`). `Intents.all()` = achado.

**Permissões do convite.** `https://discord.com/oauth2/authorize?client_id=<ID>&scope=bot%20applications.commands&permissions=<bitfield>`.

```bash
python3 -c 'p=int(input("bitfield: ")); print("ADMINISTRATOR!" if p & 0x8 else "ok", {n:bool(p&v) for n,v in {"MANAGE_GUILD":0x20,"MANAGE_ROLES":0x10000000,"MANAGE_WEBHOOKS":0x20000000,"MANAGE_CHANNELS":0x10}.items()})'
```

**Esperado:** sem `ADMINISTRATOR` (0x8 ignora overwrites de canal). Exemplo: ver canal + enviar + ler histórico = `0x400|0x800|0x10000` = `68608`.

**Bot "temporário" com admin** (caso de um bot de orquestração criado só para uma migração): data de validade anotada na tarefa; ao terminar, **Reset Token** no portal **e** remover o bot do servidor (tirar o cargo não basta se o convite tinha admin). Conferência: Server Settings → Integrations não lista o bot.

## 3. Webhook de saída (Discord)

- A URL mora no mesmo lugar que o token (arquivo `600` fora do repo; ex.: `~/.config/<app>/webhooks.json`). Nunca em `settings.json > env`, nunca em log (`logger.info(url)`), nunca em mensagem de erro.
- Ao mandar, use `allowed_mentions: {"parse": []}`: conteúdo vindo de PR/issue não dispara `@everyone`.
- **Vazou?** Não existe "regenerar token" de webhook: apague (Integrações → Webhooks, ou `DELETE /webhooks/{id}/{token}`) e crie outro. Depois, grave a URL nova com a receita da seção 1.

## 4. Webhook de entrada: verificar antes de processar

Verificador testado em `references/verificar_webhook.py` (bate com o vetor de teste oficial do GitHub):

```bash
python3 skills/security/seguranca-bots-webhooks/references/teste_verificar_webhook.py
```

**Esperado:** 6 linhas `ok`.

| provedor | header | o que é assinado | anti-replay |
|---|---|---|---|
| GitHub | `X-Hub-Signature-256: sha256=<hex>` | corpo bruto, HMAC-SHA256 | dedupe por `X-GitHub-Delivery` |
| ClickUp | `X-Signature: <hex>` | corpo bruto, HMAC-SHA256 com o `secret` devolvido na criação do webhook | dedupe por id do evento |
| Discord interactions | `X-Signature-Ed25519` + `X-Signature-Timestamp` | `timestamp + corpo`, Ed25519 com a public key do app; falhou → **401** | o Discord manda assinatura inválida de propósito para testar o endpoint |
| Standard Webhooks / Stripe | `webhook-signature` / `Stripe-Signature` | `id.timestamp.corpo` / `t.corpo` | janela de ~5 min (Stripe: nunca tolerância 0) |

Regras que valem para todos:

1. **Corpo bruto.** Verificar depois de `json.loads`/`JSON.parse` + re-serializar quebra a assinatura, ou pior, leva alguém a "consertar" desligando a verificação. FastAPI: `await request.body()`; Express/Nest: `rawBody: true` no `NestFactory.create`.
2. **Comparação em tempo constante:** `hmac.compare_digest` / `crypto.timingSafeEqual`. Checagem:

   ```bash
   grep -rnE '(signature|assinatura|x-hub-signature|x-signature)[^=]*[!=]==? ' --include='*.py' --include='*.ts' -i .
   ```

   **Esperado:** vazio.
3. Header ausente = rejeita (não "pula a verificação").
4. Dedupe pelo id de entrega; responde 2xx rápido e processa numa fila.
5. Segredo com entropia alta, fora do repo; rotação com sobreposição.
6. Log sem corpo e sem segredo.

## 5. Tokens de API (ClickUp, GitHub) usados por scripts e agentes

- ClickUp `pk_` **não expira** e vai no header sem `Bearer`. Guarde em arquivo `600` (ex.: `~/.config/<app>/clickup_token`); se vazar, Settings → Apps → API Token → **Regenerate**. App usado por outras pessoas → OAuth2.
- GitHub: `GH_TOKEN` no ambiente **vence** o login do keyring (`gh auth status` mostra de onde veio o token). Ver `seguranca-segredos`.
- Token de agente com o menor escopo: fine-grained PAT só dos repos da tarefa.

## Anti-padrões → correção

| anti-padrão | correção |
|---|---|
| "cola o token aqui que eu configuro" | o agente entrega o comando `read -rs`/`pbpaste`; o humano roda |
| URL de webhook num `.py`, `.md` ou log | arquivo `600` fora do repo; grep da seção 1 volta vazio |
| `Intents.all()` / admin no convite | `Intents.none()` + o mínimo; bitfield sem 0x8 |
| `if sig == esperado:` | `hmac.compare_digest` |
| verificar HMAC sobre JSON re-serializado | corpo bruto |
| webhook de entrada sem assinatura "porque a URL é secreta" | assinatura + dedupe; URL secreta não é autenticação |
| bot temporário com admin esquecido | validade na tarefa; reset do token + remoção do servidor |

Fontes com data de acesso: `references/fontes.md`.
