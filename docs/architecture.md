# Architecture

claude-code-kitchen has three layers. Keeping them separate is what lets one set of skills
serve any repo.

| layer | where | what lives there |
|---|---|---|
| **Rules** | `skills/orchestrate/CORE.md` | project-agnostic rules every skill reads: eligibility, routing, gates, blast radius, manifest, abort |
| **Skills** | `skills/*/SKILL.md` | the procedures: `orchestrate`, `execute`, `dotask`, `harvest`, `plan`, `qa` |
| **Adapter** | `<repo>/.claude/orchestrator.md` (+ `qa.md`) | every project value: base branch, tests, layers, caps, forbidden patterns, paths |

Rule of thumb: if a value would differ between two repos, it belongs in the adapter. A skill
that needs a missing field asks the human and writes the answer into the adapter — it never
guesses and never hard-codes.

## Roles

```mermaid
sequenceDiagram
    participant H as Human
    participant W as Waiter (main session)
    participant M as Manifest
    participant K as Kitchen (tmux kitchen-<id>)
    participant G as GitHub
    H->>W: /dotask add-kelvin
    W->>W: eligibility filters + doctor.py
    W->>M: row ⏸ queued
    W->>K: worktree + branch + .kitchen/prompt.md + tmux
    W->>M: row 🔄 running (dispatched: time)
    W-->>H: "cooking; you can keep talking to me"
    Note over W: watch.py in background (0 tokens)
    K->>K: plan → review → TDD → gates → commit
    K->>G: push + PR
    K->>M: row ✅ PR #n + session id
    K->>K: .kitchen/done (hibernate)
    W->>G: confirm PR (createdAt ≥ dispatched)
    W-->>H: "served: PR #n"
    H->>G: review + merge
    H->>W: /harvest
    W->>G: verify MERGED
    W->>K: kill session, remove worktree, delete branch
```

- **Waiter** — the main Claude Code session. Takes orders, dispatches, watches, serves. It
  never edits code: the moment it starts cooking, it stops being available to you.
- **Kitchen** — one interactive Claude Code per order, in a detached tmux session, in its
  own git worktree, with `--dangerously-skip-permissions` and no MCP servers. It works until
  the PR is open, then hibernates. You can `tmux attach` to it at any time.
- **Human** — decides what to cook, answers real blockers, reviews and merges. Never asked
  to approve a plan: an independent reviewer does that.

## Routing: by scarce resource, not by task type

The one question that decides where a unit runs is: *does it need the thing two units
cannot use at once?* That thing — the **scarce resource** — is declared in the adapter: a
dev-server port, a physical device, a shared database, or simply your eyes.

| the unit needs… | route | where |
|---|---|---|
| the scarce resource running, to know it is right | **inline** (waiter + human, one at a time) | main checkout |
| human eyes on the result, but not the scarce resource | **kitchen, stops before commit** | worktree |
| nothing visual, nothing scarce | **kitchen, to the PR** | worktree |

Inline units get no worktree: they need the main checkout's build cache. A kitchen unit that
discovers it needs the scarce resource stops (`⏳`) and is reclassified inline.

## Why these choices

- **tmux sessions, not in-session subagents.** A tmux session survives `/clear` and a closed
  terminal, can be attached to, and holds a conversation you can steer. In-session subagents
  are kept for short consultations (plan review, pre-PR review), where a returned answer is
  the point.
- **Worktrees, not branches in one checkout.** The human switches branches in the main
  checkout while kitchens run; each kitchen needs its own filesystem.
- **A Markdown manifest, not a database.** It is readable, diffable, survives everything
  except deleting it, and each kitchen writes only its own row.
- **Deterministic scripts for everything that waits or checks.** Polling with an agent burns
  tokens; a Python loop does not. Gates that an agent "promises" drift; gates that a script
  enforces do not.
- **No human pause for plan approval.** The plan is reviewed by an independent subagent;
  the human reviews the PR, where the actual change is.

## The detour rule

A bug found in the middle of a task that is outside its acceptance criteria is **recorded,
not fixed**: `/plan --problem` writes a problem doc (Symptom · Origin · How to reproduce ·
Expected vs. actual) with `found_during: <task>`, the PR lists it under "found along the
way", and the task carries on. The record costs minutes; the detour would cost the PR. The
only exception is a bug that blocks an acceptance criterion — that is a real stop (`⏳`).

## Lifecycle of an order

```
/plan ──► task doc ──► /dotask or /orchestrate ──► kitchen ──► PR ──► human merge ──► /harvest
            │                     │                   │
            │                     └─ manifest row ◄───┘ (🔄 → ✅ / ⏳ / 🚫)
            └─ /plan --problem (detours found along the way)
```

See also: [adapter.md](adapter.md) · [manifest.md](manifest.md) · [gates.md](gates.md) ·
[qa.md](qa.md) · [troubleshooting.md](troubleshooting.md).
