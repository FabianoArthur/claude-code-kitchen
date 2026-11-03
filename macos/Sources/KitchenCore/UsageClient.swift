import Foundation

public enum UsageEndpoint {
    public static let host = "api.anthropic.com"
    public static let url = URL(string: "https://api.anthropic.com/api/oauth/usage")!
    public static let beta = "oauth-2025-04-20"

    /// The only request the app ever sends with the token.
    public static func request(token: String, version: String) -> URLRequest {
        var r = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalAndRemoteCacheData, timeoutInterval: 20)
        r.httpMethod = "GET"
        r.httpShouldHandleCookies = false
        r.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        r.setValue(beta, forHTTPHeaderField: "anthropic-beta")
        r.setValue("application/json", forHTTPHeaderField: "Accept")
        r.setValue("Kitchen/\(version)", forHTTPHeaderField: "User-Agent")
        return r
    }
}

public protocol UsageTransport: Sendable {
    func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse)
}

/// Ephemeral session (no disk cache, cookies or credential store) that only talks HTTPS to
/// `api.anthropic.com` and refuses every redirect, so the bearer can't follow a 3xx elsewhere.
public final class EphemeralTransport: NSObject, UsageTransport, URLSessionTaskDelegate, Sendable {
    public static var configuration: URLSessionConfiguration {
        let c = URLSessionConfiguration.ephemeral
        c.urlCache = nil
        c.httpCookieStorage = nil
        c.urlCredentialStorage = nil
        c.httpShouldSetCookies = false
        c.requestCachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        c.timeoutIntervalForRequest = 20
        c.timeoutIntervalForResource = 30
        return c
    }

    private let session = URLSession(configuration: EphemeralTransport.configuration)

    override public init() { super.init() }

    public func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        guard let url = request.url, url.scheme == "https", url.host == UsageEndpoint.host else {
            throw URLError(.unsupportedURL)
        }
        let (data, response) = try await session.data(for: request, delegate: self)
        guard let http = response as? HTTPURLResponse else { throw URLError(.badServerResponse) }
        return (data, http)
    }

    public func urlSession(_ session: URLSession, task: URLSessionTask,
                           willPerformHTTPRedirection response: HTTPURLResponse,
                           newRequest request: URLRequest) async -> URLRequest? {
        nil
    }
}

public struct UsageClient: Sendable {
    let transport: any UsageTransport

    public init(transport: any UsageTransport = EphemeralTransport()) {
        self.transport = transport
    }

    public func fetch(token: String, version: String) async -> UsageOutcome {
        guard let (data, response) = try? await transport.send(UsageEndpoint.request(token: token, version: version)) else {
            return .network
        }
        switch response.statusCode {
        case 200: return (try? UsageReport.decode(data)).map(UsageOutcome.ok) ?? .badResponse
        case 401: return .unauthorized
        case 403: return .forbidden
        case 429: return .rateLimited(retryAfter: PollPolicy.retryAfter(response.value(forHTTPHeaderField: "Retry-After")))
        default: return .serverError(response.statusCode)
        }
    }
}
