# Gates

A gate is a check that stops a unit from moving forward. The kitchen has four, and one rule
about all of them: **a gate reports only what actually ran.**

## 0. Eligibility (before any work)

Four filters, in order, on every order:

1. **Status** — open? ("postponed" looks open and is not.)
2. **Layer** — does this repo implement it?
3. **Dependencies** — is every `depends_on` done?
4. **Reality** — was it already done? `git log <base> --grep=<id>` and a search for the
   artifact the task names.

Measured on a real project: 8 of 55 "to do" cards were already cited in commits on the base
branch. Without filter 4, the first dispatch would have rebuilt five existing classes.

## 1. `forbidden_in_diff` — deterministic, before the commit

```yaml
forbidden_in_diff:
  - pattern: "console\\.log\\("
    why: "debug output must not ship"
```

`skills/orchestrate/scripts/gate_diff.py <worktree>`:

- reads **only added lines** of the **staged** diff (`git diff --cached -U0`);
- drops the `+++` header, removed lines and context lines;
- **ignores comment lines**, judged by file extension (`--` is a comment in SQL, a decrement in
  JS), so the comment that documents a rule never trips it;
- pins the diff format (`--no-color --no-ext-diff --no-textconv --text`, fixed `a/`/`b/`
  prefixes), so your git config (`color.ui=always`, `diff.external`) or a committed
  `.gitattributes` (`*.js -diff`) cannot hide the added lines from it;
- exits `0` clean · `1` hit · `2` git failed or the adapter's block is malformed (never
  "clean" on an error).

It is a **quality** gate, not a security boundary: comment detection is by line prefix, so
`/**/ console.log(x)` reads as a comment. It keeps honest mistakes out of the diff; the
review of the PR is what stops a determined author.

Point it at the worktree, not the repo root: the root's index is not where the unit's diff
is. A hit is fixed by the agent and the gate is rerun — no human question.

## 2. Independent plan review (large units)

Units whose size is in `large_sizes` (default `L`, `XL`) get their plan reviewed by an
independent subagent: plan + blast radius in, `APPROVED` or objections out, up to 4 rounds.
**The human is not asked** — that is the point. The human reviews the PR.

## 3. Blast radius

Every plan declares the files it will touch, per adapter layer:

```markdown
### Blast radius
- api: src/api/auth/login.ts
- api: src/api/lib/limiter.ts        (read only)
- tests: tests/api/login.rate-limit.test.ts   [new]
```

Every path must exist or be marked `[new]`. Before the commit, `git diff --name-only` is
compared with the list:

| bucket | action |
|---|---|
| declared ∩ touched | fine |
| declared − touched | overestimated; harmless |
| touched − declared > ~30% of touched | explicit scope-leak warning in the task doc's `## Outcome` and the PR |

The blast radius is also how `/orchestrate` detects collisions: two units declaring the same
file never go in the same batch.

## 4. Definition of done + honest report

- **Logic/data/infra:** a test that fails before and passes after (real TDD), `tests.allowed`
  green, `## Outcome` written from `git log`/`git diff --stat`.
- **UI:** no TDD theater — exercised on the scarce resource and seen by a human.
- **Surface consumed by another repo:** find the caller (search both sides by name); if it
  breaks, warn with repo + file:line + fix. Do not fix the consumer in the same unit.

The PR body carries one line per check **actually run**, with its real output
(`45 passed`, `ruff: 0 errors`). A check that did not run is `⚠️`/`❌` with a reason. A
`## Not verified` section is mandatory (`nothing` if nothing). An unrun check presented as
run is worse than no gate: the human stops checking the rest.

## For `/dotask`: acceptance criteria and pre-PR review

- The task doc's acceptance criteria are the definition of done: the PR opens with every
  box checked or with the unchecked one justified in the PR body.
- Before the PR, an independent reviewer subagent (`model_review` from the task doc) gets
  `git diff <base>...HEAD` + the criteria and answers `APPROVED` or problems — up to 3 rounds.
  Its verdict goes in the PR body.
