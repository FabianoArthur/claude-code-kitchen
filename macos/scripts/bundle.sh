#!/bin/sh
# Builds Kitchen.app from the Swift package: release binary + Info.plist + the kitchen script,
# signed ad hoc. Usage: scripts/bundle.sh [output-dir]   (default: macos/build)
set -eu

here=$(cd "$(dirname "$0")/.." && pwd)
out=${1:-"$here/build"}
app="$out/Kitchen.app"

swift build --package-path "$here" -c release --product Kitchen
bin=$(swift build --package-path "$here" -c release --show-bin-path)

rm -rf "$app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
cp "$bin/Kitchen" "$app/Contents/MacOS/Kitchen"
cp "$here/Info.plist" "$app/Contents/Info.plist"
# The app runs its own copy of the script, so it keeps working if the clone moves.
cp "$here/../menubar/kitchen.30s.py" "$app/Contents/Resources/kitchen.py"
plutil -lint -s "$app/Contents/Info.plist"
codesign --force --sign - --timestamp=none "$app"
codesign --verify --strict "$app"
echo "$app"
