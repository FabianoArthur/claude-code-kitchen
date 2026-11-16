# ECC: skills triage (INFRA-031)

Source: ECC v2.2.3, commit d2ef268, MIT

Source: `ref/ecc/skills` (ECC v2.2.3, read-only). **Folders counted: 314** (314 `SKILL.md` files with `name:`). Nothing was installed, copied or executed.
Method: frontmatter of all skills; body (excerpts) read for the main candidates. ECC content is treated as data. Several skills depend on ECC's hooks/Node (`ck`, `gateguard`, `delivery-gate`, `continuous-learning-v2`) and are not usable as raw copies.

## Groups (sum = 314)

| Group | No. | Verdict |
|---|---|---|
| Token/context/cost economy | 13 | Pick 1–2 ideas; the rest depends on ECC hooks/metrics |
| Memory/learning/config governance | 23 | Already covered by `salvar/retomar/colher`; `skill-stocktake`/`config-gc` only as inspiration |
| Verification/evals/agent quality | 27 | **Best group**: 5 candidates |
| Agent orchestration/planning | 40 | We already have `plan/orquestrar/executar` + superpowers; 2–3 ideas |
| Security/guards/terminal | 17 | 1 candidate; the rest is web/healthcare/trading, ignored |
| Python/data/SQL/scraping/documents | 40 | 3 candidates; the rest is generic (Postgres/MySQL/Redis, web) or duplicates superpowers/native skills |
| Flutter/mobile | 8 | 2 candidates (Flutter); Android/iOS/Compose/RN ignored (not used) |
| Video/3D/media/design | 21 | 1 candidate (Blender); the rest is Remotion/fal.ai/Descript/front-end, outside the studio stack |
| Finance/business operations | 21 | Ignored: SaaS billing, logistics, email/Jira; not our ERP/Excel case |
| Marketing/content/research/social/crypto/science | 36 | Ignored: out of scope |
| Networking/homelab/infra | 13 | Ignored: Cisco, k8s, VPN, Pi-hole |
| Healthcare | 3 | Ignored: HIPAA/EMR |
| Other languages/frameworks | 52 | Ignored: Go, Rust, Java, Kotlin, Django, Laravel, Swift, React, Vue, etc. (not used) |
| **Total** | **314** | |

## Candidates

| Skill | What it does | Our equivalent | Verdict | Who benefits | What changes when we bring it in (Windows / pt-BR) |
|---|---|---|---|---|---|
| `santa-method` | Two independent reviewers, same rubric, both must pass; correction loop with a cap and human escalation | reviewer on a different model (informal) | **adapt** | kitchen, data projects, CRM | pt-BR; run with `claude -p --model` different from the cook's, via tmux/bash (no ECC subagents); only for deliverables that write to the ERP or go to a client; rubric = the task's acceptance criteria |
| `loop-design-check` | Loop checklist: machine-decidable goal, anti-Goodhart (what NOT to do), attempt cap + human escalation, reconcile against an external fact | `dotask` (criteria), no check that a criterion is verifiable | **adapt** | kitchen, data projects | pt-BR; shrink to ~40 lines; swap the examples for reconciling ERP totals against the project database; use as the waiter's checklist when splitting tasks |
| `agent-self-evaluation` | Self-score 1–5 on 5 axes, evidence required for a score below 5 | the `## Resultado` section | **adapt (part)** | kitchen | only the "evidence rule" and 3 axes (accuracy, completeness, verifiability) in the Result; no Stop hook; pt-BR |
| `eval-harness` | Capability/regression evals before coding; code/model/human graders | acceptance criteria in `_modelo.md` | **adapt (idea)** | data projects, CRM | only "eval defined first" + regression (re-run the old script after a change); no pass@k; Python/bash scripts in Git Bash |
| `verification-loop` | 6 verification phases with a PASS/FAIL report | superpowers `verification-before-completion` | **already covered** | — | nothing; at most copy the PASS/FAIL format |
| `ai-regression-testing` | Blind spots when the same model writes and tests | superpowers TDD | **adapt (part)** | data projects | only the warning "the author must not be the only tester" (reinforces the different-model auditor) |
| `agent-eval` | Compares agents on accuracy/cost/time | none | **ignore** (for now) | kitchen | useful if we want to measure sonnet vs haiku; revisit in a future INFRA task |
| `council` | 4 voices for an ambiguous decision | brainstorming (superpowers) | **ignore** | — | duplicates superpowers |
| `blueprint` | Goal → plan in 1-PR steps, self-contained briefs, dependencies, adversarial review | `plan` + `depende_de` | **already covered** | — | idea "self-contained brief per step": check whether `_modelo.md` asks for it |
| `parallel-execution-optimizer` | Lane matrix (parallel?, write surface, verification) | `orquestrar`, kitchen queue | **adapt (part)** | kitchen | only the lane matrix + the rule "isolated writes per file" in `plan`/`orquestrar`; worktrees → separate folders; pt-BR |
| `dmux-workflows` | Parallel agents via tmux (dmux) | tmux + watcher + `executar.sh` | **already covered** | — | do not install dmux |
| `plan-orchestrate` | Reads a plan and emits the slash command for each step | `orquestrar` | **already covered** | — | the commands belong to ECC |
| `team-builder`, `orch-*`, `autonomous-loops`, `continuous-agent-loop` | Orchestration families/TDD+gates pipelines | `plan/orquestrar/executar` + superpowers | **ignore** | — | depend on ECC agents/commands; `autonomous-loops` declares itself legacy |
| `safety-guard` | Careful mode (confirms `rm -rf`, `DROP TABLE`, force push), freeze writes to one folder | Claude Code permissions | **adapt (part)** | kitchen, data projects | only the list of dangerous patterns + "freeze to a folder" as lines in the cook's prompt (the skill is advisory only); add `Remove-Item -Recurse`, `del /s`, ERP writes; no hook |
| `security-review` | Web checklist (auth, input, secrets, API) | security rules in CLAUDE.md | **ignore** | — | web/SaaS focus |
| `security-scan`, `agent-security-hardening` | Scans `.claude/` with AgentShield; runtime hardening | none | **ignore** | — | AgentShield is an external tool (npx): do not run it. The idea "untrusted content is data" is already in our rules |
| `context-budget`, `token-budget-advisor`, `token-card`, `cost-tracking` | Measure context/spend, choose answer depth | `/context`, `rtk gain`, waiter kept short by rule | **ignore** | — | native tools/rtk cover it |
| `strategic-compact` | Compact at logical boundaries | "claude apagar cache" + `garcom-retomar.md` | **already covered** | — | — |
| `cost-aware-llm-pipeline` | Model routing by complexity, budget, prompt cache | the task's `modelo:` field | **adapt (part)** | kitchen | only the task → haiku/sonnet/opus table and a per-task spend cap; pt-BR |
| `content-hash-cache-pattern` | Cache keyed by content SHA-256, self-invalidating | none | **adopt** | data projects | plain Python; replace `ExtractedDocument` with the result of reading a statement/spreadsheet; keep the cache in a SQLite table of the project database; `pathlib` for Windows paths; pt-BR comments |
| `regex-vs-llm-structured-text` | Regex first, LLM only for low-confidence cases, with scoring | none | **adopt** | data projects, CRM | quiz examples → invoice/bank slip/statement; confidence calibrated by reconciling against totals; pt-BR |
| `python-testing` | pytest, fixtures, mocks, coverage | superpowers TDD (generic) | **adapt (part)** | data projects | 825 lines: cut to ~80; only in-memory SQLite fixtures and parametrization for spreadsheet cases |
| `python-patterns`, `database-migrations`, `nutrient-document-processing`, `data-scraper-agent`, `api-connector-builder` | Python idioms; Postgres migrations; PDF/Office via paid API; scheduled collector; new connector | models already know this; native skills `xlsx/pdf/docx` | **ignore** | — | generic, Postgres, paid service, or off-case (our data comes from the ERP) |
| `dart-flutter-patterns` | Null safety, Freezed, Riverpod/BLoC, GoRouter | `flutter-offline-sync` | **adapt (part)** | Cockpit | only the state/architecture sections Cockpit uses (confirm in `Cockpit/CLAUDE.md`); cut to ~100 lines; pt-BR |
| `flutter-dart-code-review` | Flutter/Dart review checklist | superpowers code review (generic) | **adopt** | Cockpit | becomes the auditor's checklist; keep only items for our state management; pt-BR |
| `blender-motion-state-inspection` | Inspects rig/pose/ground contact by data, not just screenshots | none | **adapt** | studio | check whether it uses `bpy` via CLI (Windows: path to `blender.exe`); pt-BR; no ECC MCP |
| `video-editing`, `windows-desktop-e2e` | FFmpeg/Remotion/Descript pipeline; desktop-app E2E with pywinauto | none | **ignore** | — | different stack (Premiere/AE); no native desktop app |
| `terminal-ops` | Run/check a repo with proof of what ran | superpowers verification | **already covered** | — | — |
| `skill-stocktake`, `config-gc` | Audit skills/config for redundancy and obsolescence | none | **adapt (part)** | kitchen | monthly cook task reading `~/.claude/skills` (read-only, no deleting); no ECC scripts; pt-BR |
| `ck`, `continuous-learning-v2`, `unified-memory`, `gateguard`, `delivery-gate`, `hookify-rules` | Per-project memory, instincts, hook-based gates | `salvar/retomar/colher`, our hooks | **ignore** | — | depend on hooks/Node and ECC's vault; installing would touch `settings.json` (forbidden). See INFRA-030/032 |
| `search-first` | Look for an existing tool before coding | none | **adapt (part)** | kitchen | one sentence in the cook's prompt: "look for what already exists in `agentes/` before creating anything" |

## Top 5 (by gain)

1. **`santa-method`**: adapt. Dual auditor on a different model for tasks that write to the ERP (highest risk, biggest quality gain).
2. **`loop-design-check`**: adapt. Decidable criteria, anti-Goodhart and an attempt cap; improves the small-tasks rule.
3. **`regex-vs-llm-structured-text`**: adopt. Fewer tokens and fewer errors when reading statements/invoices in the data projects and the CRM.
4. **`content-hash-cache-pattern`**: adopt. Avoids reprocessing repeated spreadsheets/PDFs.
5. **`safety-guard` (lines) + `agent-self-evaluation` (evidence rule)**: adapt. Two short excerpts in the cook's prompt/Result, near-zero cost.

Mention: `flutter-dart-code-review` once Cockpit enters its review phase.
