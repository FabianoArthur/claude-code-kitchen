"""check_tasks.py — missing and cyclic dependencies block, shared files only warn."""
import json
import subprocess
import sys

from conftest import ORCH, load

mod = load(ORCH / "check_tasks.py")
SCRIPT = ORCH / "check_tasks.py"


def write(folder, name, status="backlog", deps="", body="", id_line=True):
    ident = f"id: {name}\n" if id_line else ""
    (folder / f"{name}.md").write_text(
        f"---\n{ident}status: {status}\ndepends_on: {deps}\n---\n{body}\n", encoding="utf-8")


def cli(folder, *extra):
    return subprocess.run([sys.executable, str(SCRIPT), str(folder), *extra],
                          capture_output=True, text=True)


def test_clean_folder_exits_zero(tmp_path):
    write(tmp_path, "A")
    write(tmp_path, "B", deps="[A]")
    result = cli(tmp_path)
    assert result.returncode == 0
    assert "2 task(s); 0 blocker(s); 0 warning(s)" in result.stdout


def test_missing_dependency_exits_one_and_names_it(tmp_path):
    write(tmp_path, "A", deps="GHOST-9")
    result = cli(tmp_path)
    assert result.returncode == 1
    assert "A: unknown dependency GHOST-9" in result.stdout


def test_cycle_exits_one_with_path(tmp_path):
    write(tmp_path, "A", deps="B")
    write(tmp_path, "B", deps="C")
    write(tmp_path, "C", deps="A")
    result = cli(tmp_path)
    assert result.returncode == 1
    assert "cycle: A -> B -> C -> A" in result.stdout


def test_self_dependency_blocks(tmp_path):
    write(tmp_path, "A", deps="A")
    result = cli(tmp_path)
    assert result.returncode == 1
    assert "A: depends on itself" in result.stdout


def test_shared_file_warns_but_exits_zero(tmp_path):
    write(tmp_path, "A", body="Touches src/app/main.py")
    write(tmp_path, "B", body="Also edits src/app/main.py")
    result = cli(tmp_path)
    assert result.returncode == 0
    assert "WARNING src/app/main.py cited by A, B" in result.stdout


def test_shared_file_with_dependency_does_not_warn(tmp_path):
    write(tmp_path, "A", body="src/app/main.py")
    write(tmp_path, "B", deps="A", body="src/app/main.py")
    result = cli(tmp_path)
    assert result.returncode == 0
    assert "1 task" not in result.stdout and "2 task(s); 0 blocker(s); 0 warning(s)" in result.stdout


def test_done_tasks_do_not_warn(tmp_path):
    write(tmp_path, "A", status="done", body="src/app/main.py")
    write(tmp_path, "B", body="src/app/main.py")
    assert "0 warning(s)" in cli(tmp_path).stdout


def test_block_list_and_filename_id(tmp_path):
    (tmp_path / "one.md").write_text(
        "---\nstatus: backlog\ndepends_on:\n  - two\n  - nope\n---\n", encoding="utf-8")
    write(tmp_path, "two", id_line=False)
    result = cli(tmp_path)
    assert result.returncode == 1
    assert "one: unknown dependency nope" in result.stdout
    assert "unknown dependency two" not in result.stdout


def test_json_output(tmp_path):
    write(tmp_path, "A", deps="X")
    data = json.loads(cli(tmp_path, "--json").stdout)
    assert data["tasks"] == 1 and data["blockers"] == ["A: unknown dependency X"]


def test_bad_usage_exits_two(tmp_path):
    assert cli(tmp_path / "missing").returncode == 2


def test_selftest():
    result = subprocess.run([sys.executable, str(SCRIPT), "--selftest"],
                            capture_output=True, text=True)
    assert result.returncode == 0 and "SELFTEST OK" in result.stdout


def test_parse_ids_ignores_none():
    assert mod.parse_ids("") == [] and mod.parse_ids("[A, B]") == ["A", "B"]
    assert mod.parse_ids("none") == []
