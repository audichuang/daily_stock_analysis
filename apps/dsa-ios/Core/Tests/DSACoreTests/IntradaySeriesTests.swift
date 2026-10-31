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
}
