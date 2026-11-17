#!/usr/bin/env python3
"""check_tasks.py — validate a folder of task docs before a batch is queued (zero tokens).

usage:
  check_tasks.py <folder> [--json]
  check_tasks.py --selftest

Each `*.md` file with YAML-style frontmatter is one task. Its id is the `id:` field, or the
file name without extension when `id` is absent. Files starting with `_` are templates and
are skipped.

Blocking problems (exit 1, the queue must not be built):
  * a `depends_on` id that matches no task in the folder (the id is named);
  * a task that depends on itself;
  * a dependency cycle (the path of the cycle is printed).

Warning (exit 0): two active tasks that cite the same file and do not depend on each other,
directly or transitively. Two units declaring the same file must not run in the same batch.
Files are the path-like tokens in the body, up to a `## Result` heading.

`depends_on` accepts `[A, B]`, `A, B` or a block list (`- A` per line).
"""
import json
import os
import re
import sys
import tempfile

ACTIVE = {"backlog", "todo", "pending", "in-progress", "in progress", "running"}
PATH_RE = re.compile(r"(?<![\w:/.\-])((?:[\w.\-~]+/)+[\w.\-]+\.[A-Za-z0-9]{1,6})(?![\w/])")
FRONT_RE = re.compile(r"---\r?\n(.*?)\r?\n---", re.S)
ID_RE = re.compile(r"[\w.\-]+")


def field(front, key):
    """Raw value of a frontmatter key, including indented continuation lines."""
    lines = front.splitlines()
    for i, line in enumerate(lines):
        match = re.match(rf"^{key}:\s*(.*)$", line)
        if not match:
            continue
        parts = [match.group(1).split("#")[0]]
        for extra in lines[i + 1:]:
            if re.match(r"^\s+\S", extra) or re.match(r"^-\s", extra):
                parts.append(extra.split("#")[0])
            else:
                break
        return "\n".join(parts).strip()
    return ""


def parse_ids(raw):
    cleaned = raw
    for char in "[],\"'":
        cleaned = cleaned.replace(char, " ")
    ids = []
    for token in cleaned.split():
        token = token.lstrip("-").strip()
        if token and token.lower() not in ("none", "null", "~") and ID_RE.fullmatch(token):
            ids.append(token)
    return ids


def read_tasks(folder):
    tasks = {}
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".md") or name.startswith("_"):
            continue
        with open(os.path.join(folder, name), encoding="utf-8") as handle:
            text = handle.read()
        match = FRONT_RE.match(text)
        if not match:
            continue
        front = match.group(1)
        task_id = field(front, "id").strip("\"'") or name[:-3]
        body = re.split(r"^## Result", text[match.end():], flags=re.M)[0]
        body = re.sub(r"https?://\S+", "", body)
        tasks[task_id] = {
            "status": field(front, "status").strip("\"'").lower(),
            "deps": parse_ids(field(front, "depends_on")),
            "files": {p.lower() for p in PATH_RE.findall(body)},
        }
    return tasks


def blockers(tasks):
    errors = []
    for task_id, data in tasks.items():
        for dep in data["deps"]:
            if dep == task_id:
                errors.append(f"{task_id}: depends on itself")
            elif dep not in tasks:
                errors.append(f"{task_id}: unknown dependency {dep}")
    state = {}

    def visit(node, path):
        state[node] = 1
        for dep in tasks[node]["deps"]:
            if dep not in tasks or dep == node:
                continue
            if state.get(dep) == 1:
                cycle = path[path.index(dep):] + [dep]
                errors.append("cycle: " + " -> ".join(cycle))
            elif dep not in state:
                visit(dep, path + [dep])
        state[node] = 2

    for node in tasks:
        if node not in state:
            visit(node, [node])
    return errors


def reaches(tasks, start, target):
    seen, stack = set(), [start]
    while stack:
        node = stack.pop()
        for dep in tasks.get(node, {}).get("deps", []):
            if dep == target:
                return True
            if dep in tasks and dep not in seen:
                seen.add(dep)
                stack.append(dep)
    return False


def warnings(tasks):
    """One warning per shared file, naming the active tasks that cite it."""
    active = sorted(k for k, d in tasks.items() if d["status"] in ACTIVE)
    shared = {}
    for i, first in enumerate(active):
        for second in active[i + 1:]:
            if reaches(tasks, first, second) or reaches(tasks, second, first):
                continue
            for path in tasks[first]["files"] & tasks[second]["files"]:
                shared.setdefault(path, set()).update((first, second))
    return [f"{path} cited by {', '.join(sorted(ids))}" for path, ids in sorted(shared.items())]


def check(folder):
    tasks = read_tasks(folder)
    return len(tasks), blockers(tasks), warnings(tasks)


def run(argv):
    args = [a for a in argv if a != "--json"]
    if len(args) != 1 or not os.path.isdir(args[0]):
        print(__doc__)
        return 2
    count, errors, warns = check(args[0])
    if "--json" in argv:
        print(json.dumps({"tasks": count, "blockers": errors, "warnings": warns}))
    else:
        print(f"{count} task(s); {len(errors)} blocker(s); {len(warns)} warning(s)")
        for line in [f"BLOCKER {e}" for e in errors] + [f"WARNING {w}" for w in warns]:
            print(line)
    return 1 if errors else 0


def selftest():
    def write(folder, name, deps=""):
        text = f"---\nid: {name}\nstatus: backlog\ndepends_on: {deps}\n---\nbody\n"
        with open(os.path.join(folder, name + ".md"), "w", encoding="utf-8") as handle:
            handle.write(text)

    ok = True
    with tempfile.TemporaryDirectory(prefix="kitchen-check-tasks-") as base:
        clean = os.path.join(base, "clean")
        os.mkdir(clean)
        write(clean, "A")
        write(clean, "B", deps="[A]")
        count, errors, warns = check(clean)
        ok &= count == 2 and not errors and not warns
        bad = os.path.join(base, "bad")
        os.mkdir(bad)
        write(bad, "A", deps="B")
        write(bad, "B", deps="A")
        write(bad, "C", deps="Z")
        errors = check(bad)[1]
        ok &= any("cycle: A -> B -> A" in e for e in errors) and "C: unknown dependency Z" in errors
    print("SELFTEST OK" if ok else "SELFTEST FAILED")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    return run(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
