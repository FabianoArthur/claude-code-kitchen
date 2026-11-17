"""guard_rules — the rule table of the kitchen guard (see guard.py).

A rule is a name, a flag and a check. `irreversible=True` means the action cannot be taken
back once it runs (a merge, a forced push, a leaked credential): in the default mode
`deny-irreversible` only those rules block, the rest are logged as `would_deny`.

A check receives `(tool, tool_input, config)` and returns a short reason when the call
matches, or None. Checks must be pure and fast: the guard runs on every tool call. The guard
adds two reserved keys to `config`: `_env` (the environment) and `_cwd` (the hook event's cwd).
The worktree is `KITCHEN_WORKTREE`, else the event's cwd, else the process cwd.

User config keys read here: `bases` (protected branches), `protected_scripts` (script names
the unit must never run) and `heavy_patterns` (regexes of commands that must go through
heavy.py). Both lists are empty by default.
"""
import os
import re
from dataclasses import dataclass
from typing import Callable, Optional


class _AnyTool:
    """`Rule.tools` for a rule that looks at every tool call."""

    def __contains__(self, tool) -> bool:
        return True


SHELL_TOOLS = frozenset({"Bash"})
READ_TOOLS = frozenset({"Read", "Grep", "Glob"})
WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})
PATH_KEYS = ("file_path", "path", "notebook_path")
MAX_INPUT_BYTES = 1024 * 1024
SEP = r"[;&|\n]"  # sub-command boundary
DEFAULT_BASES = ("main", "master", "release", "staging", "dev", "production")


@dataclass(frozen=True)
class Rule:
    name: str
    irreversible: bool
    check: Callable[[str, dict, dict], Optional[str]]
    tools: object = SHELL_TOOLS


def _command(tool_input: dict) -> str:
    command = tool_input.get("command")
    if not isinstance(command, str):
        raise ValueError("tool_input.command is not a string")
    return command


def _regex_check(pattern: str, reason: str):
    compiled = re.compile(pattern)

    def check(tool: str, tool_input: dict, config: dict) -> Optional[str]:
        return reason if compiled.search(_command(tool_input)) else None

    return check


def _push_check(tool: str, tool_input: dict, config: dict) -> Optional[str]:
    bases = tuple(config.get("bases") or DEFAULT_BASES)
    command = _command(tool_input)
    for found in re.finditer(r"\bgit\b[^;&|\n]*?\bpush\b([^;&|\n]*)", command):
        args = found.group(1).replace('"', " ").replace("'", " ").split()
        for arg in args:
            if arg in ("--mirror", "--delete") or arg.startswith("--force"):
                return "forced or destructive push"
            if re.fullmatch(r"-[A-Za-z]*[fd][A-Za-z]*", arg):  # -f, -d and bundles such as -uf
                return "forced or destructive push"
            if arg.startswith("+"):  # a +src:dst refspec forces the push
                return "forced push (refspec starting with +)"
            if arg.startswith(":"):
                return "removal of a remote branch"
            target = arg.split(":")[-1].removeprefix("refs/heads/")
            if target in bases:
                return f"direct push to the base branch '{target}'"
    return None


# --- shell parsing helpers -------------------------------------------------------------------
# A small quote-aware splitter: enough to tell what a command runs and with which arguments. It is
# a guard against mistakes, not a shell: whatever it cannot resolve is treated as unsafe.

WRAPPERS = frozenset({"command", "builtin", "exec", "time", "nohup", "nice", "env", "sudo", "stdbuf"})
SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
ENV_OPTS_WITH_VALUE = frozenset({"-u", "-C", "-S", "--unset", "--chdir"})
SECRET_NAME = re.compile(r"TOKEN|KEY|SECRET|PASSWORD")
ASSIGNMENT = re.compile(r"[A-Za-z_]\w*=.*")


def _split(command: str) -> list:
    """Splits a command line into simple commands, each a list of words (quotes removed)."""
    commands, words, word = [], [], None

    def end_word():
        nonlocal word
        if word is not None:
            words.append(word)
            word = None

    def end_command():
        nonlocal words
        end_word()
        if words:
            commands.append(words)
        words = []

    i, n = 0, len(command)
    while i < n:
        ch = command[i]
        if ch == "\\" and i + 1 < n:
            word = (word or "") + command[i + 1]
            i += 2
        elif ch == "'":
            end = command.find("'", i + 1)
            end = n if end < 0 else end
            word = (word or "") + command[i + 1 : end]
            i = end + 1
        elif ch == '"':
            i += 1
            word = word or ""
            while i < n and command[i] != '"':
                if command[i] == "\\" and i + 1 < n and command[i + 1] in '"\\$`':
                    i += 1
                word += command[i]
                i += 1
            i += 1
        elif ch in " \t\r":
            end_word()
            i += 1
        elif command.startswith("$(", i):
            end_command()
            i += 2
        elif ch in ";&|()`\n":
            end_command()
            i += 1
        else:
            word = (word or "") + ch
            i += 1
    end_command()
    return commands


def _unwrap(words: list) -> list:
    """Drops leading `VAR=x`, `sudo`, `env ...`, `command` and friends; returns the real command."""
    words = list(words)
    while words:
        head = os.path.basename(words[0])
        if ASSIGNMENT.fullmatch(words[0]):
            words.pop(0)
        elif head in WRAPPERS:
            words.pop(0)
            while words and (words[0].startswith("-") or ASSIGNMENT.fullmatch(words[0])):
                option = words.pop(0)
                if option in ENV_OPTS_WITH_VALUE and words:
                    words.pop(0)
            if not words:
                return [head]  # `env` alone: it prints the environment
        else:
            break
    return words


def _commands(command: str, depth: int = 0):
    """Yields every simple command of a line (words unwrapped), also inside `sh -c '...'`."""
    for words in _split(command):
        words = _unwrap(words)
        if not words:
            continue
        yield words
        if depth < 3 and os.path.basename(words[0]) in SHELLS and "-c" in words[1:-1]:
            yield from _commands(words[words.index("-c") + 1], depth + 1)


# --- paths -----------------------------------------------------------------------------------


def _env(config: dict) -> dict:
    return config.get("_env") or {}


def _home(config: dict) -> str:
    return _env(config).get("HOME") or os.path.expanduser("~")


def _real(path: str) -> str:
    """Absolute path with every symlink followed (a dangling one resolves to its target)."""
    return os.path.realpath(path).replace("\\", "/")


def _worktree(config: dict) -> str:
    return _real(_env(config).get("KITCHEN_WORKTREE") or config.get("_cwd") or os.getcwd())


def _inside(path: str, root: str, strict: bool = False) -> bool:
    path = os.path.normcase(path).replace("\\", "/")
    root = os.path.normcase(root).replace("\\", "/").rstrip("/")
    return path.startswith(root + "/") or (not strict and path == root)


def _expand(word: str, config: dict):
    """Expands `~`, `$HOME`, `$TMPDIR`, `$PWD`; returns None when another `$` is left."""
    home = _home(config)
    if word == "~" or word.startswith("~/"):
        word = home + word[1:]
    known = {"HOME": home, "TMPDIR": _env(config).get("TMPDIR") or "/tmp", "PWD": _worktree(config)}
    word = re.sub(r"\$\{?(HOME|TMPDIR|PWD)\}?", lambda m: known[m.group(1)], word)
    return None if "$" in word else word


def _resolve(word: str, base, config: dict):
    """(realpath, had_wildcard) of a path word relative to `base`; None when it is unknown."""
    word = _expand(word, config)
    if word is None:
        return None
    wildcard = re.search(r"[*?\[]", word)
    if wildcard:  # keep the directory part before the first wildcard
        word = word[: wildcard.start()].rpartition("/")[0] or ("/" if word.startswith("/") else ".")
    if not word.startswith("/"):
        if base is None:
            return None
        word = base + "/" + word
    return _real(word), bool(wildcard)


def _temp_roots(config: dict) -> list:
    """Where a unit may write outside the worktree, compared by realpath as well as by name."""
    roots = set()
    for name in ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders"):
        roots.update((name, _real(name)))
    tmpdir = _env(config).get("TMPDIR")
    if tmpdir and os.path.isabs(tmpdir):
        real = _real(tmpdir)
        # a TMPDIR that resolves to `/` or to a parent of the home would open the whole disk
        if real.count("/") >= 2 and not _inside(_real(_home(config)), real):
            roots.update((tmpdir.replace("\\", "/"), real))
    return [r for r in roots if r not in ("", "/")]


def _outside(path: str, config: dict, strict_temp: bool = False) -> bool:
    if _inside(path, _worktree(config)):
        return False
    return not any(_inside(path, root, strict=strict_temp) for root in _temp_roots(config))


def _bases(command: str, config: dict):
    """Yields (words, base) for each simple command; base follows `cd` (None when unknown)."""
    base = _worktree(config)
    for words in _commands(command):
        yield words, base
        if os.path.basename(words[0]) in ("cd", "pushd"):
            target = next((w for w in words[1:] if not w.startswith("-")), None)
            resolved = _resolve(target, base, config) if target else None
            base = resolved[0] if resolved else None


def _path_values(tool_input: dict) -> list:
    values = []
    for key in PATH_KEYS:
        value = tool_input.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError(f"tool_input.{key} is not a string")
        values.append(value)
    return values


def _real_tool_paths(tool_input: dict, config: dict):
    """Yields the realpath of every path a file tool names; None for one it cannot resolve."""
    base = _worktree(config)
    for value in _path_values(tool_input):
        expanded = _expand(value, config)
        yield None if expanded is None else _real(expanded if expanded.startswith("/") else base + "/" + expanded)


# --- secrets ---------------------------------------------------------------------------------

_SECRET_TEXT = re.compile(
    r"(?<![\w.-])\.env(?:\.[\w.-]+)?(?![\w-])"  # .env, .env.local (examples are filtered below)
    r"|[\w.*?-]*token[\w.*?-]*\.env(?![\w-])"
    r"|(?<![\w-])\.ssh(?![\w-])"
    r"|\.config/gh(?![\w-])"
    r"|\.claude/channels(?![\w-])"
    r"|\.claude/\.credentials\.json"
    r"|(?<![\w.-])\.(?:git-credentials|netrc)(?![\w-])"
    r"|\.kitchen/mcp\.json"
    r"|\bsecurity\s+(?:find-generic-password|find-internet-password|dump-keychain)\b"
    r"|\bgh\s+auth\s+token\b"
    r"|\bgit\s+credential\s+fill\b",
    re.IGNORECASE,
)
_EXAMPLE_ENV = re.compile(r"\.(example|sample|template)$", re.IGNORECASE)


def _secret_text(text: str):
    for found in _SECRET_TEXT.finditer(text):
        if not _EXAMPLE_ENV.search(found.group(0)):
            return found.group(0)
    return None


def _secret_path(path: str):
    """What kind of secret a real path is, or None."""
    parts = [p.lower() for p in path.split("/") if p]
    name = parts[-1] if parts else ""
    pairs = [(parts[i], parts[i + 1]) for i in range(len(parts) - 1)]
    if ".ssh" in parts or (".config", "gh") in pairs or (".claude", "channels") in pairs:
        return "credential folder"
    if (".kitchen", "mcp.json") in pairs or (".claude", ".credentials.json") in pairs:
        return "credential file"
    if name in (".git-credentials", ".netrc"):
        return "credential file"
    is_env = name == ".env" or name.startswith(".env.") or re.fullmatch(r"[^/]*token[^/]*\.env", name)
    if is_env and not _EXAMPLE_ENV.search(name):
        return "env file"
    return None


def _secret_check(tool: str, tool_input: dict, config: dict) -> Optional[str]:
    if tool in SHELL_TOOLS:
        found = _secret_text(_command(tool_input))
        return f"reads a secret ({found.strip()})" if found else None
    for path in _real_tool_paths(tool_input, config):
        if path is None:
            return "path with an unresolved variable"
        what = _secret_path(path)
        if what:
            return f"{what} (after following symlinks)"
    selector = {"Glob": "pattern", "Grep": "glob"}.get(tool)
    value = tool_input.get(selector) if selector else None
    if isinstance(value, str) and _secret_text(value):
        return "selects a secret file"
    return None


# --- environment dump ------------------------------------------------------------------------

_ENV_TEXT = re.compile(
    r"/proc/[^\s/]*/environ\b"
    r"|\$\{?[!#]?\w*(?:TOKEN|KEY|SECRET|PASSWORD)\w*"
    r"|(?:\$\(|`)\s*(?:/usr/bin/)?(?:env|printenv)\s*(?:\)|`)"
)
PS_OPTS_WITH_VALUE = frozenset({"-o", "-p", "-u", "-U", "-t", "-g", "-G", "-C", "-O", "-s", "-q", "--pid", "--user"})


def _ps_shows_environment(args: list) -> bool:
    skip = False
    for arg in args:
        if skip:
            skip = False
        elif arg in PS_OPTS_WITH_VALUE:
            skip = True
        elif re.fullmatch(r"-[A-Za-z]*E[A-Za-z]*", arg) or re.fullmatch(r"[A-Za-z]*e[A-Za-z]*", arg):
            return True  # `-E` (macOS) or the BSD/procps `e` modifier (`ps e`, `ps auxe`)
    return False


def _dumps_environment(words: list) -> Optional[str]:
    name, args = os.path.basename(words[0]), words[1:]
    flags = [a for a in args if a.startswith("-")]
    rest = [a for a in args if not a.startswith("-")]
    if name == "env" and not args:
        return "env prints the environment"
    if name == "printenv" and (not rest or any(SECRET_NAME.search(a) for a in rest)):
        return "printenv prints the environment"
    if name == "export" and (not args or "-p" in flags):
        return "export lists the environment"
    if name == "set" and not args:
        return "set lists variables and the environment"
    if name in ("declare", "typeset"):
        bundle = "".join(f.lstrip("-") for f in flags)
        if not args or "p" in bundle or ("x" in bundle and not any("=" in a for a in rest)):
            return f"{name} lists variables"
    if name == "ps" and _ps_shows_environment(args):
        return "ps shows process environments"
    if name == "tmux" and {"show-environment", "showenv", "show-env"} & set(args):
        return "tmux shows its environment"
    return None


def _env_check(tool: str, tool_input: dict, config: dict) -> Optional[str]:
    command = _command(tool_input)
    found = _ENV_TEXT.search(command)
    if found:
        return f"reads the environment or a secret variable ({found.group(0).strip()[:40]})"
    for words in _commands(command):
        reason = _dumps_environment(words)
        if reason:
            return reason
    return None


# --- destructive commands --------------------------------------------------------------------


def _git_args(words: list):
    """(subcommand, args) of a `git` command, skipping global options such as `-C dir`."""
    if os.path.basename(words[0]) != "git":
        return None, []
    rest, i = words[1:], 0
    while i < len(rest) and rest[i].startswith("-"):
        i += 2 if rest[i] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace") else 1
    return (rest[i], rest[i + 1 :]) if i < len(rest) else (None, [])


def _short_flags(args: list) -> str:
    return "".join(a[1:] for a in args if re.fullmatch(r"-[A-Za-z]+", a))


def _git_check(predicate):
    def check(tool: str, tool_input: dict, config: dict) -> Optional[str]:
        for words in _commands(_command(tool_input)):
            sub, args = _git_args(words)
            reason = predicate(sub, args) if sub else None
            if reason:
                return reason
        return None

    return check


def _no_verify(sub, args):
    if sub in ("commit", "push", "merge", "am", "cherry-pick", "rebase") and "--no-verify" in args:
        return "skipping the git hooks"
    if sub == "commit" and "n" in _short_flags(args):
        return "skipping the git hooks (commit -n)"
    return None


def _reset_hard(sub, args):
    return "git reset --hard discards work" if sub == "reset" and "--hard" in args else None


def _clean_force(sub, args):
    if sub == "clean" and ("--force" in args or "f" in _short_flags(args)):
        return "git clean with force deletes untracked files"
    return None


def _rm_check(tool: str, tool_input: dict, config: dict) -> Optional[str]:
    for words, base in _bases(_command(tool_input), config):
        if os.path.basename(words[0]) != "rm":
            continue
        args = words[1:]
        if "--" in args:
            options, targets = args[: args.index("--")], args[args.index("--") + 1 :]
        else:
            options, targets = [a for a in args if a.startswith("-")], [a for a in args if not a.startswith("-")]
        if "--recursive" not in options and not re.search(r"[rR]", _short_flags(options)):
            continue
        for target in targets:
            resolved = _resolve(target, base, config)
            if resolved is None:
                return f"rm -r of a path that cannot be resolved ({target[:60]})"
            path, wildcard = resolved
            if _outside(path, config, strict_temp=not wildcard):
                return f"recursive rm outside the worktree ({path})"
    return None


_SQL = re.compile(r"\bdrop\s+(?:table|database|schema|view|index|column)\b|\btruncate\s+table\b", re.IGNORECASE)
_SQL_UPPER = re.compile(r"\bTRUNCATE\s+[A-Za-z_\"`]")  # a lower-case `truncate x` is the unix command


def _sql_check(tool: str, tool_input: dict, config: dict) -> Optional[str]:
    command = _command(tool_input)
    found = _SQL.search(command) or _SQL_UPPER.search(command)
    return f"destructive SQL ({found.group(0)[:30]})" if found else None


# --- writes outside the worktree -------------------------------------------------------------


def _redirect_targets(words: list):
    for i, word in enumerate(words):
        found = re.fullmatch(r"(?:\d*|&)>>?\|?(.*)", word)
        if found:
            target = found.group(1) or (words[i + 1] if i + 1 < len(words) else "")
            if target and not target.startswith("&") and not target.startswith("/dev/"):
                yield target
    if os.path.basename(words[0]) == "tee":
        yield from (w for w in words[1:] if not w.startswith("-"))


def _write_check(tool: str, tool_input: dict, config: dict) -> Optional[str]:
    if tool in SHELL_TOOLS:
        for words, base in _bases(_command(tool_input), config):
            for target in _redirect_targets(words):
                resolved = _resolve(target, base, config)
                if resolved is None:
                    if _expand(target, config) is None:
                        continue  # an unknown variable is not provably outside
                    return f"write to a relative path after an unknown cd ({target[:60]})"
                if _outside(resolved[0], config):
                    return f"write outside the worktree ({resolved[0]})"
        return None
    for path in _real_tool_paths(tool_input, config):
        if path is None:
            return "path with an unresolved variable"
        if _outside(path, config):
            return f"write outside the worktree ({path})"
    return None


# --- size, watch mode and the user's own lists -----------------------------------------------


def _text_size(value) -> int:
    if isinstance(value, str):
        return len(value.encode("utf-8", "surrogatepass"))
    if isinstance(value, dict):
        return sum(_text_size(k) + _text_size(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return sum(_text_size(v) for v in value)
    return 0


def _size_check(tool: str, tool_input: dict, config: dict) -> Optional[str]:
    size = _text_size(tool_input)
    if size > MAX_INPUT_BYTES:
        return f"input of {size} bytes is over the {MAX_INPUT_BYTES} byte limit; split it into smaller parts"
    return None


WATCH_SCRIPTS = re.compile(r"dev|watch|serve|start:dev|dev:.+|watch:.+|test:watch")
WATCH_FLAGS = frozenset({"--watch", "--watchall"})
# tools where `-w` means watch (for `grep -w` it does not)
WATCH_SHORT_TOOLS = frozenset({"tsc", "jest", "esbuild", "rollup", "sass", "vite", "webpack", "nodemon"})


def _watch(words: list) -> Optional[str]:
    name, args = os.path.basename(words[0]), words[1:]
    lowered = [a.lower() for a in args]
    if name in ("watch", "nodemon", "fswatch", "watchman"):
        return f"{name} never ends"
    if name == "tail" and ("--follow" in args or "f" in _short_flags(args).lower()):
        return "tail -f never ends"
    if name in ("npm", "pnpm", "yarn", "bun") and "run" in args[:1]:
        script = next((a for a in args[1:] if not a.startswith("-")), "")
        if WATCH_SCRIPTS.fullmatch(script):
            return f"`{name} run {script}` is a watch or dev server"
    if name == "vitest" and not ({"run", "--run", "-r"} & set(lowered)):
        return "vitest without `run` stays in watch mode"
    if name in WATCH_SHORT_TOOLS and "-w" in args:
        return f"{name} -w never ends"
    if WATCH_FLAGS & set(lowered) or any(a.startswith("--watch=") for a in lowered):
        return "watch mode never ends"
    return None


def _watch_check(tool: str, tool_input: dict, config: dict) -> Optional[str]:
    for words in _commands(_command(tool_input)):
        reason = _watch(words)
        if reason:
            return f"{reason}; use the single-run form"
    return None


def _config_list(config: dict, key: str) -> list:
    value = config.get(key) or []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"config.{key} is not a list of strings")
    return [v for v in value if v]


def _protected_check(tool: str, tool_input: dict, config: dict) -> Optional[str]:
    command = _command(tool_input)
    for name in _config_list(config, "protected_scripts"):
        if name in command:
            return f"{name} is a protected script"
    return None


def _heavy_check(tool: str, tool_input: dict, config: dict) -> Optional[str]:
    command = _command(tool_input)
    for pattern in _config_list(config, "heavy_patterns"):
        if re.search(pattern, command):
            return f"heavy command ({pattern}); run it through heavy.py"
    return None


RULES = (
    Rule("input-size", False, _size_check, _AnyTool()),
    Rule("merge", True, _regex_check(r"\bgh\s+pr\s+merge\b", "merging is the human's call")),
    Rule("sudo", True, _regex_check(r"(^|" + SEP + r"|\s|\()sudo\s", "sudo is not allowed for the agent")),
    Rule(
        "download-exec",
        True,
        _regex_check(r"\b(curl|wget)\b[^;&\n]*\|\s*(sudo\s+)?(ba|z|da)?sh\b", "download and run a script"),
    ),
    Rule(
        "credential",
        True,
        _regex_check(
            r"(~|\$HOME|/Users/[^/\s]+|/home/[^/\s]+)/(\.ssh|\.aws|\.config/gh|\.netrc)\b"
            r"|\.claude\.json\b|\bsecurity\s+(find-\w*-?password|dump-keychain)\b",
            "credential file or keychain",
        ),
    ),
    Rule("push", True, _push_check),
    Rule("secret-read", True, _secret_check, SHELL_TOOLS | READ_TOOLS | WRITE_TOOLS),
    Rule("env-dump", True, _env_check),
    Rule("no-verify", False, _git_check(_no_verify)),
    Rule("reset-hard", True, _git_check(_reset_hard)),
    Rule("clean-force", True, _git_check(_clean_force)),
    Rule("rm-outside", True, _rm_check),
    Rule("sql-destructive", True, _sql_check),
    Rule("write-outside", True, _write_check, SHELL_TOOLS | WRITE_TOOLS),
    Rule("watch", False, _watch_check),
    Rule("protected-script", True, _protected_check),
    Rule("heavy", False, _heavy_check),
)
