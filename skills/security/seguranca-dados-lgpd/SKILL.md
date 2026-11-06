---
name: seguranca-dados-lgpd
description: Use quando for criar, guardar, logar, exportar ou apagar dado pessoal — tripulação, posição de embarcação ligada a quem estava a bordo, e-mail, telefone, CPF, dado de login — ou quando um incidente puder ter exposto esse dado. Sintomas de que precisa: e-mail ou CPF em log, coleção guardando mais campos do que a tela usa, telemetria de posição sem prazo de retenção, dump de produção copiado para máquina de dev, "não sabemos quem tem acesso a esse dado", vazamento sem saber se precisa avisar a ANPD e em quanto tempo.
---

# Dados pessoais e LGPD — o que um time pequeno faz na prática

## Visão geral

Não é parecer jurídico. É o mínimo técnico que a Lei 13.709/2018 (LGPD) e as resoluções da ANPD pedem de quem desenvolve, com o comando que mostra se está sendo feito. Dúvida de enquadramento (base legal, porte, alto risco) vai para quem responde juridicamente pela empresa. A skill só aponta onde a dúvida está.

Atualização de 2026: a ANPD passou a ser **Agência** Nacional de Proteção de Dados (MP 1.317/2025, convertida na Lei 15.352/2026). As resoluções continuam numeradas "CD/ANPD".

## 1. O que é dado pessoal aqui

Art. 5º I: "informação relacionada a pessoa natural identificada ou identificável". Num sistema de monitoramento de frota e tripulação (o exemplo que guiou esta skill):

| dado | por quê |
|---|---|
| nome, e-mail, telefone, CPF de tripulante e usuário | identifica direto |
| **escala de tripulação** (quem estava a bordo e quando) | identifica e liga pessoa a lugar e horário |
| **posição da embarcação** (rastreador GPS, telemetria) | vira dado pessoal do tripulante quando cruzada com a escala: dá para saber onde **uma pessoa** estava. *Inferência do art. 5º I; não há guia específico da ANPD sobre geolocalização de empregados.* |
| dado de login (senha, hash, token) | a Res. 15/2024 lista "dados de autenticação em sistemas" entre os que tornam um incidente comunicável |
| log de acesso com IP + usuário | identifica |

Bases legais prováveis para dado de tripulação (art. 7º): **II** obrigação legal/regulatória, **V** execução de contrato (de trabalho), **IX** legítimo interesse (que pede o registro do art. 37 com mais cuidado). Consentimento em relação de emprego é base frágil (assimetria); confirme com o jurídico antes de usá-la.

## 2. Minimização: coletar e guardar o mínimo (art. 6º III)

```bash
# campos de PII declarados nos schemas/models
grep -rnE '(email|cpf|phone|telefone|birth|nascimento|address|endereco|rg)\b' --include='*.schema.ts' --include='*.model.ts' --include='*.entity.ts' --include='models.py' --include='schemas.py' -i src backend app 2>/dev/null | wc -l
# o que sai na resposta da API (DTO/response_model): o mesmo campo aparece?
```

**Esperado:** o número não cresce num PR sem justificativa (sem `| wc -l`, a lista mostra onde cada campo mora; num backend auditado em 2026-09-23 eram 2 linhas). **Pergunta de review:** cada campo pessoal novo tem uso na tela ou numa obrigação? Se não, não entra. Resposta de API devolve só o que a tela usa (DTO de saída / `response_model`: ver `seguranca-api` §2).

**Logs sem PII** (OWASP Logging Cheat Sheet: excluir, mascarar ou hashear identificadores, tokens, senhas, strings de conexão):

```bash
grep -rnE '(logger|log|console)\.(log|info|debug|warn|error)\(.*(email|cpf|phone|telefone|password|senha|token)' -i \
  --include='*.ts' --include='*.py' --exclude-dir=venv --exclude-dir=.venv --exclude-dir=node_modules src backend app 2>/dev/null
```

**Esperado:** vazio, ou só mensagens sem o valor ("Verifying token" é ok; `sent to ${email}` não). Medido em 2026-09-23: um backend NestJS tinha 8 ocorrências, 3 com e-mail de usuário em claro (use case de reset de senha e serviços de envio de e-mail); um backend FastAPI tinha 0.

**Varredura de arquivo de log ou export** (detector testado em `references/pii_scan.py`: CPF com dígito verificador, e-mail, telefone BR; imprime só o valor mascarado):

```bash
python3 skills/security/seguranca-dados-lgpd/references/teste_pii_scan.py          # 6 testes, "falhas: 0"
python3 skills/security/seguranca-dados-lgpd/references/pii_scan.py <arquivo-ou-dir>; echo "rc=$?"
```

**Esperado:** `rc=0` e `achados: 0`. `rc=1` lista `tipo  arquivo:linha  valor-mascarado`. Triagem: e-mail de sistema (`noreply@…`) não é dado pessoal. Rodado num repo de automação: 3 achados, todos `noreply@anthropic.com` das linhas `Co-Authored-By`. Heurística: não acha nome, endereço nem coordenada. Para PII em texto livre há o Presidio (agora em `data-privacy-stack/presidio`, v2.2.364), mas ele vem pronto só para inglês e **não tem CPF/CNPJ**: exige recognizer próprio e modelo de português.

## 3. Retenção e descarte

```bash
# TTL no Mongo: coleções com expiração automática
grep -rnE 'expireAfterSeconds|expires:' --include='*.ts' src
# Postgres/SQLAlchemy: rotina de purge?
grep -rnE 'DELETE FROM|\.delete\(\).*(created_at|timestamp)|purge|retention|retencao' -i --include='*.py' --exclude-dir=venv backend app
```

**Esperado:** telemetria de posição, logs de acesso e dados de ex-tripulantes com prazo definido e mecanismo (TTL/purge). Série temporal: descarte por partição, não `DELETE` massivo. Prazo é decisão de negócio/jurídico; a skill cobra que **exista** e esteja no código.

## 4. Acesso e cópias

- **Dump de produção em máquina de dev** é tratamento. Se precisa de dado realista, anonimize na origem (troque nome/e-mail/CPF, reduza a precisão da posição) antes de copiar.
- Usuário do banco por aplicação e por ambiente, com role mínima (ver `seguranca-infra` §4). MFA em Atlas, GitHub e painel de nuvem (o guia da ANPD para pequeno porte pede MFA em sistema com dado pessoal).
- Backup com dado pessoal: cifrado, em local separado e **não sincronizado em tempo real** (proteção contra ransomware, guia ANPD).
- Transmissão sempre por TLS.

## 5. Direitos do titular (art. 18) — dá para cumprir?

Confirmação, acesso, correção, anonimização/eliminação do excessivo, portabilidade, informação sobre compartilhamento. Na prática, para cada coleção com dado pessoal: **dá para achar tudo de uma pessoa por um identificador e exportar/apagar?** Se o dado da pessoa está espalhado sem chave comum, o pedido vira arqueologia. Registre onde cada dado pessoal mora (é o "registro das operações" do art. 37; agente de pequeno porte pode fazê-lo de forma simplificada).

## 6. Incidente com dado pessoal: prazo

Resolução CD/ANPD nº 15/2024:

- **Quando comunicar:** incidente que possa afetar significativamente direitos **e** envolva pelo menos um de: dado sensível; de criança, adolescente ou idoso; financeiro; **de autenticação em sistemas**; sob sigilo; **em larga escala**.
- **Prazo:** **3 dias úteis** para a ANPD **e** para o titular, contados de quando se soube que o incidente afetou dado pessoal. Complementação em 20 dias úteis. **Agente de pequeno porte: prazo em dobro.** Enquadramento como pequeno porte (Res. CD/ANPD nº 2/2022): microempresa, EPP ou startup, **fora** de tratamento de alto risco. Monitorar a localização de pessoas pode pesar no critério de alto risco; confirme com o jurídico.
- **Registro:** guardar registro de **todo** incidente, mesmo os não comunicados (com o motivo de não comunicar), por **no mínimo 5 anos**.
- Comunicação por formulário eletrônico da ANPD.
- Dado criptografado e ininteligível pesa a favor do controlador (art. 48 §3º).

Resposta técnica (rotação, auditoria, contenção) em `seguranca-segredos` §7. Aqui entra só o relógio: **anote a hora em que se soube.**

## 7. Encarregado (DPO)

Art. 41 manda indicar encarregado. Agente de pequeno porte é dispensado (Res. 2/2022, art. 11), **mas precisa de canal de comunicação com o titular**. Quem indica: ato formal, com substituto, contato divulgado no site, comunicação em português (Res. CD/ANPD nº 18/2024). O encarregado não responde pela conformidade; o controlador responde.

## Anti-padrões → correção

| anti-padrão | correção |
|---|---|
| `logger.info(\`… ${email}\`)` | logar id ou e-mail mascarado |
| schema com campo pessoal "para o futuro" | só o que tem uso |
| posição da embarcação guardada para sempre | retenção definida + TTL/purge |
| dump de produção no notebook | cópia anonimizada |
| "vazou, vamos ver semana que vem" | relógio de 3 dias úteis a partir do conhecimento |
| incidente pequeno sem registro | registro de todo incidente por 5 anos |
| consentimento como base para dado de empregado | base legal definida com o jurídico (contrato/obrigação legal) |

## Checklist de PR que toca dado pessoal

- [ ] campo pessoal novo tem uso; resposta da API não devolve mais que a tela usa
- [ ] nenhum log novo com PII (grep da §2)
- [ ] retenção definida para dado novo que cresce no tempo
- [ ] dado de teste/fixture sintético, nunca cópia de produção

Fontes com data de acesso: `references/fontes.md`.
