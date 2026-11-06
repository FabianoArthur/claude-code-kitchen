---
name: save
description: Use when the user wants to save the state of the session so the next one can pick it up — "save the session", "save progress", "log where we are", "/save", or at the end of a work block before /clear. Writes LOCALLY into the task doc (one doc per task, the same one plan and execute use) — rewrites Current state, updates Pending, prepends a Session log entry (Changed · Decisions · Pending), marks sync_pending, keeps ## Links. No commit, no push, no tracker call; pushing to a tracker is a separate, explicit step. Pairs with /resume.
---

# /save — the session's state, into the task doc

```
/save                  the active task (from the branch, or the most recently updated doc)
/save <slug|id>        that task; creates the doc if it does not exist yet
```

**Read `../orchestrate/CORE.md` §1** — the adapter (`.claude/orchestrator.md`, found walking
up from cwd) provides `vault.cards` (where task docs live), `backlog.*` (status vocabulary)
and, optionally, `vault.permanent`. No adapter, or no `vault.cards` → **ask** where task
docs go and write the answer into the adapter; do not invent a path.

Companion: `/resume` reads what this writes. The doc is the same one `/plan` creates and
`/execute` fills (`## Outcome`), so one task has one doc for its whole life.

**Local first.** This skill writes one local Markdown file. It does not touch a tracker, the
manifest or git. The tracker (if you use one) catches up in a separate, explicit step; the
only signal between the two is `sync_pending: true` in the front matter. That is what keeps
saving free: no API call, no tokens spent on a remote read.

## Step 1 — Resolve the target doc

- Argument given → match it against file names in `<vault.cards>`, then against `card_id`
  and `title` in the front matter. One match → use it.
- No argument → the active task: `git branch --show-current` against the `branch:` front
  matter key, then the most recently `updated:` doc. **Do not query a tracker to find it.**
- No match → create `<vault.cards>/<slug>.md` from the template of `/plan` (also
  `examples/task.md`), using the argument as slug and title. Fields you cannot know
  (`priority`, `size`, `repos`, `card_id`) stay **empty** — never guess them; `/plan --revise`
  or the human fills them. If the argument looks like a tracker id, put it in `card_id:`.
- Several candidates and no way to tell → ask one question (CORE §10 allows it: the answer
  changes where you write).

## Step 2 — Update the doc

Get the date with `date +%F` — never from memory.

1. **`## Current state`** — rewrite it: one self-contained paragraph, what is true *now*
   (it overwrites the previous one; the history is the log).
2. **`## Pending`** — a checklist of what is left. Create the section (after `## Current
   state`) if the doc has none; tick what this session finished, add what it discovered.
3. **`## Session log`** — **prepend** (newest first) a new entry:

   ```markdown
   ### YYYY-MM-DD — saved by /save ⏳ to sync
   - **Changed:** what was done, with `file:line` where it helps (describe, do not stage).
   - **Decisions:** what was decided and why — the part nobody can rederive from the diff.
   - **Pending:** what is left, in one line (the checklist above has the detail).
   ```

   The `⏳ to sync` marker is what `/sync` looks for: it posts the marked entries to the
   tracker and flips the marker to `✅ synced <date>`. Without a tracker it is just a
   harmless label.

   Several saves in one day → one entry per save; do not merge them. Never edit older
   entries.
4. **Front matter** — `updated: <date>` and `sync_pending: true`. Change the status field
   (`backlog.status_field`) **only** if the session clearly moved the task, and only to a
   value from the adapter's vocabulary (`open_statuses` and friends); otherwise leave it.
5. **`## Links`** — keep the section and make sure it holds the repo or integration the
   session touched and any permanent note it used or created. Missing section → create it
   before `## Session log`.
6. **Durable decision?** If the session settled something that constrains work *outside*
   this task, and the adapter has `vault.permanent`, write one line to
   `<vault.permanent>/<area>.md` with a link back to the doc (CORE §6 — the cut is "if this
   is forgotten, will someone break or re-litigate it in 3 months?"). No `vault.permanent`
   → leave it in the task doc; do not create a folder.

Do not touch `## Outcome` (written by `/execute` from git) or any section the doc template
does not define. Do not describe code structure in prose — that is a code graph's job.

## Step 3 — Confirm

Report: the doc's path and `sync_pending: true`. If the adapter has a `status_push`
command (or you use `/sync`), name it and say the push is a separate step you did not run; if it has none, say
nothing about trackers.

## This skill does NOT

- Commit, stage, push or open a PR — the diff of the repo is not its business. No commit,
  no push.
- Call a tracker — no tracker call, no MCP, no API. `sync_pending` is the handoff.
- Clear `sync_pending` — only whoever actually pushes to the tracker does (`/sync`).
- Edit a manifest — each kitchen owns its own row (CORE §7).
- Start working on the pending items.
