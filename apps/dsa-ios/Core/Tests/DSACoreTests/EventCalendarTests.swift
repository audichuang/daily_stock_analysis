import Foundation
import XCTest
@testable import DSACore

final class EventCalendarTests: XCTestCase {
    private func event(day: String, timezone: String = "America/New_York", status: String = "confirmed", kind: String = "release") throws -> CalendarEvent {
        let value: [String: Any] = ["id": "earnings-AAPL", "type": "earnings", "code": "AAPL", "name": "Apple", "date": day, "status": status, "detail": "盤後 EPS 1.20", "sourceUrl": "https://example.test", "timezone": timezone, "dateKind": kind]
        return try JSONDecoder().decode(CalendarEvent.self, from: JSONSerialization.data(withJSONObject: value))
    }

    func testDeviceTodayFollowsDeviceTimezoneNotEastern() throws {
        // 台北 11/1 06:00＝UTC／美東仍是 10/31，月曆要開 11 月。
        var parts = DateComponents(year: 2026, month: 10, day: 31, hour: 22)
        parts.timeZone = TimeZone(secondsFromGMT: 0)
        let now = try XCTUnwrap(Calendar(identifier: .gregorian).date(from: parts))
        XCTAssertEqual(EventCalendarDate.deviceToday(now: now, timeZone: try XCTUnwrap(TimeZone(identifier: "Asia/Taipei"))), "2026-11-01")
        XCTAssertEqual(EventCalendarDate.deviceToday(now: now, timeZone: try XCTUnwrap(TimeZone(identifier: "America/New_York"))), "2026-10-31")
    }

    func testUpcomingCompanyEventsSkipsPastAndLimits() throws {
        var parts = DateComponents(year: 2026, month: 11, day: 2, hour: 1)
        parts.timeZone = TimeZone(secondsFromGMT: 0)
        let now = try XCTUnwrap(Calendar(identifier: .gregorian).date(from: parts))
        let events = try ["2026-11-01", "2026-11-05", "2026-11-03", "2026-11-09"].map { try event(day: $0, timezone: "Asia/Taipei") }
        XCTAssertEqual(events.upcomingCompanyEvents(limit: 2, now: now).map(\.date), ["2026-11-03", "2026-11-05"])
    }

    func testNextCompanyEventUsesEventTimezoneForPastDates() throws {
        // 台北 11/2 09:00＝美東 11/1 20:00。
        var parts = DateComponents(year: 2026, month: 11, day: 2, hour: 1)
        parts.timeZone = TimeZone(secondsFromGMT: 0)
        let now = try XCTUnwrap(Calendar(identifier: .gregorian).date(from: parts))
        let yesterdayTaipei = try event(day: "2026-11-01", timezone: "Asia/Taipei")
        let nextTaipei = try event(day: "2026-11-03", timezone: "Asia/Taipei")
        XCTAssertEqual([yesterdayTaipei, nextTaipei].nextCompanyEvent(now: now)?.date, "2026-11-03")
        // 同一天的 11/1 對美東仍是今天，不可被排除。
        let todayEastern = try event(day: "2026-11-01")
        XCTAssertEqual([todayEastern, nextTaipei].nextCompanyEvent(now: now)?.date, "2026-11-01")
        let deadline = try event(day: "2026-11-02", timezone: "Asia/Taipei", kind: "statutory_deadline")
        XCTAssertEqual([deadline, nextTaipei].nextCompanyEvent(now: now)?.date, "2026-11-03")
    }

    func testUpcomingQueryRangeStartsFromEarliestMarketDate() throws {
        // 台北 11/1 08:00 = 美東 10/31 20:00（夏令時間）。
        let now = try XCTUnwrap(ISO8601DateFormatter().date(from: "2026-11-01T00:00:00Z"))
        let taipei = try XCTUnwrap(TimeZone(identifier: "Asia/Taipei"))
        let range = try XCTUnwrap(EventCalendarDate.upcomingQueryRange(now: now, days: 45, deviceTimeZone: taipei))
        XCTAssertEqual(range.from, "2026-10-31")
        XCTAssertEqual(range.to, "2026-12-15")
        // 台北下午美東也已同日時，下界不能再往前多退一天。
        let later = try XCTUnwrap(ISO8601DateFormatter().date(from: "2026-11-01T06:00:00Z"))
        XCTAssertEqual(EventCalendarDate.upcomingQueryRange(now: later, days: 45, deviceTimeZone: taipei)?.from, "2026-11-01")
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
