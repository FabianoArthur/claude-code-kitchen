import AppKit
import KitchenCore
import Observation

/// The app's single source of truth. Two loops (kitchen script, Claude usage) run as Tasks;
/// all decisions live in the pure KitchenCore reducers.
@Observable @MainActor
public final class AppModel {
    public static let refreshChoices: [TimeInterval] = [15, 30, 60, 120]

    public private(set) var feed = KitchenFeed()
    public private(set) var panel = PanelState()
    public private(set) var usage: UsageState = .idle
    public private(set) var refreshing = false
    /// Re-read every 30 s so relative times ("3m ago") stay current.
    public private(set) var now: Date
    public private(set) var source: Result<KitchenSource, KitchenFailure>?

    public var refreshInterval: TimeInterval {
        didSet { persist(refreshInterval, "refreshInterval"); restartKitchenLoop() }
    }
    public var showWeeklyInMenuBar: Bool {
        didSet { persist(showWeeklyInMenuBar, "showWeeklyInMenuBar") }
    }
    public var showUsage: Bool {
        didSet { persist(showUsage, "showUsage"); wakeUsage() }
    }

    public let isDemo: Bool
    private let defaults: UserDefaults
    private let calendar: Calendar
    private var engine = UsageEngine()
    private var usageBusy = false
    private var kitchenTask: Task<Void, Never>?
    private var usageTask: Task<Void, Never>?
    private var clockTask: Task<Void, Never>?
    private let client = UsageClient()

    public init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        calendar = .current
        isDemo = false
        now = Date()
        let interval = defaults.double(forKey: "refreshInterval")
        refreshInterval = Self.refreshChoices.contains(interval) ? interval : 30
        showWeeklyInMenuBar = defaults.bool(forKey: "showWeeklyInMenuBar")
        showUsage = defaults.object(forKey: "showUsage") as? Bool ?? true
    }

    /// A frozen model for `--demo` and tests: no processes, no keychain, no network.
    public init(demo snapshot: KitchenSnapshot, usage: UsageState, now: Date, calendar: Calendar = .current) {
        defaults = .standard  // never written: persist() is a no-op in demo mode
        self.calendar = calendar
        isDemo = true
        self.now = now
        refreshInterval = 30
        showWeeklyInMenuBar = false
        showUsage = true
        self.usage = usage
        feed = KitchenFeed(snapshot: snapshot, refreshedAt: now)
        panel = PanelState.derive(feed, calendar: calendar)
    }

    public var weeklyPercent: Double? {
        usage.report?.meters().first?.percent
    }

    public var version: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "dev"
    }

    private func persist(_ value: Any, _ key: String) {
        guard !isDemo else { return }
        defaults.set(value, forKey: key)
    }

    // MARK: lifecycle

    public func start() {
        guard !isDemo, kitchenTask == nil else { return }
        source = KitchenSource.resolve(
            pythonOverride: defaults.string(forKey: "pythonPath").flatMap(nonEmpty),
            scriptOverride: defaults.string(forKey: "scriptPath").flatMap(nonEmpty),
            bundledScript: Bundle.main.url(forResource: "kitchen", withExtension: "py"))
        restartKitchenLoop()
        wakeUsage()
        clockTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(30))
                self?.now = Date()
            }
        }
    }

    /// Panel opened: refresh the kitchen if it's older than a few seconds; let the usage
    /// engine decide whether a request is due (it usually isn't).
    public func panelOpened() {
        guard !isDemo else { return }
        now = Date()
        if (feed.refreshedAt.map { now.timeIntervalSince($0) > 5 } ?? true) { restartKitchenLoop() }
        wakeUsage()
    }

    public func refresh() {
        guard !isDemo else { return }
        restartKitchenLoop()
        wakeUsage()
    }

    /// *Try again* on the usage card (lifts a keychain halt).
    public func retryUsage() {
        engine.retry()
        usage = engine.state
        wakeUsage()
    }

    // MARK: kitchen loop

    private func restartKitchenLoop() {
        guard !isDemo, !refreshing else { return }
        kitchenTask?.cancel()
        kitchenTask = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                await self.refreshKitchen()
                try? await Task.sleep(for: .seconds(self.refreshInterval))
            }
        }
    }

    private func refreshKitchen() async {
        guard let source else { return }
        refreshing = true
        defer { refreshing = false }
        let result: Result<KitchenSnapshot, KitchenFailure>
        switch source {
        case .failure(let failure): result = .failure(failure)
        case .success(let s): result = await s.snapshot()
        }
        now = Date()
        switch result {
        case .success(let snapshot): feed = KitchenFeed(snapshot: snapshot, refreshedAt: now)
        case .failure(let failure): feed.failure = failure
        }
        panel = PanelState.derive(feed, calendar: calendar)
    }

    // MARK: usage loop

    private func wakeUsage() {
        guard !isDemo else { return }
        usageTask?.cancel()
        usageTask = nil
        guard showUsage else { return }
        usageTask = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                switch self.engine.next(now: Date()) {
                case .halted:
                    return  // until retryUsage()
                case .wait(let until):
                    try? await Task.sleep(for: .seconds(max(1, until.timeIntervalSinceNow)))
                case .readCredential:
                    // Re-checked before every keychain read: turning usage off must stop reads,
                    // and a poll still finishing in a cancelled loop must not overlap a new one.
                    guard self.showUsage else { return }
                    if self.usageBusy {
                        try? await Task.sleep(for: .seconds(1))
                        continue
                    }
                    await self.pollUsage()
                }
            }
        }
    }

    private func pollUsage() async {
        usageBusy = true
        defer { usageBusy = false }
        let outcome = await CredentialReader.read()
        // The credential lives only in this scope: it is never assigned to a property.
        if let credential = engine.credential(outcome, now: Date()) {
            usage = engine.state
            let result = await client.fetch(token: credential.accessToken, version: version)
            engine.response(result, now: Date())
        }
        usage = engine.state
        now = Date()
    }

    // MARK: actions

    public func open(_ url: URL) {
        guard let scheme = url.scheme?.lowercased(), scheme == "https" || scheme == "http" else { return }
        NSWorkspace.shared.open(url)
        closePanel()
    }

    public func attach(_ session: String) {
        guard case .success(let source) = source else { return }
        closePanel()
        Task { _ = await source.attach(session: session) }
    }

    public func copy(_ text: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
    }

    public func openManifests() {
        guard let dir = feed.snapshot?.manifestDir, !dir.isEmpty else { return }
        var isDir: ObjCBool = false
        guard FileManager.default.fileExists(atPath: dir, isDirectory: &isDir), isDir.boolValue else { return }
        NSWorkspace.shared.open(URL(fileURLWithPath: dir, isDirectory: true))
        closePanel()
    }

    private func closePanel() {
        NSApp.keyWindow?.close()
    }
}

private func nonEmpty(_ s: String) -> String? {
    let t = s.trimmingCharacters(in: .whitespaces)
    return t.isEmpty ? nil : (t as NSString).expandingTildeInPath
}
