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
bash scripts/test-ui.sh  # 預設用 DSA iPhone 18 Pro Max；可選參數 [udid] [evidence-dir]
```

腳本建立動態 port 的合成 HTTP 服務、真啟動 App 操作，保存 `.xcresult` 截圖及日誌；不是市場／模型驗收。11 個工具入口的 fixture 只驗證路由、同源登入與 WebKit 橋接，不代表真實網頁功能全部驗收。大字級金額與 K 線實體／量柱對齊需檢視實際 PNG，不能只看 accessibility 文字。真後端驗收依 [iOS 功能地圖](../../.claude/skills/verify/features/ios.md)。

### Cloudflare Access

連線畫面展開「Cloudflare Access（選填）」，輸入 Client ID／Secret 後按「儲存憑證」再連接。工具分頁的「Cloudflare Access 憑證」可返回設定；驗證失敗也會自動展開該區塊。已儲存只顯示「已設定」，Secret 不回顯，可更換或明確移除。

憑證依 origin（scheme／host／有效 port）存 Keychain，使用 `AfterFirstUnlockThisDeviceOnly`；同一 bundle ID／簽章的 App 更新會保留，登出只清 DSA session。換 origin 不會沿用憑證，這個屬性也不會移轉到另一部裝置。原生請求只向設定的 origin 加上兩個 Access Header，工具子資源使用原生記憶體 cookie jar 取得的 `CF_Authorization`。重新啟動會自動讀取憑證及 DSA cookie 並連線；後端 session 有效即進首頁，過期才需要管理員密碼。

### 選用的真實 Access UITest

沿用 `scripts/test-ui.sh`，在 shell 的既有秘密管理流程匯出以下變數（不要把秘密放進指令文字、`.env`、截圖或版控）：

| 變數 | 用途 |
| --- | --- |
| `DSA_REAL_ACCESS_URL` | 真實 HTTPS 服務網址，例如 `https://dsa.audichuang.app` |
| `DSA_REAL_ACCESS_CLIENT_ID` | Access Client ID |
| `DSA_REAL_ACCESS_CLIENT_SECRET` | Access Secret |
| `DSA_REAL_DSA_PASSWORD` | 首次 DSA 登入時需要；已有有效 session 可省略 |

```sh
bash scripts/test-ui.sh
```

前三個變數未完整設定，`testRealCloudflareAccessOptIn` 會 skip；其餘合成測試仍會執行。測試透過環境預填欄位，按儲存及登入後終止 App，再以不含憑證的環境啟動並開啟工具頁。不用 `typeText` 輸入秘密，避免 XCTest 動作日誌記錄它。憑證預填程式只在腳本額外指定 `DSA_ACCESS_UITEST` 且為 `DEBUG` 時編譯；一般 Debug 與 Release 都沒有這條路徑。測試 runner 透過 `TEST_RUNNER_` 傳遞環境，不把秘密寫入 `.xctestrun`；真實驗收產物仍請留在私人位置。真實測試使用 fixture bundle ID，會保留該 origin 的 Keychain 憑證，可於測試版的設定明確移除；不影響正式 App。

UITest 的管理員密碼於密碼欄位出現時才預填，避免先檢查 Access 的連線動作清掉它。合成 Access 案例會先經由真 UI 清除該 fixture 的既有登入及憑證，彼此不依賴前一案例是否成功清理；真實 Access 的選用測試保留既有 Keychain，不套用這項清理。

## TestFlight

先在 App Store Connect 建立 App 記錄，bundle ID 與 `project.yml` 一致。將 [signing.env.example](signing.env.example) 的必要值匯出到 shell；金鑰留在既有秘密管理位置：

```sh
bash scripts/testflight.sh --archive  # 封存、未上傳
bash scripts/testflight.sh --upload   # 封存並上傳內部 TestFlight
```

上傳成功仍須核對 Apple processing 狀態，並將有效 build 加入自己的內部測試群組。此流程不推 `main`、不打 Git tag、不發布 App Store，也不部署後端。

0.1.2（build `202610300059`）已由 Apple 標為 `VALID`／`IN_BETA_TESTING`，內部群組「自己」可更新；首次使用公網網址需重新登入。詳見 [交付紀錄](../../docs/ios-app.md)。
