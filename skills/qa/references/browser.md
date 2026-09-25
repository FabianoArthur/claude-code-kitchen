# browser.md — UI cases: browser automation in the waiter (today's route) + Playwright (dormant)

Loaded when the matrix has UI cases. Hard context, not negotiable: browser automation (for
example the Claude in Chrome extension) usually exists ONLY in the waiter (INLINE route,
human present) — a kitchen session is born with no MCP; a browser case in a dispatched unit
= wrong routing (`⏳` and report, SKILL.md "Two entry points"). §3 (Playwright) is dormant
until the adapter says otherwise. A dev server NEVER starts without the human — its port is
typically the project's `scarce_resource`. The QA adapter carries
`browser: {route, base_url, login_as, flags}`.

## §1 Browser automation protocol — today's route

**Triage first: does the case deserve a browser?** A case only becomes a browser case if the
defect is observable ONLY in the UI (render, visual state, interaction, feedback). If the
oracle is an API response, the case GOES DOWN to an HTTP probe (dispatchable route, api.md)
— cheaper and parallelisable. **The matrix decides, not habit**: reread each browser case
asking "which assertion here cannot be checked over HTTP?"; no answer → reclassify.

**Setup (once per run):**

1. Load every browser tool you will need in ONE go (a single tool-search call, if your
   harness defers tools). One call per tool wastes a round trip.
2. Read the current tab context FIRST. Create a new tab for the run — NEVER reuse the
   human's tab without an explicit request: they work in the same browser.
3. Log in per the adapter's `browser.login_as`; base per `browser.base_url`.

**Free oracles — once per visited screen, always, cost ~0, and they decide:**

- Console messages: ANY framework error/warning is a finding without judgement (duplicate
  key, state update on an unmounted component, unhandled error). Do not interpret it
  benevolently — record it and classify later.
- Network requests: 4xx/5xx in a normal flow; the SAME call firing in a loop (an effect
  without dependencies); a refetch on every keystroke (missing debounce). A bad network
  pattern is a finding even with the screen "working".

**Sensor cost, cheapest first:** read the page text or the accessibility structure — use it
as the default assertion. Screenshot ONLY as FAIL evidence, saved to `.qa/evidence/` — never
as a way to "look at the screen" case by case. GIF/recording: never.

**3 environment targets, cheapest first (the qa_preflight.py policy prevails):**

- (a) **Local UI mocked with MSW** (or similar) — the adapter's `browser.flags` gives
  error/empty/loading states without a real API, the most expensive to force in staging.
  BUT the dev server is the human's: ask them to start it with the flag; never start it
  yourself (hard rule 4).
- (b) **Staging** (`browser.base_url`) — read-mostly: navigate/read freely, write only the
  minimum the case needs, with teardown. Shared data shifts under your feet: a divergence
  there does NOT fail without a retest; environmental vs. real triage (SKILL.md Step 6)
  before FAIL.
- (c) **Production** — NEVER. Not even a GET "just to compare" (hard rule 2).

**Interaction discipline:**

- Wait for a CONDITION (element/text present), never a fixed sleep — the #1 cause of
  flakiness. Async action → recheck the state BEFORE asserting.
- Fill forms with the form-input tool, not character by character.
- NEVER trigger native dialogs (alert/confirm/prompt/beforeunload) — they freeze the
  automation. A case that depends on them → SKIP with a named reason in the matrix.
- Each case fills `result`+`evidence` in `.qa/cases.tsv` right away (evidence = quoted
  text/console/network; screenshot only on FAIL).

## §2 Messy-user scenarios (apply to the P0 flows)

Real users do not follow the developer's happy path. On the matrix's P0 flows, run the
personas (1 case per applicable persona, not the Cartesian product):

- **Impatient**: double-submit on the button (clicking twice before it disables), refresh
  mid-flow, back/forward in the middle of a wizard. Oracle: the side effect happens once
  (check the network: how many POSTs went out?).
- **Distracted**: leaves the screen and comes back (state preserved or cleanly reset — never
  a corrupted hybrid); session expired mid-action (a clear error + a way to recover, not a
  blank screen); multiple tabs on the same account (tab B does not corrupt what A did).
- **Power user**: unforeseen combinations of filters/options; state created directly through
  the API and read by the UI (does the screen cope with data it would not create itself?).
- **Malicious**: unicode/emoji in an indexed/searchable field; maximum sizes; pasting huge
  text. Oracle: no 500, no corruption, a structured error.
- **Cross-cutting**: switching language/key data IN THE MIDDLE of a flow (does the partial
  state follow or break?); aggressive timing <2 s between actions — machines do not pause
  like humans, and that is how a "non-reproducible" race reproduces.

Standard check for all three: **no duplicated effect, no state corruption, no silent
failure** (clean console+network are part of the PASS, not a courtesy).

## §3 DORMANT — Playwright route (do NOT use until `browser.route: dispatchable`)

This section does NOT authorise installing anything. Switching is the human's decision via
`/plan` — never the skill's in the middle of a run.

**Objective triggers to PROPOSE the switch** (propose it when closing the report, 1 line):

- The same UI flow was re-run by hand in ≥3 distinct QA runs;
- The human asked for a reproducible release/CI smoke without them present;
- The inline queue became the batch's bottleneck (browser cases damming the kitchen).

**Payoff that justifies the cost**: the browser becomes a dispatchable route — headless, in a
worktree, tmux — and UI cases route like API ones (Step 5), freeing the human.

**The accumulated matrix IS the script**: each browser case executed (`.qa/cases.tsv` of past
runs + run files) converts almost 1:1 into a spec. Conversion rules (infrastructure first,
cases after):

- Locators by role+accessible name → visible text → `data-testid`. NEVER CSS/position — a
  reorganised menu kills most CSS selectors and few intent-based ones.
- A Page Object per page: a business action hides the selector; an action that navigates
  returns the next page's PO; the spec only composes POs and asserts.
- Seed/reset state through the API (test-only scenario endpoints), never through the UI —
  orders of magnitude cheaper; navigate the UI only when the step IS the journey under test.
- Wait for a condition with a timeout (the framework's auto-wait), zero fixed sleeps.
- Config (baseURL, credentials) via env — the adapter's `browser:` fields migrate directly.

**When the switch happens**: the adapter gets `browser.route: dispatchable`; browser cases
leave the inline queue and go to tmux `kitchen-qa-<slug>` like API ones; MSW/flags still hold
for hard states; console+network remain oracles (Playwright exposes them). This file then
updates itself — §1 becomes the exception (inline exploration) and §3 the rule.
