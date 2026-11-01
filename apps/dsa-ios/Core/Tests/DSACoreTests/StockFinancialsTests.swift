import Foundation
import XCTest
@testable import DSACore

final class StockFinancialsTests: XCTestCase {
    private let json = """
    {"stock_code":"2330.TW","market":"tw","status":"ok","status_reason":null,"stock_name":"台積電","template":"general",
     "currency":"TWD","trading_currency":"TWD",
     "source":{"id":"market.financial_statement","label":"公開資訊觀測站","source_unit":"新台幣千元","url":null},
     "cross_check":null,
     "periods":[{"key":"2026Q2","label":"2026 Q2","fiscal_year":2026,"fiscal_quarter":2,"period_end":"2026-06-30",
                 "announce_date":"2026-08-14","announce_date_kind":"statutory_deadline","filing_form":""}],
     "metrics":[{"key":"gross_margin","label":"毛利率","kind":"ratio","unit":"%","definition":"毛利 ÷ 營收",
                 "points":[{"period":"2026Q2","value":67.72,"yoy_pct":null,"qoq_pct":null,"yoy_pp":9.1,"qoq_pp":-1.47,"derived":false}]}],
     "not_applicable":[{"key":"contract_liabilities","label":"合約負債","reason":"沒有揭露"}],
     "monthly_revenue":[{"month":"2026-09","revenue":511857399000.0,"yoy_pct":54.6,"mom_pct":-0.6,"announce_date":"2026-10-10"}],
     "ttm_revenue_yoy_pct":36.2,"limitations":["法定期限"],"is_stale":false,
     "commentary":{"status":"ready","period":"2026Q2","generated_at":null,"model":"m","headline":"重點",
       "highlights":[{"metric_key":"gross_margin","period":"2026Q2","importance":"high","what_happened":"上升",
                      "why_it_matters":"定價力","how_to_read":"毛利除以營收"}],"message":null}}
    """

    private func decode() throws -> StockFinancials {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(StockFinancials.self, from: Data(json.utf8))
    }

    func testDecodesServerContract() throws {
        let value = try decode()
        XCTAssertEqual(value.metrics.first?.points.first?.yoyPp, 9.1)
        XCTAssertEqual(value.ttmRevenueYoyPct, 36.2)
        XCTAssertEqual(value.commentary.highlights(for: "gross_margin").first?.howToRead, "毛利除以營收")
        XCTAssertTrue(value.commentary.highlights(for: "revenue").isEmpty)
    }

    func testRatioChangeIsPercentagePoints() throws {
        let metric = try XCTUnwrap(try decode().metrics.first)
        XCTAssertEqual(metric.value(metric.points.first, currency: "TWD"), "67.7%")
        XCTAssertEqual(metric.yoy(metric.points.first), "+9.1 個百分點")
        XCTAssertEqual(metric.qoq(metric.points.first), "−1.5 個百分點")
    }

    func testAmountUsesReportingCurrencyAndNeverFakesZero() {
        XCTAssertEqual(FinancialFormat.amount(1.27e12, currency: "TWD"), "1.27 兆元")
        XCTAssertEqual(FinancialFormat.amount(-3.3e9, currency: "USD"), "−33.0 億美元")
        XCTAssertEqual(FinancialFormat.amount(nil, currency: "USD"), "—")
        XCTAssertEqual(FinancialFormat.amount(0, currency: "USD"), "0 美元")
        XCTAssertEqual(FinancialFormat.metric(136.25, kind: "per_share", unit: "TWD/ADR", currency: "TWD"), "136.25 元／ADR")
        XCTAssertEqual(FinancialFormat.metric(27.25, kind: "per_share", unit: "TWD/股", currency: "TWD"), "27.25 元")
    }
}
