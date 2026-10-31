# iOS：Daily Stock AI

入口 `apps/dsa-ios/App/DSAMarketApp.swift`，建置來源 `project.yml`。此地圖補充主 skill 的 Web 地圖，合成數據不替代市場／模型驗證。

## Launch

合成流程：`bash apps/dsa-ios/scripts/test-ui.sh` 固定使用 `DSA iPhone 18 Pro Max`、以 fixture bundle ID 建置，會開獨立 HTTP fixture 並真啟動 App，保存 log／xcresult；缺網址的 skip 不算驗收。

手動／真服務：先執行 `.claude/skills/verify/scripts/ios_sim.sh up`，取得同一台 `DSA iPhone 18 Pro Max` 的 UDID；手動裝的是正式 bundle ID，不會覆蓋 fixture 版。依 `apps/dsa-ios/README.md` 建置後，以 `xcrun simctl install <UDID> <DSAMarket.app>` 安裝。原生操作用桌面控制或 XCTest；Xcode 新版可能在 Device Hub 呈現模擬器。

真服務採主 skill 的隔離 `--online` profile，確認唯讀市場庫與獨立 SQLite。Debug 用 `SIMCTL_CHILD_DSA_TEST_SERVER=<本輪 URL> xcrun simctl launch <UDID> com.audichuang.dsa`。原生畫面是使用者入口，API／SQLite 是第二視角。

## Drive 與終態

| 旅程 | 必備操作與終態 |
| --- | --- |
| 連線／登入 | 錯網址可修正、錯密碼被拒、正確登入讀資料；重開保留安全 cookie；本機登出後再登入，其他裝置不受影響。新舊預設 URL 只移轉一次，自訂網址及移轉後手動改回的網址保留，跨域不搬 cookie；公網成功登入與未登入 401 分開取證 |
| 今日／自選 | 台美切換，比對同代碼、價格、來源與日期；A/H股不混成美股；台股含後綴／美股搜尋、增減後重開名單仍一致。標準字級以七檔fixture確認至少六列完整可見，價格與漲跌可讀；指數完整日期及AI日期保留 |
| 圖表 | 日 K／收盤線、1／3／6個月、單根讀值；OHLCV與回應相同、缺值不補0，分開核對日K與報價日期。台北／美西時區的日期與月份邊界一致；實際截圖須看見寬於影線的蠟燭實體，價格／量柱同日中心對齊，不能只以 chart accessibility element 存在判通過 |
| 行情語意 | 「資料參考時間」不可推論為供應商即時時戳；空買賣盤顯示無報價，正常價格及成交量／損益零值保留。來源成交量與交易所全天量分開核對，不以擷取時間或單位換算證明兩者口徑相同 |
| AI 分析 | 原生按鈕發起，保存task→completed→history ID與真模型；離頁續查、404允許新任務、500保留進行中任務 |
| 研究 | 個股與歷史開同一報告，核對摘要／價位／依據／失效／時間；分頁與搜尋範圍明確，分享得到真報告 |
| 資產 | 用頂層CNY、兩個TWD帳戶及一個USD帳戶的fixture核對原幣分組；CNY換算缺漏不污染完整TWD/USD組。切換幣別後帳戶與金額一致，缺帳戶匯率不顯示不可靠合計；缺價／過期／延遲可見、Shioaji正常價不誤警告；展開成本與中文資料說明、導向正確個股 |
| 工具 | 逐一操作問股、選股、決策訊號、分析工作台、回測、帳本、基金、警報、資料中心、用量、設定 11 個入口；核對路由並沿用同源登入。四維度 HTML 對應正確代碼；匯出產生真檔案及原生分享。fixture 只證明 route／bridge，不代表真實網頁功能全部通過 |
| 輔助字級 | 以 Accessibility XXXL 實看指數、資產總覽、帳戶、持股與個股行情；完整金額、幣別與正負號須可逐項捲入 navbar／tabbar 間，不要求整卡塞一屏。用 PNG／OCR 核對，不以 AX 保留完整字串判通過；還原 large 後再確認六列密度 |
| TestFlight | Release archive／簽章、upload、Apple有效build、內部群組逐步取證；實體手機／正式HTTPS登入另記 |

fixture 允許注入資料與故障且明標合成。真模型由原生按鈕發起，不預先插報告替代流程。帳本／設定寫入只對隔離服務；通知與正式操作沿用既有授權。

## Evidence 與清理

保存commit、build、UDID／OS、profile、操作前後截圖、API／SQLite核對與exit。xcresult需可讀才稱完整測試結果；Xcode測試結束後卡住時保留log並標結果封裝未完成，不算全綠。單測、合成 UI、正式資料唯讀核對、成功公網登入及 Apple build 狀態分開記錄；帳本 FIFO 一致不替代券商對帳單，美股當日高低範圍不替代同時點即時價核對。歷史還原價基準與未解碼策略數值等限制也須保留。

只停本輪fixture PID，依主skill清理隔離後端並保留application-evidence.sqlite3。私人報告、cookie、密碼與Keychain內容不入庫。

手動／真服務驗證結束後執行 `.claude/skills/verify/scripts/ios_sim.sh down` 關機。

## Cloudflare Access（真實服務）

入口：工具分頁「Cloudflare Access 憑證」；連線驗證失敗時連線頁會自動展開同一區塊。

```bash
set -a; . ~/.config/op/agent-sa.env; set +a
# 從 1Password Agent vault 匯出，不寫進指令文字：
#   DSA_REAL_ACCESS_URL、DSA_REAL_ACCESS_CLIENT_ID、DSA_REAL_ACCESS_CLIENT_SECRET、DSA_REAL_DSA_PASSWORD
bash apps/dsa-ios/scripts/test-ui.sh <專用模擬器 UDID> <證據目錄>
```

終態：`testRealCloudflareAccessOptIn` 是 Passed。缺 `DSA_REAL_DSA_PASSWORD` 時它會在 Access 通過後 skip，28 passed、1 skipped 不算驗收。真機依序確認：重開被擋、輸入憑證後恢復、再重開不用重填、工具內嵌頁可開。實跑紀錄見 `docs/verification.md`。
