# Daily Stock AI：iOS App

Daily Stock AI 是本專案的原生 iOS 客戶端，支援台股與美股。核心流程是「行情 → AI 論點 → 依據與風險 → 失效條件」；資料和模型仍由既有 FastAPI 服務提供。

## 功能範圍

| 入口 | 能力 |
| --- | --- |
| 今日 | 台／美指數、自選報價、大盤研究，各筆資料分別標示來源與時間 |
| 自選／個股 | 同步名單、名稱／代碼搜尋、原生日 K／收盤線／成交量、1／3／6 個月與拖曳讀值 |
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

## 行情與研究語意

報價、日 K、研究是不同時點的資料。缺價顯示 `—`，不補0；備援、官方收盤與過期分別標示。台股保留 `.TW/.TWO` 與槓桿字母，美股頁不把 A/H 股當美股。圖表使用 daily OHLCV，範圍以最後資料日為準，不提供週／月 K 聚合或 tick 串流。

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
