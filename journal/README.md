# 決策日誌（append-only，進版控）

台股波段流程第 2 層（skill `tw-swing-research`）每天做完事件面研究後，把每一檔的判斷追加一行到
`swing-decisions.jsonl`。60 個交易日後由 `make verify-decisions` 回驗。

完整的四層契約與各層被驗證到什麼程度：[`../docs/tw-swing-pipeline.md`](../docs/tw-swing-pipeline.md)。
回驗採逐筆雙邊手續費、賣出證交稅與買賣各 0.15% 滑價；二代健保邊界見
[`../docs/tw-trading-costs.md`](../docs/tw-trading-costs.md)。

## 為什麼放這裡、而且要 commit

- **`.claude/reviews/` 進不了版本庫**：`.gitignore` 忽略 `.claude/*`，而 `scripts/check_ai_assets.py`
  會**擋掉** skills 以外任何被追蹤的 `.claude/` 檔案。放那裡等於這份記錄不存在。
- **git history 就是防竄改機制**：`confidence` 是一個對未來的預測，只有在**結果出來之前**就已經
  commit，它才有意義。事後補記或改掉一個數字，回驗算出來的 Brier score 全是假的。
  所以規則是：**當天研究完就 commit，不要累積幾天一起補；事後補的 `outcome` 另開一個 commit。**
  踩過：2408／3017（08-13 的判斷）晚了 10 天才進版控；morning-calls 有 4 筆是 08-05 同一個 commit
  補進來的，5 筆裡最後只有 1 筆可計分。

## 一行一個決策，欄位語意

| 欄位 | 意思 |
| --- | --- |
| `date` | **訊號日**（候選 JSON 的 `as_of`），決定回驗的持有窗口起點 |
| `decided_at` | 你**實際做完判斷**的時點（帶時區）。進場日取「`date` 與它兩者較晚者」的次一交易日 |
| `verdict` | `enter` / `pass`，只有這兩種 |
| `confidence` | 「進場後**第 60 個交易日收盤**淨報酬 ≥ +30%」的主觀機率。池子基準率 **20.2%** |
| `exp_upside` / `exp_downside` | 命中／沒命中時的**條件均值**報酬。`exp_downside` 填負數 |
| `entry_range` | 建議進場區間。開盤跳空高於上界 → 回驗判定**未成交**，不計入統計 |
| `invalidation_legs` | 把 `invalidation` 拆成逐腿的陣列，每腿 `{"leg", "source", "true_at_write"}`。`source` 寫**去哪裡查得到**（DB 欄位如 `market.price.close`，或具名的外部來源如「SCFI 週報」）；`true_at_write` 是寫入當下這腿**是否已經成立**。規則與理由見 skill `tw-swing-research` Step 4 |
| `invalidation` | 論題失效條件（催化劑破功、跌破結構），**不是**固定百分比停損。裡面的均線數值是**寫入當天的快照**，別照它判——`make verify-decisions` 會把每個 `MA<n>` 即時重算（前復權）並在「照舊值會得到相反結論」時標 ⚠。踩過：6166 在 07-28 收 137.0，照日誌的 `MA10(136.7)` 看是未跌破，當天真正的 MA10 是 138.70，其實已跌破 |
| `catalyst` / `catalyst_type` / `durable` / `digested` | 催化劑本身、五類分類、可否延續、消化程度 |
| `peer_confirm` / `peer_recent_12m` | 同業有沒有一起動、該產業近 12 個月訊號的實測結果 |
| `theme` | 主題（貨櫃運價、AI 伺服器…）。同主題第二檔起要降部位 |
| `sources` | 每個具名事實的來源連結 |

期望報酬（`pass` 的第三個條件）：

```
E[R] = exp_upside × confidence + exp_downside × (1 − confidence)     # 加號
```

## 檔案

- `swing-decisions.jsonl` — 正式日誌，回驗只讀這個
- `swing-decisions-v0-superseded.jsonl` — 2026-07-26 那一輪，在 skill 修正前做的（期望值公式
  符號寫錯、缺 `decided_at` 等必填欄位），只留稽核軌跡，**不進回驗**
- `morning-calls.jsonl` — 每日盤前的 **regime 判讀與動作**（skill `tw-morning-call`），一天一行。
  跟上面兩個檔的層級不同：那是**逐檔**的 60 日進場預測，這是**當日大盤**的方向與動作。
  **回驗程式還沒寫**（`make verify-decisions` 只讀 `swing-decisions.jsonl`），所以欄位刻意都是
  事後能驗對錯的觀測值。`gap_expected` **不能對 `market.market_index` 驗**，那張表沒有開盤價；
  要改對 TWSE 官方加權指數日資料（`MI_5MINS_HIST`，驗法見 skill `tw-morning-call` Step 4）。
  每行都要明寫 `exclude_from_scoring`，累積到 20 筆**可計分**的判讀再寫回驗；在那之前，
  不要聲稱 regime 判讀有經驗證的優勢。
  選填的期交所欄位（2026-10-20 起；之前的行沒有）。**從 `uv run python scripts/taifex_positions.py --json` 原樣複製**
  （`make taifex` 的同一支腳本加 `--json`；欄位名、單位都已對好，不要從文字輸出手抄換算）：
  `foreign_fut_oi`（外資台指期大台淨未平倉口數，整數，負＝淨空）、`foreign_fut_oi_chg`（較前一交易日的
  口數變化，整數）、`pc_oi_ratio`（臺指選擇權 P/C 未平倉比，**小數**：文字輸出的 66.17% 在 JSON 已是 0.6617）。
  不可用或沒有日變化時 JSON 裡已是 `null`（原因在 `reasons`），照填 `null`，不要去搜尋補數字。它們只是 `reason` 的佐證，不是 regime 門檻。

## 怎麼用

```bash
make morning            # 每天早上：補資料 → 昨晚國際盤 → 期交所籌碼 → 待觸發計畫 → 候選，接著跑 tw-morning-call
make swing              # 更新資料 → 全市場篩選 → 產出候選 JSON，接著跑 tw-swing-research
make verify-decisions   # 60 交易日後回驗（未到期的會列出剩餘天數）
```

回驗看的是四個量，**不是命中率**——候選池本來就是正期望值，「進場的那些賺錢」證明不了任何事：

```
E[R|enter] − E[R|全收]        選出來的比全收好多少
E[R|pass]                     放棄掉的後來漲了多少（機會成本）
Brier(conf) vs Brier(20.2%)   confidence 有沒有比「一律報基準率」更準
可成交口徑                    同 5 個空位下「全收 vs 只收 enter」兩本帳
```

結論一律要求 **bootstrap 區間不跨零且已到期 ≥20 筆**，否則標為 inconclusive。
- `media-picks.jsonl` — **財經電視節目點名**（`make media-picks`，`scripts/tw_media_picks.py`），一筆點名一行。
  來源是固定頻道的完整版，清單與篩選規則在腳本的 `CHANNELS`（電視財經節目 9 個、投顧分析師每日解盤 10 個、研究型 2 個）：NotebookLM 產生逐字稿並逐集列出點名，
  股名對照 `apps/dsa-web/public/stocks.index.json` 轉代號，再附播出當時已知的本地數據。
  收盤資料還沒入庫（看 `market.price` 的最新場次；上市、上櫃都抓到才會寫入那天，例如下午手動跑、或上櫃行情抓失敗）時，該集先不寫、留給下一輪（stderr 印 `[defer]`）；`--since` 預設 4 天前，週五延後的集數隔週一仍補得到，但收盤資料停更超過這個窗口的集數會漏掉，要手動帶 `--since` 補。
  **這是候選來源，不是買進訊號**：上一輪掃描的點名事後表現是 inconclusive（`docs/research/2026-10-22-tw-media-sweep.md`）。
  腳本當天自己追加；跟 `swing-decisions.jsonl` 一樣**當天 commit**，事後不改。累積夠多再對 0050 回驗，在那之前不聲稱有效。

  | 欄位 | 意思 |
  | --- | --- |
  | `date` | 播出日：標題裡有日期（`20261020`、`2026.10.20`、`2026/10/20`，且在上傳日之前 14 天內）就用它，否則退回上傳日。**2026-10-23 之前寫入的列（沒有 `date_source` 欄）一律是上傳日**：有 5 支影片、137 列晚於標題日期（例如 `2JgSp6Oa-jk` 標題 20261016、`date` 寫 10-20），這些列的 `data` 含播出後的行情；另外 2026-10-22 16～17 點擷取的列有一部分 `data.as_of` 是前一天收盤（當時收盤還沒入庫）；標題含「盤前」的舊列（陳昆仁 #財經早點名）可能用了播出日收盤。回驗舊列以標題日期為準、用 `data.as_of` 判斷 `data` 的實際基準，jsonl 不改寫 |
  | `upload_date` / `date_source` | YouTube 上傳日；`date` 的來源（`title` 標題日期、`upload` 上傳日）。2026-10-23 起才有 |
  | `show` / `kind` / `video_id` / `url` / `title` | 節目、來源類別、影片。`kind`：`tv`（電視財經節目）、`advisor`（投顧分析師，頻道本身在招攬會員，有利益衝突）、`research`（財報狗、MoneyDJ 這類研究型）；回驗要分開算。2026-10-22 第一次 commit 的那批沒有這欄，都是 `tv` |
  | `name` / `name_said` | NotebookLM 還原的正確股名／逐字稿裡的寫法（語音辨識常有同音錯字，例如「建頂」） |
  | `stock_code` / `resolve` / `code_llm` | 對到的代號、怎麼對到的、NotebookLM 原本給的代號。順序：逐字稿念的是數字（ETF 常這樣）就用那個代號（`code`）；否則先用還原後的股名比對（`exact`／`alias`），比對不到才用 NotebookLM 給的代號（名稱吻合 `code`，不吻合 `code_mismatch`，要人工確認）；最後才是字面相近（`fuzzy`，要人工確認）或 `unresolved`（留 `null`）。實測 NotebookLM 的股名比它猜的代號可靠（宜鼎被給成宜特的代號）。整集沒有點名時寫一行 `no_picks`，避免重抓 |
  | `stance` | `bullish`／`bearish`／`avoid`／`neutral`；同一檔不同來賓看法不同時分兩行 |
  | `speaker` / `reason` / `theme` / `condition` / `quote` | 誰說的、理由、題材、節目給的價位或進出場條件（原話）、關鍵原話 |
  | `data` | 播出當時已知的最近一個收盤（`as_of` 是實際的交易日；節目收盤後播出用播出日收盤，標題含「盤前」的節目用前一天以前的收盤）：`close`、`vs_ma20_pct`／`vs_ma60_pct`（前復權）、`from_60d_high_pct`、`ret_5d_pct`、`revenue_yoy_3m`（已公告的最近三個月）、`foreign_5d_lots`／`trust_5d_lots`（上市、上櫃都有；窗口內法人資料有缺日時才是 `null`）。無行情時整欄 `null` |
  | `extracted_at` / `notebook_id` | 擷取時點、NotebookLM notebook（一天一本，30 天後刪；逐字稿另存 `data/media_picks/`，gitignore） |
