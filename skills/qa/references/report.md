# report.md — Step 8: what the model writes in the report and how to close the run

`qa_report.py` builds counters, findings, coverage and facts→cases mechanically from the
TSVs and validates the anti-theater rules (FAIL S1/S2 without `record` = invalid report).
You write ONLY the 3 MODEL holes: verdict, requirement questions, environment/policy — plus
the human line of each finding and the dossier in `/plan --problem`.

## TSV schema (the data contract — exact, tab-separated columns)

- `facts.tsv`: `id  source  fact  limits` — `limits` with tokens separated by `;`.
- `cases.tsv`: `id  facts  limit  prio  technique  input  oracle  oracle_source  route  cut  result  sev  record  evidence`
  — `result` ∈ PASS|FAIL|SKIP|`-` (not run); `sev` ∈ S1–S4; `record` = the
  `/plan --problem` slug; `facts` accepts several ids separated by commas.
- `gaps.tsv`: `fact  reason` — every fact without a case needs a row here.
- `budget.tsv`: managed by `qa_budget.py` — never edit it by hand.

## Verdict (1 line, tied)

- Answers the **charter's guiding question** against the task's **acceptance criteria**.
  Format: `<VERDICT>: <why in half a line, citing the decisive cases>` — e.g.
  `FAILED: C4 (S1) loses the order when checking out a cart with 0 items; C1–C3 P0 PASS.`
- Mechanical rules (the script reminds you, you decide): open S1 → **FAILED** · open S2 →
  at most **PASSED-WITH-RESERVATIONS** · **PASSED** requires 100% of the executed P0s PASS
  with an independent oracle (spec/doc/external calculation — `impl` alone does not count) ·
  **BLOCKED** when pre-flight/a dependency prevented the P0s — say WHICH.
- Never "N tests passed" as a verdict — a checkbox is not the goal (the canonical case:
  "✓ payment" with 347 tests and zero coverage of the one provider that matters). The
  verdict predicts post-deploy risk, with the NOT-covered next to it calibrating confidence.

## 1 line per finding (in the report) + dossier (in /plan --problem)

The report line — EXACT conditions, never "X does not work":
`fails FOR <who/which input> WHEN <precise condition>` — e.g. "applying a coupon fails FOR a
cart holding only gift cards WHEN the order is already paid (500, C7)". Severity by measured
impact, not by symptom category.

The dossier — goes in the doc created by `/plan --problem` (template Symptom/Origin/How to
reproduce/Expected vs. actual), not in the report:

- **Symptom** from the user's point of view, not the stack trace's.
- **Origin**: file:line + the suspect commit by time correlation — or an explicit "cause
  unknown". Never omit the field.
- **Repro** validated to reproduce 100% — if it does not always reproduce, the real
  condition (timing, concurrent state, shared resource) has not been found yet: say what is
  missing.
- **Impact**: % of flows/users affected, is there a workaround?
- **Suggest a regression test of the PATTERN**, not just of the case (failed with 0 items →
  an empty-collection regression on every save, not only on this endpoint).

## Requirement questions

A doubtful rule ≠ a bug. A divergence between behaviour and expectation that **reading code
does not resolve** becomes an objective question to the human — e.g. "is the 9 pm target in
the store's time zone or UTC? The code uses UTC (`schedule.service.ts:114`), the task says
'by 9 pm' with no time zone." — always with the evidence of both sides. Never assume a side
nor report it as a bug: reporting an assumption as a defect burns credibility and causes
ping-pong.

## Closing (fixed order)

1. `python3 <skills>/qa/scripts/qa_report.py <.qa-dir> <depth>` → paste the output into the
   run file's `## Report` and fill the 3 MODEL holes (verdict · questions · environment/policy
   with the pre-flight output + commands + teardown). Exit 1 = invalid report: fix the listed
   reasons before any other step.
2. 1 line in the task doc's `## Session log`: date + verdict + link to the run file.
3. FAIL screenshots next to the run file; full teardown (hard rule 8): probes deleted, seeded
   data removed, `.qa/` cleaned.
4. `permanent/` ONLY if the run revealed a constraint on future work. Cut: "will forgetting
   this break something in 3 months?" No → no note.
5. Dispatched run (tmux): write session id + `.kitchen/done` and stop; the WAITER kills the
   tmux session, removes worktree and branch — never the agent. `/harvest` does not sweep QA.
6. Re-run cost, 1 line at the end of the report: "if `<target/file>` changes, rerun cases
   `<ids>` (~`<cost in cases/tool uses>`)" — it is what makes the next run cheaper than this
   one.
