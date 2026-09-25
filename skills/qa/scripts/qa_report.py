#!/usr/bin/env python3
"""
qa_report — builds the run's `## Report` from the <.qa-dir> artifacts (zero tokens).

Why it exists: report prose was one of the most expensive phases of an unguided QA pass —
and the anti-QA-theater validity rules must be checked by a machine, not promised:

  - FAIL finding S1/S2 without a slug in `record` → INVALID REPORT (the bug would evaporate);
  - FAIL finding without severity → invalid;
  - executed case (result != -) without an oracle → does not count, invalid;
  - ledger counters ALWAYS printed (an overrun stays visible, not hidden).

The model only writes on top: the verdict (1 line), 1 line per finding, and the
"Requirement questions". Everything else comes from here.

Usage:
    python3 qa_report.py <.qa-dir> <smoke|standard|audit>   # markdown on stdout
    python3 qa_report.py --selftest

Exit: 0 valid report; 1 invalid (reasons at the top of the output).
"""
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_budget import CAPS, totals  # noqa: E402
from qa_matrix import read_tsv  # noqa: E402


def build(qa_dir, depth):
    qa_dir = Path(qa_dir)
    facts = read_tsv(qa_dir / "facts.tsv")
    cases = read_tsv(qa_dir / "cases.tsv")
    gaps = read_tsv(qa_dir / "gaps.tsv")
    total = totals(qa_dir)
    cap = CAPS.get(depth, {})

    invalid = []
    for c in cases:
        if c.get("result") == "FAIL":
            if c.get("sev") not in {"S1", "S2", "S3", "S4"}:
                invalid.append(f"finding {c['id']} FAIL without severity")
            elif c["sev"] in {"S1", "S2"} and not c.get("record", "").strip():
                invalid.append(f"finding {c['id']} {c['sev']} without a /plan --problem slug")
        if c.get("result", "-") not in {"-", ""} and not c.get("oracle", "").strip():
            invalid.append(f"case {c['id']} executed without an oracle — does not count")

    out = []
    if invalid:
        out.append("**INVALID REPORT** — fix before closing the run:")
        out += [f"- {m}" for m in invalid]
        out.append("")

    executed = [c for c in cases if c.get("result", "-") not in {"-", ""}]
    fails = [c for c in executed if c["result"] == "FAIL"]
    out.append("## Report")
    out.append("")
    out.append(f"- depth: **{depth}** · cases designed: {len(cases)} · executed: "
               f"{len(executed)} · FAIL: {len(fails)} · gaps: {len(gaps)}")
    out.append("- counters: " + " · ".join(
        f"{d}: {total[d]}/{cap.get(d, '?')}" for d in ("files", "lines", "queries",
                                                      "cases", "probes", "tool_uses")))
    out.append("")
    out.append("### Verdict")
    out.append("<!-- MODEL: 1 line tied to the acceptance criteria/charter. Rules: open S1→FAILED; "
               "S2→at most PASSED-WITH-RESERVATIONS; PASSED needs 100% of P0 PASS with an "
               "independent oracle -->")
    out.append("")
    if fails:
        out.append("### Findings")
        out.append("| id | sev | case | evidence | record |")
        out.append("|---|---|---|---|---|")
        for c in fails:
            out.append(f"| {c['id']} | {c.get('sev', '?')} | {c.get('input', '')[:60]} | "
                       f"{c.get('evidence', '')[:80]} | {c.get('record', '') or '—'} |")
        out.append("")
    out.append("### Requirement questions")
    out.append("<!-- MODEL: a doubtful rule ≠ a bug — list what needs a human decision -->")
    out.append("")
    out.append("### Coverage")
    by_prio = Counter((c.get("prio", "?"), c.get("result", "-")) for c in cases)
    for p in ("P0", "P1", "P2"):
        designed = sum(v for (pp, _), v in by_prio.items() if pp == p)
        if designed:
            out.append(f"- {p}: {designed} designed · {by_prio.get((p, 'PASS'), 0)} PASS · "
                       f"{by_prio.get((p, 'FAIL'), 0)} FAIL · {by_prio.get((p, 'SKIP'), 0)} SKIP")
    by_tech = Counter(c.get("technique", "?") for c in cases)
    out.append("- by technique: " + ", ".join(f"{t}: {n}" for t, n in sorted(by_tech.items())))
    out.append("")
    out.append("### NOT covered (mandatory)")
    below = [c["id"] for c in cases if c.get("cut") == "below"]
    if below:
        out.append(f"- below the cut line: {', '.join(below)}")
    for g in gaps:
        out.append(f"- gap {g.get('fact', '?')}: {g.get('reason', '')}")
    impl_weak = [c["id"] for c in executed if "impl" in
                 {s.strip() for s in c.get("oracle_source", "").split(",")}]
    if impl_weak:
        out.append(f"- cases with a partly impl⚠ oracle: {', '.join(impl_weak)}")
    out.append("<!-- MODEL: add suites forbidden by the adapter and the charter's out-of-scope -->")
    out.append("")
    out.append("### Facts → cases")
    out.append("| fact | source | became |")
    out.append("|---|---|---|")
    gap_by_fact = {g["fact"]: g for g in gaps}
    for f in facts:
        ids = [c["id"] for c in cases
               if f["id"] in [x.strip() for x in c.get("facts", "").split(",")]]
        if ids:
            became = ", ".join(ids)
        elif f["id"] in gap_by_fact:
            became = f"gap: {gap_by_fact[f['id']].get('reason', '')[:50]}"
        else:
            became = "⚠ ORPHAN"
        out.append(f"| {f['id']} | {f.get('source', '')} | {became} |")
    out.append("")
    out.append("### Environment and policy")
    out.append("<!-- MODEL: paste the qa_preflight.py output + commands run + teardown done -->")

    print("\n".join(out))
    return 1 if invalid else 0


def selftest():
    ok = True
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "facts.tsv").write_text("id\tsource\tfact\tlimits\nF1\ta:1\tx\t\n")
        head = ("id\tfacts\tlimit\tprio\ttechnique\tinput\toracle\toracle_source"
                "\troute\tcut\tresult\tsev\trecord\tevidence\n")
        # 1: FAIL S1 without record → invalid
        (d / "cases.tsv").write_text(head + "C1\tF1\t\tP0\tsmoke\tGET /\t200\tspec\tapi\texec\tFAIL\tS1\t\tlog\n")
        ok &= build(d, "standard") == 1
        # 2: FAIL S1 with record → valid
        (d / "cases.tsv").write_text(head + "C1\tF1\t\tP0\tsmoke\tGET /\t200\tspec\tapi\texec\tFAIL\tS1\tbug-x\tlog\n")
        ok &= build(d, "standard") == 0
        # 3: S3 without record → valid (only S1/S2 require it)
        (d / "cases.tsv").write_text(head + "C1\tF1\t\tP0\tsmoke\tGET /\t200\tspec\tapi\texec\tFAIL\tS3\t\tlog\n")
        ok &= build(d, "standard") == 0
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
    return build(args[0], args[1])


if __name__ == "__main__":
    sys.exit(main())
