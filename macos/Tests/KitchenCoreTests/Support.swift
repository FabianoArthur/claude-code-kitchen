import Foundation

enum Fixture {
    static func data(_ name: String) throws -> Data {
        guard let url = Bundle.module.url(forResource: name, withExtension: nil, subdirectory: "Fixtures") else {
            throw CocoaError(.fileNoSuchFile)
        }
        return try Data(contentsOf: url)
    }
}

/// 2026-01-01 00:00 UTC — the `generated_at` of the fixtures.
let fixtureNow = Date(timeIntervalSince1970: 1_767_225_600)
