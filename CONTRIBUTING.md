# Contributing

Thanks for helping! Bug reports, docs fixes and focused PRs are all welcome.

## Ground rules

- **Project values never go into a skill.** If you need a new setting, add a field to the
  adapter (`skills/orchestrate/CORE.md` §1, `docs/adapter.md`, `examples/adapter.md`) and
  have the skill read it.
- **Scripts stay stdlib-only and single-file**, runnable with `python3 script.py`, each with
  a `--selftest`. Python 3.10+.
- **tmux in tests uses a private socket** (`tmux -L <name>`, see `tests/conftest.py`). Never
  touch the default tmux server in a test.
- **Logic changes come with a test that fails before the change.**
- Conventional commits: `type(scope): description` (`feat`, `fix`, `docs`, `test`,
  `refactor`, `ci`, `build`, `chore`, `perf`, `style`).

## Local checks (the same ones CI runs)

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest                      # includes every script's --selftest
ruff check .
shellcheck install.sh
zsh -n shell/zshrc-guard.zsh
npx --yes markdownlint-cli2@0.18.1 "**/*.md"
lychee --offline --no-progress --include-fragments '**/*.md'
gitleaks dir . --redact
```

## Keeping private data out

This repository is public. Before pushing, make sure the diff contains no personal paths,
e-mail addresses, tokens, or names of private projects/clients. `tests/test_no_private_data.py`
checks generic patterns; if you maintain a fork with your own private terms, put them in a
local `.private-denylist` file (one term per line, git-ignored) and the same test will check
them too — the list itself never gets committed.

## Changing a skill

Skills are instructions for an agent, so wording is behaviour. In the PR description, say
which failure the change prevents and, if you can, how you observed it. Keep `CORE.md` the
single source of shared rules — skills reference it instead of restating it.
