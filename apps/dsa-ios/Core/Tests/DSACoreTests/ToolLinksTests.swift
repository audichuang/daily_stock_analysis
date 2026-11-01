import XCTest
@testable import DSACore

final class ToolLinksTests: XCTestCase {
    private func query(_ path: String) -> [String: String] {
        let items = URLComponents(string: path)?.queryItems ?? []
        return Dictionary(uniqueKeysWithValues: items.map { ($0.name, $0.value ?? "") })
    }

    func testChatPathPercentEncodesChineseName() {
        let path = ToolLinks.chatPath(code: "2330.TW", name: "台積電", recordID: 42)
        XCTAssertTrue(path.hasPrefix("/chat?"))
        XCTAssertFalse(path.contains("台積電"))
        XCTAssertTrue(path.contains("name=%E5%8F%B0%E7%A9%8D%E9%9B%BB"))
        XCTAssertEqual(query(path), ["stock": "2330.TW", "name": "台積電", "recordId": "42"])
    }

    func testChatPathEncodesQueryDelimitersAndOmitsEmpty() {
        let path = ToolLinks.chatPath(code: "AAPL", name: "A&B=C", recordID: nil)
        XCTAssertEqual(query(path), ["stock": "AAPL", "name": "A&B=C"])
    }

    func testAlertPathIncludesValidPrice() {
        let path = ToolLinks.alertPath(code: "2330.TW", direction: .below, price: 1012.5)
        XCTAssertEqual(query(path), [
            "new": "1", "target": "2330.TW", "type": "price_cross", "direction": "below", "price": "1012.5",
        ])
    }

    func testAlertPathOmitsInvalidPrice() {
        for price in [0, -5, Double.nan, Double.infinity] as [Double] {
            let path = ToolLinks.alertPath(code: "2330.TW", direction: .above, price: price)
            XCTAssertNil(query(path)["price"], "price \(price)")
            XCTAssertFalse(path.contains("price="), path)
        }
        XCTAssertNil(query(ToolLinks.alertPath(code: "2330.TW", direction: .above, price: nil))["price"])
    }

    func testPortfolioPath() {
        XCTAssertEqual(ToolLinks.portfolioPath(entry: "trade"), "/portfolio?entry=trade")
    }
}
