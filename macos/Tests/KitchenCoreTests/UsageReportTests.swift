import Foundation
import Testing
@testable import KitchenCore

@Suite struct UsageReportTests {
    @Test func decodesTheMeasuredShape() throws {
        let r = try UsageReport.decode(Fixture.data("usage.json"))
        #expect(r.sevenDay?.utilization == 62)
        #expect(r.fiveHour?.utilization == 18)
        #expect(r.sevenDayOpus?.utilization == 81)
        #expect(r.sevenDaySonnet == nil)
        // the malformed entry is dropped, the rest survive
        #expect(r.limits.count == 4)
        #expect(r.sevenDay?.resetsAt == ISO8601.parse("2026-01-03T04:00:00.254006+00:00"))
    }

    @Test func parsesMicrosecondTimestamps() {
        let d = ISO8601.parse("2026-11-06T14:00:00.254006+00:00")
        #expect(d != nil)
        #expect(abs(d!.timeIntervalSince1970 - 1_793_973_600.254006) < 0.001)
        #expect(ISO8601.parse("2026-11-06T14:00:00+00:00")?.timeIntervalSince1970 == 1_793_973_600)
        #expect(ISO8601.parse("2026-11-06T14:00:00Z")?.timeIntervalSince1970 == 1_793_973_600)
        #expect(ISO8601.parse("2026-11-06T11:00:00-03:00")?.timeIntervalSince1970 == 1_793_973_600)
        #expect(ISO8601.parse("yesterday") == nil)
    }

    @Test func metersInOrderWeekFiveHoursThenModels() throws {
        let r = try UsageReport.decode(Fixture.data("usage.json"))
        let m = r.meters()
        #expect(m.map(\.label) == ["Week", "5 hours", "Sonnet", "Opus"])
        #expect(m.map(\.percent) == [62, 18, 96, 85])  // limits win over the legacy opus window
        #expect(m[0].kind == .week && m[1].kind == .fiveHour && m[2].kind == .model)
        #expect(m[1].resetsAt == ISO8601.parse("2026-01-01T03:10:00.254006+00:00"))
    }

    @Test func closedFiveHourWindowIsAnEmptyMeter() throws {
        let r = try UsageReport.decode(Data(#"{"five_hour": null, "seven_day": {"utilization": 8.0, "resets_at": "2026-11-06T14:00:00+00:00"}}"#.utf8))
        let m = r.meters()
        #expect(m.map(\.label) == ["Week", "5 hours"])
        #expect(m[1].percent == nil && m[1].resetsAt == nil)
    }

    @Test func legacyModelWindowsAppearWhenLimitsAreAbsent() throws {
        let r = try UsageReport.decode(Data(#"{"seven_day": {"utilization": 1}, "seven_day_opus": {"utilization": 40}, "seven_day_sonnet": {"utilization": 3}}"#.utf8))
        #expect(r.meters().map(\.label) == ["Week", "5 hours", "Opus", "Sonnet"])
    }

    @Test func emptyObjectStillGivesTheTwoMainMeters() throws {
        let m = try UsageReport.decode(Data("{}".utf8)).meters()
        #expect(m.map(\.label) == ["Week", "5 hours"])
        #expect(m.allSatisfy { $0.percent == nil })
    }
}

@Suite struct SeverityTests {
    @Test(arguments: [
        (0.0, Severity.normal), (79.9, .normal), (80.0, .warning), (94.9, .warning),
        (95.0, .critical), (100.0, .critical), (130.0, .critical),
    ])
    func thresholds(percent: Double, expected: Severity) {
        #expect(Severity(percent: percent) == expected)
    }

    @Test func unknownPercentIsNormal() {
        #expect(Severity(percent: nil) == .normal)
    }
}
