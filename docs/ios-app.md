# Daily Stock AI：iOS App

Daily Stock AI 是本專案的原生 iOS 客戶端，支援台股與美股。核心流程是「行情 → AI 論點 → 依據與風險 → 失效條件」；資料和模型仍由既有 FastAPI 服務提供。

## 功能範圍

| 入口 | 能力 |
| --- | --- |
| 今日 | 台／美指數、自選報價、大盤研究，各筆資料分別標示來源與時間 |
| 自選／個股 | 同步名單、名稱／代碼搜尋、價格走勢頂端是「分時｜日 K｜週 K｜月 K」分頁、區間下拉（1M～5Y、全部，捲動縮放後選單只是回到該寬度）與「⋯」（K 線／收盤線、看懂 K 線）；K 線可捲動與縮放，主圖 MA／EMA／布林、副圖 MACD／KD／RSI、重點標記；長按拖曳讀值 |
| AI 研究 | 原生報告、歷史分頁、已載入資料搜尋、策略價位、證據、失效條件、完整報告與分享 |
| 資產 | 原生現金／市值／損益、分帳戶持股、幣別與報價品質 |
| 工具 | 內嵌既有問股、分析工作台、選股、決策訊號、帳本、基金、回測、告警、資料中心、用量與設定 |

前四項為 SwiftUI／Swift Charts 原生介面。工具使用受認證保護的既有 Web 介面；台股個股頁另開四維度 HTML 檔案。功能是否可執行仍取決於後端設定與資料源。此版沒有券商下單、iOS 推播或行情背景常駐訂閱。

## 連線與帳號

- 正式建置只接受 HTTPS；Debug 另接受 loopback HTTP 供隔離驗證。
- 公網入口為 `https://dsa.audichuang.app`，已透過 Cloudflare Tunnel 部署，仍保留 DSA 密碼認證。舊入口 `https://dsa.ttnas.audichuang.app` 保留，使用它時手機仍需同一 tailnet 與 Tailscale VPN。
- 登入頁可設定服務網址。建置時以 `DSA_SERVER_URL` 預填、`DSA_PREVIOUS_SERVER_URL` 指定舊預設；範例在 `apps/dsa-ios/signing.env.example`，兩者都不是後端 `.env` 欄位。未設定的開發建置仍可開啟連線頁。
- 0.1.2 對同一個新預設只移轉一次：裝置儲存的網址符合舊預設時改用新預設，自訂網址保留；移轉後手動改回私有入口也會保留。Cookie 不跨網域搬移，首次使用公網入口需重新登入。
- 沿用現有單一管理員，沒有新增多人帳號隔離；自選與工具操作會同步到網頁。
- 密碼僅用於當次登入；session cookie 存裝置 Keychain，保留安全屬性。原生 HTTP 使用獨立記憶體 cookie jar，WebKit 使用非持久 store。
- 「登出這部裝置」只清本機登入，不呼叫會輪替全域 session secret 的後端 logout。

### Cloudflare Access Service Token

連線頁提供收合的「Cloudflare Access（選填）」，工具分頁的裝置設定亦有入口。憑證失效時回到連線頁、自動展開該區塊並顯示「Cloudflare Access 驗證失敗，請檢查 Client ID／Secret」；不把 Access 的 302 當作 DSA 密碼失效。已設定的 Secret 不回顯，更換需重新輸入兩個欄位，亦可明確「移除憑證」。離線錯誤保留憑證及原本網路錯誤。

Client ID／Secret 使用獨立 Keychain service，以小寫 scheme／host／有效 port 的 origin 為 key，存取屬性為 `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`，不寫 UserDefaults 或 log。同一 App 身分更新不需重填；登出僅清 `dsa_session`，不刪 Access 憑證。跨裝置還原不保留這組憑證，換服務 origin 則讀另一組，不搬移舊憑證。

原生 HTTP 僅由 `AppStore` 建立獨立 `.ephemeral` URLSession；`DSAClient.responseData` 集中附加 `CF-Access-Client-Id`／`CF-Access-Client-Secret`，每次依 scheme／host／port 核對。跨 origin 轉址全部拒絕，同源轉址重新附加 Header。只有 3xx 且 Location 的 HTTPS host 為 `cloudflareaccess.com` 或其子網域才判為 Access 驗證失敗，一般 403／網路錯誤不誤判。

`.ephemeral` 的私有 `httpCookieStorage` 仍會接收 `Set-Cookie`，只在記憶體保存（[Apple 文件](https://developer.apple.com/documentation/foundation/urlsessionconfiguration/httpcookiestorage)）。工具頁開啟前若缺 `CF_Authorization`，先用原生 `authStatus` 取得；有設定 Token 卻沒有 cookie 時顯示設定錯誤。隨後將 `dsa_session` 與 `CF_Authorization` 注入非持久 WKWebView，再載入頁面；子資源使用 cookie，網頁不接收 Service Token Header。WebKit 導往 Access 登入網域時停止並顯示相同的明確錯誤。取消轉址後收到的 `WebKitErrorDomain` 102 不覆蓋已辨識的 Access 訊息；未擋下 Access 的頁框中斷及一般網路錯誤仍照常顯示。

實際自動登入路徑：`DSAMarketApp.task` → `AppStore.connect()` → 依儲存網址 origin 讀 Access Keychain → 建立 ephemeral session／DSAClient → `SessionVault.restore` 還原 DSA cookie → 原生 `authStatus`（帶 Access Header，同時取得新的 Access cookie）→ DSA session 有效則直接首頁與 refresh。啟動期間顯示連線進度，不要求操作連線頁。後端 401，或 `authStatus` 明確表示尚未登入，才顯示管理員密碼欄位；App 沿用 cookie 的伺服器到期日，不延長後端 session。本次未修改後端 session 年限。

合成 UITest 分開驗證有效／錯誤 Token、終止 process 再啟動、登出保留與明確移除，以及 WebKit 子資源以 cookie 通過。真實 Access 的環境變數與純 UITest 編譯入口見 [iOS README](../apps/dsa-ios/README.md#選用的真實-access-uitest)；未提供憑證就 skip，真機與正式 Access 由使用者另外驗證。

## 行情與研究語意

報價、日 K、研究是不同時點的資料。缺價顯示 `—`，不補0；備援、官方收盤與過期分別標示。台股保留 `.TW/.TWO` 與槓桿字母，美股頁不把 A/H 股當美股。圖表使用 daily OHLCV（profile 以 `history_days=1100` 取約六年），範圍以最後資料日為準；週／月 K 由 App 依交易日聚合（週一起算，開＝首根開、收＝末根收、高低取極值、量相加），均線在完整序列上算完再裁到可見區間（日 K 5／20／60、週 K 5／13／26、月 K 3／6／12）。切到 1Y／3Y 自動換週 K、5Y 換月 K，使用者可再切回。日 K 來源缺當天時，後端用報價補一根 `provisional` 暫定 K（交易日以 `latest_opened_session` 依市場當地時間判定，過期報價不補），App 畫成半透明並標「暫定・即時報價」。週／月 K 的 x 位置與拖曳選取用區間首末交易日的中點。指標（`Indicators.swift`）與重點標記（`KeyPoints.swift`）都在 DSACore：KD 為台股常用 (9,3,3)、起始 50；MACD 柱不乘 2；RSI 為 Wilder 平滑；52 週高低資料不足一年不畫；缺口最多標最近三個未回補者，部分回補時縮成剩下的區間。價格 Y 軸只依可見 K 棒高低決定，超出的指標線被裁掉。分時只在切到該分頁時打 `/api/v1/stocks/{code}/trend?range=day`（台股 Shioaji 分鐘線、其他市場 yfinance 5 分鐘線，只有價沒有量），以市場當地交易時段為 x 軸、24 小時制；昨收取同時抓的 `range=month` 日線中早於分時交易日的最後一根收盤（不用頁面載入時的報價昨收，開過夜會錯日），抓不到就不顯示漲跌；分時與日線分開載入，分時一到就出圖，日線之後補上昨收（fixture `--daily-trend-delay` 守這條）；昨收不納入 Y 軸（大跳空會把走勢壓扁），非交易日顯示最近一個交易日並註明。視窗算術在 `ChartViewport`（右側留白 0.6 根、預設至少 12 根、雙指張開不會變寬）。AI 報告的進場／停損／目標價目前是自由文字，尚未畫上圖（需先改成結構化數值）。不提供 tick 串流。後端 `history_days` 上限為 1825；App 送超過舊上限 365 的值，所以要先部署後端再發 App，否則整份 profile 會 422。

0.1.2 將報價欄改稱「資料參考時間」，因 API 可能回傳供應商時間或資料取得時間，不能僅憑它判斷即時性。空買賣盤顯示「無報價」，一般成交量或損益的有效零值仍保留。行情數量標為「來源成交量（股）」，不宣稱等同交易所全天總量。歷史 API 尚未完整標示還原價／分割調整口徑，不宜假設所有來源同一基準。

日 K 的交易日期、月份範圍與標籤採一致的 date-only 規則，避免裝置時區把日期移到前一天；真實 timestamp 仍依原時間語意顯示。蠟燭實體與成交量柱使用明確日寬，兩圖共用日期範圍與 Y 軸標籤寬度。

AI 直接讀取 `structured_report` 的論點、證據與失效條件，沒有時顯示既有摘要。模型評分不是勝率；App 不推導交易建議。非同步分析明確送 `notify:false`，可離頁後接續查詢；後端回任務不存在時允許重新發起。

0.1.1 起，資產按各帳戶 `base_currency` 分組：新臺幣、美元分開顯示，其他實際存在的幣別也保留。沒有跨幣別總額；不使用後端固定 CNY 的頂層合計，也不自行改標或換算。帳戶內缺匯率時只隱藏該幣別的不可靠合計，不讓換成 CNY 的缺漏影響其他完整原幣組。真實負現金仍保留，帳本編輯沿用工具頁。

看盤首頁與自選使用緊湊分隔列，現價與漲跌固定靠右，AI 日期仍保留。持股列預設呈現價格、損益與股數，成本／來源由明細展開；通用限制集中到中文「資料說明」，缺價／過期／延遲仍就地標示。台股回應中的三條一般限制來自後端固定能力聲明，不再逐筆顯示成一整塊資料錯誤。

輔助使用大字級下，指數改為滿寬縱排，資產、帳戶與個股行情數值改為單欄，持股名稱與金額縱排；可分段捲動閱讀完整金額，不限制系統字級。一般字級仍維持緊湊列表。

## 建置、驗證與交付

建置指令見 [iOS README](../apps/dsa-ios/README.md)，`project.yml` 是 XcodeGen 設定來源，DSACore 是零第三方相依的本地 Swift Package。支援 iOS 17 以上、iPhone／iPad；實際驗證裝置與版本依證據記錄。

Core 單測、合成 HTTP UI 測試、隔離真服務及正式環境四個層級分開記錄。流程見 [iOS 驗證地圖](../.claude/skills/verify/features/ios.md)，實跑狀態見 [驗證紀錄](verification.md)。

TestFlight 完成需同時具備簽章封存、上傳、Apple 有效 build 與自己的內部測試群組；archive／upload exit0 本身不代表可安裝。新 App 記錄可由 Xcode 發佈／驗證精靈沿用既有 Apple 登入建立，也可使用 App Store Connect 網頁。若精靈建立後顯示錯誤，先依 bundle ID 查 API 確認是否已建立，避免重複操作。此交付不推 `main`、不打 Git tag。回滾可停用新 build／改用前一內部 build；移除 App 不影響既有 Web 與資料庫。

### 首次內部發送（2026-10-29）

- App Store Connect App ID：`6828303016`；Bundle ID：`com.audichuang.dsa`。
- 版本 `0.1.0`、build `202610291412` 已上傳並成為 `VALID`，受眾為 `INTERNAL_ONLY`。
- 內部群組「自己」可存取此 build，本人測試者狀態為 `INVITED`；沒有公開測試連結。TestFlight 測試說明已附繁中連線步驟。
- 正式入口沿用 Komodo 的 `ingress-ttnas` 私有 Caddy 反代與既有 wildcard 憑證，手機仍需 Tailscale。此項部署經使用者另外確認；DSA 容器與資料庫未重啟。
- TestFlight tester ID 依 App 分別建立；把同一人的舊 App tester UUID 直接加入新群組會遭拒。使用本人既有 email 與新群組建立關係，不需更動 ASC user 權限。
- 實體手機安裝、首次登入及正式帳本操作仍需與模擬器／隔離服務驗證分開記錄。

### 0.1.1 更新（2026-10-29）

build `202610292218` 已在同一個內部群組開放更新，Apple狀態為 `VALID`／`IN_BETA_TESTING`，不需另建tester。修正資產分幣及列表密度，畫面與測試證據見驗證紀錄；帳本原始金額與後端計算保持原樣。

本次Xcode直傳曾停在取得上傳指示；先用 `asc builds uploads list` 與 `asc builds list` 確認未送達，再停止本輪exporter、改將同一archive匯出為IPA，透過既有 `asc builds upload --app <App-ID> --ipa <IPA-path>` 上傳成功。不要在上傳結果不明時盲目重送，仍須讀回Apple的有效build與群組關係才算可更新。

### 0.1.2 更新（2026-10-30）

本版包含公網預設網址移轉、時間／空委買語意、日 K 日期與實體、量價對齊及大字級修正。簽章封存／IPA 上傳完成，build `202610300059` 已由 Apple 標為 `VALID`／`INTERNAL_ONLY`／`IN_BETA_TESTING`，內部群組「自己」已包含此版，繁中測試說明已寫入。封存的 35 份來源檔案雜湊與提交 `3ab595cc` 一致。

程式已由 [PR #153](https://github.com/audichuang/daily_stock_analysis/pull/153) 在 [CI 40917582436](https://github.com/audichuang/daily_stock_analysis/actions/runs/40917582436) 通過後合進 develop（`5cc6e097`）；未推 main 或 tag。

### 0.1.2 修正版（build 202610300656；2026-10-30）

修正自選頁下拉更新一直顯示「暫時無法取得資料／已取消」、報價不更新：`.refreshable` 的 task 在 store 發布中途結果時被 SwiftUI 取消，最慢的報價請求因此中斷（NAS access log 該輪沒有 quotes 紀錄）。`AppStore.refresh()` 改由 store 自己的 Task 執行；fixture 報價加 `--quote-delay 2` 的 UI test 修前紅、修後綠。程式由 [PR #155](https://github.com/audichuang/daily_stock_analysis/pull/155) 在 CI 40968619038 通過後合進 develop（`656d4a5d`）。從該提交封存（預設 `https://dsa.audichuang.app`，舊入口 `https://dsa.ttnas.audichuang.app`），以 `asc builds upload` 上傳，Apple 回讀為 `VALID`，內部群組「自己」已包含此版，繁中測試說明已寫入；實體手機安裝未在本輪驗證。

Cloudflare Tunnel 已部署；原生 URLSession 已取得公網 200 JSON，受保護 API 未登入回 401。使用者成功公網登入、登入後 cookie 與正式 App/API 流程仍待驗證。

驗收結果及金融資料限制見 [驗證紀錄](verification.md)。回滾可改用前一有效 build，或於登入頁改回私有入口並啟用 Tailscale；本次沒有遷移帳本資料。入口部署回滾依 nas-ops 的 `operator/cloudflare/dsa-public-2026-10-29.md`，只撤回本次 hostname 的設定。

首版介面與本文件為繁體中文，英文索引同步新增入口，未宣稱完整英文在地化。
