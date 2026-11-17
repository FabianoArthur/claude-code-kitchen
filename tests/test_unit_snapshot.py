"""unit_snapshot.py — the dispatch-time snapshot of a unit's permissions."""
import json
import os
import stat
import subprocess
import sys

import pytest

from conftest import ORCH, load

snap = load(ORCH / "unit_snapshot.py")
SCRIPT = ORCH / "unit_snapshot.py"
POSIX = os.name == "posix"

DOC = """---
model_exec: sonnet
proof: yes
double_proof: no
allow_config: no
mcp: [mcp__s__alpha, mcp__s__beta]
allow_ci: no
---
# body

## Blast radius
- api: src/a.py
- tests: tests/test_a.py   [new]

## Notes
- other: not/a/file.py
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("KITCHEN_UNITS_DIR", str(tmp_path / "units"))
    doc = tmp_path / "doc.md"
    doc.write_text(DOC, encoding="utf-8")
    return tmp_path, doc


def run(tmp_path, doc, *extra, unit="U-1"):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "write", str(doc), "--unit", unit,
         "--worktree", str(tmp_path), "--manifest", str(tmp_path / "m.md"), *extra],
        capture_output=True, text=True, env=os.environ.copy())


def test_write_creates_snapshot_with_fields(env):
    tmp_path, doc = env
    launch = tmp_path / "launch.sh"
    launch.write_text("echo hi", encoding="utf-8")
    prompt = tmp_path / "prompt.md"
    prompt.write_text("p", encoding="utf-8")
    r = run(tmp_path, doc, "--branch", "feat/x", "--launch", str(launch), "--prompt", str(prompt))
    assert r.returncode == 0, r.stderr
    d = snap.load("U-1")
    assert d["schema"] == 1 and d["unit"] == "U-1"
    assert d["model_exec"] == "sonnet"
    assert d["proof"] is True and d["double_proof"] is False and d["allow_config"] is False
    assert d["mcp"] == ["mcp__s__alpha", "mcp__s__beta"]
    assert d["branch"] == "feat/x"
    assert d["sha256"] == snap.sha256_file(doc)
    assert d["allow_ci"] is False
    assert d["files"] == ["src/a.py", "tests/test_a.py"]  # stops at the next heading
    assert d["launch_sha256"] == snap.sha256_file(launch)
    assert d["prompt_sha256"] == snap.sha256_file(prompt)
    assert d["written_at"].endswith("Z")


@pytest.mark.skipif(not POSIX, reason="POSIX permission bits")
def test_permissions(env):
    tmp_path, doc = env
    assert run(tmp_path, doc).returncode == 0
    folder = tmp_path / "units"
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert stat.S_IMODE((folder / "U-1.json").stat().st_mode) == 0o600
    assert [p.name for p in folder.iterdir()] == ["U-1.json"]  # no temp file left


@pytest.mark.parametrize("bad", ["a/b", "..", "a b", "x;y", ""])
def test_bad_id_rejected(env, bad):
    tmp_path, doc = env
    r = run(tmp_path, doc, unit=bad)
    assert r.returncode == 2 and "invalid unit id" in r.stderr
    assert not (tmp_path / "units").exists()


def test_missing_fields_default_restrictive(env):
    tmp_path, doc = env
    doc.write_text("---\nmodel_exec: haiku\n---\n", encoding="utf-8")
    assert run(tmp_path, doc).returncode == 0
    d = snap.load("U-1")
    assert d["model_exec"] == "haiku"  # positive control: the doc was parsed
    assert d["proof"] is False and d["double_proof"] is False
    assert d["allow_config"] is False and d["allow_ci"] is False and d["mcp"] == []
    assert d["files"] == []
    assert d["launch_sha256"] is None and d["prompt_sha256"] is None


@pytest.mark.parametrize("value,expected", [
    ("yes", True), ("true", True), ("TRUE", True), ("'yes'", True),
    ("no", False), ("false", False), ("1", False), ("sim", False), ("", False)])
def test_allow_config_truthiness(env, value, expected):
    tmp_path, doc = env
    doc.write_text(f"---\nmodel_exec: opus\nallow_config: {value}\n---\n", encoding="utf-8")
    assert run(tmp_path, doc).returncode == 0
    assert snap.load("U-1")["allow_config"] is expected


def test_mcp_block_list(env):
    tmp_path, doc = env
    doc.write_text("---\nmodel_exec: opus\nmcp:\n  - mcp__s__one\n  - mcp__s__two\nproof: yes\n---\n", encoding="utf-8")
    assert run(tmp_path, doc).returncode == 0
    d = snap.load("U-1")
    assert d["mcp"] == ["mcp__s__one", "mcp__s__two"] and d["proof"] is True


def test_load_rejects_bad_files(env):
    tmp_path, doc = env
    assert snap.load("U-1") is None  # absent
    assert run(tmp_path, doc).returncode == 0
    path = tmp_path / "units" / "U-1.json"
    good = json.loads(path.read_text())
    path.write_text("{not json", encoding="utf-8")
    assert snap.load("U-1") is None
    path.write_text(json.dumps({**good, "schema": 2}), encoding="utf-8")
    assert snap.load("U-1") is None
    path.write_text(json.dumps({**good, "unit": "OTHER"}), encoding="utf-8")
    assert snap.load("U-1") is None
    path.write_text(json.dumps(good), encoding="utf-8")
    assert snap.load("U-1") == good  # positive control: the good file loads


def test_show_prints_snapshot(env):
    tmp_path, doc = env
    assert run(tmp_path, doc).returncode == 0
    r = subprocess.run([sys.executable, str(SCRIPT), "show", "U-1"],
                       capture_output=True, text=True, env=os.environ.copy())
    assert r.returncode == 0 and json.loads(r.stdout)["unit"] == "U-1"
    r = subprocess.run([sys.executable, str(SCRIPT), "show", "NOPE"],
                       capture_output=True, text=True, env=os.environ.copy())
    assert r.returncode == 2


def test_units_dir_env_is_honoured(env):
    tmp_path, doc = env
    assert run(tmp_path, doc).returncode == 0
    assert (tmp_path / "units" / "U-1.json").is_file()


def test_escalation_blocked_on_tampered_doc(env):
    tmp_path, doc = env
    assert run(tmp_path, doc).returncode == 0
    before = (tmp_path / "units" / "U-1.json").read_text()
    doc.write_text(DOC.replace("allow_config: no", "allow_config: yes")
                   .replace("mcp__s__beta]", "mcp__s__beta, mcp__s__gamma]")
                   .replace("proof: yes", "proof: no")
                   .replace("sonnet", "opus"), encoding="utf-8")
    r = run(tmp_path, doc)
    assert r.returncode == 3
    for needle in ("allow_config", "mcp__s__gamma", "proof", "model_exec"):
        assert needle in r.stderr
    assert (tmp_path / "units" / "U-1.json").read_text() == before  # nothing written
    r = run(tmp_path, doc, "--approve-escalation")
    assert r.returncode == 0  # positive control: the same doc passes once approved
    assert snap.load("U-1")["allow_config"] is True


def test_branch_change_is_escalation(env):
    tmp_path, doc = env
    assert run(tmp_path, doc, "--branch", "feat/a").returncode == 0
    r = run(tmp_path, doc, "--branch", "feat/b")
    assert r.returncode == 3 and "branch" in r.stderr


def test_reduction_and_hash_change_pass(env):
    tmp_path, doc = env
    assert run(tmp_path, doc).returncode == 0
    old = snap.load("U-1")
    doc.write_text(DOC.replace(", mcp__s__beta]", "]") + "more text\n", encoding="utf-8")
    r = run(tmp_path, doc)
    assert r.returncode == 0, r.stderr
    new = snap.load("U-1")
    assert new["mcp"] == ["mcp__s__alpha"] and new["sha256"] != old["sha256"]


def test_selftest_runs():
    r = subprocess.run([sys.executable, str(SCRIPT), "--selftest"],
                       capture_output=True, text=True)
    assert r.returncode == 0 and "ALL PASSED" in r.stdout


def stderr_and_nothing_written(tmp_path, r, field):
    assert r.returncode == 2
    assert f"{field}:" in r.stderr
    assert not (tmp_path / "units" / "U-1.json").exists()


def swap(doc, old, new):
    doc.write_text(DOC.replace(old, new), encoding="utf-8")


@pytest.mark.parametrize("field,old,new,extra,good", [
    ("model_exec", "model_exec: sonnet", "model_exec: sonnet\x1b[31m", (), "model_exec: haiku"),
    ("model_exec", "model_exec: sonnet", "model_exec: gpt", (), "model_exec: opus"),
    ("mcp", "mcp__s__beta]", "mcp__s__be\x1bta]", (), "mcp__s__beta]"),
    ("mcp", "mcp__s__beta]", "bad name]", (), "mcp__s__beta]"),
    ("files", "src/a.py", "../x", (), "src/a.py"),
    ("files", "src/a.py", "/etc/passwd", (), "src/a.py"),
    ("files", "src/a.py", "src/../../x", (), "src/a.py"),
    ("files", "src/a.py", "src/a\x1b.py", (), "src/a.py"),
])
def test_invalid_field_exits_2_and_valid_twin_is_written(env, field, old, new, extra, good):
    tmp_path, doc = env
    swap(doc, old, new)
    stderr_and_nothing_written(tmp_path, run(tmp_path, doc, *extra), field)
    swap(doc, old, good)  # positive control: the same snapshot with a valid value is written
    r = run(tmp_path, doc, *extra)
    assert r.returncode == 0, r.stderr
    assert snap.load("U-1") is not None


def test_branch_checked_against_default_and_given_regex(env):
    tmp_path, doc = env
    stderr_and_nothing_written(tmp_path, run(tmp_path, doc, "--branch", "oops/x"), "branch")
    stderr_and_nothing_written(tmp_path, run(tmp_path, doc, "--branch", "feat/x\x1b"), "branch")
    assert run(tmp_path, doc, "--branch", "feat/x").returncode == 0  # default regex accepts
    path = tmp_path / "units" / "U-1.json"
    path.unlink()
    r = run(tmp_path, doc, "--branch", "feat/x", "--branch-regex", r"^task-\d+$")
    stderr_and_nothing_written(tmp_path, r, "branch")
    r = run(tmp_path, doc, "--branch", "task-12", "--branch-regex", r"^task-\d+$")
    assert r.returncode == 0, r.stderr
    assert snap.load("U-1")["branch"] == "task-12"


def test_allow_ci_false_to_true_is_escalation(env):
    tmp_path, doc = env
    assert run(tmp_path, doc).returncode == 0
    before = (tmp_path / "units" / "U-1.json").read_text()
    swap(doc, "allow_ci: no", "allow_ci: yes")
    r = run(tmp_path, doc)
    assert r.returncode == 3 and "allow_ci: False -> True" in r.stderr
    assert (tmp_path / "units" / "U-1.json").read_text() == before
    assert run(tmp_path, doc, "--approve-escalation").returncode == 0
    assert snap.load("U-1")["allow_ci"] is True
    swap(doc, "allow_ci: no", "allow_ci: no")  # true -> false is a reduction
    assert run(tmp_path, doc).returncode == 0
    assert snap.load("U-1")["allow_ci"] is False


def test_files_gain_escalates_and_loss_passes(env):
    tmp_path, doc = env
    assert run(tmp_path, doc).returncode == 0
    swap(doc, "- api: src/a.py\n", "- api: src/a.py\n- api: `src/new.py`  (read only)\n")
    r = run(tmp_path, doc)
    assert r.returncode == 3 and "files: added ['src/new.py']" in r.stderr
    swap(doc, "- api: src/a.py\n", "")  # loses a file: reduction
    r = run(tmp_path, doc)
    assert r.returncode == 0, r.stderr
    assert snap.load("U-1")["files"] == ["tests/test_a.py"]


def test_diff_is_ascii_one_field_per_line(env):
    tmp_path, doc = env
    assert run(tmp_path, doc, "--branch", "feat/a").returncode == 0
    swap(doc, "allow_config: no", "allow_config: yes")
    doc.write_text(doc.read_text() + "free text must not appear" + chr(10),
                   encoding="utf-8")
    r = run(tmp_path, doc, "--branch", "feat/a")
    assert r.returncode == 3
    lines = [ln.strip() for ln in r.stderr.splitlines()[1:]]
    assert lines == ["allow_config: False -> True"]
    assert "free text" not in r.stderr
    r = run(tmp_path, doc, "--branch", "feat/\u00e9", "--approve-escalation")
    assert r.returncode == 2 and "branch:" in r.stderr  # outside the default regex
