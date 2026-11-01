# 個股財報與 AI 導讀

Web（報告頁、即時看板展開列）與 iOS（個股頁）的「財報」區塊。API：`GET /api/v1/stocks/{code}/financials`（只讀導讀快取）、`POST /api/v1/stocks/{code}/financials/commentary`（沒有快取才打 LLM）。程式：`src/services/stock_financials.py`、`us_financials.py`、`financial_commentary.py`。

## 資料來源

| 市場 | 季度數字 | 公告日語意 | 備註 |
|---|---|---|---|
| 台股 | `market.financial_statement`（MOPS，新台幣千元，換算成元） | `statutory_deadline`：法定期限，實際公告可能更早，庫內沒有實際日 | 財報季更要手動跑；過下一季期限兩週仍沒有新列，`is_stale=true` |
| 美股 | SEC companyfacts（`SEC_EDGAR_USER_AGENT`）→ 沒有 XBRL 季報或未設定時 yfinance | SEC 是 `filed` 實際申報日；yfinance 是 `unknown` | 美股財報**沒有落庫**；解析結果程序內快取 6 小時，失敗 5 分鐘 |
| 台股月營收 | `market.monthly_revenue`（千元，換算成元） | 庫內公告日 | 重用 `tw_stock_dossier.fundamentals` |

ETF（台股代號 00／02 開頭且沒有財報列、美股 `quoteType` 是 ETF／基金）回 `not_applicable`；其他市場回 `unsupported`；來源失敗回 `unavailable`；查無回 `no_data`。HTTP 都是 200，用 `status` 區分。

## 欄位與選欄理由

| 欄位 | 為什麼選 |
|---|---|
| 營收、月營收（台股） | 成長的起點；月營收比季報早一個多月 |
| 毛利率、營業利益率 | 定價能力與本業獲利能力，看趨勢比看絕對值有用 |
| 淨利、EPS | 最後賺多少；要和營業利益對照才分得出業外 |
| 營業現金流、資本支出、自由現金流 | 分辨帳面獲利和真實現金，資本支出看擴產 |
| 負債比 | 財務風險的最簡單讀數 |
| 合約負債 | 訂單能見度，只顯示有單獨揭露的公司 |
| 股東權益報酬率（近四季，金融業） | 金融業最核心的獲利指標，取代上面不適用的欄位 |

一般模板：營收、毛利率、營業利益率、淨利、EPS、營業現金流、資本支出、自由現金流、負債比、合約負債。金融模板（台股產業 17 或有金融科目；美股 SIC 6000~6499）：淨收益、營收（有才顯示）、淨利、EPS、ROE，其他列進 `not_applicable` 並寫原因。整列沒有值的欄位不回傳。

每期回傳年增與季增：金額是 `yoy_pct`／`qoq_pct`（基期 ≤0 時為 null，沒有意義），比率是 `yoy_pp`／`qoq_pp`（百分點）。基期用期末日距離找，不靠標籤。

## 容易算錯的地方（都有測試）

- **台股現金流量表是年初至今累計**，Q2＝H1−Q1、Q4＝FY−9M。少一季就留空，不拿累計值充數；`derived=true` 代表差分而來。損益表單季欄優先，沒有才用累計差分。約 500 家半年才申報一次的公司 Q1、Q3 沒有資料，所以 Q2 也算不出來。
- **`date` 欄是公告截止日**，3/31 是前一年 Q4。
- **金融業「母公司業主」是綜合損益**（解析時 keep-last；2881 實測 3,120 億 vs 本期淨利 642 億）。淨利只讀 `母公司業主（淨利／損）`，否則 `本期淨利（淨損）`。
- **合約負債只讀 `合約負債－流動`、`合約負債－非流動`**；`LIKE` 會掃進保險合約負債（2881 為 4.77 兆）。
- **資本支出統一支出為正**：台股與 yfinance 是負數、SEC 是正數；自由現金流＝營業現金流−資本支出。
- **SEC 同一 tag 混單季與 YTD**：用 end−start 天數分類，缺單季才差分；fact 的 `fy`／`fp` 指申報不是該列期間，期間取每份申報內最晚的 `end`。同期多份申報取最新值、公告日取最早。只讀該期期末的 instant，停用的 tag（INTC 合約負債停在 2021）不會充數。
- **幣別跟財報走**：TSM `currency=TWD`、`trading_currency=USD`；yfinance 的 EPS 是每 ADR（136.25＝27.25×5），`unit` 標 `TWD/ADR`。
- **yfinance 最新季可能是空的**（INTC 只有 EPS，營收、淨利 NaN），這種季整列丟掉；SEC 仍有資料時以 SEC 為準。
- **SEC 與 yfinance 交叉比對**（差異 >1% 列進 `cross_check.mismatches`，以 SEC 為準）：INTC 的營業利益實測有差，Yahoo 用的是自己的定義。

## AI 導讀（`FINANCIAL_COMMENTARY_ENABLED`，預設關閉）

- 開頁路徑（GET）絕不呼叫 LLM。`commentary.status=missing` 時客戶端才 POST；同鍵併發只付一次，失敗記 10 分鐘（程序內）免得每次開頁都花錢。
- 快取在應用庫 `financial_commentary`，鍵是代號、最新期間、來源、提示詞版本、季度數字雜湊。月營收每月更新**不觸發**重生成；財報重編會。改提示詞要升 `PROMPT_VERSION`。表由 `create_all` 與 `_ensure_financial_commentary_schema` 建，舊環境不用動。
- LLM 回 `metric_key`、`period`、`importance`、`what_happened`、`why_it_matters`、`how_to_read`。欄位或期間不存在、該格沒有值就丟那一條；一條都不剩算失敗。
- **文字裡的財務數字只能是佔位符** `{{gross_margin@2026Q2:yoy}}`，由程式換成回應裡的值。佔位符對不上，或殘留期間、時間長度以外的阿拉伯數字，丟那一條。程式不判斷文字語意。排名與連續幾季由程式算好放進資料包的 `trend`（模型自己數實測會錯），提示詞要求照抄，但程式不驗文字有沒有照抄。
- 截斷的 JSON 算失敗，不走 `json_repair`（修得回來但最後一句是斷的）。輸出上限 16384，同 `tw_stock_report`。
- 欄位的 `definition` 是固定教學，開關關閉也看得到。導讀內容只有繁中。

## 維運

開啟導讀要在該環境設 `FINANCIAL_COMMENTARY_ENABLED=true`；美股要 SEC 為主來源還要 `SEC_EDGAR_USER_AGENT`。回滾：關開關即可，要清快取就 `DROP TABLE financial_commentary`（重開會自動重建）。
