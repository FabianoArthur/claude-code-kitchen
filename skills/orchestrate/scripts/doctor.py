#!/usr/bin/env python3
"""
doctor — deterministic batch pre-flight: checks the machine BEFORE dispatch (CORE §1, §2).

Why it exists: dispatch failures are **silent**. A kitchen session is a detached tmux
session: if `claude` is not on the PATH that tmux's `sh -c` sees, if `origin/<base>` does
not exist, if the worktrees directory cannot be created, the session starts, dies within
seconds and leaves the unit *looking* dispatched. That only shows up at the next sweep,
with N units already fired — far more expensive than 3 seconds of checking here.

The split is the rule:
  CRITICAL (exit 1) — dispatch does not happen, or is born broken. **Do not dispatch.**
  WARNING  (exit 0) — dispatches, but you pay later: PR that does not open, `.kitchen/`
                      dirtying the diff, a live session being run over, worktree without deps.

Nothing here is project-specific: `base`, `worktrees`, `gh`, `prepare_worktree` and
`max_parallel` come from the adapter (CORE §1), found by walking UP from the given
directory. A missing required field **is** the finding — the doctor never invents a value.

Usage:
    python3 doctor.py <repo-dir>             # pre-flight
    python3 doctor.py <repo-dir> --max 4     # N worktrees in the batch (default: max_parallel)
    python3 doctor.py --selftest             # built-in tests, no network

Output: one line per check (✓ / ⚠ / ✗); every ✗ and ⚠ carries the ACTION to fix it.
Exit: 0 = ready to dispatch · 1 = critical issue(s) · 2 = usage error
"""
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

CRITICAL = "CRITICAL — without this, dispatch breaks"
WARNING = "WARNING — dispatches, but you pay later"
ADAPTER = Path(".claude") / "orchestrator.md"
SESSION_PREFIX = "kitchen-"


# ─────────────────────────── report ───────────────────────────

class Report:
    """Collects lines so the selftest can inspect them instead of only printing."""

    def __init__(self):
        self.items = []          # ("section"|"✓"|"⚠"|"✗", text, action)
        self.critical = 0
        self.warnings = 0

    def section(self, title):
        self.items.append(("section", title, None))

    def ok(self, msg):
        self.items.append(("✓", msg, None))

    def warn(self, msg, action):
        self.items.append(("⚠", msg, action))
        self.warnings += 1

    def fail(self, msg, action):
        self.items.append(("✗", msg, action))
        self.critical += 1

    def text(self):
        return "\n".join(f"{m} {t}" + (f" ↳ {a}" if a else "") for m, t, a in self.items)

    def print(self):
        for mark, text, action in self.items:
            if mark == "section":
                print(f"\n{text}")
                continue
            print(f"  {mark} {text}")
            if action:
                print(f"      ↳ {action}")
        print()
        if self.critical == 0:
            print(f"READY to dispatch — 0 critical, {self.warnings} warning(s).")
        else:
            print(f"{self.critical} critical issue(s) — fix before dispatching "
                  f"({self.warnings} warning(s) too).")
        return 1 if self.critical else 0


# ─────────────────────────── helpers ───────────────────────────

def sh(cmd, cwd=None, timeout=20):
    """subprocess.run that never raises: missing binary = 127, timeout = 124."""
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return subprocess.CompletedProcess(cmd, 127, "", "binary not found")
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", f"no answer within {timeout}s")


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0


def existing_ancestor(p):
    """First existing path walking up from `p` — to know whether `p` can be created."""
    for candidate in [p, *p.parents]:
        if candidate.exists():
            return candidate
    return Path(p.anchor or "/")


# ─────────────────────────── adapter (§1) ───────────────────────────

def find_adapter(start):
    """Walk up from `start` until `.claude/orchestrator.md` (§1), like gate_diff does."""
    here = Path(start).resolve()
    for candidate in [here, *here.parents]:
        path = candidate / ADAPTER
        if path.exists():
            return path
    return None


def _strip(value):
    """Drop quotes and trailing comment (`list: "9011"   # name`)."""
    value = value.strip()
    if value[:1] in ("'", '"'):
        quote = value[0]
        end = value.find(quote, 1)
        return value[1:end] if end > 0 else value[1:]
    return re.split(r"\s+#", value, maxsplit=1)[0].strip()


def field(text, name):
    """Read a TOP-LEVEL scalar of the adapter — pure stdlib, no PyYAML.

    Accepts inline (`base: main`), quoted (`gh: "env -u GH_TOKEN gh"`) and folded
    (`gh: >` + indented lines). Anchored at `^` on purpose: `status_field:` inside
    `backlog:` is indented and must not be mistaken for a top-level field.
    """
    m = re.search(rf"(?m)^{re.escape(name)}:[ \t]*(.*)$", text)
    if not m:
        return None
    value = m.group(1).strip()
    if value in (">", "|", ">-", "|-", ">+", "|+"):
        pieces = []
        for line in text[m.end():].split("\n")[1:]:
            if line.strip() and not line.startswith((" ", "\t")):
                break
            if not line.strip() or line.strip().startswith("#"):
                continue
            pieces.append(line.strip())
        value = " ".join(pieces)
    return _strip(value) or None


def read_adapter(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    return {key: field(text, key)
            for key in ("base", "worktrees", "gh", "prepare_worktree", "max_parallel")}


# ─────────────────────────── critical checks ───────────────────────────

def check_binaries(r):
    claude = shutil.which("claude")
    if claude:
        r.ok(f"claude on PATH — {claude}  (THIS absolute path goes in the tmux command, §2)")
    else:
        r.fail("claude is not on PATH",
               "check with `command -v claude`. If it only exists as an alias/function of your "
               "shell, tmux's `sh -c` cannot see it — §2 requires the absolute path at dispatch.")
    tmux = shutil.which("tmux")
    if tmux:
        version = sh(["tmux", "-V"], timeout=5).stdout.strip() or "version ?"
        r.ok(f"tmux on PATH — {tmux} ({version})")
    else:
        r.fail("tmux is not on PATH",
               "install tmux (e.g. `brew install tmux` / `apt install tmux`) — without it there "
               "is no kitchen session (§2) and no dispatcher.")
    return bool(tmux)


def check_adapter(r, repo):
    path = find_adapter(repo)
    if path is None:
        r.fail(f"no `{ADAPTER}` walking up from {Path(repo).resolve()}",
               "§9 (bootstrap): create the repo's adapter with the human and record base, "
               "worktrees, scarce_resource, layers and tests. See examples/adapter.md.")
        return None, {}
    r.ok(f"adapter found — {path}")
    return path, read_adapter(path)


def check_git(r, repo, base):
    top = sh(["git", "-C", str(repo), "rev-parse", "--show-toplevel"])
    if top.returncode != 0:
        r.fail(f"git does not answer in {repo} (rc={top.returncode})",
               f"run the doctor inside the repo. Detail: {(top.stderr or '').strip()[:160]}")
        return None
    root = Path(top.stdout.strip())
    branch = sh(["git", "-C", str(repo), "branch", "--show-current"]).stdout.strip()
    r.ok(f"git answers — root {root} (checkout on `{branch or 'detached HEAD'}`)")

    if not base:
        r.fail("adapter declares no `base`",
               "§1: required field. Ask the human which base branch this repo uses (read it "
               "off merged PRs, not off the default branch) and record it in the adapter.")
        return root
    ref = f"refs/remotes/origin/{base}"
    if sh(["git", "-C", str(repo), "show-ref", "--verify", "--quiet", ref]).returncode == 0:
        sha = sh(["git", "-C", str(repo), "rev-parse", "--short", f"origin/{base}"]).stdout.strip()
        r.ok(f"base `origin/{base}` exists ({sha}) — branches and worktrees come from it")
    else:
        r.fail(f"`origin/{base}` does not exist in this repo",
               f"`git -C {repo} fetch origin {base}` — or fix `base:` in the adapter if this "
               "repo's base is another branch. Every worktree of the batch starts there; "
               "without the ref, `worktree add` fails for each unit.")
    return root


def check_worktrees(r, worktrees, root):
    if not worktrees:
        r.fail("adapter declares no `worktrees`",
               "§1: required field. Record the parent dir of the worktrees (preferably INSIDE "
               "the repo, otherwise the adapter is unreachable walking up from a worktree).")
        return None
    p = Path(os.path.expanduser(worktrees))
    if not p.is_absolute() and root:
        p = root / p
    p = Path(os.path.normpath(str(p)))

    if p.is_dir():
        if os.access(p, os.W_OK):
            r.ok(f"worktrees {p} exists and is writable")
        else:
            r.fail(f"worktrees {p} exists but is not writable",
                   f"`chmod u+w {p}` (or fix the owner) — `git worktree add` writes there.")
    elif p.exists():
        r.fail(f"{p} exists and is NOT a directory", "point `worktrees:` at a directory.")
    else:
        parent = existing_ancestor(p)
        if parent.is_dir() and os.access(parent, os.W_OK):
            r.ok(f"worktrees {p} does not exist yet, but can be created (mkdir -p under {parent})")
        else:
            r.fail(f"worktrees {p} does not exist and CANNOT be created (blocked at {parent})",
                   f"create it by hand (`mkdir -p {p}`) or fix `worktrees:` in the adapter.")
    return p


# ─────────────────────────── warning checks ───────────────────────────

def check_gh(r, gh_cmd):
    gh_cmd = gh_cmd or "gh"
    try:
        parts = shlex.split(gh_cmd)
    except ValueError:
        r.warn(f"adapter `gh` field does not parse: {gh_cmd!r}",
               "fix the quotes in the adapter — §1 says to use THIS command wherever a skill "
               "writes `gh`.")
        return
    res = sh(parts + ["auth", "status"], timeout=20)
    if res.returncode == 0:
        r.ok(f"`{gh_cmd} auth status` OK — execute can open the PR at the end of the unit")
    elif res.returncode == 127:
        r.warn(f"`{parts[0]}` not found (adapter command: `{gh_cmd}`)",
               "install the GitHub CLI — without it the unit does all the work and stops "
               "before the PR, which is where execute ends.")
    else:
        detail = ((res.stderr or "") + (res.stdout or "")).strip().replace("\n", " ")[:160]
        r.warn(f"`{gh_cmd} auth status` failed (rc={res.returncode}): {detail}",
               "`gh auth login`. If the error mentions a token/401, it is the §1 case: an "
               "invalid `GH_TOKEN` shadows the keyring — the fix is the adapter carrying "
               "`gh: \"env -u GH_TOKEN gh\"`, never hard-coding it in a skill.")


def check_exclude(r, repo):
    res = sh(["git", "-C", str(repo), "rev-parse", "--git-common-dir"])
    if res.returncode != 0:
        r.warn("could not find the git-common-dir to check the exclude file",
               "check by hand that `.kitchen/` is in "
               "`$(git rev-parse --git-common-dir)/info/exclude` (§2).")
        return
    common = Path(res.stdout.strip())
    if not common.is_absolute():
        common = Path(repo) / common
    exclude = Path(os.path.normpath(str(common / "info" / "exclude")))
    lines = []
    if exclude.exists():
        lines = [line.strip() for line in
                 exclude.read_text(encoding="utf-8", errors="replace").splitlines()]
    if any(line in (".kitchen/", ".kitchen", "/.kitchen/", "/.kitchen") for line in lines):
        r.ok(f"`.kitchen/` is already in {exclude} — prompt and launch.sh do not dirty the diff")
    else:
        r.warn(f"`.kitchen/` is not in {exclude}",
               f"`printf '.kitchen/\\n' >> {exclude}` — applies to every worktree of the repo "
               "at once (§2). Without it the unit's `.kitchen/prompt.md` enters its `git add .`.")


def check_sessions(r, has_tmux):
    if not has_tmux:
        r.warn(f"{SESSION_PREFIX}* sessions not checked (no tmux)", "fix the tmux critical above.")
        return
    res = sh(["tmux", "list-sessions", "-F", "#{session_name}"], timeout=10)
    names = [n.strip() for n in res.stdout.split() if n.strip().startswith(SESSION_PREFIX)]
    if not names:
        r.ok(f"no live {SESSION_PREFIX}* session — the batch starts on clean ground")
        return
    r.warn(f"{len(names)} {SESSION_PREFIX}* session(s) already alive: {', '.join(sorted(names))}",
           "DO NOT kill. §2: if the id's session already exists, STOP and reconcile — "
           "`tmux attach -t '=<name>'` to see where it is (a live session ≠ working; the fine "
           "state is the manifest row, §7), or `/orchestrate --resume`. Dispatching on top "
           "collides on the session name.")


def checkout_size(repo):
    """Bytes of the HEAD checkout (sum of blobs) — what each new worktree materialises."""
    res = sh(["git", "-C", str(repo), "ls-tree", "-r", "-l", "HEAD"], timeout=60)
    if res.returncode != 0:
        return None
    total = 0
    for line in res.stdout.splitlines():
        parts = line.split(None, 4)
        if len(parts) >= 4 and parts[3].isdigit():
            total += int(parts[3])
    return total


def check_disk(r, target, repo, n, n_source):
    where = existing_ancestor(Path(target)) if target else Path(repo)
    try:
        free = shutil.disk_usage(where).free
    except OSError as e:
        r.warn(f"could not measure free space at {where}: {e}", "check with `df -h` first.")
        return
    size = checkout_size(repo)
    if size is None:
        r.warn(f"{human(free)} free at {where}, but the cost was not estimated (HEAD has no tree?)",
               "check by hand that checkout × N fits before dispatching.")
        return
    count = n if n else 1
    need = size * count
    summary = (f"{human(free)} free at {where} · {count} worktree(s) × ~{human(size)} "
               f"= ~{human(need)} [{n_source}]")
    if not n:
        r.warn(summary, "batch size unknown: pass `--max N` or declare `max_parallel` in the "
                        "adapter (§2) so the whole batch is checked, not one worktree.")
    elif free > need * 2:
        r.ok(summary)
    else:
        r.warn(summary + " — less than 2× headroom",
               "free space (`/harvest` removes worktrees of merged PRs) or lower "
               "`max_parallel`. A worktree that fills the disk mid-checkout leaves the unit dirty.")


def check_prepare_worktree(r, root, command, adapter):
    has_node = root is not None and (root / "node_modules").exists()
    if command:
        r.ok(f"`prepare_worktree` declared — {command}")
    elif has_node:
        r.warn("the checkout has node_modules, but the adapter declares no `prepare_worktree`",
               f"a new worktree is born WITHOUT deps and the unit breaks on its first test. Ask "
               f"the human how this repo prepares a worktree (install? symlink?) and record it "
               f"in {adapter or '<adapter>'} — §1: project values live in the adapter.")
    else:
        r.ok("checkout without node_modules — nothing to prepare in the worktree")


def check_adapter_reach(r, adapter, worktrees):
    """A worktree outside the repo tree = adapter unreachable walking up from it (§1)."""
    if not adapter or not worktrees:
        return
    adapter_root = adapter.parent.parent.resolve()
    target = Path(worktrees).resolve()
    if adapter_root == target or adapter_root in target.parents:
        r.ok(f"worktrees is under {adapter_root} — the adapter is reachable from a worktree")
    else:
        r.warn(f"worktrees ({target}) is OUTSIDE the tree of {adapter_root}",
               "§1 finds the adapter walking UP from cwd: from a worktree outside the repo no "
               "skill (nor gate_diff) finds it — the gate would say 'clean' without looking. "
               "Point `worktrees:` inside the repo.")


# ─────────────────────────── pre-flight ───────────────────────────

def diagnose(repo, max_n=None, offline=False):
    r = Report()
    repo = str(Path(repo))

    r.section(CRITICAL)
    has_tmux = check_binaries(r)
    adapter, fields = check_adapter(r, repo)
    root = check_git(r, repo, fields.get("base"))
    if adapter:
        worktrees = check_worktrees(r, fields.get("worktrees"), root)
    else:
        worktrees = None
        r.warn("worktrees not checked (no adapter)", "fix the adapter above first.")

    n, source = max_n, "--max"
    cap = (fields.get("max_parallel") or "").strip()
    if n is None and cap.isdigit():
        n, source = int(cap), "adapter max_parallel"
    if n is None:
        source = "no cap declared"

    r.section(WARNING)
    if offline:
        r.ok("`gh` check skipped (--selftest runs without network)")
    else:
        check_gh(r, fields.get("gh"))
    if root:
        check_exclude(r, repo)
    check_sessions(r, has_tmux)
    if root:
        check_disk(r, worktrees, repo, n, source)
    check_prepare_worktree(r, root, fields.get("prepare_worktree"), adapter)
    check_adapter_reach(r, adapter, worktrees)
    return r


# ─────────────────────────── selftest ───────────────────────────

def _expect(condition, label):
    print(f"  {'✓' if condition else '✗'} {label}")
    return bool(condition)


def _stub(folder, name, body):
    p = Path(folder) / name
    p.write_text(body)
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return p


def _repo(base, name, adapter_yaml=None, with_file=True):
    """Offline fake git repo: origin/<base> becomes a local ref, no remote at all."""
    repo = Path(base) / name
    repo.mkdir(parents=True)
    sh(["git", "init", "-q", str(repo)])
    if with_file:
        (repo / "README.md").write_text("test content\n" * 50)
        sh(["git", "-C", str(repo), "add", "."])
    sh(["git", "-C", str(repo), "-c", "user.name=kitchen", "-c", "user.email=kitchen@example.com",
        "-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m", "base"])
    sh(["git", "-C", str(repo), "update-ref", "refs/remotes/origin/dev", "HEAD"])
    if adapter_yaml is not None:
        (repo / ".claude").mkdir()
        (repo / ADAPTER).write_text("# Test adapter\n\n```yaml\n" + adapter_yaml + "```\n")
    return repo


def selftest():
    ok = True
    base = tempfile.mkdtemp(prefix="kitchen-doctor-selftest-")
    stubs = Path(base) / "bin"
    stubs.mkdir()
    _stub(stubs, "claude", "#!/bin/sh\nexit 0\n")
    _stub(stubs, "tmux", "#!/bin/sh\ncase \"$1\" in\n  -V) echo 'tmux stub' ;;\n"
                         "  list-sessions) exit 1 ;;\nesac\nexit 0\n")
    path_before = os.environ.get("PATH", "")
    os.environ["PATH"] = f"{stubs}{os.pathsep}{path_before}"
    try:
        print("doctor selftest (no network, everything in a tempdir)\n")

        no_adapter = _repo(base, "no-adapter")
        r1 = diagnose(no_adapter, max_n=2, offline=True)
        ok &= _expect(r1.critical >= 1, "repo WITHOUT adapter → critical (do not dispatch)")
        ok &= _expect("orchestrator.md" in r1.text(), "names the missing file")
        ok &= _expect("§9" in r1.text(), "points at the bootstrap (§9) as the action")

        complete = _repo(base, "ok", adapter_yaml=(
            "project: test\n"
            "base: dev\n"
            f"worktrees: {base}/ok/.worktrees\n"
            "max_parallel: 2\n"
            'prepare_worktree: "npm ci"\n'
            'gh: "env -u GH_TOKEN gh"\n'))
        exclude = Path(complete) / ".git" / "info" / "exclude"
        exclude.parent.mkdir(exist_ok=True)
        exclude.write_text(".kitchen/\n")
        r2 = diagnose(complete, offline=True)
        ok &= _expect(r2.critical == 0, "adapter present + binaries on PATH → READY")
        ok &= _expect("origin/dev" in r2.text(), "confirmed the adapter's base on origin/")
        ok &= _expect("can be created" in r2.text(), "missing-but-creatable worktrees passes")
        ok &= _expect("2 worktree(s)" in r2.text(), "used the adapter's max_parallel as N")

        ghost_base = _repo(base, "wrong-base", adapter_yaml=(
            "base: doesnotexist\n"
            f"worktrees: {base}/wrong-base/.worktrees\n"))
        r3 = diagnose(ghost_base, offline=True)
        ok &= _expect(r3.critical >= 1 and "origin/doesnotexist" in r3.text(),
                      "base missing on origin/ → critical")
        ok &= _expect("fetch origin doesnotexist" in r3.text(), "the action is the concrete fetch")

        impossible = _repo(base, "wt-impossible", adapter_yaml=(
            "base: dev\nworktrees: /dev/null/never/works\n"))
        r4 = diagnose(impossible, offline=True)
        ok &= _expect(r4.critical >= 1 and "CANNOT be created" in r4.text(),
                      "uncreatable worktrees → critical")

        no_prepare = _repo(base, "no-prepare", adapter_yaml=(
            "base: dev\n" f"worktrees: {base}/no-prepare/.worktrees\n"))
        (Path(no_prepare) / "node_modules").mkdir()
        r5 = diagnose(no_prepare, offline=True)
        ok &= _expect(r5.critical == 0 and "prepare_worktree" in r5.text(),
                      "node_modules without prepare_worktree → warning, not critical")
        ok &= _expect(".kitchen/" in r5.text(), "exclude without .kitchen/ → warning with the fix")

        outside = _repo(base, "outside", adapter_yaml=(
            "base: dev\n" f"worktrees: {base}/elsewhere\n"))
        r6 = diagnose(outside, offline=True)
        ok &= _expect("OUTSIDE" in r6.text(), "worktrees outside the repo → reachability warning")

        sample = ('base: dev\ngh: >\n  env -u GH_TOKEN gh\n'
                  'worktrees: /tmp/x   # trailing comment\n'
                  'backlog:\n  base: NOT-THIS-ONE\n')
        ok &= _expect(field(sample, "gh") == "env -u GH_TOKEN gh", "field(): folded `>` read")
        ok &= _expect(field(sample, "worktrees") == "/tmp/x", "field(): comment dropped")
        ok &= _expect(field(sample, "base") == "dev", "field(): top level only (ignores nested)")
        ok &= _expect(field(sample, "missing") is None, "field(): absent returns None")
    finally:
        os.environ["PATH"] = path_before
        shutil.rmtree(base, ignore_errors=True)
    print("\nselftest:", "ALL PASSED" if ok else "FAILED")
    return 0 if ok else 1


# ─────────────────────────── cli ───────────────────────────

def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 2
    if "--selftest" in argv:
        return selftest()

    repo = argv[0]
    if repo.startswith("-"):
        print(__doc__)
        return 2
    if not Path(repo).is_dir():
        print(f"ERROR: {repo} is not a directory", file=sys.stderr)
        return 2
    max_n = None
    if "--max" in argv:
        try:
            max_n = int(argv[argv.index("--max") + 1])
        except (IndexError, ValueError):
            print("ERROR: --max expects an integer (how many worktrees the batch opens)",
                  file=sys.stderr)
            return 2
        if max_n < 1:
            print("ERROR: --max must be >= 1", file=sys.stderr)
            return 2

    print(f"doctor — batch pre-flight in {Path(repo).resolve()}")
    return diagnose(repo, max_n=max_n).print()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
