---
name: plan
description: Use when the user asks to plan or break work into tasks ("plan this", "create the tasks for this", "turn it into cards", "build the plan for X"), and in --problem mode when a human OR an agent in the middle of another task needs to record a bug/unexpected behaviour without stopping what it is doing. Writes task docs — What / Why / Acceptance criteria / Technical notes (task) or Symptom / Origin / How to reproduce / Expected vs. actual (problem) — ready for /dotask to execute and for an optional tracker sync.
---

# /plan — brainstorm → task docs

```
/plan <description of what to build/change>   split into tasks and write the docs
/plan --problem <report of the finding>        record a problem WITHOUT stopping whoever found it
/plan --revise <slug>                          refine an existing task
```

**Read `../orchestrate/CORE.md` §1** — the adapter (`.claude/orchestrator.md`, found walking
up from cwd) provides `vault.cards`, `backlog.*`, the size scale and `layers`. No adapter →
CORE §9 bootstrap; **do not invent a docs path**.

Companions: `/dotask` runs one task created here; `/orchestrate` sequences several. This
skill only PLANS and WRITES.

## Step 1 — Real context before any task

- Understand the request against the code as it IS: a code-graph query (if you have one) +
  reading the entry point. A task planned only from the request's text is born wrong —
  text describes intent, not what exists.
- **Reality filter (CORE §1.4):** was the request (or part of it) already done?
  `git log <base> --grep`, the named artifact in the code. Already there → report it with
  the evidence (sha, file:line) and do NOT create the task.
- Ambiguity that reading the code does not resolve → **ask before splitting** (one question
  at a time). Preference and validating the obvious do not count (CORE §10).

## Step 2 — Split

- Smallest sensible deliverables; **each task = one PR** that stands on its own.
- Per task: short title, repo/layer (adapter vocabulary), `size` on the adapter's scale
  (default `XS|S|M|L|XL`), **`priority` (urgent|high|normal|low — required)**, `depends_on`
  (slugs/ids that must close first).
- Two tasks crossing the same files → note the collision in both tasks' Technical notes
  (`/orchestrate` uses it to keep them out of the same batch).

## Step 3 — Confirm BEFORE writing

Show the table (title · size · priority · repo · depends_on · one-line scope) and **STOP —
the human confirms, edits or cuts.** It is this skill's only human gate.
Exception: `--problem` mode does not pause — a record is not a decision; write and report.

## Step 4 — Write the docs

One file per task: `<vault.cards>/<kebab-slug>.md`. The slug is the **local id** — it is
what `/dotask` receives. Task template (also in `examples/task.md`):

```markdown
---
card_id:
title: "<slug> — <short title>"
status: backlog
priority: <urgent|high|normal|low>
size: <XS|S|M|L|XL>
difficulty: <low|medium|high>
model_exec: <alias for --model at dispatch — guide below>
model_review: <alias for the independent pre-PR reviewer — guide below>
repos: <repo(s), comma separated>
branch:
depends_on:
epic:
updated: <YYYY-MM-DD>
type: task
origin: plan
---

# <short title>

## What
<the deliverable in 1–3 sentences — what changes in the system when this closes>

## Why
<motivation tied to a fact: the task/PR/incident it came from, the risk it covers>

## Acceptance criteria
- [ ] <verifiable, with HOW to verify (command, screen, API call …)>
- [ ] <…>

## Technical notes
<file:line, what already exists, constraints, reference PR/commit, collisions>

## Current state
<one self-contained line — a tracker sync can use it as the card description>

## Links
- <repo / integration / related tasks / permanent notes>

## Session log
### <YYYY-MM-DD> — created by /plan
- **Changed:** task created from <request/context>.
```

Template rules:

- **An acceptance criterion is verifiable**: each one says HOW to verify it. "Works
  correctly" is not a criterion; `gh api repos/<owner>/<repo>/rules/branches/main` showing
  the check is.
- **Technical notes carry the context you already paid to gather** — file:line, what
  exists, where it came from. Whoever executes should not rediscover any of it.
- Dates: `date +%F`. Never from memory.
- `epic:` is optional — fill it when the split came from an epic (`status_push` runs once
  per epic).
- **Slug collision**: a file with that name already exists → do NOT overwrite. Same task →
  it is a `--revise` case (append, do not recreate); different task → suffix the slug; in
  doubt, resolve it at the Step 3 gate.

### Difficulty and models — who executes and who reviews

`size` measures duration; `difficulty` measures the risk of getting it wrong. A giant rename
is L/low; a concurrency fix is S/high. The pair picks the models (aliases of
`claude --model`; **the doc WINS over the adapter's `model_by_size`** at dispatch):

| difficulty | model_exec | model_review |
|---|---|---|
| low — mechanical, config, text, rename | sonnet | sonnet |
| medium — ordinary logic, known integration | sonnet | opus |
| high — concurrency, data migration, algorithm, production | opus | opus |

Deviating from the table → justify it in the Technical notes. In doubt between two levels,
pick the higher one: a stronger review is cheap next to a wrong PR.

## Step 5 — Report

Slugs created + how to continue: `/dotask <slug>` (run one) · `/orchestrate <slugs>`
(sequence several) · tracker sync (if you use one — a separate, human call).

## --revise mode — refine an existing task

Reopen `<vault.cards>/<slug>.md` and apply Steps 1–3 to it (real context again — the code
may have moved since it was created). Rules:

- Keep `card_id` — the tracker card stays the same.
- May change `size`/`difficulty`/`model_*`/`depends_on`/criteria — and goes through the
  Step 3 human gate like any plan.
- Log it in `## Session log` (`### <date> — revised by /plan --revise`, saying what changed).
- Task at `🔄`/`⏳` in some manifest → **do not revise under a running agent**: report and
  stop.

## --problem mode — record without stopping anyone

For a bug/unexpected behaviour found in the middle of other work (by you, by the human, or
by a `/dotask` kitchen session — the "detour rule" there points here). Rules:

1. **Do not fix.** Recording is not executing; fixing here is scope leak.
2. **Do not stop the caller.** Whoever was executing carries on with the original task.
3. **Real evidence**: file:line of the culprits, grep output, origin PR/epic — no "it
   seems". Without enough evidence, write what remains to be verified.
4. **Dedup**: before creating, search `<vault.cards>` for a similar symptom. Already there →
   add the new evidence to the existing doc instead of duplicating.

Problem template (same front matter as a task, with `origin: plan--problem` and
`found_during`):

```markdown
---
card_id:
title: "<slug> — <symptom in half a line>"
status: backlog
priority: <estimated from the evidence — production broken or data being corrupted → urgent/high; say you estimated>
size: <estimated — say you estimated>
difficulty: <estimated — a bug of unknown cause is never "low">
model_exec: <per the difficulty table>
model_review: <per the difficulty table>
repos: <repo where the bug lives>
branch:
depends_on:
updated: <YYYY-MM-DD>
type: task
origin: plan--problem
found_during: "<slug/id of the task running when the problem showed up>"
---

# <symptom in half a line>

## Symptom
<the wrong behaviour, from the point of view of whoever uses the system>

## Origin
<repo · origin epic/PR · file:line of the culprits — with what grep/reading proved, e.g.
"loadDraft defined in draft-storage.ts:22 but NOT called anywhere (grep: definition +
test only)">

## How to reproduce
1. <concrete step>
2. <concrete step>
3. <concrete step>

## Expected vs. actual
**Expected:** <the promised behaviour, with the reference (design/spec/card) that promises
it> / **Actual:** <what happens>. Side effect: <secondary effect, if any>.

## Current state
Problem recorded via /plan --problem during <found_during> — evidence above; no fix applied.

## Session log
### <YYYY-MM-DD> — recorded by /plan --problem
- **Changed:** record created; no fix applied (detour rule).
```

## This skill does NOT

- Execute, open a PR or create a branch — that is `/dotask` / `/execute`.
- Push to a tracker — that is a separate call.
- Create a task for something that already exists (reality filter first, always).
- Fix the problem it is recording (`--problem` mode).
- Write outside `<vault.cards>` or invent fields outside the template.
