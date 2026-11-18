"""mcp_config.py — MCP secrets resolved from the Keychain at server start.

The real Keychain is never touched: `mcp_config.SECURITY` is swapped for a fake script, and the
secret below is invented. The exec path needs fork/exec of scripts, so those tests are POSIX only.
"""
import json
import os
import subprocess
import sys

import pytest

from conftest import ORCH, load

mcp = load(ORCH / "mcp_config.py")
snap = load(ORCH / "unit_snapshot.py")
SCRIPT = ORCH / "mcp_config.py"
POSIX = os.name == "posix"
SECRET = "dummy"

FAKE_SECURITY = """#!{python}
import json, sys
log, store = {log!r}, {store!r}
args = sys.argv[1:]
open(log, "a").write(json.dumps(args) + "\\n")
data = json.load(open(store))
account = args[args.index("-a") + 1] if "-a" in args else ""
if args[:1] != ["find-generic-password"] or args[args.index("-s") + 1] != "kitchen-mcp":
    sys.exit(44)
if account not in data:
    sys.exit(44)
print(data[account])
"""

FAKE_SERVER = """#!{python}
import json, os, sys
json.dump({{"env": dict(os.environ), "argv": sys.argv[1:]}}, open({out!r}, "w"))
"""

LAUNCH = (
    "import sys; sys.path.insert(0, {orch!r}); import mcp_config; "
    "mcp_config.SECURITY = {security!r}; sys.exit(mcp_config.main(sys.argv[1:]))"
)


@pytest.fixture
def kit(tmp_path, monkeypatch):
    monkeypatch.setenv("KITCHEN_UNITS_DIR", str(tmp_path / "units"))
    monkeypatch.delenv("API_KEY", raising=False)
    work = tmp_path / "work"
    work.mkdir()
    out = tmp_path / "server-env.json"
    store = tmp_path / "keychain.json"
    store.write_text(json.dumps({"MY_TOKEN": SECRET}), encoding="utf-8")
    log = tmp_path / "security-calls.log"
    security = tmp_path / "security"
    security.write_text(FAKE_SECURITY.format(python=sys.executable, log=str(log),
                                             store=str(store)), encoding="utf-8")
    security.chmod(0o755)
    server = tmp_path / "server.py"
    server.write_text(FAKE_SERVER.format(python=sys.executable, out=str(out)), encoding="utf-8")
    server.chmod(0o755)
    registry = {"mcpServers": {
        "docs": {"command": str(server), "args": ["--ro"], "env": {"API_KEY": "${MY_TOKEN}"}},
        "lost": {"command": str(server), "env": {"OTHER": "${NOT_STORED}"}},
        "plain": {"command": str(server)},
    }}
    reg = tmp_path / "kitchen-mcp.json"
    reg.write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setenv("KITCHEN_MCP_REGISTRY", str(reg))
    return {"tmp": tmp_path, "work": work, "out": out, "log": log, "security": security,
            "reg": reg, "store": store}


def dispatch(kit, mcp_line, unit="U-1"):
    doc = kit["tmp"] / "doc.md"
    doc.write_text("---\nmodel_exec: sonnet\n" + mcp_line + "\n---\nbody\n", encoding="utf-8")
    rc, msg = snap.write(doc, unit, kit["work"], kit["tmp"] / "m.md", approve_escalation=True)
    assert rc == 0, msg


def launch(kit, *args):
    code = LAUNCH.format(orch=str(ORCH), security=str(kit["security"]))
    return subprocess.run([sys.executable, "-c", code, *args], capture_output=True, text=True,
                          env=os.environ.copy())


def test_write_turns_a_placeholder_server_into_a_wrapper(kit):
    dispatch(kit, "mcp: [mcp__docs__read, mcp__plain__x]")
    r = subprocess.run([sys.executable, str(SCRIPT), "write", "--unit", "U-1"],
                       capture_output=True, text=True, env=os.environ.copy())
    assert r.returncode == 0, r.stderr
    text = (kit["work"] / ".kitchen" / "mcp.json").read_text(encoding="utf-8")
    servers = json.loads(text)["mcpServers"]
    docs = servers["docs"]
    assert docs["command"] == "python3"
    assert docs["args"][0] == str(SCRIPT) and os.path.isabs(docs["args"][0])
    assert docs["args"][1:] == ["run", "U-1", "docs"]
    assert "${" not in text and SECRET not in text and "env" not in docs
    assert "env" not in servers["plain"]  # a server without a secret is untouched


def test_inline_value_is_still_refused(kit):
    reg = json.loads(kit["reg"].read_text(encoding="utf-8"))
    reg["mcpServers"]["docs"]["env"] = {"API_KEY": "sk-live-1"}
    kit["reg"].write_text(json.dumps(reg), encoding="utf-8")
    dispatch(kit, "mcp: [mcp__docs__read]")
    r = subprocess.run([sys.executable, str(SCRIPT), "write", "--unit", "U-1"],
                       capture_output=True, text=True, env=os.environ.copy())
    assert r.returncode == 2 and "inline value" in r.stderr


@pytest.mark.skipif(not POSIX, reason="exec of fake scripts needs POSIX")
def test_run_hands_the_secret_only_to_the_server(kit):
    dispatch(kit, "mcp: [mcp__docs__*]")
    assert SECRET not in os.environ.values()  # the session never had it
    r = launch(kit, "run", "U-1", "docs")
    assert r.returncode == 0, r.stderr
    # positive control first: the server ran and received the secret, with its own args
    seen = json.loads(kit["out"].read_text(encoding="utf-8"))
    assert seen["env"]["API_KEY"] == SECRET
    assert seen["argv"] == ["--ro"]
    calls = [json.loads(line) for line in kit["log"].read_text(encoding="utf-8").splitlines()]
    assert calls == [["find-generic-password", "-s", "kitchen-mcp", "-a", "MY_TOKEN", "-w"]]
    # then the absences: nothing leaked to the session environment, output or argv
    assert SECRET not in os.environ.values() and "API_KEY" not in os.environ
    assert SECRET not in r.stdout + r.stderr
    assert SECRET not in json.dumps(seen["argv"])


@pytest.mark.skipif(not POSIX, reason="exec of fake scripts needs POSIX")
def test_missing_secret_exits_2_naming_the_variable(kit):
    dispatch(kit, "mcp: [mcp__lost__x]")
    r = launch(kit, "run", "U-1", "lost")
    assert r.returncode == 2
    assert "NOT_STORED" in r.stderr and "Keychain" in r.stderr
    # the refusal came from the lookup, and the server never started
    assert json.loads(kit["log"].read_text(encoding="utf-8").splitlines()[0])[4] == "NOT_STORED"
    assert not kit["out"].exists()
    assert SECRET not in r.stdout + r.stderr


@pytest.mark.skipif(not POSIX, reason="exec of fake scripts needs POSIX")
def test_server_outside_the_snapshot_exits_2(kit):
    dispatch(kit, "mcp: [mcp__plain__x]")  # docs is in the registry but not in the snapshot
    r = launch(kit, "run", "U-1", "docs")
    assert r.returncode == 2 and "not in the snapshot" in r.stderr
    assert not kit["log"].exists()  # the Keychain was never asked
    assert not kit["out"].exists()


@pytest.mark.skipif(not POSIX, reason="exec of fake scripts needs POSIX")
def test_unknown_unit_exits_2(kit):
    r = launch(kit, "run", "NOPE-1", "docs")
    assert r.returncode == 2 and "snapshot" in r.stderr
    assert not kit["log"].exists()


def test_read_secret_uses_the_absolute_system_path():
    assert mcp.SECURITY == "/usr/bin/security"
    assert mcp.KEYCHAIN_SERVICE == "kitchen-mcp"
