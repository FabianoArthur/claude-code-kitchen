# Bootstrapping /qa — first run in a repo without `.claude/qa.md`

Loaded when `qa_preflight.py` exits 3. Goal: PROPOSE the QA adapter and **STOP for the
human to confirm** — the only human gate of /qa. The kitchen's golden rule: never a project
value hard-coded in a skill; a field you cannot verify on disk → ask the human, and the
answer is recorded HERE (in the repo's qa.md).

## Prerequisite

`<repo>/.claude/orchestrator.md` must exist FIRST — qa.md extends it via `extends`
(`tests.allowed`/`forbidden`, `gh`, worktrees, vault, scarce resource). Missing → run the
CORE §9 bootstrap first, **in the same stop**: propose both adapters together and the human
confirms once.

## What to detect on disk before proposing (concrete commands)

- Environment danger → becomes `forbidden_env[]` + `import_rule_grep`:
  `grep -EinH 'mongodb\+srv|postgres://|prod|amazonaws|\.com' .env .env.* 2>/dev/null`
  (production indicators, real hosts); and scripts that import the app's root module:
  `grep -rlnE 'AppModule|create_app' scripts/ 2>/dev/null`
  — booting the root module can start EVERY cron job.
- Environments: staging URL in docs/README (`grep -rEin 'staging|homol|hml' README.md docs/`);
  frontend: mock flags (`grep -rEin 'MSW|ENABLE_MOCK' .env* src/mocks/ 2>/dev/null`) and
  variables pointing at production (`grep -EinH 'VITE_|API_URL' .env* 2>/dev/null`).
- Test output: does a shell hook mangle jest/vitest output? If the orchestrator adapter
  already documents a workaround, **inherit it** — do not rediscover it.
- Sibling consumers (who calls this repo?): search the sibling repos for this repo's routes/
  types → becomes `external_oracles`.

## Full qa.md schema (the EXACT format qa_preflight.py parses — it is LAW)

```yaml
project: <name>                        # same name as in orchestrator.md
extends: .claude/orchestrator.md       # inherits tests.*, gh, worktrees, vault
environments:                          # the run's environment policy
  local:
    allowed: true|false                # on the line RIGHT AFTER `local:` (the parser needs it); false → exit 1
    why: "<if false>"                  # e.g. ".env points at the production database"
  staging:
    url: <url>                         # base URL of the staging environment
    credentials: "<HOW to get them — never the value>"   # e.g. "password manager, item <X>"
    rate_limits: "<what is environment, not a bug>"      # feeds the Step 6 triage
    mutation_allowed: "<what may be written>"            # e.g. "only entities prefixed qa-"
  production: read_zero                # immutable — not even GET (hard rule 2)
forbidden_env:                         # item on ONE LINE, double quotes; pattern = regex, case-insensitive
  - {file: ".env", grep_pattern: "<regex>", why: "<...>"}
probe:
  allowed: true|false                  # do local ephemeral probes exist in this repo?
  safe_env: "<file>"                   # a human creates it once; preflight checks it matches no forbidden_env
  import_rule_grep: "<regex>"          # rejects a dangerous probe, e.g. "AppModule"
  teardown: "<rule>"                   # e.g. "rm the probe + drop every qa_* database"
filtered_output: "<command>"           # a command that returns trustworthy test output
regression_suite_allowed: true|false   # false → a vetoed suite stays NAMED under "NOT covered"
external_oracles: [<list>]             # where independent oracles come from (consumers, spec, docs)
risk_profile: [<3-5 risks>]            # from the repo's real history; orders the matrix's P0s
data: {seed: "<how to seed without dirtying>", reset: "<how to reset>"}
browser: {route: inline|dispatchable, base_url: <url>, login_as: "<how>", flags: "<e.g. VITE_ENABLE_MSW=true>"}
```

## Proposal and stop

1. Build the qa.md from what you detected; mark `# INFERRED` on every line you did NOT verify
   on disk.
2. Sanity check BEFORE showing it: write the proposal to `<scratch>/repo/.claude/qa.md`, copy
   the files cited in `forbidden_env` to `<scratch>/repo/`, and run
   `python3 <skills>/qa/scripts/qa_preflight.py <scratch>/repo` — the exit code must be the
   expected one (a broken parse = an invalid proposal; fix it first).
3. Show the human the yaml + the open questions (how to get staging credentials? what
   mutation is allowed there? does safe_env exist or will they create it?). **STOP — the
   human confirms or edits.**
4. Confirmed → write it to `<repo>/.claude/qa.md`.
5. `.gitignore`: if the repo ignores `.claude/`, make sure the adapters are un-ignored with
   `.claude/*` + `!.claude/qa.md` (it must be `.claude/*`, never `.claude/` — otherwise git
   does not descend into the directory and the negation is never evaluated). Validate with
   `git check-ignore`.
6. Run `qa_preflight.py <repo>` for real and go on to Step 1 of the run.
