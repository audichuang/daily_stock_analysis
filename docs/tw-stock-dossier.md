# 台股個股四維度資料包

`scripts/tw_stock_dossier.py` 把單一台股的基本面、合約負債、籌碼、估值與 SMC 技術結構整理成一份資料包（Markdown 或 `--json`），**只列數字與出處、不下結論**，給人或 LLM 寫個股深度報告用。查不到的欄位一律印「無資料」，不估算。

```bash
uv run --env-file .env python scripts/tw_stock_dossier.py 3324
uv run --env-file .env python scripts/tw_stock_dossier.py 3324.TWO --date 2026-08-28 --json
uv run --env-file .env python scripts/tw_stock_dossier.py 2330 --no-branch   # 不連網查分點
```

唯讀本地 `market` schema；只有券商分點會即時連網。

## HTML 分析報告

版面參考 botbook.cc：先是四維度結論卡，接著是基本面、合約負債、籌碼面、估值、SMC 價位階梯與結構事件，最後是追蹤重點。比 botbook 多了以下內容：
- 當日與近 5 日分點並排
- 三大法人 20 日累計
- 獨立的估值段（PE 百分位刻度）
- 價位階梯標出每個價位距現價的百分比（量到近端邊，現價在區間內為 0，和盯盤看板、價位警報同一個量法）
- 頁尾列出各段資料日

實作在 `src/services/tw_stock_report.py`（資料包在同目錄的 `tw_stock_dossier.py`）；`scripts/` 底下的同名檔只是 CLI 包裝，因為 Docker 映像不含 `scripts/`。

**Web 入口**：首頁個股詳情的「四維度分析」按鈕只在 `.TW`／`.TWO` 出現，按下開啟抽屜。
- 後端是 `GET /api/v1/stocks/{code}/dossier`，參數 `narrative`、`theme=light|dark`、`date`。
- 抽屜先載入純數字版，再背景請求 `narrative=true` 的版本，拿到就替換。報告放在不執行腳本的 sandbox iframe 裡。
- 錯誤碼：
  - 400 `unsupported_market`：不是台股代號。
  - 400 `invalid_date`：`date` 格式對但不是真的日期（例如 `2026-13-45`）。
  - 404 `not_found`：本地行情查無此股；或後綴寫錯市場（例如 `2330.TWO`），訊息會提示正確的代號「2330.TWO 應為 2330.TW」。股票索引裡兩邊都查不到（新掛牌）時不擋。
  - 503 `dossier_unavailable`：台股庫不可用或產生報告出錯。

**解讀（narrative）**：
- 撰寫規則與 JSON 格式只有一份，就是 `NARRATIVE_RULES`。Web 由伺服器設定的生成後端撰寫（呼叫 `GeminiAnalyzer.generate_text`，用量在 LLM 用量頁記為「四維度分析」，即 `call_type=stock_dossier`）。
- 結果依「股票＋資料基準日」快取在 `DATABASE_PATH` 同目錄的 `dossier_narratives/`，同一天重開不重算——除非同一基準日的資料晚入庫（解讀記下各段資料日 `data_stamp`：最新營收月、最新季、法人／融資／集保／估值的 as_of、現價，任一變了就重寫），或這次比上次完整（分點晚到、上次讀取失敗的段落這次讀到了；兩個維度都不能比上次差，反過來或互有缺漏都不重寫）。為了寫得更完整而重寫時 LLM 失敗，沿用數字相同的舊解讀；數字本身變了就照常顯示失敗。所以收盤後法人、融資陸續入庫時，同一檔一天可能重付 2～3 次 LLM；Docker 裡就是 `/app/data` 這個 volume。
- LLM 失敗或回傳格式不對時，頁面退回只列數字並顯示提示，失敗的結果不會被快取。
- 快取檔先寫暫存檔再 rename，寫到一半被殺不會留下截斷的 JSON；萬一快取檔還是壞了（讀不出 JSON 或不是物件），當作沒有快取、重呼 LLM 蓋掉它，不會整個基準日都顯示「AI 解讀產生失敗」。
- **數字核對只是便宜的防呆**：解讀裡帶小數或千分位的數字，要能在資料包找到，或所在句子標了「自算」。不帶小數也沒有千分位的整數（「5 日」「30 張」）不核對，推導算式本身也不驗算；張數、人數一換成帶小數的「萬張」「萬人」就會被核對。
  - 允許的寫法：四捨五入到 0~3 位、絕對值，以及只對帶單位的欄位做的換算：`*_k`（千元）換成億（÷100,000）或萬（÷10）；張數（三大法人 `*_lots`、融資融券餘額與增減、分點每列的買進／賣出／買賣超與 `buy_total`／`sell_total`）與總股東人數換成萬（÷10,000，例如「14.9 萬張」「309.9 萬人」）。換算過的數字**後面必須真的寫「億」「萬」**（寫成「37.7 千元」、「14.9 張」或不寫單位都核對不到）；Fib `position`（0~1）×100 寫成百分比；Fib／OTE 常數 0.5、0.618、0.705、0.786（含 ×100）。
  - 價位與現價的距離：SMC 各價位（事件、OB、FVG、流動性、Fib／OTE）與近 5 日／當日主力均價對現價的距離％，兩個方向（價位/現價−1、現價/價位−1）都認，但數字後面必須緊接「%」。報告的價位階梯本來就印這些數；沒這條時正式站每份解讀都被標黃，看板結論卡也就永遠不出現。
  - 快取檔記錄核對規則的版本（`check_version`，目前 3）。版本不同的舊快取一律當過期重寫，看板也不採用它的結論卡標籤，規則收緊後舊快取不會一直沿用。
  - 價格、PE／PB 等其他欄位只認原值，所以小數點抄錯位（1085 寫成 108.5）會被標出。
  - 有核對不到的數字時，頁面照常顯示，頂部列出這些數字。這份解讀照樣快取，但只算 6 小時新鮮，之後開啟才重寫，避免每次開都重付一次 LLM。全部核對得到的解讀不受 6 小時限制。
- 解讀規則要求 OTE 跟著最新結構解讀：最新事件是空方結構時，OTE 是反彈賣壓區，不准寫成買進區、進場區或支撐。
- 同一檔、同一基準日的資料包在行程內快取 10 分鐘，所以先看數字、再等解讀，不會重查分點。

報告內文只有繁體中文（台股限定功能）；抽屜本身的按鈕與標題有中、英、繁三語。

**技術面的文字**：結構事件多方寫「突破」、空方寫「跌破」（例如「🔽 BOS BEARISH（跌破 1,395.0）」）；OTE 那一行依最新結構標成「OTE 多方進場區」或「OTE 空方進場區」，還沒有結構事件時是「OTE 進場區」，和看板同一套標籤。

**容錯**：資料包每一段各自容錯，任一段查詢出錯只讓那段顯示「無資料」，頁首列出讀取失敗的段落（`errors`），不會整頁 503。只有查不到價格或整個台股庫連不上時，才回 404／503。

**CLI／skill**：本機要用 Claude Code 寫解讀時走 skill `/stock-report`（`.claude/skills/stock-report/SKILL.md`）。

```bash
uv run --env-file .env python scripts/tw_stock_report.py 3324 --dump-data /tmp/3324.json
uv run --env-file .env python scripts/tw_stock_report.py 3324 --data /tmp/3324.json --print-prompt   # 規則＋資料包
uv run --env-file .env python scripts/tw_stock_report.py 3324 --data /tmp/3324.json --narrative /tmp/3324.narrative.json -o reports/dossier/3324_2026-10-21.html
```

## 每一段的來源與限制

| 段落 | 來源 | 限制 |
|---|---|---|
| 月營收 13 個月、近 12 月累計年增 | `market.monthly_revenue` | 依公告日過濾（`--date` 之後才公告的月份不會出現）；累計年增要滿 24 個月才算 |
| 季度毛利率／營益率／淨利率／EPS | `market.financial_statement`（`income_sheet`） | 季度標籤由公告截止日換算（`financial_statement.afterIFRS`）。金融保險業實際截止日晚約 15 天，用 `--date` 看歷史時這類公司可能提前看到財報（見 `afterIFRS` 說明） |
| 合約負債 | `financial_statement`（`balance_sheet` 的「合約負債－流動／非流動」） | 約 1,900 家有單獨列示；沒列的公司（如 3324）多半併在其他流動負債，報告寫「無法評估」，不拿別的科目代替 |
| 三大法人 5／20 日 | `market.institutional`（上市＋上櫃） | 單位換成張；窗口內有缺值就不印累計 |
| 融資融券 | `market.margin`（上市＋上櫃） | 單位張、T+1；不含融資使用率（表內沒有限額欄） |
| 千張大戶、股東人數 | `market.holding_dist`（集保） | 開放資料只給最新一週；要週變化得先 `market_data.cli holding-history <代號>` 補歷史（每檔約 51 個請求）。TDCC 表單 token 每次請求後輪換，某週逾時後會重新 GET 查詢頁換 token；回「查無此資料」的週次拒收，整串只印一條 `**WARN`（附週數與範圍）——代號打錯、該週無資料、作廢 token 回的頁面逐字相同，全部週次都查無時先檢查代號。補完約 51 週，春節那週集保不出資料，前後相隔約兩週是正常的，不是漏補 |
| 券商分點 | 富邦 DJ 個股主力進出頁（`data_provider/tw_broker_branch.py`） | **只有前 15 名買超與前 15 名賣超**；HHI 只在前 15 名買超分點內計算，「平均買超成本」是這 15 家的加權成本，不是全體大戶成本 |
| 估值 | `market.valuation`（上市 BWIBBU、上櫃 peQryDate） | 本益比百分位要近 3 年至少 120 個有值交易日才算 |
| SMC 結構 | `market.price` 套前復權（`market_repo.front_adjust_multipliers`）後算 | 定義寫死在 `src/services/smc_structure.py` 模組說明（擺動點 n=3、收盤突破才算、OB／FVG／Fib 的取法）；SMC 沒有統一標準，換定義數字就不同 |

## 和 botbook.cc 範例報告的對照

2026-10-22 拿 botbook.cc 的 3324 雙鴻報告（基準日 2026-08-28）逐項對照：

- **分點 HHI 959 與我們用前 15 名買超分點算出的完全一致**，前 5 名買超分點與張數也逐筆相同——對方的 HHI 同樣只用前 15 名，不是全市場分點。
- 季度毛利率／營益率／淨利率／EPS 八季逐格一致；本益比 26.29、融資使用率 20.21% 與 TPEx 端點原始欄位一致（資料包目前不輸出融資使用率：`market.margin` 沒存融資限額）。
- **對方月營收整條錯一個月**：標成「26/08 3,765,466（+116.7%）」的其實是 2026-07（8/10 公告），8 月營收要到 9/10 才公告，基準日 08-28 時不可能有。
- 「C9S 籌碼九階段」與「大戶成本 L5」是對方自訂的衍生指標，沒有公開定義，這裡不做。

## 上線順序（正式庫）

1. 安靜時段對正式庫套 migration `d3a8b6e15c27`（只加欄位與新表，`lock_timeout` 10 秒，拿不到鎖就失敗重跑）。
2. 合併並部署新程式到所有會寫 `market` schema 的地方：本機排程共用的主 checkout（`docs/daily-report-ops.md`）要切回含這次改動的分支；NAS Web 只讀不寫，不受影響。
3. 之後才回補上櫃（`backfill institutional_tpex|margin_tpex|valuation_tpex`）或讓 `daily` 抓上櫃。順序反過來，舊程式的 resume／整日換血看不到 `market` 欄，會把同一天的上市、上櫃當成同一份。

回滾（順序不能反：舊程式看不到 `market` 欄，上櫃列還在時它的整日換血會把上櫃一起刪掉、refresh 會因列數對不上而拒絕上市修正）：

1. 先停所有寫入 `market` schema 的排程。
2. **還在新程式時**匯出 `holding_dist` 與上櫃列，再 `DELETE FROM market.<institutional|margin|valuation> WHERE market='tpex'`、清空 `holding_dist`。
3. 降版 migration（表內還有上述資料時會拒絕執行）。
4. 最後才把主 checkout 退回舊程式、恢復排程。

## 相關

- 上櫃法人／融資／估值與集保怎麼更新、回補：skill `update-market-data`、`docs/market-data-pitfalls.md`
- 只抓不入庫的處置／注意股、事件日曆：`market_data/risk_flags.py`、`market_data/events.py`
