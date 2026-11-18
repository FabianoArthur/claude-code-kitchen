#!/usr/bin/env python3
"""
end_session — end a unit's whole process tree, then its tmux session.

`tmux kill-session` only sends SIGHUP to the pane: a child that ignores it, or one that
moved itself into a new session (`setsid`, `start_new_session=True`), survives. This
script records the unit's root process at dispatch and, at the end, walks its descendants
and signals every distinct process group (SIGTERM, a grace period, then SIGKILL).

Safety: the registered pid is only trusted if its command name and start time still match
what was recorded. A recycled pid means the tree is someone else's: exit 2, nothing is
killed (the tmux session is still ended, it is named after the unit).

A double-forked orphan leaves the tree by ppid (launchd or init adopts it), so after the
kill a best-effort sweep looks for it by environment: every process of the same uid, started
at or after the registered start time, with exactly KITCHEN_UNIT=<ID> in its environment
(Linux: /proc/<pid>/environ; macOS: `ps -E`) gets SIGTERM, a grace period, then SIGKILL.
Each hit is logged as `sweep`. Never the script itself or its ancestors.

Known limit: a process started with `env -i` (or one that scrubbed KITCHEN_UNIT) carries no
mark and is not found.

Usage:
    python3 end_session.py register <ID> <PID>
    python3 end_session.py end <ID>
    python3 end_session.py --selftest

Environment (for tests): KITCHEN_LOGS_DIR (default ~/.claude/kitchen-logs),
KITCHEN_TMUX_SOCKET (tmux -L name; default: the default server).
Files: <logs>/<ID>.pid (the registration), <logs>/end-<ID>.log (what happened).
Exit codes: 0 done, 2 pid recycled, invalid id or path outside the logs dir, 64 usage.
"""
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time

PS = "/bin/ps"
PROC = "/proc"
GRACE_SECONDS = 5.0
EXIT_OK = 0
EXIT_REFUSED = 2
EXIT_USAGE = 64
ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
LSTART_RE = re.compile(r"^(\w{3}\s+\w{3}\s+\d+\s+\d\d:\d\d:\d\d\s+\d{4})\s+(.+)$")


def logs_dir():
    return os.environ.get("KITCHEN_LOGS_DIR") or os.path.expanduser("~/.claude/kitchen-logs")


def valid_id(unit_id):
    return bool(ID_RE.match(unit_id)) and unit_id not in (".", "..")


def inside(path, base):
    """True when the realpath of `path` is `base` or below it (both resolved)."""
    real_path, real_base = os.path.realpath(path), os.path.realpath(base)
    try:
        return os.path.commonpath([real_path, real_base]) == real_base
    except ValueError:
        return False


def unit_file(name):
    """Resolved path of `name` in the logs dir, or None if it would land outside it."""
    path = os.path.join(logs_dir(), name)
    return os.path.realpath(path) if inside(path, logs_dir()) else None


def refuse_paths(unit_id):
    """EXIT_REFUSED (after printing why) unless the id is valid and both files stay in the logs dir."""
    if not valid_id(unit_id):
        print(f"invalid unit id: {unit_id!r}")
        return EXIT_REFUSED
    for name in (f"{unit_id}.pid", f"end-{unit_id}.log"):
        if unit_file(name) is None:
            print(f"refused: {name} resolves outside the logs directory")
            return EXIT_REFUSED
    return None


def log(unit_id, msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    path = unit_file(f"end-{unit_id}.log") if valid_id(unit_id) else None
    if path:
        os.makedirs(logs_dir(), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    print(line)


def _ps(*args):
    env = dict(os.environ, LC_ALL="C")
    return subprocess.run([PS, *args], capture_output=True, text=True, env=env)


def proc_info(pid):
    """(comm, lstart) of a live pid, or None. lstart has its spaces normalised."""
    r = _ps("-o", "lstart=,comm=", "-p", str(int(pid)))
    m = LSTART_RE.match(r.stdout.strip()) if r.returncode == 0 else None
    if not m:
        return None
    return m.group(2).strip(), " ".join(m.group(1).split())


def process_table():
    """{pid: (ppid, pgid)} for every process."""
    table = {}
    for line in _ps("-A", "-o", "pid=,ppid=,pgid=").stdout.splitlines():
        parts = line.split()
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            table[int(parts[0])] = (int(parts[1]), int(parts[2]))
    return table


def descendants(root, table):
    """root plus every process reachable from it by ppid."""
    found, todo = {root}, [root]
    while todo:
        cur = todo.pop()
        for pid, (ppid, _pgid) in table.items():
            if ppid == cur and pid not in found:
                found.add(pid)
                todo.append(pid)
    return found


def _group_alive(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _signal_all(pgids, loose_pids, sig):
    for pgid in pgids:
        try:
            os.killpg(pgid, sig)
        except (ProcessLookupError, PermissionError):
            pass
    for pid in loose_pids:
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            pass


def kill_tree(root, grace=GRACE_SECONDS, _table=None):
    """SIGTERM, wait up to `grace` seconds, SIGKILL; returns (pgids, loose pids, sigkilled)."""
    table = _table if _table is not None else process_table()
    members = descendants(root, table)
    own = os.getpgrp()
    pgids, loose = set(), set()
    for pid in members:
        if pid not in table:
            continue
        pgid = table[pid][1]
        if pgid == own or pgid <= 1:
            loose.add(pid)  # never signal our own group: kill the member alone
        else:
            pgids.add(pgid)
    loose.discard(os.getpid())
    _signal_all(pgids, loose, signal.SIGTERM)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if not any(_group_alive(g) for g in pgids) and not any(_pid_alive(p) for p in loose):
            return sorted(pgids), sorted(loose), False
        time.sleep(0.1)
    _signal_all(pgids, loose, signal.SIGKILL)
    return sorted(pgids), sorted(loose), True


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _running(pid):
    """Alive and not a zombie."""
    r = _ps("-o", "stat=", "-p", str(int(pid)))
    stat = r.stdout.strip()
    return r.returncode == 0 and bool(stat) and not stat.startswith("Z")


def parse_lstart(text):
    """Epoch seconds of a `ps` lstart string (C locale), or None."""
    try:
        return time.mktime(time.strptime(" ".join(text.split()), "%a %b %d %H:%M:%S %Y"))
    except (ValueError, OverflowError):
        return None


def _ancestors(pid, table):
    found = set()
    while pid in table and table[pid][0] > 0 and table[pid][0] not in found:
        pid = table[pid][0]
        found.add(pid)
    return found


def _candidates_proc(unit_id):
    """[(pid, comm, lstart)] of own-uid processes with KITCHEN_UNIT=<id> in /proc/<pid>/environ."""
    needle = f"KITCHEN_UNIT={unit_id}".encode()
    hits = []
    try:
        names = os.listdir(PROC)
    except OSError:
        return hits
    for name in names:
        if not name.isdigit():
            continue
        try:
            if os.stat(os.path.join(PROC, name)).st_uid != os.getuid():
                continue
            with open(os.path.join(PROC, name, "environ"), "rb") as f:
                entries = f.read().split(b"\0")
        except OSError:
            continue  # gone or not readable: next pid
        if needle in entries:
            info = proc_info(int(name))
            if info:
                hits.append((int(name), info[0], info[1]))
    return hits


PS_ROW_RE = re.compile(r"^\s*(\d+)\s+(\w{3}\s+\w{3}\s+\d+\s+\d\d:\d\d:\d\d\s+\d{4})\s+(.*)$")


def _candidates_ps(unit_id):
    """Same as _candidates_proc through `ps -E`, which appends the environment to the command."""
    needle = f"KITCHEN_UNIT={unit_id}"
    hits = []
    r = _ps("-E", "-ww", "-U", str(os.getuid()), "-o", "pid=,lstart=,command=")
    for line in r.stdout.splitlines():
        m = PS_ROW_RE.match(line)
        if not m:
            continue
        tokens = m.group(3).split()
        if needle in tokens:  # whole token: KITCHEN_UNIT=<id>0 and X_KITCHEN_UNIT=<id> do not match
            hits.append((int(m.group(1)), os.path.basename(tokens[0]), " ".join(m.group(2).split())))
    return hits


def sweep(unit_id, since, grace=GRACE_SECONDS, backend=None):
    """Best effort: end leftover processes marked KITCHEN_UNIT=<id> that started at or after `since`.

    Returns the list of (pid, comm, lstart) found. Logs one `sweep` line per hit, none when empty.
    """
    if backend is None:
        backend = _candidates_proc if sys.platform.startswith("linux") else _candidates_ps
    try:
        table = process_table()
        skip = {os.getpid()} | _ancestors(os.getpid(), table)
        found = []
        for pid, comm, lstart in backend(unit_id):
            started = parse_lstart(lstart)
            if pid in skip or started is None or started < since:
                continue
            found.append((pid, comm, lstart))
    except Exception as e:  # best effort: never break the end of a unit
        log(unit_id, f"sweep: skipped ({type(e).__name__})")
        return []
    if not found:
        return []
    pids = [f[0] for f in found]
    _signal_all([], pids, signal.SIGTERM)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline and any(_running(p) for p in pids):
        time.sleep(0.1)
    forced = {p for p in pids if _running(p)}
    _signal_all([], forced, signal.SIGKILL)
    for pid, comm, lstart in found:
        log(unit_id, f"sweep: pid={pid} comm={comm} lstart={lstart} sigkill={'yes' if pid in forced else 'no'}")
    return found


def kill_tmux(unit_id):
    cmd = ["tmux"]
    if os.environ.get("KITCHEN_TMUX_SOCKET"):
        cmd += ["-L", os.environ["KITCHEN_TMUX_SOCKET"]]
    cmd += ["kill-session", "-t", f"=kitchen-{unit_id}"]
    try:
        return subprocess.run(cmd, capture_output=True).returncode
    except FileNotFoundError:
        return None


def register(unit_id, pid):
    refused = refuse_paths(unit_id)
    if refused is not None:
        return refused
    info = proc_info(pid)
    if not info:
        log(unit_id, f"register: pid {pid} does not exist")
        return 1
    os.makedirs(logs_dir(), exist_ok=True)
    with open(unit_file(f"{unit_id}.pid"), "w", encoding="utf-8") as f:
        json.dump({"pid": int(pid), "comm": info[0], "lstart": info[1]}, f)
    log(unit_id, f"registered pid={pid} comm={info[0]} lstart={info[1]}")
    return EXIT_OK


def end(unit_id, grace=GRACE_SECONDS):
    refused = refuse_paths(unit_id)
    if refused is not None:
        return refused
    path = unit_file(f"{unit_id}.pid")
    rc = EXIT_OK
    try:
        with open(path, encoding="utf-8") as f:
            reg = json.load(f)
        reg_pid = int(reg["pid"])
    except (OSError, ValueError, KeyError, TypeError):
        log(unit_id, "end: no valid registration; no process tree to kill")
        reg = None
    if reg:
        info = proc_info(reg_pid)
        if info is None:
            log(unit_id, f"pid {reg_pid} is gone; root exited (orphans are not touched: the root cannot be verified)")
        elif info != (reg.get("comm"), reg.get("lstart")):
            log(unit_id, f"pid {reg_pid} was recycled (now {info[0]} started {info[1]}; "
                         f"registered {reg.get('comm')} {reg.get('lstart')}): NOT killing")
            rc = EXIT_REFUSED
        else:
            pgids, loose, forced = kill_tree(reg_pid, grace)
            log(unit_id, f"killed tree of pid {reg_pid}: pgids={pgids} loose={loose} "
                         f"sigkill={'yes' if forced else 'no'}")
        if rc == EXIT_OK:
            since = parse_lstart(reg.get("lstart") or "")
            if since is not None:
                sweep(unit_id, since, grace)
            try:
                os.remove(path)
            except OSError:
                pass
    tmux_rc = kill_tmux(unit_id)
    log(unit_id, f"tmux kill-session =kitchen-{unit_id} -> rc={tmux_rc}")
    return rc


def selftest():
    ok = True
    with tempfile.TemporaryDirectory() as td:
        os.environ["KITCHEN_LOGS_DIR"] = td
        child = subprocess.Popen(["sleep", "60"], start_new_session=True)
        threading.Thread(target=child.wait, daemon=True).start()  # reap: no zombie
        try:
            checks = [
                ("proc_info sees the child", proc_info(child.pid) is not None),
                ("register ok", register("st-1", child.pid) == EXIT_OK),
                ("registration file written", os.path.isfile(os.path.join(td, "st-1.pid"))),
                ("bad id refused", end("../x") == EXIT_REFUSED),
                ("end ok", end("st-1", grace=2) == EXIT_OK),
            ]
            time.sleep(0.5)
            checks.append(("child died", child.poll() is not None))
            checks.append(("end log written", os.path.isfile(os.path.join(td, "end-st-1.log"))))
            for label, good in checks:
                print(f"  {'✓' if good else '✗'} {label}")
                ok &= good
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
    print("SELFTEST OK" if ok else "SELFTEST FAILED")
    return 0 if ok else 1


def main(argv):
    if argv[:1] == ["--selftest"]:
        return selftest()
    if len(argv) == 3 and argv[0] == "register" and argv[2].isdigit():
        return register(argv[1], argv[2])
    if len(argv) == 2 and argv[0] == "end":
        return end(argv[1])
    print(__doc__)
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
