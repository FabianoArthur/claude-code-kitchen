"""guard_rules — the rule table of the kitchen guard (see guard.py).

A rule is a name, a flag and a check. `irreversible=True` means the action cannot be taken
back once it runs (a merge, a forced push, a leaked credential): in the default mode
`deny-irreversible` only those rules block, the rest are logged as `would_deny`.

A check receives `(tool, tool_input, config)` and returns a short reason when the call
matches, or None. Checks must be pure and fast: the guard runs on every tool call.
"""
import re
from dataclasses import dataclass
from typing import Callable, Optional

SHELL_TOOLS = frozenset({"Bash"})
SEP = r"[;&|\n]"  # sub-command boundary
DEFAULT_BASES = ("main", "master", "release", "staging", "dev", "production")


@dataclass(frozen=True)
class Rule:
    name: str
    irreversible: bool
    check: Callable[[str, dict, dict], Optional[str]]
    tools: frozenset = SHELL_TOOLS


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


RULES = (
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
)
