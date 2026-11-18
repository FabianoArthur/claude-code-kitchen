#!/usr/bin/env python3
"""
guard — the PreToolUse hook that fences the kitchen's units.

It only acts inside a kitchen session, so installing it never touches the waiter's own session.
A session is kitchen when `KITCHEN_SESSION=1`, or, without the variable, when the hook event's
`cwd` is inside the worktree of a unit snapshot (or under `~/.claude/kitchen-runs/`): a child
process that wiped the environment does not switch the guard off. Everywhere else it exits 0
without writing a log (outside the variable case it reads stdin only to look at the `cwd`).
The unit id (`KITCHEN_UNIT`) is trusted only when that cwd is inside the unit's own worktree;
otherwise the strictest case applies (see guard_rules.py).

Input: the hook JSON on stdin (`tool_name`, `tool_input`). Output: exit 0 (allow) or exit 2 (deny,
reason on stderr). One jsonl line per call goes to `guard.jsonl`:
`{ts, unit, tool, rule, decision, mode, detail}`. The log is safe to keep: secrets are masked, every
text field is cut at 200 characters, and Write/Edit calls record only the path and the size, never
the content. The first write of a new day renames the previous file to `guard-YYYY-MM-DD.jsonl`.

Modes (`"mode"` in `~/.claude/kitchen-guard.json`):
  log                 never blocks; a rule that would block is logged as `would_deny`
  deny-irreversible   blocks the rules marked `irreversible`, logs the rest as `would_deny` (default)
  deny                blocks every rule
A missing, unreadable or invalid config means `deny-irreversible`.

Fail-closed: inside the kitchen, unreadable input or ANY exception (including one raised by a
rule) exits 2. This guards against mistakes; it is not a sandbox against a hostile unit.

Environment: KITCHEN_SESSION, KITCHEN_UNIT; KITCHEN_GUARD_CONFIG and KITCHEN_LOG_DIR override the
default paths (`~/.claude/kitchen-guard.json`, `~/.claude/kitchen-logs/`).

Usage:
    python3 guard.py < event.json
    python3 guard.py report [--days 7] [--log-dir DIR] [--json]
    python3 guard.py --selftest

`report` is the deterministic half of the guard analyst (brigade/guard-analyst.md): it counts the
log by rule and decision over the last N days and lists a few real cases per rule. It only reads.
"""
import argparse
import datetime
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))  # also under `python -I`
import guard_rules  # noqa: E402

MODES = ("log", "deny-irreversible", "deny")
DEFAULT_MODE = "deny-irreversible"
FIELD_LIMIT = 200
CONTENT_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
_CONTENT_KEYS = ("content", "old_string", "new_string", "new_source")
_SECRET = re.compile(
    r"(gh[pousr]_\w{10,}|sk-[\w-]{10,}|xox[abprs]-[\w-]{10,}|AKIA[0-9A-Z]{12,}"
    r"|Bearer\s+[\w.~+/=-]{8,})"
    r"|((?:token|password|passwd|secret|api[_-]?key)\s*[=:]\s*)\S+",
    re.IGNORECASE,
)


def now() -> float:
    """The clock; tests replace it."""
    return time.time()


def _mask(text: str) -> str:
    text = _SECRET.sub(lambda m: (m.group(2) + "***") if m.group(2) else "***", text)
    return text[:FIELD_LIMIT]


def _size(tool_input: dict) -> int:
    """Bytes of content a file tool carries (the content itself is never logged)."""
    total = 0
    for key in _CONTENT_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str):
            total += len(value.encode("utf-8"))
    edits = tool_input.get("edits")
    if isinstance(edits, list):
        total += sum(_size(edit) for edit in edits if isinstance(edit, dict))
    return total


def summarize(tool: str, tool_input: dict) -> str:
    """What the log may say about a call: the command, or for file tools only path and size."""
    if tool in CONTENT_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        suffix = f" ({_size(tool_input)} bytes)"
        return _mask(str(path))[: FIELD_LIMIT - len(suffix)] + suffix  # the size always survives the cut
    return str(tool_input.get("command", ""))


def _rotate(directory: str, stamp: float) -> None:
    """Move a log last written on an earlier day to guard-YYYY-MM-DD.jsonl."""
    current = os.path.join(directory, "guard.jsonl")
    try:
        last = time.strftime("%Y-%m-%d", time.localtime(os.stat(current).st_mtime))
    except OSError:
        return
    if last >= time.strftime("%Y-%m-%d", time.localtime(stamp)):
        return
    target = os.path.join(directory, f"guard-{last}.jsonl")
    if os.path.exists(target):  # never overwrite a day already rotated: append instead
        with open(current, "rb") as src, open(target, "ab") as dst:
            dst.write(src.read())
        os.remove(current)
    else:
        os.replace(current, target)


def _home_claude(env) -> str:
    return os.path.join(env.get("HOME") or os.path.expanduser("~"), ".claude")


def load_config(env) -> dict:
    """The user's config, or {} when it is absent or unreadable."""
    path = env.get("KITCHEN_GUARD_CONFIG") or os.path.join(_home_claude(env), "kitchen-guard.json")
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def resolve_mode(config: dict) -> str:
    mode = config.get("mode")
    return mode if mode in MODES else DEFAULT_MODE


def write_log(env, mode: str, tool: str, rule: str, decision: str, detail: str = "") -> None:
    """Append one jsonl line. A log failure never changes the decision."""
    try:
        directory = env.get("KITCHEN_LOG_DIR") or os.path.join(_home_claude(env), "kitchen-logs")
        os.makedirs(directory, mode=0o700, exist_ok=True)
        stamp = now()
        _rotate(directory, stamp)
        line = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(stamp)),
            "unit": _mask(env.get("KITCHEN_UNIT", "")),
            "tool": _mask(tool),
            "rule": rule[:FIELD_LIMIT],
            "decision": decision,
            "mode": mode,
            "detail": _mask(detail),
        }
        with open(os.path.join(directory, "guard.jsonl"), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError:
        pass


def evaluate(event: dict, config: dict, env=None):
    """Returns (rule_name, irreversible, reason) of the first matching rule, or None.

    Rules also see the process context under the reserved config keys `_env` (the environment
    mapping) and `_cwd` (the `cwd` of the hook event); a user config cannot set them.
    """
    tool = event.get("tool_name")
    tool_input = event.get("tool_input")
    if not isinstance(tool, str) or not isinstance(tool_input, dict):
        raise ValueError("event has no tool_name/tool_input")
    config = {**config, "_env": dict(os.environ if env is None else env), "_cwd": event.get("cwd")}
    for rule in guard_rules.RULES:
        if tool in rule.tools:
            reason = rule.check(tool, tool_input, config)
            if reason:
                return rule.name, rule.irreversible, reason
    return None


def main(env=None, stdin=None, stderr=None) -> int:
    env = os.environ if env is None else env
    stdin = sys.stdin if stdin is None else stdin
    stderr = sys.stderr if stderr is None else stderr
    mode, tool = DEFAULT_MODE, ""
    preloaded = None
    if env.get("KITCHEN_SESSION") != "1":
        try:  # no variable: kitchen only if the event's cwd is inside a unit's worktree
            preloaded = json.load(stdin)
            if not isinstance(preloaded, dict) or not guard_rules.cwd_in_kitchen(env, preloaded.get("cwd")):
                return 0
        except Exception:
            return 0  # nothing says this is the kitchen: stay out of the waiter's way
    try:
        config = load_config(env)
        mode = resolve_mode(config)
        try:
            event = preloaded if preloaded is not None else json.load(stdin)
            if not isinstance(event, dict):
                raise ValueError("event is not an object")
        except ValueError as exc:
            write_log(env, mode, tool, "bad-input", "deny", str(exc))
            print(f"guard: bad-input: unreadable event ({exc}); blocked (fail-closed)", file=stderr)
            return 2
        tool = str(event.get("tool_name", ""))
        hit = evaluate(event, config, env)
        if hit is None:
            write_log(env, mode, tool, "", "allow", summarize(tool, event["tool_input"]))
            return 0
        rule, irreversible, reason = hit
        blocks = mode == "deny" or (mode == "deny-irreversible" and irreversible)
        detail = summarize(tool, event["tool_input"])
        if blocks:
            write_log(env, mode, tool, rule, "deny", detail)
            print(f"guard: {rule}: {reason}. Ask the human.", file=stderr)
            return 2
        write_log(env, mode, tool, rule, "would_deny", detail)
        return 0
    except Exception as exc:  # fail-closed: inside the kitchen an error blocks
        write_log(env, mode, tool, "internal-error", "deny", f"{type(exc).__name__}: {exc}")
        print(f"guard: internal-error: {type(exc).__name__}: {exc}; blocked (fail-closed)", file=stderr)
        return 2


REPORT_SAMPLES = 3
_LOG_NAME = re.compile(r"^guard(-\d{4}-\d{2}-\d{2})?\.jsonl$")
_SAMPLED = ("deny", "would_deny")


def _parse_ts(value):
    """Epoch seconds of a log timestamp, or None when it is missing or malformed."""
    try:
        return datetime.datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%S%z").timestamp()
    except ValueError:
        return None


def build_report(directory: str, days: int, stamp: float) -> dict:
    """Count the log lines of the last `days` days by rule and decision.

    Reads `guard.jsonl` and every `guard-YYYY-MM-DD.jsonl` in `directory`. A line that is not
    valid JSON, not an object, or has no usable `ts` is counted under `skipped`, never raised.
    Each rule keeps up to REPORT_SAMPLES `deny` / `would_deny` cases with file and line number.
    """
    cutoff = stamp - days * 86400
    report = {"days": days, "files": [], "lines": 0, "skipped": 0, "decisions": {}, "rules": {}}
    try:
        names = sorted(n for n in os.listdir(directory) if _LOG_NAME.match(n))
    except OSError:
        return report
    for name in names:
        report["files"].append(name)
        try:
            handle = open(os.path.join(directory, name), encoding="utf-8", errors="replace")
        except OSError:
            continue
        with handle:
            for number, raw in enumerate(handle, 1):
                if not raw.strip():
                    continue
                try:
                    line = json.loads(raw)
                except ValueError:
                    line = None
                when = _parse_ts(line.get("ts")) if isinstance(line, dict) else None
                if when is None:
                    report["skipped"] += 1
                    continue
                if when < cutoff:
                    continue
                report["lines"] += 1
                rule = str(line.get("rule") or "(none)")
                decision = str(line.get("decision") or "(none)")
                report["decisions"][decision] = report["decisions"].get(decision, 0) + 1
                entry = report["rules"].setdefault(rule, {"counts": {}, "samples": []})
                entry["counts"][decision] = entry["counts"].get(decision, 0) + 1
                if decision in _SAMPLED and len(entry["samples"]) < REPORT_SAMPLES:
                    entry["samples"].append(
                        {
                            "file": name,
                            "line": number,
                            "ts": line.get("ts"),
                            "unit": str(line.get("unit", "")),
                            "tool": str(line.get("tool", "")),
                            "decision": decision,
                            "detail": str(line.get("detail", ""))[:FIELD_LIMIT],
                        }
                    )
    return report


def format_report(report: dict) -> str:
    out = [
        f"guard report: last {report['days']} days, {report['lines']} decisions "
        f"in {len(report['files'])} file(s), {report['skipped']} line(s) skipped",
        "decisions: " + (", ".join(f"{k}={v}" for k, v in sorted(report["decisions"].items())) or "none"),
        "",
    ]
    ranked = sorted(report["rules"].items(), key=lambda kv: (-sum(kv[1]["counts"].values()), kv[0]))
    for rule, entry in ranked:
        counts = ", ".join(f"{k}={v}" for k, v in sorted(entry["counts"].items()))
        out.append(f"{rule}: {counts}")
        for case in entry["samples"]:
            out.append(
                f"  - {case['file']}:{case['line']} {case['decision']} unit={case['unit']} "
                f"{case['tool']}: {case['detail']}"
            )
    return "\n".join(out) + "\n"


def report_main(argv, env=None, out=None) -> int:
    env = os.environ if env is None else env
    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(prog="guard.py report", description="Count guard decisions by rule.")
    parser.add_argument("--days", type=int, default=7, help="window in days (default 7)")
    parser.add_argument("--log-dir", help="log folder (default: KITCHEN_LOG_DIR or ~/.claude/kitchen-logs)")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    args = parser.parse_args(argv)
    if args.days < 1:
        parser.error("--days must be at least 1")
    directory = args.log_dir or env.get("KITCHEN_LOG_DIR") or os.path.join(_home_claude(env), "kitchen-logs")
    report = build_report(directory, args.days, now())
    out.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n" if args.json else format_report(report))
    return 0


def selftest() -> int:
    import io
    import subprocess
    import tempfile

    failures = []

    def check(label, ok):
        print(("ok   " if ok else "FAIL ") + label)
        if not ok:
            failures.append(label)

    with tempfile.TemporaryDirectory() as tmp:
        env = {
            "PATH": os.environ.get("PATH", ""),
            "KITCHEN_SESSION": "1",
            "KITCHEN_UNIT": "SELFTEST",
            "KITCHEN_GUARD_CONFIG": os.path.join(tmp, "none.json"),
            "KITCHEN_LOG_DIR": os.path.join(tmp, "logs"),
        }
        script = os.path.realpath(__file__)
        if os.name == "nt":  # Windows needs these to start Python at all
            env.update({k: os.environ[k] for k in ("SYSTEMROOT", "TEMP", "TMP") if k in os.environ})

        def bash_event(command):
            return json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})

        def call(command):
            event = bash_event(command)
            start = time.perf_counter()
            done = subprocess.run(
                [sys.executable, "-I", script], input=event, env=env, text=True, capture_output=True
            )
            return done.returncode, (time.perf_counter() - start) * 1000

        check("blocks a push to main", call("git push origin main")[0] == 2)
        check("allows git status", call("git status")[0] == 0)
        times = sorted(call("git status")[1] for _ in range(50))
        p95 = times[int(len(times) * 0.95) - 1]
        # Process start-up on Windows is slow and says nothing about the guard: only gate on POSIX.
        label = f"hook process p95 {p95:.0f} ms < 150 ms over 50 calls"
        check(label, p95 < 150 if os.name != "nt" else True)
        in_process = []
        for _ in range(50):
            start = time.perf_counter()
            code = main(env=env, stdin=io.StringIO(bash_event("git status")), stderr=io.StringIO())
            in_process.append((time.perf_counter() - start) * 1000)
            if code != 0:
                failures.append("in-process call failed")
        in_process.sort()
        p95_local = in_process[int(len(in_process) * 0.95) - 1]
        check(f"in-process p95 {p95_local:.1f} ms < 150 ms over 50 calls", p95_local < 150)
        with open(os.path.join(tmp, "logs", "guard.jsonl"), encoding="utf-8") as handle:
            lines = [json.loads(line) for line in handle]
        required = {"ts", "unit", "tool", "rule", "decision", "mode"}
        check("jsonl lines carry the required fields", all(required <= set(line) for line in lines))
        secret = "ghp_" + "a1B2c3D4e5F6g7H8i9J0"
        main(env=env, stdin=io.StringIO(bash_event(f"git push origin main {secret}")), stderr=io.StringIO())
        write = json.dumps({"tool_name": "Write", "tool_input": {"file_path": "/tmp/x", "content": "BODY"}})
        main(env=env, stdin=io.StringIO(write), stderr=io.StringIO())
        with open(os.path.join(tmp, "logs", "guard.jsonl"), encoding="utf-8") as handle:
            text = handle.read()
        check("a token is masked in the log", secret not in text)
        check("Write logs path and size, not content", "BODY" not in text and "/tmp/x (4 bytes)" in text)
        fixture = os.path.join(tmp, "fixture")
        os.makedirs(fixture)
        stamp = now()

        def row(days_ago, rule, decision):
            ts = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(stamp - days_ago * 86400))
            return json.dumps({"ts": ts, "unit": "U", "tool": "Bash", "rule": rule, "decision": decision})

        rows = [row(1, "push", "deny"), row(1, "push", "deny"), row(1, "", "allow"), "{broken", row(30, "push", "deny")]
        with open(os.path.join(fixture, "guard.jsonl"), "w", encoding="utf-8") as handle:
            handle.write("\n".join(rows) + "\n")
        result = build_report(fixture, 7, stamp)
        check("report counts by rule and decision", result["rules"]["push"]["counts"] == {"deny": 2})
        check("report skips old and broken lines", result["lines"] == 3 and result["skipped"] == 1)
    print("\nselftest:", "FAILED" if failures else "ALL PASSED")
    return 1 if failures else 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["report"]:
        sys.exit(report_main(sys.argv[2:]))
    if "--selftest" in sys.argv[1:]:
        sys.exit(selftest())
    sys.exit(main())
