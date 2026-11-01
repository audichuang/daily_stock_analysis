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
        // Keychain 跨案例保留：前一個案例沒登出或中途失敗時，先清掉，否則後面全部看不到登入畫面。
        let ready = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            self.app.tabBars.buttons["今日"].exists || self.app.buttons["connect-button"].exists
        }, object: nil)
        _ = XCTWaiter.wait(for: [ready], timeout: 20)
        if app.tabBars.buttons["今日"].exists {
            logoutFromToolsAfterLogin()
            // 登出後畫面還沒探測 auth，沒有密碼欄；重開才是案例預期的登入畫面。
            app.terminate()
            app.launch()
        }
    }

    override func tearDown() {
        if let app {
            capture("最終畫面")
            app.terminate()
        }
    }

    func testCloudflareAccessPersistsAcrossTerminationAndBridgesCookieToSubresources() throws {
        let server = try XCTUnwrap(ProcessInfo.processInfo.environment["DSA_ACCESS_FIXTURE_SERVER"])
        launchFreshAccessFixture(server: server, secret: "fixture-access-secret")
        XCTAssertTrue(text(containing: "Cloudflare Access 驗證失敗").waitForExistence(timeout: 15))
        XCTAssertTrue(app.secureTextFields["access-client-secret"].exists, "驗證失敗要自動展開憑證設定")
        XCTAssertFalse(app.secureTextFields["server-password"].exists)
        tap(app.buttons["access-save"])
        tap(app.buttons["connect-button"])
        XCTAssertTrue(app.secureTextFields["server-password"].waitForExistence(timeout: 15))
        tap(app.buttons["connect-button"])
        XCTAssertTrue(app.tabBars.buttons["今日"].waitForExistence(timeout: 20))
        capture("Access-首次登入")

        // 真正終止 process；第二次 launch 不帶任何憑證或密碼預填。
        app.terminate()
        app.launchEnvironment = ["DSA_TEST_SERVER": server]
        app.launch()
        XCTAssertTrue(app.tabBars.buttons["今日"].waitForExistence(timeout: 20))
        XCTAssertFalse(app.secureTextFields["server-password"].exists)
        capture("Access-終止後自動登入")
        tap(app.tabBars.buttons["工具"])
        tap(app.buttons["tools.route.chat"])
        XCTAssertTrue(text(containing: "Access 子資源 Cookie 已驗證").waitForExistence(timeout: 20))
        capture("Access-WebKit子資源Cookie")
        tap(app.links["測試 Access 失效轉址"])
        XCTAssertTrue(text(containing: "Cloudflare Access 驗證失敗").waitForExistence(timeout: 10))
        XCTAssertFalse(app.webViews.firstMatch.exists, "整頁錯誤不留 WebView")
        capture("Access-WebKit轉址錯誤")
        goBack(from: "AI 問股", to: "工具與設定")
        logoutFromTools()
        expandAccessSettings()
        XCTAssertTrue(app.staticTexts["access-configured"].waitForExistence(timeout: 10))
        XCTAssertFalse(app.secureTextFields["access-client-secret"].exists, "儲存的 Secret 不回顯")
        tap(app.buttons["access-remove"])
        tap(app.buttons["connect-button"])
        XCTAssertTrue(text(containing: "Cloudflare Access 驗證失敗").waitForExistence(timeout: 15))
        XCTAssertFalse(app.secureTextFields["server-password"].exists)
    }

    func testCloudflareAccessRejectsWrongSecretAndCanReplaceWithoutBackendPasswordPrompt() throws {
        let server = try XCTUnwrap(ProcessInfo.processInfo.environment["DSA_ACCESS_FIXTURE_SERVER"])
        launchFreshAccessFixture(server: server, secret: "invalid-synthetic")
        XCTAssertTrue(text(containing: "Cloudflare Access 驗證失敗").waitForExistence(timeout: 15))
        tap(app.buttons["access-save"])
        tap(app.buttons["connect-button"])
        XCTAssertTrue(text(containing: "Cloudflare Access 驗證失敗").waitForExistence(timeout: 15))
        XCTAssertFalse(app.secureTextFields["server-password"].exists)
        capture("Access-錯誤憑證可更換")
        launchAccess(server: server, clientID: "fixture-access-id", secret: "fixture-access-secret", password: "fixture-password")
        XCTAssertTrue(text(containing: "Cloudflare Access 驗證失敗").waitForExistence(timeout: 15))
        tap(app.buttons["access-replace"])
        tap(app.buttons["access-save"])
        tap(app.buttons["connect-button"])
        XCTAssertTrue(app.secureTextFields["server-password"].waitForExistence(timeout: 15))
        XCTAssertFalse(text(containing: "Cloudflare Access 驗證失敗").exists)
        tap(app.buttons["access-remove"])
    }

    func testRealCloudflareAccessOptIn() throws {
        let environment = ProcessInfo.processInfo.environment
        guard let server = environment["DSA_REAL_ACCESS_URL"],
              let clientID = environment["DSA_REAL_ACCESS_CLIENT_ID"], !clientID.isEmpty,
              let secret = environment["DSA_REAL_ACCESS_CLIENT_SECRET"], !secret.isEmpty else {
            throw XCTSkip("未設定真實 Access UITest 環境變數；跳過正式環境驗證。")
        }
        launchAccess(server: server, clientID: clientID, secret: secret, password: environment["DSA_REAL_DSA_PASSWORD"])
        // 即使該 origin 之前已儲存憑證，也以這次明確提供的值更換。
        if app.tabBars.buttons["今日"].waitForExistence(timeout: 5) {
            tap(app.tabBars.buttons["工具"])
            tap(app.buttons["tools.connection"])
            tap(app.buttons["tools.access"])
        } else if !app.buttons["access-save"].exists { tap(app.descendants(matching: .any)["access-section"].firstMatch) }
        if app.buttons["access-replace"].exists { tap(app.buttons["access-replace"]) }
        tap(app.buttons["access-save"])
        tap(app.buttons["connect-button"])
        if app.secureTextFields["server-password"].waitForExistence(timeout: 5) {
            guard environment["DSA_REAL_DSA_PASSWORD"]?.isEmpty == false else {
                throw XCTSkip("Access 已儲存；首次 DSA 登入還需要 DSA_REAL_DSA_PASSWORD。")
            }
            tap(app.buttons["connect-button"])
        }
        XCTAssertTrue(app.tabBars.buttons["今日"].waitForExistence(timeout: 30))
        app.terminate()
        app.launchEnvironment = ["DSA_TEST_SERVER": server]
        app.launch()
        XCTAssertTrue(app.tabBars.buttons["今日"].waitForExistence(timeout: 30))
        tap(app.tabBars.buttons["工具"])
        tap(app.buttons["tools.route.chat"])
        XCTAssertTrue(app.webViews.firstMatch.waitForExistence(timeout: 20))
        let loaded = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: app.progressIndicators["tool-loading"])
        XCTAssertEqual(XCTWaiter.wait(for: [loaded], timeout: 30), .completed)
        XCTAssertFalse(app.descendants(matching: .any)["tool-error"].firstMatch.exists)
        capture("真實Access-重啟與工具頁")
    }

    private func launchAccess(server: String, clientID: String, secret: String, password: String?) {
        app.terminate()
        app.launchEnvironment = ["DSA_TEST_SERVER": server, "DSA_ACCESS_TEST_PREFILL": "1",
                                 "DSA_ACCESS_TEST_CLIENT_ID": clientID, "DSA_ACCESS_TEST_CLIENT_SECRET": secret]
        app.launchEnvironment["DSA_ACCESS_TEST_PASSWORD"] = password
        app.launch()
    }

    private func launchFreshAccessFixture(server: String, secret: String) {
        launchAccess(server: server, clientID: "fixture-access-id", secret: secret, password: "fixture-password")
        let ready = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            self.app.tabBars.buttons["今日"].exists || self.app.buttons["connect-button"].exists
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [ready], timeout: 20), .completed)
        // Keychain 刻意跨 process 保留；每個案例先以真 UI 清掉該 fixture 的既有登入與 Token。
        if app.tabBars.buttons["今日"].exists {
            tap(app.tabBars.buttons["工具"])
            logoutFromTools()
        }
        expandAccessSettings()
        if app.staticTexts["access-configured"].exists {
            tap(app.buttons["access-remove"])
            XCTAssertTrue(app.secureTextFields["access-client-secret"].exists)
            launchAccess(server: server, clientID: "fixture-access-id", secret: secret, password: "fixture-password")
        }
    }

    private func expandAccessSettings() {
        if !app.textFields["access-client-id"].exists && !app.staticTexts["access-configured"].exists {
            tap(app.descendants(matching: .any)["access-section"].firstMatch)
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
        tap(marketPicker.buttons["美股"])
        XCTAssertTrue(text(containing: "S&P 500（測試）").waitForExistence(timeout: 15))
        capture("02-切換美股")
        tap(marketPicker.buttons["台股"])

        tap(app.tabBars.buttons["自選"])
        let rowCodes = ["2330.TW", "2317.TW", "00631L.TW", "2303.TW", "2603.TW", "0050.TW", "00878.TW"]
        XCTAssertTrue(app.buttons["stock-row.2330.TW"].waitForExistence(timeout: 10))
        let top = app.navigationBars["自選"].frame.maxY
        let bottom = app.tabBars.firstMatch.frame.minY
        let visibleRows = rowCodes.map { app.buttons["stock-row.\($0)"] }.filter {
            $0.exists && $0.frame.minY >= top && $0.frame.maxY <= bottom
        }
        XCTAssertGreaterThanOrEqual(visibleRows.count, 6, "標準字級應同屏完整顯示至少六筆自選")
        for row in visibleRows {
            XCTAssertLessThanOrEqual(row.frame.height, 57, "自選列高度 52～56pt，留一點 cell 取整誤差")
            XCTAssertGreaterThanOrEqual(row.frame.height, 52, "縮小版面仍需保留可讀文字與點擊空間")
        }
        capture("02b-緊湊自選列表")
        XCTAssertFalse(app.buttons["stock-row.2330.TW"].label.contains("2330.TW"), "代號顯示去後綴，路由仍用完整代號")
        tap(app.buttons["stock-row.2330.TW"])
        XCTAssertTrue(app.buttons["watchlist-toggle"].waitForExistence(timeout: 15))
        XCTAssertTrue(text(containing: "資料參考時間").waitForExistence(timeout: 10))
        XCTAssertFalse(text(containing: "報價時間 ·").exists)
        // 三行報價與持股條都要在首屏，分頁列隱藏且內容不被遮。
        let quotePosition = app.descendants(matching: .any)["stock.position"].firstMatch
        XCTAssertTrue(quotePosition.waitForExistence(timeout: 10))
        XCTAssertTrue(app.frame.contains(quotePosition.frame), "持股條要在首屏")
        XCTAssertTrue(text(containing: "已收盤").waitForExistence(timeout: 10), "postmarket 要顯示已收盤")
        XCTAssertTrue(app.descendants(matching: .any)["stock.change"].firstMatch.label.contains("+1.69%"))
        XCTAssertFalse(app.tabBars.buttons["今日"].exists && app.tabBars.buttons["今日"].isHittable, "個股頁要隱藏底部分頁")
        let stockTitle = app.descendants(matching: .any)["stock.title"].firstMatch
        XCTAssertTrue(stockTitle.label.contains("2330.TW"), "標題第二行是代號")
        app.swipeUp()
        app.swipeUp()
        let titleHasPrice = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label CONTAINS %@", "600"), object: stockTitle)
        XCTAssertEqual(XCTWaiter.wait(for: [titleHasPrice], timeout: 5), .completed, "捲動後標題要含現價")
        capture("03a-捲動後標題含現價")
        app.swipeDown()
        app.swipeDown()
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
        tap(app.buttons["1月"])
        XCTAssertTrue(app.buttons["chart.range"].label.contains("1 個月"))
        XCTAssertTrue(text(containing: "最新").exists, "1M 視窗在月 K 下仍要看得到最新一根")
        // 指標改成直接按的列，不再經過選單。
        tap(app.buttons["chart.oscillator.KD"])
        XCTAssertTrue(text(containing: "KD(9,3,3)").waitForExistence(timeout: 5), "副圖應切成 KD")
        tap(app.buttons["chart.overlay.布林"])
        XCTAssertTrue(app.buttons["chart.ma.1"].waitForExistence(timeout: 5))
        capture("03e-布林與KD副圖")
        tap(app.buttons["chart.more"])
        tap(app.buttons["看懂 K 線"])
        XCTAssertTrue(text(containing: "上方細線（上影線）").waitForExistence(timeout: 5))
        capture("03d-看懂K線說明")
        tap(app.buttons["chart.guide.done"])
        // 副圖列的問號要直接開到「副圖」段落。
        tap(app.buttons["chart.guide"])
        tap(app.buttons["chart.guide.oscillator"])
        XCTAssertTrue(app.buttons["chart.guide.tab.oscillator"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["chart.guide.tab.oscillator"].isSelected, "圖表入口要帶段落")
        tap(app.buttons["chart.guide.done"])
        tap(app.buttons["chart.tab.intraday"])
        // fixture 的日線晚 6 秒才回（test-ui.sh --daily-trend-delay 6）：分時要先出圖，昨收之後補上。
        XCTAssertTrue(text(containing: "分時來源：fixture（合成分時）").waitForExistence(timeout: 4), "分時不能被較慢的日線請求拖住")
        XCTAssertTrue(text(containing: "昨收 590.03").waitForExistence(timeout: 15), "分時昨收要取分時那天之前的日線收盤")
        XCTAssertTrue(text(containing: "資料截至").exists, "分時要標資料截至時間")
        XCTAssertTrue(text(containing: "均價").exists, "fixture 帶均價，讀數要顯示")
        capture("03f-分時")
        tap(app.buttons["chart.tab.day"])
        XCTAssertTrue(app.buttons["chart.tab.day"].isSelected)

        let emptyBid = app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@ AND label CONTAINS %@", "最佳買價", "無報價")).firstMatch
        scrollTo(emptyBid)
        XCTAssertTrue(emptyBid.exists, "空委買應為無報價，不是零元可買")
        capture("03b-空委買與來源成交量")

        selectStockTab("news")
        scrollTo(text(containing: "相關新聞"))
        capture("新聞-個股頁預設分類")
        XCTAssertFalse(text(containing: "產業資料頁（合成）").exists)
        XCTAssertFalse(text(containing: "EX-99.1").exists)

        selectStockTab("chips")
        XCTAssertTrue(text(containing: "三大法人").waitForExistence(timeout: 5))
        capture("03g-籌碼分頁")
        selectStockTab("ai")
        XCTAssertTrue(app.descendants(matching: .any)["stock.ai.block"].firstMatch.waitForExistence(timeout: 5))
        XCTAssertTrue(app.descendants(matching: .any)["stock.advice.text"].firstMatch.label.contains("持股者"), "有持股時預設看持股建議")
        capture("03h-AI分頁")
        let reportLink = app.buttons["stock-report-link"]
        tap(reportLink)
        XCTAssertTrue(app.descendants(matching: .any)["report.screen"].firstMatch.waitForExistence(timeout: 15))
        let conclusion = app.descendants(matching: .any)["report.conclusion"].firstMatch
        XCTAssertTrue(conclusion.waitForExistence(timeout: 10))
        XCTAssertTrue(app.frame.intersects(conclusion.frame), "結論卡在首屏")
        XCTAssertTrue(app.descendants(matching: .any)["report.sinceReport"].firstMatch.waitForExistence(timeout: 10), "現價與報告後漲跌")
        capture("04a-報告結論卡")
        scrollTo(text(containing: "相關新聞"))
        scrollTo(text(containing: "SEC 8-K 公告"))
        capture("新聞-完整報告新聞與公告")
        XCTAssertTrue(text(containing: "合成通訊社 · 2024-01-31").exists)
        XCTAssertTrue(text(containing: "合成公告").exists)
        XCTAssertFalse(text(containing: "EX-99.1").exists)
        let latestNews = app.links["report.news.link.0"]
        XCTAssertTrue(latestNews.label.contains("最新新聞（合成）"), "應依日期排序")
        tap(app.descendants(matching: .any)["report.news.references"].firstMatch)
        scrollTo(text(containing: "產業資料頁（合成）"))
        capture("新聞-展開其他參考資料")
        XCTAssertTrue(text(containing: "財報資料頁（合成）").exists)
        XCTAssertTrue(text(containing: "市場資料頁（合成）").exists)
        scrollTo(text(containing: "判斷依據"))
        XCTAssertTrue(text(containing: "月營收（測試）").exists)
        capture("04-AI研究依據")
        scrollTo(text(containing: "改判條件"))
        XCTAssertTrue(text(containing: "跌破測試支撐需重新判斷").exists)
        capture("05-論點失效條件")
        // 全文：段落可收合、跳轉膠囊、表格原生列。
        tap(app.descendants(matching: .any)["report.fullText"].firstMatch)
        tap(app.buttons["report.jump.2"])
        let table = app.descendants(matching: .any)["report.table"].firstMatch
        XCTAssertTrue(table.waitForExistence(timeout: 5), "跳轉要展開目標段落")
        XCTAssertLessThanOrEqual(table.frame.maxX, app.frame.maxX, "表格不能溢出螢幕")
        capture("05a-完整報告表格與分段")
        goBackFromReport(to: "台積電（測試）")

        tap(app.buttons["analysis-start"])
        XCTAssertTrue(text(containing: "原分析任務已不存在，請重新產生分析。").waitForExistence(timeout: 15))
        capture("06a-原任務404後可重新分析")
        tap(app.buttons["analysis-start"])
        // 已有報告時重新分析要先過確認框。
        tap(app.buttons.matching(NSPredicate(format: "identifier == %@ OR label == %@", "stock.reanalyze.confirm", "開始重新分析")).firstMatch)
        XCTAssertTrue(text(containing: "分析已完成，報告已更新。").waitForExistence(timeout: 25), "fixture 需經兩次 processing 再 completed")
        capture("06-新分析完成")
        selectStockTab("news")
        scrollTo(text(containing: "這次分析沒有可顯示的新聞或官方公告。"))
        capture("新聞-新分析個股空狀態")
        selectStockTab("ai")
        tap(app.buttons["stock-report-link"])
        scrollTo(text(containing: "這次分析沒有可顯示的新聞或官方公告。"))
        capture("新聞-完整報告空狀態")
        goBackFromReport(to: "台積電（測試）")
        // 財報區塊：AI 標記的欄位點開要看到說明，固定教學也在
        selectStockTab("financials")
        let marginRow = app.buttons["financials.metric.gross_margin"]
        scrollTo(marginRow)
        XCTAssertTrue(marginRow.label.contains("AI 重點"), "AI 標記的欄位要有視覺標示")
        XCTAssertFalse(app.buttons["financials.metric.revenue"].label.contains("AI 重點"), "沒被標記的欄位不能有標示")
        tap(marginRow)
        XCTAssertTrue(text(containing: "合成：毛利率上升").waitForExistence(timeout: 10))
        XCTAssertTrue(text(containing: "合成：毛利率教學").exists)
        capture("06a-財報AI導讀")
        tap(app.buttons["完成"])
        selectStockTab("ai")
        tap(app.buttons["stock-dossier-link"])
        XCTAssertTrue(text(containing: "四維度合成檔案 2330.TW").waitForExistence(timeout: 15))
        XCTAssertFalse(text(containing: "四維度合成檔案 AAPL").exists)
        capture("06b-指定台股四維度檔案")
        goBack(from: "四維度個股檔案", to: "台積電（測試）")
        goBack(from: "台積電（測試）", to: "自選")

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
        // 上面分析過台積電：同日兩份併成一列，新的在上、舊的收在「同日另 1 份」。
        tap(app.buttons["research.versions.2330.TW"])
        XCTAssertTrue(text(containing: "觀望 → 買進").exists, "同日動作改變要有變化行")
        capture("09a-研究庫同日整併")
        let savedReport = app.buttons["research.report.101"]
        tap(savedReport)
        XCTAssertTrue(app.descendants(matching: .any)["report.screen"].firstMatch.waitForExistence(timeout: 15))
        capture("09-歷史研究報告")

        tap(app.tabBars.buttons["資產"])
        XCTAssertTrue(text(containing: "合成測試帳戶").waitForExistence(timeout: 15))
        let total = app.descendants(matching: .any)["portfolio.summary.totalEquity"].firstMatch
        XCTAssertTrue(total.waitForExistence(timeout: 10))
        XCTAssertTrue(total.label.contains("1,800,000"), "總覽讀 consolidated_* 加基金，不用頂層CNY合計，也不自己換匯")
        XCTAssertFalse(text(containing: "282,345.67").exists, "不能重標原本的CNY數字")
        XCTAssertFalse(text(containing: "realtime_quote_best_effort").exists)
        XCTAssertTrue(text(containing: "含基金").exists)
        let position = app.buttons["portfolio.position.1.2330.TW"]
        XCTAssertTrue(position.exists)
        XCTAssertGreaterThanOrEqual(position.frame.height, 44)
        XCTAssertLessThanOrEqual(position.frame.height, 76, "四欄列要維持緊湊")
        XCTAssertFalse(position.label.contains("可能延遲"), "Shioaji非過期報價不能被一律標成延遲")
        XCTAssertTrue(app.descendants(matching: .any)["portfolio.insight.concentration"].firstMatch.waitForExistence(timeout: 10), "集中度要接 /portfolio/risk")
        XCTAssertFalse(app.buttons["portfolio.positionDetails.1.2330.TW"].exists, "「…」已改成左滑")
        capture("10-資產帳本")

        tap(app.segmentedControls["portfolio.market-picker"].buttons["美股"])
        XCTAssertTrue(app.buttons["portfolio.position.3.AAPL"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["portfolio.position.3.AAPL"].label.contains("可能延遲"))
        XCTAssertTrue(app.buttons["portfolio.position.3.MSFT"].label.contains("可能延遲"))
        XCTAssertFalse(app.buttons["portfolio.account.1"].exists)
        XCTAssertTrue(total.label.contains("1,800,000"), "市場篩選只影響列表，總覽仍是全部資產")
        capture("10b-美股篩選")
        tap(app.segmentedControls["portfolio.market-picker"].buttons["全部"])

        tap(app.buttons["portfolio.account.1"])
        let collapsed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: app.buttons["portfolio.position.1.2330.TW"])
        XCTAssertEqual(XCTWaiter.wait(for: [collapsed], timeout: 5), .completed, "帳戶收合要連持股一起收")
        tap(app.buttons["portfolio.account.1"])
        XCTAssertTrue(position.waitForExistence(timeout: 5))
        position.swipeLeft()
        tap(app.buttons["明細"])
        XCTAssertTrue(text(containing: "平均成本").waitForExistence(timeout: 5))
        capture("10c-左滑持股明細")

        tap(app.buttons["portfolio.view-mode"])
        tap(app.buttons["合併持股"])
        XCTAssertTrue(text(containing: "新臺幣持股").waitForExistence(timeout: 5))
        XCTAssertTrue(text(containing: "美元持股").exists, "不同幣別分組，不混算")
        XCTAssertTrue(app.buttons["portfolio.merged.2330.TW"].exists)
        capture("10e-合併持股")
        tap(app.buttons["portfolio.view-mode"])
        tap(app.buttons["依帳戶"])

        tap(app.buttons["portfolio.data-notes"])
        XCTAssertTrue(text(containing: "報價依可用來源更新").exists)
        XCTAssertFalse(text(containing: "fx_and_cost_basis_partial").exists)
        capture("10d-中文資料說明")

        tap(app.tabBars.buttons["工具"])
        tap(app.buttons["tools.route.chat"])
        XCTAssertTrue(app.webViews.firstMatch.waitForExistence(timeout: 15))
        XCTAssertTrue(text(containing: "進階工具（合成驗收頁）").waitForExistence(timeout: 15), "共用登入 cookie 才能開啟受保護的工具驗收頁")
        XCTAssertTrue(text(containing: "內嵌模式：ios").exists, "工具頁必須帶 ?embed=ios 載入")
        XCTAssertFalse(app.tabBars.buttons["工具"].isHittable, "內嵌工具頁要隱藏底部分頁")
        XCTAssertFalse(text(containing: "已連接你的分析服務").exists, "說明橫條已移除")
        capture("11-內嵌工具與Cookie")
        tap(app.webViews.buttons["匯出合成設定 JSON"])
        XCTAssertTrue(text(containing: "fixture-settings").waitForExistence(timeout: 15), "blob 匯出完成後必須以原生分享介面呈現檔案")
        capture("11b-Blob檔案原生分享")
        tap(app.buttons["header.closeButton"])
        XCTAssertTrue(app.webViews.buttons["匯出合成設定 JSON"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.webViews.buttons["匯出合成設定 JSON"].isHittable, "原生分享視窗必須已關閉")
        goBack(from: "AI 問股", to: "工具與設定")
        XCTAssertFalse(app.buttons["tools.calendar"].exists, "行事曆只從今日頁進")
        XCTAssertFalse(app.buttons["tools.route."].exists, "完整分析與原生畫面重複，已移除")
        XCTAssertFalse(app.buttons["tools.route.backtest"].exists, "進階預設收合")
        for (route, title) in [("screening", "條件選股"), ("portfolio", "帳本管理"), ("settings", "服務設定"),
                               ("alerts", "價格警報"), ("decision-signals", "決策訊號"), ("backtest", "歷史回測"),
                               ("funds", "基金"), ("data", "資料中心"), ("usage", "AI 用量")] {
            if !app.buttons["tools.route.\(route)"].exists { tap(app.buttons["tools.advanced"]) }
            tap(app.buttons["tools.route.\(route)"])
            XCTAssertTrue(app.webViews.staticTexts["頁面路徑：/\(route)"].waitForExistence(timeout: 15), "工具必須載入對應路徑")
            capture("tool-\(route)")
            goBack(from: title, to: "工具與設定")
        }
        logoutFromTools()
        XCTAssertTrue(app.buttons["connect-button"].waitForExistence(timeout: 15), "本機登出後應回到連線畫面")
        capture("12-本機登出")
    }

    /// fixture 的報價延遲 2 秒；下拉更新途中 store 先發布其他結果，報價請求不能因此被取消成「已取消」。
    func testCalendarMonthSelectionStatusesAndNextEarningsWarning() throws {
        let password = app.secureTextFields["server-password"]
        XCTAssertTrue(password.waitForExistence(timeout: 15))
        password.tap()
        password.typeText("fixture-password")
        tap(app.buttons["connect-button"])
        XCTAssertTrue(app.tabBars.buttons["今日"].waitForExistence(timeout: 20))
        tap(app.segmentedControls["market-picker"].buttons["美股"])
        scrollTo(eventsCard)
        XCTAssertTrue(eventsCardText("Apple（測試）").waitForExistence(timeout: 15), "今日總覽要列近期財報")
        XCTAssertTrue(eventsCardText("財報 · ").exists, "要看得出事件類型")
        tap(app.segmentedControls["market-picker"].buttons["台股"])
        XCTAssertFalse(eventsCardText("Apple（測試）").exists, "台股分頁不列美股事件")
        tap(app.segmentedControls["market-picker"].buttons["美股"])
        XCTAssertTrue(eventsCardText("Apple（測試）").waitForExistence(timeout: 5))
        capture("13-今日近期事件")
        tap(app.buttons["today.calendar"])
        XCTAssertTrue(app.navigationBars["事件行事曆"].waitForExistence(timeout: 10))
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = .current
        formatter.dateFormat = "yyyy-MM-dd"
        let today = formatter.string(from: Date())
        let day = app.buttons["calendar.day.\(today)"]
        XCTAssertTrue(day.waitForExistence(timeout: 10))
        let marked = NSPredicate(format: "label CONTAINS %@", "有事件")
        expectation(for: marked, evaluatedWith: day)
        waitForExpectations(timeout: 15)
        tap(day)
        XCTAssertTrue(text(containing: "美東").waitForExistence(timeout: 10))
        capture("14-行事曆月曆與財報")
        let deadline = app.descendants(matching: .any)["calendar.event.fixture-deadline"].firstMatch
        scrollTo(deadline)
        XCTAssertTrue(deadline.staticTexts["法定期限"].exists)
        XCTAssertTrue(deadline.staticTexts["合成財報法定期限；不代表實際發布日"].exists)
        capture("15-行事曆法定期限")
        scrollTo(app.buttons["calendar.next"])
        tap(app.buttons["calendar.next"])
        let estimated = text(containing: "合成推估財報")
        XCTAssertTrue(estimated.waitForExistence(timeout: 15))
        scrollTo(estimated)
        XCTAssertTrue(app.staticTexts["推估"].exists)
        capture("16-換月與推估")
        let undated = text(containing: "尚未排定日期")
        scrollTo(undated)
        XCTAssertFalse(text(containing: "Microsoft（測試）").exists, "未定清單預設要收合")
        tap(undated)
        XCTAssertTrue(text(containing: "Microsoft（測試）").waitForExistence(timeout: 5))
        capture("17-下次財報未定")
        goBack(from: "事件行事曆", to: "今日")
        tap(app.tabBars.buttons["自選"])
        tap(app.segmentedControls["market-picker"].buttons["美股"])
        tap(app.buttons["stock-row.AAPL"])
        XCTAssertTrue(app.descendants(matching: .any)["stock.nextEarnings"].waitForExistence(timeout: 15))
        let soon = app.descendants(matching: .any)["stock.earnings.soon"].firstMatch
        XCTAssertTrue(soon.waitForExistence(timeout: 15))
        XCTAssertTrue(app.frame.contains(soon.frame), "七天內提示要在首屏看得到")
        XCTAssertTrue(text(containing: "美東").exists)
        capture("18-個股七天內財報警示")
        // Keychain 跨案例保留；登出才不會讓下一個案例看不到登入畫面。
        app.terminate()
        app.launch()
        tap(app.tabBars.buttons["工具"])
        logoutFromTools()
        XCTAssertTrue(app.buttons["connect-button"].waitForExistence(timeout: 15))
    }

    func testWrongPasswordKeepsInputAndShowsMappedErrorNearField() throws {
        let password = app.secureTextFields["server-password"]
        XCTAssertTrue(password.waitForExistence(timeout: 15))
        XCTAssertFalse(text(containing: "看見行情").exists, "品牌標語與功能介紹已移除")
        password.tap()
        password.typeText("wrong-password")
        tap(app.buttons["connect-button"])
        let error = app.descendants(matching: .any)["connection.error.password"].firstMatch
        XCTAssertTrue(error.waitForExistence(timeout: 15))
        XCTAssertTrue(error.label.contains("密碼不正確"), "後端訊息要映射成繁中，不直接顯示原文")
        XCTAssertFalse(text(containing: "測試密碼錯誤").exists)
        XCTAssertGreaterThanOrEqual(error.frame.minY, password.frame.maxY, "錯誤要在密碼欄下方")
        XCTAssertLessThan(error.frame.minY - password.frame.maxY, 60, "錯誤要貼近密碼欄")
        XCTAssertTrue(app.buttons["connect-button"].isEnabled, "密碼沒被清空，按鈕才會是可按的")
        tap(app.buttons["server-password-toggle"])
        XCTAssertEqual(app.textFields["server-password"].value as? String, "wrong-password", "打錯不清空，可切換顯示")
        capture("連線-密碼錯誤")
    }

    func testResearchLibrarySearchesServerAndHasMarketReviewRow() throws {
        let password = app.secureTextFields["server-password"]
        XCTAssertTrue(password.waitForExistence(timeout: 15))
        password.tap()
        password.typeText("fixture-password")
        tap(app.buttons["connect-button"])
        XCTAssertTrue(app.tabBars.buttons["AI 研究"].waitForExistence(timeout: 20))
        tap(app.tabBars.buttons["AI 研究"])
        XCTAssertTrue(app.buttons["research.report.102"].waitForExistence(timeout: 15))
        XCTAssertFalse(text(containing: "已載入").exists, "已載入文案已移除")
        XCTAssertFalse(text(containing: "非勝率").exists)
        XCTAssertTrue(text(containing: "一句話結論").exists, "結論讀 one_sentence")

        tap(app.buttons["research.scope.market"])
        XCTAssertTrue(app.buttons["research.report.201"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.buttons["research.report.201"].label.contains("大盤複盤"))
        XCTAssertFalse(app.buttons["research.report.102"].exists)
        capture("研究庫-大盤複盤")
        tap(app.buttons["research.scope.all"])

        let search = app.searchFields.firstMatch
        XCTAssertTrue(search.waitForExistence(timeout: 5))
        search.tap()
        search.typeText("Apple")
        let onlyApple = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            self.app.buttons["research.report.102"].exists && !self.app.buttons["research.report.201"].exists
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [onlyApple], timeout: 10), .completed, "搜尋由伺服器篩選")
        capture("研究庫-搜尋")
        // 搜尋鍵盤蓋住分頁列，登入狀態交給下一個案例的 setUp 清掉。
    }

    func testWatchlistGroupsCreateMoveAndSwitch() throws {
        let password = app.secureTextFields["server-password"]
        XCTAssertTrue(password.waitForExistence(timeout: 15))
        password.tap()
        password.typeText("fixture-password")
        tap(app.buttons["connect-button"])
        XCTAssertTrue(app.tabBars.buttons["今日"].waitForExistence(timeout: 20))
        tap(app.tabBars.buttons["自選"])
        XCTAssertTrue(app.buttons["stock-row.2330.TW"].waitForExistence(timeout: 10))
        // 還沒有分組時不出現分組籤。
        XCTAssertFalse(app.buttons["watchlist-group-tab.全部"].exists)

        tap(app.buttons["watchlist-edit-groups"])
        let name = app.textFields["watchlist-group-name"]
        XCTAssertTrue(name.waitForExistence(timeout: 5))
        name.tap()
        name.typeText("半導體")
        tap(app.buttons["watchlist-group-add"])
        tap(app.buttons["watchlist-group-move.2330.TW"])
        tap(app.buttons["移到 半導體"])
        tap(app.buttons["watchlist-groups-save"])

        tap(app.buttons["watchlist-group-tab.半導體"])
        XCTAssertTrue(app.buttons["stock-row.2330.TW"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["stock-row.2317.TW"].exists)

        tap(app.buttons["watchlist-group-tab.未分組"])
        XCTAssertTrue(app.buttons["stock-row.2317.TW"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["stock-row.2330.TW"].exists)

        tap(app.buttons["watchlist-group-tab.全部"])
        XCTAssertTrue(app.buttons["stock-row.2330.TW"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["stock-row.2317.TW"].exists)
    }

    func testLastRowIsNotCoveredByTabBar() throws {
        let password = app.secureTextFields["server-password"]
        XCTAssertTrue(password.waitForExistence(timeout: 15), "應顯示測試伺服器的登入畫面")
        password.tap()
        password.typeText("fixture-password")
        tap(app.buttons["connect-button"])
        XCTAssertTrue(app.tabBars.buttons["今日"].waitForExistence(timeout: 20))

        for tab in ["今日", "自選", "AI 研究", "資產", "工具"] {
            tap(app.tabBars.buttons[tab])
            let anchor = app.otherElements["page-bottom-anchor"].firstMatch
            // 資產與研究是惰性列表，底部標記要捲到才存在；先等資料載入再開始捲。
            _ = anchor.waitForExistence(timeout: 5)
            for _ in 0..<8 where !anchor.exists || anchor.frame.maxY > app.tabBars.firstMatch.frame.minY {
                app.swipeUp()
            }
            XCTAssertTrue(anchor.exists, "\(tab) 應有頁面底部標記")
            XCTAssertLessThanOrEqual(
                anchor.frame.maxY,
                app.tabBars.firstMatch.frame.minY,
                "\(tab) 捲到底時最後一列要完整露出，不被分頁列蓋住"
            )
            capture("底部內距-\(tab)")
        }

        // Keychain 跨案例保留；登出才不會讓下一個案例看不到登入畫面。
        tap(app.tabBars.buttons["工具"])
        logoutFromTools()
        XCTAssertTrue(app.buttons["connect-button"].waitForExistence(timeout: 15))
    }

    func testTodayEventsCardRecoversFromFailure() throws {
        try setCalendarFailing(true)
        addTeardownBlock { [self] in try? setCalendarFailing(false) }
        let password = app.secureTextFields["server-password"]
        XCTAssertTrue(password.waitForExistence(timeout: 15))
        password.tap()
        password.typeText("fixture-password")
        tap(app.buttons["connect-button"])
        XCTAssertTrue(app.tabBars.buttons["今日"].waitForExistence(timeout: 20))
        tap(app.segmentedControls["market-picker"].buttons["美股"])
        scrollTo(eventsCard)
        XCTAssertTrue(eventsCardText("暫時無法讀取行事曆").waitForExistence(timeout: 15), "失敗不能顯示成沒有事件")
        XCTAssertFalse(eventsCardText("Apple（測試）").exists)
        capture("事件卡失敗")

        try setCalendarFailing(false)
        tap(app.buttons["today.events.retry"])
        XCTAssertTrue(eventsCardText("Apple（測試）").waitForExistence(timeout: 15), "重試要恢復")

        // 下拉更新也要能恢復：重開讓卡片再次失敗，服務恢復後只靠下拉。
        try setCalendarFailing(true)
        app.terminate()
        app.launch()
        XCTAssertTrue(app.tabBars.buttons["今日"].waitForExistence(timeout: 20))
        tap(app.segmentedControls["market-picker"].buttons["美股"])
        scrollTo(eventsCard)
        XCTAssertTrue(eventsCardText("暫時無法讀取行事曆").waitForExistence(timeout: 15))
        try setCalendarFailing(false)
        sleep(4) // 等連線後的首輪 refresh 跑完，避免下拉被 refreshing guard 略過。
        eventsCard.press(forDuration: 0.1, thenDragTo: app.tabBars.firstMatch)
        XCTAssertTrue(eventsCardText("Apple（測試）").waitForExistence(timeout: 20), "下拉更新要恢復")

        tap(app.tabBars.buttons["工具"])
        logoutFromTools()
        XCTAssertTrue(app.buttons["connect-button"].waitForExistence(timeout: 15))
    }

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

    func testFullReportFailureIsVisibleWithoutExpanding() throws {
        try setFixtureSwitch("markdown-failing", on: true)
        addTeardownBlock { [self] in try? setFixtureSwitch("markdown-failing", on: false) }
        let password = app.secureTextFields["server-password"]
        if password.waitForExistence(timeout: 5) {
            password.tap()
            password.typeText("fixture-password")
            tap(app.buttons["connect-button"])
        }
        XCTAssertTrue(app.tabBars.buttons["AI 研究"].waitForExistence(timeout: 20))
        tap(app.tabBars.buttons["AI 研究"])
        tap(app.buttons["research.report.101"])
        let failure = text(containing: "完整報告讀取失敗")
        scrollTo(failure)
        capture("完整報告失敗狀態")
        try setFixtureSwitch("markdown-failing", on: false)
        tap(app.buttons["重新載入"].firstMatch)
        let recovered = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: failure)
        XCTAssertEqual(XCTWaiter.wait(for: [recovered], timeout: 10), .completed, "重試成功後失敗狀態要消失")
        tap(app.tabBars.buttons["工具"])
        logoutFromTools()
        XCTAssertTrue(app.buttons["connect-button"].waitForExistence(timeout: 15))
    }

    func testReportNewsOpensInSystemBrowser() throws {
        let password = app.secureTextFields["server-password"]
        if password.waitForExistence(timeout: 5) {
            password.tap()
            password.typeText("fixture-password")
            tap(app.buttons["connect-button"])
        }
        XCTAssertTrue(app.tabBars.buttons["AI 研究"].waitForExistence(timeout: 20))
        tap(app.tabBars.buttons["今日"])
        // 主要旅程會更新台積電報告；鴻海保留固定有新聞的 #111，不依賴案例順序。
        tap(app.buttons["stock-row.2317.TW"])
        selectStockTab("news")
        let references = app.descendants(matching: .any)["report.news.references"].firstMatch
        scrollTo(references)
        XCTAssertTrue(text(containing: "SEC 8-K 公告").exists)
        XCTAssertFalse(text(containing: "產業資料頁（合成）").exists)
        capture("新聞-個股頁預設分類")
        selectStockTab("ai")
        tap(app.buttons["stock-report-link"])
        // 舊報告存「減倉」：有枚舉時依枚舉顯示詞彙表用語。
        let storedAction = app.descendants(matching: .any)["report.action"].firstMatch
        XCTAssertTrue(storedAction.waitForExistence(timeout: 10))
        XCTAssertEqual(storedAction.label, "減碼")
        XCTAssertFalse(text(containing: "減倉").exists)
        scrollTo(references)
        XCTAssertTrue(app.links["report.news.link.0"].label.contains("最新新聞（合成）"))
        XCTAssertFalse(text(containing: "EX-99.1").exists)
        XCTAssertFalse(text(containing: "raw_fixture_document").exists)
        capture("新聞-完整報告新聞與公告")
        tap(references)
        scrollTo(text(containing: "市場資料頁（合成）"))
        capture("新聞-展開其他參考資料")
        tap(references)
        let newsLink = app.links["report.news.link.0"]
        tap(newsLink)
        let safari = XCUIApplication(bundleIdentifier: "com.apple.mobilesafari")
        XCTAssertTrue(safari.wait(for: .runningForeground, timeout: 15), "新聞連結應交給系統瀏覽器")
        let screenshot = XCTAttachment(screenshot: safari.screenshot())
        screenshot.name = "新聞-外部瀏覽器"
        screenshot.lifetime = .keepAlways
        add(screenshot)
        try safari.screenshot().pngRepresentation.write(to: screenshotDirectory.appendingPathComponent("新聞-外部瀏覽器.png"))
        app.activate()
        XCTAssertTrue(app.descendants(matching: .any)["report.screen"].firstMatch.waitForExistence(timeout: 10))
        capture("新聞-由外部瀏覽器返回報告")
        // 個股頁隱藏分頁列，先退回今日再切分頁。
        goBackFromReport(to: "鴻海（測試）")
        goBack(from: "鴻海（測試）", to: "今日")
        tap(app.tabBars.buttons["AI 研究"])
        tap(app.buttons["research.report.102"])
        // 舊報告沒有枚舉也只存「減倉」：別名仍顯示減碼；legacy 價位顯示原文。
        let aliasAction = app.descendants(matching: .any)["report.action"].firstMatch
        XCTAssertTrue(aliasAction.waitForExistence(timeout: 10))
        XCTAssertEqual(aliasAction.label, "減碼")
        XCTAssertTrue(text(containing: "等待測試支撐確認").exists, "legacy 價位顯示原文")
        XCTAssertFalse(app.descendants(matching: .any)["report.price.ruler"].firstMatch.exists, "legacy 不畫價位尺")
        scrollTo(text(containing: "這次分析沒有可顯示的新聞或官方公告。"))
        capture("新聞-完整報告空狀態")
        tap(app.tabBars.buttons["今日"])
        tap(app.segmentedControls["market-picker"].buttons["美股"])
        tap(app.buttons["stock-row.AAPL"])
        XCTAssertTrue(app.buttons["stock.tab.news"].waitForExistence(timeout: 15))
        XCTAssertFalse(app.buttons["stock.tab.chips"].exists, "美股沒有籌碼資料，分頁要隱藏")
        selectStockTab("news")
        scrollTo(text(containing: "這次分析沒有可顯示的新聞或官方公告。"))
        capture("新聞-個股頁空狀態")
        goBack(from: "Apple（測試）", to: "今日")
        // Keychain 跨案例保留；登出才不會讓下一個案例看不到登入畫面。
        tap(app.tabBars.buttons["工具"])
        logoutFromTools()
        XCTAssertTrue(app.buttons["connect-button"].waitForExistence(timeout: 15))
    }

    func testTodayCardsAndExclusiveStates() throws {
        try setFixtureFailure("watchlist", true)
        addTeardownBlock { [self] in try? setFixtureFailure("watchlist", false) }
        login()
        XCTAssertTrue(app.navigationBars["今日"].waitForExistence(timeout: 10))
        XCTAssertTrue(text(containing: "合成自選名單失敗").waitForExistence(timeout: 15))
        XCTAssertFalse(text(containing: "建立你的觀察名單").exists, "錯誤與空狀態互斥")
        capture("今日-名單失敗")

        try setFixtureFailure("watchlist", false)
        tap(app.buttons["重新載入"])
        XCTAssertTrue(app.buttons["stock-row.2330.TW"].waitForExistence(timeout: 15))
        XCTAssertFalse(app.buttons["新增自選股"].exists, "今日頁不再有重複的＋")
        XCTAssertTrue(app.descendants(matching: .any)["today.market-status"].firstMatch.label.contains("盤後"))
        XCTAssertTrue(app.buttons["today.review"].label.contains("AI 盤勢"))

        let twii = text(containing: "加權指數（測試）")
        let tpex = text(containing: "櫃買指數（測試）")
        XCTAssertEqual(twii.frame.width, tpex.frame.width, accuracy: 1, "指數卡等寬")

        let assets = app.buttons["today.assets"]
        XCTAssertTrue(assets.waitForExistence(timeout: 15))
        XCTAssertTrue(assets.label.contains("1,800,000"), "資產卡讀換算後的台幣合計，含基金，與資產頁同口徑")
        XCTAssertFalse(assets.label.contains("282,345"), "不能重標頂層 CNY")
        capture("今日-總覽")

        // 異動大：正 2 漲 2%，長榮不到 1%，正 2 要排前面。列在 LazyVStack 裡，先捲到後面那列。
        let strong = app.buttons["stock-row.00631L.TW"]
        let weak = app.buttons["stock-row.2603.TW"]
        scrollTo(weak)
        XCTAssertLessThan(strong.frame.minY, weak.frame.minY)
        tap(app.segmentedControls["today.sort"].buttons["自訂"])
        XCTAssertLessThan(app.buttons["stock-row.2330.TW"].frame.minY, strong.frame.minY, "自訂回到伺服器順序")
        tap(app.segmentedControls["today.sort"].buttons["異動大"])
        logoutFromToolsAfterLogin()
    }

    func testTodayHoldingTodosCardShowsRowsAndFailure() throws {
        login()
        XCTAssertTrue(app.navigationBars["今日"].waitForExistence(timeout: 10))
        let card = app.descendants(matching: .any)["today.holdingTodos"].firstMatch
        XCTAssertTrue(card.waitForExistence(timeout: 15), "資產卡下方要有持股待辦卡")
        let rows = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "today.holdingTodos.row."))
        XCTAssertTrue(rows.firstMatch.waitForExistence(timeout: 10))
        XCTAssertGreaterThanOrEqual(rows.count, 1, "持股待辦至少一列")
        // Fixture: 2317 已觸停損排第一。
        XCTAssertTrue(app.buttons["today.holdingTodos.row.2317.TW"].exists)
        XCTAssertTrue(app.buttons["today.holdingTodos.all"].exists)
        capture("今日-持股待辦")

        // 讀取失敗要明講，不能變成「持股無待處理」。
        try setFixtureFailure("decision-signals", true)
        addTeardownBlock { [self] in try? setFixtureFailure("decision-signals", false) }
        app.terminate()
        app.launch()
        XCTAssertTrue(app.tabBars.buttons["今日"].waitForExistence(timeout: 20))
        XCTAssertTrue(text(containing: "暫時無法讀取持股待辦").waitForExistence(timeout: 15))
        XCTAssertFalse(text(containing: "持股無待處理").exists)
        capture("今日-持股待辦失敗")
        try setFixtureFailure("decision-signals", false)
        logoutFromToolsAfterLogin()
    }

    func testWatchlistSortMetricSwipeAndSearchAdd() throws {
        login()
        tap(app.tabBars.buttons["自選"])
        let expensive = app.buttons["stock-row.2330.TW"]
        let cheap = app.buttons["stock-row.00878.TW"]
        XCTAssertTrue(cheap.waitForExistence(timeout: 15))
        XCTAssertTrue(cheap.label.contains("價格過期"), "過期是例外，要標")
        XCTAssertFalse(expensive.label.contains("價格過期"), "正常報價不警告")
        XCTAssertTrue(expensive.label.contains("持股"), "持股字標")

        tap(app.buttons["watchlist.sort.price"])
        tap(app.buttons["watchlist.sort.price"])
        XCTAssertLessThan(cheap.frame.minY, expensive.frame.minY, "現價遞增")
        capture("自選-現價遞增")
        tap(app.buttons["watchlist.metric-menu"])
        tap(app.buttons["成交值"])
        XCTAssertTrue(expensive.label.contains("74.1 億"))
        capture("自選-右欄成交值")

        app.terminate()
        app.launch()
        XCTAssertTrue(app.tabBars.buttons["自選"].waitForExistence(timeout: 20))
        tap(app.tabBars.buttons["自選"])
        XCTAssertTrue(cheap.waitForExistence(timeout: 15))
        XCTAssertLessThan(cheap.frame.minY, expensive.frame.minY, "排序重開仍記得")
        XCTAssertTrue(expensive.label.contains("74.1 億"), "右欄重開仍記得")
        // 還原，不影響其他案例。
        tap(app.buttons["watchlist.sort.price"])
        tap(app.buttons["watchlist.metric-menu"])
        tap(app.buttons["漲跌幅"])

        tap(app.buttons["watchlist.filter"])
        let filter = app.textFields["watchlist.filter-field"]
        XCTAssertTrue(filter.waitForExistence(timeout: 5))
        filter.tap()
        filter.typeText("長榮")
        XCTAssertFalse(expensive.exists)
        tap(app.buttons["watchlist.filter"])
        XCTAssertTrue(expensive.waitForExistence(timeout: 5), "收合篩選要清掉條件")

        tap(app.buttons["watchlist.scope.held"])
        XCTAssertTrue(expensive.waitForExistence(timeout: 5))
        XCTAssertFalse(cheap.exists, "持股籤只留手上有的")
        capture("自選-持股")
        tap(app.buttons.matching(NSPredicate(format: "identifier == %@ OR identifier == %@", "watchlist.scope.all", "watchlist-group-tab.全部")).firstMatch)

        tap(app.segmentedControls["market-picker"].buttons["美股"])
        tap(app.buttons["新增自選股"])
        let search = app.searchFields.firstMatch
        XCTAssertTrue(search.waitForExistence(timeout: 10))
        search.tap()
        search.typeText("MSFT")
        tap(app.buttons["search.add.MSFT"])
        let added = app.buttons.matching(NSPredicate(format: "identifier == %@ AND label == %@", "search.add.MSFT", "已在自選")).firstMatch
        XCTAssertTrue(added.waitForExistence(timeout: 10), "搜尋面板直接加入")
        capture("自選-搜尋直接加入")
        tap(app.buttons["關閉"])
        tap(app.buttons["search-dismiss"])

        let microsoft = app.buttons["stock-row.MSFT"]
        XCTAssertTrue(microsoft.waitForExistence(timeout: 10))
        microsoft.swipeLeft()
        tap(app.buttons["移除"])
        let gone = expectation(for: NSPredicate(format: "exists == false"), evaluatedWith: microsoft)
        wait(for: [gone], timeout: 10)
        capture("自選-左滑移除")
        tap(app.segmentedControls["market-picker"].buttons["台股"])
        logoutFromToolsAfterLogin()
    }

    func testWatchlistLoadStates() throws {
        addTeardownBlock { [self] in
            for target in ["watchlist", "quotes", "partial"] { try? setFixtureFailure(target, false) }
        }
        try setFixtureFailure("watchlist", true)
        login()
        tap(app.tabBars.buttons["自選"])
        let errorView = text(containing: "合成自選名單失敗")
        XCTAssertTrue(errorView.waitForExistence(timeout: 15), "沒有資料時整頁顯示錯誤")
        XCTAssertFalse(text(containing: "這個市場還沒有自選股").exists, "失敗不能顯示成沒有自選")
        capture("自選四態-載入失敗")

        try setFixtureFailure("watchlist", false)
        tap(app.buttons["重新載入"])
        let row = app.buttons["stock-row.2330.TW"]
        XCTAssertTrue(row.waitForExistence(timeout: 15))
        let banner = app.descendants(matching: .any)["stock-list.banner"].firstMatch
        XCTAssertFalse(banner.exists)
        sleep(4) // 等這輪 refresh 結束，避免下拉被 refreshing guard 略過。

        try setFixtureFailure("quotes", true)
        row.press(forDuration: 0.1, thenDragTo: app.tabBars.firstMatch)
        XCTAssertTrue(banner.waitForExistence(timeout: 15))
        XCTAssertTrue(text(containing: "報價暫時無法取得").exists)
        XCTAssertTrue(row.exists, "報價失敗不能連名單一起丟")
        capture("自選四態-報價失敗")
        try setFixtureFailure("quotes", false)
        sleep(4)

        try setFixtureFailure("partial", true)
        row.press(forDuration: 0.1, thenDragTo: app.tabBars.firstMatch)
        XCTAssertTrue(text(containing: "1 檔沒有報價").waitForExistence(timeout: 15))
        XCTAssertTrue(app.buttons["stock-row.2303.TW"].label.contains("尚無報價"))
        capture("自選四態-部分無報價")
        try setFixtureFailure("partial", false)
        sleep(4)

        try setFixtureFailure("watchlist", true)
        row.press(forDuration: 0.1, thenDragTo: app.tabBars.firstMatch)
        XCTAssertTrue(text(containing: "更新失敗，顯示上次的資料").waitForExistence(timeout: 15))
        XCTAssertTrue(row.exists, "更新失敗保留舊清單")
        capture("自選四態-更新失敗")
        try setFixtureFailure("watchlist", false)
        tap(app.buttons["stock-list.retry"])
        let cleared = expectation(for: NSPredicate(format: "exists == false"), evaluatedWith: banner)
        wait(for: [cleared], timeout: 15)
        logoutFromToolsAfterLogin()
    }

    private func login() {
        let password = app.secureTextFields["server-password"]
        if password.waitForExistence(timeout: 10) {
            password.tap()
            password.typeText("fixture-password")
            tap(app.buttons["connect-button"])
        }
        XCTAssertTrue(app.tabBars.buttons["今日"].waitForExistence(timeout: 20))
    }

    /// Keychain 跨案例保留；登出才不會讓下一個案例看不到登入畫面。
    private func logoutFromToolsAfterLogin() {
        tap(app.tabBars.buttons["工具"])
        logoutFromTools()
        XCTAssertTrue(app.buttons["connect-button"].waitForExistence(timeout: 15))
    }

    private func setFixtureFailure(_ target: String, _ failing: Bool) throws {
        let environment = ProcessInfo.processInfo.environment
        let server = try XCTUnwrap(
            environment["DSA_TEST_SERVER"] ?? environment["DSA_FIXTURE_PORT"].map { "http://127.0.0.1:\($0)" }
        )
        let url = try XCTUnwrap(URL(string: "\(server)/__fixture/fail?target=\(target)&on=\(failing ? 1 : 0)"))
        let done = expectation(description: "fixture 切換 \(target)")
        var status: Int?
        URLSession.shared.dataTask(with: url) { _, response, _ in
            status = (response as? HTTPURLResponse)?.statusCode
            done.fulfill()
        }.resume()
        wait(for: [done], timeout: 10)
        XCTAssertEqual(status, 200)
    }

    private var eventsCard: XCUIElement { app.descendants(matching: .any)["today.events"].firstMatch }

    /// 只在事件卡內找：自選列也有同名公司，全域搜尋會讓事件卡失敗時假綠。
    private func eventsCardText(_ value: String) -> XCUIElement {
        eventsCard.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", value)).firstMatch
    }

    /// 內容分頁可能捲出畫面，tap 內建捲動。
    private func selectStockTab(_ tab: String, file: StaticString = #filePath, line: UInt = #line) {
        let button = app.buttons["stock.tab.\(tab)"]
        XCTAssertTrue(button.waitForExistence(timeout: 15), file: file, line: line)
        // 從報告頁退回時頁面停在原捲動位置；籤被捲到導覽列底下時 isHittable 仍為真，點了卻落在導覽列。
        for _ in 0..<6 where button.frame.minY < app.navigationBars.firstMatch.frame.maxY { app.swipeDown() }
        tap(button, file: file, line: line)
    }

    private func setCalendarFailing(_ failing: Bool) throws {
        try setFixtureSwitch("calendar-failing", on: failing)
    }

    private func setFixtureSwitch(_ name: String, on: Bool) throws {
        let environment = ProcessInfo.processInfo.environment
        let server = try XCTUnwrap(
            environment["DSA_TEST_SERVER"] ?? environment["DSA_FIXTURE_PORT"].map { "http://127.0.0.1:\($0)" }
        )
        let url = try XCTUnwrap(URL(string: "\(server)/__fixture/\(name)?on=\(on ? 1 : 0)"))
        let done = expectation(description: "fixture 切換")
        var status: Int?
        URLSession.shared.dataTask(with: url) { _, response, _ in
            status = (response as? HTTPURLResponse)?.statusCode
            done.fulfill()
        }.resume()
        wait(for: [done], timeout: 10)
        XCTAssertEqual(status, 200)
    }

    private func text(containing value: String) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", value)).firstMatch
    }

    /// 登出是最後一列且要確認。
    private func logoutFromTools(file: StaticString = #filePath, line: UInt = #line) {
        tap(app.buttons["tools.logout"], file: file, line: line)
        let confirm = app.buttons["確認登出"]
        XCTAssertTrue(confirm.waitForExistence(timeout: 5), "登出前必須要求確認", file: file, line: line)
        confirm.tap()
    }

    private func tap(_ element: XCUIElement, file: StaticString = #filePath, line: UInt = #line) {
        scrollTo(element, file: file, line: line)
        XCTAssertTrue(element.isHittable, "控制項無法點擊：\(element)", file: file, line: line)
        XCTAssertTrue(element.isEnabled, "控制項尚未啟用：\(element)", file: file, line: line)
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

    /// 報告頁標題是股名／大盤複盤名稱，會和上一層個股頁同名，所以改認 report.screen 再按導覽列返回鈕。
    private func goBackFromReport(to previousTitle: String, file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertTrue(app.descendants(matching: .any)["report.screen"].firstMatch.waitForExistence(timeout: 5),
                      "應位於報告頁", file: file, line: line)
        let back = app.navigationBars.buttons.matching(NSPredicate(format: "identifier == %@ OR label == %@", "BackButton", previousTitle)).firstMatch
        XCTAssertTrue(back.waitForExistence(timeout: 5), file: file, line: line)
        XCTAssertTrue(back.isHittable, "返回按鈕不可被其他 sheet 遮住", file: file, line: line)
        back.tap()
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
