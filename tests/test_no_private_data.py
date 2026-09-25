"""Guard the public tree against personal or internal data.

Generic patterns are checked here, in the open. Project- or company-specific terms are
NOT listed in this repo (that would publish them): put them, one per line, in a local,
git-ignored `.private-denylist` and this test checks them too.
"""
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DENYLIST = ROOT / ".private-denylist"

ALLOWED_EMAILS = re.compile(
    r"(noreply@anthropic\.com|@users\.noreply\.github\.com|@([a-z0-9-]+\.)*example\.(com|org|net)$)", re.I)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
HOME_PATH = re.compile(r"/(Users|home)/[A-Za-z0-9._-]+/")
TOKENS = re.compile(
    r"(pk_\d{3,}_[A-Z0-9]{8,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}"
    r"|xox[abp]-[A-Za-z0-9-]{10,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})")
# Long pure-digit ids (tracker list/space ids, chat channel ids). Hex SHAs are excluded by
# requiring a non-hex neighbour, and the pinned checksums in CI are 64 hex chars anyway.
LONG_ID = re.compile(r"(?<![0-9a-fA-F])\d{11,}(?![0-9a-fA-F])")


def tracked_files():
    out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout.split()
    for name in out:
        path = ROOT / name
        if name == ".private-denylist" or not path.is_file():
            continue
        try:
            yield name, path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue


def hits(pattern, allow=None):
    found = []
    for name, text in tracked_files():
        for n, line in enumerate(text.splitlines(), 1):
            for m in pattern.finditer(line):
                if allow and allow.search(m.group(0)):
                    continue
                found.append(f"{name}:{n}: {m.group(0)}")
    return found


def test_no_home_paths():
    assert hits(HOME_PATH) == []


def test_no_real_email_addresses():
    assert hits(EMAIL, ALLOWED_EMAILS) == []


def test_no_token_shaped_strings():
    assert hits(TOKENS) == []


def test_no_long_numeric_ids():
    assert hits(LONG_ID) == []


def test_local_denylist():
    if not DENYLIST.is_file():
        pytest.skip("no local .private-denylist (optional)")
    terms = [t.strip().lower() for t in DENYLIST.read_text(encoding="utf-8").splitlines()
             if t.strip() and not t.startswith("#")]
    found = []
    for name, text in tracked_files():
        for n, line in enumerate(text.splitlines(), 1):
            low = line.lower()
            for term in terms:
                if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", low):
                    if name == "LICENSE" and "copyright" in low:
                        continue
                    found.append(f"{name}:{n}: <term #{terms.index(term) + 1}>")
    assert found == [], "private terms found (terms not echoed): " + ", ".join(found)
