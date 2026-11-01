import XCTest
@testable import DSACore

final class ReportPresentationTests: XCTestCase {
    private func decoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }

    private func artifact(level: String = "good", missing: String = "[]", sourceStatus: String = "null", evidence: String = "[]") throws -> ResearchArtifact {
        try decoder().decode(ResearchArtifact.self, from: Data("""
        {"schema_version": "research-artifact-v1", "artifact_id": "a", "subject": {"stock_code": "AAPL"},
         "thesis": {"direction": "neutral", "summary": "s", "reasons": [], "risks": [],
                    "position_advice": {"no_position": "等回檔", "has_position": "續抱"}},
         "evidence": \(evidence), "invalidation_conditions": [], "next_actions": [],
         "data_quality": {"level": "\(level)", "source_count": 0, "stale_count": 0, "missing_blocks": \(missing), "limitations": []},
         "source_status": \(sourceStatus)}
        """.utf8))
    }

    private func strategy(_ json: String) throws -> ReportStrategy {
        try decoder().decode(ReportStrategy.self, from: Data(json.utf8))
    }

    // MARK: 舊回應相容

    func testOldReportPayloadStillDecodes() throws {
        let report = try decoder().decode(AnalysisReport.self, from: Data(#"{"meta": {"query_id": "q", "stock_code": "NVDA"}, "summary": {}, "strategy": {"stop_loss": "跌破月線"}}"#.utf8))
        XCTAssertNil(report.meta.held)
        XCTAssertNil(report.summary.positionAdvice)
        XCTAssertNil(report.strategy?.sniperPrices)
    }

    func testNewReportFieldsDecodeUnderSnakeCaseKeys() throws {
        let report = try decoder().decode(AnalysisReport.self, from: Data("""
        {"meta": {"query_id": "q", "stock_code": "2330.TW", "held": true, "currency": "TWD", "change_amount": -3.5,
                  "previous_report": {"id": 7, "action": "reduce", "score": 40, "created_at": "2030-01-01", "stop_loss": 500.5}},
         "summary": {"one_sentence": "一句話", "position_advice": {"no_position": "空手", "has_position": "持股"},
                     "phase_watch_conditions": ["條件"], "guardrail_applied": true},
         "strategy": {"sniper_prices": {"ideal_buy": 590, "stop_loss": 570}, "sniper_prices_source": "structured"}}
        """.utf8))
        XCTAssertEqual(report.meta.previousReport?.stopLoss, 500.5)
        XCTAssertEqual(report.summary.positionAdvice?.hasPosition, "持股")
        XCTAssertEqual(report.summary.phaseWatchConditions, ["條件"])
        XCTAssertEqual(report.strategy?.sniperPrices?.idealBuy, 590)
    }

    func testChipKeysWithDigitsDecode() throws {
        let chips = try decoder().decode(StockProfileChips.self, from: Data(#"{"margin_chg_5": 12.0, "margin_chg_20": -3.0, "foreign_net": 1000}"#.utf8))
        XCTAssertEqual(chips.marginChg5, 12)
        XCTAssertEqual(chips.marginChg20, -3)
        XCTAssertEqual(chips.foreignNet, 1000)
    }

    // MARK: 分頁

    func testUSStockHidesChipsTabButKeepsFinancials() {
        XCTAssertEqual(StockDetailTab.available(market: "us", hasChips: false, hasReport: true), [.ai, .financials, .news])
        XCTAssertEqual(StockDetailTab.available(market: "tw", hasChips: true, hasReport: true), [.ai, .chips, .financials, .news])
    }

    func testTabsHideWhenDataIsMissing() {
        XCTAssertEqual(StockDetailTab.available(market: "tw", hasChips: false, hasReport: false), [.ai, .financials])
        XCTAssertEqual(StockDetailTab.available(market: "jp", hasChips: false, hasReport: false), [.ai])
    }

    // MARK: 上下檔

    func testNeighborsStopAtListEndsAndIgnoreForeignCodes() {
        let list = ["A", "B", "C"]
        XCTAssertEqual(StockNeighbors.of("B", in: list).previous, "A")
        XCTAssertEqual(StockNeighbors.of("B", in: list).next, "C")
        XCTAssertNil(StockNeighbors.of("A", in: list).previous)
        XCTAssertNil(StockNeighbors.of("C", in: list).next)
        XCTAssertNil(StockNeighbors.of("Z", in: list).next)
    }

    // MARK: 價位

    func testStructuredLevelsUseNumbers() throws {
        let levels = PriceLevel.levels(from: try strategy(#"{"ideal_buy": "長句", "sniper_prices": {"ideal_buy": 590.5}, "sniper_prices_source": "structured"}"#))
        XCTAssertEqual(levels.first(where: { $0.kind == .idealBuy })?.value, 590.5)
    }

    func testLegacySourceNeverExposesNumbersEvenIfPresent() throws {
        let levels = PriceLevel.levels(from: try strategy(#"{"ideal_buy": "站回 590 附近", "sniper_prices": {"ideal_buy": 590.5}, "sniper_prices_source": "legacy"}"#))
        let ideal = levels.first(where: { $0.kind == .idealBuy })
        XCTAssertNil(ideal?.value)
        XCTAssertEqual(ideal?.text, "站回 590 附近")
    }

    func testRulerNeedsTwoDistinctPrices() {
        XCTAssertNil(PriceRuler(values: [100, nil]))
        XCTAssertNil(PriceRuler(values: [100, 100]))
        let ruler = PriceRuler(values: [100, nil, 200])
        XCTAssertEqual(ruler?.fraction(150), 0.5)
        XCTAssertEqual(ruler?.fraction(250), 1, "超出範圍貼邊，不畫到尺外")
    }

    func testChangeSinceReportRejectsMissingBase() throws {
        XCTAssertEqual(try XCTUnwrap(ReportMath.changePercent(from: 100, to: 110)), 10, accuracy: 0.0001)
        XCTAssertNil(ReportMath.changePercent(from: nil, to: 110))
        XCTAssertNil(ReportMath.changePercent(from: 0, to: 110))
    }

    // MARK: 缺資料

    func testGapsCountOnlyFailedSourcesAfterSnakeCaseKeyConversion() throws {
        let gaps = ReportGaps.of(try artifact(sourceStatus: #"{"sec_finra": "no_data", "insider": "timeout", "futu": "not_configured", "ratings": "ok", "estimates": "not_supported"}"#))
        XCTAssertEqual(Set(gaps.items), ["SEC／FINRA", "內部人交易"])
    }

    func testGapsResolveBlockTitleAndIncompleteLevel() throws {
        let evidence = #"[{"id": "context:chip", "source_type": "analysis_context", "title": "籌碼資料", "freshness": "unknown", "quality_level": "unknown"}]"#
        let gaps = ReportGaps.of(try artifact(level: "limited", missing: #"["chip", "other"]"#, evidence: evidence))
        XCTAssertEqual(gaps.items, ["籌碼資料", "other"])
        XCTAssertTrue(gaps.incomplete)
        XCTAssertFalse(ReportGaps.of(try artifact(level: "usable")).incomplete)
    }

    func testThesisPositionAdviceDecodesAsStruct() throws {
        XCTAssertEqual(try artifact().thesis.positionAdvice?.noPosition, "等回檔")
    }

    // MARK: 證據分組

    func testEvidenceGroupsFollowFixedOrderAndFallBackToSourceType() throws {
        let evidence = """
        [{"id": "1", "source_type": "analysis_context", "title": "輸入", "freshness": "unknown", "quality_level": "unknown"},
         {"id": "2", "source_type": "x", "group": "news", "title": "新聞", "freshness": "unknown", "quality_level": "unknown"},
         {"id": "3", "source_type": "x", "group": "sec_filing", "title": "8-K", "freshness": "unknown", "quality_level": "unknown"},
         {"id": "4", "source_type": "mystery", "title": "?", "freshness": "unknown", "quality_level": "unknown"}]
        """
        let groups = EvidenceGroup.groups(try artifact(evidence: evidence).evidence)
        XCTAssertEqual(groups.map(\.key), ["sec_filing", "news", "context", "other"])
        XCTAssertEqual(groups.first?.title, "SEC 公告")
    }

    func testCompactNumberUnits() {
        XCTAssertEqual(DisplayNumber.compact(12_345_678), "1,234.57 萬")
        XCTAssertEqual(DisplayNumber.compact(250_000_000), "2.5 億")
        XCTAssertEqual(DisplayNumber.compact(nil), "—")
    }

    func testMarketPhaseUnknownShowsNothing() {
        XCTAssertEqual(MarketPhaseLabel.text("postmarket"), "已收盤")
        XCTAssertNil(MarketPhaseLabel.text("unknown"))
        XCTAssertNil(MarketPhaseLabel.text(nil))
    }

    func testMarketSessionDecodesFromIndicesPayload() throws {
        let session = try decoder().decode(MarketSessionStatus.self, from: Data(#"{"items": [], "region": "tw", "market_phase": "postmarket", "market_open": false}"#.utf8))
        XCTAssertEqual(session.marketPhase, "postmarket")
        XCTAssertEqual(session.marketOpen, false)
    }
}
