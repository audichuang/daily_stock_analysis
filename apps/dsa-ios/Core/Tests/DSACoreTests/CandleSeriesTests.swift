import Foundation
import XCTest
@testable import DSACore

final class CandleSeriesTests: XCTestCase {
    private var year: Int { Calendar(identifier: .gregorian).component(.year, from: Date()) - 1 }

    private func candle(_ day: String, open: Double, high: Double, low: Double, close: Double, volume: Double? = 100) throws -> ChartCandle {
        ChartCandle(date: try XCTUnwrap(TradingDay.parse(day)), open: open, high: high, low: low, close: close, volume: volume)
    }

    func testWeeklyAggregationStartsOnMondayAndKeepsFirstOpenLastCloseExtremesAndVolumeSum() throws {
        // 2025-12-29（一）到 2026-01-02（五）跨年仍是同一週；2026-01-05（一）起是下一週。
        let daily = [
            try candle("2026-01-05", open: 20, high: 21, low: 19, close: 20.5),
            try candle("2025-12-29", open: 10, high: 12, low: 9, close: 11, volume: 100),
            try candle("2025-12-31", open: 11, high: 15, low: 10, close: 14, volume: nil),
            try candle("2026-01-02", open: 14, high: 14.5, low: 8, close: 13, volume: 300)
        ]
        let weeks = CandleSeries.aggregate(daily, period: .week)
        XCTAssertEqual(weeks.count, 2)
        let first = try XCTUnwrap(weeks.first)
        XCTAssertEqual(first.periodStart, TradingDay.parse("2025-12-29"))
        XCTAssertEqual(first.date, TradingDay.parse("2026-01-02"))
        XCTAssertEqual([first.open, first.high, first.low, first.close], [10, 15, 8, 13])
        XCTAssertEqual(first.volume, 400, "缺量的那天不算 0 也不讓整週變成缺量")
        XCTAssertEqual(weeks.last?.periodStart, TradingDay.parse("2026-01-05"))
    }

    func testMonthlyAggregationSplitsOnCalendarMonthAndDayPeriodOnlySorts() throws {
        let daily = [
            try candle("\(year)-03-03", open: 5, high: 6, low: 4, close: 5.5),
            try candle("\(year)-02-27", open: 3, high: 4, low: 2, close: 3.5),
            try candle("\(year)-02-03", open: 1, high: 2, low: 0.5, close: 1.5)
        ]
        let months = CandleSeries.aggregate(daily, period: .month)
        XCTAssertEqual(months.map(\.open), [1, 5])
        XCTAssertEqual(months.map(\.close), [3.5, 5.5])
        XCTAssertEqual(months.first?.low, 0.5)
        XCTAssertEqual(CandleSeries.aggregate(daily, period: .day).map(\.close), [1.5, 3.5, 5.5])
    }

    func testMovingAverageSkipsIncompleteWindowAndAveragesTrailingCloses() throws {
        let closes: [Double] = [1, 2, 3, 4, 5]
        let candles = try closes.enumerated().map { index, close in
            try candle("\(year)-03-0\(index + 1)", open: close, high: close, low: close, close: close)
        }
        let ma3 = CandleSeries.movingAverage(candles, window: 3)
        XCTAssertEqual(ma3.map(\.value), [2, 3, 4])
        XCTAssertEqual(ma3.first?.date, candles[2].date, "均線點落在窗口最後一根，不提早出現")
        XCTAssertTrue(CandleSeries.movingAverage(candles, window: 6).isEmpty)
        XCTAssertEqual(CandleSeries.movingAverage(candles, window: 1).map(\.value), closes)
    }

    func testCandleBodyWidthScalesWithPeriodSpan() throws {
        let center = try XCTUnwrap(TradingDay.parse("\(year)-10-29"))
        let week = TradingDay.candleBody(around: center, spanDays: 7)
        XCTAssertEqual(week.upperBound.timeIntervalSince(week.lowerBound), 86_400 * 7 * 0.65, accuracy: 0.001)
        XCTAssertEqual(center.timeIntervalSince(week.lowerBound), week.upperBound.timeIntervalSince(center), accuracy: 0.001)
    }

    func testMonthlySelectionAndAnchorStayInsideTheirOwnMonth() throws {
        let daily = [
            try candle("2025-12-01", open: 1, high: 1, low: 1, close: 1),
            try candle("2025-12-31", open: 2, high: 2, low: 2, close: 2),
            try candle("2026-01-02", open: 3, high: 3, low: 3, close: 3),
            try candle("2026-01-30", open: 4, high: 4, low: 4, close: 4)
        ]
        let months = CandleSeries.aggregate(daily, period: .month)
        let january = try XCTUnwrap(months.last)
        XCTAssertEqual(january.anchor, TradingDay.parse("2026-01-16"), "月 K 畫在當月中間，不以月底為中心")
        let tenth = try XCTUnwrap(TradingDay.parse("2026-01-10"))
        XCTAssertEqual(CandleSeries.nearest(to: tenth, in: months)?.close, 4, "1/10 要選到一月，不是離月底較近的十二月")
        let ma = CandleSeries.movingAverage(months, window: 1)
        XCTAssertEqual(ma.last?.anchor, january.anchor)
        XCTAssertEqual(try candle("2026-01-02", open: 1, high: 1, low: 1, close: 1).anchor, TradingDay.parse("2026-01-02"))
    }

    func testProvisionalDayMarksItsWholeWeek() throws {
        let daily = [
            try candle("2026-10-26", open: 90, high: 92, low: 88, close: 90.5),
            ChartCandle(date: try XCTUnwrap(TradingDay.parse("2026-10-30")), open: 68, high: 69, low: 63, close: 65.76, volume: 1, isProvisional: true)
        ]
        XCTAssertEqual(CandleSeries.aggregate(daily, period: .week).map(\.isProvisional), [true])
        XCTAssertEqual(CandleSeries.aggregate(daily, period: .day).map(\.isProvisional), [false, true])
    }
}
