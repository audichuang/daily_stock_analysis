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
| `confidence` | 「進場後**第 60 個交易日收盤**淨報酬 ≥ +30%」的主觀機率。池子基準率 **20.4%**（2026-10-26 重測，舊 20.2% 作廢） |
| `model_confidence_raw` | 2026-10-27 起。模型照錨點與研究結論寫下的**原始機率**，事後不調。`confidence` 是最終採用值，沒覆寫時兩者相同 |
| `override` | 2026-10-27 起。`true`＝人工改了原判（`confidence` 與 `model_confidence_raw` 不同，或 `verdict` 被改）；沒改就 `false` |
| `override_reason` | 2026-10-27 起。`override` 為 `true` 時的一句理由；否則 `null` |
| `exp_upside` / `exp_downside` | 命中／沒命中時的**條件均值**報酬。`exp_downside` 填負數 |
| `entry_range` | 建議進場區間。開盤跳空高於上界 → 回驗判定**未成交**，不計入統計 |
| `invalidation_legs` | 把 `invalidation` 拆成逐腿的陣列，每腿 `{"leg", "source", "true_at_write"}`。`source` 寫**去哪裡查得到**（DB 欄位如 `market.price.close`，或具名的外部來源如「SCFI 週報」）；`true_at_write` 是寫入當下這腿**是否已經成立**。規則與理由見 skill `tw-swing-research` Step 4 |
| `invalidation` | 論題失效條件（催化劑破功、跌破結構），**不是**固定百分比停損。裡面的均線數值是**寫入當天的快照**，別照它判——`make verify-decisions` 會把每個 `MA<n>` 即時重算（前復權）並在「照舊值會得到相反結論」時標 ⚠。踩過：6166 在 07-28 收 137.0，照日誌的 `MA10(136.7)` 看是未跌破，當天真正的 MA10 是 138.70，其實已跌破 |
| `catalyst` / `catalyst_type` / `durable` / `digested` | 催化劑本身、五類分類、可否延續、消化程度 |
| `peer_confirm` / `peer_recent_12m` | 同業有沒有一起動、該產業近 12 個月訊號的實測結果 |
| `theme` | 主題（貨櫃運價、AI 伺服器…）。同主題第二檔起要降部位 |
| `sources` | 每個具名事實的來源連結 |

**前瞻封存期**：2026-10-27 起寫入的 `swing-decisions.jsonl` 決策視為前瞻封存，**不得拿來回頭調整突破池門檻**
（門檻與 20.4% 錨點都在同一段歷史上定的，含 2026 年已到期事件，屬樣本內）。到期 ≥20 筆後，用
`model_confidence_raw` 對 `confidence` 做原判與覆寫的配對 Brier 比較；第一批 h60 約 2027 年 1 月到期。
2026-10-27 之前的列沒有這三個欄位；`verify_swing_decisions.py` 目前不讀它們，之後做原判對覆寫的比較時，缺欄位的舊列視為「原判＝最終、未覆寫」。

期望報酬（`pass` 的第三個條件）：

```
E[R] = exp_upside × confidence + exp_downside × (1 − confidence)     # 加號
```

## 檔案

- `experiment-registry.jsonl` — **實驗登記表**（2026-10-27 起，append-only，進版控）。每個確認性或探索性實驗在**看到結果之前**先登記一行；
  改規格、改 prompt 或改 skill 版本就**另追加一行新的 `trial_id`**（同 `family_id`），不改舊行，狀態變化也用追加（同 `trial_id` 後一行為準）。
  試過幾種規格要全部揭露，多重比較才算得出來。

  | 欄位 | 意思 |
  | --- | --- |
  | `family_id` | 同一組假說／同一條 pipeline（例：`macro-ladder`），多重比較校正以 family 為單位 |
  | `trial_id` | 這一次具體規格的唯一 ID；改規格就換新的 |
  | `hypothesis` | 要檢定的假說，一句話，事前寫定 |
  | `primary_metric` | 主指標與判準（含 CI 與門檻），事前寫定；其餘指標一律探索性 |
  | `formal_n` | 正式樣本數；pilot 還沒估出 σ_d 之前是 `null` |
  | `status` | `preregistered`（確認性，已預登記）／`exploratory`（探索性）／`running`／`concluded`／`abandoned` |
  | `prompt_or_skill_version` | 受測的 prompt 或 skill 版本（skill 用 `SKILL.md` 的 git blob sha 當代理）；尚未上線是 `null` |
  | `registered_at` | 登記日（`YYYY-MM-DD`） |
  | `notes` | 出處（`.claude/reviews/` 不進版控，這裡寫決策項編號與預期）、先驗、旗標與限制 |

- `swing-decisions.jsonl` — 正式日誌，回驗只讀這個
- `swing-decisions-v0-superseded.jsonl` — 2026-07-26 那一輪，在 skill 修正前做的（期望值公式
  符號寫錯、缺 `decided_at` 等必填欄位），只留稽核軌跡，**不進回驗**
- `morning-calls.jsonl` — 每日盤前的 **regime 判讀與動作**（skill `tw-morning-call`），一天一行。
  跟上面兩個檔的層級不同：那是**逐檔**的 60 日進場預測，這是**當日大盤**的方向與動作。
  回驗由 `scripts/verify_morning_calls.py` 做（18:00 `daily_report.sh` 帶 `--append`，手動 `make verify-morning`），
  結果寫進下面的 `morning-calls-outcomes.jsonl`，本檔不改。每行都要明寫 `exclude_from_scoring`：
  **只有明寫 `false` 才計分**，缺欄位當成不計分。可計分不到 20 筆或區間跨零一律 inconclusive，
  不要聲稱 regime 判讀有經驗證的優勢。
  選填的期交所欄位（2026-10-20 起；之前的行沒有）。**從 `uv run python scripts/taifex_positions.py --json` 原樣複製**
  （`make taifex` 的同一支腳本加 `--json`；欄位名、單位都已對好，不要從文字輸出手抄換算）：
  `foreign_fut_oi`（外資台指期大台淨未平倉口數，整數，負＝淨空）、`foreign_fut_oi_chg`（較前一交易日的
  口數變化，整數）、`pc_oi_ratio`（臺指選擇權 P/C 未平倉比，**小數**：文字輸出的 66.17% 在 JSON 已是 0.6617）。
  不可用或沒有日變化時 JSON 裡已是 `null`（原因在 `reasons`），照填 `null`，不要去搜尋補數字。它們只是 `reason` 的佐證，不是 regime 門檻。
  選填的機率欄位（2026-10-27 起；之前的行沒有，回驗跳過該指標）。07:30 凍結、都是 **0~1 小數**，超出範圍當缺：
  `p_close_up`（收盤高於前收，主目標）、`p_oc_up`（收盤高於官方開盤，主目標）、`p_gap_up`（09:05 指數高於前收，次要）、
  `model_version`（`claude`／`fable`／`fable_synth`／`equal_weight`，現行填 `claude`）、`skill_version`（`tw-morning-call/SKILL.md`
  的 git blob sha，`git hash-object` 取得）、`input_snapshot_hash`（07:30 凍結 pack 的 sha256，`uv run python scripts/morning_fable_arms.py --print-hash` 的輸出，供與 Fable 臂配對時確認兩臂看同一份；舊列沒有）、`gap_basis`（`tx_settle`＝`gap_expected` 是夜盤收盤 ÷ 同合約前一日結算價；缺＝舊口徑，夜盤收盤 ÷ 前一日現貨收盤）。
  **休市日的列不計分**：臨時休市（颱風假等；進版控的清單是 `journal/closed-dates.txt`，append-only，與 `market_data.closures.adhoc_closed_dates()`、交易日曆取聯集）或非交易日那天盤前判讀照跑也會留一行
  （例如 2026-10-23），journal 不改原行，所以回驗一律在讀取端排除 `date` 落在休市日的列，並在輸出標明排除幾筆。
  `swing-decisions.jsonl` 已由 `scripts/verify_swing_decisions.py` 的 `read_log` 做掉；日後寫 morning-calls 回驗要沿用同一個判斷
  （`read_log` 的聯集邏輯），不要另寫；新增臨時休市日要追加到 `journal/closed-dates.txt`。

- `morning-arms.jsonl` — 盤前判讀的**其他模型臂**（2026-10-28 起；final-decision 第 7 項第一步），目前只有 `model_version="fable"`（Fable 獨立臂），
  由 `scripts/morning_fable_arms.py` 在 `make morning` 之後前景跑一次寫入。append-only、進版控，**一臂一列、鍵＝(`date`, `model_version`)**，同鍵已存在就不再寫（不覆寫）。
  臂只看凍結的 `make morning` 完整輸出（`reports/morning-packs/<日期>.txt`；同日重跑另存 `<日期>.<HHMM>.txt`，臂腳本取**最早**那份，07:30 那份才是凍結的），
  不讀 Claude 臂的判讀、journal 或任何其他模型的結論。Claude 臂另有 Step 2 的即時補數（夜盤、期貨），**兩臂輸入不完全相同**，配對比較的是整條流程而不是單純模型。
  欄位：`date`、`model_version`、`cli_model`（CLI `modelUsage` 的鍵，實際跑的模型）、`p_close_up`／`p_oc_up`／`p_gap_up`（定義與 `morning-calls.jsonl` 相同；非 0~1 有限小數寫 `null`）、
  `reason`（基準率→調整的文字，截斷）、`input_snapshot_hash`（pack bytes 的 sha256）、`prompt_hash`（system＋user 模板的 sha256，不含 pack）、`latency_s`、
  `cost_usd`（CLI 回的 `total_cost_usd`，**名目值**，訂閱登入下不是實際帳單）、`decided_at`（ISO8601 +08:00）、
  `exclude_from_scoring`（寫入時台北時間已過 09:00 → `true`）、`error`（空＝成功）。
  **失敗也寫一列**（CLI 非 0、逾時、`is_error`、解析失敗、機率不合法）：`error` 非空、p 為 `null`，才看得到失敗率；單臂失敗不讓盤前流程失敗。
  **等權臂不落檔**：`verify_morning_calls.py` 事後算——同日 claude 與 fable 三個 p 都有值時取算術平均。
  回驗（`verify_morning_calls.py`）依 `date` 與 outcomes join，只算兩臂 `input_snapshot_hash` 一致的天，排除 `exclude_from_scoring=true`、`error` 非空、
  無對應 outcome（休市日或尚未回驗）與 hash 缺／不一致的列並印筆數；每臂印對 claude 的配對 Brier 差（claude − 該臂，正＝該臂較好）與 10 日 block bootstrap CI。
  **半年內只出描述性報表**，不下升級結論。登記見 `experiment-registry.jsonl` 的 `morning-arms-fable-indep`；期間不改 prompt（改了要重登記）。
- `morning-calls-outcomes.jsonl` — 上一檔的**事後結果**，一個判讀日一行、以 `date` 為鍵，append-only、同一天不重寫
  （18:00 由 `daily_report.sh` 另開 commit，和預測分開）。休市日不寫；當日官方日資料或 DB 收盤還沒到的那天跳過、隔天補。欄位：
  - `scorable`：判讀列 `exclude_from_scoring` 明寫 `false` 才是 `true`；`note` 記不計分或無法驗的原因。
  - 實際缺口三種，都是相對前一交易日（`prev_session`）：`gap_open_official`＝TWSE 官方開盤（`MI_5MINS_HIST`，09:00:00 第一筆，
    未成交個股以昨收計所以**偏向 0**）、`gap_0905`＝09:05:00 加權指數（`MI_5MINS_INDEX`，含開盤後 5 分鐘走勢）、
    `gap_tx_open`＝台指期近月（當日日盤量最大的月份，`tx_contract`）日盤開盤 ÷ 同契約前一日結算價（期交所 `futDataDown`）。
    `err_<量測>`＝實際 − 預估。
  - `night_spot_gap`＝夜盤收盤 ÷ 前一日現貨收盤（skill 公式用對數字時的值；期交所把夜盤記在它**結束**的那天）、
    `night_tx_chg`＝夜盤收盤 ÷ 前一日結算價、`input_err`＝`gap_expected` − 對應口徑的夜盤值（`gap_basis=tx_settle` 對 `night_tx_chg`，舊列對 `night_spot_gap`；抄錯或用了 21:30 前報價）。
    彙總依 `gap_basis` 分組、縮放比是「實際 ÷ 該組 raw」（新口徑 `night_tx_chg`、舊口徑 `night_spot_gap`；`--brief`／Bark 的縮放建議只看新口徑組，樣本不足就 inconclusive）：`gap_expected` 可能已照建議乘過縮放比，拿它估會把修正再修一次。
  - 09:05 或期貨量測暫時抓不到時，7 個曆日內延後不寫（寫了就不會重算）；超過 7 天仍缺才寫入並在 `note` 記缺哪項。
  - `day_return`／`intraday_return`：收盤 ÷ 前收、收盤 ÷ 官方開盤。`gap_dir_hit`（預估方向對 `gap_0905`）、
    `day_dir_hit`（預估缺口方向對全日方向，描述性，盤前判讀不預測收盤）。
  - `breadth_ma20_close`：當日收盤站上 MA20 比例（與 `screen_tw` 報告 §1 同一份程式碼）；`vix_prior`：台股收盤時已知的
    最近一筆 VIX（前一個美股交易日，`market.macro_series`）。`regime_by_close` 只用這兩項判（VIX>30 宣洩、breadth<25% 全面承壓、
    breadth>50% 且 VIX<20 順風、其餘輪動；族群分化與爆量不在檢查內），`regime_consistent` 是它與判讀標籤是否相同，自創標籤為 `null`。
  - 機率計分欄（判讀列有 `p_*` 才有意義）：`p_close_up`／`p_oc_up`／`p_gap_up` 與 `model_version`／`skill_version`／`gap_basis` 照抄判讀列
    （非 0~1 小數的 `p_*` 寫 `null` 並在 `note` 記原因）；`y_close_up`／`y_oc_up`／`y_gap_up`＝實際結果（1＝高於、0＝不高於；
    收盤對前收、收盤對官方開盤、`gap_0905` 對前收）；`night_dir_up`＝`night_spot_gap` 是否為正。
  - 四條基準，每條各一組方向值與機率值，三個目標各一份：`base_<k>_dir_<目標>`（0／1）與 `base_<k>_p_<目標>`，目標＝`close_up`／`oc_up`／`gap_up`。
    (a) 永遠看漲（方向恆 1，機率＝252 日滾動上漲頻率）；(b) 昨日方向（機率＝P(漲｜昨日同向) 的 252 日滾動頻率）；
    (c) 07:30 前最近一個美股交易日的 S&P 方向（`market.macro_series` 的 `^GSPC`；機率＝P(漲｜S&P 同向) 的滾動頻率）；
    (d) `night_spot_gap` 符號（方向＝`night_dir_up`，**機率先留 `null`**，等夜盤歷史回補）。機率一律 Laplace 加一 `(k+1)/(n+2)`，
    只用 `date` 早於判讀日的資料；`base_n_<目標>` 是用到的歷史筆數。`gap_up` 的 (a)(b)(c) 機率與 (b) 方向一律 `null`（歷史沒有逐日 09:05 指數，官方開盤與 09:05 不是同一事件）；(a) 恆看漲、(c) S&P 方向不需要 09:05 歷史，方向值照寫、照算命中差 a_i，彙總對 gap_up 只印「Brier 不可用（缺 09:05 歷史）」；基準歷史任一月份抓不到時整組留 `null` 並印不可用。
    資料源抓不到時該基準欄是 `null`，輸出明印「不可用」，不補 0。
  - 彙總（`render_prob_summary`）：模型 Brier、對各基準的配對差 d_i（基準 Brier − 模型 Brier，正＝模型較好）與命中差 a_i（模型方向＝p>0.5），
    10 日 circular block bootstrap 95% CI；n<20 或 CI 跨零印 inconclusive，n<20 只報整體偏差 p̄−ȳ。缺 `p_*` 的舊列跳過。
  - `action_flag`：觀望／續抱遇到全日 ±1.5% 以上、買進遇到 −1.5% 以下、減碼遇到 +1.5% 以上時標出，**描述，不是績效**。

## 怎麼用

```bash
make morning            # 每天早上：補資料 → 昨晚國際盤 → 期交所籌碼 → 待觸發計畫 → 候選，接著跑 tw-morning-call
make swing              # 更新資料 → 全市場篩選 → 產出候選 JSON，接著跑 tw-swing-research
make verify-decisions   # 60 交易日後回驗（未到期的會列出剩餘天數）
make verify-morning     # 盤前判讀回驗：預估缺口 vs 實際、regime 對定義（唯讀；18:00 排程才寫 outcomes）
```

回驗看的是四個量，**不是命中率**——候選池本來就是正期望值，「進場的那些賺錢」證明不了任何事：

```
E[R|enter] − E[R|全收]        選出來的比全收好多少
E[R|pass]                     放棄掉的後來漲了多少（機會成本）
Brier(conf) vs Brier(20.4%)   confidence 有沒有比「一律報基準率」更準
可成交口徑                    同 5 個空位下「全收 vs 只收 enter」兩本帳
```

結論一律要求 **bootstrap 區間不跨零且已到期 ≥20 筆**，否則標為 inconclusive。
- `media-picks.jsonl` — **財經電視節目點名**（`make media-picks`，`scripts/tw_media_picks.py`），一筆點名一行。
  來源是固定頻道的完整版，清單與篩選規則在腳本的 `CHANNELS`（電視財經節目 10 個、投顧分析師每日解盤 12 個、獨立 YouTuber 1 個、研究型 2 個）：NotebookLM 產生逐字稿並逐集列出點名，
  股名對照 `apps/dsa-web/public/stocks.index.json` 轉代號，再附播出當時已知的本地數據。
  收盤資料還沒入庫（看 `market.price` 的最新場次；上市、上櫃都抓到才會寫入那天，例如下午手動跑、或上櫃行情抓失敗）時，該集先不寫、留給下一輪（stderr 印 `[defer]`）；`--since` 預設 4 天前，週五延後的集數隔週一仍補得到，但收盤資料停更超過這個窗口的集數會漏掉，要手動帶 `--since` 補。
  **這是候選來源，不是買進訊號**：上一輪掃描的點名事後表現是 inconclusive（`docs/research/2026-10-22-tw-media-sweep.md`）。
  腳本當天自己追加；跟 `swing-decisions.jsonl` 一樣**當天 commit**，事後不改。累積夠多再對 0050 回驗，在那之前不聲稱有效。

  | 欄位 | 意思 |
  | --- | --- |
  | `date` | 播出日：標題裡有日期（`20261020`、`2026.10.20`、`2026/10/20`，且在上傳日之前 14 天內）就用它，否則退回上傳日。**2026-10-23 之前寫入的列（沒有 `date_source` 欄）一律是上傳日**：有 5 支影片、137 列晚於標題日期（例如 `2JgSp6Oa-jk` 標題 20261016、`date` 寫 10-20），這些列的 `data` 含播出後的行情；另外 2026-10-22 16～17 點擷取的列有一部分 `data.as_of` 是前一天收盤（當時收盤還沒入庫）；標題含「盤前」的舊列（陳昆仁 #財經早點名）可能用了播出日收盤。回驗舊列以標題日期為準、用 `data.as_of` 判斷 `data` 的實際基準，jsonl 不改寫 |
  | `upload_date` / `date_source` | YouTube 上傳日；`date` 的來源（`title` 標題日期、`upload` 上傳日）。2026-10-23 起才有 |
  | `show` / `kind` / `video_id` / `url` / `title` | 節目、來源類別、影片。`kind`：`tv`（電視財經節目）、`advisor`（投顧分析師，頻道本身在招攬會員，有利益衝突）、`kol`（一綺聊股這類非投顧的 YouTuber）、`research`（財報狗、MoneyDJ 這類研究型）；回驗要分開算。瘋狂股市福利社、理周TV 是多位投顧同台，同一人同一天的看法可能在不同 `show` 各記一次，算「幾個頻道看多」時要用 `speaker` 去重。2026-10-22 第一次 commit 的那批沒有這欄，都是 `tv` |
  | `name` / `name_said` | NotebookLM 還原的正確股名／逐字稿裡的寫法（語音辨識常有同音錯字，例如「建頂」） |
  | `stock_code` / `resolve` / `code_llm` | 對到的代號、怎麼對到的、NotebookLM 原本給的代號。順序：逐字稿念的是數字（ETF 常這樣）就用那個代號（`code`）；否則先用還原後的股名比對（`exact`／`alias`），比對不到才用 NotebookLM 給的代號（名稱吻合 `code`，不吻合 `code_mismatch`，要人工確認）；最後才是字面相近（`fuzzy`，要人工確認）或 `unresolved`（留 `null`）。實測 NotebookLM 的股名比它猜的代號可靠（宜鼎被給成宜特的代號）。整集沒有點名時寫一行 `no_picks`，避免重抓 |
  | `stance` | `bullish`／`bearish`／`avoid`／`neutral`；同一檔不同來賓看法不同時分兩行 |
  | `speaker` / `reason` / `theme` / `condition` / `quote` | 誰說的、理由、題材、節目給的價位或進出場條件（原話）、關鍵原話 |
  | `data` | 播出當時已知的最近一個收盤（`as_of` 是實際的交易日；播出日 17:00 後才上傳的用播出日；標題含「盤前」、或播出日 17:00 前就上傳的〔盤中連線〕用前一天以前的，因為當天的個股法人買賣超下午才公布；2026-10-23 晚上以前寫入的列只看標題的「盤前」，下午上傳的集數可能含當天法人）：`close`、`cum_adj_factor`（首個交易日至 `as_of` 的除權息／分割因子連乘，沿用 `market_data` 的事件對齊與去重；跨日快照以 `close / cum_adj_factor` 比較首次至今報酬，任一端舊快照缺因子時退回原始價並明標未還原）、`vs_ma20_pct`／`vs_ma60_pct`（前復權）、`from_60d_high_pct`、`ret_5d_pct`、`revenue_yoy_3m`（截止日依法定公告期限已看得到的最近三個月，保險類 15 日、遇休市順延）、`foreign_5d_lots`／`trust_5d_lots`（上市、上櫃都有；窗口內法人資料有缺日時才是 `null`）。無行情時整欄 `null` |
  | `extracted_at` / `notebook_id` | 擷取時點、NotebookLM notebook（一天一本，30 天後刪；逐字稿另存 `data/media_picks/`，gitignore） |

- `media-picks-review.jsonl` — **媒體點名的代號覆核**，一筆覆核一行，由 23:00 排程的 Claude 讀
  `scripts/media_picks_summary.py` 的 `review` 清單後追加（`media-picks.jsonl` 原行不改）。對象是 `resolve` 為
  `code_mismatch`／`fuzzy`／`unresolved` 的點名：語音辨識的同音誤字（「上權」→上詮）、NotebookLM 還原成全名而對不到索引
  （「台灣化學纖維」→台化 1326）、已下市或併入的公司（新光金）。回驗讀 `media-picks.jsonl` 時，以
  `(video_id, name_said, stock_code)` 對上這裡的最後一筆覆核，`verdict` 為 `correct` 就改用 `corrected_code`、`not_stock`／`unclear` 就排除。
  `scripts/media_picks_summary.py` 下次執行時會回灌：`correct` 的點名改掛到 `corrected_code`（本輪與歷史列都改，原代號留在 `corrected_from`；該列的 `data` 是照錯的代號抓的，回灌時丟掉），`not_stock` 不計入個股；`unclear` 照原代號，回驗時自行排除。

  | 欄位 | 意思 |
  | --- | --- |
  | `video_id` / `show` / `name_said` / `stock_code` | 被覆核那一行的原值（`stock_code` 可能是 `null`），三者合起來對回原行 |
  | `verdict` | `confirm`（原代號對）／`correct`（改成 `corrected_code`）／`not_stock`（不是個股，例如指數、產業、人名）／`unclear`（逐字稿也判斷不了） |
  | `corrected_code` | `verdict=correct` 時的代號，帶 `.TW`／`.TWO` 後綴；其他情況 `null` |
  | `reason` | 判斷依據，一句話（例如逐字稿上下文、索引裡的正式名稱） |
  | `reviewed_at` | 覆核時點（帶時區） |

- `media-picks-verdicts.jsonl` — **媒體點名的 Claude 判斷**，一檔一行，由 23:00 排程的 Claude 讀完
  `scripts/media_picks_summary.py` 的證據、對挑出來的個股跑 `scripts/tw_stock_dossier.py` 後追加。腳本只整理證據，好壞由 Claude
  判斷；這個檔讓那些判斷可以回驗（例如 `research` 與 `avoid` 之後的報酬差）。研究名單，不是買進訊號。

  選檔前也讀摘要的「前幾輪點名過、判斷檔沒有涵蓋的檔」（JSON `unjudged`，索引末段只放每輪統計與判斷過卻沒寫進判斷檔的檔，完整清單用 `--unjudged`）：回看 7 天、早於本輪擷取、且此檔沒有涵蓋那次點名的判斷列（有 `written_at` 的列只看它是否不早於那次擷取；沒有 `written_at` 的舊列才看 `since`）（已套用代號覆核；更早的舊判斷不算涵蓋，列在 `last_verdict`）。附點名時段、多空人數、`media_picks_judge.py --log` 記下的判斷紀錄；沒有判斷紀錄不代表判過。要不要補判、補哪幾檔由主 agent 決定，新舊候選共用 8 檔上限；補判的檔 `--code`（也就是逐檔判斷拿到的原話）會附上前幾輪的舊證據。舊證據的原話帶代號比對狀態（`resolve`、說的名稱、LLM 代號、影片 id、覆核結果）：前幾輪代號沒把握的點名不在本輪 review 清單，`--unjudged` 會標「代號沒把握且未覆核 N 筆」，要不要先覆核（逐字稿在 `data/media_picks/<video_id>.txt`）由主 agent 決定。腳本不自動補判、不推定投資建議；`since` 與 `--judge-since` 保留原語義。

  | 欄位 | 意思 |
  | --- | --- |
  | `date` | 本輪日期（台北） |
  | `code` / `name` | 代號（帶 `.TW`／`.TWO`，已套用代號覆核）與名稱 |
  | `verdict` | `research`（值得隔天交給 tw-swing-research，每輪最多 3 檔）／`watch`（有道理但時機或證據不夠）／`avoid`（理由站不住、太熱或有明顯風險） |
  | `thesis` | 講者的邏輯與資料支不支持，兩三句 |
  | `evidence` | 判斷引用的關鍵數字（字串陣列，附數值與日期） |
  | `risks` | 風險（字串陣列） |
  | `flip` | 什麼變化會改變看法 |
  | `bull_voices` / `bear_voices` | 本輪看多／看空的講者數（依講者去重） |
  | `data_as_of` | 資料包的基準日 |
  | `since` | 本輪的 since（log 的 `RESULT since=`，帶時區），表示判到這一輪為止；下一輪的 `media_picks_summary.py --judge-since` 用它找出還沒判過的輪次。補判時判讀範圍會往前涵蓋，但這裡仍記本輪的 since。`media_picks_summary.py` 的「前幾輪點名過、判斷檔沒有涵蓋的檔」也用它：同代號 `written_at` 不早於那次擷取才算涵蓋；沒有 `written_at` 的舊列才退回 `since` 不早於那次點名所屬那一輪 |
  | `written_at` | 寫入時點（帶時區） |

  **回驗**：`scripts/verify_media_picks.py`（`make verify-media-picks`）把每筆 verdict（進場＝`written_at` 台北日期之後第一個交易日的開盤）與每個講者點名（進場＝播出日之後第一個交易日的開盤，播出當天的價格一律不用）接上 5／10／20 個交易日後相對 0050 的超額報酬（扣成本），依 verdict、講者（看多與看空分開，看空命中＝超額<0）分表。**命中一律用毛超額（兩邊都不扣成本）**：個股賣出稅 0.3% 對 0050 的 0.1%，淨超額會讓一檔沒動的股票被算成看空命中；均值超額看多用淨（可交易）、看空用毛，報告表頭有註明。**n<20、進場日不足 5 個不同交易日（research−avoid 差兩組各自要 ≥5 天）或 bootstrap 95% CI 跨零一律標 inconclusive**；視窗未走完的事件排除並計數、不補值。逐檔判斷（`media_picks_judge.py`）會把講者的 10 日紀錄附進提示詞，n<20 或進場日<5 天時明寫「樣本不足」要求忽略。

- `ptt-picks.jsonl` — **PTT 股票板 `[標的]` 文**（`make ptt-picks`，`scripts/tw_ptt_picks.py`），一篇一行。
  `[標的]` 是板規格式的推薦文（標的／分類／分析／進退場機制），直接解析原文、不經 LLM；`Re:` 回文不收。實測一週約 12 篇，其中約一半是大盤／台指期或美股（`resolve=market`，不附 `data`）。
  跟媒體點名一樣是**候選來源，不是買進訊號**；作者是匿名網友，推／噓數是擷取當下的值（文章越新越少），不是最終值。同一次搜尋翻頁會按文章 ID 去重，避免翻頁時有新文章將同一篇擠到下一頁而重複寫入；不同文章仍各自保留。

  | 欄位 | 意思 |
  | --- | --- |
  | `date` / `posted_at` / `article_id` / `url` / `title` / `author` | 發文日與時刻（台北，取自文章檔名的 unix 秒）、文章、PTT ID |
  | `target` / `stock_code` / `resolve` | 作者寫的標的、對到的代號、怎麼對到的：先比對股名，比對不到才用作者寫的數字（含只寫 `2330.TW`、`00631L.TW`、`6811.TWO` 而沒有名稱；台股後綴隨代號移除，其他市場後綴不移除；股名吻合 `code`、不吻合 `code_mismatch`，例如小米 1810、年份 2025 都是四位數）；板規範本的 `(例 2330.TW 台積電)` 會先拿掉；沒寫代號又是大盤、台指期、費半這類字眼時是 `market`（不做字面相近比對，否則「台灣大盤」會被對成台灣大） |
  | `category` / `stance` | 作者填的分類原文；`stance` 只在分類（或標題結尾）只出現「多」或只出現「空」時才是 `bullish`／`bearish`，討論、請益、多空都寫的是 `neutral` |
  | `reason` / `condition` | 分析／正文（前 500 字）、進退場機制（前 300 字，板規範本的提示字已拿掉）；沒照範本寫的文章 `reason` 是全文前 500 字 |
  | `has_statement` | 對帳單欄有附連結 |
  | `push_up` / `push_down` / `push_neutral` | 擷取當下的推／噓／→ 數 |
  | `edited_at` | 最後一次編輯的時刻（`※ 編輯` 標記）；內文是擷取當下讀的，編輯過的文可能在行情走完後改了多空或進出場，回驗時要排除或改用這個時刻 |
  | `data` | 發文當時已知的資料，欄位同 media-picks；17:00 前發的文用前一天以前的（當天個股法人買賣超下午才公布） |
  | `extracted_at` | 擷取時點 |
