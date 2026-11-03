#!/bin/sh
# Captures docs/images/macos-app-{light,dark}.png from the app's --demo window (made-up data
# over its own backdrop, so nothing real can appear). Needs a logged-in GUI session and, for
# the terminal running it, the Screen Recording permission.
# Usage: scripts/screenshots.sh path/to/Kitchen.app output-dir
set -eu

app=$1
out=$2
mkdir -p "$out"
bin="$app/Contents/MacOS/Kitchen"

for mode in light dark; do
    fifo=$(mktemp -u)
    mkfifo "$fifo"
    "$bin" --demo "$mode" >"$fifo" &
    pid=$!
    read -r window <"$fifo"
    rm -f "$fifo"
    sleep 2   # let the glass settle
    screencapture -x -o -l "$window" "$out/macos-app-$mode.png"
    kill "$pid"
    wait "$pid" 2>/dev/null || true
    echo "$out/macos-app-$mode.png"
done
