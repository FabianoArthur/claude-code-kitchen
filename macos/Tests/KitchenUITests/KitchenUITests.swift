import AppKit
import KitchenCore
import SwiftUI
import Testing
@testable import KitchenUI

private var utc: Calendar {
    var c = Calendar(identifier: .gregorian)
    c.timeZone = TimeZone(identifier: "UTC")!
    return c
}

@MainActor @Suite struct KitchenUITests {
    @Test func demoDataCoversEveryPanelPart() {
        let model = DemoData.model(calendar: utc)
        let p = model.panel
        #expect(p.body == .units)
        #expect(p.attention.count == 1)
        #expect(p.sections.map(\.status) == [.waiting, .running, .queued, .done])
        #expect(p.sections[3].earlier.count == 2)
        #expect(p.harvested == 1)
        #expect(p.updated == "14:02")
        #expect(model.usage.report?.meters().map(\.label) == ["Week", "5 hours", "Sonnet", "Opus"])
        #expect(model.isDemo)
    }

    @Test func demoDataIsMadeUp() {
        for unit in DemoData.snapshot.units {
            #expect(unit.project == "demo-app")
            if let link = unit.prLink { #expect(link.host == "github.com" && link.path.hasPrefix("/example/")) }
        }
    }

    @Test func menuBarTextAddsTheWeeklyPercentOnlyWhenAsked() {
        let model = DemoData.model(calendar: utc)
        #expect(MenuBarLabel(model: model).text == "▸2 !1")
        model.showWeeklyInMenuBar = true
        #expect(MenuBarLabel(model: model).text == "▸2 !1 62%")
        model.showUsage = false
        #expect(MenuBarLabel(model: model).text == "▸2 !1")
    }

    @Test func menuBarVoiceOverLabelSaysTheWeeklyPercentWhenItIsShown() {
        let model = DemoData.model(calendar: utc)
        let base = MenuBarLabel(model: model).spokenLabel
        #expect(!base.contains("62"))
        model.showWeeklyInMenuBar = true
        #expect(MenuBarLabel(model: model).spokenLabel == base + ", 62% of the weekly limit used")
        model.showUsage = false
        #expect(MenuBarLabel(model: model).spokenLabel == base)
    }

    @Test(arguments: [ColorScheme.light, .dark])
    func panelRenders(scheme: ColorScheme) throws {
        let view = PanelView(model: DemoData.model(calendar: utc)).environment(\.colorScheme, scheme)
        let renderer = ImageRenderer(content: view)
        let image = try #require(renderer.nsImage)
        #expect(image.size.width == Theme.panelWidth)
        #expect(image.size.height > 200)
    }

    @Test func usageCardRendersEveryState() throws {
        let now = DemoData.now
        let states: [UsageState] = [
            .idle, .ok(DemoData.usage, fetchedAt: now),
            .stale(DemoData.usage, fetchedAt: now, problem: .unavailable, retryAt: now.addingTimeInterval(600)),
            .problem(.keychainDenied), .problem(.needsLogin), .problem(.notSignedIn),
        ]
        for state in states {
            let card = UsageCard(state: state, now: now, retry: {}).frame(width: Theme.panelWidth)
            #expect(ImageRenderer(content: card).nsImage != nil)
        }
    }

    @Test func emptyAndFailedPanelsRender() throws {
        let empty = try KitchenSnapshot.decode(Data(#"{"schema": 1, "globs": 0}"#.utf8))
        let model = AppModel(demo: empty, usage: .problem(.keychainTimedOut), now: DemoData.now, calendar: utc)
        #expect(model.panel.body == .noGlobs)
        #expect(ImageRenderer(content: PanelView(model: model)).nsImage != nil)
    }
}
