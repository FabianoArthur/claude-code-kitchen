import Foundation
import Testing
@testable import KitchenCore

@Suite struct UsageTextTests {
    let now = fixtureNow

    @Test func problemMessages() {
        #expect(UsageProblem.notSignedIn.message(now: now) == "Not signed in to Claude Code")
        #expect(UsageProblem.needsLogin.message(now: now) == "Open Claude Code to renew the session")
        #expect(UsageProblem.keychainDenied.message(now: now) == "Keychain access was denied or unavailable")
        #expect(UsageProblem.keychainTimedOut.message(now: now) == "The keychain prompt timed out")
        #expect(UsageProblem.unreadable.message(now: now) == "Couldn't read the Claude Code credential")
        #expect(UsageProblem.rateLimited(retryAt: now.addingTimeInterval(600)).message(now: now) == "Rate limited — retrying in 10m")
        #expect(UsageProblem.unavailable.message(now: now) == "Usage unavailable right now")
    }

    @Test func onlyKeychainProblemsOfferTryAgain() {
        #expect(UsageProblem.keychainDenied.offersRetry && UsageProblem.keychainTimedOut.offersRetry)
        #expect(!UsageProblem.needsLogin.offersRetry && !UsageProblem.unavailable.offersRetry)
    }

    @Test func footnotes() {
        let r = UsageReport()
        #expect(UsageState.ok(r, fetchedAt: now.addingTimeInterval(-180)).footnote(now: now) == "updated 3m ago")
        #expect(UsageState.stale(r, fetchedAt: now.addingTimeInterval(-720), problem: .unavailable,
                                 retryAt: now.addingTimeInterval(600)).footnote(now: now) == "updated 12m ago · retrying in 10m")
        #expect(UsageState.problem(.needsLogin).footnote(now: now) == nil)
    }
}
