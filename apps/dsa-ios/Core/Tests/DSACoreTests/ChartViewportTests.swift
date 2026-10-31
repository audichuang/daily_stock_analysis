import Foundation
import XCTest
@testable import DSACore

final class ChartViewportTests: XCTestCase {
    private let day: TimeInterval = 86_400
    private let month: TimeInterval = 30.44 * 86_400

    private func monthlyDomain() throws -> (ClosedRange<Date>, Date) {
        let first = try XCTUnwrap(TradingDay.parse("2024-08-16"))
        let last = try XCTUnwrap(TradingDay.parse("2026-10-15"))
        return (ChartViewport.domain(firstAnchor: first, lastAnchor: last, spanDays: 30), last)
    }

    func testOneMonthPresetOnMonthlyCandlesStillShowsTheLatestBars() throws {
        // Codex 重現：1M 視窗切到月 K，右側留白比視窗寬，25 根月 K 全部不可見。
        let (domain, lastAnchor) = try monthlyDomain()
        let viewport = ChartViewport.initial(domain: domain, preferred: month, spanDays: 30)
        XCTAssertTrue((viewport.start...viewport.end).contains(lastAnchor), "最新一根要在畫面裡")
        XCTAssertEqual(viewport.length, 360 * day, accuracy: 1, "月 K 至少 12 根")
        XCTAssertEqual(viewport.end, domain.upperBound)
        XCTAssertLessThanOrEqual(domain.upperBound.timeIntervalSince(lastAnchor), 30 * day, "右側留白不超過一根 K 棒")
    }

    func testPresetNeverExceedsAvailableHistory() throws {
        let (domain, _) = try monthlyDomain()
        let viewport = ChartViewport.initial(domain: domain, preferred: 60 * month, spanDays: 30)
        XCTAssertEqual(viewport.start, domain.lowerBound)
        XCTAssertEqual(viewport.end, domain.upperBound)
    }

    func testSpreadingFingersNeverWidensTheWindow() throws {
        // Codex 重現：1M 週 K 張開 10%，被 84 天下限撐寬成 84 天。
        let last = try XCTUnwrap(TradingDay.parse("2026-10-28"))
        let domain = ChartViewport.domain(firstAnchor: last.addingTimeInterval(-1_500 * day), lastAnchor: last, spanDays: 7)
        let base = ChartViewport(start: domain.upperBound.addingTimeInterval(-month), length: month)
        let zoomedIn = ChartViewport.pinched(from: base, magnification: 1.1, domain: domain, spanDays: 7)
        XCTAssertLessThanOrEqual(zoomedIn.length, base.length)
        XCTAssertEqual(zoomedIn.end, base.end, "右緣固定")
        let zoomedOut = ChartViewport.pinched(from: base, magnification: 0.5, domain: domain, spanDays: 7)
        XCTAssertEqual(zoomedOut.length, 2 * month, accuracy: 1)
        let huge = ChartViewport.pinched(from: base, magnification: 0.001, domain: domain, spanDays: 7)
        XCTAssertEqual(huge.start, domain.lowerBound, "縮到最小就是整張圖")
    }

    func testPinchInStopsAtTwelveBars() throws {
        let last = try XCTUnwrap(TradingDay.parse("2026-10-28"))
        let domain = ChartViewport.domain(firstAnchor: last.addingTimeInterval(-1_500 * day), lastAnchor: last, spanDays: 1)
        let base = ChartViewport(start: domain.upperBound.addingTimeInterval(-90 * day), length: 90 * day)
        XCTAssertEqual(ChartViewport.pinched(from: base, magnification: 100, domain: domain, spanDays: 1).length, 12 * day, accuracy: 1)
    }
}
