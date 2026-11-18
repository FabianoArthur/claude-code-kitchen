"""Tests for `guard.py report`: counts by rule and decision over a jsonl fixture."""
import io
import json
import subprocess
import sys
import time

import pytest
from conftest import ORCH, load

guard = load(ORCH / "guard.py")

NOW = time.mktime((2026, 6, 15, 12, 0, 0, 0, 0, -1))


def row(days_ago, rule, decision, detail="cmd"):
    ts = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(NOW - days_ago * 86400))
    return {
        "ts": ts, "unit": "U-1", "tool": "Bash", "rule": rule,
        "decision": decision, "mode": "log", "detail": detail,
    }


def write(path, rows):
    path.write_text("\n".join(r if isinstance(r, str) else json.dumps(r) for r in rows) + "\n", encoding="utf-8")


@pytest.fixture
def logs(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "now", lambda: NOW)
    write(
        tmp_path / "guard.jsonl",
        [
            row(0.5, "push", "deny", "git push origin main"),
            row(1, "push", "deny", "git push -f"),
            row(2, "push", "would_deny"),
            row(2, "", "allow", "git status"),
            row(3, "secrets", "deny", "cat ~/.ssh/id_x"),
            "not json at all",
            json.dumps([1, 2]),
            json.dumps({"rule": "push", "decision": "deny"}),  # no ts
            row(20, "push", "deny", "too old"),
        ],
    )
    write(tmp_path / "guard-2026-06-10.jsonl", [row(5, "secrets", "deny"), row(6, "", "allow")])
    (tmp_path / "other.jsonl").write_text(json.dumps(row(0, "push", "deny")) + "\n", encoding="utf-8")
    return tmp_path


def test_counts_by_rule_and_decision(logs):
    report = guard.build_report(str(logs), 7, NOW)
    assert report["files"] == ["guard-2026-06-10.jsonl", "guard.jsonl"]  # other.jsonl is not a guard log
    assert report["rules"]["push"]["counts"] == {"deny": 2, "would_deny": 1}
    assert report["rules"]["secrets"]["counts"] == {"deny": 2}
    assert report["rules"]["(none)"]["counts"] == {"allow": 2}
    assert report["decisions"] == {"deny": 4, "would_deny": 1, "allow": 2}
    assert report["lines"] == 7


def test_window_and_bad_lines(logs):
    assert guard.build_report(str(logs), 30, NOW)["rules"]["push"]["counts"]["deny"] == 3  # the 20-day line counts
    assert guard.build_report(str(logs), 1, NOW)["lines"] == 2
    assert guard.build_report(str(logs), 7, NOW)["skipped"] == 3  # text, non-object, missing ts


def test_samples_carry_file_and_line(logs):
    report = guard.build_report(str(logs), 7, NOW)
    first = report["rules"]["push"]["samples"][0]
    assert (first["file"], first["line"], first["decision"]) == ("guard.jsonl", 1, "deny")
    assert first["detail"] == "git push origin main"
    assert all(s["decision"] != "allow" for e in report["rules"].values() for s in e["samples"])


def test_samples_are_capped(tmp_path):
    write(tmp_path / "guard.jsonl", [row(0.1, "push", "deny") for _ in range(10)])
    report = guard.build_report(str(tmp_path), 7, NOW)
    assert report["rules"]["push"]["counts"]["deny"] == 10
    assert len(report["rules"]["push"]["samples"]) == guard.REPORT_SAMPLES


def test_missing_folder_is_an_empty_report(tmp_path):
    report = guard.build_report(str(tmp_path / "nope"), 7, NOW)
    assert report["lines"] == 0 and report["files"] == []


def test_report_main_text_and_json(logs):
    out = io.StringIO()
    assert guard.report_main(["--days", "7", "--log-dir", str(logs)], env={}, out=out) == 0
    text = out.getvalue()
    assert "push: deny=2, would_deny=1" in text and "guard.jsonl:1 deny" in text
    out = io.StringIO()
    assert guard.report_main(["--days", "7", "--log-dir", str(logs), "--json"], env={}, out=out) == 0
    assert json.loads(out.getvalue())["rules"]["push"]["counts"]["deny"] == 2


def test_report_uses_the_log_dir_env(logs):
    out = io.StringIO()
    guard.report_main([], env={"KITCHEN_LOG_DIR": str(logs)}, out=out)
    assert "push: deny=2" in out.getvalue()  # default window is 7 days


def test_days_must_be_positive(logs):
    with pytest.raises(SystemExit):
        guard.report_main(["--days", "0", "--log-dir", str(logs)], env={}, out=io.StringIO())


def test_cli_runs_outside_the_kitchen(logs):
    """`report` works with no KITCHEN_SESSION and never writes a log line of its own."""
    script = ORCH / "guard.py"
    done = subprocess.run(
        [sys.executable, "-I", str(script), "report", "--days", "100000", "--log-dir", str(logs)],
        capture_output=True,
        text=True,
        env={"PATH": ""},
    )
    assert done.returncode == 0, done.stderr
    assert "push: deny=" in done.stdout  # positive control: it really counted
    assert sorted(p.name for p in logs.iterdir()) == ["guard-2026-06-10.jsonl", "guard.jsonl", "other.jsonl"]
