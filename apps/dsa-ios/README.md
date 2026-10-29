# Daily Stock AI for iOS

台股與美股的原生 SwiftUI 看盤 App，連接本專案既有 FastAPI 服務。手機上的核心是「行情 → AI 論點 → 來源與風險 → 失效條件」；完整工具沿用服務端網頁。iOS 17 以上，支援 iPhone／iPad，無第三方 Swift 套件。

功能範圍、連線、資料語意與交付紀錄見 [iOS App 說明](../../docs/ios-app.md)。

## 本機建置

使用現有 Xcode 與 XcodeGen，不自動安裝相依：

```sh
cd apps/dsa-ios
xcodegen generate
xcodebuild -project DSAMarket.xcodeproj -scheme DSAMarket \
  -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build
swift test --package-path Core
```

`project.yml` 是專案設定來源，新增檔案後重新產生 Xcode 專案。預設開啟連線頁；正式服務只接受 HTTPS，Debug 另外接受 loopback HTTP 供隔離驗證。

### 預設入口與更新移轉

公網入口 `https://dsa.audichuang.app` 已由 Cloudflare Tunnel 提供，沿用 DSA 密碼認證；私有 `https://dsa.ttnas.audichuang.app` 仍可透過 Tailscale 存取。以下是 iOS 建置環境，不是後端 `.env`：

| 變數 | 用途 |
| --- | --- |
| `DSA_SERVER_URL` | 本次建置預填的 HTTPS 入口；公網建置設為 `https://dsa.audichuang.app`，留空時由連線頁輸入 |
| `DSA_PREVIOUS_SERVER_URL` | 可選的舊預設入口；本次移轉設為 `https://dsa.ttnas.audichuang.app`，留空不移轉既有設定 |

儲存網址符合舊預設時，同一個新預設只移轉一次；自訂網址與移轉後手動改回的網址保留。Cookie 依主機隔離、不跨域搬移，新入口需重新登入。`scripts/testflight.sh` 會把兩個變數傳入 Xcode 設定。

## 驗證

```sh
xcrun simctl list devices available
bash scripts/test-ui.sh  # 固定使用 DSA Fixture iPhone 17
```

腳本建立動態 port 的合成 HTTP 服務、真啟動 App 操作，保存 `.xcresult` 截圖及日誌；不是市場／模型驗收。11 個工具入口的 fixture 只驗證路由、同源登入與 WebKit 橋接，不代表真實網頁功能全部驗收。大字級金額與 K 線實體／量柱對齊需檢視實際 PNG，不能只看 accessibility 文字。真後端驗收依 [iOS 功能地圖](../../.claude/skills/verify/features/ios.md)。

## TestFlight

先在 App Store Connect 建立 App 記錄，bundle ID 與 `project.yml` 一致。將 [signing.env.example](signing.env.example) 的必要值匯出到 shell；金鑰留在既有秘密管理位置：

```sh
bash scripts/testflight.sh --archive  # 封存、未上傳
bash scripts/testflight.sh --upload   # 封存並上傳內部 TestFlight
```

上傳成功仍須核對 Apple processing 狀態，並將有效 build 加入自己的內部測試群組。此流程不推 `main`、不打 Git tag、不發布 App Store，也不部署後端。

0.1.2（build `202610300059`）已由 Apple 標為 `VALID`／`IN_BETA_TESTING`，內部群組「自己」可更新；首次使用公網網址需重新登入。詳見 [交付紀錄](../../docs/ios-app.md)。
