import Foundation
import XCTest
@testable import DSACore

final class StockListPresentationTests: XCTestCase {
    func testDisplayCodeStripsOnlyMarketSuffix() {
        XCTAssertEqual(StockCodeDisplay.display("2330.TW"), "2330")
        XCTAssertEqual(StockCodeDisplay.display("6488.TWO"), "6488")
        XCTAssertEqual(StockCodeDisplay.display("00631L.TW"), "00631L")
        XCTAssertEqual(StockCodeDisplay.display("AAPL.US"), "AAPL")
        XCTAssertEqual(StockCodeDisplay.display("AAPL"), "AAPL")
        XCTAssertEqual(StockCodeDisplay.display("BRK.B"), "BRK.B", "股別不是市場後綴")
    }

    func testTaiwanPutsNameFirstAndUSPutsTickerFirst() {
        assertTitles(StockRowTitles(code: "2330.TW", name: "台積電"), "台積電", "2330")
        assertTitles(StockRowTitles(code: "AAPL", name: "Apple"), "AAPL", "Apple")
        assertTitles(StockRowTitles(code: "2330.TW", name: "  "), "2330", nil)
        assertTitles(StockRowTitles(code: "AAPL", name: nil), "AAPL", nil)
    }

    func testOnlyNearLimitIsMarked() {
        XCTAssertEqual(LimitProximity.of(price: 109.5, limitUp: 110, limitDown: 90), .nearUp)
        XCTAssertEqual(LimitProximity.of(price: 110, limitUp: 110, limitDown: 90), .nearUp)
        XCTAssertEqual(LimitProximity.of(price: 90.5, limitUp: 110, limitDown: 90), .nearDown)
        XCTAssertNil(LimitProximity.of(price: 108, limitUp: 110, limitDown: 90), "漲 8% 還不算近漲停")
        XCTAssertNil(LimitProximity.of(price: 92, limitUp: 110, limitDown: 90))
        XCTAssertNil(LimitProximity.of(price: 190, limitUp: nil, limitDown: nil), "美股沒有漲跌停")
        XCTAssertNil(LimitProximity.of(price: nil, limitUp: 110, limitDown: 90))
    }

    func testRowWarnsOnlyOnExceptions() {
        XCTAssertNil(warning(stale: false, code: "2330.TW", sourceCode: "shioaji"))
        XCTAssertNil(warning(stale: nil, code: "AAPL", sourceCode: "yfinance"), "美股走 yfinance 是常態")
        XCTAssertNil(warning(stale: false, code: "AAPL", source: "yfinance(intraday,可能延迟)"))
        XCTAssertEqual(warning(stale: true, code: "2330.TW", sourceCode: "shioaji"), "價格過期")
        XCTAssertEqual(warning(stale: true, code: "AAPL", sourceCode: "yfinance"), "價格過期")
        XCTAssertEqual(warning(stale: true, code: "2330.TW", sourceCode: "yfinance"), "可能延遲", "台股降級時後端一律標 stale，不算過期")
        XCTAssertEqual(warning(stale: true, code: "2330.TW", source: "fallback"), "可能延遲", "舊後端只有 source")
        XCTAssertEqual(StockRowWarning.text(hasQuote: false, isStale: nil, sourceCode: nil, source: nil, code: "2330.TW"), "尚無報價")
    }

    func testReportDateOnlyShownWhenOld() {
        let now = date("2026-11-10T12:00:00Z")
        let zone = TimeZone(secondsFromGMT: 0)!
        XCTAssertNil(ReportAge.staleLabel(createdAt: "2026-11-10T08:00:00", now: now, timeZone: zone))
        XCTAssertNil(ReportAge.staleLabel(createdAt: "2026-11-05 18:00:00", now: now, timeZone: zone), "剛好 5 天不算舊")
        XCTAssertEqual(ReportAge.staleLabel(createdAt: "2026-11-04T18:00:00+08:00", now: now, timeZone: zone), "6 天前")
        XCTAssertEqual(ReportAge.staleLabel(createdAt: "2026-09-01", now: now, timeZone: zone), "2 個月前")
        XCTAssertEqual(ReportAge.staleLabel(createdAt: "2024-01-31T13:30:00+08:00", now: now, timeZone: zone), "2 年前")
        XCTAssertNil(ReportAge.staleLabel(createdAt: nil, now: now, timeZone: zone))
        XCTAssertNil(ReportAge.staleLabel(createdAt: "壞資料", now: now, timeZone: zone))
    }

    func testAmountAndSignedNumberFormat() {
        XCTAssertEqual(StockListFormat.amount(7_410_000_000), "74.1 億")
        XCTAssertEqual(StockListFormat.amount(25_000), "2.5 萬")
        XCTAssertEqual(StockListFormat.amount(0), "0", "0 是讀數")
        XCTAssertEqual(StockListFormat.amount(nil), "—")
        XCTAssertEqual(StockListFormat.signedNumber(1.5), "+1.5")
        XCTAssertEqual(StockListFormat.signedNumber(-1.5), "\u{2212}1.5")
        XCTAssertEqual(StockListFormat.signedNumber(0), "0")
    }

    func testSortKeepsMissingValuesLastInBothDirections() {
        let entries = [entry("A", change: 1), entry("B", change: nil), entry("C", change: -3), entry("D", change: 2)]
        XCTAssertEqual(codes(StockSort(key: .changePercent, ascending: false), entries), ["D", "A", "C", "B"])
        XCTAssertEqual(codes(StockSort(key: .changePercent, ascending: true), entries), ["C", "A", "D", "B"])
        XCTAssertEqual(codes(.biggestMove, entries), ["C", "D", "A", "B"], "異動大看絕對值")
        XCTAssertEqual(codes(.custom, entries), ["A", "B", "C", "D"], "自訂保留伺服器順序")
    }

    func testSortIsStableAndTreatsNonFiniteAsMissing() {
        let entries = [entry("A", change: 1), entry("B", change: .nan), entry("C", change: 1)]
        XCTAssertEqual(codes(StockSort(key: .changePercent, ascending: false), entries), ["A", "C", "B"])
    }

    func testHeaderTapCyclesAndStorageRoundTrips() {
        let first = StockSort.custom.tapped(.price)
        XCTAssertEqual(first, StockSort(key: .price, ascending: false))
        let second = first.tapped(.price)
        XCTAssertEqual(second, StockSort(key: .price, ascending: true))
        XCTAssertEqual(second.tapped(.price), .custom)
        XCTAssertEqual(second.tapped(.name), StockSort(key: .name, ascending: true), "名稱第一下遞增")
        XCTAssertEqual(StockSort(storage: second.storage), second)
        XCTAssertNil(StockSort(storage: "unknown:desc"))
        XCTAssertNil(StockSort(storage: "price"))
    }

    func testSwitchingMetricOnlyMovesSortWhenSortedByMetric() {
        let byChange = StockSort(key: .changePercent, ascending: true)
        XCTAssertEqual(byChange.switching(to: .amount), StockSort(key: .amount, ascending: true))
        let byPrice = StockSort(key: .price, ascending: false)
        XCTAssertEqual(byPrice.switching(to: .amount), byPrice)
        XCTAssertEqual(StockSort.custom.switching(to: .volumeRatio), .custom)
    }

    func testSummaryCountsChangesActionsAndLatestAcrossZones() {
        let summary = StockListSummary(
            entries: [entry("A", change: 1), entry("B", change: -1), entry("C", change: 0), entry("D", change: nil), entry("E", change: 2)],
            actions: [.buy, .hold, .watch, .reduce, nil],
            quoteTimes: ["2026-01-02T13:30:00+08:00", "2026-01-02T05:40:00+00:00", nil]
        )
        XCTAssertEqual(summary.up, 2)
        XCTAssertEqual(summary.down, 1)
        XCTAssertEqual(summary.flat, 1, "沒有報價不算平盤")
        XCTAssertEqual(summary.actionCount, 2, "續抱與觀望不算動作")
        XCTAssertEqual(summary.latestQuoteAt, "2026-01-02T05:40:00+00:00", "13:40 台北比 13:30 台北新，不是字串比大小")
    }

    func testContentStatesAreMutuallyExclusive() {
        XCTAssertEqual(state(codes: 0, loaded: false), .loading)
        XCTAssertEqual(state(codes: 0, loaded: true), .empty)
        XCTAssertEqual(state(codes: 0, loaded: true, list: "x"), .failed("x"), "失敗不能顯示成沒有自選")
        XCTAssertEqual(state(codes: 3, loaded: true), .ready(nil))
        XCTAssertEqual(state(codes: 3, loaded: true, list: "x"), .ready(.refreshFailed("x")), "有舊資料不蓋掉清單")
        XCTAssertEqual(state(codes: 3, loaded: true, quote: "y"), .ready(.quotesFailed("y")))
        XCTAssertEqual(state(codes: 3, loaded: true, missing: 1), .ready(.partialQuotes(1)))
        XCTAssertEqual(state(codes: 3, loaded: true, quote: "y", missing: 3), .ready(.quotesFailed("y")), "整批失敗不報成部分缺價")
    }

    func testMarketPhaseLabelsOnlyKnownValues() {
        XCTAssertEqual(MarketPhaseLabel.text("intraday"), "盤中")
        XCTAssertEqual(MarketPhaseLabel.text("non_trading"), "休市")
        XCTAssertNil(MarketPhaseLabel.text("unknown"))
        XCTAssertNil(MarketPhaseLabel.text(nil))
    }

    func testAssetSummaryPrefersConsolidatedAndNeverRelabelsCNY() throws {
        let consolidated = try snapshot(extra: #""display_currency":"TWD","consolidated_equity_base":1575000,"consolidated_day_pnl_base":-1500,"consolidated_fx_missing":false"#)
        XCTAssertEqual(consolidated.todayAssetSummary,
                       TodayAssetSummary(currency: "TWD", equity: 1_575_000, dayPnl: -1_500, consolidated: true))

        let withFunds = try snapshot(extra: #""display_currency":"TWD","consolidated_equity_base":1575000,"consolidated_day_pnl_base":-1500,"consolidated_fund_value_base":200000,"consolidated_fund_day_pnl_base":500,"consolidated_fx_missing":false"#)
        XCTAssertEqual(withFunds.todayAssetSummary,
                       TodayAssetSummary(currency: "TWD", equity: 1_775_000, dayPnl: -1_000, consolidated: true), "基金口徑要與資產頁相同")

        let missingFx = try snapshot(extra: #""display_currency":"TWD","consolidated_equity_base":null,"consolidated_fx_missing":true"#)
        XCTAssertEqual(missingFx.todayAssetSummary,
                       TodayAssetSummary(currency: "TWD", equity: 1_000, dayPnl: nil, consolidated: true), "換算失敗不給今日損益")

        let oldServer = try snapshot(extra: nil)
        XCTAssertEqual(oldServer.todayAssetSummary?.currency, "TWD", "舊後端頂層是 CNY，不能拿來當總資產")
        XCTAssertEqual(oldServer.todayAssetSummary?.equity, 1_000)

        XCTAssertNil(try snapshot(extra: nil, accounts: "[]").todayAssetSummary, "沒有帳戶不顯示資產卡")
    }

    func testHeldKeysMatchWithOrWithoutMarketSuffixAndSkipClosedPositions() throws {
        let value = try snapshot(extra: nil)
        XCTAssertTrue(value.heldKeys.contains(StockHoldings.key("2330.TW")))
        XCTAssertTrue(value.heldKeys.contains(StockHoldings.key("2330")))
        XCTAssertFalse(value.heldKeys.contains(StockHoldings.key("2317.TW")), "數量 0 的已出清不算持股")
    }

    func testIndicesSnapshotDecodesMarketStatusAndOldServerShape() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let current = try decoder.decode(MarketIndicesSnapshot.self, from: Data(#"{"items":[{"code":"TWII","name":"加權","current":1,"change":0,"change_pct":0,"source":null,"source_code":null,"as_of":null}],"region":"tw","market_phase":"intraday","market_open":true}"#.utf8))
        XCTAssertEqual(current.marketPhase, "intraday")
        XCTAssertEqual(current.marketOpen, true)
        let old = try decoder.decode(MarketIndicesSnapshot.self, from: Data(#"{"items":[]}"#.utf8))
        XCTAssertNil(old.marketPhase)
        XCTAssertNil(old.marketOpen)
    }

    // MARK: - helpers

    private func assertTitles(_ value: StockRowTitles, _ primary: String, _ secondary: String?, line: UInt = #line) {
        XCTAssertEqual(value.primary, primary, line: line)
        XCTAssertEqual(value.secondary, secondary, line: line)
    }

    private func warning(stale: Bool?, code: String, sourceCode: String? = nil, source: String? = nil) -> String? {
        StockRowWarning.text(hasQuote: true, isStale: stale, sourceCode: sourceCode, source: source, code: code)
    }

    private func date(_ value: String) -> Date {
        ISO8601DateFormatter().date(from: value)!
    }

    private func entry(_ code: String, change: Double?) -> StockListEntry {
        StockListEntry(code: code, changePercent: change)
    }

    private func codes(_ sort: StockSort, _ entries: [StockListEntry]) -> [String] {
        sort.apply(to: entries).map(\.code)
    }

    private func state(codes: Int, loaded: Bool, list: String? = nil, quote: String? = nil, missing: Int = 0) -> StockListContentState {
        .resolve(codeCount: codes, hasLoaded: loaded, listError: list, quoteError: quote, missingQuotes: missing)
    }

    private func snapshot(extra: String?, accounts: String? = nil) throws -> PortfolioSnapshot {
        let position = #"{"symbol":"%@","market":"tw","currency":"TWD","quantity":%@,"avg_cost":1,"total_cost":1,"last_price":1,"market_value_base":1,"unrealized_pnl_base":0,"price_source":"x","price_stale":false,"price_available":true,"data_quality":"ok","limitations":[]}"#
        let held = String(format: position, "2330.TW", "1000")
        let closed = String(format: position, "2317.TW", "0")
        let account = #"[{"account_id":1,"account_name":"a","market":"tw","base_currency":"TWD","total_cash":100,"total_market_value":900,"total_equity":1000,"realized_pnl":0,"unrealized_pnl":0,"data_quality":"ok","limitations":[],"positions":[\#(held),\#(closed)]}]"#
        let extraField = extra.map { "," + $0 } ?? ""
        let json = #"{"as_of":"2026-01-01","cost_method":"fifo","currency":"CNY","account_count":1,"total_cash":1,"total_market_value":2,"total_equity":3,"realized_pnl":0,"unrealized_pnl":0,"fx_stale":false,"data_quality":"ok","limitations":[],"accounts":\#(accounts ?? account)\#(extraField)}"#
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(PortfolioSnapshot.self, from: Data(json.utf8))
    }
}
