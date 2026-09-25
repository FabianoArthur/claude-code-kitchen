# CORE — the kitchen's rulebook, valid in any project

Read by `orchestrate`, `execute`, `dotask`, `harvest`, `plan` and `qa`. Nothing here is
project-specific: every binding (test command, backlog location, layers, hooks) comes from
the **adapter**.

Restaurant vocabulary, used throughout the docs:

| term | meaning |
|---|---|
| **waiter** | the main Claude Code session. Takes orders, dispatches them, serves results. **Never cooks** (never edits code itself). |
| **kitchen** | one detached tmux session per order (`kitchen-<ID>`), running an interactive Claude Code in its own git worktree, until the PR is open. |
| **order** | a task doc (a *unit* of work). |
| **ticket** | the **manifest**: the durable record of what is in flight. |
| **serve** | report back when a dish is ready (PR open), paused (needs a human) or dropped (aborted). |
| **harvest** | clean up worktrees whose PR was actually merged. |

---

## 1. The adapter

Find it by walking **up** from `cwd` until `.claude/orchestrator.md` exists. If there is
none: **do not improvise** — go to §9 (bootstrap).

Fields:

| field | required | meaning |
|---|---|---|
| `base` | yes | base branch. **Always the base; the kitchen never writes to it directly.** |
| `worktrees` | yes | parent directory of the worktrees (keep it **inside** the repo, see below) |
| `scarce_resource` | yes | the physical/global resource that forces serial work (a dev-server port, a device, a shared DB, the human's eyes) |
| `backlog.type` | yes | `markdown` \| `github-issues` \| `clickup` \| `none` |
| `backlog.folder`, `.size_field`, `.status_field`, `.epic_field` | if `markdown` | where and how to read task docs |
| `backlog.open_statuses`, `.never_take` | no | which statuses count as open, and which look open but must never be picked (e.g. `postponed`) |
| `backlog.reader` | no | command that reads a card from an external tracker (see `docs/integrations.md`) |
| `layer_of_this_repo` | no | which layer of a mixed backlog this repo implements (eligibility filter 2) |
| `large_sizes` | no | sizes that trigger the plan review gate (§3b); default `[L, XL]` |
| `consumers` | no | repos (or paths) that consume this repo's public surface (§5 downstream check) |
| `layers` | yes | map `name: path` — the vocabulary of the **blast radius** |
| `tests.allowed` | yes | what a kitchen session MAY run |
| `tests.forbidden` + `.why_forbidden` | yes | what collides on the scarce resource |
| `forbidden_in_diff[]` | no | `{pattern, why}` — deterministic diff gate (§3a) |
| `gate_forbidden_in_diff` | no | command that implements §3a (default: `scripts/gate_diff.py`) |
| `gh` | no | how to invoke `gh` in this environment (default: `gh`) |
| `max_parallel` | no | cap on simultaneous kitchen sessions (absent = dispatch everything at once) |
| `prepare_worktree` | no | command run inside a freshly created worktree (deps); absent = nothing |
| `branch_regex` | no | branch-name validation (default in `execute` Step 2; never assume a tracker's id format) |
| `model_by_size` | no | map `size: model-alias` — becomes `--model` at dispatch; size absent from the map = account default |
| `post_commit` | no | hook after each commit (e.g. regenerate a code graph) |
| `status_push` | no | command that pushes status to an external tracker |
| `vault.*` | no | where to write task docs / permanent notes / plans (`vault.cards`, `vault.permanent`, `vault.plans`) |

A fully commented example lives in `examples/adapter.md`.

**About `gh`:** wherever a skill writes `gh …`, use the adapter's `gh` value if present.
It exists because an environment can have a `gh` credential broken in a way that only a
prefix fixes — e.g. an invalid `GH_TOKEN` environment variable, which `gh` treats as the
active account and uses **over** the keyring login, making every call return HTTP 401. In
that case the adapter carries `gh: "env -u GH_TOKEN gh"`. Never hard-code that fix in a
skill: it belongs to the environment, not to the rule.

**Hard rule:** if a decision depends on a field missing from the adapter, **ask the human
and write the answer into the adapter**. Never hard-code a project value in a skill.

### Eligibility of an order — four filters, in this order

An order is a candidate only if it passes all four. Failing any: **report with the reason
and drop it**; never force it through.

1. **Status** — is it in an open status? States like "postponed" look open and **are
   not**: postponing is the human's decision.
2. **Layer** — does it belong to this repo's layer? Product backlogs often mix layers
   (mobile, backend, hardware), and the repo at hand implements **one**. An order from
   another layer is dropped as impossible, not as low priority. No layer field → infer
   from the content and **say you inferred it**.
3. **Dependencies** — is every id in `depends_on` done? No → **blocked**. Report the chain
   (who is missing, in which layer, in which status) and drop it.
4. **Reality check — was it already done?** Order status is kept by hand and **drifts**.
   Before anything else, two 2-second checks:
   - `git log <base> --grep="<ID>"` — does the id already appear in a commit?
   - does the artifact named in the title / acceptance criteria already exist? (`class Foo`,
     a file, an endpoint — search the code, not the order)

   Any hit → **STOP and report "probably already done", with the evidence (commit sha,
   file:line).** Ask the human to confirm and fix the status. Never rebuild on top of it
   and never "update the status yourself" — it may be partial work, and only the human
   knows.

   > Not hypothetical. Measured on a real project: **8 of the 55 "to do" cards were
   > already cited in commits on the base branch** — and 7 of them were among the 15
   > cards executable in that layer. Without this filter, the first dispatch would have
   > rebuilt five classes that already existed.

Never estimate from a human-hours field of the order (`estimate`, `points`): different
scale from the agent wall-clock table. Estimate from the size field.

## 2. Routing — by scarce resource, not by "type"

| The unit needs… | Route | Where it works |
|---|---|---|
| the `scarce_resource` running to know it is right | **inline** (waiter + human, serial) | **main checkout** |
| human eyes on the result, but not the scarce resource | **kitchen, stops before commit** | worktree |
| nothing visual, nothing from the scarce resource | **kitchen, to the PR** | worktree |

An inline unit **gets no worktree**: it needs the main checkout's build cache (a new
worktree rebuilds from scratch). Only kitchen routes use worktrees.

**Two tempos:** dispatch the kitchen batch and work the inline queue with the human while
it cooks.

**No kitchen session ever runs `tests.forbidden`.** If a kitchen unit finds it needs that,
it **stops** and is reclassified as inline.

In genuine doubt between inline and kitchen-that-stops: choose **inline**.

### How a kitchen session is dispatched — attachable tmux session

"Kitchen" as a **route** means: **an interactive Claude Code running inside a detached tmux
session**, in the unit's worktree — not the in-session subagent tool. (Deliberate
exception: the plan-gate reviewer (§3b) and the pre-PR reviewer are in-session subagents —
they are consultations that return an answer, not units of work.)

Worktree and branch are created **before** dispatch, with the canonical command of
`execute` Step 2 (`git worktree add <worktrees>/<ID> -b <branch> <base>` +
`prepare_worktree` from the adapter). Then:

```bash
mkdir -p <worktree>/.kitchen
# write .kitchen/prompt.md: id, route, EXACT branch, adapter path, path of this CORE,
# ABSOLUTE path of the batch manifest, preliminary blast radius, and the instruction to
# follow `execute` through the kitchen entry point (its Step 1)
tmux has-session -t '=kitchen-<ID>' 2>/dev/null   # already exists? STOP and reconcile — do not kill
tmux new-session -d -s kitchen-<ID> -c <worktree> \
  'env -u CLAUDECODE -u GHOSTTY_RESOURCES_DIR -u GHOSTTY_BIN_DIR -u GHOSTTY_SHELL_FEATURES -u GHOST_COMPLETE_ACTIVE -u TERM_PROGRAM KITCHEN_SESSION=1 <claude> "$(cat .kitchen/prompt.md)" --dangerously-skip-permissions --strict-mcp-config'
```

- **`env -u … KITCHEN_SESSION=1` is mandatory.** A tmux pane inherits the tmux server's
  *global* environment, not your shell's. If your terminal exports integration variables
  (the list above is Ghostty's; adjust for yours), an interactive-shell hook can `exec` a
  PTY proxy and the kitchen's first shell command hangs forever while the screen says
  `esc to interrupt`. `KITCHEN_SESSION=1` also triggers `shell/zshrc-guard.zsh`, a second
  layer in case a variable comes back another way. Details: `docs/troubleshooting.md`.
- **Every `-t` uses exact match**, quotes mandatory (zsh expands `=word` without them).
  Without `=`, tmux matches by **prefix**: `kitchen-FE-2` sees and kills `kitchen-FE-21`.
  Form per command: `has-session`/`kill-session`/`attach` use `'=kitchen-<ID>'`; PANE
  commands (`capture-pane`, `send-keys`, `list-panes`) use **`'=kitchen-<ID>:'`** — with
  a trailing colon; without it capture returns empty, silently.
- **The prompt goes in a file** (`.kitchen/prompt.md`), never inline in the command —
  shell quoting breaks long prompts silently.
- **`<claude>` is the absolute path** of the binary (resolve with `command -v claude` at
  dispatch time): tmux's `sh -c` may not load your shell's PATH.
- **`--dangerously-skip-permissions` is deliberate:** a detached session has nobody to
  approve a permission prompt — any prompt would freeze the unit silently. Mitigations:
  isolated worktree, the rules of these skills (never push to the base or protected
  branches, never `--force`), branch protection on the remote, and ideally a sandbox
  (container/VM) around the whole thing. Read the security section of the README before
  using this.
- **`--strict-mcp-config` is the default — a kitchen session is born with NO MCP server.**
  Each MCP costs a process, context for tool definitions and boot time, **per session**,
  and a code unit uses none. Declared exception: a unit that provably needs one gets only
  that one via `--mcp-config '<json of that server>'`.
- **`--model` by size:** if the adapter has `model_by_size` and the unit's size is in the
  map (e.g. `XS/S: sonnet`), add `--model <alias>`. The resource saved is the account's
  rate limit, shared by N concurrent sessions. **Precedence:** a `model_exec` field in the
  task doc (written by `plan`) wins over the adapter's map.
- `.kitchen/` must not dirty the diff: check `$(git rev-parse --git-common-dir)/info/exclude`
  and add `.kitchen/` if missing (applies to every worktree of the repo at once).
- Follow/talk: `tmux attach -t '=kitchen-<ID>'` (detach without killing: `Ctrl-b d`);
  peek without attaching: `tmux capture-pane -p -t '=kitchen-<ID>:'`. The session stays
  alive after it finishes — review and adjustment requests happen **in the kitchen's own
  conversation**, not in the waiter. Consequence: a live session ≠ working; the fine
  state signal is the manifest row (§7), never `tmux ls`.
- **Two dialogs can hold the boot** (so the post-dispatch check is mandatory): (a) the
  Bypass Permissions acceptance — shown the first time `--dangerously-skip-permissions`
  runs on a machine; (b) the folder-trust dialog in a new worktree. Attach, accept, detach.
  A kitchen screen with none of that and no activity = investigate before watching.
- Lifetime: survives closing the terminal and `/clear` in the waiter; **dies on reboot**.
  That is why the manifest is mandatory (§7).

**Batch with a cap (`max_parallel` in the adapter):** do not fire everything — write a
`.kitchen/launch.sh` in each worktree with the canonical command above, plus the queue
`<worktrees>/.kitchen-queue.tsv` (`id<TAB>worktree`, dispatch order), and start only the
deterministic dispatcher (zero tokens, self-tested with `--selftest`):

```bash
tmux new-session -d -s kitchen-dispatcher \
  'python3 <skills>/orchestrate/scripts/dispatcher.py <worktrees>/.kitchen-queue.tsv --max <N>'
```

It keeps ≤N sessions alive, starts the next when a slot frees, reaps hibernated sessions
(below) and exits by itself when the queue is empty. A unit paused `⏳ waiting on human`
holds its slot **on purpose** — it is real RAM/CPU; reviewing frees it.

**Hibernation (RAM back):** Claude Code persists the conversation on disk and resumes it
with `claude --resume <session-id>`. A session that finished its work does not need to
live: when closing the unit (PR open), the agent writes its own session id to its manifest
row and to `.kitchen/done` (`execute` Step 12). **`.kitchen/done` present = the session may
be killed**, even before merge — the dispatcher, the waiter and `harvest` do that. To resume:

```bash
tmux new-session -d -s kitchen-<ID> -c <worktree> \
  'env -u CLAUDECODE -u GHOSTTY_RESOURCES_DIR -u GHOSTTY_BIN_DIR -u GHOSTTY_SHELL_FEATURES -u GHOST_COMPLETE_ACTIVE -u TERM_PROGRAM KITCHEN_SESSION=1 <claude> --resume <session-id> --dangerously-skip-permissions --strict-mcp-config'
```

## 3. The three gates

**(a) `forbidden_in_diff` — deterministic, before the commit.**

The mechanics matter: examine **only the added lines** of the staged diff
(`git diff --cached -U0` → lines starting with `+`, dropping the `+++` header), and
**ignore comment lines**. A pattern applied to the whole file fires on a comment that
documents the rule itself, or on pre-existing code the unit never touched — and a gate that
cries wolf is a gate people start ignoring.

Hit on an added code line → **the agent fixes it and reruns the gate**; it does not ask the
human. It is a rule, not an opinion. When writing a new pattern, prefer usage syntax
(`Foo(`, `Bar.of`) over a bare name (`Foo`).

`scripts/gate_diff.py <dir>` implements this. Point it at **the directory where the diff
is** (the worktree), not at the repo root — pointing at the root reads the wrong index and
answers "clean" without having looked at anything.

**(b) Plan review gate — large units only.**
If the unit's size is in the adapter's `large_sizes` (default `L`/`XL`), dispatch an **independent** subagent to
review the *plan* (not the code): it receives the plan + blast radius and answers
`APPROVED` or a list of objections. Iterate ≤4 rounds until `APPROVED`.

> **This gate does NOT pause for the human.** That is the whole point: a plan is approved
> by an independent reviewer, and the human comes in at the PR. Do not ask "can I go ahead
> with the plan?" — not even out of habit.

**(c) Reconciled blast radius.** §4.

## 4. Blast radius

Every plan declares, **per adapter layer**, the files it expects to touch:

```markdown
## Blast radius
- <layer>: <path>            [new]     (read only)
```

Mandatory **always, no size exception**. Opening an exception ("small order doesn't need
it") is how the kitchen rots: soon everything is small.

**How to build it:** a code-graph query if you have one (optional), **crossed with actually
reading the entry point**. Never from the order's text — an order describes the intent of
the day it was written, not what exists today.

**Validation:** every declared path must exist on disk or be marked `[new]`. An invented
path = gate failed, redo the list.

**Reconciliation, before commit** — compare against `git diff --name-only`:

| bucket | action |
|---|---|
| declared ∩ touched | ok |
| declared − touched | plan overestimated — harmless, no comment |
| **touched − declared** | if > ~30% of touched files → **explicit warning in `## Outcome`** |

## 5. Definition of done

Per type, and explicit, because implicit is negotiable.

**Logic / data / infra:**

- a new test that **fails before and passes after** (real TDD, not a test written at the end);
- `tests.allowed` green;
- `post_commit` run;
- `## Outcome` written.

**Visual / UI:**

- all of the above **minus TDD**, **plus**: exercised on the `scarce_resource` and **seen
  by the human**.

**Every unit, on top of its type:**

- changed a surface another repo consumes → **downstream-break warning** (below);
- **honest** gate report (below): green only for what actually ran.

### Surface consumed by another repo — finding the caller is DoD, not courtesy

Applies to every change someone outside sees: endpoint signature, request/response shape,
DTO/enum, validation rule, auth/permission code, route path, error shape. Before calling
the unit done:

1. **Look for the caller in the consuming repos** — the ones declared in the adapter; field
   missing → §1 hard rule. Search by the **name** of the route/DTO/type/field/enum on both
   sides, not only the obvious call site. The consumer is not always another repo: it can
   be the other half of the same one (`backend/` + `frontend/`).
2. **Nothing breaks** → one line recording the check, and move on.
3. **Something breaks** → **WARN**: which repo, which `file:line`, what breaks, how to fix.
   Mandatory, not optional — including when the change is ready to ship, which is exactly
   when it is tempting to omit.

**Do not fix the consumer in this unit.** Scope follows the order unless the human says
otherwise; the downstream break becomes another unit — detour rule: record it with
`plan --problem` and move on.

> Not hypothetical. Measured on a real project: the backend started returning an envelope
> `{points, coverage, ...}` and the frontend kept reading an array — a page fell into the
> error boundary in staging. **No unit test in either repo caught it**: each side was green
> against its own fixture. The order even predicted the break in prose; prose is not a gate.

### Honest gates — evidence before claims

One line per check you **actually ran**, each with the real result (the number, the
output, the outcome) — never "should pass".

- A gate you did **not** run is `⚠️`/`❌` with a one-word reason. Never a `✅` you cannot
  back with command output.
- Close by declaring **what was not verified** ("browser check not run — needs a seeded
  backend"). An unrun check that looks run is worse than no gate: the human stops checking
  the rest.

### TDD on UI is theater — explicit position

A widget test asserts a widget exists, not that the layout is right. Visual rules pass
green and arrive wrong on screen. So: **TDD mandatory on logic; on UI the gate is the
scarce resource + human eyes.** Never claim TDD covers UI.

### Commits

Conventional commits: `type(scope): description`, types
`feat|fix|test|perf|refactor|chore|docs|style|build|ci`. A rule, not a suggestion.

## 6. Recording — three writes, three lifetimes

| Where | What | Lives |
|---|---|---|
| **in the task doc**, section `## Outcome` | commits and files (**derived from git**), the decision and the **why**, what was left out, scope-leak warning (§4) | forever, next to the requirement |
| **`<vault.permanent>/<area>.md`** | only a decision that constrains future work **outside** this unit — 1 line + a link to the order | forever |
| **manifest** | orchestration state | dies with the batch |

**The factual part of `## Outcome` comes from git, not from memory:** commits from
`git log <base>..HEAD --oneline`, files from `git diff --stat <base>..HEAD`. You write
**only** the why and what was left out. An agent that writes the whole section records what
it meant to do, not what it did.

**Do not duplicate code structure in prose** — that is a code graph's job, if you use one.

**Cut for `permanent/`:** "if this is forgotten, will someone break or re-litigate it in 3
months?" If not, it stays in the task doc.

**Links are part of the write.** If your notes live in a linked-notes tool (Obsidian or
similar), every write ends with links: the task doc links the entity it touched (repo,
integration) and the permanent notes it used; a permanent note links back to its origin
order. A note with no outgoing link is an incomplete record.

## 7. Manifest

`<vault.plans>/YYYY-MM-DD-<slug>-manifest.md`. It is the durable record of the batch.
Kitchen tmux sessions survive `/clear` and a closed terminal, but die on reboot — and even
alive, without a manifest nobody knows what was in flight, nor on which route.

```yaml
---
type: manifest
project: <name>
base: <base> @ <sha>
created: YYYY-MM-DD
dispatched: YYYY-MM-DD HH:MM
---
| unit | size | route | state | branch/worktree | PR | session (resume) |
|------|------|-------|-------|-----------------|----|------------------|
```

States: `⏸ queued` · `🔄 running` · `⏳ waiting on human` · `✅ PR` · `🚫 aborted`

Transitions: the agent writes `🔄→⏳/✅/🚫`; **`⏳→🔄` is the resume**, and whoever unblocked
it writes it — the agent when it goes back to work, or the waiter/supervisor that resolved
the pause. A `⏳` row with an agent already working raises a false alarm in any watcher.

Rewrite **at every state change**, not at the end. `⏳` always with the reason in one line
in the cell itself — an eternal `🔄` row with a stopped agent is this system's invisible
failure mode.

**Concurrent writes:** each kitchen session updates **only its own row** (the one holding
its id); the waiter writes the others. Occasional conflicts are resolved at reconciliation.

**When resuming, reconcile against reality** — worktree exists? branch exists? PR merged?
base moved? session alive (`tmux has-session -t '=kitchen-<ID>'`)? The file is a record,
not the truth. Reading the session:

- alive → agent working, paused, or with an open conversation — the manifest row says which;
- dead **with** `.kitchen/done` → hibernated, normal; `claude --resume <session-id>` if needed;
- dead **without** `.kitchen/done` and state `🔄` → probable crash/reboot: inspect
  `git -C <worktree> status` + `log`, rewrite `.kitchen/prompt.md` describing what you found
  ("there are commits X, uncommitted diff in Y — resume from Step N of `execute`") and
  recreate the session. **Never** re-dispatch the original prompt on top of partial work.

**`harvest` boundary:** a worktree with no manifest entry is **never touched**.

## 8. Sequencing — the minimum per decision

- **bundle** — orders from the same epic that form one deliverable: one worktree, one
  branch, one PR. Carrier = the first id listed.
- **stack** — just a note in the manifest ("do after X"). No branch-off-branch, no
  retargeted PR.
- **file collision** — intersection of the declared blast radii. Two units declaring the
  same file **do not go in the same batch**.

## 9. Bootstrapping a project with no adapter

1. Detect: package manager, test command, folder structure (**reading the disk**, not the
   README), default branch — and, better, **the base merged PRs actually target**
   (`gh pr list --state merged --json baseRefName`). A repo's declared default branch can be
   stale; reading it once sent a fix to a branch nobody deploys.
2. Find the `scarce_resource` — what prevents two units from running together? (a device, a
   port, a shared DB, a license, a GPU). If there is none, say so.
3. Propose the full adapter and **STOP — the human confirms or edits.**
4. Write it to `<project>/.claude/orchestrator.md` and continue.

## 10. When to really stop

Only these count as a real need for new information. For everything else: keep going.

- the order is ambiguous/contradictory in a way **reading the code does not resolve**;
- a destructive or hard-to-reverse action outside the command's scope;
- a test red for a real reason (a bug), not a dirty environment;
- a missing credential/permission (`gh` not authenticated, remote unreachable);
- the `scarce_resource` is needed and the unit is in the kitchen (→ reclassify).

**Does not count:** a preference doubt, a finished plan waiting for a nod, thinking the
human would like to know.

## 11. Aborting a unit

Worktrees and branches are cheap to throw away. Two roles, and the split matters — **the
kitchen session cannot clean up after itself** (killing its own session interrupts claude
mid-flight; `git worktree remove` fails on its own cwd).

**The kitchen session does only:**

1. Writes on its own manifest row: `🚫 aborted` + the reason in one line.
2. Reverts the order's status to its original value.
3. If something learned deserves to last, writes it to `permanent/` **before** stopping.
4. Stays idle in the conversation — the session remains attachable for a post-mortem.

**The waiter (or the human) cleans up, in order:**

1. `tmux kill-session -t '=kitchen-<ID>'` if the session exists — **before** the remove,
   always. Git **does not refuse** to remove a clean worktree with a live process inside;
   without the kill an agent keeps running in a deleted directory.
2. `git worktree remove <dir>` (never `rm -rf` — it leaves the worktree registered). A dirty
   worktree from a mid-flight abort: `--force` is acceptable **here, and only here** —
   nothing was merged and the decision to abort was already made.
3. `git branch -D <branch>` (`-D` is correct here: nothing was merged).

## 12. How to talk to the human

A work partner, not a customer. Do not praise the question, do not agree to agree. If they
are wrong, push back and point **where**, with evidence (file:line, command output).
Half-true: say which half does not hold. Right but incomplete: complete it.
