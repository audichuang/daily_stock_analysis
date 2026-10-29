# iOS：Daily Stock AI

入口 `apps/dsa-ios/App/DSAMarketApp.swift`，建置來源 `project.yml`。此地圖補充主 skill 的 Web 地圖，合成數據不替代市場／模型驗證。

## Launch

使用本輪專用 Simulator，保留其他裝置。依 `apps/dsa-ios/README.md` 建置後，以 `xcrun simctl install <UDID> <DSAMarket.app>` 安裝。原生操作用桌面控制或 XCTest；Xcode 新版可能在 Device Hub 呈現模擬器。

合成流程：`bash apps/dsa-ios/scripts/test-ui.sh <UDID> <證據目錄>`，會開獨立 HTTP fixture 並真啟動 App，保存 log／xcresult；缺網址的 skip 不算驗收。

真服務採主 skill 的隔離 `--online` profile，確認唯讀市場庫與獨立 SQLite。Debug 用 `SIMCTL_CHILD_DSA_TEST_SERVER=<本輪 URL> xcrun simctl launch <UDID> com.audichuang.dsa`。原生畫面是使用者入口，API／SQLite 是第二視角。

## Drive 與終態

| 旅程 | 必備操作與終態 |
| --- | --- |
| 連線／登入 | 錯網址可修正、錯密碼被拒、正確登入讀資料；重開保留安全 cookie；本機登出後再登入，其他裝置不受影響 |
| 今日／自選 | 台美切換，比對同代碼、價格、來源與日期；A/H股不混成美股；台股含後綴／美股搜尋、增減後重開名單仍一致。標準字級以七檔fixture確認至少六列完整可見，價格與漲跌可讀；指數完整日期及AI日期保留 |
| 圖表 | 日 K／收盤線、1／3／6個月、單根讀值；OHLCV與回應相同、缺值不補0，分開核對日K與報價日期 |
| AI 分析 | 原生按鈕發起，保存task→completed→history ID與真模型；離頁續查、404允許新任務、500保留進行中任務 |
| 研究 | 個股與歷史開同一報告，核對摘要／價位／依據／失效／時間；分頁與搜尋範圍明確，分享得到真報告 |
| 資產 | 用頂層CNY、兩個TWD帳戶及一個USD帳戶的fixture核對原幣分組；CNY換算缺漏不污染完整TWD/USD組。切換幣別後帳戶與金額一致，缺帳戶匯率不顯示不可靠合計；缺價／過期／延遲可見、Shioaji正常價不誤警告；展開成本與中文資料說明、導向正確個股 |
| 工具 | 涉及工具沿用登入；四維度HTML對應正確代碼；匯出產生真檔案及原生分享，不以Web成功訊息代替 |
| TestFlight | Release archive／簽章、upload、Apple有效build、內部群組逐步取證；實體手機／正式HTTPS登入另記 |

fixture 允許注入資料與故障且明標合成。真模型由原生按鈕發起，不預先插報告替代流程。帳本／設定寫入只對隔離服務；通知與正式操作沿用既有授權。

## Evidence 與清理

保存commit、build、UDID／OS、profile、操作前後截圖、API／SQLite核對與exit。xcresult需可讀才稱完整測試結果；Xcode測試結束後卡住時保留log並標結果封裝未完成，不算全綠。

只停本輪fixture PID，依主skill清理隔離後端並保留application-evidence.sqlite3。私人報告、cookie、密碼與Keychain內容不入庫。
