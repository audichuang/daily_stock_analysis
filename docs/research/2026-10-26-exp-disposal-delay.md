# 實驗：處置公告後延後進場 vs 正常進場 vs 剔除（只上市）2026-10-26

> 研究紀錄（快照）。來源：`docs/research/2026-10-26-analyst-methods-gap.md` 第 5 項（實驗 4 改寫）。
> 長期結論只在通過下方判準時寫進 `docs/tw-swing-pipeline.md`／`docs/tw-analysis-overview.md` 的已研究清單；
> **不論結果如何都不改 live 篩選規則**（目前「只標記、不剔除」）。

## 0. 事先登記（跑之前寫好、先 commit）

**背景**：劉燕宜 2022（台大碩論，樣本 2018-01～2021-06）指公告後前 3 天異常報酬顯著為負、約 3 天後回升，
對 h60 持有期比較支持「延後 3～4 天進場」而不是「剔除」。2026-08-10 起處置期 10→5 日、撮合改約 2 分鐘一次，
論文樣本完全在新制之前。

**假說（H1）**：對突破候選池中「訊號日收盤時已公告處置、且處置期涵蓋進場日」的事件，延後 3 或 4 個交易日進場
（持有長度不變）比正常 T+1 進場的扣成本淨報酬均值較高、P(≥30%) 也較高。
**對立的剔除假說（H2）**：從池中剔除這些事件，池均值與 P(≥30%) 都提高。

**資料**：TWSE `rwd/zh/announcement/punish` 2013 起的上市處置公告，`scripts/fetch_twse_disposal_history.py`
逐年抓、去重後存 `data/twse_punish_history.csv`（gitignore，不入庫；列數、公布日範圍、sha256 前 16 碼記在 §1）。
端點的區間語意是「處置期與查詢區間重疊」（2021 上下半年 169＋183 列、全年 336 列、重疊 16 列，實測），所以分段抓後去重。
上櫃處置的歷史端點未核實，**只做上市**：上市判定＝種子檔 `.TW`（`scripts/stock_index_seeds/stock_list_tw.csv`
不是 `.TWO` 的都算上市；已下市的上櫃公司不在種子檔，若混入池會被當成上市且永遠不會被處置名單命中——§1 記這個數）。

**制度沿革**：處置期長度以 `market.price` 交易日曆數，不從中文「五個營業日」反推；撮合間隔從處置內容抽
「約每 N 分鐘撮合一次」。`--timeline` 依公布年份（2026 拆 08-10 前後）、第一次／第二次處置分列。只描述、不是判準。

**事件池（凍結定義，與 `2026-10-26-exp-rebaseline-anchor.md` 逐格相同、不改任何門檻）**：
日均額（20 日）≥ 2 億、收盤 > 不含最近 5 天的 60 日高、5 日漲幅 ≥ 5%、5/60 日量比 1.3~2.0、
月營收 YoY ≥ 20%（法定期限有效公告日之後可見、`market_data/revenue_deadline.py`、45 曆日保鮮、上市口徑）。
宇宙：`market.price` 當日有價格列 ∩ `market_data.adjust.is_common_stock`。事件級去重以各自期距為間隔。

**受影響事件（訊號）**：事件訊號日 D，存在一筆處置公告，公布日 A ≤ D（A 落在非交易日時取之前最後一個交易日），
且處置期 [S, E] 涵蓋進場日 D+1。這與 live `risk_flags` 以 next_session 查名單同語意（處置中／即將處置），
量的就是 live 旗標會標到的那批。D 之後、D+h 之內才公告的（持有中才知道）只計數、不入任何臂。

**各臂**（都在同一批受影響事件上配對）：

- 正常：D+1 開盤買、D+h 收盤賣。
- 延後 k（k = 3、4）：以 max(D, A+k) 為「訊號日」，即公告後第 k+1 個交易日開盤買，**持有同樣 h 日**
  （出場跟著往後挪；只挪進場不挪出場會讓持有長度不同，比較無意義）。
- 處置期後（次要、只描述）：以 max(D, E) 為訊號日，處置迄日後第一個交易日開盤買、持有 h 日。迄日用公告當下的值，
  順延不另推算。
- 剔除：受影響事件從上市池移除，比較「未受影響池」與「上市全池」。

**期距**：h60 為主；h20、h10、h5 為次要（與 rebaseline 同一組），只描述。

**成本**：`scripts/tw_trade_costs.round_trip_return`（真源 `src/utils/tw_trade_costs`，與
`src/services/backtest_price_basis.py` 同源）：20 萬名目本金、手續費 0.1425%（最低 20 元）雙邊、賣出證交稅 0.3%、
買賣各 0.15% 滑價；下市以最後成交價結算（`--delisting last`）。處置股撮合間隔 5～45 分鐘、可能要預收款券，
**實際滑價可能高於 0.15%**——對正常臂（處置期內進場）不利、對延後臂中延後到處置期後者有利，這個偏誤方向記為限制。

**時點（PIT）**：TWSE 在 A 日收盤後公告，D+1 開盤前已公開，A ≤ D 的列可用。價格以 `adjust.load_factors` 前復權。
法人資料：凍結定義沒有法人條件，不涉及「入庫為終值而非盤後初值」的問題。

**樣本窗**：2020-01-01 ~ 2026-07-24（與 rebaseline 主跑同窗）；bootstrap 2,000 次、block = 期距、seed = 42。
新制（2026-08-10 起）的 h60 事件在此窗與現有資料下一定為 0，新制**無法**由本實驗評估，結論只適用舊制。

**判準**（每臂、每期距各自判；h60 才算數）：

- 受影響事件（配對後）n ≥ 30，否則 inconclusive。
- 延後 k 通過 ＝ 成對均值差（臂 − 正常）與成對 P(≥30%) 差的點估計**都 > 0**，且均值差的成對 circular block
  bootstrap 95% 區間整段 > 0（`paired_block_bootstrap`）。P(≥30%) 差的區間照實列、不作通過條件。
- 剔除通過 ＝ 「未受影響池 − 上市全池」的均值差與 P(≥30%) 差點估計都 > 0，且均值差的 block bootstrap 95%
  區間整段 > 0（`exclusion_block_bootstrap`，同取樣核心、統計量為兩組均值差）。
- 兩個點估計都 < 0 且均值差區間整段 < 0 記「較差」；其餘一律 inconclusive。
- k = 3 與 k = 4 是兩次檢定、沒有多重比較校正：只有一個通過時記「弱、未經校正」。

命令（`DATABASE_URL` 由主 checkout 的 `.env` 於同一命令匯出、`STORAGE_DATABASE_URL=''`；唯讀）：

```
uv run --frozen python scripts/fetch_twse_disposal_history.py --last-day 2026-10-26
uv run --frozen python scripts/fetch_twse_disposal_history.py --timeline
uv run --frozen python scripts/measure_signal_forward.py --disposal-cache data/twse_punish_history.csv               # h60
uv run --frozen python scripts/measure_signal_forward.py --disposal-cache data/twse_punish_history.csv --horizon 20
uv run --frozen python scripts/measure_signal_forward.py --disposal-cache data/twse_punish_history.csv --horizon 10
uv run --frozen python scripts/measure_signal_forward.py --disposal-cache data/twse_punish_history.csv --horizon 5
```

## 1. 結果

（待跑）
