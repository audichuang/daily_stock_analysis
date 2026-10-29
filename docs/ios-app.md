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
- 登入頁可設定服務網址。`DSA_SERVER_URL` 可在建置時預填，範例在 `apps/dsa-ios/signing.env.example`，不是後端 `.env` 新欄位；未設定的開發建置仍可開啟連線頁。
- 私有 Tailscale 網址需手機登入同一 tailnet 並啟用 VPN，路由與 ACL 決定可達性。安裝 App 不會配置 NAS。
- 沿用現有單一管理員，沒有新增多人帳號隔離；自選與工具操作會同步到網頁。
- 密碼僅用於當次登入；session cookie 存裝置 Keychain，保留安全屬性。原生 HTTP 使用獨立記憶體 cookie jar，WebKit 使用非持久 store。
- 「登出這部裝置」只清本機登入，不呼叫會輪替全域 session secret 的後端 logout。

## 行情與研究語意

報價、日 K、研究是不同時點的資料。缺價顯示 `—`，不補0；備援、官方收盤與過期分別標示。台股保留 `.TW/.TWO` 與槓桿字母，美股頁不把 A/H 股當美股。圖表使用 daily OHLCV，範圍以最後資料日為準，不提供週／月 K 聚合或 tick 串流。

AI 直接讀取 `structured_report` 的論點、證據與失效條件，沒有時顯示既有摘要。模型評分不是勝率；App 不推導交易建議。非同步分析明確送 `notify:false`，可離頁後接續查詢；後端回任務不存在時允許重新發起。

資產合計依回應換算幣別呈現，缺匯率時隱藏不可靠合計，個股保留報價來源／日期／缺價狀態。帳本編輯沿用工具頁。

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

首版介面與本文件為繁體中文，英文索引同步新增入口，未宣稱完整英文在地化。
