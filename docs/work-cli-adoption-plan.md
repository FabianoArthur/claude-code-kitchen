# work-cli → waiter/kitchen on Windows (INFRA-029, 2026-11-15)

Source: TrussInt/work-cli v0.6.1, analysis only

Source: `TrussInt/work-cli` v0.6.1, a shallow clone for reading only, kept in `cookbook/pantry/work-cli` (safe to delete).
What it is: the "control plane" of a ClickUp vault with a fleet of machines over SSH (a Mac coordinator plus Mac/Linux workers),
with SQLite, Graphify, a Postgres per task, and Claude/Codex/Gemini in tmux. About two thirds of the code covers ClickUp, the fleet, the database and the graph,
which we neither have nor need. Four small ideas are useful to us: **slots for heavy commands**,
**tokens per task**, **a PreToolUse guard** and **dependency checks before dispatching**.

## Inventory (`internal/cli`, the 31 files without `_test`)

| File | What it does | What we have today | Verdict: why / Windows |
|---|---|---|---|
| app.go | command registry, `--json`, exit codes by error type (2 = wrong usage; heavy: 75 no slot, 124 timeout) | loose scripts | **ignore**; only copy the 75/124 convention into `pesado.py` (W1) |
| bootstrap.go | `host bootstrap/auth`: provisions an SSH worker (packages, keys, gh/claude login) | `mac/caixa.sh` (SSH with a forced command) | **ignore**: we have no fleet |
| claude_sync.go | packages `.claude/`, sends it to the workers, reinstalls hooks | `synced/` skills | **ignore** |
| clickup.go | `clickup me/lists/types/modules`, `task get/list/search/fields/comments/branch` | skill `sync-clickup` | **ignore**: our task is a `.md` file, not ClickUp |
| context.go | `task context`: Markdown for the agent (task, relations, comments, worktree, graph) | `tarefa_enxuta.py` | **adapt** (W14): put the `## Resultado` of the `depende_de` tasks into the prompt. Windows: nothing breaks |
| daemon.go | `daemon run/install/stream/status`: a per-worker service, a Unix socket with mode 0600, an event journal | `vigia.sh` (30 s loop) + `estado.json` | **ignore**: only makes sense with a fleet (launchd/systemd → Task Scheduler; a Unix socket with 0600 does not translate) |
| database.go | `db ensure/status/drop`: an isolated Postgres per task in a container | nothing | **ignore**: no Docker/Postgres in our projects |
| diagnostics.go | diagnostic bundle with secrets masked | `discord_api.limpar()` already masks everything sent to Discord | **ignore** |
| doctor.go | checks git, uvx, tmux, gh, docker, sqlite, token (without printing the token) | `testar_ambiente_cozinha.sh` (claude's environment), `orq_doctor.py` (only the orchestrate skill) | **adapt** (W13): `cozinha_doctor.py`, one ok/MISSING line per item. Windows: check the tmux shim and `vigia.pid` (tasklist), no uvx/docker |
| fence.go | `fence check/renew/revoke/import`: generation + lease; only the live owner of a task may push, open a PR or write to ClickUp | rules in CLAUDE.md (CRM without push, `erp_write: yes`) | **ignore** the lease (1 machine, no reassignment); reuse only the list of publishing commands (W4) |
| fleet.go | `watch`, `notify`, `session status`, `limit get/set`, auto-tuning: exit code, stop, "wedge", a blocked re-alert every 5 min, open PR | `vigia_tmux.py` (stalled, waiting via `hook_esperando.py`, Discord cards) | **adapt** (W12): re-alert for "waiting". We already have the rest. Windows: osascript → Discord/tray; pgrep → psutil/`Win32_Process` |
| graph.go | `graph build/refresh/status/query` (graphify via uvx) | skill `graphify` when we ask for it | **ignore for now**: building the graph costs (uvx); the data projects, CRM and INFRA are almost only data and scripts |
| guard.go | PreToolUse hook (Bash and Write/Edit): denies heredoc, `python -c`, cat/head/tail on a file, writing with `>`, a script in /tmp, publishing with a fence. Uses a real bash parser (mvdan.cc/sh) | only `rtk-rewrite.sh` on PreToolUse | **adapt** (W3–W6): `guarda_cozinha.py`, enabled only for cooks. Windows: temp folders = %TEMP%, MSYS /tmp, scratchpad; drive-letter paths with a backslash or a slash, and the `/c/` form; no mvdan → shlex + conservative rules |
| guard_heavy.go | separates test/typecheck/build (npm/pnpm/yarn/bun, vitest/jest/playwright, tsc/vite/next/webpack, docker compose), requires a scope, denies watch mode | nothing | **adapt** (W4) together with the guard; add pytest, `go test/vet/build`, `flutter test`, `blender -b` |
| heavy.go | `heavy run/status`: N slots for heavy commands (flock on `slot-N`; the kernel releases it if the owner dies); a timeout kills the group (124); no slot within X min → 75 | only `COZINHA_MAX` (counts cooks, not commands) and the 5 "brake" sessions | **adapt** (W1). Windows: flock/Setpgid/kill(-pgid) → `msvcrt.locking` + a Job Object (`criar_job` already exists in `bandeja_recursos.py`) |
| hooks.go | `hooks check/install`: installs hooks without duplicating and keeps the rest; the guard fails closed (`work guard … \|\| deny`) | `aplicar_hook.py` (installs `hook_esperando`) | **adapt** (W5): `aplicar_hook.py --guarda/--check`. Windows: the hook command calls `python` with an absolute path (no binary on PATH); "fail closed" becomes `python … \|\| echo <deny>` in the hook's bash |
| host.go | `host add/list/doctor/status/metrics/sample/remove/upgrade/enable/disable` | `mac/caixa.sh` | **ignore** |
| overview.go | `overview`, `pr list`: a single snapshot (sprint + PRs + sessions) | `estado.json` + `painel_bandeja.pyw` + the Discord panel | **ignore** |
| remote.go | `task attach/resume/stop` on the worker via SSH | nothing | **ignore** |
| run.go | `task run`: worktree, graph, context, and launches the agent (headless/`--tmux`/`--host`); a dispatch lock and a session cap | 3× `executar.sh` + `fila-cozinha.sh` + `ambiente-cozinha.sh` | **ignore** the command; keep one idea: export `COZINHA_ID` in the session (W5), so the guard knows it is inside a cook |
| scheduler.go | `scheduler status/explain`, `sprint run`: picks a worker per task (external first) and respects dependencies | the data project's `despachar.sh` + the FIFO queue | **ignore**: 1 machine |
| session.go | `session attach/send/kill` | tmux shim + `bandeja_acoes.py` | **ignore**; lesson: `send-keys -l "text"`, wait 300 ms, `Enter` separately |
| sprint_check.go | before dispatching: unknown dependency, a task depending on itself, or a cycle; two dispatchable tasks that cite the same file without depending on each other | nothing (`despachar.sh` only reads `depende_de`) | **adapt** (W10, W11): `checar_tarefas.py`. Windows: a path cited with `\` or `/` counts as the same file |
| sprint_write.go | `sprint add/status`, `outbox list/retry`: durable writes to ClickUp (saves the batch first, resumes later) | `sync-clickup` | **ignore** (the outbox idea stays, in case `sync-clickup` breaks midway) |
| status.go | `status`: a fleet view from SQLite, without hanging on SSH/ClickUp | `estado.json` | **ignore** |
| sync.go | pulls the sprint into SQLite | — | **ignore** |
| task_set.go | edits a frontmatter boolean in ClickUp | local frontmatter | **ignore** |
| time.go | a swappable `now` for tests | — | **ignore** |
| update.go | rebuilds, reinstalls hooks, publishes to the workers, restarts the watcher | — | **ignore**: we have no binary |
| usage.go | `task usage`: sums the transcript's tokens (never counting the same message id twice; unknown never becomes 0), saved by the hook | `bandeja_uso.py` (only the plan's %); nothing per task | **adopt** (W7–W9): measures the "waiter ≤ 1M/day" goal and each task's cost. Windows: nothing breaks |
| worktree.go | `worktree start/status` | the `executar`/`dotask`/`orquestrar` skills already use worktrees | **ignore** |

The packages in `internal/` outside `cli` (agent, coordinator, db, taskdb, tmux, sysinfo…) only support these commands and get the same verdict.

## Path: a Go binary or a port of the ideas?

**Recommendation: port the ideas to Python/bash and do not compile work-cli.**

1. The code does not compile for Windows without changes. `syscall.Flock` (heavy, run, fleet), `Setpgid` and `syscall.Kill(-pgid)` exist only on Unix,
   and `sysinfo` only has `_darwin`/`_linux` versions. Compiling would need a fork of a colleague's repository (no push), which we would have to maintain.
2. Even compiled, almost every command requires the vault (`cu.json`, a ClickUp key, SQLite, uvx/graphify, docker). Our flow is `.md` + tmux + Discord.
3. The useful parts (heavy, guard, guard_heavy, usage, sprint_check, hooks) total ~1.8k lines of Go, half of it dealing with ClickUp/fleet/flags.
   In Python, in the style of the scripts with `test_*.py` we already have, they fit into short sonnet tasks.
4. `go.mod` asks for Go 1.27.1, and the scoop `go` downloads any missing toolchain by itself.

### What breaks on Windows, and what to use instead

- launchd/systemd → Task Scheduler (`Register-ScheduledTask`) or a Startup shortcut (what the panel already uses).
- flock (the kernel releases it on a crash) → `msvcrt.locking` in Python (the OS releases it when the process dies). MSYS2's `flock` only works between processes of the same MSYS runtime, and the scoop Git Bash uses a different `msys-2.0.dll`: it cannot be trusted.
- Setpgid + kill(-pgid) / forwarded SIGTERM → a Job Object with KILL_ON_JOB_CLOSE (or `taskkill /T /F /PID`).
- pgrep → psutil / `Get-CimInstance Win32_Process`. osascript → Discord and the tray (both already exist).
- sysctl/vm_stat/pmset (memory pressure, thermal) → `GlobalMemoryStatusEx` / counters (`bandeja_recursos.py` already measures this).
- A Unix socket with 0600 → a JSON file (`estado.json` is already that channel). `~/.zshrc` + AGENT_HEADLESS → `ambiente-cozinha.sh` already does this.
- Paths: `/tmp`, `/var/folders` → `%TEMP%`, MSYS `/tmp`, and the drive-letter form × the `/c/…` form. Anything that compares paths must normalize all three forms.
- tmux: through the MSYS2 shim, which already works. `#{pane_dead_status}`/`remain-on-exit` need a test before anyone depends on them.

## Plan in small tasks (a proposal: the waiter numbers and creates them only after the owner's OK)

Priority: W1, W2, W7, W8 and W10 first; the guard (W3–W6) next; the rest when a slot opens.

- **W1. `pesado.py`: slots for heavy commands.** `sonnet`, `depende_de: []`. Deliverable: `agentes/pesado.py` + `agentes/test_pesado.py`.
  1) `python pesado.py [--timeout 15m] [--espera 20m] -- <cmd…>`; N slots read from `agentes/fila/pesado-limite` on every attempt (default 3). 2) A lock with `msvcrt.locking` on `agentes/fila/pesado/vaga-N`; a process killed with `taskkill /F` frees its slot with no cleanup. 3) A timeout kills the whole tree (Job Object) and exits with 124; no slot within `--espera` exits with 75; in other cases it exits with the command's code. 4) `pesado.py status` lists the busy slots (command, since when) by testing the lock, not the file contents. 5) Tests: 2 processes competing for 1 slot, a timeout, and exit 75.
- **W2. A kitchen limit that changes without a restart (replaces the "brake").** `sonnet`, `[]`. Deliverable: `fila-cozinha.sh` reads the limit from `agentes/fila/limite` on every pass, plus `agentes/limite.sh get|set N`.
  1) Changing the file takes effect on the next pass, also for sessions already in the queue. 2) A missing file or a value outside 1..`COZINHA_MAX` → uses `COZINHA_MAX`. 3) `limite.sh get` shows the limit, where it came from, how many are running and how many are waiting. 4) A test with fake sessions: limit 1→2→3 releases one at a time. 5) Updates the "kitchen limit" section of the root `CLAUDE.md`; does **not** kill the brake sessions (the owner decides).
- **W3. Guard: core and shell rules (record only).** `sonnet`, `[]`. Deliverable: `agentes/guarda_cozinha.py` + a test.
  1) Reads the PreToolUse JSON on stdin and answers `{}` or a deny with the reason in pt-BR, pointing to the right tool (Read/Write/Edit/Grep). 2) Acts only with `COZINHA_ID` in the environment; otherwise (waiter, the owner) it always allows. 3) Rules: a heredoc that creates a file; `python -c`/`node -e`; reading with cat/head/tail/type/Get-Content; writing with `>`/`tee`/Set-Content (except `/dev/null` and `2>&1`); a script in a temp folder, in all 3 path forms. 4) `agentes/guarda.json` sets the mode: `registrar` (default: allows and logs to `agentes/logs/guarda.log`) or `negar`. 5) A command that cannot be parsed → logged (in `negar`, denied). 6) ≥ 30 test cases; < 150 ms per call.
- **W4. Guard: heavy commands and publishing.** `sonnet`, `[W1, W3]`. Deliverable: new rules in `guarda_cozinha.py` + tests.
  1) test/typecheck/build outside `pesado.py` (npm/pnpm/yarn/bun, vitest/jest/playwright, tsc/vite/next/webpack, pytest, `go test/vet/build`, `flutter test`, `blender -b`) → denied, returning the command already wrapped. 2) Watch mode (`--watch`, `vitest` without `run`, `npm run dev`, `docker compose up` without `-d`) → denied. 3) A test without scope (no path, `-k`, `-t` or `-run`) → denied with the reason. 4) Publishing (`git push`, write-type `gh pr/release/repo/workflow/issue`, non-GET `gh api`): a per-project rule in `guarda.json` (CRM = deny). 5) ERP write scripts listed in `guarda.json` → denied if the task file (`COZINHA_ARQ`) does not have `erp_write: yes`. 6) Tests for each rule.
- **W5. Wire the guard into the cooks.** `sonnet`, `[W3]`. Deliverable: `export COZINHA_ID COZINHA_ARQ` in the 3 `executar.sh` files + `aplicar_hook.py --guarda/--check`.
  1) The 3 `executar.sh` files export both variables in the session body. 2) `--check` says whether the guard is installed; `--guarda` run twice leaves the file identical. 3) The hook fails closed only in a cook: if python fails with `COZINHA_ID` present, it denies; without it, it allows. 4) Installs in `registrar` mode, with a backup of `settings.json` first (needs terminal approval). 5) Test: a fake haiku cook runs `cat x` and the line shows up in `guarda.log`; the waiter produces no line.
- **W6. Switch the guard to `negar`.** `sonnet`, `[W4, W5]`, after about 3 days of recording. 1) A report with the count per rule and the false positives from `guarda.log`. 2) Adjust the rules that had false positives, with a test. 3) Turn on `modo: negar`, if the owner approves. 4) One line in the root `CLAUDE.md` explaining the guard.
- **W7. `tokens_transcript.py`.** `sonnet`, `[]`. Deliverable: `agentes/discord/tokens_transcript.py` + a test.
  1) `totais(path)` sums input, output, cache_creation and cache_read from Claude's JSONL transcript. 2) Counts each message id only once (a repeated turn does not double). 3) Unknown format → `None`, never 0. 4) Incremental reading by offset (a large transcript costs little on each tick). 5) `python tokens_transcript.py <file>` prints 1 line. 6) 3 fixtures: normal, repeated, unknown.
- **W8. The watcher records tokens.** `sonnet`, `[W7]`. 1) `vigia_tmux.py` writes `tokens` per session into `estado.json`, using the transcript that `achar_transcript` already finds. 2) The final Discord card shows "tokens: 1.2 M (input · output · cache)". 3) The waiter's tokens go in a separate field (`garcom_tokens_dia`). 4) No new Discord call per tick. 5) The `discord/` tests keep passing.
- **W9. The panel shows the day's tokens.** `haiku`, `[W8]`. 1) `painel_bandeja.pyw` shows one line with the day's tokens (kitchen / waiter). 2) A waiter above 1M is highlighted. 3) An `estado.json` without the field → the line disappears and nothing breaks. 4) `test_widget_*.py` pass.
- **W10. `checar_tarefas.py`.** `sonnet`, `[]`. Deliverable: `agentes/checar_tarefas.py <folder>` + a test.
  1) An unknown `depende_de`, a task depending on itself, or a cycle → blocked (exits 1). 2) Two pending/running tasks, with no dependency between them, citing the same file path (with `/` or `\` and an extension) → a warning (exits 0). 3) Works with INFRA-, TAREFA- and CRM-. 4) Output ≤ 15 lines; optional `--json`. 5) Fixtures for a cycle, an unknown dependency and a shared file.
- **W11. Dispatch only after the check.** `haiku`, `[W10]`. 1) The data project's `despachar.sh` runs `checar_tarefas.py` and skips blocked tasks, saying why. 2) One line in the root `CLAUDE.md`: the waiter runs the check before dispatching a batch. 3) A test with W10's fixtures folder.
- **W12. The watcher re-alerts on waiting sessions.** `sonnet`, `[]`. 1) A session "waiting" for longer than `reavisar_minutos` (in `config.json`, default 15) raises a new alert every interval, in the same topic. 2) The alert says how long it has been waiting. 3) When the session moves again, the re-alerts stop. 4) A test with a fake clock.
- **W13. `cozinha_doctor.py`.** `haiku`, `[]`. 1) One ok/MISSING line for: tmux shim, claude, rtk, gh, python, go, watcher alive (`vigia.pid`), `estado.json` less than 2 min old, queue folder, hooks installed. 2) Never reads or prints a token. 3) Exits 1 if anything is missing. 4) Runs in < 5 s.
- **W14. The prompt carries the dependencies' result.** `sonnet`, `[]`. 1) `tarefa_enxuta.py` adds "## Dependências" with the first 8 lines of the `## Resultado` of each task in `depende_de`. 2) At most 40 extra lines. 3) A dependency not found → one warning line. 4) A test.

**Left out for now:** auto-tuning of the limits by memory pressure (heavy/tune.go). It only makes sense after W1 and W2 are in use.
If it comes, it follows work-cli's rules: drop fast, rise slowly (only after K good readings in a row), and a missing metric never raises the limit.
