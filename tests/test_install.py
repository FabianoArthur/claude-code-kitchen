"""install.sh — always run against a temporary skills dir, never the real ~/.claude."""
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILLS = sorted(p.name for p in (ROOT / "skills").iterdir() if (p / "SKILL.md").is_file())


def install(target, *args, home=None):
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_SKILLS_DIR"}
    env["HOME"] = str(home or target.parent / "fake-home")  # a bug can never reach the real home
    return subprocess.run(["bash", str(ROOT / "install.sh"), "--target", str(target), *args],
                          capture_output=True, text=True, env=env)


@pytest.fixture
def target(tmp_path):
    return tmp_path / "skills"


def test_ships_the_six_skills():
    assert SKILLS == ["dotask", "execute", "harvest", "orchestrate", "plan", "qa"]


def test_fresh_install_links_every_skill(target):
    r = install(target)
    assert r.returncode == 0, r.stderr
    for name in SKILLS:
        link = target / name
        assert link.is_symlink()
        assert link.resolve() == (ROOT / "skills" / name).resolve()


def test_idempotent(target):
    install(target)
    before = {p.name: os.readlink(p) for p in target.iterdir()}
    r = install(target)
    assert r.returncode == 0
    assert {p.name: os.readlink(p) for p in target.iterdir()} == before
    assert r.stdout.count("already linked") == len(SKILLS)
    assert not list(target.glob("*.bak-*"))


def test_existing_directory_is_backed_up_not_clobbered(target):
    (target / "plan").mkdir(parents=True)
    (target / "plan" / "SKILL.md").write_text("my own plan skill\n")
    r = install(target)
    assert r.returncode == 0, r.stderr
    backups = list(target.glob("plan.bak-*"))
    assert len(backups) == 1
    assert (backups[0] / "SKILL.md").read_text() == "my own plan skill\n"
    assert (target / "plan").is_symlink()


def test_foreign_symlink_is_backed_up(target, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    target.mkdir()
    (target / "qa").symlink_to(elsewhere)
    install(target)
    backups = list(target.glob("qa.bak-*"))
    assert len(backups) == 1 and backups[0].is_symlink()
    assert backups[0].resolve() == elsewhere.resolve()
    assert (target / "qa").resolve() == (ROOT / "skills" / "qa").resolve()


def test_dry_run_changes_nothing(target):
    (target / "plan").mkdir(parents=True)
    r = install(target, "--dry-run")
    assert r.returncode == 0
    assert "[dry-run]" in r.stdout
    assert [p.name for p in target.iterdir()] == ["plan"]
    assert not (target / "plan").is_symlink()


def test_uninstall_removes_only_our_links(target):
    (target / "plan").mkdir(parents=True)
    (target / "unrelated").mkdir()
    install(target)
    r = install(target, "--uninstall")
    assert r.returncode == 0, r.stderr
    left = sorted(p.name for p in target.iterdir())
    assert "unrelated" in left
    assert not any((target / n).is_symlink() for n in SKILLS)
    assert any(n.startswith("plan.bak-") for n in left)   # backups are never deleted
    assert "mv" in r.stdout                               # says how to restore


def test_uninstall_dry_run_keeps_links(target):
    install(target)
    install(target, "--uninstall", "--dry-run")
    assert all((target / n).is_symlink() for n in SKILLS)


def test_unknown_flag_fails(target):
    r = install(target, "--bogus")
    assert r.returncode == 2
    assert not target.exists()


def test_env_var_target(tmp_path):
    target = tmp_path / "via-env"
    env = dict(os.environ, CLAUDE_SKILLS_DIR=str(target), HOME=str(tmp_path / "h"))
    r = subprocess.run(["bash", str(ROOT / "install.sh")], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert (target / "execute").is_symlink()


def test_shell_guard_only_acts_for_non_human_shells():
    import shutil
    if shutil.which("zsh") is None:
        pytest.skip("zsh not installed")
    guard = ROOT / "shell" / "zshrc-guard.zsh"
    base = {"PATH": os.environ["PATH"], "TERM_PROGRAM": "SomeTerm", "GHOSTTY_RESOURCES_DIR": "/x"}
    script = f'source "{guard}"; print -r -- "${{TERM_PROGRAM:-unset}} ${{GHOSTTY_RESOURCES_DIR:-unset}}"'
    human = subprocess.run(["zsh", "-f", "-c", script], env=base, capture_output=True, text=True)
    agent = subprocess.run(["zsh", "-f", "-c", script], env=dict(base, KITCHEN_SESSION="1"),
                           capture_output=True, text=True)
    claude = subprocess.run(["zsh", "-f", "-c", script], env=dict(base, CLAUDECODE="1"),
                            capture_output=True, text=True)
    assert human.stdout.strip() == "SomeTerm /x"
    assert agent.stdout.strip() == "unset unset"
    assert claude.stdout.strip() == "unset unset"
