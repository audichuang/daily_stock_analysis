import XCTest
@testable import DSAMarket

final class PortfolioPresentationTests: XCTestCase {
    func testKnownPortfolioCapabilityNotesAreReadable() {
        XCTAssertEqual(PresentationText.limitation("realtime_quote_best_effort"), "報價依可用來源更新，部分可能延遲")
        XCTAssertEqual(PresentationText.limitation("fx_and_cost_basis_partial"), "損益估算受匯率與成本計算方式影響")
        XCTAssertEqual(PresentationText.limitation("sector_and_risk_metrics_limited"), "產業分類與風險指標尚未完整提供")
    }

    func testUnknownDetailsArePreservedForTroubleshooting() {
        XCTAssertEqual(PresentationText.limitation("provider_new_warning"), "provider_new_warning")
        XCTAssertEqual(PresentationText.limitation("匯率來源尚未更新"), "匯率來源尚未更新")
    }
}
