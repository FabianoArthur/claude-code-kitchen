import Foundation
import Testing
@testable import KitchenCore

private struct StubTransport: UsageTransport {
    let status: Int
    let body: Data
    var headers: [String: String] = [:]
    var fails = false

    func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        if fails { throw URLError(.notConnectedToInternet) }
        return (body, HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: headers)!)
    }
}

@Suite struct UsageClientTests {
    @Test func requestCarriesOnlyTheExpectedHeaders() {
        let r = UsageEndpoint.request(token: "tok", version: "1.2.3")
        #expect(r.url?.absoluteString == "https://api.anthropic.com/api/oauth/usage")
        #expect(r.httpMethod == "GET")
        #expect(r.value(forHTTPHeaderField: "Authorization") == "Bearer tok")
        #expect(r.value(forHTTPHeaderField: "anthropic-beta") == "oauth-2025-04-20")
        #expect(r.value(forHTTPHeaderField: "User-Agent") == "Kitchen/1.2.3")
        #expect(Set(r.allHTTPHeaderFields!.keys) == ["Authorization", "anthropic-beta", "User-Agent", "Accept"])
        #expect(r.cachePolicy == .reloadIgnoringLocalAndRemoteCacheData)
        #expect(!r.httpShouldHandleCookies)
    }

    @Test func outcomes() async throws {
        let body = try Fixture.data("usage.json")
        #expect(await UsageClient(transport: StubTransport(status: 200, body: body)).fetch(token: "t", version: "1") == .ok(try UsageReport.decode(body)))
        #expect(await UsageClient(transport: StubTransport(status: 200, body: Data("<html>".utf8))).fetch(token: "t", version: "1") == .badResponse)
        #expect(await UsageClient(transport: StubTransport(status: 401, body: Data())).fetch(token: "t", version: "1") == .unauthorized)
        #expect(await UsageClient(transport: StubTransport(status: 403, body: Data())).fetch(token: "t", version: "1") == .forbidden)
        #expect(await UsageClient(transport: StubTransport(status: 429, body: Data(), headers: ["Retry-After": "1200"])).fetch(token: "t", version: "1") == .rateLimited(retryAfter: 1200))
        #expect(await UsageClient(transport: StubTransport(status: 429, body: Data())).fetch(token: "t", version: "1") == .rateLimited(retryAfter: nil))
        #expect(await UsageClient(transport: StubTransport(status: 502, body: Data())).fetch(token: "t", version: "1") == .serverError(502))
        #expect(await UsageClient(transport: StubTransport(status: 0, body: Data(), fails: true)).fetch(token: "t", version: "1") == .network)
    }

    @Test func transportRefusesRedirects() async {
        let t = EphemeralTransport()
        let task = URLSession.shared.dataTask(with: UsageEndpoint.url)
        let response = HTTPURLResponse(url: UsageEndpoint.url, statusCode: 302, httpVersion: nil, headerFields: ["Location": "https://example.com/"])!
        let next = await t.urlSession(URLSession.shared, task: task, willPerformHTTPRedirection: response, newRequest: URLRequest(url: URL(string: "https://example.com/")!))
        #expect(next == nil)
    }

    @Test func transportRefusesOtherHosts() async {
        let t = EphemeralTransport()
        await #expect(throws: URLError.self) {
            _ = try await t.send(URLRequest(url: URL(string: "https://example.com/api/oauth/usage")!))
        }
        await #expect(throws: URLError.self) {
            _ = try await t.send(URLRequest(url: URL(string: "http://api.anthropic.com/api/oauth/usage")!))
        }
    }

    @Test func sessionKeepsNothingOnDisk() {
        let c = EphemeralTransport.configuration
        #expect(c.urlCache == nil && c.httpCookieStorage == nil && c.urlCredentialStorage == nil)
        #expect(!c.httpShouldSetCookies)
    }
}
