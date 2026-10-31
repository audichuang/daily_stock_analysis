# SEC／FINRA 證據驗收 2026-10-31

## 基線與邊界

工作分支 `feat/us-sec-evidence`。本地 HEAD 與 fetch 後 `origin/develop` 均為 `b3306e727be7360b9de48625b8d6a619f5348edb`，`git pull --ff-only` 回 `Already up to date`。初始工作樹乾淨。建立此 worktree 專用 Python 3.12 venv，依指示安裝 `requirements.txt` 與 `.github/requirements-ci.txt`，沒有改動依賴清單或 lockfile；所有 Python／gate 命令使用 `uv run --frozen`。

取證只讀公開 SEC／FINRA HTTP；`DATABASE_URL='' STORAGE_DATABASE_URL='' LITELLM_MODE=PRODUCTION`，未連正式庫、未啟動服務或模型、未發通知、未操作 NAS。User-Agent 在本輪執行環境取既有 Git 聯絡資訊，不在程式或 fixture 寫入 email。

## 真實網路：新 provider

以 `SecEdgarClient(...).get_evidence(symbol, deadline=time.monotonic() + 25)` 各跑一遍；同時執行 `format_us_evidence` 與 `sec_news_evidence_present`，兩檔均產生提示詞且判為有新聞證據。這是直接操作正式 provider 的唯讀結果，與下節離線 fixture 分開；沒有以 fixture 回應冒充真網路。

| 讀數 | INTC | GOOG |
| --- | --- | --- |
| 整包耗時 | 3.51 秒 | 7.24 秒 |
| 最近 10-Q 申報日 | 2026-10-30 | 2026-10-29 |
| 近 14 天 8-K | 2026-10-29；`2.02,9.01` | 2026-10-28；`2.02,9.01` |
| 8-K 接收時間（UTC） | 2026-10-29T20:08:53.000Z | 2026-10-28T20:01:33.000Z |
| 附件 | `q326earningsrelease.htm`，摘錄 6000 字元 | `googexhibit991q32026.htm`，摘錄 6000 字元 |
| Form 4 已讀／清單數 | 3／3，`complete=true` | 39／39，`complete=true` |
| P 買進／S 賣出（股） | 105,263／0 | 0／247 |
| 可分類／排除交易筆數 | 1／0 | 3／177 |
| FINRA 結算日 | 2026-10-15 | 2026-10-15 |
| FINRA 放空部位（股） | 148,504,504 | 48,412,278 |
| FINRA 回補天數 | 1.54 | 3.29 |

INTC 摘錄確認包含第四季營收 150～160 億美元、non-GAAP EPS 0.25 的公司指引。這是公司自述，不是獨立驗證或投資績效結論。Form 4 依交易日再過濾，因此清單份數不等於窗口內交易筆數；GOOG 合計涵蓋 Alphabet 同一 CIK 的所有普通股股別，不能解讀成僅 Class C。

一手來源：[INTC 8-K](https://www.sec.gov/Archives/edgar/data/50863/000005086326000188/intc-20261029.htm)、[INTC 財報新聞稿](https://www.sec.gov/Archives/edgar/data/50863/000005086326000188/q326earningsrelease.htm)、[GOOG 8-K](https://www.sec.gov/Archives/edgar/data/1652044/000165204426000080/goog-20261028.htm)、[GOOG 財報附件](https://www.sec.gov/Archives/edgar/data/1652044/000165204426000080/googexhibit991q32026.htm)。FINRA 使用[官方資料端點](https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest)，各 ticker 回 212 列；無 `sortFields`、以 `symbolCode EQUAL` 查詢，本機取最新結算日；最新日期各只有一列。

可在設定好 `SEC_EDGAR_USER_AGENT` 的環境以此重跑（不發模型請求）：

```bash
DATABASE_URL='' STORAGE_DATABASE_URL='' LITELLM_MODE=PRODUCTION uv run --frozen python - <<'PY'
import json, os, time
from data_provider.sec_edgar import SecEdgarClient
for symbol in ('INTC', 'GOOG'):
    evidence = SecEdgarClient(os.environ['SEC_EDGAR_USER_AGENT']).get_evidence(
        symbol, deadline=time.monotonic() + 25)
    print(symbol, json.dumps(evidence, ensure_ascii=False))
PY
```

## Fixture 與測試

`tests/fixtures/sec_company_tickers.json` 是官方 ticker 清單中 INTC／GOOG／GOOGL／BRK-B 的縮本；`sec_submissions_{intc,goog}.json` 保留各兩筆 8-K、兩筆 Form 4 及一筆 10-Q 的原始欄式結構；`sec_index_{intc,goog}.json` 保留實際 HTML 清單。`sec_form4_{intc,goog}.xml` 來自實際最近申報（INTC 的 P 與 GOOG 的 S）；`sec_earnings_intc.htm` 保留實際新聞稿的開頭與財測原文片段，縮減 HTML 包裝；`finra_short_intc.json` 是最新三期實際回應。

測試執行時平移申報與交易日期，窗口用執行當下的相對日期，不依賴 fixture 的日曆日仍在窗口內。非市場代碼、衍生交易、未來／過期交易、無效股數為從實際 XML 結構衍生的測試輸入。`sec_disabled_baseline.json` 在改碼前由基線原碼擷取：完整補充證據文字、四語傳統 prompt SHA-256、完整 agent messages 與結果序列化。測試也確認未設 User-Agent 不呼叫新 provider、切換開關不混用快取、真實普通／agent 路徑在歷史保存前登記 SEC 證據且保留搜尋計數。

語法與 flake8 critical gate 通過；受影響測試命令：

```bash
DATABASE_URL='' STORAGE_DATABASE_URL='' LITELLM_MODE=PRODUCTION uv run --frozen python -m pytest \
  tests/test_config_registry.py \
  tests/test_sec_edgar.py tests/test_event_gap_decision.py tests/test_event_gap_lookback.py \
  tests/test_us_data_evidence.py tests/test_us_search_evidence.py tests/test_us_market_path.py \
  tests/test_notification_empty_news_disclosure.py tests/test_pipeline_finalize.py -q
```

## 正反 mutation

每次只改一個條件，啟動新的 pytest 程序，確認 exit 1 且為斷言失敗，再以 `finally` 還原原始碼；非匯入／語法失敗，未以 mock 短路被測判定。25 個 mutation 全部抓到。表內數字是對應定向命令的失敗數，測試還原後再跑完整驗證。

| Mutation | 失敗數 |
| --- | ---: |
| 傳統路徑移除 SEC 登記 | 4 |
| agent 路徑移除 SEC 登記 | 4 |
| 一般 8-K 標頭也算新聞 | 3 |
| 過度要求一定有摘錄，拒絕 Item 2.02 | 2 |
| 移除 14 天窗口 | 2 |
| 過度縮為 3 天窗口 | 1 |
| 未設 User-Agent 仍啟用 | 1 |
| 過度停用有效 User-Agent | 2 |
| 非美股誤啟用 | 2 |
| Form 4 所有代碼算買賣 | 1 |
| 過度排除 S，只算 P | 1 |
| 衍生交易混入普通股 | 1 |
| Form 4 移除交易日窗口 | 1 |
| Form 4 過度縮為 60 天 | 1 |
| Form 4 存在仍印 Yahoo 交易合計 | 1 |
| 過度清空 Yahoo 所有放空欄位，連官方缺值也不補 | 1 |
| 不移除 Yahoo 與 FINRA 重複的欄位 | 1 |
| FINRA 改取最舊結算日 | 1 |
| 移除 SEC 限速 | 1 |
| 限速過度拒絕所有有效請求 | 1 |
| 移除設定切換的快取隔離 | 1 |
| 官方來源忽略階段預算 | 1 |
| 官方來源預算過度設為 0 | 1 |
| 移除 SEC 環境限定設定登記 | 1 |
| 過度將 SEC 聯絡資料加入 Web 設定介面 | 1 |

首輪受影響測試 460 項通過；加入設定契約後為 522 項通過。首輪全量為 12,773 通過、129 跳過、8 排除，唯一失敗是 `.env.example` 新鍵未登記。這是本次變更的契約遺漏，已在 `src/core/config_registry.py` 加入 `WEB_SETTINGS_HIDDEN_FROM_UI`，並補正反 mutation 證明既能登記又不增加 UI。129 項跳過皆來自 `market_data/tests` 的 DB 測試，原因是本次依指示清空 `DATABASE_URL`；8 項 `network` 測試由命令選擇排除。完整重跑命令如下，結果於完成後記在文末：

```bash
DATABASE_URL='' STORAGE_DATABASE_URL='' LITELLM_MODE=PRODUCTION uv run --frozen ./scripts/ci_gate.sh offline-tests
```

## 修改檔案

- Provider 與整合：`data_provider/sec_edgar.py`、`data_provider/base.py`、`data_provider/us_evidence.py`、`src/core/pipeline.py`。
- 設定：`src/config.py`、`src/core/config_registry.py`、`.env.example`。
- 測試：`tests/test_sec_edgar.py`、`tests/test_event_gap_decision.py`、`tests/test_event_gap_lookback.py`。
- 十個 fixture：`sec_company_tickers.json`、`sec_disabled_baseline.json`、`sec_earnings_intc.htm`、`sec_form4_goog.xml`、`sec_form4_intc.xml`、`sec_index_goog.json`、`sec_index_intc.json`、`sec_submissions_goog.json`、`sec_submissions_intc.json`、`finra_short_intc.json`，皆位於 `tests/fixtures/`。
- 文件：`docs/CHANGELOG.md`、`docs/us-data-sources.md`、本驗證紀錄。

## 未驗證與限制

完整 Web／agent 真模型生成、落庫後的 UI、通知與 NAS 部署未實測：本次任務明確禁止這些操作。替代驗證是兩條真實 pipeline／finalize 在外部模型及儲存隔離下的測試，加上直接呼叫新 provider 的真 HTTP 結果；不宣稱模型遵循了提示詞。

未驗多程序合計限速、FINRA 未來匿名權限、所有公司附件格式、4/A 修訂對合計的影響。附件辨識依目前已驗證的 HTML 內容，無法辨識或預算不足時省略摘錄；Item 2.02 的索引事實仍可算新聞證據。Form 4 部分讀取明示 `complete=false`。SEC／FINRA 不入評分、行情或 `capital_flow`；清空 User-Agent 回到原行為，完整回滾為 revert 本次 commit。

本文沒有對應英文版；README 中英首頁未改，來源契約集中在 `docs/us-data-sources.md`。已核對本文檔名、程式介面與 gate 命令。

## 最終驗證結果

- `syntax`／`flake8`：exit 0，flake8 critical 為 0。
- 受影響測試：522 passed，45 warnings，exit 0。
- 還原全部 mutation 後的全量離線測試：**12,774 passed、129 skipped、8 deselected、997 subtests passed**，681 warnings，369.91 秒，exit 0。129 項皆為未設定 `DATABASE_URL` 的 `market_data/tests`；沒有未解釋的失敗。測試期間未改檔，完成後只補本段數字。
- 正反 mutation：25／25 被斷言抓到；原始碼皆已還原。
- 原始 gate／pytest／mutation 日誌與真實 provider 回應保存在本機 `.claude/reviews/verification/us-sec-evidence-20261031/`（gitignore，無 User-Agent 或秘密值）。
