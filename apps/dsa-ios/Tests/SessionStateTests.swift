import Foundation
import XCTest
@testable import DSAMarket

@MainActor
final class SessionStateTests: XCTestCase {
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
        let taiwan = ["2330.TW", "6488.TWO", "00631L.TW", "2887A.TW", "123456.TWO"]
        let unitedStates = ["AAPL", "TSLA", "BRK-B", "BRK.B", "AAPL.US"]
        let others = ["600519", "600519.SH", "000001.SZ", "00700.HK", "HK00700", "SH600519", "2330", "AAPL.TW", "123.TW", "1234567.TW"]

        store.selectedMarket = "tw"
        for code in taiwan { XCTAssertTrue(store.isInMarket(code), code) }
        for code in unitedStates + others { XCTAssertFalse(store.isInMarket(code), code) }

        store.selectedMarket = "us"
        for code in unitedStates { XCTAssertTrue(store.isInMarket(code), code) }
        for code in taiwan + others { XCTAssertFalse(store.isInMarket(code), code) }
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
