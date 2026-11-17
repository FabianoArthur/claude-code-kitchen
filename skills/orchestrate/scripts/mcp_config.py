#!/usr/bin/env python3
"""
mcp_config — least-privilege MCP servers for one unit.

Each unit gets only the MCP servers and tools it asked for, and nothing else. The list comes
from the unit's dispatch-time snapshot (`unit_snapshot.load`), never from the task doc, so
editing `mcp:` in the doc after dispatch changes nothing.

Usage:
    python3 mcp_config.py write --unit ID [--registry FILE]
    python3 mcp_config.py --selftest

`write` reads the snapshot's `mcp` list (names like `mcp__server__tool` or `mcp__server__*`),
writes `<worktree>/.kitchen/mcp.json` (mode 0600) with only the requested servers taken from
the registry, and prints the tool names comma-separated for `--allowedTools`. With no `mcp`
in the snapshot it writes nothing and prints nothing.

Registry: `~/.claude/kitchen-mcp.json` (override: `--registry` or `KITCHEN_MCP_REGISTRY`):
    {"mcpServers": {"name": {"command": ..., "args": [...], "env": {...}}}, "deny": ["name"]}
A missing or invalid registry means zero servers. The `deny` list can only add to DENY_ALWAYS.

Refused (exit 2): a malformed tool name; a server that is not in the registry, is in the
registry `deny` list or matches DENY_ALWAYS (by name, command, args or url); any `env` or
`headers` value in a requested server. An inline secret is refused outright, and so is a
`${VAR}` reference: a placeholder must never reach `mcp.json` or the session environment,
so such servers need a wrapper that fetches the secret itself.

Exit: 0 = ok · 2 = error
"""
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import unit_snapshot  # noqa: E402

NAME_RE = re.compile(r"^mcp__[A-Za-z0-9_-]+__([A-Za-z0-9_-]+|\*)$")
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*\}$")
# Messaging and mail servers: a unit must never be able to talk to people. Matched as a
# case-insensitive substring of the server name and of its command, args and url.
DENY_ALWAYS = ("discord", "slack", "telegram", "whatsapp", "teams", "imessage", "sms",
               "twilio", "email", "gmail", "outlook", "smtp", "imap")


class McpError(Exception):
    pass


def default_registry():
    env = os.environ.get("KITCHEN_MCP_REGISTRY")
    return Path(env) if env else Path.home() / ".claude" / "kitchen-mcp.json"


def load_registry(path):
    """(servers, deny) from the registry; ({}, []) when it is missing or invalid."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, []
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        return {}, []
    deny = data.get("deny")
    deny = [d.lower() for d in deny if isinstance(d, str)] if isinstance(deny, list) else []
    return {k: v for k, v in servers.items() if isinstance(v, dict)}, deny


def server_of(tool):
    return tool.split("__")[1]


def denied_by_fixed_list(name, spec):
    args = spec.get("args")
    args = " ".join(str(a) for a in args) if isinstance(args, list) else str(args or "")
    probe = " ".join([name, str(spec.get("command", "")), str(spec.get("url", "")), args])
    probe = probe.lower()
    return next((word for word in DENY_ALWAYS if word in probe), None)


def check_secrets(name, spec):
    for field in ("env", "headers"):
        block = spec.get(field)
        if block is None:
            continue
        if not isinstance(block, dict):
            raise McpError(f"server {name!r}: {field} must be an object")
        for key, value in block.items():
            if isinstance(value, str) and PLACEHOLDER_RE.match(value):
                raise McpError(f"server {name!r}: {field}.{key} is a ${{VAR}} reference; "
                               "it needs a wrapper that fetches the secret itself")
            raise McpError(f"server {name!r}: {field}.{key} holds an inline value "
                           "(secrets must never live in the registry)")


def build(tools, registry):
    """The `mcp.json` content for `tools`; raises McpError on any violation."""
    for tool in tools:
        if not isinstance(tool, str) or not NAME_RE.match(tool):
            raise McpError(f"invalid MCP name {tool!r} (use mcp__server__tool)")
    servers, deny = load_registry(registry)
    chosen = {}
    for tool in tools:
        name = server_of(tool)
        if name in chosen:
            continue
        if name not in servers:
            raise McpError(f"server {name!r} is not in the registry")
        spec = servers[name]
        word = denied_by_fixed_list(name, spec)
        if word:
            raise McpError(f"server {name!r} is always denied (matches {word!r})")
        if name.lower() in deny:
            raise McpError(f"server {name!r} is on the registry deny list")
        check_secrets(name, spec)
        chosen[name] = spec
    return {"mcpServers": chosen}


def write_private(path, text):
    """Write `text` to `path` with mode 0600 through a temporary file in the same folder."""
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".mcp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def write(unit_id, registry=None):
    """Writes `.kitchen/mcp.json` for the unit; returns the tool names (empty = no file)."""
    snap = unit_snapshot.load(unit_id)
    if snap is None:
        raise McpError(f"no valid snapshot for unit {unit_id!r}")
    tools = snap.get("mcp")
    if not tools:
        return []
    if not isinstance(tools, list):
        raise McpError("snapshot field mcp is not a list")
    worktree = snap.get("worktree")
    if not isinstance(worktree, str) or not worktree:
        raise McpError("snapshot has no worktree")
    config = build(tools, registry or default_registry())
    write_private(Path(worktree) / ".kitchen" / "mcp.json",
                  json.dumps(config, indent=2, sort_keys=True) + "\n")
    return list(tools)


def selftest():
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("PASS" if cond else "FAIL"), name)
        ok = ok and bool(cond)

    def refused(tools, registry_text):
        with tempfile.TemporaryDirectory() as tmp:
            reg = Path(tmp) / "reg.json"
            if registry_text is not None:
                reg.write_text(registry_text, encoding="utf-8")
            try:
                build(tools, reg)
            except McpError:
                return True
            return False

    def registry_with(spec):
        return json.dumps({"mcpServers": {"docs": spec}})

    good = registry_with({"command": "docs-server"})
    with tempfile.TemporaryDirectory() as tmp:
        reg = Path(tmp) / "reg.json"
        reg.write_text(good, encoding="utf-8")
        built = build(["mcp__docs__read", "mcp__docs__*"], reg)
        check("build picks requested server", list(built["mcpServers"]) == ["docs"])
    check("bad name refused", refused(["docs__read"], good))
    check("unknown server refused", refused(["mcp__nope__x"], good))
    check("missing registry refused", refused(["mcp__docs__x"], None))
    check("always-denied refused",
          refused(["mcp__docs__x"], registry_with({"command": "x", "args": ["--slack"]})))
    check("inline secret refused",
          refused(["mcp__docs__x"], registry_with({"command": "x", "env": {"K": "abc"}})))
    check("placeholder refused",
          refused(["mcp__docs__x"], registry_with({"command": "x", "env": {"K": "${K}"}})))
    print("\nselftest:", "ALL PASSED" if ok else "FAILED")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    try:
        if len(argv) >= 3 and argv[0] == "write" and argv[1] == "--unit":
            registry = None
            if len(argv) == 5 and argv[3] == "--registry":
                registry = argv[4]
            elif len(argv) != 3:
                raise McpError("usage: mcp_config.py write --unit ID [--registry FILE]")
            tools = write(argv[2], registry)
            if tools:
                print(",".join(tools))
            return 0
        raise McpError("usage: mcp_config.py write --unit ID [--registry FILE] | --selftest")
    except (McpError, unit_snapshot.SnapshotError, OSError) as exc:
        print(f"mcp_config: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
