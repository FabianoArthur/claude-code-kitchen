# Troubleshooting — the real traps

Each of these cost real hours before it was understood. The fix is already built into the
skills; this page explains why, so you recognise the symptom.

## The kitchen hangs on its first shell command

**Symptom:** a freshly dispatched kitchen shows "running 1 shell command…" for an hour. The
screen still says `esc to interrupt`. The command is trivial (`git status`) and runs in under
a second elsewhere. Not deterministic: in a measured run, 3 of 5 sessions hung.

**Cause:** a tmux pane inherits the tmux **server's global** environment, not your current
shell's. If your terminal exports integration variables (for example Ghostty sets
`GHOSTTY_RESOURCES_DIR`), an interactive-shell hook can react by `exec`-ing a PTY proxy.
Claude Code's shell then *becomes* that proxy and the command never reaches a shell. The
process tree of a hung session shows the proxy as a child of `claude` and an idle `zsh`.

**Fix (two layers, both shipped):**

1. The canonical dispatch command unsets the variables **inside the pane command**:
   `env -u CLAUDECODE -u GHOSTTY_RESOURCES_DIR … KITCHEN_SESSION=1 <claude> …`.
   Unsetting them in your own shell before `tmux new-session` does nothing — the pane does
   not inherit your shell.
2. [`shell/zshrc-guard.zsh`](../shell/zshrc-guard.zsh), pasted at the top of `~/.zshrc`,
   unsets them whenever `CLAUDECODE` or `KITCHEN_SESSION` is set. Human shells are
   untouched.

Measured: without either layer, 2 of 5 sessions reached their first command within 30 s;
with the guard alone, 5 of 5; with both, 5 of 5.

Check a running kitchen:

```bash
pane=$(tmux list-panes -t '=kitchen-<id>:' -F '#{pane_pid}')
ps -o pid,ppid,comm -g "$(ps -o pgid= -p "$pane")"   # look for an unexpected proxy
tmux show-environment -g | grep -E 'GHOSTTY|TERM_PROGRAM|CLAUDECODE'
```

If `CLAUDECODE` shows up in `tmux show-environment -g`, the tmux server was (re)started from
inside a Claude Code shell and every human pane inherits it too:
`tmux set-environment -gu CLAUDECODE`.

## `tmux kill-session -t kitchen-FE-2` killed `kitchen-FE-21`

tmux matches `-t` by **prefix** unless you ask for an exact match. Always:

- sessions: `tmux has-session -t '=kitchen-<id>'` (and `kill-session`, `attach`);
- panes: `tmux capture-pane -p -t '=kitchen-<id>:'` — with a **trailing colon**. Without it
  `capture-pane` returns nothing, silently.

Quote it: zsh expands `=word` into a command path otherwise.

## The prompt arrives truncated or mangled

Long prompts inline in a `tmux new-session '…'` command break on quoting, silently. The
prompt always goes in `.kitchen/prompt.md` and the command reads it with
`"$(cat .kitchen/prompt.md)"`.

## The session starts and dies within seconds

tmux runs the pane command with `sh -c`, which may not load your shell's PATH. Use the
absolute path of `claude` (`command -v claude` at dispatch time). `doctor.py` checks this.

## The session is alive but does nothing

Two dialogs can hold the first boot:

- **Bypass Permissions** acceptance — shown the first time `--dangerously-skip-permissions`
  runs on a machine;
- **folder trust** — shown for a directory Claude Code has not seen (every new worktree). It
  opens with "No, exit" selected.

Check ~30 s after dispatch with `tmux capture-pane -p -t '=kitchen-<id>:'`, then attach,
accept, detach (`Ctrl-b d`). Never arm the watcher on a stuck dialog.

## Every `gh` call returns HTTP 401

An invalid `GH_TOKEN` in the environment wins over your keyring login — `gh` treats the
environment variable as the active account. Your terminal works; the agent's environment does
not. Put the fix in the adapter, not in a skill:

```yaml
gh: "env -u GH_TOKEN gh"
```

## A kitchen is slow to boot and heavy on RAM

Every MCP server is a process plus tool definitions in context, per session. Kitchens start
with `--strict-mcp-config` (no MCP at all). Give a unit a server only if it provably needs
it: `--mcp-config '<json of that server>'`.

## The diff gate says "clean" but you know it should fire

- You pointed it at the repo root instead of the worktree — the root's index has nothing
  staged.
- The line you expect it to catch is a comment (ignored by design) or was not staged.
- The pattern was written with the wrong escaping. In the adapter's double-quoted YAML,
  write `"console\\.log\\("`. `gate_diff.py --selftest` shows the parser at work.

## The watcher never wakes up after a pause

The row still says `⏳`. Whoever resolved the pause must rewrite it to `🔄 running` —
otherwise the watcher exits again on the same `⏳`. (It is the documented `⏳ → 🔄`
transition.)

## `/harvest` refuses to delete a branch

`git branch -d` refuses when the branch is not merged into your **local** base — common
after a squash merge. Fetch and fast-forward the base; if it still refuses, check by hand.
`/harvest` never uses `-D`.

## A compound shell watcher exits early

Shell hooks that rewrite common utilities (token-saving proxies and similar) can change the
output or exit code of `grep` inside a `while` loop, and the loop exits with no event. That
is why the watchers are single Python processes.
