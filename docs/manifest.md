# The manifest (the ticket)

`<vault.plans>/YYYY-MM-DD-<slug>-manifest.md` — one per batch (a `/dotask` is a batch of
one). It is written **before** anything is dispatched, and it is the only thing that tells
you, after a reboot, what was in flight.

```markdown
---
type: manifest
project: my-app
base: main @ 1a2b3c4
created: 2026-01-15
dispatched: 2026-01-15 14:05
---
| unit | size | route | state | branch/worktree | PR | session (resume) |
|------|------|-------|-------|-----------------|----|------------------|
| rate-limit-login | M | kitchen | ✅ PR #42 | feat/rate-limit-login | #42 | 7f3c…e1 |
| audit-log-export | S | kitchen | ⏳ waiting on human: needs the export format decided | feat/audit-log-export | | |
| new-onboarding-ui | L | inline | ⏸ queued | (main checkout) | | |
```

## States and who writes them

| state | meaning | written by |
|---|---|---|
| `⏸ queued` | in the batch, not dispatched yet | waiter |
| `🔄 running` | a kitchen is working on it | waiter at dispatch; **whoever unblocks a `⏳`** |
| `⏳ waiting on human` | stopped on a real blocker — the reason is in the cell | the kitchen |
| `✅ PR` | PR open (number + session id recorded) | the kitchen |
| `🚫 aborted` | dropped — the reason is in the cell | the kitchen |

- Each kitchen edits **only its own row** (the one whose first cell is its id). The waiter
  writes the others.
- `⏳` is always followed by a one-line reason. A `🔄` row with a stopped agent is the
  system's invisible failure mode — that is why every stop writes `⏳` first.
- `⏳ → 🔄` is the resume. Whoever resolved the pause rewrites the row; otherwise the watcher
  wakes up on the same `⏳` and alerts in a loop.

## The `dispatched:` time

Branches are reused across attempts. When the watcher says "done", the waiter confirms the PR
with `gh pr view <branch> --json createdAt` and only trusts a PR created **after**
`dispatched:` (with ~2 minutes of slack). An older PR belongs to an earlier attempt.

## Hibernation

A finished kitchen writes its Claude Code session id to its row and to
`<worktree>/.kitchen/done`. From then on the tmux session may be killed to free RAM — by the
dispatcher, by `/harvest`, or by the waiter — and revived later:

```bash
tmux new-session -d -s kitchen-<id> -c <worktree> \
  'env -u CLAUDECODE KITCHEN_SESSION=1 <claude> --resume <session-id> --dangerously-skip-permissions --strict-mcp-config'
```

## Reconciling after a crash or reboot

The file is a record, not the truth. For each row, check reality:

| session | `.kitchen/done` | row | meaning | action |
|---|---|---|---|---|
| alive | — | any | working, paused, or idle in conversation | the row says which |
| dead | present | ✅ | hibernated | nothing; `--resume` if you need it |
| dead | absent | 🔄 | crashed / rebooted | inspect `git status` + `git log` in the worktree, rewrite `.kitchen/prompt.md` describing what you found, recreate the session |

Never re-dispatch the original prompt on top of partial work.

## Watching without tokens

```bash
python3 skills/orchestrate/scripts/watch.py <worktree> <id> --manifest <manifest>
```

Exit codes: `0` done · `2` crash · `3` waiting on human · `4` manifest missing · `5` aborted
· `6` timeout. It reads the unit's row by **exact** id match, so `task-2` never reads
`task-21`'s state.

## Harvest boundary

`/harvest` touches only worktrees listed in some manifest. Anything else is reported and left
alone. When every unit of a manifest is harvested, durable decisions move to
`vault.permanent` and the manifest is deleted.
