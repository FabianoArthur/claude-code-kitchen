# ECC v2.2.3: agents, commands, rules, contexts, workflows (INFRA-030, 2026-11-16)

Source: ECC v2.2.3, commit d2ef268, MIT

Analysis only. Nothing from ECC was installed or executed. ECC content is treated as data. Every ECC agent opens with a "Prompt Defense Baseline" block (generic, not needed here).
Verified totals: 71 agents, 98 commands, 122 rule files (23 folders), 3 contexts, 2 files in workflows. The work-cli plan (W1–W14) is only cited; see [work-cli-adoption-plan.md](../work-cli-adoption-plan.md).

## 1. Inventory

### Agents (71)

| Item | What it does | What we have | Verdict |
|---|---|---|---|
| planner, architect, code-architect | step-by-step plan; architecture design; architecture derived from code patterns | skills `plan`/`orquestrar`, superpowers `writing-plans`/`brainstorming` | **already covered** (adopt only the `architect` idea as a short "spec/decision" task on opus, per the small-tasks rule) |
| code-explorer | traces execution paths and layers of an existing feature | superpowers skills + Claude Code's Explore | **already covered** |
| code-reviewer | severity-ranked review before commit | superpowers `requesting-code-review` + a reviewer on a different model | **already covered** |
| silent-failure-hunter | finds empty `catch`, fallbacks that hide errors, logs without context | nothing specific (ERP integrations swallow errors easily) | **adapt** |
| agent-evaluator | scores agent output on 5 axes (accuracy, completeness, clarity, actionability, concision), requires evidence, read-only Bash | manual waiter review + auditor; superpowers `verification-before-completion` | **adapt** (becomes the taster for tasks in `revisar` status) |
| loop-operator | runs an autonomous loop: checkpoints, detects stalls and retry storms, escalates | watcher (`vigia_tmux.py`), `garcom_ocioso.py`; W8/W9 | **adapt** (escalation rules only) |
| harness-optimizer | tunes harness hooks/evals/routing with pass@k; depends on `node scripts/harness-audit.js` | nothing | **ignore** (needs ECC's node/scripts; the idea of auditing the kitchen fits INFRA-033) |
| security-reviewer | hunts vulnerabilities (OWASP, secrets) before commit | superpowers does not cover it; security rule in CLAUDE.md | **adapt** (with our own list: the ERP credentials file, the CRM's `data/` folder, ERP writes) |
| code-simplifier, refactor-cleaner | simplifies while preserving behavior; removes dead code with verification | nothing formal | **adapt** (cleanup cook: short task on sonnet/haiku) |
| tdd-guide | requires tests first | superpowers `test-driven-development` | **already covered** |
| build-error-resolver | fixes build/type errors with minimal changes | superpowers `systematic-debugging` | **already covered** (see react/dart below) |
| python-reviewer | PEP 8, types, security, Python idioms | nothing (our data and infra projects are Python) | **adapt** |
| react-reviewer, react-build-resolver, typescript-reviewer | review/build for React, Vite and TS | nothing (CRM and TJO are React 19 + Vite/TS) | **adapt** (a single "web" prompt for CRM/TJO) |
| flutter-reviewer, dart-build-resolver | widget/state review; fixes `dart analyze` | nothing (Cockpit is Flutter) | **adapt** |
| e2e-runner | E2E with Vercel Agent Browser/Playwright | skill `qa`? (not verified here) | **ignore** for now (CRM has no E2E; revisit when it does) |
| doc-updater, docs-lookup | updates codemaps/docs; looks up current library docs | `salvar`, `colher`; Context7 if installed | **already covered** |
| commit-reviewer | reviews the staged diff and drafts a Conventional Commits message | nothing formal; our repos use free-form messages | **ignore** (low gain) |
| spec-miner | extracts behavioral specs from legacy code (OpenSpec, opus) | nothing | **adapt** (useful for a colleague's CRM and the backend rewrite; opus, read-only) |
| conversation-analyzer | finds behaviors a hook should prevent (haiku) | nothing; depends on `/hookify` | **adapt** (idea: haiku reads transcripts and proposes rules for the W3–W6 guard) |
| gan-planner / gan-generator / gan-evaluator | generator-vs-evaluator loop with a rubric and strict grading on a running app | reviewer on a different model (only grades at the end) | **adapt** (only the "no praise" evaluator and the rubric; the full loop is expensive) |
| comment-analyzer, pr-test-analyzer, type-design-analyzer | analysis of comments, PR test coverage, type design | – | **ignore** (our repos have almost no PRs and no strong typing) |
| performance-optimizer, database-reviewer | bottlenecks; PostgreSQL | – (SQLite/spreadsheets) | **ignore** |
| fastapi-reviewer | FastAPI review | – (the CRM backend has no Python/Go decision yet) | **ignore for now**; revisit if the backend is Python |
| Languages we do not use: bengali, cpp (2), csharp, django (2), fsharp, go (2), harmonyos, java (2), kotlin (2), php, pytorch-build, ruby, rust (2), swift (2), vue | reviewers/resolvers for those stacks | – | **ignore in bulk: 22 items** |
| Outside our domain: a11y-architect, chief-of-staff, healthcare-reviewer, homelab-architect, network-architect/config-reviewer/troubleshooter, marketing-agent, seo-specialist, mle-reviewer, rag-pipeline-reviewer, opensource-forker/packager/sanitizer | healthcare, networking, SEO, marketing, ML/RAG, open source, email | – | **ignore in bulk: 14 items** |

Count: 36 ignored in bulk + 35 individual items or small groups = 71.

### Commands (98)

| Group | What it does | What we have | Verdict |
|---|---|---|---|
| Build/review/test for languages we do not use (cpp×3, go×3, kotlin×3, gradle-build, rust×3, vue-review): **14** | shortcuts for the agents above | – | ignore |
| react-build/review/test (3), python-review, fastapi-review (2), flutter-build/review/test (3) | shortcuts for the adopted agents | – | **adapt** as station-taster prompts, not as slash commands (python/react/flutter); ignore fastapi |
| epic-* (7: claim, decompose, publish, review, sync, unblock, validate) | epic coordination via GitHub issues and `node scripts/github-coordination.js` | `.md` tasks, `depende_de`, W10 `checar_tarefas.py`, W11 | **ignore** (the idea "reopen a blocked task when its dependency closes" = `epic-unblock`; already planned in the W10/W11 dispatcher) |
| orch-* (6: add-feature, build-mvp, change-feature, fix-defect, refine-code, review) | pipelines: research→plan→TDD→review→gates | `plan`+`orquestrar`+`dotask`, superpowers (TDD, debugging, code review) | **already covered**; `orch-fix-defect` (red regression test before the fix) is worth using as a bug-task script |
| multi-* (5), astra-review (1) | multi-model flow with Codex/Antigravity/GPT; Claude is the only one that writes files | reviewer on a different model | **ignore** (depend on external CLIs we do not have) |
| santa-loop (1) | two independent reviewers (Opus + external model) must both say NICE before publishing; PASS/FAIL rubric | reviewer on a different model (one reviewer) | **adapt** (formalize: objective rubric + "both approve" on tasks with `erp_write: yes`) |
| prp-* (5), plan, plan-prd, plan-canvas (3) | PRP/PRD/plan and execution with validation loops | `plan`, superpowers `writing/executing-plans` | **already covered**; from `prp-implement` take only the rule "validation failed → fix before moving on" (already in `verification-before-completion`) |
| Instincts/learning (12: evolve, instinct-export/import/status, projects, promote, prune, learn, learn-eval, skill-create, skill-health, skill-host-compat) | memory via "instincts" with confidence, promotion and pruning | `colher`, Claude Code memory | **ignore** here (belongs to INFRA-031); `learn-eval` (self-evaluate before saving) → **adapt** inside `colher` |
| hookify* (4) | creates hooks from conversation | W3–W6 guard | **ignore** (we do not edit `settings.json`; see conversation-analyzer) |
| Session (4: save-session, resume-session, sessions, checkpoint) | saves/resumes sessions, git checkpoints | skills `salvar`/`retomar`, `garcom-retomar.md` | **already covered** |
| Cost/model (3: cost-report, token-card, model-route) | spend report via node hook; token card; recommends a model per task | W7–W9 (tokens from the transcript); `modelo:` in frontmatter | **adapt** `model-route` (haiku mechanical / sonnet default / opus architecture-ambiguous) as a checklist for the waiter when registering a task; **ignore** cost-report/token-card (node + hook) |
| Loops (4: loop-start, loop-status, gan-build, gan-design) | loop with a stop condition and status | watcher + queue | **ignore** (covered by the adapted loop-operator) |
| Quality (9: harness-audit, quality-gate, security-scan, test-coverage, build-fix, refactor-clean, code-review, review-pr, issue-review) | audits, gates, reviews | superpowers review/verification | **already covered**; `refactor-clean` and `security-scan` follow the adapted agents; `harness-audit` (deterministic scorecard) is an idea for INFRA-033; `security-scan` depends on AgentShield (external install): ignore |
| Git/management (pr, jira, marketing-campaign: 3) | PR, Jira, campaign | ClickUp (`sync-clickup`) | ignore |
| Meta/ECC (9: update-codemaps, update-docs, aside, auto-update, ecc-guide, setup-pm, pm2, project-init, feature-dev) | ECC's own utilities | – | **ignore**; `aside` (side question without losing context) is already native to Claude Code |

Group sums verified: 98 (santa-loop and astra-review counted once each).

### Rules (122 files in 23 folders)

| Folder | Verdict |
|---|---|
| `common/` (10: agents, code-review, coding-style, development-workflow, git-workflow, hooks, patterns, performance, security, testing) | **adapt** only `performance.md` (haiku/sonnet/opus + avoid the last 20% of context → matches our context economy and `modelo:`) and `code-review.md` (mandatory review triggers and severities). The rest duplicates superpowers (TDD, workflow) or presupposes `ecc:planner`. |
| `python/` (6), `dart/` (5), `typescript/` (5), `react/` (5), `web/` (7) | **adapt**: read as a checklist for the matching stack's taster prompt; do not copy into `~/.claude/rules` (it would change behavior in every project). |
| Other 17 folders (angular, arkts, cpp, csharp, fsharp, golang, java, kotlin, nuxt, perl, php, react-native, ruby, rust, swift, vue + README): **17 items** | **ignore in bulk** |

### Contexts (3) and workflows (2)

- `contexts/dev.md`, `research.md`, `review.md`: short modes ("write first", "read before acting", review checklist with severity). **Already covered** (superpowers + each project's CLAUDE.md); take only the "Output: group by severity" format for the taster prompt.
- `workflows/orch-review.workflow.js` + `README.md`: script for the native Workflow tool (one reviewer per dimension in parallel + adversarial verification of every CRITICAL/HIGH finding; fails closed if the diff is missing). **Ignore** (experimental tool, JS); **idea to keep**: "try to refute every serious finding before reporting it" in the taster.

## 2. Brigade roles (adopt/adapt)

| ECC agent | Role in the kitchen | Model | Replaces/complements |
|---|---|---|---|
| agent-evaluator (+ the GAN evaluator: strict rubric, "no praise") | **Taster** (Provador) for tasks in `status: revisar` | sonnet (opus on `erp_write: yes`) | complements the different-model auditor and `verification-before-completion` |
| santa-loop | **Double taster** (Provador duplo) for risky tasks | opus + another model | extends the current auditor (one reviewer) |
| silent-failure-hunter | **Swallowed-error taster** (Provador de erros engolidos) (Python for data/infra, Express for the CRM) | sonnet | complements `requesting-code-review` |
| security-reviewer | **Security inspector** (Segurança): secrets, ERP, the CRM's `data/` folder | sonnet | complements the Security rules in CLAUDE.md |
| python-reviewer; react/typescript-reviewer + react-build-resolver; flutter-reviewer + dart-build-resolver | **Station tasters** (Provadores por stack) (data/infra; CRM/TJO; Cockpit) | sonnet (resolvers: haiku) | complement `code-review`; resolvers complement `systematic-debugging` |
| code-simplifier + refactor-cleaner | **Dishwasher** (Limpeza), cleanup | haiku/sonnet, short task | no equivalent |
| spec-miner | **Archaeologist** (Chef/planejador de legado): specs for a colleague's CRM before the backend rewrite | opus, read-only | complements `brainstorming`/`plan` |
| architect (idea) | **Decision chef** (Chef de decisão): short spec/decision task | opus | already described in the small-tasks rule |
| loop-operator (escalation rules) | **Maître/watcher** (Maître/vigia): no progress in 2 checkpoints, identical repeated failure, cost out of range | no LLM (rules in `vigia_tmux.py`) | complements W8/W9 and `garcom_ocioso.py` |
| conversation-analyzer | **Memory/hygiene** (Memória/higiene): reads transcripts, proposes rules for the guard (W3–W6) | haiku | complements `colher` |

## 3. Top 5 (by gain)

1. **A standard taster (agent-evaluator + the strict rubric from gan-evaluator + santa-loop).** Today the waiter's review is free-form. It becomes a 5-axis rubric, a score below 5 only with evidence, read-only Bash, and two reviewers on `erp_write: yes` tasks. What changes: every `revisar` task goes through the taster before the waiter says "done".
2. **silent-failure-hunter as a fixed step for any task that writes data** (ERP writes, the CRM's SQLite). It catches fallbacks that hide errors, the costliest defect in spreadsheet/API automation. What changes: a standard acceptance criterion, "no swallowed errors", on tasks.
3. **Station tasters (python / react+ts / flutter) as prompts, not as files in `~/.claude`.** The checklists from `rules/python`, `dart`, `typescript`, `react`, `web` become the taster's prompt; nothing global is altered. What changes: code tasks get a short second pass on sonnet.
4. **Escalation rules from loop-operator + routing from `model-route`/`rules/common/performance.md`.** Escalate when there is no progress after 2 checks or an identical failure repeats; the waiter picks `modelo:` by heuristic (haiku mechanical, sonnet default, opus ambiguous/architecture). What changes: the watcher gains 2–3 deterministic rules (zero token cost) and task registration gains a model checklist.
5. **spec-miner for legacy code (a colleague's CRM) + cleanup (code-simplifier/refactor-cleaner).** A behavioral spec before rewriting the backend in Python/Go reduces regressions; cleanup becomes a short haiku/sonnet task. What changes: a new opus decision task before the CRM backend implementation.

Do not adopt: instincts/hookify/cost-tracker (they depend on ECC's hooks and node; see INFRA-031/032) and multi-model flows with external CLIs.
