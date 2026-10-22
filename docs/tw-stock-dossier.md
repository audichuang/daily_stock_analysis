# 台股個股四維度資料包

`scripts/tw_stock_dossier.py` 把單一台股的基本面、合約負債、籌碼、估值與 SMC 技術結構整理成一份資料包（Markdown 或 `--json`），**只列數字與出處、不下結論**，給人或 LLM 寫個股深度報告用。查不到的欄位一律印「無資料」，不估算。

```bash
uv run --env-file .env python scripts/tw_stock_dossier.py 3324
uv run --env-file .env python scripts/tw_stock_dossier.py 3324.TWO --date 2026-08-28 --json
uv run --env-file .env python scripts/tw_stock_dossier.py 2330 --no-branch   # 不連網查分點
```

唯讀本地 `market` schema；只有券商分點會即時連網。

## 每一段的來源與限制

| 段落 | 來源 | 限制 |
|---|---|---|
| 月營收 13 個月、近 12 月累計年增 | `market.monthly_revenue` | 依公告日過濾（`--date` 之後才公告的月份不會出現）；累計年增要滿 24 個月才算 |
| 季度毛利率／營益率／淨利率／EPS | `market.financial_statement`（`income_sheet`） | 季度標籤由公告截止日換算（`financial_statement.afterIFRS`）。金融保險業實際截止日晚約 15 天，用 `--date` 看歷史時這類公司可能提前看到財報（見 `afterIFRS` 說明） |
| 合約負債 | `financial_statement`（`balance_sheet` 的「合約負債－流動／非流動」） | 約 1,900 家有單獨列示；沒列的公司（如 3324）多半併在其他流動負債，報告寫「無法評估」，不拿別的科目代替 |
| 三大法人 5／20 日 | `market.institutional`（上市＋上櫃） | 單位換成張；窗口內有缺值就不印累計 |
| 融資融券 | `market.margin`（上市＋上櫃） | 單位張、T+1；不含融資使用率（表內沒有限額欄） |
| 千張大戶、股東人數 | `market.holding_dist`（集保） | 開放資料只給最新一週；要週變化得先 `market_data.cli holding-history <代號>` 補歷史（每檔約 51 個請求） |
| 券商分點 | 富邦 DJ 個股主力進出頁（`data_provider/tw_broker_branch.py`） | **只有前 15 名買超與前 15 名賣超**；HHI 只在前 15 名買超分點內計算，「平均買超成本」是這 15 家的加權成本，不是全體大戶成本 |
| 估值 | `market.valuation`（上市 BWIBBU、上櫃 peQryDate） | 本益比百分位要近 3 年至少 120 個有值交易日才算 |
| SMC 結構 | `market.price` 套前復權（`market_repo.front_adjust_multipliers`）後算 | 定義寫死在 `src/services/smc_structure.py` 模組說明（擺動點 n=3、收盤突破才算、OB／FVG／Fib 的取法）；SMC 沒有統一標準，換定義數字就不同 |

## 和 botbook.cc 範例報告的對照

2026-10-22 拿 botbook.cc 的 3324 雙鴻報告（基準日 2026-08-28）逐項對照：

- **分點 HHI 959 與我們用前 15 名買超分點算出的完全一致**，前 5 名買超分點與張數也逐筆相同——對方的 HHI 同樣只用前 15 名，不是全市場分點。
- 季度毛利率／營益率／淨利率／EPS 八季逐格一致；本益比 26.29、融資使用率 20.21% 與 TPEx 端點原始欄位一致（資料包目前不輸出融資使用率：`market.margin` 沒存融資限額）。
- **對方月營收整條錯一個月**：標成「26/08 3,765,466（+116.7%）」的其實是 2026-07（8/10 公告），8 月營收要到 9/10 才公告，基準日 08-28 時不可能有。
- 「C9S 籌碼九階段」與「大戶成本 L5」是對方自訂的衍生指標，沒有公開定義，這裡不做。

## 上線順序（正式庫）

1. 安靜時段對正式庫套 migration `d3a8b6e15c27`（只加欄位與新表，`lock_timeout` 10 秒，拿不到鎖就失敗重跑）。
2. 合併並部署新程式到所有會寫 `market` schema 的地方：本機排程共用的主 checkout（`docs/daily-report-ops.md`）要切回含這次改動的分支；NAS Web 只讀不寫，不受影響。
3. 之後才回補上櫃（`backfill institutional_tpex|margin_tpex|valuation_tpex`）或讓 `daily` 抓上櫃。順序反過來，舊程式的 resume／整日換血看不到 `market` 欄，會把同一天的上市、上櫃當成同一份。

回滾（順序不能反：舊程式看不到 `market` 欄，上櫃列還在時它的整日換血會把上櫃一起刪掉、refresh 會因列數對不上而拒絕上市修正）：

1. 先停所有寫入 `market` schema 的排程。
2. **還在新程式時**匯出 `holding_dist` 與上櫃列，再 `DELETE FROM market.<institutional|margin|valuation> WHERE market='tpex'`、清空 `holding_dist`。
3. 降版 migration（表內還有上述資料時會拒絕執行）。
4. 最後才把主 checkout 退回舊程式、恢復排程。

## 相關

- 上櫃法人／融資／估值與集保怎麼更新、回補：skill `update-market-data`、`docs/market-data-pitfalls.md`
- 只抓不入庫的處置／注意股、事件日曆：`market_data/risk_flags.py`、`market_data/events.py`
