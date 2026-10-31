import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif
import XCTest
@testable import DSACore

final class DSACoreTests: XCTestCase {
    private var session: URLSession!
    private var client: DSAClient!

    func testReportNewsUsesExactAnalysisAndDecodesAdditiveFields() async throws {
        StubURLProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/api/v1/history/101/news")
            let query = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)?.queryItems ?? []
            XCTAssertTrue(query.contains(URLQueryItem(name: "analysis_only", value: "true")))
            XCTAssertTrue(query.contains(URLQueryItem(name: "limit", value: "100")))
            return (200, #"{"total":1,"items":[{"title":"新聞","snippet":"摘要","url":"https://example.test","source":"官方","published_date":null,"dimension":"announcements"}]}"#)
        }
        let response = try await client.reportNews(101)
        XCTAssertEqual(response.total, 1)
        XCTAssertEqual(response.items.first?.sourceLabel, "官方")
        XCTAssertNil(response.items.first?.dateLabel)
        XCTAssertTrue(response.items.first?.isNews == true)
    }

    override func setUpWithError() throws {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [StubURLProtocol.self]
        session = URLSession(configuration: configuration)
        client = try DSAClient(baseURL: URL(string: "https://market.example.test")!, session: session)
    }

    override func tearDown() {
        session.invalidateAndCancel()
        StubURLProtocol.handler = nil
    }

    func testServerURLTrustBoundary() throws {
        for address in ["http://market.example.test", "http://192.168.1.5:7777", "ftp://market.example.test", "https://user:password@market.example.test", "https://market.example.test?token=secret", "https://market.example.test#fragment"] {
            XCTAssertThrowsError(try DSAClient(baseURL: URL(string: address)!, session: session), address)
        }
        XCTAssertNoThrow(try DSAClient(baseURL: URL(string: "https://market.example.test:8443/dsa")!, session: session))
        #if DEBUG
        XCTAssertNoThrow(try DSAClient(baseURL: URL(string: "http://127.0.0.1:9999")!, session: session))
        #else
        XCTAssertThrowsError(try DSAClient(baseURL: URL(string: "http://127.0.0.1:9999")!, session: session))
        #endif
    }

    func testAuthUsesCamelCaseContractAndJSONPassword() async throws {
        StubURLProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/api/v1/auth/status")
            return (200, #"{"authEnabled":true,"loggedIn":false,"passwordSet":true,"passwordChangeable":true,"setupState":"enabled"}"#)
        }
        let status = try await client.authStatus()
        XCTAssertTrue(status.authEnabled)
        XCTAssertFalse(status.loggedIn)
        StubURLProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/api/v1/auth/login")
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Content-Type"), "application/json")
            let payload = try body(request)
            XCTAssertEqual(payload["password"] as? String, "fixture secret & 中文")
            return (200, #"{"ok":true}"#)
        }
        try await client.login(password: "fixture secret & 中文")
    }

    func testAnalysisRequestNeverSendsNotificationAndDoesNotRetryPost() async throws {
        var calls = 0
        StubURLProtocol.handler = { request in
            calls += 1
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/v1/analysis/analyze")
            let payload = try body(request)
            XCTAssertEqual(payload["stock_code"] as? String, "00631L.TW")
            XCTAssertEqual(payload["async_mode"] as? Bool, true)
            XCTAssertEqual(payload["notify"] as? Bool, false)
            XCTAssertEqual(payload["report_language"] as? String, "zh-TW")
            return (503, #"{"detail":{"error":"model_unavailable","message":"模型目前無法使用"}}"#)
        }
        do {
            _ = try await client.startAnalysis("00631L.TW")
            XCTFail("失敗的分析不能回報成功")
        } catch let error as DSAError {
            XCTAssertEqual(error.localizedDescription, "模型目前無法使用")
        }
        XCTAssertEqual(calls, 1)
    }

    func testLogoutAcceptsEmpty204ButPreservesServerFailure() async throws {
        StubURLProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/api/v1/auth/logout")
            XCTAssertEqual(request.httpMethod, "POST")
            return (204, "")
        }
        try await client.logout()
        StubURLProtocol.handler = { _ in (500, #"{"error":"internal_error","message":"Failed to invalidate session"}"#) }
        do {
            try await client.logout()
            XCTFail("登出失敗不可回報成功")
        } catch let error as DSAError {
            XCTAssertEqual(error.localizedDescription, "Failed to invalidate session")
        }
    }

    func testQuoteBatchKeepsMissingValueAndRealZeroDistinct() async throws {
        StubURLProtocol.handler = { request in
            let components = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)!
            XCTAssertEqual(components.queryItems?.first?.value, "2330.TW,6488.TWO")
            return (200, #"{"items":[{"stock_code":"2330.TW","quote":{"stock_code":"2330.TW","stock_name":"台積電","current_price":1000,"change":0,"change_percent":0,"volume":0,"source":"fallback","as_of":"2026-01-02T13:30:00+08:00","is_stale":true},"error":null},{"stock_code":"6488.TWO","quote":null,"error":"no_data"}]}"#)
        }
        let quotes = try await client.quotes(["2330.TW", "6488.TWO"])
        XCTAssertEqual(quotes[0].quote?.changePercent, 0)
        XCTAssertEqual(quotes[0].quote?.volume, 0)
        XCTAssertEqual(quotes[0].quote?.isStale, true)
        XCTAssertNil(quotes[0].quote?.bestBid)
        XCTAssertNil(quotes[1].quote)
        XCTAssertEqual(quotes[1].error, "no_data")
    }

    func testQuotesRespectServerFiftyCodeLimit() async throws {
        var sizes: [Int] = []
        StubURLProtocol.handler = { request in
            let query = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)!.queryItems!
            sizes.append(query.first(where: { $0.name == "codes" })!.value!.split(separator: ",").count)
            return (200, #"{"items":[]}"#)
        }
        _ = try await client.quotes((0..<51).map { "S\($0)" })
        XCTAssertEqual(sizes, [50, 1])
    }

    func testCalendarDecodesSourceURLTimezoneAndDeadlineContract() async throws {
        let today = EventCalendarDate.key(Date())
        StubURLProtocol.handler = { _ in
            (200, #"{"events":[{"id":"earnings-BRK.B","type":"earnings","code":"BRK.B","name":"Berkshire","date":"\#(today)","status":"confirmed","detail":"盤前","source_url":"https://example.test/source","timezone":"America/New_York","date_kind":"release","updated_at":null},{"id":"tw-deadline","type":"financial_deadline","code":null,"name":"台股財報期限","date":"\#(today)","status":"confirmed","detail":"不代表實際發布日","source_url":"https://example.test/law","timezone":"Asia/Taipei","date_kind":"statutory_deadline","updated_at":null}],"undated":[],"cache_updated_at":null}"#)
        }
        let result = try await client.calendarEvents(from: today, to: today)
        XCTAssertEqual(result.events.first?.sourceUrl, "https://example.test/source")
        XCTAssertEqual(result.events.first?.date, today)
        XCTAssertEqual(result.events.first?.timezoneLabel, "美東 ET")
        XCTAssertEqual(result.events.last?.statusLabel, "法定期限")
        XCTAssertNil(result.events.last?.code)
    }

    func testCalendarReadsCacheRangeAndDecodesUndatedWithoutInventingDate() async throws {
        let start = EventCalendarDate.key(Date())
        let end = EventCalendarDate.key(Date().addingTimeInterval(7 * 86400))
        StubURLProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/api/v1/calendar/events")
            let query = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)!.queryItems!
            XCTAssertEqual(query.first { $0.name == "from" }?.value, start)
            XCTAssertEqual(query.first { $0.name == "to" }?.value, end)
            XCTAssertEqual(query.first { $0.name == "code" }?.value, "BRK.B")
            return (200, #"{"events":[],"undated":[{"code":"BRK.B","name":"Berkshire","detail":"未提供日期"}],"cache_updated_at":null}"#)
        }
        let value = try await client.calendarEvents(from: start, to: end, code: "BRK.B")
        XCTAssertTrue(value.events.isEmpty)
        XCTAssertEqual(value.undated.first?.code, "BRK.B")
        XCTAssertNil(value.cacheUpdatedAt)
    }

    func testProfilePreservesEvidenceRiskAndInvalidation() async throws {
        StubURLProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/api/v1/stocks/2330.TW/profile")
            return (200, profileFixture)
        }
        let profile = try await client.stockProfile("2330.TW")
        XCTAssertEqual(profile.quote.status, "unavailable")
        XCTAssertNil(profile.quote.data)
        XCTAssertEqual(profile.history.data.first?.close, 101)
        let artifact = try XCTUnwrap(profile.research.data.structuredReport)
        XCTAssertEqual(artifact.thesis.reasons, ["營收成長"])
        XCTAssertEqual(artifact.thesis.risks, ["估值偏高"])
        XCTAssertEqual(artifact.evidence.first?.freshness, "stale")
        XCTAssertEqual(artifact.invalidationConditions.first?.description, "跌破支撐重新評估")
        XCTAssertEqual(artifact.dataQuality.missingBlocks, ["institutional"])
    }

    func testHistoryUsesNumericRecordAndKeepsTextPriceRanges() async throws {
        StubURLProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/api/v1/history/12")
            return (200, #"{"meta":{"id":12,"query_id":"batch-shared","stock_code":"2330.TW"},"summary":{"analysis_summary":"等待確認","sentiment_score":null,"action_label":"觀望"},"strategy":{"ideal_buy":"900–920","stop_loss":"跌破 880 再評估"},"structured_report":null}"#)
        }
        let report = try await client.report(12)
        XCTAssertEqual(report.meta.id, 12)
        XCTAssertNil(report.summary.sentimentScore)
        XCTAssertEqual(report.strategy?.idealBuy, "900–920")
    }

    func testStockIndexDecodesBothPublishedFormatsAndSuffixes() async throws {
        StubURLProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/stocks.index.json")
            return (200, #"[["00631L.TW","00631L","元大台灣50正2",null,null,[],"TW","etf",true,10],["6488.TWO","6488","環球晶",null,null,["環球晶圓"],"TW","stock",true,null]]"#)
        }
        let tupleItems = try await client.stockIndex()
        XCTAssertEqual(tupleItems[0].canonicalCode, "00631L.TW")
        XCTAssertEqual(tupleItems[1].aliases, ["環球晶圓"])
        StubURLProtocol.handler = { _ in
            (200, #"[{"canonicalCode":"AAPL","displayCode":"AAPL","nameZh":"蘋果","market":"US","assetType":"stock","active":true}]"#)
        }
        let objects = try await client.stockIndex()
        XCTAssertEqual(objects.first?.canonicalCode, "AAPL")
        XCTAssertEqual(objects.first?.aliases, [])
    }

    func testHTTPErrorEnvelopeAndAuthenticationExpiry() async throws {
        StubURLProtocol.handler = { _ in (401, #"{"error":"unauthorized","message":"請登入"}"#) }
        do {
            _ = try await client.watchlist()
            XCTFail("401 不能變成空自選")
        } catch let error as DSAError {
            XCTAssertTrue(error.requiresLogin)
            XCTAssertEqual(error.localizedDescription, "請登入")
        }
    }

    func testMalformedPayloadIsVisibleFailure() async throws {
        StubURLProtocol.handler = { _ in (200, #"{"items":[{"stock_code":"2330.TW","quote":{"stock_code":"2330.TW","current_price":"not a price"}}]}"#) }
        do {
            _ = try await client.quotes(["2330.TW"])
            XCTFail("格式錯誤不能轉成假行情")
        } catch let error as DSAError {
            guard case .decoding = error else { return XCTFail("應回格式錯誤") }
        }
    }

    func testBasePathAndDynamicSegmentCannotChangeEndpoint() async throws {
        let nestedClient = try DSAClient(baseURL: URL(string: "https://market.example.test/dsa/")!, session: session)
        StubURLProtocol.handler = { request in
            XCTAssertEqual(request.url?.absoluteString, "https://market.example.test/dsa/api/v1/analysis/status/a%2Fb%3Fadmin=true")
            return (200, #"{"task_id":"a/b?admin=true","status":"failed","progress":null,"error":"測試"}"#)
        }
        let task = try await nestedClient.taskStatus("a/b?admin=true")
        XCTAssertEqual(task.status, "failed")
        XCTAssertNil(task.progress)
    }
}

private final class StubURLProtocol: URLProtocol {
    static var handler: ((URLRequest) throws -> (Int, String))?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        do {
            let handler = try XCTUnwrap(Self.handler)
            let (status, json) = try handler(request)
            let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: "HTTP/1.1", headerFields: ["Content-Type": "application/json"])!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: Data(json.utf8))
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}

private func body(_ request: URLRequest) throws -> [String: Any] {
    var data = request.httpBody ?? Data()
    if data.isEmpty, let stream = request.httpBodyStream {
        stream.open()
        defer { stream.close() }
        let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: 1024)
        defer { buffer.deallocate() }
        while stream.hasBytesAvailable {
            let count = stream.read(buffer, maxLength: 1024)
            if count <= 0 { break }
            data.append(buffer, count: count)
        }
    }
    return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
}

private let profileFixture = #"""
{
  "requested_code":"2330.TW","canonical_code":"2330.TW","market":"tw","as_of":"2026-01-02",
  "quote":{"status":"unavailable","data":null,"limitations":["報價暫缺"]},
  "history":{"status":"fresh","period":"daily","data":[{"date":"2026-01-02","open":100,"high":102,"low":99,"close":101,"volume":1000}],"limitations":[]},
  "research":{"status":"partial","limitations":[],"data":{"latest_report":null,"recent_reports":[],"structured_report":{
    "schema_version":"research-artifact-v1","artifact_id":"report-12","source_report_id":12,
    "subject":{"stock_code":"2330.TW","stock_name":"台積電","market":"tw"},
    "thesis":{"direction":"neutral","summary":"等待確認","reasons":["營收成長"],"risks":["估值偏高"],"confidence":null},
    "evidence":[{"id":"revenue","source_type":"fundamental","title":"月營收","source":"TWSE","freshness":"stale","quality_level":"limited","as_of":"2026-01-01"}],
    "invalidation_conditions":[{"id":"support","category":"price","description":"跌破支撐重新評估","severity":"warning","threshold":"90"}],
    "next_actions":[{"action":"watch","label":"觀察支撐"}],
    "data_quality":{"level":"limited","source_count":1,"stale_count":1,"missing_blocks":["institutional"],"limitations":["法人資料暫缺"]}
  }}},
  "evidence_quality":{"status":"partial","blocks":{"quote":"unavailable"},"limitations":["報價暫缺"]}
}
"""#
