import XCTest
@testable import DSAMarket

final class MarketDataPresentationTests: XCTestCase {
    func testEmptyOrderBookPriceIsNotZeroDollarOffer() {
        XCTAssertEqual(MarketDataPresentation.orderBookPrice(0, volume: 0), "無報價")
        XCTAssertEqual(MarketDataPresentation.orderBookPrice(115.5, volume: 9308), "115.5")
        XCTAssertEqual(MarketDataPresentation.orderBookPrice(nil, volume: nil), "—")
    }

    func testNormalBookAndGenuineZeroReadingsRemainVisible() {
        XCTAssertEqual(MarketDataPresentation.orderBookPrice(100, volume: 20), "100")
        XCTAssertEqual(MarketDataPresentation.orderBookPrice(100, volume: nil), "100")
        XCTAssertEqual(MarketDataPresentation.orderBookPrice(100, volume: 0), "100")
        XCTAssertEqual(DisplayFormat.number(0), "0")
        XCTAssertEqual(DisplayFormat.percent(0), "0.00%")
    }
}
