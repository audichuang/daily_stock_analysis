# scripts — 研究、索引、門檻與打包腳本

> 本檔只寫本目錄增量。

## 模組定位

這個目錄混了七種性質完全不同的腳本,動手前先認清手上這支是哪一種——副作用差很多:

| 類別 | 腳本 | 副作用 |
|---|---|---|
| 台股波段研究 | `screen_tw`、`measure_signal_forward`、`measure_market_regime`、`measure_revenue_momentum`、`portfolio_walkforward`、`backtest_screen`、`verify_swing_decisions` | 唯讀本地 Postgres;`measure_market_regime`／`measure_revenue_momentum` 的狀態與營收特徵純函式在 `src/services/tw_backtest_context.py`(與台股 prompt 共用,改量測口徑要同步那裡寫死的 CI 文案),結論見 `docs/tw-signal-research-2026-10.md`;`verify_swing_decisions` 只讀 `journal/`,沒有任何腳本會寫它;`screen_tw` 的 `main()` 在基準日＝預期場次時另即時抓官方公告(處置／注意股、事件日曆,`--no-risk-flags`／`--no-events` 關閉),純函式與三支量測 loader 不連網 |
| 個股資料包 | `tw_stock_dossier` | 唯讀本地 Postgres;券商分點另連網查富邦 DJ(`--no-branch` 關閉),不寫 DB |
| 每日報告回測 | `backtest_daily_report_levels`、`shadow_buy_eval` | 唯讀應用庫(報告價位;有 `STORAGE_DATABASE_URL` 就讀它,否則 `data/stock_analysis.db`;`shadow_buy_eval` 只認 `STORAGE_DATABASE_URL`/`--db`,連線設 READ ONLY,`--by-variant` 依 `dashboard.prompt_variant` 分表、未標記歸 `untagged`)與 Postgres(行情);後者寫 markdown 到 `reports/` |
| 盤前／盤中取數 | `overnight`、`taifex_positions`、`intraday_breadth`、`kr_tw_memory_watch` | 連網(yfinance／Shioaji／期交所),不寫 DB;後兩支另讀 DB |
| 股票索引 | `fetch_tw_stock_list`、`merge_tw_into_index`、`refresh_us_stock_index`、`refresh_stock_index`、`generate_index_from_csv` | **改寫進版控的索引檔與種子 CSV** |
| 資料庫維運 | `migrate_sqlite_to_pg`、`backfill_price_change_sign`、`migrate_storage_to_postgres` | **寫入 Postgres**;最後一支只碰 `--schema` 指定的應用庫表(分析歷史等),有 `--dry-run`,目標非空需 `--replace` |
| 門檻／治理／打包 | `ci_gate.sh`、`ci_test_shard`、`check_ai_assets`、`test.sh`、`build-*`、`pyinstaller_runtime_compat` | CI 與發版流程直接呼叫,檔名被測試用字串釘住 |

## 進來改要遵守

- **台股波段研究的契約正本是 `docs/tw-swing-pipeline.md`,成本口徑是 `docs/tw-trading-costs.md`。**改門檻、視窗、成本之前先讀,改完同步文件裡「凍結的訊號定義」。
- **訊號定義是各寫各的,沒有共用 import,而且門檻也各存一份。**live 在 `screen_tw.py`(條件逐檔切片、門檻在 `BREAKOUT`);量測在 `measure_signal_forward.py`(整張面板 `shift`/`rolling`、門檻是它自己的 argparse 預設);`portfolio_walkforward.py` import 量測的訊號,但門檻預設與排序公式又各抄一份。**只改 `BREAKOUT` 不會讓 `make measure`／`make portfolio` 跟著變**——它們照常結束,印出來的是另一組訊號。踩過兩次口徑差(60 日高的視窗、月營收保鮮期是曆日不是交易列)。
- **`backtest_screen.py` 不是 live 策略的回測。**檔名與說明寫著 screen_tw,但它有自己的 `FACTORS`、預設跑 `momentum`,沒有 `breakout`。別拿它當凍結訊號的正本。
- **成本、稅率、滑價、年化天數一律走 `tw_trade_costs.py`**(真源在 `src/utils/`,這裡的同名檔只是 shim,因為每日報告的成本檢核也要用同一組費率),不要在腳本裡自己寫常數。個股與 ETF 的證交稅率不同,0050 基準沿用個股稅率會高估基準成本,而那個誤差方向對策略有利。
- **價格面板不要 `ffill`**:索引是多檔交易日的聯集,補出來的假 K 棒會佔掉均線視窗的一格、擠掉最舊的真 K 棒,結果不報錯但足以翻轉「已跌破／未跌破」。
- **argparse 的 help 字串裡百分號要寫成 `%%`。**裸的 `%` 會讓 `--help` 在進 `main` 之前就 `ValueError`(修過兩次)。

## 踩雷

- **`migrate_sqlite_to_pg.py` 是已完成的一次性遷移,不要再執行。**它沒有 argparse(任何參數都被當成 sqlite 路徑),對 `market` schema 七張表逐一 `TRUNCATE` 後重灌,而且**每張表各自 commit**——中途失敗時前面的表已經被舊資料換掉。該 schema 是台股歷史的唯一資料源、沒有備份。
- **`--help` 不是安全探針**:沒有 argparse 的腳本 `main()` 直接做事、把參數忽略或當成路徑。拿 `--help` 掃一遍會真的執行它們(踩過:一次掃描重寫了進版控的 `stocks.index.json`);要探能不能跑,先 `grep -c argparse`。
- **`daily_report.sh` 被 `source` 時只載入函式、不跑 main**,`tests/test_daily_report_sh.py` 靠這點測試;不要直接執行腳本去測。逾時、鎖與完成標記的語意見 `docs/daily-report-ops.md`。
- **`merge_tw_into_index.py` 沒有 argparse**,任何參數都會被忽略並直接改寫索引;目標檔不存在時只印 skip、照樣回 0。`refresh_us_stock_index.py` 有 `--dry-run`,但不加參數仍會連網並寫檔。
- **台股索引只用 `make refresh-tw`,不要用 `refresh_stock_index` 全量重生**:全量需要本 repo 通常沒有的 Tushare 匯出檔,缺檔會丟掉三萬多筆 A 股條目。
- **回補 `price.change` 的正負號不能用 `close - lag(close)`。**官方比的是當日參考價(前收 × 復權因子),除權息日兩者方向不同;讀取視窗也要往前多取,否則每檔每年第一個交易日沒有前一列可比、被靜默跳過。
- **`pyinstaller_runtime_compat.py` 的環境變數必須在 import 時設定**,不能收進 `main()`:它是被當成 runtime hook 載入的,不走 `__main__`。收進去之後打包照樣成功,凍結後的程式才壞。
- **`exit 0` 不是正確性。**這裡踩過的缺陷幾乎都是照常結束、數字是錯的(排序分數整欄 NaN 讓 `--top N` 退化成代號最小的 N 檔;兩支回測各用不同年化天數)。驗證要看輸出內容,不是看結束碼。`test.sh` 的期望值是手寫的,也曾把缺陷釘成正確答案。
