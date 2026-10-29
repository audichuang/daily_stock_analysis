import Foundation
import XCTest
@testable import DSACore

final class TradingDayTests: XCTestCase {
    private var year: Int { Calendar(identifier: .gregorian).component(.year, from: Date()) - 1 }

    func testTradingDayLabelsStayOnTheirSourceDateRegardlessOfDeviceTimeZone() throws {
        let date = try XCTUnwrap(TradingDay.parse("\(year)-10-29"))
        let locale = Locale(identifier: "en_US_POSIX")
        XCTAssertEqual(date.formatted(TradingDay.readoutStyle(locale: locale)), "Oct 29, \(year)")
        XCTAssertEqual(date.formatted(TradingDay.axisStyle(locale: locale)), "10/29")
        XCTAssertEqual(TradingDay.readoutStyle().timeZone.secondsFromGMT(), 0)
        XCTAssertEqual(TradingDay.axisStyle().timeZone.secondsFromGMT(), 0)
        XCTAssertEqual(TradingDay.calendar.component(.hour, from: date), 0)
    }

    func testMonthRangesClampMonthEndAndKeepMidnightAcrossDaylightSavingChanges() throws {
        let februaryEnd = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0) ? 29 : 28
        let cases = [
            ("\(year)-03-31", 1, "\(year)-02-\(februaryEnd)"),
            ("\(year)-11-30", 1, "\(year)-10-30"),
            ("\(year)-05-31", 3, "\(year)-02-\(februaryEnd)"),
            ("\(year)-08-31", 6, "\(year)-02-\(februaryEnd)"),
            ("\(year)-01-31", 1, "\(year - 1)-12-31")
        ]
        for (latestValue, months, expectedValue) in cases {
            let latest = try XCTUnwrap(TradingDay.parse(latestValue))
            let expected = try XCTUnwrap(TradingDay.parse(expectedValue))
            let start = try XCTUnwrap(TradingDay.start(months: months, before: latest))
            XCTAssertEqual(start, expected, "\(latestValue), \(months)M")
            let previousDay = expected.addingTimeInterval(-86_400)
            XCTAssertLessThan(previousDay, start)
            XCTAssertGreaterThanOrEqual(expected, start)
            XCTAssertGreaterThan(latest, start)
        }
    }

    func testCandleBodyHasDailyWidthCenteredOnItsWickWithoutTouchingAdjacentDays() throws {
        let center = try XCTUnwrap(TradingDay.parse("\(year)-10-29"))
        let body = TradingDay.candleBody(around: center)
        let following = TradingDay.candleBody(around: center.addingTimeInterval(86_400))
        XCTAssertEqual(body.upperBound.timeIntervalSince(body.lowerBound), 56_160, accuracy: 0.001)
        XCTAssertEqual(center.timeIntervalSince(body.lowerBound), 28_080, accuracy: 0.001)
        XCTAssertEqual(body.upperBound.timeIntervalSince(center), 28_080, accuracy: 0.001)
        XCTAssertLessThan(body.upperBound, following.lowerBound)
    }
}
