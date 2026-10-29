import XCTest
@testable import DSACore

final class TaskRecoveryTests: XCTestCase {
    func testOnlyMissingTaskAllowsStartingAnotherAnalysis() {
        XCTAssertTrue(DSAError.http(status: 404, code: "not_found", message: "expired").isNotFound)
        for status in [401, 403, 409, 429, 500, 503] {
            XCTAssertFalse(DSAError.http(status: status, code: nil, message: "temporary").isNotFound)
        }
        XCTAssertFalse(DSAError.invalidResponse.isNotFound)
    }
}
