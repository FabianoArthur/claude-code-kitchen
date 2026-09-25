# Design techniques — tagged fact → matrix rows

Loaded in Step 3 (standard/audit). You have `.qa/facts.tsv` (F1..Fn with file:line and
`limits` tokens) and you are going to fill `.qa/cases.tsv`. Order of application on EACH
fact: decision (§3) if there are combined conditions → BVA (§2) WHENEVER there is a limit →
full partitioning (§1) → guessing (§6) closes it. Black box first (from the contract); the
code is a safety net — structural coverage is BLIND to missing code, and a bug is often the
`if` that does not exist. Final rule: **a fact without a case → a row in `gaps.tsv` with a
reason; `qa_matrix.py` checks it and does not negotiate.**

## §1 Equivalence partitioning

Trigger: the fact describes a range, format, enum or input acceptance condition.
Procedure (4 derivation rules):

- range (`1..999`) → 1 valid class + 2 invalid (below, above)
- cardinality (`1..N items`) → 1 valid + 2 invalid (zero, >N)
- an enum handled distinctly → 1 valid PER value + 1 invalid (value outside the enum)
- a must-be condition (`id is a ULID`) → 1 valid + 1 invalid
Generation rules: **1 case per class** (varying values within the same class costs without
detecting); a valid case covers as MANY valid classes as possible at once; an invalid case
covers **EXACTLY ONE** invalid class (error checks mask each other); prefer the simplest
input of the class. Split a class if its elements may be handled differently (e.g. an enum
`type` with its own branch per value).

```
C10	F3	-	P1	partition	vehicle=abc (wrong type)	400 without stack	spec,consumer	api	exec
C11	F3	-	P1	partition	vehicle missing	400	spec	api	exec
```

## §2 BVA — boundary values (highest payoff per case; the gate REQUIRES 3 points per limit)

Trigger: a token in the fact's `limits:` — every comparator, window, cap, size, cut-off
date. "Bugs love boundaries" (the classic `>` vs `>=`).
Mechanical procedure:

- relational comparator → 3 cases: below / **exactly at the point** / above (
  `qa_matrix.py --skeleton` already prints the 3 rows; fill input+oracle)
- equality (`==`) → 1 at the point + 2 off it (one on each side)
- cardinality → 0, 1, max, max+1 elements; a page exactly full and full+1
- **the OUTPUT has its own boundaries** (they do not match the input's): force the minimum
  and maximum output, and try to provoke output outside the promised range
- ordered sets → first and last element; loops → 0, 1, many iterations
- internal limits where behaviour changes (batch size, pagination, cache) — the miss measured on
  a real project: **reading "a report window >7d switches to daily buckets" and not testing 7d±ε**.

```
C20	F1	7d	P1	BVA	window 7d−1s	hourly buckets	doc	api	exec
C21	F1	7d	P1	BVA	window exactly 7d	hourly buckets	doc	api	exec
C22	F1	7d	P1	BVA	window 7d+1s	daily buckets	doc	api	exec
```

## §3 Decision table

Trigger: the fact combines conditions → effects (permissions×roles, flags, discounts,
status×transition). Procedure: list causes and effects (a database update IS an effect);
note constraints (exclusive, requires, masks); each column of the table = 1 case with the
expected effects **present AND absent** made explicit. Anti-explosion pruning: at an OR node
that must be true, turn on ONE input at a time. A complex boolean expression → MC/DC: N+1
cases (one independence pair per condition) instead of 2^N; a condition without a possible
pair = a badly designed expression (a design finding). Watch short-circuit (`&&`/`||`)
masking a condition never evaluated. By-product: building the table exposes spec ambiguity
BEFORE running — ambiguity becomes a "Requirement question".

```
C30	F5	-	P0	decision	isActive=F,isVirtual=F	ABSENT from current-state	spec,consumer	api	exec
C31	F5	-	P0	decision	isActive=T,isVirtual=T	ABSENT (virtual masks active)	spec	api	exec
```

## §4 State transition

Trigger: the fact describes a life cycle (order status, session, job, payment).
Procedure: draw states+events (a 5-line mermaid in the run file); cases = (a) every VALID
transition once; (b) the most dangerous INVALID transitions (event in the wrong state —
cancelling the completed one, paying the cancelled one); (c) is the state left behind still
consistent? (does the CANCELLED order disappear from the aggregations? — a real bug found
this way); (d) re-entry/duplicate event in the same state (idempotency).
Prioritise by money/data: a transition that writes is P0.

## §5 Properties (property-based) — audit, or when the fact IS an invariant

Trigger: "always sorted", "never negative", "the sum matches", "roundtrip preserves".
Procedure (hypothesis in pytest; fast-check in vitest/jest):

- ONE property per partition (including "invalid input → structured exception")
- the generator covers exactly the property's range including boundaries; hard data: build
  a valid one and INJECT the variation (1 probe value outside the others' range), never
  filter random values until they fit (a triangle from 3 random ints ≈ 0% valid)
- order insensitivity → shuffle; a known result → a sentinel outside the range
- mutable state → a sequence of actions with a global invariant checked after EACH action
- failed → record the counterexample+seed as a permanent example-based case in the evidence

## §6 Error guessing — catalogue (1 case per item applicable to the fact)

0 and output forced to 0 · empty collection/1 element · all equal · already sorted ·
duplicates · negative quantity · truncated/partial input · leading zeros · even/odd when the
algorithm differs · power-of-2 size ±1 (buffers, binary search) · **double submit/retry of
the same POST** (idempotency) · and the most profitable: *the assumptions the implementer
probably made about what the spec left out* (look for what the task does NOT say and the
code decided on its own — each silent decision is a case).

Mechanical checklists per input type (apply them when building `input`):

- **list**: null · empty · 1 · many · duplicates · ALL equal · reversed/shuffled order · N
  below the internal limit (top-3 with 2) · neutral values at the ends
- **string**: null · empty · length 1 · only spaces · inner spaces · unicode/emoji (above all
  in an indexed field) · maximum length · equal to the delimiter
- **numeric**: 0 · negative · range limit · wrong type · currency precision/rounding
- **payload**: missing field ≠ null ≠ empty string (3 cases) · wrong type · extra field

## §7 Pruned combinatorics (risk-oriented pairwise)

Trigger: independent facts with interacting dimensions (filters × view × export). NEVER the
Cartesian product. Select where interaction reveals bugs: new values × complex flows; high
value × modifiers; combinations that ALREADY failed (git log). Complete with pairwise.
Rules: an exceptional case (null/empty) tested once, **never combined**; do not combine
dimensions without reason to believe the code handles them together; still exploding →
report it as a design finding (the method does too much).
Bugs also live where features share state OVER TIME: expires DURING the flow, stock hits
zero in the session, key data changes midway — 1 case per pair that reads/writes the same
state (prio P1).

## §8 Recurring traps (check against EVERY time/format fact)

- **time zone**: a window computed in UTC vs. shown in local time; a naive `end` accepted
  and echoed; a daily target ("9 pm") with no defined time zone → a Requirement question,
  not an assumption
- **DST/rollover**: a day with 23h/25h; a window crossing midnight, month, year; months of
  28/31 days
- **clock**: the real `now()` in a historical query; a test without a frozen clock
- **units**: ms vs s in the SAME flow (a start in ms, points in s — real); km/mi; decimal `.`
  vs `,` in a spreadsheet export for a comma-decimal locale (a real bug found)
- **off-by-one**: `slice(0, n)` vs `n+1`; a full page+1; first/last day included?
- **empty ≠ error**: 200+empty list vs a structured 4xx — distinct contracts, both tested;
  **null ≠ absent ≠ ""** (3 cases, not 1)
- **huge**: the whole dataset, 10k points, text at the limit — clipping/pagination/timeout
