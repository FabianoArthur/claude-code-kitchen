# api.md — running API/backend cases

Loaded when the run's route includes API/backend. It is the most dispatchable and cheapest
of the three E2E rungs: it runs in a worktree + tmux, with no human and no browser. Context
that IS LAW here: the repo's QA adapter (`.claude/qa.md`) defines `environments` (local may
be FORBIDDEN — e.g. a repo whose `.env` points at production), `probe.safe_env`,
`probe.import_rule_grep`, `filtered_output` and staging `rate_limits`. `qa_preflight.py`
already printed that policy in Step 1 — no decision in this file overrides it. Preflight
exit 1 = nothing local starts.

## Execution ladder (cheap → expensive; go down only as needed)

**1. The module's existing spec.** If the target already has a test covered by the
orchestrator adapter's `tests.allowed`, run it first — the cheapest case, scenario already
built. Output ALWAYS through `qa_filter.py -- <cmd>` or the QA adapter's `filtered_output`
command (failures + count, ≤10 lines). An existing spec that already covers a matrix case →
mark the case with that evidence, do not duplicate it in a probe. `tests.forbidden` stays
forbidden: it goes named under "NOT covered", never run in secret.

**2. Ephemeral probe.** A throwaway spec/script in `.qa/probes/`, written for ONE handful of
matrix cases. It imports ONLY the target module — never boot the whole app (in some apps,
importing the root module starts every cron job against a real database). Validate it
BEFORE running: `python3 <skills>/qa/scripts/qa_preflight.py <repo> --probe <file>` — it
applies the adapter's `probe.import_rule_grep`; rejected → fix the import, do not work
around it. Run it with the adapter's `probe.safe_env` (never the repo's `.env`). Deleted at
teardown, no exception (hard rule 8).

**3. Black-box HTTP against staging.** When the case needs the deployed system (real auth,
middleware, a live integration): `curl` with the token of the environment declared in the
adapter, **read-mostly** — GET freely within the rate limit; mutation only on a resource
seeded by the run itself and removed at teardown, never on third-party data. Respect the
adapter's `rate_limits`: a burst that trips an upstream limit is ENVIRONMENT, not a target
bug — back off and retry once; if it persists, record it as an environmental limitation,
not a finding. Production: `read_zero` holds even for GET.

Go down a rung only when the case cannot be answered on the current one, and say in the run
file why ("case 12 needs the auth middleware → rung 3").

## Probe protocol

### Scenario and data

- Minimal test data builders with sensible defaults; the case overrides only what matters.
- DIRTY data on purpose: unicode/emoji in an indexed field, maximum length, zero, negative,
  incoherent-but-real combinations (address in country A + payment in country B). Clean data
  validates the developer's mental model, not reality.
- Full independence: the probe builds and cleans its own world; it must pass twice in a row.
  Passes on the 1st and fails on the 2nd = leaking state — fix the probe before trusting it.
- Frozen clock (`vi.setSystemTime` / `freezegun`) when the branch depends on a date — with
  the date that exercises the branch, never the real `now()`.
- flush/commit/await save BEFORE any verification read — otherwise the SELECT validates an
  illusory state.
- Delete/update: insert → operate → **RE-READ from the database** → assert. Never assert on
  the in-memory object.

### Test double rules (deterministic decision)

- MOCK: slow dependencies (DB, network), external infra (HTTP, SMTP, filesystem), scenarios
  hard to force for real (exception, timeout, a specific date).
- NEVER mock: the dependency that IS the responsibility under test (a mocked repository =
  green with a broken query); domain entities/objects (instantiate them); a third-party lib
  directly (SDK, ORM, HTTP client) — if there is an abstraction of your own, mock that.
- Stubs for queries (vary the return: empty, 1, many, boundary); mock+verify for commands
  with an exact count — a duplicated call is a bug. Verify ONLY the relevant interactions.

### Fault injection

- An exception only on item 1 of a batch → was item 2 processed? Did the whole process
  abort? (continue-on-error is behaviour to prove, not to assume.)
- Every patch/monkeypatch restored in `finally` — a probe that leaks a double contaminates
  the next case.

## Mechanical checklist per endpoint (1 case per applicable item)

- Empty input / only spaces → a structured error with a code, NEVER 500.
- Numeric ≤0 or out of range → rejection or a documented, deterministic clamp.
- **Empty is not an error**: a search with no result → success + empty list; a real failure
  → a structured error code. Two different contracts — test BOTH.
- Timeout / dependency down → a VISIBLE failure (error, log, alert), never a silent fallback
  returning a "working" default (the worst failure mode: it looks healthy).
- Partial failure (1 of N dependencies broken) → the healthy results preserved.
- A stack trace in a response payload is ALWAYS a bug (S2+), even with the "right" status.
- Auth: no token → 401; invalid/expired token → 401; ANOTHER tenant's resource → 404/403
  without leaking existence or content — 200 with someone else's data is S1.
- Idempotency: the same POST twice (retry/double submit) → 1 side effect, not 2.
- Inverted time window (end < start) or a malformed date → a structured 4xx, never 500.

## Query/database checklist (when the target has a query/filter/aggregation)

- For EACH filter condition: 1 record that MUST appear + 1 excluded for violating ONLY that
  condition (catches a forgotten or inverted condition). Assert size AND identity.
- A state that returns zero rows — does the consumer cope?
- Identical rows/duplicates — do they show up duplicated?
- NULL in each column used in the predicate, one at a time.
- Numeric/date boundary of the filter: on point and off point.
- Group-by/aggregation with ≥2 groups (1 group hides a wrong group-by) and with equal vs.
  different values.
- After any mutation: re-read from the database before asserting (never trust the return of
  the operation).
- A test database with the SAME engine as production — in-memory gives false greens on
  queries.

## Evidence

- Each executed case gets in the `evidence` column of `.qa/cases.tsv`: the exact command +
  expected + obtained, in ≤3 lines. Without that, PASS/FAIL is not auditable.
- Output ALWAYS filtered (`qa_filter.py` or the adapter's `filtered_output`). NEVER dump an
  HTTP response or a raw log into the context — that violates the source ratchet.
- Big JSON → `jq` extracting ONLY the field that decides the case
  (e.g. `curl -s ... | jq '{status: .status, total: .items | length}'`).
- Failure → environmental vs. real triage BEFORE recording (reproduces in isolation?
  correlates with deploy/time/rate limit?); retry 1–2× ONLY for environmental.
