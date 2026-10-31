# 美股新聞與補充證據

個股傳統與 agent 分析共用市場來源判定、基本面預算與最後落庫護欄。新增證據只追加到分析上下文；不需要資料庫遷移，也沒有 Web／iOS 介面變更。

## 新聞來源與三態計數

`SearchService.is_available_for_stock(code)` 對合法 `.TW`／`.TWO` 代碼接受 FinMind 或通用 provider；其他市場只接受通用 provider。原本 `is_available` 保留「服務有任一來源」的語意，供大盤、題材與初始化診斷使用。

只有 FinMind 時，美股流程不發起搜尋，以 warning 記錄未配置該市場來源，`news_result_count=None`；已有通用來源、搜尋失敗或零命中為 `0`；成功為實際條數。agent 工具也先檢查市場，計數來自分析期間實際消費的工具回傳，不採用分析結束後為保存情報而補查的結果。社交與本地情報池是否有證據，沿用結構化 `news_evidence_present` 合併結果。

`TAVILY_API_KEYS` 支援逗號分隔的多把金鑰。每個 provider 建立時隨機選輪替起點；同一次搜尋遇到認證／額度錯誤立即切到下一把，每把最多一次（重複金鑰先去重）。一般搜尋與 `topic=news` 共用邏輯。其他錯誤與成功的零命中不切換金鑰，也不加延遲重試。

## DeepSeek 媒體與網頁搜尋

以 `DEEPSEEK_SEARCH_API_KEYS`（逗號分隔、空白省略）啟用，預設空白，僅環境設定、不增加 Web 介面。**不讀取模型用的 `DEEPSEEK_API_KEY`／`DEEPSEEK_API_KEYS`，搜尋金鑰也不注入 LiteLLM**，避免改變模型推斷與路由。未設定時，保留原 provider 順序、搜尋結果、傳統四語 prompt、agent 使用者訊息與決策結果，對照修改前 `96761715` 的快照測試；下節新增的事件事實是獨立能力，不受搜尋開關控制。

啟用時通用 provider 順序為 DeepSeek → Tavily → 其餘原有來源（其餘相對順序保留）。台股 `search_stock_news` 為 FinMind → DeepSeek → Tavily；其他市場不經 FinMind。任一來源失敗、零結果，或經日期／關聯過濾後沒有可用結果，會真正呼叫下一來源。

`search_comprehensive_intel` **保留原本按面向輪流選起點的邏輯**，不是每個面向都先問 DeepSeek。只設定 DeepSeek 與 Tavily 且各面向首選皆成功時：

| 市場 | 最新消息 | 機構分析 | 風險排查 | 第四面向 | 第五面向 |
| --- | --- | --- | --- | --- | --- |
| 美股 | DeepSeek | Tavily | DeepSeek | 財報：Tavily | 產業：DeepSeek |
| 台股 | 有 token 時 FinMind，否則 DeepSeek | Tavily | DeepSeek | 公告：Tavily | 財報：DeepSeek |

FinMind 只插入台股「最新消息」最前面，不影響其他面向輪替；失敗後沿該面向的候選順序嘗試，沒有可用來源才保留失敗。設定其他 provider 時仍依可用來源數輪流，不改演算法。預設 `max_searches=3` 只跑前三個面向；本次真實驗收用 5 以涵蓋第四、第五面向。中文／英文名稱沿既有別名解析與查詢組裝，DeepSeek 保留 Unicode 字元，不限定英文。

依 [DeepSeek 官方文件](https://api-docs.deepseek.com/guides/search/)，使用 `POST https://api.deepseek.com/v1/tools/search`、Bearer 與 JSON 的 `query`／`count`。查詢含 `after:`／`before:` 日界；原查詢已有同名運算子則不重複加入，`site:`／`lang:` 可沿用。先為日界保留長度，再截查詢，總長不超過 128 Unicode 字元，空白查詢不發請求；`count` 介於 1～50，每次 HTTP 最多等 10 秒。來源 `summary` 進 `SearchResult.snippet`，無 summary 才取 snippet；**每則含日期提醒最多 500 字元**，比照本專案 Tavily 既有的 500 字元，避免 2000～5000 字元的原始摘要放大 prompt。沿用每面向最多 3 則的最終限制。

DeepSeek 與 Tavily 的金鑰輪替抽至 `RotatingKeySearchProvider`：隨機起點、重複 key 去重、同一呼叫每把最多一次，401／402／429 換下一把；Tavily 另保留 SDK 類別與 432／433 的辨識。其他錯誤不換 key，200 零結果不換 key，而由 SearchService 改試下一 provider；不新增同一把 key 的重試。日誌不含金鑰前綴或例外本文，失敗結果僅留例外類別。官方說明只對 200 且有結果計費，價格與權限仍以官方當時契約為準。

### 日期精度與三天窗口

官方宣稱 `date` 為 UTC RFC 3339；本次財報查詢 12／12、四檔多面向 DeepSeek 原始結果 72／72 均固定為 `16:00:00+00:00`。INTC 官方新聞稿原文為 **2026-10-29 16:01 EDT**，搜尋卻標 `2026-10-28T16:00:00+00:00`；Alphabet 逐字稿原文日期 **10/28**，搜尋標 `10/27T16:00:00+00:00`。這些值不是精確發布時刻。

根據樣本，推論來源以 **UTC+8 日曆日的午夜**包裝日期，轉成 UTC 後落在前一天 16:00。本 provider 只對這個已觀察型態還原 UTC+8 日曆日，其他帶時區的時間保留其 UTC 日，不一律加一天，也不依部署機器的本地時區決定此換日。輸出明標「DeepSeek 搜尋日期未經原文核實；日級日期非精確發布時間」。此推論不是 DeepSeek 對內部實作的確認，不保證全站的日期正確。

`latest_news`、個股 `risk_check`、台股 `announcements` 仍做既有三天窗口過濾，日期未知則換下一來源；不以擷取時間冒充發布時間，不放寬全域窗口。測試同時確認前 2 天的邊界可保留、前 3 天及更舊資料仍剔除。機構分析與財報面向沿原有 180 天、可保留未知日期的政策，不應誤讀成每個面向都只含三天新聞。原始值、原文發布日期、四檔各面向的來源／筆數／標題／日期見[本輪驗證紀錄](research/2026-10-31-deepseek-search-event-verification.md)。

DeepSeek 搜尋的是媒體與網頁，包含搜尋引擎排序、摘要與日期推定；SEC 是下節的一手申報，保留 accession、官方時間與公司新聞稿原文。搜尋結果不取代 SEC 申報事實，SEC 新聞稿內容仍是公司自述，兩者都不代表獨立核實投資論題。

實際 Tavily SDK 將 401 映射為 `InvalidAPIKeyError`，429 為 `UsageLimitExceededError`，403／432／433 為 `ForbiddenError`。因此這三類 SDK 例外會切換；仍保有 HTTP response 的例外則精確檢查 401／429／432／433。SDK 的 `ForbiddenError` 已失去原始狀態碼，無法再區別 403 和 432／433。錯誤分類不靠文字比對。來源：[官方 HTTP 錯誤說明](https://help.tavily.com/articles/8645538886-understanding-http-errors)、[官方 Python SDK](https://github.com/tavily-ai/tavily-python/blob/master/tavily/tavily.py)。

## yfinance 證據

只在美股基本面階段取用，維持報價路徑不讀 `ticker.info` 的低延遲契約。

| 上下文 | 來源與口徑 |
| --- | --- |
| `valuation.data.forward_pe` | 既有 `info.forwardPE`，預期盈餘口徑；不替代近四季 PE |
| `us_evidence.short_interest` | `sharesShort`（股）、`shortRatio`（回補天數）、`shortPercentOfFloat`（轉百分比）；`dateShortInterest` 作資料日，未提供則明講資料日未知 |
| `us_evidence.institutions_pct`／`insiders_pct` | `heldPercentInstitutions`／`heldPercentInsiders` 轉百分比；來源更新頻率不等同即時持股 |
| `us_evidence.next_earnings_at` | 未來的 `earningsTimestamp`，UTC ISO 時間；過去時間省略，不推算下一季 |
| `us_evidence.insider_90d` | `insider_transactions` 中最近 90 個日曆日、日期不在未來且可辨識 `Purchase`／`Sale` 的交易；買股數減賣股數，另列排除筆數，不把贈與／行權當買賣，不宣稱完整申報 |
| `us_evidence.ratings_30d` | `upgrades_downgrades` 最近 30 個日曆日的筆數與最多 20 筆明細（日期、機構、Action、前後評等）；提示「評等可能尚未反映最新事件」 |

`info` 證據沿用既有基本面 bundle 的請求；內部人交易與評等各自獨立請求，受 `FUNDAMENTAL_FETCH_TIMEOUT_SECONDS` 與剩餘 `FUNDAMENTAL_STAGE_TIMEOUT_SECONDS` 限制。單項拋錯時保留其他項；預算耗盡就省略尚未取得的項目，不延長分析等待。沿用既有有界背景工作池與逾時隔離；逾時是呼叫端停止等待，背景請求可能稍後完成，不能視為已取消遠端請求。

缺值與非有限值省略，來源明確回傳的 0 保留。證據不計入 coverage／基本面總狀態或規則評分。Yahoo 的預估盈餘、評等及持股可能延遲，事件後不可假設已更新。

## SEC EDGAR 與 FINRA

設定 `SEC_EDGAR_USER_AGENT` 為應用／組織名稱及實際可聯絡的 email，即在美股基本面 bundle 之後、Yahoo 活動摘要之前取得官方證據。不提供內建聯絡人；空白時 **SEC 與 FINRA 整包停用**，不發新請求、不追加欄位或提示詞。關閉時的傳統四種報告語言 prompt、agent messages 與結構化結果，對照 `b3306e7` 的 `tests/fixtures/sec_disabled_baseline.json` 逐字驗證。設定切換使用不同基本面快取鍵，避免讀到另一種開關狀態的證據。

`data_provider/sec_edgar.py` 以 [SEC ticker 清單](https://www.sec.gov/files/company_tickers.json) 找 CIK；清單在程序內快取 24 小時，同一 CIK 可對應 GOOG／GOOGL 等多個 ticker。申報來源為 [SEC submissions API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)，必要時讀取官方歷史分頁。所有 SEC 請求跨執行緒共享最少 0.11 秒的起始間隔，符合 [SEC 10 req/s 與 User-Agent 規範](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)。這是單一程序的限速，多程序部署仍須自行分配總額度。

| 上下文 | 來源與口徑 |
| --- | --- |
| `us_evidence.sec_filings.recent_8k` | 近 14 天（含邊界、排除未來）的 8-K；`date`、`accepted_at`（來源 UTC 時間）、`items`、`url`。Item 2.02 時掃描 accession 目錄 `index.json` 的 HTML 附件，以內容辨識財報新聞稿，不依賴 `ex99` 檔名；取得時附 `excerpt`、`excerpt_url`。摘錄去除 HTML、最多 6000 字元，財測／指引／重點優先，保留原文，非全文或模型摘要 |
| `us_evidence.sec_filings.latest_10q_date` | 最近一份 10-Q 的申報日期；不下載整份季報、不取代既有財報數值 |
| `us_evidence.insider_form4` | 近 90 天送件的 Form 4 原始 XML，僅合計交易日也在 90 天內的普通股 `P` 買進／`S` 賣出；含 `buy_shares`、`sell_shares`、`net_shares`、`classified_count`、`excluded_count`。A／M／F／G 等非市場代碼與衍生證券交易排除；無效股數不計入。XML 的 `xslF345X06/` 瀏覽轉換前綴不帶入原始 XML URL |
| `us_evidence.finra_short` | [FINRA consolidatedShortInterest](https://developer.finra.org/docs#consolidated-short-interest) 的 `currentShortPositionQuantity` → `shares_short`（股）、`daysToCoverQuantity` → `days_to_cover`、`settlementDate` → `as_of`；以 `symbolCode EQUAL` 匿名 POST，不帶 `sortFields`，本機選最大且非未來的結算日 |

Form 4 的 `filings_read`／`filings_available` 揭露讀取進度，`complete=false` 表示歷史分頁或 XML 未讀完；不得將部分合計當完整 90 天淨交易。完全沒讀到 XML 時不產生 Form 4 合計，保留 Yahoo；官方索引確認窗口內沒有申報時可回傳 0。合計是 **同一 CIK 的各股別普通股**，GOOG／GOOGL 不拆開；不合計衍生證券，也不對 `4/A` 修訂申報重算歷史。`complete` 只表示本輪原始 Form 4 清單讀取完整，不保證申報無漏報或無修訂。

prompt 有 `insider_form4` 時只印官方交易合計，不再印 `insider_90d`。FINRA 股數／回補天數逐欄優先，官方缺的欄位才印 Yahoo；Yahoo 的流通股放空比例仍保留自身來源與日期，不能冒充 FINRA 同期數字。FINRA 的資料名稱雖位於 `otcMarket` 群組，實測亦回傳 INTC／GOOG 的 NNM 記錄；它是結算部位，非每日放空成交量。官方文件的一般授權契約要求 OAuth，本次匿名唯讀可用，不保證持續開放，401／403／400／逾時均省略該來源。

FINRA 先查一次，再讀 SEC 索引、財報附件與 Form 4，兩來源各自失敗不互相丟棄結果。每個 HTTP 請求有明確 connect／read timeout，單項上限沿用 `FUNDAMENTAL_FETCH_TIMEOUT_SECONDS`，並扣剩餘期限；整包由既有有界工作池限制於 `FUNDAMENTAL_STAGE_TIMEOUT_SECONDS` 剩餘預算，略留回傳時間。預算不足就停止取得新資料，不延長階段、不重試。逾時工作可能稍後結束，但結果不再併入本次報告。這條路徑不碰資料庫、通知或 `capital_flow`，不改 coverage／評分。

提示詞明列「SEC 官方申報，來源一手；新聞稿內容為公司自述」，以外部資料而非指令輸入。14 天內的 8-K 只有 Item 2.02 或已取得實質摘錄才加入 `news_evidence_present`；一般標頭、單獨 10-Q、Form 4、FINRA 均不算新聞證據。傳統與 agent 都在 finalize 前登記，`news_result_count` 仍只計搜尋結果，可能為 `None`／`0` 而同時有 SEC 新聞證據；旗標不保證申報與價格波動是同一事件。

清空 `SEC_EDGAR_USER_AGENT` 即停用本功能；完整回滾為 revert 本次 commit。實測、fixture 來源與 mutation 詳見[SEC 驗證紀錄](research/2026-10-31-us-sec-evidence-verification.md)。

## 富途 OpenD：啟用與部署

只有明確設定 `FUTU_OPEND_HOST` 才抓美股補充證據，使用現有 `FutuFetcher` 與既有 `futu-api`，沒有新增依賴。沿用 `FUTU_OPEND_PORT`（既有預設 11111）。設定 `FUTU_OPEND_HOST` 也會同時啟用既有港股富途報價／基本面路徑，並非只開美股證據。

```dotenv
# 填 DSA 執行環境能到達的 OpenD 主機／服務名稱
FUTU_OPEND_HOST=192.168.31.105
FUTU_OPEND_PORT=11111
```

部署者先在可登入富途帳號的主機執行 OpenD，完成登入及美股行情權限配置，再讓 DSA 容器與 OpenD 位於可互通的網路。若兩者在相同 Docker network，可使用 OpenD 的 service name；OpenD 在另一台主機時填可達的內網位址。容器內 `127.0.0.1` 指容器本身，只有 OpenD 與 DSA 共用 network namespace 才適用。限制監聽範圍與防火牆，不把 OpenD 端口直接公開到網際網路。

目前正式 OpenD 跑在 **audinas**，ops repo 的 `hosts/audinas/futu-opend` 管理部署，DSA 使用 `FUTU_OPEND_HOST=192.168.31.105`。版本釘在 **10.9.6918**：10.10 起設定檔自動登入被移除，10.12 命令列互動登入已實測回 `Account credentials incomplete`，因此不能直接假設升版後仍可沿用目前登入方式。這些為本次使用者提供的真實驗收紀錄。

此路徑只讀行情，不呼叫交易 API、不依賴期權權限，也不採用富途 PE（快照與 K 線口徑已有矛盾實例）。未開戶帳號能否取到資料仍以實際行情權限為準，沒有資料不補 0。

`fundamental_context.us_evidence.futu` 包含：

- `daily_flow`：明確指定 `PeriodType.DAY`，按來源日期排序後取最近最多 5 個交易日，保留 `in_flow`、`main_in_flow`（USD）。分鐘線的 `main_in_flow=N/A` 不會變成 0。
- `distribution`：最新來源回應的超大／大／中／小單流入與流出，附 `update_time`，缺欄省略。
- `snapshot`：最新快照的 `volume_ratio`、`turnover_rate` 及來源時間（有提供才附）。只補本次 `realtime` 缺值，已有值不覆蓋。

資金流只含正常交易時段，未經回測、不計入評分。接口上限各為 30 次／30 秒，這條路徑每檔各呼叫一次、不自動重試；大量股票請控制批次頻率，限流視為缺資料。基本面快取沿用既有 TTL。官方契約：[每日資金流](https://openapi.futunn.com/futu-api-doc/en/quote/get-capital-flow.html)、[資金分佈](https://openapi.futunn.com/futu-api-doc/en/quote/get-capital-distribution.html)。

連線先做最多 1 秒 TCP 探測；SDK 同步連線等待也設明確上限。所有富途請求另受剩餘基本面預算限制，OpenD 不在線不會等待 SDK 長時間重連。`capital_flow` 不接收這些資料，避免觸發 `stabilize_decision_with_structure` 的校準；有無富途資料的決策穩定結果有離線測試比對。

## 事件判讀開關

```dotenv
EVENT_GAP_DECISION_ENABLED=false
EVENT_GAP_THRESHOLD_PCT=12
EVENT_GAP_LOOKBACK_SESSIONS=5
```

預設關閉。開啟後，僅美股個股與合法台股代碼，在最近 `EVENT_GAP_LOOKBACK_SESSIONS` 個交易場次（預設 5，含當日）中，任一日收盤漲跌幅絕對值大於或等於門檻就觸發；多日符合時取最近一場。5 場表示事件距今 0～4 場有效，距事件日達 5 場即失效，週末與假日不額外計數。這裡的「gap」是設定名稱，並非開盤跳空幅度。

日線優先採用 `pct_chg`，缺值時才由相鄰收盤價計算。傳統與 agent 分流前共用已載入的日線，最多帶回看場次加一筆作前收比較，不新增行情網路請求；日線不足以判定時，保留原有僅看當日 `change_pct`／`today.pct_chg` 的處理，不用收盤價冒充缺失低點。`event_date`、`change_pct`、`event_low`、`sessions_since_event` 記錄所選事件日、該日幅度、低點與距今場次。傳統 system／user 與 agent 的 system prompt 都明列日期、幅度和已知低點；低點未知時省略該行。

事件視窗與新聞時效分開：在目前 3 天新聞設定下，搜尋仍只保留今日與前 2 個日曆日，本地情報池沿用最近 3 天（滾動 72 小時）的查詢。週五事件到週一僅隔 1 個交易場次，仍在事件視窗內，但發布日標為週五的文章已超出搜尋的 3 日視窗。若本地情報、近期追蹤新聞與社交證據也都沒有，且未取得前節的 SEC 實質 8-K，`news_evidence_present=false`，程式仍會觀望，即使歷史上確實發生財報事件。啟用 SEC 後，近 14 天財報申報可在搜尋過期時補足證據；旗標仍不保證是同一事件。不把事件日帶入搜尋，也不放寬搜尋新聞視窗。

觸發時，傳統分析與單 agent／多策略各 stage 的 system prompt 追加繁中優先規則：先判事件與投資論題，再判事件後下修估值，最後觀察幾個交易日不破事件低點與量縮。可分批試單，但必須交代失效條件；重新評估不得使用含事件前價格的均線。提示詞不保證模型遵守，沒有新增對模型文字的掃描或自動解讀。

事件事實另提供 `post_event_min_close`（事件日之後、已知日線的最低收盤）、`latest_close`（最新場次已知收盤）、`event_low_broken`（已知事件後最低收盤嚴格低於事件日低點）。事件當日不混入事件後統計，觸及而未低於不算跌破；反彈不會抹掉先前收盤已跌破的事實。缺少相應資料就省略欄位與提示行，不把即時價當收盤，也不由未知日線推論「守住」。提示詞明講已跌破時，止跌條件須改用事件後新低重新計算，不得假設事件日低點仍守住；這是收盤觀察，不保證盤中沒有跌破。此增補不改評分或無新聞護欄。

如果結構化 `news_evidence_present=false`，共用 `_finalize_and_persist_result` 在其他護欄完成後、歷史與決策訊號寫入前，強制 `decision_type=hold`、`action=watch`、低信心，清除可執行交易計畫，揭露「重大波動但沒有新聞，不下買賣結論」。結果在 `dashboard.event_gap` 追加同一事件的日期、幅度、低點、距今場次、門檻、證據狀態與護欄原因。這項決策調整與富途純資訊無關。

未開啟或未達門檻時，事件功能不追加 prompt／結果欄位。`tests/fixtures/event_gap_baseline.json` 保存修改前 commit 的 16 組完整 prompt 雜湊與結果序列化快照；新證據出現時的 prompt 增補則屬前述獨立資料能力。

關閉事件功能可設 `EVENT_GAP_DECISION_ENABLED=false`；停用富途證據可清空 `FUTU_OPEND_HOST`。完整回滾使用本次 commit 的 revert，不改舊歷史紀錄。本文沒有對應的英文版；README 中英雙語首頁均未改動，細節集中於此專題文件。

首輪離線驗收與逐項 mutation 結果見[驗證紀錄](research/2026-10-31-us-data-evidence-verification.md)。

事件交易日視窗、新聞時效與本輪 mutation 見[修正驗證紀錄](research/2026-10-31-us-event-gap-lookback-verification.md)。
