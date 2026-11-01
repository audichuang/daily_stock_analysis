import Foundation
import XCTest
@testable import DSACore

final class PortfolioOverviewTests: XCTestCase {
    func testOverviewReadsConsolidatedFieldsAndAddsFunds() throws {
        let overview = try XCTUnwrap(try snapshot(extra: consolidated()).overview)
        XCTAssertEqual(overview.currency, "TWD")
        XCTAssertEqual(overview.totalAssets, 1_800_000)
        XCTAssertEqual(overview.dayPnl, 9_800)
        XCTAssertEqual(overview.marketValue, 900_000)
        XCTAssertEqual(try XCTUnwrap(overview.unrealizedPct), 50_000.0 / 850_000.0 * 100, accuracy: 0.0001)
        XCTAssertFalse(overview.hasNegativeCash)
    }

    func testOverviewNeverFallsBackToCNYAggregate() throws {
        // 舊服務沒有 display_currency：頂層 CNY 不能被當成總覽。
        XCTAssertNil(try snapshot(extra: [:]).overview)
    }

    func testMissingFundIsNotTreatedAsZeroSilently() throws {
        var extra = consolidated()
        extra["consolidated_fund_value_base"] = nil
        extra["consolidated_fund_day_pnl_base"] = nil
        let overview = try XCTUnwrap(try snapshot(extra: extra).overview)
        XCTAssertEqual(overview.totalAssets, 1_600_000)
        XCTAssertFalse(overview.fundsIncluded, "畫面要靠這個標明總額只算帳本")
    }

    func testFxMissingKeepsTotalEmpty() throws {
        var extra = consolidated()
        extra["consolidated_equity_base"] = NSNull()
        extra["consolidated_fx_missing"] = true
        let overview = try XCTUnwrap(try snapshot(extra: extra).overview)
        XCTAssertNil(overview.totalAssets, "缺匯率不能拿基金當總額")
        XCTAssertTrue(overview.fxMissing)
    }

    func testNegativeCashFlag() throws {
        var extra = consolidated()
        extra["consolidated_cash_base"] = -1.0
        XCTAssertTrue(try XCTUnwrap(try snapshot(extra: extra).overview).hasNegativeCash)
    }

    func testMarketKeysPutTaiwanAndUSFirst() throws {
        let value = try snapshot(accounts: [account(1, market: "hk", currency: "HKD"), account(2, market: "us", currency: "USD"), account(3, market: "TW", currency: "TWD")])
        XCTAssertEqual(value.marketKeys, ["tw", "us", "hk"])
    }

    func testMergeSumsSameSymbolAcrossAccountsAndKeepsCurrenciesApart() throws {
        let accounts = [
            account(1, market: "tw", currency: "TWD", positions: [position("2330.TW", value: 600, pnl: 100, cost: 500, quantity: 1)]),
            account(2, market: "tw", currency: "TWD", positions: [position("2330.TW", value: 300, pnl: -50, cost: 350, quantity: 1), position("0050.TW", value: 100, pnl: 0, cost: 100, quantity: 1)]),
            account(3, market: "us", currency: "USD", positions: [position("AAPL", market: "us", currency: "USD", value: 50, pnl: 5, cost: 45, quantity: 1)])
        ]
        let groups = PortfolioHoldings.merged(try snapshot(accounts: accounts).accounts)
        XCTAssertEqual(groups.map(\.currency), ["TWD", "USD"])
        let tsmc = try XCTUnwrap(groups[0].holdings.first)
        XCTAssertEqual(tsmc.symbol, "2330.TW")
        XCTAssertEqual(tsmc.marketValue, 900)
        XCTAssertEqual(tsmc.unrealizedPnl, 50)
        XCTAssertEqual(tsmc.accountCount, 2)
        XCTAssertEqual(tsmc.quantity, 2)
        XCTAssertEqual(tsmc.avgCost, 425)
        XCTAssertEqual(try XCTUnwrap(tsmc.sharePct), 90, accuracy: 0.001, "佔比只比同幣別")
        XCTAssertEqual(try XCTUnwrap(groups[1].holdings[0].sharePct), 100, accuracy: 0.001)
    }

    func testMergeWithOneUnavailablePriceHasNoTotal() throws {
        let accounts = [
            account(1, market: "tw", currency: "TWD", positions: [position("2330.TW", value: 600, pnl: 100, cost: 500, quantity: 1)]),
            account(2, market: "tw", currency: "TWD", positions: [position("2330.TW", value: 0, pnl: 0, cost: 350, quantity: 1, available: false)])
        ]
        let holding = try XCTUnwrap(PortfolioHoldings.merged(try snapshot(accounts: accounts).accounts).first?.holdings.first)
        XCTAssertNil(holding.marketValue, "少算一筆的合計不能看起來像真的")
        XCTAssertNil(holding.unrealizedPnl)
        XCTAssertNil(holding.sharePct)
    }

    func testFxMissingAccountHidesHoldingAmounts() throws {
        let value = try snapshot(accounts: [account(1, market: "tw", currency: "TWD", fxMissing: true, positions: [position("2330.TW", value: 600, pnl: 100, cost: 500, quantity: 1)])])
        let holding = try XCTUnwrap(PortfolioHoldings.forAccount(value.accounts[0]).first)
        XCTAssertNil(holding.marketValue)
        XCTAssertNil(holding.unrealizedPnl)
        XCTAssertNil(holding.unrealizedPct)
    }

    func testSortPutsMissingValuesLastAndHonoursKey() throws {
        let value = try snapshot(accounts: [account(1, market: "tw", currency: "TWD", positions: [
            position("B", value: 100, pnl: 50, cost: 50, quantity: 1),
            position("A", value: 300, pnl: -10, cost: 310, quantity: 1),
            position("C", value: 0, pnl: 0, cost: 1, quantity: 1, available: false)
        ])])
        XCTAssertEqual(PortfolioHoldings.forAccount(value.accounts[0], sort: .marketValue).map(\.symbol), ["A", "B", "C"])
        XCTAssertEqual(PortfolioHoldings.forAccount(value.accounts[0], sort: .pnl).map(\.symbol), ["B", "A", "C"])
        XCTAssertEqual(PortfolioHoldings.forAccount(value.accounts[0], sort: .symbol).map(\.symbol), ["A", "B", "C"])
    }

    func testInsightsUseServerWeightsAndPercentForLoss() throws {
        let value = try snapshot(accounts: [account(1, market: "tw", currency: "TWD", positions: [
            position("2330.TW", value: 600, pnl: -100, cost: 700, quantity: 1, pct: -14.3),
            position("0050.TW", value: 100, pnl: -50, cost: 150, quantity: 1, pct: -33.3)
        ])])
        let risk = try decode(PortfolioRiskReport.self, [
            "concentration": ["top_positions": [["symbol": "2330.TW", "weight_pct": 61.9, "is_alert": true] as [String: Any]]],
            "sector_concentration": ["top_sectors": [["sector": "半導體", "weight_pct": 70.0] as [String: Any]]]
        ])
        let insights = PortfolioInsights.make(snapshot: value, risk: risk)
        XCTAssertEqual(insights.map(\.id), ["concentration", "loss", "sector"])
        XCTAssertTrue(insights[0].isAlert)
        XCTAssertEqual(insights[0].title, "最大持股")
        XCTAssertEqual(insights[0].detail, "2330.TW · 佔總資產")
        XCTAssertEqual(insights[1].detail, "0050.TW", "虧損比百分比，不比金額")
        XCTAssertEqual(try XCTUnwrap(insights[1].changeValue), -33.3, accuracy: 0.001, "最大虧損要用漲跌色")
        XCTAssertEqual(insights[2].detail, "半導體", "正常產業仍要產生產業卡")
    }

    func testUnclassifiedSectorProducesNoSectorCard() throws {
        let value = try snapshot(accounts: [account(1, market: "tw", currency: "TWD", positions: [position("2330.TW", value: 600, pnl: 10, cost: 590, quantity: 1, pct: 1.7)])])
        for label in ["UNCLASSIFIED", "unknown", " "] {
            let risk = try decode(PortfolioRiskReport.self, [
                "sector_concentration": ["top_sectors": [["sector": label, "weight_pct": 80.0] as [String: Any]]]
            ])
            XCTAssertEqual(PortfolioInsights.make(snapshot: value, risk: risk).map(\.id), ["loss"], "「\(label)」不是產業，不產生產業卡")
        }
        let classified = try decode(PortfolioRiskReport.self, [
            "sector_concentration": ["top_sectors": [["sector": "半導體", "weight_pct": 80.0] as [String: Any]]]
        ])
        XCTAssertEqual(PortfolioInsights.make(snapshot: value, risk: classified).map(\.id), ["loss", "sector"])
    }

    func testInsightsSurviveRiskFailureAndHideNullWeights() throws {
        let value = try snapshot(accounts: [account(1, market: "tw", currency: "TWD", positions: [position("2330.TW", value: 600, pnl: 10, cost: 590, quantity: 1, pct: 1.7)])])
        XCTAssertEqual(PortfolioInsights.make(snapshot: value, risk: nil).map(\.id), ["loss"], "風險端點失敗不拖垮頁面")
        let noWeights = try decode(PortfolioRiskReport.self, ["concentration": ["top_positions": [["symbol": "2330.TW", "weight_pct": NSNull()] as [String: Any]]]])
        XCTAssertEqual(PortfolioInsights.make(snapshot: value, risk: noWeights).map(\.id), ["loss"], "缺匯率時權重是 null，不顯示")
    }

    func testUnknownPnlIsNotReportedAsNoLoss() throws {
        let known = try snapshot(accounts: [account(1, market: "tw", currency: "TWD", positions: [position("2330.TW", value: 600, pnl: 10, cost: 590, quantity: 1, pct: 1.7)])])
        XCTAssertEqual(PortfolioInsights.make(snapshot: known, risk: nil).first?.detail, "目前沒有虧損部位")
        let unknown = try snapshot(accounts: [account(1, market: "tw", currency: "TWD", positions: [position("2330.TW", value: 600, pnl: 10, cost: 590, quantity: 1, available: false)])])
        XCTAssertEqual(PortfolioInsights.make(snapshot: unknown, risk: nil).first?.detail, "部分部位損益未知")
    }

    func testNativeTotalsForFilteredAccountsDoNotMixCurrencies() throws {
        let value = try snapshot(accounts: [account(1, market: "tw", currency: "TWD"), account(2, market: "us", currency: "USD")])
        XCTAssertEqual(value.accounts.filter { $0.market == "us" }.currencyTotals.map(\.currency), ["USD"])
        XCTAssertEqual(value.currencyTotals.map(\.currency), ["TWD", "USD"])
    }

    // MARK: 測試資料

    private func consolidated() -> [String: Any] {
        ["display_currency": "TWD", "consolidated_equity_base": 1_600_000.0, "consolidated_market_value_base": 900_000.0,
         "consolidated_cash_base": 700_000.0, "consolidated_unrealized_pnl_base": 50_000.0, "consolidated_realized_pnl_base": 0.0,
         "consolidated_day_pnl_base": 8_800.0, "consolidated_fund_value_base": 200_000.0, "consolidated_fund_day_pnl_base": 1_000.0,
         "consolidated_fx_stale": false, "consolidated_fx_missing": false]
    }

    private func decode<T: Decodable>(_ type: T.Type, _ payload: [String: Any]) throws -> T {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(type, from: JSONSerialization.data(withJSONObject: payload))
    }

    private func snapshot(accounts: [[String: Any]] = [], extra: [String: Any] = [:]) throws -> PortfolioSnapshot {
        var payload: [String: Any] = [
            "as_of": "2000-01-01", "cost_method": "fifo", "currency": "CNY", "account_count": accounts.count,
            "total_cash": 11_111, "total_market_value": 77_777, "total_equity": 88_888,
            "realized_pnl": 3_333, "unrealized_pnl": 4_444, "fx_stale": false, "fx_missing": true,
            "data_quality": "partial", "limitations": [], "accounts": accounts
        ]
        payload.merge(extra) { _, new in new }
        return try decode(PortfolioSnapshot.self, payload)
    }

    private func account(_ id: Int, market: String, currency: String, fxMissing: Bool = false, positions: [[String: Any]] = []) -> [String: Any] {
        ["account_id": id, "account_name": "合成帳戶 \(id)", "market": market, "base_currency": currency,
         "total_cash": 1, "total_market_value": 1, "total_equity": 2, "realized_pnl": 0, "unrealized_pnl": 0,
         "fx_missing": fxMissing, "fx_stale": false, "data_quality": "ok", "limitations": [], "positions": positions]
    }

    private func position(_ symbol: String, market: String = "tw", currency: String = "TWD", value: Double, pnl: Double, cost: Double,
                          quantity: Double, available: Bool = true, pct: Double = 1) -> [String: Any] {
        ["symbol": symbol, "market": market, "currency": currency, "quantity": quantity, "avg_cost": cost / quantity,
         "total_cost": cost, "last_price": value / quantity, "market_value_base": value, "unrealized_pnl_base": pnl,
         "unrealized_pnl_pct": pct, "valuation_currency": currency, "price_source": "realtime_quote",
         "price_stale": false, "price_available": available, "data_quality": "ok", "limitations": []]
    }
}
