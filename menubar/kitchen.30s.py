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

  title   a flame SF Symbol + running / waiting counts (▸2 !1); the symbol turns orange when a
          unit waits on you and red on a divergence — nothing else is added to the bar
  menu    one item per unit, grouped by state, with a gray metadata line under its name;
          submenu = what the agent is doing right now, Open PR / Attach / Copy attach command
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
    "stale_days": 3,                 # ignore manifests with no active row older than this
    "max_age_days": 0,               # ignore ANY manifest older than this (0 = never)
    "worktree_roots": [],            # where relative worktree paths of a manifest resolve
    "pr_url": "",                    # e.g. https://github.com/OWNER/REPO/pull/{n}
    "pr_urls": {},                   # same, per manifest project name
    "terminal": "Terminal",          # Terminal | iTerm | Ghostty
    "tmux": "",                      # path to tmux; empty = look it up
}

# 🧹 "harvested" is the post-merge state some manifests use once a unit is cleaned up
EMOJI = {"🚫": "aborted", "✅": "done", "⏳": "waiting", "🔄": "running", "⏸": "queued",
         "🧹": "harvested"}
STATES = ("running", "waiting", "queued", "done", "aborted", "harvested", "unknown")
ACTIVE = ("running", "waiting", "queued")
# SF Symbol per state (group header) and the colour that carries its meaning. Colours are
# "light,dark" pairs so they read on both menu appearances.
SYMBOL = {"running": "play.fill", "waiting": "hand.raised.fill", "queued": "hourglass",
          "done": "checkmark.circle.fill", "aborted": "xmark.circle", "harvested": "archivebox",
          "unknown": "questionmark.circle"}
TONE = {"running": "#0a60d0,#4da3ff", "waiting": "#c25400,#ff9f0a", "queued": "#6e6e73,#98989d",
        "done": "#1f8a3b,#32d74b", "aborted": "#6e6e73,#98989d", "harvested": "#6e6e73,#98989d",
        "unknown": "#6e6e73,#98989d", "attention": "#d70015,#ff453a"}
MUTED = "#6e6e73,#98989d"
LABEL = {"waiting": "Waiting on you", "running": "Running", "queued": "Queued",
         "done": "Done", "aborted": "Aborted", "harvested": "Harvested",
         "unknown": "Unknown state"}
DONE_RECENT = 86400   # finished units whose manifest changed longer ago than this fold away

SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
PR_URL_IN_CELL = re.compile(r"https?://[^\s)>\]|]+")
PR_NUMBER = re.compile(r"#(\d+)")
PR_PATH = re.compile(r"/pull/(\d+)")
# Claude Code's own screen furniture: hint line, mode line, the spinner ("✶ Wandering… (8m)")
CHROME = re.compile(r"^\W*(\?\s*)?for shortcuts|^\W*⏵⏵|^\W*(accept edits|bypass permissions)"
                    r"|^[✶✻✽✢✳·*]\s", re.I)


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
        elif key in ("stale_days", "max_age_days"):
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
            "project": "", "dispatched": None, "manifest": "", "mtime": None}


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
        age_days = (now - mtime) / 86400
        no_active_row = not any(r["status"] in ACTIVE for r in parsed["rows"])
        if (no_active_row and age_days > cfg["stale_days"]) or \
                (cfg["max_age_days"] and age_days > cfg["max_age_days"]):
            continue
        for r in parsed["rows"]:
            if r["unit"] in seen:
                continue
            seen.add(r["unit"])
            r.update(project=parsed["project"], dispatched=parsed["dispatched"], manifest=path,
                     mtime=mtime)
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
                                "text": f"{r['unit']}: marked running but its session is gone and left "
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


def _line(text, depth=0, **params):
    """One menu line: `<--*>text | k=v …`. Empty params are dropped; an empty text gives an
    image-only item (`| sfimage=flame`)."""
    rest = " ".join(f"{k}={_q(v)}" for k, v in params.items() if v not in (None, ""))
    text = "--" * depth + text
    if not rest:
        return text
    return f"{text} | {rest}" if text else f"| {rest}"


def _sym(symbol, tone):
    return {"sfimage": symbol, "sfcolor": TONE.get(tone, tone)}


def _muted(text, depth=0, **params):
    return _line(text, depth, size=11, color=MUTED, **params)


def _pr_link(cfg, entry):
    url = entry["pr_url"]
    if not url and entry["pr"]:
        template = cfg["pr_urls"].get(entry["project"]) or cfg["pr_url"]
        if template and "{n}" in template:
            url = template.replace("{n}", entry["pr"])
    return url if re.match(r"https?://", url or "") else ""


def _action(script, verb, session):
    return f"bash={_q(script)} param1={verb} param2={_q(session)} terminal=false refresh=false"


def _session_actions(script, session, depth=1):
    pre = "--" * depth
    return [f"{pre}Attach | sfimage=terminal {_action(script, 'attach', session)}",
            f"{pre}Copy attach command | sfimage=doc.on.doc {_action(script, 'copy', session)}"]


def title_line(model):
    """Menu-bar title: flame symbol + (running, waiting) counts. Colour/symbol carry the alarm."""
    counts = model["counts"]
    if model["divergences"]:
        symbol, tone = "exclamationmark.triangle.fill", "attention"
    elif counts["waiting"]:
        symbol, tone = "flame.fill", "waiting"
    elif counts["running"]:
        symbol, tone = "flame.fill", None
    else:
        symbol, tone = "flame", None
    bits = []
    if counts["running"]:
        bits.append(f"▸{counts['running']}")
    if counts["waiting"]:
        bits.append(f"!{counts['waiting']}")
    color = TONE[tone] if tone else None
    return _line(" ".join(bits), sfimage=symbol, sfcolor=color, color=color)


def render(model, cfg, now, script, warning=None, panes=None):
    panes = panes or {}
    divs = model["divergences"]
    out = [title_line(model), "---"]
    if warning:
        out.append(_line(clean(warning, 100), **_sym("exclamationmark.triangle.fill", "attention"),
                         color=TONE["attention"]))
    if model["tmux_reason"]:
        out.append(_muted(f"tmux unavailable: {clean(model['tmux_reason'])} — showing manifests only",
                          sfimage="bolt.slash", sfcolor=MUTED))
    if divs:
        out.append(_line(f"Needs attention ({len(divs)})", size=11, color=TONE["attention"],
                         **_sym("exclamationmark.triangle.fill", "attention")))
        for d in divs:
            out.append(_line(clean(d["text"], 100), sfimage="circle.fill", sfcolor=TONE["attention"],
                             sfsize=8))
            if d["session"] and safe_name(d["session"]):
                out.extend(_session_actions(script, d["session"]))
        out.append("---")
    if not model["entries"]:
        hint = ("No manifest globs configured — see docs/menubar.md" if not model["globs"]
                else "No manifest rows found (check the globs in the config)")
        out.append(_muted(hint, sfimage="tray", sfcolor=MUTED))
    for status in ("waiting", "running", "queued", "done", "aborted", "unknown"):
        group = [e for e in model["entries"] if e["status"] == status]
        if not group:
            continue
        older = []
        if status == "done":
            older = [e for e in group if e["mtime"] is not None and now - e["mtime"] > DONE_RECENT]
            group = [e for e in group if e not in older]
        out.append(_line(f"{LABEL[status]} ({len(group) + len(older)})", size=11, color=TONE[status],
                         **_sym(SYMBOL[status], status)))
        for e in group:
            out.extend(_item(e, cfg, script, panes))
        if older:
            out.append(_line(f"Earlier ({len(older)})", **_sym("clock.arrow.circlepath", "done")))
            for e in older:
                link = _pr_link(cfg, e)
                out.append(_line(_title(e, with_pr=True), 1, href=link or None))
    if model["counts"]["harvested"]:
        out.append(_muted(f"{model['counts']['harvested']} harvested (hidden)",
                          **_sym(SYMBOL["harvested"], "harvested")))
    out.append("---")
    out.append(_muted(f"Updated {time.strftime('%H:%M', time.localtime(now))}", sfimage="clock",
                      sfcolor=MUTED))
    out.append(_line("Refresh now", sfimage="arrow.clockwise", refresh="true"))
    if model["manifest_dir"]:
        out.append(_line("Open manifests folder", sfimage="folder", bash="/usr/bin/open",
                         param1=model["manifest_dir"], terminal="false"))
    return "\n".join(out)


def _title(e, with_pr=False):
    text = clean(e["unit"], 48)
    if with_pr and e["pr"]:
        text += f" · PR #{e['pr']}"
    return text


def _item(e, cfg, script, panes):
    """Name line (with its submenu), then a small gray metadata line, then the ⏳ reason."""
    status = e["status"]
    pane = panes.get(e["session"]) if e["session"] else ""
    link = _pr_link(cfg, e)
    has_branch = e["branch"] and e["branch"] not in ("—", "–", "-") and not e["branch"].startswith("(")
    lines = [_line(_title(e), sfimage="circle.fill", sfcolor=TONE[status], sfsize=8)]
    if pane:
        lines.append(_muted(pane, 1, sfimage="text.alignleft", sfcolor=MUTED))
    if link:
        lines.append(_line(f"Open PR #{e['pr']}", 1, sfimage="arrow.up.right.square", href=link))
    if has_branch:
        lines.append(_muted(f"branch: {clean(e['branch'], 60)}", 1, sfimage="arrow.triangle.branch",
                            sfcolor=MUTED))
    if e["alive"] and e["session"] and safe_name(e["session"]):
        lines.extend(_session_actions(script, e["session"]))
    meta = [clean(e["project"], 40)] if e["project"] else []
    if e["age"] is not None:
        meta.append(fmt_age(e["age"]))
    if e["pr"]:
        meta.append(f"PR #{e['pr']}")
    if meta:
        lines.append(_muted("   " + " · ".join(meta)))
    if e["reason"]:
        lines.append(_line("   " + clean(e["reason"], 70), size=12, color=TONE[status]))
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
        print(_line("", sfimage="exclamationmark.triangle.fill", sfcolor=TONE["attention"]))
        print("---")
        print(_line("kitchen plugin error: " + clean(type(e).__name__ + ": " + str(e), 100),
                    color=TONE["attention"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
