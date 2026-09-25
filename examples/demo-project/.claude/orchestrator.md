# Adapter — demo project

```yaml
project: tempconv-demo
base: main
worktrees: .worktrees
scarce_resource: "none — pure library, no server"
backlog:
  type: markdown
  folder: docs/tasks
  size_field: size
  status_field: status
  open_statuses: [backlog]
  never_take: [postponed]
layers:
  lib: tempconv/
  tests: tests/
tests:
  allowed: "python3 -m pytest -q"
  forbidden: "nothing"
  why_forbidden: "the demo has no shared resource"
forbidden_in_diff:
  - pattern: "print\\("
    why: "library code must not print"
gh: "gh"
max_parallel: 2
large_sizes: [L, XL]
vault:
  cards: docs/tasks
  plans: docs/plans
  permanent: docs/decisions
```
