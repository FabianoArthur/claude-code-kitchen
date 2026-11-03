# Menu-bar widget (macOS)

A [SwiftBar](https://github.com/swiftbar/SwiftBar) plugin that shows what is cooking without
opening a terminal — and, more usefully, what is **wrong** with the kitchen without anyone
having to look. It spends zero tokens: it only reads the batch [manifests](manifest.md) and
asks tmux for the session list, every 30 seconds.

The bar shows a flame SF Symbol and, next to it, only what asks for your attention: how many
units are running (`▸`) and how many are waiting on you (`!`). Nothing else is added to the bar —
the *symbol and its colour* carry the alarm:

| state | bar | symbol |
|---|---|---|
| empty, or only queued / done units | *(symbol only)* | `flame`, system colour |
| units running | `▸2` | `flame.fill`, system colour |
| a unit waits on you | `▸2 !1` | `flame.fill`, **orange** |
| a divergence (see below) | `▸2 !1` | `exclamationmark.triangle.fill`, **red** |

Colours are `light,dark` pairs, so they read on both menu appearances; the calm states use the
system colour and follow the menu bar tint.

## Before and after

Before (0.1.0) — every line began with an emoji and carried all of its metadata:

```text
🍳 🔄1 ⏳1 ✅1 ⏸1 ⚠️1
─────────────────────────────────────────
⚠️ Divergences (1)
⚠️ kitchen-ghost: live session with no manifest row
⏳ Waiting on human (1)
⏳ export-csv · demo-app · PR #42 — pick the CSV dialect
🔄 Running (1)
🔄 rate-limit · demo-app · 11m
```

After — SF Symbols coloured by state, the name on its own line, a small gray line under it:

```text
▸1 !1                                       ← flame (red triangle while there is a divergence)
─────────────────────────────────────────
⚠ Needs attention (1)                       red
● kitchen-ghost: live session with no manifest row
    ⌄ Attach · Copy attach command
✋ Waiting on you (1)                       orange
● export-csv
    demo-app                                small, gray
    pick the CSV dialect                    orange: why it is waiting
▶ Running (1)                               blue
● rate-limit                                ⌄ screen line · branch · Open PR · Attach · Copy
    demo-app · 11m                          small, gray
⌛ Queued (1)                               gray
✓ Done (1)                                  green
  ⏱ Earlier (3)                             ⌄ finished more than a day ago, with PR links
─────────────────────────────────────────
⏲ Updated 09:07                             small, gray
↻ Refresh now
📁 Open manifests folder
```

(The text preview approximates the symbols with ordinary glyphs; the real menu draws SF
Symbols.) Empty groups do not appear. Units that finished more than a day ago (by the age of
their manifest file) fold into an **Earlier** submenu.

## What the menu shows

- **One item per unit**, grouped by state (waiting on you first): the unit id on its own
  line, then a small gray line with the project, the time since the session was created (or
  since dispatch) and the PR number, then — for a unit waiting on a human — the reason.
- **Submenu** of each unit: the last useful line on the agent's screen (`tmux capture-pane`),
  the branch, **Open PR**, **Attach** (opens a terminal attached to the session) and
  **Copy attach command**.
- **Divergences** — the failure modes of a kitchen that nobody sees until they look:

  | divergence | meaning |
  |---|---|
  | live session, no manifest row | a session you forgot about, or a row somebody deleted |
  | `🔄` row, dead session, no `done` marker | the agent crashed (or the machine rebooted) mid-task |
  | live session whose unit wrote `done` | finished and hibernated — kill the session to free RAM |

- Footer: when it last ran, **Refresh now**, **Open manifests folder**, each with an icon.

A live session does not mean the agent is working; the manifest row is the fine signal, and
this widget puts both side by side. See [manifest.md](manifest.md#reconciling-after-a-crash-or-reboot)
for the reconciliation rules it mirrors.

## Install

Requirements: macOS, `python3`, `tmux`, and **SwiftBar 2.0 or newer** (checked on 2.1.1).
The menu is drawn with the `sfimage`, `sfcolor` and `sfsize` parameters; a SwiftBar that
predates them ignores those parameters, so every line still carries its text and the menu stays
readable — only the icons and colours go away, and the bar then shows just the counts. The
`terminal` and `clock.arrow.circlepath` symbols need macOS 12 or newer; on macOS 11 those two
items simply have no icon.

1. Install SwiftBar: `brew install --cask swiftbar`, open it once and choose a plugin
   folder (any folder works; SwiftBar suggests one under `~/Library/Application Support`).
2. Copy the plugin into that folder and make sure it is executable:

   ```bash
   cp menubar/kitchen.30s.py "<your SwiftBar plugin folder>/"
   chmod +x "<your SwiftBar plugin folder>/kitchen.30s.py"
   ```

   Copy it rather than symlinking it if your clone lives in a worktree that
   `/harvest` may delete. The `30s` in the file name is the refresh interval (rename it to
   `kitchen.1m.py`, `kitchen.10s.py`…).
3. Write a config (below) — at minimum the `manifests` globs.
4. Click the menu-bar item → **Refresh now**.

To check what SwiftBar will show, run the plugin by hand:

```bash
python3 menubar/kitchen.30s.py
```

## Configuration

A JSON file at `~/.config/kitchen-menubar/config.json`. To use another path, set the
`KITCHEN_MENUBAR_CONFIG` environment variable (SwiftBar's own environment, or a wrapper).
Every key is optional; a bad value is ignored with a warning line at the top of the menu.

```json
{
  "socket": "work",
  "prefixes": ["kitchen-", "orq-"],
  "manifests": ["~/notes/plans/*manifest*.md", "~/code/*/docs/*manifest*.md"],
  "done_markers": [".kitchen/done", ".orq/done"],
  "stale_days": 3,
  "worktree_roots": ["~/code/my-app"],
  "pr_urls": { "my-app": "https://github.com/OWNER/REPO/pull/{n}" },
  "terminal": "Terminal"
}
```

| key | default | meaning |
|---|---|---|
| `socket` | none | tmux server name (`tmux -L <socket>`); none = the default server |
| `prefixes` | `["kitchen-"]` | session-name prefixes that belong to the kitchen; other sessions are ignored. A unit `x` is the session `<prefix>x` |
| `manifests` | `[]` | globs (`~` allowed) of manifest files. The widget has no way to guess where your plans live, so this is the one key you must set |
| `done_markers` | `[".kitchen/done"]` | marker files, relative to the session's directory (or the unit's worktree), that mean "the unit closed" |
| `stale_days` | `3` | a manifest with no active row (`🔄`/`⏳`/`⏸`) that was last modified more than this many days ago is ignored |
| `max_age_days` | `0` | ignore **any** manifest older than this many days, even one with an open `⏳` row; `0` = never. Useful when abandoned batches keep the title orange |
| `worktree_roots` | `[]` | directories that a **relative** worktree path in a manifest row (`feat/x · .worktrees/x`) is resolved against. Needed only to find `done` markers of units whose session is already dead |
| `pr_urls` / `pr_url` | none | PR link template with `{n}` for the PR number, per manifest `project` or as the default. A full URL in the manifest's PR cell is used as is; only `http(s)` links are ever produced |
| `terminal` | `"Terminal"` | what **Attach** opens: `Terminal`, `iTerm`, or `Ghostty` (via `open -na`, best effort) |
| `tmux` | auto | path to the `tmux` binary (SwiftBar's `PATH` is minimal; `/opt/homebrew/bin` and `/usr/local/bin` are searched by default) |

### Manifest dialects

The widget reads a unit's state from the **emoji** in the state cell, so it works on the
public English manifests (`type: manifest`, `unit | size | route | state | …`,
`⏸ queued · 🔄 running · ⏳ waiting on human · ✅ PR · 🚫 aborted`) and on Portuguese ones
(`tipo: manifesto`, `unidade | tam | rota | estado | …`, `⏸ na fila · 🔄 rodando ·
⏳ aguarda humano · ✅ PR · 🚫 abortada`) alike. If the same unit id appears in several
manifests, the row from the most recently modified file wins. Rows in a `🧹` ("harvested", used by some
manifests after the merge) are counted but hidden from the menu.

## Behaviour you can rely on

- **It never freezes or breaks the menu bar.** Every `tmux` call has a short timeout. If
  `tmux` is missing or hangs, the menu says so and still lists the manifest rows (and skips
  the divergences, which need to know the sessions). An unexpected error becomes one menu
  line, not a traceback.
- **It never writes anything.** The only side effects are the two menu actions: *Attach*
  opens a terminal, *Copy* puts the attach command on the clipboard. Session and socket names
  are checked against `[A-Za-z0-9._-]` before they reach a command line.
- It is a single stdlib-only file (Python 3.9+) because SwiftBar runs a copy of it from its
  own folder. The manifest-row parsing is therefore a small duplicate of the logic in
  `skills/orchestrate/scripts/watch.py`.
