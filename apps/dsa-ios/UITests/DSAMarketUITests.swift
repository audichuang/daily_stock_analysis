import XCTest

/// 真啟動 App 並操作 HTTP fixture；這組測試不代表正式行情或模型端驗收。
final class DSAMarketUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        let environment = ProcessInfo.processInfo.environment
        let server = environment["DSA_TEST_SERVER"]
            ?? environment["DSA_FIXTURE_PORT"].map { "http://127.0.0.1:\($0)" }
        guard let server, !server.isEmpty else {
            throw XCTSkip("未提供 DSA_TEST_SERVER／DSA_FIXTURE_PORT；未執行 UI 驗收。")
        }
        app = XCUIApplication()
        app.launchEnvironment["DSA_TEST_SERVER"] = server
        app.launchArguments = ["-AppleLanguages", "(zh-Hant)", "-AppleLocale", "zh_TW"]
        app.launch()
    }

    override func tearDown() {
        if let app {
            capture("最終畫面")
            app.terminate()
        }
    }

    func testMarketResearchWatchlistPortfolioAndLocalLogout() throws {
        let password = app.secureTextFields["server-password"]
        XCTAssertTrue(password.waitForExistence(timeout: 15), "應顯示測試伺服器的登入畫面")
        password.tap()
        password.typeText("fixture-password")
        tap(app.buttons["connect-button"])
        XCTAssertTrue(app.tabBars.buttons["今日"].waitForExistence(timeout: 20))
        XCTAssertTrue(text(containing: "加權指數（測試）").waitForExistence(timeout: 15))
        capture("01-登入後台股首頁")

        let marketPicker = app.segmentedControls["market-picker"]
        tap(marketPicker.buttons["美股 US"])
        XCTAssertTrue(text(containing: "S&P 500（測試）").waitForExistence(timeout: 15))
        capture("02-切換美股")
        tap(marketPicker.buttons["台股 TAIWAN"])

        tap(app.tabBars.buttons["自選"])
        let taiwanStock = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "2330.TW")).firstMatch
        tap(taiwanStock)
        XCTAssertTrue(app.buttons["watchlist-toggle"].waitForExistence(timeout: 15))
        let priceChart = app.descendants(matching: .any)["chart.price"].firstMatch
        scrollTo(priceChart)
        XCTAssertTrue(priceChart.exists, "個股必須有實際繪製的測試 K 線")
        capture("03-個股報價與日K")

        let reportLink = app.buttons["stock-report-link"]
        tap(reportLink)
        XCTAssertTrue(app.descendants(matching: .any)["report.screen"].firstMatch.waitForExistence(timeout: 15))
        scrollTo(text(containing: "判斷依據"))
        XCTAssertTrue(text(containing: "月營收（測試）").exists)
        capture("04-AI研究依據")
        scrollTo(text(containing: "何時需要重新判斷"))
        XCTAssertTrue(text(containing: "跌破測試支撐需重新判斷").exists)
        capture("05-論點失效條件")
        goBack()

        tap(app.buttons["analysis-start"])
        XCTAssertTrue(text(containing: "分析已完成，報告已更新。").waitForExistence(timeout: 25), "fixture 需經兩次 processing 再 completed")
        capture("06-新分析完成")
        goBack()

        tap(app.buttons["新增自選股"])
        let search = app.searchFields.firstMatch
        XCTAssertTrue(search.waitForExistence(timeout: 10))
        search.tap()
        search.typeText("MSFT")
        let microsoft = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "Microsoft（測試）")).firstMatch
        tap(microsoft)
        let watchlistToggle = app.buttons["watchlist-toggle"]
        XCTAssertTrue(watchlistToggle.waitForExistence(timeout: 15))
        XCTAssertEqual(watchlistToggle.label, "加入自選股")
        watchlistToggle.tap()
        XCTAssertTrue(app.buttons.matching(NSPredicate(format: "identifier == %@ AND label == %@", "watchlist-toggle", "移除自選股")).firstMatch.waitForExistence(timeout: 10))
        capture("07-新增美股自選")
        watchlistToggle.tap()
        XCTAssertTrue(app.buttons.matching(NSPredicate(format: "identifier == %@ AND label == %@", "watchlist-toggle", "加入自選股")).firstMatch.waitForExistence(timeout: 10))
        capture("08-移除美股自選")
        goBack()
        tap(app.buttons["完成"])

        tap(app.tabBars.buttons["AI 研究"])
        let savedReport = app.buttons["research.report.101"]
        tap(savedReport)
        XCTAssertTrue(app.descendants(matching: .any)["report.screen"].firstMatch.waitForExistence(timeout: 15))
        capture("09-歷史研究報告")

        tap(app.tabBars.buttons["資產"])
        XCTAssertTrue(text(containing: "合成測試帳戶").waitForExistence(timeout: 15))
        scrollTo(text(containing: "合成測試帳戶"))
        capture("10-資產帳本")

        tap(app.tabBars.buttons["工具"])
        tap(app.buttons["tools.route.chat"])
        XCTAssertTrue(app.webViews.firstMatch.waitForExistence(timeout: 15))
        XCTAssertTrue(text(containing: "進階工具（合成驗收頁）").waitForExistence(timeout: 15), "共用登入 cookie 才能開啟受保護的工具驗收頁")
        capture("11-內嵌工具與Cookie")
        goBack()
        tap(app.buttons["tools.logout"])
        XCTAssertTrue(app.buttons["connect-button"].waitForExistence(timeout: 15), "本機登出後應回到連線畫面")
        capture("12-本機登出")
    }

    private func text(containing value: String) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", value)).firstMatch
    }

    private func tap(_ element: XCUIElement, file: StaticString = #filePath, line: UInt = #line) {
        scrollTo(element, file: file, line: line)
        XCTAssertTrue(element.isHittable, "控制項無法點擊：\(element)", file: file, line: line)
        element.tap()
    }

    private func scrollTo(_ element: XCUIElement, file: StaticString = #filePath, line: UInt = #line) {
        if element.waitForExistence(timeout: 3), element.isHittable { return }
        for _ in 0..<14 {
            app.swipeUp()
            if element.exists && element.isHittable { return }
        }
        XCTAssertTrue(element.exists && element.isHittable, "捲動後仍找不到可操作控制項", file: file, line: line)
    }

    private func goBack(file: StaticString = #filePath, line: UInt = #line) {
        let back = app.navigationBars.buttons.firstMatch
        XCTAssertTrue(back.waitForExistence(timeout: 5), file: file, line: line)
        back.tap()
    }

    private func capture(_ name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
