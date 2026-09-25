# Mutation — judging the SUITE, not just the target

Loaded when the run has a mutation gate (audit; or standard with a critical-logic target).
It answers the question coverage does not: **would the green suite catch the bug if it
existed?** Coverage measures execution; mutation measures assertion strength.

Engine: `scripts/qa_mutation.py` (stdlib, zero install). It applies 1 mutant at a time,
runs the adapter's SCOPED command, and restores the file byte-for-byte with a hash check in
`finally`.

## When to run it (the gate is expensive — only where it pays)

| situation | run? |
|---|---|
| the target is business/calculation/filter logic with a green suite you distrust | **yes** — the canonical case |
| the target's suite never failed / tests written after the code (not TDD) | **yes** — pseudo-test is the hypothesis |
| an S1/S2 bug found in an area → "which others would the suite also let through?" | **yes** — bugs cluster |
| a P0 executed PASS and you must decide whether that PASS is worth anything | **yes, on the P0's file** |
| the target is UI/layout, wiring, a logic-free DTO, config | no — mutants there are noise |
| the adapter has `regression_suite_allowed: false` and there is no scoped spec for the target | no — no scoped command, no run (never the whole suite) |

## Procedure (5 steps, ~6–10 tool uses)

1. **Pick the target by risk**, not convenience: the file implementing the highest-priority
   fact of the matrix (the adapter's `risk_profile` orders them). One file per run in
   `standard`; up to three in `audit`.
2. **Find the scoped command** that exercises that file — the module's spec, from the
   orchestrator adapter's `tests.allowed` (e.g. `npx jest --runInBand <spec>`,
   `pytest tests/<file>`). No scoped spec: **do not run** — record the gap "target without
   its own suite" (already a coverage finding).
3. **Check the floor**: the command must pass GREEN on the original code. Red before
   mutating = a dirty environment or a bug already present; fix/report first.
4. **Run it** (file clean in git; ALWAYS in a worktree):

   ```
   python3 <skills>/qa/scripts/qa_mutation.py <file> \
     --cmd "<scoped command>" --max 12 --timeout 120
   ```

   `--list` first shows the mutants without running anything (cheap; helps choose).
5. **Triage every survivor** (mandatory — a survivor is not an automatic bug).

## Triage — 5 outcomes for each ALIVE mutant

The script already separates the first from the others: each survivor comes out labelled
**NOT COVERED** or **COVERED**, because it runs a second probe that replaces the line with a
crash. If the suite stays green with the crash planted, nobody passes there.

| diagnosis | how to recognise it | action |
|---|---|---|
| **not covered** (NoCoverage) | labelled `NOT COVERED`: no test executes the line, or none enters that branch | a missing **CASE**, not an assertion — write a test that REACHES the code; strengthening an assertion of a test that never passes there is useless |
| **equivalent** | the mutation does not change observable behaviour (unreachable limit, redundant guard, dead flag) | discard, 1 line of justification in the report |
| **weak assertion** | labelled `COVERED`: the test runs the line but only asserts status/size/"didn't blow up" | finding **S3 "weak suite"** + a new case with the missing assertion |
| **missing partition** | labelled `COVERED`, but no test reaches the POINT the mutation changes (the classic: `>` → `>=` survives because nobody tests the exact limit) | **a new BVA case** (techniques.md §2) |
| **real bug** | the mutation reveals that the correct behaviour is not even what is tested (the original code is the wrong one) | a normal finding (S1/S2 by severity) → `/plan --problem` |

`NOT COVERED` and `weak assertion` look like the same defect in the score and have opposite
fixes — that is why the probe exists. Strengthening the assertion of a test that never runs
the line is wasted work.

## The missing assertion, by mutation type

Survived and is `COVERED`? The mutation type says what the test should be asserting:

| the mutation that survived | the test is not asserting… |
|---|---|
| `>` ↔ `>=`, `<` ↔ `<=` | the behaviour **at the exact point** of the limit (3-point BVA) |
| `==` ↔ `!=` | one side of the equality — the case that tells equal from different is missing |
| `&&` ↔ `\|\|` | the combination where the two conditions diverge (only "both true" is covered) |
| `true` ↔ `false`, a removed negation | the opposite branch of the decision |
| `+` ↔ `-`, `*` ↔ `/` | the **value** of the result — the test probably only checks type, size or "didn't throw" |
| `i++` ↔ `i--`, index off-by-one | the first/last element, or the exact cardinality of the output |
| a removed call (side effect) | that the effect **happened** (record written, event published, mock called N times) |
| a return swapped for `null`/`[]`/`{}` | the **content** of the return, not just that it exists |
| an inverted guard condition | the case the guard protects (invalid input must be rejected) |

## Prove the new case kills the mutant (mandatory)

Writing the case and seeing it green does **not** close the gap: the case may pass without
exercising what the mutant changes. Close the loop with the same engine, mutating only that
line:

```
python3 <skills>/qa/scripts/qa_mutation.py <file> \
  --only-line <L> --cmd "<command of the new case>"
```

Expected: the mutant that used to survive now **dies**. Still ALIVE → the new case does not
catch the regression; rewrite it before marking the gap as closed. It is the same principle
as "see the test fail", applied to fixing the suite — without this proof, a badly chosen
case enters the matrix, stays green, and the gap stays open while looking closed.

Rules: the raw score (`X killed / Y alive`) **is not a quality metric** and does not go in
the verdict — what goes is what triage produced (new cases and findings). A timeout counts
as suspect-killed: investigate only if it is a P0's mutant (a mutation that causes an
infinite loop is a robustness finding).

## What to record

- Each survivor triaged as weak-assertion/missing-partition becomes a **new row in
  `cases.tsv`** (`technique=BVA|partition`, `oracle_source` = the independent oracle the
  assertion should have used) — and, if the budget allows, it runs in the same run.
- Under `## NOT covered`: "mutation run on `<file>` (N mutants): M survivors, triaged as
  <equivalent/gaps>" — and the logic files that were **not** mutated.
- A "weak suite" finding belongs to the repo, not the target: the `/plan --problem` doc
  points at the weak spec (file:line) and suggests the missing assertion — a regression of
  the PATTERN, not of the case.

## Real evidence (measured on a real project)

Target: a validation module checking that a loaded quantity does not exceed a container's
capacity, with a scoped pytest file (9 green tests): **7 mutants killed, 1 ALIVE** —
`quantity > capacity` survived the `>` → `>=` mutation. Triage: **missing partition**. The
spec tested 90% of capacity (below) and 200% (above) and **never the exact point** —
swapping `>` for `>=` by mistake would go unnoticed. Not a product bug (filling exactly to
capacity should be allowed); it is the "at the point" BVA case missing from the suite. This
is the picture of what mutation finds and coverage does not: the line was 100% covered.

## Selftest (proof the engine works)

`python3 scripts/qa_mutation.py --selftest` builds a target with `>` and `>= and <=`, runs it
with a STRONG suite (kills everything, exit 0) and a WEAK happy-path one (survivors, exit
1), and checks the file restore. It is the living demonstration of the principle: the weak
suite's survivors are exactly the limits it does not test.
