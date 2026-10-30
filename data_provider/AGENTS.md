# data_provider — 多資料源適配與 fallback

## 模組定位

所有行情/基本面/大盤統計的取數都經 `base.py::DataFetcherManager`——市場路由、優先序、熔斷、欄位補全都在那裡決定,各 `*_fetcher.py` 只管單一來源。上游維護 A 股/港股/美股路徑;台股那幾條是本 fork 增量,合併上游時最容易被沖掉。

## 台股取數地圖

| 資料 | 來源(依序) | 要知道的 |
|---|---|---|
| 日線 | `MarketDBFetcher`(本地 `market` schema)→ yfinance | 依 `priority` 排序,沒有錨定首選;細節見 `market_data/AGENTS.md` |
| 即時報價/走勢 | `ShioajiFetcher` → yfinance | **順序寫死在 `get_realtime_quote`,不讀 `priority`**;正本 `docs/realtime-board.md` |
| 大盤統計(家數/成交額/三大法人) | `TwseFetcher`;家數依序 `twtazu_od` → `MI_INDEX?type=MS`(含漲跌停)→ `tw_breadth.py` 由本地 DB 自算(無漲跌停) | 單位是**億元**;`TwseFetcher` 刻意退出日線路由。前兩者回應都自帶日期、須等於最新交易日才採用,被拒收才往下退 |
| 估值/月營收 | 報價上有就用,缺了才補(台股一律問 `TwseFundamentalAdapter`(官方即時 API),因報價從不帶殖利率) | **不讀本地 DB**。估值快照**整包拒收凍結端點**(端點會停更卻照樣回 200;規則與快取見 adapter docstring)。PE 是交易所的**近四季**口徑(prompt 標「本益比（近四季）」,不是「動態」)。月營收的民國「資料年月」用 `twse_fetcher._roc_date` 轉,必須 **call-time import**(頂層 import 會與 `base.py`→adapter、`twse_fetcher`→`.base` 成環),也別另寫第三份解析 |
| 財報(營收/淨利/營運現金流) | `YfinanceFundamentalAdapter`(季報表 → 缺才退 `info` 的近四季聚合) | 逐欄退回,同一張表可混單季與近四季,所以 `financial_report.basis` 逐欄標 `quarter`／`ttm`／`ttm_derived`(淨利 = 近四季營收×淨利率)／`quarter_derived`(單季營收×近四季淨利率,僅估算),prompt 說明欄印口徑。金額經 `_format_amount` 帶單位與幣別、負值保留正負號;幣別跟財報 `currency` 走(HK ADR 可為 CNY),不跟交易市場走。ROE 等比率原樣 |
| 個股三大法人 | 當日走 `TwInstitutionalFetcher`(網路);歷史趨勢才讀本地 DB | 單位是**股**,不是張。歷史上市、上櫃都有(上櫃自 2018-01-15 起,同表 `market='tpex'`),場次不足 2 時 prompt 改印揭露句、不算趨勢;「近 5／20 日累計」只在窗口內每一場都有值時才印(`tw_institutional_trend.py`);本地歷史比「今天之前最後一個交易日」舊就視為停更並明講 |
| 券商分點 | `tw_broker_branch.py` 按需查富邦 DJ 個股主力進出頁,不入庫、不進報告 prompt(目前只有 `scripts/tw_stock_dossier.py` 用) | 只有前 15 名買超／賣超;HHI 只在前 15 名內算、平均成本是這 15 家的;頁面 `getYMD1` 是迄日、`getYMD2` 是起日 |
| 賣方共識(`ANALYST_CONSENSUS_ENABLED`,預設關) | `analyst_consensus.py`(yfinance,台股＋美股) | 只在基本面階段抓,會呼叫 `ticker.info`,**不能搬到報價路徑**;沒有共識本身的 as_of,新鮮度只能從價格日期推;純資訊,不進 coverage／status。**共識隨每份報告落在 `analysis_history.context_snapshot` 的 `fundamental_context.consensus`,as_of＝報告時間**(不另建表;沒被分析的股票沒有,要固定時點得另開子票,見 `docs/macro-data.md`),回測研究直接從那裡讀 |
| 個股融資融券 | 只讀本地 DB(`market_repo.margin`,3 秒 statement timeout);純函式 `tw_margin_trend.py` 算最新餘額、5／20 場次變化與券資比 | 單位是**張**(與三大法人的股不同),**T+1 發布**所以 prompt 標資料日。上市、上櫃同表(上櫃 `market='tpex'`),查無資料回空字串;場次 <6／<21 不印對應變化。注入點在三大法人 `if/elif` **之外**,T86 成功或失敗都出現;prompt-only、fail-open、不入持久化 context |

## 進來改要遵守

- **台股的 yfinance 報價 `source` 必須維持 `fallback`**(us/jp/kr 才標 `yfinance`):Shioaji 降級時 `limit_up`/`limit_down` 變 `None`,這是降級的可辨識訊號。索引裡有的台股名稱**不會**變英文,別拿名稱語言判斷。
- **上市+上櫃合計的欄位(成交額、三大法人)任一邊缺就整組作廢**,不拿活著的那一邊當合計——兩邊可能反向。家數、成交額、法人三組各自獨立降級;缺值維持 0/`None`,下游用 truthiness 判成「沒有資料」,所以不要補近似值(`tw_breadth` 因此不合成漲跌停家數)。
- **新增會回大盤統計的 fetcher,必須登記進 `base.py` 的 `_STATS_MARKET_FETCHER_SUPPORT`。**不在表中 = 每個市場都參與,而第一個回非空的來源就勝出。日線那張支援表是另一張,補了一張擋不住另一張。
- **大盤統計的新鮮度參照(「最新交易日」)取 OpenAPI／rwd 兩版 FMTQIK 較新的一份,不可退回只看 OpenAPI。**OpenAPI 版盤後會落後一天以上,拿它當參照不會報錯,而是把當日新鮮的法人、上櫃、本地寬度全當過期拒收,成交額還印成前一交易日的。
- **兩套三大法人不能互相換算或比較**:大盤複盤那組是億元,個股那組是股。
- **18:00 報告當下拿到的三大法人(個股 T86、大盤 BFI82U)是證交所初版**,官方之後還會改(投信最常變)。報告和官方網站對不上時,先別當成抓錯——數字與資料庫端的處理見 `docs/market-data-pitfalls.md` 的「T86 初版」。
- **月營收 YoY 不寫進通用的 `revenue_yoy`**:口徑是月不是年,回填會被下游「營收同比」標籤讀成年增。
- **代碼格式規則的單一真源是 `src/services/market_symbol_utils.py`**:fetcher 委派給它、別手寫;剝後綴時 `.TWO` 要排在 `.TW` 前面。
- **改 `yfinance_fetcher._convert_stock_code` 就要同步 `yfinance_fundamental_adapter._convert_to_yf_symbol`**(兩份各自存在,有測試釘住一致)。只改一邊的症狀是報價正常、基本面整塊 N/A,報告照樣渲染。

## 踩雷

- **認不得的代碼格式不會報錯,會掉進 A 股預設分支**(補 `.SZ` 去查、靜默回空)。新增市場或新寫法時,每一個 converter 都要有對應分支。
- **`YFINANCE_PRIORITY` 不是只影響美股。**設成小於 1 會讓 yfinance 排到本地 DB 前面,Yahoo 一有資料就不再讀 `market` schema。
- **指數別名漏登記會被當成同字母的個股**:`SOX` 沒進 `us_index_mapping.py` 時解析成另一家真實公司,價格是真的、公司是錯的。非美股指數的坑見 `docs/realtime-board.md`。
- **yfinance 報價路徑在本地名稱索引命中時不呼叫 `ticker.info`**(那是看板延遲的主因),所以 quote 上的 PE/PB/幣別為空是設計,估值由 fundamental 階段回填。別為了補欄位把 `ticker.info` 加回報價路徑。
- **AkShare 內部的 `requests.get` 不帶 timeout,而 `DataFetcherManager` 呼叫 fetcher 時持有該實例的鎖**(`_call_fetcher_method`)。對端握手不回應時,這次呼叫永遠不返回,排在同一把鎖後面的其他股票也跟著停,整份報告卡死且不報錯(2026-10-12 實測卡在 `stock_cyq_em`)。新增或改動 `ak.*` 呼叫一律包 `_akshare_call_with_timeout`;目前仍未包的有 `stock_zh_a_hist`、`fund_etf_hist_em` 與幾個 spot 介面,只走 A 股/ETF 路徑。A 股專屬的補充資料(籌碼、資金流)在 manager 層用 `_is_non_cn_request` 擋掉非 A 股,別只在單一 fetcher 裡擋。
