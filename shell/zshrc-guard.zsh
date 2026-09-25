# >>> claude-code-kitchen: non-human shell guard >>>
# Paste at the TOP of ~/.zshrc, before any terminal-integration block (completion proxies,
# multiplexer auto-start, and similar).
#
# Why: a shell opened by Claude Code (its Bash tool) inside a kitchen tmux session inherits
# the tmux server's GLOBAL environment — including terminal-integration variables such as
# GHOSTTY_RESOURCES_DIR. Some interactive-shell hooks react to those variables by `exec`-ing
# a PTY proxy or auto-attaching a multiplexer. The shell then becomes that proxy, the
# agent's command never runs, and the kitchen hangs forever on its first shell command while
# the screen still says "esc to interrupt".
#
# Condition: CLAUDECODE (set by Claude Code in every child shell) or KITCHEN_SESSION (set by
# the kitchen's dispatch command). Neither exists in a human terminal, so for a human this
# guard is a no-op. `! -t 0` is not used: it does not tell Claude's shell (which may have a
# PTY) apart from a human's.
#
# What it does: removes, from THIS shell's environment, the variables later blocks use to
# detect the terminal, so those blocks become no-ops without editing them (installers tend
# to rewrite their own blocks). Add your terminal's variables to the list if they differ.
if [[ -n "$CLAUDECODE" || -n "$KITCHEN_SESSION" ]]; then
  unset GHOSTTY_RESOURCES_DIR GHOSTTY_BIN_DIR GHOSTTY_SHELL_FEATURES \
        GHOST_COMPLETE_ACTIVE TERM_PROGRAM TERM_PROGRAM_VERSION
fi
# <<< claude-code-kitchen: non-human shell guard <<<
