import XCTest
@testable import DSAMarket

final class ReportNewsPresentationTests: XCTestCase {
    func testNoIntelligenceMessageIdentifiesIndependentSubscriptionSource() {
        let message = PresentationText.limitation("no_symbol_intelligence")
        XCTAssertTrue(message.contains("RSS／Atom／NewsNow"))
        XCTAssertTrue(message.contains("不代表分析未參考新聞"))
        XCTAssertEqual(PresentationText.limitation("no_reports"), "尚無這檔股票的分析報告")
        XCTAssertEqual(PresentationText.limitation("未知限制"), "未知限制")
    }
}
