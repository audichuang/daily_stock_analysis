import XCTest
@testable import DSAMarket

final class WebNavigationPolicyTests: XCTestCase {
    private let server = URL(string: "https://market.example.test")!

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
