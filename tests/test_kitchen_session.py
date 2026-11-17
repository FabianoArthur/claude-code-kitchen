"""kitchen_session.py: slots, minimal environment, stdin prompt, verdict from `result` only."""
import json
import os
import subprocess
import sys

import pytest
from conftest import ORCH, load

ks = load(ORCH / "kitchen_session.py")
SCRIPT = str(ORCH / "kitchen_session.py")
posix_only = pytest.mark.skipif(os.name != "posix", reason="needs a POSIX tmux")

FAKE = """#!{python}
import json, os, sys
data = sys.stdin.buffer.read()
open("seen-stdin.bin", "wb").write(data)
json.dump(sys.argv[1:], open("seen-argv.json", "w"))
json.dump(dict(os.environ), open("seen-env.json", "w"))
open("seen-cwd.txt", "w").write(os.getcwd())
print(json.dumps({{"type": "result", "result": {result}, "is_error": False}}))
"""

NASTY = "run `touch y` then $(touch x) and don't stop; \"quoted\" $HOME\n"


def write_claude(path, result='"SAFE: fine"'):
    path.write_text(FAKE.format(python=sys.executable, result=result))
    path.chmod(0o755)


@pytest.fixture
def kit(tmp_path, private_tmux):
    claude = tmp_path / "claude"
    write_claude(claude)
    prompt = tmp_path / "prompt.txt"
    prompt.write_text(NASTY)
    work = tmp_path / "worktree"
    work.mkdir()
    return {"claude": str(claude), "prompt": str(prompt), "runs": str(tmp_path / "runs"),
            "socket": private_tmux, "work": str(work), "tmp": tmp_path}


def cli(*args):
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, timeout=60)


def start(kit, unit="U1", kind="proof", *extra):
    return cli("start", "--kind", kind, "--unit", unit, "--prompt-file", kit["prompt"],
               "--model", "m", "--claude", kit["claude"], "--add-dir", kit["work"],
               "--socket", kit["socket"], "--runs-dir", kit["runs"], *extra)


def wait(kit, unit="U1", kind="proof", timeout="20"):
    return cli("wait", kind, unit, "--timeout", timeout, "--socket", kit["socket"],
               "--runs-dir", kit["runs"])


def test_extract_result_uses_only_the_result_field():
    assert ks.extract_result('{"type":"result","result":"SAFE","note":"BLOCK"}') == "SAFE"
    assert ks.extract_result('[{"type":"system"},{"type":"result","result":"OK"}]') == "OK"
    assert ks.extract_result("SAFE but not json") is None
    assert ks.extract_result('{"result": ["SAFE"]}') is None
    assert ks.extract_result('{"result": "  "}') is None
    assert ks.extract_result('{"nothing": 1}') is None


def test_minimal_env_has_only_basics_and_kitchen_vars(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    monkeypatch.setenv("PYTHONPATH", "/evil")
    env = ks.minimal_env("inspect", "U9", "/run", "/opt/bin/claude")
    assert set(env) == {"PATH", "HOME", "TMPDIR", "LANG", "KITCHEN_SESSION", "KITCHEN_UNIT",
                        "KITCHEN_KIND", "KITCHEN_RUN_DIR"}
    assert env["KITCHEN_SESSION"] == "1" and env["KITCHEN_UNIT"] == "U9"
    assert env["PATH"].startswith(os.path.abspath("/opt/bin") + os.pathsep)


def test_claude_argv_is_a_list_without_the_prompt():
    argv = ks.claude_argv("/c/claude", "opus", ["/w1", "/w2"])
    assert argv[0] == "/c/claude" and "-p" in argv
    assert argv[argv.index("--setting-sources") + 1] == "user"
    assert argv.count("--add-dir") == 2 and "/w2" in argv
    assert argv[argv.index("--disallowedTools") + 1] == "Edit Write NotebookEdit"


@pytest.mark.parametrize("unit", ["../x", "a b", "-rf"])
def test_start_refuses_bad_unit_id(tmp_path, unit):
    prompt = tmp_path / "p.txt"
    prompt.write_text("x")
    r = cli("start", "--kind", "proof", "--unit", unit, "--prompt-file", str(prompt),
            "--model", "m", "--claude", "/bin/true", "--runs-dir", str(tmp_path / "runs"))
    assert r.returncode == 2
    assert not (tmp_path / "runs").exists()


@posix_only
def test_start_runs_claude_with_minimal_env_and_stdin_prompt(kit):
    r = start(kit)
    assert r.returncode == 0, r.stderr
    w = wait(kit)
    assert w.returncode == 0, w.stdout
    rundir = ks.run_dir("proof", "U1", kit["runs"])
    # positive control: the fake claude really ran, so the absences below mean something
    assert open(os.path.join(rundir, "seen-stdin.bin"), "rb").read() == NASTY.encode()
    assert not os.path.exists(os.path.join(rundir, "x")) and not os.path.exists(os.path.join(rundir, "y"))
    assert not (kit["tmp"] / "x").exists() and not (kit["tmp"] / "y").exists()
    argv = json.load(open(os.path.join(rundir, "seen-argv.json")))
    assert all("touch" not in a for a in argv)
    assert argv[argv.index("--add-dir") + 1] == kit["work"]
    env = json.load(open(os.path.join(rundir, "seen-env.json")))
    assert env["KITCHEN_SESSION"] == "1" and env["KITCHEN_UNIT"] == "U1" and env["KITCHEN_KIND"] == "proof"
    extras = set(env) - {"PATH", "HOME", "TMPDIR", "LANG", "LC_CTYPE", "PWD", "SHLVL", "_",
                         "KITCHEN_SESSION", "KITCHEN_UNIT", "KITCHEN_KIND", "KITCHEN_RUN_DIR"}
    assert not extras
    assert os.path.realpath(open(os.path.join(rundir, "seen-cwd.txt")).read()) == os.path.realpath(rundir)


@posix_only
def test_modes_and_verdict_file(kit):
    assert start(kit, "U2", "inspect").returncode == 0
    assert wait(kit, "U2", "inspect").returncode == 0
    rundir = ks.run_dir("inspect", "U2", kit["runs"])
    assert oct(os.stat(rundir).st_mode & 0o777) == "0o700"
    assert oct(os.stat(os.path.join(rundir, "verdict.json")).st_mode & 0o777) == "0o600"
    assert oct(os.stat(os.path.join(rundir, "prompt.md")).st_mode & 0o777) == "0o600"
    assert json.load(open(os.path.join(rundir, "verdict.json")))["result"] == "SAFE: fine"


@posix_only
def test_start_waits_for_a_free_slot(kit, tmp_path):
    subprocess.run(["tmux", "-L", kit["socket"], "new-session", "-d", "-s", "kitchen-busy", "sleep 60"],
                   check=True)
    limit = tmp_path / "limit"
    limit.write_text("1\n")
    blocked = start(kit, "U3", "proof", "--max", "4", "--limit-file", str(limit))
    assert blocked.returncode == 3 and "no free slot" in blocked.stderr
    assert not os.path.exists(ks.run_dir("proof", "U3", kit["runs"]))
    limit.write_text("2\n")  # control: the same call works once the limit allows it
    assert start(kit, "U3", "proof", "--max", "4", "--limit-file", str(limit)).returncode == 0
    assert wait(kit, "U3").returncode == 0


@posix_only
def test_wait_gives_null_without_a_verdict(kit):
    r = wait(kit, "NONE", timeout="1")
    assert r.returncode == 1 and r.stdout.strip() == "null"


@posix_only
def test_non_string_result_is_null(kit):
    write_claude(kit["tmp"] / "claude", result="12345")
    assert start(kit, "U4").returncode == 0
    r = wait(kit, "U4", timeout="20")
    assert r.returncode == 1 and r.stdout.strip() == "null"
    rundir = ks.run_dir("proof", "U4", kit["runs"])
    assert os.path.exists(os.path.join(rundir, "seen-stdin.bin"))  # claude did run
    assert not os.path.exists(os.path.join(rundir, "verdict.json"))


def test_selftest_flag():
    r = subprocess.run([sys.executable, SCRIPT, "--selftest"], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
