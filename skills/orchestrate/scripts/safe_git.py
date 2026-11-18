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
run. `git()` then runs the real command with `--no-replace-objects`,
`GIT_NO_REPLACE_OBJECTS=1`, hooks and fsmonitor off, and no external diff or textconv. A
config that cannot be read, or a `git status` that fails, is a refusal, never an empty answer.

Closed environment: every git of this module, the reads before the check included, runs
with an environment built from scratch: a short allowlist of variables, no inherited
`GIT_*`, `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=~/.claude/kitchen-git/gitconfig`,
`XDG_CONFIG_HOME=~/.claude/kitchen-git/xdg` and an absolute `GH_CONFIG_DIR`. So `~/.gitconfig`,
`$XDG_CONFIG_HOME/git/config` and the system config never reach the waiter's git. On every
call the `kitchen-git` folder must be 0700 and owned by the user, `gitconfig` 0600 with only
allowlisted keys (plus the credential helper `gh auth setup-git` writes for github.com), and
`xdg` empty. `safe_git.py init` creates them.

Remote commands: `fetch`, `ls-remote`, `push` and `remote` need `url`, which must start with
one of `URL_SCHEMES` (https only: this module never runs ssh) and must equal
`remote.origin.url`. `fetch` always gets `--no-tags`; `--tags` and `-t` are refused.

Limits: the check and the command are two git invocations, so a unit that rewrites the
config in between wins the race; the per-call lock belongs to the callers. This module
narrows the window, it is not a sandbox against a malicious unit.

Submodules and nested repositories: a repository inside the worktree (`git init sub`, then
`git add sub` makes a gitlink) makes `git status` and `git diff` start a child git inside
`sub`, which reads the config of `sub`, which nobody checked; a `filter.x.clean` there runs
as the waiter. So every git of this module carries `submodule.recurse=false`,
`diff.ignoreSubmodules=all`, `status.submoduleSummary=false`, `fetch.recurseSubmodules=false`
and `protocol.file.allow=never` (`FILE_PROTOCOL`; tests with a local origin swap it for
`always`), and `status`/`diff` get `--ignore-submodules=all`. After the config check,
`check()` also refuses (on every call) when:

  4. `ls-files -s -z` of the worktree, or `ls-tree -r -z <sha>` of the sha the call
     received, has mode 160000 (a gitlink);
  5. a `.git` (folder, `gitdir:` file or symlink) exists below the root of a tree, found by
     `os.walk` without following symlinks and without running git. Names are compared
     casefolded and without the code points HFS+ ignores. Only the root `.git` is skipped
     and, in the main clone, the registered worktrees;
  6. `<git-common-dir>/objects/info/alternates` exists.

Output that a program reads uses `-z`, paths go after `--`, and whatever is shown to a
human goes through `ascii()`. The list of changed paths comes from `diff_tree()`
(plumbing, which shows a gitlink; porcelain `diff` hides it).

gh: `gh(*args, cwd=...)` runs the absolute `gh` with the same closed environment plus
`GIT_CONFIG_COUNT`/`KEY_n`/`VALUE_n` (hooks and fsmonitor off, the submodule keys),
`GIT_CEILING_DIRECTORIES` = parent of the cwd and `GIT_DIR` = an absent path in the cwd, so the
git inside `gh` finds no repository. The cwd must be `~/.claude/kitchen-runs/<kind>-<ID>` or
`.../doctor`, 0700, owned by the user, with no `.git` in it or above it up to HOME, and outside
the clone and every registered worktree. Every call carries `--repo <owner>/<name>` (except
`api repos/<owner>/<name>/...` and `auth status`) and `pr create` also `--head`. Nothing else
in `scripts/` starts gh.

Usage:
    python3 safe_git.py init                                         create ~/.claude/kitchen-git
    python3 safe_git.py check <clone> [<worktree>] [--url <url>]     exit 0 ok, 7 refused
    python3 safe_git.py --selftest
"""
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

EXIT_REFUSED = 7

GIT_BIN = "git"
GH_BIN = "gh"
FETCH_SPEC = "+refs/heads/*:refs/remotes/origin/*"
# The waiter never runs ssh. Tests with a local origin swap this with monkeypatch.
URL_SCHEMES = ("https://",)
# `never` also blocks fetch and push to a local origin: tests with a bare local origin
# swap it for "always" with monkeypatch.
FILE_PROTOCOL = "never"
# Subcommands that talk to a remote and therefore need the explicit url.
URL_COMMANDS = {"fetch", "ls-remote", "push", "remote"}
CREDENTIAL_KEY = "credential.https://github.com.helper"

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
# Subcommands that take --ignore-submodules.
SUBMODULE_AWARE = {"status", "diff"}
# Code points that HFS+ ignores when it compares names (`.g\u200cit` is `.git` there).
HFS_IGNORED = dict.fromkeys(
    [0x200C, 0x200D, 0x200E, 0x200F, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E,
     0x206A, 0x206B, 0x206C, 0x206D, 0x206E, 0x206F, 0xFEFF])
# Subcommands that can run an external diff driver or a textconv filter.
DIFFING = {"diff", "log", "show"}
# The minimal environment: these names, LC_* and KITCHEN_*. Nothing else is inherited.
PASS_ENV = ("PATH", "HOME", "USER", "LOGNAME", "SHELL", "TERM", "LANG", "TMPDIR")
if os.name != "posix":  # Windows cannot start a process without these
    PASS_ENV += ("SYSTEMROOT", "USERPROFILE", "TEMP", "TMP")
PASS_PREFIXES = ("LC_", "KITCHEN_")


class GitRefused(Exception):
    """The tree cannot be trusted; the caller must stop. The message is one ASCII line."""

    def __init__(self, reason):
        super().__init__(ascii(str(reason))[1:-1])


def _flags():
    """Flags on every git of this module. Read at call time: FILE_PROTOCOL can be patched."""
    return [*SAFE_FLAGS,
            "-c", "submodule.recurse=false",
            "-c", "diff.ignoreSubmodules=all",
            "-c", "status.submoduleSummary=false",
            "-c", "fetch.recurseSubmodules=false",
            "-c", f"protocol.file.allow={FILE_PROTOCOL}"]


def _kitchen_dir():
    return Path(os.path.expanduser("~")) / ".claude" / "kitchen-git"


def _gh_config_dir():
    """Absolute gh config dir, taken from the caller's own environment (gh keeps its login there)."""
    explicit = os.environ.get("GH_CONFIG_DIR")
    if explicit:
        return os.path.abspath(explicit)
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = xdg if xdg else os.path.join(os.path.expanduser("~"), ".config")
    return os.path.abspath(os.path.join(base, "gh"))


def _env():
    """Environment built from scratch: allowlist only, no GIT_* from the caller."""
    env = {k: v for k, v in os.environ.items()
           if k in PASS_ENV or k.startswith(PASS_PREFIXES)}
    kitchen = _kitchen_dir()
    env.update(
        LC_ALL="C",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=str(kitchen / "gitconfig"),
        XDG_CONFIG_HOME=str(kitchen / "xdg"),
        GH_CONFIG_DIR=_gh_config_dir(),
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_TERMINAL_PROMPT="0",
    )
    return env


def _run(argv, cwd=None):
    try:
        return subprocess.run(
            argv, cwd=cwd, env=_env(), stdin=subprocess.DEVNULL, capture_output=True,
            text=True, encoding="utf-8", errors="surrogateescape", check=False,
        )
    except OSError as exc:
        raise GitRefused(f"cannot run git: {exc}") from None


def _exec(argv, cwd=None):
    """The one place that starts git for the waiter (tests patch it to simulate a failing git)."""
    return _run(argv, cwd)


def _gh_abs():
    """Absolute path of gh, or None. The helper line `gh auth setup-git` writes uses it."""
    found = shutil.which(GH_BIN)
    return os.path.abspath(found) if found else None


def _helper_values():
    """Accepted value lists for the github.com helper: an empty value, then the gh helper."""
    gh = _gh_abs()
    if gh is None:
        return []
    return [["", f"!{path} auth git-credential"] for path in sorted({gh, os.path.realpath(gh)})]


def _owned(path, st, mode, what):
    if os.name == "posix":
        if st.st_uid != os.getuid():
            raise GitRefused(f"{what} {path} is not owned by the user")
        if stat.S_IMODE(st.st_mode) != mode:
            raise GitRefused(f"{what} {path} has mode {oct(stat.S_IMODE(st.st_mode))}, "
                             f"expected {oct(mode)}")


def _lstat(path, what, want_dir):
    try:
        st = os.lstat(path)
    except OSError:
        raise GitRefused(f"{what} {path} is missing (run safe_git.py init)") from None
    if want_dir and not stat.S_ISDIR(st.st_mode):
        raise GitRefused(f"{what} {path} is not a plain folder")
    if not want_dir and not stat.S_ISREG(st.st_mode):
        raise GitRefused(f"{what} {path} is not a regular file")
    return st


def _validate_kitchen():
    """Refuse unless the folder that holds git's own config is exactly what init made."""
    base = _kitchen_dir()
    _owned(base, _lstat(base, "kitchen-git folder", True), 0o700, "kitchen-git folder")
    xdg = base / "xdg"
    st = _lstat(xdg, "xdg folder", True)
    if os.name == "posix" and st.st_uid != os.getuid():
        raise GitRefused(f"xdg folder {xdg} is not owned by the user")
    if os.listdir(xdg):
        raise GitRefused(f"xdg folder {xdg} is not empty")
    cfg = base / "gitconfig"
    _owned(cfg, _lstat(cfg, "gitconfig", False), 0o600, "gitconfig")
    res = _run([GIT_BIN, *_flags(), "config", "--file", str(cfg), "--list", "-z"])
    helpers = []
    for key, value in _entries(res, str(cfg)):
        if key.lower() == CREDENTIAL_KEY:
            helpers.append(value)
        elif not ALLOWED_KEY.fullmatch(key):
            raise GitRefused(f"config key not allowed: {key} (in {cfg})")
    if helpers and helpers not in _helper_values():
        raise GitRefused(f"{CREDENTIAL_KEY} has unexpected values {helpers!r} (in {cfg})")


def init():
    """Create ~/.claude/kitchen-git (0700), its gitconfig (0600) and the empty xdg folder."""
    base = _kitchen_dir()
    base.parent.mkdir(parents=True, exist_ok=True)
    for folder in (base, base / "xdg"):
        folder.mkdir(exist_ok=True)
        if os.name == "posix":
            os.chmod(folder, 0o700)
    cfg = base / "gitconfig"
    if not cfg.exists():
        gh = _gh_abs()
        text = ""
        if gh is not None:
            cmd = f"!{gh} auth git-credential".replace("\\", "\\\\").replace('"', '\\"')
            text = f'[credential "https://github.com"]\n\thelper =\n\thelper = "{cmd}"\n'
        fd = os.open(cfg, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
    _validate_kitchen()


def _read(directory, *args):
    """Pre-check read (rev-parse / config only). Returns the completed process."""
    return _exec([GIT_BIN, *_flags(), "-C", str(directory), *args])


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


def check(clone, worktree=None, url=None, sha=None):
    """Raise GitRefused unless the config, the object store and the tree layout are trusted."""
    if url is not None and not url.startswith(URL_SCHEMES):
        raise GitRefused(f"url scheme not allowed: {url!r} (only {', '.join(URL_SCHEMES)})")
    _validate_kitchen()
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
                res = _exec([GIT_BIN, *_flags(), "config", "--file", str(cfg), "--list", "-z"])
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
    _check_no_nested(clone, trees, common, sha)


def _stdout(directory, *args):
    res = _read(directory, *args)
    if res.returncode != 0:
        raise GitRefused(f"git {args[0]} failed in {directory} (rc {res.returncode})")
    return res.stdout


def _has_gitlink(listing):
    """True when a `-z` listing of `ls-files -s` or `ls-tree` has an entry of mode 160000."""
    return any(chunk.split(" ", 1)[0] == "160000" for chunk in listing.split("\0") if chunk)


def _is_dot_git(name):
    return name.casefold().translate(HFS_IGNORED) == ".git"


def _registered_worktrees(common):
    """Roots of the worktrees registered in the common dir, read from files, without git."""
    roots = set()
    admin = common / "worktrees"
    if not admin.is_dir():
        return roots
    for entry in admin.iterdir():
        try:
            text = (entry / "gitdir").read_text(encoding="utf-8", errors="surrogateescape")
        except OSError:
            continue
        line = text.strip()
        if line:
            roots.add(os.path.realpath(os.path.dirname(line)))
    return roots


def _walk_for_dot_git(root, skip):
    """Refuse a `.git` below `root`. The root `.git` and the `skip` roots are not entered."""
    def fail(exc):
        raise GitRefused(f"cannot walk {root}: {exc}")

    root = str(root)
    for here, dirs, files in os.walk(root, followlinks=False, onerror=fail):
        at_root = here == root
        # Symlinks to folders are listed in `dirs` (and not followed): the name check sees them.
        names = [n for n in dirs + files if not (at_root and n == ".git")]
        for name in names:
            if _is_dot_git(name):
                raise GitRefused(f"nested .git below the root of {root}: "
                                 f"{os.path.join(here, name)}")
        dirs[:] = [d for d in dirs if not (at_root and d == ".git")
                   and os.path.realpath(os.path.join(here, d)) not in skip]


def _check_no_nested(clone, trees, common, sha):
    """Gitlinks, a `.git` below a root, and `alternates` are refusals (rules 4 to 6)."""
    for tree in trees:
        if _has_gitlink(_stdout(tree, "ls-files", "-s", "-z")):
            raise GitRefused(f"gitlink (mode 160000) in the index of {tree}")
    if sha is not None and _has_gitlink(_stdout(trees[-1], "ls-tree", "-r", "-z", sha)):
        raise GitRefused(f"gitlink (mode 160000) in tree {sha}")
    main = os.path.realpath(clone)
    for tree in trees:
        skip = _registered_worktrees(common) if os.path.realpath(tree) == main else set()
        _walk_for_dot_git(tree, skip)
    if os.path.lexists(common / "objects" / "info" / "alternates"):
        raise GitRefused(f"objects/info/alternates exists in {common}")


def git(clone, worktree, *args, url=None, sha=None):
    """Check the tree, then run git with the safe flags in the worktree (or the clone)."""
    args = list(args)
    sub = args[0] if args else None
    if sub in URL_COMMANDS and url is None:
        raise GitRefused(f"git {sub} needs an explicit url")
    if sub == "fetch":
        if any(a == "--tags" or re.fullmatch(r"-[A-Za-z]*t[A-Za-z]*", a) for a in args[1:]):
            raise GitRefused("git fetch with --tags or -t is not allowed")
        if "--no-tags" not in args:
            args.insert(1, "--no-tags")
    check(clone, worktree, url=url, sha=sha)
    if args and args[0] in DIFFING:
        args[1:1] = ["--no-ext-diff", "--no-textconv"]
    if sub in SUBMODULE_AWARE and "--ignore-submodules=all" not in args:
        args.insert(1, "--ignore-submodules=all")
    cwd = worktree if worktree is not None else clone
    return _exec([GIT_BIN, *_flags(), "-C", str(cwd), *args])


def status_porcelain(clone, worktree=None):
    """`git status --porcelain -z` entries. A failing git is a refusal, never a clean tree."""
    res = git(clone, worktree, "status", "--porcelain", "-z")
    if res.returncode != 0:
        raise GitRefused(f"git status failed in {worktree or clone} (rc {res.returncode})")
    return [e for e in res.stdout.split("\0") if e]


def diff_tree(clone, worktree, base, sha):
    """Changed paths from `diff-tree -r --raw -z --no-renames <base> <sha>`.

    Returns (old_mode, new_mode, status, path) tuples; a gitlink shows as mode 160000.
    Plumbing on purpose: the porcelain `diff` hides submodules. Show paths with ascii().
    """
    res = git(clone, worktree, "diff-tree", "-r", "--raw", "-z", "--no-renames", base, sha,
              "--", sha=sha)
    if res.returncode != 0:
        raise GitRefused(f"git diff-tree failed in {worktree or clone} (rc {res.returncode})")
    parts = res.stdout.split("\0")
    out = []
    i = 0
    while i + 1 < len(parts):
        if not parts[i].startswith(":"):
            i += 1
            continue
        old_mode, new_mode, _old, _new, status = parts[i][1:].split(" ")
        out.append((old_mode, new_mode, status, parts[i + 1]))
        i += 2
    return out


def ls_files(clone, worktree, *paths):
    """Tracked paths (`ls-files -z`), restricted to `paths`, which go after `--`."""
    args = ["ls-files", "-z"]
    if paths:
        args += ["--", *paths]
    res = git(clone, worktree, *args)
    if res.returncode != 0:
        raise GitRefused(f"git ls-files failed in {worktree or clone} (rc {res.returncode})")
    return [e for e in res.stdout.split("\0") if e]


REPO_NAME = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
RUN_DIR_NAME = re.compile(r"(doctor|[A-Za-z0-9]+-[A-Za-z0-9][A-Za-z0-9._-]*)")
NO_GIT_NAME = ".kitchen-no-git"


def _runs_root():
    return Path(os.path.realpath(os.path.join(os.path.expanduser("~"), ".claude", "kitchen-runs")))


def _inside(path, root):
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:  # different drives
        return False


def _check_gh_cwd(cwd, clone):
    """Return the realpath of `cwd` unless it is not a kitchen run folder that git cannot reach."""
    real = os.path.realpath(cwd)
    if clone is not None:
        main = os.path.realpath(clone)
        roots = {main} | _registered_worktrees(Path(os.path.realpath(os.path.join(main, ".git"))))
        for root in sorted(roots):
            if _inside(real, root):
                raise GitRefused(f"gh cwd {cwd} is inside the clone or a worktree ({root})")
    runs = _runs_root()
    if os.path.dirname(real) != str(runs) or not RUN_DIR_NAME.fullmatch(os.path.basename(real)):
        raise GitRefused(f"gh cwd {cwd} is not <kind>-<ID> or doctor under {runs}")
    _owned(real, _lstat(real, "gh cwd", True), 0o700, "gh cwd")
    home = os.path.realpath(os.path.expanduser("~"))
    here = real
    while True:
        if os.path.lexists(os.path.join(here, ".git")):
            raise GitRefused(f"gh cwd {cwd}: .git exists in {here}")
        if here == home:
            break
        parent = os.path.dirname(here)
        if parent == here:
            raise GitRefused(f"gh cwd {cwd} is not below HOME {home}")
        here = parent
    if os.path.lexists(os.path.join(real, NO_GIT_NAME)):
        raise GitRefused(f"gh cwd {cwd}: {NO_GIT_NAME} exists")
    return real


def _option_values(args, long, short):
    """Values given to `--long v`, `--long=v`, `-S v` or `-Sv`."""
    found = []
    for i, arg in enumerate(args):
        if arg == long or arg == short:
            found.append(args[i + 1] if i + 1 < len(args) else "")
        elif arg.startswith(long + "="):
            found.append(arg[len(long) + 1:])
        elif short and arg.startswith(short) and not arg.startswith("--"):
            found.append(arg[len(short):])
    return found


def _check_gh_args(args):
    """Every gh call names its repository; `pr create` also names its head."""
    if not args:
        raise GitRefused("gh needs arguments")
    if list(args[:2]) == ["auth", "status"]:
        return
    if args[0] == "api":
        endpoint = args[1] if len(args) > 1 else ""
        if not re.fullmatch(r"repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(/.*)?", endpoint):
            raise GitRefused(f"gh api needs repos/<owner>/<name>/... right after api, got {endpoint!r}")
        return
    repos = _option_values(args, "--repo", "-R")
    if not repos or not all(REPO_NAME.fullmatch(r) for r in repos):
        raise GitRefused(f"gh {args[0]} needs --repo <owner>/<name>, got {repos!r}")
    if list(args[:2]) == ["pr", "create"] and not any(_option_values(args, "--head", "-H")):
        raise GitRefused("gh pr create needs --head")


def _gh_env(real_cwd):
    """The closed environment plus config entries and a git that cannot find any repository."""
    env = _env()
    pairs = [_flags()[i + 1].partition("=")[::2] for i, f in enumerate(_flags()) if f == "-c"]
    env["GIT_CONFIG_COUNT"] = str(len(pairs))
    for n, (key, value) in enumerate(pairs):
        env[f"GIT_CONFIG_KEY_{n}"] = key
        env[f"GIT_CONFIG_VALUE_{n}"] = value
    env["GIT_CEILING_DIRECTORIES"] = os.path.dirname(real_cwd)
    env["GIT_DIR"] = os.path.join(real_cwd, NO_GIT_NAME)
    return env


def _exec_gh(gh_argv, cwd, env):
    """The one place that starts gh (tests patch PATH or this function)."""
    try:
        return subprocess.run(gh_argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="surrogateescape", check=False)
    except OSError as exc:
        raise GitRefused(f"cannot run gh: {exc}") from None


def gh(*args, cwd, clone=None):
    """Run the absolute `gh` with a closed environment, in a kitchen run folder outside any repo.

    `cwd` is `~/.claude/kitchen-runs/<kind>-<ID>` or `.../doctor` (0700, owned by the user, no
    `.git` up to HOME). Pass `clone` so a cwd inside the clone or a registered worktree is
    refused by name. gh's own git sees `GIT_DIR` pointing at an absent path.
    """
    _check_gh_args(args)
    _validate_kitchen()
    real = _check_gh_cwd(cwd, clone)
    exe = _gh_abs()
    if exe is None:
        raise GitRefused("gh not found on PATH")
    return _exec_gh([exe, *args], real, _gh_env(real))


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

    def refused(fn, *a, **kw):
        try:
            fn(*a, **kw)
        except GitRefused as exc:
            return str(exc)
        return None

    saved = {k: os.environ.get(k) for k in ("HOME", "USERPROFILE")}
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        os.environ["HOME"] = os.environ["USERPROFILE"] = str(home)
        try:
            msg = refused(check, Path(tmp))
            case("missing kitchen-git is refused", msg is not None and "init" in msg)
            init()
            case("init makes kitchen-git", (home / ".claude" / "kitchen-git" / "gitconfig").is_file())
            env = _env()
            case("closed env", "GIT_DIR" not in env and env["GIT_CONFIG_NOSYSTEM"] == "1"
                 and env["GIT_CONFIG_GLOBAL"].endswith("gitconfig"))
            clone = Path(tmp) / "clone"
            plain("init", "-q", str(clone))
            plain("commit", "-q", "--allow-empty", "-m", "init", cwd=clone)
            case("fresh init passes", refused(check, clone) is None)
            plain("worktree", "add", "-q", "-b", "feat/x", str(Path(tmp) / "wt"), cwd=clone)
            wt = Path(tmp) / "wt"
            case("worktree passes", refused(check, clone, wt) is None)
            msg = refused(git, clone, wt, "fetch", "origin")
            case("fetch without url refused", msg is not None and "url" in msg)
            msg = refused(check, clone, wt, url="git@example.com:o/r.git")
            case("ssh url refused", msg is not None and "scheme" in msg)
            msg = refused(git, clone, wt, "fetch", "--tags", "origin",
                          url="https://example.com/r.git")
            case("fetch --tags refused", msg is not None and "--tags" in msg)
            case("submodule flags on", "protocol.file.allow=never" in " ".join(_flags()))
            (wt / "sub").mkdir()
            (wt / "sub" / ".git").write_text("gitdir: /outside\n", encoding="utf-8")
            msg = refused(check, clone, wt)
            case("nested .git refused", msg is not None and "nested .git" in msg)
            (wt / "sub" / ".git").unlink()
            case("tree passes again", refused(check, clone, wt) is None)
            plain("config", "core.askpass", "/bin/true", cwd=clone)
            msg = refused(check, clone, wt)
            case("core.askpass refused by name", msg is not None and "core.askpass" in msg)
            plain("config", "--unset", "core.askpass", cwd=clone)
            (clone / ".git" / "info" / "grafts").write_text("", encoding="utf-8")
            msg = refused(check, clone)
            case("grafts refused", msg is not None and "info/grafts" in msg)
            case("gh without --repo refused", "--repo" in (refused(_check_gh_args, ["pr", "list"]) or ""))
            case("gh pr create without --head refused",
                 "--head" in (refused(_check_gh_args, ["pr", "create", "--repo", "o/r"]) or ""))
            case("gh api repos path ok", refused(_check_gh_args, ["api", "repos/o/r/pulls"]) is None)
            case("gh cwd outside kitchen-runs refused",
                 "kitchen-runs" in (refused(gh, "auth", "status", cwd=tmp) or ""))
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
    print("\nselftest:", "ALL PASSED" if ok else "FAILED")
    return 0 if ok else 1


USAGE = ("usage: safe_git.py init | check <clone> [<worktree>] [--url <url>] | --selftest")


def main(argv):
    if "--selftest" in argv:
        return selftest()
    args = list(argv)
    if args == ["init"]:
        try:
            init()
        except (GitRefused, OSError) as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return EXIT_REFUSED
        return 0
    url = None
    if "--url" in args:
        i = args.index("--url")
        if i + 1 >= len(args):
            print(USAGE, file=sys.stderr)
            return 2
        url = args[i + 1]
        del args[i:i + 2]
    if not args or args[0] != "check" or not 2 <= len(args) <= 3:
        print(USAGE, file=sys.stderr)
        return 2
    try:
        check(args[1], args[2] if len(args) == 3 else None, url=url)
    except GitRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
