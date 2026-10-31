import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif
import XCTest
@testable import DSACore

final class CloudflareAccessTests: XCTestCase {
    private let origin = URL(string: "https://market.example.test")!
    private var access: CloudflareAccess {
        CloudflareAccess(origin: origin, credentials: AccessCredentials(clientID: "fixture-id", clientSecret: "synthetic"))
    }

    func testHeadersAreScopedToSchemeHostAndEffectivePort() {
        for address in ["https://market.example.test/api/v1/auth/status", "https://MARKET.example.test:443/tool"] {
            let request = access.authorizing(URLRequest(url: URL(string: address)!))
            XCTAssertTrue(request.value(forHTTPHeaderField: "CF-Access-Client-Id") == "fixture-id")
            XCTAssertTrue(request.value(forHTTPHeaderField: "CF-Access-Client-Secret") == "synthetic")
        }
        for address in ["https://other.example.test", "https://sub.market.example.test", "http://market.example.test",
                        "https://market.example.test:8443", "https://market.example.test.evil.test"] {
            var original = URLRequest(url: URL(string: address)!)
            original.setValue("stale", forHTTPHeaderField: "CF-Access-Client-Id")
            original.setValue("stale", forHTTPHeaderField: "CF-Access-Client-Secret")
            let request = access.authorizing(original)
            XCTAssertNil(request.value(forHTTPHeaderField: "CF-Access-Client-Id"))
            XCTAssertNil(request.value(forHTTPHeaderField: "CF-Access-Client-Secret"))
        }
    }

    func testRedirectDelegateAllowsOnlySameOriginAndReappliesHeaders() {
        let delegate = OriginRedirectDelegate(origin: origin, access: access)
        let request = delegate.redirectedRequest(URLRequest(url: origin.appendingPathComponent("next")))
        XCTAssertTrue(request?.value(forHTTPHeaderField: "CF-Access-Client-Secret") == "synthetic")
        for address in ["https://team.cloudflareaccess.com/login", "https://other.example.test",
                        "http://market.example.test", "https://market.example.test:444"] {
            XCTAssertNil(delegate.redirectedRequest(URLRequest(url: URL(string: address)!)))
        }
        let http = OriginRedirectDelegate(origin: URL(string: "http://localhost")!)
        XCTAssertNotNil(http.redirectedRequest(URLRequest(url: URL(string: "http://localhost:80/path")!)))
        XCTAssertNil(http.redirectedRequest(URLRequest(url: URL(string: "http://localhost:443/path")!)))
    }

    func testEveryClientRequestAndChangedServerUseScopedHeaders() async throws {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [AccessURLProtocol.self]
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel(); AccessURLProtocol.handler = nil }
        AccessURLProtocol.handler = { request in
            let trusted = request.url?.host == self.origin.host
            XCTAssertEqual(request.value(forHTTPHeaderField: "CF-Access-Client-Id") != nil, trusted)
            XCTAssertEqual(request.value(forHTTPHeaderField: "CF-Access-Client-Secret") != nil, trusted)
            return (200, [:], #"{"authEnabled":false,"loggedIn":false,"passwordSet":false,"ok":true}"#)
        }
        let client = try DSAClient(baseURL: origin, session: session, access: access)
        _ = try await client.authStatus()
        try await client.login(password: "synthetic-password")
        try await client.logout()
        let changed = try DSAClient(baseURL: URL(string: "https://other.example.test")!, session: session, access: access)
        _ = try await changed.authStatus()
    }

    func testOnlyAccessRedirectsAreAuthenticationFailures() async throws {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [AccessURLProtocol.self]
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel(); AccessURLProtocol.handler = nil }
        let client = try DSAClient(baseURL: origin, session: session)
        for destination in ["https://team.cloudflareaccess.com/cdn-cgi/access/login", "https://TEAM.CLOUDFLAREACCESS.COM/login"] {
            AccessURLProtocol.handler = { _ in (302, ["Location": destination], "") }
            do { _ = try await client.authStatus(); XCTFail("Access 轉址不可視為成功") }
            catch let error as DSAError {
                guard case .cloudflareAccess = error else { return XCTFail("應辨識 Access 轉址") }
                XCTAssertFalse(error.requiresLogin)
            }
        }
        for (status, destination) in [(302, "https://cloudflareaccess.com.evil.test/login"),
                                      (302, "https://fakecloudflareaccess.com/login"),
                                      (302, "https://other.example.test/login"), (302, "/login"),
                                      (403, "https://team.cloudflareaccess.com/login")] {
            AccessURLProtocol.handler = { _ in (status, ["Location": destination], "") }
            do { _ = try await client.authStatus(); XCTFail("非成功回應不可通過") }
            catch let error as DSAError {
                guard case .http(let actual, _, _) = error else { return XCTFail("一般錯誤不可誤判為 Access") }
                XCTAssertEqual(actual, status)
            }
        }
        AccessURLProtocol.handler = { _ in throw URLError(.notConnectedToInternet) }
        do { _ = try await client.authStatus(); XCTFail("離線不可通過") }
        catch { XCTAssertEqual((error as? URLError)?.code, .notConnectedToInternet) }
    }
}

private final class AccessURLProtocol: URLProtocol {
    static var handler: ((URLRequest) throws -> (Int, [String: String], String))?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        do {
            let (status, headers, body) = try Self.handler!(request)
            let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: "HTTP/1.1", headerFields: headers)!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: Data(body.utf8))
            client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
    override func stopLoading() { }
}
