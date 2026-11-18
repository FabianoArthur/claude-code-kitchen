"""skills/third-party/install.sh — no network: a local git repository plays the upstream."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills" / "third-party" / "install.sh"
PINS = ROOT / "skills" / "third-party" / "pins.tsv"


def git(cwd, *args):
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@example.com",
                           *args], check=True, capture_output=True, text=True, env=env).stdout.strip()


@pytest.fixture
def upstream(tmp_path):
    repo = tmp_path / "upstream"
    skill = repo / "skills" / "demo"
    (skill / "hooks").mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: demo\n---\nbody\n")
    (skill / "notes.md").write_text("notes\n")
    (skill / "hooks" / "evil.sh").write_text("echo no\n")
    (repo / "hooks").mkdir()
    (repo / "hooks" / "top.sh").write_text("echo no\n")
    (repo / "settings.json").write_text("{}\n")
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    return repo


def pins_file(tmp_path, upstream, sha=None, path="skills/demo"):
    sha = sha or git(upstream, "rev-parse", "HEAD")
    f = tmp_path / "pins.tsv"
    f.write_text(f"# header\ndemo\t{upstream}\tv1\t{sha}\t{path}\n")
    return f


def run(tmp_path, pins, *args):
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_SKILLS_DIR"}
    env["HOME"] = str(tmp_path / "fake-home")
    target = tmp_path / "skills"
    cmd = [shutil.which("bash") or "bash", str(SCRIPT), "--pins", str(pins), "--target", str(target), *args]
    return subprocess.run(cmd,
                          capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)


def test_installs_only_the_skill_folder(tmp_path, upstream):
    r = run(tmp_path, pins_file(tmp_path, upstream))
    assert r.returncode == 0, r.stderr
    dest = tmp_path / "skills" / "demo"
    assert (dest / "SKILL.md").is_file() and (dest / "notes.md").is_file()
    assert not (dest / "settings.json").exists()


def test_wrong_sha_refuses_and_copies_nothing(tmp_path, upstream):
    r = run(tmp_path, pins_file(tmp_path, upstream, sha="0" * 40))
    assert r.returncode != 0
    assert not (tmp_path / "skills").exists()


def test_missing_skill_folder_refuses(tmp_path, upstream):
    r = run(tmp_path, pins_file(tmp_path, upstream, path="skills/nope"))
    assert r.returncode != 0
    assert not (tmp_path / "skills").exists()


def test_hooks_folder_is_never_copied(tmp_path, upstream):
    assert run(tmp_path, pins_file(tmp_path, upstream)).returncode == 0
    dest = tmp_path / "skills" / "demo"
    assert not (dest / "hooks").exists()
    assert not list(dest.rglob("*.sh"))


def test_existing_target_is_backed_up_not_deleted(tmp_path, upstream):
    old = tmp_path / "skills" / "demo"
    old.mkdir(parents=True)
    (old / "SKILL.md").write_text("mine\n")
    pins = pins_file(tmp_path, upstream)
    # no terminal and no --yes: refuses and leaves everything alone
    r = run(tmp_path, pins)
    assert r.returncode == 3
    assert (old / "SKILL.md").read_text() == "mine\n"
    r = run(tmp_path, pins, "--yes")
    assert r.returncode == 0, r.stderr
    backups = list((tmp_path / "skills").glob("demo.bak-*"))
    assert len(backups) == 1
    assert (backups[0] / "SKILL.md").read_text() == "mine\n"
    assert "body" in (old / "SKILL.md").read_text()


def test_dry_run_changes_nothing(tmp_path, upstream):
    r = run(tmp_path, pins_file(tmp_path, upstream), "--dry-run")
    assert r.returncode == 0
    assert "[dry-run]" in r.stdout
    assert not (tmp_path / "skills").exists()


def test_only_unknown_name_is_an_error(tmp_path, upstream):
    assert run(tmp_path, pins_file(tmp_path, upstream), "--only", "other").returncode == 2


def test_real_pins_are_full_shas_for_both_skills():
    rows = [line.split("\t") for line in PINS.read_text().splitlines() if line and not line.startswith("#")]
    assert [r[0] for r in rows] == ["archify", "ponytail"]
    for r in rows:
        assert len(r[3]) == 40 and set(r[3]) <= set("0123456789abcdef")
        assert r[1].startswith("https://github.com/")
