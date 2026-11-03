import Foundation
import KitchenCore

/// Made-up data for `--demo` screenshots and view tests. Nothing here comes from a real kitchen.
public enum DemoData {
    /// 2026-01-01 14:02 UTC.
    public static let now = Date(timeIntervalSince1970: 1_767_276_120)

    public static let snapshot: KitchenSnapshot = {
        let json = #"""
        {"schema": 1, "generated_at": 1767276120, "warning": null, "error": null, "tmux_reason": "",
         "globs": 1, "manifest_dir": "/demo/plans",
         "units": [
          {"unit": "rate-limit", "project": "demo-app", "status": "running", "branch": "feat/rate-limit",
           "session": "kitchen-rate-limit", "alive": true, "age_seconds": 754, "age_text": "12m",
           "pane": "Running tests: 214 passed, 3 to go", "attach_command": "tmux attach -t '=kitchen-rate-limit'"},
          {"unit": "export-csv", "project": "demo-app", "status": "waiting", "reason": "pick the CSV dialect",
           "branch": "feat/export-csv", "pr": "43", "pr_link": "https://github.com/example/demo-app/pull/43",
           "session": "kitchen-export-csv", "alive": true, "age_seconds": 4320, "age_text": "1h12",
           "pane": "Which CSV dialect should the export use?", "attach_command": "tmux attach -t '=kitchen-export-csv'"},
          {"unit": "search-api", "project": "demo-app", "status": "running", "branch": "feat/search-api",
           "session": "kitchen-search-api", "alive": true, "age_seconds": 1500, "age_text": "25m",
           "pane": "Writing src/search/index.ts", "attach_command": "tmux attach -t '=kitchen-search-api'"},
          {"unit": "dark-mode", "project": "demo-app", "status": "queued", "branch": "feat/dark-mode"},
          {"unit": "login-fix", "project": "demo-app", "status": "done", "branch": "fix/login",
           "pr": "42", "pr_link": "https://github.com/example/demo-app/pull/42"},
          {"unit": "docs-refresh", "project": "demo-app", "status": "done", "recent": false, "pr": "38"},
          {"unit": "ci-cache", "project": "demo-app", "status": "done", "recent": false, "pr": "37"},
          {"unit": "old-idea", "project": "demo-app", "status": "harvested", "recent": false}
         ],
         "divergences": [
          {"kind": "orphan", "unit": "kitchen-stray", "session": "kitchen-stray",
           "text": "kitchen-stray: live session with no manifest row", "attach_command": "tmux attach -t '=kitchen-stray'"}
         ]}
        """#
        // The literal is fixed and covered by a test; a failure here is a programming error.
        return try! KitchenSnapshot.decode(Data(json.utf8))
    }()

    public static let usage: UsageReport = UsageReport(
        fiveHour: UsageWindow(utilization: 18, resetsAt: now.addingTimeInterval(3 * 3600 + 10 * 60)),
        sevenDay: UsageWindow(utilization: 62, resetsAt: now.addingTimeInterval(2 * 86_400 + 4 * 3600)),
        limits: [
            UsageLimit(kind: "weekly_scoped", percent: 96, modelName: "Sonnet"),
            UsageLimit(kind: "weekly_scoped", percent: 81, modelName: "Opus"),
        ])

    /// UTC, so a screenshot never reveals the time zone of the machine that took it.
    public static var calendar: Calendar {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = TimeZone(identifier: "UTC")!
        return c
    }

    @MainActor
    public static func model(calendar: Calendar = DemoData.calendar) -> AppModel {
        AppModel(demo: snapshot, usage: .ok(usage, fetchedAt: now.addingTimeInterval(-180)), now: now, calendar: calendar)
    }
}
