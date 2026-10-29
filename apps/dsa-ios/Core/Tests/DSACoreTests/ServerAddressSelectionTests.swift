import XCTest
@testable import DSACore

final class ServerAddressSelectionTests: XCTestCase {
    private let old = "https://private.example.test"
    private let current = "https://public.example.test"

    func testExistingDefaultMigratesToPublicEndpoint() {
        for saved in [old, old + "/", "https://PRIVATE.example.test:443/"] {
            XCTAssertEqual(ServerAddressSelection.initial(saved: saved, currentDefault: current, previousDefault: old), current)
        }
    }

    func testCustomServerAndCustomPathStayUnchanged() {
        for saved in ["https://custom.example.test", old + "/custom", "https://private.example.test:8443", current] {
            XCTAssertEqual(ServerAddressSelection.initial(saved: saved, currentDefault: current, previousDefault: old), saved)
        }
    }

    func testExplicitChoiceAfterMigrationIsNotOverriddenAgain() {
        XCTAssertEqual(ServerAddressSelection.initial(saved: old, currentDefault: current,
                                                       previousDefault: old, lastSeenDefault: current), old)
        let newer = "https://next.example.test"
        XCTAssertEqual(ServerAddressSelection.initial(saved: current, currentDefault: newer,
                                                       previousDefault: current, lastSeenDefault: current), newer)
    }

    func testNewInstallUsesCurrentDefaultAndUnconfiguredAppStillOpens() {
        XCTAssertEqual(ServerAddressSelection.initial(saved: nil, currentDefault: current, previousDefault: old), current)
        XCTAssertEqual(ServerAddressSelection.initial(saved: nil, currentDefault: "", previousDefault: nil), "")
    }

    func testMigrationRequiresExplicitPreviousDefaultAndSafeNewURL() {
        XCTAssertEqual(ServerAddressSelection.initial(saved: old, currentDefault: current, previousDefault: nil), old)
        for invalid in ["", "http://public.example.test", "https://user:pass@public.example.test", "https://public.example.test?token=secret"] {
            XCTAssertEqual(ServerAddressSelection.initial(saved: old, currentDefault: invalid, previousDefault: old), old)
        }
    }
}
