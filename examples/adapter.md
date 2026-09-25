# Adapter — example (`<your-repo>/.claude/orchestrator.md`)

Copy this file to `.claude/orchestrator.md` at the root of the repo you want to
orchestrate, then edit every value. The skills never hard-code a project value: whatever
they need comes from here. If a skill needs a field that is missing, it asks you and writes
the answer back into this file.

The scripts read the yaml block below with a small stdlib parser (no PyYAML), so keep these
two rules: **top-level keys start at column 0**, and **quote values that contain `#` or
`:`**.

```yaml
# ── required ──────────────────────────────────────────────────────────────
project: my-app

# The branch PRs target. Read it off merged PRs, not off the repo's default branch:
#   gh pr list --state merged --limit 20 --json baseRefName --jq '.[].baseRefName' | sort | uniq -c
# The kitchen never pushes to it directly.
base: main

# Parent directory of the kitchen worktrees. Keep it INSIDE the repo (and in .gitignore or
# .git/info/exclude): skills find this adapter by walking up from the worktree.
worktrees: .worktrees

# What stops two units from running at the same time. Anything that needs it goes to the
# inline queue (you + the waiter), one at a time.
scarce_resource: "the dev server on port 5173, and my eyes"

backlog:
  type: markdown            # markdown | github-issues | clickup | none
  folder: docs/tasks        # where task docs live (markdown backlog)
  size_field: size          # front-matter key holding XS|S|M|L|XL
  status_field: status
  epic_field: epic
  open_statuses: [backlog, todo]
  never_take: [postponed, blocked]   # look open, are not: postponing is a human decision

# Blast-radius vocabulary: every plan lists the files it will touch per layer.
layers:
  api: src/api/
  web: src/web/
  db: migrations/

tests:
  allowed: "npm test -- --run"                 # what a kitchen session MAY run
  forbidden: "npm run e2e"                     # what collides on the scarce resource
  why_forbidden: "e2e boots the dev server on 5173"

# ── optional ──────────────────────────────────────────────────────────────

# Deterministic diff gate (CORE §3a): checked against ADDED, non-comment lines only.
forbidden_in_diff:
  - pattern: "console\\.log\\("
    why: "debug output must not ship"
  - pattern: "localhost:\\d+"
    why: >
      hard-coded dev URL; use the configured base URL

# How to call gh here. Example: an invalid GH_TOKEN in the environment shadows your keyring
# login and every call returns HTTP 401 — this prefix fixes it.
gh: "env -u GH_TOKEN gh"

max_parallel: 3                               # cap on simultaneous kitchen sessions
prepare_worktree: "npm ci --prefer-offline"   # run inside each new worktree
branch_regex: "^(feat|fix|perf|refactor|chore|docs)/[a-z0-9][a-z0-9._/-]*$"

model_by_size:                                # becomes --model at dispatch
  XS: sonnet
  S: sonnet
large_sizes: [L, XL]                          # sizes that get the independent plan review

post_commit: ""                               # e.g. a code-graph refresh; empty = nothing
status_push: ""                               # e.g. a tracker sync script; empty = nothing
consumers: ["../my-app-mobile"]               # who consumes this repo's API (downstream check)

vault:
  cards: docs/tasks                           # task docs
  plans: docs/plans                           # plans + manifests
  permanent: docs/decisions                   # durable decisions
```
