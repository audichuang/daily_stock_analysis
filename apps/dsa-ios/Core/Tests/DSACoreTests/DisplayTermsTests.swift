import XCTest
@testable import DSACore

final class DisplayTermsTests: XCTestCase {
    func testActionEnumWinsOverStoredLabel() {
        XCTAssertEqual(DecisionAction.displayText(action: "reduce", label: "減倉"), "減碼")
        XCTAssertEqual(DecisionAction.displayText(action: "sell", label: "買入"), "賣出")
        XCTAssertEqual(DecisionAction.displayText(action: "HOLD", label: nil), "續抱")
    }

    func testLegacyLabelsWithoutEnumUseGlossary() {
        XCTAssertEqual(DecisionAction.displayText(action: nil, label: "減倉"), "減碼")
        XCTAssertEqual(DecisionAction.displayText(action: nil, label: "减仓"), "減碼")
        XCTAssertEqual(DecisionAction.displayText(action: nil, label: "買入"), "買進")
        XCTAssertEqual(DecisionAction.displayText(action: nil, label: "持有"), "續抱")
        // 第 2 批 B04 開始存的新詞也要認得。
        XCTAssertEqual(DecisionAction.resolve(action: nil, label: "減碼"), .reduce)
        XCTAssertEqual(DecisionAction.resolve(action: nil, label: "買進"), .buy)
    }

    func testAliasMatchesWholeLabelOnly() {
        XCTAssertNil(DecisionAction.resolve(action: nil, label: "不建議買進"))
        XCTAssertEqual(DecisionAction.displayText(action: nil, label: "暫不減碼"), "暫不減碼")
    }

    func testUnknownActionFallsBackToLabelThenAdvice() {
        XCTAssertEqual(DecisionAction.displayText(action: "new_action", label: "分批布局"), "分批布局")
        XCTAssertEqual(DecisionAction.displayText(action: nil, label: " ", advice: "等待回測"), "等待回測")
        XCTAssertEqual(DecisionAction.displayText(action: nil, label: nil, advice: "減倉"), "減碼")
        XCTAssertNil(DecisionAction.displayText(action: nil, label: nil))
    }

    func testEveryActionHasGlossaryLabel() {
        let labels = DecisionAction.allCases.map(\.displayLabel)
        XCTAssertEqual(Set(labels), ["買進", "加碼", "續抱", "觀望", "迴避", "減碼", "賣出", "警報"])
    }

    func testNegativeNumbersUseUnicodeMinus() {
        XCTAssertEqual(DisplayNumber.minusSign, "\u{2212}")
        XCTAssertEqual(DisplayNumber.number(-1234.5), "\u{2212}1,234.5")
        XCTAssertEqual(DisplayNumber.percent(-1.5), "\u{2212}1.50%")
        XCTAssertEqual(DisplayNumber.moneyWhole(-1000, currency: "TWD"), "TWD \u{2212}1,000")
    }

    func testPercentSign() {
        XCTAssertEqual(DisplayNumber.percent(1.5), "+1.50%")
        XCTAssertEqual(DisplayNumber.percent(0), "0.00%")
        // 四捨五入成 0 不帶正負號。
        XCTAssertEqual(DisplayNumber.percent(-0.001), "0.00%")
        XCTAssertEqual(DisplayNumber.percent(0.001), "0.00%")
    }

    func testMissingIsNotZero() {
        for missing: Double? in [nil, .nan, .infinity] {
            XCTAssertEqual(DisplayNumber.number(missing), "—")
            XCTAssertEqual(DisplayNumber.percent(missing), "—")
            XCTAssertEqual(DisplayNumber.price(missing, currency: "TWD"), "—")
            XCTAssertEqual(DisplayNumber.moneyWhole(missing), "—")
        }
        XCTAssertEqual(DisplayNumber.number(0), "0")
        XCTAssertEqual(DisplayNumber.price(0, currency: "USD"), "0.00")
    }

    func testPriceDigitsDependOnCurrencyAndLevel() {
        XCTAssertEqual(DisplayNumber.price(1005, currency: "TWD"), "1,005")
        XCTAssertEqual(DisplayNumber.price(512.5, currency: "TWD"), "512.5")
        XCTAssertEqual(DisplayNumber.price(45.35, currency: "TWD"), "45.35")
        XCTAssertEqual(DisplayNumber.price(1234.5, currency: "USD"), "1,234.50")
        XCTAssertEqual(DisplayNumber.price(0.1234, currency: "USD"), "0.1234")
    }

    func testMoneyWholeHasNoDecimals() {
        XCTAssertEqual(DisplayNumber.moneyWhole(1234567.89, currency: "TWD"), "TWD 1,234,568")
        XCTAssertEqual(DisplayNumber.moneyWhole(1000), "1,000")
    }
}
