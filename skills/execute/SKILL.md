---
name: execute
description: Use when the user asks to execute/do ONE backlog task identified by an id (or a handful that form a single deliverable) — takes it from the task doc to an open PR without pausing for plan approval, stopping only on a real blocker. Creates branch and worktree from the base, builds the blast radius, applies TDD on logic, runs the deterministic gates, records the decision and the why, and opens the PR. For several tasks at once, use `orchestrate` first.
---

# /execute — task → open PR

```
/execute <id> [id2 …]     one unit (several ids = a bundle, if they form one deliverable)
/execute <id> --inline    force the inline route (main checkout, with the human)
```

**Read `../orchestrate/CORE.md` before any step.** This skill is the engine of one unit;
`orchestrate` decides what became a unit.

What it adds on top of a normal development flow: pre-flight, a reconciled blast radius,
the three gates, a mandatory record, and **the hard rule that plan approval does NOT pause
for the human.**

---

## Step 0 — Pre-flight

1. Load the adapter (CORE §1). No adapter → bootstrap (CORE §9), stop to confirm.
2. Read the task doc and apply the **four eligibility filters** (CORE §1): status, layer,
   dependencies, **and the reality check** (was it already done?). Failing any → **report
   the reason with the evidence and stop.** Do not take over someone else's work, do not
   resume something under review, do not try an order from another layer, do not start an
   order with an open dependency, and **never rebuild on top of something that already
   exists** — order status drifts.
3. `git status --porcelain` on a dirty main checkout → **stop and ask** (commit, stash, or
   continue). The inline queue uses that same checkout.
4. local `base` == `origin/base`? Diverged → show it and ask.
5. Several ids: are they one deliverable (same epic, one PR makes sense)? Yes → bundle,
   carrier = first id. No → **stop and say** they are separate units; suggest `orchestrate`.

## Step 1 — Route

CORE §2. Announce the route in one line, with the reason.

- `inline` → works in the **main checkout**, on a new branch from `base`. No worktree (a
  new worktree rebuilds from scratch; the main checkout has the cache).
- `kitchen` / `kitchen: stop before commit` → worktree.

**Kitchen route decided in the waiter** (you are NOT inside a `kitchen-<ID>` tmux
session): run the full pre-flight (Step 0), prepare worktree and branch (Step 2), write
`.kitchen/prompt.md` and dispatch the tmux session (CORE §2). Your job ends there — report
how to follow it (`tmux attach -t '=kitchen-<ID>'`).

**Kitchen entry point** (your prompt came from `.kitchen/prompt.md`): run only items 1–2 of
Step 0 (adapter + four filters) and **skip 0.3–0.5** — the main checkout's pre-flight
belongs to whoever dispatched, and a dirty main checkout is normal during a batch (the
inline queue works there; not your problem). In Step 2, only confirm the branch. From
Step 3 on, everything is yours.

## Step 2 — Branch and workplace

Branch: `<type>/<ID>-<kebab-slug>`, type derived from the order (`feat` for a task, `fix`
for a bug). Validate it against the adapter's `branch_regex`; without the field, use
`^(feat|fix|perf|refactor|chore|docs)/[a-zA-Z0-9][a-zA-Z0-9._/-]*$` — the id format belongs
to the project's tracker, **never assume one**. An id that already IS a kebab slug (a task
born in `plan`, no tracker card): branch = `<type>/<slug>`, without repeating the slug.

Kitchen route: `git worktree add <worktrees>/<ID> -b <branch> <base>`, then the adapter's
`prepare_worktree` (absent = nothing to run; **do not invent one** — an install inside a
worktree whose dependencies are symlinked, for instance, pollutes the shared copy). **If you
are the agent inside the tmux session**, worktree and branch were created at dispatch —
confirm (`git branch --show-current` matches the branch in your prompt?) and go to Step 3.

Inline route: `git switch -c <branch> <base>` in the main checkout.

## Step 3 — Status: in progress

Write the order's status field = in progress. Do **not** run `status_push` now — it runs
once per epic at the end of the batch (`orchestrate` Step 10).

## Step 4 — Brainstorm, seeded from the order

Brainstorm the approach **seeded by the description and acceptance criteria you already
read**. Do not ask the human to repeat what is written in the order. (If you use a
brainstorming skill, invoke it here.)

Only ask when the order is ambiguous in a way that **reading the code does not resolve**
(CORE §10). Preference, validating the obvious, or "confirm I understood?" do not count.

Inline route: the human is present, so conversation is natural — but still do not ask what
the order already answers.

Kitchen session: **mute** brainstorming — zero questions to the human. An ambiguity that
reading the code does not resolve = a real stop: Step 9 protocol (`⏳` + reason on your
manifest row), never a question left hanging in the conversation.

## Step 5 — Plan, with blast radius

Write the plan to `<vault.plans>/<ID>-<slug>.md` (or next to the task doc if the adapter
has no `vault.plans`).

The plan **must** contain a `## Blast radius` section in the adapter's `layers` vocabulary
(CORE §4). Build it from a code-graph query (if any) + actually reading the entry point,
never from the order's text. Validate that every path exists or is marked `[new]`.

A plan without a valid blast radius does not go to Step 7.

## Step 6 — Plan review gate (large units only)

If the unit is large (default `L`/`XL`): dispatch an **independent** subagent (here, yes,
the in-session subagent tool — CORE §2, exception for the plan gate; do not open another
tmux session) to review the **plan**, giving it plan + blast radius. It answers `APPROVED`
or objections. Iterate ≤4 rounds.

> **Do NOT pause for the human here.** Not to notify, not out of habit. The independent
> reviewer is the approval; the human comes in at the PR. This step is why the kitchen
> exists.

Small/medium unit: no gate, straight to Step 7.

## Step 7 — Implement

**Logic / data / infra:** test-driven — a test that **fails before** and passes after. A
test written at the end does not count as TDD; do not claim it does.

**Visual / UI:** implement and exercise it on the `scarce_resource`. Do not pretend a
widget test covers layout (CORE §5).

Implement **in this session, sequentially**. Do not fan implementation out to
sub-subagents — the kitchen's parallelism comes from several units, not from chopping one.
(This does not affect Step 6: that is a review gate, not implementation.)

**If you find you need `tests.forbidden`** (the scarce resource) and you are a kitchen
session: **do not run it.** Set your manifest row to `⏳ waiting on human — reclassify
inline` and stay idle in the conversation (Step 9 protocol). The waiter/human reclassifies
at reconciliation.

## Step 8 — Gates, before the commit

In this order, none optional:

1. **`tests.allowed` green.** Red because of a real bug → CORE §10, stop. Red because of the
   environment → fix it and continue.
2. **`forbidden_in_diff`** (CORE §3a): hit → **fix it and rerun the gate**, without asking.
   Run `gate_forbidden_in_diff` (default `../orchestrate/scripts/gate_diff.py`) **pointing
   at the directory where the diff is** (the worktree, not the repo root — pointing at the
   root reads the wrong index and answers "clean" without having looked at anything).
3. **Blast radius reconciliation** (CORE §4): `git diff --name-only` against the declared
   list. Bucket `touched − declared` > ~30% → record the warning in Step 10.
4. **DoD** for the unit's type (CORE §5).

**Honest gates — evidence before claims.** Each gate's result enters the report and the PR
body as **one line per check you ACTUALLY ran**, with the real number/outcome from the
command output (`174 tests, 0 failures`; `lint: 0 errors`), never "should pass" or "ok". A
gate you did **not** run is `⚠️`/`❌` with a one-word reason — **never a green ✅ you cannot
back with command output.** Applies to the four above and to any extra check.

## Step 9 — Stop point of the "stop before commit" route

If the route is `[kitchen: stop before commit]`: **STOP HERE, without committing.** Print
in the conversation:

- the `git diff` (or `--stat` if large);
- the gate results;
- **what specifically to look at** (what is visual and may be wrong without breaking a test);
- what was left out.

Set **your** manifest row to `⏳ waiting on human` and **stay idle in the conversation** —
the human will attach (`tmux attach -t '=kitchen-<ID>'`), review and approve or ask for
changes right there. Approved → Step 10. Changes requested → back to Step 7.
**When resuming (approved OR changes), rewrite `🔄 running` on your row before continuing**
— a `⏳` row with a working agent raises a false alarm in whoever is watching (CORE §7,
`⏳→🔄` transition). (Inline route: the human is already present; show the diff and talk.)

**General stop protocol in a tmux session** — applies to ANY real stop, not only this one:
a CORE §10 blocker, reclassification because of `tests.forbidden`, a plan gate without
`APPROVED` after 4 rounds. Always: `⏳ waiting on human` + a one-line reason on your
manifest row, then stay idle in the conversation. Stopping without writing `⏳` leaves the
row at `🔄` forever — the blocker stays invisible until someone attaches by chance.

Other routes: go straight on.

## Step 10 — Commit and record

1. **Commit** with conventional commits (CORE §5). The message describes what changed and
   why, not "implements <ID>".
2. The adapter's **`post_commit`** (e.g. regenerate a code graph), if any.
3. **`## Outcome` in the task doc** (CORE §6). The factual part is **derived from git**:
   - commits: `git log <base>..HEAD --oneline`
   - files: `git diff --stat <base>..HEAD`
   And written by you: **the decision and the why**, what was left out, and the scope-leak
   warning if Step 8.3 fired.
4. **`permanent/<area>.md`** — only if the decision constrains work **outside** this unit.
   One line + a link to the order. Cut: "will forgetting this break or re-litigate
   something in 3 months?"
5. **Links in the task doc**, if your notes tool uses links (CORE §6): the repo/integration
   touched and the permanent notes used or created.

Do not describe code structure in prose.

## Step 11 — PR

```
git push -u origin <branch>
<gh> pr create --base <base> --title "<conventional>" --body "<body>"
```

`<gh>` = the adapter's `gh` field if present; otherwise plain `gh` (CORE §1). In an
environment with a credential broken by an environment variable, plain `gh` returns HTTP 401
on every call and the PR never opens — the adapter knows the right prefix.

**PR title: must pass the repo's commitlint, when there is one.** Before opening, check
for config (`.commitlintrc*`, `commitlint.config.*`, or a `commitlint` block in
`package.json`) and **obey it**: restricted `type-enum`, required or forbidden scope,
imperative subject, length limit. A title that fails lint **blocks the merge** and burns a
round trip with the human just to rename. No config → conventional commits (CORE §5).

PR body: what changes and why, the final blast radius, and the gate results with real
numbers (Step 8). **A `## Not verified` section is mandatory**, listing what was left
unchecked ("not exercised on mobile"; "browser check not run — needs a seeded backend").
Nothing to declare → write `nothing`. **An unrun check is never presented as done**, and a
missing section counts as a false claim. Link the order.

`gh` unavailable → stop at the push, hand over the compare URL, and say the PR is pending.

## Step 12 — Close

1. Order status field = in review.
2. Update **your** manifest row if there is one (`✅ PR` + number) — never other units' rows
   (CORE §7, concurrent writes).
3. **Kitchen session — hibernate:** find your session id (the newest conversation file of
   this directory under Claude Code's projects folder — the file name without `.jsonl`),
   write it into the `session (resume)` column of your manifest row and into
   `.kitchen/done`. From then on your session may be killed at any time (dispatcher,
   `harvest` or the waiter) and revived with `claude --resume` (CORE §2). **Do not kill
   your own session** — the supervisor reaps.
4. **Final report** in ~6 lines: what was done, route, commits, gates, PR, what was left out.

## Step 13 — Do not clean up

`execute` does **not** merge, close the order, or remove the worktree. That is the human's,
after reviewing the PR. End with the reminder: `/harvest` after merging.

## Aborting

If the unit must die midway: CORE §11, step by step. Do not improvise, and do not leave an
orphan worktree.
