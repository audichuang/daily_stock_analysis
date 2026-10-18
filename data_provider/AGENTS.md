# data_provider — 多資料源適配與 fallback

> 共通規則見 repo 根 `AGENTS.md`(§7 資料源護欄),本檔只寫本模組增量。

## 模組定位

所有行情/基本面/大盤統計的取數都經 `base.py::DataFetcherManager`——市場路由、優先序、熔斷、欄位補全都在那裡決定,各 `*_fetcher.py` 只管單一來源。上游維護 A 股/港股/美股路徑;台股那幾條是本 fork 增量,合併上游時最容易被沖掉。

## 台股取數地圖

| 資料 | 來源(依序) | 要知道的 |
|---|---|---|
| 日線 | `MarketDBFetcher`(本地 `market` schema)→ yfinance | 依 `priority` 排序,沒有錨定首選;細節見 `market_data/AGENTS.md` |
| 即時報價/走勢 | `ShioajiFetcher` → yfinance | **順序寫死在 `get_realtime_quote`,不讀 `priority`**;正本 `docs/realtime-board.md` |
| 大盤統計(家數/成交額/三大法人) | `TwseFetcher`;家數被拒收時退 `tw_breadth.py` 由本地 DB 自算 | 單位是**億元**;`TwseFetcher` 刻意退出日線路由 |
| 估值/月營收 | 報價上有就用,缺了才補(台股一律問 `TwseFundamentalAdapter`(官方即時 API),因報價從不帶殖利率) | **不讀本地 DB**。月營收已進個股 prompt(「財報與股利」表一列,單月口徑、標明月份;含月增、累計年增,可為負);民國「資料年月」用 `twse_fetcher._roc_date` 轉(**call-time import**,adapter 頂層 import 會與 `base.py`→adapter、`twse_fetcher`→`.base` 成環,也別另寫第三份解析)。**估值每列帶 `as_of`(端點的民國 `Date`,同一個 `_roc_date`)**:整包最新 `as_of` 落後 `_today()` 超過 10 曆日(`_MAX_SNAPSHOT_AGE_DAYS`,涵蓋春節)或根本沒有可解析日期就**整包拒收**(端點會凍結卻照樣回 200);上市／上櫃各一份快取(`valuation_twse`／`valuation_tpex`),失敗或凍結不進快取、下次重試,TTL 後重抓失敗最多回退舊快取 24h。PE 是交易所的**近四季**口徑(prompt 標「本益比（近四季，<as_of>）」,不是「動態」),殖利率(`dividend_yield`)也併入並在 prompt 標「交易所公告」 |
| 個股三大法人 | 當日走 `TwInstitutionalFetcher`(網路);歷史趨勢才讀本地 DB | 單位是**股**,不是張。**歷史只有上市;上櫃(`.TWO`)只有當日**,場次不足 2 時 prompt 改印揭露句、不算趨勢;「近 5／20 日累計」只在窗口內每一場都有值時才印(`tw_institutional_trend.py`);本地歷史比「今天之前最後一個交易日」舊就視為停更並明講 |
| 個股融資融券 | 只讀本地 DB(`market_repo.margin`,3 秒 statement timeout);純函式 `tw_margin_trend.py` 算最新餘額、5／20 場次變化與券資比 | 單位是**張**(與三大法人的股不同),**T+1 發布**所以 prompt 標資料日。**只有上市**:上櫃(`.TWO`)固定印「沒有本地融資融券資料」揭露句、不查 DB;場次 <6／<21 不印對應變化。注入點在三大法人 `if/elif` **之外**,T86 成功或失敗都出現;prompt-only、fail-open、不入持久化 context |

## 進來改要遵守

- **台股的 yfinance 報價 `source` 必須維持 `fallback`**(us/jp/kr 才標 `yfinance`)。`source` 由 `shioaji` 變 `fallback`、且 `limit_up`/`limit_down` 變 `None`,是「Shioaji 金鑰沒注入(Doppler `shioaji/dev`)、已靜默降級成延遲報價」唯一可辨識的訊號——症狀是能跑但數字不對勁,不是報錯。索引裡有的台股名稱**不會**變英文,別拿名稱語言判斷。
- **上市+上櫃合計的欄位(成交額、三大法人)任一邊缺就整組作廢**,不拿活著的那一邊當合計——兩邊可能反向。家數、成交額、法人三組各自獨立降級;缺值維持 0/`None`,下游用 truthiness 判成「沒有資料」,所以不要補近似值(`tw_breadth` 因此不合成漲跌停家數)。
- **新增會回大盤統計的 fetcher,必須登記進 `base.py` 的 `_STATS_MARKET_FETCHER_SUPPORT`。**不在表中 = 每個市場都參與,而第一個回非空的來源就勝出。日線那張支援表是另一張,補了一張擋不住另一張。
- **大盤統計的新鮮度參照(「最新交易日」)取 OpenAPI／rwd 兩版 FMTQIK 較新的一份,不可退回只看 OpenAPI。**OpenAPI 版盤後會落後一天以上,拿它當參照不會報錯,而是把當日新鮮的法人、上櫃、本地寬度全當過期拒收,成交額還印成前一交易日的。
- **兩套三大法人不能互相換算或比較**:大盤複盤那組是億元,個股那組是股。
- **18:00 報告當下拿到的三大法人(個股 T86、大盤 BFI82U)是證交所初版**,官方之後還會改(投信最常變;2026-10-15 投信買超初版 283.03 億、定版 292.83 億)。報告和官方網站對不上時,先別當成抓錯——細節與資料庫端的處理見 `market_data/AGENTS.md` 踩雷「T86 初版」。
- **月營收 YoY 不寫進通用的 `revenue_yoy`**:口徑是月不是年,回填會被下游「營收同比」標籤讀成年增。
- **代碼格式規則的單一真源是 `src/services/market_symbol_utils.py`**,fetcher 裡委派給它,不要再手寫一份。台股是 4~6 位數字加至多一個 ASCII 大寫字母(`00631L`、`2887A`);剝後綴時 `.TWO` 要排在 `.TW` 前面。
- **改 `yfinance_fetcher._convert_stock_code` 就要同步 `yfinance_fundamental_adapter._convert_to_yf_symbol`**(兩份各自存在,有測試釘住一致)。只改一邊的症狀是報價正常、基本面整塊 N/A,報告照樣渲染。

## 踩雷

- **認不得的代碼格式不會報錯,會掉進 A 股預設分支**(補 `.SZ` 去查、靜默回空)。新增市場或新寫法時,每一個 converter 都要有對應分支。
- **`YFINANCE_PRIORITY` 不是只影響美股。**設成小於 1 會讓 yfinance 排到本地 DB 前面,Yahoo 一有資料就不再讀 `market` schema。
- **指數別名漏登記會被當成同字母的個股**:`SOX` 沒進 `us_index_mapping.py` 時解析成另一家真實公司,價格是真的、公司是錯的。非美股指數的坑見 `docs/realtime-board.md`。
- **yfinance 報價路徑在本地名稱索引命中時不呼叫 `ticker.info`**(那是看板延遲的主因),所以 quote 上的 PE/PB/幣別為空是設計,估值由 fundamental 階段回填。別為了補欄位把 `ticker.info` 加回報價路徑。
- **AkShare 內部的 `requests.get` 不帶 timeout,而 `DataFetcherManager` 呼叫 fetcher 時持有該實例的鎖**(`_call_fetcher_method`)。對端握手不回應時,這次呼叫永遠不返回,排在同一把鎖後面的其他股票也跟著停,整份報告卡死且不報錯(2026-10-12 實測卡在 `stock_cyq_em`)。新增或改動 `ak.*` 呼叫一律包 `_akshare_call_with_timeout`;目前仍未包的有 `stock_zh_a_hist`、`fund_etf_hist_em` 與幾個 spot 介面,只走 A 股/ETF 路徑。A 股專屬的補充資料(籌碼、資金流)在 manager 層用 `_is_non_cn_request` 擋掉非 A 股,別只在單一 fetcher 裡擋。
- **`tw_institutional_fetcher.py` 檔頭說它「沒有接進報告」,那句是上游留下的舊描述**:實際已由 `base.py` 的基本面組裝呼叫,不是死碼,別依檔頭把呼叫端刪掉。
