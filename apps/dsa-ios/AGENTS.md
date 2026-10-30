# dsa-ios — 原生 iOS 客戶端

## 模組定位

SwiftUI App（Daily Stock AI），打 repo 根 `api/` 的同一套 `/api/v1`，正式連 NAS 服務。功能範圍、連線與資料語意的正本是 `docs/ios-app.md`，交付紀錄也寫在那裡。

- `Core/`（DSACore）：HTTP client 與模型，不需模擬器，用 `swift test --package-path Core` 測試
- `App/State/AppStore.swift`：全 App 共用的連線、自選、報價與指數狀態；`App/Views/` 是各分頁
- 「工具」分頁不是原生畫面，是用 WKWebView 內嵌既有 Web 頁面並共用登入 cookie

## 進來改要遵守

- `project.yml` 是專案設定來源，新增或搬移檔案後要跑 `xcodegen generate`。重新產生的 `DSAMarket.xcodeproj` 有進版控，要一起 commit。
- `Core/Sources/DSACore/Models.swift` 手動鏡像 `api/v1/schemas/`（沒有 codegen，`DSAClient` 用 `convertFromSnakeCase` 解碼）；欄位改名或型別變了，tsc 和 CI 都抓不到，只會在手機上解碼失敗。
- 由 SwiftUI 持有的 task（`.refreshable`、`.task`）會被框架取消；URLSession 被取消時丟的是 `URLError.cancelled`，不是 `CancellationError`。要寫進共用狀態的載入，改由 store 自己的 `Task` 執行，呼叫端只等它完成。踩過：每次下拉更新報價都失敗，畫面顯示「已取消」。

## 驗證

- 完整流程與證據規格走 `/verify` skill（`features/ios.md`）。
- UI 測試跑在合成的 `scripts/fixture-server.py` 上；要重現正式服務的慢回應，用 fixture 的 `--quote-delay`（`scripts/test-ui.sh` 已帶 2 秒）。

## 模擬器

這台 Mac 還有其他專案的模擬器（`MO …`、`CB …`、`OKI …`），磁碟有限；本 App 只用一台 `DSA iPhone 18 Pro Max`，fixture UI 測試與手動驗證共用。

- 兩者靠 bundle ID 分開：`scripts/test-ui.sh` 建置時把 `DSA_BUNDLE_ID` 設成 `com.audichuang.dsa.fixture`，手動驗證裝的是預設的 `com.audichuang.dsa`，安裝、登入 cookie 與 Keychain 互不覆蓋。改 bundle 設定時別讓兩者變回同一個。
- 一律依名稱在執行時解析 UDID，不把 UDID 寫進檔案；找不到或同名不只一台時停下問使用者。
- 不新增、不刪除、不 erase 模擬器（要換機型先問使用者）；不碰 `MO …`、`CB …`、`OKI …` 與實機。
- 不用 `booted` 別名，不用 `killall` 收 CoreSimulatorService。
- 自己跑 `xcodebuild` 時用 `-destination id=<解析出的 UDID>` 並加 `-parallel-testing-enabled NO`，免得 Xcode 另外 clone 模擬器。
- 一次只跑一個模擬器建置。
