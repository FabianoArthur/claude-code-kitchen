# Oracles — naming the source and judging the result

Every case in `.qa/cases.tsv` gets `oracle_source` filled BEFORE it runs — a closed taxonomy,
combinable with commas (`impl,invariant`). The gate (`qa_matrix.py`) rejects an empty
source, one outside the taxonomy, and `impl` alone. No independent source reachable within
the budget → the case becomes a row in `.qa/gaps.tsv` with a reason, never an invented
expected value.

## Taxonomy — how to derive each source (cheapest first)

### `spec` — what the human ASKED for

Task doc, acceptance criteria — already paid in Step 0. The best source for P0: the verdict
ties to the acceptance criteria, so the case that exercises them literally is the most
defensible. Derivation: a `facts.tsv` fact sourced from the task → the literal expected
value of the criterion's sentence. A vague spec ("fast", "easy") is not an oracle: turn it
into a Requirement question, or record in the case the assumption adopted.

### `consumer` — whoever calls it in practice

The shape the consumer expects IS a contract, even undocumented. Derivation: search the
sibling repo (the frontend consuming the backend's endpoint — counts toward the query cap)
or real call sites by file:line. What the caller destructures (`resp.data.items`, the field
used in a `.map`) is the expected value; a field the caller reads that the endpoint stopped
sending is a FAIL even with a 200. In a diff: a stronger pre-condition or a weaker
post-condition = breaking — write the case from the caller's point of view.

### `invariant` — a property that depends on nobody

A domain truth checkable just by looking at the output: sorted, never negative, the sum of
the parts matches the total, idempotent (the 2nd call changes nothing), output ≤ input,
unique id. Cost ~0: needs no spec nor code reading, just 1 domain sentence from `facts.tsv`.
The default source of property cases (audit) and the cheapest complement to rescue a case
from `impl` alone.

### `parity` — the SAME data through two routes

Consistency between surfaces showing the same data: do the table and the exported CSV
agree? do the N endpoints returning an order's total return the same total? does the dashboard
counter match the listing's size? Derivation: 2 calls/screens + a diff — neither needs to be
"right"; a divergence is already a finding (one of the two lies). Powerful when there is no
spec: the system contradicting itself needs no requirement interpretation.

### `doc` — a versioned external reference

The repo's OpenAPI/Swagger, an API README, a library's docs, an RFC. Derivation: grep for
`openapi|swagger|@ApiProperty` within the cap. Different from `spec`: `doc` is the published
technical contract; `spec` is the human's intent. An outdated doc vs. current behaviour = a
Requirement question (which of the two is the contract?), not an automatic FAIL.

### `impl` ⚠ — the code itself, NEVER alone

Reading code to find limits and branches (mechanical BVA of the `if`s) is legitimate and
cheap — but an expected value derived ONLY from there is a circular oracle: whoever wrote
the bug computes the wrong expected value and the test enshrines the error as the answer
key. Correct use: `impl` finds WHERE to test; combined (`impl,invariant`, `impl,consumer`)
it says WHAT to expect. A snapshot of current behaviour as the answer key = `impl` in
disguise — same veto.

## Judgement rules (apply to EACH executed case)

1. **Expected BEFORE running, including what must NOT change.** A case = input + precise
   output + vetoed side effects: records outside the filter untouched, no duplication on
   retry, input not mutated. Half the battle is what the program must not do — the `oracle`
   column records both sides.
2. **Examine the whole result, not only the main assertion.** A plausible-but-wrong output
   passes when you look at 1 field; a null neighbouring field, a wrong count and a warning in
   the log are findings of the SAME case — evidence already paid for.
3. **A doubtful rule ≠ a bug.** Spec and behaviour diverge in a way reading code does not
   resolve ("9 pm in whose time zone?") → a "Requirement question" in the report. Never a
   mirror-approval (the code becomes the rule), never an invented bug (your reading becomes
   the rule).
4. **Environmental vs. real triage BEFORE reporting.** Reproduces in isolation, outside
   concurrency? Correlates with deploy/time/the adapter's rate limit? Clustered failures (same
   endpoint, data, time) = systemic; scattered = probably infra. Retry 1–2× ONLY for
   environmental — retry-until-green on a deterministic failure manufactures a false green.
   And "the test is wrong" is a first-class hypothesis: a divergence has a double hypothesis
   (a bug in the target OR in the case) — check the case before opening a record.
5. **Severity by MEASURED impact, never by symptom category.** "Just performance"/"just
   cosmetic" does not exist before connecting it to the data: who goes through there, what
   they lose, is there a workaround? That separates S1–S4 — a failure on the main flow ≠ a
   failure in help text.
6. **Trend > threshold.** Latency/memory growing monotonically with everything green = a
   reportable latent defect, with a projection of when it blows up. In repeated probes, the
   derivative says more than the final pass/fail.

## Free oracles (cost ~0 — use them WHENEVER the route allows)

- **Browser console + network 4xx/5xx** (inline route): an error there is a finding without
  judgement — collect it before any visual assertion.
- **Exit code + count of the filtered suite** (`qa_filter.py -- <cmd>`): assertions written by
  someone else, running for free — respecting the adapter's `tests.forbidden`.
- **Existing schema validators** (zod/pydantic/class-validator): pre/post-conditions already
  written. Input violating a pre-condition must give 422/raise, never a plausible value; a
  violated post-condition (negative where ≥0 is promised) is a bug with a ready oracle.
- **HTTP status + shape vs. an equivalent call that already works**: the healthy neighbouring
  endpoint defines the expected envelope, error format and pagination — cheap parity.

## A target with embedded AI

- **Layers, cheap → expensive**: rule/heuristic on 100% of outputs (empty? "Error" leaking?
  a claim without hedging? response tokens absent from the sources?) → drift statistics
  (length, refusal rate, repetition) → an LLM judge ONLY on the flagged ones, with structured
  output (closed labels), confirmed by a 2nd pass or structured data — never a single verdict
  as proof.
- **External ground truth for factual content**: a hallucination is a wrong answer that looks
  right; plausibility is not an oracle. Dynamic facts come from a tool/RAG — key assertion:
  the answer contains EXACTLY the data the tool returned.
- **Refusal as an oracle**: a question with no answer in the corpus → "I don't have that
  information"; a confident invented answer = a critical bug. Tool failure → admit it, never
  fabricate.
- **Tolerant assertions, never an exact string**: must_include + bounds + expected elements;
  still flaky → N runs + majority vote, and high divergence between runs is itself a
  reportable finding (self-consistency).
- **Trajectory in a multi-step flow**: compare the set AND SEQUENCE of tool calls with the
  expected ones — catches a wrong process with a plausible output (a mandatory step skipped).
- **You are an LLM judge and you hallucinate**: your own verdict on correctness = PLAUSIBLE
  until confirmed by a real run, structured data or a 2nd pass — only then is it a finding.
