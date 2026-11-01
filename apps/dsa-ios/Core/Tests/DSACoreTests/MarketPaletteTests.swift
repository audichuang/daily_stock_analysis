import XCTest
@testable import DSACore

final class MarketPaletteTests: XCTestCase {
    func testUpAndDownHaveSimilarLuminance() {
        let up = MarketPalette.relativeLuminance(MarketPalette.up)
        let down = MarketPalette.relativeLuminance(MarketPalette.down)
        XCTAssertLessThanOrEqual(abs(up - down), 0.1, "up \(up) vs down \(down)")
    }

    func testValuesMatchWebHex() {
        XCTAssertEqual(MarketPalette.up, PaletteRGB(red: 1.0, green: 0.44, blue: 0.46))
        XCTAssertEqual(MarketPalette.down, PaletteRGB(red: 0.18, green: 0.72, blue: 0.47))
    }

    // Reverse check: the previous green was visibly brighter than the red and must fail the bar.
    func testOldDownWouldFailLuminanceBar() {
        let up = MarketPalette.relativeLuminance(MarketPalette.up)
        let oldDown = MarketPalette.relativeLuminance(PaletteRGB(red: 0.28, green: 0.83, blue: 0.61))
        XCTAssertGreaterThan(abs(up - oldDown), 0.1)
    }

    func testRelativeLuminanceEndpoints() {
        XCTAssertEqual(MarketPalette.relativeLuminance(PaletteRGB(red: 1, green: 1, blue: 1)), 1, accuracy: 1e-9)
        XCTAssertEqual(MarketPalette.relativeLuminance(PaletteRGB(red: 0, green: 0, blue: 0)), 0, accuracy: 1e-9)
    }
}
