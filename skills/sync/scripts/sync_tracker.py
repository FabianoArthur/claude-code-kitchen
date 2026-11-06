#!/usr/bin/env python3
"""sync_tracker — push local task docs (sync_pending: true) to an issue tracker.

Pure stdlib, no MCP. ClickUp is the first adapter. The model only invokes and reports; all
the logic lives here, so a push costs almost no model tokens.

    python3 sync_tracker.py push [TARGET] [--all] [--no-status] [--dry-run] [--adapter FILE]

  TARGET       substring matching ONE doc by file name / title / card_hint.
               Without it: every doc with `sync_pending: true`.
  --all        ignore sync_pending (with or without TARGET).
  --no-status  do not touch the card's status.
  --dry-run    read the tracker, write nothing (no card, no comment, no doc). Always run this first.
  --adapter    path to .claude/orchestrator.md (default: found walking up from cwd).

Configuration comes from the adapter, never from the script:

    vault:
      cards: docs/tasks              # where the task docs live
    tracker:
      type: clickup
      list_id: "<id of the list that receives the cards>"
      token_env: CLICKUP_API_TOKEN   # optional; this is the default
      token_file: ~/.config/claude-code-kitchen/clickup_token   # optional; this is the default

The token is read from the environment variable first, then from the file (which must not be
readable by group/others). It is sent only as an Authorization header and never printed.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

API = "https://api.clickup.com/api/v2"
PENDING = "⏳ to sync"
DONE = "✅ synced"
DEFAULT_TOKEN_ENV = "CLICKUP_API_TOKEN"
DEFAULT_TOKEN_FILE = "~/.config/claude-code-kitchen/clickup_token"


def die(msg):
    raise SystemExit(f"ERROR: {msg}")


# ------------------------------------------------------------------ adapter
def find_adapter(start=None):
    p = Path(start or Path.cwd()).resolve()
    for d in (p, *p.parents):
        f = d / ".claude" / "orchestrator.md"
        if f.is_file():
            return f
    return None


def _clean(v):
    v = v.strip()
    if v[:1] in "\"'":
        q = v[0]
        end = v.find(q, 1)
        return v[1:end] if end > 0 else v[1:]
    return v.split(" #", 1)[0].strip()


def _block_value(text, block, key):
    m = re.search(rf"(?m)^{re.escape(block)}:[ \t]*$", text)
    if not m:
        return None
    for line in text[m.end():].split("\n")[1:]:
        if line.strip() and not line.startswith((" ", "\t")):
            break
        k = re.match(rf"^[ \t]+{re.escape(key)}:[ \t]*(.*)$", line)
        if k:
            return _clean(k.group(1)) or None
    return None


def load_config(adapter):
    """The tracker block + the cards folder, resolved against the repo that owns the adapter."""
    adapter = Path(adapter)
    text = adapter.read_text(encoding="utf-8")
    root = adapter.parent.parent
    cfg = {k: _block_value(text, "tracker", k) for k in ("type", "list_id", "token_env", "token_file")}
    cards = _block_value(text, "vault", "cards")
    cfg["cards"] = (root / cards) if cards else None
    return cfg


# ------------------------------------------------------------------ token
def read_token(env_name, token_file, environ=None):
    environ = os.environ if environ is None else environ
    tok = (environ.get(env_name) or "").strip()
    if tok:
        return tok
    f = Path(token_file).expanduser()
    if f.is_file():
        if f.stat().st_mode & 0o077:
            die(f"{f} is readable by other users; run: chmod 600 {f}")
        tok = f.read_text(encoding="utf-8").strip()
        if tok:
            return tok
    die(f"no token: set ${env_name} or create {f} (chmod 600). "
        "The token belongs to you; the adapter only says where it is.")


# ------------------------------------------------------------------ front matter / markdown
def split_doc(text):
    """(front-matter lines, body). The fences are not included."""
    if not text.startswith("---"):
        return [], text
    parts = text.split("\n")
    for i in range(1, len(parts)):
        if parts[i].strip() == "---":
            return parts[1:i], "\n".join(parts[i + 1:])
    return [], text


def parse_fm(fm_lines):
    fm = {}
    for ln in fm_lines:
        m = re.match(r"^([A-Za-z0-9_]+):\s*(.*)$", ln)
        if m:
            v = m.group(2).strip()
            if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
                v = v[1:-1]
            fm[m.group(1)] = v
    return fm


def section(body, header):
    out, grab = [], False
    for ln in body.split("\n"):
        if ln.startswith("## "):
            if grab:
                break
            grab = ln.strip() == f"## {header}"
            continue
        if grab:
            out.append(ln)
    return "\n".join(out).strip()


def pending_log_entries(body):
    """Session-log entries whose heading carries the '⏳ to sync' marker `/save` writes."""
    log = section(body, "Session log")
    keep = []
    for block in re.split(r"(?m)^(?=### )", log):
        head = block.strip().splitlines()[0] if block.strip() else ""
        if head.startswith("### ") and PENDING in head:
            keep.append(block.strip())
    return "\n\n".join(keep)


def state_snapshot(body):
    for header in ("Current state", "What", "Symptom"):
        text = section(body, header)
        if text:
            return f"## {header}\n{text}"
    return ""


def build_comment(fm, body, today):
    return (f"Sync from the local task doc — {today}\n"
            f"doc: {fm.get('title', '(untitled)')}\n\n"
            f"{state_snapshot(body) or '(no Current state / What / Symptom section)'}\n\n"
            f"## Log (to sync)\n{pending_log_entries(body) or '(no entries marked ' + PENDING + ')'}")


def rewrite_doc(text, card_id, card_url, today):
    fm_lines, body = split_doc(text)
    seen = set()
    values = {"card_id": card_id, "card_url": card_url, "sync_pending": "false", "updated": today}

    def setline(ln):
        m = re.match(r"^([A-Za-z0-9_]+):", ln)
        if m and m.group(1) in values:
            seen.add(m.group(1))
            return f"{m.group(1)}: {values[m.group(1)]}"
        return ln

    new_fm = [setline(ln) for ln in fm_lines]
    new_fm += [f"{k}: {v}" for k, v in values.items() if k not in seen]
    # Keep any text after the marker (e.g. a parenthesised summary): no end-of-line anchor.
    new_body = re.sub(rf"(?m)^(### .+?) {re.escape(PENDING)}", rf"\1 {DONE} {today}", body)
    # split_doc drops the newline that followed the closing fence; without it the fence glues
    # onto the body ("---# Title") and the front matter becomes unreadable.
    return "---\n" + "\n".join(new_fm) + "\n---\n" + new_body


# ------------------------------------------------------------------ priority
PRIORITY_BY_NAME = {"urgent": 1, "high": 2, "normal": 3, "low": 4}
PRIORITY_LABEL = {v: k for k, v in PRIORITY_BY_NAME.items()}


def parse_priority(value):
    """'high' / '2' -> 2. Empty, a template comment or an unknown value -> None."""
    if value is None:
        return None
    v = str(value).split("#", 1)[0].strip().lower()
    if not v:
        return None
    if v.isdigit():
        return int(v) if int(v) in PRIORITY_LABEL else None
    return PRIORITY_BY_NAME.get(v)


def doc_priority(fm):
    return parse_priority(fm.get("priority"))


# ------------------------------------------------------------------ ClickUp
class ClickUp:
    def __init__(self, token, list_id):
        self._token, self.list_id = token, list_id

    def _call(self, method, path, body=None):
        url = f"{API}{path}"
        req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                     method=method)
        req.add_header("Authorization", self._token)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read().decode()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300].replace(self._token, "***")
            die(f"{method} {path} -> HTTP {e.code}: {detail}")
        except urllib.error.URLError as e:
            die(f"{method} {path} -> network: {e.reason}")

    def list_statuses(self):
        d = self._call("GET", f"/list/{self.list_id}")
        return {s["status"].lower(): s["status"] for s in d.get("statuses", [])}

    def all_tasks(self):
        tasks, page = [], 0
        while page <= 50:
            d = self._call("GET", f"/list/{self.list_id}/task?subtasks=true&include_closed=true&page={page}")
            batch = d.get("tasks", [])
            tasks.extend(batch)
            if d.get("last_page") or not batch:
                break
            page += 1
        return tasks

    def create(self, payload):
        return self._call("POST", f"/list/{self.list_id}/task", payload)

    def comment(self, card_id, text):
        self._call("POST", f"/task/{card_id}/comment", {"comment_text": text, "notify_all": False})

    def set_status(self, card_id, status):
        self._call("PUT", f"/task/{card_id}", {"status": status})

    def get_priority(self, card_id):
        task = self._call("GET", f"/task/{card_id}")
        return parse_priority(((task.get("priority") or {}) or {}).get("id"))

    def set_priority(self, card_id, prio):
        self._call("PUT", f"/task/{card_id}", {"priority": prio})


# ------------------------------------------------------------------ push
def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def find_card(tasks, fm):
    """Conservative name match, doc <-> task. Returns the task or None."""
    head = _norm(fm.get("title", "").split("—")[0])
    tail = _norm(fm.get("title", "").split("—")[-1])
    cands = [c for c in (_norm(fm.get("title", "")), head, tail, _norm(fm.get("card_hint", ""))) if len(c) >= 8]
    for t in tasks:
        tn = _norm(t.get("name", ""))
        if tn and any(c in tn or tn in c for c in cands):
            return t
    return None


def select_docs(cards_dir, target, everything):
    docs = sorted(Path(cards_dir).glob("*.md"))
    if target:
        needle = target.lower()
        return [p for p in docs if needle in " ".join(
            [p.stem, *(parse_fm(split_doc(p.read_text(encoding="utf-8"))[0]).get(k, "")
                       for k in ("title", "card_hint"))]).lower()]
    if everything:
        return docs
    return [p for p in docs if parse_fm(split_doc(p.read_text(encoding="utf-8"))[0])
            .get("sync_pending", "").lower() == "true"]


def push(docs, tracker, today=None, out=sys.stdout, dry=False, use_status=True):
    today = today or date.today().isoformat()
    say = lambda s="": print(s, file=out)  # noqa: E731
    if not docs:
        say("Nothing to do: no doc matched the target / none has sync_pending: true.")
        return 0
    statuses, tasks = tracker.list_statuses(), tracker.all_tasks()
    say(f"{'[DRY-RUN] ' if dry else ''}{len(tasks)} cards in the list · {len(docs)} doc(s)\n")
    missing_priority = []

    for path in docs:
        text = path.read_text(encoding="utf-8")
        fm_lines, body = split_doc(text)
        fm = parse_fm(fm_lines)
        say(f"== {path.name}\n   title: {fm.get('title', path.stem)}")
        created = False
        card_id, card_url = fm.get("card_id", "").strip(), fm.get("card_url", "").strip()

        if card_id:
            say(f"   card_id (front matter): {card_id}")
        else:
            match = find_card(tasks, fm)
            if match:
                card_id, card_url = match["id"], match.get("url", "")
                say(f"   matched existing card {card_id} · {match.get('name', '')[:50]}")
            else:
                prio = doc_priority(fm)
                if prio is None:
                    # No default: an invented "normal" would pass for a real priority in the backlog.
                    say("   MISSING PRIORITY — card NOT created. Set `priority: urgent|high|normal|low`.\n")
                    missing_priority.append(path.name)
                    continue
                payload = {"name": fm.get("title", path.stem), "priority": prio}
                if state_snapshot(body):
                    payload["markdown_description"] = state_snapshot(body)
                doc_status = fm.get("status", "").lower()
                if use_status and doc_status in statuses:
                    payload["status"] = statuses[doc_status]
                if dry:
                    say(f"   [dry] would CREATE (status={payload.get('status', '-')}, "
                        f"priority={PRIORITY_LABEL[prio]})")
                    card_url = "(new)"
                else:
                    made = tracker.create(payload)
                    card_id, card_url = made["id"], made.get("url", "")
                    say(f"   CREATED {card_id} · {card_url}")
                created = True

        comment = build_comment(fm, body, today)
        if dry:
            say(f"   [dry] would COMMENT ({len(comment)} chars)")
        elif card_id:
            tracker.comment(card_id, comment)
            say("   COMMENTED")

        if card_id and not created:
            doc_status = fm.get("status", "").lower()
            if use_status and doc_status:
                if doc_status not in statuses:
                    say(f"   status '{doc_status}' is not a status of the tracker's list — left alone "
                        "(change the doc, or use --no-status)")
                elif dry:
                    say(f"   [dry] could set status -> {statuses[doc_status]}")
                else:
                    tracker.set_status(card_id, statuses[doc_status])
                    say(f"   STATUS -> {statuses[doc_status]}")
            prio = doc_priority(fm)
            if prio is not None and prio != tracker.get_priority(card_id):
                if dry:
                    say(f"   [dry] could set priority -> {PRIORITY_LABEL[prio]}")
                else:
                    tracker.set_priority(card_id, prio)
                    say(f"   PRIORITY -> {PRIORITY_LABEL[prio]}")

        if dry:
            say("   [dry] would rewrite the doc (sync_pending: false, markers flipped)")
        elif card_id:
            path.write_text(rewrite_doc(text, card_id, card_url, today), encoding="utf-8")
            say("   DOC REWRITTEN (sync_pending: false)")
        say()

    say("Done." + ("  (nothing was changed — DRY-RUN)" if dry else ""))
    if missing_priority:
        say(f"\nNOT CREATED, MISSING PRIORITY ({len(missing_priority)}): " + ", ".join(missing_priority))
        return 0 if dry else 1
    return 0


# ------------------------------------------------------------------ cli
def main(argv):
    if not argv or argv[0] in ("-h", "--help") or argv[0] != "push":
        print(__doc__)
        return 0 if not argv or argv[0] in ("-h", "--help") else 2
    rest = argv[1:]
    adapter = None
    if "--adapter" in rest:
        i = rest.index("--adapter")
        adapter = rest[i + 1] if i + 1 < len(rest) else die("--adapter needs a file")
        del rest[i:i + 2]
    flags = {a for a in rest if a.startswith("--")}
    positional = [a for a in rest if not a.startswith("--")]
    adapter = Path(adapter) if adapter else find_adapter()
    if not adapter or not adapter.is_file():
        die("no .claude/orchestrator.md found. Create the adapter first (docs/adapter.md).")
    cfg = load_config(adapter)
    if not cfg["cards"]:
        die("the adapter has no vault.cards — add it (the folder with your task docs).")
    if (cfg["type"] or "clickup") != "clickup":
        die(f"tracker.type '{cfg['type']}' has no adapter yet (only: clickup).")
    if not cfg["list_id"]:
        die("the adapter has no tracker.list_id — add the id of the list that receives the cards.")
    token = read_token(cfg["token_env"] or DEFAULT_TOKEN_ENV, cfg["token_file"] or DEFAULT_TOKEN_FILE)
    docs = select_docs(cfg["cards"], positional[0] if positional else None, "--all" in flags)
    return push(docs, ClickUp(token, cfg["list_id"]), dry="--dry-run" in flags,
                use_status="--no-status" not in flags)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
