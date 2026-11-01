import Foundation
import XCTest
@testable import DSACore

final class ReportNewsTests: XCTestCase {
    private func item(_ fields: [String: Any] = [:]) throws -> ReportNewsItem {
        let values: [String: Any] = ["title": "新聞標題", "snippet": "一般摘要", "url": "https://example.test/news"]
            .merging(fields) { _, new in new }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(ReportNewsItem.self, from: JSONSerialization.data(withJSONObject: values))
    }

    func testEventAnchorIsNewsNotReference() throws {
        XCTAssertTrue(try item(["dimension": "event_anchor", "title": "Why Intel stock moved"]).isNews)
        XCTAssertFalse(try item(["dimension": "event_anchor_x", "title": "未知面向"]).isNews)
    }

    func testClassificationUsesOnlyDimensionIncludingUnknownAndOldAPI() throws {
        for dimension in ["latest_news", "announcements", "risk_check"] {
            XCTAssertTrue(try item(["dimension": dimension, "title": "IBISWorld 資料頁"]).isNews)
        }
        for dimension in ["earnings", "market_analysis", "industry", "unknown", ""] {
            XCTAssertFalse(try item(["dimension": dimension, "title": "最新新聞 官方公告 8-K"]).isNews)
        }
        let old = try item()
        XCTAssertFalse(old.isNews)
        XCTAssertNil(old.dateLabel)
        XCTAssertEqual(old.sourceLabel, "example.test")
    }

    func testSortingUsesPublicationDateAndPutsUnknownLastStably() throws {
        let older = try item(["title": "較早", "published_date": "2024-01-29T16:00:00Z"])
        let newer = try item(["title": "較新", "published_date": "2024-01-31T00:00:00+08:00"])
        let unknown = try item(["title": "未知"])
        let invalid = try item(["title": "無效", "published_date": "不是日期"])
        XCTAssertEqual(ReportNewsItem.newestFirst([unknown, older, invalid, newer]).map(\.title), ["較新", "較早", "未知", "無效"])
        XCTAssertEqual(newer.dateLabel, "2024-01-31")
        XCTAssertEqual(try item(["published_date": "2024-01-31"]).dateLabel, "2024-01-31")
        XCTAssertEqual(try item(["published_date": "2024-01-31T00:00:00"]).dateLabel, "2024-01-31")
        XCTAssertEqual(try item(["published_date": "2024-01-31T00:00:00.123456"]).dateLabel, "2024-01-31")
        XCTAssertNil(invalid.dateLabel)
    }

    func testSummaryRemovesInternalNoteAndMarkdownButKeepsOrdinaryProse() throws {
        let text = "【DeepSeek 搜尋日期未經原文核實；日級日期非精確發布時間】**營收** [改善](https://example.test)"
        XCTAssertEqual(try item(["snippet": text]).summary, "營收 改善")
        XCTAssertEqual(try item(["snippet": "【公司公告】營收改善"]).summary, "【公司公告】營收改善")
        XCTAssertEqual(try item(["snippet": "| 季度 | 營收 |\n| --- | --- |\n| Q3 | 100 | "]).summary, "")
        XCTAssertEqual(try item(["snippet": "EX-99.1 2 intc-ex991.htm 原始財報文件"]).summary, "")
        XCTAssertEqual(try item(["snippet": "<!DOCTYPE html><html>原始文件</html>"]).summary, "")
        XCTAssertEqual(try item(["snippet": "<p>可讀的摘要</p>"]).summary, "可讀的摘要")
        XCTAssertEqual(try item(["snippet": "摘要\n```json\n{\"raw_document\":true}\n```\n補充內容"]).summary, "摘要 補充內容")
        XCTAssertEqual(try item(["snippet": "```json\n{\"raw_document\":true}"]).summary, "")
    }

    func testSECDocumentTitleDoesNotInventFormOrEarnings() throws {
        XCTAssertEqual(try item(["title": "Document", "url": "https://www.sec.gov/Archives/intc-8k.htm"]).displayTitle, "SEC 8-K 公告")
        XCTAssertEqual(try item(["title": "Document", "url": "https://www.sec.gov/Archives/intc-ex991.htm"]).displayTitle, "SEC 官方文件")
        XCTAssertEqual(try item(["title": "Document", "url": "https://news.test/doc"]).displayTitle, "Document")
        XCTAssertEqual(try item(["title": "英特爾公布第三季結果", "url": "https://www.sec.gov/Archives/intc-8k.htm"]).displayTitle, "英特爾公布第三季結果")
    }

    func testExternalLinksAllowHTTPOnlyAndKeepUnsafeTitlesReadable() throws {
        for url in ["javascript:alert(1)", "file:///tmp/news", "data:text/html,test", "no-url:key", "https://user:pass@example.test/news", "https:missing-host"] {
            let row = try item(["url": url])
            XCTAssertNil(row.externalURL, url)
            XCTAssertEqual(row.displayTitle, "新聞標題")
        }
        for url in ["http://example.test/news", "https://example.test/news"] {
            XCTAssertEqual(try item(["url": url]).externalURL?.absoluteString, url)
        }
    }

    func testEarningsCountsAsNewsOnlyWithPublishedDate() throws {
        func item(_ date: String?) throws -> ReportNewsItem {
            var value: [String: Any] = ["title": "t", "snippet": "s", "url": "https://a.test/1", "dimension": "earnings"]
            if let date { value["publishedDate"] = date }
            return try JSONDecoder().decode(ReportNewsItem.self, from: JSONSerialization.data(withJSONObject: value))
        }
        XCTAssertTrue(try item("2026-10-30").isNews)
        XCTAssertFalse(try item(nil).isNews)
    }
}
