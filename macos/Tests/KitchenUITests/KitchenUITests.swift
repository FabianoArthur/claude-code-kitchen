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

    /// Header + divider + footer, with no list: the size a collapsed list area renders at.
    static let chromeAllowance: CGFloat = 160

    private func renderedSize(_ model: AppModel, _ scheme: ColorScheme = .light) throws -> CGSize {
        // One render pass with an unspecified proposal, like the menu-bar window sizing to fit.
        let renderer = ImageRenderer(content: PanelView(model: model).environment(\.colorScheme, scheme))
        return try #require(renderer.nsImage).size
    }

    /// The demo's content is taller than the cap, so the list area must be exactly at the cap
    /// on the very first render (no measure-then-resize round trip): at least `maxListHeight`,
    /// at most the cap plus the header and footer.
    @Test(arguments: [ColorScheme.light, .dark])
    func tallPanelRendersAtTheListCap(scheme: ColorScheme) throws {
        let size = try renderedSize(DemoData.model(calendar: utc), scheme)
        #expect(size.width == Theme.panelWidth)
        #expect(size.height >= Theme.maxListHeight)
        #expect(size.height <= Theme.maxListHeight + Self.chromeAllowance)
    }

    /// A short panel hugs its content: taller than the chrome alone (the list is not collapsed)
    /// and shorter than the capped demo.
    @Test func shortPanelHugsItsContent() throws {
        let one = try KitchenSnapshot.decode(Data(#"""
            {"schema": 1, "globs": 1, "counts": {"running": 1},
             "units": [{"unit": "solo", "project": "demo-app", "status": "running", "alive": true}]}
            """#.utf8))
        let short = try renderedSize(AppModel(demo: one, usage: .ok(DemoData.usage, fetchedAt: DemoData.now),
                                              now: DemoData.now, calendar: utc))
        let tall = try renderedSize(DemoData.model(calendar: utc))
        #expect(short.height > Self.chromeAllowance + 100)  // header/footer + usage card + one row
        #expect(short.height < tall.height - 100)
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
