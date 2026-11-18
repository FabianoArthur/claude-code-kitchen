#!/usr/bin/env bash
# install.sh — install third-party skills (archify, ponytail) pinned to a reviewed commit.
#
#   bash skills/third-party/install.sh                  install every skill in pins.tsv
#   bash skills/third-party/install.sh --dry-run        show the plan, download and change nothing
#   bash skills/third-party/install.sh --only NAME      only archify or ponytail
#   bash skills/third-party/install.sh --target DIR     use DIR instead of ${CLAUDE_SKILLS_DIR:-~/.claude/skills}
#   bash skills/third-party/install.sh --yes            do not ask before backing up a same-named skill
#   bash skills/third-party/install.sh --pins FILE      use another pins file (tests)
#
# How it works:
#   - pins.tsv lists name, repository, tag, full commit SHA and the skill folder;
#   - each repository is fetched shallow (that one commit only) into a temporary directory,
#     and `git rev-parse HEAD` must equal the pinned SHA, otherwise nothing is installed;
#   - only the skill folder is copied (never hooks/, commands/, plugins or settings.json);
#   - an existing skill with the same name is MOVED to <name>.bak-<timestamp> (after you confirm
#     or pass --yes), never deleted. Nothing from the downloads is executed.
#
# Works with bash 3.2+ (the macOS default).
set -euo pipefail

usage() {
  sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'
}

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PINS="$HERE/pins.tsv"
TARGET="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
DRY_RUN=0
ASSUME_YES=0
ONLY=""

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    -y|--yes) ASSUME_YES=1 ;;
    --only)
      [ $# -ge 2 ] || { echo "error: --only needs a skill name" >&2; exit 2; }
      ONLY="$2"; shift ;;
    --target)
      [ $# -ge 2 ] || { echo "error: --target needs a directory" >&2; exit 2; }
      TARGET="$2"; shift ;;
    --pins)
      [ $# -ge 2 ] || { echo "error: --pins needs a file" >&2; exit 2; }
      PINS="$2"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "error: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

[ -f "$PINS" ] || { echo "error: pins file not found: $PINS" >&2; exit 2; }

# Selected pin lines: "name<TAB>url<TAB>tag<TAB>sha<TAB>path".
selected() {
  local name url tag sha path
  while IFS=$'\t' read -r name url tag sha path; do
    case "$name" in ''|'#'*) continue ;; esac
    if [ -n "$ONLY" ] && [ "$name" != "$ONLY" ]; then continue; fi
    printf '%s\t%s\t%s\t%s\t%s\n' "$name" "$url" "$tag" "$sha" "$path"
  done < "$PINS"
}

PLAN="$(selected)"
if [ -z "$PLAN" ]; then
  echo "error: no skill selected${ONLY:+ (unknown name: $ONLY)}" >&2
  exit 2
fi

# Validate every line before touching anything.
while IFS=$'\t' read -r name url tag sha path; do
  if [ -z "$url" ] || [ -z "$path" ]; then
    echo "error: malformed line for '$name' in $PINS" >&2; exit 2
  fi
  case "$sha" in
    *[!0-9a-f]*|'') echo "error: $name: the pin must be a full lowercase commit SHA" >&2; exit 2 ;;
  esac
  [ "${#sha}" -eq 40 ] || { echo "error: $name: the pin must be a full 40-character SHA" >&2; exit 2; }
  case "$name$path" in
    *..*|/*) echo "error: $name: unsafe name or path" >&2; exit 2 ;;
  esac
done <<EOF_PLAN
$PLAN
EOF_PLAN

if [ "$DRY_RUN" -eq 1 ]; then
  while IFS=$'\t' read -r name url tag sha path; do
    echo "[dry-run] $name: fetch $url @ $tag (${sha:0:7}), copy $path/ -> $TARGET/$name"
    if [ -e "$TARGET/$name" ] || [ -L "$TARGET/$name" ]; then
      echo "[dry-run] $name: already exists, would be moved to $name.bak-<timestamp>"
    fi
  done <<EOF_PLAN
$PLAN
EOF_PLAN
  exit 0
fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/third-party-skills.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

# --- 1. download and verify everything first, so a failure installs nothing ----
while IFS=$'\t' read -r name url tag sha path; do
  repo="$WORK/$name.repo"
  git init -q "$repo"
  git -C "$repo" remote add origin "$url"
  if ! git -C "$repo" fetch -q --depth 1 origin "$sha" 2>/dev/null; then
    echo "error: $name: could not fetch commit $sha from $url — refusing" >&2
    exit 1
  fi
  git -C "$repo" -c advice.detachedHead=false checkout -q FETCH_HEAD
  got="$(git -C "$repo" rev-parse HEAD)"
  if [ "$got" != "$sha" ]; then
    echo "error: $name: commit mismatch (pinned $sha, got $got) — refusing" >&2
    exit 1
  fi
  if [ ! -f "$repo/$path/SKILL.md" ]; then
    echo "error: $name: no $path/SKILL.md at $sha — refusing" >&2
    exit 1
  fi
  # Copy only the skill folder; hooks, commands and git data never come along.
  mkdir -p "$WORK/$name.out"
  tar -C "$repo/$path" -cf - --exclude=hooks --exclude=commands --exclude=.git . \
    | tar -C "$WORK/$name.out" -xf -
  echo "verified $name $tag ($sha)"
done <<EOF_PLAN
$PLAN
EOF_PLAN

# --- 2. back up same-named skills (never delete) --------------------------------
found=""
while IFS=$'\t' read -r name _; do
  if [ -e "$TARGET/$name" ] || [ -L "$TARGET/$name" ]; then found="$found $name"; fi
done <<EOF_PLAN
$PLAN
EOF_PLAN

if [ -n "$found" ] && [ "$ASSUME_YES" -ne 1 ]; then
  echo "These skills already exist in $TARGET and would be moved to <name>.bak-<timestamp>:" >&2
  for n in $found; do echo "  $n" >&2; done
  if [ -t 0 ]; then
    printf 'Back them up and continue? [y/N] ' >&2
    read -r answer || answer=""
    case "$answer" in
      y|Y|yes|YES) ;;
      *) echo "aborted: nothing was changed" >&2; exit 3 ;;
    esac
  else
    echo "error: no terminal to ask — nothing was changed. Rerun with --yes to back them up," >&2
    echo "       or use --target DIR to install somewhere else." >&2
    exit 3
  fi
fi

# --- 3. install ----------------------------------------------------------------------
stamp="$(date +%Y%m%d%H%M%S)"
mkdir -p -- "$TARGET"
while IFS=$'\t' read -r name _; do
  dest="$TARGET/$name"
  if [ -e "$dest" ] || [ -L "$dest" ]; then
    backup="$dest.bak-$stamp"
    i=1
    while [ -e "$backup" ] || [ -L "$backup" ]; do
      backup="$dest.bak-$stamp-$i"
      i=$((i + 1))
    done
    mv -- "$dest" "$backup"
    echo "backup   $name -> $(basename "$backup")"
  fi
  mkdir -p -- "$dest"
  (cd "$WORK/$name.out" && tar -cf - .) | (cd "$dest" && tar -xf -)
  echo "installed $name -> $dest"
done <<EOF_PLAN
$PLAN
EOF_PLAN
