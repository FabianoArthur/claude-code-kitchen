"""sync_tracker.py — offline: a fake tracker and a faked HTTP layer, never the network."""
import io
import json
import os
import stat
import urllib.error

import pytest

from conftest import ROOT, load

st = load(ROOT / "skills" / "sync" / "scripts" / "sync_tracker.py")

DOC = """---
card_id:
title: "rate-limit-login — Rate-limit the login endpoint"
status: in-progress
priority: high
sync_pending: true
updated: 2026-01-16
---

# Rate-limit the login endpoint

## Current state

Counter works; Retry-After missing.

## Session log

### 2026-01-16 — saved by /save ⏳ to sync (second save)
- **Changed:** limiter per account.

### 2026-01-15 — created by /plan
- **Changed:** task created.
"""


class FakeTracker:
    def __init__(self, tasks=(), statuses=("backlog", "in-progress", "done"), priority=None):
        self.tasks, self.statuses, self.priority = list(tasks), {s: s for s in statuses}, priority
        self.calls = []

    def list_statuses(self):
        return self.statuses

    def all_tasks(self):
        return self.tasks

    def create(self, payload):
        self.calls.append(("create", payload))
        return {"id": "t1", "url": "https://tracker.example.com/t/t1"}

    def comment(self, card_id, text):
        self.calls.append(("comment", card_id, text))

    def set_status(self, card_id, status):
        self.calls.append(("status", card_id, status))

    def get_priority(self, card_id):
        return self.priority

    def set_priority(self, card_id, prio):
        self.calls.append(("priority", card_id, prio))


@pytest.fixture
def cards(tmp_path):
    d = tmp_path / "cards"
    d.mkdir()
    (d / "rate-limit-login.md").write_text(DOC)
    return d


# ---- the pure parts ------------------------------------------------------------------

def test_pending_entries_are_only_the_marked_ones():
    _, body = st.split_doc(DOC)
    got = st.pending_log_entries(body)
    assert "limiter per account" in got and "created by /plan" not in got


def test_comment_carries_state_and_pending_log():
    fm_lines, body = st.split_doc(DOC)
    text = st.build_comment(st.parse_fm(fm_lines), body, "2026-01-17")
    assert "Counter works" in text and "limiter per account" in text and "2026-01-17" in text


def test_rewrite_closes_the_fence_and_flips_the_markers():
    out = st.rewrite_doc(DOC, "t1", "https://tracker.example.com/t/t1", "2026-01-17")
    assert out.startswith("---\n") and "\n---\n\n# Rate-limit" in out   # fence on its own line
    assert "---#" not in out and "---#" not in st.rewrite_doc("---\ntitle: x\n---\n# x\n", "1", "u", "d")
    fm = st.parse_fm(st.split_doc(out)[0])
    assert fm["sync_pending"] == "false" and fm["card_id"] == "t1" and fm["updated"] == "2026-01-17"
    assert "⏳ to sync" not in out
    assert "### 2026-01-16 — saved by /save ✅ synced 2026-01-17 (second save)" in out


def test_rewrite_adds_missing_keys():
    out = st.rewrite_doc("---\ntitle: x\n---\n\n# x\n", "9", "u", "2026-01-17")
    fm = st.parse_fm(st.split_doc(out)[0])
    assert (fm["card_id"], fm["card_url"], fm["sync_pending"]) == ("9", "u", "false")


@pytest.mark.parametrize("raw,want", [("urgent", 1), ("High", 2), ("normal", 3), ("low", 4), ("2", 2),
                                      ("", None), ("# urgent|high|normal|low", None), ("5", None),
                                      ("whatever", None)])
def test_parse_priority(raw, want):
    assert st.parse_priority(raw) == want


def test_adapter_config_reads_nested_block_and_cards(tmp_path):
    adapter = tmp_path / ".claude" / "orchestrator.md"
    adapter.parent.mkdir()
    adapter.write_text('base: main\nvault:\n  cards: docs/tasks\ntracker:\n  type: clickup\n'
                       '  list_id: "123"   # the list\n  token_env: MY_TOKEN\n')
    cfg = st.load_config(adapter)
    assert cfg["list_id"] == "123" and cfg["token_env"] == "MY_TOKEN" and cfg["type"] == "clickup"
    assert cfg["cards"] == tmp_path / "docs" / "tasks"


# ---- the token -----------------------------------------------------------------------

def test_token_comes_from_env_first(tmp_path):
    f = tmp_path / "tok"
    f.write_text("from-file\n")
    f.chmod(0o600)
    assert st.read_token("T", f, {"T": " from-env "}) == "from-env"
    assert st.read_token("T", f, {}) == "from-file"


def test_token_file_with_loose_permissions_is_refused(tmp_path):
    f = tmp_path / "tok"
    f.write_text("secret\n")
    f.chmod(0o644)
    with pytest.raises(SystemExit) as e:
        st.read_token("T", f, {})
    assert "secret" not in str(e.value)


def test_missing_token_says_where_to_put_it_without_inventing_one(tmp_path):
    with pytest.raises(SystemExit) as e:
        st.read_token("T", tmp_path / "nope", {})
    assert "T" in str(e.value) and "nope" in str(e.value)


# ---- push ----------------------------------------------------------------------------

def run_push(cards, tracker, **kw):
    out = io.StringIO()
    code = st.push(list(sorted(cards.glob("*.md"))), tracker, today="2026-01-17", out=out, **kw)
    return code, out.getvalue()


def test_dry_run_changes_nothing(cards):
    t = FakeTracker()
    before = (cards / "rate-limit-login.md").read_text()
    code, text = run_push(cards, t, dry=True)
    assert code == 0 and t.calls == []
    assert (cards / "rate-limit-login.md").read_text() == before
    assert "would CREATE" in text and "DRY-RUN" in text


def test_creates_card_comments_and_clears_the_flag(cards):
    t = FakeTracker()
    code, _ = run_push(cards, t)
    assert code == 0
    kinds = [c[0] for c in t.calls]
    assert kinds == ["create", "comment"]
    assert t.calls[0][1]["name"].startswith("rate-limit-login")
    assert t.calls[0][1]["priority"] == 2 and t.calls[0][1]["status"] == "in-progress"
    fm = st.parse_fm(st.split_doc((cards / "rate-limit-login.md").read_text())[0])
    assert fm["sync_pending"] == "false" and fm["card_id"] == "t1"


def test_no_priority_means_no_card_and_a_failing_exit(cards):
    p = cards / "rate-limit-login.md"
    p.write_text(DOC.replace("priority: high\n", "priority:\n"))
    t = FakeTracker()
    code, text = run_push(cards, t)
    assert code == 1 and t.calls == []                       # never an invented default
    assert "MISSING PRIORITY" in text
    assert st.parse_fm(st.split_doc(p.read_text())[0])["sync_pending"] == "true"   # untouched


def test_matches_an_existing_card_by_name_instead_of_duplicating(cards):
    t = FakeTracker(tasks=[{"id": "77", "name": "Rate-limit the login endpoint", "url": "u77"}], priority=2)
    run_push(cards, t)
    assert [c[0] for c in t.calls] == ["comment", "status"]
    assert t.calls[0][1] == "77"


def test_status_unknown_to_the_tracker_is_skipped_not_fatal(cards):
    t = FakeTracker(tasks=[{"id": "77", "name": "Rate-limit the login endpoint"}],
                    statuses=("open", "closed"), priority=2)
    code, text = run_push(cards, t)
    assert code == 0 and "status" not in [c[0] for c in t.calls]
    assert "not a status of the tracker" in text


def test_no_status_flag_leaves_status_alone(cards):
    t = FakeTracker(tasks=[{"id": "77", "name": "Rate-limit the login endpoint"}], priority=2)
    run_push(cards, t, use_status=False)
    assert "status" not in [c[0] for c in t.calls]


def test_priority_change_is_pushed_for_an_existing_card(cards):
    t = FakeTracker(tasks=[{"id": "77", "name": "Rate-limit the login endpoint"}], priority=4)
    run_push(cards, t)
    assert ("priority", "77", 2) in t.calls


def test_card_id_in_the_doc_wins_over_name_matching(cards):
    p = cards / "rate-limit-login.md"
    p.write_text(DOC.replace("card_id:\n", "card_id: 555\n"))
    t = FakeTracker(tasks=[{"id": "77", "name": "Rate-limit the login endpoint"}], priority=2)
    run_push(cards, t)
    assert t.calls[0][:2] == ("comment", "555")


def test_only_pending_docs_by_default_and_target_narrows(cards):
    (cards / "other.md").write_text(DOC.replace("sync_pending: true", "sync_pending: false")
                                    .replace("rate-limit-login", "other-thing"))
    assert [p.name for p in st.select_docs(cards, None, False)] == ["rate-limit-login.md"]
    assert [p.name for p in st.select_docs(cards, "other", False)] == ["other.md"]
    assert len(st.select_docs(cards, None, True)) == 2


# ---- the ClickUp client over faked HTTP ----------------------------------------------

class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_clickup_client_sends_the_token_only_as_a_header(monkeypatch):
    seen = {}

    def fake_open(req, timeout=0):
        seen.update(url=req.full_url, method=req.get_method(), auth=req.get_header("Authorization"),
                    body=req.data)
        return FakeResp(json.dumps({"id": "1", "url": "u"}).encode())

    monkeypatch.setattr(st.urllib.request, "urlopen", fake_open)
    c = st.ClickUp("pk_SECRETSECRET", "42")
    assert c.create({"name": "n", "priority": 2}) == {"id": "1", "url": "u"}
    assert seen["auth"] == "pk_SECRETSECRET" and seen["url"].endswith("/list/42/task")
    assert b"pk_SECRET" not in (seen["body"] or b"") and "pk_SECRET" not in seen["url"]


def test_clickup_http_errors_never_echo_the_token(monkeypatch):
    def boom(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"err":"bad"}'))

    monkeypatch.setattr(st.urllib.request, "urlopen", boom)
    with pytest.raises(SystemExit) as e:
        st.ClickUp("pk_SECRETSECRET", "42").list_statuses()
    assert "401" in str(e.value) and "pk_SECRET" not in str(e.value)


def test_clickup_pagination_stops_on_last_page(monkeypatch):
    pages = iter([{"tasks": [{"id": "a"}], "last_page": False}, {"tasks": [{"id": "b"}], "last_page": True}])
    monkeypatch.setattr(st.urllib.request, "urlopen", lambda req, timeout=0: FakeResp(json.dumps(next(pages)).encode()))
    assert [t["id"] for t in st.ClickUp("tok", "42").all_tasks()] == ["a", "b"]


def test_script_has_no_personal_defaults():
    src = (ROOT / "skills" / "sync" / "scripts" / "sync_tracker.py").read_text()
    assert "/Users/" not in src and "pk_" not in src.replace("pk_SECRET", "")
    assert os.access(ROOT / "skills" / "sync" / "scripts" / "sync_tracker.py", os.R_OK)
    assert stat.S_ISREG(os.stat(ROOT / "skills" / "sync" / "scripts" / "sync_tracker.py").st_mode)
