import Foundation
import XCTest
import DSACore
import Security
@testable import DSAMarket

@MainActor
final class SessionStateTests: XCTestCase {
    func testEphemeralCookieStorageAndToolBootstrapAgainstAccessFixture() async throws {
        guard let address = ProcessInfo.processInfo.environment["DSA_ACCESS_FIXTURE_SERVER"], let url = URL(string: address) else {
            throw XCTSkip("此整合測試需由 test-ui.sh 啟動 Access fixture。")
        }
        let previous = UserDefaults.standard.object(forKey: "serverAddress")
        defer {
            try? AccessVault.remove(for: url)
            SessionVault.clear(for: url)
            UserDefaults.standard.set(previous, forKey: "serverAddress")
        }
        let store = AppStore()
        store.serverAddress = address
        SessionVault.clear(for: url)
        try store.saveAccessCredentials(clientID: "fixture-access-id", secret: "fixture-access-secret")
        await store.connect()
        XCTAssertTrue(store.needsPassword)
        await store.connect(password: "fixture-password")
        XCTAssertTrue(store.connected)
        let storage = try XCTUnwrap(store.session?.configuration.httpCookieStorage)
        let accessCookie = try XCTUnwrap(storage.cookies(for: url)?.first { $0.name == "CF_Authorization" })
        XCTAssertTrue(accessCookie.isHTTPOnly)
        storage.deleteCookie(accessCookie)
        XCTAssertFalse((storage.cookies(for: url) ?? []).contains { $0.name == "CF_Authorization" })
        let cookies = try await store.toolCookies()
        XCTAssertEqual(Set(cookies.map(\.name)), Set(["dsa_session", "CF_Authorization"]))
        XCTAssertTrue((storage.cookies(for: url) ?? []).contains { $0.name == "CF_Authorization" })
        await store.logout()
    }

    func testAccessVaultUsesCanonicalOriginAndDeviceOnlyAccessibility() throws {
        let url = URL(string: "https://access-\(UUID().uuidString.lowercased()).example.test/path")!
        let equivalent = URL(string: "https://\(url.host!.uppercased()):443/other")!
        defer { try? AccessVault.remove(for: url) }
        let credentials = AccessCredentials(clientID: "fixture-id", clientSecret: "synthetic")
        try AccessVault.save(credentials, for: url)
        XCTAssertTrue(try AccessVault.load(for: equivalent) == credentials)
        XCTAssertNil(try AccessVault.load(for: URL(string: "http://\(url.host!)")!))
        XCTAssertNil(try AccessVault.load(for: URL(string: "https://\(url.host!):8443")!))
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                  kSecAttrService as String: Bundle.main.bundleIdentifier! + ".cloudflare-access",
                                  kSecAttrAccount as String: ServiceOrigin.key(url),
                                  kSecReturnAttributes as String: true]
        var result: CFTypeRef?
        XCTAssertEqual(SecItemCopyMatching(query as CFDictionary, &result), errSecSuccess)
        let attributes = try XCTUnwrap(result as? [String: Any])
        XCTAssertEqual(attributes[kSecAttrAccessible as String] as? String, kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly as String)
        try AccessVault.save(AccessCredentials(clientID: "new-id", clientSecret: "replacement"), for: equivalent)
        XCTAssertTrue(try AccessVault.load(for: url)?.clientID == "new-id")
    }

    func testLogoutAndOfflineKeepAccessCredentialsButChangedServerDoesNotReceiveThem() async throws {
        let url = URL(string: "https://access-\(UUID().uuidString.lowercased()).example.test")!
        let other = URL(string: "https://other-\(UUID().uuidString.lowercased()).example.test")!
        let previous = UserDefaults.standard.object(forKey: "serverAddress")
        defer {
            try? AccessVault.remove(for: url)
            SessionVault.clear(for: url); SessionVault.clear(for: other)
            SessionStateURLProtocol.handler = nil
            UserDefaults.standard.set(previous, forKey: "serverAddress")
        }
        let store = AppStore(configurationFactory: stubConfiguration)
        store.serverAddress = url.absoluteString
        try store.saveAccessCredentials(clientID: "fixture-id", secret: "synthetic")
        SessionStateURLProtocol.handler = { request in
            XCTAssertTrue(request.value(forHTTPHeaderField: "CF-Access-Client-Secret") == "synthetic")
            throw URLError(.notConnectedToInternet)
        }
        await store.connect()
        XCTAssertFalse(store.needsPassword)
        XCTAssertNotNil(store.connectionError)
        await store.logout()
        XCTAssertNotNil(try AccessVault.load(for: url))
        store.serverAddress = other.absoluteString
        SessionStateURLProtocol.handler = { request in
            XCTAssertNil(request.value(forHTTPHeaderField: "CF-Access-Client-Id"))
            XCTAssertNil(request.value(forHTTPHeaderField: "CF-Access-Client-Secret"))
            return (200, #"{"authEnabled":true,"loggedIn":false,"passwordSet":true}"#)
        }
        await store.connect()
        XCTAssertTrue(store.needsPassword)
        await store.logout()
    }

    func testTimestampWithExplicitZoneUsesDeviceTimeForBothISOFormats() {
        let taipei = TimeZone(secondsFromGMT: 8 * 3600)!
        let utc = TimeZone(secondsFromGMT: 0)!
        XCTAssertEqual(DisplayFormat.time("2026-10-29T05:14:08.844310+00:00", timeZone: taipei),
                       "2026/10/29 13:14 GMT+8")
        XCTAssertEqual(DisplayFormat.time("2026-10-29T05:14:08+00:00", timeZone: taipei),
                       "2026/10/29 13:14 GMT+8")
        XCTAssertEqual(DisplayFormat.time("2026-10-29T13:14:08+08:00", timeZone: utc),
                       "2026/10/29 05:14 GMT")
    }

    func testTimestampWithoutZoneKeepsOriginalClockAndDate() {
        let taipei = TimeZone(secondsFromGMT: 8 * 3600)!
        XCTAssertEqual(DisplayFormat.time("2026-10-29T05:14:08.844310", timeZone: taipei),
                       "2026-10-29 05:14:08.844310")
        XCTAssertEqual(DisplayFormat.time("2026-10-29T05:14:08", timeZone: taipei), "2026-10-29 05:14:08")
        XCTAssertEqual(DisplayFormat.time("2026-10-29", timeZone: taipei), "2026-10-29")
    }

    func testFirstTimeSetupIsDistinctFromPasswordLoginAndDisabledAuthentication() async {
        let url = URL(string: "https://setup-\(UUID().uuidString.lowercased()).example.test")!
        let previousAddress = UserDefaults.standard.object(forKey: "serverAddress")
        defer {
            SessionStateURLProtocol.handler = nil
            SessionVault.clear(for: url)
            UserDefaults.standard.set(previousAddress, forKey: "serverAddress")
        }
        var authStatus = #"{"authEnabled":true,"loggedIn":false,"passwordSet":false}"#
        SessionStateURLProtocol.handler = { request in
            switch request.url?.path {
            case "/api/v1/auth/status": return (200, authStatus)
            case "/api/v1/stocks/watchlist": return (200, #"{"stock_codes":[]}"#)
            case "/api/v1/stocks/indices": return (200, #"{"items":[]}"#)
            case "/api/v1/history": return (200, #"{"total":0,"page":1,"limit":50,"items":[]}"#)
            default: throw URLError(.unsupportedURL)
            }
        }
        let store = AppStore(configurationFactory: stubConfiguration)
        store.serverAddress = url.absoluteString
        await store.connect()
        XCTAssertFalse(store.connected)
        XCTAssertFalse(store.needsPassword)
        XCTAssertEqual(store.connectionError, "請先在網頁完成管理員密碼設定，再連接 App。")

        authStatus = #"{"authEnabled":true,"loggedIn":false,"passwordSet":true}"#
        await store.connect()
        XCTAssertFalse(store.connected)
        XCTAssertTrue(store.needsPassword)
        XCTAssertNil(store.connectionError)

        authStatus = #"{"authEnabled":false,"loggedIn":false,"passwordSet":false}"#
        await store.connect()
        XCTAssertTrue(store.connected)
        XCTAssertFalse(store.needsPassword)
        XCTAssertNil(store.connectionError)
        await store.logout()
    }

    func testWrongPasswordMapsToPasswordFieldAndAddressIsNormalized() async throws {
        let host = "session-n-\(UUID().uuidString.lowercased()).example.test"
        let url = URL(string: "https://\(host)")!
        let previousAddress = UserDefaults.standard.object(forKey: "serverAddress")
        defer {
            SessionStateURLProtocol.handler = nil
            SessionVault.clear(for: url)
            UserDefaults.standard.set(previousAddress, forKey: "serverAddress")
        }
        SessionStateURLProtocol.handler = { request in
            switch request.url?.path {
            case "/api/v1/auth/status": return (200, #"{"authEnabled":true,"loggedIn":false,"passwordSet":true}"#)
            case "/api/v1/auth/login": return (401, #"{"error":"invalid_password","message":"密码错误"}"#)
            default: throw URLError(.unsupportedURL)
            }
        }
        let store = AppStore(configurationFactory: stubConfiguration)
        store.serverAddress = "  \(host)/ "
        await store.connect()
        XCTAssertEqual(store.baseURL, url)
        XCTAssertEqual(store.serverAddress, url.absoluteString)
        XCTAssertTrue(store.needsPassword)

        await store.connect(password: "wrong")
        XCTAssertEqual(store.connectionIssue?.field, .password)
        XCTAssertEqual(store.connectionError, "密碼不正確，請再試一次。")
        XCTAssertTrue(store.needsPassword, "打錯留在登入表單，不退回改網址")
        await store.logout()
    }

    func testCancelledConnectionShowsNoErrorAndLeavesStartup() async throws {
        let url = URL(string: "https://session-c-\(UUID().uuidString.lowercased()).example.test")!
        defer { SessionStateURLProtocol.handler = nil }
        SessionStateURLProtocol.handler = { _ in
            Thread.sleep(forTimeInterval: 1)
            return (200, #"{"authEnabled":true,"loggedIn":false,"passwordSet":true}"#)
        }
        let store = AppStore(configurationFactory: stubConfiguration)
        store.serverAddress = url.absoluteString
        store.startingUp = true
        let pending = Task { await store.submitConnection() }
        try await Task.sleep(for: .milliseconds(100))
        store.cancelConnecting()
        await pending.value
        XCTAssertFalse(store.startingUp)
        XCTAssertNil(store.connectionIssue, "取消不是連線失敗")
        XCTAssertFalse(store.connecting)
        XCTAssertFalse(store.connected)
        await store.logout()
    }

    func testInvalidReplacementCanReturnToOriginalServerAndThenConnectToAnotherServer() async throws {
        let serverA = URL(string: "https://session-a-\(UUID().uuidString.lowercased()).example.test")!
        let serverB = URL(string: "https://session-b-\(UUID().uuidString.lowercased()).example.test")!
        let previousAddress = UserDefaults.standard.object(forKey: "serverAddress")
        defer {
            SessionStateURLProtocol.handler = nil
            SessionVault.clear(for: serverA)
            SessionVault.clear(for: serverB)
            UserDefaults.standard.set(previousAddress, forKey: "serverAddress")
        }
        SessionStateURLProtocol.handler = { request in
            switch request.url?.path {
            case "/api/v1/auth/status":
                let loggedIn = request.url?.host == serverB.host
                return (200, "{\"authEnabled\":true,\"loggedIn\":\(loggedIn),\"passwordSet\":true}")
            case "/api/v1/stocks/watchlist": return (200, #"{"stock_codes":[]}"#)
            case "/api/v1/stocks/indices": return (200, #"{"items":[]}"#)
            case "/api/v1/history": return (200, #"{"total":0,"page":1,"limit":50,"items":[]}"#)
            default: throw URLError(.unsupportedURL)
            }
        }
        let store = AppStore(configurationFactory: stubConfiguration)
        store.serverAddress = serverA.absoluteString
        await store.connect()
        XCTAssertTrue(store.needsPassword)
        let originalSession = try XCTUnwrap(store.session)

        store.serverAddress = "http://invalid.example.test"
        await store.connect()
        XCTAssertNotNil(store.connectionError)
        XCTAssertEqual(store.baseURL, serverA)
        XCTAssertTrue(store.session === originalSession)

        store.serverAddress = serverA.absoluteString
        await store.connect()
        XCTAssertNil(store.connectionError)
        XCTAssertTrue(store.needsPassword)
        XCTAssertTrue(store.session === originalSession)

        store.serverAddress = serverB.absoluteString
        await store.connect()
        XCTAssertNil(store.connectionError)
        XCTAssertTrue(store.connected)
        XCTAssertFalse(store.needsPassword)
        XCTAssertEqual(store.baseURL, serverB)
        XCTAssertFalse(store.session === originalSession)
        XCTAssertNotNil(store.refreshedAt)
        await store.logout()
    }

    func testMarketClassificationSeparatesTaiwanUSAndOtherMarkets() {
        let store = AppStore()
        let taiwan = ["2330.TW", "6488.TWO", "00631L.TW", "2887A.TW", "123456.TWO", "2330.tw", "00631l.two"]
        let unitedStates = ["AAPL", "TSLA", "BRK-B", "BRK.B", "AAPL.US", "aapl", "brk.b", "aapl.us"]
        let others = ["600519", "600519.SH", "000001.SZ", "00700.HK", "HK00700", "SH600519", "2330", "AAPL.TW", "123.TW", "1234567.TW", "ſ", "K", "２３３０.tw", "7203.T"]

        store.selectedMarket = "tw"
        for code in taiwan { XCTAssertTrue(store.isInMarket(code), code) }
        for code in unitedStates + others { XCTAssertFalse(store.isInMarket(code), code) }

        store.selectedMarket = "us"
        for code in unitedStates { XCTAssertTrue(store.isInMarket(code), code) }
        for code in taiwan + others { XCTAssertFalse(store.isInMarket(code), code) }
    }

    func testNewPublicEndpointDoesNotInheritPrivateEndpointCookie() throws {
        let suffix = UUID().uuidString.lowercased()
        let oldURL = URL(string: "https://private-\(suffix).example.test")!
        let newURL = URL(string: "https://public-\(suffix).example.test")!
        defer { SessionVault.clear(for: oldURL); SessionVault.clear(for: newURL) }
        let original = try XCTUnwrap(URLSessionConfiguration.ephemeral.httpCookieStorage)
        let destination = try XCTUnwrap(URLSessionConfiguration.ephemeral.httpCookieStorage)
        let cookie = try XCTUnwrap(HTTPCookie.cookies(withResponseHeaderFields: [
            "Set-Cookie": "dsa_session=test-private-token; Path=/; HttpOnly; Secure; SameSite=Lax"
        ], for: oldURL).first)
        original.setCookie(cookie)
        try SessionVault.save(original, for: oldURL)
        SessionVault.restore(into: destination, for: newURL)
        XCTAssertTrue((destination.cookies ?? []).isEmpty)
        SessionVault.restore(into: destination, for: oldURL)
        XCTAssertEqual(destination.cookies(for: oldURL)?.first?.value, "test-private-token")
    }

    func testVaultRoundTripPreservesHTTPOnlyAndSameSite() throws {
        for sameSite in ["Lax", "Strict", "None"] {
            let url = URL(string: "https://vault-\(UUID().uuidString.lowercased()).example.test")!
            defer { SessionVault.clear(for: url) }
            let source = try XCTUnwrap(URLSessionConfiguration.ephemeral.httpCookieStorage)
            let destination = try XCTUnwrap(URLSessionConfiguration.ephemeral.httpCookieStorage)
            let cookie = try XCTUnwrap(HTTPCookie.cookies(withResponseHeaderFields: [
                "Set-Cookie": "dsa_session=test-token; Max-Age=3600; Path=/; HttpOnly; Secure; SameSite=\(sameSite)"
            ], for: url).first)
            source.setCookie(cookie)

            try SessionVault.save(source, for: url)
            SessionVault.restore(into: destination, for: url)

            let restored = try XCTUnwrap(destination.cookies(for: url)?.first)
            XCTAssertEqual(restored.value, "test-token")
            XCTAssertTrue(restored.isHTTPOnly)
            XCTAssertTrue(restored.isSecure)
            XCTAssertEqual(restored.properties?[HTTPCookiePropertyKey(rawValue: "SameSite")] as? String,
                           sameSite.lowercased())
        }
    }

    func testVaultDoesNotInventCookieSecurityAttributes() throws {
        let url = URL(string: "https://vault-\(UUID().uuidString.lowercased()).example.test")!
        defer { SessionVault.clear(for: url) }
        let source = try XCTUnwrap(URLSessionConfiguration.ephemeral.httpCookieStorage)
        let destination = try XCTUnwrap(URLSessionConfiguration.ephemeral.httpCookieStorage)
        let cookie = try XCTUnwrap(HTTPCookie.cookies(withResponseHeaderFields: [
            "Set-Cookie": "dsa_session=test-token; Max-Age=3600; Path=/"
        ], for: url).first)
        source.setCookie(cookie)

        try SessionVault.save(source, for: url)
        SessionVault.restore(into: destination, for: url)

        let restored = try XCTUnwrap(destination.cookies(for: url)?.first)
        XCTAssertFalse(restored.isHTTPOnly)
        XCTAssertFalse(restored.isSecure)
        XCTAssertNil(restored.properties?[HTTPCookiePropertyKey(rawValue: "SameSite")])
    }
}

private func stubConfiguration() -> URLSessionConfiguration {
    let configuration = URLSessionConfiguration.ephemeral
    configuration.protocolClasses = [SessionStateURLProtocol.self]
    return configuration
}

private final class SessionStateURLProtocol: URLProtocol {
    static var handler: ((URLRequest) throws -> (Int, String))?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        do {
            let handler = try XCTUnwrap(Self.handler)
            let (status, body) = try handler(request)
            let response = try XCTUnwrap(HTTPURLResponse(url: try XCTUnwrap(request.url), statusCode: status,
                                                       httpVersion: "HTTP/1.1", headerFields: ["Content-Type": "application/json"]))
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: Data(body.utf8))
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() { }
}
