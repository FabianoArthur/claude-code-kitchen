# Demo project — try the kitchen end to end

A tiny Python library (`tempconv`) with an adapter and one task, so you can watch a full
order go from task doc to pull request without risking a real repo.

## 1. Make it a real repo of its own

The kitchen works on git worktrees and pull requests, so copy the demo out of this clone
and give it its own history and GitHub remote (a private throwaway repo is fine):

```bash
cp -R examples/demo-project ~/kitchen-demo
cd ~/kitchen-demo
git init -b main && git add . && git commit -m "chore: demo baseline"
gh repo create kitchen-demo --private --source . --push
printf '.kitchen/\n' >> .git/info/exclude
```

## 2. Check the machine

```bash
python3 <path-to-claude-code-kitchen>/skills/orchestrate/scripts/doctor.py .
```

Expect `READY to dispatch`. Fix any `✗` it reports (each one comes with the command to run).

## 3. Place an order

Open Claude Code in `~/kitchen-demo` (this session is the **waiter**) and ask:

```
/dotask kelvin-support
```

The waiter reads `docs/tasks/kelvin-support.md`, applies the eligibility filters, writes a
manifest in `docs/plans/`, creates the worktree `.worktrees/kelvin-support` on branch
`feat/kelvin-support`, and dispatches the **kitchen**: a detached tmux session
`kitchen-kelvin-support` running Claude Code inside that worktree.

## 4. Watch without spending tokens

```bash
tmux attach -t '=kitchen-kelvin-support'     # look (detach with Ctrl-b d)
cat docs/plans/*-kelvin-support-manifest.md  # the state row: 🔄 → ✅ / ⏳ / 🚫
```

The waiter runs `watch.py` in the background and tells you when the dish is served.

## 5. What you should see

- a test for absolute zero written **before** the implementation (TDD on logic);
- the diff gate refusing a `print(` if the kitchen adds one (`forbidden_in_diff`);
- a PR against `main` whose body lists every gate with its real output, a `## Not verified`
  section, and the reviewer's verdict.

## 6. Clean up after merging

```
/harvest
```

It removes the worktree and the branch **only** after confirming the PR was merged.
