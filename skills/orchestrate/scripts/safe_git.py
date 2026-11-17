#!/usr/bin/env python3
"""
safe_git — run git on a clone or worktree that a unit has written to, with an allowlisted config.

A linked worktree shares the clone's local config, `config.worktree`, `info/` and `shallow`
with every other unit. A unit can therefore plant `gpg.program` + `log.showSignature`,
`filter.<x>.clean`, `core.askpass`, `core.fsmonitor`, an `include.path`, grafts... and the
next git the waiter runs (log, status, diff, checkout) would execute a program the unit
chose, with the waiter's powers. Every waiter git on such a tree goes through this module.

`check()` refuses unless ALL of these hold (it runs on every call, because other live
units share the clone):

  1. every key of the local config of the clone and of the worktree, and of the files
     `<git-dir>/config.worktree` and `<git-common-dir>/config.worktree`, is on the
     allowlist (case-insensitive). Anything else, `include.path` and `includeIf.*` too,
     is a refusal that names the key;
  2. `remote.origin.fetch` is empty or exactly `+refs/heads/*:refs/remotes/origin/*`, and
     with `url`, `remote.origin.url` is exactly that url;
  3. the common dir has neither `info/grafts` nor `shallow`, and it is `<clone>/.git`
     (realpath comparison, never a string prefix).

Before the check only `rev-parse --git-dir|--git-common-dir` and `config --list|--get-all`
run, always with the system and global config switched off. `git()` then runs the real
command with `--no-replace-objects`, `GIT_NO_REPLACE_OBJECTS=1`, hooks and fsmonitor off,
and no external diff or textconv. A config that cannot be read, or a `git status` that
fails, is a refusal, never an empty answer.

Limits: the check and the command are two git invocations, so a unit that rewrites the
config in between wins the race; the closed environment and the per-call lock belong to
the callers. This module narrows the window, it is not a sandbox against a malicious unit.

Usage:
    python3 safe_git.py check <clone> [<worktree>] [--url <url>]     exit 0 ok, 7 refused
    python3 safe_git.py --selftest
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

EXIT_REFUSED = 7

GIT_BIN = "git"
FETCH_SPEC = "+refs/heads/*:refs/remotes/origin/*"

# Keys git itself writes on init, clone, remote add and worktree add, plus identity.
ALLOWED_KEY = re.compile(
    r"core\.(bare|filemode|ignorecase|logallrefupdates|repositoryformatversion|symlinks"
    r"|precomposeunicode)"
    r"|remote\.origin\.(url|fetch)"
    r"|user\.(name|email)"
    r"|branch\..+\.(remote|merge)",
    re.IGNORECASE,
)

# Flags on every git the waiter runs on a unit's tree.
SAFE_FLAGS = ["--no-replace-objects", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false"]
# Subcommands that can run an external diff driver or a textconv filter.
DIFFING = {"diff", "log", "show"}
PASS_ENV = ("PATH", "HOME", "SYSTEMROOT", "TMPDIR", "TEMP", "TMP")


class GitRefused(Exception):
    """The tree cannot be trusted; the caller must stop. The message is one ASCII line."""

    def __init__(self, reason):
        super().__init__(ascii(str(reason))[1:-1])


def _env():
    """Environment built from scratch: no GIT_* from the caller, no system/global/XDG config."""
    env = {k: os.environ[k] for k in PASS_ENV if k in os.environ}
    env.update(
        LC_ALL="C",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL="/dev/null",
        XDG_CONFIG_HOME="/dev/null",
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_TERMINAL_PROMPT="0",
    )
    return env


def _exec(argv, cwd=None):
    """The one place that starts git (tests patch it to simulate a failing git)."""
    try:
        return subprocess.run(
            argv, cwd=cwd, env=_env(), stdin=subprocess.DEVNULL, capture_output=True,
            text=True, encoding="utf-8", errors="surrogateescape", check=False,
        )
    except OSError as exc:
        raise GitRefused(f"cannot run git: {exc}") from None


def _read(directory, *args):
    """Pre-check read (rev-parse / config only). Returns the completed process."""
    return _exec([GIT_BIN, *SAFE_FLAGS, "-C", str(directory), *args])


def _dir_of(directory, what):
    res = _read(directory, "rev-parse", what)
    if res.returncode != 0 or not res.stdout.strip():
        raise GitRefused(f"{directory}: rev-parse {what} failed (rc {res.returncode})")
    return Path(os.path.realpath(os.path.join(str(directory), res.stdout.strip())))


def _parse(stdout):
    """`config --list -z` output → list of (key, value)."""
    entries = []
    for chunk in stdout.split("\0"):
        if chunk:
            key, _, value = chunk.partition("\n")
            entries.append((key, value))
    return entries


def _entries(res, source):
    if res.returncode != 0:
        raise GitRefused(f"cannot read git config of {source} (rc {res.returncode})")
    return _parse(res.stdout)


def _values(directory, key):
    res = _read(directory, "config", "--local", "--get-all", key)
    if res.returncode not in (0, 1):  # 1 = key absent
        raise GitRefused(f"cannot read {key} of {directory} (rc {res.returncode})")
    return res.stdout.split("\n")[:-1] if res.stdout else []


def check(clone, worktree=None, url=None):
    """Raise GitRefused unless the config and the object store of the tree are trusted."""
    clone = Path(clone)
    trees = [clone] + ([Path(worktree)] if worktree is not None else [])
    expected_common = Path(os.path.realpath(clone / ".git"))
    commons = set()
    sources = []  # (label, [(key, value)])
    for tree in trees:
        git_dir = _dir_of(tree, "--git-dir")
        common = _dir_of(tree, "--git-common-dir")
        if common != expected_common:
            raise GitRefused(f"common dir of {tree} is {common}, expected {expected_common}")
        commons.add(common)
        sources.append((f"local config of {tree}",
                        _entries(_read(tree, "config", "--local", "--list", "-z"), f"{tree}")))
        for folder in (git_dir, common):
            cfg = folder / "config.worktree"
            if cfg.exists():
                res = _exec([GIT_BIN, *SAFE_FLAGS, "config", "--file", str(cfg), "--list", "-z"])
                sources.append((str(cfg), _entries(res, str(cfg))))
    for label, entries in sources:
        for key, value in entries:
            if not ALLOWED_KEY.fullmatch(key):
                raise GitRefused(f"config key not allowed: {key} (in {label})")
            if key.lower() == "remote.origin.fetch" and value != FETCH_SPEC:
                raise GitRefused(f"remote.origin.fetch is {value!r} (in {label})")
            if key.lower() == "remote.origin.url" and url is not None and value != url:
                raise GitRefused(f"remote.origin.url is {value!r}, expected {url!r} (in {label})")
    for tree in trees:
        fetch = _values(tree, "remote.origin.fetch")
        if fetch and fetch != [FETCH_SPEC]:
            raise GitRefused(f"remote.origin.fetch of {tree} is {fetch!r}")
        if url is not None and _values(tree, "remote.origin.url") != [url]:
            raise GitRefused(f"remote.origin.url of {tree} is not {url!r}")
    (common,) = commons
    for name in ("info/grafts", "shallow"):
        if (common / name).exists():
            raise GitRefused(f"{name} exists in {common}")


def git(clone, worktree, *args, url=None):
    """Check the tree, then run git with the safe flags in the worktree (or the clone)."""
    check(clone, worktree, url=url)
    args = list(args)
    if args and args[0] in DIFFING:
        args[1:1] = ["--no-ext-diff", "--no-textconv"]
    cwd = worktree if worktree is not None else clone
    return _exec([GIT_BIN, *SAFE_FLAGS, "-C", str(cwd), *args])


def status_porcelain(clone, worktree=None):
    """`git status --porcelain -z` entries. A failing git is a refusal, never a clean tree."""
    res = git(clone, worktree, "status", "--porcelain", "-z", "--ignore-submodules=all")
    if res.returncode != 0:
        raise GitRefused(f"git status failed in {worktree or clone} (rc {res.returncode})")
    return [e for e in res.stdout.split("\0") if e]


def selftest():
    ok = True

    def case(name, cond):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + name)
        ok = ok and cond

    def plain(*argv, cwd=None):
        env = {**_env(), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
        subprocess.run([GIT_BIN, *argv], cwd=cwd, env=env, check=True, capture_output=True)

    def refused(*a, **kw):
        try:
            check(*a, **kw)
        except GitRefused as exc:
            return str(exc)
        return None

    with tempfile.TemporaryDirectory() as tmp:
        clone = Path(tmp) / "clone"
        plain("init", "-q", str(clone))
        plain("commit", "-q", "--allow-empty", "-m", "init", cwd=clone)
        case("fresh init passes", refused(clone) is None)
        plain("worktree", "add", "-q", "-b", "feat/x", str(Path(tmp) / "wt"), cwd=clone)
        wt = Path(tmp) / "wt"
        case("worktree passes", refused(clone, wt) is None)
        plain("config", "core.askpass", "/bin/true", cwd=clone)
        msg = refused(clone, wt)
        case("core.askpass refused by name", msg is not None and "core.askpass" in msg)
        plain("config", "--unset", "core.askpass", cwd=clone)
        (clone / ".git" / "info" / "grafts").write_text("", encoding="utf-8")
        msg = refused(clone)
        case("grafts refused", msg is not None and "info/grafts" in msg)
    print("\nselftest:", "ALL PASSED" if ok else "FAILED")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    args = list(argv)
    url = None
    if "--url" in args:
        i = args.index("--url")
        if i + 1 >= len(args):
            print("usage: safe_git.py check <clone> [<worktree>] [--url <url>]", file=sys.stderr)
            return 2
        url = args[i + 1]
        del args[i:i + 2]
    if not args or args[0] != "check" or not 2 <= len(args) <= 3:
        print("usage: safe_git.py check <clone> [<worktree>] [--url <url>]", file=sys.stderr)
        return 2
    try:
        check(args[1], args[2] if len(args) == 3 else None, url=url)
    except GitRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
