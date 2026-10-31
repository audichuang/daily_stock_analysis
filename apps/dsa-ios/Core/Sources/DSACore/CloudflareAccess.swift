import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

public enum ServiceOrigin {
    public static func key(_ url: URL) -> String {
        var components = URLComponents()
        components.scheme = url.scheme?.lowercased()
        components.host = url.host?.lowercased()
        components.port = url.port ?? (components.scheme == "https" ? 443 : 80)
        return components.string ?? ""
    }

    public static func same(_ lhs: URL, _ rhs: URL) -> Bool {
        lhs.user == nil && lhs.password == nil && rhs.user == nil && rhs.password == nil
            && key(lhs) == key(rhs)
    }
}

public struct AccessCredentials: Codable, Sendable, Equatable {
    public let clientID: String
    public let clientSecret: String

    public init(clientID: String, clientSecret: String) {
        self.clientID = clientID
        self.clientSecret = clientSecret
    }
}

public struct CloudflareAccess: Sendable {
    private let origin: URL
    private let credentials: AccessCredentials

    public init(origin: URL, credentials: AccessCredentials) {
        self.origin = origin
        self.credentials = credentials
    }

    func authorizing(_ original: URLRequest) -> URLRequest {
        var request = original
        let trusted = request.url.map { ServiceOrigin.same($0, origin) } ?? false
        request.setValue(trusted ? credentials.clientID : nil, forHTTPHeaderField: "CF-Access-Client-Id")
        request.setValue(trusted ? credentials.clientSecret : nil, forHTTPHeaderField: "CF-Access-Client-Secret")
        return request
    }

    public static func isLoginURL(_ url: URL) -> Bool {
        guard let host = url.host?.lowercased(), url.scheme?.lowercased() == "https" else { return false }
        return host == "cloudflareaccess.com" || host.hasSuffix(".cloudflareaccess.com")
    }
}
