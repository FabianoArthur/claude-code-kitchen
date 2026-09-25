---
name: orchestrate
description: Use when the user asks to sequence, plan or dispatch SEVERAL tasks at once — from backlog ids, from an epic/keyword, or from a free-form description of work. Decides what runs in parallel in the kitchen (tmux sessions), what stays in the inline queue with the human, what becomes a single PR, and writes a durable manifest so the batch survives the session. Also for backlog triage ("what order", "can these run together", "split this feature into parallel tasks") and for resuming an interrupted batch (--resume).
---

# /orchestrate — backlog → manifest → dispatched batch

```
/orchestrate <id> [id2 …]        sequence existing orders
/orchestrate <epic | keyword>    sequence the open orders of the epic
/orchestrate "<description>"     propose orders → CONFIRM → sequence
/orchestrate --resume            reconcile and continue the last batch
```

**Read `CORE.md` (same folder) before any step.** Companion of `execute` (runs one unit)
and `harvest` (sweeps what was merged).

Use it when there are **3+ candidates**, or when a feature must be split. For a single
unit, go straight to `execute` (or `dotask`).

---

## Step 0 — Adapter and pre-flight

1. Load the adapter (CORE §1). No adapter → bootstrap (CORE §9) and **stop for
   confirmation**.
2. Pre-flight — `python3 <this folder>/scripts/doctor.py <repo>` covers the machine
   (claude/tmux on PATH, adapter, `origin/<base>`, worktrees dir, `gh auth`, `.kitchen/`
   excluded, live sessions, disk). **Exit 1 = do not dispatch.** Then, and **stop at the
   first failure**:
   - `git status --porcelain` on the main checkout → **dirty = stop.** List what is there
     and ask: commit, stash, or continue knowing the inline queue works in that same
     checkout. Do not decide alone: it may be days of offline work.
   - local `base` == `origin/base`? Diverged → show the difference and ask.
3. `--resume`: read the last manifest, **reconcile against real git** (CORE §7) and
   continue where it stopped. Do not reprocess a unit already at `✅ PR`.

## Step 1 — Gather candidates

**Ids or epic/keyword** → read the orders from the backlog. Drop what is not open and
**report what was dropped, with its status**; never omit silently.

**Free-form description** → the work is not in the backlog yet:

1. Split it into the smallest sensible deliverables. For each: short title, probable
   layer, estimated size, one-line scope.
2. Show the whole table and **STOP — the human confirms, edits or cuts.** This is the only
   mandatory human gate of this skill.
3. Only after confirmation, create the orders in the project's format (use `plan`) and
   continue.

## Step 2 — Read each candidate

Extract: size, epic, priority, declared dependencies, files cited in technical notes, **and
whether it touches a visual surface or the `scarce_resource`**.

**Treat a file cited in an order as a hint, not a fact.** Confirm it against the disk
before using it in a decision — an order describes the intent of the day it was written.

## Step 3 — Preliminary blast radius

For each candidate, sketch the blast radius (CORE §4) — enough to detect collisions. A
code-graph query if you have one, plus reading the entry point.

It is not the final blast radius (that is born in the plan, inside `execute`); it is the
input of Step 5.

## Step 4 — Route each unit

Apply CORE §2. Tag each unit:

- `[kitchen]` — no visual surface
- `[kitchen: stop before commit]` — visual, without needing the scarce resource
- `[inline]` — needs the scarce resource

## Step 5 — Group and order

- **bundle**: same epic + one deliverable → one worktree/branch/PR, carrier = first id.
- **collision**: blast radii that intersect → **not in the same batch**. Order them: the
  one that unblocks goes first.
- **stack**: real dependency → a note in the manifest, no branch machinery (CORE §8).

A unit is in at most one bundle.

## Step 6 — Estimate

From order size to time-to-open-PR (agent working, not counting human review). Default
t-shirt scale (override in the adapter if your project uses another):

| size | ≈ |
|---|---|
| XS | ~15 min |
| S | 15–30 min |
| M | 30–60 min |
| L | 1–2 h |
| XL | 2–4 h |

A bundle ≈ its largest member, not the sum. Report two numbers:

- **parallel** = max(kitchen batch) **+** sum of the inline queue (it is serial);
- **sequential** = sum of everything.

And say what limits the parallelism. Do not refine further — the estimate's only job is to
tell which unit to sit with.

## Step 7 — Write the manifest BEFORE dispatching

Write the manifest (CORE §7) with everything at `⏸ queued`. **Before** firing any kitchen
session — a manifest written after dispatch protects nothing.

## Step 8 — Present the batch

One line per unit: `id · size · route · ~time · why`. Bundles grouped under the carrier.
Then: the two totals, what limits them, and the two-tempo plan in one sentence ("I fire the
N kitchen units and start the inline queue with you on <id>").

If the batch has >1 inline unit, say the order and why.

## Step 9 — Ask, then actually dispatch

**Ask: "fire these N now, or hold?"** Do not stop at the manifest — stopping there is the
friction this system exists to remove.

On yes:

1. **Kitchen batch** — one tmux session per unit (CORE §2): create worktree and branch
   **with the canonical command of `execute` Step 2** (`git worktree add
   <worktrees>/<ID> -b <branch> <base>` + the adapter's `prepare_worktree`), write
   `<worktree>/.kitchen/prompt.md` (id, route, exact branch, paths of the adapter, of CORE
   and **of the manifest**, preliminary blast radius, and the instruction to follow
   `execute` through the kitchen entry point) and `.kitchen/launch.sh` with the canonical
   dispatch command.
   **No `max_parallel` in the adapter:** run every `launch.sh` before the inline queue.
   **With `max_parallel`:** write the queue `<worktrees>/.kitchen-queue.tsv` and start only
   the dispatcher (CORE §2) — it doses, reaps hibernated sessions and exits by itself.
2. Update the manifest: `🔄 running`, and `dispatched: YYYY-MM-DD HH:MM` in its front matter.
3. **Check the boot** ~30 s later: `tmux capture-pane -p -t '=kitchen-<ID>:'`. Accept the
   bypass/trust dialogs if they are showing (CORE §2).
4. **Immediately**, without waiting for the batch: start the **first unit of the inline
   queue** with the human, in the main checkout, following `execute`. That is the second
   tempo.
5. A dispatched session **does not report back here** — the fine state signal is the
   **manifest** (each kitchen writes its own row at every transition:
   `🔄`→`⏳`/`✅`/`🚫`), crossed with `<gh> pr list`. `tmux ls` only tells **alive/dead**: a
   live session does not mean working. To watch without spending tokens, run
   `scripts/watch.py` in the background (see `dotask`). Tell the human how to follow:
   `tmux attach -t '=kitchen-<ID>'` (detach: `Ctrl-b d`). A unit in
   `[stop before commit]` pauses in its own tmux session with the diff ready — the human
   attaches, reviews and approves (or asks for changes) in that kitchen's conversation.

On "hold": leave the manifest and the line to resume (`/orchestrate --resume`).

## Step 10 — Close the batch

When no unit is left at `🔄` or `⏸` — by the **reconciled manifest** (rows written by the
kitchens themselves, crossed with `<gh> pr list`; CORE §7). `tmux ls` here only flags
anomalies: a dead process with a row still at `🔄` and no `.kitchen/done` = investigate
before closing.

1. If the adapter has `status_push`: run it **once per epic touched** (not once per order).
2. Report: what opened a PR, what waits on a human, what aborted and why.
3. End with the reminder: **run `/harvest` after merging** — it is not automatic, by
   design (polling costs an agent round per trigger; merges happen a few times a day).

## This skill does NOT

- Merge, close orders, or remove worktrees — that is `harvest`, and a human call.
- Create anything in the backlog without explicit confirmation (Step 1).
- Dispatch silently: Step 9 waits for a yes.
- Brainstorm or write plans — that is per unit, inside `execute`. This is backlog
  sequencing, one level above.
