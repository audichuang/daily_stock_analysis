import Foundation
import XCTest
@testable import DSACore

final class ResearchLibraryTests: XCTestCase {
    private let taipei = TimeZone(identifier: "Asia/Taipei")!
    /// 2000-01-15 12:00 台北。
    private let now = Date(timeIntervalSince1970: 947_908_800)

    func testSameDaySameStockMergesNewestFirstWithChangeSummary() throws {
        let days = ResearchLibrary.days([
            try item(3, code: "2330.TW", at: "2000-01-15T15:00:00.123456+08:00", action: "buy", score: 72),
            try item(2, code: "2317.TW", at: "2000-01-15T14:00:00+08:00", action: "watch", score: 50),
            try item(1, code: "2330.TW", at: "2000-01-15T09:00:00+08:00", action: "watch", score: 58)
        ], now: now, timeZone: taipei)
        XCTAssertEqual(days.count, 1)
        XCTAssertEqual(days[0].entries.map { $0.primary.id }, [3, 2], "保留新到舊，整併不重排")
        XCTAssertEqual(days[0].entries[0].earlier.map(\.id), [1])
        XCTAssertEqual(days[0].entries[0].changeSummary, "觀望 → 買進 · 評分 58 → 72")
        XCTAssertNil(days[0].entries[1].changeSummary, "單份沒有變化行")
    }

    func testUnchangedVersionsHaveNoChangeLine() throws {
        let days = ResearchLibrary.days([
            try item(2, code: "2330.TW", at: "2000-01-15T15:00:00+08:00", action: "watch", score: 58),
            try item(1, code: "2330.TW", at: "2000-01-15T09:00:00+08:00", action: "watch", score: 58)
        ], now: now, timeZone: taipei)
        XCTAssertEqual(days[0].entries.count, 1)
        XCTAssertNil(days[0].entries[0].changeSummary, "沒變就不能出現變化行")
    }

    func testChangeComparesActionEnumNotStoredLabel() throws {
        // 舊存檔標籤「減倉」與枚舉 reduce 是同一個動作，不算改變。
        let days = ResearchLibrary.days([
            try item(2, code: "2330.TW", at: "2000-01-15T15:00:00+08:00", action: "reduce", score: nil),
            try item(1, code: "2330.TW", at: "2000-01-15T09:00:00+08:00", action: nil, label: "減倉", score: nil)
        ], now: now, timeZone: taipei)
        XCTAssertNil(days[0].entries[0].changeSummary)
    }

    func testDifferentDaysStaySeparate() throws {
        let days = ResearchLibrary.days([
            try item(2, code: "2330.TW", at: "2000-01-15T09:00:00+08:00"),
            try item(1, code: "2330.TW", at: "2000-01-14T15:00:00+08:00")
        ], now: now, timeZone: taipei)
        XCTAssertEqual(days.map(\.key), ["2000-01-15", "2000-01-14"])
        XCTAssertEqual(days.map(\.title), ["今天", "昨天"])
        XCTAssertTrue(days.allSatisfy { $0.entries.count == 1 && $0.entries[0].earlier.isEmpty })
    }

    func testMarketReviewsMergeByRegionAndNeverWithStocks() throws {
        let days = ResearchLibrary.days([
            try item(3, code: "TWII", at: "2000-01-15T15:00:00+08:00", type: "market_review", region: "tw"),
            try item(2, code: "SPX", at: "2000-01-15T14:00:00+08:00", type: "market_review", region: "us"),
            try item(1, code: "TWII", at: "2000-01-15T09:00:00+08:00")
        ], now: now, timeZone: taipei)
        XCTAssertEqual(days[0].entries.map { $0.primary.id }, [3, 2, 1])
        XCTAssertTrue(days[0].entries[0].primary.isMarketReview)
    }

    func testMissingIdIsNotMergedAndBadDateGetsOwnGroup() throws {
        let days = ResearchLibrary.days([
            try item(nil, code: "2330.TW", at: "2000-01-15T15:00:00+08:00"),
            try item(1, code: "2330.TW", at: "2000-01-15T09:00:00+08:00"),
            try item(2, code: "2330.TW", at: nil)
        ], now: now, timeZone: taipei)
        XCTAssertEqual(days[0].entries.count, 2, "打不開的列不能把可開的報告藏起來")
        XCTAssertEqual(days[1].title, "日期未提供")
    }

    func testOlderDayTitlesIncludeWeekdayAndYearWhenDifferent() {
        XCTAssertEqual(ResearchLibrary.title(for: "2000-01-10", now: now, timeZone: taipei), "01/10（週一）")
        XCTAssertEqual(ResearchLibrary.title(for: "1999-12-31", now: now, timeZone: taipei), "1999/12/31（週五）")
    }

    func testConclusionPrefersOneSentenceAndFallsBackToSummary() throws {
        XCTAssertEqual(try item(1, code: "A", at: nil, oneSentence: "一句話", summary: "摘要").conclusion, "一句話")
        XCTAssertEqual(try item(1, code: "A", at: nil, oneSentence: "  ", summary: "摘要").conclusion, "摘要")
        XCTAssertNil(try item(1, code: "A", at: nil).conclusion)
    }

    private func item(_ id: Int?, code: String, at createdAt: String?, action: String? = nil, label: String? = nil, score: Int? = nil,
                      type: String? = nil, region: String? = nil, oneSentence: String? = nil, summary: String? = nil) throws -> HistoryItem {
        var payload: [String: Any] = ["query_id": "q\(id ?? 0)", "stock_code": code]
        payload["id"] = id
        payload["created_at"] = createdAt
        payload["action"] = action
        payload["action_label"] = label
        payload["sentiment_score"] = score
        payload["report_type"] = type
        payload["region"] = region
        payload["one_sentence"] = oneSentence
        payload["analysis_summary"] = summary
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(HistoryItem.self, from: JSONSerialization.data(withJSONObject: payload))
    }
}
