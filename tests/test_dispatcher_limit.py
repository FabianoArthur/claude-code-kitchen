"""dispatcher.py live limit: re-read every pass, `limit get|set|reset`, what counts."""
import os
import shutil
import subprocess
import sys

import pytest
from conftest import ORCH, load

dispatcher = load(ORCH / "dispatcher.py")
PREFIX = "kitchen-"


class FakeTmux:
    """Stands in for the tmux wrapper: `sessions` is whatever the test says is alive."""

    socket = None

    def __init__(self, live=()):
        self.live = list(live)
        self.started = []

    def sessions(self, prefix):
        return [n for n in self.live if n.startswith(prefix) and n != f"{prefix}dispatcher"]

    def alive(self, name):
        return name in self.live


def fake_launch(tmux):
    def launch(_tmux, unit_id, worktree, prefix):
        tmux.live.append(prefix + unit_id)
        tmux.started.append(unit_id)
        return True
    return launch


@pytest.fixture
def limit_file(tmp_path):
    return str(tmp_path / ".kitchen-limit")


@pytest.mark.parametrize("content,expected,origin", [
    ("1\n", 1, "limit file"),
    ("  3  ", 3, "limit file"),
    ("4", 4, "limit file"),
])
def test_valid_file_wins(limit_file, content, expected, origin):
    with open(limit_file, "w") as handle:
        handle.write(content)
    assert dispatcher.effective_limit(limit_file, 4) == (expected, origin)


@pytest.mark.parametrize("content", ["0", "5", "-1", "abc", "", "2.5", "1 2", "9999999"])
def test_invalid_or_out_of_range_falls_back_to_max(limit_file, content):
    with open(limit_file, "w") as handle:
        handle.write(content)
    limit, origin = dispatcher.effective_limit(limit_file, 4)
    assert limit == 4
    assert origin.startswith("--max")


def test_missing_file_falls_back_to_max(limit_file):
    assert dispatcher.effective_limit(limit_file, 3)[0] == 3
    assert dispatcher.effective_limit(None, 3) == (3, "--max")


def test_limit_is_reread_on_every_pass(limit_file, monkeypatch):
    tmux = FakeTmux()
    monkeypatch.setattr(dispatcher, "launch", fake_launch(tmux))
    pending = [(f"u{i}", f"/w/u{i}") for i in range(1, 7)]
    launched = []
    # Pass 1: no file, cap 2 -> two start.
    dispatcher.start_ready(tmux, pending, launched, PREFIX, limit_file, 2)
    assert tmux.started == ["u1", "u2"]
    # Limit drops to 1 mid-run; a slot frees (2 -> 1 alive): nothing new may start.
    with open(limit_file, "w") as handle:
        handle.write("1\n")
    tmux.live.remove("kitchen-u1")
    dispatcher.start_ready(tmux, pending, launched, PREFIX, limit_file, 2)
    assert tmux.started == ["u1", "u2"], "limit 1 with 1 alive must not start anything"
    # The second one finishes: exactly one new session comes up.
    tmux.live.remove("kitchen-u2")
    dispatcher.start_ready(tmux, pending, launched, PREFIX, limit_file, 2)
    assert tmux.started == ["u1", "u2", "u3"]
    # Removing the file restores the cap on the very next pass.
    os.remove(limit_file)
    dispatcher.start_ready(tmux, pending, launched, PREFIX, limit_file, 2)
    assert tmux.started == ["u1", "u2", "u3", "u4"]


def test_proof_and_inspect_sessions_count_toward_the_cap(limit_file, monkeypatch):
    tmux = FakeTmux(["kitchen-proof-A1", "kitchen-inspect-A2"])
    monkeypatch.setattr(dispatcher, "launch", fake_launch(tmux))
    # Positive control: the sessions are really seen and counted...
    assert tmux.sessions(PREFIX) == ["kitchen-proof-A1", "kitchen-inspect-A2"]
    pending = [("B1", "/w/B1")]
    dispatcher.start_ready(tmux, pending, [], PREFIX, limit_file, 2)
    # ...so a cap of 2 is already full and the unit keeps waiting.
    assert tmux.started == [] and pending == [("B1", "/w/B1")]
    # With room for a third the same unit does start (the refusal came from the count).
    dispatcher.start_ready(tmux, pending, [], PREFIX, limit_file, 3)
    assert tmux.started == ["B1"]


def test_tmux_wrapper_counts_proof_and_inspect_but_not_the_dispatcher(monkeypatch):
    class Out:
        returncode = 0
        stdout = ("kitchen-FE-1\nkitchen-proof-FE-1\nkitchen-inspect-FE-1\n"
                  "kitchen-dispatcher\nother\n")

    monkeypatch.setattr(dispatcher.subprocess, "run", lambda *a, **k: Out())
    assert dispatcher.Tmux().sessions(PREFIX) == [
        "kitchen-FE-1", "kitchen-proof-FE-1", "kitchen-inspect-FE-1"]


def test_limit_set_get_reset(limit_file, tmp_path, capsys):
    queue = tmp_path / "queue.tsv"
    done = tmp_path / "w1"
    (done / ".kitchen").mkdir(parents=True)
    (done / ".kitchen" / "done").write_text("x\n")
    queue.write_text(f"A\t{tmp_path}/w0\nB\t{done}\nC\t{tmp_path}/w2\n")
    tmux = FakeTmux(["kitchen-C", "kitchen-proof-Z"])

    def run(action, value=None):
        capsys.readouterr()
        rc = dispatcher.limit_command(action, value, limit_file, 4, PREFIX, tmux, str(queue))
        return rc, dict(line.split(": ", 1) for line in capsys.readouterr().out.splitlines())

    rc, info = run("get")
    assert rc == 0
    assert info == {"limit": "4", "origin": "--max (no limit file)", "running": "2", "waiting": "1"}
    rc, info = run("set", "2")
    assert rc == 0 and info["limit"] == "2" and info["origin"] == "limit file"
    assert open(limit_file).read() == "2\n"
    rc, info = run("reset")
    assert rc == 0 and info["limit"] == "4" and not os.path.exists(limit_file)
    assert run("reset")[0] == 0  # idempotent


@pytest.mark.parametrize("value", [None, "0", "5", "x", "-1"])
def test_limit_set_rejects_bad_values_and_keeps_the_file(limit_file, value, capsys):
    with open(limit_file, "w") as handle:
        handle.write("3\n")
    rc = dispatcher.limit_command("set", value, limit_file, 4, PREFIX, FakeTmux())
    assert rc == 2
    assert "1..4" in capsys.readouterr().err
    assert open(limit_file).read() == "3\n"


def test_limit_cli_without_tmux_server(tmp_path):
    queue = tmp_path / "queue.tsv"
    queue.write_text("")
    base = [sys.executable, str(ORCH / "dispatcher.py"), "limit"]
    tail = ["--queue", str(queue), "--max", "4", "--prefix", "kt-nosuch-"]
    env = {k: v for k, v in os.environ.items() if k != "TMUX"}
    env["TMUX_TMPDIR"] = str(tmp_path)  # no server there: sessions() is empty, not an error
    r = subprocess.run(base + ["set", "3"] + tail, capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert "limit: 3" in r.stdout and "origin: limit file" in r.stdout
    assert (tmp_path / ".kitchen-limit").read_text() == "3\n"  # default sits next to the queue
    r = subprocess.run(base + ["reset"] + tail, capture_output=True, text=True, env=env)
    assert "limit: 4" in r.stdout and not (tmp_path / ".kitchen-limit").exists()
    r = subprocess.run(base + ["bogus"] + tail, capture_output=True, text=True, env=env)
    assert r.returncode == 2


def test_selftest_switches_limit_midrun(private_tmux, tmp_path):
    if shutil.which("sh") is None or os.name == "nt":
        pytest.skip("needs a POSIX host with tmux")
    env = {k: v for k, v in os.environ.items() if k != "TMUX"}
    r = subprocess.run([sys.executable, str(ORCH / "dispatcher.py"), "--selftest"],
                       capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "no new session while 1 is still running" in r.stdout
