# 美股新聞與補充證據

個股傳統與 agent 分析共用市場來源判定、基本面預算與最後落庫護欄。新增證據只追加到分析上下文；不需要資料庫遷移，也沒有 Web／iOS 介面變更。

## 新聞來源與三態計數

`SearchService.is_available_for_stock(code)` 對合法 `.TW`／`.TWO` 代碼接受 FinMind 或通用 provider；其他市場只接受通用 provider。原本 `is_available` 保留「服務有任一來源」的語意，供大盤、題材與初始化診斷使用。

只有 FinMind 時，美股流程不發起搜尋，以 warning 記錄未配置該市場來源，`news_result_count=None`；已有通用來源、搜尋失敗或零命中為 `0`；成功為實際條數。agent 工具也先檢查市場，計數來自分析期間實際消費的工具回傳，不採用分析結束後為保存情報而補查的結果。社交與本地情報池是否有證據，沿用結構化 `news_evidence_present` 合併結果。

`TAVILY_API_KEYS` 支援逗號分隔的多把金鑰。每個 provider 建立時隨機選輪替起點；同一次搜尋遇到認證／額度錯誤立即切到下一把，每把最多一次（重複金鑰先去重）。一般搜尋與 `topic=news` 共用邏輯。其他錯誤與成功的零命中不切換金鑰，也不加延遲重試。

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

事件視窗與新聞時效分開：在目前 3 天新聞設定下，搜尋仍只保留今日與前 2 個日曆日，本地情報池沿用最近 3 天（滾動 72 小時）的查詢。週五事件到週一僅隔 1 個交易場次，仍在事件視窗內，但發布日標為週五的文章已超出搜尋的 3 日視窗。若本地情報、近期追蹤新聞與社交證據也都沒有，`news_evidence_present=false`，程式仍會觀望，即使歷史上確實發生財報事件。反之，任一現有來源有近期證據即可為 true，旗標不保證是同一事件。此輪不把事件日帶入搜尋，也不放寬新聞視窗。

觸發時，傳統分析與單 agent／多策略各 stage 的 system prompt 追加繁中優先規則：先判事件與投資論題，再判事件後下修估值，最後觀察幾個交易日不破事件低點與量縮。可分批試單，但必須交代失效條件；重新評估不得使用含事件前價格的均線。提示詞不保證模型遵守，沒有新增對模型文字的掃描或自動解讀。

如果結構化 `news_evidence_present=false`，共用 `_finalize_and_persist_result` 在其他護欄完成後、歷史與決策訊號寫入前，強制 `decision_type=hold`、`action=watch`、低信心，清除可執行交易計畫，揭露「重大波動但沒有新聞，不下買賣結論」。結果在 `dashboard.event_gap` 追加同一事件的日期、幅度、低點、距今場次、門檻、證據狀態與護欄原因。這項決策調整與富途純資訊無關。

未開啟或未達門檻時，事件功能不追加 prompt／結果欄位。`tests/fixtures/event_gap_baseline.json` 保存修改前 commit 的 16 組完整 prompt 雜湊與結果序列化快照；新證據出現時的 prompt 增補則屬前述獨立資料能力。

關閉事件功能可設 `EVENT_GAP_DECISION_ENABLED=false`；停用富途證據可清空 `FUTU_OPEND_HOST`。完整回滾使用本次 commit 的 revert，不改舊歷史紀錄。本文沒有對應的英文版；README 中英雙語首頁均未改動，細節集中於此專題文件。

首輪離線驗收與逐項 mutation 結果見[驗證紀錄](research/2026-10-31-us-data-evidence-verification.md)。

事件交易日視窗、新聞時效與本輪 mutation 見[修正驗證紀錄](research/2026-10-31-us-event-gap-lookback-verification.md)。
