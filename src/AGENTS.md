# src — 分析主流程、大盤複盤、報告與通知

> `src/agent/` 的契約正本在 `docs/multi-strategy-contract.md`。

## 模組定位

個股分析(`analyzer.py` + `core/pipeline.py`)與大盤複盤(`market_analyzer.py` + `core/market_review.py`)是兩條獨立流程,共用通知與報告語言層。

名字猜不到用途、或帶額外契約的子目錄:

- `notification_sender/`:各通知渠道;新增渠道實作 `base.py` 的 `Sender` protocol,並在 `notification.py` 的 `NotificationService._senders` 註冊(另見下方 `detect_configured_channels`)。
- `llm/`:生成後端、usage／provider 快取與 transport 編排(`client.py::LLMClient`:backend fallback／脫敏／串流);與 `GeminiAnalyzer` 的邊界見該檔模組 docstring。
- `agent/`:tool-calling agent(多輪對話、分歧偵測、事件流),`AGENT_MODE=true` 啟用;策略定義在根目錄 `strategies/*.yaml`(見 `strategies/README.md`);問股後端由 `AGENT_BACKEND` 選(`auto`／`litellm` 走 LiteLLM,`codex_app_server` 走本機 Codex)。這裡的缺陷幾乎都是同一種形狀:**報告照常產出、測試照常通過、只有數字或語言是錯的**,而 LLM 會在錯的數字上疊出通順的敘事。

## 進來改要遵守

- **動作、停損、買點一律讀 LLM 給的結構化欄位**(`decision_type`／`action`／`sniper_prices` 等,以 code 為準),消費端不從建議文字推、不做子字串或否定詞掃描;細節見 `docs/tw-analysis-overview.md`。
- **複盤日期跟著盤勢走,不是伺服器掛鐘。**開盤後(含盤後)標該市場當地的當天,開盤前與非交易日才標最近一場已收盤。改成一律掛鐘,美股複盤永遠早一天;改成一律日曆,台北週一盤中會把當天價格存成上週五。
- **市場時鐘只讀一次、往下傳。**`infer_market_phase`、`get_effective_trading_date` 都收 `current_time`;各自讀鐘會讓跨午夜／跨收盤邊界的同一批判定自相矛盾,測試也釘不住。
- **「同一場次」沒有單一函式把關。**台股表頭加權指數釘本地 DB 該場次的官方收盤(只管那一檔、查無該列就保留即時值);家數、成交額、法人則對齊 TWSE 回報的最新交易日,並以 `trade_date` 帶出;`_get_market_statistics` 拿它與 `overview.date` 比對,**不同日(含缺 `trade_date`)就整批不採用**並記 `status=session_mismatch`,prompt 與報告加「不得推論」一行——所以盤中與 13:30 後官方發布前的複盤沒有家數／法人是正確的,不是壞掉。法人在複盤日為台北今天時標「盤後初版」(官方事後會修正)。
- **判斷今天哪些市場開市,用「市場當地日或伺服器日」的聯集。**只看市場當地日,台北週一早上紐約還是週日,`tw,us` 會靜默收成 `tw`。
- **只在 PREMARKET 不追加當日 K 棒。**開盤前的「即時價」其實是昨收,追加會造出一根假 K 棒、所有指標都算在它上面;盤後相反,那個報價就是當日收盤,仍要追加。開盤前 DB 缺上一場時例外:報價就是那一場的收盤,補成**那一場**(不是今天)的 K 棒,否則指標算在少了 T-1 的序列上。分析上下文的 `today` 估算列同理:日期標報價所屬場次(`quote_session`),不是掛鐘日;DB 最新列早於該場次就把它平移成 `yesterday`。這個日期也是回測／skill outcome 的 `analysis_date`(口徑見 `docs/analysis-context-pack.md`「回测」)。
- **「沒有讀數」不是 0,也不是中性的 50。**缺的欄位要省略或標示缺資料;評分器在所有維度都不可用時仍會回 50,要用「有沒有任一維度可用」判斷,`data_quality` 不能代替。一組彙總值裡有一格非有限,整組作廢。NaN 不能用 truthiness 判(`bool(nan)` 為真)。
- **守門放在資料進入結構化契約的入口,不要只在某個消費端擋。**連續三輪修復都錯在放錯層:call site 的過濾被 `a or build()` 抵銷、建構期的清洗攔不到「先建空物件再逐欄賦值」的生產路徑。非有限值在序列化邊界遞迴清洗;已落庫的舊資料要在讀取端套同一個判定。
- **個股結果的後處理掛在 `_finalize_and_persist_result`**,傳統與 agent 兩條路徑都經過它。必須在歷史寫入前就存在的欄位,要在呼叫它**之前**、兩條路徑都寫。
- **新增通知渠道除了註冊 sender,還要同步 `detect_configured_channels`**——診斷路徑只讀設定、不會去建 sender,兩邊不一致時診斷說的與實際發的不同。
- **寫外部來源的字串欄位(標題、URL、查詢)要先截到欄位長度。**上游預設 SQLite、不檢查 `VARCHAR` 長度;應用庫搬到 Postgres 後,一筆超長字串會讓整個寫入 transaction 回滾(踩過:`news_intel.title`,修法見 `storage.py` 的 `DatabaseManager._fit_news_intel_column`)。
- **彙總報告的失敗揭露從唯一分派點 `generate_aggregate_report` 往下傳。**表頭檔數是成功數,失敗另起一行;分組信不帶(清單是整輪的,會點名組外代碼)。`REPORT_RENDERER_ENABLED` 打開時模板路徑會提早返回,那一行不會出現。

## 語言

- **新增使用者可見字串要補齊每一種報告語言**(`report_language.py` 的 `SUPPORTED_REPORT_LANGUAGES`)。漏掉不會報錯:查表靜默回退簡體,`_localized_text` 不傳 `zh_tw` 也是回簡體。模板路徑同樣要補——它是 LLM 回空時實際走的路。
- **prompt 本體的語言會壓過語言指令。**內文是簡體時,就算 system 與 user prompt 都要求繁體,模型照樣輸出簡體。
- **`zh-TW` 目前仍會出簡體的路徑**(都是「非英文就當簡體」的二分法,不是漏翻一兩個字):逾時部分完成通知、分享圖、大盤統計表、個股系統提示的市場角色與準則、台股複盤模板的策略段、儀表板的小節標題、資料源顯示名。前兩項的來龍去脈在 `docs/upstream-sync-2026-09-20.md` 與 `docs/upstream-sync-2026-08-30.md`,其餘沒有文件記錄。

## 踩雷

- **LLM 回空與回非法 JSON 是兩種失敗。**回空多半是推理模型(如 `deepseek-v4-flash`)把預算花在推理上:內容為空而 `finish_reason=length`,症狀是隨機「分析未成功」,台股美股都會中。**這種情況加預算不是可用的槓桿**——個股分析的輸出上限是 `analyzer.ANALYSIS_MAX_OUTPUT_TOKENS`,`LLM_MAX_TOKENS` 只有選股 pipeline 讀得到,`deepseek-v4-flash` 實測 8192 下仍約 1/3 回空;要修就換 `LITELLM_MODEL`。非法 JSON 會走文字 fallback、該次結果標為失敗;完整性重試救回時仍會成功、進彙總,兩次都非法才不進。別用同一種重試處理兩者。
- **輸出被截斷是第三種失敗,與上一條不同,這裡預算就是槓桿。**Sonnet 5.5 的 adaptive thinking 也算在額度內,原本的 8192 會讓回應停在 JSON 開頭(`finish_reason=length`),所以上限調成 16000。截斷只在 `analyze()` 傳 `on_output_truncated` 時才算失敗:不進文字 fallback(那條會對 JSON 原文數關鍵字,算出假的分數與動作)、不塞草稿,用原 prompt 重送一次;再截斷就 `success=False`、不落庫,錯誤訊息直說超過上限。每次被截斷都當下入帳 `llm_usage`。`analyze()` 裡回空且 `finish_reason=length` 也走這條(重送一次、訊息說超過上限);但推理模型的槓桿仍是換模型,不是再加預算。
- **排程器的 signal handler 只做賦值**,不取鎖、不寫 log。光把 log 移出去不夠——只要 handler 會拿任何不可重入的鎖,另一條執行緒就能跟它組成死鎖;單執行緒重現不出來,而 systemd 仍顯示 active。
- **判斷「是不是台股」的函式不只一個,規則也不同**:後綴是否合法以 `market_symbol_utils.get_suffix_market` 為準,但另有幾處只看字尾 `.TW`／`.TWO`。新增判斷時委派給它,不要再寫一個 `endswith`。
- **改上游的預設值時留空,不要刪除。**刪掉的話上游下次動到那幾行會自動合併回來;留成空字串,衝突就會出現在寫著理由的位置(踩過:分享圖預設帶上游作者的社群帳號)。上游的命名即使撞名也不改——每次合併都要付代價。
- **上游新增的閘門常常沒有 `tw`。**支援市場的集合要從單一來源衍生;合併後逐一確認台股還在每個 region 集合裡(踩過:台股複盤靜默失去盤面信號)。同名的 `MARKET_LIGHT_REGIONS` 有兩個、意義不同,不要合併。
- **正則的 `\b` 在中日韓文字旁邊不成立**(CJK 也算 `\w`),裸的 `\btw\b` 還會命中 `2330.TW`。繁體是「大盤複盤」的「複」,不是「復」。
