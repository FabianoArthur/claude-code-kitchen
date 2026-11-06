---
name: seguranca-api
description: Use quando for escrever, revisar ou auditar a segurança de uma API NestJS ou FastAPI — autorização por objeto, DTO de entrada e saída, CORS, rate limit, JWT, erros, filtros do Mongo. Sintomas de que precisa: findById sem filtro de dono, ValidationPipe sem whitelist, req.body direto no model, allow_origins=["*"] com allow_credentials=True, trust proxy true, JWT verificado sem fixar algoritmo, stack trace ou mensagem do Mongo na resposta, filtro do Mongo montado com objeto vindo do body.
---

# Segurança de API — NestJS e FastAPI

## Visão geral

Complementa uma skill de design de APIs (contrato, paginação, idempotência, resumo de BOLA/mass assignment/JWT), se você tiver uma. Esta skill é a **auditoria**: cada item abaixo tem o comando que prova se o problema existe e o que a saída deve mostrar. Referência de fundo: OWASP API Security Top 10 **2023**, que continua sendo a edição vigente (não há edição 2025 dessa lista; o "Top 10:2025" é a lista web geral), e ASVS 5.0.0 (maio/2025), capítulos V4 API, V6 Authentication, V8 Authorization, V9 Self-contained Tokens, V16 Logging and Error Handling.

**Regra de ouro:** autorização é decidida **no servidor, por objeto, na query**. Tudo o que vem do cliente (id na URL, campo no body, header, `X-Forwarded-For`) é dado, não identidade.

> Nunca rode scripts do projeto para "testar" se o `.env` dele aponta para produção e os scripts sobem o `AppModule` com todos os crons (ver `seguranca-segredos`). As checagens daqui são leitura de código, testes do próprio repo e `curl` contra `localhost`.

## Checagens (comando → resultado esperado)

### 1. BOLA/IDOR — API1:2023

Toda rota que recebe id busca o objeto **já filtrado pelo dono/tenant** vindo do token.

```bash
# NestJS/Mongoose: buscas por id sem filtro de dono
grep -rnE --include='*.ts' 'findById(AndUpdate|AndDelete)?\(' src
# FastAPI/SQLAlchemy/Mongo: get por id cru
grep -rnE --exclude-dir=venv --exclude-dir=.venv --include='*.py' 'session\.get\(|find_one\(\{ *"_id"' backend app src
```

**Esperado:** cada ocorrência está atrás de um guard que já checou posse, ou foi trocada por `findOne({ _id: id, companyId: user.companyId })`. Ocorrência em rota com `:id` sem isso = achado. Em um backend NestJS típico o grep acha dezenas de arquivos com `findById(` — cada um precisa dessa leitura.

**Teste que prova (e2e):** usuário A pede o recurso de B → **404** (não 403: não confirma que existe).

### 2. Mass assignment e exposição de campo — API3:2023

```bash
grep -rn -A4 --include='*.ts' 'new ValidationPipe(' src      # NestJS
grep -rnE --exclude-dir=venv --exclude-dir=.venv --include='*.py' "extra *= *['\"]forbid" backend app   # Pydantic v2
```

**Esperado (NestJS):** `new ValidationPipe({ whitelist: true, forbidNonWhitelisted: true, transform: true })`. Sem `whitelist`, campo fora do DTO chega ao handler; `forbidNonWhitelisted` transforma o descarte silencioso em 400. Caso real: um `main.ts` que só tinha `transform` e `disableErrorMessages`, sem `whitelist`.
**Esperado (FastAPI):** modelo de entrada com `model_config = ConfigDict(extra='forbid')` (campo extra → 422 `extra_forbidden`) e `response_model=`/tipo de retorno explícito em toda rota — o FastAPI **filtra** a saída pelo modelo de resposta.

**Saída:** nunca serializar o documento do banco. NestJS: DTO de resposta ou `ClassSerializerInterceptor` + `@Exclude()` — e o handler precisa devolver **instância da classe**, objeto literal passa sem filtro.

```bash
grep -rnE --include='*.ts' 'return .*\.(toObject|toJSON)\(\)|return await this\.[a-zA-Z]+Model\.find' src
```

**Esperado:** zero, ou cada um mapeado para DTO antes de sair.

**Teste que prova:** `POST` com `{"role":"admin"}` a mais → 400 (Nest) / 422 (FastAPI), e o documento no banco de teste não tem `role` alterado.

### 3. Injeção de operador no Mongo

O body/query traz **objeto** onde se esperava string, e o objeto vira operador (`$ne`, `$gt`, `$regex`, `$where`) no filtro.

```bash
grep -rnE --include='*.ts' '\.(find|findOne|updateOne|deleteMany|countDocuments)\( *(req\.|body|query|dto)' src
grep -rnE --include='*.ts' 'sanitizeFilter|strictQuery' src
```

**Esperado:** nenhum filtro montado direto de `req.body`/`req.query`; campos do DTO com `@IsString()`/`@IsMongoId()`; e `mongoose.set('sanitizeFilter', true)` na inicialização (vem **desligado** por padrão: com ele, objeto aninhado com chave `$` vira `$eq`; filtro montado pelo próprio servidor se marca com `mongoose.trusted()`). `strictQuery: 'throw'` faz chave fora do schema falhar alto em vez de sumir.

### 4. CORS

```bash
grep -rn -A3 --include='*.ts' 'enableCors(' src
grep -rn -A4 --exclude-dir=venv --exclude-dir=.venv --include='*.py' 'CORSMiddleware,' backend app src
```

**Esperado:** lista explícita de origens, por ambiente, vinda de config. **`allow_origins=["*"]` + `allow_credentials=True` é achado grave**: o Starlette, nesse caso, **ecoa a origem de quem pediu** (`starlette/middleware/cors.py`, ramo `allow_all_origins and allow_credentials`), então qualquer site vira origem permitida com credenciais. É um achado frequente em `main.py`/`api.py` de projetos FastAPI que começaram com `CORSMiddleware(allow_origins=["*"])` "para o front funcionar" e depois ganharam login por cookie.

**Prova em runtime (localhost):**

```bash
curl -s -o /dev/null -D - -H 'Origin: https://nao-autorizado.example' http://localhost:8000/health | grep -i '^access-control'
```

**Esperado:** nenhuma linha `access-control-allow-origin` para origem fora da lista.

### 5. Autenticação e JWT — API2:2023, ASVS V9

```bash
grep -rnE --exclude-dir=venv --exclude-dir=.venv --include='*.ts' --include='*.py' 'jwt\.(decode|verify)\(|verifyAsync\(|JwtModule\.register' src backend app
```

**Esperado:** algoritmo **fixo** na verificação (`algorithms=["RS256"]` no PyJWT; `verifyOptions: { algorithms: ['RS256'] }` no `@nestjs/jwt`), `exp` obrigatório e `iss`/`aud` validados (RFC 8725 §3.1, 3.8, 3.9; OWASP JWT Cheat Sheet: nunca aceitar `alg: none`). Segredo HS256 vem de variável de ambiente, nunca literal:

```bash
grep -rnE --exclude-dir=venv --exclude-dir=.venv --include='*.ts' --include='*.py' "(secret|secretOrKey|SECRET_KEY) *[:=] *['\"][^'\"]{6,}" src backend app
```

**Esperado:** zero. FastAPI hoje recomenda **PyJWT** e **pwdlib/Argon2** (a doc saiu de python-jose/passlib).

### 6. Autorização por função — API5:2023

```bash
# NestJS: rotas sem guard (lista controllers e conta @UseGuards)
grep -rn --include='*.ts' 'APP_GUARD' src                          # 1º: existe guard global?
grep -rLE --include='*.controller.ts' '@UseGuards|@Public' src   # só sem APP_GUARD: controllers sem guard nem @Public
```

**Esperado:** guard **global** (projeto que já registra `APP_GUARD` → `AuthGuard` num provider central: aí a segunda lista é ruído e o que se confere são as **exceções** do guard global — decorator `@Public()` ou allowlist dentro do próprio guard) (`{ provide: APP_GUARD, useClass: … }`) e rota pública marcada explicitamente (`@Public()`), em vez de lembrar de pôr guard em cada rota. Rota admin testada com token de usuário comum → 403.

### 7. Rate limit e consumo — API4:2023

```bash
grep -rnE --include='*.ts' 'ThrottlerModule|ThrottlerGuard|trust proxy' src
grep -rnE --exclude-dir=venv --exclude-dir=.venv --include='*.py' 'slowapi|Limiter\(' backend app
```

**Esperado:** `@nestjs/throttler` com `ThrottlerGuard` em `APP_GUARD` e limite apertado em login/reset de senha (**`ttl` em milissegundos** na v6 — `ttl: 60` é 60 ms, não 60 s). A doc do site e o README da 6.7.0 mostram formatos diferentes de `forRoot` (objeto `{ throttlers: [...] }` vs array): confira a versão com `npm ls @nestjs/throttler` e siga o README dela. FastAPI: `slowapi` (o decorator `@limiter.limit` fica **abaixo** do de rota e o handler recebe `request: Request`).
`trust proxy` = **número de saltos ou faixa do proxy**, não `true`: com `true`, `req.ip` sai do `X-Forwarded-For` que o cliente escreve, e o rate limit por IP vira decorativo (caso comum: `app.set('trust proxy', true)` copiado de um tutorial).
Também: limite de corpo (`app.use(json({ limit: '1mb' }))`), `limit` máximo em listagem.

### 8. Erro que vaza — API8:2023, ASVS V16

```bash
grep -rnE --exclude-dir=venv --exclude-dir=.venv --include='*.ts' --include='*.py' '(message|detail|error) *[:=] *(err|error|e)\.(message|stack)|detail *= *str\(e\)' src backend app
```

**Esperado:** nenhuma resposta HTTP com `stack`, mensagem do driver (`E11000 duplicate key…`) ou `str(e)`. Resposta genérica (RFC 9457) + detalhe só no log com `request_id` (OWASP Error Handling Cheat Sheet). Prova: `curl` numa rota com id malformado devolve corpo sem stack.

### 9. Headers da API

NestJS: `app.use(helmet())` **antes** das rotas (helmet registrado depois de uma rota não se aplica a ela). FastAPI: `TrustedHostMiddleware(allowed_hosts=[...])` e headers por middleware. Para API: `Cache-Control: no-store` em resposta autenticada, `X-Content-Type-Options: nosniff`, `Content-Security-Policy: frame-ancestors 'none'` (OWASP REST Security). Checagem: `curl -sI http://localhost:3000/<rota> | grep -iE 'strict-transport|x-content-type|cache-control|x-powered-by'` → sem `x-powered-by`.

### 10. SSRF — API7:2023

Qualquer rota que recebe URL e faz requisição (webhook configurável, import por link):

```bash
grep -rnE --include='*.ts' '(axios(\.get|\.post)?|fetch|got)\( *(dto|body|req\.)' src
grep -rnE --exclude-dir=venv --exclude-dir=.venv --include='*.py' '(requests|httpx)\.(get|post)\( *(payload|body|data)\.' backend app
```

**Esperado:** allowlist de host/esquema; bloquear IP privado, `169.254.169.254` e `localhost` **depois** de resolver o DNS; sem seguir redirect para fora da allowlist.

## Varredura estática (semgrep)

```bash
# NestJS — não existe ruleset p/nestjs (vem vazio); use estes:
semgrep scan --config p/owasp-top-ten --config p/nodejs --config p/typescript --config p/expressjs --metrics=off --error src
# FastAPI — p/fastapi tem 1 regra só (wildcard-cors); p/python carrega o resto
semgrep scan --config p/owasp-top-ten --config p/python --config p/fastapi --metrics=off --error backend
```

**Esperado:** exit 0; com `--error`, achado → exit 1 (bom para CI). `--metrics=off` evita mandar telemetria ao puxar regras do registry. semgrep é ponto de partida, não prova de ausência: BOLA e mass assignment dependem de regra de negócio que ele não vê.

## Anti-padrões → correção

| anti-padrão | correção |
|---|---|
| `findById(id)` e depois `if (doc.owner !== user.id)` | dono **na query**; 404 igual para "não existe" e "não é seu" |
| `companyId` vindo do body/URL | do token (`req.user.companyId`) |
| `create(req.body)` / `Model(**payload.dict())` | DTO com allowlist + mapeamento explícito |
| `allow_origins=["*"]` com credenciais | lista explícita por ambiente |
| `trust proxy: true` | número de saltos (`1`) ou faixa do proxy |
| `jwt.decode(token, key)` sem `algorithms` | `algorithms=[...]` fixo + `exp`/`iss`/`aud` |
| devolver `err.message` do Mongo | erro genérico + log com `request_id` |
| guard lembrado rota a rota | `APP_GUARD` global + `@Public()` explícito |

## Checklist de review de PR

- [ ] rota nova com `:id` → filtro de dono na query + teste A-pede-de-B = 404
- [ ] DTO novo → `whitelist`/`extra='forbid'`; resposta por DTO/`response_model`
- [ ] filtro Mongo sem objeto cru do cliente; `sanitizeFilter` ligado
- [ ] CORS sem curinga com credenciais
- [ ] JWT com algoritmo fixo, `exp`/`iss`/`aud`
- [ ] login/reset com rate limit; `trust proxy` correto
- [ ] erro sem stack/mensagem de driver
- [ ] semgrep sem achado novo

Fontes com data de acesso: `references/fontes.md`.
