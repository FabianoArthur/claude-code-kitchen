# Fontes — seguranca-web-front

Acesso de todas: **2026-09-23**. Versões no registry npm nessa data: react 19.3.0, vite 8.3.0, dompurify 3.4.16, eslint-plugin-react 7.37.5, eslint-plugin-security 4.0.1.

| fonte | o que sustenta |
|---|---|
| [OWASP ASVS 5.0.0](https://github.com/OWASP/ASVS) | V3 Web Frontend Security, V7 Session Management |
| [React — common components (`dangerouslySetInnerHTML`)](https://react.dev/reference/react-dom/components/common) | risco de XSS se a origem não for totalmente confiável |
| [React 19 `sanitizeURL.js`](https://raw.githubusercontent.com/facebook/react/v19.0.0/packages/react-dom-bindings/src/shared/sanitizeURL.js) | `javascript:` bloqueado ("React has blocked a javascript: URL…") |
| [React CHANGELOG 16.9](https://github.com/facebook/react/blob/main/CHANGELOG.md) | depreciação de `javascript:` URLs (no 18 era só aviso no build open source) |
| [DOMPurify](https://github.com/cure53/DOMPurify) | `DOMPurify.sanitize()`; `RETURN_TRUSTED_TYPE` |
| [MDN — CSP](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CSP) | CSP estrita com nonce, `strict-dynamic`, `frame-ancestors` |
| [OWASP CSP CS](https://cheatsheetseries.owasp.org/cheatsheets/Content_Security_Policy_Cheat_Sheet.html) | `object-src 'none'; base-uri 'none'`; `frame-ancestors` não funciona em `<meta>`; `Report-Only` |
| [MDN — Trusted Types](https://developer.mozilla.org/en-US/docs/Web/API/Trusted_Types_API) | Baseline 2026; `require-trusted-types-for 'script'` |
| [Vite — Env variables and modes](https://vite.dev/guide/env-and-mode) | `VITE_*` não deve conter informação sensível: vai para o bundle |
| [Vite — shared options (`envPrefix`)](https://vite.dev/config/shared-options) | `envPrefix: ''` expõe tudo e o Vite dá erro |
| [Vite — build options (`build.sourcemap`)](https://vite.dev/config/build-options) | padrão `false`; `'hidden'` |
| [OWASP Session Management CS](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html) | não guardar token/JWT/refresh em `localStorage`/`sessionStorage`; cookie `Secure`/`HttpOnly`/`SameSite` |
| [OWASP HTML5 Security CS](https://cheatsheetseries.owasp.org/cheatsheets/HTML5_Security_Cheat_Sheet.html) | não guardar identificador de sessão em local storage; um XSS rouba tudo |
| [OWASP HTTP Headers CS](https://cheatsheetseries.owasp.org/cheatsheets/HTTP_Headers_Cheat_Sheet.html) | valores de HSTS, nosniff, Referrer-Policy, Permissions-Policy, COOP; `X-XSS-Protection` ausente ou 0 |
| [OWASP Secure Headers Project](https://owasp.org/www-project-secure-headers/) | catálogo de headers |
| [MDN HTTP Observatory](https://developer.mozilla.org/en-US/observatory) · [FAQ](https://developer.mozilla.org/en-US/observatory/docs/faq) | Mozilla Observatory antigo desligado em out/2024 |
| [eslint-plugin-react `no-danger`](https://github.com/jsx-eslint/eslint-plugin-react/blob/master/docs/rules/no-danger.md) | regra contra props perigosas |
| [eslint-plugin-security](https://github.com/eslint-community/eslint-plugin-security) | config recomendada; muitos falsos positivos (mais útil no back Node) |
| [semgrep registry `p/react`](https://semgrep.dev/c/p/react) | inclui `react-dangerouslysetinnerhtml` |

## Medições locais (2026-09-23, só leitura, grep de código)

- Os greps da skill foram rodados em dois frontends reais (React 19 + Vite e CRA); os nomes dos projetos foram removidos desta cópia pública. Resultados típicos: poucos `dangerouslySetInnerHTML` (um deles CSS de config do shadcn/ui), um `href` dinâmico vindo de mensagem de IA, alguns `innerHTML` (a maioria só com SVG/classes do código, um interpolando dado da API) e tokens em `localStorage`.
- Grep de token só com string literal: 0 achados (falso negativo); com constante (`getItem(ACCESS_TOKEN)`): 13.
- Função `seguro()` da §1 testada no Node com 8 casos (https, relativa, mailto, `javascript:`, `JavaScript:` com espaço, `data:`, `vbscript:`, URL malformada): 0 falhas.

## Não confirmado

- Se `react/no-danger` está no preset `recommended` (a skill manda ligar explicitamente).
- Método e parâmetros exatos da API v2 do MDN Observatory (a skill não usa a API).
- Restrição atual da chave do Google Maps no console: não é verificável pelo código.
