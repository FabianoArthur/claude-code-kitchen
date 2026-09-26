# Security policy

## Supported versions

| version | supported |
|---|---|
| latest release (`0.1.x`) and `main` | yes |
| anything older | no — update to the latest release |

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use GitHub's private
vulnerability reporting instead: on this repository, go to **Security → Report a
vulnerability**.

This is a project maintained by one person in their spare time, so the timelines are honest
rather than fast:

- acknowledgement within **7 days**;
- a first assessment (accepted / not a vulnerability / need more information) within
  **14 days**;
- a fix or a documented mitigation for accepted reports as soon as practical, and a
  GitHub security advisory crediting you (unless you prefer not to be named).

Useful to include: what an attacker can do, the steps to reproduce, and the version
(commit) you tested.

## Scope

In scope:

- the scripts in `skills/*/scripts/` and `install.sh` (e.g. a path the installer could
  clobber, a gate that reports "clean" when it should not, unsafe file handling);
- instructions in the skills that would lead an agent to leak secrets, push to a protected
  branch, run destructive commands outside the documented flow, or follow instructions
  found in a task doc, issue or command output.

Out of scope, because they are inherent and documented: an agent started with
`--dangerously-skip-permissions` can run any command your user can run. The threat model
and its mitigations (sandbox, least-privilege tokens, branch protection, no MCP by default,
trusted input only) are in the README's
[security section](README.md#security---dangerously-skip-permissions).
