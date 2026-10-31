# 美股資料源與社群做法調查 2026-10-31

當日快照。限額與授權會變，引用前回官方頁確認。社群內容是自述，未獨立驗證；標「共識」只代表這批樣本。

## 現況（2026-10-31 的 develop）

- 日線：yfinance → Finnhub → Alpha Vantage → Longbridge（`data_provider/base.py` 的 `is_us` 分支），Mac `.env` 沒有後三者的金鑰，NAS 未核對。
- 即時：yfinance，Longbridge 補欄位。基本面：yfinance `.info` 與季報表。賣方共識：`analyst_consensus.py`（`ANALYST_CONSENSUS_ENABLED=true`）。
- 美股籌碼（機構、內部人、空頭、資金流）develop 尚未進報告；`feat/us-data-evidence` 正在接 yfinance 放空／持股／內部人／評等與富途資金流。
- `market-observatory` 是另一條線：Yahoo chart、Nasdaq、Cboe，在 Cloudflare Worker 內抓。

## 富途 OpenD 實測（同日另一 session）

只註冊未開戶，INTC、GOOG、NVDA 拿得到報價、資金分佈、當日分鐘與每日資金流、日 K、板塊；選擇權無權限。美股行情是促銷期免費，文件沒有截止日。資金流分級口徑與美股涵蓋交易所未驗證，預測力未回測（inconclusive）。

## 免費資料源

### 長期免費、免開戶、有官方文件（repo 目前都沒有 fetcher）

| 來源 | 資料 | 限額／時效 | 注意 |
|---|---|---|---|
| [SEC EDGAR](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) | Form 4、8-K、XBRL | [10 req/s](https://www.sec.gov/os/accessing-edgar-data)；提交資料不到 1 秒 | 要 User-Agent |
| [13F](https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets)、[N-PORT](https://www.sec.gov/data-research/sec-markets-data/form-n-port-data-sets) | 機構與基金持股 | 季更 | 13F 延遲大，不適合當短線訊號 |
| [FINRA](https://developer.finra.org/docs) | 空頭、暗池 ATS | 1,200 req/min；[空頭月 2 次](https://www.finra.org/finra-data/browse-catalog/equity-short-interest)；暗池延遲 2～4 週 | 文件要 OAuth，實測匿名可用，可能收緊 |
| [Reg SHO 日檔](https://www.finra.org/finra-data/browse-catalog/short-sale-volume) | 場外放空量 | 每日 | 不等於空頭部位 |
| [CFTC COT](https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm) | 期貨部位 | 週更 | |
| [Cboe VIX](https://www.cboe.com/tradable_products/vix/vix_historical_data/) | VIX 歷史 | 日更 | P/C 歷史 CSV 止於 2019-10 |
| [FRED](https://fred.stlouisfed.org/docs/api/terms_of_use.html) | 總經 | 限額未公布 | repo 已用 |

### 要帳戶或額度小

| 來源 | 免費範圍 | 判斷 |
|---|---|---|
| [Alpaca Basic](https://docs.alpaca.markets/docs/about-market-data-api) | IEX、200/min、WS 30 檔 | 行情備援候選；台灣註冊資格未查到，未實測 |
| [Longbridge](https://open.longbridge.com/docs/qa/broker.md) | 美股 LV1 | repo 已有整合，但要開戶；台灣資格未查到 |
| [Finnhub](https://finnhub.io/static/swagger.json) | quote、內部人、filings | K 線、持股、ETF 標 Premium；60/min 是三方說法 |
| [Tiingo](https://www.tiingo.com/about/pricing) | 1,000/日、500 檔/月 | 日線交叉核對候選 |
| [Massive（原 Polygon）](https://massive.com/knowledge-base/article/what-is-the-request-limit-for-massives-restful-apis) | 5/min，當日資料過午夜 ET 才給 | 不適合監控 |
| [Twelve Data](https://twelvedata.com/pricing)、[Alpha Vantage](https://www.alphavantage.co/premium/)、[EODHD](https://eodhd.com/pricing)、[Marketstack](https://marketstack.com/pricing) | 8/min、25/日、20/日、100/月 | 額度太小 |

### 非官方、無授權保證

yfinance、api.nasdaq.com、[Cboe 延遲選擇權 JSON](https://cdn-api.cboe.com/api/global/delayed_quotes/options/AAPL.json)（實測 AAPL 3,380 筆，含 IV、Greeks、OI，條款未讀到）、Apewisdom。可自用，要接受隨時失效。

### 沒有免費 API

[Unusual Whales](https://unusualwhales.com/public-api)（試用要綁卡）、[ORATS](https://orats.com/data-api)、[Quiver](https://api.quiverquant.com/pricing/)。Fintel、Tradytics、Market Chameleon、Barchart 的方案本次查不到。

## 社群看法

- 英文圈共識：單看選擇權 flow 沒有方向優勢（[例一](https://www.reddit.com/r/optionstrading/comments/1tahecl/)、[例二](https://www.reddit.com/r/options/comments/1qyrc8s/)）；公開 GEX 數字對持倉假設敏感（[r/quant](https://www.reddit.com/r/quant/comments/1vnb92w/)），指數層級尚可、個股差，有人只拿來當 regime 濾網（[例](https://www.reddit.com/r/options/comments/1rwspuu/)）。
- 英文圈共識：yfinance 不適合當正式資料源，會限流、也有錯值（[限流](https://www.reddit.com/r/YAHOOFINANCE/comments/1nffceo/)、[月線錯值](https://www.reddit.com/r/YAHOOFINANCE/comments/1q24o8t/)）；解法是排程落本地庫，不在分析當下才抓。
- 少數說法：看 breadth（[例](https://www.reddit.com/r/technicalanalysis/comments/1w7id99/)）、預估修正（[例](https://www.reddit.com/r/ValueInvesting/comments/1szr8lj/)）；用 SEC＋FINRA 排程（[例](https://www.reddit.com/r/ai_trading/comments/1uqipy8/)，作者導流）。
- 暗池、CTA、資金流的有效性：社群證據太薄，inconclusive。
- 中文圈：常見 Finviz、TradingView、Seeking Alpha，以及牛牛看盤、別家下單（[PTT 2026-05](https://www.ptt.cc/bbs/Stock/M.1779451506.A.2E0.html)）。台灣開戶資格說法互相矛盾；2026-05 中國證監會對富途、老虎、長橋立案（[鳳凰科技](https://tech.ifeng.com/c/8tKxjyElZma)），對台灣帳號的影響未查證。
- 取樣限制：小紅書 `NEED_LOGIN`、B 站字幕 `NEED_LOGIN`，只拿到標題；Threads 無命中；Reddit 走公開網頁，部分全文被截斷。
