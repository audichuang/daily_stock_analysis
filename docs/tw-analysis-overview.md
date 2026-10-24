# 台股分析現況總覽（2026-10-23 更新）

> 一頁看懂：每日個股分析抓哪些數據、怎麼判斷、哪些規則會改掉 LLM 的結論、有哪些開關，以及 2026-10-22 那輪診斷與回測**已經回答過的問題**。
> 細節以各連結文件為準；本頁數字或行為和程式不一致時，以程式為準並回頭修這裡。

## 1. 三條線各自做什麼

| 線 | 入口 | 週期 | 產出 |
|---|---|---|---|
| AI 每日個股報告 | 平日 18:00 `make daily-report-detached`（Mac 排程）；NAS Web 臨時分析 | 隔日～數日的操作建議 | `dsa.analysis_history`、`dsa.decision_signals`、推播 |
| 台股波段 | skill `tw-swing-research` / `tw-morning-call`；`scripts/screen_tw.py` 預篩 | 60 個交易日、目標 ≥+30% | `journal/swing-decisions.jsonl`、`morning-calls.jsonl` |
| 價值研究 | skill `value-research`、`earnings-review` | 季、年 | 研究筆記 |

排程與維運見 `docs/daily-report-ops.md`；怎麼讀報告見 `docs/tw-operating-guide.md`。**目前沒有 2～5 天短波段專用的契約與訊號**（待辦，見 §7）。

## 2. 每日個股分析抓的數據

流程：`src/core/pipeline.py::analyze_stock` → 組 context → `src/analyzer.py` 組 prompt → LLM（本機 `claude_code_cli`、NAS 用 LiteLLM）→ `_finalize_and_persist_result` 跑護欄（§3）→ 落庫。

| 數據 | 來源 | 進 prompt | 注意 |
|---|---|---|---|
| 日線 OHLCV、均線、乖離、MACD、RSI、ATR14 | 本地 `market.price`（前復權算指標）→ yfinance | 是 | 顯示價是未還原；指標用還原價（`docs/realtime-board.md`） |
| 即時報價、漲跌停 | Shioaji → yfinance | 是 | `source` 變 `fallback` 代表 Shioaji 金鑰沒注入、已降級 |
| 三大法人（當日＋5／20 日累計） | 當日 TWSE T86／TPEx；趨勢讀本地 `market.institutional` | 是 | 單位是**股**；18:00 拿到的是初版，prompt 標「初版，投信常於隔夜修正」（約 1/4 份報告與定版不同，多在投信欄）；隔日 `daily` 由 `REVISED_SOURCES` 換成定版；上櫃歷史自 2018-01-15（#39） |
| 融資融券（餘額、5／20 場變化、券資比） | 本地 `market.margin` | 是 | 單位是**張**，T+1；上櫃同表 `market='tpex'`（#39） |
| 估值（近四季本益比、淨值比、殖利率） | 上市優先讀本地 `market.valuation` 當日值，退回 `TwseFundamentalAdapter`（BWIBBU 只有 T-1）；上櫃走 TPEx OpenAPI | 是，附 `as_of` 日期 | 整包 `as_of` 落後 10 曆日就拒收 |
| 月營收（單月、月增、年增、累計年增） | 官方 OpenAPI | 是 | 不讀本地 DB 的 16 年 PIT 資料 |
| 月營收動能（前 3 月均年增 vs 本月、強勢股大幅降速） | 本地 `market.monthly_revenue` | 是，資訊列 | `src/services/tw_backtest_context.py`；只當資訊 |
| 大盤狀態（0050 季線與斜率、站上月線／季線家數比例） | 本地 `market.price` 自算 | 是，資訊區塊 | 每日快取一次；附回測可信度文案 |
| 處置／注意股、未來 10 交易日法說會與除權息 | `market_data/risk_flags.py`、`events.py` 即時抓官方 | 是（`TW_LIVE_EVENTS_ENABLED`） | 回應日期不新鮮就寫「未確認」，不寫「否」 |
| 賣方共識（EPS 修正方向、分歧、評級、目標價） | yfinance（`data_provider/analyst_consensus.py`） | 是（`ANALYST_CONSENSUS_ENABLED`，預設關） | 目標價系統性偏多；明寫不得據此提高信心或放寬門檻 |
| 每日大盤脈絡（紅綠燈、複盤摘要、風險標籤） | 當日大盤複盤 | 是 | 黃燈不再自動標 conservative（§3） |
| 新聞 | FinMind 台股新聞（Doppler 注入）→ 通用搜尋 | 是 | 18:00 每日報告的情報搜尋在台股也先走 FinMind；任一維度的來源失敗會換下一個來源；`make analyze` 不含 Doppler，會退回通用搜尋 |
| 財報（營收、淨利、現金流、ROE） | yfinance 季報 | 是 | 逐欄標 `quarter`／`ttm` 口徑 |
| 估值歷史百分位、集保大戶、券商分點、SMC 結構、合約負債 | #39：`market.valuation`、`market.holding_dist`、`tw_broker_branch.py`、`smc_structure.py` | **否**（只在個股檔案：邏輯在 `src/services/tw_stock_dossier.py`，`scripts/tw_stock_dossier.py` 與 Web `/stocks` 都用它） | 集保與上櫃回補 2026-10-22 起跑 |
| A 股主力資金流、龍虎榜 | — | 台股固定 `not_supported` | 這是零買進的主因之一（§4） |

資料取數地圖與坑：`data_provider/AGENTS.md`、`market_data/AGENTS.md`、`docs/market-data-pitfalls.md`。

## 3. 會改掉 LLM 結論的規則（依執行順序）

全在 `src/core/pipeline.py::_finalize_and_persist_result`。每道護欄壓分時，原始分數記在 `dashboard.decision_score_calibration.raw_score`（只補不蓋），影子評估靠它。

1. **結構校準** `stabilize_decision_with_structure`（`src/analyzer.py`）：用支撐／壓力與資金流校準買賣。
   - 資金流**抓取失敗**（failed、空、全 N/A）→ 買進降成「持有觀察」、分數 ≤59。
   - 資金流 `not_supported`（市場沒有這種資料源，台股、美股都是）：
     - `CAPITAL_FLOW_NOT_SUPPORTED_DOWNGRADE=true`（**預設，舊行為**）→ 照樣降級。
     - 設 `false` → 不降級；台股改用三大法人：外資＋投信同買為流入、同賣為流出、其餘中性，再走支撐壓力校準。法人資料日不是最近兩個已收盤場次就當沒有資料。A 股的 `not_supported` 一律照舊降級。
2. **市場階段護欄** `apply_phase_decision_guardrails`：盤前、盤中等階段的措辭與動作限制。
3. **大盤脈絡護欄** `apply_daily_market_context_guardrail`：只在 `high_risk`、`market_cooling`、`low_position_cap` 標籤或明確倉位上限時，把積極買進軟化成觀望、分數 ≤52；「積極買進」只看 LLM 的 `decision_type=buy`（缺值或非法時才用共用 advice 對照表），不再比對報告文字。黃燈單獨出現、「謹慎／觀望」字樣都**不再**觸發（2026-10-22 修）。
4. **交易成本護欄** `apply_trade_cost_guardrail`：扣完來回成本（`TW_BROKER_FEE_DISCOUNT`）後報酬風險比不足就不給買進。

LLM 端還有提示詞的評分規則（`src/analyzer.py` 評分標準、`src/agent/skills/defaults.py`）：上游 A 股「嚴進」哲學，要求多頭排列、乖離 <5%。`TW_MA_ALIGNMENT_WEIGHTED=true` 時，台股改成多頭排列為加分項、乖離 5～10% 限放量突破加 ATR 停損。

## 4. 已經回答過的問題（不要重做）

全部是 2026-10-22 的診斷與回測，完整報告在 [`docs/research/2026-10-22-no-buy-diagnosis.md`](research/2026-10-22-no-buy-diagnosis.md)（零買進診斷）與 [`docs/research/2026-10-22-tw-media-sweep.md`](research/2026-10-22-tw-media-sweep.md)（台灣財經媒體與投行掃描）。量化結論的正本在 [`docs/tw-signal-research-2026-10.md`](tw-signal-research-2026-10.md)。

- **為什麼 873 份報告（2026-07-06～10-22）零買進？** 結構性的，不是 LLM 看空。
  - 主因：資金流 `not_supported` 被當成「缺資料」，LLM 原判買進的 124 份（原始分 60～82）全被壓成 59／持有觀察。這就是分數永遠到不了 70 的原因。
  - 第二層：大盤黃燈一律標 conservative（10 月 84% 報告帶這個標籤）。
  - LLM 層：要求多頭排列。不成立時 LLM 判買進只有 1.2%，成立時 38%。乖離 >5% 不是主因（只占 6.3%）。
- **放寬就會賺嗎？** 沒有證據。
  - 被壓掉的原判買進對其他報告：持有 1／3／5 日的差都跨零（3 日 −0.21%，[−1.84, +1.47]）。
  - 對 0050：3 日 −0.85%，[−1.97, −0.17]（影子評估，n=118，樣本內）。
  - `sentiment_score` 沒有排序能力：剔除 ETF 後分數越高、之後 3 日反而越差。
  - 「觀望」沒有篩選效果：觀望 3 日 −1.11%，全體 −1.10%。
  - 所以資金流修正預設關，先累積影子數據。
- **大盤偏保守該壓買進嗎？** 不該。3～5 日期距下六種大盤狀態對突破候選都跨零。寬度高（>50% 站上季線）之後反而較差；極端超賣（站上月線 <20%）是唯一穩定的逢低訊號。
- **月營收轉弱要擋進場或出場嗎？** 不要。
  - 對突破候選進場全部跨零。
  - 強勢股大幅降速只在 20 日相對落後 1.08pp，但絕對報酬仍正。
  - 「斷創高就出場」不成立。
- **常見短線進場法有用嗎？** 這段期間（約 4 個月）都虧：均線交叉放量、突破 20 日高、外資連 3 買、多頭回踩，3 日淨報酬 −1.2%～−2.5%。現有突破訊號縮到 2～3 日也顯著為負，要 20 日才轉正（2020～2026）。
- **投行預估比較準嗎？** 目標價系統性偏多：31 檔自選中 26 檔有覆蓋，全部高於現價，中位 +34.8%。有用的是 EPS 修正方向與分歧，台股尚未驗證。媒體點名個股的事後表現 inconclusive，主要由進場時點決定。
- **還有哪些財經頻道、PTT 值不值得收？** 2026-10-23 篩過約 20 個頻道，收 4 個、試跑後拿掉 2 個（戰績宣傳、幾乎不點名台股），其餘的不收理由與 PTT `[標的]` 文的試跑見 [`docs/research/2026-10-23-media-sources-expansion.md`](research/2026-10-23-media-sources-expansion.md)。兩者都只是候選來源。
- **年底看多要怎麼用？** 調部位（核心 0050 曝險上限），不放寬個股門檻；用季線、市場寬度、外資現貨＋期貨方向等可量測的狀態代替點位預測，事先寫好失效條件。

## 5. 開關一覽（`.env`；NAS 另在 `config/.env`）

| key | 預設 | Mac 正式（2026-10-23） | 作用 | 建議 |
|---|---|---|---|---|
| `CAPITAL_FLOW_NOT_SUPPORTED_DOWNGRADE` | `true` | 未設（`true`） | `false`＝台股資金流改看三大法人、`not_supported` 不降級 | 等影子數據 2～3 個月 |
| `TW_MA_ALIGNMENT_WEIGHTED` | `false` | `true` | 台股多頭排列改加分項 | 可開，但同時設 `TW_MA_ALIGNMENT_AB_RATIO=0.5`：一半標 `tw-ma-weighted`、一半標 `tw-ma-control` 當同期對照；只開這項（比例預設 1）就沒有對照組 |
| `TW_MA_ALIGNMENT_AB_RATIO` | `1` | `0.5` | 上項的加權組比例 | 實驗期間 `0.5` |
| `ANALYST_CONSENSUS_ENABLED` | `false` | `true` | 賣方共識資訊區塊 | 可開 |
| `TW_LIVE_EVENTS_ENABLED` | `true` | 未設（`true`） | 處置／注意與事件日曆 | 保持開 |
| `TW_BROKER_INDEX_TARGETS` | 空 | 未設 | 人工維護一行券商年底指數目標，30 天未更新就不顯示 | 選用 |
| `PROMPT_VARIANT` | `baseline` | 未設（`baseline`） | 報告上的提示詞版本標籤 | A/B 時改 |
| `TW_BROKER_FEE_DISCOUNT` | `1.0` | 未設（`1.0`） | 手續費折扣，影響交易成本護欄與回測 | 填券商實際折扣 |

## 6. 怎麼量測（改規則前後都要跑）

| 工具 | 回答什麼 |
|---|---|
| `make shadow-buy`（`scripts/shadow_buy_eval.py`，`--by-variant`） | 被護欄壓掉的 LLM 原判買進，若照報告的進場、停損、停利做，2～5 日報酬如何、對 0050 如何；唯讀 |
| `scripts/measure_market_regime.py` | 大盤狀態對前瞻 3／5／10 日報酬 |
| `scripts/measure_revenue_momentum.py` | 月營收動能訊號 |
| `scripts/measure_signal_forward.py`、`backtest_screen.py` | 突破候選池的前瞻分布 |
| `make verify-decisions`（`scripts/verify_swing_decisions.py`） | 波段決策日誌到期回驗（要到期 ≥20 筆） |

判讀規則：95% CI 跨零一律 inconclusive；樣本內、重疊窗口要標；結論寫進 docs 前要過對抗審查（`AGENTS.md` §1.2）。

## 7. 還沒做的

- **2～5 天短波段專用契約與新訊號**：不要把現有突破訊號直接縮短持有期，已證實為負。
- 影子評估累積 2～3 個月後，再決定 `CAPITAL_FLOW_NOT_SUPPORTED_DOWNGRADE` 與 `TW_MA_ALIGNMENT_WEIGHTED`。
- 把 #39 的上櫃籌碼、集保、分點接進個股 prompt（目前只在 dossier）。
- 資料：期交所法人未平倉入庫、當沖比與借券（FinMind 免費）、加權／櫃買指數歷史（`market_index` 只從 2026-07 開始）。
- 強勢股營收降速改用 `decel_lt0`（兩個期距都穩），目前用的是 `decel_le20`。
- `dsa` 正式庫裡有 5 筆測試資料待清（id 3／6／398 等，需使用者確認）。
- 波段日誌 08-14～10-19 停擺：同期 33 個交易日有 27 天有候選，是流程沒跑，不是市場沒機會。
