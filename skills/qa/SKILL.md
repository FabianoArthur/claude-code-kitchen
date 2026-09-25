---
name: qa
description: Use when the user asks to test, validate, QA, "break", check that something is solid, or hunt for bugs in a feature, task, PR, endpoint, screen or integration — given a task id, a slug, a PR number or just a sentence of context. Also to plan tests ("what would you test in X"), run an approved QA plan, or resume an interrupted QA run. NOT for writing tests for code you are implementing yourself (that is the TDD inside /execute) nor for fixing bugs.
---

# /qa — QA run: target → verdict with evidence

```
/qa <task-id|slug|#PR|sentence>        full run (intake → report)
/qa --plan <target>                    stop at the matrix gate; write an executable plan
/qa --run <run-file>                   resume an approved --plan, from Step 5 on
/qa --resume [slug]                    reconcile an interrupted run against reality and continue
/qa --depth smoke|standard|audit       (modifier; default: inferred and DECLARED)
/qa --inline                           force the inline route (human present)
```

**Mission: find errors, assuming they exist.** A successful test case is one that makes the
target FAIL. Testing "to confirm it works" selects weak inputs — invert that. Testing shows
the presence of bugs, never their absence: deliver calibrated confidence, with the
NOT-covered declared.

**Read `../orchestrate/CORE.md`** — §1 adapter, §2 routes, §7 manifest, §9 bootstrap. QA is a
kind of kitchen unit, not a parallel system.

## Hard rules (breaking any = invalid run)

1. **QA does not fix, does not commit target code, does not open a PR.** Bug found →
   `/plan --problem` RIGHT AWAY (dedup by searching the docs; real evidence;
   `found_during: qa-<slug>`) and move on to the next case. A report with S1/S2 and no
   record slug is invalid — a finding that only exists in the chat evaporates.
2. **Production is untouchable.** `environments.production: read_zero` in the QA adapter
   holds even for GET. `qa_preflight.py` exit 1 = nothing local starts; only
   `tests.allowed` and HTTP against staging.
3. **The orchestrator adapter's `tests.forbidden` stays forbidden.** A regression suite
   vetoed by the adapter stays NAMED under "NOT covered", never run in secret.
4. A dev server never starts without the human present (inline route).
5. Trackers: read-only; any write goes through a separate, human-requested sync.
6. Every case has a NAMED oracle before it runs; source `impl` never alone.
7. A fact with a numeric limit becomes a BVA case (3 points) or a declared gap — the gate
   checks it.
8. Always tear down: probes deleted, seeded data removed, `.qa/` cleaned at the end.

## Depth — budget contract (countable caps, ledger in `.qa/budget.tsv`)

| cap per run | smoke | standard (default) | audit (only on request) |
|---|---|---|---|
| code-graph queries | 2 | 3 | 5 |
| files read (lines) | 3 (≤200) | 6 (≤300) | 12 (≤500) |
| cases executed | 8 (P0 only) | 20 (P0+P1) | 40 (P0–P2 + properties) |
| probes | 2 | 4 | 8 |
| tool uses ~ | 25 | 60 | 120 |
| references loaded | 0 | 2–3 | up to 5 |
| files under mutation | 0 | 1 (if logic) | up to 3 |

**Depth comes from an OBSERVABLE predicate, not from an impression of the target.** Write
the literal line `depth: <X> because <predicate>` in the Charter, picking the predicate
from this closed list:

| predicate (checkable before reading code) | depth |
|---|---|
| explicit `--depth` flag from the human | what they asked |
| task doc with `size: L` or `XL` | audit |
| task doc with `size: M` | standard |
| target names ≥3 routes/screens, OR `<gh> pr diff --stat` shows ≥10 files | standard |
| **any other case** — including a single target, a loose sentence, an XS/S task, a small PR, a fix verification, a task without `size` | **smoke** |

There is no "the target looks rich" or "worth a proper look" predicate. A target that turns
out bigger DURING Step 2: finish in smoke and say in the report "`--depth standard` fits" —
upgrading midway costs double and delivers half a matrix. Also declare the cost in one line
("smoke: ~8 P0 cases, ~25 tool uses"). Never ask the human; declare and go.

> Measured on a real project, three runs: all three chose `standard` on their own (one of
> them for a route WITHOUT parameters) and cost 102k–133k tokens, against 81k for a
> baseline without the skill on the same task. `standard` costs ~2× `smoke`. The predicate
> exists because choosing by judgement failed three times out of three. Depth is the cost
> knob: `standard` exists for targets that deserve it; choosing it by habit burns the
> human's budget.

`python3 <this folder>/scripts/qa_budget.py <.qa-dir> check <depth>` at every phase: ≥80% of
any cap → cut there; the rest becomes "NOT covered", never extra reading. Overrunning
silently is a report defect.

## Source ratchet (FIXED order; going back is a named violation)

(a) the task doc — already paid → (b) a code-graph query, if you have one (≤ cap) → (c)
targeted reading ONLY at the file:line pointed to, within the cap, guided by the adapter's
`risk_profile`.
**NEVER-READ:** a whole feature directory, the test suite, `node_modules`, a whole
code-graph report, a log without grep, an HTTP response dump.

## Technique selector and scales

| the fact has… | technique | reference |
|---|---|---|
| a numeric/date/cardinality limit | BVA — 3 points per limit (the gate requires it) | techniques.md §2 |
| combined conditions (flags, permissions, discounts) | decision table | techniques.md §3 |
| input ranges/enums/formats | equivalence partitioning (1 case per class) | techniques.md §1 |
| states with transitions (order status, session) | state transition | techniques.md §4 |
| an invariant ("always sorted", "never negative") | property (audit) | techniques.md §5 |
| an assumption the implementer probably made | error guessing (catalogue) | techniques.md §6 |
| a green suite you suspect catches nothing | mutation (judges the SUITE) | mutation.md |

**Oracle taxonomy** (column `oracle_source`; the gate rejects `impl` alone — a circular
oracle: whoever wrote the bug computes the wrong expected value):
`spec` task/acceptance criteria · `consumer` whoever really calls it (the shape the client
expects IS a contract) · `invariant` a property that depends on nobody (sorted, never
negative, idempotent) · `parity` routes/screens/exports of the same data agree · `doc`
OpenAPI/versioned external reference · `impl`⚠ the code itself. Hard judgement, failure
triage, a target with embedded AI → `oracles.md`.

**Case PRIORITY (before running):** P0 = breaks the main flow/money/data; P1 = an important
function wrong; P2 = rare edge/cosmetic.
**Finding SEVERITY (after):** S1 = loses data, security, 500 on the main flow, touches
production · S2 = main function wrong with no workaround · S3 = wrong with a workaround ·
S4 = cosmetic.

## Flow — Steps 0–8

**Step 0 — Target, adapters, charter.** Resolve the target: task id | slug | `#PR`
(`<gh> pr view/diff --stat`) | sentence. Identify the target REPO(s) (front matter `repos:`,
or content) — the adapters' walk-up (`.claude/orchestrator.md` AND `.claude/qa.md`) happens
IN the target repo, not in cwd. No `qa.md` → bootstrap (references/bootstrap.md): propose it
and **STOP for the human to confirm** — the only human gate of the run. Create the run file
`<vault.plans>/YYYY-MM-DD-qa-<slug>.md`. **Canonical** front matter (`--resume` finds runs
by it — do not invent variations):

```yaml
---
type: qa-run
target: "<task-id|slug|#PR|sentence>"
slug: qa-<slug>
repos: <repo(s)>
depth: smoke|standard|audit
state: "<step where it stopped>"
created: YYYY-MM-DD
---
```

Then the `## Charter`: target, depth+predicate+caps, provisional route, target environment,
guiding question ("what makes this feature FAIL?"), out of scope. Create `.qa/` in the
workplace and make sure `.qa/` is in `$(git rev-parse --git-common-dir)/info/exclude`.

**Step 1 — Deterministic pre-flight.** `python3 <this folder>/scripts/qa_preflight.py
<target-repo>` — prints the environment policy the run obeys (it goes in the report).
Exit 1 → hard rule 2.

**Step 2 — Recon (ratchet).** Stop reading when you hit the files cap: what is missing
becomes a declared gap, **never extra reading "because the oracle needed it"** — if the
consumer did not fit in the cap, the case becomes a gap or drops in priority. Mandatory
output: `## Facts` in the run file + `.qa/facts.tsv` (`id	source	fact	limits`) — facts with
file:line, not prose. Fact = asserted behaviour, limit, contract, consumer, invariant.
Record the phase in the ledger (`qa_budget.py <dir> add recon --files N --lines N
--queries N`).

**Step 3 — Mechanical matrix.** Load the MINIMUM: `techniques.md` (standard/audit) +
`api.md` XOR `browser.md` depending on the route. `oracles.md` only if judgement is hard
(the taxonomy above is enough to fill the column); `exploratory.md` for audit or a loose
sentence with no task doc; `mutation.md` when there is a mutation gate. In `smoke`, none —
this file is enough. `qa_matrix.py --skeleton <.qa-dir>` prints the BVA rows for the
declared limits; apply the selector to EACH fact and fill `.qa/cases.tsv` (columns in the
header the skeleton prints). Draw the CUT LINE (`cut: exec|below`) against the budget
BEFORE running. Fact without a case → `.qa/gaps.tsv` with a reason.

**Token-saving order in Step 3:** prioritise the facts BEFORE writing, design cases up to
the depth's `cases` cap, and **summarise what would fall below the cut in ONE line of
`gaps.tsv`** — never write out in full a case that will not run. Measured: a run designed
31 full cases (cap 20), 15 of them never to run, and cost more tokens than the baseline
without the skill.

**Step 4 — Gate.** `python3 <this folder>/scripts/qa_matrix.py <.qa-dir> --depth <depth>` —
red → fix and redo without asking (≤2 iterations; on the 3rd, stop and report).
**`--plan` STOPS HERE**: write charter+facts+matrix+estimate to the run file and end by
saying how to run it (`/qa --run <file>`).

**Step 5 — Route and dispatch.** CORE §2: a case that needs a browser/dev server/human eyes
→ INLINE (browser automation usually exists only in the waiter); API/unit/probe → a worktree
plus a tmux session `kitchen-qa-<slug>` (the canonical `execute` Step 2 command; branch `qa/<slug>` only
to isolate — QA does not commit). **Manifest BEFORE dispatch** (CORE §7, route `qa`, final
state `✅ report <path>` instead of a PR). **Copy `.qa/` into the worktree** at dispatch and
consolidate the TSVs back at the end — the worktree cannot see the main checkout's untracked
directory, and without facts/cases the agent would redesign the matrix (double spend). A
target can split across both routes, in two tempos. Watch it with
`qa_watcher.py <worktree> <slug>`. Collision: QA of target X never in the same batch as a
dev unit touching X.

**Step 6 — P0-first execution.** P0 first; a P0 failed → stop and report (do not burn budget
on P2 over a broken foundation). An ephemeral probe = a throwaway test/script in the pattern
of api.md, run through `qa_filter.py -- <cmd>` (returns only failures+count, ≤10 lines).
Browser inline per browser.md (console+network are free oracles). Fill `result`
(PASS/FAIL/SKIP) and `evidence` in `.qa/cases.tsv` after each case. `qa_budget.py check`
at every block. Failure → environmental vs. real triage BEFORE reporting (reproduces in
isolation? correlates with deploy/time/rate limit?); retry 1–2× ONLY for environmental —
never retry-until-green on a deterministic failure.

**Step 6b — Mutation gate (always in audit; in standard when the target is logic).** A P0
that passed GREEN is only worth something if the suite covering it can fail. Run
`qa_mutation.py <P0 file> --cmd "<scoped spec from the adapter>"` and **triage each
survivor** (mutation.md): equivalent (discard), weak assertion or missing partition (a new
case in the matrix, typically BVA), real bug (a finding). The raw score does not enter the
verdict — what triage produced does. Without a scoped spec for the target, the gap "target
without its own suite" is already a finding; never run the whole suite where the adapter
forbids it.

**Step 7 — Findings.** The detour rule, no exceptions (hard rule 1). Severity by impact,
not by symptom category. Fill `sev` and `record` (problem slug) in `.qa/cases.tsv`.

**Step 8 — Report and close.** `python3 <this folder>/scripts/qa_report.py <.qa-dir>
<depth>` builds the `## Report` (counters, coverage, findings, facts→cases); you write ONLY:
the verdict (1 line tied to the acceptance criteria/charter), 1 line per finding, and the
"Requirement questions" (a doubtful rule ≠ a bug — e.g. "9 pm in whose time zone?").
Verdict rules: open S1 → FAILED; S2 → at most PASSED-WITH-RESERVATIONS; PASSED requires 100%
of P0 PASS with an independent oracle; BLOCKED = pre-flight/dependency prevented the P0s
(say which). Then: 1 line in the task doc's `## Session log`; FAIL screenshots next to the
run file; teardown (hard rule 8). Dispatched: write session id + `.kitchen/done` (CORE §2
hibernation); the waiter kills the tmux session, removes worktree and branch (CORE §11
roles). `permanent/` only if the run revealed a constraint on future work. **/harvest does
not sweep QA** — closing is done here.

## Integration with /dotask and /plan

- **QA task** (a doc with `type: qa`, created by /plan): `/dotask <slug>` routes here — the
  run is the task; the end is the report, not a PR.
- **`/dotask <slug> --qa`**: after the task's PR, /dotask invokes `/qa #<PR>` — depth smoke
  (standard if `size: L|XL`), anchor oracle = the doc's acceptance criteria, and the verdict
  becomes a `<gh> pr comment` (the only /qa write on a PR; failing informs the review, it
  closes nothing). The PR diff is the **first input of Step 2** (`<gh> pr diff --stat`
  already says where the risk lives — a change to existing code deserves double rigour).
- **A problem doc** (`origin: plan--problem`) is a natural target of
  `/qa --depth smoke <slug>` to verify the fix: the P0 case is the doc's repro, and the
  report closes the loop (suggesting a regression test of the PATTERN).

## Two entry points

- **Waiter:** Steps 0–8; dispatch and cleanup are yours.
- **Kitchen session (`kitchen-qa-<slug>`, prompt from `.kitchen/prompt.md`):** charter,
  matrix and manifest already exist — confirm branch/worktree, run Steps 6–8, write
  `.kitchen/done` and stay idle in the conversation. A real stop = `⏳ waiting on human` +
  reason on YOUR manifest row (`execute` Step 9 protocol). Zero MCP: browser cases are not
  yours — if the matrix only has browser cases, the unit was routed wrong; `⏳` and report.

## --resume

Reconcile against REALITY, never against memory: the run file (last step with a filled
section) × manifest × `tmux has-session -t '=kitchen-qa-<slug>'` × worktree × `.qa/`. Session
dead without `.kitchen/done` → inspect `.qa/cases.tsv` (a filled `result` = real progress)
and recreate the session describing the state found. Nothing to continue → a status report,
not a new run.

## Anti QA-theater (self-check before the report)

A green suite ≠ healthy; coverage detects holes, it never proves anything. Asserting only a
200 status, snapshotting current behaviour as the answer key, several values of the same
class, retry-until-green, mocking what IS the responsibility, data that is too clean — all of
these count as executed cases and find no bugs. In doubt about a case: "what bug does it
catch that the others do not?" No answer → cut it and spend the budget where it hurts.
