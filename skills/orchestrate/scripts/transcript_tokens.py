#!/usr/bin/env python3
"""
transcript_tokens — token totals from Claude Code session transcripts.

Prints numbers and ids only, never any text from a transcript.

Usage:
    python3 transcript_tokens.py session --cwd DIR --session UUID [--projects-dir DIR] [--json]
    python3 transcript_tokens.py today [--date YYYY-MM-DD] [--projects-dir DIR] [--json]
    python3 transcript_tokens.py --selftest

`session` sums input, output, cache_creation and cache_read tokens of one session and also
reports the current context: the input side (input + cache_creation + cache_read) of the LAST
message, not a sum. `today` sums every session under the projects folder, counting only the
messages stamped inside the given local day (default: today, local time).

Transcripts live in `<projects>/<slug>/<session-id>.jsonl`. The slug is the working
directory with every non-alphanumeric character replaced by `-`. Because that rule is
inferred, the slug folder is looked up under two spellings (the rule above, and the
older "only `/` becomes `-`"), and the whole projects folder can be given with
`--projects-dir` or `KITCHEN_PROJECTS_DIR` (default `~/.claude/projects`).

The session id comes from a file a unit can edit, so it is only trusted as a UUID, and the
final path, after realpath, must stay inside the projects folder.

Each message id counts once (a transcript repeats a turn in several chunks: the largest
value of each field wins). Lines that are not valid JSON are skipped and counted.

Exit: 0 = ok · 1 = no usable data · 2 = error
"""
import json
import os
import re
import sys
import tempfile
from datetime import date, datetime, time, timedelta
from pathlib import Path

FIELDS = (
    ("input", "input_tokens"),
    ("output", "output_tokens"),
    ("cache_creation", "cache_creation_input_tokens"),
    ("cache_read", "cache_read_input_tokens"),
)
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class TranscriptError(Exception):
    pass


def projects_dir(override=None):
    raw = override or os.environ.get("KITCHEN_PROJECTS_DIR") or "~/.claude/projects"
    return Path(os.path.expanduser(raw))


def slug_candidates(cwd):
    """Folder names Claude Code may use for `cwd`, most likely first."""
    cwd = str(cwd)
    out = []
    for slug in (re.sub(r"[^A-Za-z0-9]", "-", cwd), cwd.replace("/", "-")):
        if slug not in out:
            out.append(slug)
    return out


def session_path(cwd, session_id, projects=None):
    """Resolve the transcript path, or raise TranscriptError. Never returns a path outside
    the projects folder."""
    if not isinstance(session_id, str) or not UUID_RE.match(session_id):
        raise TranscriptError("invalid session id")
    base = os.path.realpath(projects_dir(projects))
    first = None
    for slug in slug_candidates(cwd):
        candidate = os.path.realpath(os.path.join(base, slug, session_id + ".jsonl"))
        if candidate == base or os.path.commonpath([base, candidate]) != base:
            raise TranscriptError("path escapes the projects folder")
        first = first or candidate
        if os.path.isfile(candidate):
            return candidate
    raise TranscriptError("transcript not found: " + os.path.basename(first or ""))


def _record(line):
    """Parse one line. Returns ('bad', None) for corrupt JSON, ('skip', None) when the line
    has no usage, else ('ok', (message_id, values, timestamp))."""
    try:
        d = json.loads(line)
    except ValueError:
        return "bad", None
    if not isinstance(d, dict):
        return "bad", None
    m = d.get("message")
    if not isinstance(m, dict) or not isinstance(m.get("usage"), dict):
        return "skip", None
    usage = m["usage"]
    vals = {}
    for key, name in FIELDS:
        v = usage.get(name, 0)
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            return "bad", None
        vals[key] = v
    mid = m.get("id") or d.get("requestId") or d.get("uuid")
    if not isinstance(mid, str) or not mid:
        return "skip", None
    ts = d.get("timestamp")
    return "ok", (mid, vals, ts if isinstance(ts, str) else None)


def _parse_ts(ts, tz):
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz) if tz else dt.astimezone()
    return dt.astimezone(tz) if tz else dt.astimezone()


def read_messages(path):
    """Return (messages, corrupt, order). `messages` maps id -> {field: max, 'ts': first ts}."""
    msgs = {}
    order = []
    corrupt = 0
    with open(path, "rb") as f:
        for raw in f:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            kind, rec = _record(line)
            if kind == "bad":
                corrupt += 1
                continue
            if kind == "skip":
                continue
            mid, vals, ts = rec
            cur = msgs.get(mid)
            if cur is None:
                cur = msgs[mid] = dict.fromkeys(vals, 0)
                cur["ts"] = ts
            if mid in order:
                order.remove(mid)
            order.append(mid)
            for k, v in vals.items():
                cur[k] = max(cur[k], v)
            if cur["ts"] is None:
                cur["ts"] = ts
    return msgs, corrupt, order


def _sum(msgs, ids):
    t = {k: sum(msgs[i][k] for i in ids) for k, _ in FIELDS}
    t["total"] = sum(t.values())
    t["messages"] = len(ids)
    return t


def session_totals(path):
    msgs, corrupt, order = read_messages(path)
    if not msgs:
        return None
    t = _sum(msgs, list(msgs))
    last = msgs[order[-1]]
    t["context"] = last["input"] + last["cache_creation"] + last["cache_read"]
    t["corrupt_lines"] = corrupt
    return t


def day_totals(projects=None, day=None, tz=None):
    """Sum messages stamped inside local `day` across every session transcript."""
    base = projects_dir(projects)
    day = day or datetime.now(tz).date()
    midnight = datetime.combine(day, time.min)
    start = midnight.replace(tzinfo=tz) if tz else midnight.astimezone()
    end = start + timedelta(days=1)
    total = dict.fromkeys([k for k, _ in FIELDS], 0)
    sessions = messages = corrupt = 0
    if base.is_dir():
        for path in sorted(base.glob("*/*.jsonl")):
            if not path.is_file() or path.is_symlink():
                continue
            try:
                if datetime.fromtimestamp(path.stat().st_mtime).astimezone() < start:
                    continue
                msgs, bad, _ = read_messages(path)
            except OSError:
                continue
            corrupt += bad
            ids = []
            for mid, m in msgs.items():
                dt = _parse_ts(m["ts"], tz)
                if dt is not None and start <= dt < end:
                    ids.append(mid)
            if not ids:
                continue
            sessions += 1
            messages += len(ids)
            for i in ids:
                for k in total:
                    total[k] += msgs[i][k]
    total["total"] = sum(total.values())
    total.update(day=day.isoformat(), sessions=sessions, messages=messages, corrupt_lines=corrupt)
    return total


def _fmt(d):
    return " ".join("%s=%s" % (k, v) for k, v in d.items())


def selftest():
    import shutil
    from datetime import timezone

    tmp = Path(tempfile.mkdtemp(prefix="tt-"))
    try:
        sid = "12345678-1234-1234-1234-123456789abc"
        proj = tmp / "p"
        (proj / "-a-b").mkdir(parents=True)
        lines = [
            {"timestamp": "2026-01-02T10:00:00Z", "message": {"id": "m1", "usage": {
                "input_tokens": 10, "output_tokens": 5, "cache_creation_input_tokens": 100,
                "cache_read_input_tokens": 0}}},
            "{broken",
            {"timestamp": "2026-01-02T10:01:00Z", "message": {"id": "m2", "usage": {
                "input_tokens": 3, "output_tokens": 2, "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 110}}},
        ]
        (proj / "-a-b" / (sid + ".jsonl")).write_text(
            "\n".join(x if isinstance(x, str) else json.dumps(x) for x in lines) + "\n")
        p = session_path("/a/b", sid, str(proj))
        t = session_totals(p)
        assert t["input"] == 13 and t["output"] == 7 and t["corrupt_lines"] == 1, t
        assert t["context"] == 113, t
        d = day_totals(str(proj), date(2026, 1, 2), timezone.utc)
        assert d["total"] == t["total"] and d["sessions"] == 1, d
        try:
            session_path("/a/b", "../x", str(proj))
        except TranscriptError:
            pass
        else:
            raise AssertionError("traversal accepted")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("selftest ok")
    return 0


def _opt(argv, name):
    if name in argv:
        i = argv.index(name)
        if i + 1 >= len(argv):
            raise TranscriptError("missing value for " + name)
        return argv[i + 1]
    return None


def main(argv):
    if argv[:1] == ["--selftest"]:
        return selftest()
    if not argv or argv[0] not in ("session", "today"):
        print(__doc__.strip().split("\n\n")[1], file=sys.stderr)
        return 2
    try:
        as_json = "--json" in argv
        projects = _opt(argv, "--projects-dir")
        if argv[0] == "session":
            cwd, sid = _opt(argv, "--cwd"), _opt(argv, "--session")
            if not cwd or not sid:
                raise TranscriptError("session needs --cwd and --session")
            result = session_totals(session_path(cwd, sid, projects))
            if result is None:
                print("tokens: unknown")
                return 1
        else:
            raw = _opt(argv, "--date")
            try:
                day = date.fromisoformat(raw) if raw else None
            except ValueError:
                raise TranscriptError("bad --date, expected YYYY-MM-DD") from None
            result = day_totals(projects, day)
    except TranscriptError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    except OSError as e:
        print("error: %s" % type(e).__name__, file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True) if as_json else _fmt(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
