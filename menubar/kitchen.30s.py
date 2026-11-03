#!/usr/bin/env python3
# <swiftbar.title>Kitchen</swiftbar.title>
# <swiftbar.version>v0.1.0</swiftbar.version>
# <swiftbar.author>claude-code-kitchen contributors</swiftbar.author>
# <swiftbar.desc>Unit counts by state, one item per unit, and manifest-vs-tmux divergences.</swiftbar.desc>
# <swiftbar.dependencies>python3,tmux</swiftbar.dependencies>
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
# <swiftbar.hideSwiftBar>true</swiftbar.hideSwiftBar>
"""
kitchen — macOS menu-bar widget (SwiftBar plugin) for claude-code-kitchen. Zero tokens.

Reads the batch manifests (docs/manifest.md) and the tmux sessions, and shows:

  title   🍳 🔄2 ⏳1 ✅3        unit counts by state (only the non-zero ones)
  menu    one item per unit, grouped by state; submenu = what the agent is doing right now,
          Open PR / Attach / Copy attach command
  alerts  divergences — the failure modes nobody sees until they look:
            · a live session with no manifest row
            · a 🔄 row whose session is dead and which left no `done` marker (a crash)
            · a live session whose unit already wrote `done` (kill it to free RAM)

It is one standalone, stdlib-only file because SwiftBar runs a copy of it from its plugin
folder: it cannot import watch.py, so the small manifest-row parser lives here too (both
dialects: the public English one and the Portuguese one — the state is read off the emoji).

Configuration: a JSON file, ~/.config/kitchen-menubar/config.json (override the path with the
KITCHEN_MENUBAR_CONFIG environment variable). See docs/menubar.md. The plugin never writes
anything and never lets an error reach the menu bar as a traceback.

Actions (called by the menu items themselves):
    kitchen.30s.py attach <session>     open a terminal attached to the session
    kitchen.30s.py copy <session>       copy the attach command to the clipboard
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SEP = "@@@"  # field separator for `tmux -F`: printable ASCII, so no tmux version rewrites it
TMUX_TIMEOUT = 3
MAX_PANES = 12
MAX_MANIFESTS = 60

DEFAULTS = {
    "socket": None,                  # tmux -L <name>; None = the default server
    "prefixes": ["kitchen-"],        # session-name prefixes that belong to the kitchen
    "manifests": [],                 # globs of manifest files
    "done_markers": [".kitchen/done"],
    "stale_days": 3,                 # ignore all-✅/🚫 manifests older than this
    "worktree_roots": [],            # where relative worktree paths of a manifest resolve
    "pr_url": "",                    # e.g. https://github.com/OWNER/REPO/pull/{n}
    "pr_urls": {},                   # same, per manifest project name
    "terminal": "Terminal",          # Terminal | iTerm | Ghostty
    "tmux": "",                      # path to tmux; empty = look it up
}

EMOJI = {"🚫": "aborted", "✅": "done", "⏳": "waiting", "🔄": "running", "⏸": "queued"}
STATES = ("running", "waiting", "queued", "done", "aborted", "unknown")
ICON = {"running": "🔄", "waiting": "⏳", "queued": "⏸", "done": "✅", "aborted": "🚫", "unknown": "❔"}
TITLE_STATES = ("running", "waiting", "queued", "done")
LABEL = {"waiting": "Waiting on human", "running": "Running", "queued": "Queued",
         "done": "PR open / done", "aborted": "Aborted", "unknown": "Unknown state"}
ATTENTION = "#d9480f,#ff9f0a"

SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
PR_URL_IN_CELL = re.compile(r"https?://[^\s)>\]|]+")
PR_NUMBER = re.compile(r"#(\d+)")
PR_PATH = re.compile(r"/pull/(\d+)")
CHROME = re.compile(r"^\W*(\?\s*)?for shortcuts|^\W*⏵⏵|^\W*(accept edits|bypass permissions)", re.I)


# ------------------------------------------------------------------ config

def config_path():
    env = os.environ.get("KITCHEN_MENUBAR_CONFIG")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".config" / "kitchen-menubar" / "config.json"


def _str_list(value):
    if isinstance(value, str):
        value = [value]
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return [v for v in value if v]
    return None


def load_config(path):
    """(config, warning). A missing file is normal; a bad one falls back to the defaults."""
    import json

    cfg = {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v)
           for k, v in DEFAULTS.items()}
    path = Path(path)
    if not path.is_file():
        return cfg, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("top level must be an object")
    except (OSError, ValueError) as e:
        return cfg, f"config error: {path.name}: {e}"
    bad = []
    for key, value in data.items():
        if key not in DEFAULTS:
            continue
        if key in ("prefixes", "manifests", "done_markers", "worktree_roots"):
            lst = _str_list(value)
            if lst is None:
                bad.append(key)
            else:
                cfg[key] = lst
        elif key in ("socket", "pr_url", "terminal", "tmux"):
            if isinstance(value, str):
                cfg[key] = value or (None if key == "socket" else cfg[key])
            elif value is None and key == "socket":
                cfg[key] = None
            else:
                bad.append(key)
        elif key == "stale_days":
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
                cfg[key] = value
            else:
                bad.append(key)
        elif key == "pr_urls":
            if isinstance(value, dict) and all(isinstance(v, str) for v in value.values()):
                cfg[key] = value
            else:
                bad.append(key)
    warning = ("config error: ignored invalid value for " + ", ".join(bad)) if bad else None
    return cfg, warning


# ------------------------------------------------------------------ manifests

def classify(cell):
    """The unit's state from the emoji in a state cell — identical in both dialects."""
    best, where = "unknown", None
    for emoji, status in EMOJI.items():
        i = cell.find(emoji)
        if i != -1 and (where is None or i < where):
            best, where = status, i
    return best


def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _is_separator(line):
    return bool(re.fullmatch(r"\s*\|?[\s:|-]+\|?\s*", line)) and "-" in line


def _frontmatter(text):
    meta = {}
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for line in lines[1:]:
            if line.strip() == "---":
                break
            key, _, value = line.partition(":")
            if _:
                meta[key.strip().lower()] = value.strip()
    return meta


def _parse_time(value):
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt).timestamp()
        except ValueError:
            continue
    return None


def _column(header, *names):
    for i, h in enumerate(header):
        low = h.lower()
        if any(low == n or low.startswith(n) for n in names):
            return i
    return None


def parse_manifest(text):
    meta = _frontmatter(text)
    out = {"project": meta.get("project") or meta.get("projeto") or "",
           "dispatched": _parse_time(meta.get("dispatched") or meta.get("despachado") or ""),
           "rows": []}
    lines = text.splitlines()
    for i, line in enumerate(lines):
        # a table starts at a row that is directly followed by its separator row
        if not (line.lstrip().startswith("|") and i + 1 < len(lines) and _is_separator(lines[i + 1])
                and not _is_separator(line)):
            continue
        header = _cells(line)
        col = {"state": _column(header, "state", "estado"),
               "size": _column(header, "size", "tam"),
               "route": _column(header, "route", "rota"),
               "branch": _column(header, "branch"),
               "pr": _column(header, "pr")}
        for row_line in lines[i + 2:]:
            if not row_line.lstrip().startswith("|"):
                break
            cells = _cells(row_line)
            if not cells or not cells[0]:
                continue
            out["rows"].append(_row(cells, col))
    return out


def _cell(cells, idx):
    return cells[idx] if idx is not None and idx < len(cells) else ""


def _row(cells, col):
    state_cell = _cell(cells, col["state"])
    if col["state"] is None:
        state_cell = next((c for c in cells[1:] if any(e in c for e in EMOJI)), "")
    status = classify(state_cell)
    reason = ""
    if status in ("waiting", "aborted") and ":" in state_cell:
        reason = state_cell.split(":", 1)[1].strip()
    branch, _, worktree = _cell(cells, col["branch"]).partition("·")
    worktree = worktree.strip()
    if worktree.startswith("("):
        worktree = ""
    pr_cell = _cell(cells, col["pr"])
    pr = pr_url = ""
    m = PR_URL_IN_CELL.search(pr_cell)
    if m:
        pr_url = m.group(0)
        pm = PR_PATH.search(pr_url)
        pr = pm.group(1) if pm else ""
    if not pr:
        m = PR_NUMBER.search(pr_cell) or PR_NUMBER.search(state_cell)
        pr = m.group(1) if m else ""
    return {"unit": cells[0], "size": _cell(cells, col["size"]), "route": _cell(cells, col["route"]),
            "status": status, "state_cell": state_cell, "reason": reason, "branch": branch.strip(),
            "worktree": worktree, "pr": pr, "pr_url": pr_url,
            "project": "", "dispatched": None, "manifest": ""}


def load_rows(cfg, now):
    """Rows of every recent manifest. A unit id seen in several manifests: newest file wins."""
    found = {}
    for pattern in cfg["manifests"]:
        for path in glob.glob(os.path.expanduser(pattern)):
            found[os.path.realpath(path)] = path
    files = []
    for real in found:
        try:
            if os.path.isfile(real):
                files.append((os.path.getmtime(real), real))
        except OSError:
            continue
    files.sort(reverse=True)
    rows, seen = [], set()
    for mtime, path in files[:MAX_MANIFESTS]:
        try:
            with open(path, encoding="utf-8") as fh:
                parsed = parse_manifest(fh.read())
        except (OSError, UnicodeDecodeError):
            continue
        if not parsed["rows"]:
            continue
        all_closed = all(r["status"] in ("done", "aborted") for r in parsed["rows"])
        if all_closed and now - mtime > cfg["stale_days"] * 86400:
            continue
        for r in parsed["rows"]:
            if r["unit"] in seen:
                continue
            seen.add(r["unit"])
            r.update(project=parsed["project"], dispatched=parsed["dispatched"], manifest=path)
            rows.append(r)
    return rows


# ------------------------------------------------------------------ tmux

def _tmux(cfg, *args):
    exe = cfg.get("tmux") or shutil.which(
        "tmux", path=os.pathsep.join([os.environ.get("PATH", ""), "/opt/homebrew/bin",
                                      "/usr/local/bin", "/usr/bin"])) or "tmux"
    return [exe] + (["-L", cfg["socket"]] if cfg.get("socket") else []) + list(args)


def list_sessions(cfg, run=subprocess.run):
    """{'ok', 'sessions': [{name, created, path}], 'reason'}. Never raises."""
    fmt = SEP.join(["#{session_name}", "#{session_created}", "#{session_path}"])
    try:
        p = run(_tmux(cfg, "list-sessions", "-F", fmt), capture_output=True, text=True,
                timeout=TMUX_TIMEOUT)
    except FileNotFoundError:
        return {"ok": False, "sessions": [], "reason": "tmux not found"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "sessions": [], "reason": "tmux timed out"}
    except OSError:
        return {"ok": False, "sessions": [], "reason": "tmux failed to start"}
    if p.returncode != 0:
        err = (p.stderr or "").lower()
        if "no server running" in err or "error connecting to" in err or "no sessions" in err:
            return {"ok": True, "sessions": [], "reason": ""}
        return {"ok": False, "sessions": [], "reason": "tmux error"}
    sessions = []
    for line in (p.stdout or "").splitlines():
        parts = line.split(SEP, 2)
        if len(parts) != 3 or not parts[0]:
            continue
        try:
            created = int(parts[1])
        except ValueError:
            continue
        sessions.append({"name": parts[0], "created": created, "path": parts[2]})
    return {"ok": True, "sessions": sessions, "reason": ""}


def clean(text, limit=0):
    """Menu-safe text: no newlines, and no `|` (SwiftBar starts parameters there)."""
    text = re.sub(r"\s+", " ", str(text).replace("|", "¦")).strip()
    if limit and len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def pane_summary(cfg, session, run=subprocess.run):
    """The last useful line on the session's screen, or '' if there is none."""
    try:
        p = run(_tmux(cfg, "capture-pane", "-p", "-J", "-t", f"={session}:"),
                capture_output=True, text=True, timeout=TMUX_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return ""
    if p.returncode != 0:
        return ""
    for line in reversed((p.stdout or "").splitlines()):
        line = line.strip().strip("│┃|").strip()
        if not re.search(r"[A-Za-z0-9]", line) or CHROME.search(line):
            continue
        return clean(line, 80)
    return ""


# ------------------------------------------------------------------ the model

def safe_name(name):
    return bool(SAFE_NAME.match(name or "")) and "\n" not in name


def fmt_age(seconds):
    if seconds is None:
        return ""
    s = int(seconds)
    if s < 60:
        return "<1m"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h{(s % 3600) // 60:02d}"
    return f"{s // 86400}d{(s % 86400) // 3600:02d}h"


def _done_marker(cfg, base, done_exists):
    return bool(base) and any(done_exists(os.path.join(base, m)) for m in cfg["done_markers"])


def _worktree_dirs(cfg, worktree):
    if not worktree:
        return []
    expanded = os.path.expanduser(worktree)
    if os.path.isabs(expanded):
        return [expanded]
    return [os.path.join(os.path.expanduser(r), expanded) for r in cfg["worktree_roots"]]


def build_model(cfg, rows, tmux, now, done_exists=os.path.isfile):
    known = tmux["ok"]
    mine = {}
    for s in tmux["sessions"]:
        if any(s["name"].startswith(p) for p in cfg["prefixes"]):
            mine[s["name"]] = s
    matched = set()
    entries, divergences = [], []
    counts = {k: 0 for k in STATES}
    for r in rows:
        counts[r["status"]] += 1
        session = next((p + r["unit"] for p in cfg["prefixes"] if p + r["unit"] in mine), None)
        alive = session is not None
        if alive:
            matched.add(session)
        if alive:
            dirs = [mine[session]["path"]]
        else:
            dirs = _worktree_dirs(cfg, r["worktree"])
        done = any(_done_marker(cfg, d, done_exists) for d in dirs)
        if alive:
            age = now - mine[session]["created"]
        elif r["dispatched"] and r["status"] in ("running", "waiting"):
            age = now - r["dispatched"]
        else:
            age = None
        entry = dict(r, session=session, alive=alive, done=done, age=age)
        entries.append(entry)
        if not known:
            continue
        if r["status"] == "running" and not alive and not done:
            divergences.append({"kind": "crash", "unit": r["unit"], "session": None,
                                "text": f"{r['unit']}: marked 🔄 but its session is gone and left "
                                        "no done marker (crashed?)"})
        elif alive and done:
            divergences.append({"kind": "reapable", "unit": r["unit"], "session": session,
                                "text": f"{r['unit']}: done — session still alive, "
                                        "can be killed to free RAM"})
    if known:
        for name in mine:
            if name not in matched:
                divergences.append({"kind": "orphan", "unit": name, "session": name,
                                    "text": f"{name}: live session with no manifest row"})
    manifest_dir = ""
    if rows:
        manifest_dir = os.path.dirname(rows[0]["manifest"])
    return {"counts": counts, "entries": entries, "divergences": divergences,
            "tmux_reason": "" if known else tmux["reason"], "manifest_dir": manifest_dir,
            "globs": len(cfg["manifests"])}


# ------------------------------------------------------------------ SwiftBar output

def _q(value):
    value = str(value).replace('"', "")
    return f'"{value}"' if re.search(r"\s", value) else value


def _pr_link(cfg, entry):
    url = entry["pr_url"]
    if not url and entry["pr"]:
        template = cfg["pr_urls"].get(entry["project"]) or cfg["pr_url"]
        if template and "{n}" in template:
            url = template.replace("{n}", entry["pr"])
    return url if re.match(r"https?://", url or "") else ""


def _action(script, verb, session):
    return f"bash={_q(script)} param1={verb} param2={_q(session)} terminal=false refresh=false"


def _session_actions(script, session, prefix="--"):
    return [f"{prefix}Attach | {_action(script, 'attach', session)}",
            f"{prefix}Copy attach command | {_action(script, 'copy', session)}"]


def render(model, cfg, now, script, warning=None, panes=None):
    panes = panes or {}
    counts, divs = model["counts"], model["divergences"]
    title = ["🍳"] + [f"{ICON[s]}{counts[s]}" for s in TITLE_STATES if counts[s]]
    if divs:
        title.append(f"⚠️{len(divs)}")
    head = " ".join(title)
    if counts["waiting"] or divs:
        head += f" | color={ATTENTION}"
    out = [head, "---"]
    if warning:
        out.append(f"⚠️ {clean(warning, 100)} | color=red")
    if model["tmux_reason"]:
        out.append(f"tmux unavailable: {clean(model['tmux_reason'])} — showing manifests only"
                   " | color=gray")
    if divs:
        out.append(f"⚠️ Divergences ({len(divs)}) | size=11 color=gray")
        for d in divs:
            out.append(f"⚠️ {clean(d['text'], 100)}")
            if d["session"] and safe_name(d["session"]):
                out.extend(_session_actions(script, d["session"]))
        out.append("---")
    if not model["entries"]:
        if not model["globs"]:
            out.append("No manifest globs configured — see docs/menubar.md | color=gray")
        else:
            out.append("No manifest rows found (check the globs in the config) | color=gray")
    for status in ("waiting", "running", "queued", "done", "aborted", "unknown"):
        group = [e for e in model["entries"] if e["status"] == status]
        if not group:
            continue
        out.append(f"{LABEL[status]} ({len(group)}) | size=11 color=gray")
        for e in group:
            out.extend(_item(e, cfg, script, panes))
    out.append("---")
    out.append(f"Updated {time.strftime('%H:%M', time.localtime(now))} | color=gray")
    out.append("Refresh now | refresh=true")
    if model["manifest_dir"]:
        out.append(f"Open manifests folder | bash=/usr/bin/open param1={_q(model['manifest_dir'])}"
                   " terminal=false")
    return "\n".join(out)


def _item(e, cfg, script, panes):
    bits = [f"{ICON[e['status']]} {clean(e['unit'])}"]
    if e["project"]:
        bits.append(clean(e["project"]))
    if e["age"] is not None:
        bits.append(fmt_age(e["age"]))
    if e["pr"]:
        bits.append(f"PR #{e['pr']}")
    line = " · ".join(bits)
    if e["reason"]:
        line += " — " + clean(e["reason"], 60)
    lines = [line]
    pane = panes.get(e["session"]) if e["session"] else ""
    if pane:
        lines.append(f"--{pane} | size=11 color=gray")
    link = _pr_link(cfg, e)
    if link:
        lines.append(f"--Open PR #{e['pr']} | href={link}")
    if e["branch"]:
        lines.append(f"--branch: {clean(e['branch'], 60)} | size=11 color=gray")
    if e["alive"] and e["session"] and safe_name(e["session"]):
        lines.extend(_session_actions(script, e["session"]))
    return lines


# ------------------------------------------------------------------ actions

def attach_command(cfg, session):
    sock = f" -L {cfg['socket']}" if cfg.get("socket") else ""
    return f"tmux{sock} attach -t '={session}'"


def _applescript_str(text):
    return text.replace("\\", "\\\\").replace('"', '\\"')


def do_attach(cfg, session, run=subprocess.run):
    if not safe_name(session) or (cfg.get("socket") and not safe_name(cfg["socket"])):
        return False
    cmd = _applescript_str(attach_command(cfg, session))
    terminal = cfg.get("terminal") or "Terminal"
    if terminal == "Terminal":
        argv = ["/usr/bin/osascript", "-e", 'tell application "Terminal"', "-e", "activate",
                "-e", f'do script "{cmd}"', "-e", "end tell"]
    elif terminal == "iTerm":
        argv = ["/usr/bin/osascript", "-e", 'tell application "iTerm"', "-e", "activate",
                "-e", f'create window with default profile command "{cmd}"', "-e", "end tell"]
    elif terminal == "Ghostty":
        tmux = _tmux(cfg, "attach", "-t", f"={session}")
        argv = ["/usr/bin/open", "-na", "Ghostty", "--args", "-e"] + tmux
    else:
        return False
    try:
        return run(argv, capture_output=True, text=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def do_copy(cfg, session, run=subprocess.run):
    if not safe_name(session) or (cfg.get("socket") and not safe_name(cfg["socket"])):
        return False
    try:
        run(["/usr/bin/pbcopy"], input=attach_command(cfg, session), text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return True


# ------------------------------------------------------------------ entry point

def main(argv):
    cfg, warning = load_config(config_path())
    if argv:
        actions = {"attach": do_attach, "copy": do_copy}
        if len(argv) != 2 or argv[0] not in actions:
            print(__doc__)
            return 1
        return 0 if actions[argv[0]](cfg, argv[1]) else 1
    now = time.time()
    try:
        rows = load_rows(cfg, now)
        tmux = list_sessions(cfg)
        model = build_model(cfg, rows, tmux, now)
        panes = {}
        for e in model["entries"]:
            if len(panes) >= MAX_PANES:
                break
            if e["alive"] and not e["done"] and e["status"] in ("running", "waiting"):
                panes[e["session"]] = pane_summary(cfg, e["session"])
        print(render(model, cfg, now, os.path.abspath(__file__), warning=warning, panes=panes))
    except Exception as e:  # the menu bar must never show a traceback
        print(f"🍳\n---\nkitchen plugin error: {clean(type(e).__name__ + ': ' + str(e), 100)}"
              " | color=red")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
