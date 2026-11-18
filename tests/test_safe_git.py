"""safe_git.py — git on a unit-written tree, with an allowlisted config."""
import os
import shutil
import stat
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


@pytest.fixture(autouse=True)
def kitchen_home(tmp_path, monkeypatch):
    """A temporary HOME with the kitchen-git folder that `safe_git.py init` makes."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    safe_git.init()
    return home


@pytest.fixture
def local_urls(monkeypatch):
    """Tests whose origin is a local path accept any url scheme."""
    monkeypatch.setattr(safe_git, "URL_SCHEMES", ("",))


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


def test_fresh_clone_passes(tmp_path, repo, local_urls):
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
    kitchen = safe_git._kitchen_dir()
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_CONFIG_GLOBAL"] == str(kitchen / "gitconfig")
    assert env["XDG_CONFIG_HOME"] == str(kitchen / "xdg")
    assert os.path.isabs(env["GH_CONFIG_DIR"])
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


# ---- closed environment, kitchen-git folder, url rules ---------------------------------

FAKE_GIT = """#!/bin/sh
/usr/bin/env > '{dump}'.$$
exec '{real}' "$@"
"""


def sign_head(clone, branch="feat/x"):
    """Rewrite `branch` to a commit with a (fake) gpgsig header."""
    tree = plain("rev-parse", "HEAD^{tree}", cwd=clone).stdout.strip()
    sig = "gpgsig -----BEGIN PGP SIGNATURE-----\n \n fake\n -----END PGP SIGNATURE-----\n"
    body = (f"tree {tree}\nauthor t <t@example.com> 1 +0000\n"
            f"committer t <t@example.com> 1 +0000\n{sig}\nsigned\n")
    sha = subprocess.run(["git", "hash-object", "-t", "commit", "-w", "--stdin"], cwd=clone,
                         env=ENV, input=body, check=True, capture_output=True,
                         text=True).stdout.strip()
    plain("update-ref", f"refs/heads/{branch}", sha, cwd=clone)


def install_fake_git(tmp_path, monkeypatch, dump_name):
    dump = tmp_path / dump_name
    fake = tmp_path / "fake-git"
    fake.write_text(FAKE_GIT.format(dump=dump, real=shutil.which("git")), encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setattr(safe_git, "GIT_BIN", str(fake))
    return dump


@pytest.mark.skipif(not POSIX, reason="needs a #!/bin/sh fake git")
def test_home_and_xdg_config_never_reach_the_waiter_git(repo, tmp_path, kitchen_home,
                                                        monkeypatch):
    clone, wt = repo
    marker = tmp_path / "gpg-ran"
    script = make_marker_script(tmp_path / "gpg.sh", marker, "exit 1")
    sign_head(clone)
    user_cfg = f"[gpg]\n\tprogram = {script}\n[log]\n\tshowSignature = true\n"
    (kitchen_home / ".gitconfig").write_text(user_cfg, encoding="utf-8")
    xdg = tmp_path / "xdg-real"
    (xdg / "git").mkdir(parents=True)
    (xdg / "git" / "config").write_text(user_cfg, encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    # Control: ordinary git with this HOME runs the planted program.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(["git", "log", "-1"], cwd=wt, env=env, check=True, capture_output=True)
    assert marker.exists(), "scenario is not armed: plain git did not run gpg.program"
    marker.unlink()
    install_fake_git(tmp_path, monkeypatch, "env-dump")
    for name, value in (("GIT_DIR", "/nonexistent"), ("GIT_CONFIG_COUNT", "1"),
                        ("GIT_CONFIG_KEY_0", "core.askpass"), ("GIT_CONFIG_VALUE_0", "/x"),
                        ("GIT_CONFIG_PARAMETERS", "'core.askpass=/x'"),
                        ("GIT_SSH_COMMAND", "/x")):
        monkeypatch.setenv(name, value)
    res = safe_git.git(clone, wt, "log", "-1")
    assert res.returncode == 0, res.stderr
    assert not marker.exists()
    dumps = list(tmp_path.glob("env-dump.*"))
    assert dumps, "control: the fake git did not run"
    kitchen = safe_git._kitchen_dir()
    allowed_git = {"GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL", "GIT_NO_REPLACE_OBJECTS",
                   "GIT_TERMINAL_PROMPT"}
    for path in dumps:
        seen = dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)
        assert not [k for k in seen if k.startswith("GIT_") and k not in allowed_git]
        assert seen["GIT_CONFIG_NOSYSTEM"] == "1"
        assert seen["GIT_CONFIG_GLOBAL"] == str(kitchen / "gitconfig")
        assert seen["XDG_CONFIG_HOME"] == str(kitchen / "xdg")
        assert seen["GH_CONFIG_DIR"] == os.path.abspath(seen["GH_CONFIG_DIR"])


def test_every_git_of_the_module_uses_the_closed_env(repo, monkeypatch):
    clone, wt = repo
    envs = []
    real = subprocess.run

    def spy(argv, **kw):
        envs.append(kw["env"])
        return real(argv, **kw)

    monkeypatch.setenv("GIT_DIR", "/nonexistent")
    monkeypatch.setattr(safe_git.subprocess, "run", spy)
    safe_git.git(clone, wt, "rev-parse", "HEAD")
    assert len(envs) > 3, "control: the pre-check reads ran"
    for env in envs:
        assert "GIT_DIR" not in env and env["GIT_CONFIG_NOSYSTEM"] == "1"
        assert env["GIT_CONFIG_GLOBAL"] == str(safe_git._kitchen_dir() / "gitconfig")


def test_env_keeps_only_the_allowlist(monkeypatch):
    monkeypatch.setenv("SECRET_TOKEN", "x")
    monkeypatch.setenv("GIT_ASKPASS", "/x")
    monkeypatch.setenv("KITCHEN_UNIT", "U-1")
    monkeypatch.setenv("LC_CTYPE", "C")
    env = safe_git._env()
    assert "SECRET_TOKEN" not in env and "GIT_ASKPASS" not in env
    assert env["KITCHEN_UNIT"] == "U-1" and env["LC_CTYPE"] == "C"
    assert env["LC_ALL"] == "C"


def test_init_is_idempotent_and_valid(kitchen_home):
    safe_git.init()
    safe_git._validate_kitchen()
    assert (kitchen_home / ".claude" / "kitchen-git" / "xdg").is_dir()


@pytest.mark.skipif(not POSIX, reason="needs POSIX modes")
def test_init_modes():
    base = safe_git._kitchen_dir()
    assert stat.S_IMODE(base.stat().st_mode) == 0o700
    assert stat.S_IMODE((base / "gitconfig").stat().st_mode) == 0o600


def test_missing_kitchen_git_is_refused(repo, kitchen_home):
    clone, wt = repo
    shutil.rmtree(kitchen_home / ".claude")
    with pytest.raises(safe_git.GitRefused) as exc:
        safe_git.check(clone, wt)
    assert "kitchen-git" in str(exc.value)


@pytest.mark.skipif(not POSIX, reason="needs POSIX modes")
def test_gitconfig_mode_0644_is_refused(repo):
    clone, wt = repo
    safe_git.check(clone, wt)  # control: valid before the change
    (safe_git._kitchen_dir() / "gitconfig").chmod(0o644)
    with pytest.raises(safe_git.GitRefused) as exc:
        safe_git.check(clone, wt)
    assert "gitconfig" in str(exc.value) and "0o644" in str(exc.value)


@pytest.mark.skipif(not POSIX, reason="needs POSIX modes")
def test_kitchen_dir_mode_is_refused(repo):
    clone, wt = repo
    safe_git._kitchen_dir().chmod(0o755)
    with pytest.raises(safe_git.GitRefused) as exc:
        safe_git.check(clone, wt)
    assert "kitchen-git folder" in str(exc.value)


def test_gitconfig_with_askpass_is_refused(repo):
    clone, wt = repo
    safe_git.check(clone, wt)  # control
    plain("config", "--file", str(safe_git._kitchen_dir() / "gitconfig"), "core.askpass", "/x")
    with pytest.raises(safe_git.GitRefused) as exc:
        safe_git.check(clone, wt)
    assert "core.askpass" in str(exc.value)


def test_xdg_folder_must_stay_empty(repo):
    clone, wt = repo
    (safe_git._kitchen_dir() / "xdg" / "git").mkdir()
    with pytest.raises(safe_git.GitRefused) as exc:
        safe_git.check(clone, wt)
    assert "xdg" in str(exc.value)


def test_credential_helper_values(repo, monkeypatch):
    clone, wt = repo
    gitconfig = safe_git._kitchen_dir() / "gitconfig"
    monkeypatch.setattr(safe_git, "_gh_abs", lambda: "/opt/tools/gh")
    plain("config", "--file", str(gitconfig), "--unset-all", safe_git.CREDENTIAL_KEY)
    plain("config", "--file", str(gitconfig), "--add", safe_git.CREDENTIAL_KEY, "")
    plain("config", "--file", str(gitconfig), "--add", safe_git.CREDENTIAL_KEY,
          "!/opt/tools/gh auth git-credential")
    safe_git.check(clone, wt)  # the values `gh auth setup-git` writes
    plain("config", "--file", str(gitconfig), "--add", safe_git.CREDENTIAL_KEY, "!/tmp/evil")
    with pytest.raises(safe_git.GitRefused) as exc:
        safe_git.check(clone, wt)
    assert "helper" in str(exc.value)


def test_init_writes_the_gh_helper(tmp_path, monkeypatch):
    home = tmp_path / "home2"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(safe_git, "_gh_abs", lambda: "/opt/tools/gh")
    safe_git.init()
    text = (home / ".claude" / "kitchen-git" / "gitconfig").read_text(encoding="utf-8")
    assert "!/opt/tools/gh auth git-credential" in text


@pytest.mark.parametrize("sub", ["fetch", "ls-remote", "push", "remote"])
def test_remote_commands_need_a_url(repo, monkeypatch, sub):
    clone, wt = repo
    calls = []
    monkeypatch.setattr(safe_git, "_exec", lambda argv, cwd=None: calls.append(argv))
    with pytest.raises(safe_git.GitRefused) as exc:
        safe_git.git(clone, wt, sub, "origin")
    assert "url" in str(exc.value)
    assert calls == []


def make_origin(tmp_path, repo):
    """A bare origin and a clone of it whose origin url is a local path."""
    src, _ = repo
    bare = tmp_path / "origin.git"
    plain("clone", "-q", "--bare", str(src), str(bare))
    work = tmp_path / "work"
    plain("clone", "-q", str(bare), str(work))
    return bare, work


def spy_exec(monkeypatch):
    calls = []
    real = safe_git._exec

    def spy(argv, cwd=None):
        calls.append(argv)
        return real(argv, cwd)

    monkeypatch.setattr(safe_git, "_exec", spy)
    return calls


def test_changed_origin_url_is_refused_before_fetch(tmp_path, repo, local_urls):
    bare, work = make_origin(tmp_path, repo)
    url = str(bare)
    assert safe_git.git(work, None, "fetch", "origin", url=url).returncode == 0  # control
    other = tmp_path / "othér.git"
    plain("clone", "-q", "--bare", str(bare), str(other))
    plain("config", "remote.origin.url", str(other), cwd=work)
    before = plain("for-each-ref", cwd=bare).stdout
    with pytest.raises(safe_git.GitRefused) as exc:
        safe_git.git(work, None, "fetch", "origin", url=url)
    msg = str(exc.value)
    assert "remote.origin.url" in msg and "xe9" in msg and msg.isascii()
    assert plain("for-each-ref", cwd=bare).stdout == before
    plain("config", "remote.origin.url", url, cwd=work)
    assert safe_git.git(work, None, "fetch", "origin", url=url).returncode == 0


def test_fetch_never_brings_tags(tmp_path, repo, local_urls):
    bare, work = make_origin(tmp_path, repo)
    src = repo[0]
    base = plain("symbolic-ref", "--short", "HEAD", cwd=src).stdout.strip()
    # A new commit on the origin, tagged `origin/<base>` and `<base>` after the clone.
    (src / "b.txt").write_text("b\n", encoding="utf-8")
    plain("add", "b.txt", cwd=src)
    plain("commit", "-q", "-m", "second", cwd=src)
    plain("push", "-q", str(bare), f"HEAD:refs/heads/{base}", cwd=src)
    sha = plain("rev-parse", f"refs/heads/{base}", cwd=bare).stdout.strip()
    plain("tag", f"origin/{base}", sha, cwd=bare)
    plain("tag", base, sha, cwd=bare)
    # Control: on a copy of the scenario, a plain fetch writes both tags into the clone.
    copy = tmp_path / "work-copy"
    shutil.copytree(work, copy)
    plain("fetch", "-q", "origin", cwd=copy)
    tags = plain("for-each-ref", "--format=%(refname)", "refs/tags/", cwd=copy).stdout.split()
    assert sorted(tags) == sorted([f"refs/tags/origin/{base}", f"refs/tags/{base}"])
    # The waiter fetch moves the branch and leaves no tag.
    assert safe_git.git(work, None, "fetch", "origin", url=str(bare)).returncode == 0
    assert plain("rev-parse", f"refs/remotes/origin/{base}", cwd=work).stdout.strip() == sha
    assert plain("for-each-ref", "refs/tags/", cwd=work).stdout == ""


@pytest.mark.parametrize("flag", ["--tags", "-t", "-qt"])
def test_fetch_with_tags_flag_is_refused(tmp_path, repo, local_urls, monkeypatch, flag):
    bare, work = make_origin(tmp_path, repo)
    assert safe_git.git(work, None, "fetch", "origin", url=str(bare)).returncode == 0  # control
    calls = spy_exec(monkeypatch)
    with pytest.raises(safe_git.GitRefused) as exc:
        safe_git.git(work, None, "fetch", flag, "origin", url=str(bare))
    assert "tags" in str(exc.value)
    assert calls == []


def test_fetch_gets_no_tags_flag_once(tmp_path, repo, local_urls, monkeypatch):
    bare, work = make_origin(tmp_path, repo)
    calls = spy_exec(monkeypatch)
    safe_git.git(work, None, "fetch", "origin", url=str(bare))
    assert calls[-1].count("--no-tags") == 1
    safe_git.git(work, None, "fetch", "--no-tags", "origin", url=str(bare))
    assert calls[-1].count("--no-tags") == 1


@pytest.mark.skipif(not POSIX, reason="needs a #!/bin/sh fake git")
@pytest.mark.parametrize("url", ["git@example.com:o/r.git", "ssh://git@example.com/o/r.git",
                                 "file:///tmp/r.git", "/tmp/r.git"])
def test_non_https_url_is_refused_by_scheme(repo, tmp_path, monkeypatch, url):
    clone, wt = repo
    install_fake_git(tmp_path, monkeypatch, "ran")
    plain("remote", "add", "origin", "https://example.com/r.git", cwd=clone)
    # Control: with the fake git in place, an https url reaches git (the dump is written).
    safe_git.git(clone, wt, "ls-remote", "--get-url", "origin", url="https://example.com/r.git")
    assert list(tmp_path.glob("ran.*")), "control: the fake git did not run"
    for old in tmp_path.glob("ran.*"):
        old.unlink()
    plain("config", "remote.origin.url", url, cwd=clone)
    with pytest.raises(safe_git.GitRefused) as exc:
        safe_git.git(clone, wt, "fetch", "origin", url=url)
    assert "scheme" in str(exc.value)
    assert not list(tmp_path.glob("ran.*"))


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
