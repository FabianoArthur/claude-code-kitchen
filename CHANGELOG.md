# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/Fabiano-Arthur/claude-code-kitchen/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Fabiano-Arthur/claude-code-kitchen/releases/tag/v0.1.0
