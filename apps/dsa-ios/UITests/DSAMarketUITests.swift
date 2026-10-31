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
        let rowCodes = ["2330.TW", "2317.TW", "00631L.TW", "2303.TW", "2603.TW", "0050.TW", "00878.TW"]
        XCTAssertTrue(app.buttons["stock-row.2330.TW"].waitForExistence(timeout: 10))
        let top = app.navigationBars["自選股"].frame.maxY
        let bottom = app.tabBars.firstMatch.frame.minY
        let visibleRows = rowCodes.map { app.buttons["stock-row.\($0)"] }.filter {
            $0.exists && $0.frame.minY >= top && $0.frame.maxY <= bottom
        }
        XCTAssertGreaterThanOrEqual(visibleRows.count, 6, "標準字級應同屏完整顯示至少六筆自選")
        for row in visibleRows {
            XCTAssertLessThanOrEqual(row.frame.height, 104, "自選列不應恢復成大卡片")
            XCTAssertGreaterThanOrEqual(row.frame.height, 64, "縮小版面仍需保留可讀文字與點擊空間")
        }
        capture("02b-緊湊自選列表")
        let taiwanStock = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "2330.TW")).firstMatch
        tap(taiwanStock)
        XCTAssertTrue(app.buttons["watchlist-toggle"].waitForExistence(timeout: 15))
        XCTAssertTrue(text(containing: "資料參考時間").waitForExistence(timeout: 10))
        XCTAssertFalse(text(containing: "報價時間 ·").exists)
        let priceChart = app.descendants(matching: .any)["chart.price"].firstMatch
        scrollTo(priceChart)
        XCTAssertTrue(priceChart.exists, "個股必須有實際繪製的測試 K 線")
        capture("03-個股報價與日K")

        tap(app.buttons["chart.tab.month"])
        XCTAssertTrue(app.buttons["chart.tab.month"].isSelected, "切到月 K")
        XCTAssertTrue(app.buttons["chart.range"].label.contains("5 年"), "月 K 預設視窗是 5Y")
        XCTAssertTrue(app.buttons["chart.ma.2"].exists, "月 K 應有第三條均線可切換")
        XCTAssertFalse(text(containing: "已顯示全部").exists, "fixture 有六年資料，5Y 不應提示資料不足")
        capture("03c-5Y月K與均線")
        tap(app.buttons["chart.range"])
        tap(app.buttons["1M"])
        XCTAssertTrue(app.buttons["chart.range"].label.contains("1 個月"))
        XCTAssertTrue(text(containing: "最新").exists, "1M 視窗在月 K 下仍要看得到最新一根")
        tap(app.buttons["chart.oscillator"])
        tap(app.buttons["KD"])
        XCTAssertTrue(text(containing: "副圖 KD").waitForExistence(timeout: 5), "副圖應切成 KD")
        tap(app.buttons["chart.overlay"])
        tap(app.buttons["布林"])
        XCTAssertTrue(app.buttons["chart.ma.1"].waitForExistence(timeout: 5))
        capture("03e-布林與KD副圖")
        tap(app.buttons["chart.more"])
        tap(app.buttons["看懂 K 線"])
        XCTAssertTrue(text(containing: "上方細線（上影線）").waitForExistence(timeout: 5))
        capture("03d-看懂K線說明")
        tap(app.buttons["chart.guide.done"])
        tap(app.buttons["chart.tab.intraday"])
        XCTAssertTrue(text(containing: "分時來源：fixture（合成分時）").waitForExistence(timeout: 10), "分時要打 /trend 並標來源")
        XCTAssertTrue(text(containing: "昨收 590.03").exists, "分時昨收要取分時那天之前的日線收盤")
        capture("03f-分時")
        tap(app.buttons["chart.tab.day"])
        XCTAssertTrue(app.buttons["chart.tab.day"].isSelected)

        let emptyBid = app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@ AND label CONTAINS %@", "最佳買價", "無報價")).firstMatch
        scrollTo(emptyBid)
        XCTAssertTrue(emptyBid.exists, "空委買應為無報價，不是零元可買")
        capture("03b-空委買與來源成交量")

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
        XCTAssertTrue(text(containing: "暫定・即時報價").waitForExistence(timeout: 10), "日 K 缺當天時，報價補上的暫定 K 要標示出來")
        watchlistToggle.tap()
        XCTAssertTrue(app.buttons.matching(NSPredicate(format: "identifier == %@ AND label == %@", "watchlist-toggle", "移除自選股")).firstMatch.waitForExistence(timeout: 10))
        capture("07-新增美股自選")
        watchlistToggle.tap()
        XCTAssertTrue(app.buttons.matching(NSPredicate(format: "identifier == %@ AND label == %@", "watchlist-toggle", "加入自選股")).firstMatch.waitForExistence(timeout: 10))
        capture("08-移除美股自選")
        goBack(from: "Microsoft（測試）", to: "搜尋股票")
        // 模擬器 AX 的原生搜尋控制項是「關閉」；退出搜尋模式後才會顯示 App 的「完成」。
        tap(app.buttons["關閉"])
        tap(app.buttons["search-dismiss"])

        tap(app.tabBars.buttons["AI 研究"])
        let savedReport = app.buttons["research.report.101"]
        tap(savedReport)
        XCTAssertTrue(app.descendants(matching: .any)["report.screen"].firstMatch.waitForExistence(timeout: 15))
        capture("09-歷史研究報告")

        tap(app.tabBars.buttons["資產"])
        XCTAssertTrue(text(containing: "合成測試帳戶").waitForExistence(timeout: 15))
        let total = app.staticTexts.matching(NSPredicate(format: "identifier == %@ AND label CONTAINS %@", "portfolio.summary", "資產 ")).firstMatch
        XCTAssertTrue(total.waitForExistence(timeout: 10))
        XCTAssertTrue(total.label.contains("1,200,000"), "台幣總額必須加總兩個TWD帳戶，不使用頂層CNY合計")
        XCTAssertTrue(total.label.contains("新臺幣"))
        XCTAssertFalse(text(containing: "282,345.67").exists, "不能重標原本的CNY數字")
        XCTAssertFalse(text(containing: "realtime_quote_best_effort").exists)
        let position = app.buttons["portfolio.position.1.2330.TW"]
        XCTAssertTrue(position.exists)
        XCTAssertLessThanOrEqual(position.frame.height, 104)
        XCTAssertFalse(position.label.contains("可能延遲"), "Shioaji非過期報價不能被一律標成延遲")
        capture("10-資產帳本")
        tap(app.segmentedControls["portfolio.currency-picker"].buttons["美元"])
        XCTAssertTrue(total.label.contains("12,500"), "美元須顯示USD帳戶的原幣金額")
        XCTAssertTrue(total.label.contains("美元"))
        XCTAssertTrue(app.buttons["portfolio.position.3.AAPL"].exists)
        XCTAssertTrue(app.buttons["portfolio.position.3.AAPL"].label.contains("可能延遲"))
        XCTAssertTrue(app.buttons["portfolio.position.3.MSFT"].label.contains("可能延遲"))
        XCTAssertFalse(app.buttons["portfolio.account.1"].exists)
        capture("10b-美元原幣資產")
        tap(app.segmentedControls["portfolio.currency-picker"].buttons["新臺幣"])
        tap(app.buttons["portfolio.positionDetails.1.2330.TW"])
        XCTAssertTrue(text(containing: "平均成本").exists)
        capture("10c-持股展開明細")
        tap(app.buttons["portfolio.data-notes"])
        XCTAssertTrue(text(containing: "報價依可用來源更新").exists)
        XCTAssertFalse(text(containing: "fx_and_cost_basis_partial").exists)
        capture("10d-中文資料說明")

        tap(app.tabBars.buttons["工具"])
        tap(app.buttons["tools.route.chat"])
        XCTAssertTrue(app.webViews.firstMatch.waitForExistence(timeout: 15))
        XCTAssertTrue(text(containing: "進階工具（合成驗收頁）").waitForExistence(timeout: 15), "共用登入 cookie 才能開啟受保護的工具驗收頁")
        capture("11-內嵌工具與Cookie")
        tap(app.webViews.buttons["匯出合成設定 JSON"])
        XCTAssertTrue(text(containing: "fixture-settings").waitForExistence(timeout: 15), "blob 匯出完成後必須以原生分享介面呈現檔案")
        capture("11b-Blob檔案原生分享")
        tap(app.buttons["header.closeButton"])
        XCTAssertTrue(app.webViews.buttons["匯出合成設定 JSON"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.webViews.buttons["匯出合成設定 JSON"].isHittable, "原生分享視窗必須已關閉")
        goBack(from: "AI 問股", to: "工具與設定")
        for (route, title) in [("screening", "條件選股"), ("decision-signals", "決策訊號"),
                               ("", "分析工作台"), ("backtest", "歷史回測"), ("portfolio", "帳本管理"),
                               ("funds", "基金"), ("alerts", "價位警報"), ("data", "資料中心"),
                               ("usage", "AI 用量"), ("settings", "服務設定")] {
            tap(app.buttons["tools.route.\(route)"])
            XCTAssertTrue(app.webViews.staticTexts["頁面路徑：/\(route)"].waitForExistence(timeout: 15), "工具必須載入對應路徑")
            capture("tool-\(route.isEmpty ? "analysis" : route)")
            goBack(from: title, to: "工具與設定")
        }
        tap(app.buttons["tools.logout"])
        XCTAssertTrue(app.buttons["connect-button"].waitForExistence(timeout: 15), "本機登出後應回到連線畫面")
        capture("12-本機登出")
    }

    /// fixture 的報價延遲 2 秒；下拉更新途中 store 先發布其他結果，報價請求不能因此被取消成「已取消」。
    func testPullToRefreshWithSlowQuotesShowsNoError() throws {
        let password = app.secureTextFields["server-password"]
        XCTAssertTrue(password.waitForExistence(timeout: 15), "應顯示測試伺服器的登入畫面")
        password.tap()
        password.typeText("fixture-password")
        tap(app.buttons["connect-button"])
        XCTAssertTrue(app.tabBars.buttons["自選"].waitForExistence(timeout: 20))
        tap(app.tabBars.buttons["自選"])
        let firstRow = app.buttons["stock-row.2330.TW"]
        XCTAssertTrue(firstRow.waitForExistence(timeout: 15))
        let errorTitle = text(containing: "暫時無法取得資料")
        // 先等連線後的首輪 refresh 跑完，避免下拉被 refreshing guard 直接略過。
        sleep(4)
        XCTAssertFalse(errorTitle.exists)
        for round in 1...2 {
            firstRow.press(forDuration: 0.1, thenDragTo: app.tabBars.firstMatch)
            sleep(6)
            capture("13-下拉更新第\(round)次")
            XCTAssertFalse(errorTitle.exists, "下拉更新第 \(round) 次後不應出現錯誤框")
        }
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
            // 控制項在畫面上方（例如圖表頂端的選單）時往回捲，其餘往下捲。
            if element.exists && element.frame.maxY < app.frame.height * 0.2 { app.swipeDown() } else { app.swipeUp() }
            if element.exists && element.isHittable { return }
        }
        XCTAssertTrue(element.exists && element.isHittable, "捲動後仍找不到可操作控制項", file: file, line: line)
    }

    private func goBack(from title: String, to previousTitle: String, file: StaticString = #filePath, line: UInt = #line) {
        let navigation = app.navigationBars[title]
        XCTAssertTrue(navigation.waitForExistence(timeout: 5), "應位於 \(title)", file: file, line: line)
        let back = navigation.buttons.matching(NSPredicate(format: "identifier == %@ OR label == %@", "BackButton", previousTitle)).firstMatch
        XCTAssertTrue(back.waitForExistence(timeout: 5), file: file, line: line)
        XCTAssertTrue(back.isHittable, "返回按鈕不可被其他 sheet 遮住", file: file, line: line)
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
