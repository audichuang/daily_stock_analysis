import Foundation
import XCTest
@testable import DSACore

final class PortfolioCurrencyTotalsTests: XCTestCase {
    func testNativeCurrencyTotalsDoNotRelabelOrUseCNYAggregate() throws {
        let snapshot = try fixture(accounts: [
            account(1, currency: "TWD", cash: 100, marketValue: 900, unrealized: 100, realized: 10),
            account(2, currency: "USD", cash: 5, marketValue: 70, unrealized: 7, realized: 1),
            account(3, currency: "TWD", cash: 50, marketValue: 200, unrealized: -5, realized: -2)
        ])
        let totals = snapshot.currencyTotals
        XCTAssertEqual(totals.map(\.currency), ["TWD", "USD"])
        let twd = try XCTUnwrap(totals.first { $0.currency == "TWD" })
        XCTAssertEqual(twd.accountCount, 2)
        XCTAssertEqual(twd.totalEquity, 1_250)
        XCTAssertEqual(twd.totalCash, 150)
        XCTAssertEqual(twd.totalMarketValue, 1_100)
        XCTAssertEqual(twd.unrealizedPnl, 95)
        XCTAssertEqual(twd.realizedPnl, 8)
        let usd = try XCTUnwrap(totals.first { $0.currency == "USD" })
        XCTAssertEqual(usd.accountCount, 1)
        XCTAssertEqual(usd.totalEquity, 75)
        XCTAssertEqual(usd.totalMarketValue, 70)
        XCTAssertEqual(snapshot.currency, "CNY")
        XCTAssertEqual(snapshot.totalEquity, 88_888)
        XCTAssertEqual(snapshot.accounts[1].baseCurrency, "USD")
        XCTAssertEqual(snapshot.accounts[1].totalEquity, 75)
    }

    func testAggregateFXFailureDoesNotHideCompleteNativeCurrencyTotals() throws {
        let snapshot = try fixture(accounts: [
            account(1, currency: "TWD", cash: 100, marketValue: 900),
            account(2, currency: "USD", cash: 5, marketValue: 70)
        ], aggregateFXMissing: true)
        XCTAssertEqual(snapshot.currencyTotals.map(\.totalEquity), [1_000, 75])
        XCTAssertTrue(snapshot.currencyTotals.allSatisfy { !$0.fxMissing && !$0.fxStale })
    }

    func testMissingAccountFXHidesOnlyItsCurrencyGroup() throws {
        let snapshot = try fixture(accounts: [
            account(1, currency: "TWD", cash: 100, marketValue: 900),
            account(2, currency: "TWD", cash: 50, marketValue: 200, fxMissing: true),
            account(3, currency: "USD", cash: 5, marketValue: 70)
        ])
        let twd = try XCTUnwrap(snapshot.currencyTotals.first { $0.currency == "TWD" })
        XCTAssertEqual(twd.accountCount, 2)
        XCTAssertTrue(twd.fxMissing)
        XCTAssertNil(twd.totalEquity)
        XCTAssertNil(twd.totalCash)
        XCTAssertNil(twd.totalMarketValue)
        XCTAssertNil(twd.unrealizedPnl)
        XCTAssertNil(twd.realizedPnl)
        let usd = try XCTUnwrap(snapshot.currencyTotals.first { $0.currency == "USD" })
        XCTAssertFalse(usd.fxMissing)
        XCTAssertEqual(usd.totalEquity, 75)
    }

    func testAgedRatesRemainVisibleAndLimitationsStayWithTheirCurrency() throws {
        let snapshot = try fixture(accounts: [
            account(1, currency: "TWD", cash: -100, marketValue: 900,
                    fxStale: true, limitations: ["fx_and_cost_basis_partial"]),
            account(2, currency: "TWD", cash: 50, marketValue: 200,
                    limitations: ["fx_and_cost_basis_partial", "realtime_quote_best_effort"]),
            account(3, currency: "USD", cash: 5, marketValue: 70)
        ])
        let twd = try XCTUnwrap(snapshot.currencyTotals.first { $0.currency == "TWD" })
        XCTAssertTrue(twd.fxStale)
        XCTAssertFalse(twd.fxMissing)
        XCTAssertEqual(twd.totalCash, -50)
        XCTAssertEqual(twd.totalEquity, 1_050)
        XCTAssertEqual(Set(twd.limitations), ["fx_and_cost_basis_partial", "realtime_quote_best_effort"])
        XCTAssertEqual(twd.limitations.count, 2)
        XCTAssertTrue(try XCTUnwrap(snapshot.currencyTotals.first { $0.currency == "USD" }).limitations.isEmpty)
    }

    func testActualCNYAndOtherCurrenciesRemainDistinctAndOrdered() throws {
        let snapshot = try fixture(accounts: [
            account(1, currency: "JPY", cash: 20, marketValue: 80),
            account(2, currency: "CNY", cash: 40, marketValue: 160),
            account(3, currency: "USD", cash: 5, marketValue: 70),
            account(4, currency: "TWD", cash: 100, marketValue: 900)
        ])
        XCTAssertEqual(snapshot.currencyTotals.map(\.currency), ["TWD", "USD", "CNY", "JPY"])
        XCTAssertEqual(snapshot.currencyTotals.map(\.totalEquity), [1_000, 75, 200, 100])
    }

    func testNoAccountsDoesNotInventCNYCurrencyGroup() throws {
        XCTAssertTrue(try fixture(accounts: []).currencyTotals.isEmpty)
    }
}

private func account(
    _ id: Int, currency: String, cash: Double, marketValue: Double,
    unrealized: Double = 0, realized: Double = 0,
    fxMissing: Bool = false, fxStale: Bool = false, limitations: [String] = []
) -> [String: Any] {
    ["account_id": id, "account_name": "合成帳戶 \(id)", "market": currency == "TWD" ? "tw" : "us",
     "base_currency": currency, "total_cash": cash, "total_market_value": marketValue,
     "total_equity": cash + marketValue, "realized_pnl": realized, "unrealized_pnl": unrealized,
     "fx_missing": fxMissing, "fx_stale": fxStale, "data_quality": limitations.isEmpty ? "ok" : "partial",
     "limitations": limitations, "positions": []]
}

private func fixture(accounts: [[String: Any]], aggregateFXMissing: Bool = false) throws -> PortfolioSnapshot {
    let payload: [String: Any] = [
        "as_of": "2000-01-01", "cost_method": "fifo", "currency": "CNY", "account_count": accounts.count,
        "total_cash": 11_111, "total_market_value": 77_777, "total_equity": 88_888,
        "realized_pnl": 3_333, "unrealized_pnl": 4_444,
        "fx_missing": aggregateFXMissing, "fx_stale": aggregateFXMissing,
        "data_quality": "partial", "limitations": ["aggregate_only"], "accounts": accounts
    ]
    let decoder = JSONDecoder()
    decoder.keyDecodingStrategy = .convertFromSnakeCase
    return try decoder.decode(PortfolioSnapshot.self, from: JSONSerialization.data(withJSONObject: payload))
}
