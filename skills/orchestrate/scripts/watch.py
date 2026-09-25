#!/usr/bin/env python3
"""
watch — deterministic watcher for ONE dispatched kitchen unit (zero tokens).

The waiter must not burn context polling tmux, and a compound shell loop is fragile (a
shell hook that rewrites utilities, or a mangled exit code, makes it exit early without
an event). One python process has nothing to rewrite. Run it in the background and act on
its exit code.

A live session does not mean working — the fine signal is the manifest row. This script
reads both, in this order, every iteration:

  <worktree>/.kitchen/done exists      → the unit closed (hibernatable)     exit 0
  manifest row of <id> says ✅          → PR recorded (died before `done`)   exit 0
  manifest row of <id> says 🚫          → aborted: report the reason         exit 5
  manifest row of <id> says ⏳          → waiting on a human: go tell them   exit 3
  tmux session <prefix><id> is dead    → crash/reboot: reconcile (CORE §7)  exit 2
  --max-minutes elapsed, session alive → nothing concluded: attach and look exit 6

The manifest must exist: a wrong path would make the ⏳/🚫 triggers blind in silence
(stderr of a background job is invisible), so a missing manifest is exit 4.

After exit 0, confirm the PR yourself (`<gh> pr view <branch> --json url,state,createdAt`)
and only trust a PR created AFTER the manifest's `dispatched:` time — branches are reused
across attempts. A failed `gh` call is INCONCLUSIVE, never "no PR yet".

Usage:
    python3 watch.py <worktree> <id> --manifest <path> [--interval 30]
                     [--max-minutes 240] [--prefix kitchen-] [--socket NAME]
    python3 watch.py --selftest
"""
import subprocess
import sys
import tempfile
import time
from pathlib import Path

EXIT_DONE = 0
EXIT_CRASH = 2
EXIT_WAITING = 3
EXIT_USAGE = 4
EXIT_ABORTED = 5
EXIT_TIMEOUT = 6


def session_alive(name, socket=None):
    cmd = ["tmux"] + (["-L", socket] if socket else []) + ["has-session", "-t", f"={name}"]
    try:
        return subprocess.run(cmd, capture_output=True).returncode == 0
    except FileNotFoundError:
        return False


def row_state(manifest_text, unit_id):
    """The state cell of the manifest row whose FIRST cell is exactly `unit_id`.

    Exact cell match on purpose: `task-2` must never read the row of `task-21`.
    Returns the whole row text after the id if there is no recognisable state column.
    """
    for line in manifest_text.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and cells[0] == unit_id:
            for cell in cells[1:]:
                if any(mark in cell for mark in ("⏸", "🔄", "⏳", "✅", "🚫")):
                    return cell
            return " | ".join(cells[1:])
    return None


def watch(worktree, unit_id, manifest, interval=30, max_minutes=240.0, prefix="kitchen-",
          socket=None, _alive=None, _sleep=time.sleep, log=print):
    alive_fn = _alive or (lambda name: session_alive(name, socket))
    name = prefix + unit_id
    done = Path(worktree) / ".kitchen" / "done"
    manifest = Path(manifest)
    deadline = time.monotonic() + max_minutes * 60
    while True:
        if not manifest.is_file():
            log(f"error: manifest {manifest} does not exist — the ⏳/🚫 triggers would be blind")
            return EXIT_USAGE
        state = row_state(manifest.read_text(encoding="utf-8"), unit_id) or ""
        is_done = done.is_file()
        is_alive = alive_fn(name)
        log(f"alive={is_alive} done={is_done} state={state or '(no row)'}")
        if is_done:
            log(f"done: {name} closed — session id in {done}; confirm the PR, then hibernate")
            return EXIT_DONE
        if "✅" in state:
            log(f"done: manifest marks ✅ for {unit_id} (no .kitchen/done — died before "
                "hibernating); confirm the PR")
            return EXIT_DONE
        if "🚫" in state:
            log(f"aborted: {state} — cleanup is the waiter's job (CORE §11)")
            return EXIT_ABORTED
        if "⏳" in state:
            log(f"waiting on human: {state} — attach with: tmux attach -t '={name}'. "
                "Once resolved, rewrite the row to 🔄 before watching again.")
            return EXIT_WAITING
        if not is_alive:
            log(f"crash: {name} is dead without .kitchen/done — reconcile (CORE §7): inspect "
                "`git status`/`log` in the worktree and rewrite .kitchen/prompt.md")
            return EXIT_CRASH
        if time.monotonic() >= deadline:
            log(f"timeout after {max_minutes} min with {name} alive — attach and look")
            return EXIT_TIMEOUT
        _sleep(interval)


def selftest():
    ok = True
    with tempfile.TemporaryDirectory() as td:
        wt = Path(td) / "wt"
        (wt / ".kitchen").mkdir(parents=True)
        m = Path(td) / "m.md"
        quiet = {"_sleep": lambda s: None, "log": lambda *a: None}

        def case(state, alive, expected, label, **kw):
            m.write_text(f"| unit | state |\n|---|---|\n| u-1 | {state} |\n", encoding="utf-8")
            got = watch(wt, "u-1", m, interval=0, _alive=lambda n: alive, **quiet, **kw)
            print(f"  {'✓' if got == expected else '✗'} {label} (expected {expected}, got {got})")
            return got == expected

        ok &= case("⏳ waiting on human", True, EXIT_WAITING, "⏳ → waiting")
        ok &= case("🚫 aborted", True, EXIT_ABORTED, "🚫 → aborted")
        ok &= case("✅ PR #1", False, EXIT_DONE, "✅ without done → done")
        ok &= case("🔄 running", False, EXIT_CRASH, "dead without done → crash")
        ok &= case("🔄 running", True, EXIT_TIMEOUT, "alive past deadline → timeout",
                   max_minutes=0.0)
        (wt / ".kitchen" / "done").write_text("sid\n")
        ok &= case("🔄 running", True, EXIT_DONE, "done file → done")
        got = watch(wt, "u-1", Path(td) / "missing.md", interval=0, **quiet)
        print(f"  {'✓' if got == EXIT_USAGE else '✗'} missing manifest → usage error")
        ok &= got == EXIT_USAGE
    print("SELFTEST OK" if ok else "SELFTEST FAILED")
    return 0 if ok else 1


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else EXIT_USAGE
    if argv[0] == "--selftest":
        return selftest()
    if len(argv) < 2 or argv[0].startswith("-") or "--manifest" not in argv:
        print(__doc__)
        return EXIT_USAGE
    worktree, unit_id = argv[0], argv[1]
    opts = {"--manifest": None, "--interval": "30", "--max-minutes": "240",
            "--prefix": "kitchen-", "--socket": None}
    rest = argv[2:]
    while rest:
        if rest[0] not in opts or len(rest) < 2:
            print(f"unknown or incomplete flag: {rest[0]}")
            return EXIT_USAGE
        opts[rest[0]] = rest[1]
        rest = rest[2:]
    return watch(worktree, unit_id, opts["--manifest"], interval=float(opts["--interval"]),
                 max_minutes=float(opts["--max-minutes"]), prefix=opts["--prefix"],
                 socket=opts["--socket"])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
