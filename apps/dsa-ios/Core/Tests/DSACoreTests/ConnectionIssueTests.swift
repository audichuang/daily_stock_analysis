import Foundation
import XCTest
@testable import DSACore

final class ConnectionIssueTests: XCTestCase {
    func testWrongPasswordMapsToSameTraditionalChineseWhateverTheServerSays() {
        for message in ["密码错误", "測試密碼錯誤", "Invalid password"] {
            let issue = ConnectionIssue.from(DSAError.http(status: 401, code: "invalid_password", message: message))
            XCTAssertEqual(issue, ConnectionIssue(field: .password, message: "密碼不正確，請再試一次。"))
        }
    }

    func testRateLimitIsNotShownAsWrongPassword() {
        let issue = ConnectionIssue.from(DSAError.http(status: 429, code: "rate_limited", message: "Too many failed attempts. Please try again later."))
        XCTAssertEqual(issue, ConnectionIssue(field: .password, message: "嘗試次數過多，請稍後再試。"))
    }

    func testAccessFailureStaysOnAccessSectionWithOriginalText() {
        let issue = ConnectionIssue.from(DSAError.cloudflareAccess)
        XCTAssertEqual(issue.field, .access)
        XCTAssertTrue(issue.message.contains("Cloudflare Access 驗證失敗"), "UITest 與使用者都靠這句辨識")
    }

    func testAddressErrorsGoToAddressField() {
        XCTAssertEqual(ConnectionIssue.from(DSAError.invalidServerURL).field, .address)
        XCTAssertEqual(ConnectionIssue.from(URLError(.cannotFindHost)).field, .address)
        XCTAssertEqual(ConnectionIssue.from(URLError(.serverCertificateUntrusted)).field, .address)
    }

    func testNetworkAndUnknownServerErrorsAreGeneral() {
        XCTAssertEqual(ConnectionIssue.from(URLError(.notConnectedToInternet)).field, .general)
        XCTAssertEqual(ConnectionIssue.from(URLError(.timedOut)).field, .general)
        let issue = ConnectionIssue.from(DSAError.http(status: 500, code: "internal_error", message: "服務錯誤"))
        XCTAssertEqual(issue, ConnectionIssue(field: .general, message: "服務錯誤"))
    }

    func testExpiredSessionWithoutCodeAsksToLogInAgain() {
        XCTAssertEqual(ConnectionIssue.from(DSAError.http(status: 401, code: nil, message: "x")).field, .password)
    }

    func testAddressNormalization() {
        XCTAssertEqual(ServerAddress.normalized("  market.example.test/ ")?.absoluteString, "https://market.example.test")
        XCTAssertEqual(ServerAddress.normalized("https://market.example.test///")?.absoluteString, "https://market.example.test")
        XCTAssertEqual(ServerAddress.normalized("market.example.test:8443/base")?.absoluteString, "https://market.example.test:8443/base")
    }

    func testNormalizationDoesNotUpgradeOrWeakenAnExplicitScheme() throws {
        // 明寫 http 不偷偷改 https，交給 validateServerURL 拒絕。
        let url = try XCTUnwrap(ServerAddress.normalized("http://market.example.test"))
        XCTAssertEqual(url.scheme, "http")
    }

    func testBlankOrSpacedAddressIsRejected() {
        for raw in ["", "   ", "market example.test", "https://"] {
            XCTAssertNil(ServerAddress.normalized(raw), raw)
        }
    }
}
