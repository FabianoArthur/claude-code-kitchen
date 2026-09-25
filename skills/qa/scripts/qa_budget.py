#!/usr/bin/env python3
"""
qa_budget — /qa budget ledger in COUNTABLE units, with the 80% rule.

Why it exists: an agent cannot measure tokens in flight — but it can count files, lines,
queries, cases, probes and tool uses. An unbudgeted QA pass measured on a real project
cost 61k–112k tokens; the cap turns into an auditable contract: overrunning silently is a
report defect, and the cut becomes "NOT covered", never extra reading.

Ledger: <.qa-dir>/budget.tsv (phase + 6 counters, one row per `add`).

Usage:
    python3 qa_budget.py <.qa-dir> add <phase> [--files N] [--lines N] [--queries N]
                                              [--cases N] [--probes N] [--tool-uses N]
    python3 qa_budget.py <.qa-dir> check <smoke|standard|audit>
        → prints each dimension as used/cap; exit 0 = CONTINUE,
          exit 1 = STOP-AND-REPORT (some dimension ≥80% of its cap)
    python3 qa_budget.py --selftest
"""
import sys
import tempfile
from pathlib import Path

DIMENSIONS = ["files", "lines", "queries", "cases", "probes", "tool_uses"]
CAPS = {
    "smoke":    {"queries": 2, "files": 3,  "lines": 600,  "cases": 8,  "probes": 2, "tool_uses": 25},
    "standard": {"queries": 3, "files": 6,  "lines": 1800, "cases": 20, "probes": 4, "tool_uses": 60},
    "audit":    {"queries": 5, "files": 12, "lines": 6000, "cases": 40, "probes": 8, "tool_uses": 120},
}


def ledger_path(qa_dir):
    return Path(qa_dir) / "budget.tsv"


def add(qa_dir, phase, values):
    p = ledger_path(qa_dir)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("phase\t" + "\t".join(DIMENSIONS) + "\n")
    row = phase + "\t" + "\t".join(str(values.get(d, 0)) for d in DIMENSIONS)
    with p.open("a") as handle:
        handle.write(row + "\n")
    print(f"ledger += {phase}: " +
          ", ".join(f"{d}={values.get(d, 0)}" for d in DIMENSIONS if values.get(d, 0)))
    return 0


def totals(qa_dir):
    p = ledger_path(qa_dir)
    total = {d: 0 for d in DIMENSIONS}
    if not p.exists():
        return total
    for line in p.read_text().splitlines()[1:]:
        fields = line.split("\t")
        for i, d in enumerate(DIMENSIONS, start=1):
            if i < len(fields) and fields[i].strip().isdigit():
                total[d] += int(fields[i])
    return total


def check(qa_dir, depth):
    if depth not in CAPS:
        print(f"invalid depth '{depth}' ({'|'.join(CAPS)})")
        return 1
    cap = CAPS[depth]
    total = totals(qa_dir)
    over = []
    for d in DIMENSIONS:
        used, limit = total[d], cap[d]
        mark = ""
        if used >= limit:
            mark = "  ← OVER"
            over.append(d)
        elif used >= 0.8 * limit:
            mark = "  ← ≥80%"
            over.append(d)
        print(f"  {d}: {used}/{limit}{mark}")
    if over:
        print(f"STOP-AND-REPORT: {', '.join(over)} at the limit — cut here; the rest is NOT covered")
        return 1
    print("CONTINUE")
    return 0


def selftest():
    ok = True
    with tempfile.TemporaryDirectory() as td:
        add(td, "recon", {"files": 2, "lines": 300, "queries": 2})
        ok &= check(td, "standard") == 0
        add(td, "run", {"cases": 15, "probes": 2, "tool_uses": 30})
        ok &= check(td, "standard") == 0       # 15/20 cases = 75% < 80%
        add(td, "run", {"cases": 1})
        ok &= check(td, "standard") == 1       # 16/20 = 80%
        ok &= check(td, "audit") == 0          # same ledger, bigger cap
        ok &= check(td, "banana") == 1
    print("SELFTEST: " + ("OK" if ok else "FAILED"))
    return 0 if ok else 1


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    if args[0] == "--selftest":
        return selftest()
    qa_dir = args[0]
    if len(args) >= 3 and args[1] == "add":
        values, i = {}, 3
        while i < len(args):
            key = args[i].lstrip("-").replace("-", "_")
            if key in DIMENSIONS and i + 1 < len(args):
                values[key] = int(args[i + 1])
                i += 2
            else:
                print(f"unknown flag {args[i]}")
                return 1
        return add(qa_dir, args[2], values)
    if len(args) >= 3 and args[1] == "check":
        return check(qa_dir, args[2])
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
