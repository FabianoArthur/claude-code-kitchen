"""QA scripts: every --selftest plus contract checks across scripts."""
import subprocess
import sys

import pytest

from conftest import QA, load

SCRIPTS = ["qa_budget.py", "qa_matrix.py", "qa_report.py", "qa_filter.py",
           "qa_preflight.py", "qa_mutation.py", "qa_watcher.py"]


@pytest.mark.parametrize("script", SCRIPTS)
def test_selftest(script):
    r = subprocess.run([sys.executable, str(QA / script), "--selftest"],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]


def test_matrix_and_budget_caps_agree():
    budget = load(QA / "qa_budget.py")
    matrix = load(QA / "qa_matrix.py")
    assert {d: c["cases"] for d, c in budget.CAPS.items()} == matrix.CASE_CAP


def test_skeleton_emits_three_bva_rows_per_limit(tmp_path, capsys):
    matrix = load(QA / "qa_matrix.py")
    (tmp_path / "facts.tsv").write_text("id\tsource\tfact\tlimits\nF1\ta:1\tcap\t100;7d\n")
    matrix.skeleton(tmp_path)
    rows = [r for r in capsys.readouterr().out.splitlines()[1:] if r.startswith("C")]
    assert len(rows) == 6 and all("\tBVA\t" in r for r in rows)


def test_mutation_refuses_dirty_file_outside_git(tmp_path):
    target = tmp_path / "x.py"
    target.write_text("def f(a):\n    return a > 1\n")
    r = subprocess.run([sys.executable, str(QA / "qa_mutation.py"), str(target),
                        "--cmd", f"{sys.executable} -c pass"], capture_output=True, text=True)
    assert r.returncode == 2 and "SAFETY" in r.stdout
    assert target.read_text() == "def f(a):\n    return a > 1\n"
