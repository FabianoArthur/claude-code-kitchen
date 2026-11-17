#!/usr/bin/env python3
"""kitchen_session.py — start a taster or inspector session without shell strings (zero tokens).

A taster (`proof`) or inspector (`inspect`) review runs in its own tmux session,
`kitchen-<kind>-<ID>`, separate from the unit's session. Nothing here goes through a shell: tmux
receives an argv list, the prompt travels by stdin, and the reviewer's answer is read from the
`result` field of Claude's JSON output only.

usage:
  kitchen_session.py start --kind proof|inspect --unit ID --prompt-file FILE --model MODEL
                     --claude PATH [--add-dir DIR]... [--max N] [--limit-file PATH]
                     [--prefix kitchen-] [--socket NAME] [--runs-dir DIR]
  kitchen_session.py wait KIND ID [--timeout SECONDS] [--socket NAME] [--prefix kitchen-]
                     [--runs-dir DIR]
  kitchen_session.py --selftest

start   creates the run folder `<runs-dir>/<kind>-<ID>/` (mode 0700), copies the prompt into it
        (mode 0600) and starts the tmux session. It refuses to start when no slot is free: the
        count is every live `<prefix>*` session (the dispatcher's rule) against the live limit
        (`--limit-file`, same file and rules as dispatcher.py, capped by `--max`).
        The session runs `kitchen_session.py _run`, which calls Claude with a minimal
        environment (PATH, HOME, TMPDIR, LANG plus KITCHEN_*), cwd in the run folder, the given
        `--add-dir` folders readable, project settings off, and the prompt on stdin. The verdict
        is `result` from the JSON output, stored in `verdict.json` (mode 0600); a missing or
        non-string `result` is stored as null. The script never reads the worktree and never
        captures the pane.
wait    prints the verdict JSON, or `null` when none arrives within --timeout (default 600) or
        the session ended without writing one. Exit 0 with a verdict, 1 with null.

Environment (for tests): KITCHEN_RUNS_DIR (default ~/.claude/kitchen-runs).
Exit codes: 0 ok, 1 no verdict, 2 bad usage or id, 3 no free slot, 4 session already running,
5 could not start tmux.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dispatcher  # noqa: E402  (same folder; stdlib only)

KINDS = ("proof", "inspect")
TOOLS = "Bash Read Glob Grep"  # reviewers read and run checks; they never edit
DENIED_TOOLS = "Edit Write NotebookEdit"
MAX_VERDICT = 200_000
SAFE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
EXIT_NO_SLOT = 3
EXIT_RUNNING = 4
EXIT_TMUX = 5


def runs_root(override=None):
    raw = override or os.environ.get("KITCHEN_RUNS_DIR") or "~/.claude/kitchen-runs"
    return os.path.abspath(os.path.expanduser(raw))


def run_dir(kind, unit, override=None):
    return os.path.join(runs_root(override), f"{kind}-{unit}")


def session_name(prefix, kind, unit):
    return f"{prefix}{kind}-{unit}"


def check_ids(kind, unit):
    if kind not in KINDS:
        print(f"invalid kind {kind!r} (allowed: {', '.join(KINDS)})", file=sys.stderr)
        raise SystemExit(2)
    if not dispatcher.SAFE_ID.match(unit) or ".." in unit:
        print(f"invalid unit id {unit!r} (allowed: letters, digits, . _ -)", file=sys.stderr)
        raise SystemExit(2)


def minimal_env(kind, unit, rundir, claude):
    """The only environment Claude gets: no tokens, no PYTHONPATH, no inherited extras."""
    path = os.path.dirname(os.path.abspath(claude)) + os.pathsep + SAFE_PATH
    env = {
        "PATH": path,
        "HOME": os.path.expanduser("~"),
        "TMPDIR": tempfile.gettempdir(),
        "LANG": os.environ.get("LANG", "en_US.UTF-8"),
        "KITCHEN_SESSION": "1",
        "KITCHEN_UNIT": unit,
        "KITCHEN_KIND": kind,
        "KITCHEN_RUN_DIR": rundir,
    }
    return env


def claude_argv(claude, model, add_dirs):
    argv = [claude, "-p", "--model", model, "--output-format", "json",
            "--permission-mode", "default", "--strict-mcp-config",
            "--setting-sources", "user", "--disable-slash-commands",
            "--tools", TOOLS, "--allowedTools", TOOLS, "--disallowedTools", DENIED_TOOLS]
    for directory in add_dirs:
        argv += ["--add-dir", directory]
    return argv


def extract_result(text):
    """Return the `result` string of Claude's JSON output, or None. Nothing else is trusted."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if isinstance(data, list):  # some versions print the event list; take the last result event
        data = next((e for e in reversed(data) if isinstance(e, dict) and e.get("type") == "result"), None)
    if not isinstance(data, dict):
        return None
    result = data.get("result")
    if not isinstance(result, str) or not result.strip():
        return None
    return result[:MAX_VERDICT]


def write_private(path, data):
    """Write bytes with mode 0600 from the first byte (no window with default permissions)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    os.chmod(path, 0o600)


def verdict_path(rundir):
    return os.path.join(rundir, "verdict.json")


def read_verdict(rundir):
    try:
        with open(verdict_path(rundir), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("result"), str) else None


def cmd_run(args):
    """Body of the tmux session: call Claude, store output.json, rc and verdict.json."""
    rundir = args.run_dir
    with open(os.path.join(rundir, "prompt.md"), "rb") as handle:
        prompt = handle.read()
    argv = claude_argv(args.claude, args.model, args.add_dir or [])
    env = minimal_env(args.kind, args.unit, rundir, args.claude)
    try:
        done = subprocess.run(argv, input=prompt, capture_output=True, cwd=rundir, env=env)
        code, out, err = done.returncode, done.stdout, done.stderr
    except OSError as exc:
        code, out, err = 127, b"", str(exc).encode()
    write_private(os.path.join(rundir, "output.json"), out)
    write_private(os.path.join(rundir, "stderr.txt"), err[-20000:])
    result = extract_result(out.decode("utf-8", "replace")) if code == 0 else None
    payload = {"kind": args.kind, "unit": args.unit, "result": result, "exit": code,
               "finished": time.strftime("%Y-%m-%d %H:%M:%S")}
    write_private(os.path.join(rundir, "rc"), f"{code}\n".encode())
    if result is not None:
        write_private(verdict_path(rundir), json.dumps(payload).encode())
    return 0 if result is not None else 1


def cmd_start(args):
    check_ids(args.kind, args.unit)
    tmux = dispatcher.Tmux(args.socket)
    name = session_name(args.prefix, args.kind, args.unit)
    if tmux.alive(name):
        print(f"{name} is already running", file=sys.stderr)
        return EXIT_RUNNING
    limit, origin = dispatcher.effective_limit(args.limit_file, args.max)
    live = len(tmux.sessions(args.prefix))
    if live >= limit:
        print(f"no free slot: {live} running, limit {limit} ({origin})", file=sys.stderr)
        return EXIT_NO_SLOT
    with open(args.prompt_file, "rb") as handle:
        prompt = handle.read()
    rundir = run_dir(args.kind, args.unit, args.runs_dir)
    os.makedirs(rundir, mode=0o700, exist_ok=True)
    os.chmod(rundir, 0o700)
    for stale in ("verdict.json", "output.json", "stderr.txt", "rc"):
        try:
            os.remove(os.path.join(rundir, stale))
        except FileNotFoundError:
            pass
    write_private(os.path.join(rundir, "prompt.md"), prompt)
    argv = [sys.executable, "-I", os.path.abspath(__file__), "_run",
            "--kind", args.kind, "--unit", args.unit, "--run-dir", rundir,
            "--model", args.model, "--claude", os.path.abspath(args.claude)]
    for directory in args.add_dir or []:
        argv += ["--add-dir", os.path.abspath(directory)]
    result = tmux.run("new-session", "-d", "-s", name, "-c", rundir, *argv)
    if result.returncode != 0 or not tmux.alive(name):
        # A very short run may already be over; the verdict file tells that apart from a failure.
        if not os.path.exists(os.path.join(rundir, "rc")):
            print(f"could not start {name}: {result.stderr.strip()[:200]}", file=sys.stderr)
            return EXIT_TMUX
    print(f"started {name} (run folder: {rundir})")
    return 0


def cmd_wait(args):
    check_ids(args.kind, args.unit)
    tmux = dispatcher.Tmux(args.socket)
    name = session_name(args.prefix, args.kind, args.unit)
    rundir = run_dir(args.kind, args.unit, args.runs_dir)
    deadline = time.monotonic() + args.timeout
    while True:
        verdict = read_verdict(rundir)
        if verdict is not None:
            print(json.dumps(verdict))
            return 0
        if not tmux.alive(name):
            verdict = read_verdict(rundir)  # written between the two checks
            print(json.dumps(verdict) if verdict is not None else "null")
            return 0 if verdict is not None else 1
        if time.monotonic() >= deadline:
            print("null")
            return 1
        time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))


def build_parser():
    parser = argparse.ArgumentParser(prog="kitchen_session.py", description="taster/inspector sessions")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--prefix", default="kitchen-")
        p.add_argument("--socket")
        p.add_argument("--runs-dir")

    start = sub.add_parser("start")
    start.add_argument("--kind", required=True, choices=KINDS)
    start.add_argument("--unit", required=True)
    start.add_argument("--prompt-file", required=True)
    start.add_argument("--model", required=True)
    start.add_argument("--claude", required=True)
    start.add_argument("--add-dir", action="append")
    start.add_argument("--max", type=int, default=4)
    start.add_argument("--limit-file")
    common(start)
    wait = sub.add_parser("wait")
    wait.add_argument("kind", choices=KINDS)
    wait.add_argument("unit")
    wait.add_argument("--timeout", type=float, default=600)
    common(wait)
    run = sub.add_parser("_run")
    run.add_argument("--kind", required=True, choices=KINDS)
    run.add_argument("--unit", required=True)
    run.add_argument("--run-dir", required=True)
    run.add_argument("--model", required=True)
    run.add_argument("--claude", required=True)
    run.add_argument("--add-dir", action="append")
    return parser


def expect(condition, label):
    print(f"  [{'ok' if condition else 'FAILED'}] {label}")
    return bool(condition)


FAKE_CLAUDE = """#!{python}
import json, os, sys
prompt = sys.stdin.buffer.read()
with open("seen-stdin.bin", "wb") as f:
    f.write(prompt)
with open("seen-argv.json", "w") as f:
    json.dump(sys.argv[1:], f)
with open("seen-env.json", "w") as f:
    json.dump(dict(os.environ), f)
print(json.dumps({{"type": "result", "result": "SAFE: all good", "is_error": False}}))
"""


def selftest():
    ok = True
    ok &= expect(extract_result('{"type":"result","result":"SAFE"}') == "SAFE", "result is read from JSON")
    ok &= expect(extract_result("SAFE, not json") is None, "non-JSON gives null")
    ok &= expect(extract_result('{"result": 7}') is None, "non-string result gives null")
    ok &= expect(extract_result('{"other": "x"}') is None, "missing result gives null")
    env = minimal_env("proof", "U1", "/r", "/opt/claude/bin/claude")
    ok &= expect(set(env) == {"PATH", "HOME", "TMPDIR", "LANG", "KITCHEN_SESSION", "KITCHEN_UNIT",
                              "KITCHEN_KIND", "KITCHEN_RUN_DIR"}, "minimal environment keys")
    if os.name != "posix" or shutil.which("tmux") is None:
        print("  [skip] end-to-end run needs posix and tmux")
        return 0 if ok else 1
    base = tempfile.mkdtemp(prefix="kitchen-session-selftest-")
    socket = f"kitchentest-session-{os.getpid()}"
    claude = os.path.join(base, "claude")
    with open(claude, "w") as handle:
        handle.write(FAKE_CLAUDE.format(python=sys.executable))
    os.chmod(claude, 0o755)
    prompt = os.path.join(base, "prompt.txt")
    with open(prompt, "w") as handle:
        handle.write("check `touch y` and $(touch x) and it's fine\n")
    runs = os.path.join(base, "runs")
    common = ["--socket", socket, "--runs-dir", runs]
    try:
        start = [sys.executable, os.path.abspath(__file__), "start", "--kind", "proof", "--unit", "ST-1",
                 "--prompt-file", prompt, "--model", "m", "--claude", claude, "--max", "2",
                 "--add-dir", base] + common
        code = subprocess.run(start, capture_output=True, text=True).returncode
        ok &= expect(code == 0, "start succeeds")
        done = subprocess.run([sys.executable, os.path.abspath(__file__), "wait", "proof", "ST-1",
                               "--timeout", "20"] + common, capture_output=True, text=True)
        ok &= expect(done.returncode == 0 and '"SAFE: all good"' in done.stdout, "wait returns the verdict")
        rundir = run_dir("proof", "ST-1", runs)
        with open(os.path.join(rundir, "seen-stdin.bin"), "rb") as handle:
            seen = handle.read()
        with open(prompt, "rb") as handle:
            ok &= expect(seen == handle.read(), "prompt arrives whole on stdin")
        ok &= expect(not os.path.exists(os.path.join(rundir, "x")) and not os.path.exists(os.path.join(rundir, "y")),
                     "nothing in the prompt was executed")
    finally:
        subprocess.run(["tmux", "-L", socket, "kill-server"], capture_output=True)
        shutil.rmtree(base, ignore_errors=True)
    print("selftest ok" if ok else "selftest FAILED")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    args = build_parser().parse_args(argv)
    if args.command == "_run":
        return cmd_run(args)
    if args.command == "start":
        return cmd_start(args)
    return cmd_wait(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
