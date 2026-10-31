import Foundation
import XCTest
@testable import DSACore

final class IndicatorsTests: XCTestCase {
    private func candles(_ rows: [(Double, Double, Double, Double, Double?)]) throws -> [ChartCandle] {
        let start = try XCTUnwrap(TradingDay.parse("2025-01-01"))
        return rows.enumerated().map { index, row in
            ChartCandle(date: start.addingTimeInterval(Double(index) * 86_400), open: row.0, high: row.1, low: row.2, close: row.3, volume: row.4)
        }
    }

    func testEMAStartsFromSimpleAverageAndSmoothsAfterwards() {
        let values = Indicators.ema([1, 2, 3, 4], period: 3)
        XCTAssertNil(values[1])
        XCTAssertEqual(values[2], 2)
        XCTAssertEqual(values[3], 3, "4×0.5 + 2×0.5")
        XCTAssertEqual(Indicators.ema([1, 2], period: 3), [nil, nil])
    }

    func testBollingerUsesPopulationDeviation() throws {
        let band = try XCTUnwrap(Indicators.bollinger([2, 4, 4, 4, 5, 5, 7, 9], period: 8, width: 2).last ?? nil)
        XCTAssertEqual(band.middle, 5)
        XCTAssertEqual(band.upper, 9, accuracy: 1e-9)
        XCTAssertEqual(band.lower, 1, accuracy: 1e-9)
    }

    func testMACDSignalStartsOnlyAfterEnoughDIFValues() throws {
        let closes = (0..<40).map { Double($0) }
        let macd = Indicators.macd(closes)
        XCTAssertNil(macd[24])
        let firstDif = try XCTUnwrap(macd[25])
        XCTAssertNil(firstDif.dea, "DIF 只有一筆時還沒有訊號線")
        XCTAssertNotNil(macd[33]?.dea)
        // 等差上升的序列，DIF 收斂到固定值，DEA 追上後柱狀體趨近 0。
        XCTAssertEqual(try XCTUnwrap(macd[39]?.histogram), 0, accuracy: 1e-6)
    }

    func testKDFollowsRSVAndHoldsWhenRangeIsFlat() throws {
        let rows: [(Double, Double, Double, Double, Double?)] = [(10, 10, 10, 10, 1), (10, 12, 8, 12, 1), (12, 12, 12, 12, 1)]
        let kd = Indicators.kd(try candles(rows), period: 2)
        XCTAssertNil(kd[0])
        // RSV(1)=100 → K=50×2/3+100/3≈66.67，D=50×2/3+K/3≈55.56
        XCTAssertEqual(try XCTUnwrap(kd[1]).k, 200.0 / 3, accuracy: 1e-9)
        XCTAssertEqual(try XCTUnwrap(kd[1]).d, 500.0 / 9, accuracy: 1e-9)
        XCTAssertEqual(try XCTUnwrap(kd[2]).k, 200.0 / 3 * 2 / 3 + 100.0 / 3, accuracy: 1e-9, "收在兩根區間的最高，RSV=100")
    }

    func testRSIIsHundredWhenOnlyGainsAndFiftyWhenFlat() {
        XCTAssertEqual(Indicators.rsi([1, 2, 3, 4], period: 3).last ?? nil, 100)
        XCTAssertEqual(Indicators.rsi([5, 5, 5, 5], period: 3).last ?? nil, 50)
        let mixed = Indicators.rsi([1, 2, 1, 2], period: 3)
        XCTAssertEqual(mixed[3] ?? -1, 100 - 100 / (1 + (2.0 / 3) / (1.0 / 3)), accuracy: 1e-9)
    }

    func testCrossesDetectGoldenAndDeathInOrder() throws {
        let base = try candles(Array(repeating: (1, 1, 1, 1, nil), count: 4))
        func points(_ values: [Double]) -> [MovingAveragePoint] {
            zip(base, values).map { MovingAveragePoint(window: 1, date: $0.date, anchor: $0.anchor, value: $1) }
        }
        let crosses = KeyPoints.crosses(fast: points([1, 3, 3, 1]), slow: points([2, 2, 2, 2]))
        XCTAssertEqual(crosses.map(\.golden), [true, false])
        XCTAssertEqual(crosses.first?.date, base[1].date)
    }

    func testUnfilledGapsShrinkWhenPartlyFilledAndDropWhenFilled() throws {
        let rows: [(Double, Double, Double, Double, Double?)] = [
            (10, 10, 9, 10, 1),
            (12, 13, 12, 13, 1),         // 跳空上漲 10→12
            (13, 13, 11, 12, 1),         // 回補到 11，剩 10～11
            (12, 12, 11.5, 12, 1),
            (11.3, 11.4, 11.2, 11.3, 1)  // 跳空下跌 11.5→11.4，沒碰到 11 以下
        ]
        let gaps = KeyPoints.unfilledGaps(try candles(rows))
        XCTAssertEqual(gaps.map(\.up), [true, false])
        XCTAssertEqual(gaps.first.map { [$0.lower, $0.upper] }, [10, 11])
        XCTAssertEqual(gaps.last.map { [$0.lower, $0.upper] }, [11.4, 11.5])
        let filled = rows + [(11.3, 11.6, 11.3, 11.6, 1)]
        XCTAssertEqual(KeyPoints.unfilledGaps(try candles(filled)).map(\.up), [true], "下跌缺口被 11.6 回補後消失")
        let crash = rows + [(9, 9, 7, 7, 1)]
        XCTAssertFalse(KeyPoints.unfilledGaps(try candles(crash)).contains { $0.up }, "跌破 10 後上漲缺口已回補")
    }

    func testVolumeSpikeNeedsFullWindowAndYearRangeNeedsAYearOfData() throws {
        let rows: [(Double, Double, Double, Double, Double?)] = [(1, 1, 1, 1, 10), (1, 1, 1, 1, 10), (1, 1, 1, 1, 25), (1, 1, 1, 1, 15)]
        XCTAssertEqual(KeyPoints.volumeSpikes(try candles(rows), window: 2, ratio: 2).map(\.volume), [25])
        XCTAssertNil(KeyPoints.yearRange(try candles(rows)), "只有幾天資料時不能標成 52 週高低")
    }
}
