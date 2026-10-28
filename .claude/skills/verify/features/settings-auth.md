# 設定、認證與登入

## Sub-features

- `/settings`：設定欄位、草稿、儲存與重整後持久化；生成 backend 的真 CLI smoke。
- `/login`：啟用認證、初次設密碼、登出、錯密碼、登入 redirect 與 session 持久化。
- 改密碼、匯入／匯出環境檔、排程及通知測試各自另驗，不由基本設定成功推論。
- 本檔是待執行 recipe；每條結果由本輪證據決定。

## How to get to it (user POV)

由導覽列進設定；報告語言可開 `/settings?category=notification`。
認證卡片在設定頁，開啟後從側欄登出；受保護路由會導向 `/login?redirect=…`。
欄位 id 是 `setting-${item.key}`，來源 `apps/dsa-web/src/components/settings/SettingsField.tsx`。

## Driving it with ego-browser

1. 依上層 Launch／Doctor 核對本輪 URL、ENV_FILE、SQLite 與設定檔位置；保存設定頁 snapshot。
   基本設定可從空庫開始；真 CLI smoke 另需該 backend 可用的登入態與執行檔。
2. 以 `#setting-REPORT_LANGUAGE` 選 `zh-TW`，保存草稿畫面；繁中頁頂用
   `loc=role:button[name*="儲存設定"]`，名稱含異動數量，精確比對會找不到。等待儲存完成再重整。
   等 PUT `/api/v1/system/config` 成功，重整後欄位仍為相同值；
   保存 GET `/api/v1/system/config` 的 `config_version`、對應欄位及本輪 ENV_FILE 該列。
3. 問股需同時啟用 `#setting-AGENT_MODE`，設定 `#setting-AGENT_BACKEND`，Codex 使用 single 架構及正逾時。
   保存後查已知基金 ID，確認 market 連線仍存在。改動涉及生成 backend 時，在
   「AI 模型」分類的 `[data-testid="generation-backend-status-panel"]` 中點重新整理／JSON 冒煙測試；
   不假設 `category=llm` 有效，實跑此值會回基礎分類。
   保存 POST `/api/v1/system/config/generation-backends/smoke-test` 的 `success`、backend 與 diagnostics；
   靜態 executable 檢查或狀態刷新不能代替真生成。失敗保留訊息，不換 mock 宣稱模型可用。
4. 認證旅程在本輪設定的 AuthSettingsCard 勾選啟用，填暫時密碼／確認後提交。
   selectors 取卡片內實際 label；來源 `AuthSettingsCard.tsx`，API POST `/api/v1/auth/settings`。
   核對 GET `/api/v1/auth/status` 的 `authEnabled=true`；後續以這個期望核對認證狀態。
5. 側欄登出並完成 ConfirmDialog；開本輪 `/portfolio`，確認被導到帶 redirect 的登入頁。
   用 `#password` 送一次錯密碼，保留可見拒絕與 HTTP 結果；再送正確密碼，核對回到 redirect。
   若是初次登入設密碼畫面，另填 `#passwordConfirm`，不把它當一般登入欄位。
6. 重整後仍在受保護頁，GET auth/status 仍 loggedIn；再由 UI 登出，確認保護重新生效。
   改密碼屬本輪範圍時，另經 ChangePasswordCard 修改，驗舊密碼失效、新密碼可登入。
7. 保存每步 receipt、畫面、去敏 API 結果及設定前後差異；Cleanup 後確認證據仍在。
   設定、真 CLI smoke、認證各自記結果；不能只憑保存成功訊息標整頁完成。

## Gotchas

- LoginPage 用 `#password` 與 `form button[type="submit"]`；按鈕文字會按狀態變化，不固定叫「登入」。
- 密碼管理器提示是應用外的私人 iframe；用安全 `snapshot()`，先關閉提示再截圖，不儲存密碼庫項目。

- 所有設定與認證操作只對本輪服務；`ENV_FILE` 指到正式 `.env` 時停止寫入。
- `src/auth.py` 把 `.admin_password_hash`、`.session_secret` 放在 DATABASE_PATH 同層；
  密碼、hash、session cookie、token 與完整環境檔均不收進可分享證據，僅保存去敏狀態。
- 預設 Doctor 的認證期望是 false；啟用認證後不能以這個預設斷言取代認證旅程的真結果。
- 排程執行、通知測試與環境檔匯入有額外副作用；基本設定旅程保持排程停用，通知另外授權。
- 實作來源：`SettingsPage.tsx`、`LoginPage.tsx`、`components/layout/SidebarNav.tsx`、
  `components/settings/{AuthSettingsCard,ChangePasswordCard,GenerationBackendStatusPanel}.tsx`；
  API 為 `api/v1/endpoints/{system_config,auth}.py`，設定重載在 `src/services/system_config_service.py`。
