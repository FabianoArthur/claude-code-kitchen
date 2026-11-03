import Foundation

/// What the app knows about the kitchen: the last good snapshot (if any), when it was taken,
/// and the failure of the latest refresh (if it failed).
public struct KitchenFeed: Equatable, Sendable {
    public var snapshot: KitchenSnapshot?
    public var refreshedAt: Date?
    public var failure: KitchenFailure?

    public init(snapshot: KitchenSnapshot? = nil, refreshedAt: Date? = nil, failure: KitchenFailure? = nil) {
        self.snapshot = snapshot
        self.refreshedAt = refreshedAt
        self.failure = failure
    }
}

public enum PanelBody: Equatable, Sendable {
    case loading
    case noGlobs
    case noRows
    case units
    case failed(String)
}

public enum PanelBanner: Equatable, Sendable, Identifiable {
    case stale(String)
    case tmux(String)
    case warning(String)

    public var text: String {
        switch self {
        case .stale(let t), .tmux(let t), .warning(let t): t
        }
    }

    public var id: String { text }
}

public struct UnitSection: Equatable, Sendable, Identifiable {
    public var status: UnitStatus
    public var units: [KitchenUnit]
    /// Done units older than a day: folded into a closed *Earlier* disclosure.
    public var earlier: [KitchenUnit]

    public var id: UnitStatus { status }
    public var title: String { status.title }
    public var count: Int { units.count + earlier.count }
}

public struct MenuBarSummary: Equatable, Sendable {
    public var symbol: String
    public var text: String
    public var accessibilityLabel: String

    public init(symbol: String, text: String, accessibilityLabel: String) {
        self.symbol = symbol
        self.text = text
        self.accessibilityLabel = accessibilityLabel
    }
}

/// Everything the panel and the menu-bar label render, derived purely from a `KitchenFeed`.
public struct PanelState: Equatable, Sendable {
    public static let sectionOrder: [UnitStatus] = [.waiting, .running, .queued, .done, .aborted, .unknown]

    public var body: PanelBody = .loading
    public var banners: [PanelBanner] = []
    public var attention: [Divergence] = []
    public var sections: [UnitSection] = []
    public var harvested = 0
    public var summary = "Loading…"
    /// Clock time of the last good refresh ("14:02").
    public var updated: String?
    public var menuBar = MenuBarSummary(symbol: "flame", text: "", accessibilityLabel: "Kitchen: loading")

    public init() {}

    public static func derive(_ feed: KitchenFeed, calendar: Calendar = .current) -> PanelState {
        var p = PanelState()
        guard let s = feed.snapshot else {
            if let failure = feed.failure {
                p.body = .failed(failure.message)
                p.summary = "Couldn't read the kitchen"
                p.menuBar = MenuBarSummary(symbol: "flame", text: "", accessibilityLabel: "Kitchen: couldn't read the kitchen")
            }
            return p
        }
        p.updated = feed.refreshedAt.map { Formatting.clock($0, calendar: calendar) }
        if feed.failure != nil {
            p.banners.append(.stale("Couldn't refresh — showing \(p.updated ?? "older data")"))
        }
        if !s.tmuxReason.isEmpty { p.banners.append(.tmux("tmux unavailable — showing manifests only")) }
        if let warning = s.warning, !warning.isEmpty { p.banners.append(.warning(warning)) }

        p.attention = s.divergences
        p.harvested = s.count(.harvested)
        p.sections = sectionOrder.compactMap { status in
            let group = s.units.filter { $0.status == status }
            guard !group.isEmpty else { return nil }
            let fold = status == .done
            return UnitSection(status: status, units: group.filter { !fold || $0.recent },
                               earlier: fold ? group.filter { !$0.recent } : [])
        }
        if s.globs == 0 { p.body = .noGlobs }
        else if p.sections.isEmpty && p.attention.isEmpty { p.body = .noRows }
        else { p.body = .units }

        let running = s.count(.running), waiting = s.count(.waiting), diverged = s.divergences.count
        var parts: [String] = []
        if running > 0 { parts.append("\(running) running") }
        if waiting > 0 { parts.append("\(waiting) waiting on you") }
        if diverged > 0 { parts.append(diverged == 1 ? "1 needs attention" : "\(diverged) need attention") }
        let queued = s.count(.queued)
        p.summary = parts.isEmpty ? (queued > 0 ? "\(queued) queued" : "Idle") : parts.joined(separator: " · ")

        let symbol = diverged > 0 ? "exclamationmark.triangle.fill" : (running + waiting > 0 ? "flame.fill" : "flame")
        let text = [running > 0 ? "▸\(running)" : nil, waiting > 0 ? "!\(waiting)" : nil].compactMap(\.self).joined(separator: " ")
        p.menuBar = MenuBarSummary(symbol: symbol, text: text,
                                   accessibilityLabel: "Kitchen: " + (parts.isEmpty ? "idle" : parts.joined(separator: ", ")))
        return p
    }
}
