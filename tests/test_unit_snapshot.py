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
mcp: [alpha, beta]
---
# body
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
    assert d["mcp"] == ["alpha", "beta"]
    assert d["branch"] == "feat/x"
    assert d["sha256"] == snap.sha256_file(doc)
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
    assert d["allow_config"] is False and d["mcp"] == []
    assert d["launch_sha256"] is None and d["prompt_sha256"] is None


@pytest.mark.parametrize("value,expected", [
    ("yes", True), ("true", True), ("TRUE", True), ("'yes'", True),
    ("no", False), ("false", False), ("1", False), ("sim", False), ("", False)])
def test_allow_config_truthiness(env, value, expected):
    tmp_path, doc = env
    doc.write_text(f"---\nallow_config: {value}\n---\n", encoding="utf-8")
    assert run(tmp_path, doc).returncode == 0
    assert snap.load("U-1")["allow_config"] is expected


def test_mcp_block_list(env):
    tmp_path, doc = env
    doc.write_text("---\nmcp:\n  - one\n  - two\nproof: yes\n---\n", encoding="utf-8")
    assert run(tmp_path, doc).returncode == 0
    d = snap.load("U-1")
    assert d["mcp"] == ["one", "two"] and d["proof"] is True


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
                   .replace("[alpha, beta]", "[alpha, beta, gamma]")
                   .replace("proof: yes", "proof: no")
                   .replace("sonnet", "opus"), encoding="utf-8")
    r = run(tmp_path, doc)
    assert r.returncode == 3
    for needle in ("allow_config", "gamma", "proof", "model_exec"):
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
    doc.write_text(DOC.replace("[alpha, beta]", "[alpha]") + "more text\n", encoding="utf-8")
    r = run(tmp_path, doc)
    assert r.returncode == 0, r.stderr
    new = snap.load("U-1")
    assert new["mcp"] == ["alpha"] and new["sha256"] != old["sha256"]


def test_selftest_runs():
    r = subprocess.run([sys.executable, str(SCRIPT), "--selftest"],
                       capture_output=True, text=True)
    assert r.returncode == 0 and "ALL PASSED" in r.stdout
