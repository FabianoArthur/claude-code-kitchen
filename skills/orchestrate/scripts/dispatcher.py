#!/usr/bin/env python3
"""dispatcher.py — deterministic batch dispatcher for the kitchen (zero tokens).

usage:
  dispatcher.py <queue.tsv> --max N [--prefix kitchen-] [--interval 15] [--socket NAME]
  dispatcher.py --selftest

queue.tsv: one unit per line, `id<TAB>worktree-path`. Blank lines and `#` comments are
ignored. Each worktree needs a `.kitchen/launch.sh` (written by /orchestrate) that starts
the detached tmux session `<prefix><id>`.

The dispatcher keeps at most N `<prefix>*` sessions alive, starts the next unit of the
queue when a slot frees, and kills any session whose worktree gained `.kitchen/done`
(hibernation: the conversation persists on disk and comes back with
`claude --resume <session-id>`). A unit paused waiting on a human does not write
`.kitchen/done` and holds its slot on purpose. It exits when the queue is empty and no
session it launched is still alive.

--socket NAME runs every tmux call against `tmux -L NAME` (and exports it to launch.sh as
KITCHEN_TMUX_SOCKET). Tests use it so they never touch your default tmux server.
"""
import os
import re
import subprocess
import sys
import tempfile
import time

DONE = os.path.join(".kitchen", "done")
LAUNCH = os.path.join(".kitchen", "launch.sh")
# The id becomes a tmux session name (`:`/`.` are target syntax there) and part of a
# worktree path: letters, digits, `.`, `_`, `-`; no leading `-` or `.`, never `..`.
SAFE_ID = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]*$")


class Tmux:
    """Thin wrapper so every call honours the optional private socket."""

    def __init__(self, socket=None):
        self.socket = socket

    def run(self, *args):
        base = ["tmux"] + (["-L", self.socket] if self.socket else [])
        return subprocess.run(base + list(args), capture_output=True, text=True)

    def sessions(self, prefix):
        result = self.run("list-sessions", "-F", "#{session_name}")
        if result.returncode != 0:
            return []
        names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return [n for n in names if n.startswith(prefix) and n != f"{prefix}dispatcher"]

    def alive(self, name):
        # `=` forces an exact match: without it tmux matches by prefix and
        # `kitchen-FE-2` would also see `kitchen-FE-21`.
        return self.run("has-session", "-t", f"={name}").returncode == 0

    def kill(self, name):
        return self.run("kill-session", "-t", f"={name}")


def read_queue(path):
    units = []
    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) != 2 or not parts[0] or not parts[1]:
                sys.exit(f"invalid queue line (expected id<TAB>worktree): {raw.rstrip()!r}")
            if not SAFE_ID.match(parts[0]) or ".." in parts[0]:
                sys.exit(f"invalid unit id {parts[0]!r} (allowed: letters, digits, . _ -)")
            units.append((parts[0], parts[1]))
    return units


def launch(tmux, unit_id, worktree, prefix):
    script = os.path.join(worktree, LAUNCH)
    name = prefix + unit_id
    if not os.path.isfile(script):
        print(f"[dispatcher] {unit_id}: no {script} — skipped", flush=True)
        return False
    env = dict(os.environ)
    if tmux.socket:
        env["KITCHEN_TMUX_SOCKET"] = tmux.socket
    result = subprocess.run(["sh", script], capture_output=True, text=True, cwd=worktree, env=env)
    if tmux.alive(name):
        print(f"[dispatcher] started {name}", flush=True)
        return True
    detail = (result.stderr or result.stdout).strip()[:200]
    print(f"[dispatcher] {unit_id}: launch.sh ran (rc={result.returncode}) but {name} "
          f"did not come up — {detail}", flush=True)
    return False


def reap(tmux, launched, prefix):
    for unit_id, worktree in launched:
        name = prefix + unit_id
        if os.path.exists(os.path.join(worktree, DONE)) and tmux.alive(name):
            tmux.kill(name)
            print(f"[dispatcher] hibernated {name} (.kitchen/done present; "
                  "claude --resume brings it back)", flush=True)


def run(queue_path, max_parallel, prefix, interval, socket=None):
    tmux = Tmux(socket)
    pending = read_queue(queue_path)
    launched = []
    print(f"[dispatcher] {len(pending)} queued · cap {max_parallel} · prefix {prefix}", flush=True)
    while True:
        reap(tmux, launched, prefix)
        while pending and len(tmux.sessions(prefix)) < max_parallel:
            unit_id, worktree = pending.pop(0)
            if launch(tmux, unit_id, worktree, prefix):
                launched.append((unit_id, worktree))
        if not pending and not any(tmux.alive(prefix + u) for u, _ in launched):
            print("[dispatcher] queue empty, none of my sessions alive — done", flush=True)
            return 0
        time.sleep(interval)


def expect(condition, label):
    print(f"  [{'ok' if condition else 'FAILED'}] {label}")
    return bool(condition)


def selftest():
    """Runs a real 4-unit batch with cap 2 on a PRIVATE tmux socket."""
    socket = f"kitchentest-dispatcher-{os.getpid()}"
    tmux = Tmux(socket)
    prefix = "kt-"
    base = tempfile.mkdtemp(prefix="kitchen-dispatcher-selftest-")
    plan = [("u1", 999), ("u2", 4), ("u3", 4), ("u4", 2)]
    lines = []
    for unit_id, seconds in plan:
        worktree = os.path.join(base, unit_id)
        os.makedirs(os.path.join(worktree, ".kitchen"))
        with open(os.path.join(worktree, LAUNCH), "w") as handle:
            handle.write("#!/bin/sh\n"
                         f"tmux -L \"$KITCHEN_TMUX_SOCKET\" new-session -d -s {prefix}{unit_id} "
                         f"'sleep {seconds}'\n")
        lines.append(f"{unit_id}\t{worktree}")
    queue_path = os.path.join(base, "queue.tsv")
    with open(queue_path, "w") as handle:
        handle.write("\n".join(lines) + "\n# ignored comment\n")

    proc = subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), queue_path, "--max", "2",
         "--prefix", prefix, "--interval", "1", "--socket", socket],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    peak, seen = 0, set()
    done_written = u1_dead_after_done = False
    deadline = time.time() + 60
    try:
        while time.time() < deadline:
            live = tmux.sessions(prefix)
            peak = max(peak, len(live))
            seen.update(live)
            if not done_written and f"{prefix}u1" in live and f"{prefix}u3" in seen:
                with open(os.path.join(base, "u1", DONE), "w") as handle:
                    handle.write("selftest\n")
                done_written = True
            if done_written and not tmux.alive(f"{prefix}u1"):
                u1_dead_after_done = True
            if proc.poll() is not None:
                break
            time.sleep(0.3)
    finally:
        exited = proc.poll() is not None
        if not exited:
            proc.kill()
        output = proc.stdout.read() if proc.stdout else ""
        tmux.run("kill-server")

    ok = True
    ok &= expect(exited and proc.returncode == 0, "dispatcher exited by itself with rc=0")
    ok &= expect(peak <= 2, f"never exceeded the cap (observed peak: {peak})")
    ok &= expect(seen == {f"{prefix}{u}" for u, _ in plan}, f"all 4 units started ({sorted(seen)})")
    ok &= expect(u1_dead_after_done, "session with .kitchen/done was killed (hibernation)")
    ok &= expect("hibernated" in output, "log recorded the hibernation")
    print("SELFTEST OK" if ok else "SELFTEST FAILED")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    if not argv or argv[0].startswith("-"):
        print(__doc__)
        return 2

    def value_of(flag, default):
        return argv[argv.index(flag) + 1] if flag in argv else default

    return run(argv[0], int(value_of("--max", "4")), value_of("--prefix", "kitchen-"),
               float(value_of("--interval", "15")), value_of("--socket", None))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
