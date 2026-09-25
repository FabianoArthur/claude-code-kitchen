"""The examples must stay parseable by the scripts that read them."""
import shutil
import subprocess
import sys

from conftest import ORCH, QA, ROOT, load

doctor = load(ORCH / "doctor.py")
gate = load(ORCH / "gate_diff.py")
preflight = load(QA / "qa_preflight.py")
DEMO = ROOT / "examples" / "demo-project"


def test_example_adapter_fields():
    text = (ROOT / "examples" / "adapter.md").read_text()
    assert doctor.field(text, "base") == "main"
    assert doctor.field(text, "worktrees") == ".worktrees"
    assert doctor.field(text, "gh") == "env -u GH_TOKEN gh"
    assert doctor.field(text, "max_parallel") == "3"
    assert gate.parse_patterns(text) == [
        (r"console\.log\(", "debug output must not ship"),
        (r"localhost:\d+", "hard-coded dev URL; use the configured base URL"),
    ]


def test_example_qa_adapter_parses():
    cfg = preflight.parse_qa_md((ROOT / "examples" / "qa.md").read_text())
    assert cfg["local_allowed"] is False
    assert cfg["production"] == "read_zero"
    assert cfg["safe_env"] == ".env.qa"
    assert cfg["forbidden_env"][0]["pattern"] == r"prod-db\.example\.com|sslmode=require"
    assert cfg["import_rule_grep"] == r"createApp\(|AppModule"


def git(*args, cwd):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
                           "-c", "commit.gpgsign=false", *args],
                          cwd=cwd, capture_output=True, text=True, check=True)


def test_demo_files_are_tracked():
    # A local ignore rule once hid the demo's adapter: the test passed from the working
    # tree and failed in CI, where the file did not exist. Check the index, not the disk.
    tracked = subprocess.run(["git", "ls-files", "examples/demo-project"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.split()
    assert "examples/demo-project/.claude/orchestrator.md" in tracked


def test_demo_project_end_to_end_gate(tmp_path):
    repo = tmp_path / "demo"
    shutil.copytree(DEMO, repo, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    git("init", "-q", "-b", "main", cwd=repo)
    git("add", ".", cwd=repo)
    git("commit", "-q", "-m", "baseline", cwd=repo)
    git("update-ref", "refs/remotes/origin/main", "HEAD", cwd=repo)

    report = doctor.diagnose(repo, offline=True)
    assert "orchestrator.md" in report.text()
    assert "origin/main" in report.text()

    tests = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                           cwd=repo, capture_output=True, text=True)
    assert tests.returncode == 0, tests.stdout

    wt = repo / ".worktrees" / "kelvin-support"
    git("worktree", "add", "-q", str(wt), "-b", "feat/kelvin-support", cwd=repo)
    lib = wt / "tempconv" / "__init__.py"
    lib.write_text(lib.read_text() + "\n\ndef celsius_to_kelvin(c):\n    print(c)\n    return c + 273.15\n")
    git("add", ".", cwd=wt)
    r = subprocess.run([sys.executable, str(ORCH / "gate_diff.py"), str(wt)],
                       capture_output=True, text=True)
    assert r.returncode == 1 and "library code must not print" in r.stdout
