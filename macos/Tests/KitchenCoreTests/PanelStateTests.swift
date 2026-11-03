import Foundation
import Testing
@testable import KitchenCore

private var utc: Calendar {
    var c = Calendar(identifier: .gregorian)
    c.timeZone = TimeZone(identifier: "UTC")!
    return c
}

private func snapshot(_ json: String) throws -> KitchenSnapshot {
    try KitchenSnapshot.decode(Data(json.utf8))
}

@Suite struct PanelStateTests {
    @Test func loadingBeforeTheFirstRun() {
        let p = PanelState.derive(KitchenFeed(), calendar: utc)
        #expect(p.body == .loading)
        #expect(p.menuBar == MenuBarSummary(symbol: "flame", text: "", accessibilityLabel: "Kitchen: loading"))
    }

    @Test func fullFixture() throws {
        let s = try KitchenSnapshot.decode(Fixture.data("kitchen.json"))
        let p = PanelState.derive(KitchenFeed(snapshot: s, refreshedAt: fixtureNow), calendar: utc)
        #expect(p.body == .units)
        #expect(p.banners == [.warning("config error: ignored invalid value for stale_days")])
        #expect(p.attention.map(\.kind) == ["crash", "orphan"])
        #expect(p.sections.map(\.status) == [.waiting, .running, .queued, .done, .aborted])
        #expect(p.sections[1].units.map(\.unit) == ["rate-limit", "search-api"])
        #expect(p.sections.map(\.title) == ["Waiting on you", "Running", "Queued", "Done", "Aborted"])
        #expect(p.summary == "2 running · 1 waiting on you · 2 need attention")
        #expect(p.menuBar == MenuBarSummary(
            symbol: "exclamationmark.triangle.fill", text: "▸2 !1",
            accessibilityLabel: "Kitchen: 2 running, 1 waiting on you, 2 need attention"))
        #expect(p.updated == "00:00")
    }

    @Test func oldDoneUnitsFoldIntoEarlierAndHarvestedOnlyCount() throws {
        let s = try snapshot(#"""
        {"schema": 1, "globs": 1, "units": [
          {"unit": "a", "status": "done", "recent": true},
          {"unit": "b", "status": "done", "recent": false},
          {"unit": "c", "status": "harvested", "recent": false},
          {"unit": "d", "status": "harvested"},
          {"unit": "e", "status": "mystery"}
        ]}
        """#)
        let p = PanelState.derive(KitchenFeed(snapshot: s), calendar: utc)
        #expect(p.sections.map(\.status) == [.done, .unknown])
        #expect(p.sections[0].units.map(\.unit) == ["a"])
        #expect(p.sections[0].earlier.map(\.unit) == ["b"])
        #expect(p.sections[0].count == 2)
        #expect(p.sections[1].title == "Unknown state")
        #expect(p.harvested == 2)
        #expect(p.summary == "Idle")
        #expect(p.menuBar == MenuBarSummary(symbol: "flame", text: "", accessibilityLabel: "Kitchen: idle"))
    }

    @Test func runningOnlyUsesTheFilledFlame() throws {
        let s = try snapshot(#"{"schema": 1, "globs": 1, "units": [{"unit": "a", "status": "running"}, {"unit": "q", "status": "queued"}]}"#)
        let p = PanelState.derive(KitchenFeed(snapshot: s), calendar: utc)
        #expect(p.menuBar == MenuBarSummary(symbol: "flame.fill", text: "▸1", accessibilityLabel: "Kitchen: 1 running"))
        #expect(p.summary == "1 running")
    }

    @Test func waitingOnlyNamesTheWait() throws {
        let s = try snapshot(#"{"schema": 1, "globs": 1, "units": [{"unit": "a", "status": "waiting"}, {"unit": "q", "status": "queued"}]}"#)
        let p = PanelState.derive(KitchenFeed(snapshot: s), calendar: utc)
        #expect(p.menuBar.symbol == "flame.fill" && p.menuBar.text == "!1")
        #expect(p.summary == "1 waiting on you")
        let q = try snapshot(#"{"schema": 1, "globs": 1, "units": [{"unit": "q", "status": "queued"}]}"#)
        #expect(PanelState.derive(KitchenFeed(snapshot: q), calendar: utc).summary == "1 queued")
    }

    @Test func emptyStates() throws {
        let none = try snapshot(#"{"schema": 1, "globs": 0}"#)
        #expect(PanelState.derive(KitchenFeed(snapshot: none), calendar: utc).body == .noGlobs)
        let noRows = try snapshot(#"{"schema": 1, "globs": 2}"#)
        #expect(PanelState.derive(KitchenFeed(snapshot: noRows), calendar: utc).body == .noRows)
        let onlyOrphan = try snapshot(#"{"schema": 1, "globs": 2, "divergences": [{"kind": "orphan", "text": "x"}]}"#)
        #expect(PanelState.derive(KitchenFeed(snapshot: onlyOrphan), calendar: utc).body == .units)
    }

    @Test func tmuxBanner() throws {
        let s = try snapshot(#"{"schema": 1, "globs": 1, "tmux_reason": "tmux not found", "units": [{"unit": "a", "status": "queued"}]}"#)
        #expect(PanelState.derive(KitchenFeed(snapshot: s), calendar: utc).banners == [.tmux("tmux unavailable — showing manifests only")])
    }

    @Test func failureWithoutDataShowsTheError() {
        let p = PanelState.derive(KitchenFeed(failure: .timedOut), calendar: utc)
        #expect(p.body == .failed("The kitchen script took too long to answer"))
        #expect(p.menuBar.accessibilityLabel == "Kitchen: couldn't read the kitchen")
    }

    @Test func failureWithDataKeepsItWithAStaleBanner() throws {
        let s = try KitchenSnapshot.decode(Fixture.data("kitchen.json"))
        let p = PanelState.derive(
            KitchenFeed(snapshot: s, refreshedAt: fixtureNow.addingTimeInterval(14 * 3600 + 120), failure: .badOutput),
            calendar: utc)
        #expect(p.body == .units)
        #expect(p.banners.first == .stale("Couldn't refresh — showing 14:02"))
        #expect(p.menuBar.symbol == "exclamationmark.triangle.fill")
    }

    @Test(arguments: [
        (KitchenFailure.exit(2), "The kitchen script exited with status 2"),
        (.badOutput, "The kitchen script's output wasn't valid JSON"),
        (.unsupportedSchema(3), "The kitchen script speaks a newer format (3) — rebuild the app"),
        (.scriptError("KeyError: 'x'"), "The kitchen script failed: KeyError: 'x'"),
        (.outputTooLarge, "The kitchen script's output was too large"),
        (.pythonMissing, "python3 not found — set pythonPath (see Settings)"),
        (.scriptMissing, "The kitchen script is missing — set scriptPath (see Settings)"),
    ])
    func failureTexts(failure: KitchenFailure, text: String) {
        #expect(failure.message == text)
    }

    @Test func unitAccessibilityLabel() throws {
        let s = try KitchenSnapshot.decode(Fixture.data("kitchen.json"))
        #expect(s.units[1].accessibilityLabel == "export-csv, waiting on you, demo-app, 1 hour 12 minutes, PR 43: pick the CSV dialect")
        #expect(s.units[0].accessibilityLabel == "rate-limit, running, demo-app, 12 minutes")
    }
}
