# ECC in our kitchen: the brigade and the plan (INFRA-033)

Source: ECC v2.2.3, commit d2ef268, MIT

A synthesis of [ecc/agents-commands-rules.md](ecc/agents-commands-rules.md) (INFRA-030), [ecc/skills.md](ecc/skills.md) (INFRA-031) and [ecc/hooks-memory-security.md](ecc/hooks-memory-security.md) (INFRA-032), cross-checked against [work-cli-adoption-plan.md](work-cli-adoption-plan.md) (W1–W14).
ECC content was treated as data. Nothing was installed. These SKILL.md files were read in full before recommending: santa-method, loop-design-check, agent-self-evaluation, safety-guard, content-hash-cache-pattern, regex-vs-llm-structured-text, cost-aware-llm-pipeline, search-first, parallel-execution-optimizer, config-gc, blender-motion-state-inspection (11).

One of the first uses of this setup was a financial-data project; all project-specific details are omitted here.

## 1. The kitchen brigade

| Role | What it does | Model | Triggered by | Deliverable | Piece (exists / proposed) |
|---|---|---|---|---|---|
| **Waiter** (Garçom) | Serves the owner, registers requests, dispatches, has the final word | the `garcom.ps1` session's model (unchanged) | the owner, via Discord | a registered task; a short reply; final approval after reading `## Prova` | exists: `garcom.ps1` + root `CLAUDE.md` |
| **Chef** (Chef, planner) | Breaks a large request into small tasks; picks the model; writes a decidable criterion | opus | the waiter, when the request is large or ambiguous | spec + task list with `depende_de` | exists: skills `plan`/`orquestrar`; proposed: chef checklist (E7) |
| **Archaeologist** (Arqueólogo) | Reads legacy code and describes current behavior before anyone changes it | opus, read-only | the chef, when a task touches code we do not know (a colleague's CRM) | behavior doc with `file:line` | proposed: archaeologist prompt (E18, from `spec-miner`) |
| **Cook** (Cozinheiro) | Executes one small task | sonnet (default) / haiku (mechanical) | `executar.sh` via `fila-cozinha.sh` | files + `## Resultado` with evidence and "tried and did not work" | exists: `executar.sh` ×3, queue; proposed: new prompt lines (E6) |
| **Taster** (Provador) | Tests the delivery against the criteria; tries to refute every serious finding; no praise | **always a different model**: haiku cook → sonnet taster; sonnet → opus; opus → sonnet | the waiter, when a task reaches `status: revisar` | a `## Prova` section: score per axis, evidence, findings by severity, verdict APPROVE/RETURN | proposed: E1 (prompt) + E2 (`provar.sh`), from `agent-evaluator` + `gan-evaluator` |
| **Double taster** (Provador duplo, risk inspector) | Two independent tasters, same rubric; passes only if both approve; up to 3 rounds, then the owner | sonnet + opus (different from each other; neither sees the cook's conversation) | mandatory on `erp_write: yes` and on any deliverable that goes to a client | 2 JSON verdicts + a final verdict in `## Prova` | proposed: E5 (`provar.sh --duplo`), from `santa-method`/`santa-loop` |
| **Station tasters** (Provadores de estação) | The stack's checklist added to the taster's rubric | the taster's model | `provar.sh`, by project folder | checklist items inside `## Prova` | proposed: Python (E3: data projects, agents), web (E4: CRM, TJO), 3D (E21, only with the owner's OK). Flutter postponed |
| **Maître** (Maître, watcher) | Watches tmux, posts to Discord, flags stalled/waiting sessions, escalates | none (Python) | `vigia.sh` every 30 s | Discord cards, `estado.json` | exists: `vigia_tmux.py` (`travou_minutos`, heartbeat), W8, W12; proposed: escalation (E14) and process-tree cleanup (E10) |
| **Security inspector** (Fiscal de segurança) | Denies a dangerous command before it runs | none (Python hook) | every cook tool call (`COZINHA_ID`) | denial + `guarda.log` | W3–W6 (`guarda_cozinha.py`); proposed: extra rules (E11) and a jsonl log (E12) |
| **Doorman** (Porteiro) | Cleans external text (invisible Unicode/bidi, HTML comments) before anyone reads it | none (Python) | the cook/waiter on receiving an attachment, Discord or ClickUp | cleaned text + a count of what was removed | proposed: `sanear_texto.py` (E9) |
| **Cashier** (Caixa) | Counts tokens and context; warns on a loop of identical calls | none (Python) | the watcher (tick) and a hook | tokens in `estado.json`; a warning at ~160k/250k and at 5 identical calls | W7–W9; proposed: context/loop monitor (E13) |
| **Pantry keeper** (Despenseiro) | Decides what becomes memory, promotes and prunes | sonnet | skills `salvar`/`colher` at the end of a task | memory with `visto_em`, a prune list | exists: `salvar`/`colher`; proposed: E16 (needs the owner's OK) |
| **Dishwasher/porter** (Copeiro, cleanup) | Removes dead code and simplifies without changing behavior | haiku (sonnet if not mechanical) | the chef, as its own task after a large delivery | smaller diff + identical tests before/after | proposed: dishwasher prompt (E19), from `code-simplifier`/`refactor-cleaner` |
| **Storekeeper** (Almoxarife) | Monthly audit of skills/config/rules; proposes new guard rules from the logs | haiku, read-only | the waiter, once a month | a report; nothing deleted | proposed: E20 (from `config-gc`) and E15 (from `conversation-analyzer`) |

**Where the model must differ:** the simple taster is always a different model from the cook (the `ai-regression-testing` rule: the author must not be the only tester). In the double taster, the two differ from each other and neither receives the cook's conversation, only the task and the files. The waiter no longer reviews from scratch: it reads `## Prova` and checks the numbers it cites.

## 2. What to bring in (by gain)

| # | Item | ECC origin | Who benefits | Effort | Task |
|---|---|---|---|---|---|
| 1 | A different-model taster with a 5-axis rubric, mandatory evidence for a score below 5, findings by severity, "try to refute" the serious ones | agent-evaluator, gan-evaluator (evaluator only), rules `common/code-review.md`, contexts "group by severity", workflows "refute", agent-self-evaluation, ai-regression-testing (principle) | all | M | E1, E2 |
| 2 | Lines in the cook's prompt: destructive patterns, write only in the task folder, look for what already exists, the evidence rule, "tried and did not work" | safety-guard (Careful + Freeze), search-first, agent-self-evaluation, longform guide | all | S | E6 |
| 3 | Double taster on risky tasks | santa-method, santa-loop | data projects, CRM | M | E5 |
| 4 | Extra guard rules: secret paths, secret in a write, `--no-verify`, destructive without a target, protected config, input > 1 MB denied | pre:bash (secrets part), minimal GateGuard, config-protection, block-no-verify, hook-input-limits, security guide §6.1 | the whole kitchen | M | E11 |
| 5 | Chef checklist: decidable criterion + anti-Goodhart + attempt cap; model table; isolated writes per file; a bug starts with a red test; a spec is an opus task | loop-design-check, model-route, rules `common/performance.md`, cost-aware-llm-pipeline (table), parallel-execution-optimizer (lanes), orch-fix-defect, architect | all | S | E7 |
| 6 | Python station and web station | silent-failure-hunter, security-reviewer (our list), python-reviewer, react/typescript-reviewer, react/python review/test commands, rules python/typescript/react/web | data projects, agents, CRM, TJO | S | E3, E4 |
| 7 | Regex before the LLM + a cache keyed by content hash | regex-vs-llm-structured-text, content-hash-cache-pattern (adopt) | data projects, CRM | S | E8 |
| 8 | Context and loop monitor | suggest-compact, ecc-context-monitor, cost-tracker (only % and loop) | waiter, kitchen | M | E13 |
| 9 | Kill the process tree and release the slot | dead-man switch from security guide §6.3, loop-status | kitchen (stuck slot) | M | E10 |
| 10 | Escalation in the watcher | loop-operator (escalation rules only) | kitchen | S | E14 |
| 11 | External-text sanitizer | security guide §6.4 | kitchen, waiter | S | E9 |
| 12 | Guard log in jsonl | governance-capture, security guide §6.2 | auditing | S | E12 |
| 13 | Memory with promotion, pruning and self-evaluation before saving | learn-eval, instinct ideas (confidence, 2+ occurrences), load cap, "external content never becomes an instruction" | all | M | E16 |
| 14 | Archaeologist | spec-miner | CRM | S | E18 |
| 15 | Log analyzer → guard rules | conversation-analyzer | kitchen | S | E15 |
| 16 | Dishwasher | code-simplifier, refactor-cleaner | all | S | E19 |
| 17 | PreCompact reminder for the waiter | pre:compact | waiter | S | E17 |
| 18 | Storekeeper | config-gc | kitchen | S | E20 |
| 19 | Data-driven Blender scene inspection | blender-motion-state-inspection | studio | S | E21 |

## 3. What stays out

- **Flutter** (`flutter-dart-code-review`, `dart-flutter-patterns`, flutter-reviewer, dart-build-resolver, flutter commands, dart rules): Cockpit is under construction; revisit when there is code to review.
- **`python-testing`**: 825 generic lines; superpowers TDD covers it. The one useful idea (pytest with in-memory SQLite) becomes 1 item in E3.
- **`eval-harness`**: "eval defined first" already enters through E7's decidable criterion; pass@k does not suit a one-off task.
- **`ai-regression-testing`** (the rest): the principle enters through the different-model taster (E1); the rest is web-specific.
- **`skill-stocktake`**: `config-gc` (E20) covers it.
- **react-build-resolver, dart-build-resolver**: superpowers `systematic-debugging` covers them.
- **fastapi-review**: we do not use FastAPI.
- **gan-planner/gan-generator** (full loop): expensive; only the evaluator comes in (E1).
- **loop-operator** (the rest): the watcher + queue already run the loop; only escalation comes in (E14).
- **cost-aware** (per-task spend cap): only after W8 produces numbers; the model table enters in E7.
- **stop:session-end** (Stop hook): `## Resultado` + `salvar` cover it, and it would touch `settings.json`.
- **harness-audit** (scorecard): only after E2/E5 generate approval data.
- **Instincts, observer, continuous-learning-v2, ck, unified-memory, gateguard/delivery-gate (skills), hookify**: ECC's Node/hooks; the observer does not run on Windows; they duplicate our memory and would touch settings.
- **Node hooks in general, run-with-flags, AgentShield/security-scan**: Node/npx; our versions are Python (W3, E11).
- **cost-report, token-card, cost-tracker (telemetry)**: W7–W9 and `rtk gain` cover them.
- **Orchestration** (epic/multi-*, orch-*, team-builder, autonomous-loops, plan-orchestrate, dmux-workflows, blueprint): duplicates `plan`/`orquestrar`/tmux.
- **verification-loop, terminal-ops, strategic-compact**: already covered (superpowers and "claude apagar cache").
- **Remaining common rules** (coding-style, git-workflow, testing, development-workflow…): duplicate superpowers. No rule goes into `~/.claude/rules`, because it would change every project.
- **Whole groups** (marketing, healthcare, networking, SaaS finance, other languages, Remotion/fal.ai video): outside our stack.
- **Cook network access** (egress denied / `--allowedTools` by task type, security guide §6.5): **not decided here**. It is a question for the owner (end of section 5).

## 4. Fit with work-cli

General rule: **work-cli wins on mechanism** (hook, installation, record/deny mode, tests); ECC only adds rules, prompts and roles.

| ECC proposal | Related W | Adds | Overlaps | Who wins |
|---|---|---|---|---|
| E11 extra rules | W3, W4 | secret, `--no-verify`, destructive without a target, protected config, 1 MB | "ERP DELETE/write" is already in W4 | W3 on mechanism; W4 on the ERP (E11 does not repeat it) |
| E12 jsonl | W3 (`guarda.log`), W6 (report) | per-call fields and the jsonl format | it is the same log | W3. If W3 has not run yet, E12 becomes a W3 criterion and leaves the plan |
| E13 monitor | W7 | context % and loop detector | reading tokens from the transcript | W7 (E13 imports `tokens_transcript.py`) |
| E14 escalation | W8, W12, `travou_minutos` | "no progress", repeated error, cost out of range | stalled warning and waiting re-warning | watcher/W12 (E14 does not duplicate the warning) |
| E10 process tree | W1 | kills the tree of the **finished session** and releases the slot | W1 kills only the heavy command's tree | complementary |
| E7 lanes | W10 | rule "parallel tasks do not write to the same file/table" when writing tasks | W10 checks for a shared file | W10 checks; E7 only guides the chef |
| E1/E2 taster | W14 | the taster reads the dependencies' Result through the same function | none | complementary |
| E15 analyzer | W6 | proposes **new** rules from the logs | W6 measures the existing rules | complementary |
| E6 cook prompt | W5 | security and evidence lines | the 3 `executar.sh` are the same files | do not run E6 and W5 at the same time |
| W2 limit file, W13 doctor | — | nothing new; the doctor can check the new pieces later | — | W |

## 5. Plan in small tasks

Suggested order = order of the numbers. No task file was created; the waiter registers them once the owner approves.

**E1. Taster rubric and prompt** · `modelo: sonnet` · `depende_de: —`
Deliverable: `agentes/prompts/provador.md`. Criteria: 5 axes (accuracy, completeness, verifiability, security, scope) scored 1–5; a score below 5 requires evidence (`file:line` or command + output); findings by severity, each critical one with an attempt to refute; ends with JSON `{verdict, checks[], criticals[], suggestions[]}` + a summary of ≤ 10 lines; forbids Edit/Write and any command that writes; ≤ 80 lines, pt-BR.

**E2. `provar.sh`** · `modelo: sonnet` · `depende_de: E1`
Deliverable: `agentes/provar.sh <task-path>`. Criteria: reads `modelo:` and picks a different model (haiku→sonnet, sonnet→opus, opus→sonnet); runs `claude -p --model` without Edit/Write, going through `fila-cozinha.sh`; appends the station by folder (agents/data → Python, CRM/TJO → web) if the file exists; writes the output into `## Prova` without touching `status`; refuses a task not in `revisar`; a test with a dummy task creates `## Prova`.

**E3. Python station** · `modelo: sonnet` · `depende_de: E1`
Deliverable: `agentes/prompts/estacao-python.md`. Criteria: ≤ 40 items, each with "how to verify"; silent failure (empty `except`, `pass`, a fallback that hides an error, a log without context); our security items (the ERP credentials file is never read, ERP writes only with `erp_write: yes`, the read-only ERP flag); pytest with in-memory SQLite for the project database; ECC source cited per block; pt-BR.

**E4. Web station** · `modelo: sonnet` · `depende_de: E1`
Deliverable: `agentes/prompts/estacao-web.md`. Criteria: ≤ 40 items for React 19 + Vite/TS + Express (CRM) and React (TJO); empty `catch` and unhandled promises; `Truss-CRM/data/` never committed or exposed, no push to the colleague's repo; verification by `tsc --noEmit`, lint and a scoped test (no watch); ECC source cited; pt-BR.

**E5. Double taster** · `modelo: sonnet` · `depende_de: E2`
Deliverable: a `--duplo` option in `provar.sh`. Criteria: 2 tasters (sonnet and opus) in parallel, same rubric, unable to see each other; APPROVE only if both approve; criticals merged without duplicates; the round is logged in `## Prova` and on the 3rd rejection it writes "escalate to the owner"; `erp_write: yes` forces the double taster even without the flag; a test with simulated APPROVE+RETURN outputs yields RETURN.

**E6. New lines in the cook's prompt** · `modelo: haiku` · `depende_de: —` (not together with W5)
Deliverable: an identical block in the PROMPT of the 3 `executar.sh` files (agents, data project, CRM). Criteria: do not run destructive commands (`rm -rf`, `Remove-Item -Recurse`, `del /s`, `git reset --hard`, `git checkout .`, `push --force`, `DROP`, `--no-verify`); if the task requires one, stop and explain in the Result; write only in the task/project folder; "look for what already exists in `agentes/` and in the project before creating anything"; a Result with evidence for anything not 100% done and a "tried and did not work" item; the diff shows only the block; `bash -n` passes on all 3.

**E7. Chef checklist** · `modelo: sonnet` · `depende_de: —`
Deliverable: `agentes/docs/checklist-chef.md` + 1 line in the "small tasks" section of the root `CLAUDE.md` pointing to it. Criteria: a machine-decidable criterion + "what not to do" + attempt cap and escalation; a table haiku mechanical / sonnet default / opus spec-ambiguous-architecture; parallel tasks do not write to the same file/table; a bug starts with a red test that reproduces it; a spec is its own opus task; ≤ 60 lines.

**E8. Data patterns** · `modelo: sonnet` · `depende_de: —`
Deliverable: `agentes/docs/padroes-dados.md`. Criteria: regex/parser first, the LLM only for low-confidence items, with a confidence score; reconciliation against totals (statement, invoice, bank slip); a cache keyed by the SHA-256 of the **content**, in a SQLite table, self-invalidating; a Python example with `pathlib`; 3–5 candidate scripts in the data projects/CRM (read-only, no code changes); ≤ 80 lines.

**E9. Sanitizer** · `modelo: haiku` · `depende_de: —`
Deliverable: `agentes/sanear_texto.py`. Criteria: removes zero-width/bidi (U+200B–U+200F, U+202A–U+202E, U+2066–U+2069, U+FEFF) and `<!-- -->`; reports on stderr what it removed by type; reads a file or stdin and writes UTF-8 to stdout; pt-BR accents intact (test); ≥ 10 tests; 3-line usage at the top.

**E10. Kill the tree and release the slot** · `modelo: sonnet` · `depende_de: —`
Deliverable: `agentes/encerrar_sessao.py` + PID registration in `executar.sh`. Criteria: `executar.sh` records the session's `claude` PID; at session end, `taskkill /T /F` only on the registered tree; checks name and start time before killing (never a recycled PID); the queue slot is released; log in `agentes/logs/`; a test with a dummy child process shows the child killed.

**E11. Extra guard rules** · `modelo: sonnet` · `depende_de: W3, W4`
Deliverable: new rules in `guarda_cozinha.py`/`guarda.json` + tests. Criteria: denies reading `.env`, the ERP credentials file, `.clickup_token`, `~/.claude/channels/` (Read, Grep and Bash); denies Write/Edit with a secret pattern in the content; denies `--no-verify` and `-c core.hooksPath=`; denies destructive commands without a target and edits to protected config (`discord/config.json`, `.mcp.json`, `settings*.json`, `tokens*.env`, a project's `CLAUDE.md`) unless the task says `libera_config: sim`; input > 1 MB or invalid JSON is denied (only with `COZINHA_ID`); ≥ 15 new tests, < 150 ms.

**E12. Guard log in jsonl** · `modelo: haiku` · `depende_de: W3`
Deliverable: a jsonl format for the guard log. Criteria: 1 line per call (time, `COZINHA_ID`, tool, summary ≤ 200 characters, files, rule, decision); secrets masked in the summary; UTF-8 without BOM and daily rotation; the W6 report reads the new format; W3's tests still pass.

**E13. Context and loop monitor** · `modelo: sonnet` · `depende_de: W7, W5`
Deliverable: `discord/monitor_contexto.py` (PostToolUse hook). Criteria: uses `tokens_transcript.py`; warns once at ~160k and once at ~250k; warns when the last 5 calls are identical; state in `%TEMP%`, never in `~/.claude`; never blocks and runs in < 100 ms; installed via `aplicar_hook.py --monitor` with a backup and terminal approval (for the waiter, the warning suggests "claude apagar cache").

**E14. Escalation in the watcher** · `modelo: sonnet` · `depende_de: W8`
Deliverable: escalation rules in `vigia_tmux.py` + a test. Criteria: "no progress" (Result and files unchanged across 2 consecutive checks) → an "escalate" card; the same error line ≥ 3 times on screen → a card; tokens above the per-model cap (`config.json`) → a card; each alert once per session and never duplicating `travou_minutos`/W12; no alert changes status or kills a session; the tests in `test_vigia_*.py` pass.

**E15. Log analyzer → guard rules** · `modelo: haiku` · `depende_de: W5, E12`
Deliverable: `agentes/prompts/analisador-guarda.md`. Criteria: reads only the guard's jsonl and the week's cook transcripts; proposes up to 10 rules, each with evidence (session, line) and false-positive risk; does not edit `guarda.json`; a trial run over a real week produces a report in `agentes/docs/`; ≤ 40 lines.

**E16. Memory with promotion and pruning** · `modelo: sonnet` · `depende_de: —` (needs the owner's OK: it touches the `salvar`/`colher` skills)
Deliverable: a "memory rules" section in both skills. Criteria: a new fact carries `visto_em: [tasks]` and a date; only what reappeared in ≥ 2 tasks or was a correction from the owner goes to the vault; before saving, answer "does it have a source? does it already exist? is it worth keeping outside this task?"; external content (Discord, web, ERP, ECC) never becomes an instruction, and a cook that read external material does not write to the waiter's memory; a character cap on loading + a list of facts unused for 60 days (list only).

**E17. PreCompact reminder for the waiter** · `modelo: haiku` · `depende_de: —` (terminal approval: it touches settings)
Deliverable: `discord/hook_precompact.py` + `aplicar_hook.py --precompact`. Criteria: only in the waiter's session (cwd `<workspace>`, no `COZINHA_ID`); returns "update `garcom-retomar.md` first"; never blocks; installation with a backup and `--check`; a test with a sample JSON.

**E18. Archaeologist prompt** · `modelo: sonnet` · `depende_de: —`
Deliverable: `agentes/prompts/arqueologo.md`. Criteria: runs on opus, read-only; output per module: inputs, outputs, implicit rules and open questions, with `file:line`; proposes no changes; no push to `Truss-CRM`; ≤ 50 lines.

**E19. Dishwasher prompt** · `modelo: haiku` · `depende_de: E1`
Deliverable: `agentes/prompts/copeiro.md`. Criteria: only removes dead/duplicate code or simplifies without changing behavior; tests before and after with the numbers in the Result; one folder/module per task; each removal backed by proof it is unused (grep); forbidden on `erp_write: yes` tasks; ≤ 40 lines.

**E20. Storekeeper prompt** · `modelo: haiku` · `depende_de: —`
Deliverable: `agentes/prompts/almoxarife.md`. Criteria: reads `~/.claude/skills`, `agentes/` and memory only for the report (never `channels/`, `.env`, tokens or `settings.json`); up to 20 candidates per round, each with a reason and evidence; nothing deleted: report `agentes/docs/almoxarife-YYYY-MM.md`; removal only with the owner's OK; ≤ 40 lines.

**E21. Blender checklist (studio)** · `modelo: sonnet` · `depende_de: the owner's OK for the studio`
Deliverable: a checklist in `3D/` (folder to be agreed). Criteria: state extracted with `blender.exe --background <file> --python <script>` (Windows path); limits: ground penetration > 1–2 cm, scale ± 5 %, rotation > 30°/frame; a report with inventory, orientation, a frame table and a verdict; the `.blend` is only read; ≤ 60 lines, pt-BR.

### Questions for the owner (answered in section 6)

1. **Cook network access** (INFRA-032): restrict the network or tools by task type? It may break tasks that query the ERP or ClickUp.
2. Does the taster run **every time** a task goes to `revisar` (more tokens: opus tests sonnet) or only when the waiter calls it?
3. Do we release E16, which touches the `salvar`/`colher` skills?
4. Do we release E17? It touches settings and needs terminal approval.
5. Do we release E21 while the studio is still under construction?

## 6. Owner's decisions (2026-11-16)

1. **Network:** no general network restriction. Restriction **only on MCPs**: each cook receives only the MCP tools the task needs (least privilege, per tool). A task without `mcp:` = no MCP. → **E22**.
2. **Taster at the end of the task, when the deliverable is a feature to test** (code, script, feature): the chef marks `provar: sim` and the waiter runs `provar.sh` by itself when the task comes back. Docs/analysis stay with the waiter's review (taster only if the waiter calls it). → adjusts **E2** and **E7**.
3. **Sanitary inspector (security reviewer)** joins the brigade at two moments: (a) **at planning**, before any code, it checks that the spec's architecture and solution are safe; if not, the spec goes back to the chef; (b) **at the end**, after the last part, it reviews the security of the whole (not only the last diff). opus, read-only. The PreToolUse hook (W3/E11), formerly called "security inspector", is now called the **Guard** (Guarda). → **E23**, **E24** and an adjustment to **E7**.
4. **E16 approved** (it touches `salvar`/`colher`).
5. **E17 approved** (it touches settings; the final installation is approved in the terminal).
6. **E21 approved** (checklist in `3D/docs/`).

**Adjustments:**

- **E2:** the waiter runs `provar.sh` by itself on a task with `provar: sim`; on the others, only on demand.
- **E6:** `depende_de: INFRA-037` (the same cook prompts); do not run together with E22 or W5.
- **E7:** the chef checklist includes `provar: sim` for a task that delivers a feature; a spec goes through `fiscalizar.sh --plano` before becoming tasks; the chain ends with `fiscalizar.sh --final`; an `mcp:` field with the minimum.
- **E11–E15:** depend on work-cli's W3/W4/W5/W7/W8, which still await approval (INFRA-029); they stay `bloqueada` until then.

**E22. Minimal MCP per task** · `modelo: sonnet` · `depende_de: E6`
Deliverable: an `mcp:` field in the task frontmatter (a list of tools with the exact name `mcp__server__tool`; `mcp__server__*` only with the chef's justification) + support in the executors (agents, data project, CRM, TMO). Criteria: without `mcp:` the cook starts with no MCP at all (check the servers from `.mcp.json`, plugins and claude.ai connectors, e.g. `--strict-mcp-config` with an empty config); with `mcp:` only those tools are allowed and the rest are denied; a test with a dummy cook proves both cases (it lists the available tools); Discord can never be granted to a cook; the rule is documented in each project's `_modelo.md`/convention; `bash -n` passes on the executors.

**E23. Sanitary inspector prompt** · `modelo: sonnet` · `depende_de: E1`
Deliverable: `agentes/prompts/fiscal-sanitario.md`. Criteria: a `plano` mode (before code: sensitive data, secrets, permissions and MCPs, external input, external writes such as ERP/ClickUp/push, attack surface, new dependencies) and a `final` mode (the whole chain: summed diff, config, permissions); uses the sections of ECC's security guide cited in [ecc/hooks-memory-security.md](ecc/hooks-memory-security.md); JSON output `{verdict: SAFE|ADJUST|BLOCK, findings[{severity, evidence, fix}]}` + a summary of ≤ 10 lines; read-only (no Edit/Write); ≤ 80 lines, pt-BR.

**E24. `fiscalizar.sh`** · `modelo: sonnet` · `depende_de: E2, E23`
Deliverable: `agentes/fiscalizar.sh <task> --plano | --final <chain ids>`. Criteria: runs on opus through `fila-cozinha.sh`, without Edit/Write; `--plano` writes `## Fiscal (plano)` into the spec and, if not SAFE, writes "back to the chef"; `--final` gathers the Result and files of every task in the chain and writes `## Fiscal (final)` into the last one; never changes `status`; a test with a dummy unsafe spec (e.g. a token in plain text) gives BLOCK and with a clean spec gives SAFE.
