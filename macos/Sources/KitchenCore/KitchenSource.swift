import Foundation

/// Where the kitchen script lives and how to run it.
public struct KitchenSource: Sendable {
    public static let pythonCandidates = ["/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"]
    public static let timeout: TimeInterval = 20

    public let python: URL
    public let script: URL
    public let environment: [String: String]?

    public init(python: URL, script: URL, environment: [String: String]? = nil) {
        self.python = python
        self.script = script
        self.environment = environment
    }

    /// Overrides (from `defaults`) first, then the usual interpreter paths and the bundled script.
    public static func resolve(pythonOverride: String?, scriptOverride: String?, bundledScript: URL?,
                               exists: (String) -> Bool = FileManager.default.isExecutableFile(atPath:),
                               environment: [String: String]? = nil) -> Result<KitchenSource, KitchenFailure> {
        let python = pythonOverride.map { [$0] } ?? pythonCandidates
        guard let pythonPath = python.first(where: exists) else { return .failure(.pythonMissing) }
        guard let script = scriptOverride.map(URL.init(fileURLWithPath:)) ?? bundledScript, exists(script.path) else {
            return .failure(.scriptMissing)
        }
        return .success(KitchenSource(python: URL(fileURLWithPath: pythonPath), script: script, environment: environment))
    }

    /// One `kitchen.py --json` run.
    public func snapshot() async -> Result<KitchenSnapshot, KitchenFailure> {
        switch await ProcessRunner.run(python, ["-I", script.path, "--json"], timeout: Self.timeout, environment: environment) {
        case .success(let output): KitchenSnapshot.interpret(output)
        case .failure(.timedOut): .failure(.timedOut)
        case .failure(.outputTooLarge): .failure(.outputTooLarge)
        case .failure(.launchFailed): .failure(.pythonMissing)
        }
    }

    /// The script's own `attach <session>` action, so the terminal choice stays in `config.json`.
    public func attach(session: String) async -> Bool {
        let result = await ProcessRunner.run(python, ["-I", script.path, "attach", session], timeout: Self.timeout,
                                             environment: environment)
        return (try? result.get().status) == 0
    }
}
