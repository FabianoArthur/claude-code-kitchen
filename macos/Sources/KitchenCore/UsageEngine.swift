import Foundation

/// How often the usage endpoint may be called.
public enum PollPolicy {
    public static let minimumInterval: TimeInterval = 300
    public static let maximumInterval: TimeInterval = 3600

    /// 5 → 10 → 20 → 40 → 60 min after consecutive failures.
    public static func backoff(failures: Int) -> TimeInterval {
        guard failures > 1 else { return minimumInterval }
        return min(maximumInterval, minimumInterval * pow(2, Double(min(failures - 1, 8))))
    }

    /// A `Retry-After` in seconds, clamped to 5–60 min; nil when absent or not a number.
    public static func retryAfter(_ header: String?) -> TimeInterval? {
        guard let header, let seconds = Double(header.trimmingCharacters(in: .whitespaces)), seconds >= 0 else {
            return nil
        }
        return min(maximumInterval, max(minimumInterval, seconds))
    }
}

/// What one call of the endpoint produced. Fixed cases, never the HTTP body.
public enum UsageOutcome: Equatable, Sendable {
    case ok(UsageReport)
    case unauthorized
    case forbidden
    case rateLimited(retryAfter: TimeInterval?)
    case serverError(Int)
    case badResponse
    case network
}

public enum UsageProblem: Equatable, Sendable {
    case notSignedIn
    case needsLogin
    case keychainDenied
    case keychainTimedOut
    case unreadable
    case rateLimited(retryAt: Date)
    case unavailable
}

public enum UsageState: Equatable, Sendable {
    case idle
    case loading
    case ok(UsageReport, fetchedAt: Date)
    case stale(UsageReport, fetchedAt: Date, problem: UsageProblem, retryAt: Date)
    case problem(UsageProblem)

    public var report: UsageReport? {
        switch self {
        case .ok(let r, _), .stale(let r, _, _, _): r
        default: nil
        }
    }
}

/// The usage card's state machine. Pure: the app model feeds it keychain and HTTP outcomes and
/// asks it what to do next, so every rule in the *Security rules* table is unit-tested here.
public struct UsageEngine: Sendable {
    public enum Step: Equatable, Sendable {
        case wait(until: Date)
        case readCredential
        /// The keychain was denied or the dialog went unanswered: nothing happens until `retry()`.
        case halted
    }

    public private(set) var state: UsageState = .idle
    private var nextAllowed: Date = .distantPast
    private var failures = 0
    private var halted = false
    private var inFlight: String?
    private var rejected: String?
    private var last: (report: UsageReport, at: Date)?

    public init() {}

    public func next(now: Date) -> Step {
        if halted { return .halted }
        return now < nextAllowed ? .wait(until: nextAllowed) : .readCredential
    }

    /// Feeds a keychain read; returns the credential to send, or nil when no request should be made.
    public mutating func credential(_ outcome: CredentialOutcome, now: Date) -> Credential? {
        nextAllowed = now.addingTimeInterval(PollPolicy.minimumInterval)
        switch outcome {
        case .found(let credential):
            if credential.isExpired(at: now) {
                rejected = credential.fingerprint
                state = .problem(.needsLogin)
                return nil
            }
            if credential.fingerprint == rejected {
                state = .problem(.needsLogin)
                return nil
            }
            rejected = nil
            inFlight = credential.fingerprint
            if state == .idle { state = .loading }
            return credential
        case .notFound: state = .problem(.notSignedIn)
        case .unreadable: state = .problem(.unreadable)
        case .denied:
            halted = true
            state = .problem(.keychainDenied)
        case .timedOut:
            halted = true
            state = .problem(.keychainTimedOut)
        }
        return nil
    }

    public mutating func response(_ outcome: UsageOutcome, now: Date) {
        defer { inFlight = nil }
        switch outcome {
        case .ok(let report):
            failures = 0
            last = (report, now)
            state = .ok(report, fetchedAt: now)
            nextAllowed = now.addingTimeInterval(PollPolicy.minimumInterval)
        case .unauthorized, .forbidden:
            rejected = inFlight
            state = .problem(.needsLogin)
            nextAllowed = now.addingTimeInterval(PollPolicy.minimumInterval)
        case .rateLimited(let retryAfter):
            failures += 1
            let at = now.addingTimeInterval(retryAfter ?? PollPolicy.backoff(failures: failures))
            fail(.rateLimited(retryAt: at), retryAt: at)
        case .serverError, .badResponse, .network:
            failures += 1
            fail(.unavailable, retryAt: now.addingTimeInterval(PollPolicy.backoff(failures: failures)))
        }
    }

    /// *Try again*: lifts a keychain halt. Never shortens the 5-minute spacing between requests.
    public mutating func retry() {
        halted = false
    }

    private mutating func fail(_ problem: UsageProblem, retryAt: Date) {
        nextAllowed = retryAt
        if let last {
            state = .stale(last.report, fetchedAt: last.at, problem: problem, retryAt: retryAt)
        } else {
            state = .problem(problem)
        }
    }
}

extension UsageProblem {
    /// Fixed text for the usage card.
    public func message(now: Date) -> String {
        switch self {
        case .notSignedIn: "Not signed in to Claude Code"
        case .needsLogin: "Open Claude Code to renew the session"
        case .keychainDenied: "Keychain access was denied or unavailable"
        case .keychainTimedOut: "The keychain prompt timed out"
        case .unreadable: "Couldn't read the Claude Code credential"
        case .rateLimited(let at): "Rate limited — retrying in \(Formatting.duration(until: at, now: now))"
        case .unavailable: "Usage unavailable right now"
        }
    }

    /// Keychain halts wait for the user; every other problem retries on its own.
    public var offersRetry: Bool {
        self == .keychainDenied || self == .keychainTimedOut
    }
}

extension UsageState {
    /// "updated 3m ago", or "updated 12m ago · retrying in 10m" while showing old values.
    public func footnote(now: Date) -> String? {
        switch self {
        case .ok(_, let at): "updated \(Formatting.ago(since: at, now: now))"
        case .stale(_, let at, _, let retryAt):
            "updated \(Formatting.ago(since: at, now: now)) · retrying in \(Formatting.duration(until: retryAt, now: now))"
        default: nil
        }
    }
}
