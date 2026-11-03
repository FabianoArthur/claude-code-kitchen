import Foundation
import Testing
@testable import KitchenCore

@Suite struct KitchenSourceTests {
    let bundled = URL(fileURLWithPath: "/App/Kitchen.app/Contents/Resources/kitchen.py")

    @Test func picksTheFirstInstalledPythonAndTheBundledScript() throws {
        let files: Set = ["/usr/local/bin/python3", "/usr/bin/python3", bundled.path]
        let s = try KitchenSource.resolve(pythonOverride: nil, scriptOverride: nil, bundledScript: bundled, exists: files.contains).get()
        #expect(s.python.path == "/usr/local/bin/python3")
        #expect(s.script == bundled)
    }

    @Test func overridesWin() throws {
        let files: Set = ["/x/python3", "/y/kitchen.py", "/usr/bin/python3", bundled.path]
        let s = try KitchenSource.resolve(pythonOverride: "/x/python3", scriptOverride: "/y/kitchen.py", bundledScript: bundled, exists: files.contains).get()
        #expect(s.python.path == "/x/python3" && s.script.path == "/y/kitchen.py")
    }

    @Test func missingPiecesAreNamed() {
        #expect(KitchenSource.resolve(pythonOverride: nil, scriptOverride: nil, bundledScript: bundled, exists: { $0 == bundled.path }).failure == .pythonMissing)
        #expect(KitchenSource.resolve(pythonOverride: nil, scriptOverride: nil, bundledScript: nil, exists: { _ in true }).failure == .scriptMissing)
        #expect(KitchenSource.resolve(pythonOverride: "/nope", scriptOverride: nil, bundledScript: bundled, exists: { $0 != "/nope" }).failure == .pythonMissing)
    }

    @Test func runsTheRealScriptAgainstAnEmptyConfig() async throws {
        // The repo's script, a config with no globs: proves the process plumbing end to end.
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().appendingPathComponent("../../../menubar/kitchen.30s.py").standardized
        let python = KitchenSource.pythonCandidates.first { FileManager.default.isExecutableFile(atPath: $0) }
        guard let python, FileManager.default.fileExists(atPath: root.path) else { return }
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let config = dir.appendingPathComponent("config.json")
        try Data(#"{"manifests": []}"#.utf8).write(to: config)
        let source = KitchenSource(python: URL(fileURLWithPath: python), script: root,
                                   environment: ["KITCHEN_MENUBAR_CONFIG": config.path, "PATH": "/usr/bin:/bin"])
        let s = try await source.snapshot().get()
        #expect(s.globs == 0 && s.units.isEmpty)
    }
}

extension Result {
    var failure: Failure? { if case .failure(let f) = self { f } else { nil } }
}
