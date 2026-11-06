# Toolkit: the tools the kitchen is run with

Everything here is **optional and made by other people**. The kitchen needs only what
[`install.sh`](../install.sh) asks for (git, tmux, Python 3.10+, `gh`); it neither depends on
nor installs anything below. This is the kit its author runs it with, grouped by what it is
for, so you can pick. Install commands are the ones each project's own docs showed when this
page was written; check them before running, and read what a hook or plugin will change in
your settings.

## Save tokens and context

Each kitchen is a full Claude Code session, several share one plan's quota, and every token a
session reads is sent again on each call after it. Anything that makes a session read less
pays off once per kitchen.

| tool | what it does | install |
|---|---|---|
| [RTK](https://www.rtk-ai.app/) (Rust Token Killer, [source](https://github.com/rtk-ai/rtk)) | CLI proxy: rewrites shell commands and trims the noise from their output (git, test runners, linters, docker…) before the agent reads it. Apache 2.0. | `brew install rtk-ai/tap/rtk`, then `rtk init --global` |
| [graphify](https://github.com/Graphify-Labs/graphify) | Builds a knowledge graph of a repo into `graphify-out/graph.json`; the agent asks `graphify query "<question>"`, `graphify path A B`, `graphify explain X` and gets a small scoped answer instead of reading files. | `uv tool install graphifyy` (two "y"; the command is `graphify`), then `graphify install` |
| [context7](https://github.com/upstash/context7) | Looks up current, version-specific library docs on demand, instead of pasting docs into the prompt. Plugin in the official marketplace. | `/plugin install context7@claude-plugins-official` |

Notes:

- `rtk init --global` installs a `PreToolUse` hook in Claude Code's `settings.json` that
  rewrites **every** Bash call, kitchens included. The kitchen's own watchers are Python
  scripts for that reason (see [Shell hooks and output proxies](integrations.md#shell-hooks-and-output-proxies)).
- graphify fills the kitchen's [code graph](integrations.md#code-graph) slot: the skills use a
  graph first when building a blast radius, and `post_commit` can refresh it after each
  commit. Add `graphify-out/` to `.gitignore` if you do not want to commit it.

## Claude Code plugins

From the official marketplace (`claude-plugins-official`); install with
`/plugin install <name>@claude-plugins-official`.

| plugin | what it does |
|---|---|
| [superpowers](https://github.com/obra/superpowers) | Brainstorming, subagent-driven development with built-in review, systematic debugging, red/green TDD. |
| code-review | Automated pull-request review with several specialised agents and confidence scoring. |
| code-simplifier | Simplifies recently modified code for clarity while preserving behaviour. |
| feature-dev | Feature workflow with agents for codebase exploration, architecture and quality review. |
| claude-md-management | Audits and maintains `CLAUDE.md` files. |
| skill-creator | Creates, improves and benchmarks skills. |
| frontend-design | Production-grade frontend interfaces with a deliberate design direction. |
| github | The official GitHub MCP server (issues, PRs, code search). |
| discord | A Discord bridge with access control: a way for the waiter to receive and announce requests away from the terminal. |

From other marketplaces (third party):

| plugin | what it does |
|---|---|
| [claude-council](https://github.com/hex/claude-council) (marketplace [hex/claude-marketplace](https://github.com/hex/claude-marketplace)) | Asks several other AI models the same question and shows the answers side by side: a second opinion. |
| [ui-ux-pro-max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) | A searchable UI/UX design-rules skill for frontend work. |

## Watch your usage

| tool | what it does | install |
|---|---|---|
| [claude-monitor](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor) | Terminal monitor of Claude Code usage and limits, with forecasting and local history. | `uv tool install claude-monitor` |
| the menu-bar widget and **Kitchen.app** (this repo) | The kitchen's own state in the macOS menu bar; the app also shows plan usage. | [menubar.md](menubar.md), [macos-app.md](macos-app.md) |

## Gates and checks

The ones this repo's CI uses; run any of them against your own
project too. Nothing here is required to use the kitchen.

| tool | used for |
|---|---|
| [pytest](https://docs.pytest.org) | this repo's test suite (it also runs every script's `--selftest`) |
| [ruff](https://github.com/astral-sh/ruff) | Python lint |
| [shellcheck](https://github.com/koalaman/shellcheck) | shell script lint |
| [gitleaks](https://github.com/gitleaks/gitleaks) | secret scan |
| [markdownlint-cli2](https://github.com/DavidAnson/markdownlint-cli2) | Markdown lint |
| [lychee](https://github.com/lycheeverse/lychee) | link check |

## What the kitchen runs on

| tool | why |
|---|---|
| [tmux](https://github.com/tmux/tmux) | one detached session per unit; survives `/clear` and a closed terminal |
| `git worktree` | one isolated checkout per unit |
| [GitHub CLI](https://cli.github.com) (`gh`) | opens the PR, reads issues |
| [uv](https://docs.astral.sh/uv/) | installs the Python-based tools above in isolated environments |
| `caffeinate` (built into macOS) | a Mac that goes to sleep pauses its tmux sessions; `caffeinate -i` keeps it awake while a kitchen works |
