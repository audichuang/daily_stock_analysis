import XCTest

/// 真啟動 App 並操作 HTTP fixture；這組測試不代表正式行情或模型端驗收。
final class DSAMarketUITests: XCTestCase {
    private var app: XCUIApplication!
    private var screenshotDirectory: URL!

    override func setUpWithError() throws {
        continueAfterFailure = false
        let environment = ProcessInfo.processInfo.environment
        let server = environment["DSA_TEST_SERVER"]
            ?? environment["DSA_FIXTURE_PORT"].map { "http://127.0.0.1:\($0)" }
        guard let server, !server.isEmpty else {
            throw XCTSkip("未提供 DSA_TEST_SERVER／DSA_FIXTURE_PORT；未執行 UI 驗收。")
        }
        screenshotDirectory = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("DSA-UI-Evidence", isDirectory: true)
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: screenshotDirectory, withIntermediateDirectories: true)
        print("DSA_UI_EVIDENCE_DIR=\(screenshotDirectory.path)")
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
        goBack(from: "AI 研究", to: "台積電（測試）")

        tap(app.buttons["analysis-start"])
        XCTAssertTrue(text(containing: "原分析任務已不存在，請重新產生分析。").waitForExistence(timeout: 15))
        capture("06a-原任務404後可重新分析")
        tap(app.buttons["analysis-start"])
        XCTAssertTrue(text(containing: "分析已完成，報告已更新。").waitForExistence(timeout: 25), "fixture 需經兩次 processing 再 completed")
        capture("06-新分析完成")
        tap(app.buttons["stock-dossier-link"])
        XCTAssertTrue(text(containing: "四維度合成檔案 2330.TW").waitForExistence(timeout: 15))
        XCTAssertFalse(text(containing: "四維度合成檔案 AAPL").exists)
        capture("06b-指定台股四維度檔案")
        goBack(from: "四維度個股檔案", to: "台積電（測試）")
        goBack(from: "台積電（測試）", to: "自選股")

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
        goBack(from: "Microsoft（測試）", to: "搜尋股票")
        tap(app.buttons["search-dismiss"])

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
        tap(app.webViews.buttons["匯出合成設定 JSON"])
        XCTAssertTrue(text(containing: "fixture-settings").waitForExistence(timeout: 15), "blob 匯出完成後必須以原生分享介面呈現檔案")
        capture("11b-Blob檔案原生分享")
        app.swipeDown()
        XCTAssertTrue(app.webViews.buttons["匯出合成設定 JSON"].waitForExistence(timeout: 10))
        goBack(from: "AI 問股", to: "工具與設定")
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

    private func goBack(from title: String, to previousTitle: String, file: StaticString = #filePath, line: UInt = #line) {
        let navigation = app.navigationBars[title]
        XCTAssertTrue(navigation.waitForExistence(timeout: 5), "應位於 \(title)", file: file, line: line)
        let back = navigation.buttons.matching(NSPredicate(format: "identifier == %@ OR label == %@", "BackButton", previousTitle)).firstMatch
        XCTAssertTrue(back.waitForExistence(timeout: 5), file: file, line: line)
        back.tap()
    }

    private func capture(_ name: String) {
        let screenshot = app.screenshot()
        let attachment = XCTAttachment(screenshot: screenshot)
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
        // Xcode 27.1 已實際卡在 xcresult finalize；另存測試自己的 PNG，保留可檢視證據。
        do {
            try screenshot.pngRepresentation.write(to: screenshotDirectory.appendingPathComponent(name + ".png"), options: .atomic)
        } catch {
            XCTFail("無法保存 UI 截圖：\(error.localizedDescription)")
        }
    }
}
