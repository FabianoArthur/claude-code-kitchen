import Foundation
import Testing
@testable import KitchenCore

@Suite struct KitchenSnapshotTests {
    @Test func decodesTheFixtureTheScriptProduces() throws {
        let s = try KitchenSnapshot.decode(Fixture.data("kitchen.json"))
        #expect(s.schema == 1)
        #expect(s.generatedAt == fixtureNow)
        #expect(s.warning == "config error: ignored invalid value for stale_days")
        #expect(s.error == nil)
        #expect(s.globs == 1)
        #expect(s.manifestDir == "/fixtures/plans")
        #expect(s.count(.running) == 2 && s.count(.waiting) == 1 && s.count(.harvested) == 0)
        #expect(s.units.map(\.unit) == ["rate-limit", "export-csv", "search-api", "login-fix", "old-idea", "new-ui"])
        let rl = s.units[0]
        #expect(rl.status == .running && rl.alive && !rl.done)
        #expect(rl.session == "kitchen-rate-limit")
        #expect(rl.ageText == "12m" && rl.ageSeconds == 754)
        #expect(rl.pane == "Running tests: 214 passed, 3 to go")
        #expect(rl.attachCommand == "tmux attach -t '=kitchen-rate-limit'")
        let ex = s.units[1]
        #expect(ex.status == .waiting && ex.reason == "pick the CSV dialect")
        #expect(ex.prLink == URL(string: "https://github.com/example/demo-app/pull/43"))
        #expect(ex.pr == "43")
        #expect(s.units[5].ageText == nil && s.units[5].attachCommand == nil)
        #expect(s.divergences.map(\.kind) == ["crash", "orphan"])
        #expect(s.divergences[0].session == nil && s.divergences[0].attachCommand == nil)
        #expect(s.divergences[1].attachCommand == "tmux attach -t '=kitchen-stray'")
    }

    @Test func decodesTheErrorFixture() throws {
        let s = try KitchenSnapshot.decode(Fixture.data("kitchen-error.json"))
        #expect(s.error == "ZeroDivisionError: division by zero")
        #expect(s.units.isEmpty && s.divergences.isEmpty)
    }

    @Test func toleratesMissingFieldsAndUnknownStates() throws {
        let json = #"{"schema": 1, "units": [{"unit": "x", "status": "brand-new-state"}], "extra": [1, 2]}"#
        let s = try KitchenSnapshot.decode(Data(json.utf8))
        #expect(s.units.count == 1)
        #expect(s.units[0].status == .unknown)
        #expect(s.units[0].pane == "" && s.units[0].prLink == nil && s.units[0].recent)
        #expect(s.divergences.isEmpty && s.warning == nil && s.tmuxReason == "")
    }

    @Test func onlyHTTPLinksAreKept() throws {
        let json = #"{"schema": 1, "units": [{"unit": "a", "status": "done", "pr_link": "javascript:alert(1)"}, {"unit": "b", "status": "done", "pr_link": "file:///etc/hosts"}]}"#
        let s = try KitchenSnapshot.decode(Data(json.utf8))
        #expect(s.units.allSatisfy { $0.prLink == nil })
    }

    @Test func interpretMapsProcessOutcomes() throws {
        let good = ProcessOutput(status: 0, stdout: try Fixture.data("kitchen.json"), stderr: Data())
        #expect((try? KitchenSnapshot.interpret(good).get())?.units.count == 6)
        let failed = ProcessOutput(status: 2, stdout: Data(), stderr: Data("boom".utf8))
        #expect(KitchenSnapshot.interpret(failed) == .failure(.exit(2)))
        let garbage = ProcessOutput(status: 0, stdout: Data("not json".utf8), stderr: Data())
        #expect(KitchenSnapshot.interpret(garbage) == .failure(.badOutput))
        let future = ProcessOutput(status: 0, stdout: Data(#"{"schema": 2}"#.utf8), stderr: Data())
        #expect(KitchenSnapshot.interpret(future) == .failure(.unsupportedSchema(2)))
        let err = ProcessOutput(status: 0, stdout: try Fixture.data("kitchen-error.json"), stderr: Data())
        #expect(KitchenSnapshot.interpret(err) == .failure(.scriptError("ZeroDivisionError: division by zero")))
    }
}
