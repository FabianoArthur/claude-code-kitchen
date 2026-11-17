"""safe_git.py — git on a unit-written tree, with an allowlisted config."""
import os
import subprocess
import sys

import pytest

from conftest import ORCH, load

safe_git = load(ORCH / "safe_git.py")

POSIX = os.name == "posix"
ENV = {
    **os.environ,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}


def plain(*argv, cwd=None):
    """Ordinary git, outside safe_git (this is what a careless caller would run)."""
    return subprocess.run(["git", *argv], cwd=cwd, env=ENV, check=True, capture_output=True,
                          text=True)


def make_marker_script(path, marker, body="cat"):
    path.write_text(f"#!/bin/sh\ntouch '{marker}'\n{body}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture
def repo(tmp_path):
    """A clone (git init + one commit) and a linked worktree."""
    clone = tmp_path / "clone"
    plain("init", "-q", str(clone))
    (clone / "a.txt").write_text("hello\n", encoding="utf-8")
    plain("add", "a.txt", cwd=clone)
    plain("commit", "-q", "-m", "first", cwd=clone)
    wt = tmp_path / "wt"
    plain("worktree", "add", "-q", "-b", "feat/x", str(wt), cwd=clone)
    return clone, wt


def assert_refused(clone, wt, *names, **kw):
    with pytest.raises(safe_git.GitRefused) as exc:
        safe_git.check(clone, wt, **kw)
    for name in names:
        assert name in str(exc.value)
    assert "\n" not in str(exc.value)
    return exc.value


# ---- trees that must pass -------------------------------------------------------------

def test_fresh_init_and_worktree_pass(repo):
    clone, wt = repo
    safe_git.check(clone)
    safe_git.check(clone, wt)


def test_fresh_clone_passes(tmp_path, repo):
    src, _ = repo
    dst = tmp_path / "cloned"
    plain("clone", "-q", str(src), str(dst))
    safe_git.check(dst)
    safe_git.check(dst, url=str(src))
    plain("worktree", "add", "-q", "-b", "feat/y", str(tmp_path / "wt2"), cwd=dst)
    safe_git.check(dst, tmp_path / "wt2", url=str(src))


def test_git_and_status_porcelain_run_when_clean(repo):
    clone, wt = repo
    res = safe_git.git(clone, wt, "rev-parse", "--abbrev-ref", "HEAD")
    assert res.returncode == 0 and res.stdout.strip() == "feat/x"
    assert safe_git.status_porcelain(clone, wt) == []
    (wt / "new.txt").write_text("x\n", encoding="utf-8")
    assert safe_git.status_porcelain(clone, wt) == ["?? new.txt"]


def test_allowed_keys_pass_and_branch_keys_any_name(repo):
    clone, wt = repo
    plain("config", "user.name", "Someone", cwd=clone)
    plain("config", "branch.feat/x.remote", "origin", cwd=clone)
    plain("config", "branch.feat/x.merge", "refs/heads/feat/x", cwd=clone)
    safe_git.check(clone, wt)


# ---- refusals by config key -----------------------------------------------------------

@pytest.mark.parametrize("key", ["core.askpass", "core.fsmonitor", "core.sshCommand",
                                 "include.path", "includeIf.gitdir:/x/.path", "alias.st",
                                 "remote.origin.pushurl",
                                 "filter.x.clean", "gpg.program"])
def test_key_outside_allowlist_is_refused_by_name(repo, key):
    clone, wt = repo
    plain("config", key, "value", cwd=clone)
    assert_refused(clone, wt, key.split(".")[0].lower())


def test_key_case_is_ignored(repo):
    clone, wt = repo
    plain("config", "GPG.Program", "/bin/true", cwd=clone)
    assert_refused(clone, wt, "gpg.program")


def test_config_worktree_file_is_checked(repo):
    clone, wt = repo
    git_dir = plain("rev-parse", "--absolute-git-dir", cwd=wt).stdout.strip()
    plain("config", "--file", os.path.join(git_dir, "config.worktree"), "core.askpass", "/x")
    assert_refused(clone, wt, "core.askpass", "config.worktree")


def test_common_config_worktree_file_is_checked(repo):
    clone, wt = repo
    plain("config", "--file", str(clone / ".git" / "config.worktree"), "core.pager", "/x")
    assert_refused(clone, wt, "core.pager")


def test_unreadable_config_is_refused_not_empty(repo):
    clone, wt = repo
    (clone / ".git" / "config").write_text("[core\n", encoding="utf-8")
    with pytest.raises(safe_git.GitRefused):
        safe_git.check(clone, wt)


# ---- refusals by value and by object store --------------------------------------------

def test_fetch_with_two_values_is_refused(repo):
    clone, wt = repo
    plain("remote", "add", "origin", "https://example.com/r.git", cwd=clone)
    safe_git.check(clone, wt)
    plain("config", "--add", "remote.origin.fetch", "+refs/pull/*:refs/remotes/origin/pr/*",
          cwd=clone)
    assert_refused(clone, wt, "remote.origin.fetch")


def test_fetch_with_other_value_is_refused(repo):
    clone, wt = repo
    plain("remote", "add", "origin", "https://example.com/r.git", cwd=clone)
    plain("config", "remote.origin.fetch", "+refs/heads/main:refs/remotes/origin/evil", cwd=clone)
    assert_refused(clone, wt, "remote.origin.fetch")


def test_url_must_match_when_given(repo):
    clone, wt = repo
    plain("remote", "add", "origin", "https://example.com/r.git", cwd=clone)
    safe_git.check(clone, wt, url="https://example.com/r.git")
    assert_refused(clone, wt, "remote.origin.url", url="https://example.com/other.git")


def test_url_given_but_no_remote_is_refused(repo):
    clone, wt = repo
    assert_refused(clone, wt, "remote.origin.url", url="https://example.com/r.git")


def test_grafts_is_refused(repo):
    clone, wt = repo
    sha = plain("rev-parse", "HEAD", cwd=clone).stdout.strip()
    plain("rev-parse", "--git-dir", cwd=clone)  # control: the repo is readable
    (clone / ".git" / "info").mkdir(exist_ok=True)
    (clone / ".git" / "info" / "grafts").write_text(f"{sha}\n", encoding="utf-8")
    assert_refused(clone, wt, "info/grafts")


def test_shallow_is_refused(repo):
    clone, wt = repo
    sha = plain("rev-parse", "HEAD", cwd=clone).stdout.strip()
    (clone / ".git" / "shallow").write_text(f"{sha}\n", encoding="utf-8")
    assert_refused(clone, wt, "shallow")


def test_common_dir_of_another_clone_is_refused(tmp_path, repo):
    clone, _ = repo
    other = tmp_path / "other"
    plain("init", "-q", str(other))
    plain("commit", "-q", "--allow-empty", "-m", "x", cwd=other)
    plain("worktree", "add", "-q", "-b", "feat/o", str(tmp_path / "wt-o"), cwd=other)
    safe_git.check(other, tmp_path / "wt-o")  # control: each pair alone is fine
    assert_refused(clone, tmp_path / "wt-o", "common dir")


def test_not_a_repo_is_refused(tmp_path):
    (tmp_path / "plain").mkdir()
    with pytest.raises(safe_git.GitRefused):
        safe_git.check(tmp_path / "plain")


def test_reason_is_ascii_single_line(tmp_path, repo):
    clone, wt = repo
    plain("config", "core.askpass", "café\nline", cwd=clone)
    err = assert_refused(clone, wt, "core.askpass")
    assert str(err).isascii()


# ---- armed scenarios: the refusal must come before the program runs --------------------

@pytest.mark.skipif(not POSIX, reason="needs a #!/bin/sh marker script")
def test_gpg_program_never_runs_through_safe_git(repo, tmp_path):
    clone, wt = repo
    marker = tmp_path / "gpg-ran"
    script = make_marker_script(tmp_path / "gpg.sh", marker, "exit 1")
    tree = plain("rev-parse", "HEAD^{tree}", cwd=clone).stdout.strip()
    sig = "gpgsig -----BEGIN PGP SIGNATURE-----\n \n fake\n -----END PGP SIGNATURE-----\n"
    body = (f"tree {tree}\nauthor t <t@example.com> 1 +0000\n"
            f"committer t <t@example.com> 1 +0000\n{sig}\nsigned\n")
    sha = subprocess.run(["git", "hash-object", "-t", "commit", "-w", "--stdin"], cwd=clone,
                         env=ENV, input=body, check=True, capture_output=True,
                         text=True).stdout.strip()
    plain("update-ref", "refs/heads/feat/x", sha, cwd=clone)
    plain("config", "gpg.program", str(script), cwd=clone)
    plain("config", "log.showSignature", "true", cwd=clone)
    # Control: plain git does run the planted program.
    plain("log", "-1", cwd=wt)
    assert marker.exists(), "scenario is not armed: plain git did not run gpg.program"
    marker.unlink()
    with pytest.raises(safe_git.GitRefused) as exc:
        safe_git.git(clone, wt, "log", "-1")
    assert "gpg.program" in str(exc.value) or "log.showsignature" in str(exc.value).lower()
    assert not marker.exists()


@pytest.mark.skipif(not POSIX, reason="needs a #!/bin/sh marker script")
def test_filter_clean_never_runs_through_safe_git(repo, tmp_path):
    clone, wt = repo
    marker = tmp_path / "filter-ran"
    script = make_marker_script(tmp_path / "clean.sh", marker)
    (wt / ".gitattributes").write_text("*.txt filter=x\n", encoding="utf-8")
    (wt / "a.txt").write_text("changed, different size\n", encoding="utf-8")
    plain("config", "filter.x.clean", str(script), cwd=clone)
    # Control: `git add` always pipes the file through the clean filter. (`git status` can
    # skip the filter when the size changed, because the stat data already says "modified".)
    plain("add", "a.txt", cwd=wt)
    assert marker.exists(), "scenario is not armed: plain git did not run filter.x.clean"
    marker.unlink()
    with pytest.raises(safe_git.GitRefused) as exc:
        safe_git.status_porcelain(clone, wt)
    assert "filter.x.clean" in str(exc.value)
    assert not marker.exists()


@pytest.mark.skipif(not POSIX, reason="needs a #!/bin/sh marker script")
def test_core_askpass_is_refused_before_any_git(repo, tmp_path):
    clone, wt = repo
    marker = tmp_path / "askpass-ran"
    script = make_marker_script(tmp_path / "ask.sh", marker, "echo x")
    plain("config", "core.askpass", str(script), cwd=clone)
    with pytest.raises(safe_git.GitRefused) as exc:
        safe_git.git(clone, wt, "status")
    assert "core.askpass" in str(exc.value)
    assert not marker.exists()


def test_git_does_not_run_the_command_when_refused(repo, monkeypatch):
    clone, wt = repo
    plain("config", "core.askpass", "/x", cwd=clone)
    calls = []
    real = safe_git._exec
    monkeypatch.setattr(safe_git, "_exec", lambda argv, cwd=None: (calls.append(argv), real(argv, cwd))[1])
    with pytest.raises(safe_git.GitRefused):
        safe_git.git(clone, wt, "checkout", "main")
    assert calls, "control: the pre-check reads did run"
    assert all("checkout" not in argv for argv in calls)
    assert all(argv[1:2] == ["--no-replace-objects"] for argv in calls)


def test_check_is_repeated_on_every_call(repo):
    clone, wt = repo
    assert safe_git.git(clone, wt, "rev-parse", "HEAD").returncode == 0
    plain("config", "core.askpass", "/x", cwd=clone)
    with pytest.raises(safe_git.GitRefused):
        safe_git.git(clone, wt, "rev-parse", "HEAD")


def test_command_line_has_safe_flags_and_env(repo, monkeypatch):
    clone, wt = repo
    seen = []
    real = safe_git._exec

    def spy(argv, cwd=None):
        seen.append(argv)
        return real(argv, cwd)

    monkeypatch.setattr(safe_git, "_exec", spy)
    monkeypatch.setenv("GIT_DIR", "/nonexistent")
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "'core.askpass=/x'")
    safe_git.git(clone, wt, "diff", "HEAD")
    argv = seen[-1]
    assert "--no-replace-objects" in argv
    assert "core.hooksPath=/dev/null" in argv and "core.fsmonitor=false" in argv
    assert "--no-ext-diff" in argv and "--no-textconv" in argv
    env = safe_git._env()
    assert env["GIT_NO_REPLACE_OBJECTS"] == "1"
    assert env["GIT_CONFIG_NOSYSTEM"] == "1" and env["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert "GIT_DIR" not in env and "GIT_CONFIG_PARAMETERS" not in env


def test_status_failure_is_refusal_not_empty_list(repo, monkeypatch):
    clone, wt = repo
    real = safe_git._exec
    assert safe_git.status_porcelain(clone, wt) == []  # control: the real git works

    def failing(argv, cwd=None):
        if "status" in argv:
            return subprocess.CompletedProcess(argv, 128, "", "fatal: broken")
        return real(argv, cwd)

    monkeypatch.setattr(safe_git, "_exec", failing)
    with pytest.raises(safe_git.GitRefused) as exc:
        safe_git.status_porcelain(clone, wt)
    assert "status" in str(exc.value)


# ---- CLI ------------------------------------------------------------------------------

def run_cli(*args):
    return subprocess.run([sys.executable, str(ORCH / "safe_git.py"), *args],
                          capture_output=True, text=True)


def test_cli_ok_and_refused_exit_codes(repo):
    clone, wt = repo
    ok = run_cli("check", str(clone), str(wt))
    assert ok.returncode == 0, ok.stderr
    plain("config", "core.askpass", "/x", cwd=clone)
    bad = run_cli("check", str(clone), str(wt))
    assert bad.returncode == 7
    assert "core.askpass" in bad.stderr and len(bad.stderr.strip().splitlines()) == 1


def test_cli_url_option(repo):
    clone, wt = repo
    plain("remote", "add", "origin", "https://example.com/r.git", cwd=clone)
    assert run_cli("check", str(clone), "--url", "https://example.com/r.git").returncode == 0
    assert run_cli("check", str(clone), "--url", "https://example.com/x.git").returncode == 7


def test_cli_usage_error():
    assert run_cli("check").returncode == 2


def test_selftest():
    res = run_cli("--selftest")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "ALL PASSED" in res.stdout
