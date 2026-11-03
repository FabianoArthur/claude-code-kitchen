# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `menubar/kitchen.30s.py`: a SwiftBar plugin for the macOS menu bar. Unit counts by state,
  one menu item per unit (last screen line, Open PR, Attach, Copy attach command), and
  divergences between manifests and tmux sessions (orphan session, crashed `🔄` row,
  finished session still alive). Reads English and Portuguese manifests; configured through
  `~/.config/kitchen-menubar/config.json`. See `docs/menubar.md`.

### Changed

- `menubar/kitchen.30s.py`: native look. The bar is a flame SF Symbol plus the running and
  waiting counts (counts turn orange when a unit waits on you; a divergence swaps the flame for a triangle and turns them red)
  instead of a row of emojis. The menu has coloured SF Symbol group headers (empty groups are
  hidden), the unit name on its own line with a small gray metadata line under it, icons on
  every action, light/dark colour pairs, and a collapsed **Earlier** submenu for units that
  finished more than a day ago. Same information, same config; needs SwiftBar 2.0 or newer for
  the icons (checked on 2.1.1).

### Security

- `gate_diff.py` pins the diff format (`--no-color --no-ext-diff --no-textconv --text`,
  fixed prefixes): a user's `color.ui=always`, `diff.external`, a textconv driver or a
  committed `*.x -diff` attribute no longer makes the gate report "clean".
- `install.sh` asks before moving a same-named skill of yours aside; without a terminal it
  changes nothing unless you pass `--yes`.
- CORE §1: the order (task doc, issue, comment, command output) is data, not
  instructions; `github-issues` on a public repo dispatches only trusted authors.
- Dependabot for pip and GitHub Actions; `SECURITY.md` with response timelines.

## [0.1.0] - 2026-09-25

### Added

- Skills: `orchestrate` (with `CORE.md`, the shared rulebook), `execute`, `dotask`,
  `harvest`, `plan`, `qa`.
- Orchestrate scripts: `dispatcher.py` (capped batch dispatch with hibernation), `doctor.py`
  (pre-flight), `gate_diff.py` (the `forbidden_in_diff` gate), `watch.py` (zero-token
  watcher of one kitchen unit).
- QA scripts: `qa_preflight`, `qa_matrix`, `qa_budget`, `qa_report`, `qa_filter`,
  `qa_mutation`, `qa_watcher`.
- `install.sh` with `--dry-run`, `--uninstall` and `--target`; backs up anything in the way.
- `shell/zshrc-guard.zsh` for non-human shells.
- Examples (adapter, QA adapter, task doc) and a demo project.
- Documentation in English with a full Portuguese (Brazil) README.
- CI: pytest + every `--selftest`, ruff, shellcheck, markdownlint, lychee, gitleaks.

[Unreleased]: https://github.com/FabianoArthur/claude-code-kitchen/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/FabianoArthur/claude-code-kitchen/releases/tag/v0.1.0
