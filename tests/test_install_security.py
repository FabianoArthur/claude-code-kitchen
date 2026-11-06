"""install.sh --with-security — the optional pack is opt-in and uninstalls cleanly.

Always run against a temporary skills dir, never the real ~/.claude."""
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PACK = ROOT / "skills" / "security"
SECURITY = sorted(p.name for p in PACK.iterdir() if (p / "SKILL.md").is_file())


def install(target, *args):
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_SKILLS_DIR"}
    env["HOME"] = str(target.parent / "fake-home")
    return subprocess.run(["bash", str(ROOT / "install.sh"), "--target", str(target), *args],
                          capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)


@pytest.fixture
def target(tmp_path):
    return tmp_path / "skills"


def test_the_pack_has_eight_skills():
    assert len(SECURITY) == 8
    assert all(n.startswith("seguranca-") for n in SECURITY)


def test_default_install_does_not_link_the_pack(target):
    r = install(target)
    assert r.returncode == 0, r.stderr
    assert not [p for p in target.iterdir() if p.name.startswith("seguranca-")]
    assert "--with-security" in r.stdout            # the hint is shown


def test_flag_links_the_pack(target):
    r = install(target, "--with-security")
    assert r.returncode == 0, r.stderr
    for name in SECURITY:
        link = target / name
        assert link.is_symlink()
        assert link.resolve() == (PACK / name).resolve()


def test_flag_is_idempotent(target):
    install(target, "--with-security")
    before = {p.name: os.readlink(p) for p in target.iterdir()}
    r = install(target, "--with-security")
    assert r.returncode == 0
    assert {p.name: os.readlink(p) for p in target.iterdir()} == before
    assert not list(target.glob("*.bak-*"))


def test_dry_run_with_flag_changes_nothing(target):
    r = install(target, "--with-security", "--dry-run")
    assert r.returncode == 0
    assert not target.exists()
    assert r.stdout.count("seguranca-") >= len(SECURITY)


def test_existing_pack_skill_is_not_moved_without_consent(target):
    (target / "seguranca-api").mkdir(parents=True)
    (target / "seguranca-api" / "SKILL.md").write_text("mine\n")
    r = install(target, "--with-security")
    assert r.returncode == 3
    assert (target / "seguranca-api" / "SKILL.md").read_text() == "mine\n"
    assert not (target / "plan").exists()           # nothing was changed at all


def test_without_flag_a_same_named_skill_is_left_alone(target):
    (target / "seguranca-api").mkdir(parents=True)
    r = install(target)
    assert r.returncode == 0, r.stderr
    assert not (target / "seguranca-api").is_symlink()


def test_uninstall_removes_the_pack_links_and_only_ours(target):
    install(target, "--with-security")
    (target / "seguranca-api").unlink()
    (target / "seguranca-api").mkdir()
    (target / "seguranca-api" / "SKILL.md").write_text("mine\n")
    r = install(target, "--uninstall")
    assert r.returncode == 0, r.stderr
    assert not [p for p in target.iterdir() if p.is_symlink()]
    assert (target / "seguranca-api" / "SKILL.md").read_text() == "mine\n"
