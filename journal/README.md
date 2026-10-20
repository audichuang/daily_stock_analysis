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
