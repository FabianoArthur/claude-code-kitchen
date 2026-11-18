# Third-party skills

Two skills written by other people are useful in the kitchen. We do not vendor them (about 40 MB
of someone else's code). Instead, `skills/third-party/install.sh` downloads one reviewed commit
of each and copies only the skill folder into your skills directory.

| Skill | What it does | Pinned version | License |
|---|---|---|---|
| `archify` | Draws architecture diagrams from a codebase. | [tt-a1i/archify](https://github.com/tt-a1i/archify) v3.2.0, `208acba` | Apache-2.0 (README), MIT (LICENSE in the folder, copied with it) |
| `ponytail` | A "lazy senior developer" style: the smallest change that works, tests only for risky logic. | [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail) v5.3.3, `7801d06` | MIT |

The full SHAs live in [`skills/third-party/pins.tsv`](../skills/third-party/pins.tsv).

## Install

```bash
bash skills/third-party/install.sh --dry-run          # show the plan, change nothing
bash skills/third-party/install.sh                    # both skills
bash skills/third-party/install.sh --only ponytail    # one skill
bash skills/third-party/install.sh --target DIR       # instead of ${CLAUDE_SKILLS_DIR:-~/.claude/skills}
```

For each skill the script fetches that single commit, checks that `git rev-parse HEAD` equals
the pinned SHA (otherwise it exits non-zero and installs nothing), and copies only the skill
folder. An existing skill with the same name is moved to `<name>.bak-<timestamp>` after you
confirm (or pass `--yes`); nothing is ever deleted. To update a skill, review the new upstream
commit and change the line in `pins.tsv`.

## Rules

- The task and the project rules always win over a skill.
- Use `ponytail` at level `full`, never `ultra`.
- An `archify` diagram that contains private data stays local: never publish or share it online.
- Hooks, commands and plugins from these projects are **not** installed. `ponytail` ships a
  `SessionStart` hook that edits `settings.json`; we do not let third-party code change the
  user's settings or run on every session. The skill alone (a text file) is enough.
