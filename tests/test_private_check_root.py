"""Tests for KITCHEN_CHECK_ROOT / KITCHEN_CHECK_EXTRA in tests/test_no_private_data.py.

The target tree is hostile test data: it carries a fake `pytest.py`, `_pytest/__init__.py`, a
`conftest.py` and a `pyproject.toml` with `addopts = -p x`, all of which write a marker file if
they ever run. The check must run from this clone, import nothing from the target and never
follow a symlink out of it.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHECK = ROOT / "tests" / "test_no_private_data.py"
TOKEN_TEST = f"{CHECK}::test_no_token_shaped_strings"
# Built at run time so this file does not itself look like a token to the scan.
SECRET = "gh" + "p_" + "A" * 36

MARKER_CODE = (
    "import os\n"
    "open(os.environ['KITCHEN_TEST_MARKER'], 'a').write('ran ' + __name__ + '\\n')\n"
)


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def symlink(link, dest):
    try:
        link.symlink_to(dest)
    except OSError as exc:  # Windows without the symlink privilege
        pytest.skip(f"cannot create symlinks here: {exc}")


def python_flags():
    """`-I` unless pytest only lives in the user site (then isolated mode cannot import it)."""
    probe = subprocess.run([sys.executable, "-I", "-c", "import pytest"], capture_output=True)
    return ["-I"] if probe.returncode == 0 else []


def run_check(tmp_path, root=None, extra=None):
    env = {k: v for k, v in os.environ.items()
           if k not in ("KITCHEN_CHECK_ROOT", "KITCHEN_CHECK_EXTRA", "PYTEST_ADDOPTS")}
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["KITCHEN_TEST_MARKER"] = str(tmp_path / "marker.txt")
    if root is not None:
        env["KITCHEN_CHECK_ROOT"] = str(root)
    if extra is not None:
        env["KITCHEN_CHECK_EXTRA"] = os.pathsep.join(str(e) for e in extra)
    cmd = [sys.executable, *python_flags(), "-m", "pytest", "--rootdir", str(ROOT),
           "-c", str(ROOT / "pyproject.toml"), "-p", "no:cacheprovider", TOKEN_TEST]
    return subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)


@pytest.fixture
def target(tmp_path):
    """A git tree with hostile Python files that write a marker if they are imported or run."""
    tree = tmp_path / "target"
    (tree / "_pytest").mkdir(parents=True)
    (tree / "pytest.py").write_text(MARKER_CODE)
    (tree / "_pytest" / "__init__.py").write_text(MARKER_CODE)
    (tree / "conftest.py").write_text(MARKER_CODE)
    (tree / "pyproject.toml").write_text('[tool.pytest.ini_options]\naddopts = "-p x"\n')
    (tree / "notes.txt").write_text("harmless\n")
    git(tree, "init", "-q")
    return tree


def test_clean_target_passes_and_nothing_from_it_runs(tmp_path, target):
    # Positive control: the hostile files do write the marker when imported on purpose.
    env = dict(os.environ, KITCHEN_TEST_MARKER=str(tmp_path / "marker.txt"))
    subprocess.run([sys.executable, "-c", "import conftest"], cwd=target, env=env, check=True)
    assert (tmp_path / "marker.txt").exists()
    (tmp_path / "marker.txt").unlink()

    result = run_check(tmp_path, root=target)
    assert "1 passed" in result.stdout, result.stdout + result.stderr
    assert not (tmp_path / "marker.txt").exists()


def test_secret_in_target_is_found_in_a_regular_file(tmp_path, target):
    (target / "leak.txt").write_text(f"token = {SECRET}\n")
    result = run_check(tmp_path, root=target)
    assert result.returncode != 0
    assert "leak.txt:1" in result.stdout
    assert not (tmp_path / "marker.txt").exists()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs POSIX FIFOs and symlinks")
def test_symlink_is_not_followed_and_fifo_does_not_hang(tmp_path, target):
    # Positive control: the same secret in a regular file of the target is found.
    (target / "leak.txt").write_text(f"token = {SECRET}\n")
    assert run_check(tmp_path, root=target).returncode != 0
    (target / "leak.txt").unlink()

    outside = tmp_path / "outside.txt"
    outside.write_text(f"token = {SECRET}\n")
    symlink(target / "k", outside)
    os.mkfifo(target / "pipe")
    result = run_check(tmp_path, root=target)  # the 120 s timeout fails the test if the FIFO blocks
    assert "1 passed" in result.stdout, result.stdout + result.stderr
    assert SECRET not in result.stdout
    assert not (tmp_path / "marker.txt").exists()


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="needs symlinks")
def test_symlink_text_is_scanned(tmp_path, target):
    symlink(target / "link", "/" + "home" + "/someone/secret.txt")
    result = run_check(tmp_path, root=target)
    assert result.returncode != 0 and "link:1" in result.stdout


def test_extra_files_are_scanned(tmp_path, target):
    title = tmp_path / "title.txt"
    body = tmp_path / "body.txt"
    title.write_text("a clean title\n")
    body.write_text(f"body mentions {SECRET}\n")
    clean = run_check(tmp_path, root=target, extra=[title])
    assert "1 passed" in clean.stdout, clean.stdout + clean.stderr
    dirty = run_check(tmp_path, root=target, extra=[title, body])
    assert dirty.returncode != 0 and "<extra file #2>:1" in dirty.stdout


def test_without_variables_it_scans_this_clone(tmp_path):
    result = run_check(tmp_path)
    assert "1 passed" in result.stdout, result.stdout + result.stderr
