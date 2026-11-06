"""The optional security pack (skills/security/*): shape checks + its own offline tests."""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PACK = ROOT / "skills" / "security"
SKILLS = sorted(p for p in PACK.iterdir() if (p / "SKILL.md").is_file())
NAMES = [p.name for p in SKILLS]
EXPECTED = ["seguranca-agentes", "seguranca-api", "seguranca-bots-webhooks",
            "seguranca-dados-lgpd", "seguranca-dependencias", "seguranca-infra",
            "seguranca-segredos", "seguranca-web-front"]


def front_matter(path):
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path}: no front matter"
    block = text.split("\n---", 1)[0]
    return dict(re.findall(r"^([a-z-]+):\s*(.+)$", block, flags=re.M))


def test_the_eight_skills_are_there():
    assert NAMES == EXPECTED


@pytest.mark.parametrize("skill", SKILLS, ids=NAMES)
def test_front_matter_matches_the_directory(skill):
    fm = front_matter(skill / "SKILL.md")
    assert fm["name"] == skill.name
    assert len(fm["description"]) > 40


@pytest.mark.parametrize("skill", SKILLS, ids=NAMES)
def test_every_skill_cites_its_sources(skill):
    fontes = skill / "references" / "fontes.md"
    assert fontes.is_file()
    text = fontes.read_text(encoding="utf-8")
    assert "http" in text
    assert re.search(r"^## Não confirmado", text, flags=re.M), "say what was NOT verified"


def test_pack_readme_declares_its_language():
    readme = (PACK / "README.md").read_text(encoding="utf-8")
    assert "português" in readme.lower()


def test_cross_references_point_at_skills_that_exist():
    for skill in SKILLS:
        text = (skill / "SKILL.md").read_text(encoding="utf-8")
        for ref in set(re.findall(r"`(seguranca-[a-z-]+)`", text)):
            assert ref in NAMES, f"{skill.name} mentions {ref}, which is not in the pack"


def run(cmd, cwd):
    env = {k: v for k, v in os.environ.items()}
    env["HOME"] = str(cwd)          # nothing can reach the real home
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, env=env,
                          stdin=subprocess.DEVNULL, timeout=120)


def test_webhook_verifier_own_tests():
    d = PACK / "seguranca-bots-webhooks" / "references"
    r = run([sys.executable, "-I", "teste_verificar_webhook.py"], d)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.count("ok ") >= 6


def test_pii_scan_own_tests():
    d = PACK / "seguranca-dados-lgpd" / "references"
    r = run([sys.executable, "teste_pii_scan.py"], d)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "falhas: 0" in r.stdout or "achados: 0" in r.stdout


def test_fence_hook_battery():
    d = PACK / "seguranca-agentes" / "references" / "cerca"
    r = run(["bash", "teste.sh", "./cerca.py"], d)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "falhas: 0" in r.stdout
