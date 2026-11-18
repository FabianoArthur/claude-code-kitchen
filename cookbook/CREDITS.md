# Credits

The cookbook is a catalog built on other people's work. This file says what came from where
and what is ours.

## Everything Claude Code (ECC)

- Repository: <https://github.com/affaan-m/ECC>
- Version and commit indexed: v2.2.3, commit `d2ef268` (`d2ef2680594f9a17526a6e1a2e18b3d242c5d17b`)
- License: MIT, © 2026 Affaan Mustafa. The license text is kept in [`LICENSE-ECC`](LICENSE-ECC),
  as the MIT license requires.

**What came from it:** the inspiration and the raw material. `ecc-index.md` lists the names,
types, paths and one-line descriptions (copied from each item's own frontmatter, truncated) of
its agents, commands, skills, rules, scripts and hooks. `COOKBOOK.md` and the graph group those
items by occasion. The ECC source itself is **not** vendored here: `fetch_pantry.sh` downloads
it, pinned to the commit above, into the git-ignored `pantry/` folder.

## work-cli

- Repository: `TrussInt/work-cli`, v0.6.1. It is a **private** repository: we analyzed it and
  borrowed ideas only (fleet scheduling, worker selection, slots for heavy commands). **No code
  from it is included.** `fetch_pantry.sh` fetches it only for people who already have access,
  and skips it otherwise.

## What is ours

- The occasion-based organization of the catalog (`COOKBOOK.md`), the pt-BR search synonyms, the
  graph and the scripts that build it (`index_ecc.py`, `build_cookbook.py`, `build_graph.py`), and
  `fetch_pantry.sh`.
- The `cookbook` skill (`skills/cookbook/`).
- The analysis documents in [`docs/`](../docs/): the kitchen brigade and adoption plan
  (`ecc-adoption-plan.md`), the work-cli plan (`work-cli-adoption-plan.md`) and the review of
  ECC's agents, commands, rules, hooks, memory, security and skills (`docs/ecc/`). They record
  our own decisions about what to adopt, adapt or ignore.

If you are an author of a project listed here and want something changed or removed, please open
an issue.

## Third-party skills

- `archify` — tt-a1i, <https://github.com/tt-a1i/archify>, Apache-2.0 (README) and MIT (LICENSE in the skill folder).
- `ponytail` — DietrichGebert, <https://github.com/DietrichGebert/ponytail>, MIT.

Neither is vendored: `skills/third-party/install.sh` downloads a pinned commit (see
[`docs/third-party-skills.md`](../docs/third-party-skills.md)).
