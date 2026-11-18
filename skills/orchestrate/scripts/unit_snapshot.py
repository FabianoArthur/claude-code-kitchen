#!/usr/bin/env python3
"""
unit_snapshot — a dispatch-time snapshot of what a unit is allowed to do.

Why it exists: the task doc lives in the unit's worktree, and the unit can edit it. If the
guard, the prover or the publisher read permissions from the doc, a unit could grant itself
more. So the waiter reads the doc ONCE, at dispatch, and writes the permissions to
`~/.claude/kitchen-units/<ID>.json`, outside the worktree. Everything else reads the snapshot.

Usage:
    python3 unit_snapshot.py write <doc> --unit ID --worktree PATH --manifest PATH
                             [--branch B] [--branch-regex RE] [--launch FILE] [--prompt FILE]
                             [--approve-escalation]
    python3 unit_snapshot.py show ID
    python3 unit_snapshot.py --selftest

As a module: `load(unit_id)` returns the snapshot dict, or None when the file is missing,
is not valid JSON, has `schema` != 1 or names a different unit. Callers treat None as
"apply the most restrictive policy".

`KITCHEN_UNITS_DIR` replaces the default folder (tests use it).

Validation (exit 2, nothing written, the stderr line names the field): `model_exec` must be
`haiku`, `sonnet` or `opus`; `branch` must match `--branch-regex` (the adapter's
`branch_regex`; the default is the pattern of the execute skill, Step 2); every `mcp` name
must match the tool-name pattern of `mcp_config.py`; every `files` path (the list under the
doc's `## Blast radius` heading) must be relative to the repo root, without `..`. No field
may hold a control character (ESC included).

Escalation: rewriting an existing snapshot is refused (exit 3, difference on stderr,
nothing written) when it widens the unit's authority: `allow_config` or `allow_ci` false ->
true, a new `files` path, a new
`mcp` server, `proof` or `double_proof` true -> false, or a change of `model_exec`,
`worktree`, `task_doc`, `manifest` or `branch`. Only the waiter passes
`--approve-escalation`, after showing the difference to the human. Reductions and changes
of `sha256`, `written_at` or the file hashes pass. The difference is printed one field per
line, as `name: ascii(old) -> ascii(new)`, with no free text taken from the doc.

Exit: 0 = ok · 2 = error · 3 = escalation refused
"""
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 1
ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
TRUE_WORDS = {"yes", "true"}
# Fields whose change, in any direction, counts as an escalation.
MODELS = ("haiku", "sonnet", "opus")
DEFAULT_BRANCH_RE = r"^(feat|fix|perf|refactor|chore|docs)/[a-zA-Z0-9][a-zA-Z0-9._/-]*$"
MCP_NAME_RE = re.compile(r"^mcp__[A-Za-z0-9_-]+__([A-Za-z0-9_-]+|\*)$")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
NOTE_RE = re.compile(r"\s+(\(.*\)|\[new\])\s*$")
IDENTITY_FIELDS = ("model_exec", "worktree", "task_doc", "manifest", "branch")


class SnapshotError(Exception):
    pass


def units_dir():
    env = os.environ.get("KITCHEN_UNITS_DIR")
    return Path(env) if env else Path.home() / ".claude" / "kitchen-units"


def check_id(unit_id):
    if not isinstance(unit_id, str) or not ID_RE.match(unit_id) or unit_id in (".", ".."):
        raise SnapshotError(f"invalid unit id {unit_id!r} (allowed: letters, digits, . _ -)")
    return unit_id


def snapshot_path(unit_id):
    return units_dir() / f"{check_id(unit_id)}.json"


def load(unit_id):
    """The snapshot of `unit_id`, or None if absent, unreadable or inconsistent."""
    try:
        data = json.loads(snapshot_path(unit_id).read_text(encoding="utf-8"))
    except (SnapshotError, OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or data.get("unit") != unit_id:
        return None
    return data


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_frontmatter(text):
    """Top-level `key: value` pairs of the leading `---` block; block lists become lists."""
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields, key = {}, None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        item = re.match(r"^\s+-\s*(.*?)\s*$", line)
        if item and key is not None:
            if not isinstance(fields.get(key), list):
                fields[key] = []
            fields[key].append(item.group(1))
            continue
        pair = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*?)\s*$", line)
        if pair:
            key = pair.group(1)
            fields[key] = pair.group(2)
    return fields


def _unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def as_bool(value):
    """Only `yes` / `true` (any case, optionally quoted) are true; anything else is false."""
    return isinstance(value, str) and _unquote(value).lower() in TRUE_WORDS


def as_list(value):
    """`mcp: [a, b]` (inline) or a block of `- a` items; anything else is empty."""
    if isinstance(value, list):
        items = value
    elif isinstance(value, str) and value.strip().startswith("["):
        inner = value.strip()[1:]
        items = inner[:inner.rfind("]")].split(",") if "]" in inner else inner.split(",")
    else:
        items = []
    out = []
    for item in items:
        item = _unquote(item)
        if item and item not in out:
            out.append(item)
    return out


def blast_radius_files(text):
    """Paths listed under the doc's `## Blast radius` heading (`- layer: path  (note) [new]`)."""
    out, inside, level = [], False, 0
    for line in text.lstrip("﻿").splitlines():
        head = HEADING_RE.match(line)
        if head:
            if inside and len(head.group(1)) <= level:
                break
            if not inside and head.group(2).strip().lower() == "blast radius":
                inside, level = True, len(head.group(1))
            continue
        item = re.match(r"^\s*[-*]\s+(.*?)\s*$", line) if inside else None
        if not item:
            continue
        body = item.group(1)
        layer = re.match(r"^[\w.-]+:\s+(.*)$", body)
        if layer:
            body = layer.group(1)
        for _ in range(2):  # a trailing note and a [new] marker may both be present
            body = NOTE_RE.sub("", body)
        body = body.strip().strip("`")
        if body and body not in out:
            out.append(body)
    return out


def _clean(field, value):
    if CONTROL_RE.search(value):
        raise SnapshotError(f"{field}: control character in value {ascii(value)}")
    return value


def validate(model, branch, mcp, files, branch_regex=None):
    """Raises SnapshotError, naming the field, for a value outside the rules."""
    _clean("model_exec", model)
    if model not in MODELS:
        raise SnapshotError(f"model_exec: {ascii(model)} is not one of {', '.join(MODELS)}")
    if branch:
        _clean("branch", branch)
        try:
            pattern = re.compile(branch_regex or DEFAULT_BRANCH_RE)
        except re.error as exc:
            raise SnapshotError(f"branch: invalid --branch-regex ({exc})") from None
        if not pattern.search(branch):
            raise SnapshotError(f"branch: {ascii(branch)} does not match the branch regex")
    for name in mcp:
        _clean("mcp", name)
        if not MCP_NAME_RE.match(name):
            raise SnapshotError(f"mcp: {ascii(name)} is not a valid tool name")
    for path in files:
        _clean("files", path)
        parts = path.replace("\\", "/").split("/")
        if path.startswith(("/", "~", "\\")) or re.match(r"^[A-Za-z]:", path) or ".." in parts:
            raise SnapshotError(f"files: {ascii(path)} must be relative to the repo root, "
                                "without '..'")


def build(doc, unit_id, worktree, manifest, branch=None, launch=None, prompt=None,
          branch_regex=None):
    doc = Path(doc)
    if not doc.is_file():
        raise SnapshotError(f"task doc not found: {doc}")
    fields = parse_frontmatter(doc.read_text(encoding="utf-8"))
    for name, path in (("launch", launch), ("prompt", prompt)):
        if path is not None and not Path(path).is_file():
            raise SnapshotError(f"--{name} file not found: {path}")
    model = fields.get("model_exec")
    model = _unquote(model) if isinstance(model, str) else ""
    mcp = as_list(fields.get("mcp"))
    files = blast_radius_files(doc.read_text(encoding="utf-8"))
    validate(model, branch or "", mcp, files, branch_regex)
    return {
        "schema": SCHEMA,
        "unit": check_id(unit_id),
        "worktree": os.path.realpath(worktree),
        "task_doc": os.path.realpath(doc),
        "manifest": os.path.realpath(manifest),
        "written_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sha256": sha256_file(doc),
        "model_exec": model,
        "proof": as_bool(fields.get("proof")),
        "double_proof": as_bool(fields.get("double_proof")),
        "allow_config": as_bool(fields.get("allow_config")),
        "allow_ci": as_bool(fields.get("allow_ci")),
        "mcp": mcp,
        "files": files,
        "branch": branch or "",
        "launch_sha256": sha256_file(launch) if launch else None,
        "prompt_sha256": sha256_file(prompt) if prompt else None,
    }


def escalations(old, new):
    """Human-readable lines for each way `new` widens the authority of `old`."""
    out = []
    for key in ("allow_config", "allow_ci"):
        if not old.get(key) and new.get(key):
            out.append(f"{key}: {ascii(bool(old.get(key)))} -> {ascii(True)}")
    for key in ("mcp", "files"):
        added = [s for s in new.get(key, []) if s not in old.get(key, [])]
        if added:
            out.append(f"{key}: added {ascii(added)}")
    for key in ("proof", "double_proof"):
        if old.get(key) and not new.get(key):
            out.append(f"{key}: {ascii(True)} -> {ascii(bool(new.get(key)))}")
    for key in IDENTITY_FIELDS:
        if old.get(key) != new.get(key):
            out.append(f"{key}: {ascii(old.get(key))} -> {ascii(new.get(key))}")
    return out


def write_atomic(path, data):
    folder = path.parent
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write(doc, unit_id, worktree, manifest, branch=None, launch=None, prompt=None,
          approve_escalation=False, branch_regex=None):
    """Write the snapshot. Returns (exit_code, message)."""
    new = build(doc, unit_id, worktree, manifest, branch, launch, prompt, branch_regex)
    old = load(unit_id)
    if old is not None:
        diff = escalations(old, new)
        if diff and not approve_escalation:
            return 3, ("escalation refused; pass --approve-escalation after a human "
                       "reviews:\n" + "\n".join(f"  {line}" for line in diff))
    path = snapshot_path(unit_id)
    write_atomic(path, new)
    return 0, str(path)


def parse_args(argv):
    opts, pos, flags = {}, [], set()
    valued = {"--unit", "--worktree", "--manifest", "--branch", "--branch-regex", "--launch",
              "--prompt"}
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in valued:
            if i + 1 >= len(argv):
                raise SnapshotError(f"{arg} needs a value")
            opts[arg[2:]] = argv[i + 1]
            i += 2
        elif arg == "--approve-escalation":
            flags.add(arg)
            i += 1
        elif arg.startswith("--"):
            raise SnapshotError(f"unknown option {arg}")
        else:
            pos.append(arg)
            i += 1
    return pos, opts, flags


def selftest():
    """Exercises the contract in a temporary folder; never touches the real ~/.claude."""
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("PASS" if cond else "FAIL"), name)
        ok = ok and bool(cond)

    saved = os.environ.get("KITCHEN_UNITS_DIR")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        os.environ["KITCHEN_UNITS_DIR"] = str(tmp / "units")
        try:
            doc = tmp / "doc.md"
            doc.write_text("---\nmodel_exec: sonnet\nproof: yes\nallow_config: no\n"
                           "mcp: [mcp__s__a, mcp__s__b]\n---\nbody\n", encoding="utf-8")
            args = dict(unit_id="U-1", worktree=tmp, manifest=tmp / "m.md")
            rc, _ = write(doc, **args)
            snap = load("U-1")
            check("write ok", rc == 0 and snap is not None)
            check("fields", snap and snap["proof"] is True and snap["allow_config"] is False
                  and snap["mcp"] == ["mcp__s__a", "mcp__s__b"] and snap["model_exec"] == "sonnet")
            doc.write_text(doc.read_text().replace("allow_config: no", "allow_config: yes"),
                           encoding="utf-8")
            rc, msg = write(doc, **args)
            check("escalation refused", rc == 3 and "allow_config" in msg)
            check("approved escalation passes",
                  write(doc, approve_escalation=True, **args)[0] == 0)
            check("bad id", load("../x") is None)
            doc.write_text(doc.read_text().replace("model_exec: sonnet", "model_exec: gpt"),
                           encoding="utf-8")
            try:
                write(doc, approve_escalation=True, **args)
                check("invalid model rejected", False)
            except SnapshotError as exc:
                check("invalid model rejected", "model_exec" in str(exc))
        finally:
            if saved is None:
                os.environ.pop("KITCHEN_UNITS_DIR", None)
            else:
                os.environ["KITCHEN_UNITS_DIR"] = saved
    print("\nselftest:", "ALL PASSED" if ok else "FAILED")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    try:
        pos, opts, flags = parse_args(argv)
        if len(pos) == 2 and pos[0] == "write":
            for need in ("unit", "worktree", "manifest"):
                if need not in opts:
                    raise SnapshotError(f"write needs --{need}")
            rc, msg = write(pos[1], opts["unit"], opts["worktree"], opts["manifest"],
                            opts.get("branch"), opts.get("launch"), opts.get("prompt"),
                            "--approve-escalation" in flags, opts.get("branch-regex"))
            print(msg, file=sys.stderr if rc else sys.stdout)
            return rc
        if len(pos) == 2 and pos[0] == "show":
            snap = load(pos[1])
            if snap is None:
                raise SnapshotError(f"no valid snapshot for {pos[1]!r}")
            print(json.dumps(snap, indent=2, sort_keys=True))
            return 0
        raise SnapshotError("usage: unit_snapshot.py write <doc> --unit ID --worktree P "
                            "--manifest P | show ID | --selftest")
    except SnapshotError as exc:
        print(f"unit_snapshot: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
