"""mcp_config.py — least-privilege MCP servers per unit."""
import json
import os
import stat
import subprocess
import sys

import pytest

from conftest import ORCH, load

mcp = load(ORCH / "mcp_config.py")
snap = load(ORCH / "unit_snapshot.py")
SCRIPT = ORCH / "mcp_config.py"
POSIX = os.name == "posix"

REGISTRY = {
    "mcpServers": {
        "docs": {"command": "docs-server", "args": ["--ro"]},
        "wiki": {"command": "wiki-server"},
        "chatty": {"command": "bridge", "args": ["--target", "Slack"]},
        "blocked": {"command": "blocked-server"},
        "keyed": {"command": "keyed-server", "env": {"API_KEY": "sk-live-123"}},
        "templated": {"command": "tpl-server", "headers": {"Authorization": "${TOKEN}"}},
    },
    "deny": ["blocked"],
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("KITCHEN_UNITS_DIR", str(tmp_path / "units"))
    reg = tmp_path / "kitchen-mcp.json"
    reg.write_text(json.dumps(REGISTRY), encoding="utf-8")
    monkeypatch.setenv("KITCHEN_MCP_REGISTRY", str(reg))
    work = tmp_path / "work"
    work.mkdir()
    return tmp_path, work, reg


def dispatch(tmp_path, work, mcp_line, unit="U-1"):
    """Writes a snapshot the way the waiter does at dispatch."""
    doc = tmp_path / "doc.md"
    text = "---\nmodel_exec: sonnet\n" + (mcp_line + "\n" if mcp_line else "") + "---\nbody\n"
    doc.write_text(text, encoding="utf-8")
    rc, msg = snap.write(doc, unit, work, tmp_path / "m.md", approve_escalation=True)
    assert rc == 0, msg


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                          env=os.environ.copy())


def test_writes_only_requested_servers_and_prints_allowed_tools(env):
    tmp_path, work, _ = env
    dispatch(tmp_path, work, "mcp: [mcp__docs__read, mcp__docs__search]")
    r = run("write", "--unit", "U-1")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "mcp__docs__read,mcp__docs__search"
    config = json.loads((work / ".kitchen" / "mcp.json").read_text(encoding="utf-8"))
    assert list(config["mcpServers"]) == ["docs"]  # wiki is in the registry but not requested
    assert config["mcpServers"]["docs"] == REGISTRY["mcpServers"]["docs"]


def test_block_list_and_wildcard(env):
    tmp_path, work, _ = env
    dispatch(tmp_path, work, "mcp:\n  - mcp__docs__*\n  - mcp__wiki__get")
    r = run("write", "--unit", "U-1")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "mcp__docs__*,mcp__wiki__get"
    config = json.loads((work / ".kitchen" / "mcp.json").read_text(encoding="utf-8"))
    assert sorted(config["mcpServers"]) == ["docs", "wiki"]


@pytest.mark.skipif(not POSIX, reason="POSIX permission bits")
def test_file_mode_is_0600_and_no_temp_left(env):
    tmp_path, work, _ = env
    dispatch(tmp_path, work, "mcp: [mcp__docs__read]")
    assert run("write", "--unit", "U-1").returncode == 0
    folder = work / ".kitchen"
    assert stat.S_IMODE((folder / "mcp.json").stat().st_mode) == 0o600
    assert [p.name for p in folder.iterdir()] == ["mcp.json"]


def test_changing_the_doc_after_dispatch_changes_nothing(env):
    tmp_path, work, _ = env
    dispatch(tmp_path, work, "mcp: [mcp__docs__read]")
    (tmp_path / "doc.md").write_text("---\nmcp: [mcp__wiki__get]\n---\n", encoding="utf-8")
    r = run("write", "--unit", "U-1")
    assert r.returncode == 0 and r.stdout.strip() == "mcp__docs__read"
    config = json.loads((work / ".kitchen" / "mcp.json").read_text(encoding="utf-8"))
    assert list(config["mcpServers"]) == ["docs"]


@pytest.mark.parametrize("bad", ["docs__read", "mcp__docs", "mcp__docs__", "mcp__do cs__x",
                                 "mcp__docs__a b", "mcp____x", "read"])
def test_bad_name_is_an_error(env, bad):
    tmp_path, work, _ = env
    dispatch(tmp_path, work, f"mcp: [{bad}]")
    r = run("write", "--unit", "U-1")
    assert r.returncode == 2 and "invalid MCP name" in r.stderr
    assert not (work / ".kitchen").exists()


@pytest.mark.parametrize("tool,reason", [
    ("mcp__nope__x", "not in the registry"),
    ("mcp__blocked__x", "registry deny list"),
    ("mcp__chatty__x", "always denied"),
])
def test_denied_servers_are_errors(env, tool, reason):
    tmp_path, work, _ = env
    dispatch(tmp_path, work, f"mcp: [mcp__docs__read, {tool}]")
    r = run("write", "--unit", "U-1")
    assert r.returncode == 2 and reason in r.stderr
    assert not (work / ".kitchen").exists()  # nothing partial


def test_registry_deny_cannot_remove_the_fixed_list(env, monkeypatch):
    tmp_path, work, reg = env
    reg.write_text(json.dumps({"mcpServers": {"discord": {"command": "x"}}, "deny": []}),
                   encoding="utf-8")
    dispatch(tmp_path, work, "mcp: [mcp__discord__send]")
    r = run("write", "--unit", "U-1")
    assert r.returncode == 2 and "always denied" in r.stderr


@pytest.mark.parametrize("word", mcp.DENY_ALWAYS)
def test_every_fixed_word_denies(word):
    assert mcp.denied_by_fixed_list("srv", {"command": "x", "url": f"https://{word.upper()}.example"}) == word


@pytest.mark.parametrize("content", [None, "not json", "[]", '{"mcpServers": 3}'])
def test_missing_or_invalid_registry_means_zero_servers(env, content):
    tmp_path, work, reg = env
    if content is None:
        reg.unlink()
    else:
        reg.write_text(content, encoding="utf-8")
    assert mcp.load_registry(reg) == ({}, [])
    dispatch(tmp_path, work, "mcp: [mcp__docs__read]")
    r = run("write", "--unit", "U-1")
    assert r.returncode == 2 and "not in the registry" in r.stderr
    assert not (work / ".kitchen").exists()


def test_inline_secret_is_an_error_and_never_written(env):
    tmp_path, work, _ = env
    dispatch(tmp_path, work, "mcp: [mcp__keyed__x]")
    r = run("write", "--unit", "U-1")
    assert r.returncode == 2 and "inline value" in r.stderr
    assert "sk-live-123" not in r.stderr + r.stdout
    assert not (work / ".kitchen").exists()


def test_placeholder_is_an_error_and_never_written(env):
    tmp_path, work, _ = env
    dispatch(tmp_path, work, "mcp: [mcp__templated__x]")
    r = run("write", "--unit", "U-1")
    assert r.returncode == 2 and "${VAR} reference" in r.stderr
    assert not (work / ".kitchen").exists()


def test_unrequested_bad_server_does_not_block_others(env):
    tmp_path, work, _ = env
    dispatch(tmp_path, work, "mcp: [mcp__docs__read]")  # keyed/templated are in the registry
    assert run("write", "--unit", "U-1").returncode == 0


def test_snapshot_without_mcp_writes_nothing(env):
    tmp_path, work, _ = env
    dispatch(tmp_path, work, "")
    r = run("write", "--unit", "U-1")
    assert r.returncode == 0 and r.stdout == ""
    assert not (work / ".kitchen").exists()


def test_empty_mcp_list_writes_nothing(env):
    tmp_path, work, _ = env
    dispatch(tmp_path, work, "mcp: []")
    r = run("write", "--unit", "U-1")
    assert r.returncode == 0 and r.stdout == ""
    assert not (work / ".kitchen").exists()


def test_missing_snapshot_is_an_error(env):
    r = run("write", "--unit", "NOPE")
    assert r.returncode == 2 and "no valid snapshot" in r.stderr


def test_registry_flag_overrides_default(env, tmp_path):
    tmp, work, _ = env
    other = tmp / "other.json"
    other.write_text(json.dumps({"mcpServers": {"extra": {"command": "e"}}}), encoding="utf-8")
    dispatch(tmp, work, "mcp: [mcp__extra__go]")
    r = run("write", "--unit", "U-1", "--registry", str(other))
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "mcp__extra__go"


def test_usage_error():
    r = run("write")
    assert r.returncode == 2 and "usage" in r.stderr


def test_selftest_runs():
    r = run("--selftest")
    assert r.returncode == 0 and "ALL PASSED" in r.stdout and "FAIL " not in r.stdout
