#!/usr/bin/env python3
"""
qa_matrix — deterministic gate for the /qa case matrix.

Why it exists: the most expensive miss of agent-driven QA, measured on a real project, is
READING a limit in the code ("a report window >7 days switches to daily buckets") and NOT
creating the case at the limit. Knowledge without technique is coverage by chance. The
model designs the matrix (it is good at that); this script checks what is not negotiable:

  - every fact F* is referenced by ≥1 case OR by 1 gap with a reason;
  - every token in a fact's `limits` → ≥3 BVA cases for that (fact, limit)
    (below / at / above) OR a gap citing the token;
  - every case has: a concrete input, a named oracle, an oracle source in the taxonomy
    {spec, consumer, invariant, parity, doc, impl} — and `impl` NEVER alone;
  - priority P0|P1|P2 and cut exec|below on every case; ≥1 P0 case with cut exec;
  - technique in the closed list (BVA partition decision state property guessing
    journey smoke exploratory).

Files (TSV with header, in <.qa-dir>):
  facts.tsv   id  source  fact  limits          # limits: tokens separated by ';'
  cases.tsv   id  facts  limit  prio  technique  input  oracle  oracle_source  route  cut  result  sev  record  evidence
  gaps.tsv    fact  reason                      # the reason may cite the limit token

Usage:
    python3 qa_matrix.py <.qa-dir> [--depth smoke|standard|audit]   # gate: 0 clean, 1 violations
    python3 qa_matrix.py --skeleton <.qa-dir>   # prints the cases.tsv header + BVA rows
    python3 qa_matrix.py --selftest
"""
import sys
import tempfile
from pathlib import Path

CASES_HEADER = ("id\tfacts\tlimit\tprio\ttechnique\tinput\toracle\toracle_source"
                "\troute\tcut\tresult\tsev\trecord\tevidence")
SOURCES = {"spec", "consumer", "invariant", "parity", "doc", "impl"}
TECHNIQUES = {"BVA", "partition", "decision", "state", "property", "guessing",
              "journey", "smoke", "exploratory"}
PRIOS = {"P0", "P1", "P2"}
CASE_CAP = {"smoke": 8, "standard": 20, "audit": 40}   # mirrors qa_budget.py


def read_tsv(path):
    p = Path(path)
    if not p.is_file():
        return []
    lines = [line for line in p.read_text().splitlines()
             if line.strip() and not line.startswith("#")]
    if not lines:
        return []
    header = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        fields = line.split("\t")
        fields += [""] * (len(header) - len(fields))
        rows.append(dict(zip(header, fields, strict=False)))  # extra cells dropped
    return rows


def gate(qa_dir, depth=None):
    qa_dir = Path(qa_dir)
    facts = read_tsv(qa_dir / "facts.tsv")
    cases = read_tsv(qa_dir / "cases.tsv")
    gaps = read_tsv(qa_dir / "gaps.tsv")
    errors = []

    if not facts:
        errors.append("facts.tsv empty or missing — Step 2 produced no facts")
    if not cases:
        errors.append("cases.tsv empty or missing — Step 3 produced no matrix")

    fact_ids = {f["id"] for f in facts}
    facts_with_case = set()
    facts_with_gap = {g["fact"] for g in gaps}
    gap_reasons = " ".join(g.get("reason", "") for g in gaps)

    for c in cases:
        cid = c.get("id", "?")
        refs = [x.strip() for x in c.get("facts", "").split(",") if x.strip()]
        if not refs:
            errors.append(f"case {cid}: no fact attached")
        for r in refs:
            if r not in fact_ids:
                errors.append(f"case {cid}: unknown fact '{r}'")
            facts_with_case.add(r)
        if not c.get("input", "").strip():
            errors.append(f"case {cid}: empty input — a CONCRETE input is required")
        if not c.get("oracle", "").strip():
            errors.append(f"case {cid}: no named oracle")
        sources = {s.strip() for s in c.get("oracle_source", "").split(",") if s.strip()}
        if not sources:
            errors.append(f"case {cid}: no oracle source")
        elif not sources <= SOURCES:
            errors.append(f"case {cid}: source outside the taxonomy: {sources - SOURCES}")
        elif sources == {"impl"}:
            errors.append(f"case {cid}: oracle is ONLY 'impl' — add an independent one "
                          "(spec/consumer/invariant/parity/doc) or make it a gap")
        if c.get("prio") not in PRIOS:
            errors.append(f"case {cid}: invalid prio '{c.get('prio')}' (P0|P1|P2)")
        if c.get("technique") not in TECHNIQUES:
            errors.append(f"case {cid}: technique '{c.get('technique')}' not in {sorted(TECHNIQUES)}")
        if c.get("cut") not in {"exec", "below"}:
            errors.append(f"case {cid}: invalid cut '{c.get('cut')}' (exec|below)")

    for f in facts:
        if f["id"] not in facts_with_case and f["id"] not in facts_with_gap:
            errors.append(f"fact {f['id']} orphaned: no case and no gap — an extracted fact "
                          "becomes a case or a declared gap")
        for token in [t.strip() for t in f.get("limits", "").split(";") if t.strip()]:
            bva = [c for c in cases
                   if f["id"] in [x.strip() for x in c.get("facts", "").split(",")]
                   and c.get("technique") == "BVA" and c.get("limit", "").strip() == token]
            if len(bva) >= 3:
                continue
            if f["id"] in facts_with_gap and token in gap_reasons:
                continue
            errors.append(f"fact {f['id']}, limit '{token}': {len(bva)}/3 BVA cases "
                          "(below/at/above) and no gap citing the token")

    if cases and not any(c.get("prio") == "P0" and c.get("cut") == "exec" for c in cases):
        errors.append("no P0 case with cut=exec — the run would execute nothing essential")

    # Measured on a real project: a run wrote 31 full cases against a cap of 20 and spent
    # more tokens than a baseline WITHOUT the skill — 15 of them cut=below, written out in
    # full never to run. Writing a case is expensive; draw the cut line BEFORE writing.
    if depth:
        cap = CASE_CAP.get(depth)
        if cap and len(cases) > cap:
            errors.append(f"matrix with {len(cases)} cases for a cap of {cap} at '{depth}': "
                          f"writing a case that never runs is pure cost — keep ≤{cap} rows "
                          "and summarise what fell below the cut in 1 line of gaps.tsv")

    if errors:
        print(f"GATE RED — {len(errors)} violation(s):")
        for e in errors:
            print(f"  ✗ {e}")
        return 1
    n_exec = sum(1 for c in cases if c.get("cut") == "exec")
    print(f"GATE GREEN — {len(facts)} facts, {len(cases)} cases ({n_exec} to run), "
          f"{len(gaps)} declared gaps")
    return 0


def skeleton(qa_dir):
    facts = read_tsv(Path(qa_dir) / "facts.tsv")
    print(CASES_HEADER)
    n = 1
    for f in facts:
        for token in [t.strip() for t in f.get("limits", "").split(";") if t.strip()]:
            for point in ("below", "at", "above"):
                print(f"C{n:02d}\t{f['id']}\t{token}\tP1\tBVA\t<{point} {token}>"
                      f"\t<expected>\t<source>\t<route>\texec\t-\t\t\t")
                n += 1
    if n == 1:
        print("# no fact with limits — fill cases.tsv under the header above")
    return 0


def selftest():
    ok = True
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "facts.tsv").write_text(
            "id\tsource\tfact\tlimits\n"
            "F1\ta.py:10\twindow >7d switches to daily buckets\t7d\n"
            "F2\tb.py:20\tresponse sorted by date\t\n")
        # 1: F1 without BVA and F2 orphaned → red
        (d / "cases.tsv").write_text(CASES_HEADER + "\n"
            "C1\tF1\t\tP0\tsmoke\tGET /x\t200 and shape\tspec\tapi\texec\t-\t\t\t\n")
        ok &= gate(d) == 1
        # 2: complete matrix → green
        (d / "cases.tsv").write_text(CASES_HEADER + "\n"
            "C1\tF1\t\tP0\tsmoke\tGET /x\t200 and shape\tspec\tapi\texec\t-\t\t\t\n"
            "C2\tF1\t7d\tP1\tBVA\twindow 7d-1s\thourly buckets\tdoc\tapi\texec\t-\t\t\t\n"
            "C3\tF1\t7d\tP1\tBVA\twindow 7d\thourly buckets\tdoc\tapi\texec\t-\t\t\t\n"
            "C4\tF1\t7d\tP1\tBVA\twindow 7d+1s\tdaily buckets\tdoc\tapi\texec\t-\t\t\t\n"
            "C5\tF2\t\tP1\tproperty\t3 windows\tdates ascending\tinvariant\tapi\tbelow\t-\t\t\t\n")
        ok &= gate(d) == 0
        # 3: impl-only oracle → red
        (d / "cases.tsv").write_text(CASES_HEADER + "\n"
            "C1\tF1\t\tP0\tsmoke\tGET /x\tsame as the code\timpl\tapi\texec\t-\t\t\t\n"
            "C2\tF1\t7d\tP1\tBVA\ta\tb\tdoc\tapi\texec\t-\t\t\t\n"
            "C3\tF1\t7d\tP1\tBVA\ta\tb\tdoc\tapi\texec\t-\t\t\t\n"
            "C4\tF1\t7d\tP1\tBVA\ta\tb\tdoc\tapi\texec\t-\t\t\t\n"
            "C5\tF2\t\tP1\tproperty\ta\tb\tinvariant\tapi\texec\t-\t\t\t\n")
        ok &= gate(d) == 1
        # 4: a gap covers the fact and the limit → green
        (d / "cases.tsv").write_text(CASES_HEADER + "\n"
            "C1\tF2\t\tP0\tproperty\t3 windows\tdates ascending\tinvariant\tapi\texec\t-\t\t\t\n")
        (d / "gaps.tsv").write_text("fact\treason\nF1\tlimit 7d needs 7 days of staging data — "
                                    "outside the smoke budget\n")
        ok &= gate(d) == 0
        # 5: matrix above the depth's cap → red (only when the depth is given)
        rows = [CASES_HEADER]
        for i in range(1, 10):
            rows.append(f"C{i}\tF2\t\tP0\tsmoke\te{i}\to{i}\tspec\tapi\t"
                        + ("exec" if i < 3 else "below") + "\t-\t\t\t")
        (d / "cases.tsv").write_text("\n".join(rows) + "\n")
        ok &= gate(d, "smoke") == 1      # 9 cases > cap 8
        ok &= gate(d) == 0               # no depth, no cap check
        ok &= gate(d, "standard") == 0   # 9 < 20
    print("SELFTEST: " + ("OK" if ok else "FAILED"))
    return 0 if ok else 1


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    if args[0] == "--selftest":
        return selftest()
    if args[0] == "--skeleton":
        return skeleton(args[1])
    depth = args[args.index("--depth") + 1] if "--depth" in args else None
    return gate(args[0], depth)


if __name__ == "__main__":
    sys.exit(main())
