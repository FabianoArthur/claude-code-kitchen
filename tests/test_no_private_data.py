"""Guard the public tree against personal or internal data.

Generic patterns are checked here, in the open. Project- or company-specific terms are
NOT listed in this repo (that would publish them): put them, one per line, in a local,
git-ignored `.private-denylist` and this test checks them too.

Two optional variables let the same check vet another tree before it is published:
- KITCHEN_CHECK_ROOT: scan this git tree instead of this clone (the denylist stays this clone's);
- KITCHEN_CHECK_EXTRA: extra files to scan (for example a PR title and body), separated by os.pathsep.
The scanned tree is only read as data: symlinks are checked by their link text and never followed,
and only regular files are opened.
"""
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DENYLIST = ROOT / ".private-denylist"
SCAN_ROOT = Path(os.environ.get("KITCHEN_CHECK_ROOT") or ROOT)
EXTRA = [p for p in os.environ.get("KITCHEN_CHECK_EXTRA", "").split(os.pathsep) if p]

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


def read_data(path):
    """Text of a file without following links: link text for a symlink, content for a regular file.

    Returns None for anything else (FIFO, socket, device, missing, not UTF-8).
    """
    try:
        mode = os.lstat(path).st_mode
        if stat.S_ISLNK(mode):
            return os.readlink(path)
        if not stat.S_ISREG(mode):
            return None
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        return None
    with os.fdopen(fd, "rb") as fh:
        if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
            return None
        try:
            return fh.read().decode("utf-8")
        except UnicodeDecodeError:
            return None


def tracked_files():
    out = subprocess.run(["git", "-c", "core.fsmonitor=false", "ls-files", "-z", "-co", "--exclude-standard"],
                         cwd=SCAN_ROOT, capture_output=True, text=True, check=True).stdout.split("\0")
    for name in filter(None, out):
        if name == ".private-denylist" and SCAN_ROOT == ROOT:
            continue
        text = read_data(SCAN_ROOT / name)
        if text is not None:
            yield name, text
    for n, extra in enumerate(EXTRA, 1):
        text = read_data(extra)
        if text is not None:
            yield f"<extra file #{n}>", text


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
