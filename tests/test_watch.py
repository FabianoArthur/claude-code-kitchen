"""watch.py — the dotask watcher as one deterministic process (zero tokens)."""
import subprocess
import sys


from conftest import ORCH, load

watch = load(ORCH / "watch.py")

MANIFEST = """---
type: manifest
---
| unit | size | route | state | branch/worktree | PR | session (resume) |
|------|------|-------|-------|-----------------|----|------------------|
| other-21 | S | kitchen | ⏳ waiting on human: tests red | feat/other-21 | | |
| {uid} | M | kitchen | {state} | feat/{uid} | | |
"""


def write(tmp_path, state, uid="task-2"):
    m = tmp_path / "manifest.md"
    m.write_text(MANIFEST.format(uid=uid, state=state), encoding="utf-8")
    wt = tmp_path / "wt"
    (wt / ".kitchen").mkdir(parents=True, exist_ok=True)
    return m, wt


def run(m, wt, alive=True, **kw):
    return watch.watch(wt, "task-2", m, interval=0, _alive=lambda name: alive,
                       _sleep=lambda s: None, **kw)


def test_done_file_wins(tmp_path):
    m, wt = write(tmp_path, "🔄 running")
    (wt / ".kitchen" / "done").write_text("session-id\n")
    assert run(m, wt) == watch.EXIT_DONE


def test_pr_mark_without_done_file(tmp_path):
    m, wt = write(tmp_path, "✅ PR #12")
    assert run(m, wt, alive=False) == watch.EXIT_DONE


def test_waiting_on_human(tmp_path):
    m, wt = write(tmp_path, "⏳ waiting on human: ambiguous order")
    assert run(m, wt) == watch.EXIT_WAITING


def test_aborted(tmp_path):
    m, wt = write(tmp_path, "🚫 aborted: dependency open")
    assert run(m, wt) == watch.EXIT_ABORTED


def test_dead_session_without_done_is_crash(tmp_path):
    m, wt = write(tmp_path, "🔄 running")
    assert run(m, wt, alive=False) == watch.EXIT_CRASH


def test_timeout_with_live_session(tmp_path):
    m, wt = write(tmp_path, "🔄 running")
    assert run(m, wt, max_minutes=0.0) == watch.EXIT_TIMEOUT


def test_missing_manifest_is_an_error_not_silence(tmp_path):
    _, wt = write(tmp_path, "🔄 running")
    assert run(tmp_path / "nope.md", wt) == watch.EXIT_USAGE


def test_row_match_is_exact_not_prefix(tmp_path):
    # `task-2` must not read the ⏳ of `task-21`
    m = tmp_path / "manifest.md"
    m.write_text(MANIFEST.format(uid="task-21", state="⏳ waiting") +
                 "| task-2 | S | kitchen | 🔄 running | feat/task-2 | | |\n", encoding="utf-8")
    wt = tmp_path / "wt"
    (wt / ".kitchen").mkdir(parents=True)
    assert watch.row_state(m.read_text(encoding="utf-8"), "task-2") == "🔄 running"
    assert run(m, wt, max_minutes=0.0) == watch.EXIT_TIMEOUT


def test_keeps_waiting_while_running(tmp_path):
    m, wt = write(tmp_path, "🔄 running")
    calls = {"n": 0}

    def alive(name):
        calls["n"] += 1
        if calls["n"] == 3:
            (wt / ".kitchen" / "done").write_text("sid\n")
        return True

    assert watch.watch(wt, "task-2", m, interval=0, _alive=alive,
                       _sleep=lambda s: None) == watch.EXIT_DONE
    assert calls["n"] >= 3


def test_session_name_uses_prefix(tmp_path):
    m, wt = write(tmp_path, "🔄 running")
    seen = []
    watch.watch(wt, "task-2", m, interval=0, max_minutes=0.0,
                _alive=lambda name: seen.append(name) or True, _sleep=lambda s: None)
    assert seen and seen[0] == "kitchen-task-2"


def test_real_tmux_on_private_socket(tmp_path, private_tmux):
    m, wt = write(tmp_path, "🔄 running")
    subprocess.run(["tmux", "-L", private_tmux, "new-session", "-d", "-s", "kitchen-task-2",
                    "sleep 30"], check=True)
    assert watch.session_alive("kitchen-task-2", socket=private_tmux)
    assert not watch.session_alive("kitchen-task", socket=private_tmux)  # exact match
    subprocess.run(["tmux", "-L", private_tmux, "kill-session", "-t", "=kitchen-task-2"])
    assert watch.watch(wt, "task-2", m, interval=0, socket=private_tmux) == watch.EXIT_CRASH


def test_cli_selftest():
    r = subprocess.run([sys.executable, str(ORCH / "watch.py"), "--selftest"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
