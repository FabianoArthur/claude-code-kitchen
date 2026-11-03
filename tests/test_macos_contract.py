"""Contract between `menubar/kitchen.30s.py --json` and the macOS app that decodes it.

The Swift tests decode the fixtures in macos/Tests/KitchenCoreTests/Fixtures/. This test
regenerates the same output from a fixed scenario and checks that the *shape* — the union of
keys and JSON types over the top level, every unit and every divergence — still matches the
committed fixture. Change the Python output and this fails until the fixture (and therefore
the Swift decoder, whose tests read it) is updated:

    KITCHEN_UPDATE_FIXTURES=1 python -m pytest tests/test_macos_contract.py

The scenario is built so every nullable field appears at least once with a value and once as
null; the values that change from run to run (`generated_at`, `manifest_dir`) are normalised.
"""
import json
import os
import subprocess

from conftest import ROOT, load

PLUGIN = ROOT / "menubar" / "kitchen.30s.py"
FIXTURES = ROOT / "macos" / "Tests" / "KitchenCoreTests" / "Fixtures"
SEP = "@@@"
NOW = 1767225600.0  # 2026-01-01 00:00 UTC

MANIFEST = """\
---
type: manifest
project: demo-app
---
| unit | size | route | state | branch/worktree | PR | session (resume) |
|------|------|-------|-------|-----------------|----|------------------|
| rate-limit | M | kitchen | 🔄 running | feat/rate-limit · .worktrees/rate-limit | | |
| export-csv | S | kitchen | ⏳ waiting on human: pick the CSV dialect | feat/export-csv | #43 | |
| search-api | L | kitchen | 🔄 running | feat/search-api · .worktrees/search-api | | |
| login-fix | S | kitchen | ✅ PR #42 | fix/login-fix | #42 | 7f3c |
| old-idea | S | kitchen | 🚫 aborted: superseded | feat/old-idea | | |
| new-ui | L | inline | ⏸ queued | (main checkout) | | |
"""


def scenario(mod, tmp_path):
    manifest = tmp_path / "plan-manifest.md"
    manifest.write_text(MANIFEST, encoding="utf-8")
    os.utime(manifest, (NOW - 600, NOW - 600))
    cfg = dict(mod.DEFAULTS, manifests=[str(tmp_path / "*manifest*.md")],
               pr_url="https://github.com/example/demo-app/pull/{n}")
    sessions = [("kitchen-rate-limit", int(NOW) - 754, str(tmp_path)),
                ("kitchen-export-csv", int(NOW) - 4320, str(tmp_path)),
                ("kitchen-stray", int(NOW) - 120, str(tmp_path))]
    out = "".join(f"{n}{SEP}{c}{SEP}{p}\n" for n, c, p in sessions)

    def run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, out, "")

    rows = mod.load_rows(cfg, NOW)
    model = mod.build_model(cfg, rows, mod.list_sessions(cfg, run=run), NOW)
    panes = {"kitchen-rate-limit": "Running tests: 214 passed, 3 to go",
             "kitchen-export-csv": "Which CSV dialect should the export use?"}
    data = mod.to_json(model, cfg, NOW, warning="config error: ignored invalid value for stale_days",
                       panes=panes)
    data["manifest_dir"] = "/fixtures/plans"
    return data


def error_scenario(mod):
    data = mod.empty_json(NOW, error="ZeroDivisionError: division by zero")
    return data


def _type(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    return type(value).__name__


def shape(data):
    """{section: {key: sorted types}} — the union over every element of each list."""
    def union(items):
        seen = {}
        for item in items:
            for k, v in item.items():
                seen.setdefault(k, set()).add(_type(v))
        return {k: sorted(v) for k, v in seen.items()}
    top = {k: [_type(v)] for k, v in data.items() if k not in ("units", "divergences", "counts")}
    return {"top": top, "counts": sorted(data["counts"]),
            "units": union(data["units"]), "divergences": union(data["divergences"])}


def _check(name, data):
    path = FIXTURES / name
    if os.environ.get("KITCHEN_UPDATE_FIXTURES"):
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    committed = json.loads(path.read_text(encoding="utf-8"))
    assert shape(data) == shape(committed), f"{name} drifted — regenerate it (see module docstring)"
    return committed


def test_kitchen_fixture_matches_the_script(tmp_path):
    mod = load(PLUGIN)
    data = scenario(mod, tmp_path)
    committed = _check("kitchen.json", data)
    assert committed == data, "values drifted too — regenerate kitchen.json"


def test_every_nullable_field_has_a_value_somewhere(tmp_path):
    mod = load(PLUGIN)
    s = shape(scenario(mod, tmp_path))
    for section in ("units", "divergences"):
        for key, types in s[section].items():
            assert types != ["null"], f"{section}.{key} is only ever null in the scenario"
    assert s["top"]["warning"] == ["str"]


def test_error_fixture_matches_the_script():
    mod = load(PLUGIN)
    data = error_scenario(mod)
    committed = _check("kitchen-error.json", data)
    assert committed == data
