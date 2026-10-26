# 實驗：突破候選池基準率重測（`confidence` 錨點 20.2%）2026-10-26

> 研究紀錄（快照）。長期結論只在通過下方判準時寫進 `docs/tw-swing-pipeline.md` 與
> `.claude/skills/tw-swing-research/SKILL.md`。

## 0. 事先登記（跑之前寫好、先 commit）

**為什麼要重測**：`tw-swing-research` 的 E[R] 閘門與 `confidence` 錨點用的 P(≥30%)=20.2%（974 事件），
是在三個讀取端修正之前量的，已標「待重測、暫不可比」：

1. SW-F1：颱風／休市日的除權息因子被丟棄（`market_data.adjust.snap_events_to_sessions` 已修，並由 data-repair 票以合併後邏輯重建 `market.price_adjustment`、修 2017-10-17 價格槽）。
2. 月營收法定期限遇休市順延（`market_data/revenue_deadline.py`）。
3. 宇宙統一：量測與 live 共用 `market_data.adjust.is_common_stock`（research-universe 票，#99）。

**假說**：這三個修正不改變突破候選池「h60 扣成本淨報酬為正、P(≥30%) 高於同池對等基準」的定性結論；
只更新錨點數字。**不把新數字與 20.2% 比好壞**——舊數字的讀取端已知有誤，比較沒有意義，只在原處標作廢。

**訊號（凍結定義，與 `docs/tw-swing-pipeline.md` 第 1 層逐格相同、不改任何門檻）**：
日均額（20 日）≥ 2 億、收盤 > 不含最近 5 天的 60 日高、5 日漲幅 ≥ 5%、5/60 日量比 1.3~2.0、
月營收 YoY ≥ 20%（法定期限有效公告日之後可見、45 曆日保鮮、預設上市口徑）。

**宇宙**：`market.price` 當日有價格列 ∩ `is_common_stock`（四位數普通股，排除 ETF、TDR、特別股）。
創新板不在量測端排除（沿用既有做法，理由見腳本註解）。

**期距**：h60 為主（`confidence` 的定義期距）；h20、h10、h5 為次要（`docs/tw-signal-research-2026-10.md`
對同一池用過的期距），只描述、不作為錨點。事件級去重以各自期距為間隔。

**成本**：`scripts/tw_trade_costs.round_trip_return`（轉出 `src/utils/tw_trade_costs`，與
`src/services/backtest_price_basis.py` 同一真源）：20 萬名目本金、手續費 0.1425%（最低 20 元）雙邊、
賣出證交稅 0.3%、買賣各 0.15% 滑價；T+1 開盤買、第 h 個交易日收盤賣；下市以最後成交價結算（`--delisting last`）。

**時點（PIT）**：價格以 `adjust.load_factors` 前復權；月營收用法定期限有效公告日。
法人資料：凍結定義**沒有法人條件**，不適用（不涉及「入庫為終值而非盤後初值」的問題）。

**樣本窗**：主跑 2020-01-01 ~ 2026-07-24（與舊數字同窗，差異只來自讀取端修正與宇宙），
bootstrap 2,000 次、block = 期距、seed = 42。另跑 h60 `--end 2026-10-22`（DB 最新日）作為標註過的補充列，不作錨點。

**釘住的環境**：程式 HEAD `3a5c5729`（加上本票只新增 P(≥30%) 區間輸出的那個 commit）；`market.price`
最新日 2026-10-22；`market.price_adjustment` 依來源列數 twse_twt49u 15,317／tpex_exdailyq 11,272／
tpex_revivt 296／twse_twtauu 360／inferred_price 22／verified_manual 4。

**判準（全部成立才更新錨點，否則 inconclusive、維持「待重測」）**：

- (a) h60 候選池均值的 circular block bootstrap 95% 區間排除 0。
- (b) h60 候選池的均值**與** P(≥30%) 兩者的點估計都高於「基準(限有月營收)」那一列（腳本沒有對等基準的成對區間，不另建，僅比點估計）。
- (c) h60 事件數 n ≥ 300。
- 錨點本身以 P(≥30%) 的點估計與其 block bootstrap 95% 區間（本票新增的輸出）一起登錄；區間寬度照實寫，不以此判通過與否。

命令（主跑）：

```
uv run --frozen python scripts/measure_signal_forward.py            # h60，預設窗
uv run --frozen python scripts/measure_signal_forward.py --horizon 20
uv run --frozen python scripts/measure_signal_forward.py --horizon 10
uv run --frozen python scripts/measure_signal_forward.py --horizon 5
uv run --frozen python scripts/measure_signal_forward.py --end 2026-10-22   # 補充列
```

（`DATABASE_URL` 由主 checkout 的 `.env` 於同一命令匯出、`STORAGE_DATABASE_URL=''`；唯讀。）

## 1. 結果

（跑完後填。）
