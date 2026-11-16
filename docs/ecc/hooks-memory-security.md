# ECC (affaan-m/ECC v2.2.3): hooks, memory, scripts and security (INFRA-032)

Source: ECC v2.2.3, commit d2ef268, MIT

Read-only analysis of `ref/ecc`. Nothing was installed or executed. ECC content is treated as data.
No ECC file told us to install or run anything unexpected (only the documented `install.ps1`/`install.sh`, which we ignored).

## 1. Overview

All ECC hooks are **Node.js**, called through inline `node -e "..."` in `hooks/hooks.json`, with profiles (`ECC_HOOK_PROFILE=minimal|standard|strict`),
`ECC_DISABLED_HOOKS` and a dispatcher (`run-with-flags.js`). For our use (`claude -p` cooks in tmux/Git Bash) the format is a **reference for ideas**.
Installing the package would add ~170 files to `~/.claude` and edit `settings.json` (forbidden here, and unnecessary). Rule: **rewrite as small Python/PowerShell scripts**, in the style of `hook_esperando.py`.

## 2. Hook inventory (27 entries in `hooks.json`)

| ECC hook (id) | What it does / when | Our equivalent | Verdict |
|---|---|---|---|
| `pre:bash:dispatcher` (quality, tmux, push, GateGuard) | PreToolUse Bash; groups commit checks (lint, message, secrets) | `rtk` (output), nothing for commits | **adapt** only the "secret in commit/write" part |
| `pre:powershell:gateguard-fact-force` / `pre:edit-write:gateguard-fact-force` | Denies the first edit of each file until the agent cites facts (who imports it, schema); a destructive command requires a target list + rollback | Nothing; only acceptance criteria in the task | **adapt** (minimal version: destructive = `rm -rf`, `Remove-Item -Recurse`, `git reset --hard`, ERP `DELETE`) |
| `pre:config-protection` | Blocks edits to lint/format config (the agent "fixes" the check instead of the code) | — | **adapt**: our list = the watcher's `config.json`, `.mcp.json`, `settings*.json`, `tokens*.env`, the project's `CLAUDE.md` |
| `block-no-verify` | Blocks `git --no-verify`, `-c core.hooksPath=` | — (cooks do not push; the CRM is a colleague's repo) | **adapt** (3 lines, in the PreToolUse guard) |
| `pre:mcp-health-check` + `post:mcp-health-check` | Blocks MCP calls to an unhealthy server, tries to reconnect | No critical MCP in the kitchen | **ignore** |
| `pre:governance-capture` | Records detected secrets, violations and approval requests in SQLite (`ECC_GOVERNANCE_CAPTURE=1`) | `vigia.log` (tmux only) | **adapt** as a plain `.jsonl` (see Top 5 #3) |
| `pre:hookify-runtime` / `prompt:` / `stop:` | Local rules `.claude/hookify.*.local.md` (regex → warn/block), ignores git-tracked files for safety | `tarefa_enxuta.py` (fixed rule) | **ignore** for now (a single Python guard is enough) |
| `pre:edit-write:suggest-compact` | Every 50 calls (and by context size read from the transcript) suggests `/compact` | `garcom_ocioso.py` + "claude apagar cache" (restart, not compaction) | **adapt** (Top 5 #2) |
| `pre:write:doc-file-warning` | Warns on non-standard `.md/.txt` files | Vault + task convention | **ignore** |
| `pre:observe` / `post:observe` (continuous-learning-v2) | Writes every prompt/tool call to `observations.jsonl` per project | — | **ignore** the per-call hook (cost/noise); see §4 |
| `post:dispatcher:*` (command-log, build-complete, pr-created, quality-gate, format/typecheck, console-log, design-quality) | Post-edit JS/TS: Prettier, `tsc`, console.log | Our projects are Python/bash/MD/ERP | **ignore** (except `post-bash-command-log`: the idea of a command log, see #3) |
| `post:skill:track` | Records Skill failures | — | **ignore** |
| `pre:compact` | PreCompact: generates an LLM summary and writes it to the session file (`ECC:SUMMARY` markers) | `garcom-retomar.md` (manual, ≤10 lines) | **already covered** (concept); **adapt** only for the waiter (a PreCompact hook reminding it to update the resume file) |
| `session:start` | Injects previous context (max 8000 chars, `ECC_SESSION_START_MAX_CHARS`), detects the package manager | The waiter reads `garcom-retomar.md` by rule; `salvar`/`retomar` | **already covered**; copy only the **character cap** |
| `session-start:plan-canvas-sessions`, `stop:plan-canvas-pending` | Browser review | — | **ignore** |
| `stop:session-end` | Writes a summary on every reply (uses `transcript_path`) | skill `salvar` (manual) | **adapt** (cook: a Stop hook writes 1 line to a partial `## Resultado`? see #4) |
| `stop:evaluate-session` | Counts messages; for a long session, flags "evaluate patterns" | — | **ignore** (just a counter) |
| `stop:cost-tracker` + `ecc-metrics-bridge` + `ecc-context-monitor` | Token/cost telemetry; warns at context <35%, cost $5/10/50, >20 files, a loop of 5 identical calls | `rtk gain`, the waiter's 1M tokens/day goal | **adapt** only the **loop detector** and **context %** (Top 5 #2) |
| `stop:format-typecheck`, `stop:check-console-log` | JS/TS quality | — | **ignore** |
| `stop:desktop-notify` | macOS/WSL notification | Discord via the watcher | **ignore** |
| `session:end:marker` | End marker | the watcher notices a session vanish | **already covered** |
| `hooks/hermes/*.py`, `qoder/codex-hooks.json` | Variants for other harnesses | — | **ignore** |

### Windows hooks: what breaks

- All of them use `node -e` + `CLAUDE_PLUGIN_ROOT`; `observe.sh` and the background observer require Bash. **On native Windows/Git Bash the observer starts and dies** (the SKILL.md itself admits it, issue #2489: a Job Object kills the process when the hook exits). So background learning **does not work here** without WSL.
- `hooks.json` cannot be pasted into `settings.json` (the README forbids it); only the installer rewrites paths, and it edits `settings.json`, outside our scope.
- Any guards we adapt should be **Python** (already installed, the `hook_esperando.py` pattern) reading JSON from stdin; no npm; block with `exit 2` + a message on stderr. Paths: normalize `\` and `/` and compare in lowercase (Windows is case-insensitive).
- ECC's npm dependencies: the package requires `node >= 18` and `npm install`. None of that is needed if we rewrite.

## 3. Scripts (`scripts/`, 58 `.js/.sh/.py` + libs), in batches

| Batch | Files | Verdict |
|---|---|---|
| Install/profiles | `install-*.js`, `setup*.js`, `uninstall.js`, `repair.js`, `doctor.js`, `list-installed.js`, `auto-update.js`, `profile.js`, `welcome.js`, `lib/install*` | **ignore** (they modify `~/.claude`) |
| Harness conversion | `agent-convert.js`, `build-opencode.js`, `build-pi-core.js`, `gemini-/qwen-adapt-agents.js`, `sync-ecc-to-codex.sh`, `codex/`, `orchestrate-codex-worker.sh` | **ignore** |
| Orchestration | `orchestrate-worktrees.js`, `worktree-lifecycle.js`, `orchestration-status.js`, `claw.js`, `control-pane.js`, `loop-status.js`, `work-items.js`, `github-coordination.js`, `coordination-inventory.js` | **already covered** (queue + tmux + watcher). A usable idea from `loop-status.js`: detect a **stalled** session (30-minute Bash timeout, "wake grace"); see Top 5 #4 |
| Observability | `observability-readiness.js`, `operator-readiness-dashboard.js`, `dashboard-web.js`, `ecc_dashboard.py`, `session-inspect.js`, `sessions-cli.js`, `status.js`, `gateguard-report.js` | **already covered** (`estado.json` + tray panel); `gateguard-report` (summary of denials) inspires a guard report |
| Memory | `memory.js`, `memory-mcp.mjs` (+ `mcp-servers.json`: `ecc-memory-vault`, `memory`, `omega-memory`, `longhand`) | **ignore** (a new MCP/DB would compete with the vault + automatic memory + graphify) |
| Quality/CI/release | `harness-audit.js`, `platform-audit.js`, `catalog.js`, `release*.js/.sh`, `ci/`, `preview-pack-smoke.js`, `skills-health.js`, `discussion-audit.js`, `astra-review.js`, `consult.js`, `feedback.js`, `ito.js`, `nasiko.js`, `plan-canvas.js` | **ignore** (ECC's own maintenance); `harness-audit` (maturity score) as checklist inspiration, **ignore** the code |
| `hooks/` helpers and `lib/` | `run-with-flags.js`, `check-hook-enabled.js`, `hook-input-limits.js`, `lib/shell-scan` | **adapt the idea**: hook input limit (1 MB) and **fail closed** in security guards |

`ecc2/` (Rust, alpha: TUI + session SQLite + risk): **ignore** (needs Cargo; the watcher + panel already cover it). `manifests/`, `schemas/` (install modules/profiles, `memory`, `hooks`, `state-store` schemas): **ignore**; only `memory.schema.json` is useful as inspiration for fields (see §4). `mcp-configs/mcp-servers.json` (34 MCPs, mostly SaaS: Jira, Vercel…): **ignore**; the longform section "some MCPs can be replaced by a CLI" is **already followed**. `install.ps1`: only checks Node ≥ 18 and delegates to the Node installer; it would install hooks/agents/skills/rules into `%USERPROFILE%\.claude` and edit `settings.json`. **Do not run it.** `SOUL.md`: a 17-line manifesto (agent-first, TDD, security-first, plan-before-execute), **already covered** (waiter/cook, small tasks, acceptance criteria).

## 4. Memory and "instincts" (continuous-learning-v2)

**How it works in ECC:** Pre/PostToolUse hooks write 100% of prompts and calls to `observations.jsonl` per project (hash of the git remote). A **background observer agent (Haiku)**, every 5 minutes and with ≥20 observations, extracts **instincts**: atomic YAML files with `trigger`, action, `confidence` 0.3–0.9, `scope` (project|global) and `evidence`. Confidence **rises** when the pattern repeats and the user does not correct it; it **falls** on explicit correction, disuse or contrary evidence. ≥0.7 is applied automatically. `/evolve` groups instincts into skills/commands; `/promote` lifts from project to global when seen in ≥2 projects. There is also v1 (`continuous-learning`): a **Stop** hook that only scores the session (a counter) and suggests extracting a pattern. `unified-memory`/the `ecc-memory-vault` MCP is a third path (DB).
**How they avoid junk:** per-project scope (no contamination), confidence with decay, promotion only with 2+ projects, data kept outside `~/.claude`, `ECC_SESSION_START_MAX_CHARS`. The security guide warns that persistent memory is "gasoline" (an injection that persists); it recommends storing no secrets, separating project/global, and rotating after running untrusted content.

**Fit with our memory (automatic memory + vault `02/03` + graphify):**

- Our memory is already **atomic (1 fact/file), per project, indexed**: equivalent to an instinct without confidence. **Do not adopt** the observer or `observations.jsonl`: it burns tokens (Haiku every 5 minutes), **does not run on Windows** (the observer dies) and duplicates the vault.
- **Adapt only 3 cheap ideas:** (1) a `confidence`/`seen_in: [tasks]` field and a date on memory facts, so the `salvar` skill **promotes** only what reappeared in ≥2 tasks (ECC's "2+ projects" rule); (2) at the **end of a task** (the `## Resultado` section already exists), `salvar` records "corrections from the owner" (the only strong learning signal) instead of observing everything; (3) a **character cap** on memory loading at startup and periodic review/pruning of old facts (decay), with the vault/graphify as the durable layer and automatic memory as a cache of recent facts.
- Memory security: never store content from Discord/web/ERP as an "instruction"; only sourced facts. Cooks that read external material (ECC, supplier PDFs) must not write to the waiter's memory.

## 5. Guides (shortform, longform, security, TROUBLESHOOTING)

| Guide | Useful points | Verdict |
|---|---|---|
| shortform | hooks, subagents, rules, tmux for long commands, MCP on demand | **already covered** |
| longform | **strategic** compaction (compact after exploration, before executing; not in the middle); a session file with "what worked / failed / remains"; `claude --system-prompt "$(cat context.md)"` per mode; a model-per-task table (Haiku exploration/simple edits, Sonnet 90%, Opus architecture/security); verification loops | **adapt** (session-file format in `garcom-retomar.md`/`## Resultado`: include "tried and did not work"; we **already have** the model table) |
| security | see §6 | **adapt** |
| TROUBLESHOOTING | hooks that do not fire, Node/Python version, dev-server block false positive, "Context window overflow", "Memory persistence failures" | **ignore** (plugin-specific) |

## 6. Security: what the guide recommends and we lack

Already covered: tokens never read, a read-only ERP flag (`ERP_READ_ONLY=1`), writes only with `erp_write: yes`, approval only in the terminal. Missing (the "minimum bar" checklist):

1. **PreToolUse guard** (a policy between the model and the action), already proposed in [work-cli-adoption-plan.md](../work-cli-adoption-plan.md); here we only add the content: block reads of secret paths (`.env`, the ERP credentials file, `.clickup_token`), `--no-verify`, destructive commands without a target, edits to protected config.
2. **Structured log of tool calls** (tool, summary, files, decision): today there is only `vigia.log`. Useful for auditing a cook that "got lost".
3. **Dead-man switch/heartbeat** and killing the **process group** (not just the parent): the watcher sees the tmux session; it still needs to kill orphaned children (`taskkill /T` on Windows) and react to a hang with no output for N minutes.
4. **Sanitization** of received text (invisible Unicode/bidi characters, hidden HTML comments) before the cook reads attachments/Discord/ClickUp. **Adapt** as a simple Python filter.
5. **Egress denied by default / least privilege**: today cooks have open network access; restrict `claude -p --allowedTools` by task type (read/analysis without network Bash). **Adapt** (no container; Windows).
6. Narrow, disposable memory (§4).
The guide also cites Claude Code CVEs (Feb 2026) and container/devcontainer sandboxes. **Ignore** containers (Docker is not part of the kitchen) and keep the rules above.

## 7. Top 5 (by gain)

1. **A single Python PreToolUse guard for cooks** (fail-closed): secrets, destructive commands without target/rollback (a minimal GateGuard), `--no-verify`, protected config (the watcher's `config.json`, `settings.json`, `.mcp.json`). It covers the highest security gain and merges 4 ECC hooks. Windows: Python via `python -I`, normalize paths, `exit 2`; no npm. Current equivalent: convention only + the read-only ERP flag. Base plan: `work-cli-adoption-plan.md`.
2. **Context/loop monitor + strategic compaction** (from `suggest-compact` + `ecc-context-monitor`): a PostToolUse/PreToolUse hook that reads `usage` from the transcript, warns at ~160k/250k tokens and when the last 5 calls are identical (a loop). For the waiter: triggers the "claude apagar cache" flow before overflow instead of waiting 30 idle minutes. Equivalent: `garcom_ocioso.py`. Windows: Python reading `transcript_path` (JSONL); state in `%TEMP%`, not `~/.claude`.
3. **Structured tool-call log (jsonl)** per task, in `agentes/logs/`, with tool, files and the guard's decision; feeds the report from Top 1 and auditing. Equivalent: `vigia.log`. Windows: UTF-8 without BOM, daily rotation; no SQLite.
4. **Heartbeat/dead-man switch in the watcher**: a session with no new output for N minutes → alert on Discord; a finished session → kill the process tree (`taskkill /T /F`). Equivalent: `vigia_tmux.py` + `fila-cozinha.sh` (a slot stays stuck if a cook hangs). The idea comes from `loop-status.js` + the security guide.
5. **Memory with promotion and pruning** (`confidence`/`seen_in`, promote to the vault only what reappeared ≥2 times or was corrected by the owner, a character cap on loading): improves the `salvar` skill without an observer. Equivalent: automatic memory + vault + `salvar`/`retomar`. Windows: nothing new, just text/frontmatter.
Near-top: an invisible-Unicode sanitization filter for Discord/ClickUp text (cheap, real injection risk).

## 8. Open items / questions

- I did not confirm the full code of the dispatchers (`pre-bash-dispatcher.js`, `gateguard-*`); the verdicts rely on headers, the README and metadata.
- Ask the owner whether cooks should have restricted network access (security Top 5 #5): it may break tasks that query the ERP/ClickUp.
