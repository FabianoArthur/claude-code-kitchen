# The adapter

Every repo you orchestrate gets one file: `.claude/orchestrator.md`. Skills find it by
walking **up** from the current directory, which is why worktrees must live inside the repo
(`worktrees: .worktrees`) — from a worktree outside the repo, nothing would find the adapter
and the diff gate would say "clean" without looking.

A complete, commented example: [`examples/adapter.md`](../examples/adapter.md).
The QA adapter (`.claude/qa.md`): [`examples/qa.md`](../examples/qa.md).

## Fields

| field | required | notes |
|---|---|---|
| `base` | yes | the branch PRs target. **Measure it from merged PRs**, not from the repo's default branch — see below. |
| `worktrees` | yes | parent dir of kitchen worktrees, inside the repo. |
| `scarce_resource` | yes | what forces serial work. "none" is a valid answer. |
| `backlog.type` | yes | `markdown` (default) · `github-issues` · `clickup` · `none` — see [integrations.md](integrations.md). |
| `backlog.folder`, `size_field`, `status_field`, `epic_field` | markdown | where task docs live and which front-matter keys to read. |
| `backlog.open_statuses`, `never_take` | no | statuses that count as open; statuses that look open but are not (postponed). |
| `backlog.reader` | no | a command that reads a card from an external tracker. |
| `layers` | yes | `name: path` map; the blast-radius vocabulary. |
| `tests.allowed` | yes | what a kitchen may run (unit tests, lint). |
| `tests.forbidden`, `why_forbidden` | yes | what collides on the scarce resource (e2e, dev server). |
| `forbidden_in_diff` | no | list of `{pattern, why}` checked on added lines only. |
| `gate_forbidden_in_diff` | no | a custom gate command; default `skills/orchestrate/scripts/gate_diff.py`. |
| `gh` | no | how to call the GitHub CLI here (default `gh`). |
| `max_parallel` | no | cap on simultaneous kitchens; enables the dispatcher. |
| `prepare_worktree` | no | run in each new worktree (e.g. `npm ci`). Do not invent one. |
| `branch_regex` | no | branch-name validation. |
| `model_by_size` | no | `size: model` map → `--model` at dispatch. The task doc's `model_exec` wins. |
| `large_sizes` | no | sizes that get the independent plan review (default `[L, XL]`). |
| `layer_of_this_repo` | no | for mixed backlogs: which layer this repo implements. |
| `consumers` | no | repos that consume this repo's public surface (downstream-break check). |
| `post_commit` | no | hook after each commit (e.g. refresh a code graph). |
| `status_push` | no | pushes status to a tracker, once per epic at the end of a batch. |
| `vault.cards`, `vault.plans`, `vault.permanent` | no | where task docs, plans/manifests and durable decisions live. |

## Parsing rules

The scripts use a tiny stdlib parser (no PyYAML dependency). Keep:

- top-level keys at column 0 (nested keys are ignored when a script looks for a top-level
  one — `backlog: { base: … }` never shadows `base:`);
- values with `#` or `:` quoted;
- `forbidden_in_diff` items as `- pattern: "…"` followed by `why:` (inline or folded `>`).
  Regex escapes follow YAML double-quote rules: write `"console\\.log\\("`.

## Measure the base branch, do not trust config

A repo's declared default branch can be stale. Before writing `base:`, look at where merged
PRs actually went:

```bash
gh pr list --state merged --limit 20 --json baseRefName --jq '.[].baseRefName' | sort | uniq -c
```

Measured on a real project: an adapter written from the default branch sent a confirmed fix
to a branch nobody deploys, and the fix never reached the screen.

## Bootstrapping

No adapter yet? Any skill will run the CORE §9 bootstrap: it reads the disk (package manager,
test command, folders, merged-PR bases), asks what the scarce resource is, proposes the whole
adapter, and **stops for you to confirm** before writing it.

## Keeping it out of (or in) git

The adapter is project configuration; committing it lets the whole team share it. If your
repo ignores `.claude/`, un-ignore just the adapters:

```gitignore
.claude/*
!.claude/orchestrator.md
!.claude/qa.md
```

(`.claude/*`, not `.claude/` — otherwise git never descends into the directory and the
negation is never evaluated. Check with `git check-ignore -v .claude/orchestrator.md`.)
