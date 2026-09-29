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
| 估值/月營收 | 報價上有就用,缺了才問 `TwseFundamentalAdapter`(官方即時 API) | **不讀本地 DB** |
| 個股三大法人 | 當日走 `TwInstitutionalFetcher`(網路);歷史趨勢才讀本地 DB | 單位是**股**,不是張 |

## 進來改要遵守

- **台股的 yfinance 報價 `source` 必須維持 `fallback`**(us/jp/kr 才標 `yfinance`)。`source` 由 `shioaji` 變 `fallback`、且 `limit_up`/`limit_down` 變 `None`,是「Shioaji 金鑰沒注入(Doppler `shioaji/dev`)、已靜默降級成延遲報價」唯一可辨識的訊號——症狀是能跑但數字不對勁,不是報錯。索引裡有的台股名稱**不會**變英文,別拿名稱語言判斷。
- **上市+上櫃合計的欄位(成交額、三大法人)任一邊缺就整組作廢**,不拿活著的那一邊當合計——兩邊可能反向。家數、成交額、法人三組各自獨立降級;缺值維持 0/`None`,下游用 truthiness 判成「沒有資料」,所以不要補近似值(`tw_breadth` 因此不合成漲跌停家數)。
- **新增會回大盤統計的 fetcher,必須登記進 `base.py` 的 `_STATS_MARKET_FETCHER_SUPPORT`。**不在表中 = 每個市場都參與,而第一個回非空的來源就勝出。日線那張支援表是另一張,補了一張擋不住另一張。
- **大盤統計的新鮮度參照(「最新交易日」)取 OpenAPI／rwd 兩版 FMTQIK 較新的一份,不可退回只看 OpenAPI。**OpenAPI 版盤後會落後一天以上,拿它當參照不會報錯,而是把當日新鮮的法人、上櫃、本地寬度全當過期拒收,成交額還印成前一交易日的。
- **兩套三大法人不能互相換算或比較**:大盤複盤那組是億元,個股那組是股。
- **月營收 YoY 不寫進通用的 `revenue_yoy`**:口徑是月不是年,回填會被下游「營收同比」標籤讀成年增。
- **代碼格式規則的單一真源是 `src/services/market_symbol_utils.py`**,fetcher 裡委派給它,不要再手寫一份。台股是 4~6 位數字加至多一個 ASCII 大寫字母(`00631L`、`2887A`);剝後綴時 `.TWO` 要排在 `.TW` 前面。
- **改 `yfinance_fetcher._convert_stock_code` 就要同步 `yfinance_fundamental_adapter._convert_to_yf_symbol`**(兩份各自存在,有測試釘住一致)。只改一邊的症狀是報價正常、基本面整塊 N/A,報告照樣渲染。

## 踩雷

- **認不得的代碼格式不會報錯,會掉進 A 股預設分支**(補 `.SZ` 去查、靜默回空)。新增市場或新寫法時,每一個 converter 都要有對應分支。
- **`YFINANCE_PRIORITY` 不是只影響美股。**設成小於 1 會讓 yfinance 排到本地 DB 前面,Yahoo 一有資料就不再讀 `market` schema。
- **指數別名漏登記會被當成同字母的個股**:`SOX` 沒進 `us_index_mapping.py` 時解析成另一家真實公司,價格是真的、公司是錯的。非美股指數的坑見 `docs/realtime-board.md`。
- **yfinance 報價路徑在本地名稱索引命中時不呼叫 `ticker.info`**(那是看板延遲的主因),所以 quote 上的 PE/PB/幣別為空是設計,估值由 fundamental 階段回填。別為了補欄位把 `ticker.info` 加回報價路徑。
- **`tw_institutional_fetcher.py` 檔頭說它「沒有接進報告」,那句是上游留下的舊描述**:實際已由 `base.py` 的基本面組裝呼叫,不是死碼,別依檔頭把呼叫端刪掉。
