# 實驗：反波動部位加權、PB≥2 否決 2026-10-26

> 研究紀錄（快照）。來源：`docs/research/2026-10-26-analyst-methods-gap.md` 第 9 項（實驗 5）與第 11 項（實驗 6）。
> 只報告、**不改 live 篩選規則或部位規則**。長期結論只在通過判準（或明確反向）時才寫進 `docs/tw-swing-pipeline.md`。
> 票面寫的檔名是 `2026-10-26-experiments.md`；依同日其他實驗票（`exp-lhr-veto`、`exp-rebaseline-anchor`）的慣例改用本檔名。

## 0. 共用設定（跑之前寫好、先 commit）

**候選池（不改任何門檻）**：`docs/tw-swing-pipeline.md` 第 1 層＝`measure_signal_forward.py` 預設參數：
日均額（20 日）≥ 2 億、收盤 > 不含最近 5 天的 60 日高、5 日漲幅 ≥ 5%、5/60 日量比 1.3~2.0、
月營收 YoY ≥ 20%（法定期限有效公告日之後可見、45 曆日保鮮、預設上市口徑）。

**宇宙**：`market.price` 當日有價格列 ∩ `market_data.adjust.is_common_stock`（research-universe 票合併的共用判定：
四位數普通股，排除 ETF、TDR、特別股）。事件層量測（第 2 節）沿用既有做法不排除創新板；組合層（第 1 節）沿用
`portfolio_walkforward.py` 預設**排除創新板**（與 live `screen_tw.funnel` 一致）。

**成本**：`scripts/tw_trade_costs`（與 `src/services/backtest_price_basis.py` 同一真源）：手續費 0.1425%（最低 20 元）雙邊、
賣出證交稅 0.3%、買賣各 0.15% 滑價；事件層名目本金 20 萬，組合層本金 100 萬、5 個空位；
T+1 開盤買、第 h 個交易日收盤賣；下市以最後成交價結算（`--delisting last`）。

**時點（PIT）**：價格以 `adjust.load_factors` 前復權；月營收用法定期限有效公告日（`market_data/revenue_deadline.py`）。
**法人資料**：兩個實驗都不用法人資料，不涉及「入庫為終值而非盤後初值」的問題。

**樣本窗**：2020-01-01 ~ 2026-07-24（與錨點重測、LHR 實驗同窗）；bootstrap 2,000 次、block = 期距、seed = 42。

**期距**：h60 為主；h20、h10、h5 次要、只描述（`docs/tw-signal-research-2026-10.md` 對同池用過的期距）。

**釘住的環境**：程式 `b40886fa`（本票新增 `--weighting`／`--pb` 的 commit）；`market.price` 最新日 2026-10-22；
`market.price_adjustment` 依來源列數 twse_twt49u 15,317／tpex_exdailyq 11,272／twse_twtauu 360／tpex_revivt 296／
inferred_price 22／verified_manual 4；`market.valuation` 上市 2020-01-02~2026-10-22（1,640,626 列、PB 有值 1,640,364）、
上櫃 2020-01-02~2026-10-22（1,347,764 列、PB 有值 1,347,207）。

命令（`DATABASE_URL` 由主 checkout 的 `.env` 於同一命令匯出、`STORAGE_DATABASE_URL=''`；唯讀）見各節。

## 1. 實驗 5：反波動部位加權（組合層）

**先承認**：這**是隱性擇時，不是新因子**。repo 已判定「PB 與低波動的絕對單調性是市場擇時」
（`docs/tw-swing-pipeline.md` 已研究清單第 9 條），且突破池內**高波動的均值較高、右尾較肥**
（同文件「新增的單調因子」；LHR 實驗也確認否決高波動就是砍右尾）。反波動加權會把錢從高波動候選移到低波動候選，
批判方的預測是：**報酬下降、波動也下降，Sharpe 未必改善**。只測加權，不測「剔除最高波動三分之一」（原分析的變體，依上述已知會砍右尾）。

**假說（H5）**：在同訊號、同排序（live `screen_tw` 公式）、同 5 個空位的組合模擬裡，把每筆部位從等權改成反波動倍數，
組合的逐日報酬會提高。

**加權規則（凍結，`portfolio_walkforward.invvol_weights`）**：

- `vol20` = 還原收盤日報酬 20 日標準差（`measure_signal_forward.volatility20`，與 `backtest_screen.py` 同定義），取**訊號日**值（收盤後可見）。
- 每筆預算 = `前一日收盤權益 / 空位數 × w`，仍受當下現金限制（現金不足就買少或放棄，與等權同一套會計）。
- **主規則 `--weighting invvol`**：`w = clip(參考波動 / vol20_i, 0.5, 2.0)`，參考波動 = 起始以來（含訊號日）**所有訊號格** vol20 的中位數（擴張窗、PIT）；
  累積不到 20 格前、或 vol20 缺值時 `w = 1`。候選池整體變得更波動時所有部位一起縮小——**這就是隱性擇時那一部分**，要靠下面的平均持股比重看出來。
- **次要 `--weighting invvol-xs`**（描述用）：參考波動改成**當日流動池**（日均額 ≥ 2 億）vol20 的橫斷面中位數。突破候選的波動多半高於市場中位，預期平均倍數 < 1。
- 每臂報告平均持股比重（收盤權益扣現金的比例，逐日平均），讓「降槓桿／擇時」看得見。

**判準（h60、主規則 vs 等權，全部成立才算通過；否則 inconclusive）**：

- (a) 逐日組合報酬差（反波動 − 等權）均值 > 0，且其 block bootstrap 95% 區間（block 60、2,000 次、seed 42；
  重用 `paired_block_bootstrap`）排除 0。
- (b) 票面要求的「均值與 P(≥30%) 都改善」在組合層的對應：成交筆的**投入成本加權**均值與成本加權 P(≥30%)（淨報酬）都高於等權臂。
- (c) Sharpe 較高，且最大回撤不比等權深。
- **反向判定**：(a) 的區間整段 < 0 → 判「反波動加權有害」，寫進已研究清單。
- 只有 Sharpe／回撤改善但 (a) 區間跨零 → inconclusive（只是降風險，不算通過）。

**次要（只描述）**：`invvol-xs`（h60）；`invvol` 在 h20／h10／h5（block = 期距）；`invvol --walk-forward`（h60、擴張窗選參）。

命令：

```
uv run --frozen python scripts/portfolio_walkforward.py --weighting invvol               # h60（主）
uv run --frozen python scripts/portfolio_walkforward.py --weighting invvol-xs
uv run --frozen python scripts/portfolio_walkforward.py --weighting invvol --horizon 20
uv run --frozen python scripts/portfolio_walkforward.py --weighting invvol --horizon 10
uv run --frozen python scripts/portfolio_walkforward.py --weighting invvol --horizon 5
uv run --frozen python scripts/portfolio_walkforward.py --weighting invvol --walk-forward
```

## 2. 實驗 6：PB≥2 否決搬到突破池（事件層）

**來源與疑慮**：原研究是 250 日、全流動池、只有上市：PB≥2 相對同日全池 −4.43%，CI [−9.75, −0.44]，上緣只離零 0.44pp，
而且是在大量臂裡挑出來的（`docs/tw-swing-pipeline.md`「唯一 CI 不跨零的方向性結論」）。突破池的條件（YoY ≥ 20、5 日漲幅 ≥ 5%）
多半篩到成長股，**PB≥2 的比例可能很高，否決後池子可能被掏空**；PB 也可能與高波動、右尾相關。

**訊號（凍結）**：

- `PB` = `market.valuation.pb_ratio`（上市 BWIBBU_d／BWIBBU_ALL、上櫃 peQryDate，兩市場都有，2020-01 起），取**訊號日 D** 的值。
  D 日估值以 D 日收盤價計算、D 日盤後發布，早於 T+1 開盤進場，不是前視；淨值用的是交易所當時採用的最近一期財報（交易所的 PIT）。
- 估值缺列時最多沿用前 5 個交易列（`PB_FFILL_DAYS`）；PB ≤ 0 或空白（淨值為負、無法計算）視為缺值。**缺 PB 的事件不否決**（留在留下臂），另行計數。
- **主判準否決規則：PB ≥ 2.0**（含 2.0，與原研究的「PB≥2」同）。不設次要門檻。
- 否決在**事件層**做：先照原定義產生並去重候選事件，再依訊號日 PB 切「留下／否決」，兩臂嚴格是原池子集（與 LHR 實驗共用 `report_subset_veto`）。

**閘門（先量占比，再決定做不做）**：先報 PB≥2 占全部事件與占有 PB 事件的比例、PB 分位、逐年占比、Spearman(PB, vol20)。
**主門檻的留下 n ≥ 300 且否決 n ≥ 100** 才做否決比較；閘門沒過就以「池子會被掏空／否決樣本太少」作結，不做檢定、不換門檻重試。

**判準（h60、閘門通過才跑，全部成立才算通過；否則 inconclusive）**：

- (a) 留下 − 原池 的**均值**差 > 0，且其 block bootstrap 95% 區間（`subset_diff_bootstrap`）排除 0。
- (b) 留下 − 原池 的 **P(≥30%)** 差 > 0，且其 block bootstrap 95% 區間排除 0。
- (c) 即閘門（留下 n ≥ 300、否決 n ≥ 100）。
- **反向判定**：(a) 與 (b) 的區間都整段 < 0 → 判「PB 否決有害」，可長期保存的死路結論。
- 任一區間跨零、或只有一個指標改善 → inconclusive。
- 波動控制：vol20 三分位內各自比較留下／否決（描述、無區間）。

**次要（只描述）**：h20／h10／h5（事件以各自期距去重，同一閘門）。

命令：

```
uv run --frozen python scripts/measure_signal_forward.py --pb                 # h60（主）
uv run --frozen python scripts/measure_signal_forward.py --pb --horizon 20
uv run --frozen python scripts/measure_signal_forward.py --pb --horizon 10
uv run --frozen python scripts/measure_signal_forward.py --pb --horizon 5
```

**限制（事先已知）**：估值只有 2020-01 起（約 6.5 年、單一多頭為主的時期）；月營收存活偏誤與上市口徑同 `measure_signal_forward.py` 說明。
