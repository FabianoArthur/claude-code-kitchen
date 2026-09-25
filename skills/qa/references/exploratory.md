# exploratory.md — disciplined exploration (session-based, time-boxed, recorded)

Loaded when depth=audit OR the target is a loose sentence with no task doc — without
acceptance criteria to anchor the matrix, risk becomes the map. Exploration here is a
session with a charter, a time box and a record; "poking around until something turns up"
is QA theater and does not count as an executed case.

## Charter (before touching anything)

- Fixed format, 1 line, written in the run's `## Charter`:
  **"Explore <area> using <resources> to discover <risk class>"**.
  E.g. "Explore the order import using hostile payloads against staging to discover data
  corruption in time-zone conversion".
- Time box in **number of tool uses, not minutes** — the agent counts tool uses, not the
  clock. Default: **15 tool uses per charter, 2–3 charters max** (fits the ~120 audit cap
  together with the matrix; record each closed charter in the `qa_budget.py` ledger).
- Prioritise charters by the charter's guiding question: **"what makes this feature
  FAIL?"** — the charter most likely to answer it runs first. A charter that would only
  confirm the happy path is not a charter, it is cost.
- Without a task doc, the Step 2 "facts" are risk hypotheses: write them as such in
  `.qa/facts.tsv` (source `exploration`) — the charter exists to promote or bury them.

## Tours (pick 2–3 from the adapter's `risk_profile`; 1 charter per tour)

| tour | where it hits | what to look for |
|---|---|---|
| **money** | the path that creates/shows value: the main feature end to end with REAL staging data | wrong value at the end of the flow, lost state, duplicated side effect |
| **vandal** | hostile inputs at the entry points | unicode/emoji, maximum length, negatives/zero, double submit, missing field vs null |
| **borders** | where data changes owner/format: import/export, time zones, conversions, hand-offs between modules | loss/truncation in transit, swapped units, encoding, contracts diverging between sides |
| **history** | where there WAS a bug: `git log --grep="fix" --oneline -- <module>` | bug clusters = more bugs nearby; retest the fix's neighbourhood, not just the fix |
| **abandoned** | what nobody looks at: error states, empty states, every locale, permissions of rare roles | raw 500, hard-coded text, a screen broken by an empty list, a role without a guard |
| **time** | what expires, schedules or depends on the clock: session, cache staleness, cron, DST | stale served as fresh, off-by-one expiry, server time zone ≠ user's |

- The tour picks WHERE to look; the charter's risk class defines WHAT counts as failing. A
  tour without a declared risk class is a stroll, not exploration.
- A tour that needs a browser/dev server is the INLINE route (Step 5) — a kitchen session
  does not run it; if every charter is a browser one, the unit was routed wrong.
- Anti-bias guardrail: a quiet history is not health — if every risk tour points at the same
  module, spend 1 charter on the abandoned tour anyway.

## ReAct discipline

- Cycle: **hypothesis → ONE concrete probe → observe → adjust the hypothesis**. Each action
  is informed by the previous ones — never a fixed script, never N probes fired at once (the
  2nd blind probe wastes what the 1st taught).
- High uncertainty about where to attack → list 2–3 strategies, weigh cost × probability of
  finding a bug, **pick ONE** — do not run all of them.
- A probe has a named oracle BEFORE it runs (hard rule 6): "expected X because <source>". A
  probe without an expected value is poking around — the eye sees what it wants.
- **Stop on the detection curve**: a charter produced zero findings → **CHANGE tour**
  (rotation), do not insist on the same one with weaker probes. **2 dry tours in a row →
  exploration over** — record it and go back to the matrix (or close the run).
- A finding mid-charter: **1 row in `.qa/cases.tsv`** (`technique=exploratory`, result FAIL,
  minimal evidence) **and CONTINUE the charter**. Going deeper is a new case AFTER the time
  box, never a detour now — the detour burns the charter.
- Time box ran out with a hot hypothesis: record it in `.qa/gaps.tsv` (reason `time-box`) —
  it becomes the next run's charter, not a silent extension of this one.

## Record (exploration is auditable too)

- Each charter closes with a block in the run file:
  `charter: <line> | tour: <name> | tool uses: <n>/<box> | findings: <cases.tsv ids>
  | DID NOT look at: <1 honest line>`. Without the "did not look at", the report overstates
  coverage — exploration with no declared out-of-scope does not enter the verdict.
- An exploration finding follows **hard rule 1 of SKILL.md, no exception**: S1/S2 →
  `/plan --problem` RIGHT AWAY, with real evidence and `found_during: qa-<slug>`; S3/S4 stay
  in `cases.tsv` and show up in the report.
- In the report, exploration counts separately from the matrix: number of charters, tours
  run, tours NOT run (and why), findings per charter. Zero findings in 2–3 well-chosen
  charters is information (calibrated confidence), not failure — as long as the tours cover
  the `risk_profile` and the "did not look at" is declared.
- Teardown holds the same (hard rule 8): exploratory probes deleted, seeded data removed — a
  charter leaves no trace in the environment.
