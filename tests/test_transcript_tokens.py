"""transcript_tokens.py — token sums from session transcripts."""
import json
import os
import subprocess
import sys
from datetime import date, timedelta, timezone

import pytest

from conftest import ORCH, load

tt = load(ORCH / "transcript_tokens.py")
SCRIPT = ORCH / "transcript_tokens.py"
SID = "12345678-1234-1234-1234-123456789abc"


def msg(mid, i=0, o=0, cc=0, cr=0, ts="2026-03-10T12:00:00Z"):
    return {"timestamp": ts, "message": {"id": mid, "content": "SECRET TEXT", "usage": {
        "input_tokens": i, "output_tokens": o,
        "cache_creation_input_tokens": cc, "cache_read_input_tokens": cr}}}


def write(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(x if isinstance(x, str) else json.dumps(x) for x in lines) + "\n")
    return path


@pytest.fixture
def projects(tmp_path):
    return tmp_path / "projects"


def test_sums_and_dedupes_chunks(projects):
    p = write(projects / "-a-b" / (SID + ".jsonl"), [
        msg("m1", i=10, o=1, cc=100),
        msg("m1", i=10, o=5, cc=100),  # same turn repeated: max wins
        msg("m2", i=3, o=2, cr=110),
    ])
    t = tt.session_totals(str(p))
    assert (t["input"], t["output"], t["cache_creation"], t["cache_read"]) == (13, 7, 100, 110)
    assert t["total"] == 230 and t["messages"] == 2


def test_context_is_last_message_not_sum(projects):
    p = write(projects / "x" / (SID + ".jsonl"), [
        msg("m1", i=5, cc=1000), msg("m2", i=7, cr=2000), msg("m3", i=1, o=9, cc=4, cr=50)])
    t = tt.session_totals(str(p))
    assert t["context"] == 1 + 4 + 50  # output excluded, earlier turns excluded
    assert t["input"] == 13


def test_corrupt_lines_skipped_and_counted(projects):
    p = write(projects / "x" / (SID + ".jsonl"), [
        msg("m1", i=1), "{not json", "[1, 2]", msg("m2", i=2),
        '{"message": {"id": "z", "usage": {"input_tokens": "x"}}}'])
    t = tt.session_totals(str(p))
    assert t["input"] == 3 and t["corrupt_lines"] == 3


def test_no_usage_returns_none(projects):
    p = write(projects / "x" / (SID + ".jsonl"), [{"type": "summary"}])
    assert tt.session_totals(str(p)) is None


@pytest.mark.parametrize("cwd,slug", [
    ("/srv/app/proj", "-srv-app-proj"),
    ("/srv/app/my.proj_x", "-srv-app-my-proj-x"),
])
def test_slug_alnum_rule_found(projects, cwd, slug):
    assert tt.slug_candidates(cwd)[0] == slug
    write(projects / slug / (SID + ".jsonl"), [msg("m1", i=1)])
    assert tt.session_path(cwd, SID, str(projects)).endswith(slug + os.sep + SID + ".jsonl")


def test_slug_slash_only_fallback_found(projects):
    cwd = "/srv/app/my.proj"
    alt = tt.slug_candidates(cwd)[1]
    assert alt == "-srv-app-my.proj" and alt != tt.slug_candidates(cwd)[0]
    write(projects / alt / (SID + ".jsonl"), [msg("m1", i=1)])
    assert tt.session_path(cwd, SID, str(projects)).endswith(SID + ".jsonl")


def test_projects_dir_from_env(projects, monkeypatch):
    write(projects / "-a" / (SID + ".jsonl"), [msg("m1", i=1)])
    monkeypatch.setenv("KITCHEN_PROJECTS_DIR", str(projects))
    assert tt.session_path("/a", SID).endswith(SID + ".jsonl")


@pytest.mark.parametrize("bad", [
    "../x", "../../etc/passwd", "", "not-a-uuid", SID + "/..", SID + ".jsonl", "1234"])
def test_invalid_session_id_refused(projects, bad):
    projects.mkdir()
    with pytest.raises(tt.TranscriptError, match="invalid session id"):
        tt.session_path("/a", bad, str(projects))


def test_cwd_cannot_traverse(projects):
    projects.mkdir()
    # Positive control: a normal cwd is looked up and merely not found.
    with pytest.raises(tt.TranscriptError, match="not found"):
        tt.session_path("/a", SID, str(projects))
    # Slugs never contain a separator, so ".." in a cwd stays inside one folder name.
    for slug in tt.slug_candidates("/../.."):
        assert "/" not in slug and os.sep not in slug
    with pytest.raises(tt.TranscriptError, match="not found"):
        tt.session_path("/../..", SID, str(projects))


@pytest.mark.skipif(os.name != "posix", reason="symlinks")
def test_symlink_out_of_projects_refused(projects, tmp_path):
    outside = tmp_path / "outside"
    write(outside / (SID + ".jsonl"), [msg("m1", i=1)])
    projects.mkdir()
    os.symlink(outside, projects / "-a")
    with pytest.raises(tt.TranscriptError, match="escapes"):
        tt.session_path("/a", SID, str(projects))


def test_day_total_local_time_across_sessions(projects):
    tz = timezone(timedelta(hours=-3))
    # 2026-03-10 local = 03:00Z on the 10th up to 03:00Z on the 11th
    write(projects / "-a" / (SID + ".jsonl"), [
        msg("a1", i=1, ts="2026-03-10T02:59:00Z"),     # 9th local: excluded
        msg("a2", i=10, ts="2026-03-10T03:00:00Z"),    # in
        msg("a3", i=100, ts="2026-03-11T02:59:00Z"),   # in
        msg("a4", i=1000, ts="2026-03-11T03:00:00Z"),  # 11th local: excluded
    ])
    write(projects / "-b" / "87654321-1234-1234-1234-123456789abc.jsonl", [
        msg("b1", o=5, ts="2026-03-10T15:00:00Z"), "{bad"])
    d = tt.day_totals(str(projects), date(2026, 3, 10), tz)
    assert (d["input"], d["output"]) == (110, 5)
    assert d["sessions"] == 2 and d["messages"] == 3 and d["corrupt_lines"] == 1


def test_cli_prints_numbers_only(projects):
    write(projects / "-a-b" / (SID + ".jsonl"), [msg("m1", i=4, o=6)])
    r = subprocess.run([sys.executable, str(SCRIPT), "session", "--cwd", "/a/b", "--session", SID,
                        "--projects-dir", str(projects)], capture_output=True, text=True)
    assert r.returncode == 0 and "total=10" in r.stdout
    assert "SECRET" not in r.stdout + r.stderr


def test_cli_errors(projects):
    projects.mkdir()
    r = subprocess.run([sys.executable, str(SCRIPT), "session", "--cwd", "/a", "--session", "../x",
                        "--projects-dir", str(projects)], capture_output=True, text=True)
    assert r.returncode == 2 and "invalid session id" in r.stderr


def test_selftest():
    r = subprocess.run([sys.executable, str(SCRIPT), "--selftest"], capture_output=True, text=True)
    assert r.returncode == 0 and "selftest ok" in r.stdout
