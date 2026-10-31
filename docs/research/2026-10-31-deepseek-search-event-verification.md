# DeepSeek 搜尋與事件後走勢驗證 2026-10-31

## 基線與範圍

本地 HEAD `96761715f980384b0016d213093a726f28d09759`，分支 `feat/us-sec-evidence`；fetch 後遠端基線 `origin/develop` 為 `b3306e727be7360b9de48625b8d6a619f5348edb`。目前分支含前次 SEC commit，不能從遠端 fast-forward，故保留原 worktree，不 merge／rebase。環境沿用本 worktree 的獨立 Python 3.12 venv，命令皆 `uv run --frozen`；沒有改依賴、模型設定或部署。

驗收遵守禁止事項：不跑真 LLM、不連正式 DB、不動 NAS、不發通知。DeepSeek 金鑰由使用者指定的 1Password 路徑即時注入子程序環境，Tavily 沿用主 checkout 已有的搜尋金鑰；均不寫檔、不印出、不匯出其他 `.env` 值。DB 變數保持空白，沒有以讀主 checkout 的 `.env` 載入正式 DB。新 provider HTTP 與四檔多面向搜尋是真實 API；模型、歷史保存與 FinMind 優先為隔離測試，層級分開。

## 日期調查

[官方文件](https://api-docs.deepseek.com/guides/search/) 宣稱 `date` 是 UTC RFC 3339，但 INTC 與 GOOG 各 6 筆（12／12）都為 `16:00:00+00:00`；四檔多面向搜尋的 DeepSeek 原始結果另有 72／72 筆同樣固定於此時刻。完整原始日級值與查詢保存在本輪本機證據，不從前綴直接斷言美東發布日期。

| 對照來源 | DeepSeek 原始值 | 原文與其他一手證據 | 本次日級輸出 |
| --- | --- | --- | --- |
| [Intel 官方新聞稿](https://www.intc.com/news-events/press-releases/detail/1786/intel-reports-third-quarter-2026-financial-results) | `2026-10-28T16:00:00+00:00` | `<time datetime="2026-10-29T16:01:00">`，頁面明標 `Oct 29, 2026 • 4:01 PM EDT` | 2026-10-29 |
| [Alphabet Q3 逐字稿原頁](https://stockanalysis.com/stocks/googl/transcripts/712854-q3-2026/) | `2026-10-27T16:00:00+00:00` | 頁首 `Oct 28, 2026`；前次 SEC 8-K 官方送件時間 `2026-10-28T20:01:33.000Z`（送件時間不是發布時間） | 2026-10-28 |

推論：這批結果把來源日曆日按 UTC+8 午夜包成時間戳，轉成 UTC 後成為前一天 16:00；不是可用的發布時刻。僅針對精確符合此型態的值還原 UTC+8 日期，其他帶時區時間使用 UTC 日，不一律加一天，不依伺服器時區換日。每則摘要加「日期未經原文核實／日級日期非精確發布時間」，不能因引擎回傳 UTC 格式就當作核實事件時間。Yahoo 原文抓取回 429、James Sharp 頁回 403，未拿這兩頁主張已完成原文對照，也未補造時間。

三天新聞窗口仍僅包含今天與前兩個日曆日；邊界測試釘住前兩天可保留、前三天與更舊仍剔除。未知日期在嚴格新聞面向省略並實際改查下一來源，不以 `retrieved_at` 冒充發布時間。機構／財報面向沿用既有 180 天且允許未知日期，所以下表的較舊財報與未知日期並不代表三天新聞守門被放寬。

## 真實多面向搜尋

實際呼叫 `SearchService(deepseek_keys=..., tavily_keys=..., news_max_age_days=3, searxng_public_instances_enabled=False).search_comprehensive_intel(code, name, max_searches=5)`。本輪沒有 FinMind token，所以台股最新消息由 DeepSeek 回覆；FinMind 優先另有真路徑 fixture 測試。每面向向 provider 要 6 則，經既有時效與關聯流程保留最多 3 則。下列日期為送入 prompt 的日級值，`未提供` 保留來源缺值。

多面向原邏輯未變：美股五面向為最新／機構／風險／財報／產業；台股為最新／機構／風險／公告／財報。只有兩個通用 provider 時依序為 DeepSeek、Tavily、DeepSeek、Tavily、DeepSeek；有 FinMind token 時只在台股最新消息前插入 FinMind。個股單一路徑則一直按 FinMind（限台股）→DeepSeek→Tavily，失敗／零結果改試下一個。

### INTC

整包 7.2 秒。

| 面向 | 來源／筆數 | 標題 | 日期 |
| --- | --- | --- | --- |
| latest_news | DeepSeek／3 | Intel (INTC) Q3 2026 Earnings Call Transcript & Audio | 2026-10-29 |
| latest_news | DeepSeek／3 | Intel Corporation (INTC) Q3 FY2026 earnings call transcript | 2026-10-29 |
| latest_news | DeepSeek／3 | Intel (INTC) Q3 2026 Earnings Call Transcript | 2026-10-30 |
| market_analysis | Tavily／3 | Intel Stock Forecast & INTC Price Target 2026 from analysts | 未提供 |
| market_analysis | Tavily／3 | Intel (INTC) Stock Forecast, Price Targets and Analysts Predictions - TipRanks.com | 未提供 |
| market_analysis | Tavily／3 | Intel Corporation (INTC) Analyst Insights, Price Targets & Recommendations - Yahoo Finance | 未提供 |
| risk_check | DeepSeek／3 | Intel Corporation Investigation – INTC | 2026-10-30 |
| risk_check | DeepSeek／3 | 2026-10-30 \| Levi & Korsinsky Announces Investigation of Securities Claims Against Intel Corporation (INTC) \| TSX:INTC \| Press Release | 2026-10-30 |
| risk_check | DeepSeek／3 | Intel (INTC) Beats Earnings Estimates but Stock Dips on Guidance | 2026-10-29 |
| earnings | Tavily／3 | Revenue Growth Forecast For Intel Corporation (INTC) | 未提供 |
| earnings | Tavily／3 | Intel (INTC) Earnings: What to Expect This Quarter | 未提供 |
| earnings | Tavily／3 | Intel (INTC) Earnings Date & Report - Investing.com | 未提供 |
| industry | DeepSeek／3 | BUZZ - Wall Street Perspective: Intel's Outlook Appears Dim, Recovery Once Again in Doubt \| Bitget News | 2026-10-30 |
| industry | DeepSeek／3 | Intel Drags Down CPU Rivals. Is it a Buying Opportunity for AMD and Arm? | 2026-10-31 |
| industry | DeepSeek／3 | 華爾街觀點：Intel前景黯淡，復甦再遭質疑 \| Bitget 新聞 | 2026-10-30 |

### GOOG

整包 8.43 秒。

| 面向 | 來源／筆數 | 標題 | 日期 |
| --- | --- | --- | --- |
| latest_news | DeepSeek／2 | Waymo’s backers valued it at $126 billion. The Alphabet division that houses it brought in $372 million last quarter—and lost $2.05 billion | 2026-10-30 |
| latest_news | DeepSeek／2 | 美科技巨头，股价突然重挫10% | 2026-10-29 |
| market_analysis | Tavily／3 | Alphabet Inc. (GOOG) Analyst Ratings, Estimates & Forecasts - Yahoo Finance | 未提供 |
| market_analysis | Tavily／3 | Alphabet (GOOGL) Stock Forecast: Analyst Ratings, Predictions & Price Target 2026 | 未提供 |
| market_analysis | Tavily／3 | Alphabet Class A (GOOGL) Stock Forecast, Price Targets and Analysts Predictions - TipRanks.com | 未提供 |
| risk_check | DeepSeek／3 | GOOG Slides As Earnings Miss And Legal Risks Rattle Traders | 2026-10-29 |
| risk_check | DeepSeek／3 | google alphabet share price: Latest News & Videos, Photos about google alphabet share price \| The Economic Times - Page 1 | 2026-10-30 |
| risk_check | DeepSeek／3 | Alphabet GOOGL Slides As Earnings Miss And Legal Risks Mount | 2026-10-29 |
| earnings | Tavily／3 | Alphabet (GOOGL) Margin Improvement Reinforces Bullish Earnings Narratives - Simply Wall St News | 未提供 |
| earnings | Tavily／3 | Alphabet (NasdaqGS:GOOGL) Stock Forecast & Analyst Predictions - Simply Wall St | 未提供 |
| earnings | Tavily／3 | Google (Alphabet) Q3 2026 Earnings Expectations: What Analysts Are Forecasting \| Plus500 | 未提供 |
| industry | DeepSeek／3 | Alphabet將迎財報日 討論重奪主導地位 - 星島日報 | 2026-10-28 |
| industry | DeepSeek／3 | 谷歌云逼近微软Azure，但为何微软反而赢得“财报日大考”？ | 2026-10-29 |
| industry | DeepSeek／3 | Search under seige? | 2026-10-30 |

### 2330.TW

整包 5.2 秒。

| 面向 | 來源／筆數 | 標題 | 日期 |
| --- | --- | --- | --- |
| latest_news | DeepSeek／3 | 台積電砸388億元買友達中科廠 取得近13萬坪廠房 \| 聯合新聞網 | 2026-10-29 |
| latest_news | DeepSeek／3 | 台積電砸388億收購友達中科廠 友達認列185億元處分利益 | 2026-10-29 |
| latest_news | DeepSeek／3 | 台積電買下友達台中廠，是否為加速 CoWoS 佈局？ | 2026-10-29 |
| market_analysis | Tavily／3 | 股票512980 研报 目标价 评级 深度分析 | 未提供 |
| market_analysis | Tavily／3 | 股票159583 研报 目标价 评级 深度分析 | 未提供 |
| market_analysis | Tavily／3 | 股票512400sh 研报 目标价 评级 深度分析 | 未提供 |
| risk_check | DeepSeek／3 | 台積電股價重挫逾4% 資金外流與宏觀逆風夾擊 | 2026-10-30 |
| risk_check | DeepSeek／3 | 台股悲情10月！外資砍8800億 法人曝「台積電被賣最多的原因」 \| ETtoday財經雲 \| ETtoday新聞雲 | 2026-10-31 |
| risk_check | DeepSeek／3 | 外資提款潮湧現！單週賣超逾兩千億重擊半導體族群，台積電等3檔遭殃 | 2026-10-30 |
| announcements | Tavily／3 | What TSMC Holders Got Right - Simply Wall St | 2026-10-31 |
| announcements | Tavily／3 | Beyond NVIDIA: Why TSMC Stock Looks Attractive After Q3 Earnings - TradingView | 2026-10-29 |
| announcements | Tavily／3 | Quarterly profit at chip assembler ASE hit 27 billion Taiwan dollars, up from 10.9 billion a year ago. - Stock Titan | 2026-10-29 |
| earnings | DeepSeek／3 | 台積電 (TSM) 業績 | 2026-07-16 |
| earnings | DeepSeek／3 | 台積電 (TSM) 業績 | 2026-07-16 |
| earnings | DeepSeek／3 | 《半導體》台積電Q4營收估季增13%拚連7高 毛利率持穩 - 財經 | 2026-10-15 |

### 3481.TW

整包 12.18 秒。

| 面向 | 來源／筆數 | 標題 | 日期 |
| --- | --- | --- | --- |
| latest_news | DeepSeek／3 | 友達(2409)、群創(3481)殺到快跌停能撿？面板雙虎拚轉型，誰能先靠AI封裝翻身？日月光、力成也搶進....FOPLP受惠股還有哪些？- 今周刊 | 2026-10-30 |
| latest_news | DeepSeek／3 | 法說變法會！ 友達一度摜殺跌停、群創跌逾8％ \| ETtoday財經雲 \| ETtoday新聞雲 | 2026-10-30 |
| latest_news | DeepSeek／3 | 外資賣超688億元…賣超聯電12.9萬張最多 友達、群創也齊遭大賣 \| 聯合新聞網 | 2026-10-29 |
| market_analysis | Tavily／3 | 股票515030 研报 目标价 评级 深度分析 | 未提供 |
| market_analysis | Tavily／3 | 股票159819 研报 目标价 评级 深度分析 | 未提供 |
| market_analysis | Tavily／3 | 富国上海金etf 研报 目标价 评级 深度分析 | 未提供 |
| risk_check | DeepSeek／3 | 外資賣超688億元…賣超聯電12.9萬張最多 友達、群創也齊遭大賣 \| 聯合新聞網 | 2026-10-29 |
| risk_check | DeepSeek／3 | 外資周狂賣1733億！瘋砍聯電10.95萬張居冠 再捲款「面板雙虎」14.28萬張跑路 \| FTNN 新聞網 | 2026-10-31 |
| risk_check | DeepSeek／3 | 面板全慘跌！外資退貨「這2檔」4萬張 友達連中2刀失血26.21億元殺跌停 \| FTNN 新聞網 | 2026-10-30 |
| announcements | Tavily／3 | NPKI: Revenue and Adjusted EBITDA accelerated as fleet and manufacturing investment continued - TradingView | 2026-10-31 |
| announcements | Tavily／3 | TIGR UPCOMING DEADLINE: Faruqi & Faruqi, LLP Reminds UP Fintech I - The National Law Review | 2026-10-31 |
| announcements | Tavily／3 | YRD Shareholder Notice: Shareholder Rights Law Firm Robbins - GlobeNewswire | 2026-10-31 |
| earnings | DeepSeek／3 | 《光電股》群創2利多抗跌 重返7字頭衝18年高價 | 2026-06-23 |
| earnings | DeepSeek／3 | 群創營收／5月206億元 月減2.78%、年增10.28% | 2026-06-10 |
| earnings | DeepSeek／3 | 群創波波前進 | 2026-05-17 |

3481 的 Tavily 機構分析混入其他 ETF 的 Instagram 頁，公告混入 NPKI／TIGR／YRD 等無關公司；這是實際取得的原文標題，不是已核實與群創相關的證據。本輪依要求保留既有關聯與輪流演算法，沒有為讓結果好看而替換或補造。DeepSeek 查媒體／網頁，不能取代 SEC 的一手申報；即使搜尋結果 URL 指到 SEC，也不是新 SEC provider 已核實的官方索引。

## 事件後事實與相容性

新增相對日期重現：事件日低點 278.29、次日收盤 278.22，舊程式以 `KeyError: post_event_min_close` 穩定紅。現在輸出最低收盤 278.22、最新收盤 278.22、`event_low_broken=true`；後續反彈到 280 仍揭露曾跌破。比較的是事件日之後已知日線的收盤，事件當日排除；等於低點不算跌破，缺收盤／低點就省略對應新欄與提示行，不推論盤中是否守住。

傳統 system／user 與 agent system 的真組裝邊界均確認帶入這些事實與「事件後新低重新計算／不得假設事件日低點仍守住」規則；外部模型 mock，不宣稱真模型已遵守。

`tests/fixtures/deepseek_disabled_baseline.json` 在改碼前由 `96761715` 擷取，鎖住 INTC／2330.TW 搜尋結果、完整情報文字、四語傳統 prompt 雜湊、agent 使用者訊息與結果；日期以相對當天替換成占位值，測試不會隨日曆失效。未設獨立搜尋金鑰維持這些內容逐字一致。事件新事實是本輪另一項已授權行為改動：前次 SEC 快照保留原檔，只在比較結果前逐值驗證新加的 `latest_close` 再比對其餘內容，不以重新生成舊快照掩蓋變化。

`tests/fixtures/deepseek_search_dates.json` 是實際回應各取三則、summary 截短的縮本，保留 title／URL／date／site_name／authority／rerank_score；其餘為隔離的 HTTP、key、內容長度、日期窗口與事件 fixture。摘要含日期提醒每則最多 500 字元，採 summary、缺才退 snippet，與 Tavily 既有上限一致。

## 正反 mutation

每次改一個條件，新的 pytest 程序必須 exit 1 且有定向失敗，最後還原程式。未設搜尋 key 誤用模型 key、不退下一來源、不換 key、已跌破不揭露都有實際紅燈；亦檢查過度更正日期、過度宣告跌破與過度輪替等反向案例。

| Mutation | 失敗數 |
| --- | ---: |
| 誤沿用模型金鑰 | 1 |
| 個股搜尋不退下一來源 | 4 |
| 多面向搜尋不退下一來源 | 4 |
| 過度略過 DeepSeek | 1 |
| 不換認證與額度失敗金鑰 | 6 |
| 過度對所有錯誤換金鑰 | 3 |
| 金鑰前綴洩漏日誌 | 6 |
| 例外本文洩漏結果 | 3 |
| 不截短 Unicode 查詢 | 3 |
| 不限制 summary 長度 | 3 |
| 過度縮短 summary | 3 |
| 誤用 snippet 而非 summary | 3 |
| 忽略日級 UTC 前一日編碼 | 4 |
| 所有時間戳過度加一天 | 1 |
| 把舊新聞日期冒充今天 | 3 |
| 混入事件當日收盤 | 1 |
| 反彈後忘記先前跌破 | 1 |
| 已跌破卻不揭露 | 2 |
| 未跌破也過度宣告跌破 | 2 |
| 觸及低點誤判跌破 | 1 |
| 規則仍假設低點守住 | 2 |
| 移除搜尋環境鍵登記 | 1 |
| 過度暴露搜尋金鑰到 UI | 1 |

## 未驗證與回滾

未跑真 LLM、UI、正式 DB、NAS、通知，依任務邊界；不宣稱模型遵循、報告落庫或部署完成。FinMind 沒有本輪線上憑證，只有優先／退回測試；查詢結果關聯性仍有上述真實限制。DeepSeek 日期修正是依樣本辨識的日級型態，未獲供應商確認，不保證所有站點的原文日期正確。

清空 `DEEPSEEK_SEARCH_API_KEYS` 可停用新搜尋；事件事實是獨立改動，完整回滾需 revert 本次 commit。文件沒有對應英文版，README 中英首頁未改。已核對欄位、檔名與命令；gate 與全量結果於本輪完成後記在文末。

## 最終驗證

- `uv run --frozen ./scripts/ci_gate.sh syntax`／`flake8`：exit 0，flake8 critical 為 0。
- 受影響測試：**573 passed**，5 warnings，9.97 秒，exit 0；包含 `tests/test_search*.py`、新 DeepSeek／事件測試、US 搜尋、事件原路徑、SEC 相容快照、market review runtime 與 config 測試。
- 全量命令：`DATABASE_URL='' STORAGE_DATABASE_URL='' LITELLM_MODE=PRODUCTION uv run --frozen ./scripts/ci_gate.sh offline-tests`。
- 全量：**12,816 passed、129 skipped、8 deselected、997 subtests passed**，681 warnings，351.18 秒，exit 0。129 項皆為無 `DATABASE_URL` 的 `market_data/tests`，8 項為 network 選擇排除；沒有待解釋的失敗。期間沒有改檔，完成後僅追加本段紀錄。
- 正反 mutation：**23／23** 被抓到，已還原原始碼。
- 原始 HTTP 日期、四檔搜尋 JSON、gate／pytest／mutation 日誌在本機 `.claude/reviews/verification/deepseek-search-event-20261031/`（gitignore，不含搜尋金鑰或 Authorization）。
