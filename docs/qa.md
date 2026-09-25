# QA runs

`/qa` is a kitchen unit whose product is a **verdict with evidence**, not a PR. Its mission
is to make the target fail. The full procedure is in
[`skills/qa/SKILL.md`](../skills/qa/SKILL.md); this page is the map.

## Shape of a run

```
target (task, #PR, sentence)
  └─ Step 0  charter + depth from an observable predicate (smoke | standard | audit)
  └─ Step 1  qa_preflight.py        environment policy (production is never touched)
  └─ Step 2  recon → facts.tsv      facts with file:line, within a counted budget
  └─ Step 3  matrix → cases.tsv     technique per fact; 3-point BVA per limit
  └─ Step 4  qa_matrix.py           gate: no orphan fact, no impl-only oracle, ≥1 P0
  └─ Step 5  route                  API/unit → kitchen · browser → inline with the human
  └─ Step 6  run P0 first           qa_filter.py keeps output to failures + counts
  └─ Step 6b qa_mutation.py         does the suite that passed even fail on a mutant?
  └─ Step 7  findings               S1/S2 → /plan --problem immediately
  └─ Step 8  qa_report.py           report; invalid if a severe finding has no record
```

## The data contract

All scripts share these tab-separated files in `.qa/`:

| file | columns |
|---|---|
| `facts.tsv` | `id source fact limits` (limits separated by `;`) |
| `cases.tsv` | `id facts limit prio technique input oracle oracle_source route cut result sev record evidence` |
| `gaps.tsv` | `fact reason` |
| `budget.tsv` | managed by `qa_budget.py` |

Closed vocabularies: techniques `BVA partition decision state property guessing journey smoke
exploratory` · oracle sources `spec consumer invariant parity doc impl` · priorities `P0 P1
P2` · severities `S1–S4` · cut `exec below`.

## Budgets

Depth sets countable caps (files read, lines, queries, cases, probes, tool uses).
`qa_budget.py check` says `CONTINUE` or `STOP-AND-REPORT` at 80% of any cap; what does not
fit becomes "NOT covered", never extra reading. Depth is picked by a predicate (explicit flag,
task size, number of routes/files), not by judgement — measured on a real project, judgement
picked the expensive depth three times out of three.

## The QA adapter

`.claude/qa.md` declares the environments (local allowed or not, staging URL and rate
limits, production `read_zero`), the `forbidden_env` patterns the preflight greps for, the
probe rules and the risk profile. Example: [`examples/qa.md`](../examples/qa.md). Schema:
[`skills/qa/references/bootstrap.md`](../skills/qa/references/bootstrap.md).

## Scripts

| script | job | exit codes |
|---|---|---|
| `qa_preflight.py <repo>` / `--probe <file>` | environment policy; probe import check | 0 ok · 1 nothing local starts · 2 probe rejected · 3 no qa.md |
| `qa_matrix.py <dir> [--depth]` / `--skeleton` | matrix gate; BVA skeleton | 0 green · 1 red |
| `qa_budget.py <dir> add` / `check` | countable ledger | 0 continue · 1 stop |
| `qa_filter.py -- <cmd>` | failures + summary only | the command's |
| `qa_mutation.py <file> --cmd` | mutation testing with a coverage probe | 0 all killed · 1 survivors · 2 unsafe |
| `qa_report.py <dir> <depth>` | report skeleton + validity rules | 0 valid · 1 invalid |
| `qa_watcher.py <worktree> <slug>` | watches a dispatched run | 0 done · 2 crash · 3 timeout |

Every script has `--selftest`.
