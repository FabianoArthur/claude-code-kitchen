"""dispatcher.py, doctor.py and gate_diff.py: selftests plus end-to-end checks."""
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

from conftest import ORCH, load

gate = load(ORCH / "gate_diff.py")
doctor = load(ORCH / "doctor.py")


def sh(*cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True)


@pytest.mark.parametrize("script", ["gate_diff.py", "doctor.py", "watch.py"])
def test_selftests(script):
    r = subprocess.run([sys.executable, str(ORCH / script), "--selftest"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_dispatcher_selftest_uses_private_socket():
    if shutil.which("tmux") is None:
        pytest.skip("tmux not installed")
    sock_dir = tempfile.mkdtemp(prefix="kt-", dir="/tmp")
    env = {k: v for k, v in os.environ.items() if k != "TMUX"}
    env["TMUX_TMPDIR"] = sock_dir
    try:
        r = subprocess.run([sys.executable, str(ORCH / "dispatcher.py"), "--selftest"],
                           capture_output=True, text=True, env=env, timeout=120)
    finally:
        shutil.rmtree(sock_dir, ignore_errors=True)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.fixture
def repo_with_worktree(tmp_path):
    """Adapter at the repo root, diff staged in a worktree below it (the §3a trap)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    ident = ["-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]
    sh("git", "init", "-q", "-b", "main", str(repo))
    (repo / ".claude").mkdir()
    (repo / ".claude" / "orchestrator.md").write_text(
        "```yaml\nbase: main\nforbidden_in_diff:\n"
        '  - pattern: "console\\\\.log\\\\("\n    why: "no debug output"\n```\n')
    (repo / "a.js").write_text("export const a = 1;\n")
    sh("git", "-C", str(repo), "add", ".")
    sh("git", "-C", str(repo), *ident, "commit", "-q", "-m", "base")
    wt = repo / ".worktrees" / "u1"
    sh("git", "-C", str(repo), "worktree", "add", "-q", str(wt), "-b", "feat/u1")
    return repo, wt


def test_gate_fires_in_worktree_and_ignores_comments(repo_with_worktree):
    _, wt = repo_with_worktree
    (wt / "a.js").write_text("export const a = 1;\n// console.log( is banned\nconsole.log(a);\n")
    sh("git", "-C", str(wt), "add", "a.js")
    r = subprocess.run([sys.executable, str(ORCH / "gate_diff.py"), str(wt)],
                       capture_output=True, text=True)
    assert r.returncode == 1, r.stdout
    assert "1 hit" in r.stdout and "no debug output" in r.stdout


def test_gate_clean_when_only_comment_added(repo_with_worktree):
    _, wt = repo_with_worktree
    (wt / "a.js").write_text("export const a = 1;\n// console.log( is banned\n")
    sh("git", "-C", str(wt), "add", "a.js")
    r = subprocess.run([sys.executable, str(ORCH / "gate_diff.py"), str(wt)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_gate_fails_loudly_outside_git(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "orchestrator.md").write_text(
        'forbidden_in_diff:\n  - pattern: "x"\n    why: "y"\n')
    r = subprocess.run([sys.executable, str(ORCH / "gate_diff.py"), str(tmp_path)],
                       capture_output=True, text=True)
    assert r.returncode == 2  # never "clean" when git itself failed


def test_gate_parse_patterns_empty_block():
    assert gate.parse_patterns("base: main\nforbidden_in_diff:\nmax_parallel: 2\n") == []


def test_doctor_reads_english_fields():
    text = "base: main\nworktrees: .worktrees\nmax_parallel: 3\nbacklog:\n  base: nested\n"
    assert doctor.field(text, "base") == "main"
    assert doctor.field(text, "max_parallel") == "3"


# Review round 1: three ways the gate said "clean" when it should fire.
def test_gate_added_line_starting_with_plusplus_is_content():
    diff = "diff --git a/a.js b/a.js\n--- a/a.js\n+++ b/a.js\n@@ -1 +1,2 @@\n+++i; console.log(i)\n"
    assert len(gate.check(gate.parse_added_lines(diff), [(r"console\.log\(", "x")])) == 1


def test_gate_double_dash_is_only_a_comment_in_languages_that_use_it():
    js = "diff --git a/a.js b/a.js\n--- a/a.js\n+++ b/a.js\n@@\n+--n; console.log(n)\n"
    sql = "diff --git a/q.sql b/q.sql\n--- a/q.sql\n+++ b/q.sql\n@@\n+-- console.log( in a comment\n"
    assert len(gate.check(gate.parse_added_lines(js), [(r"console\.log\(", "x")])) == 1
    assert gate.check(gate.parse_added_lines(sql), [(r"console\.log\(", "x")]) == []


def test_gate_malformed_block_is_an_error_not_clean(repo_with_worktree):
    _, wt = repo_with_worktree
    # the adapter is committed, so the worktree has its own copy and walk-up finds it first
    (wt / ".claude" / "orchestrator.md").write_text(
        '```yaml\nbase: main\nforbidden_in_diff:\n  - "console\\\\.log"\n```\n')
    r = subprocess.run([sys.executable, str(ORCH / "gate_diff.py"), str(wt)],
                       capture_output=True, text=True)
    assert r.returncode == 2 and "malformed" in (r.stdout + r.stderr)


def test_gate_pattern_flag_without_value_is_usage_error(tmp_path):
    r = subprocess.run([sys.executable, str(ORCH / "gate_diff.py"), str(tmp_path), "--pattern"],
                       capture_output=True, text=True)
    assert r.returncode == 2 and "Traceback" not in r.stderr
