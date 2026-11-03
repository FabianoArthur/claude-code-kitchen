import Foundation
import Testing
@testable import KitchenCore

@Suite struct FormattingTests {
    let now = fixtureNow

    static let resets: [(Double, String)] = [
        (-5, "now"), (0, "now"), (20, "1m"), (300, "5m"), (3540, "59m"),
        (3600, "1h"), (11_400, "3h 10m"), (86_400, "1d"), (189_540, "2d 4h"),
    ]

    @Test(arguments: resets)
    func resetsIn(seconds: Double, expected: String) {
        #expect(Formatting.duration(until: now.addingTimeInterval(seconds), now: now) == expected)
    }

    static let spoken: [(Double, String)] = [
        (11_400, "3 hours 10 minutes"), (187_200, "2 days 4 hours"), (60, "1 minute"), (86_400, "1 day"),
    ]

    @Test(arguments: spoken)
    func spokenDuration(seconds: Double, expected: String) {
        #expect(Formatting.spokenDuration(until: now.addingTimeInterval(seconds), now: now) == expected)
    }

    static let agos: [(Double, String)] = [
        (10, "just now"), (59, "just now"), (60, "1m ago"), (180, "3m ago"), (7200, "2h ago"), (259_200, "3d ago"),
    ]

    @Test(arguments: agos)
    func updatedAgo(seconds: Double, expected: String) {
        #expect(Formatting.ago(since: now.addingTimeInterval(-seconds), now: now) == expected)
    }

    @Test(arguments: [(0.0, "0%"), (0.1, "<1%"), (8.0, "8%"), (61.6, "62%"), (100.0, "100%"), (112.0, "112%")])
    func percent(value: Double, expected: String) {
        #expect(Formatting.percent(value) == expected)
    }

    @Test func clock() {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(identifier: "UTC")!
        #expect(Formatting.clock(fixtureNow.addingTimeInterval(14 * 3600 + 2 * 60), calendar: cal) == "14:02")
    }
}
