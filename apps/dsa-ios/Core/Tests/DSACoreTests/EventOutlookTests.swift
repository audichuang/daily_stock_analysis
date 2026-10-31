import XCTest
@testable import DSACore

final class EventOutlookTests: XCTestCase {
    private func decode(_ json: String) throws -> EventOutlook {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(EventOutlook.self, from: Data(json.utf8))
    }

    func testDecodesApiPayloadAndSummarizesConsensus() throws {
        let outlook = try decode("""
        {"event": "Q3 財報", "event_type": "earnings", "event_date": "2030-11-18",
         "consensus": {"eps": 2.47, "revenue": 109000000000.0, "analysts": 44, "currency": "USD"},
         "track_record": "近四季皆超預期", "revision_trend": null, "expectation": "beat", "confidence": "medium",
         "reasoning": "理由", "scenarios": [{"case": "miss", "expected_reaction": "下跌",
         "action_if_holding": "減碼", "action_if_flat": "觀望"}], "news_impact": "影響", "verify_after": "毛利率"}
        """)
        XCTAssertEqual(outlook.expectationLabel, "判斷：超預期")
        XCTAssertEqual(outlook.confidenceLabel, "把握度中")
        XCTAssertEqual(outlook.scenarios?.first?.actionIfHolding, "減碼")
        XCTAssertEqual(outlook.consensusSummary, "EPS 2.47 USD · 營收 1090 億 USD · 44 位分析師")
    }

    func testMissingAndUnknownValuesFallBackToInsufficient() throws {
        let outlook = try decode(#"{"event": "法說會", "expectation": "future_value", "consensus": null}"#)
        XCTAssertEqual(outlook.expectationLabel, "資料不足，不判斷")
        XCTAssertNil(outlook.consensusSummary)
        XCTAssertNil(outlook.confidenceLabel)
    }

    func testOldReportWithoutFieldStillDecodes() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let report = try decoder.decode(AnalysisReport.self, from: Data(#"{"meta": {"query_id": "q", "stock_code": "NVDA"}, "summary": {}}"#.utf8))
        XCTAssertNil(report.eventOutlook)
    }
}
