---
name: dotask
description: Use when the user asks to run ONE task by id/slug all the way ("run <slug>", "do task X", "take it to the PR", "dotask <id>"). Supervisor on top of the kitchen — dispatches the task to a tmux session (the execute flow), writes the manifest, watches it with a deterministic watcher and only ends with an open PR. A bug found midway does NOT stop the task — it becomes a record via `plan --problem`. With --sync, pushes the task doc to your tracker at the end (optional integration).
---

# /dotask — task doc → open PR, without dropping it halfway

```
/dotask <slug|id> [--sync]    run until the PR is open; --sync pushes to the tracker at the end
/dotask <slug|id> --qa        same, then run /qa on the PR diff and comment the verdict
/dotask <slug|id> --status    only report where the task is (dispatches nothing)
```

**Read `../orchestrate/CORE.md` before any step.** This skill reimplements nothing: it
resolves the task, dispatches through the canonical mechanism (worktree + tmux session,
CORE §2, the `execute` flow) and **watches until the PR opens**. For several tasks at once,
use `/orchestrate`.

## Step 0 — Resolve the task

1. Adapter (CORE §1). `<id>` can be a **slug** (file `<vault.cards>/<slug>.md`) or a
   **tracker id** (search the task docs' front matter). No doc → if the adapter has a
   backlog reader (`backlog.reader`), read the card and create a minimal doc in the `plan`
   format before continuing; no card either → stop and suggest `/plan`.
   **A doc with `type: qa` (or a `qa-*` slug whose scope is testing, not building): the task
   IS a QA run** — invoke the `qa` skill and follow its flow (it has its own dispatch,
   watcher and report; the manifest is its own). The end of that route is the **report**,
   not a PR — the endings of Step 4 do not apply.
2. **Four eligibility filters** (CORE §1): status, layer, dependencies (`depends_on` open →
   stop and report the chain) and reality (already done?).
3. **Deterministic pre-flight, before dispatching anything:**

   ```bash
   python3 <skills>/orchestrate/scripts/doctor.py <repo>
   ```

   Contract: **exit 1 = critical → do NOT dispatch** (report what it flagged and stop);
   exit 0 = go on, carrying the warnings to the report. It covers `execute` Step 0 (clean
   main checkout, base == origin) and the health of `<gh>`.

## Step 1 — Route

CORE §2. The task needs the `scarce_resource` → **not a case for autonomous /dotask**: say
so and run it inline with the human (the `execute` flow). Inline keeps the manifest
(Step 2, worktree column = main checkout), the acceptance criteria as DoD, the detour rule,
the pre-PR review and Step 5 — it only skips the tmux dispatch and the watcher.
Kitchen route → continue.

## Step 2 — Manifest BEFORE dispatch

A batch of one is still a batch: write `<vault.plans>/YYYY-MM-DD-<slug>-manifest.md`
(CORE §7) with its single row at `⏸ queued`. Without a manifest `/harvest` **can never
clean this worktree** (CORE §7 boundary) and a crash becomes a mystery with no record.

## Step 3 — Dispatch

The canonical CORE §2 command: worktree + branch through `execute` Step 2 — **when the id
IS the slug (task born in `/plan`, no tracker card): branch = `<type>/<slug>`, without
repeating the slug** — and record the chosen branch in the doc's `branch:` field. A `.kitchen/done` left in a
reused worktree by an earlier attempt must be removed first — the watcher would read it as
"done" at once. Then `.kitchen/prompt.md`, session `kitchen-<slug>`, `--strict-mcp-config`. **`--model` comes
from the doc's `model_exec`** (the doc wins over the adapter's `model_by_size`; absent in
both = account default). Besides the standard content, the prompt carries FOUR rules of this
skill:

1. **Acceptance criteria are the DoD.** The PR only opens with every criterion of the doc
   checked (`- [x]`) or with the unchecked one justified in the PR body.
2. **The detour rule** (section below), verbatim.
3. **Independent pre-PR review.** Between the gates (`execute` Step 8) and the PR
   (Step 11), dispatch an in-session reviewer subagent with the doc's **`model_review`**,
   giving it the diff (`git diff <base>...HEAD`) + the acceptance criteria. It returns
   `APPROVED` or a list of problems; fix and repeat (≤3 rounds). No `APPROVED` by the 3rd →
   the stop protocol of `execute` Step 9 (`⏳` + reason). The review verdict goes in the PR
   body.
4. **Doc without a tracker id = the card does not exist yet.** The status lives in the doc's
   front matter (edit `status:` there); **do not call the tracker** — there is nothing to
   update. The card is born at `--sync`, if requested.

Update the manifest: `🔄 running` — and record the **dispatch instant**
(`dispatched: YYYY-MM-DD HH:MM` in the manifest's front matter; `created:` only has the
date, and a date does not tell two attempts on the same day apart). Step 4 needs it to not
confuse this batch's PR with a PR from an earlier attempt of the same task.

**Check the boot before arming the watcher:** ~30 s after dispatch,
`tmux capture-pane -p -t '=kitchen-<slug>:'` (trailing colon — CORE §2). Two possible
dialogs: the Bypass Permissions acceptance (first time on the machine) and folder trust
(attach, accept, detach). Without this check the watcher would watch a stuck dialog
thinking it is work.

## The detour rule — a bug midway does NOT stop the task

If the agent (or you) finds a bug/unexpected behaviour **outside the scope of the
acceptance criteria** during execution:

1. **Do not fix it.** Out of scope is out of scope.
2. **Record it** via `/plan --problem` (template Symptom / Origin / How to reproduce /
   Expected vs. actual): a new doc with file:line evidence and
   `found_during: <slug of this task>`.
3. **Note it in the PR**: the body lists "found along the way: <recorded slug(s)>".
4. **Carry on with the original task.** The record costs minutes; the detour would cost
   the PR.

Only exception: the bug **prevents** an acceptance criterion (the task cannot close on top
of it). That is a real blocker: record the problem the same way AND apply the `execute`
Step 9 stop protocol (`⏳ waiting on human` + reason on the manifest).

## Step 4 — Watch until the PR (without burning tokens on polling)

The watcher is **a background process, not an agent**:

```bash
python3 <skills>/orchestrate/scripts/watch.py <worktree> <slug> --manifest <manifest>
```

Exit codes: `0` done (`.kitchen/done` or `✅` on the row) · `2` crash (session dead, no
`done`) · `3` `⏳` waiting on human · `4` manifest missing (the ⏳/🚫 triggers would be
blind — fix the path) · `5` `🚫` aborted · `6` timeout with the session alive. It logs one
line per iteration (`alive/done/state`).

**A query that errors is not an answer.** Network failure, `<gh>` exit ≠ 0, timeout, 401,
empty JSON because of an error — all INCONCLUSIVE, never "no PR yet". Conclude nothing from
a failed check: do not rewrite the manifest, do not give up — try again. A network blip
read as a verdict is the easiest way to declare failure on work that was already done.

When the watcher exits, decide in this order:

- **exit 0** → the agent closed: confirm the PR
  (`<gh> pr view <branch> --json url,state,createdAt`), reap the session (hibernation,
  CORE §2) and go to Step 5. **The PR only counts if `createdAt` ≥ the manifest's
  `dispatched`** (with ~120 s slack for clocks/latency): branches are reused across
  attempts, and an already merged PR from an earlier attempt at the SAME task makes the
  watcher cry a false ✅. `createdAt` older than the dispatch = another batch's PR → treat
  as "no PR" and keep watching. `✅`/`done` without a verifiable PR (or only an old one) is
  an anomaly: flag it.
- **exit 3 (`⏳`)** → take it to the human NOW (reason + how to attach:
  `tmux attach -t '=kitchen-<slug>'`). Resolved in the agent's conversation → **rewrite the
  row to `🔄 running` yourself** (you are the waiter; without it the watcher wakes up on the
  same `⏳` and alerts in a loop — CORE §7, `⏳→🔄`) and watch again.
- **exit 2 (crash)** → CORE §7 reconciliation (inspect `git -C <worktree> status`/`log`,
  rewrite `.kitchen/prompt.md` with the partial state, recreate the session) and watch
  again. **Never** re-dispatch the original prompt on top of partial work.
- **exit 5 (`🚫`)** → stop and report the reason; cleanup is the waiter's role (CORE §11).
- **exit 6 (timeout)** → attach and look; do not conclude anything from the clock alone.

**/dotask only ends successfully when the PR is open.** The only other endings are `🚫` and
a `⏳` the human decided not to resolve now.

## Step 5 — Close

1. Manifest: `✅ PR` + number + session id (the agent already wrote it in `execute`
   Step 12; check).
2. Report: PR, commits, acceptance criteria checked (and what was justified), detours
   recorded (`/plan --problem` → slugs).
3. `--sync` (optional tracker integration, see `docs/integrations.md`): **dry-run first,
   always**, and confirm the dry-run targets **exactly 1 doc** and the right card (matching
   by name can grab the wrong card). Commenting on an existing, confirmed card → apply.
   **Creating a card** → show it and wait for the human's OK.
4. `--qa`: the PR opened → run the QA pass on the diff BEFORE the final report. Invoke `qa`
   with target `#<PR>`: depth **smoke** (`standard` if the doc has `size: L|XL`), anchor
   oracle = the doc's acceptance criteria. At the end: `<gh> pr comment <PR> --body` with
   the verdict + findings (1 line each) + link to the report — the ONLY write of `/qa` on a
   PR, and a failing verdict does NOT close the PR: it is information for the human review.
5. Remind: merging, closing the card and removing the worktree are the human's + `/harvest`.

## --status — read only

1. Newest manifest of the slug: glob `<vault.plans>/*-<slug>-manifest.md` (there may be
   several, from past attempts — take the newest).
2. One verdict line per source: manifest row (state) · `tmux has-session -t
   '=kitchen-<slug>'` (process alive?) · `.kitchen/done` (hibernated?) · `<gh> pr view
   <branch>` (PR — same `createdAt` rule as Step 4).
3. No manifest at all → "never dispatched; use `/dotask <slug>`".

Zero writes — touches no manifest, doc, session or tracker.

## This skill does NOT

- Sequence a backlog — several tasks is `/orchestrate`.
- Fix out-of-scope bugs (detour rule: record and carry on).
- Merge, close cards or remove worktrees (`/harvest` after the merge).
- Push to a tracker without `--sync`, and never CREATE a card there without the human's OK.
- Watch with an agent in a loop — the watcher is a process; tokens are spent on work.
