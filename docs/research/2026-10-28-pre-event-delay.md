# 實驗：FOMC／CPI／NFP 前一個台股交易日延後進場 vs 正常進場（突破池 h60）2026-10-28

> 研究紀錄（快照）。來源：2026-10-27 策略決策第 6 項（`.claude/reviews/` 不進版控）；登記在
> `journal/experiment-registry.jsonl` 的 `pre-event-delay-h60-breakout`。受測規則是 skill `tw-morning-call`
> Step 2.5 的「重大事件前一天不新建部位，除非 `breakout` 的論點與事件無關」。
> 框架沿用 [`2026-10-26-exp-disposal-delay.md`](2026-10-26-exp-disposal-delay.md)（同一個突破池、成本、成對 block bootstrap）。

## 0. 事先登記（跑之前寫好、先 commit）

**假說（H1）**：突破池中，正常進場日恰好是 FOMC／CPI／NFP 公布前最後一個台股交易日的事件，改成延後到事件公布後
第一個台股交易日進場（持有長度不變），扣成本淨報酬的均值與 P(≥30%) 都比正常進場高。

**事前判斷：預期 inconclusive，先驗偏向不支持。** 理由：`docs/tw-analysis-overview.md` §4 六種大盤狀態對突破候選
3～5 日全部跨零；延後只有 1 個交易日，對 h60 的差距小、雜訊大；前例 disposal-delay 有效配對只有 16～21 個也是
inconclusive。粗估事件前一日約占池 13%、可配對約 120 個。**inconclusive 時 Step 2.5 那條維持「只寫進 `reason`」，
不升級成硬規則、也不刪。** 這是歷史後段驗證（池定義 2026-10 才凍結），不是樣本外。

**事件日對齊（三種事件同一條規則）**：FOMC 決議 14:00 ET（台北次日 02:00／03:00）、CPI 與 NFP 08:30 ET
（台北當日 20:30／21:30），都落在美國公布日 R 的台股收盤（13:30）之後、下一個台股開盤之前。

- `T` ＝ 台股交易日中 `date ≤ R` 的最後一天（R 是台股休市日或週末時往前移）。T 當天 07:30 盤前判讀時事件尚未公布，
  就是規則說的「事件前一天」。
- 受影響事件 ＝ 訊號日 D 的下一個交易日是 T（正常臂 T 開盤買進、抱著事件公布）。
- 延後臂 ＝ 以 T 當訊號日，T 的下一個交易日開盤買進（事件結果已知），**持有同樣 h 日**（出場跟著往後挪一天）。
- 同一個 T 撞到多種事件只算一次（類型合併標記）。

**事件日資料**（研究快取 `~/.cache/dsa/research/pre-event-delay/`，不寫正式 DB；`--fetch` 抓、平常只讀）：

- FOMC：Fed 官網 `fomchistorical2020.htm`（2020，只取例會）＋現行行事曆頁 `fomccalendars.htm`（2021 起，
  沿用 `market_data.macro.parse_fed_calendar`；與 `market.event_calendar` 的 FOMC 列核對一致，見 §1）。
  2020-03 的 17-18 日例會被取消、改開 15 日臨時會：臨時會事前不可知，不算事件；**被取消的 03-18 在當時公布的行事曆上，
  嚴格照「當時已知」的規則會擋 03-17 的進場，這裡沒有算，是已知的一處偏離**。
- CPI（ALFRED rid=10）、NFP（Employment Situation，rid=50）：ALFRED release downloaddates 的首發日。清單混有非首發日期
  （CPI 每年 2 月的季節因子修訂、NFP 的更正與基準預估），規則是「每個日曆月只留一個」：CPI 留當月最後一個、
  NFP 留當月第一個；被丟掉的日期列在 §1。2025 年政府停擺造成的延後與合併發布照 ALFRED 實際日期。
- stlouisfed.org 對帶瀏覽器 User-Agent 的請求會掛住或斷線（2026-10-28 實測），用 requests 預設 UA 即可。

**事件池（凍結定義，與 disposal-delay、rebaseline 逐格相同）**：`measure_signal_forward` 的突破池（日均額 ≥ 2 億、
收盤 > 不含最近 5 天的 60 日高、5 日漲幅 ≥ 5%、5/60 日量比 1.3~2.0、月營收 YoY ≥ 20%），宇宙＝當日有價格列 ∩ 普通股，
事件級去重。h60 為唯一期距。樣本窗 2020-01-01 ~ 2026-07-24。

**成本**：`tw_trade_costs.round_trip_return`（20 萬名目、手續費 0.1425% 雙邊、證交稅 0.3%、買賣各 0.15% 滑價），
平盤來回約 0.882%。延後臂與正常臂各付一次完整來回成本，所以成對差已經是扣成本後的比較；被避開的跌幅要超過 0.882%
才打平這條門檻只在「改成不進場」時才相關（見下方漏掉的交易）。

**判準（事先登記）**：

- 主檢定 ＝ 全部受影響事件（配對後）的「延後 − 正常」成對均值差與成對 P(≥30%) 差，circular block bootstrap
  （block = 60 交易日、2,000 次、seed 42、整段交易日曆、同日橫斷面一起抽；`paired_block_bootstrap`）。
- **兩個 95% 區間都整段 > 0 才算「支持」**；兩個區間都整段 < 0 記「較差」；n < 30 或其餘一律 inconclusive。
  （比 disposal-delay 嚴：那邊 P(≥30%) 差只要點估計 > 0。）
- 同時報：單筆持有期最大回撤（逐日收盤對進場價與之前高點的最大跌幅，毛、兩臂各算）、受影響事件數與占比
  （規則若做成「不進場」就是漏掉的交易數）、延後臂無報酬而掉出配對的數量。
- **子檢定「大局緊縮日」**：機械定義＝T 盤前可見（美國日期 < T）的 FRED DGS10、yfinance `BZ=F`（Brent）、`DX-Y.NYB`（DXY）
  各自 20 個觀測前到最新值的變化同時 > 0；同一判準。預期 n 很小、事前寫明 inconclusive。正式庫 `macro_series`
  只從 2024 起，所以另抓快取。
- **C8 補遺**：訊號日落在 2025-04-07～2025-05-23（借券賣出／融券暫時管制期）的事件分列、標記，不剔除。
- 分事件類型（FOMC／CPI／NFP）、C8、非緊縮日只描述，不作判定。

命令（`DATABASE_URL` 由主 checkout 的 `.env` 只匯出這一個變數、`STORAGE_DATABASE_URL=''`；連線設 `default_transaction_read_only`）：

```
uv run --frozen python scripts/research_pre_event_delay.py --fetch
uv run --frozen python scripts/research_pre_event_delay.py
```

## 1. 結果

（跑完後填）
