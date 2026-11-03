import Foundation

/// The states a manifest row can be in, as `kitchen.30s.py --json` names them.
public enum UnitStatus: String, CaseIterable, Sendable, Decodable {
    case waiting, running, queued, done, aborted, harvested, unknown

    public init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = UnitStatus(rawValue: raw) ?? .unknown
    }

    /// Section title, same wording as the SwiftBar plugin.
    public var title: String {
        switch self {
        case .waiting: "Waiting on you"
        case .running: "Running"
        case .queued: "Queued"
        case .done: "Done"
        case .aborted: "Aborted"
        case .harvested: "Harvested"
        case .unknown: "Unknown state"
        }
    }

    /// Lower-case phrase for VoiceOver labels.
    public var phrase: String {
        self == .waiting ? "waiting on you" : title.lowercased()
    }
}

/// One manifest row. Every field is optional on the wire; missing ones get a neutral default.
public struct KitchenUnit: Equatable, Sendable, Identifiable, Decodable {
    public var unit: String
    public var project: String
    public var status: UnitStatus
    public var reason: String
    public var size: String
    public var route: String
    public var branch: String
    public var pr: String
    public var prLink: URL?
    public var session: String?
    public var alive: Bool
    public var done: Bool
    public var ageSeconds: Double?
    public var ageText: String?
    public var recent: Bool
    public var pane: String
    public var attachCommand: String?

    public var id: String { "\(project)/\(unit)/\(branch)" }

    enum CodingKeys: String, CodingKey {
        case unit, project, status, reason, size, route, branch, pr, prLink, session, alive, done
        case ageSeconds, ageText, recent, pane, attachCommand
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        unit = c.lenient(String.self, .unit) ?? ""
        project = c.lenient(String.self, .project) ?? ""
        status = c.lenient(UnitStatus.self, .status) ?? .unknown
        reason = c.lenient(String.self, .reason) ?? ""
        size = c.lenient(String.self, .size) ?? ""
        route = c.lenient(String.self, .route) ?? ""
        branch = c.lenient(String.self, .branch) ?? ""
        pr = c.lenient(String.self, .pr) ?? ""
        prLink = c.lenient(String.self, .prLink).flatMap(webURL)
        session = c.lenient(String.self, .session)
        alive = c.lenient(Bool.self, .alive) ?? false
        done = c.lenient(Bool.self, .done) ?? false
        ageSeconds = c.lenient(Double.self, .ageSeconds)
        ageText = c.lenient(String.self, .ageText)
        recent = c.lenient(Bool.self, .recent) ?? true
        pane = c.lenient(String.self, .pane) ?? ""
        attachCommand = c.lenient(String.self, .attachCommand)
    }

    /// e.g. "export-csv, waiting on you, demo-app, 1 hour 12 minutes, PR 43: pick the CSV dialect".
    public var accessibilityLabel: String {
        var parts = [unit, status.phrase, project]
        if let ageSeconds { parts.append(Formatting.spokenAge(seconds: ageSeconds)) }
        if !pr.isEmpty { parts.append("PR \(pr)") }
        let label = parts.filter { !$0.isEmpty }.joined(separator: ", ")
        return reason.isEmpty ? label : "\(label): \(reason)"
    }
}

/// Something the manifests and tmux disagree about (crash, orphan, stale…).
public struct Divergence: Equatable, Sendable, Identifiable, Decodable {
    public var kind: String
    public var unit: String
    public var session: String?
    public var text: String
    public var attachCommand: String?

    public var id: String { "\(kind)/\(unit)/\(session ?? "")" }

    enum CodingKeys: String, CodingKey { case kind, unit, session, text, attachCommand }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        kind = c.lenient(String.self, .kind) ?? ""
        unit = c.lenient(String.self, .unit) ?? ""
        session = c.lenient(String.self, .session)
        text = c.lenient(String.self, .text) ?? ""
        attachCommand = c.lenient(String.self, .attachCommand)
    }
}

/// One run of `kitchen.30s.py --json` (schema 1, see docs/macos-app.md).
public struct KitchenSnapshot: Equatable, Sendable, Decodable {
    public static let supportedSchema = 1

    public var schema: Int
    public var generatedAt: Date?
    public var warning: String?
    public var error: String?
    public var tmuxReason: String
    public var globs: Int
    public var manifestDir: String
    public var units: [KitchenUnit]
    public var divergences: [Divergence]

    enum CodingKeys: String, CodingKey {
        case schema, generatedAt, warning, error, tmuxReason, globs, manifestDir, units, divergences
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        schema = c.lenient(Int.self, .schema) ?? 0
        generatedAt = c.lenient(Double.self, .generatedAt).map(Date.init(timeIntervalSince1970:))
        warning = c.lenient(String.self, .warning)
        error = c.lenient(String.self, .error)
        tmuxReason = c.lenient(String.self, .tmuxReason) ?? ""
        globs = c.lenient(Int.self, .globs) ?? 0
        manifestDir = c.lenient(String.self, .manifestDir) ?? ""
        units = c.lenient([KitchenUnit].self, .units) ?? []
        divergences = c.lenient([Divergence].self, .divergences) ?? []
    }

    public func count(_ status: UnitStatus) -> Int {
        units.count { $0.status == status }
    }

    public static func decode(_ data: Data) throws -> KitchenSnapshot {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(KitchenSnapshot.self, from: data)
    }

    /// Maps one finished run of the script to a snapshot or a closed, fixed-text failure.
    public static func interpret(_ output: ProcessOutput) -> Result<KitchenSnapshot, KitchenFailure> {
        guard output.status == 0 else { return .failure(.exit(output.status)) }
        guard let snapshot = try? decode(output.stdout) else { return .failure(.badOutput) }
        guard snapshot.schema == supportedSchema else { return .failure(.unsupportedSchema(snapshot.schema)) }
        if let error = snapshot.error { return .failure(.scriptError(error)) }
        return .success(snapshot)
    }
}

/// Why a refresh of the kitchen did not produce a snapshot.
public enum KitchenFailure: Error, Equatable, Sendable {
    case exit(Int32)
    case badOutput
    case unsupportedSchema(Int)
    case scriptError(String)
    case timedOut
    case outputTooLarge
    case pythonMissing
    case scriptMissing

    public var message: String {
        switch self {
        case .exit(let code): "The kitchen script exited with status \(code)"
        case .badOutput: "The kitchen script's output wasn't valid JSON"
        case .unsupportedSchema(let n): "The kitchen script speaks a newer format (\(n)) — rebuild the app"
        case .scriptError(let text): "The kitchen script failed: \(text)"
        case .timedOut: "The kitchen script took too long to answer"
        case .outputTooLarge: "The kitchen script's output was too large"
        case .pythonMissing: "python3 not found — set pythonPath (see Settings)"
        case .scriptMissing: "The kitchen script is missing — set scriptPath (see Settings)"
        }
    }
}

/// Only http(s) links ever become clickable.
func webURL(_ text: String) -> URL? {
    guard let url = URL(string: text), let scheme = url.scheme?.lowercased(),
          scheme == "https" || scheme == "http", url.host != nil else { return nil }
    return url
}

extension KeyedDecodingContainer {
    /// Decodes a value if present and of the right type; anything else becomes nil.
    func lenient<T: Decodable>(_ type: T.Type, _ key: Key) -> T? {
        (try? decodeIfPresent(type, forKey: key)) ?? nil
    }
}
