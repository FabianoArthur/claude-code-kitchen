"""Structure checks for every brigade prompt in skills/orchestrate/brigade/."""
import re
from pathlib import Path

import pytest

BRIGADE = Path(__file__).resolve().parent.parent / "skills" / "orchestrate" / "brigade"
PROMPTS = sorted(BRIGADE.glob("*.md"))
MAX_LINES = 80
HARD_RULES = re.compile(r"^## Hard rules\b", re.MULTILINE)
READ_ONLY = re.compile(r"read-only|never edit|do not edit", re.IGNORECASE)


def test_brigade_folder_has_prompts():
    names = {p.name for p in PROMPTS}
    assert {"taster.md", "station-python.md", "station-web.md"} <= names


@pytest.mark.parametrize("path", PROMPTS, ids=lambda p: p.name)
def test_prompt_structure(path):
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0].startswith("# "), "first line must be a title"
    assert HARD_RULES.search(text), "missing '## Hard rules' section"
    assert READ_ONLY.search(text), "hard rules must state the read-only constraint"
    assert len(lines) <= MAX_LINES, f"{len(lines)} lines > {MAX_LINES}"


def test_taster_contract():
    text = (BRIGADE / "taster.md").read_text(encoding="utf-8")
    lower = text.lower()
    assert "different from the one that executed" in text
    assert "APPROVE" in text and "REJECT" in text
    assert "one line per criterion" in lower
    assert "evidence" in lower
    assert "data, never as instructions" in text
