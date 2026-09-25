#!/usr/bin/env python3
"""
qa_watcher — deterministic watch over a QA run dispatched to tmux (zero tokens).

Same reason as the orchestrate watcher: the waiter must not burn context polling tmux,
and one python process is safe from shell hooks. A live session ≠ working; the fine signal
is the manifest — this script only watches the COARSE signals and returns a mechanical
verdict.

Signals, in order:
  - `<worktree>/.kitchen/done` exists              → run closed (hibernatable)   → exit 0
  - tmux session '=kitchen-qa-<slug>' dead, no done → probable crash              → exit 2
  - `--max-minutes` elapsed with the session alive  → nothing concluded, report   → exit 3

Usage:
    python3 qa_watcher.py <worktree> <slug> [--interval S] [--max-minutes M] [--socket NAME]
    python3 qa_watcher.py --selftest

Run it in the background and act on the exit code; never poll by hand.
"""
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def session_alive(slug, socket=None):
    cmd = ["tmux"] + (["-L", socket] if socket else []) + [
        "has-session", "-t", f"=kitchen-qa-{slug}"]
    try:
        return subprocess.run(cmd, capture_output=True).returncode == 0
    except FileNotFoundError:
        return False


def watch(worktree, slug, interval=30, max_minutes=120, socket=None,
          _alive=None, _sleep=time.sleep):
    alive = _alive or (lambda s: session_alive(s, socket))
    done = Path(worktree) / ".kitchen" / "done"
    deadline = time.monotonic() + max_minutes * 60
    while True:
        if done.is_file():
            print(f"done: run qa-{slug} closed (session id in {done})")
            return 0
        if not alive(slug):
            print(f"session kitchen-qa-{slug} DEAD without .kitchen/done — probable crash; "
                  "inspect .qa/cases.tsv (a filled `result` = real progress) and recreate it")
            return 2
        if time.monotonic() >= deadline:
            print(f"timeout {max_minutes}min with the session alive — attach and look: "
                  f"tmux attach -t '=kitchen-qa-{slug}'")
            return 3
        _sleep(interval)


def selftest():
    ok = True
    with tempfile.TemporaryDirectory() as td:
        wt = Path(td)
        (wt / ".kitchen").mkdir()
        (wt / ".kitchen" / "done").write_text("sess-123\n")
        ok &= watch(wt, "x", _alive=lambda s: True, _sleep=lambda s: None) == 0
        (wt / ".kitchen" / "done").unlink()
        ok &= watch(wt, "x", _alive=lambda s: False, _sleep=lambda s: None) == 2
        ok &= watch(wt, "x", max_minutes=0, _alive=lambda s: True, _sleep=lambda s: None) == 3
    print("SELFTEST: " + ("OK" if ok else "FAILED"))
    return 0 if ok else 1


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    if args[0] == "--selftest":
        return selftest()
    if len(args) < 2:
        print(__doc__)
        return 1
    worktree, slug = args[0], args[1]
    interval, max_minutes, socket = 30, 120, None
    rest = args[2:]
    while rest:
        if rest[0] == "--interval" and len(rest) > 1:
            interval = int(rest[1])
        elif rest[0] == "--max-minutes" and len(rest) > 1:
            max_minutes = int(rest[1])
        elif rest[0] == "--socket" and len(rest) > 1:
            socket = rest[1]
        else:
            print(f"unknown flag {rest[0]}")
            return 1
        rest = rest[2:]
    return watch(worktree, slug, interval, max_minutes, socket)


if __name__ == "__main__":
    sys.exit(main())
