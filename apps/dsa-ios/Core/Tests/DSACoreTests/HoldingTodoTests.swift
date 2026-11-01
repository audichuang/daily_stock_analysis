import Foundation
import XCTest
@testable import DSACore

final class HoldingTodoTests: XCTestCase {
    private func signal(_ code: String, action: String, stop: Double? = nil, close: Double? = nil,
                        triggered: Bool? = nil, held: Bool? = true, status: String? = nil) -> DecisionSignalSummary {
        DecisionSignalSummary(stockCode: code, stockName: nil, action: action, isHeld: held,
                              stopLoss: stop, stopTriggered: triggered, lastClose: close, status: status)
    }

    func testClosedAndExpiredSignalsAreNotTodos() {
        let items = [
            signal("1101.TW", action: "reduce", status: "closed"),
            signal("2303.TW", action: "sell", status: "expired"),
            signal("2330.TW", action: "sell", status: "active"),
            signal("2454.TW", action: "reduce"),
        ]
        XCTAssertEqual(HoldingTodo.build(items: items).items.map(\.code), ["2330.TW", "2454.TW"])
    }

    func testDecisionSignalQueryCarriesStatus() {
        let withStatus = DSAClient.decisionSignalQuery(holdingOnly: true, groupLatest: true, sort: "priority",
                                                       status: "active", pageSize: 100)
        XCTAssertTrue(withStatus.contains(URLQueryItem(name: "status", value: "active")))
        let without = DSAClient.decisionSignalQuery(holdingOnly: true, groupLatest: true, sort: nil,
                                                    status: nil, pageSize: 100)
        XCTAssertFalse(without.contains { $0.name == "status" })
    }

    func testMarketReviewTitleFollowsReportName() {
        XCTAssertEqual(ReportText.marketReviewTitle(stockName: "美股大盤複盤"), "美股大盤複盤")
        XCTAssertEqual(ReportText.marketReviewTitle(stockName: "  "), "大盤複盤")
        XCTAssertEqual(ReportText.marketReviewTitle(stockName: nil), "大盤複盤")
    }

    func testOrderIsStopTriggeredThenNearStopThenReduceOrSell() {
        // Codes are deliberately in reverse alphabetical order of urgency so a code sort fails.
        let items = [
            signal("1101.TW", action: "reduce", stop: 50, close: 60, triggered: false),
            signal("2303.TW", action: "hold", stop: 44.5, close: 45.6, triggered: false),
            signal("9999.TW", action: "sell", stop: 102, close: 100, triggered: true),
        ]
        let list = HoldingTodo.build(items: items)
        XCTAssertEqual(list.items.map(\.code), ["9999.TW", "2303.TW", "1101.TW"])
        XCTAssertEqual(list.items.map(\.kind), [.stopTriggered, .nearStop, .reduceOrSell])
        XCTAssertEqual(list.total, 3)
    }

    func testNearStopIsClosestFirstAndOnlyWithinThreePercent() {
        let items = [
            signal("1000.TW", action: "hold", stop: 97.5, close: 100, triggered: false),  // −2.5%
            signal("2000.TW", action: "hold", stop: 99, close: 100, triggered: false),    // −1.0%
            signal("3000.TW", action: "hold", stop: 96, close: 100, triggered: false),    // −4.0%: not a todo
            signal("4000.TW", action: "buy", stop: nil, close: 100),                      // no stop, not reduce
        ]
        let list = HoldingTodo.build(items: items)
        XCTAssertEqual(list.items.map(\.code), ["2000.TW", "1000.TW"])
        XCTAssertEqual(list.total, 2)
        XCTAssertEqual(list.signalTotal, 4)
    }

    func testTruncatesToThreeAndReportsTotal() {
        let items = (1...5).map { signal("\(1000 + $0).TW", action: "reduce") }
        let list = HoldingTodo.build(items: items, signalTotal: 10)
        XCTAssertEqual(list.items.count, 3)
        XCTAssertEqual(list.total, 5)
        XCTAssertEqual(list.signalTotal, 10)
        // Ties keep server (priority) order.
        XCTAssertEqual(list.items.map(\.code), ["1001.TW", "1002.TW", "1003.TW"])
    }

    func testEmptyWhenNothingToDoAndExplicitlyNotHeldIsSkipped() {
        let list = HoldingTodo.build(items: [
            signal("2330.TW", action: "hold", stop: 500, close: 600, triggered: false),
            signal("2317.TW", action: "sell", held: false),
        ])
        XCTAssertTrue(list.items.isEmpty)
        XCTAssertEqual(list.total, 0)
    }

    func testStopText() {
        let triggered = HoldingTodo.build(items: [signal("3380.TW", action: "sell", stop: 72, close: 70, triggered: true)]).items[0]
        XCTAssertEqual(triggered.stopText, "已跌破 72")
        XCTAssertTrue(triggered.isStopWarning)
        let near = HoldingTodo.build(items: [signal("5469.TW", action: "reduce", stop: 97.9, close: 100, triggered: false)]).items[0]
        XCTAssertEqual(near.kind, .nearStop)
        XCTAssertEqual(near.stopText, "離停損 \u{2212}2.1%")
        let reduce = HoldingTodo.build(items: [signal("2330.TW", action: "reduce")]).items[0]
        XCTAssertNil(reduce.stopText)
        XCTAssertFalse(reduce.isStopWarning)
    }

    func testDecodesSampleResponse() throws {
        let json = """
        {"items": [
          {"id": 900, "stock_code": "3380.TW", "stock_name": "明泰", "market": "tw", "source_type": "analysis",
           "trigger_source": "scheduled", "action": "sell", "action_label": "賣出", "stop_loss": 72.0,
           "plan_quality": "complete", "status": "active", "older_count": 2, "is_held": true,
           "stop_triggered": true, "last_close": 70.5, "last_close_date": "2026-10-30"},
          {"id": 901, "stock_code": "5469.TW", "stock_name": "瀚宇博", "market": "tw", "source_type": "analysis",
           "trigger_source": "scheduled", "action": "reduce", "stop_loss": null, "plan_quality": "partial",
           "status": "active", "is_held": true, "stop_triggered": null, "last_close": null}
        ], "total": 10, "page": 1, "page_size": 100}
        """
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let response = try decoder.decode(DecisionSignalListResponse.self, from: Data(json.utf8))
        XCTAssertEqual(response.total, 10)
        XCTAssertEqual(response.items.first?.stockName, "明泰")
        XCTAssertEqual(response.items.first?.stopTriggered, true)
        XCTAssertEqual(response.items.first?.lastClose, 70.5)
        XCTAssertNil(response.items.last?.stopLoss)
        let list = HoldingTodo.build(items: response.items, signalTotal: response.total)
        XCTAssertEqual(list.items.map(\.code), ["3380.TW", "5469.TW"])
        XCTAssertEqual(list.signalTotal, 10)
    }
}
