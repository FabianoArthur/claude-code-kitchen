# Fontes — seguranca-api

Acesso de todas: **2026-09-23**. Versões conferidas no registry (npm/PyPI) nessa data.

## Padrões e listas

| fonte | o que sustenta |
|---|---|
| [OWASP API Security Top 10 2023](https://api-security.owasp.org/editions/2023/en/0x11-t10) | API1–API10; 2023 é a edição vigente (o site lista só 2019 e 2023) |
| [OWASP API3:2023 BOPLA](https://api-security.owasp.org/editions/2023/en/0xa3-broken-object-property-level-authorization) | mass assignment + exposição de propriedade; evitar serialização genérica |
| [OWASP ASVS 5.0.0 (repo oficial)](https://github.com/OWASP/ASVS) | versão estável 5.0.0, maio/2025; capítulos V1–V17 em `5.0/en/` |
| [OWASP Mass Assignment CS](https://cheatsheetseries.owasp.org/cheatsheets/Mass_Assignment_Cheat_Sheet.html) | allowlist de campos, DTOs |
| [OWASP Error Handling CS](https://cheatsheetseries.owasp.org/cheatsheets/Error_Handling_Cheat_Sheet.html) | resposta genérica, detalhe só no log |
| [OWASP REST Security CS](https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html) | HTTPS só; 413/415/429; headers de API (`no-store`, `nosniff`, `frame-ancestors`) |
| [OWASP JWT CS](https://cheatsheetseries.owasp.org/cheatsheets/JSON_Web_Token_Cheat_Sheet.html) | rejeitar `alg: none`; revogação por `jti` |
| [RFC 8725 — JWT BCP](https://www.rfc-editor.org/rfc/rfc8725.html) | §3.1 algoritmo definido pelo chamador; §3.8/3.9 `iss`/`aud` |
| [draft-ietf-oauth-rfc8725bis](https://datatracker.ietf.org/doc/draft-ietf-oauth-rfc8725bis/) | sucessor da 8725, -10 (21/08/2026), enviado ao IESG; ainda não é RFC |
| [RFC 9457 — Problem Details](https://www.rfc-editor.org/rfc/rfc9457) | formato de erro (substitui a 7807) |

## NestJS / Mongoose

| fonte | o que sustenta |
|---|---|
| [NestJS — Validation](https://docs.nestjs.com/techniques/validation) | `whitelist`, `forbidNonWhitelisted`, `transform` |
| [NestJS — Guards](https://docs.nestjs.com/guards) | guard global via `APP_GUARD` |
| [NestJS — Rate limiting](https://docs.nestjs.com/security/rate-limiting) | `ThrottlerModule`, `ThrottlerGuard`; `ttl` em ms; formato `{ throttlers: [...] }` |
| [@nestjs/throttler 6.7.0 no npm](https://www.npmjs.com/package/@nestjs/throttler) | README com `forRoot([{ ttl, limit }])`; "ttl, the time to live in milliseconds" |
| [NestJS — Helmet](https://docs.nestjs.com/security/helmet) | `app.use(helmet())`; registrar antes das rotas |
| [NestJS — CORS](https://docs.nestjs.com/security/cors) | `enableCors()` com opções do pacote `cors` |
| [NestJS — Serialization](https://docs.nestjs.com/techniques/serialization) | `ClassSerializerInterceptor` + `@Exclude`; handler precisa devolver instância |
| [Mongoose — `set()` (sanitizeFilter, strictQuery)](https://mongoosejs.com/docs/api/mongoose.html) | `sanitizeFilter` desligado por padrão, envolve chave `$` em `$eq`; `strictQuery` `false/true/'throw'` |
| [Mongoose — Guide](https://mongoosejs.com/docs/guide.html) | `strictQuery` false por padrão desde o Mongoose 7 |

## FastAPI / Pydantic

| fonte | o que sustenta |
|---|---|
| [FastAPI — OAuth2 com JWT](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/) | `OAuth2PasswordBearer`; `jwt.decode(..., algorithms=[ALGORITHM])`; PyJWT + pwdlib/Argon2 |
| [FastAPI — CORS](https://fastapi.tiangolo.com/tutorial/cors/) | curinga proibido com `allow_credentials=True` |
| [FastAPI — Response Model](https://fastapi.tiangolo.com/tutorial/response-model/) | saída limitada e filtrada pelo modelo; "particularly important for security" |
| [FastAPI — Advanced Middleware](https://fastapi.tiangolo.com/advanced/middleware/) | `TrustedHostMiddleware`, `HTTPSRedirectMiddleware` |
| [Pydantic — ConfigDict](https://pydantic.dev/docs/validation/latest/api/pydantic/config/) | `extra='forbid'` → `extra_forbidden` |
| [slowapi](https://slowapi.readthedocs.io/en/latest/) | `Limiter`, `@limiter.limit`, ordem dos decorators, `request: Request` |
| Starlette `middleware/cors.py` (lido no venv, 2026-09-23) | curinga + credenciais ecoa a origem (`allow_all_origins and allow_credentials` → `allow_explicit_origin`) |

## Ferramentas

| ferramenta | versão conferida | fonte |
|---|---|---|
| semgrep CLI | 1.178.0 | [PyPI](https://pypi.org/project/semgrep/) · [CLI reference](https://docs.semgrep.dev/cli-reference) (`--error`, `--metrics`) |
| rulesets | `p/owasp-top-ten`, `p/nodejs`, `p/typescript`, `p/expressjs`, `p/python`, `p/fastapi` (1 regra); `p/nestjs` vazio | [registry](https://semgrep.dev/r) (`https://semgrep.dev/c/p/<nome>`) |
| @nestjs/core | 12.1.0 é o latest (conferido em 2026-09-23; muitos projetos ainda usam 11) | npm |
| mongoose | 9.10.2 | npm |
| fastapi / pydantic / slowapi | 0.141.1 / 2.13.5 / 0.1.10 | PyPI |

## Relação com outras skills

- Uma skill de design de APIs (contrato, paginação, idempotência): esta skill não repete, audita.
- `security-review` (embutida no Claude Code): revisão geral do diff; esta skill dá os comandos específicos da stack.

## Não confirmado

- Se a v6 do throttler aceita as duas formas de `forRoot` (por isso a skill manda seguir o README da versão instalada).
- Diferenças NestJS 11 → 12 nas APIs citadas.
- semgrep não foi executado nesta pesquisa (não instalado no Mac); os comandos seguem a CLI reference.
