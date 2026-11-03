import CryptoKit
import Foundation

/// The Claude Code OAuth access token, read fresh for one request and then dropped.
/// Its descriptions, debug output and mirror never contain the token.
public struct Credential: Sendable, Equatable, CustomStringConvertible, CustomDebugStringConvertible, CustomReflectable {
    public let accessToken: String
    public let expiresAt: Date?

    public init(accessToken: String, expiresAt: Date?) {
        self.accessToken = accessToken
        self.expiresAt = expiresAt
    }

    /// SHA-256 of the token, hex. Lets the app tell "same token as the one that got a 401"
    /// without keeping the token itself.
    public var fingerprint: String {
        SHA256.hash(data: Data(accessToken.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    public func isExpired(at now: Date) -> Bool {
        expiresAt.map { $0 <= now } ?? false
    }

    public static func == (a: Credential, b: Credential) -> Bool { a.fingerprint == b.fingerprint }

    public var description: String { "Credential(<redacted>)" }
    public var debugDescription: String { description }
    public var customMirror: Mirror { Mirror(self, children: [:]) }
}

/// Fixed-text failures: nothing from the keychain payload is ever interpolated.
public enum CredentialError: Error, Equatable, Sendable, CustomStringConvertible, LocalizedError {
    case malformed
    case missingToken

    public var description: String {
        switch self {
        case .malformed: "The Claude Code credential could not be parsed"
        case .missingToken: "The Claude Code credential has no access token"
        }
    }

    public var errorDescription: String? { description }
}

public enum CredentialParser {
    private struct Item: Decodable {
        struct OAuth: Decodable {
            var accessToken: String?
            var expiresAt: Double?
        }
        var claudeAiOauth: OAuth?
    }

    /// Parses the secret printed by `security find-generic-password -w`, which is the JSON
    /// itself or, when the secret has non-printable bytes, its hex encoding.
    public static func parse(_ raw: Data) -> Result<Credential, CredentialError> {
        guard var text = String(data: raw, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines),
              !text.isEmpty else { return .failure(.malformed) }
        if let decoded = hexDecoded(text) { text = decoded }
        guard let item = try? JSONDecoder().decode(Item.self, from: Data(text.utf8)) else { return .failure(.malformed) }
        guard let oauth = item.claudeAiOauth, let token = oauth.accessToken, !token.isEmpty else {
            return .failure(.missingToken)
        }
        let expires = oauth.expiresAt.map { $0 > 100_000_000_000 ? $0 / 1000 : $0 }.map(Date.init(timeIntervalSince1970:))
        return .success(Credential(accessToken: token, expiresAt: expires))
    }

    private static func hexDecoded(_ text: String) -> String? {
        guard text.count.isMultiple(of: 2), text.allSatisfy(\.isHexDigit), !text.hasPrefix("{") else { return nil }
        var bytes = [UInt8]()
        bytes.reserveCapacity(text.count / 2)
        var index = text.startIndex
        while index < text.endIndex {
            let next = text.index(index, offsetBy: 2)
            guard let byte = UInt8(text[index..<next], radix: 16) else { return nil }
            bytes.append(byte)
            index = next
        }
        return String(bytes: bytes, encoding: .utf8)
    }
}

/// Result of one keychain read.
public enum CredentialOutcome: Equatable, Sendable, CustomStringConvertible {
    case found(Credential)
    case notFound
    case denied
    case timedOut
    case unreadable

    public var description: String {
        switch self {
        case .found: "found(<redacted>)"
        case .notFound: "notFound"
        case .denied: "denied"
        case .timedOut: "timedOut"
        case .unreadable: "unreadable"
        }
    }
}

/// Reads Claude Code's keychain item through `/usr/bin/security`. Read only: there is no write path.
public enum CredentialReader {
    public static let executable = URL(fileURLWithPath: "/usr/bin/security")
    public static let service = "Claude Code-credentials"
    public static let arguments = ["find-generic-password", "-s", service, "-w"]
    /// Long enough to answer a keychain dialog by hand.
    public static let timeout: TimeInterval = 90
    /// `errSecItemNotFound` as an exit status.
    static let notFoundStatus: Int32 = 44

    public static func read() async -> CredentialOutcome {
        let result = await ProcessRunner.run(executable, arguments, timeout: timeout,
                                             stdoutLimit: 1 << 20, environment: [:])
        return interpret(result)
    }

    public static func interpret(_ result: Result<ProcessOutput, ProcessFailure>) -> CredentialOutcome {
        switch result {
        case .failure(.timedOut): return .timedOut
        case .failure(.outputTooLarge): return .unreadable
        case .failure(.launchFailed): return .denied
        case .success(let output) where output.status == notFoundStatus: return .notFound
        case .success(let output) where output.status != 0: return .denied
        case .success(let output):
            switch CredentialParser.parse(output.stdout) {
            case .success(let credential): return .found(credential)
            case .failure: return .unreadable
            }
        }
    }
}
