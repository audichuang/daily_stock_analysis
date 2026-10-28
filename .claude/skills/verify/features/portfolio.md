# 持股帳本

使用者在獨立帳戶錄入持股與資金，重整後仍讀到相同帳本。首條 journey 從空庫建立帳戶與同幣別入金，證明真實寫入與持久化。

## Sub-features

- `account-create`：建立帳戶並自動切換該帳戶。
- `cash-in`：今天流入 12345 CNY，現金及總權益隨之更新。
- `reload-persistence`：重整後帳戶與餘額仍存在，API/SQLite 列一致。
- `trade-ledger`：買入／賣出、原幣現金、FIFO／AVG 成本。
- `trade-import`：CSV／貼上預演與提交、重複檢查。
- `risk-exposure`：權重、成本、基金重疊曝險、警報、單股分析。
- `account-edit-delete`：編輯、封存、刪除與重放。後三項沒有被首條自動 journey 驗到。

## How to get to it (user POV)

- 側欄「持股帳本」→ `/portfolio`。
- 空庫直接顯示「新建账户」；已有帳戶由建立按鈕展開。
- 單一帳戶下的「手工录入：资金流水」與「事件记录」。全部帳戶視圖不能寫入。
- CLI 持股研究 `.claude/skills/portfolio-check/snapshot.py` 是另一入口，需 Doppler 與真行情，不能用本輪入金替代其驗證。

## Driving it with ego-browser

Preconditions:

- `instance.py launch` 與 Doctor 已通過，`initial-accounts.json` 沒有帳戶。
- 同幣別 CNY、零持股，不需要市場報價、匯率或 LLM。這個種子不證明台股交易計算。

執行 `ego-browser nodejs < "$DSA_VERIFY_RUN/drive-portfolio.mjs"`；helper 使用以下實際控制：

- 前往 `/portfolio`，等待 `input[placeholder="账户名称（必填）"]`，存空畫面。
- 填唯一 run 名稱、券商 `Verification`、`input[placeholder="基准币（如 CNY/USD/HKD）"]` 為 CNY，點 `loc=role:button[name='创建账户']`。帳戶下拉選單出現該名稱。
- 填 `input[placeholder="金额"]` 為 `12345`，保存輸入畫面，點 `loc=role:button[name='提交资金流水']`。畫面出現 `12,345`。
- `select:has(option[value="cash"])` 選 `cash`，資金流水表出現今天／流入／12345／CNY。
- reload 後仍出現帳戶與 `12,345`；GET `/api/v1/portfolio/accounts`、`/api/v1/portfolio/cash-ledger` 各只有一筆對應資料。
- Cleanup 匯出的 `portfolio_accounts` 有 run 名稱與 CNY；`portfolio_cash_ledger` 是同 account_id、`direction=in`、`amount=12345`、`currency=CNY`，日期對應本次今天。檢視 PNG 並保存 SQL 斷言結果。

線上台股交易另驗：UI 新帳戶選 `tw`／TWD，入金 100000、買入 10 股 `2330.TW`、測試成交價 1000，
核對 `accounts[]` 的原幣現金 90000、股數 10、成本 10000，再重整；不拿市價變動當帳本成本。
再買 5 股 @1400、賣 5 股 @1500，原幣現金 90500、持股 10；FIFO 已實現 2500，AVG 為 5500/3。
每次提交成功會清除股票代碼，下一筆要重填；買賣欄限定 `form select:has(option[value="buy"])`，
事件篩選也有 buy/sell 選項，不能用未限定 form 的 select。切成本用 `select:has(option[value="avg"])`。
快照 API 沒有 `currency` query，傳它會被忽略；聚合欄位預設 CNY，缺 TWD/CNY 時 UI 顯示不可用，
應核對缺匯率提示及 `fx_missing`，不能要求畫面直接出現台幣原幣金額。跨幣別成功另需真匯率。

## Gotchas

- 帳本是真實資產、自選只是觀察標的；兩者不能互當種子。近期對話「研究持股趨勢與年底停利策略」也區分這兩者。
- snapshot/risk 的 GET 可能寫入重放結果與每日快照，所以 UI 讀取同樣使用隔離庫。
- 非 CNY、持股或跨幣別 journey 需要真實對應資料；缺少時列 blocked，不能把 fallback 估值當精確市值。
- 表單部分文案目前是簡體；selector 使用現有原文。不可把 persisted view 的語言切換當成產品改動。
- `docs/portfolio-risk-exposure-dashboard.md` 的 mock API screenshot 只證明 fixture；本輪零持股不證明其曝險計算。
- 原始碼：`apps/dsa-web/src/pages/PortfolioPage.tsx`、`api/v1/endpoints/portfolio.py`、`src/repositories/portfolio_repo.py`。
