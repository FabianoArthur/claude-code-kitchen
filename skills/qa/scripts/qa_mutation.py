#!/usr/bin/env python3
"""
qa_mutation — /qa mutation-testing engine, deterministic, zero install.

Why it exists: coverage measures execution, not assertion strength: a green suite can be a
pseudo-test ("never trust a test you have not seen fail"). Many repos have no
stryker/mutmut; this script gives the essentials with the stdlib: it applies ONE mutant at
a time to the target file, runs the SCOPED test command (the adapter's `tests.allowed` —
never the whole suite where that is forbidden), and reports:

  mutant KILLED  (test failed)  = the suite catches this kind of bug — good
  mutant ALIVE   (test passed)  = weak assertion or missing partition — a finding

A survivor is NOT an automatic bug: triage in references/mutation.md separates an
equivalent mutant (discard) from a real gap (new case in the matrix or a "weak suite"
finding).

Mutators (regex, 1 line per mutant): > <-> >=, < <-> <=, === <-> !==, == <-> !=,
&& <-> ||, and <-> or, true <-> false / True <-> False.

Safety: the target file must be CLEAN in git (the original comes back by restoring the
bytes + a hash check in `finally`); ALWAYS run in a worktree, never in the main checkout
(the human switches branches there).

Usage:
    python3 qa_mutation.py <target-file> --cmd "<scoped test command>"
                           [--max N=12] [--timeout S=120] [--list] [--only-line L]
    python3 qa_mutation.py --selftest

Output: 1 line per mutant (line, mutation, KILLED|ALIVE|TIMEOUT) + score.
Exit: 0 = all killed; 1 = survivors; 2 = usage/safety error.
"""
import hashlib
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

MUTATORS = [
    (re.compile(r"(?<![-=<>!])>=(?!=)"), ">", "boundary >= → >"),
    (re.compile(r"(?<![-=<>!])>(?![>=])"), ">=", "boundary > → >="),
    (re.compile(r"(?<![<>=!])<=(?!=)"), "<", "boundary <= → <"),
    (re.compile(r"(?<![<>=!<])<(?![<=-])"), "<=", "boundary < → <="),
    (re.compile(r"==="), "!==", "negation === → !=="),
    (re.compile(r"!=="), "===", "negation !== → ==="),
    (re.compile(r"(?<![=!<>])==(?!=)"), "!=", "negation == → !="),
    (re.compile(r"(?<!=)!=(?!=)"), "==", "negation != → =="),
    (re.compile(r"&&"), "||", "logical && → ||"),
    (re.compile(r"\|\|"), "&&", "logical || → &&"),
    (re.compile(r"\band\b"), "or", "logical and → or"),
    (re.compile(r"\bor\b"), "and", "logical or → and"),
    (re.compile(r"\btrue\b"), "false", "boolean true → false"),
    (re.compile(r"\bTrue\b"), "False", "boolean True → False"),
    (re.compile(r"\bfalse\b"), "true", "boolean false → true"),
    (re.compile(r"\bFalse\b"), "True", "boolean False → True"),
]
COMMENT = re.compile(r"^\s*(#|//|\*|/\*|<!--)")
TRIPLE_QUOTES = re.compile(r'"""|\'\'\'')


def skipped_lines(lines):
    """Indexes inside a docstring/block string (`\"\"\"`/`'''`) or on a comment line.

    Measured on real code: without this the engine mutates docstring prose — `... rows) or
    `conflicting` ...` becomes a mutant that tests nothing and still costs a suite run.
    """
    out = set()
    inside = False
    for i, line in enumerate(lines):
        marks = len(TRIPLE_QUOTES.findall(line))
        if inside:
            out.add(i)
        if marks % 2 == 1:
            if not inside:
                out.add(i)      # the line that OPENS the block is prose too
            inside = not inside
        elif marks >= 2 and not inside:
            out.add(i)          # one-line docstring
        if COMMENT.match(line) or not line.strip():
            out.add(i)
    return out


def generate_mutants(lines, max_n):
    """[(line_idx, mutated_line, description)] — at most 1 mutant per (line, mutator),
    round-robin across mutator types to diversify."""
    everything = []
    skip = skipped_lines(lines)
    for i, line in enumerate(lines):
        if i in skip:
            continue
        for rx, repl, desc in MUTATORS:
            m = rx.search(line)
            if m:
                mutated = line[:m.start()] + repl + line[m.end():]
                if mutated != line:
                    everything.append((i, mutated, desc))
    by_type = {}
    for t in everything:
        by_type.setdefault(t[2], []).append(t)
    out, rounds = [], 0
    while len(out) < max_n and any(by_type.values()):
        for kind in list(by_type):
            if by_type[kind]:
                out.append(by_type[kind].pop(0))
                if len(out) >= max_n:
                    break
        rounds += 1
        if rounds > 500:
            break
    return out


SENTINEL = "QA_MUTATION_PROBE_NOT_COVERED"
# How the coverage probe works, and why it exists:
# an ALIVE mutant has TWO possible diagnoses, with opposite fixes —
#   (a) the line IS executed and no assertion complains  → weak assertion;
#   (b) the line is NOT executed by any test              → a missing case (NoCoverage).
# Without the probe both look like "ALIVE" (only the return code is read) and triage is
# blind. The probe replaces the line with a CRASH: if the suite stays green, nobody passes
# there (NoCoverage); if it blows up with the sentinel in the output, the line runs and the
# survivor is a genuinely weak assertion. It costs 1 run per survivor — not per mutant.
PROBE_BY_EXT = {
    ".py":  'raise RuntimeError("{s}")',
    ".js":  'throw new Error("{s}");',
    ".mjs": 'throw new Error("{s}");',
    ".cjs": 'throw new Error("{s}");',
    ".ts":  'throw new Error("{s}");',
    ".tsx": 'throw new Error("{s}");',
    ".jsx": 'throw new Error("{s}");',
    ".go":  'panic("{s}")',
    ".rb":  'raise "{s}"',
}


def indentation(line):
    return line[:len(line) - len(line.lstrip())]


def coverage_probe(target, lines, idx, args, timeout):
    """'not-covered' | 'covered' | 'inconclusive' for line idx.

    inconclusive = the injected crash broke the syntax (the sentinel did not show up in the
    output), so "line executed" cannot be told apart from "file does not compile". Never
    guess in that case: the report says inconclusive.
    """
    template = PROBE_BY_EXT.get(Path(target).suffix)
    if not template:
        return "inconclusive"
    new = lines.copy()
    raw = lines[idx].rstrip()
    # A line that OPENS a block (`if x:`, `elif y:`, `} else {`): replacing it orphans the
    # body and the file does not even compile — the probe used to return "inconclusive" for
    # every comparator inside a conditional, which is exactly where BVA lives. In those
    # cases the crash goes INSIDE the block: "covered" then means "some test enters this
    # branch", which is the actionable information — a branch never taken = a missing case.
    opens_block = raw.endswith(":") or raw.endswith("{")
    if opens_block:
        step = "    " if Path(target).suffix == ".py" else "  "
        new.insert(idx + 1, indentation(lines[idx]) + step + template.format(s=SENTINEL) + "\n")
    else:
        new[idx] = indentation(lines[idx]) + template.format(s=SENTINEL) + "\n"
    original = Path(target).read_bytes()
    try:
        Path(target).write_bytes("".join(new).encode())
        r = subprocess.run(args, capture_output=True, timeout=timeout)
        output = (r.stdout or b"") + (r.stderr or b"")
        if r.returncode == 0:
            return "not-covered"
        return "covered" if SENTINEL.encode() in output else "inconclusive"
    except subprocess.TimeoutExpired:
        return "covered"          # it hung running the line: someone passes there
    except OSError:
        return "inconclusive"
    finally:
        Path(target).write_bytes(original)


def clean_in_git(path):
    try:
        r = subprocess.run(["git", "status", "--porcelain", "--", str(path)],
                           capture_output=True, text=True, cwd=Path(path).parent)
        return r.returncode == 0 and not r.stdout.strip()
    except OSError:
        return False


def run(target, cmd, max_n, timeout, list_only=False, require_git=True, only_line=None):
    target = Path(target)
    if not target.is_file():
        print(f"target does not exist: {target}")
        return 2
    original = target.read_bytes()
    original_hash = hashlib.sha256(original).hexdigest()
    lines = original.decode(errors="replace").splitlines(keepends=True)
    mutants = generate_mutants(lines, max_n)
    if only_line is not None:
        # "Prove the new case kills it" mode: mutate ONLY the requested line. It closes the
        # loop — a survivor becomes a new case, and the new case must turn that mutant red.
        # Without this proof a badly chosen case enters the matrix, stays green, and the
        # gap stays open while looking closed.
        mutants = [m for m in generate_mutants(lines, 10_000) if m[0] == only_line - 1]
        if not mutants:
            print(f"no mutable point on line {only_line} — check the number (1-based) or "
                  "run without --only-line to see the available points")
            return 2
    if not mutants:
        print("no mutable point found (comparators/logicals/booleans)")
        return 0
    if list_only:
        for i, (idx, mutated, desc) in enumerate(mutants, 1):
            print(f"M{i:02d} L{idx + 1} {desc}: {mutated.strip()[:90]}")
        return 0
    if require_git and not clean_in_git(target):
        print(f"SAFETY: {target} is dirty in git (or outside a repo) — commit it first; "
              "and run in a worktree, never in the main checkout")
        return 2
    args = shlex.split(cmd)
    alive, killed, timeouts = [], 0, 0
    coverage = {}
    try:
        for i, (idx, mutated, desc) in enumerate(mutants, 1):
            new = lines.copy()
            new[idx] = mutated
            target.write_bytes("".join(new).encode())
            try:
                # cwd = the caller's (usually the repo root). Guessing the cwd from the
                # target's directory breaks every command relative to the root.
                r = subprocess.run(args, capture_output=True, timeout=timeout)
                if r.returncode == 0:
                    alive.append((i, idx + 1, desc, mutated.strip()[:80]))
                    print(f"M{i:02d} L{idx + 1} {desc}: ALIVE ⚠")
                else:
                    killed += 1
                    print(f"M{i:02d} L{idx + 1} {desc}: killed")
            except subprocess.TimeoutExpired:
                timeouts += 1
                print(f"M{i:02d} L{idx + 1} {desc}: TIMEOUT (counts as suspect-killed)")
        # Coverage probe: survivors only, with the file still under the try/finally that
        # restores the original.
        for i, line_no, _desc, _snippet in alive:
            coverage[i] = coverage_probe(target, lines, line_no - 1, args, timeout)
    finally:
        target.write_bytes(original)
        restored = hashlib.sha256(target.read_bytes()).hexdigest() == original_hash
    if not restored:
        print("SEVERE ERROR: restore failed — restore it with git checkout!")
        return 2
    not_covered = sum(1 for v in coverage.values() if v == "not-covered")
    print(f"── score: {killed} killed · {len(alive)} ALIVE ({not_covered} for LACK OF "
          f"COVERAGE) · {timeouts} timeout · {len(mutants)} mutants of {target.name}")
    if alive:
        print("survivors — the diagnosis comes pre-split; triage in references/mutation.md:")
        labels = {
            "not-covered": "NOT COVERED (no test passes here / enters this branch → a missing "
                           "CASE, not an assertion)",
            "covered": "COVERED (the branch runs, but nothing complains about the mutation) → "
                       "weak assertion OR missing partition: look for a missing case AT the "
                       "point the mutation changes",
            "inconclusive": "inconclusive (the probe broke the syntax — triage by hand)",
        }
        for i, line_no, desc, snippet in alive:
            print(f"  M{i:02d} L{line_no} {desc} → {snippet}")
            print(f"       {labels[coverage.get(i, 'inconclusive')]}")
        print("\nAfter writing the new case, PROVE it kills the mutant:")
        print(f"  python3 {Path(__file__).name} {target} --only-line <L> --cmd \"<new case cmd>\"")
        print("  (expected: that line's mutant now DIES; if it stays ALIVE,")
        print("   the new case does not catch the regression and the gap is still open)")
    return 1 if alive else 0


def selftest():
    ok = True
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "calc.py"
        target.write_text("def is_greater(a, b):\n    return a > b\n\n"
                          "def inside(x):\n    return x >= 0 and x <= 10\n")
        strong = (f"{sys.executable} -c \"import sys; sys.path.insert(0,'{td}'); import calc; "
                  "assert calc.is_greater(2,1) and not calc.is_greater(1,1); "
                  "assert calc.inside(0) and calc.inside(10) and not calc.inside(-1) "
                  "and not calc.inside(11)\"")
        weak = (f"{sys.executable} -c \"import sys; sys.path.insert(0,'{td}'); import calc; "
                "assert calc.is_greater(5,1); assert calc.inside(5)\"")
        ok &= run(target, strong, 12, 30, require_git=False) == 0
        ok &= run(target, weak, 12, 30, require_git=False) == 1
        ok &= target.read_text().count(">") >= 2          # restored
        ok &= run(target, strong, 12, 30, list_only=True, require_git=False) == 0

        # coverage probe: tells NoCoverage from Survived
        lines = target.read_text().splitlines(keepends=True)
        strong_args = shlex.split(strong)
        ok &= coverage_probe(target, lines, 1, strong_args, 30) == "covered"
        target.write_text(target.read_text() + "\ndef never_called(v):\n    return v > 100\n")
        lines2 = target.read_text().splitlines(keepends=True)
        ok &= coverage_probe(target, lines2, len(lines2) - 1, strong_args, 30) == "not-covered"
        ok &= target.read_text().endswith("return v > 100\n")   # probe restored the file

        # --only-line: proves a new case kills that line's mutant
        ok &= run(target, weak, 12, 30, require_git=False, only_line=2) == 1    # ALIVE
        ok &= run(target, strong, 12, 30, require_git=False, only_line=2) == 0  # killed
        ok &= run(target, strong, 12, 30, require_git=False, only_line=1) == 2  # nothing to mutate
    print("SELFTEST: " + ("OK" if ok else "FAILED"))
    return 0 if ok else 1


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    if args[0] == "--selftest":
        return selftest()
    target = args[0]
    cmd, max_n, timeout, list_only, only_line = None, 12, 120, False, None
    rest = args[1:]
    while rest:
        if rest[0] == "--cmd" and len(rest) > 1:
            cmd = rest[1]
            rest = rest[2:]
        elif rest[0] == "--max" and len(rest) > 1:
            max_n = int(rest[1])
            rest = rest[2:]
        elif rest[0] == "--timeout" and len(rest) > 1:
            timeout = int(rest[1])
            rest = rest[2:]
        elif rest[0] == "--only-line" and len(rest) > 1:
            only_line = int(rest[1])
            rest = rest[2:]
        elif rest[0] == "--list":
            list_only = True
            rest = rest[1:]
        else:
            print(f"unknown flag {rest[0]}")
            return 2
    if not list_only and not cmd:
        print("missing --cmd (or use --list)")
        return 2
    return run(target, cmd or "", max_n, timeout, list_only=list_only, only_line=only_line)


if __name__ == "__main__":
    sys.exit(main())
