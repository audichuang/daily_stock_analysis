import XCTest
@testable import DSACore

final class ReportGuardrailDecodingTests: XCTestCase {
    private func decoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }

    private func summary(_ json: String) throws -> ReportSummary {
        try decoder().decode(ReportSummary.self, from: Data(json.utf8))
    }

    func testSummaryDecodesModelAdviceFields() throws {
        let value = try summary("""
        {"action": "watch", "one_sentence": "資料不足，先觀望。", "guardrail_applied": true,
         "guardrail_reason": "籌碼資料缺漏", "guardrail_kind": "data_unavailable",
         "model_one_sentence": "突破前高，可分批布局。",
         "model_position_advice": {"no_position": "回檔分批買", "has_position": "續抱"}}
        """)
        XCTAssertEqual(value.modelOneSentence, "突破前高，可分批布局。")
        XCTAssertEqual(value.guardrailKind, "data_unavailable")
        XCTAssertEqual(value.modelPositionAdvice?.noPosition, "回檔分批買")
        XCTAssertEqual(value.modelPositionAdvice?.hasPosition, "續抱")
    }

    /// Old servers send none of the B02 fields; decoding must still succeed with nils.
    /// Mutation: making any new field non-optional turns this red.
    func testOldSummaryWithoutNewFieldsStillDecodes() throws {
        let value = try summary("""
        {"action": "reduce", "action_label": "減碼", "guardrail_applied": true, "guardrail_reason": "大盤轉弱"}
        """)
        XCTAssertNil(value.modelOneSentence)
        XCTAssertNil(value.modelPositionAdvice)
        XCTAssertNil(value.guardrailKind)
        XCTAssertEqual(value.guardrailReason, "大盤轉弱")
    }

    func testThesisDecodesNewFieldsAndToleratesOldShape() throws {
        let fresh = try decoder().decode(ResearchThesis.self, from: Data("""
        {"direction": "neutral", "summary": "s", "reasons": [], "risks": [],
         "guardrail_kind": "market_logic", "model_one_sentence": "可加碼"}
        """.utf8))
        XCTAssertEqual(fresh.guardrailKind, "market_logic")
        XCTAssertEqual(fresh.modelOneSentence, "可加碼")
        XCTAssertNil(fresh.modelPositionAdvice)

        let old = try decoder().decode(ResearchThesis.self, from: Data("""
        {"direction": "neutral", "summary": "s", "reasons": [], "risks": []}
        """.utf8))
        XCTAssertNil(old.guardrailKind)
        XCTAssertNil(old.modelOneSentence)
        XCTAssertNil(old.modelPositionAdvice)
    }

    func testFullReportFromOldServerDecodes() throws {
        let report = try decoder().decode(AnalysisReport.self, from: Data("""
        {"meta": {"query_id": "q", "stock_code": "GOOGL"},
         "summary": {"action": "watch", "guardrail_applied": false}}
        """.utf8))
        XCTAssertNil(report.summary.guardrailKind)
        XCTAssertNil(ReportGuardrailDisplay.of(report.summary, actionText: "觀望"))
    }

    // MARK: Presentation rules (same as Web W07)

    func testDataUnavailableShowsModelSentenceAndModelAdvice() throws {
        let value = try summary("""
        {"one_sentence": "資料不足，先觀望。", "guardrail_applied": true, "guardrail_reason": "籌碼資料缺漏",
         "guardrail_kind": "data_unavailable", "model_one_sentence": "突破前高，可分批布局。",
         "model_position_advice": {"no_position": "回檔分批買"}}
        """)
        let display = try XCTUnwrap(ReportGuardrailDisplay.of(value, actionText: "觀望"))
        XCTAssertEqual(display.headline, "模型原意：突破前高，可分批布局。")
        XCTAssertEqual(display.label, "系統護欄：資料缺，動作降為觀望")
        XCTAssertEqual(display.tone, .muted)
        XCTAssertEqual(display.details, ["籌碼資料缺漏", "護欄版：資料不足，先觀望。"])
        XCTAssertEqual(display.positionAdvice?.noPosition, "回檔分批買")
    }

    func testMarketLogicKeepsGuardedSentenceAndRevealsModelAdvice() throws {
        // phase_decision_guardrail omits model_position_advice for market_logic.
        let value = try summary("""
        {"one_sentence": "大盤轉弱，觀望。", "guardrail_applied": true, "guardrail_reason": "大盤跌破季線",
         "guardrail_kind": "market_logic", "model_one_sentence": "可加碼"}
        """)
        let display = try XCTUnwrap(ReportGuardrailDisplay.of(value, actionText: "觀望"))
        XCTAssertNil(display.headline)
        XCTAssertEqual(display.label, "系統護欄：降為觀望")
        XCTAssertEqual(display.tone, .warning)
        XCTAssertEqual(display.details, ["大盤跌破季線", "模型原本建議：可加碼"])
        XCTAssertNil(display.positionAdvice)
    }

    func testLegacyGuardrailShowsActionAndReason() throws {
        let value = try summary("""
        {"guardrail_applied": true, "guardrail_reason": "大盤轉弱"}
        """)
        let display = try XCTUnwrap(ReportGuardrailDisplay.of(value, actionText: "減碼"))
        XCTAssertNil(display.headline)
        XCTAssertEqual(display.label, "系統護欄：減碼")
        XCTAssertEqual(display.details, ["大盤轉弱"])
    }

    func testNextStepsDeduplicatesAcrossGroups() {
        XCTAssertEqual(
            ReportNextSteps.unique(["站回月線", " 站回月線 "], nil, ["量能放大"], excluding: ["跌破季線"]),
            ["站回月線", "量能放大"]
        )
        XCTAssertEqual(ReportNextSteps.unique(["跌破季線"], excluding: ["跌破季線"]), [])
    }

    func testMonthDayUsesBackendDate() {
        XCTAssertEqual(ReportDisplayDate.monthDay("2026-11-01T18:00:00"), "11/1")
        XCTAssertNil(ReportDisplayDate.monthDay(nil))
    }
}
