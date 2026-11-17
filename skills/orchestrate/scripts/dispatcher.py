#!/usr/bin/env python3
"""dispatcher.py — deterministic batch dispatcher for the kitchen (zero tokens).

usage:
  dispatcher.py <queue.tsv> --max N [--prefix kitchen-] [--interval 15] [--socket NAME]
                [--limit-file PATH]
  dispatcher.py limit get|set N|reset [--queue queue.tsv] [--max N] [--prefix kitchen-]
                [--socket NAME] [--limit-file PATH]
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

--max is the ceiling. The live limit lives in --limit-file (default `.kitchen-limit` next to
the queue) and is re-read on every pass, so it changes without a restart: a missing, invalid
or out-of-range (not 1..max) file means `--max` applies. Lowering it never kills a running
session; it only stops new starts until the count falls below the limit. Every `<prefix>*`
session counts toward it, `kitchen-proof-*` and `kitchen-inspect-*` included.
`limit get` shows the limit, where it came from, how many sessions run and how many wait.

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
LIMIT_FILE = ".kitchen-limit"
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


def effective_limit(limit_file, cap):
    """Return (limit, origin). The file wins only when it holds an integer in 1..cap."""
    if limit_file:
        try:
            with open(limit_file, encoding="utf-8") as handle:
                text = handle.read().strip()
        except OSError:
            return cap, "--max (no limit file)"
        if re.fullmatch(r"[0-9]{1,6}", text) and 1 <= int(text) <= cap:
            return int(text), "limit file"
        return cap, f"--max (limit file ignored: {text[:20]!r} is not 1..{cap})"
    return cap, "--max"


def start_ready(tmux, pending, launched, prefix, limit_file, cap):
    """Start queued units while the live session count is below the current limit."""
    limit, _ = effective_limit(limit_file, cap)
    while pending and len(tmux.sessions(prefix)) < limit:
        unit_id, worktree = pending.pop(0)
        if launch(tmux, unit_id, worktree, prefix):
            launched.append((unit_id, worktree))
    return limit


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


def run(queue_path, max_parallel, prefix, interval, socket=None, limit_file=None):
    tmux = Tmux(socket)
    limit_file = limit_file or default_limit_file(queue_path)
    pending = read_queue(queue_path)
    launched = []
    print(f"[dispatcher] {len(pending)} queued · cap {max_parallel} · prefix {prefix}", flush=True)
    last = None
    while True:
        reap(tmux, launched, prefix)
        limit, origin = effective_limit(limit_file, max_parallel)
        if limit != last:
            print(f"[dispatcher] limit {limit} ({origin})", flush=True)
            last = limit
        start_ready(tmux, pending, launched, prefix, limit_file, max_parallel)
        if not pending and not any(tmux.alive(prefix + u) for u, _ in launched):
            print("[dispatcher] queue empty, none of my sessions alive — done", flush=True)
            return 0
        time.sleep(interval)


def default_limit_file(queue_path=None):
    base = os.path.dirname(os.path.abspath(queue_path)) if queue_path else os.getcwd()
    return os.path.join(base, LIMIT_FILE)


def waiting_units(queue_path, tmux, prefix):
    """Queued units with no live session and no `.kitchen/done` yet."""
    live = set(tmux.sessions(prefix))
    return [u for u, w in read_queue(queue_path)
            if prefix + u not in live and not os.path.exists(os.path.join(w, DONE))]


def limit_command(action, value, limit_file, cap, prefix, tmux, queue_path=None):
    """`limit get|set N|reset`. Returns an exit code and prints a short report."""
    if action == "set":
        if value is None or not re.fullmatch(r"[0-9]{1,6}", value) or not 1 <= int(value) <= cap:
            print(f"limit set: expected an integer in 1..{cap}", file=sys.stderr)
            return 2
        tmp = limit_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(f"{int(value)}\n")
        os.replace(tmp, limit_file)
    elif action == "reset":
        try:
            os.remove(limit_file)
        except FileNotFoundError:
            pass
    elif action != "get":
        print("usage: dispatcher.py limit get|set N|reset", file=sys.stderr)
        return 2
    limit, origin = effective_limit(limit_file, cap)
    running = len(tmux.sessions(prefix))
    waiting = str(len(waiting_units(queue_path, tmux, prefix))) if queue_path else "unknown (no --queue)"
    print(f"limit: {limit}\norigin: {origin}\nrunning: {running}\nwaiting: {waiting}")
    return 0


def expect(condition, label):
    print(f"  [{'ok' if condition else 'FAILED'}] {label}")
    return bool(condition)


def selftest():
    """Real batch on a PRIVATE tmux socket: cap 2, then the live limit drops to 1 mid-run."""
    socket = f"kitchentest-dispatcher-{os.getpid()}"
    tmux = Tmux(socket)
    prefix = "kt-"
    base = tempfile.mkdtemp(prefix="kitchen-dispatcher-selftest-")
    plan = [("u1", 999), ("u2", 999), ("u3", 3), ("u4", 2)]
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
    limit_file = os.path.join(base, LIMIT_FILE)

    def finish(unit_id):
        with open(os.path.join(base, unit_id, DONE), "w") as handle:
            handle.write("selftest\n")

    def wait_for(test, seconds=20):
        end = time.time() + seconds
        while time.time() < end:
            if test():
                return True
            time.sleep(0.2)
        return False

    proc = subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), queue_path, "--max", "2",
         "--prefix", prefix, "--interval", "1", "--socket", socket],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    peak_before = peak_after = 0
    started_early = False
    try:
        two_up = wait_for(lambda: len(tmux.sessions(prefix)) == 2)
        peak_before = len(tmux.sessions(prefix))
        # Drop the limit to 1 while 2 sessions are running, then free one slot.
        limit_command("set", "1", limit_file, 2, prefix, tmux, queue_path)
        finish("u1")
        u1_gone = wait_for(lambda: not tmux.alive(f"{prefix}u1"))
        # u2 still holds the only allowed slot: u3 must NOT start, even over several passes.
        end = time.time() + 3.5
        while time.time() < end:
            live = tmux.sessions(prefix)
            peak_after = max(peak_after, len(live))
            started_early |= f"{prefix}u3" in live
            time.sleep(0.2)
        finish("u2")
        seen = set()
        end = time.time() + 40
        while time.time() < end and proc.poll() is None:
            live = tmux.sessions(prefix)
            seen.update(live)
            peak_after = max(peak_after, len(live))
            time.sleep(0.2)
    finally:
        exited = proc.poll() is not None
        if not exited:
            proc.kill()
        output = proc.stdout.read() if proc.stdout else ""
        tmux.run("kill-server")

    ok = True
    ok &= expect(two_up and peak_before == 2, f"cap 2 filled both slots (observed {peak_before})")
    ok &= expect(u1_gone, "session with .kitchen/done was killed (hibernation)")
    ok &= expect(not started_early, "limit 2 -> 1 mid-run: no new session while 1 is still running")
    ok &= expect(peak_after <= 1, f"never above the new limit after the switch (peak: {peak_after})")
    ok &= expect({f"{prefix}u3", f"{prefix}u4"} <= seen, f"queued units ran at limit 1 ({sorted(seen)})")
    ok &= expect("limit 1 (limit file)" in output, "log recorded the new limit")
    ok &= expect("hibernated" in output, "log recorded the hibernation")
    ok &= expect(exited and proc.returncode == 0, "dispatcher exited by itself with rc=0")
    print("SELFTEST OK" if ok else "SELFTEST FAILED")
    if not ok:
        print(output)
    return 0 if ok else 1


def option(argv, flag, default=None):
    return argv[argv.index(flag) + 1] if flag in argv else default


def main(argv):
    if "--selftest" in argv:
        return selftest()
    if not argv or argv[0].startswith("-"):
        print(__doc__)
        return 2
    cap = int(option(argv, "--max", "4"))
    prefix = option(argv, "--prefix", "kitchen-")
    socket = option(argv, "--socket")
    if argv[0] == "limit":
        rest = [a for a in argv[1:] if not a.startswith("-")]
        flagged = {option(argv, f) for f in ("--max", "--prefix", "--socket", "--queue", "--limit-file")}
        positional = [a for a in rest if a not in flagged]
        if not positional:
            print("usage: dispatcher.py limit get|set N|reset", file=sys.stderr)
            return 2
        queue_path = option(argv, "--queue")
        limit_file = option(argv, "--limit-file") or default_limit_file(queue_path)
        return limit_command(positional[0], positional[1] if len(positional) > 1 else None,
                             limit_file, cap, prefix, Tmux(socket), queue_path)
    return run(argv[0], cap, prefix, float(option(argv, "--interval", "15")), socket,
               option(argv, "--limit-file"))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
