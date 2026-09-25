# Security policy

## Supported versions

Only the latest release on `main` receives fixes.

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use GitHub's private
vulnerability reporting instead: on this repository, go to **Security → Report a
vulnerability**. You should get an acknowledgement within 7 days.

Useful to include: what an attacker can do, the steps to reproduce, and the version
(commit) you tested.

## Scope

In scope:

- the scripts in `skills/*/scripts/` and `install.sh` (e.g. a path the installer could
  clobber, a gate that reports "clean" when it should not, unsafe file handling);
- instructions in the skills that would lead an agent to leak secrets, push to a protected
  branch, or run destructive commands outside the documented flow.

Out of scope, because they are inherent and documented: an agent started with
`--dangerously-skip-permissions` can run any command your user can run. The README's
security section describes the mitigations (sandbox, least-privilege tokens, branch
protection, no MCP by default, trusted input only).
