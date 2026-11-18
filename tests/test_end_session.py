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


# --- sweep by KITCHEN_UNIT after the kill -------------------------------------------------

LINUX_ONLY = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="needs /proc/<pid>/environ")

# Double fork: the parent exits, the grandchild moves to a new session and execs a sleeper that
# records its own pid, so it is an orphan outside the registered tree.
ORPHAN = (
    "import os,sys\n"
    "if os.fork() == 0:\n"
    "    os.setsid()\n"
    "    if os.fork() == 0:\n"
    "        os.execvp('/bin/sh', ['sh', '-c', 'echo $$ > \"$1\"; exec sleep 60', 'sh', sys.argv[1]])\n"
    "    os._exit(0)\n"
    "os.wait()\n"
)


def launch_orphan(tmp_path, name, env, prefix=()):
    """Start a double-forked sleeper with `env`; returns its pid (read from a file it writes)."""
    pidfile = tmp_path / name
    subprocess.run([*prefix, sys.executable, "-c", ORPHAN, str(pidfile)], env=env, check=True, timeout=20)
    end = time.monotonic() + 10
    while time.monotonic() < end:
        if pidfile.exists() and pidfile.read_text().strip():
            return int(pidfile.read_text())
        time.sleep(0.05)
    raise AssertionError("orphan did not start")


def register_root(unit_id):
    root = spawn_reaped(["sleep", "60"], start_new_session=True)
    assert es.register(unit_id, root.pid) == 0
    return root


@LINUX_ONLY
def test_sweep_kills_double_forked_orphan_and_spares_the_rest(logs, tmp_path):
    marked = dict(os.environ, KITCHEN_UNIT="sw1")
    other = dict(os.environ, KITCHEN_UNIT="sw1-other")
    early = launch_orphan(tmp_path, "early", marked)  # marked, but started before the register
    time.sleep(1.2)  # lstart has one-second resolution
    root = register_root("sw1")
    orphan = launch_orphan(tmp_path, "orphan", marked)
    foreign = launch_orphan(tmp_path, "foreign", other)
    scrubbed = launch_orphan(tmp_path, "scrubbed", {}, prefix=["/usr/bin/env", "-i"])
    try:
        assert alive(orphan) and alive(early) and alive(foreign) and alive(scrubbed)  # positive control
        assert es.end("sw1", grace=3) == 0
        assert wait_gone(orphan)
        text = (logs / "end-sw1.log").read_text()
        assert f"sweep: pid={orphan} " in text
        assert f"pid={early} " not in text
        assert alive(early) and alive(foreign)
        assert alive(scrubbed)  # residue: `env -i` drops the mark, so the sweep cannot see it
    finally:
        for pid in (early, foreign, scrubbed, orphan, root.pid):
            try:
                os.kill(pid, 9)
            except OSError:
                pass


@LINUX_ONLY
def test_sweep_with_nothing_found_logs_no_sweep_line(logs):
    root = register_root("sw2")
    try:
        assert es.end("sw2", grace=3) == 0
        text = (logs / "end-sw2.log").read_text()
        assert "killed tree" in text  # the end ran
        assert "sweep" not in text
    finally:
        root.kill()


@LINUX_ONLY
def test_sweep_skips_unreadable_pids_and_never_itself(logs, tmp_path, monkeypatch):
    fake = tmp_path / "proc"
    (fake / "123").mkdir(parents=True)  # no environ file: unreadable, must not stop the loop
    (fake / "abc").mkdir()
    mine = fake / str(os.getpid())
    mine.mkdir()
    (mine / "environ").write_bytes(b"A=1\0KITCHEN_UNIT=sw3\0")
    monkeypatch.setattr(es, "PROC", str(fake))
    assert es._candidates_proc("sw3")[0][0] == os.getpid()  # the scan does see this process...
    assert es.sweep("sw3", 0, grace=1) == []  # ...and the sweep refuses to touch it


FAKE_PS = """#!/bin/sh
cat <<'OUT'
  {pid} {lstart} /usr/bin/sleep 60 PATH=/usr/bin KITCHEN_UNIT=mac1 HOME=/x
  {pid2} {lstart} /usr/bin/sleep 61 KITCHEN_UNIT=mac10
  {pid3} {lstart} /usr/bin/sleep 62 X_KITCHEN_UNIT=mac1
  {pid4} {lstart} /usr/bin/sleep 63 KITCHEN_UNIT=mac1
  garbage line
OUT
"""


def test_macos_branch_with_fake_ps(logs, tmp_path, monkeypatch):
    lstart = "Mon Nov 16 10:00:00 2026"
    script = tmp_path / "ps"
    script.write_text(FAKE_PS.format(pid=11, pid2=12, pid3=13, pid4=14, lstart=lstart))
    script.chmod(0o755)
    monkeypatch.setattr(es, "PS", str(script))
    assert es._candidates_ps("mac1") == [(11, "sleep", lstart), (14, "sleep", lstart)]  # exact token only
    assert es._candidates_ps("mac10") == [(12, "sleep", lstart)]


@LINUX_ONLY
def test_macos_branch_end_to_end_with_fake_ps(logs, tmp_path, monkeypatch):
    victim = spawn_reaped(["sleep", "60"], start_new_session=True)
    spare = spawn_reaped(["sleep", "60"], start_new_session=True)
    try:
        lstart = es.proc_info(victim.pid)[1]
        script = tmp_path / "ps"
        script.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = "-E" ]; then\n'
            f"  echo '{victim.pid} {lstart} /bin/sleep 60 KITCHEN_UNIT=mac2'\n"
            f"  echo '{spare.pid} {lstart} /bin/sleep 60 KITCHEN_UNIT=mac20'\n"
            f"  echo '{spare.pid} {lstart} /bin/sleep 60 X_KITCHEN_UNIT=mac2'\n"
            "else\n"
            '  exec /bin/ps "$@"\n'
            "fi\n"
        )
        script.chmod(0o755)
        monkeypatch.setattr(es, "PS", str(script))
        assert alive(victim.pid)
        found = es.sweep("mac2", es.parse_lstart(lstart), grace=3, backend=es._candidates_ps)
        assert [f[0] for f in found] == [victim.pid]
        assert wait_gone(victim.pid)
        assert alive(spare.pid)
        assert f"sweep: pid={victim.pid} comm=sleep" in (logs / "end-mac2.log").read_text()
    finally:
        victim.kill()
        spare.kill()


def test_parse_lstart():
    assert es.parse_lstart("Mon Nov 16 10:00:00 2026") < es.parse_lstart("Mon Nov  16 10:00:01 2026")
    assert es.parse_lstart("not a date") is None
