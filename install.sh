#!/usr/bin/env bash
# install.sh — link the kitchen's skills into your Claude Code skills directory.
#
#   ./install.sh                 install (symlinks; idempotent)
#   ./install.sh --dry-run       show what would happen, change nothing
#   ./install.sh --uninstall     remove only the symlinks that point into this repo
#   ./install.sh --target DIR    use DIR instead of ${CLAUDE_SKILLS_DIR:-~/.claude/skills}
#
# Safety rules:
#   - never deletes anything: an existing skill with the same name (directory, file, or a
#     symlink pointing somewhere else) is MOVED to <name>.bak-<timestamp> first;
#   - --uninstall removes only symlinks whose target is this repo, and prints how to
#     restore any backup it finds — it never restores or deletes backups by itself;
#   - does not touch your shell rc files; the shell guard is opt-in (see README).
#
# Works with bash 3.2+ (the macOS default).
set -euo pipefail

usage() {
  sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'
}

REPO_DIR=$(cd "$(dirname "$0")" && pwd -P)
SKILLS_SRC="$REPO_DIR/skills"
TARGET="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
DRY_RUN=0
UNINSTALL=0

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --uninstall) UNINSTALL=1 ;;
    --target)
      [ $# -ge 2 ] || { echo "error: --target needs a directory" >&2; exit 2; }
      TARGET="$2"
      shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "error: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

run() {
  # Print the action; execute it unless --dry-run.
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "[dry-run] $*"
  else
    "$@"
  fi
}

skill_names() {
  local dir
  for dir in "$SKILLS_SRC"/*/; do
    [ -f "${dir}SKILL.md" ] && basename "$dir"
  done
}

install_skills() {
  local stamp name src dest backup
  stamp=$(date +%Y%m%d%H%M%S)
  run mkdir -p "$TARGET"
  for name in $(skill_names); do
    src="$SKILLS_SRC/$name"
    dest="$TARGET/$name"
    if [ -L "$dest" ] && [ "$(readlink "$dest")" = "$src" ]; then
      echo "ok       $name (already linked)"
      continue
    fi
    if [ -e "$dest" ] || [ -L "$dest" ]; then
      backup="$dest.bak-$stamp"
      echo "backup   $name → $(basename "$backup") (an existing $name was in the way)"
      run mv "$dest" "$backup"
    fi
    echo "link     $name → $src"
    run ln -s "$src" "$dest"
  done
  cat <<EOF

Installed into $TARGET.
Next steps:
  1. In each repo you want to orchestrate, create .claude/orchestrator.md
     (start from $REPO_DIR/examples/adapter.md).
  2. Optional, recommended if your terminal injects integration variables:
     paste $REPO_DIR/shell/zshrc-guard.zsh at the top of your ~/.zshrc.
  3. Read the security section of the README before dispatching a kitchen session.
EOF
}

uninstall_skills() {
  local name src dest found=0
  for name in $(skill_names); do
    src="$SKILLS_SRC/$name"
    dest="$TARGET/$name"
    if [ -L "$dest" ] && [ "$(readlink "$dest")" = "$src" ]; then
      echo "remove   $name"
      run rm "$dest"
    elif [ -e "$dest" ] || [ -L "$dest" ]; then
      echo "skip     $name (not a link to this repo — left alone)"
    fi
  done
  for dest in "$TARGET"/*.bak-*; do
    [ -e "$dest" ] || [ -L "$dest" ] || continue
    if [ "$found" -eq 0 ]; then
      echo
      echo "Backups made by earlier installs (kept; restore any of them with mv):"
      found=1
    fi
    name=$(basename "$dest")
    echo "  mv \"$dest\" \"$TARGET/${name%%.bak-*}\""
  done
}

if [ ! -d "$SKILLS_SRC" ]; then
  echo "error: $SKILLS_SRC not found — run install.sh from a clone of the repo" >&2
  exit 1
fi

if [ "$UNINSTALL" -eq 1 ]; then
  uninstall_skills
else
  install_skills
fi
