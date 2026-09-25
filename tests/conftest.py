"""Shared fixtures. Importing the scripts as modules keeps them single-file and
dependency-free while letting pytest call their functions directly."""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ORCH = ROOT / "skills" / "orchestrate" / "scripts"
QA = ROOT / "skills" / "qa" / "scripts"


def load(path):
    path = Path(path)
    sys.path.insert(0, str(path.parent))  # qa scripts import each other
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def private_tmux(tmp_path, monkeypatch):
    """A tmux socket name that can never be the user's default server.

    TMUX_TMPDIR points into the test's tmp dir and TMUX is unset, so even a buggy call
    without `-L` cannot reach the real server. The server is killed on teardown.
    """
    import shutil
    import subprocess

    if shutil.which("tmux") is None:
        pytest.skip("tmux not installed")
    import tempfile

    # Unix socket paths are limited to ~104 bytes; pytest's tmp_path is too deep on macOS.
    sock_dir = Path(tempfile.mkdtemp(prefix="kt-", dir="/tmp" if os.path.isdir("/tmp") else None))
    monkeypatch.setenv("TMUX_TMPDIR", str(sock_dir))
    monkeypatch.delenv("TMUX", raising=False)
    name = f"kitchentest-{os.getpid()}"
    yield name
    subprocess.run(["tmux", "-L", name, "kill-server"], capture_output=True)
    shutil.rmtree(sock_dir, ignore_errors=True)
