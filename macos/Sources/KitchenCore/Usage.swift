import Foundation

/// One usage window: percent used (0–100, may exceed 100) and when it resets.
public struct UsageWindow: Equatable, Sendable, Decodable {
    public var utilization: Double?
    public var resetsAt: Date?

    public init(utilization: Double?, resetsAt: Date?) {
        self.utilization = utilization
        self.resetsAt = resetsAt
    }

    enum CodingKeys: String, CodingKey { case utilization, resetsAt }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        utilization = c.lenient(Double.self, .utilization)
        resetsAt = c.lenient(String.self, .resetsAt).flatMap(ISO8601.parse)
    }
}

/// An entry of the newer `limits` array.
public struct UsageLimit: Equatable, Sendable, Decodable {
    public var kind: String
    public var percent: Double?
    public var resetsAt: Date?
    public var modelName: String?
    public var isActive: Bool

    public init(kind: String, percent: Double?, resetsAt: Date? = nil, modelName: String? = nil, isActive: Bool = true) {
        self.kind = kind
        self.percent = percent
        self.resetsAt = resetsAt
        self.modelName = modelName
        self.isActive = isActive
    }

    enum CodingKeys: String, CodingKey { case kind, percent, resetsAt, scope, isActive }
    struct Scope: Decodable { var model: Model? }
    struct Model: Decodable { var displayName: String? }

    /// Strict on the fields it uses: a wrongly typed entry is dropped by `UsageReport`.
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        kind = try c.decode(String.self, forKey: .kind)
        percent = try c.decodeIfPresent(Double.self, forKey: .percent)
        resetsAt = c.lenient(String.self, .resetsAt).flatMap(ISO8601.parse)
        modelName = c.lenient(Scope.self, .scope)?.model?.displayName
        isActive = c.lenient(Bool.self, .isActive) ?? true
    }
}

/// The parts of `GET /api/oauth/usage` the app shows. Every field is optional; unknown keys are ignored.
public struct UsageReport: Equatable, Sendable, Decodable {
    public var fiveHour: UsageWindow?
    public var sevenDay: UsageWindow?
    public var sevenDayOpus: UsageWindow?
    public var sevenDaySonnet: UsageWindow?
    public var limits: [UsageLimit]

    public init(fiveHour: UsageWindow? = nil, sevenDay: UsageWindow? = nil, sevenDayOpus: UsageWindow? = nil,
                sevenDaySonnet: UsageWindow? = nil, limits: [UsageLimit] = []) {
        self.fiveHour = fiveHour
        self.sevenDay = sevenDay
        self.sevenDayOpus = sevenDayOpus
        self.sevenDaySonnet = sevenDaySonnet
        self.limits = limits
    }

    enum CodingKeys: String, CodingKey { case fiveHour, sevenDay, sevenDayOpus, sevenDaySonnet, limits }

    private struct Lossy<T: Decodable>: Decodable {
        var value: T?
        init(from decoder: Decoder) throws { value = try? T(from: decoder) }
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        fiveHour = c.lenient(UsageWindow.self, .fiveHour)
        sevenDay = c.lenient(UsageWindow.self, .sevenDay)
        sevenDayOpus = c.lenient(UsageWindow.self, .sevenDayOpus)
        sevenDaySonnet = c.lenient(UsageWindow.self, .sevenDaySonnet)
        limits = (c.lenient([Lossy<UsageLimit>].self, .limits) ?? []).compactMap(\.value)
    }

    public static func decode(_ data: Data) throws -> UsageReport {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(UsageReport.self, from: data)
    }

    /// Week, 5 hours, then one meter per model limit (deduplicated by name).
    public func meters() -> [UsageMeter] {
        let weekAll = limits.first { $0.kind == "weekly_all" }
        var out = [
            UsageMeter(kind: .week, label: "Week", percent: sevenDay?.utilization ?? weekAll?.percent,
                       resetsAt: sevenDay?.resetsAt ?? weekAll?.resetsAt),
            UsageMeter(kind: .fiveHour, label: "5 hours", percent: fiveHour?.utilization, resetsAt: fiveHour?.resetsAt),
        ]
        var seen = Set<String>()
        func add(_ name: String, _ percent: Double?, _ resetsAt: Date?) {
            guard !name.isEmpty, seen.insert(name.lowercased()).inserted else { return }
            out.append(UsageMeter(kind: .model, label: name, percent: percent, resetsAt: resetsAt))
        }
        for limit in limits where limit.kind == "weekly_scoped" {
            guard let name = limit.modelName else { continue }
            if !limit.isActive && (limit.percent ?? 0) == 0 { continue }
            add(name, limit.percent, limit.resetsAt)
        }
        if let w = sevenDayOpus { add("Opus", w.utilization, w.resetsAt) }
        if let w = sevenDaySonnet { add("Sonnet", w.utilization, w.resetsAt) }
        return out
    }
}

public struct UsageMeter: Equatable, Sendable, Identifiable {
    public enum Kind: Sendable { case week, fiveHour, model }
    public var kind: Kind
    public var label: String
    public var percent: Double?
    public var resetsAt: Date?

    public var id: String { label }
    public var severity: Severity { Severity(percent: percent) }
}

/// Colour band of a meter: the accent colour, orange from 80 %, red from 95 %.
public enum Severity: Sendable, Comparable {
    case normal, warning, critical

    public static let warningAt = 80.0
    public static let criticalAt = 95.0

    public init(percent: Double?) {
        guard let percent else { self = .normal; return }
        self = percent >= Self.criticalAt ? .critical : percent >= Self.warningAt ? .warning : .normal
    }
}

/// ISO 8601 with any number of fractional digits (the endpoint sends microseconds).
public enum ISO8601 {
    public static func parse(_ text: String) -> Date? {
        var text = text
        var fraction = 0.0
        if let dot = text.firstIndex(of: "."), let t = text.firstIndex(of: "T"), dot > t {
            let digits = text[text.index(after: dot)...].prefix { $0.isNumber }
            guard !digits.isEmpty else { return nil }
            fraction = Double("0." + digits) ?? 0
            text.removeSubrange(dot..<text.index(dot, offsetBy: digits.count + 1))
        }
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f.date(from: text).map { $0.addingTimeInterval(fraction) }
    }
}
