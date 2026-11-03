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
        "⏸ queued": "queued", "⏸ na fila": "queued", "⏸️ queued": "queued",
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
                               "unknown": 0}


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


def test_title_shows_only_nonzero_states(mod, cfg):
    first = render(mod, cfg).splitlines()[0]
    assert first.startswith("🍳 ") and "🔄1" in first and "⏳1" in first and "✅1" in first
    assert "⏸1" in first and "🚫" not in first


def test_empty_kitchen_title_is_just_the_pan(mod, cfg):
    model = mod.build_model(cfg, [], tmux_state(), NOW)
    out = mod.render(model, cfg, NOW, script="/p/k.py")
    assert out.splitlines()[0] == "🍳"
    assert "---" in out.splitlines()


def test_title_flags_waiting_and_divergences(mod, cfg):
    first = render(mod, cfg).splitlines()[0]
    assert "color=" in first       # ⏳ present → attention
    assert "⚠️" in first           # the crash divergence (🔄 row, no session)


def test_title_without_attention_has_no_color(mod, cfg):
    text = "| unit | state |\n|---|---|\n| a | ✅ PR #1 |\n"
    assert "color=" not in render(mod, cfg, text).splitlines()[0]


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
    assert "Divergences" in out
    assert "kitchen-ghost" in out and "login-fix" in out and "rate-limit" in out


def test_footer(mod, cfg):
    out = render(mod, cfg, now=time.mktime((2026, 1, 2, 9, 7, 0, 0, 0, -1)))
    assert "Updated 09:07" in out
    assert "Refresh now | refresh=true" in out
    assert "Open manifests folder" in out


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
    assert out.startswith("🍳") and "tmux not found" in out


def test_main_survives_unexpected_internal_error(mod, monkeypatch, capsys):
    monkeypatch.setattr(mod, "list_sessions", lambda *a, **k: 1 / 0)
    assert mod.main([]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0].startswith("🍳") and "Traceback" not in out


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
