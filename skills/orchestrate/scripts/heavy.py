#!/usr/bin/env python3
"""
heavy — a slot limiter for heavy commands (builds, test suites, simulators).

Usage:
    python3 heavy.py [--timeout 15m] [--wait 20m] -- <command...>
    python3 heavy.py status
    python3 heavy.py --selftest

Slots: the limit N is read from `<dir>/heavy-limit` on every attempt (default 2, so a
fanless laptop is not asked to run more than two heavy jobs at once). The lock is
`fcntl.flock(LOCK_EX | LOCK_NB)` on `<dir>/slot-N`; the kernel releases it when the holder
dies, so a crashed wrapper never leaves a stale slot. `<dir>` is `KITCHEN_HEAVY_DIR`
(default `~/.claude/kitchen-heavy`).

The command runs in its own session (process group). On timeout the whole group, including
grandchildren, gets SIGTERM, then SIGKILL after 5 s. SIGTERM, SIGHUP and SIGINT sent to the
wrapper are forwarded the same way. The wrapper does not wait for a slot forever: with no
free slot within `--wait` it exits 75.

Known limitation: macOS has no equivalent of a Windows job object with kill-on-close.
SIGKILL on the wrapper itself cannot be handled, so the command's group is left running
and its slot is released (the lock dies with the wrapper). The pgid is recorded in the slot
file, so it can be killed by hand. When the command exits, anything it left behind in its
group is killed too.

Exit: the command's own code (128+N if killed by signal N) · 124 = timeout ·
75 = no free slot in time · 2 = usage error
"""
import argparse
import fcntl
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEFAULT_LIMIT = 2
MAX_LIMIT = 64
KILL_GRACE = 5.0
EXIT_TIMEOUT = 124
EXIT_NO_SLOT = 75


class Stop(Exception):
    """Raised from a signal handler to interrupt the wait on the child."""

    def __init__(self, signum):
        super().__init__(signum)
        self.signum = signum


def heavy_dir():
    raw = os.environ.get("KITCHEN_HEAVY_DIR") or "~/.claude/kitchen-heavy"
    return Path(os.path.expanduser(raw))


def parse_duration(text):
    text = str(text).strip().lower()
    mult = {"s": 1, "m": 60, "h": 3600}
    if text and text[-1] in mult:
        return float(text[:-1]) * mult[text[-1]]
    return float(text)


def read_limit(base=None):
    """Re-read on every call; anything missing or invalid falls back to the default."""
    base = base or heavy_dir()
    try:
        n = int((base / "heavy-limit").read_text().strip())
    except (OSError, ValueError):
        return DEFAULT_LIMIT
    return n if 1 <= n <= MAX_LIMIT else DEFAULT_LIMIT


def slot_path(base, i):
    return base / f"slot-{i}"


def try_slot(base=None):
    """Return (fd, index) holding the lock of the first free slot, or None."""
    base = base or heavy_dir()
    base.mkdir(parents=True, exist_ok=True)
    for i in range(1, read_limit(base) + 1):
        fd = os.open(slot_path(base, i), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd, i
        except OSError:
            os.close(fd)
    return None


def note(fd, cmd, pgid):
    """Write `start|wrapper pid|pgid|command` into the slot file (the lock stays held)."""
    line = " ".join(cmd).replace("\n", " ").replace("|", "/")
    text = f"{time.strftime('%Y-%m-%dT%H:%M:%S')}|{os.getpid()}|{pgid}|{line}\n"
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, text.encode("utf-8", "replace"))


def group_alive(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def kill_group(pgid, proc=None, grace=KILL_GRACE):
    """SIGTERM the group, wait up to `grace` seconds, then SIGKILL what is left.

    `proc` is the group leader's Popen: it is polled so a dead leader is reaped and does
    not keep the group looking alive as a zombie."""
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    end = time.monotonic() + grace
    while time.monotonic() < end:
        if proc is not None:
            proc.poll()
        if not group_alive(pgid):
            return
        time.sleep(0.05)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def exit_code(returncode):
    return 128 - returncode if returncode < 0 else returncode


def run(cmd, timeout, fd=None):
    """Run `cmd` in a new process group. Returns the exit code to hand back."""

    def on_signal(signum, _frame):
        raise Stop(signum)

    old = {s: signal.signal(s, on_signal) for s in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)}
    try:
        try:
            proc = subprocess.Popen(cmd, start_new_session=True)
        except OSError as e:
            print(f"heavy: cannot run {cmd[0]}: {e}", file=sys.stderr)
            return 127
        pgid = proc.pid  # a session leader's pgid is its own pid
        if fd is not None:
            note(fd, cmd, pgid)
        try:
            rc = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_group(pgid, proc)
            proc.wait()
            return EXIT_TIMEOUT
        except Stop:
            for s in old:  # a second signal must not interrupt the cleanup
                signal.signal(s, signal.SIG_IGN)
            kill_group(pgid, proc)
            return exit_code(proc.wait())
        # The command is gone; sweep anything it left behind in its group.
        kill_group(pgid, proc, grace=0)
        return exit_code(rc)
    finally:
        for s, h in old.items():
            signal.signal(s, h)


def read_slot(base, i):
    """Return None if slot i is free, else the (started, pid, pgid, command) strings."""
    path = slot_path(base, i)
    if not path.exists():
        return None
    fd = os.open(path, os.O_RDWR)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
            return None
        except OSError:
            pass
        os.lseek(fd, 0, os.SEEK_SET)
        info = os.read(fd, 4096).decode("utf-8", "replace").strip()
    finally:
        os.close(fd)
    parts = (info.split("|", 3) + ["?"] * 4)[:4]
    return tuple(p or "?" for p in parts)


def status(base=None, out=None):
    base = base or heavy_dir()
    out = out or sys.stdout
    found = False
    indexes = []
    for p in base.glob("slot-*") if base.is_dir() else []:
        suffix = p.name[len("slot-"):]
        if suffix.isdigit():
            indexes.append(int(suffix))
    for i in sorted(indexes):
        info = read_slot(base, i)
        if info is None:
            continue
        started, pid, pgid, cmd = info
        print(f"slot-{i}: busy since {started} pid={pid} pgid={pgid} cmd={cmd}", file=out)
        found = True
    if not found:
        print(f"no slot busy (limit {read_limit(base)})", file=out)
    return 0


def acquire(wait):
    end = time.monotonic() + wait
    while True:
        got = try_slot()
        if got:
            return got
        left = end - time.monotonic()
        if left <= 0:
            return None
        time.sleep(min(0.5, max(0.05, left)))


def selftest():
    saved = os.environ.get("KITCHEN_HEAVY_DIR")
    tmp = Path(tempfile.mkdtemp(prefix="heavy-"))
    os.environ["KITCHEN_HEAVY_DIR"] = str(tmp)
    held = []
    try:
        assert read_limit(tmp) == DEFAULT_LIMIT
        (tmp / "heavy-limit").write_text("1\n")
        assert read_limit(tmp) == 1
        (tmp / "heavy-limit").write_text("junk\n")
        assert read_limit(tmp) == DEFAULT_LIMIT
        (tmp / "heavy-limit").write_text("1\n")
        first = try_slot(tmp)
        assert first and first[1] == 1
        held.append(first[0])
        assert try_slot(tmp) is None, "limit 1 must refuse a second slot"
        (tmp / "heavy-limit").write_text("2\n")
        second = try_slot(tmp)
        assert second and second[1] == 2, "limit is re-read on every attempt"
        held.append(second[0])
        note(first[0], ["echo", "hi"], 123)
        info = read_slot(tmp, 1)
        assert info and info[1] == str(os.getpid()) and info[2] == "123" and info[3] == "echo hi"
        assert run([sys.executable, "-c", "import sys; sys.exit(7)"], 30) == 7
        assert run([sys.executable, "-c", "import time; time.sleep(30)"], 0.3) == EXIT_TIMEOUT
        assert exit_code(-15) == 143
    finally:
        for fd in held:
            os.close(fd)
        if saved is None:
            os.environ.pop("KITCHEN_HEAVY_DIR", None)
        else:
            os.environ["KITCHEN_HEAVY_DIR"] = saved
        for p in tmp.glob("*"):
            p.unlink()
        tmp.rmdir()
    print("selftest ok")
    return 0


def main(argv):
    if argv[:1] == ["--selftest"]:
        return selftest()
    if argv[:1] == ["status"]:
        return status()
    if "--" not in argv:
        print(__doc__.strip().split("\n\n")[1], file=sys.stderr)
        return 2
    k = argv.index("--")
    parser = argparse.ArgumentParser(prog="heavy.py", add_help=False)
    parser.add_argument("--timeout", default="15m")
    parser.add_argument("--wait", default="20m")
    try:
        args = parser.parse_args(argv[:k])
        timeout, wait = parse_duration(args.timeout), parse_duration(args.wait)
    except (SystemExit, ValueError):
        return 2
    cmd = argv[k + 1:]
    if not cmd:
        return 2
    got = acquire(wait)
    if got is None:
        print("heavy: no free slot within --wait", file=sys.stderr)
        return EXIT_NO_SLOT
    fd, _ = got
    try:
        return run(cmd, timeout, fd)
    finally:
        os.close(fd)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
