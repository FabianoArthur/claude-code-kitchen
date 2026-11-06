"""The session-memory pair (`save` / `resume`): structure, adapter-driven, no hard-coded values."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NAMES = ["resume", "save"]


def front_matter(text):
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, "missing front matter"
    return dict(line.split(":", 1) for line in m.group(1).splitlines() if ":" in line)


@pytest.fixture(params=NAMES)
def skill(request):
    path = ROOT / "skills" / request.param / "SKILL.md"
    assert path.is_file(), f"{path} is missing"
    return request.param, path.read_text(encoding="utf-8")


def test_front_matter_matches_the_directory(skill):
    name, text = skill
    fm = front_matter(text)
    assert fm["name"].strip() == name
    assert len(fm["description"].strip()) > 80   # the trigger text is what makes it fire


def test_reads_the_shared_rulebook_and_the_adapter(skill):
    _, text = skill
    assert "../orchestrate/CORE.md" in text
    assert "vault.cards" in text
    assert "ask" in text.lower()       # a missing adapter field is asked, never invented


def test_no_hard_coded_project_values(skill):
    # Everything project-specific comes from the adapter; nothing may be baked into a skill.
    _, text = skill
    assert not re.search(r"/(Users|home)/", text)
    assert not re.search(r"\b\d{9,}\b", text)          # tracker list/space ids
    for term in ("clickup", "hidrofleet"):
        assert term not in text.lower()


def test_save_is_local_first():
    text = (ROOT / "skills" / "save" / "SKILL.md").read_text(encoding="utf-8")
    assert "sync_pending" in text
    for rule in ("no commit", "no push", "no tracker"):
        assert rule in text.lower()
    assert "date +%F" in text                          # dates come from the clock, not memory
    assert "## Links" in text and "## Session log" in text and "## Current state" in text


def test_resume_reads_state_and_does_not_work():
    text = (ROOT / "skills" / "resume" / "SKILL.md").read_text(encoding="utf-8")
    for state in ("⏸", "🔄", "⏳", "✅", "🚫"):
        assert state in text                           # the in-flight manifest states
    assert "sync_pending" in text
    assert "harvest" in text
    assert "does not start" in text.lower()
    assert "one next step" in text.lower()


def test_example_pair_shows_the_save_effect():
    before = (ROOT / "examples" / "task.md").read_text(encoding="utf-8")
    after = (ROOT / "examples" / "task-saved.md").read_text(encoding="utf-8")
    assert "sync_pending" not in front_matter(before)
    fm = front_matter(after)
    assert fm["sync_pending"].strip() == "true"
    assert fm["card_id"].strip() == front_matter(before)["card_id"].strip()
    log = after.split("## Session log", 1)[1]
    entries = re.findall(r"^### (\d{4}-\d{2}-\d{2})", log, re.M)
    assert len(entries) >= 2 and entries == sorted(entries, reverse=True)   # newest first
    assert "created by /plan" in log                   # the older entry is kept, not rewritten
    assert "- **Pending:**" in log and "- **Decisions:**" in log
    for heading in ("## Current state", "## Pending", "## Links"):
        assert heading in after
