#!/usr/bin/env bash
# fetch_pantry.sh — download the read-only "pantry" the cookbook points to.
#
#   bash cookbook/fetch_pantry.sh            # from anywhere; works on macOS/Linux and Git Bash
#
# Result (git-ignored, never versioned):
#   cookbook/pantry/ecc        ECC (affaan-m/ECC, MIT), shallow, pinned to ECC_COMMIT (d2ef268)
#   cookbook/pantry/work-cli   work-cli (TrussInt/work-cli, private): only if `gh` has access
#
# Every CLAUDE.md in the pantry is renamed to CLAUDE.ref.md so Claude Code never loads
# pantry text as instructions. Nothing from the pantry is executed.
set -euo pipefail

ECC_URL="https://github.com/affaan-m/ECC.git"
ECC_COMMIT="d2ef2680594f9a17526a6e1a2e18b3d242c5d17b"          # v2.2.3; the indexes in this folder were built from this commit
WORKCLI_REPO="TrussInt/work-cli"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PANTRY="${PANTRY_DIR:-$HERE/pantry}"
mkdir -p "$PANTRY"

neutralize() {  # rename CLAUDE.md -> CLAUDE.ref.md under $1
  find "$1" -name CLAUDE.md -not -path '*/.git/*' | while IFS= read -r f; do
    mv "$f" "$(dirname "$f")/CLAUDE.ref.md"
  done
}

# --- ECC -------------------------------------------------------------------
if [ -d "$PANTRY/ecc/.git" ]; then
  echo "ecc: already present in $PANTRY/ecc (delete it to fetch again)"
else
  rm -rf "$PANTRY/ecc"
  git init -q "$PANTRY/ecc"
  git -C "$PANTRY/ecc" remote add origin "$ECC_URL"
  git -C "$PANTRY/ecc" fetch -q --depth 1 origin "$ECC_COMMIT"
  git -C "$PANTRY/ecc" -c advice.detachedHead=false checkout -q FETCH_HEAD
  echo "ecc: fetched $(git -C "$PANTRY/ecc" rev-parse --short HEAD)"
fi
neutralize "$PANTRY/ecc"

# --- work-cli (optional; private repo) ---------------------------------------
if [ -d "$PANTRY/work-cli/.git" ]; then
  echo "work-cli: already present in $PANTRY/work-cli"
  neutralize "$PANTRY/work-cli"
elif command -v gh >/dev/null 2>&1 && gh repo view "$WORKCLI_REPO" >/dev/null 2>&1; then
  rm -rf "$PANTRY/work-cli"
  gh repo clone "$WORKCLI_REPO" "$PANTRY/work-cli" -- -q --depth 1
  neutralize "$PANTRY/work-cli"
  echo "work-cli: fetched"
else
  echo "work-cli: skipped (private repo; needs gh logged in with access to $WORKCLI_REPO). The cookbook still works without it." >&2
fi

echo "pantry ready in $PANTRY"
