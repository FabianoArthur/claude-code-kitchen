---
name: harvest
description: Use when the user asks to clean up, sweep or harvest what was already merged — checks every worktree recorded in a manifest, removes the ones whose PR was merged, moves durable knowledge into permanent notes, deletes the ephemeral record and reports what is still in flight. Manual trigger by design; run it after merging a PR. Also for "what is still open", "which worktrees can I delete", "clean up what landed".
---

# /harvest — sweep what was merged

```
/harvest              sweep everything recorded in a manifest
/harvest <id>         only this unit
/harvest --dry        report without deleting anything
```

**Read `../orchestrate/CORE.md` before any step.**

## Why it is manual, and will stay that way

There is no cheap event trigger for "PR merged" in a local setup. The options are polling
(cron / a scheduled cloud routine), each trigger costs a full agent round, and merges happen
a few times a day. Running `/harvest` yourself after merging is **free and instant**; paying
an agent to watch is not.

If a real webhook shows up, revisit. Until then: manual, by decision, not by omission.

---

## Step 1 — Enumerate candidates

Read the manifests at `<vault.plans>/*-manifest.md`. The worktrees listed there are the
**only** ones this skill may touch.

> **A worktree without a manifest entry is NEVER touched.** It belongs to another flow,
> another person, or predates this convention. **Report it, do not touch it.** Compare
> `git worktree list` with what is in manifests and list orphans as information.

## Step 2 — Check each candidate's merge

`<gh> pr view <branch> --json state,mergedAt,number`

`<gh>` = the adapter's `gh` field if present; otherwise plain `gh` (CORE §1). It matters
here more than anywhere: a `gh` broken by an environment variable returns HTTP 401, and
without verification **there is no cleanup** — better to delete nothing than to delete based
on a misread error.

| state | action |
|---|---|
| `MERGED` | eligible for cleanup (Step 3) |
| `OPEN` | skip, report as still in review |
| PR not found | skip and **flag** — something is out of place; do not guess |

**The merge is the gate, not the backlog status.** Closing the card is a separate human call
and can lag or lead the merge. Do not block cleanup because of it — but **report** each
card's current status in the summary, so the human sees what is pending.

`gh` unavailable → **assume nothing.** Report that it could not be verified and stop.

## Step 3 — Clean an eligible worktree

In order, and stop at any resistance:

1. `tmux has-session -t '=kitchen-<ID>' 2>/dev/null` → session alive? With the PR
   **verified MERGED** in Step 2, its work is over: `tmux kill-session -t '=kitchen-<ID>'`.
   The `=` is exact match and the quotes are mandatory — without it tmux matches by prefix
   and `kitchen-FE-2` kills `kitchen-FE-21`. Kill **before** the remove: git does NOT refuse
   to remove a clean worktree with a live process inside — without the kill an agent keeps
   running in a deleted directory. Without a verified merge: kill only if `.kitchen/done`
   exists in the worktree (the agent hibernated by contract; the context comes back with
   `claude --resume <session-id>` from the manifest row); without `done`, **do not kill** —
   there may be a conversation/adjustment in progress in there.
2. `git worktree remove <dir>` — from the main checkout. **Never `rm -rf`**: it leaves the
   worktree registered and git complains at the next `worktree add`.
   - Refused because of uncommitted changes → **stop and show the human.** A merged branch
     may still hold a draft file worth a second look. Do not force. (`.kitchen/` does not
     count: it is dispatch machinery, expected and ignored via `info/exclude`.)
3. `git branch -d <branch>` — lowercase `-d`, never `-D`. A real merge makes `-d` safe; if
   git refuses, the branch was **not** merged into the local base and you must **stop**, not
   force. (A squash-merged PR is the usual cause: fetch and fast-forward the base first; if
   git still refuses, report it and let the human decide.)
4. Before the directory disappears, look for artifacts that should not be there (build
   output, log dirs). If any, **only record it** — its owner decides.

## Step 4 — Consolidate and delete the ephemeral note

Before removing the manifest entry:

1. Does it hold a durable decision not yet in `permanent/` nor in the task doc's
   `## Outcome`? Move it there **now** (CORE §6), linking back to the order. Knowledge does
   not die with cleanup.
2. Mark the unit as harvested in the manifest.
3. Manifest with **every** unit harvested → fold what is left of durable into where it
   belongs and **delete the manifest**. An ephemeral note does not outlive its checkout.

## Step 5 — Report

One line per worktree: **cleaned** / **skipped** (why) / **flagged** (why). Then:

- what is still in flight (open PR, queued unit, `kitchen-*` tmux session still running);
- cards whose status is pending closure in the backlog;
- orphan worktrees found (information, not action);
- `kitchen-*` tmux sessions without a manifest entry (`tmux ls`) — information, not action;
- local branches merged outside this flow, if you notice them (information).

If nothing is left in flight, say it plainly ("nothing in flight — `/clear` whenever you
want"). Do **not** try to invoke `/clear`: it is a REPL reset, there is no tool for it.

## This skill does NOT

- Merge PRs or close cards — both are the human's calls.
- Touch a worktree outside a manifest.
- Force `-D` on a branch or `rm -rf` a worktree. Git's resistance is a signal, not an
  obstacle.
- Infer a merge without `gh`. No verification, no cleanup.
