#!/usr/bin/env python3
"""
qa_preflight — deterministic /qa environment gate, BEFORE anything runs.

Why it exists: the only reliable barrier against running QA on top of production is grep,
not the model's judgement on each run — an agent gets it right from memory (when it
remembers), and memory is not a rule. The motivating case: a repo whose `.env` points at a
PRODUCTION database and whose scripts boot the whole application, cron jobs included.

Mechanics:
  - finds `<repo>/.claude/qa.md` walking up from <dir> (same walk-up as CORE §1);
  - reads: `forbidden_env[]` (file + grep_pattern + why), `environments.local.allowed`,
    `probe.safe_env`, `probe.import_rule_grep`, `environments.production`;
  - greps each forbidden pattern in its file, and checks that `safe_env`, if declared,
    does NOT match any forbidden pattern;
  - prints the resulting policy (the /qa run pastes it into the report) and exits.

Exit codes:
  0  local probes allowed (safe_env present and clean, or nothing forbidden matched)
  1  NOTHING local STARTS — no server, no database, no INTEGRATION probe.
     Still allowed: the adapter's `tests.allowed` (isolated specs) and read-only HTTP against
     staging. A MOCK-ONLY probe (no env, no database, explicit mocks) is `tests.allowed`,
     not integration — but pass each file through `--probe` first.
  2  a single probe failed (--probe mode)
  3  no `.claude/qa.md` in the repo → bootstrap (references/bootstrap.md), STOP for a human

Usage:
    python3 qa_preflight.py <repo-or-worktree>
    python3 qa_preflight.py <repo> --probe <file>     # validate one probe file
    python3 qa_preflight.py --selftest
"""
import re
import sys
import tempfile
from pathlib import Path


def find_qa_md(start):
    here = Path(start).resolve()
    for p in [here, *here.parents]:
        candidate = p / ".claude" / "qa.md"
        if candidate.is_file():
            return candidate
    return None


def _unescape(pattern):
    """YAML double-quoted escapes: `\\\\.` in the file means the regex `\\.`.

    A single backslash (`mongodb\\+srv`) is kept as is, so both spellings work. Without
    this, a pattern written the YAML way silently means "one or more backslashes" and
    matches nothing — the gate would say the environment is safe.
    """
    return pattern.replace("\\\\", "\\")


def parse_qa_md(text):
    """Extracts only the fields the preflight consumes. A key parser, not a YAML parser."""
    cfg = {"forbidden_env": [], "local_allowed": None,
           "safe_env": None, "import_rule_grep": None, "production": None}
    for m in re.finditer(
            r'\{\s*file:\s*"([^"]+)"\s*,\s*grep_pattern:\s*"([^"]+)"\s*,\s*why:\s*"([^"]+)"\s*\}',
            text):
        cfg["forbidden_env"].append({"file": m.group(1), "pattern": _unescape(m.group(2)),
                                     "why": m.group(3)})
    m = re.search(r'^\s*local:\s*$\s*^\s*allowed:\s*(true|false)', text, re.M)
    if m:
        cfg["local_allowed"] = (m.group(1) == "true")
    m = re.search(r'safe_env:\s*"([^"]+)"', text)
    if m:
        cfg["safe_env"] = m.group(1)
    m = re.search(r'import_rule_grep:\s*"([^"]+)"', text)
    if m:
        cfg["import_rule_grep"] = _unescape(m.group(1))
    m = re.search(r'production:\s*(\S+)', text)
    if m:
        cfg["production"] = m.group(1)
    return cfg


def grep_file(path, pattern):
    try:
        text = Path(path).read_text(errors="replace")
    except OSError:
        return None  # file does not exist → the pattern does not match
    hits = [line for line in text.splitlines()
            if not line.lstrip().startswith("#") and re.search(pattern, line, re.I)]
    return hits or None


def run(repo_dir):
    qa_md = find_qa_md(repo_dir)
    if not qa_md:
        print(f"PREFLIGHT: no .claude/qa.md walking up from {repo_dir}")
        print("→ bootstrap: propose the adapter (references/bootstrap.md) and STOP for a human.")
        return 3
    repo = qa_md.parent.parent
    cfg = parse_qa_md(qa_md.read_text())
    print(f"PREFLIGHT: adapter {qa_md}")
    if cfg["production"]:
        print(f"  production: {cfg['production']} (immutable — not even GET)")

    danger = False
    for rule in cfg["forbidden_env"]:
        if grep_file(repo / rule["file"], rule["pattern"]):
            danger = True
            print(f"  FORBIDDEN to start anything with {rule['file']}: matches "
                  f"/{rule['pattern']}/ — {rule['why']}")

    if cfg["local_allowed"] is False:
        danger = True
        print("  environments.local.allowed: false — local environment vetoed by the adapter")

    if not danger:
        print("  local environment: no forbidden pattern matched")
        return 0

    safe = cfg["safe_env"]
    if safe:
        safe_path = repo / safe
        if not safe_path.is_file():
            print(f"  safe_env {safe}: DOES NOT EXIST — INTEGRATION probes forbidden until a "
                  "human creates it")
            print("POLICY: exit 1 — nothing STARTS. Allowed: tests.allowed (isolated specs),")
            print("  MOCK-ONLY probes validated with --probe, and read-only HTTP against staging.")
            return 1
        for rule in cfg["forbidden_env"]:
            if grep_file(safe_path, rule["pattern"]):
                print(f"  safe_env {safe}: CONTAMINATED (matches /{rule['pattern']}/) — "
                      "probes forbidden")
                print("POLICY: exit 1 — only tests.allowed + HTTP against staging")
                return 1
        print(f"  safe_env {safe}: present and clean — local probes allowed ONLY with it")
        return 0
    print("POLICY: exit 1 — only tests.allowed + HTTP against staging (no safe_env declared)")
    return 1


def validate_probe(repo_dir, path):
    qa_md = find_qa_md(repo_dir)
    if not qa_md:
        print("no qa.md")
        return 3
    pattern = parse_qa_md(qa_md.read_text())["import_rule_grep"]
    if not pattern:
        print("probe: adapter declares no import_rule_grep — ok")
        return 0
    hits = grep_file(path, pattern)
    if hits:
        print(f"PROBE REJECTED: {path} matches /{pattern}/ — {hits[0].strip()[:80]}")
        return 2
    print(f"probe ok: {path} does not match /{pattern}/")
    return 0


def selftest():
    ok = True
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "repo"
        (repo / ".claude").mkdir(parents=True)
        # The .env holds ONLY the `mongodb+srv` signal on purpose: a real first adapter wrote
        # the pattern with the wrong escaping, matched nothing, and the original test hid it
        # because the URL also contained another matching word.
        (repo / ".claude" / "qa.md").write_text(
            'environments:\n  local:\n    allowed: false\n  production: read_zero\n'
            'forbidden_env:\n  - {file: ".env", grep_pattern: "mongodb\\+srv|prod-cluster", why: "production"}\n'
            'probe:\n  safe_env: ".env.qa"\n  import_rule_grep: "AppModule"\n')
        (repo / ".env").write_text("DB_URI=mongodb+srv://user@cluster0.example.net/db\n")
        ok &= run(repo) == 1                       # 1: no safe_env on disk
        (repo / ".env.qa").write_text("DB_URI=mongodb://localhost:27017/qa\n")
        ok &= run(repo) == 0                       # 2: clean safe_env
        (repo / ".env.qa").write_text("DB_URI=mongodb+srv://prod.example.net/db\n")
        ok &= run(repo) == 1                       # 3: contaminated safe_env
        (repo / ".env.qa").write_text("# mongodb+srv commented\nDB_URI=mongodb://localhost/qa\n")
        ok &= run(repo) == 0                       # 4: a comment does not match
        probe = repo / "probe.spec.ts"
        probe.write_text('import { AppModule } from "../src/app.module";\n')
        ok &= validate_probe(repo, probe) == 2     # 5: probe booting the whole app
        probe.write_text('import { BillingModule } from "../src/billing/billing.module";\n')
        ok &= validate_probe(repo, probe) == 0
        ok &= run(td) == 3                         # 6: no qa.md
        # 7: YAML-style double backslash means the same regex as a single one
        cfg = parse_qa_md('forbidden_env:\n  - {file: ".env", grep_pattern: "db\\\\.prod", why: "p"}\n')
        ok &= cfg["forbidden_env"][0]["pattern"] == "db\\.prod"
    print("SELFTEST: " + ("OK" if ok else "FAILED"))
    return 0 if ok else 1


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    if args[0] == "--selftest":
        return selftest()
    if "--probe" in args:
        return validate_probe(args[0], args[args.index("--probe") + 1])
    return run(args[0])


if __name__ == "__main__":
    sys.exit(main())
