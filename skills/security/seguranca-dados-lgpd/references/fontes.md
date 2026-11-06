# Fontes — seguranca-dados-lgpd

Acesso de todas: **2026-09-23**.

## Lei e regulamentos (fontes oficiais)

| fonte | o que sustenta |
|---|---|
| [Lei 13.709/2018 (compilada, Planalto)](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm) | art. 5º I (dado pessoal) e VIII (encarregado, já com "Agência Nacional de Proteção de Dados"); art. 6º III necessidade e VII segurança; art. 7º bases legais; art. 18 direitos; art. 37 registro das operações; art. 41 encarregado; art. 46 segurança e privacy by design; art. 48 comunicação de incidente ("prazo razoável… definido pela autoridade"; §3º dados ininteligíveis) |
| [Resolução CD/ANPD nº 2/2022](https://www.gov.br/anpd/pt-br/acesso-a-informacao/institucional/atos-normativos/regulamentacoes_anpd/resolucao-cd-anpd-no-2-de-27-de-janeiro-de-2022) | agente de pequeno porte (art. 2º); exclusões e alto risco (arts. 3º–4º); registro simplificado (art. 9º); dispensa de encarregado com canal ao titular (art. 11); segurança simplificada (arts. 12–13); prazos em dobro (art. 14) |
| [Resolução CD/ANPD nº 15/2024 (texto)](https://bibliotecadigital.mj.gov.br/bitstream/1/12879/2/RES_ANPD_2024_15.html) · [formulário CIS](https://www.gov.br/anpd/pt-br/canais_atendimento/agente-de-tratamento/comunicado-de-incidente-de-seguranca-cis) | quando comunicar (art. 5º); 3 dias úteis, complementação em 20 dias úteis, pequeno porte em dobro (art. 6º); conteúdo da comunicação; ao titular (art. 9º); registro por 5 anos (art. 10) |
| [Resolução CD/ANPD nº 18/2024 (encarregado)](https://dspace.mj.gov.br/bitstream/1/13151/1/RES_ANPD_2024_18.html) | ato formal (art. 3º), substituto (art. 4º), divulgação no site (art. 9º), português (art. 13), responsabilidade do controlador (art. 17), conflito de interesse (art. 18) |
| [Guia ANPD de segurança para pequeno porte (2021)](https://www.gov.br/anpd/pt-br/centrais-de-conteudo/materiais-educativos-e-publicacoes/guia-orientativo-sobre-seguranca-da-informacao-para-agentes-de-tratamento-de-pequeno-porte) · [PDF](https://www.gov.br/anpd/pt-br/centrais-de-conteudo/materiais-educativos-e-publicacoes/guia-vf.pdf) · [checklist](https://www.gov.br/anpd/pt-br/centrais-de-conteudo/checklist-vf.pdf) | MFA em sistema com dado pessoal; backup separado e não sincronizado em tempo real; TLS |

## OWASP e ferramentas

| fonte | o que sustenta |
|---|---|
| [OWASP Logging CS](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html) | excluir/mascarar/hashear identificadores de sessão, tokens, senhas, strings de conexão, PII; neutralizar CR/LF |
| [OWASP Top 10 Privacy Risks](https://owasp.org/www-project-top-10-privacy-risks/) | P2 vazamento pelo operador, P3 resposta a incidente insuficiente, P6 exclusão insuficiente, P10 coleta desnecessária |
| [Presidio](https://github.com/data-privacy-stack/presidio) · [idiomas](https://presidio.dataprivacystack.org/analyzer/languages/) · [entidades](https://presidio.dataprivacystack.org/supported_entities/) | mudou de `microsoft/presidio` para `data-privacy-stack`; 2.2.364 (2026-07-22); padrão só inglês; sem entidade brasileira |

## Material próprio

- `references/pii_scan.py`: escrito do zero para este pacote. CPF validado pelo dígito verificador (módulo 11), e-mail e telefone BR por regex **próprias** (não vêm de fonte oficial). Testes: `teste_pii_scan.py`, 6 casos, 0 falhas, com o CPF sintético de exemplo 111.444.777-35.

## Medições locais (2026-09-23, só leitura)

- `pii_scan.py` num repo de automação → 3 achados, todos `noreply@anthropic.com` (linhas `Co-Authored-By`), exit 1.
- Grep de log com PII: backend NestJS 8 linhas (3 com e-mail de usuário em claro); backend FastAPI 0.

## Links

- 194 links deste pacote conferidos com GET em 2026-09-23: 192 com 200; `npmjs.com` devolve 403 para robô (pacote confirmado por `npm view`); a notícia da ANPD sobre a Res. 15/2024 devolveu 401 e foi retirada. O texto da resolução continua citado pela biblioteca do MJ.

## Não confirmado / inferência

- Posição de embarcação como dado pessoal do tripulante: **inferência** do art. 5º I; não há guia da ANPD sobre geolocalização ou monitoramento de empregados.
- Fragilidade do consentimento na relação de emprego: doutrina, não texto da ANPD.
- Enquadramento da sua empresa como agente de tratamento de pequeno porte e o critério de alto risco: decisão jurídica, fora do alcance da skill.
- Formato do CNPJ alfanumérico (Receita, 2026): não conferido; o `pii_scan.py` não detecta CNPJ.
