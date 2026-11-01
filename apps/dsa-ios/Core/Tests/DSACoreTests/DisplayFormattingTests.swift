import XCTest
@testable import DSACore

final class DisplayFormattingTests: XCTestCase {
    private let taipei = TimeZone(identifier: "Asia/Taipei")!

    private func date(_ year: Int, _ month: Int, _ day: Int, _ hour: Int = 0, _ minute: Int = 0) -> Date {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = taipei
        return calendar.date(from: DateComponents(year: year, month: month, day: day, hour: hour, minute: minute))!
    }

    func testSummaryMoneyTWDIsWholeWithPrefix() {
        XCTAssertEqual(DisplayFormatting.summaryMoney(3450907.48, currency: "TWD"), "NT$3,450,907")
        XCTAssertEqual(DisplayFormatting.summaryMoney(-1234.4, currency: "twd"), "\u{2212}NT$1,234")
    }

    func testSummaryMoneyUSDHasTwoDecimals() {
        XCTAssertEqual(DisplayFormatting.summaryMoney(12345.6, currency: "USD"), "US$12,345.60")
        XCTAssertEqual(DisplayFormatting.summaryMoney(0.004, currency: "USD"), "US$0.00")
    }

    func testSummaryMoneyMissingValue() {
        XCTAssertEqual(DisplayFormatting.summaryMoney(nil, currency: "TWD"), DisplayNumber.noValue)
        XCTAssertEqual(DisplayFormatting.summaryMoney(.nan, currency: "USD"), DisplayNumber.noValue)
    }

    func testRelativeDays() {
        let now = Date()
        let calendar: Calendar = {
            var value = Calendar(identifier: .gregorian)
            value.timeZone = taipei
            return value
        }()
        func plus(_ days: Int) -> Date { calendar.date(byAdding: .day, value: days, to: now)! }
        XCTAssertEqual(DisplayFormatting.relativeDays(from: now, to: now, timeZone: taipei), "今天")
        XCTAssertEqual(DisplayFormatting.relativeDays(from: now, to: plus(1), timeZone: taipei), "明天")
        XCTAssertEqual(DisplayFormatting.relativeDays(from: now, to: plus(3), timeZone: taipei), "3 天後")
        XCTAssertEqual(DisplayFormatting.relativeDays(from: now, to: plus(-1), timeZone: taipei), "昨天")
        XCTAssertEqual(DisplayFormatting.relativeDays(from: now, to: plus(-4), timeZone: taipei), "4 天前")
    }

    func testRelativeDaysCountsCalendarDaysNotHours() {
        // 23:50 to 00:10 the next day is only 20 minutes, but it is still「明天」.
        XCTAssertEqual(
            DisplayFormatting.relativeDays(from: date(2030, 3, 4, 23, 50), to: date(2030, 3, 5, 0, 10), timeZone: taipei),
            "明天"
        )
    }

    func testShortDateAndStamp() {
        // 2026-10-30 is a Friday.
        XCTAssertEqual(DisplayFormatting.shortDate(date(2026, 10, 30), timeZone: taipei), "10/30（五）")
        XCTAssertEqual(DisplayFormatting.shortStamp(date(2026, 10, 30, 13, 33), timeZone: taipei), "10/30 13:33")
        XCTAssertEqual(DisplayFormatting.shortStamp(date(2026, 1, 5, 9, 5), timeZone: taipei), "1/5 09:05")
    }

    func testPriceDecimalsByBand() {
        XCTAssertEqual(DisplayFormatting.priceDecimals(1085), 0)
        XCTAssertEqual(DisplayFormatting.priceDecimals(500), 0)
        XCTAssertEqual(DisplayFormatting.priceDecimals(120), 1)
        XCTAssertEqual(DisplayFormatting.priceDecimals(50), 1)
        XCTAssertEqual(DisplayFormatting.priceDecimals(23.45), 2)
        XCTAssertEqual(DisplayFormatting.priceDecimals(nil), 2)
    }
}
