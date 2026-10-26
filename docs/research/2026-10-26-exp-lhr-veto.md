# 實驗：漲停率減跌停率（LHR）否決 2026-10-26

> 研究紀錄（快照）。來源：`docs/research/2026-10-26-analyst-methods-gap.md` 第 7 項（實驗 1）。
> 只報告、**不改 live 篩選規則**。長期結論只在通過判準（或明確反向）時才寫進 `docs/tw-swing-pipeline.md`。

## 0. 事先登記（跑之前寫好、先 commit）

**文獻與疑慮**：Wang & Lien 2022（RQFA 59(2)）指出台股 LHR 越高、後續報酬越低，且效果集中在月營收
公告窗口。但本 repo 自己的研究顯示 20 日波動越高、**均值越高**、右尾越肥（`docs/tw-swing-pipeline.md`
已研究清單「新增的單調因子」），候選池前 12% 事件貢獻 >100% 總報酬；LHR 很可能與高波動高度相關，
否決高 LHR 很可能只是砍掉右尾。

**假說（H1）**：在突破候選池內，否決訊號日 LHR 偏高的事件，能讓留下的池子 h60 扣成本淨報酬的
均值**與** P(≥30%) 同時提高。**預期（批判方的預測）**：不成立——被否決的事件均值較高、右尾較肥。

**訊號（凍結）**：

- 每日收盤漲／跌停：還原後收盤的日報酬 ≥ +9.5% 算收漲停、≤ −9.5% 算收跌停
  （`LIMIT_HIT_THRESHOLD`，與 `portfolio_walkforward.LIMIT_GAP` 同值；10% 漲跌幅制度涵蓋整個樣本窗，
  停板價向下取到升降單位，實際收漲停漲幅約 9.5%~10%）。用還原價是因為除權息日停板價以參考價計算。
  只看收盤、不看盤中觸及（量測端沒載入 low，觸及跌停無法判定，兩邊口徑要一致）。
  前一日無價格（停牌、未上市）那天不算命中；新股上市前五日無漲跌幅限制、漲跌 >10% 也算命中（已知誤差）。
- `淨漲停天數 = 近 20 交易日（含訊號日）收漲停天數 − 收跌停天數`，LHR20 = 淨漲停天數 / 20
  （`scripts/measure_signal_forward.py::limit_hit_net`）。訊號日收盤即可見，T+1 開盤進場，無前視。
- **主判準否決規則：淨漲停天數 ≥ 1（LHR20 > 0）**。次要（描述、不作判準）：淨漲停天數 ≥ 2。
  LHR 是小整數、零值占多數，不用分位切。
- 否決在**事件層**做：先照原定義產生並去重候選事件，再依訊號日 LHR 切「留下／否決」，兩臂嚴格是原池子集
  （不重跑去重，避免否決後同檔晚幾天再觸發混進來）。
- 波動控制：`vol20 = 還原收盤日報酬 20 日標準差`（與 `scripts/backtest_screen.py` 的 `vol20` 同定義）。
  報告事件層 Spearman(LHR, vol20)，並在 vol20 三分位內各自比較留下／否決（描述、無區間）。

**候選池（不改任何門檻）**：`measure_signal_forward.py` 預設參數＝`docs/tw-swing-pipeline.md` 第 1 層：
日均額（20 日）≥ 2 億、收盤 > 不含最近 5 天的 60 日高、5 日漲幅 ≥ 5%、5/60 日量比 1.3~2.0、
月營收 YoY ≥ 20%（法定期限有效公告日之後可見、45 曆日保鮮、預設上市口徑）。

**宇宙**：`market.price` 當日有價格列 ∩ `market_data.adjust.is_common_stock`（research-universe 票合併的共用判定：
四位數普通股，排除 ETF、TDR、特別股）。創新板不在量測端排除（沿用既有做法）。

**期距**：h60 為主；h20、h10、h5 為次要（`docs/tw-signal-research-2026-10.md` 對同池用過的期距），只描述。
事件級去重以各自期距為間隔。

**成本**：`scripts/tw_trade_costs.round_trip_return`（與 `src/services/backtest_price_basis.py` 同一真源）：
20 萬名目本金、手續費 0.1425%（最低 20 元）雙邊、賣出證交稅 0.3%、買賣各 0.15% 滑價；
T+1 開盤買、第 h 個交易日收盤賣；下市以最後成交價結算（`--delisting last`）。

**時點（PIT）**：價格以 `adjust.load_factors` 前復權；月營收用法定期限有效公告日
（`market_data/revenue_deadline.py`）。法人資料：本實驗**只用價格**，不涉及「入庫為終值而非盤後初值」的問題。

**樣本窗**：2020-01-01 ~ 2026-07-24（與錨點重測同窗），bootstrap 2,000 次、block = 期距、seed = 42。

**統計**：`subset_diff_bootstrap`——以交易日區塊做 circular block bootstrap，每次重抽算
`mean(留下) − mean(原池)`（均值、以及 0/1 命中指標＝P(≥30%)）。此差＝(1−否決比例)×(留下 − 否決)，
與「留下 vs 否決」同號。亂數流與既有 `paired_block_bootstrap` 分開，錨點區間不受影響。

**判準（h60、主否決規則，全部成立才算通過；否則 inconclusive）**：

- (a) 留下 − 原池 的**均值**差 > 0，且其 block bootstrap 95% 區間排除 0。
- (b) 留下 − 原池 的 **P(≥30%)** 差 > 0，且其 block bootstrap 95% 區間排除 0。
- (c) 留下 n ≥ 300、否決 n ≥ 100。
- **反向判定**：(a) 與 (b) 的區間都整段 < 0 → 判「否決有害（砍右尾）」，這是可長期保存的死路結論。
- 任一區間跨零、或只有一個指標改善 → inconclusive。

**釘住的環境**：程式 `211b520d`（本票新增 `--lhr` 的 commit）；`market.price` 最新日 2026-10-22；
`market.price_adjustment` 依來源列數 twse_twt49u 15,317／tpex_exdailyq 11,272／tpex_revivt 296／
twse_twtauu 360／inferred_price 22／verified_manual 4。

命令（`DATABASE_URL` 由主 checkout 的 `.env` 於同一命令匯出、`STORAGE_DATABASE_URL=''`；唯讀）：

```
uv run --frozen python scripts/measure_signal_forward.py --lhr               # h60（主）
uv run --frozen python scripts/measure_signal_forward.py --lhr --horizon 20
uv run --frozen python scripts/measure_signal_forward.py --lhr --horizon 10
uv run --frozen python scripts/measure_signal_forward.py --lhr --horizon 5
```

## 1. 結果

（待跑）
