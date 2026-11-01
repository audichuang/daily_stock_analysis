import Foundation
import XCTest
@testable import DSACore

final class IntradaySeriesTests: XCTestCase {
    func testUSSessionUsesNewYorkHoursAndKeepsOnlyTheLastDay() throws {
        let series = try XCTUnwrap(IntradaySeries(points: [
            TrendPoint(t: "2026-10-29T15:55:00-04:00", price: 92),
            TrendPoint(t: "2026-10-30T09:30:00-04:00", price: 65.3),
            TrendPoint(t: "2026-10-30T15:55:00-04:00", price: 65.88),
            TrendPoint(t: "壞掉的時間", price: 1)
        ], market: "us"))
        XCTAssertEqual(series.sessionDay, "2026-10-30", "UTC 已是 10/31，交易日仍是紐約 10/30")
        XCTAssertEqual(series.points.map(\.price), [65.3, 65.88])
        XCTAssertEqual(series.session.lowerBound, IntradaySeries.parse("2026-10-30T09:30:00-04:00"))
        XCTAssertEqual(series.session.upperBound, IntradaySeries.parse("2026-10-30T16:00:00-04:00"))
    }

    func testTaiwanSessionAndFractionalSeconds() throws {
        let series = try XCTUnwrap(IntradaySeries(points: [
            TrendPoint(t: "2026-10-30T09:00:00.123456+08:00", price: 2375),
            TrendPoint(t: "2026-10-30T13:20:00+08:00", price: 2365)
        ], market: "tw"))
        XCTAssertEqual(series.points.count, 2)
        XCTAssertEqual(series.session.upperBound, IntradaySeries.parse("2026-10-30T13:30:00+08:00"))
    }

    func testEmptyOrUnknownMarketHasNoSeries() {
        XCTAssertNil(IntradaySeries(points: [], market: "tw"))
        XCTAssertNil(IntradaySeries(points: [TrendPoint(t: "2026-10-30T09:00:00+08:00", price: 1)], market: "mars"))
    }

    func testTrendDecodesSnakeCase() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let json = #"{"stock_code":"INTC","range":"day","source":"yfinance(intraday,可能延迟)","points":[{"t":"2026-10-30T09:30:00-04:00","price":65.3}]}"#
        let trend = try decoder.decode(StockTrend.self, from: Data(json.utf8))
        XCTAssertEqual(trend.stockCode, "INTC")
        XCTAssertEqual(trend.points.first?.price, 65.3)
    }

    func testPreviousCloseIsTheLastDailyCloseBeforeTheSessionDay() throws {
        let series = try XCTUnwrap(IntradaySeries(points: [TrendPoint(t: "2026-10-30T15:55:00-04:00", price: 65.88)], market: "us"))
        let daily = [
            TrendPoint(t: "2026-10-28", price: 95.53),
            TrendPoint(t: "2026-10-30", price: 65.76),
            TrendPoint(t: "2026-10-29", price: 92.07),
            TrendPoint(t: "2026-10-31T00:00:00+08:00", price: 1)
        ]
        XCTAssertEqual(series.previousClose(from: daily), 92.07, "取 10/30 之前最後一根，不是當天、也不是陣列最後一筆")
        XCTAssertNil(series.previousClose(from: [TrendPoint(t: "2026-10-30", price: 65.76)]), "沒有更早的日線就不給昨收，不拿別天湊")
    }

    func testTrendDecodesVolumeAndAveragePriceAndStaysCompatibleWithoutThem() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let json = #"{"stock_code":"2330.TW","range":"day","source":null,"points":[{"t":"2026-10-30T09:00:00+08:00","price":100,"volume":3000,"avg_price":99.5},{"t":"2026-10-30T09:05:00+08:00","price":101}]}"#
        let trend = try decoder.decode(StockTrend.self, from: Data(json.utf8))
        XCTAssertEqual(trend.points[0].volume, 3000)
        XCTAssertEqual(trend.points[0].avgPrice, 99.5)
        XCTAssertNil(trend.points[1].volume)
        let series = try XCTUnwrap(IntradaySeries(points: trend.points, market: "tw"))
        XCTAssertEqual(series.points[0].avgPrice, 99.5)
        XCTAssertEqual(series.volumeBars.count, 1, "沒有量的點不畫量柱，也不當成 0")
        XCTAssertEqual(series.asOf, IntradaySeries.parse("2026-10-30T09:05:00+08:00"))
    }

    func testVolumeBarChangeComparesWithPreviousPoint() throws {
        let series = try XCTUnwrap(IntradaySeries(points: [
            TrendPoint(t: "2026-10-30T09:00:00+08:00", price: 100, volume: 1),
            TrendPoint(t: "2026-10-30T09:05:00+08:00", price: 102, volume: 1),
            TrendPoint(t: "2026-10-30T09:10:00+08:00", price: 101, volume: 1)
        ], market: "tw"))
        XCTAssertEqual(series.volumeBars.map(\.change), [0, 2, -1])
    }

    func testPriceScaleCentersOnPreviousCloseForOrdinaryDays() throws {
        let series = try XCTUnwrap(IntradaySeries(points: [
            TrendPoint(t: "2026-10-30T09:00:00+08:00", price: 101),
            TrendPoint(t: "2026-10-30T09:05:00+08:00", price: 103)
        ], market: "tw"))
        let scale = series.priceScale(previousClose: 100)
        XCTAssertTrue(scale.centered)
        XCTAssertEqual((scale.domain.lowerBound + scale.domain.upperBound) / 2, 100, accuracy: 0.0001, "昨收在正中央")
        XCTAssertTrue(scale.ticks.contains(100))
        XCTAssertTrue(scale.domain.contains(103))
        XCTAssertTrue(scale.domain.contains(101))
    }

    func testPriceScaleFallsBackOnlyForLargeGapThatFlattensTheDay() throws {
        // INTC 10/30：昨收 92、當日 65 附近。以昨收為中軸會把走勢壓成一條線。
        let gapDay = try XCTUnwrap(IntradaySeries(points: [
            TrendPoint(t: "2026-10-30T09:30:00-04:00", price: 65.3),
            TrendPoint(t: "2026-10-30T15:55:00-04:00", price: 65.88)
        ], market: "us"))
        let gapScale = gapDay.priceScale(previousClose: 92.07)
        XCTAssertFalse(gapScale.centered)
        XCTAssertFalse(gapScale.domain.contains(92.07))

        // 反向：跳空不到 3% 時，走勢再平也維持中軸，不能把一般的小缺口當大跳空。
        let smallGap = try XCTUnwrap(IntradaySeries(points: [
            TrendPoint(t: "2026-10-30T09:00:00+08:00", price: 99),
            TrendPoint(t: "2026-10-30T09:05:00+08:00", price: 99.05)
        ], market: "tw"))
        XCTAssertTrue(smallGap.priceScale(previousClose: 100).centered)

        // 反向：跳空大但當天波動也大，中軸看得清楚，不退回。
        let volatile = try XCTUnwrap(IntradaySeries(points: [
            TrendPoint(t: "2026-10-30T09:00:00+08:00", price: 104),
            TrendPoint(t: "2026-10-30T09:05:00+08:00", price: 110)
        ], market: "tw"))
        XCTAssertTrue(volatile.priceScale(previousClose: 100).centered)
    }

    func testPriceScaleWithoutPreviousCloseUsesTheDayRange() throws {
        let series = try XCTUnwrap(IntradaySeries(points: [TrendPoint(t: "2026-10-30T09:00:00+08:00", price: 100)], market: "tw"))
        let scale = series.priceScale(previousClose: nil)
        XCTAssertFalse(scale.centered)
        XCTAssertTrue(scale.domain.contains(100))
        XCTAssertEqual(scale.ticks.count, 4)
    }

    func testAxisTicksSpanTheWholeSession() throws {
        let series = try XCTUnwrap(IntradaySeries(points: [TrendPoint(t: "2026-10-30T10:00:00+08:00", price: 100)], market: "tw"))
        XCTAssertEqual(series.axisTicks.first, IntradaySeries.parse("2026-10-30T09:00:00+08:00"))
        XCTAssertEqual(series.axisTicks.last, IntradaySeries.parse("2026-10-30T13:30:00+08:00"))
        XCTAssertEqual(series.axisTicks.count, 3)
    }
}
