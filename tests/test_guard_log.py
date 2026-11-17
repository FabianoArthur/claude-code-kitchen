"""Tests for the guard log: secret masking, field limits, Write/Edit privacy, daily rotation."""
import io
import json
import os
import time

import pytest
from conftest import ORCH, load

guard = load(ORCH / "guard.py")

# Invented tokens: the shape of the real thing, never a real value.
FAKE = {
    "github": "ghp_" + "a1B2c3D4e5F6g7H8i9J0",
    "openai": "sk-" + "FAKEFAKEFAKE1234567890",
    "slack": "xoxb-" + "1234567890-FAKEFAKEFAKE",
    "bearer": "Bearer " + "abc.DEF-1234567890.fake",
}


@pytest.fixture
def env(tmp_path):
    return {
        "KITCHEN_SESSION": "1",
        "KITCHEN_UNIT": "U-1",
        "KITCHEN_GUARD_CONFIG": str(tmp_path / "none.json"),
        "KITCHEN_LOG_DIR": str(tmp_path / "logs"),
    }


def call(env, tool, tool_input):
    payload = json.dumps({"tool_name": tool, "tool_input": tool_input})
    return guard.main(env=env, stdin=io.StringIO(payload), stderr=io.StringIO())


def read_log(env, name="guard.jsonl"):
    path = os.path.join(env["KITCHEN_LOG_DIR"], name)
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


@pytest.mark.parametrize("kind", sorted(FAKE))
def test_fake_token_is_masked(env, kind):
    token = FAKE[kind]
    command = f"git push origin main --header {token}"  # a deny carries the command into `detail`
    assert call(env, "Bash", {"command": command}) == 2
    lines = read_log(env)
    assert len(lines) == 1 and lines[0]["rule"] == "push"  # positive control
    assert token.split()[-1] not in json.dumps(lines)
    assert "***" in lines[0]["detail"]


def test_command_summary_is_cut_at_200(env):
    command = "git push origin main " + "x" * 500
    assert call(env, "Bash", {"command": command}) == 2
    line = read_log(env)[0]
    assert line["rule"] == "push"  # positive control: the deny came from the right rule
    assert len(line["detail"]) == 200


def test_long_path_is_cut_at_200(env):
    assert call(env, "Write", {"file_path": "/tmp/" + "d" * 500 + "/f.txt", "content": "hi"}) == 0
    detail = read_log(env)[0]["detail"]
    assert detail.startswith("/tmp/ddd")
    assert detail.endswith(" (2 bytes)")
    assert len(detail) == 200


@pytest.mark.parametrize(
    "tool,tool_input,size",
    [
        ("Write", {"file_path": "/tmp/a.txt", "content": "TOPSECRETBODY"}, 13),
        ("Edit", {"file_path": "/tmp/a.txt", "old_string": "TOPSECRETOLD", "new_string": "TOPSECRETNEW"}, 24),
        ("MultiEdit", {"file_path": "/tmp/a.txt", "edits": [{"old_string": "ab", "new_string": "TOPSECRETcd"}]}, 13),
    ],
)
def test_write_and_edit_never_log_content(env, tool, tool_input, size):
    assert call(env, tool, tool_input) == 0
    lines = read_log(env)
    assert len(lines) == 1  # positive control: the call was logged
    assert "TOPSECRET" not in json.dumps(lines)
    assert lines[0]["detail"] == f"/tmp/a.txt ({size} bytes)"


def test_daily_rotation_with_fake_clock(env, monkeypatch):
    day1 = time.mktime((2026, 3, 10, 12, 0, 0, 0, 0, -1))
    day2 = time.mktime((2026, 3, 11, 0, 5, 0, 0, 0, -1))
    clock = {"t": day1}
    monkeypatch.setattr(guard, "now", lambda: clock["t"])
    live = os.path.join(env["KITCHEN_LOG_DIR"], "guard.jsonl")

    for command in ("git status", "git log"):
        call(env, "Bash", {"command": command})
        os.utime(live, (day1, day1))  # the fake clock does not move the file's mtime
    assert not os.path.exists(os.path.join(env["KITCHEN_LOG_DIR"], "guard-2026-03-10.jsonl"))
    clock["t"] = day2
    call(env, "Bash", {"command": "git diff"})
    old = read_log(env, "guard-2026-03-10.jsonl")
    new = read_log(env)
    assert len(old) == 2 and len(new) == 1
    assert old[0]["ts"].startswith("2026-03-10") and new[0]["ts"].startswith("2026-03-11")


def test_rotation_never_overwrites_an_existing_day(env, monkeypatch):
    directory = env["KITCHEN_LOG_DIR"]
    os.makedirs(directory)
    day1 = time.mktime((2026, 3, 10, 12, 0, 0, 0, 0, -1))
    with open(os.path.join(directory, "guard-2026-03-10.jsonl"), "w", encoding="utf-8") as handle:
        handle.write('{"n": 1}\n')
    live = os.path.join(directory, "guard.jsonl")
    with open(live, "w", encoding="utf-8") as handle:
        handle.write('{"n": 2}\n')
    os.utime(live, (day1, day1))
    monkeypatch.setattr(guard, "now", lambda: day1 + 86400 * 2)
    call(env, "Bash", {"command": "git status"})
    assert [line["n"] for line in read_log(env, "guard-2026-03-10.jsonl")] == [1, 2]
    assert len(read_log(env)) == 1
