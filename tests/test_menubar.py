"""Tests for the SwiftBar plugin (menubar/kitchen.30s.py).

Everything runs against fixtures: manifests written to tmp dirs and tmux output passed in as
strings through an injected runner. Only `test_real_tmux_format` talks to a tmux server, and
only through the private socket of the `private_tmux` fixture. Nothing reads `~/.claude`.
"""
import json
import os
import subprocess
import time

import pytest

from conftest import ROOT, load

PLUGIN = ROOT / "menubar" / "kitchen.30s.py"
SEP = "@@@"

EN_MANIFEST = """\
---
type: manifest
project: demo-app
base: main @ 1a2b3c4
created: 2026-01-15
dispatched: 2026-01-15 14:05
---
| unit | size | route | state | branch/worktree | PR | session (resume) |
|------|------|-------|-------|-----------------|----|------------------|
| rate-limit | M | kitchen | 🔄 running | feat/rate-limit · .worktrees/rate-limit | | |
| export-csv | S | kitchen | ⏳ waiting on human: pick the CSV dialect | feat/export-csv | | |
| login-fix | S | kitchen | ✅ PR #42 | fix/login-fix | #42 | 7f3c |
| old-idea | S | kitchen | 🚫 aborted: superseded | feat/old-idea | | |
| new-ui | L | inline | ⏸ queued | (main checkout) | | |
"""

PT_MANIFEST = """\
---
tipo: manifesto
projeto: app-exemplo
base: main @ 1a2b3c4
criado: 2026-01-15
despachado: 2026-01-15 14:05
---
| unidade | tam | rota | estado | branch/worktree | PR | sessão (resume) |
|---------|-----|------|--------|-----------------|----|-----------------|
| tarefa-a | M | subagente | 🔄 rodando | feat/a · .worktrees/a | | |
| tarefa-b | S | subagente | ⏳ aguarda humano: decidir o formato | feat/b | | |
| tarefa-c | S | subagente | ✅ PR #7 | feat/c | #7 | abc |
| tarefa-d | S | subagente | 🚫 abortada | feat/d | | |
| tarefa-e | L | inline | ⏸ na fila | (checkout principal) | | |
"""


@pytest.fixture(scope="module")
def mod():
    return load(PLUGIN)


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path):
    """Never read the real user config: point it at a file that does not exist."""
    monkeypatch.setenv("KITCHEN_MENUBAR_CONFIG", str(tmp_path / "no-config.json"))


@pytest.fixture
def cfg(mod, tmp_path):
    c = dict(mod.DEFAULTS)
    c["manifests"] = [str(tmp_path / "*manifest*.md")]
    return c


def write(path, text, age_days=0.0):
    path.write_text(text, encoding="utf-8")
    if age_days:
        old = time.time() - age_days * 86400
        os.utime(path, (old, old))
    return path


def tmux_ls(*sessions):
    """Simulated `tmux list-sessions -F` output: (name, created_epoch, path) per session."""
    return "".join(f"{n}{SEP}{c}{SEP}{p}\n" for n, c, p in sessions)


def fake_run(stdout="", returncode=0, stderr="", panes=None, boom=None):
    """A stand-in for subprocess.run. `panes` maps '=name:' → capture-pane text."""
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        if boom:
            raise boom
        if "capture-pane" in cmd:
            target = cmd[cmd.index("-t") + 1]
            return subprocess.CompletedProcess(cmd, 0, (panes or {}).get(target, ""), "")
        return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)

    run.calls = calls
    return run


NOW = time.time()


# ---------------------------------------------------------------- manifest parsing

def test_classify_by_emoji_in_both_dialects(mod):
    cases = {
        "🧹 colhido (mergeado)": "harvested", "⏸ queued": "queued", "⏸ na fila": "queued", "⏸️ queued": "queued",
        "🔄 running": "running", "🔄 rodando": "running",
        "⏳ waiting on human: x": "waiting", "⏳ aguarda humano": "waiting",
        "✅ PR #4": "done", "🚫 aborted": "aborted", "🚫 abortada": "aborted",
        "whatever": "unknown",
    }
    for cell, want in cases.items():
        assert mod.classify(cell) == want, cell


def test_parse_public_dialect(mod):
    m = mod.parse_manifest(EN_MANIFEST)
    assert m["project"] == "demo-app"
    assert m["dispatched"] is not None
    by = {r["unit"]: r for r in m["rows"]}
    assert list(by) == ["rate-limit", "export-csv", "login-fix", "old-idea", "new-ui"]
    assert by["rate-limit"]["status"] == "running"
    assert by["rate-limit"]["worktree"] == ".worktrees/rate-limit"
    assert by["export-csv"]["status"] == "waiting"
    assert by["export-csv"]["reason"] == "pick the CSV dialect"
    assert by["login-fix"]["pr"] == "42"
    assert by["new-ui"]["status"] == "queued"


def test_parse_rig_dialect_matches_public_one(mod):
    m = mod.parse_manifest(PT_MANIFEST)
    assert m["project"] == "app-exemplo"
    assert [r["status"] for r in m["rows"]] == ["running", "waiting", "done", "aborted", "queued"]
    assert m["rows"][1]["reason"] == "decidir o formato"
    assert m["rows"][2]["pr"] == "7"


def test_parse_ignores_text_without_table_and_separator_rows(mod):
    assert mod.parse_manifest("just prose\n")["rows"] == []
    assert mod.parse_manifest("")["rows"] == []


def test_parse_pr_url_in_cell(mod):
    text = ("| unit | state | PR |\n|---|---|---|\n"
            "| a | ✅ PR | https://github.com/o/r/pull/9 |\n")
    row = mod.parse_manifest(text)["rows"][0]
    assert row["pr"] == "9"
    assert row["pr_url"] == "https://github.com/o/r/pull/9"


def test_state_column_falls_back_to_first_emoji_cell(mod):
    text = "| thing | what |\n|---|---|\n| a | 🔄 going |\n"
    assert mod.parse_manifest(text)["rows"][0]["status"] == "running"


# ---------------------------------------------------------------- config

def test_load_config_defaults_when_missing(mod, tmp_path):
    cfg, warn = mod.load_config(tmp_path / "nope.json")
    assert cfg["prefixes"] == ["kitchen-"] and cfg["socket"] is None and warn is None


def test_load_config_merges_and_normalises(mod, tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"socket": "work", "prefixes": "orq-", "stale_days": 5}))
    cfg, warn = mod.load_config(p)
    assert cfg["socket"] == "work" and cfg["prefixes"] == ["orq-"] and cfg["stale_days"] == 5
    assert warn is None


def test_load_config_bad_json_falls_back_with_warning(mod, tmp_path):
    p = tmp_path / "c.json"
    p.write_text("{not json")
    cfg, warn = mod.load_config(p)
    assert cfg["prefixes"] == ["kitchen-"] and "config" in warn.lower()


def test_load_config_ignores_wrong_types(mod, tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"stale_days": "many", "socket": 7, "manifests": {"a": 1}}))
    cfg, warn = mod.load_config(p)
    assert cfg["stale_days"] == mod.DEFAULTS["stale_days"] and cfg["socket"] is None
    assert cfg["manifests"] == mod.DEFAULTS["manifests"] and warn


def test_config_path_honours_env(mod, monkeypatch, tmp_path):
    monkeypatch.setenv("KITCHEN_MENUBAR_CONFIG", str(tmp_path / "x.json"))
    assert mod.config_path() == tmp_path / "x.json"


# ---------------------------------------------------------------- manifests on disk

def test_load_manifests_reads_globs_and_newest_row_wins(mod, cfg, tmp_path):
    write(tmp_path / "a-manifest.md", EN_MANIFEST, age_days=1)
    newer = EN_MANIFEST.replace("🔄 running", "✅ PR #50")
    write(tmp_path / "b-manifest.md", newer)
    rows = mod.load_rows(cfg, NOW)
    assert [r["unit"] for r in rows].count("rate-limit") == 1
    assert next(r for r in rows if r["unit"] == "rate-limit")["status"] == "done"


def test_stale_all_done_manifest_is_ignored(mod, cfg, tmp_path):
    write(tmp_path / "old-manifest.md", EN_MANIFEST.replace("🔄 running", "✅ PR #1")
          .replace("⏳ waiting on human: pick the CSV dialect", "🚫 aborted")
          .replace("⏸ queued", "✅ PR #2"), age_days=10)
    assert mod.load_rows(cfg, NOW) == []


def test_old_manifest_with_active_row_is_kept(mod, cfg, tmp_path):
    write(tmp_path / "old-manifest.md", EN_MANIFEST, age_days=10)
    assert mod.load_rows(cfg, NOW) != []


def test_stale_manifest_of_harvested_and_unknown_rows_is_ignored(mod, cfg, tmp_path):
    text = ("| unidade | estado |\n|---|---|\n| a | 🧹 colhido (mergeado) |\n"
            "| b | 🍳 na cozinha |\n| c | ✅ PR #1 |\n")
    write(tmp_path / "old-manifest.md", text, age_days=10)
    assert mod.load_rows(cfg, NOW) == []


def test_max_age_days_drops_even_active_manifests(mod, cfg, tmp_path):
    write(tmp_path / "old-manifest.md", EN_MANIFEST, age_days=10)
    cfg["max_age_days"] = 5
    assert mod.load_rows(cfg, NOW) == []
    cfg["max_age_days"] = 30
    assert mod.load_rows(cfg, NOW) != []


def test_recent_all_done_manifest_is_kept(mod, cfg, tmp_path):
    write(tmp_path / "new-manifest.md", PT_MANIFEST.replace("🔄 rodando", "✅ PR #1")
          .replace("⏳ aguarda humano: decidir o formato", "✅ PR #2")
          .replace("🚫 abortada", "✅ PR #3").replace("⏸ na fila", "✅ PR #4"))
    assert len(mod.load_rows(cfg, NOW)) == 5


def test_unreadable_or_binary_manifest_is_skipped(mod, cfg, tmp_path):
    (tmp_path / "bad-manifest.md").write_bytes(b"\xff\xfe\x00 not utf8")
    write(tmp_path / "ok-manifest.md", PT_MANIFEST)
    assert len(mod.load_rows(cfg, NOW)) == 5


# ---------------------------------------------------------------- tmux

def test_list_sessions_parses_output(mod, cfg):
    run = fake_run(tmux_ls(("kitchen-a", 1000, "/w/a"), ("other", 1001, "/w/o")))
    t = mod.list_sessions(cfg, run=run)
    assert t["ok"] is True
    assert [s["name"] for s in t["sessions"]] == ["kitchen-a", "other"]
    assert t["sessions"][0]["created"] == 1000 and t["sessions"][0]["path"] == "/w/a"


def test_list_sessions_uses_socket_and_never_the_default_server_by_accident(mod, cfg):
    cfg["socket"] = "mysock"
    run = fake_run(tmux_ls())
    mod.list_sessions(cfg, run=run)
    cmd = run.calls[0]
    assert cmd[1:3] == ["-L", "mysock"] and "list-sessions" in cmd
    assert run.calls[0][0].endswith("tmux")


def test_tmux_missing_is_unavailable_not_a_traceback(mod, cfg):
    t = mod.list_sessions(cfg, run=fake_run(boom=FileNotFoundError()))
    assert t == {"ok": False, "sessions": [], "reason": "tmux not found"}


def test_tmux_timeout_is_unavailable(mod, cfg):
    t = mod.list_sessions(cfg, run=fake_run(boom=subprocess.TimeoutExpired("tmux", 3)))
    assert t["ok"] is False and "timed out" in t["reason"]


def test_no_server_running_means_no_sessions_not_an_error(mod, cfg):
    run = fake_run(returncode=1, stderr="no server running on /tmp/tmux-501/default")
    t = mod.list_sessions(cfg, run=run)
    assert t["ok"] is True and t["sessions"] == []


def test_other_tmux_failure_is_unavailable(mod, cfg):
    t = mod.list_sessions(cfg, run=fake_run(returncode=1, stderr="protocol version mismatch"))
    assert t["ok"] is False


def test_garbled_lines_are_skipped(mod, cfg):
    t = mod.list_sessions(cfg, run=fake_run("garbage\n" + tmux_ls(("kitchen-a", 5, "/p"))
                                            + f"x{SEP}notanumber{SEP}/p\n"))
    assert [s["name"] for s in t["sessions"]] == ["kitchen-a"]


def test_pane_summary_skips_chrome_and_blank_lines(mod, cfg):
    pane = ("Running gate: pytest -q\n"
            "  42 passed in 1.2s\n"
            "\n"
            "╭──────────────────────╮\n"
            "│ >                    │\n"
            "╰──────────────────────╯\n"
            "  ? for shortcuts\n"
            "\n")
    run = fake_run(panes={"=kitchen-a:": pane})
    assert mod.pane_summary(cfg, "kitchen-a", run=run) == "42 passed in 1.2s"


def test_pane_summary_skips_the_spinner_line(mod, cfg):
    pane = "⏺ Bash(pytest -q)\n✶ Wandering… (8m 13s · ↓ 51.4k tokens)\n"
    assert mod.pane_summary(cfg, "kitchen-a", run=fake_run(panes={"=kitchen-a:": pane})) \
        == "⏺ Bash(pytest -q)"


def test_pane_summary_truncates_and_strips_swiftbar_separators(mod, cfg):
    run = fake_run(panes={"=kitchen-a:": "a | b " + "x" * 200 + "\n"})
    out = mod.pane_summary(cfg, "kitchen-a", run=run)
    assert "|" not in out and len(out) <= 90


def test_pane_summary_survives_failures(mod, cfg):
    assert mod.pane_summary(cfg, "kitchen-a", run=fake_run(boom=FileNotFoundError())) == ""
    assert mod.pane_summary(cfg, "kitchen-a", run=fake_run(panes={})) == ""


def test_pane_target_is_exact_match_with_colon(mod, cfg):
    run = fake_run(panes={})
    mod.pane_summary(cfg, "kitchen-a", run=run)
    assert run.calls[0][run.calls[0].index("-t") + 1] == "=kitchen-a:"


# ---------------------------------------------------------------- the model

def rows_of(mod, text):
    """Rows as load_rows() hands them over: with project, dispatch time and manifest path."""
    parsed = mod.parse_manifest(text)
    for r in parsed["rows"]:
        r.update(project=parsed["project"], dispatched=parsed["dispatched"],
                 manifest="/m/2026-01-15-demo-manifest.md")
    return parsed["rows"]


def tmux_state(*sessions):
    return {"ok": True, "reason": "", "sessions": [
        {"name": n, "created": c, "path": p} for n, c, p in sessions]}


def never_done(_p):
    return False


def test_counts_by_state(mod, cfg):
    model = mod.build_model(cfg, rows_of(mod, EN_MANIFEST), tmux_state(), NOW, done_exists=never_done)
    assert model["counts"] == {"queued": 1, "running": 1, "waiting": 1, "done": 1, "aborted": 1,
                               "harvested": 0, "unknown": 0}


def test_divergence_session_without_row(mod, cfg):
    t = tmux_state(("kitchen-ghost", NOW - 60, "/w/ghost"))
    model = mod.build_model(cfg, rows_of(mod, EN_MANIFEST), t, NOW, done_exists=never_done)
    kinds = [(d["kind"], d["unit"]) for d in model["divergences"]]
    assert ("orphan", "kitchen-ghost") in kinds


def test_sessions_outside_the_configured_prefixes_are_ignored(mod, cfg):
    t = tmux_state(("work", NOW - 60, "/w"), ("garcom", NOW - 60, "/g"))
    model = mod.build_model(cfg, rows_of(mod, EN_MANIFEST), t, NOW, done_exists=never_done)
    assert not [d for d in model["divergences"] if d["kind"] == "orphan"]


def test_divergence_running_row_with_dead_session_and_no_done(mod, cfg):
    model = mod.build_model(cfg, rows_of(mod, EN_MANIFEST), tmux_state(), NOW, done_exists=never_done)
    crashed = [d for d in model["divergences"] if d["kind"] == "crash"]
    assert [d["unit"] for d in crashed] == ["rate-limit"]


def test_dead_session_with_done_marker_found_via_worktree_root_is_not_a_crash(mod, cfg, tmp_path):
    (tmp_path / ".worktrees" / "rate-limit" / ".kitchen").mkdir(parents=True)
    (tmp_path / ".worktrees" / "rate-limit" / ".kitchen" / "done").write_text("sid\n")
    cfg["worktree_roots"] = [str(tmp_path)]
    model = mod.build_model(cfg, rows_of(mod, EN_MANIFEST), tmux_state(), NOW)
    assert not [d for d in model["divergences"] if d["kind"] == "crash"]


def test_alive_session_with_done_marker_is_reapable(mod, cfg):
    t = tmux_state(("kitchen-login-fix", NOW - 3600, "/w/login-fix"))
    model = mod.build_model(cfg, rows_of(mod, EN_MANIFEST), t, NOW,
                            done_exists=lambda p: p == "/w/login-fix/.kitchen/done")
    reap = [d for d in model["divergences"] if d["kind"] == "reapable"]
    assert [d["unit"] for d in reap] == ["login-fix"]


def test_second_done_marker_name_is_checked(mod, cfg):
    cfg["done_markers"] = [".kitchen/done", ".orq/done"]
    t = tmux_state(("kitchen-login-fix", NOW - 3600, "/w/x"))
    model = mod.build_model(cfg, rows_of(mod, EN_MANIFEST), t, NOW,
                            done_exists=lambda p: p.endswith(".orq/done"))
    assert [d["kind"] for d in model["divergences"] if d["unit"] == "login-fix"] == ["reapable"]


def test_multiple_prefixes_map_sessions_to_rows(mod, cfg):
    cfg["prefixes"] = ["kitchen-", "orq-"]
    t = tmux_state(("orq-tarefa-a", NOW - 120, "/w/a"))
    model = mod.build_model(cfg, rows_of(mod, PT_MANIFEST), t, NOW, done_exists=never_done)
    entry = next(e for e in model["entries"] if e["unit"] == "tarefa-a")
    assert entry["session"] == "orq-tarefa-a" and entry["alive"] is True
    assert not [d for d in model["divergences"] if d["unit"] in ("tarefa-a", "orq-tarefa-a")]


def test_unit_ids_are_matched_exactly_not_by_prefix(mod, cfg):
    text = "| unit | state |\n|---|---|\n| task-2 | 🔄 running |\n"
    t = tmux_state(("kitchen-task-21", NOW - 5, "/w"))
    model = mod.build_model(cfg, rows_of(mod, text), t, NOW, done_exists=never_done)
    assert next(e for e in model["entries"] if e["unit"] == "task-2")["alive"] is False
    assert [d["kind"] for d in model["divergences"]] == ["crash", "orphan"]


def test_tmux_unavailable_reports_no_session_based_divergences(mod, cfg):
    t = {"ok": False, "reason": "tmux not found", "sessions": []}
    model = mod.build_model(cfg, rows_of(mod, EN_MANIFEST), t, NOW, done_exists=never_done)
    assert model["divergences"] == [] and model["tmux_reason"] == "tmux not found"


def test_age_comes_from_session_creation_else_dispatched(mod, cfg):
    t = tmux_state(("kitchen-rate-limit", NOW - 125, "/w"))
    model = mod.build_model(cfg, rows_of(mod, EN_MANIFEST), t, NOW, done_exists=never_done)
    assert next(e for e in model["entries"] if e["unit"] == "rate-limit")["age"] == 125


def test_fmt_age(mod):
    assert [mod.fmt_age(s) for s in (5, 59, 60, 3599, 3600, 3900, 86400, 90000, None)] == \
        ["<1m", "<1m", "1m", "59m", "1h00", "1h05", "1d00h", "1d01h", ""]


# ---------------------------------------------------------------- SwiftBar output

def render(mod, cfg, text=EN_MANIFEST, t=None, now=NOW, **kw):
    model = mod.build_model(cfg, rows_of(mod, text), t or tmux_state(), now, done_exists=never_done)
    return mod.render(model, cfg, now, script="/p/kitchen.30s.py", **kw)


HEX = r"#[0-9a-fA-F]{6}"
SF_NAME = r"[a-z0-9]+(\.[a-z0-9]+)*"


def param_map(line):
    """{'sfimage': 'flame', …} of one rendered line (values may be "quoted")."""
    import shlex
    _, _, rest = line.partition(" | ") if " | " in line else ("", "", line.lstrip("| "))
    return dict(tok.split("=", 1) for tok in shlex.split(rest) if "=" in tok)


def title_of(out):
    return out.splitlines()[0]


def test_title_is_symbol_plus_at_most_two_counts(mod, cfg):
    text = "| unit | state |\n|---|---|\n| a | 🔄 running |\n| b | 🔄 running |\n| c | ✅ PR #1 |\n"
    t = tmux_state(("kitchen-a", NOW - 60, "/w/a"), ("kitchen-b", NOW - 60, "/w/b"))
    first = title_of(render(mod, cfg, text, t=t))
    assert first.startswith("▸2 | ") and param_map(first)["sfimage"] == "flame.fill"
    # normal state: no colour, so the symbol follows the menu bar (light, dark, tinted wallpaper)
    assert "color" not in param_map(first) and "sfcolor" not in param_map(first)
    # done/queued units never reach the bar
    assert "✅" not in first and "⏸" not in first and "1" not in first


def test_title_has_no_emoji_and_no_extra_text_for_waiting_or_divergence(mod, cfg):
    first = title_of(render(mod, cfg))               # 1 running, 1 waiting, crash divergence
    text = first.split(" | ")[0]
    assert text == "▸1 !1"                          # two numbers, nothing about ⏳ or ⚠
    assert not any(ord(c) > 0x2000 and c not in "▸" for c in text), text
    for emoji in "🍳🔄⏳⏸✅⚠":
        assert emoji not in first


def test_empty_kitchen_title_is_just_a_discreet_symbol(mod, cfg):
    model = mod.build_model(cfg, [], tmux_state(), NOW)
    out = mod.render(model, cfg, NOW, script="/p/k.py")
    assert title_of(out) == "| sfimage=flame"
    assert "---" in out.splitlines()


def test_waiting_turns_the_symbol_orange_and_divergence_turns_it_red(mod, cfg):
    waiting = "| unit | state |\n|---|---|\n| a | ⏳ waiting on human: why |\n"
    p = param_map(title_of(render(mod, cfg, waiting)))
    assert p["sfimage"] == "flame.fill" and p["sfcolor"] == mod.TONE["waiting"]
    diverged = param_map(title_of(render(mod, cfg)))                  # crash divergence wins
    assert diverged["sfimage"] == "exclamationmark.triangle.fill"
    assert diverged["sfcolor"] == mod.TONE["attention"]
    assert mod.TONE["attention"] != mod.TONE["waiting"]


def test_title_without_attention_has_no_color(mod, cfg):
    text = "| unit | state |\n|---|---|\n| a | ✅ PR #1 |\n"
    assert "color" not in title_of(render(mod, cfg, text))


def test_queued_only_kitchen_stays_discreet(mod, cfg):
    text = "| unit | state |\n|---|---|\n| a | ⏸ queued |\n"
    assert title_of(render(mod, cfg, text)) == "| sfimage=flame"


def test_output_is_well_formed_swiftbar(mod, cfg):
    t = tmux_state(("kitchen-rate-limit", NOW - 700, "/w/rl"), ("kitchen-ghost", NOW - 5, "/w/g"))
    out = render(mod, cfg, t=t).splitlines()
    assert out.count("---") >= 1 and out[1] == "---"
    for line in out[2:]:
        assert "\t" not in line
        # a `|` starts SwiftBar parameters, so at most one separator per line may remain
        assert line.count(" | ") <= 1, line
        assert line == "---" or line.lstrip("-").strip(), "empty menu line"
    assert any(line.startswith("--") for line in out)          # submenu lines exist


def test_every_menu_item_has_a_valid_sf_symbol_and_colours(mod, cfg):
    import re
    cfg["pr_urls"] = {"demo-app": "https://github.com/o/r/pull/{n}"}
    t = tmux_state(("kitchen-rate-limit", NOW - 700, "/w/rl"), ("kitchen-ghost", NOW - 5, "/w/g"))
    model = mod.build_model(cfg, rows_of(mod, EN_MANIFEST), t, NOW, done_exists=never_done)
    out = mod.render(model, cfg, NOW, "/p/k.py", panes={"kitchen-rate-limit": "writing tests"}).splitlines()
    pair = re.compile(rf"^{HEX}(,{HEX})?$")
    for line in out:
        if line == "---" or line.startswith("   "):    # `   …` = small subtitle under an item
            continue
        p = param_map(line)
        assert re.fullmatch(SF_NAME, p.get("sfimage", "")), f"no SF Symbol on: {line}"
        for key in ("color", "sfcolor"):
            if key in p:
                assert pair.match(p[key]), line
                assert "," in p[key], f"{key} needs a light,dark pair: {line}"
        if "sfsize" in p:
            assert p["sfsize"].isdigit()
        assert not re.search("[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]", line.split(" | ")[0]), line


def test_colours_are_consistent_per_state(mod, cfg):
    out = render(mod, cfg)
    by_text = {ln.split(" | ")[0]: param_map(ln) for ln in out.splitlines() if " | " in ln}
    assert by_text["Waiting on you (1)"]["sfcolor"] == mod.TONE["waiting"]
    assert by_text["Running (1)"]["sfcolor"] == mod.TONE["running"]
    assert by_text["Done (1)"]["sfcolor"] == mod.TONE["done"]
    assert by_text["export-csv"]["sfcolor"] == mod.TONE["waiting"]       # row dot matches header
    assert len({mod.TONE[k] for k in ("running", "waiting", "attention", "done")}) == 4


def test_groups_are_headed_and_empty_groups_do_not_appear(mod, cfg):
    text = "| unit | state |\n|---|---|\n| a | 🔄 running |\n"
    out = render(mod, cfg, text, t=tmux_state(("kitchen-a", NOW - 60, "/w/a")))
    assert "Running (1)" in out
    for absent in ("Waiting on you", "Queued", "Done", "Aborted", "Needs attention", "Earlier"):
        assert absent not in out


def test_old_finished_units_fold_into_a_submenu(mod, cfg):
    cfg["pr_urls"] = {"demo-app": "https://github.com/o/r/pull/{n}"}
    rows = rows_of(mod, EN_MANIFEST)
    for r in rows:
        r["mtime"] = NOW - 3 * 86400 if r["unit"] == "login-fix" else NOW
    out = mod.render(mod.build_model(cfg, rows, tmux_state(), NOW, done_exists=never_done),
                     cfg, NOW, "/p/k.py").splitlines()
    assert "Done (1)" in " ".join(out)
    i = next(n for n, ln in enumerate(out) if ln.startswith("Earlier (1)"))
    assert out[i + 1].startswith("--login-fix") and "href=https://github.com/o/r/pull/42" in out[i + 1]
    assert not any(ln.startswith("login-fix") for ln in out)          # not a top-level row
    # recent ones stay inline
    rows[2]["mtime"] = NOW
    inline = mod.render(mod.build_model(cfg, rows, tmux_state(), NOW, done_exists=never_done),
                        cfg, NOW, "/p/k.py")
    assert "Earlier" not in inline and "\nlogin-fix | " in inline


def test_metadata_goes_on_a_second_small_gray_line(mod, cfg):
    t = tmux_state(("kitchen-rate-limit", NOW - 700, "/w/rl"))
    out = render(mod, cfg, t=t).splitlines()
    i = next(n for n, ln in enumerate(out) if ln.startswith("rate-limit | "))
    meta = next(ln for ln in out[i + 1:] if "demo-app" in ln and not ln.startswith("--"))
    assert "demo-app · 11m" in meta
    p = param_map(meta)
    assert p["size"] == "11" and p["color"] == mod.MUTED
    assert "demo-app" not in out[i]                                  # name line stays clean


def test_submenu_actions_carry_icons(mod, cfg):
    cfg["pr_urls"] = {"demo-app": "https://github.com/o/r/pull/{n}"}
    t = tmux_state(("kitchen-rate-limit", NOW - 700, "/w/rl"))
    rows = rows_of(mod, EN_MANIFEST)
    rows[0].update(pr="9")
    out = mod.render(mod.build_model(cfg, rows, t, NOW, done_exists=never_done), cfg, NOW, "/p/k.py")
    icons = {ln.split(" | ")[0].lstrip("-"): param_map(ln).get("sfimage") for ln in out.splitlines()
             if ln.startswith("--")}
    assert icons["Attach"] == "terminal"
    assert icons["Copy attach command"] == "doc.on.doc"
    assert icons["Open PR #9"] == "arrow.up.right.square"
    assert icons["branch: feat/rate-limit"] == "arrow.triangle.branch"


def test_footer_items_have_icons(mod, cfg):
    cfg["manifests"] = ["x"]
    rows = rows_of(mod, EN_MANIFEST)
    for r in rows:
        r["manifest"] = "/m/plans/x-manifest.md"
    out = mod.render(mod.build_model(cfg, rows, tmux_state(), NOW, done_exists=never_done), cfg, NOW, "/p/k.py")
    tail = {ln.split(" | ")[0]: param_map(ln) for ln in out.splitlines()[-3:]}
    assert tail["Refresh now"]["sfimage"] == "arrow.clockwise"
    assert tail["Open manifests folder"]["sfimage"] == "folder"
    assert tail["Open manifests folder"]["param1"] == "/m/plans"


def test_waiting_reason_keeps_its_own_line(mod, cfg):
    out = render(mod, cfg).splitlines()
    line = next(ln for ln in out if "pick the CSV dialect" in ln)
    assert param_map(line)["color"] == mod.TONE["waiting"] and not line.startswith("--")


def test_menu_item_has_unit_project_age_and_reason(mod, cfg):
    t = tmux_state(("kitchen-rate-limit", NOW - 700, "/w/rl"))
    out = render(mod, cfg, t=t)
    assert "rate-limit" in out and "demo-app" in out and "11m" in out
    assert "pick the CSV dialect" in out


def test_pr_link_comes_from_template_or_cell_url(mod, cfg):
    cfg["pr_urls"] = {"demo-app": "https://github.com/o/r/pull/{n}"}
    assert "href=https://github.com/o/r/pull/42" in render(mod, cfg)
    cfg["pr_urls"] = {}
    assert "href=https://github.com" not in render(mod, cfg)
    assert "PR #42" in render(mod, cfg)


def test_pr_template_must_be_http(mod, cfg):
    cfg["pr_url"] = "file:///etc/passwd?{n}"
    assert "href=file:///etc/passwd" not in render(mod, cfg)


def test_attach_and_copy_actions_are_calls_back_into_the_script(mod, cfg):
    t = tmux_state(("kitchen-rate-limit", NOW - 700, "/w/rl"))
    out = render(mod, cfg, t=t)
    assert "bash=/p/kitchen.30s.py" in out
    assert "param1=attach" in out and "param2=kitchen-rate-limit" in out
    assert "param1=copy" in out and "terminal=false" in out


def test_dead_session_has_no_attach_action(mod, cfg):
    out = render(mod, cfg)
    assert "param1=attach" not in out


def test_pane_summary_appears_as_submenu_line(mod, cfg):
    t = tmux_state(("kitchen-rate-limit", NOW - 700, "/w/rl"))
    out = render(mod, cfg, t=t, panes={"kitchen-rate-limit": "writing tests"})
    assert "--writing tests" in out.replace("-- ", "--")


def test_divergence_section_lists_each_kind(mod, cfg):
    t = tmux_state(("kitchen-ghost", NOW - 5, "/w/g"), ("kitchen-login-fix", NOW - 5, "/w/lf"))
    model = mod.build_model(cfg, rows_of(mod, EN_MANIFEST), t, NOW,
                            done_exists=lambda p: "/w/lf/" in p)
    out = mod.render(model, cfg, NOW, script="/p/k.py")
    assert "Needs attention (3)" in out
    assert "kitchen-ghost" in out and "login-fix" in out and "rate-limit" in out


def test_harvested_rows_are_hidden_but_counted(mod, cfg):
    text = "| unidade | estado |\n|---|---|\n| a | 🧹 colhido |\n| b | 🧹 colhido |\n| c | 🔄 rodando |\n"
    out = render(mod, cfg, text)
    assert "2 harvested (hidden)" in out
    assert "\na |" not in out and "\nb |" not in out and "🧹" not in out
    assert "2" not in title_of(out)


def test_placeholder_branch_is_not_shown(mod, cfg):
    text = "| unit | state | branch/worktree |\n|---|---|---|\n| a | 🔄 running | — |\n"
    assert "branch:" not in render(mod, cfg, text)


def test_footer(mod, cfg):
    out = render(mod, cfg, now=time.mktime((2026, 1, 2, 9, 7, 0, 0, 0, -1)))
    assert "Updated 09:07" in out
    assert "Refresh now | sfimage=arrow.clockwise refresh=true" in out


def test_tmux_missing_shows_note_and_still_lists_rows(mod, cfg):
    t = {"ok": False, "reason": "tmux not found", "sessions": []}
    model = mod.build_model(cfg, rows_of(mod, EN_MANIFEST), t, NOW, done_exists=never_done)
    out = mod.render(model, cfg, NOW, script="/p/k.py")
    assert "tmux not found" in out and "rate-limit" in out and "Traceback" not in out


def test_no_manifests_hint(mod, cfg):
    cfg["manifests"] = []
    out = mod.render(mod.build_model(cfg, [], tmux_state(), NOW), cfg, NOW, script="/p/k.py")
    assert "manifest" in out.lower()


def test_config_warning_is_shown(mod, cfg):
    model = mod.build_model(cfg, [], tmux_state(), NOW)
    out = mod.render(model, cfg, NOW, script="/p/k.py", warning="config error: boom")
    assert "config error: boom" in out


# ---------------------------------------------------------------- actions & main

def test_attach_command_quotes_the_exact_session(mod, cfg):
    cfg["socket"] = "work"
    assert mod.attach_command(cfg, "kitchen-a") == "tmux -L work attach -t '=kitchen-a'"
    cfg["socket"] = None
    assert mod.attach_command(cfg, "kitchen-a") == "tmux attach -t '=kitchen-a'"


def test_unsafe_names_are_refused(mod, cfg):
    assert mod.safe_name("kitchen-a.b_c") is True
    for bad in ("a b", "a'b", "a;b", "$(x)", "", "a\nb", "=a"):
        assert mod.safe_name(bad) is False, bad


def test_attach_action_builds_osascript_for_terminal(mod, cfg):
    cfg["terminal"] = "Terminal"
    run = fake_run()
    mod.do_attach(cfg, "kitchen-a", run=run)
    cmd = run.calls[0]
    assert cmd[0] == "/usr/bin/osascript"
    script = " ".join(cmd)
    assert 'tell application "Terminal"' in script and "attach -t '=kitchen-a'" in script


def test_attach_action_rejects_unsafe_session(mod, cfg):
    run = fake_run()
    assert mod.do_attach(cfg, "a'; rm -rf ~", run=run) is False
    assert run.calls == []


def test_copy_action_pipes_command_to_pbcopy(mod, cfg):
    seen = {}

    def run(cmd, **kw):
        seen["cmd"], seen["input"] = cmd, kw.get("input")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    assert mod.do_copy(cfg, "kitchen-a", run=run) is True
    assert seen["cmd"] == ["/usr/bin/pbcopy"] and seen["input"] == "tmux attach -t '=kitchen-a'"


def test_main_prints_menu_and_never_raises_without_tmux(mod, monkeypatch, tmp_path, capsys):
    write(tmp_path / "m-manifest.md", EN_MANIFEST)
    cfgfile = tmp_path / "c.json"
    cfgfile.write_text(json.dumps({"manifests": [str(tmp_path / "*manifest*.md")],
                                   "tmux": str(tmp_path / "no-such-tmux")}))
    monkeypatch.setenv("KITCHEN_MENUBAR_CONFIG", str(cfgfile))
    assert mod.main([]) == 0
    out = capsys.readouterr().out
    assert out.startswith("▸1 !1 | ") and "tmux not found" in out


def test_main_survives_unexpected_internal_error(mod, monkeypatch, capsys):
    monkeypatch.setattr(mod, "list_sessions", lambda *a, **k: 1 / 0)
    assert mod.main([]) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[0].startswith("| sfimage=exclamationmark.triangle.fill") and lines[1] == "---"
    assert "kitchen plugin error: ZeroDivisionError" in out and "Traceback" not in out


def test_main_dispatches_actions(mod, monkeypatch):
    calls = []
    monkeypatch.setattr(mod, "do_attach", lambda cfg, name, **k: calls.append(("attach", name)) or True)
    monkeypatch.setattr(mod, "do_copy", lambda cfg, name, **k: calls.append(("copy", name)) or True)
    assert mod.main(["attach", "kitchen-a"]) == 0
    assert mod.main(["copy", "kitchen-b"]) == 0
    assert mod.main(["bogus", "x"]) == 1
    assert calls == [("attach", "kitchen-a"), ("copy", "kitchen-b")]


def test_script_has_swiftbar_metadata_and_valid_name():
    text = PLUGIN.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env python3")
    for tag in ("title", "version", "desc", "dependencies", "hideAbout"):
        assert f"<swiftbar.{tag}>" in text, tag
    # SwiftBar derives the refresh interval from the file name: name.<interval>.<ext>
    assert PLUGIN.name == "kitchen.30s.py"
    assert os.access(PLUGIN, os.X_OK)


def test_script_is_stdlib_only():
    import ast
    tree = ast.parse(PLUGIN.read_text(encoding="utf-8"))
    import sys
    allowed = set(sys.stdlib_module_names) | {"__future__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(a.name.split(".")[0] in allowed for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.module.split(".")[0] in allowed


def test_real_tmux_format(mod, private_tmux, tmp_path):
    """The one test that talks to tmux — only through the private socket."""
    subprocess.run(["tmux", "-L", private_tmux, "new-session", "-d", "-s", "kitchen-real",
                    "-c", str(tmp_path), "sleep 30"], check=True)
    cfg = dict(mod.DEFAULTS, socket=private_tmux)
    t = mod.list_sessions(cfg)
    assert t["ok"] and [s["name"] for s in t["sessions"]] == ["kitchen-real"]
    assert os.path.realpath(t["sessions"][0]["path"]) == os.path.realpath(str(tmp_path))
    assert t["sessions"][0]["created"] > 0
    # a socket nobody started → clean empty result
    t2 = mod.list_sessions(dict(mod.DEFAULTS, socket=private_tmux + "-nobody"))
    assert t2["ok"] and t2["sessions"] == []


# ---------------------------------------------------------------- --json (the macOS app's input)

def _json_model(mod, cfg, tmp_path, sessions=(), panes=None, **cfg_over):
    write(tmp_path / "m-manifest.md", EN_MANIFEST)
    cfg = dict(cfg, **cfg_over)
    rows = mod.load_rows(cfg, NOW)
    tmux = mod.list_sessions(cfg, run=fake_run(tmux_ls(*sessions)))
    return cfg, mod.build_model(cfg, rows, tmux, NOW)


def test_to_json_shape_and_counts(mod, cfg, tmp_path):
    cfg, model = _json_model(mod, cfg, tmp_path,
                             sessions=[("kitchen-rate-limit", int(NOW) - 754, str(tmp_path))])
    out = mod.to_json(model, cfg, NOW, warning=None, panes={"kitchen-rate-limit": "Running tests"})
    assert out["schema"] == 1 and out["error"] is None and out["warning"] is None
    assert out["generated_at"] == NOW
    assert out["counts"]["running"] == 1 and out["counts"]["waiting"] == 1
    assert out["globs"] == 1 and out["tmux_reason"] == ""
    assert out["manifest_dir"] == str(tmp_path)
    by = {u["unit"]: u for u in out["units"]}
    assert list(by) == ["rate-limit", "export-csv", "login-fix", "old-idea", "new-ui"]
    rl = by["rate-limit"]
    assert rl["session"] == "kitchen-rate-limit" and rl["alive"] is True and rl["done"] is False
    assert rl["age_seconds"] == pytest.approx(754, abs=1) and rl["age_text"] == "12m"
    assert rl["pane"] == "Running tests"
    assert rl["attach_command"] == "tmux attach -t '=kitchen-rate-limit'"
    assert rl["project"] == "demo-app" and rl["branch"] == "feat/rate-limit"
    ex = by["export-csv"]
    assert ex["status"] == "waiting" and ex["reason"] == "pick the CSV dialect"
    assert ex["session"] is None and ex["attach_command"] is None and ex["pane"] == ""
    assert by["new-ui"]["age_seconds"] is None and by["new-ui"]["age_text"] is None


def test_to_json_resolves_pr_links_and_only_http(mod, cfg, tmp_path):
    cfg, model = _json_model(mod, cfg, tmp_path, pr_url="https://example.com/r/pull/{n}")
    by = {u["unit"]: u for u in mod.to_json(model, cfg, NOW)["units"]}
    assert by["login-fix"]["pr"] == "42"
    assert by["login-fix"]["pr_link"] == "https://example.com/r/pull/42"
    assert by["rate-limit"]["pr_link"] is None
    cfg2, model2 = _json_model(mod, cfg, tmp_path, pr_url="javascript:alert({n})")
    by2 = {u["unit"]: u for u in mod.to_json(model2, cfg2, NOW)["units"]}
    assert by2["login-fix"]["pr_link"] is None


def test_to_json_recent_flag_folds_old_done_units(mod, cfg, tmp_path):
    write(tmp_path / "m-manifest.md", EN_MANIFEST, age_days=2)
    rows = mod.load_rows(cfg, NOW)
    model = mod.build_model(cfg, rows, {"ok": True, "sessions": [], "reason": ""}, NOW)
    by = {u["unit"]: u for u in mod.to_json(model, cfg, NOW)["units"]}
    assert by["login-fix"]["recent"] is False
    assert by["rate-limit"]["recent"] is True   # only finished units fold


def test_to_json_divergences_carry_attach_command_only_when_safe(mod, cfg, tmp_path):
    cfg, model = _json_model(mod, cfg, tmp_path, sessions=[
        ("kitchen-stray", int(NOW) - 60, str(tmp_path)),
        ("kitchen-bad;rm", int(NOW) - 60, str(tmp_path))])
    divs = {d["unit"]: d for d in mod.to_json(model, cfg, NOW)["divergences"]}
    assert divs["kitchen-stray"]["kind"] == "orphan"
    assert divs["kitchen-stray"]["attach_command"] == "tmux attach -t '=kitchen-stray'"
    assert divs["kitchen-bad;rm"]["attach_command"] is None
    crash = [d for d in divs.values() if d["kind"] == "crash"]
    assert crash and crash[0]["session"] is None and crash[0]["attach_command"] is None


def test_to_json_unsafe_socket_disables_attach_commands(mod, cfg, tmp_path):
    cfg, model = _json_model(mod, cfg, tmp_path, socket="bad sock",
                             sessions=[("kitchen-rate-limit", int(NOW), str(tmp_path))])
    by = {u["unit"]: u for u in mod.to_json(model, cfg, NOW)["units"]}
    assert by["rate-limit"]["alive"] is True and by["rate-limit"]["attach_command"] is None


def test_to_json_socket_appears_in_attach_command(mod, cfg, tmp_path):
    cfg, model = _json_model(mod, cfg, tmp_path, socket="work",
                             sessions=[("kitchen-rate-limit", int(NOW), str(tmp_path))])
    by = {u["unit"]: u for u in mod.to_json(model, cfg, NOW)["units"]}
    assert by["rate-limit"]["attach_command"] == "tmux -L work attach -t '=kitchen-rate-limit'"


def test_to_json_carries_warning_and_tmux_reason(mod, cfg, tmp_path):
    write(tmp_path / "m-manifest.md", EN_MANIFEST)
    rows = mod.load_rows(cfg, NOW)
    model = mod.build_model(cfg, rows, {"ok": False, "sessions": [], "reason": "tmux not found"}, NOW)
    out = mod.to_json(model, cfg, NOW, warning="config error: x")
    assert out["warning"] == "config error: x" and out["tmux_reason"] == "tmux not found"
    assert out["divergences"] == []


def test_to_json_has_no_credential_or_usage_fields(mod, cfg, tmp_path):
    cfg, model = _json_model(mod, cfg, tmp_path)
    out = mod.to_json(model, cfg, NOW)
    keys = set(out) | {k for u in out["units"] for k in u} | {k for d in out["divergences"] for k in d}
    for word in ("token", "credential", "oauth", "usage", "keychain", "bearer"):
        assert not [k for k in keys if word in k.lower()], word


def test_main_json_prints_one_object(mod, monkeypatch, tmp_path, capsys):
    write(tmp_path / "m-manifest.md", EN_MANIFEST)
    cfgfile = tmp_path / "c.json"
    cfgfile.write_text(json.dumps({"manifests": [str(tmp_path / "*manifest*.md")],
                                   "tmux": str(tmp_path / "no-such-tmux")}))
    monkeypatch.setenv("KITCHEN_MENUBAR_CONFIG", str(cfgfile))
    assert mod.main(["--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["schema"] == 1 and out["tmux_reason"] == "tmux not found"
    assert len(out["units"]) == 5


def test_main_json_collects_panes_of_live_units(mod, monkeypatch, tmp_path, capsys):
    write(tmp_path / "m-manifest.md", EN_MANIFEST)
    cfgfile = tmp_path / "c.json"
    cfgfile.write_text(json.dumps({"manifests": [str(tmp_path / "*manifest*.md")]}))
    monkeypatch.setenv("KITCHEN_MENUBAR_CONFIG", str(cfgfile))
    monkeypatch.setattr(mod, "list_sessions", lambda cfg: {
        "ok": True, "reason": "",
        "sessions": [{"name": "kitchen-rate-limit", "created": int(time.time()), "path": str(tmp_path)}]})
    monkeypatch.setattr(mod, "pane_summary", lambda cfg, s: "editing foo.py")
    assert mod.main(["--json"]) == 0
    by = {u["unit"]: u for u in json.loads(capsys.readouterr().out)["units"]}
    assert by["rate-limit"]["pane"] == "editing foo.py"


def test_main_json_survives_unexpected_error(mod, monkeypatch, capsys):
    monkeypatch.setattr(mod, "list_sessions", lambda *a, **k: 1 / 0)
    assert mod.main(["--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["schema"] == 1 and out["error"].startswith("ZeroDivisionError")
    assert out["units"] == [] and out["divergences"] == []


def test_main_without_json_still_prints_the_swiftbar_menu(mod, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(mod, "list_sessions", lambda *a, **k: {"ok": True, "sessions": [], "reason": ""})
    assert mod.main([]) == 0
    out = capsys.readouterr().out
    assert not out.lstrip().startswith("{") and "---" in out
