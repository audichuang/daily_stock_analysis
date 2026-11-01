import XCTest
@testable import DSACore

final class MarketReviewPayloadTests: XCTestCase {
    private func decode(_ json: String) throws -> AnalysisReport {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(AnalysisReport.self, from: Data(json.utf8))
    }

    /// Shape of GET /history/{id} for a market review: the payload sits under details.context_snapshot.
    func testDecodesMarketLightAndPlanFromContextSnapshot() throws {
        let report = try decode("""
        {"meta": {"query_id": "q", "stock_code": "MARKET"}, "summary": {},
         "details": {"news_content": null, "context_snapshot": {"market_review_payload": {
           "version": 1, "kind": "market_review", "region": "tw",
           "market_light": {"region": "tw", "trade_date": "2026-10-30", "status": "red", "score": 32,
                            "label": "偏防守", "temperature_label": "偏冷", "reasons": [], "guidance": "控制倉位，等待止跌。",
                            "dimensions": {"breadth": {"score": 30, "available": true}}},
           "next_day_plan": {"stance": "defensive", "summary": "量縮守 44,800。", "focus": ["AI"], "risks": [],
                             "key_levels": [{"label": "支撐", "price": 44800}, {"label": "壓力", "price": 46200}]}
         }}}}
        """)
        let payload = try XCTUnwrap(report.marketReviewPayload)
        XCTAssertEqual(payload.marketLight?.status, "red")
        XCTAssertEqual(payload.marketLight?.guidance, "控制倉位，等待止跌。")
        XCTAssertEqual(payload.nextDayPlan?.stance, "defensive")
        XCTAssertEqual(payload.nextDayPlan?.keyLevels?.map(\.price), [44800, 46200])

        let card = MarketReviewCardText.make(payload: payload, title: "大盤複盤", summary: "大盤複盤", oneSentence: nil, createdAt: "2026-10-30T18:00:00")
        XCTAssertEqual(card.lightText, "紅燈")
        XCTAssertEqual(card.stanceText, "防守")
        XCTAssertEqual(card.date, "10/30")
        XCTAssertEqual(card.line, "控制倉位，等待止跌。")
        XCTAssertEqual(card.keyLevels, "關鍵價 44,800 / 46,200")
    }

    func testMissingDetailsOrPayloadIsNil() throws {
        XCTAssertNil(try decode(#"{"meta": {"query_id": "q", "stock_code": "NVDA"}, "summary": {}}"#).marketReviewPayload)
        XCTAssertNil(try decode(#"{"meta": {"query_id": "q", "stock_code": "NVDA"}, "summary": {}, "details": null}"#).marketReviewPayload)
        XCTAssertNil(try decode(#"{"meta": {"query_id": "q", "stock_code": "NVDA"}, "summary": {}, "details": {"context_snapshot": {"other": 1}}}"#).marketReviewPayload)
    }

    /// context_snapshot is untyped on the backend; a string there must not break the whole report.
    func testNonObjectContextSnapshotStillDecodesReport() throws {
        let report = try decode(#"{"meta": {"query_id": "q", "stock_code": "MARKET"}, "summary": {}, "details": {"context_snapshot": "raw"}}"#)
        XCTAssertNil(report.marketReviewPayload)
        XCTAssertEqual(report.meta.queryId, "q")
    }

    func testPayloadWithoutLightOrPlanDecodesWithNilFields() throws {
        let report = try decode(#"{"meta": {"query_id": "q", "stock_code": "MARKET"}, "summary": {}, "details": {"context_snapshot": {"market_review_payload": {"version": 1, "sections": []}}}}"#)
        let payload = try XCTUnwrap(report.marketReviewPayload)
        XCTAssertNil(payload.marketLight)
        XCTAssertNil(payload.nextDayPlan)
    }

    func testCombinedReviewResolvesPerMarket() throws {
        let report = try decode("""
        {"meta": {"query_id": "q", "stock_code": "MARKET"}, "summary": {},
         "details": {"context_snapshot": {"market_review_payload": {"region": "tw,us", "markets": {
           "tw": {"market_light": {"status": "green"}},
           "us": {"next_day_plan": {"stance": "balanced"}}}}}}}
        """)
        let payload = try XCTUnwrap(report.marketReviewPayload)
        XCTAssertEqual(payload.resolved(for: "tw").marketLight?.status, "green")
        XCTAssertEqual(payload.resolved(for: "us").nextDayPlan?.stance, "balanced")
        XCTAssertNil(payload.resolved(for: "us").marketLight)
    }

    func testUnavailableLightAndUnknownStanceShowNothing() {
        let payload = MarketReviewPayload(marketLight: MarketReviewLight(status: "unavailable"), nextDayPlan: MarketReviewNextDayPlan(stance: "future", summary: "續看量能"))
        let card = MarketReviewCardText.make(payload: payload, title: nil, summary: nil, oneSentence: nil, createdAt: nil)
        XCTAssertNil(card.lightText)
        XCTAssertNil(card.stanceText)
        XCTAssertNil(card.keyLevels)
        XCTAssertEqual(card.line, "續看量能")
    }

    func testFallbackWhenSummaryIsOnlyTheTitle() {
        XCTAssertEqual(MarketReviewCardText.fallbackLine(title: "台股大盤複盤", summary: "台股大盤複盤", oneSentence: nil), MarketReviewCardText.placeholder)
        // Short and without punctuation reads like a heading, not a sentence.
        XCTAssertEqual(MarketReviewCardText.fallbackLine(title: "大盤", summary: "今日盤勢複盤", oneSentence: "權值股撐盤，中小型股轉弱。"), "權值股撐盤，中小型股轉弱。")
        XCTAssertEqual(MarketReviewCardText.fallbackLine(title: "大盤", summary: "   ", oneSentence: nil), MarketReviewCardText.placeholder)
        // A short sentence with punctuation, or a longer one, is kept as is.
        XCTAssertEqual(MarketReviewCardText.fallbackLine(title: "大盤", summary: "量縮整理。", oneSentence: "x"), "量縮整理。")
        XCTAssertEqual(MarketReviewCardText.fallbackLine(title: "大盤", summary: "外資連三日賣超但電子權值股撐盤收紅", oneSentence: "x"), "外資連三日賣超但電子權值股撐盤收紅")
    }
}
