import Foundation
import Testing
@testable import KitchenCore

@Suite struct ProcessRunnerTests {
    @Test func capturesOutputAndStatus() async throws {
        let r = try await ProcessRunner.run(URL(fileURLWithPath: "/bin/sh"), ["-c", "echo out; echo err >&2; exit 3"], timeout: 5).get()
        #expect(r.status == 3)
        #expect(String(decoding: r.stdout, as: UTF8.self) == "out\n")
        #expect(String(decoding: r.stderr, as: UTF8.self) == "err\n")
    }

    @Test func drainsLargeOutputWithoutDeadlock() async throws {
        let r = try await ProcessRunner.run(URL(fileURLWithPath: "/bin/sh"), ["-c", "head -c 200000 /dev/zero; head -c 100000 /dev/zero >&2"], timeout: 10, stderrLimit: 1 << 20).get()
        #expect(r.stdout.count == 200_000)
        #expect(r.stderr.count == 100_000)
    }

    @Test func timesOut() async {
        let start = Date()
        let r = await ProcessRunner.run(URL(fileURLWithPath: "/bin/sleep"), ["5"], timeout: 0.5)
        #expect(r == .failure(.timedOut))
        #expect(Date().timeIntervalSince(start) < 3)
    }

    @Test func capsOutput() async {
        let r = await ProcessRunner.run(URL(fileURLWithPath: "/bin/sh"), ["-c", "head -c 5000 /dev/zero"], timeout: 5, stdoutLimit: 1000)
        #expect(r == .failure(.outputTooLarge))
    }

    @Test func missingExecutable() async {
        let r = await ProcessRunner.run(URL(fileURLWithPath: "/nonexistent/python3"), [], timeout: 1)
        #expect(r == .failure(.launchFailed))
    }
}
