"""heavy.py — slot limiter. POSIX only (fcntl, process groups)."""
import os
import signal
import subprocess
import sys
import time

import pytest

pytest.importorskip("fcntl")

from conftest import ORCH, load  # noqa: E402

heavy = load(ORCH / "heavy.py")
SCRIPT = ORCH / "heavy.py"
GRANDCHILD = "sleep 300 & echo $! > \"$PIDFILE\"; wait"


@pytest.fixture
def hdir(tmp_path, monkeypatch):
    d = tmp_path / "heavy"
    monkeypatch.setenv("KITCHEN_HEAVY_DIR", str(d))
    return d


def start(hdir, tmp_path, *args):
    env = dict(os.environ, KITCHEN_HEAVY_DIR=str(hdir), PIDFILE=str(tmp_path / "pid"))
    return subprocess.Popen([sys.executable, str(SCRIPT), *args], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def run(hdir, tmp_path, *args, timeout=30):
    p = start(hdir, tmp_path, *args)
    out, err = p.communicate(timeout=timeout)
    return p.returncode, out, err


def wait_for(cond, secs=10):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def grandchild_pid(tmp_path):
    f = tmp_path / "pid"
    assert wait_for(lambda: f.exists() and f.read_text().strip()), "grandchild never started"
    pid = int(f.read_text())
    assert alive(pid), "control: grandchild must be alive before the kill"
    return pid


def test_limit_default_and_reread(hdir):
    assert heavy.read_limit() == 2
    hdir.mkdir()
    (hdir / "heavy-limit").write_text("1\n")
    assert heavy.read_limit() == 1
    (hdir / "heavy-limit").write_text("0\n")
    assert heavy.read_limit() == 2
    (hdir / "heavy-limit").write_text("nope\n")
    assert heavy.read_limit() == 2


def test_slots_respect_limit_and_reread_each_attempt(hdir):
    hdir.mkdir()
    (hdir / "heavy-limit").write_text("1\n")
    a = heavy.try_slot()
    assert a and a[1] == 1
    assert heavy.try_slot() is None
    (hdir / "heavy-limit").write_text("2\n")
    b = heavy.try_slot()
    assert b and b[1] == 2
    os.close(a[0])
    os.close(b[0])
    again = heavy.try_slot()  # the kernel dropped the locks with the descriptors
    assert again and again[1] == 1
    os.close(again[0])


def test_exit_code_is_passed_through(hdir, tmp_path):
    rc, _, _ = run(hdir, tmp_path, "--", "sh", "-c", "exit 7")
    assert rc == 7
    rc, _, _ = run(hdir, tmp_path, "--", "true")
    assert rc == 0


def test_no_slot_exits_75(hdir, tmp_path):
    hdir.mkdir()
    (hdir / "heavy-limit").write_text("1\n")
    holder = start(hdir, tmp_path, "--", "sh", "-c", GRANDCHILD)
    try:
        pid = grandchild_pid(tmp_path)  # control: the holder really took the slot
        t0 = time.monotonic()
        rc, _, err = run(hdir, tmp_path, "--wait", "1s", "--", "true")
        assert rc == 75 and "no free slot" in err
        assert time.monotonic() - t0 < 10
    finally:
        holder.terminate()
        holder.communicate(timeout=30)
    assert wait_for(lambda: not alive(pid))
    rc, _, _ = run(hdir, tmp_path, "--wait", "5s", "--", "true")
    assert rc == 0, "slot is free again once the holder is gone"


def test_timeout_kills_group_with_grandchild(hdir, tmp_path):
    p = start(hdir, tmp_path, "--timeout", "2s", "--", "sh", "-c", GRANDCHILD)
    pid = grandchild_pid(tmp_path)
    out, err = p.communicate(timeout=30)
    assert p.returncode == 124
    assert wait_for(lambda: not alive(pid)), "grandchild must die with the group"


def test_sigterm_on_wrapper_kills_group_and_passes_code(hdir, tmp_path):
    p = start(hdir, tmp_path, "--", "sh", "-c", GRANDCHILD)
    pid = grandchild_pid(tmp_path)
    p.send_signal(signal.SIGTERM)
    p.communicate(timeout=30)
    assert p.returncode == 128 + signal.SIGTERM  # the shell died of SIGTERM
    assert wait_for(lambda: not alive(pid)), "grandchild must die with the group"


def test_status_lists_slot_pid_and_command(hdir, tmp_path):
    rc, out, _ = run(hdir, tmp_path, "status")
    assert rc == 0 and "no slot busy (limit 2)" in out
    holder = start(hdir, tmp_path, "--", "sh", "-c", GRANDCHILD)
    try:
        pid = grandchild_pid(tmp_path)
        rc, out, _ = run(hdir, tmp_path, "status")
        assert rc == 0
        assert "slot-1: busy" in out
        assert f"pid={holder.pid}" in out
        assert f"pgid={holder.pid}" not in out  # the command has its own group
        assert "pgid=" in out and "sleep 300" in out
    finally:
        holder.terminate()
        holder.communicate(timeout=30)
    assert wait_for(lambda: not alive(pid))
    rc, out, _ = run(hdir, tmp_path, "status")
    assert "no slot busy" in out


def test_usage_errors(hdir, tmp_path):
    assert run(hdir, tmp_path)[0] == 2
    assert run(hdir, tmp_path, "--timeout", "1s")[0] == 2
    assert run(hdir, tmp_path, "--timeout", "1s", "--")[0] == 2


def test_selftest():
    r = subprocess.run([sys.executable, str(SCRIPT), "--selftest"], capture_output=True, text=True)
    assert r.returncode == 0 and "selftest ok" in r.stdout
