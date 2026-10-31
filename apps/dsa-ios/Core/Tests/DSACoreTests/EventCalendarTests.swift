import Foundation
import XCTest
@testable import DSACore

final class EventCalendarTests: XCTestCase {
    private func event(day: String, timezone: String = "America/New_York", status: String = "confirmed", kind: String = "release") throws -> CalendarEvent {
        let value: [String: Any] = ["id": "earnings-AAPL", "type": "earnings", "code": "AAPL", "name": "Apple", "date": day, "status": status, "detail": "盤後 EPS 1.20", "sourceUrl": "https://example.test", "timezone": timezone, "dateKind": kind]
        return try JSONDecoder().decode(CalendarEvent.self, from: JSONSerialization.data(withJSONObject: value))
    }

    func testCalendarKeepsSourceDateAcrossDeviceTimezones() throws {
        let now = Date()
        let calendar = EventCalendarDate.calendar
        let day = EventCalendarDate.key(now)
        let parsed = try XCTUnwrap(EventCalendarDate.parse(day))
        XCTAssertEqual(EventCalendarDate.key(parsed), day)
        let cells = EventCalendarDate.cells(now).compactMap { $0 }
        XCTAssertEqual(cells.first, EventCalendarDate.key(EventCalendarDate.monthStart(now)))
        XCTAssertEqual(cells.last, EventCalendarDate.key(EventCalendarDate.monthEnd(now)))
        XCTAssertEqual(cells.count, calendar.range(of: .day, in: .month, for: now)?.count)
        let snapshot = try event(day: day)
        XCTAssertEqual(snapshot.date, day)
        XCTAssertEqual(snapshot.timezoneLabel, "美東 ET")
    }

    func testSevenDayWarningUsesSourceMarketAndIncludesOnlyZeroThroughSeven() throws {
        // 相對於本次執行日的 UTC 04:30，美東仍可能是前一天；兩種夏令時間都應守住當地日期。
        let midnight = try XCTUnwrap(EventCalendarDate.parse(EventCalendarDate.key(Date())))
        let now = midnight.addingTimeInterval(30 * 60)
        let localDay = try XCTUnwrap(EventCalendarDate.parse(EventCalendarDate.key(now, timezone: "America/New_York")))
        for offset in [-1, 0, 6, 7, 8] {
            let date = try XCTUnwrap(EventCalendarDate.calendar.date(byAdding: .day, value: offset, to: localDay))
            let snapshot = try event(day: EventCalendarDate.key(date))
            XCTAssertEqual(snapshot.daysAway(now: now), offset)
            XCTAssertEqual(snapshot.isWithinSevenDays(now: now), (0...7).contains(offset))
        }
    }

    func testEstimatedAndStatutoryDatesNeverAppearConfirmed() throws {
        let day = EventCalendarDate.key(Date())
        XCTAssertEqual(try event(day: day, status: "estimated").statusLabel, "推估")
        XCTAssertEqual(try event(day: day, status: "confirmed", kind: "statutory_deadline").statusLabel, "法定期限")
        XCTAssertEqual(try event(day: day).statusLabel, "已確認")
    }
}
