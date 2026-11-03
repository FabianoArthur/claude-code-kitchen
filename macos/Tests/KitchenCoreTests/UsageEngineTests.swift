import Foundation
import Testing
@testable import KitchenCore

private func credential(_ token: String = "tok-A", expires: Date? = fixtureNow.addingTimeInterval(3600)) -> Credential {
    Credential(accessToken: token, expiresAt: expires)
}

private func report(_ week: Double = 62) -> UsageReport {
    UsageReport(sevenDay: .init(utilization: week, resetsAt: nil))
}

@Suite struct PollPolicyTests {
    @Test func backoffDoublesUpToAnHour() {
        #expect((0...6).map { PollPolicy.backoff(failures: $0) } == [300, 300, 600, 1200, 2400, 3600, 3600])
    }

    @Test(arguments: [
        (String?.none, TimeInterval?.none), ("10", 300), ("900", 900), ("86400", 3600), ("soon", nil), ("-5", nil),
    ])
    func retryAfterIsClamped(header: String?, expected: TimeInterval?) {
        #expect(PollPolicy.retryAfter(header) == expected)
    }
}

@Suite struct UsageEngineTests {
    let now = fixtureNow

    @Test func firstStepReadsTheKeychain() {
        let e = UsageEngine()
        #expect(e.state == .idle)
        #expect(e.next(now: now) == .readCredential)
    }

    @Test func aValidCredentialIsFetchedAndRequestsAreSpacedFiveMinutes() {
        var e = UsageEngine()
        let c = credential()
        #expect(e.credential(.found(c), now: now) == c)
        e.response(.ok(report()), now: now)
        #expect(e.state == .ok(report(), fetchedAt: now))
        #expect(e.next(now: now.addingTimeInterval(60)) == .wait(until: now.addingTimeInterval(300)))
        #expect(e.next(now: now.addingTimeInterval(300)) == .readCredential)
    }

    @Test func manualRefreshCannotBypassTheSpacing() {
        var e = UsageEngine()
        _ = e.credential(.found(credential()), now: now)
        e.response(.ok(report()), now: now)
        e.retry()
        #expect(e.next(now: now.addingTimeInterval(10)) == .wait(until: now.addingTimeInterval(300)))
    }

    @Test func expiredTokenIsNeverSent() {
        var e = UsageEngine()
        let old = credential(expires: now.addingTimeInterval(-1))
        #expect(e.credential(.found(old), now: now) == nil)
        #expect(e.state == .problem(.needsLogin))
    }

    @Test func unauthorizedTokenIsNotRetriedUntilTheKeychainChanges() {
        var e = UsageEngine()
        let a = credential("tok-A")
        _ = e.credential(.found(a), now: now)
        e.response(.unauthorized, now: now)
        #expect(e.state == .problem(.needsLogin))
        let later = now.addingTimeInterval(600)
        #expect(e.next(now: later) == .readCredential)
        #expect(e.credential(.found(a), now: later) == nil)  // same token: no network
        #expect(e.state == .problem(.needsLogin))
        let b = credential("tok-B")
        #expect(e.credential(.found(b), now: later.addingTimeInterval(300)) == b)
    }

    @Test func forbiddenAlsoAsksForRenewal() {
        var e = UsageEngine()
        _ = e.credential(.found(credential()), now: now)
        e.response(.forbidden, now: now)
        #expect(e.state == .problem(.needsLogin))
    }

    @Test(arguments: [(CredentialOutcome.denied, UsageProblem.keychainDenied), (.timedOut, .keychainTimedOut)])
    func deniedOrTimedOutKeychainHaltsUntilRetry(outcome: CredentialOutcome, problem: UsageProblem) {
        var e = UsageEngine()
        #expect(e.credential(outcome, now: now) == nil)
        #expect(e.state == .problem(problem))
        #expect(e.next(now: now.addingTimeInterval(86_400)) == .halted)
        e.retry()
        #expect(e.next(now: now.addingTimeInterval(86_400)) == .readCredential)
    }

    @Test func missingCredentialSaysNotSignedIn() {
        var e = UsageEngine()
        _ = e.credential(.notFound, now: now)
        #expect(e.state == .problem(.notSignedIn))
        #expect(e.next(now: now.addingTimeInterval(299)) == .wait(until: now.addingTimeInterval(300)))
        _ = e.credential(.unreadable, now: now)
        #expect(e.state == .problem(.unreadable))
    }

    @Test func errorsKeepTheLastValuesAndBackOff() {
        var e = UsageEngine()
        _ = e.credential(.found(credential()), now: now)
        e.response(.ok(report()), now: now)
        let t1 = now.addingTimeInterval(300)
        _ = e.credential(.found(credential()), now: t1)
        e.response(.serverError(503), now: t1)
        #expect(e.state == .stale(report(), fetchedAt: now, problem: .unavailable, retryAt: t1.addingTimeInterval(300)))
        let t2 = t1.addingTimeInterval(300)
        _ = e.credential(.found(credential()), now: t2)
        e.response(.network, now: t2)
        #expect(e.next(now: t2) == .wait(until: t2.addingTimeInterval(600)))
        let t3 = t2.addingTimeInterval(600)
        _ = e.credential(.found(credential()), now: t3)
        e.response(.ok(report(70)), now: t3)
        #expect(e.state == .ok(report(70), fetchedAt: t3))
        #expect(e.next(now: t3) == .wait(until: t3.addingTimeInterval(300)))
    }

    @Test func rateLimitHonoursRetryAfter() {
        var e = UsageEngine()
        _ = e.credential(.found(credential()), now: now)
        e.response(.rateLimited(retryAfter: 1800), now: now)
        #expect(e.state == .problem(.rateLimited(retryAt: now.addingTimeInterval(1800))))
        #expect(e.next(now: now) == .wait(until: now.addingTimeInterval(1800)))
    }

    @Test func badResponseIsAnError() {
        var e = UsageEngine()
        _ = e.credential(.found(credential()), now: now)
        e.response(.badResponse, now: now)
        #expect(e.state == .problem(.unavailable))
    }
}
