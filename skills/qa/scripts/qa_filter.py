#!/usr/bin/env python3
"""
qa_filter — runs a test/probe command and returns ONLY what decides: failures + summary.

Why it exists: dumping jest/pytest/vitest/curl output into the context is the second
biggest token drain of agent QA — and a shell hook that rewrites utilities can mangle the
output of compound pipelines; a single python process is safe from that.

Mechanics: runs WITHOUT a shell (argument list), merges stdout+stderr, and prints:
  - up to N lines (default 10) matching a failure pattern (FAIL/ERROR/assert/✕/Traceback…),
    collapsing consecutive stack-trace lines;
  - the summary line(s) (`X passed`, `Tests:`, …);
  - `── exit=N · total=M lines · shown=K`.

Usage:
    python3 qa_filter.py [--lines N] [--timeout S] -- <cmd> [args...]
    python3 qa_filter.py --selftest

Exit code: the command's (a target failure is a signal, not a filter error); 124 on timeout.
"""
import os
import re
import subprocess
import sys
import tempfile

FAIL_RX = re.compile(
    r"(FAIL|FAILED|ERROR|✕|✗|×|AssertionError|Traceback|Error:|error TS\d+|"
    r"Expected|Received|assert|raise[d ]|HTTP/\d\.\d [45]\d\d|\b[45]\d\d )", re.I)
SUMMARY_RX = re.compile(
    r"(\d+ (passed|failed|passing|failing|errors?|tests?)|Tests?:|Suites?:|"
    r"\d+ deselected|=+ .*(passed|failed).* =+)", re.I)
NOISE_RX = re.compile(r"^\s*(at |File \"|\s*\||\s*\^)")


def filter_output(output, max_lines):
    lines = output.splitlines()
    fails, summary = [], []
    noise_run = 0
    for line in lines:
        if SUMMARY_RX.search(line):
            summary.append(line.strip())
            continue
        if FAIL_RX.search(line):
            if NOISE_RX.match(line):
                noise_run += 1
                if noise_run > 2:
                    continue
            else:
                noise_run = 0
            if len(fails) < max_lines:
                fails.append(line.rstrip()[:200])
    return fails, summary[-3:], len(lines)


def run(cmd, max_lines, timeout):
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        output = (proc.stdout or "") + (proc.stderr or "")
        code = proc.returncode
    except subprocess.TimeoutExpired as e:
        partial = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        output = partial + "\n[TIMEOUT]"
        code = 124
    except FileNotFoundError:
        print(f"command not found: {cmd[0]}")
        return 127
    fails, summary, total = filter_output(output, max_lines)
    for line in fails + summary:
        print(line)
    print(f"── exit={code} · total={total} lines · shown={len(fails) + len(summary)}")
    return code


def selftest():
    ok = True
    fake = ("import sys\n"
            "print('ok 1')\n"
            "print('✕ case 7 FAILED: AssertionError expected 3 got 4')\n"
            + "\n".join(f"print('noise line {i}')" for i in range(200)) + "\n"
            "print('Tests: 1 failed, 9 passed, 10 total')\n"
            "sys.exit(1)\n")
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(fake)
        path = f.name
    try:
        ok &= run([sys.executable, path], 10, 60) == 1
        fails, summary, total = filter_output("x\n" * 500 + "10 passed\n", 10)
        ok &= total == 501 and not fails and summary == ["10 passed"]
        ok &= run(["/nonexistent/qa-command"], 10, 5) == 127
    finally:
        os.unlink(path)
    print("SELFTEST: " + ("OK" if ok else "FAILED"))
    return 0 if ok else 1


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    if args[0] == "--selftest":
        return selftest()
    max_lines, timeout = 10, 300
    while args and args[0].startswith("--"):
        if args[0] == "--lines":
            max_lines = int(args[1])
            args = args[2:]
        elif args[0] == "--timeout":
            timeout = int(args[1])
            args = args[2:]
        elif args[0] == "--":
            args = args[1:]
            break
        else:
            print(f"unknown flag {args[0]}")
            return 1
    if not args:
        print("missing the command after --")
        return 1
    return run(args, max_lines, timeout)


if __name__ == "__main__":
    sys.exit(main())
