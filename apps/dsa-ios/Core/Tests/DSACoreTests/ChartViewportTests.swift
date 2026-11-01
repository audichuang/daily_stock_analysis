import Foundation
import XCTest
@testable import DSACore

final class ChartViewportTests: XCTestCase {
    func testDomainAddsPaddingAroundBarsOnly() {
        let domain = ChartViewport.domain(barCount: 25)
        XCTAssertEqual(domain.lowerBound, -0.325, accuracy: 0.0001)
        XCTAssertEqual(domain.upperBound, 24.6, accuracy: 0.0001, "右側留白不超過一根 K 棒")
    }

    func testWeekendGapDoesNotAffectVisibleBarCount() throws {
        // 週五到週一差三天，換成序號後仍是相鄰兩根；一段含週末的視窗根數等於交易日數。
        let friday = try XCTUnwrap(TradingDay.parse("2026-10-30"))
        let monday = try XCTUnwrap(TradingDay.parse("2026-11-02"))
        let bars = ChartViewport.preferredBars(dates: [friday, monday], months: 1)
        XCTAssertEqual(bars, 2)
        let viewport = ChartViewport.initial(domain: ChartViewport.domain(barCount: 2), preferredBars: bars)
        XCTAssertEqual(viewport.visibleIndices(barCount: 2), 0..<2)
    }

    func testPreferredBarsCountsActualBarsWithinTheMonths() throws {
        let last = try XCTUnwrap(TradingDay.parse("2026-10-30"))
        let dates = (0..<200).reversed().map { last.addingTimeInterval(Double(-$0) * 86_400) }
        XCTAssertEqual(ChartViewport.preferredBars(dates: dates, months: 1), 31, "9/30～10/30")
        XCTAssertEqual(ChartViewport.preferredBars(dates: dates, months: 1_200), 200, "全部不超過實有根數")
        XCTAssertEqual(ChartViewport.preferredBars(dates: [], months: 3), 0)
    }

    func testPresetShowsExactlyThePreferredBarsAndTheLatestOne() {
        let viewport = ChartViewport.initial(domain: ChartViewport.domain(barCount: 300), preferredBars: 63)
        let visible = viewport.visibleIndices(barCount: 300)
        XCTAssertEqual(visible.count, 63)
        XCTAssertEqual(visible.last, 299, "最新一根要在畫面裡")
    }

    func testOneMonthPresetOnMonthlyCandlesStillShowsTwelveBars() {
        // Codex 重現過：1 個月視窗切到月 K，全部 K 棒不可見。
        let domain = ChartViewport.domain(barCount: 25)
        let viewport = ChartViewport.initial(domain: domain, preferredBars: 2)
        XCTAssertEqual(viewport.visibleIndices(barCount: 25).count, 12, "月 K 至少 12 根")
        XCTAssertEqual(viewport.end, domain.upperBound, accuracy: 0.0001)
    }

    func testPresetNeverExceedsAvailableHistory() {
        let domain = ChartViewport.domain(barCount: 5)
        let viewport = ChartViewport.initial(domain: domain, preferredBars: 60)
        XCTAssertEqual(viewport.start, domain.lowerBound, accuracy: 0.0001)
        XCTAssertEqual(viewport.end, domain.upperBound, accuracy: 0.0001)
    }

    func testSpreadingFingersNeverWidensTheWindow() {
        let domain = ChartViewport.domain(barCount: 1_000)
        let base = ChartViewport(start: domain.upperBound - 5, length: 5)
        let zoomedIn = ChartViewport.pinched(from: base, magnification: 1.1, domain: domain)
        XCTAssertLessThanOrEqual(zoomedIn.length, base.length)
        XCTAssertEqual(zoomedIn.end, base.end, accuracy: 0.0001, "右緣固定")
        let zoomedOut = ChartViewport.pinched(from: base, magnification: 0.5, domain: domain)
        XCTAssertEqual(zoomedOut.length, 10, accuracy: 0.0001)
        let huge = ChartViewport.pinched(from: base, magnification: 0.000_1, domain: domain)
        XCTAssertEqual(huge.start, domain.lowerBound, accuracy: 0.0001, "縮到最小就是整張圖")
    }

    func testPinchInStopsAtTwelveBars() {
        let domain = ChartViewport.domain(barCount: 1_000)
        let base = ChartViewport(start: domain.upperBound - 90, length: 90)
        let pinched = ChartViewport.pinched(from: base, magnification: 100, domain: domain)
        XCTAssertEqual(pinched.visibleIndices(barCount: 1_000).count, 12)
    }

    func testSelectionRoundsToNearestBarAndClamps() {
        XCTAssertEqual(ChartViewport.selectedIndex(4.4, barCount: 10), 4)
        XCTAssertEqual(ChartViewport.selectedIndex(4.6, barCount: 10), 5)
        XCTAssertEqual(ChartViewport.selectedIndex(-3, barCount: 10), 0)
        XCTAssertEqual(ChartViewport.selectedIndex(99, barCount: 10), 9)
        XCTAssertNil(ChartViewport.selectedIndex(nil, barCount: 10))
        XCTAssertNil(ChartViewport.selectedIndex(1, barCount: 0))
    }

    func testAxisTicksAreFixedMultiplesWithinTheSeries() {
        XCTAssertEqual(ChartViewport.axisTicks(barCount: 100, visibleLength: 40), [0, 10, 20, 30, 40, 50, 60, 70, 80, 90])
        XCTAssertEqual(ChartViewport.axisTicks(barCount: 2, visibleLength: 1), [0, 1])
        XCTAssertEqual(ChartViewport.axisTicks(barCount: 0, visibleLength: 40), [])
    }

    func testOscillatorDomainFollowsActualRangeAndKeepsZero() {
        let mixed = ChartViewport.oscillatorDomain(values: [-1, 3])
        XCTAssertEqual(mixed.lowerBound, -1.4, accuracy: 0.0001, "不對稱：下緣不被撐到 -3")
        XCTAssertEqual(mixed.upperBound, 3.4, accuracy: 0.0001)
        let positive = ChartViewport.oscillatorDomain(values: [2, 4])
        XCTAssertLessThan(positive.lowerBound, 0, "柱子從零軸起算，零軸要在範圍內")
        XCTAssertFalse(ChartViewport.oscillatorDomain(values: []).isEmpty)
    }

    func testVolumeUsesLotsOnlyForTaiwan() {
        XCTAssertEqual(VolumeDisplay.value(12_000, market: "tw"), 12)
        XCTAssertEqual(VolumeDisplay.unit(market: "tw"), "張")
        XCTAssertEqual(VolumeDisplay.value(12_000, market: "us"), 12_000)
        XCTAssertEqual(VolumeDisplay.unit(market: "us"), "股")
        XCTAssertEqual(VolumeDisplay.text(12_000, market: "tw"), "12 張")
    }

    func testLatestChangeComparesWithPreviousCloseNotOpen() throws {
        let first = try XCTUnwrap(TradingDay.parse("2026-10-29"))
        let second = try XCTUnwrap(TradingDay.parse("2026-10-30"))
        let older = ChartCandle(date: first, open: 90, high: 101, low: 89, close: 100, volume: nil)
        // 開低走高收紅 K，但收盤仍低於昨收：標籤要算跌。
        let latest = ChartCandle(date: second, open: 90, high: 96, low: 89, close: 95, volume: nil)
        XCTAssertEqual(CandleSeries.latestChange([latest, older]), -5)
        XCTAssertNil(CandleSeries.latestChange([latest]))
    }
}
