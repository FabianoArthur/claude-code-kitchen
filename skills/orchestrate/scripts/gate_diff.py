#!/usr/bin/env python3
"""
gate_diff — the `forbidden_in_diff` gate of CORE.md §3a, deterministic.

Why it exists: the §3a mechanics are easy to get wrong by hand, and getting them wrong is
expensive both ways. A loose gate fires on the comment that documents the rule itself (and
becomes noise everyone ignores); a gate that is too tight lets through what it should stop.

Mechanics (§3a), literally:
  - look ONLY at the added lines of the staged diff (`git diff --cached -U0`);
  - drop the `+++` header;
  - IGNORE comment lines (`#`, `//`, `/*`, `*`, `<!--`, `--`);
  - match the adapter's patterns against what is left.

Usage:
    python3 gate_diff.py <dir>                  # <dir> = WHERE THE DIFF IS (worktree or repo)
    python3 gate_diff.py <dir> --pattern REGEX  # try a one-off pattern
    python3 gate_diff.py --selftest             # run the built-in tests

The adapter is found by walking UP from <dir> until `.claude/orchestrator.md` (CORE §1).
That matters: on a kitchen route the diff lives in the *worktree* while the adapter lives
at the repo root — pointing at the repo root would read the wrong index and say "clean"
without the gate ever looking at what the unit wrote.

Adapter format (inside the adapter's yaml block):

    forbidden_in_diff:
      - pattern: "console\\.log\\("
        why: "debug output must not ship"
      - pattern: "localhost:\\d+"
        why: >
          hard-coded dev URL; use the configured base URL

Exit: 0 = clean (commit away) · 1 = hit (the agent FIXES it and reruns) · 2 = error
"""
import re
import subprocess
import sys
from pathlib import Path

# Comment prefixes per file extension. `--` is a comment only in the languages that use it:
# in JS/C `--n` is a decrement, and treating it as a comment hid real hits.
_HASH = ("#",)
_C_LIKE = ("//", "/*", "*")
COMMENT_BY_EXT = {
    **{ext: _HASH for ext in (".py", ".sh", ".bash", ".zsh", ".rb", ".pl", ".r", ".yml", ".yaml",
                              ".toml", ".cfg", ".ini", ".conf", ".mk", ".dockerfile", ".tf")},
    **{ext: _C_LIKE for ext in (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".go", ".java",
                                ".kt", ".kts", ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".swift",
                                ".rs", ".scala", ".dart", ".php", ".css", ".scss", ".less")},
    **{ext: ("--",) for ext in (".sql", ".lua", ".hs", ".elm", ".ada")},
    **{ext: ("<!--",) for ext in (".html", ".htm", ".xml", ".svg", ".vue", ".md", ".markdown")},
}
COMMENT_DEFAULT = ("#", "//", "/*", "*", "<!--")   # unknown extension: never `--`
ADAPTER = Path(".claude") / "orchestrator.md"


def is_comment(file, text):
    ext = Path(file).suffix.lower() or Path(file).name.lower()
    prefixes = COMMENT_BY_EXT.get(ext, COMMENT_DEFAULT)
    return text.lstrip().startswith(prefixes)


def parse_added_lines(diff_text):
    """[(file, text)] for added, non-comment, non-blank lines of a unified diff.

    A small state machine: `+++ ` is a file header only in the HEADER part of a file diff
    (after `diff --git` / before the first `@@`). Inside a hunk, an added line whose
    content starts with `++` (`++i; …`) arrives as `+++i; …` and is content, not a header.
    """
    current, out = "?", []
    in_header = True
    for line in diff_text.split("\n"):
        if line.startswith("diff --git "):
            in_header = True
            continue
        if line.startswith("@@"):
            in_header = False
            continue
        if in_header:
            if line.startswith("+++ "):
                current = line[6:] if line.startswith("+++ b/") else line[4:]
            continue
        if line.startswith("+"):
            text = line[1:]
            if not text.strip() or is_comment(current, text):
                continue
            out.append((current, text))
    return out


def staged_added_lines(repo):
    # Order matters: `--cached` is an option of `diff`, not of `git`.
    # `git -C <dir> --cached diff` is invalid, exits non-zero with empty stdout — and a
    # gate that reads that as "no lines" says "clean" FOREVER.
    # The flags pin the output format against config and attributes the gate does not own:
    # `color.ui=always`, `diff.external`, a textconv driver or a committed `*.x -diff` in
    # `.gitattributes` would each turn the added lines into something this parser does not
    # read — and "no lines" means "clean".
    # `diff.relative=true` would hide everything outside <dir> when <dir> is a subdirectory.
    cmd = ["git", "-C", str(repo), "-c", "core.quotePath=false", "diff", "--cached", "-U0",
           "--no-color", "--no-ext-diff", "--no-textconv", "--no-relative", "--text",
           "--src-prefix=a/", "--dst-prefix=b/"]
    # Bytes, decoded leniently: `--text` puts binaries (and any non-UTF-8 file) in the diff,
    # and a strict decode would crash with exit 1 — which reads as "hit", not "error".
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        # Never degrade to "clean" silently: a git failure is a gate failure.
        stderr = result.stderr.decode("utf-8", errors="replace").strip()[:300]
        print(f"ERROR: {' '.join(cmd)} exited {result.returncode}\n{stderr}", file=sys.stderr)
        sys.exit(2)
    return parse_added_lines(result.stdout.decode("utf-8", errors="replace"))


def check(lines, patterns):
    """[(file, text, pattern, why)] hits."""
    hits = []
    for pattern, why in patterns:
        rx = re.compile(pattern)
        for file, text in lines:
            if rx.search(text):
                hits.append((file, text.strip()[:100], pattern, why))
    return hits


def run(repo, patterns):
    lines = staged_added_lines(repo)
    if not lines:
        print("gate: nothing staged (or only comments/blank lines) — clean")
        return 0
    hits = check(lines, patterns)
    print(f"gate: {len(lines)} added code line(s) · {len(patterns)} pattern(s)")
    if not hits:
        print("✅ clean — no forbidden pattern in an added line")
        return 0
    print(f"\n❌ {len(hits)} hit(s) — FIX and rerun the gate (§3a: do not ask the human):\n")
    for file, text, _pattern, why in hits:
        print(f"  {file}\n    + {text}\n    ↳ {why}\n")
    return 1


def find_adapter(start):
    """Walk up from `start` until `.claude/orchestrator.md` (CORE §1)."""
    here = Path(start).resolve()
    for candidate in [here, *here.parents]:
        path = candidate / ADAPTER
        if path.exists():
            return path
    return None


def _unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value


def parse_patterns(adapter_text):
    """[(regex, why)] from the `forbidden_in_diff:` block of an adapter.

    Accepts `why: "inline"`, `why: inline` and folded `why: >` followed by indented lines.
    YAML double-quoted escapes are honoured for the pattern (`\\\\.` becomes `\\.`).
    """
    block = re.search(r"(?ms)^forbidden_in_diff:[ \t]*\n(.*?)(?=^\S|\Z)", adapter_text)
    if not block:
        return []
    items, current = [], None
    lines = block.group(1).split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        m = re.match(r"-\s*pattern:\s*(.+)$", stripped)
        if m:
            raw = m.group(1).strip()
            pattern = _unquote(raw)
            if raw.startswith('"'):
                pattern = pattern.replace("\\\\", "\\")
            current = [pattern, ""]
            items.append(current)
            i += 1
            continue
        m = re.match(r"why:\s*(.*)$", stripped)
        if m and current is not None:
            value = m.group(1).strip()
            if value in (">", "|", ">-", "|-"):
                folded = []
                indent = len(line) - len(line.lstrip())
                i += 1
                while i < len(lines) and (not lines[i].strip() or
                                          len(lines[i]) - len(lines[i].lstrip()) > indent):
                    if lines[i].strip():
                        folded.append(lines[i].strip())
                    i += 1
                current[1] = " ".join(folded)
                continue
            current[1] = _unquote(value)
        i += 1
    return [(p, w or "(no reason given)") for p, w in items]


def declares_block(adapter_text):
    """True when the adapter has a non-empty `forbidden_in_diff:` key."""
    m = re.search(r"(?m)^forbidden_in_diff:[ \t]*(.*)$", adapter_text)
    if not m:
        return False
    inline = m.group(1).strip()
    if inline and inline not in ("[]", "~", "null"):
        return True           # flow style `[...]` is not supported → must not read as empty
    body = re.search(r"(?ms)^forbidden_in_diff:[ \t]*\n(.*?)(?=^\S|\Z)", adapter_text)
    return bool(body and any(line.strip() and not line.strip().startswith("#")
                             for line in body.group(1).split("\n")))


def selftest():
    """Proves the §3a mechanics without any repo."""
    cases = [
        ("added code line hits",
         "+++ b/a.ts\n@@\n+const url = 'http://localhost:3000'\n", r"localhost", 1),
        ("SAME text in a COMMENT does not hit",
         "+++ b/a.ts\n@@\n+// never use http://localhost here\n", r"localhost", 0),
        ("python comment does not hit",
         "+++ b/a.py\n@@\n+# localhost forbidden\n", r"localhost", 0),
        ("REMOVED line does not hit",
         "+++ b/a.ts\n@@\n-const url = 'localhost'\n", r"localhost", 0),
        ("+++ header is not treated as content",
         "+++ b/localhost.ts\n@@\n+const x = 1\n", r"localhost", 0),
        ("context line (no +) does not hit",
         "+++ b/a.ts\n@@\n const url = 'localhost'\n", r"localhost", 0),
        ("added line starting with ++ is content, not a header",
         "+++ b/a.js\n@@\n+++i; fetch('localhost')\n", r"localhost", 1),
        ("`--` is code in JS (decrement), not a comment",
         "+++ b/a.js\n@@\n+--n; fetch('localhost')\n", r"localhost", 1),
        ("`--` IS a comment in SQL",
         "+++ b/q.sql\n@@\n+-- localhost only in dev\n", r"localhost", 0),
    ]
    ok = True
    for name, diff, pattern, expected in cases:
        got = len(check(parse_added_lines(diff), [(pattern, "test")]))
        mark = "✓" if got == expected else "✗"
        ok &= got == expected
        print(f"  {mark} {name}  (expected {expected}, got {got})")
    adapter = ('```yaml\nbase: main\nforbidden_in_diff:\n'
               '  - pattern: "console\\\\.log\\\\("\n    why: "no debug output"\n'
               '  - pattern: "localhost"\n    why: >\n      hard-coded\n      dev URL\n'
               'max_parallel: 2\n```\n')
    parsed = parse_patterns(adapter)
    expected = [(r"console\.log\(", "no debug output"), ("localhost", "hard-coded dev URL")]
    mark = "✓" if parsed == expected else "✗"
    ok &= parsed == expected
    print(f"  {mark} adapter block parsed (inline + folded why, escapes)  got {parsed}")
    malformed = 'forbidden_in_diff:\n  - "localhost"\n'
    flagged = parse_patterns(malformed) == [] and declares_block(malformed)
    print(f"  {'✓' if flagged else '✗'} a present-but-unparseable block is detected (not 'clean')")
    ok &= flagged
    print("\nselftest:", "ALL PASSED" if ok else "FAILED")
    return 0 if ok else 1


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if "--selftest" in args:
        return selftest()
    where = args[0]
    if "--pattern" in args:
        i = args.index("--pattern")
        if i + 1 >= len(args):
            print("ERROR: --pattern needs a regex", file=sys.stderr)
            return 2
        return run(where, [(args[i + 1], "one-off pattern from the command line")])
    adapter = find_adapter(where)
    if adapter is None:
        print(f"ERROR: no {ADAPTER} walking up from {where}", file=sys.stderr)
        return 2
    text = adapter.read_text(encoding="utf-8")
    patterns = parse_patterns(text)
    print(f"gate: adapter {adapter}")
    if not patterns and declares_block(text):
        # A block that exists but parses to nothing would otherwise read as "clean".
        print("ERROR: malformed forbidden_in_diff — expected items like\n"
              '  - pattern: "regex"\n    why: "reason"', file=sys.stderr)
        return 2
    if not patterns:
        print("gate: adapter declares no forbidden_in_diff — nothing to check, clean")
        return 0
    return run(where, patterns)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 — a traceback exits 1, which means "hit"
        print(f"ERROR: gate crashed: {exc!r}", file=sys.stderr)
        sys.exit(2)
