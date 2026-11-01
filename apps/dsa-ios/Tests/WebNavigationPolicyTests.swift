import XCTest
import WebKit
@testable import DSAMarket

final class WebNavigationPolicyTests: XCTestCase {
    private let server = URL(string: "https://market.example.test")!

    func testEmbeddedToolURLAppendsParameterAndKeepsExistingQuery() throws {
        XCTAssertEqual(WebNavigationPolicy.embeddedToolURL(path: "/alerts", baseURL: server)?.absoluteString,
                       "https://market.example.test/alerts?embed=ios")
        XCTAssertEqual(WebNavigationPolicy.embeddedToolURL(path: "/api/v1/stocks/2330.TW/dossier?theme=dark", baseURL: server)?.absoluteString,
                       "https://market.example.test/api/v1/stocks/2330.TW/dossier?theme=dark&embed=ios")
        XCTAssertEqual(WebNavigationPolicy.embeddedToolURL(path: "/alerts?embed=ios", baseURL: server)?.absoluteString,
                       "https://market.example.test/alerts?embed=ios")
    }

    func testEmbedParameterDoesNotChangeNavigationPolicy() throws {
        let embedded = try XCTUnwrap(WebNavigationPolicy.embeddedToolURL(path: "/alerts", baseURL: server))
        XCTAssertTrue(WebNavigationPolicy.sameOrigin(embedded, server))
        XCTAssertEqual(WebNavigationPolicy.action(url: embedded, baseURL: server, sourceOrigin: server,
                                                  shouldDownload: false, userLink: false), .allow)
        let foreign = try XCTUnwrap(WebNavigationPolicy.embeddedToolURL(path: "https://foreign.example.test/alerts", baseURL: server))
        XCTAssertFalse(WebNavigationPolicy.sameOrigin(foreign, server))
    }

    func testDownloadInterruptionIsIgnoredOnlyWhileADownloadIsStarting() {
        let interrupted = NSError(domain: "WebKitErrorDomain", code: 102)
        XCTAssertTrue(WebNavigationPolicy.isDownloadInterruption(interrupted, downloadStarting: true))
        XCTAssertFalse(WebNavigationPolicy.isDownloadInterruption(interrupted, downloadStarting: false))
        XCTAssertFalse(WebNavigationPolicy.isDownloadInterruption(
            NSError(domain: NSURLErrorDomain, code: NSURLErrorNotConnectedToInternet), downloadStarting: true))
    }

    func testPageLoadMessageIsTraditionalChineseAndSeparatesNetworkFailures() {
        XCTAssertEqual(WebNavigationPolicy.pageLoadMessage(for: NSError(domain: NSURLErrorDomain, code: NSURLErrorNotConnectedToInternet)),
                       "無法連線到分析服務，請確認網路後重試。")
        XCTAssertEqual(WebNavigationPolicy.pageLoadMessage(for: NSError(domain: "WebKitErrorDomain", code: 102)),
                       "工具頁載入失敗，請重試。")
    }

    @MainActor func testLogoutDiscardsToolWebData() async {
        let store = AppStore()
        let previous = store.toolWebDataStore
        await store.logout()
        XCTAssertFalse(store.toolWebDataStore === previous, "登出後新的工具頁不能沿用舊的 cookie")
    }

    func testAccessPolicyCancellationPreservesSpecificErrorWithoutHidingRealFailures() {
        let interrupted = NSError(domain: "WebKitErrorDomain", code: 102)
        XCTAssertTrue(WebNavigationPolicy.preservesAccessError(interrupted, blockedAccessRedirect: true))
        XCTAssertFalse(WebNavigationPolicy.preservesAccessError(interrupted, blockedAccessRedirect: false))
        for error in [NSError(domain: NSURLErrorDomain, code: NSURLErrorNotConnectedToInternet),
                      NSError(domain: "WebKitErrorDomain", code: 101),
                      NSError(domain: NSURLErrorDomain, code: 102)] {
            XCTAssertFalse(WebNavigationPolicy.preservesAccessError(error, blockedAccessRedirect: true))
        }
    }

    func testEmptyInitialFrameOriginIsUntrustedWithoutCrashing() {
        let opaqueOrigin = WebNavigationPolicy.sourceOrigin(protocolValue: "", host: "", port: 0)
        XCTAssertNil(opaqueOrigin)
        let blob = URL(string: "blob:https://market.example.test/id")!
        XCTAssertEqual(WebNavigationPolicy.action(url: blob, baseURL: server, sourceOrigin: opaqueOrigin,
                                                  shouldDownload: true, userLink: true), .cancel)
    }

    func testValidInitialFrameOriginStillSupportsOwnBlobButNotForeignFrame() throws {
        let source = try XCTUnwrap(WebNavigationPolicy.sourceOrigin(protocolValue: "https", host: "market.example.test", port: 443))
        let blob = URL(string: "blob:https://market.example.test/id")!
        XCTAssertEqual(WebNavigationPolicy.action(url: blob, baseURL: server, sourceOrigin: source,
                                                  shouldDownload: true, userLink: false), .download)
        let foreign = try XCTUnwrap(WebNavigationPolicy.sourceOrigin(protocolValue: "https", host: "foreign.example.test", port: 443))
        XCTAssertEqual(WebNavigationPolicy.action(url: blob, baseURL: server, sourceOrigin: foreign,
                                                  shouldDownload: true, userLink: true), .cancel)
    }

    func testDefaultSecurityOriginPortZeroMatchesHTTPS443() throws {
        let source = try XCTUnwrap(WebNavigationPolicy.sourceOrigin(protocolValue: "https", host: "market.example.test", port: 0))
        XCTAssertNil(source.port)
        XCTAssertTrue(WebNavigationPolicy.sameOrigin(source, URL(string: "https://market.example.test:443")!))
        XCTAssertEqual(WebNavigationPolicy.action(url: URL(string: "blob:https://market.example.test/id")!,
                                                  baseURL: server, sourceOrigin: source, shouldDownload: true, userLink: false), .download)
    }

    func testOwnBlobDownloadKeepsCreatorAndInitiatingFrameOrigin() {
        let blob = URL(string: "blob:https://market.example.test/export-uuid")!
        XCTAssertEqual(WebNavigationPolicy.action(url: blob, baseURL: server, sourceOrigin: server, shouldDownload: true, userLink: false), .download)
        XCTAssertTrue(WebNavigationPolicy.trustedDownload(blob, baseURL: server))
        XCTAssertEqual(WebNavigationPolicy.action(url: blob, baseURL: server, sourceOrigin: URL(string: "https://foreign.example.test"), shouldDownload: true, userLink: true), .cancel)
        XCTAssertEqual(WebNavigationPolicy.action(url: blob, baseURL: server, sourceOrigin: nil, shouldDownload: true, userLink: true), .cancel)
    }

    func testForeignAndOpaqueBlobNeverDownload() {
        for address in ["blob:https://foreign.example.test/id", "blob:null/id", "blob:https://market.example.test.evil.test/id", "blob:http://market.example.test/id", "blob:https://market.example.test:8443/id"] {
            let blob = URL(string: address)!
            XCTAssertFalse(WebNavigationPolicy.trustedDownload(blob, baseURL: server), address)
            XCTAssertEqual(WebNavigationPolicy.action(url: blob, baseURL: server, sourceOrigin: server, shouldDownload: true, userLink: true), .cancel, address)
        }
    }

    func testNormalNavigationAndHTTPDownloadRemainDistinct() {
        let document = URL(string: "https://market.example.test/api/v1/export")!
        XCTAssertEqual(WebNavigationPolicy.action(url: document, baseURL: server, sourceOrigin: server, shouldDownload: true, userLink: true), .download)
        XCTAssertEqual(WebNavigationPolicy.action(url: document, baseURL: server, sourceOrigin: nil, shouldDownload: false, userLink: false), .allow)
        let news = URL(string: "https://news.example.test/story")!
        XCTAssertEqual(WebNavigationPolicy.action(url: news, baseURL: server, sourceOrigin: server, shouldDownload: false, userLink: true), .external)
        XCTAssertEqual(WebNavigationPolicy.action(url: news, baseURL: server, sourceOrigin: server, shouldDownload: false, userLink: false), .cancel)
        XCTAssertFalse(WebNavigationPolicy.sameOrigin(URL(string: "https://market.example.test:8443")!, server))
        XCTAssertTrue(WebNavigationPolicy.sameOrigin(URL(string: "https://market.example.test:443")!, server))
    }

    func testDownloadFilenameCannotEscapeUniqueDirectory() {
        XCTAssertEqual(WebNavigationPolicy.safeFilename("../../settings.json"), "settings.json")
        XCTAssertEqual(WebNavigationPolicy.safeFilename("..\\..\\settings.json"), "settings.json")
        XCTAssertEqual(WebNavigationPolicy.safeFilename(".env"), "env")
        XCTAssertEqual(WebNavigationPolicy.safeFilename(".."), "export")
        XCTAssertEqual(WebNavigationPolicy.safeFilename("報告.json"), "報告.json")
        XCTAssertLessThanOrEqual(WebNavigationPolicy.safeFilename(String(repeating: "🧪", count: 300)).utf8.count, 240)
    }
}
