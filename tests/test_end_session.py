"""end_session.py — kill a unit's whole process tree safely, then its tmux session.

POSIX only (killpg, /bin/ps): these tests run on macOS and Linux CI.
"""
import json
import os
import subprocess
import sys
import threading
import time

import pytest

from conftest import ORCH

SCRIPT = ORCH / "end_session.py"
pytestmark = pytest.mark.skipif(os.name != "posix", reason="needs killpg and /bin/ps")

if os.name == "posix":
    from conftest import load

    es = load(SCRIPT)


@pytest.fixture
def logs(tmp_path, monkeypatch):
    d = tmp_path / "logs"
    monkeypatch.setenv("KITCHEN_LOGS_DIR", str(d))
    return d


def spawn_reaped(cmd, **kw):
    """Popen plus a thread that reaps it, so a killed child is not a zombie."""
    p = subprocess.Popen(cmd, **kw)
    threading.Thread(target=p.wait, daemon=True).start()
    return p


def alive(pid):
    """Running, not merely a zombie waiting to be reaped."""
    r = subprocess.run(["/bin/ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True,
                       env=dict(os.environ, LC_ALL="C"))
    stat = r.stdout.strip()
    return r.returncode == 0 and bool(stat) and not stat.startswith("Z")


def wait_gone(pid, timeout=10):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if not alive(pid):
            return True
        time.sleep(0.1)
    return False


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def test_register_records_pid_comm_lstart(logs):
    p = spawn_reaped(["sleep", "60"], start_new_session=True)
    try:
        assert es.register("u1", p.pid) == 0
        reg = json.loads((logs / "u1.pid").read_text())
        assert reg["pid"] == p.pid
        assert reg["comm"].endswith("sleep")
        assert reg["lstart"] == es.proc_info(p.pid)[1] and reg["lstart"]
    finally:
        p.kill()


def test_register_missing_pid_fails(logs):
    assert es.register("u1", 2**22 + 12345) == 1
    assert not (logs / "u1.pid").exists()


def test_end_kills_registered_tree(logs):
    p = spawn_reaped(["sleep", "60"], start_new_session=True)
    es.register("u2", p.pid)
    assert es.end("u2", grace=3) == 0
    assert wait_gone(p.pid)  # positive control: the kill really ran
    assert "killed tree" in (logs / "end-u2.log").read_text()
    assert not (logs / "u2.pid").exists()


def test_recycled_pid_exits_2_and_kills_nothing(logs):
    p = spawn_reaped(["sleep", "60"], start_new_session=True)
    try:
        es.register("u3", p.pid)
        reg = json.loads((logs / "u3.pid").read_text())
        reg["lstart"] = "Mon Jan  1 00:00:00 2001"
        (logs / "u3.pid").write_text(json.dumps(reg))
        r = run("end", "u3")
        assert r.returncode == 2
        assert "recycled" in (logs / "end-u3.log").read_text()  # refusal came from the right place
        time.sleep(0.3)
        assert alive(p.pid)
    finally:
        p.kill()


def test_grandchild_in_new_session_dies_with_living_parent(logs):
    """The child stays alive (sleeps) while its grandchild sits in its own session."""
    script = (
        "import subprocess, sys, time\n"
        "g = subprocess.Popen(['sleep', '60'], start_new_session=True)\n"
        "print(g.pid, flush=True)\n"
        "time.sleep(60)\n"
    )
    child = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True,
                             start_new_session=True)
    threading.Thread(target=child.wait, daemon=True).start()
    grand = int(child.stdout.readline())
    try:
        assert alive(child.pid) and alive(grand)
        es.register("u4", child.pid)
        assert es.end("u4", grace=3) == 0
        assert wait_gone(child.pid)
        assert wait_gone(grand)
    finally:
        for pid in (child.pid, grand):
            try:
                os.kill(pid, 9)
            except ProcessLookupError:
                pass


def test_sigkill_after_grace_for_term_ignoring_child(logs):
    script = "import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\ntime.sleep(60)\n"
    p = spawn_reaped([sys.executable, "-c", script], start_new_session=True)
    time.sleep(0.5)  # let the handler install
    es.register("u5", p.pid)
    assert es.end("u5", grace=1) == 0
    assert wait_gone(p.pid)
    assert "sigkill=yes" in (logs / "end-u5.log").read_text()


class FakeTmux:
    """A `tmux` first on PATH that records its arguments."""

    def __init__(self, tmp_path, monkeypatch):
        bindir = tmp_path / "fakebin"
        bindir.mkdir()
        self.calls = tmp_path / "tmux-calls.txt"
        tmux = bindir / "tmux"
        tmux.write_text(f'#!/bin/sh\necho "$@" >> "{self.calls}"\nexit 0\n')
        tmux.chmod(0o755)
        monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.delenv("KITCHEN_TMUX_SOCKET", raising=False)

    def recorded(self):
        return self.calls.read_text() if self.calls.exists() else ""


@pytest.fixture
def fake_tmux(tmp_path, monkeypatch):
    return FakeTmux(tmp_path, monkeypatch)


@pytest.mark.parametrize("bad", ["../x", "a/b", ".", "..", ""])
def test_invalid_id_never_reaches_tmux_or_the_filesystem(logs, fake_tmux, bad):
    assert run("end", "ok-id").returncode == 0
    assert "kill-session -t =kitchen-ok-id" in fake_tmux.recorded()  # positive control
    before = fake_tmux.recorded()
    r = run("end", bad)
    assert r.returncode in (2, 64)
    if bad:
        assert r.returncode == 2 and "invalid unit id" in r.stdout  # refused by the id rule
    assert fake_tmux.recorded() == before
    assert sorted(p.name for p in logs.iterdir()) == ["end-ok-id.log"]
    assert run("register", bad, "1").returncode in (2, 64)
    assert sorted(p.name for p in logs.iterdir()) == ["end-ok-id.log"]


def test_registration_path_outside_logs_dir_is_refused(logs, tmp_path, fake_tmux):
    logs.mkdir()
    outside = tmp_path / "outside.pid"
    outside.write_text("untouched")
    (logs / "u7.pid").symlink_to(outside)
    p = spawn_reaped(["sleep", "60"])
    try:
        r = run("register", "u7", str(p.pid))
        assert r.returncode == 2 and "outside the logs directory" in r.stdout
        assert outside.read_text() == "untouched"
        r = run("end", "u7")
        assert r.returncode == 2 and "outside the logs directory" in r.stdout
        assert fake_tmux.recorded() == ""  # tmux was not called
        assert alive(p.pid)
        # positive control: the same call with a plain registration file works
        (logs / "u7.pid").unlink()
        assert run("register", "u7", str(p.pid)).returncode == 0
        assert json.loads((logs / "u7.pid").read_text())["pid"] == p.pid
    finally:
        p.kill()


def test_log_path_symlinked_outside_is_refused(logs, tmp_path, fake_tmux):
    logs.mkdir()
    outside = tmp_path / "outside.log"
    outside.write_text("untouched")
    (logs / "end-u8.log").symlink_to(outside)
    r = run("end", "u8")
    assert r.returncode == 2 and "outside the logs directory" in r.stdout
    assert outside.read_text() == "untouched"
    assert fake_tmux.recorded() == ""


def test_logs_dir_itself_may_be_a_symlink(tmp_path, monkeypatch, fake_tmux):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    monkeypatch.setenv("KITCHEN_LOGS_DIR", str(link))
    assert run("end", "u9").returncode == 0
    assert (real / "end-u9.log").exists()


def test_end_kills_tmux_session_and_logs(logs, private_tmux, monkeypatch):
    monkeypatch.setenv("KITCHEN_TMUX_SOCKET", private_tmux)
    subprocess.run(["tmux", "-L", private_tmux, "new-session", "-d", "-s", "kitchen-u6", "sleep 60"],
                   check=True)
    has = ["tmux", "-L", private_tmux, "has-session", "-t", "=kitchen-u6"]
    assert subprocess.run(has).returncode == 0  # positive control
    assert es.end("u6", grace=1) == 0
    assert subprocess.run(has, capture_output=True).returncode != 0
    assert "kill-session =kitchen-u6 -> rc=0" in (logs / "end-u6.log").read_text()


def test_selftest_passes():
    r = run("--selftest")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SELFTEST OK" in r.stdout
