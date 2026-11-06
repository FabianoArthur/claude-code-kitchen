---
name: seguranca-web-front
description: Use quando for escrever ou revisar front React/Vite que renderiza conteúdo de usuário ou de IA, guarda token, lê variável de ambiente ou vai para produção — XSS, CSP, headers, token no browser, VITE_* no bundle, source map. Sintomas de que precisa: dangerouslySetInnerHTML com dado de fora, href vindo de API/markdown/IA, token ou refresh token em localStorage, chave "secreta" em VITE_* ou REACT_APP_*, .map publicado em produção, site sem Content-Security-Policy, X-XSS-Protection ainda configurado.
---

# Segurança no front — React 19 + Vite

## Visão geral

No front, **tudo o que vai para o browser é público**: bundle, variáveis `VITE_*`, source map, `localStorage`. A pergunta de cada item é "se houver um XSS, o que ele leva?" e "o que um curioso lê no DevTools?". Referência: ASVS 5.0 V3 Web Frontend Security e V7 Session Management; OWASP Cheat Sheets de XSS Prevention, CSP, HTML5 Security, Session Management e HTTP Headers.

## 1. XSS

React escapa texto por padrão. Os buracos são as saídas explícitas.

```bash
grep -rnE 'dangerouslySetInnerHTML' --include='*.tsx' --include='*.jsx' src
grep -rnE '\.innerHTML *=|outerHTML *=|insertAdjacentHTML|document\.write' --include='*.ts' --include='*.tsx' src
grep -rniE 'href=\{[^}]*(url|link|href)|src=\{[^}]*(url|link)' --include='*.tsx' src
```

**Esperado:** cada `dangerouslySetInnerHTML` recebe HTML de fonte **confiável e estática** (ex.: CSS gerado de config, como o `chart.tsx` do shadcn/ui) **ou** passa por `DOMPurify.sanitize()` (3.4.16) antes. HTML vindo de API, markdown ou IA sem sanitizar = achado. O mesmo vale para `el.innerHTML = \`…${valor}…\`` fora do React (marcadores de mapa): é comum um componente de mapa que interpola `city` ou `assetId` vindos da API num template de `innerHTML`; para texto, use`textContent`.

**`href` dinâmico:** o React 19 **bloqueia** `javascript:` em atributos de URL (troca por uma URL que lança erro; no 18 só avisava). Não bloqueia `data:` nem outros esquemas. Link vindo de API, markdown ou resposta de IA (ex.: o `href` de um componente de bolha de mensagem de chat) passa por allowlist de esquema:

```ts
const seguro = (u: string) => { try { return ['https:', 'http:', 'mailto:'].includes(new URL(u, location.origin).protocol) ? u : '#'; } catch { return '#'; } };
```

e ganha `rel="noopener noreferrer"` quando abre em nova aba.

Lint: `react/no-danger` e `react/jsx-no-script-url` (eslint-plugin-react) no config. Varredura: `semgrep scan --config p/react --config p/javascript --metrics=off src` (o `p/react` traz `react-dangerouslysetinnerhtml`).

## 2. Onde guardar token

```bash
grep -rniE '(localStorage|sessionStorage)\.(setItem|getItem)\( *[^,)]*(token|jwt|auth|access|refresh)' --include='*.ts' --include='*.tsx' src
```

**Esperado:** vazio. O OWASP Session Management Cheat Sheet: não guardar token de autenticação, JWT nem refresh token em `localStorage`/`sessionStorage`, porque um único XSS lê tudo. O alvo: refresh token em cookie `HttpOnly; Secure; SameSite=Lax` (ou `Strict`) emitido pelo back, access token curto **em memória**, CORS com origem explícita + `credentials`, e CSRF tratado onde `SameSite` não bastar.

Achado comum: um `AuthContext` que guarda access e refresh token no `localStorage` (mais de uma dezena de ocorrências, inclusive indiretas via um registry de storage). É mudança de contrato front↔back; enquanto não sai, a CSP da §4 é o que reduz o risco.

O grep casa com **constante** (`getItem(ACCESS_TOKEN)`), não só com string literal. Uma versão que procurava só string literal deu 0 num front que usava constante e errou (falso negativo medido).

## 3. Variáveis de ambiente no bundle

```bash
grep -rhoE 'import\.meta\.env\.VITE_[A-Z0-9_]+|process\.env\.REACT_APP_[A-Z0-9_]+' --include='*.ts' --include='*.tsx' src | sort -u
grep -rnE --include='vite.config.*' --exclude-dir=node_modules --exclude-dir=.git 'envPrefix|define:' .
```

**Esperado:** nenhuma variável cujo nome sugira segredo (`SECRET`, `PRIVATE`, `PASSWORD`, `SERVICE_ROLE`, `ADMIN`). A doc do Vite: `VITE_*` "should not contain sensitive information… bundled into your source code at build time". `envPrefix: ''` expõe **todas** as variáveis (o Vite recusa esse valor).

Chave que **precisa** estar no browser (Google Maps: `VITE_GOOGLE_MAPS_API_KEY` em Vite, `REACT_APP_GOOGLE_MAPS_API_KEY` em CRA) não é segredo, é identificador. A proteção dela é **restrição por HTTP referrer e por API** no console do Google Cloud, e cota. Confira no console; o código não prova isso.

Prova no build: `npm run build && grep -rlE '<parte-do-valor-de-uma-variável-secreta-do-back>' dist/` → vazio. Rode com um valor que só existe no `.env` do back.

## 4. CSP e headers

```bash
curl -sI https://<host-do-front> | grep -iE '^(content-security-policy|strict-transport-security|x-content-type-options|referrer-policy|permissions-policy|cross-origin-opener-policy|x-frame-options|x-xss-protection)'
```

**Esperado** (OWASP HTTP Headers Cheat Sheet):

- `Content-Security-Policy` presente. Para SPA Vite servida como estático, o viável é `script-src 'self'` (ou hashes). Nonce exige servidor gerando a resposta por request. Sempre `object-src 'none'; base-uri 'none'; frame-ancestors 'none'`. `frame-ancestors` **só funciona no header**, não em `<meta>`. Comece com `Content-Security-Policy-Report-Only`.
- `Strict-Transport-Security: max-age=63072000; includeSubDomains` (`preload` só com decisão consciente)
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy`: desligar o que não usa (`camera=(), microphone=()`; `geolocation` só se o app usa)
- `Cross-Origin-Opener-Policy: same-origin`
- `X-XSS-Protection` **ausente ou `0`** (depreciado; ligado pode até atrapalhar)

Onde configurar: no servidor/CDN que entrega o `index.html` (nginx do Dockerfile, CloudFront response headers policy), não no React. Nota geral: MDN HTTP Observatory (o antigo Mozilla Observatory foi desligado em out/2024).

Trusted Types (`require-trusted-types-for 'script'`) virou Baseline 2026: com ele, atribuir string a `innerHTML` lança erro. Bom próximo passo depois da CSP.

## 5. Source map e o que o build publica

```bash
grep -rnE --include='vite.config.*' --exclude-dir=node_modules --exclude-dir=.git 'sourcemap' .
npm run build >/dev/null && find dist -name '*.map' | head
```

**Esperado:** `build.sourcemap` ausente/`false` (padrão) ou `'hidden'` (gera o `.map` sem referência no bundle, para subir só no Sentry). Nenhum `.map` em `dist/` que vá para o CDN. Conferido: `sourcemap: false` explícito ou ausente (padrão `false`) é o esperado.

## 6. Dependências do front

`npm audit --omit=dev --audit-level=high` e `osv-scanner scan source -L package-lock.json`: ver `seguranca-dependencias`. No front, dependência de runtime (`dependencies`) vai para o browser de todo usuário.

## Anti-padrões → correção

| anti-padrão | correção |
|---|---|
| `dangerouslySetInnerHTML={{__html: resposta.html}}` | `DOMPurify.sanitize()`, ou renderizar como texto |
| `<a href={link}>` com link de API/IA | allowlist de esquema + `rel="noopener noreferrer"` |
| refresh token em `localStorage` | cookie `HttpOnly; Secure; SameSite` |
| `VITE_API_SECRET` | segredo fica no back; o front chama o back |
| chave do Maps sem restrição | restrição por referrer e por API no console |
| CSP em `<meta>` esperando proteger contra framing | `frame-ancestors` no header |
| `X-XSS-Protection: 1; mode=block` | remover (ou `0`) e usar CSP |
| `.map` no CDN | `sourcemap: false` ou `'hidden'` |

## Checklist de PR de front

- [ ] nenhum `dangerouslySetInnerHTML` novo com dado de fora sem DOMPurify
- [ ] `href`/`src` dinâmico com allowlist de esquema
- [ ] nada de token novo em web storage
- [ ] nenhuma `VITE_*` nova com cara de segredo
- [ ] build sem `.map` público

Fontes com data de acesso: `references/fontes.md`.
