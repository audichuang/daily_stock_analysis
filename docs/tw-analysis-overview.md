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
| 日線 OHLCV、均線、乖離、MACD、RSI、ATR14 | 本地 `market.price`（前復權算指標）→ yfinance | 是 | 顯示價是未還原；指標用還原價（`docs/realtime-board.md`）；盤中（含午休、收盤集合競價）僅在趨勢輸入最後一根是今日部分 K（即時疊上或 DB 已有）時，量能狀態標「盤中不判讀」並給中性 10 分，日期不明時也保守不判讀；最後一根仍是昨日完整 K 或已收盤則照常判縮放量，量比標籤不變 |
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
3. **大盤脈絡護欄** `apply_daily_market_context_guardrail`：大盤脈絡出現以下任一項時，把積極買進軟化成觀望、分數 ≤52：`high_risk`、`market_cooling`、`low_position_cap` 標籤；明確倉位上限（`position_cap`）；或大盤摘要（`summary`）文字含退潮／高風險／風險偏高／輕倉／倉位上限／倉位不超過（簡繁皆比對）、英文 high risk／elevated risk／risk-off／cooling／position cap／position limit、韓文 고위험／비중 상한 等詞（清單見 `src/daily_market_context_guardrail.py` 的 `_CONSERVATIVE_TEXT_MARKERS_*`）。判斷個股是不是「積極買進」優先看 LLM 的 `decision_type=buy`（缺值或非法時依序試三態欄位的完整標籤、結構化 `action` 投影、整段就是標籤的建議；都未知就不觸發；`hold` 但分數落在買入區也算），不再比對個股報告文字。黃燈單獨出現、「謹慎／觀望」字樣都**不再**觸發（2026-10-22 修）。這個護欄沒有回測支持（五種大盤狀態對突破候選 h3／h5 全部跨零，見 `docs/tw-signal-research-2026-10.md`），與波段線拒絕 regime 濾網的立場不同，是政策選擇。2026-10-27 起，缺三態時沿用結構化動作契約，不再從自由建議文字補判；`infer_decision_type_from_advice` 只保留既有完整標籤查表（整段查一次，不依 /|,，、 拆段），不做子字串／否定掃描。注意 `_OPERATION_ADVICE_CANONICAL_MAP` 仍與會拆段查表的 `_canonicalize_lookup_value` 呼叫端（如 `get_signal_level`）共用：加繁中別名前先確認那些路徑不會把「不建議買進、加碼」拆成買入。此為上游 #1289 的刻意分歧（記在 skill `dsa-upstream-sync` 的「fork 刻意分歧」）。
4. **交易成本護欄** `apply_trade_cost_guardrail`：扣完來回成本（`TW_BROKER_FEE_DISCOUNT`）後報酬風險比不足就不給買進。
   - 最終動作是買入／加碼，卻缺模型給的買點（`ideal_buy`）、停損價或目標價任一格 → 降為觀望、分數 ≤59，原因點名缺的格子（例「缺停損價／缺目標價，無法檢查報酬風險比」）記進 `guardrail_reason`，代碼 `trade_cost_levels_missing`。持有／觀望但分數落在買入區、又不是結構化賣出時，定稿前會先被分數對齊成買入，因此**也會被檢查**；持有、減碼、賣出、觀望不受影響。價位齊全但順序不合（停損 ≥ 買點等）仍照舊記 `levels_missing`、不降級。
   - 程式**不拿**技術面支撐價頂替模型停損（2026-10-27 移除 Agent 路徑的 `support_levels[0]` 補位）：分析器完整性重試與 Agent 路徑的 `_repair_agent_stop_loss`（同受 `REPORT_INTEGRITY_ENABLED`／`REPORT_INTEGRITY_RETRY` 控制）把支撐位／ATR14 當證據請模型補一次，補不到才由這裡降級。Agent 整份失敗、改走趨勢退路的買入不送模型補。

Web 回測與 DecisionSignal 後驗（也是 Agent 記憶的命中率來源）以 T+1 開盤進場、台股報酬還原除權息，回測另給台股比例式淨報酬；口徑見 `docs/full-guide.md`「回测功能」與 `docs/decision-signals.md`「后验评估与反馈」。

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
- **突破候選池的 `confidence` 錨點還能用嗎？** 2026-10-26 在休市日復權修正、月營收期限順延、宇宙統一之後重測：h60 扣成本 974 個事件，均值 +10.07%（block bootstrap 95% +3.22%~+16.93%），P(≥30%) **20.4%**（14.5%~26.5%），高於對等基準的 +4.69%／12.0%（點估計，未做成對區間，超額本身未檢定）。舊 20.2% 作廢；`screen_tw` 的 `measured_base_rate.p_close60_up_30pct` 與回驗的 `BASE_RATE` 已同步為 0.204（`measured_base_rate` 其餘欄位也已跟改；僅 `survivorship_bias_bound` 與 note 內 9.93%→9.60% 因 `--survivorship-bound` 未重跑，仍是舊值）。見 [`docs/research/2026-10-26-exp-rebaseline-anchor.md`](research/2026-10-26-exp-rebaseline-anchor.md)。
- **近期漲停多（LHR 高）的突破候選要擋掉嗎？** 不要。2026-10-26 實驗：近 20 日淨漲停天數 ≥ 1 就否決，h60 留下的池子均值 −4.35pp、P(≥30%) −5.84pp，兩個 block bootstrap 區間都整段為負；LHR 與 20 日波動相關 +0.78，否決就是砍掉高波動右尾。見 [`docs/research/2026-10-26-exp-lhr-veto.md`](research/2026-10-26-exp-lhr-veto.md)。
- **處置股要剔除或延後進場嗎？** 延後進場沒有證據支持、剔除較差，維持只標記。2026-10-26 用 TWSE 處置公告歷史回測突破池（只上市、2020 ~ 2026-07、舊制 10 日處置）：訊號日已公告、處置期涵蓋進場日的 h60 事件只有 34 個，延後 3／4 日進場對正常進場的成對均值差跨零、P(≥30%) 點估計反而較低（inconclusive；處置中的事件延後等於沒延後，進入配對且實際延後的只有 16／21 個）；剔除則讓池均值 −0.74pp（−1.36~−0.12）、P(≥30%) 也下降（較差，受影響組右尾較肥，但樣本小、靠少數大漲）。2026-08-10 新制（5 日處置）沒有樣本：新制事件自 2026-11 起陸續到期，已到期受影響事件 ≥30 才重跑。見 [`docs/research/2026-10-26-exp-disposal-delay.md`](research/2026-10-26-exp-disposal-delay.md)。
- **部位要不要依波動調整（低波動多買、高波動少買）？PB≥2 要不要擋？** 部位不要依波動調整（已檢定、有害）；PB≥2 否決在突破池不可用（未檢定）。2026-10-26 實驗：反波動加權讓組合年化 45.6% → 32.8%、Sharpe 1.19 → 1.00，逐日報酬差區間整段為負，20 個亂序 seed 全部較差——砍的是高波動右尾。突破池內 76% 事件 PB≥2，否決後池子只剩四分之一，未檢定。見 [`docs/research/2026-10-26-exp-invvol-pb.md`](research/2026-10-26-exp-invvol-pb.md)。
- **常見短線進場法有用嗎？** 這段期間（約 4 個月）都虧：均線交叉放量、突破 20 日高、外資連 3 買、多頭回踩，3 日淨報酬 −1.2%～−2.5%。現有突破訊號縮到 2～3 日也顯著為負，要 20 日才轉正（2020～2026）。
- **投行預估比較準嗎？** 目標價系統性偏多：31 檔自選中 26 檔有覆蓋，全部高於現價，中位 +34.8%。有用的是 EPS 修正方向與分歧，台股尚未驗證。媒體點名個股的事後表現 inconclusive，主要由進場時點決定。
- **還有哪些財經頻道、PTT 值不值得收？** 2026-10-23 篩過約 20 個頻道，收 4 個、試跑後拿掉 2 個（戰績宣傳、幾乎不點名台股），其餘的不收理由與 PTT `[標的]` 文的試跑見 [`docs/research/2026-10-23-media-sources-expansion.md`](research/2026-10-23-media-sources-expansion.md)。兩者都只是候選來源。
- **只看美股是不是片面？多看總經（殖利率、美元、台幣、油價、HYG、VIX、初領失業金）有沒有增量？** 本次規格沒有發現增量證據，確認性比較 inconclusive（待對抗審查）。2026-10-28 用 TAIEX 2010 起、07:30 資訊集做模型階梯：預登記的唯一確認性比較（加總經 vs 只加夜盤、盤中 OC、756 日窗、2017-05 起）增量 R² −2.11%（95% −5.84%~+0.47%，inconclusive），以它交易 0050 扣成本每筆 −0.62%；312 條樣本外序列裡全期顯著的增量只來自費半、美股大盤＋ADR（只對開盤缺口）與台指期夜盤，沒有一組總經變數的邊際貢獻全期 CI 下界 >0（探索性、未排除檢定力不足），2～5 日加總經在 756 窗 OLS 反而顯著變差。四條事件規則（WTI 突破、10Y 新高、台幣急貶、Brent 大漲）全部 inconclusive（同日修正第一個研究日的事件計數、FRED 殖利率跳過美國聯邦假日後重跑，結論不變）。盤前判讀的總經只當描述、不得據此改判。見 [`docs/research/2026-10-28-macro-ladder.md`](research/2026-10-28-macro-ladder.md)。
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
- 資料：當沖比與借券（FinMind 免費）、櫃買指數歷史。加權指數（TAIEX）`market_index` 已有 2010-01-04 起的日資料（含 `open`，共 4,119 列），不再只有 2026-07 起。
- 總經日線、Fed 利率預期（Kalshi）與 FOMC／財報行事曆每天入庫 `market` schema（2026-10-26 起，`MACRO_PERSIST_ENABLED` 預設開），`make morning` 的「大局」段讀它；目前只給盤前判讀用，還沒進個股 prompt（見 `docs/macro-data.md`）。歷史回測已做（2026-10-28，§4），本次規格未發現增量證據、確認性比較 inconclusive，尚待對抗審查；待辦剩 ICSA 首發值（ALFRED）與 07:30 快照，收盤近似與修訂後值的限制才能拿掉。
- skill `tw-morning-call` 的 `SKILL.md`「大局偏緊縮時 `buy` 降一級部位」仍讓總經決定部位大小，和總經模型階梯的處置「維持描述、不得據此改判」不一致；改成只寫進 `reason` 屬 final-decision 第 3 項，尚未落地。
- 期交所法人台指期未平倉已可入庫（`market.taifex_fut_oi`，`TAIFEX_OI_PERSIST_ENABLED` 預設關，2026-10-26 起；只累積不回補，還沒有任何讀取端或回測），P/C 比仍只抓不存。
- 強勢股營收降速改用 `decel_lt0`（兩個期距都穩），目前用的是 `decel_le20`。
- `dsa` 正式庫裡有 5 筆測試資料待清（id 3／6／398 等，需使用者確認）。
- 波段日誌 08-14～10-19 停擺：同期 33 個交易日有 27 天有候選，是流程沒跑，不是市場沒機會。
