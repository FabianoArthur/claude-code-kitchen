import Foundation
import Testing
@testable import KitchenCore

private let secret = "sk-ant-oat01-SECRET-VALUE-never-print"
/// One hour after `fixtureNow`, in milliseconds — the unit Claude Code stores `expiresAt` in.
private let expiresAtMs = (Int(fixtureNow.timeIntervalSince1970) + 3_600) * 1_000
private let payload = #"{"claudeAiOauth":{"accessToken":"\#(secret)","refreshToken":"sk-ant-ort01-OTHER","expiresAt":\#(expiresAtMs),"scopes":["user:inference"],"subscriptionType":"max"},"mcpOAuth":{"x":{"accessToken":"mcp-other"}}}"#

@Suite struct CredentialTests {
    @Test func parsesTheClaudeCodeItem() throws {
        let c = try CredentialParser.parse(Data((payload + "\n").utf8)).get()
        #expect(c.accessToken == secret)
        #expect(c.expiresAt == Date(timeIntervalSince1970: 1_767_229_200))
    }

    @Test func parsesHexOutput() throws {
        let hex = Data(payload.utf8).map { String(format: "%02x", $0) }.joined()
        let c = try CredentialParser.parse(Data((hex + "\n").utf8)).get()
        #expect(c.accessToken == secret)
    }

    @Test func secondsAreAcceptedToo() throws {
        let c = try CredentialParser.parse(Data(#"{"claudeAiOauth":{"accessToken":"t","expiresAt":1767229200}}"#.utf8)).get()
        #expect(c.expiresAt == Date(timeIntervalSince1970: 1_767_229_200))
    }

    @Test(arguments: ["", "not json", "{}", #"{"claudeAiOauth":{}}"#, #"{"claudeAiOauth":{"accessToken":""}}"#, "[\"\(secret)\"]"])
    func malformedInputGivesAFixedError(input: String) {
        let r = CredentialParser.parse(Data(input.utf8))
        guard case .failure(let error) = r else { Issue.record("expected failure"); return }
        #expect(!String(describing: error).contains(secret))
        #expect(!error.localizedDescription.contains(secret))
    }

    @Test func theTokenNeverAppearsInDescriptions() throws {
        let c = try CredentialParser.parse(Data(payload.utf8)).get()
        var dumped = ""
        dump(c, to: &dumped)
        for text in [String(describing: c), String(reflecting: c), "\(c)", dumped, String(describing: CredentialOutcome.found(c))] {
            #expect(!text.contains(secret))
        }
    }

    @Test func fingerprintIsADigestNotTheToken() {
        let a = Credential(accessToken: secret, expiresAt: nil)
        #expect(a.fingerprint.count == 64)
        #expect(!a.fingerprint.contains(secret))
        #expect(a.fingerprint == Credential(accessToken: secret, expiresAt: nil).fingerprint)
        #expect(a.fingerprint != Credential(accessToken: "other", expiresAt: nil).fingerprint)
    }

    @Test func readerUsesFixedArguments() {
        #expect(CredentialReader.executable == URL(fileURLWithPath: "/usr/bin/security"))
        #expect(CredentialReader.arguments == ["find-generic-password", "-s", "Claude Code-credentials", "-w"])
    }

    @Test func readerMapsExitCodes() {
        let ok = ProcessOutput(status: 0, stdout: Data(payload.utf8), stderr: Data())
        #expect(CredentialReader.interpret(.success(ok)) == .found(Credential(accessToken: secret, expiresAt: nil)))
        #expect(CredentialReader.interpret(.success(.init(status: 44, stdout: Data(), stderr: Data()))) == .notFound)
        #expect(CredentialReader.interpret(.success(.init(status: 51, stdout: Data(), stderr: Data()))) == .denied)
        #expect(CredentialReader.interpret(.success(.init(status: 0, stdout: Data("junk".utf8), stderr: Data()))) == .unreadable)
        #expect(CredentialReader.interpret(.failure(.timedOut)) == .timedOut)
        #expect(CredentialReader.interpret(.failure(.launchFailed)) == .denied)
    }
}
