---
name: "tw-morning-call"
description: "台股每日盤前判讀：一鍵取數（補資料／隔夜收盤／待觸發計畫／候選）→ 補美股即時期貨與台指期夜盤 → 判定今天的 regime（順風／輪動／全面承壓／宣洩）→ 給出今天買、減碼、或不動的明確動作。當使用者問今天能不能進場、今天該買還是該賣、今天大盤怎麼看、今天要不要動、或量化候選 0 檔時該怎麼辦時使用。"
---

# 台股盤前判讀 (Morning Call)

量化層是 **supplier，不是 gate**。它每天供應數字，不決定今天能不能動——那是這份 skill 的工作。

差別具體到什麼程度：2026-07-30 早上，`breakout` 池 **0 檔**（前一日大盤 −3.76%，突破新高的股票結構上不存在），
而同一份 DB 用寬門檻掃得出 **48 檔「逆勢抗跌 + 法人買超」**。把 0 檔當成「今天沒事做」是錯的兩次——
一次是漏掉那 48 檔攜帶的族群資訊，一次是漏掉持倉今天該不該減。

**你的價值在 regime 判讀，不在重述硬指標。** 把 DB 的數字重新排列組合再說一遍，等於沒做這一層。

## Step 1：一鍵取數

```bash
make morning       # 補資料 → 大局（總經／Fed 利率預期／台股位階與資金／未來 14 天事件）→ 昨晚國際盤收盤 → 期交所籌碼 → 待觸發計畫 → 昨晚媒體點名 → 今日 breakout 候選
```

七件事都在裡面，**不要用搜尋湊隔夜數字**：`scripts/overnight.py` 有日期戳、有 ADR 折算、
有日期一致性檢查，而搜尋引擎會把不同交易日的收盤混在一起（實測差到 3.7pp）。
`overnight.py` 任一序列失敗會回 1（表裡該列印「失敗」），`make morning` 忽略這個錯誤、後面幾段照跑；
失敗的那幾個數字要自己補查，不能當成沒有變動。

**期交所籌碼區塊**（`scripts/taifex_positions.py`，單跑用 `make taifex`）印前一交易日的外資台指期（大台 TXF）
淨未平倉與日變化、臺指選擇權 P/C 未平倉比。讀法：

- 只有回應最新一列的日期＝預期場次才印數字；否則該項印 `⚠ …：不可用（原因）`，**就當今天沒有這個數字**，
  不要去搜尋補。兩項各自降級，一項不可用不影響另一項。
- 日變化只在前一列正好是前一交易日時才印；印「不列日變化」時只有水位。
- 出現 `⚠ 跨月結算` 時，未平倉變化含結算／轉倉效應，不要讀成法人換方向。

**昨晚媒體點名區塊**（`scripts/media_picks_brief.py`，單跑 `uv run --env-file .env python scripts/media_picks_brief.py`）：
濃縮 23:00 排程寫的 `journal/media-picks-verdicts.jsonl` 最近一輪（超過 4 天印「已過期」、沒有檔印「沒有媒體點名判斷」）。
分「持股相關」（avoid 排最前）、research、watch 的翻轉條件、其餘避開名單；腳本只挑列與截短，不判斷，**不是買進訊號**。
持股清單取不到時印「持股清單取不到」、其餘照印；整段失敗 `make morning` 照跑。

今日候選的報告 §0 有一行「處置／注意股名單」狀態，§5 有「事件日曆」；待觸發計畫的代號不在候選裡，
要查處置／注意狀態用 `uv run python -m market_data.risk_flags <代號…>`（`2424` 或 `2424.TW` 皆可）。

再補一次寬掃，拿今天的資金流向樣本（`market.institutional`／`margin`／`valuation` 上市與上櫃共表，
上櫃回補完成前，缺法人資料的上櫃股會被 `momentum` 的「法人買超」篩選剔除，族群分布可能偏上市）：

```bash
uv run --env-file .env python scripts/screen_tw.py --strategy momentum \
  --top 40 --min-turnover 1 --json /tmp/mom.json --out /tmp/mom.md \
  --no-risk-flags --no-events   # 寬掃只看族群分布，不必再抓一次即時名單與事件
```

`momentum` 池只當**觀測**：它在 13 年回測是十個因子裡同曝險超額最差的一個（約 −13%），
所以讀它的**標籤與族群分布**（`逆勢抗跌`、產業欄），不讀它的 `score` 排序，也不拿它當進場理由。
有正期望證據的進場來源只有 `breakout` 池。

**大局區塊**（`scripts/macro_brief.py`，單跑 `make macro`；資料由 daily 寫進 `market` schema，語意見
[`docs/macro-data.md`](../../../docs/macro-data.md)）：總經序列的 1週／1月／3月變化、距一年高、對 MA60／MA200，
Fed 各場會議的升息／不變／降息機率（Kalshi 買賣價中點），加權均線位階、外資與投信近 5／20 日的買賣超，
未來 14 天的 FOMC 與財報。序列標「⚠過期」或某段印 `**WARN macro_brief`，就當作今天沒有那個數字，**不要用搜尋補**；
財報日一律是 estimated，可能差一天。

**完成條件**：手上有大局五層的數字（總經：10 年／2 年殖利率、美元／台幣、原油、黃金、高收益債；Fed 最近兩場會議的升息機率；
台股：加權對 MA60／MA120 與外資近 5 日；未來 14 天事件），隔夜收盤七項、breadth 三個數字（站上 MA20 比例、漲跌家數、RSI14 中位）、
期交所兩項（外資台指期淨未平倉＋日變化、P/C 未平倉比；不可用就寫不可用）、
待觸發計畫清單、`breakout` 檔數與 screen 報告 §0 的處置／注意股名單狀態、`momentum` 的族群分布。

**凍結與 Fable 臂**：`make morning` **成功（結束碼 0）**時，完整 stdout 會另存 `reports/morning-packs/<日期>.txt`（同日已有則另存 `<日期>.<HHMMSS>.txt`，臂腳本取最早那份；失敗不留 pack）。
跑完立刻在**前景**接著跑（不用背景 agent、不用 `&`：Orca 排程的 session 結束回合會殺背景程序；要帶 `--env-file .env`，`MORNING_FABLE_MODEL` 在那裡）：

```bash
uv run --env-file .env python scripts/morning_fable_arms.py              # 只看過濾後的 pack、寫 journal/morning-arms.jsonl；沒設模型會印「跳過」
uv run --env-file .env python scripts/morning_fable_arms.py --print-hash # 印 Fable 實際輸入（過濾後）的 sha256，Step 4 抄進 input_snapshot_hash
```

跳過或失敗（腳本一律 exit 0，失敗會自己留一列 error）都照常往下，**不重試**。Fable 臂只看**過濾後**的取數段（大局、國際盤、期交所、今日候选）：
「近期判讀校正」「待触发计划」與媒體點名判斷含 journal 判讀，腳本會整段丟掉，所以它不會看到你或歷史的判讀。
你另有 Step 2 的即時補數（夜盤、期貨），**兩臂輸入不完全相同**，配對比較的是「整條流程」而不是單純模型。
`--print-hash` 找不到 pack 時 stdout 為空（說明在 stderr、結束碼非 0）：這時 `input_snapshot_hash` 寫 `null`。

## Step 2：補「現在」

Step 1 給的全是**收盤**。美股期貨與台指期夜盤要的是現在，`overnight.py` 抓不到（yfinance 在台北
早上還沒切到次日場次，拿到的是昨天的期貨），這兩個要人工查：

| 要查 | 來源（實測可用） |
| --- | --- |
| 台指期夜盤收盤（05:00） | [期交所盤後行情](https://www.taifex.com.tw/cht/3/futDailyMarketReport)——官方，有場次時間戳 |
| 美股期貨、VIX、日經／恆生期貨 | [鉅亨國際期指](https://www.cnyes.com/futures/indexftr.aspx) |
| **今天韓國開盤後**（08:00 起）的 SK海力士 | 韓股與台股同時段，`make morning` 只給到它的**前一交易日**收盤。要連續監看走 `scripts/kr_tw_memory_watch.py`（見下） |

法人台指期未平倉與 P/C 已由 `make morning` 的期交所區塊帶出，**不用人工查**；但那是前一交易日日盤的籌碼，
不是夜盤價格，夜盤收盤仍照上表人工查。

要盯整天而不是查一次，用監看腳本——它同時抓韓國三檔與台灣記憶體四檔，算同日價差，只在門檻觸發時推 Bark：

```bash
doppler run -p shioaji -c dev -- uv run --env-file .env python scripts/kr_tw_memory_watch.py
```

**必須在韓股開盤（台北 08:00）前啟動**：yfinance 的韓股日 K 會整根缺、`previousClose` 也會停在前一根
（2026-08-04 實測 `000660.KS` 日 K 停在 07-31、拿 `previousClose` 算會得到 **−8.79%，那是前一日的跌幅**），
只有 `fast_info['lastPrice']` 對 ⇒ baseline 只能在開盤前鎖。開盤後才啟動腳本會直接拒跑。

**開盤預期缺口（主口徑）= 台指期夜盤收盤 ÷ 同合約前一日日盤結算價 − 1**，所有價位照這個比例修正；
journal 寫 `"gap_basis":"tx_settle"`。這是期貨口徑，要換算成現貨缺口得並列期現基差。
「夜盤收盤 ÷ 前一日現貨收盤」不再是主口徑，只當量測欄位（回驗的 `night_spot_gap`）保留；兩種口徑的統計分開算、不混。
夜盤一律指 15:00 開盤、隔日 05:00 收盤的盤後場次。

算完先看 `make morning` 的「近期判讀校正」段（`scripts/verify_morning_calls.py --brief`，讀 18:00 寫的回驗結果）：
它印出過去預估對實際的偏差與縮放比。**只有印出「已有統計支持」才把夜盤公式的原始缺口乘上縮放比**並在 `reason` 註明；
inconclusive 時只當提醒（例如近期偏高估就不要把缺口講滿），`gap_expected` 照公式寫。
比對實際值看 09:05 指數或台指期開盤，**不要看官方開盤**：09:00 那筆把還沒成交的個股以昨收計，天生偏向 0。
**夜盤收盤（05:00）之前的預估不算數**：2026-10-26 21:25 先估開低 −0.5%～−1.5%，當晚美股費半 +2.82%，
實際開高 +0.37%；07:30 用夜盤收盤算的 +0.3% 才對。

### 每個族群配自己的代理

**費半是邏輯／代工／IC 設計的代理，對記憶體無效。** `make morning` 的輸出已按市場分三組
（美股／韓股／連續報價），記憶體那三檔代理與解讀行都在裡面，**不必人工查**。739 交易日實測
（2023-01~2026-07，台灣記憶體籃子＝華邦電／南亞科／旺宏／晶豪科／群聯等權）：

| 台灣記憶體 vs | r |
| --- | --: |
| 韓國記憶體（SK海力士＋三星，**同日**——韓台同時段交易） | **0.577** |
| 隔夜美光 `MU`(t−1) | **0.364** |
| 費半（同日） | **0.123** |

拿錯代理會把族群崩跌讀成「殺盤侷限於族群」。**2026-08-03 犯過**：費半 +0.07% 判無事，
而同一時間美光 −5.90%、SanDisk −5.09%、SK海力士 −8.79%、三星 −8.76%，台灣記憶體卻全數漲停。
完整量測與條件分布見
[`docs/tw-swing-pipeline.md`](../../../docs/tw-swing-pipeline.md) 的「族群代理」節。

每個數字都要 **triangulate**：用「前一日收盤 × (1 + 漲跌幅) = 今日收盤」驗算，對不上就換來源。
這條抓到過三次真錯誤——首頁表格欄位錯位（道瓊點差變成 1.00）、`▼-683` 被讀成「上漲 683」、
兩篇報導數字相同但標了不同日期（用數字自洽性反推，才知道哪一天才對）。
時點同樣要驗：台指期夜盤 15:00 就開，**15:00~21:30 的報價完全不含美股資訊**。

**完成條件**：夜盤收盤（附場次時間）、開盤預期缺口、美股期貨方向、VIX 水位，
**加上今天要判的每個族群各自的代理數字**，每個都經過驗算。

## Step 2.5：大局

regime 是「今天」，大局是「這幾週」。先用一兩句話寫出大局，再判 regime，避免把中期修正當成單日事件：

- **總經週期**：Fed 還在升息、按兵不動還是降息？看最近兩場會議的機率，以及和一週前比的變化。殖利率、原油、美元同向往上＝緊縮，高本益比族群承壓（**未經回測，只寫進 `reason`，不得改動作或部位**）。
- **主線產業**：台股權重最重的那條主線（目前是 AI／半導體）在費半、美光、韓國記憶體上離一年高點多遠、是否跌破 MA200。
- **資金面**：外資近 5／20 日的方向、台幣的方向。兩者同向流出＝外資撤離，不是個股問題。
- **技術位階**：加權在 MA60／MA120／MA240 的哪一邊、距一年高點多遠。
- **本週事件**：FOMC、巨頭財報落在哪一天（台北時間要加一天）。事件前一兩天的開盤缺口，不能當成趨勢。
- **隔夜已公布／今日待公布**（`make morning` 大局段的兩欄）：「隔夜已公布」是前一台股場次 13:30 之後已出的經濟數據（CPI、非農＋失業率、零售、PCE、初領），印**首發**實際值、前值、vintage；週一早上會看到上週五晚上的 NFP。**一律標「無共識」：沒有當時點共識，不能寫「高於／低於預期」，也不要自己去找共識補上**；只講方向與幅度（例：前值到首發值的變化），並承認這個數字的反應多半已在夜盤裡，不要把它當成今天還拿得到的報酬。看到「首發值尚未入庫」就說資料還沒到，不要拿 FRED 的現值頂替。「今日待公布」是到次一場次 13:30 為止的事件（含央行理監事會、ISM 規則推估日——ISM 日期是推估，可能差一天），「部位暴露」要自己依持倉寫：哪些部位、哪個方向，事件前不新建部位的規則照上面。初領失業金是週頻，儀表日線表不列，只在事件段出現。

大局**不改 regime 的定義門檻**（沒有回測支持），只寫進 `reason`（下面兩條是待驗證的部位規則）：大局偏緊縮時，`buy` 降一級部位；
重大事件前一天不新建部位，除非 `breakout` 的論點與事件無關。
以上兩條降級規則**未經回測，只寫進 `reason`，不得改動作或部位**（待歷史總經回測驗證後才升格）。
`FedWatch／Kalshi` 是**利率結果機率，不是台股上漲機率**：不要把它直接當成 `p_close_up` 之類的輸入。
（2026-10-28 回測 FOMC／CPI／NFP 前一日延後一天進場：突破池 h60 配對 112 個，均值 +1.08pp、P(≥30%) +0.9pp，兩個區間都跨零、inconclusive，維持只寫 `reason`。見 [`docs/research/2026-10-28-pre-event-delay.md`](../../../docs/research/2026-10-28-pre-event-delay.md)。）

## Step 3：判 regime

四種。用 breadth、VIX 水位、隔夜族群分化三者定位，**不用指數漲跌幅**——同樣的 −2% 可以是輪動也可以是崩盤。

| regime | 辨識 | 今天的動作 |
| --- | --- | --- |
| **順風** | breadth >50% 站上 MA20、VIX <20、隔夜收紅 | `breakout` 池通常有貨 → 交棒 skill `tw-swing-research` 逐檔研究 |
| **rotation 輪動** | 指數小動但族群分化大、breadth 中性（實例 2026-07-28：道瓊 +1.03% 而費半 −4.49%） | 只在受益族群進場、受害族群一律不看；部位降一級 |
| **broad selloff 全面承壓** | breadth <25%、VIX 20~30、隔夜全黑、輪動避風港消失（實例 2026-07-30：連道瓊也 −2.19%） | 不新進；持倉逐檔對 `invalidation` 判定，觸發就處理 |
| **capitulation 宣洩** | 大跌爆量 + 跌停家數暴增 + 破整數關卡後拉回 + VIX >30 | 唯一值得逆勢看的 regime，且要**等確認**（次日不破前低 + 費半止穩），不猜底 |

VIX **看水位不看漲跌**：費半兩日崩 9.6% 而 VIX 只到 20.66，殺盤還侷限在族群；同樣的費半跌幅配
VIX 35，那是系統性 risk-off，兩者的正確動作相反。

`capitulation` 與 `broad selloff` 最容易混——爆量與跌停家數是必要條件，VIX >30 是**充分**條件。
只有爆量沒有 VIX，仍然是 `broad selloff`。

**代理與台股背離時不下注。** 2026-08-03：台灣記憶體全數漲停 +10%，而同日韓國 −8.8%。
r=0.577 的兩個市場走出 19pp 反向，這個形狀（韓跌>5% 同日台漲>5%）在 739 個交易日裡 **0 例**，
放寬到 ±3% 仍 0 例。**無前例 ⇒ 收斂方向不可預測 ⇒ 背離是不進場的理由，不是賭收斂的理由。**
別用條件分布補這個洞：韓國 ≤−7% 後台灣次日均值 −1.35%（n=17、基準 +0.23%）看似有方向，
但三個門檻的 bootstrap CI 全部跨零、下跌比僅 52~57%（基準 50%），判 **inconclusive**。

**標籤紀律**：定義門檻沒過就不要掛那個標籤。2026-08-05 掛了 `tailwind`，收盤流動池 breadth
48.74%、全體 36.85%，都沒過 >50%。門檻沒過時可以降一格（改判 `rotation`），也可以照原判斷
寫、但在 `reason` 明寫「門檻未過」。**不要為了貼標籤去改門檻**：目前沒有樣本支持任何新門檻。
四種以外的自創標籤（例如 `relief_bounce`）同樣不要用，事後沒辦法對定義計分。

期交所的外資淨未平倉與 P/C 只當 `reason` 的佐證，**不是 regime 的判定門檻**——沒有任何回測支持 P/C 或未平倉門檻，
不要用它們改判 regime。

**完成條件**：你能用一句話說出今天是哪個 regime，並指出**哪個數字讓你排除了其他三個**。

## Step 4：動作與留檔

動作恰好一個：**buy / reduce / hold / wait**。每個都要帶一句理由與一個**可觀察的翻轉條件**
（「費半一日內不再跌逾 2% 且加權站回 40,000」是可觀察的；「等情緒好轉」不是）。

- `buy` → 標的只能來自 `breakout` 池，走 skill `tw-swing-research` 完成逐檔研究與 `journal/swing-decisions.jsonl` 留檔
- `reduce` → 逐檔點出是哪一條 `invalidation` 觸發的
- `hold` / `wait` → 寫明在等哪個數字，以及它出現時要做什麼

昨晚媒體點名區塊（Step 1）怎麼用：

- research 列只是線索：要放進 `tw-swing-research` 的候選清單，得同時過該 skill 自己的進場規則（`breakout` 池等），過不了就不進，**不能因為被點名而進場**。
- watch 列預設靜默；只有今天的數據明顯達到它的翻轉條件時，才在 Bark 提一句。
- 持股被判 avoid 的，Bark 固定留一行（名稱、代號、一句理由），不論今天動作是什麼。

### 機率輸出（07:30 凍結，可計分）

每一行另寫三個 0~1 **小數**（不是百分數）的機率，寫下後不改：

- `p_close_up`：收盤高於前一日收盤（**主目標**）
- `p_oc_up`：收盤高於當日官方開盤（**主目標**）
- `p_gap_up`：09:05 加權指數高於前一日收盤（次要）

另寫 `model_version`（枚舉 `claude`／`fable`／`fable_synth`／`equal_weight`；現行流程填 `claude`）與
`skill_version`（本檔的 git blob sha，`git hash-object .claude/skills/tw-morning-call/SKILL.md` 的輸出，原樣複製）與
`input_snapshot_hash`（Step 1 之後 `uv run --env-file .env python scripts/morning_fable_arms.py --print-hash` 的 stdout，原樣複製；stdout 為空就寫 `null`，配對時該天會被排除）。

**機率要先列基準率再調整**，順序固定：外部基準率（例如近一年該目標的上漲頻率，回驗腳本或 DB 查得）→ 初始機率（等於基準率）
→ 上調／下調的證據（每條寫方向與大約幅度）→ 最終機率。把這個流程寫進 `reason`；沒有證據支持就停在基準率附近，
不要為了顯得有觀點而離開基準率。三個機率各自獨立估，不必互相加總。回驗會拿它對四條基準（永遠看漲、昨日方向、S&P 方向、夜盤符號）算 Brier。

追加一行到 `journal/morning-calls.jsonl`（append，**進版控**）：

```json
{"date":"2026-07-30","regime":"broad_selloff","action":"wait",
 "gap_expected":-0.0098,"gap_basis":"tx_settle",
 "p_close_up":0.38,"p_oc_up":0.45,"p_gap_up":0.30,
 "model_version":"claude","skill_version":"<git hash-object 的輸出>","input_snapshot_hash":"<--print-hash 的 stdout，空則 null>","sox_pct":-0.0533,"vix":20.66,"breadth_ma20":0.153,
 "breakout_count":0,"reason":"隔夜全黑且輪動避風港消失，breadth 15.3% 已在超賣但 VIX 未到宣洩",
 "flip_condition":"費半一日內不再跌逾 2% 且加權指數站回 40,000",
 "exclude_from_scoring":false,"decided_at":"2026-07-30T07:10+08:00"}
```

每個交易日 18:00 由 `scripts/verify_morning_calls.py --append` 回驗（`make verify-morning` 手動看），結果寫進
`journal/morning-calls-outcomes.jsonl`，所以欄位都選事後能驗對錯的觀測值：

- `regime`：拿當日收盤的 breadth 與 VIX 對定義驗。
- `foreign_fut_oi`／`foreign_fut_oi_chg`／`pc_oi_ratio`（選填，2026-10-20 起）：**不要手抄或換算**，跑
  `uv run python scripts/taifex_positions.py --json`（`make taifex` 的同一支腳本加 `--json`），把輸出的這三個欄位原樣複製，
  例如 `"foreign_fut_oi":-89748,"foreign_fut_oi_chg":1397,"pc_oi_ratio":0.6617`（`pc_oi_ratio` 已是小數）。
  不可用或沒有日變化時那一欄已是 `null`，原因在輸出的 `reasons`，可抄進 `reason`。語意見 `journal/README.md`。
- `p_close_up`／`p_oc_up`／`p_gap_up`／`model_version`／`skill_version`：回驗算三個目標的實際方向與 Brier，缺這些欄位的舊列跳過該指標；語意見 `journal/README.md`。
- `gap_expected`：回驗同時量官方開盤（`MI_5MINS_HIST`，偏向 0）、09:05 指數（`MI_5MINS_INDEX`）與台指期日盤開盤
  ÷ 前一日結算價，另記 `night_spot_gap`（夜盤 ÷ 前一日現貨收盤）與 `night_tx_chg`（夜盤 ÷ 前一日結算價）；輸入錯誤 `input_err` 依 `gap_basis` 分流（`tx_settle` 對 `night_tx_chg`、舊列對 `night_spot_gap`），縮放比建議只看新口徑組；語意見 `journal/README.md`。

休市日（臨時休市清單／非交易日）那天寫下的判讀不計分，回驗讀取端要排除並印出排除筆數（見 `journal/README.md`；`swing-decisions.jsonl` 已內建）。
可計分樣本不到 20 筆、或偏差區間跨零時，回驗一律印 inconclusive；在那之前**不要聲稱 regime 判讀有經驗證的優勢**。

**每一行都要明寫 `exclude_from_scoring`**（`true` 或 `false`），不能省略：欄位缺席時沒辦法分辨
「可計分」還是「忘了標」，2026-08-04 那筆就是這樣。只要判讀寫進版控之前結果已經出來，就填 `true`，
例如盤中寫、收盤後補寫、跟當天的 outcome 一起 commit。

**commit 節奏**：判讀一寫完就單獨 commit 那一行；事後補上的 `outcome` 一律另開一個 commit。
防竄改保證只來自「預測比結果先進版控」。2026-08-05 那次 commit 一口氣補進 4 筆，5 筆裡最後只有 1 筆可計分。

**完成條件**：一個動作、一句理由、一個可觀察的翻轉條件、`exclude_from_scoring` 已明寫、一行已追加。
最後**現在就**把這一行 commit＋push 到 `develop`（只 add `journal/morning-calls.jsonl`，Fable 臂這次有寫新列時再加 `journal/morning-arms.jsonl`，AGENTS §1）。

## 邊界

- 盤前的 DB 基準日必然是前一交易日（台股 13:30 收盤、法人與融資 T+1 才補齊）。盤中要即時數字走
  Shioaji 看板（見 `docs/realtime-board.md`），不是這條流程。
- **盤中被問「今天怎麼買」時**，即時 breadth 用 `uv run --env-file .env python scripts/intraday_breadth.py`
  （Shioaji 批次 snapshot 自算流動性池的漲跌家數、站上 MA20／MA60、漲停鎖死檔數）。但**盤中值不是
  收盤值**：2026-08-03 盤中 09:50 中位 +3.37%、上漲 445／下跌 100，收盤變成 +0.66%、1229／595，
  衝高回落把訊號整個翻面。盤中留檔要標時點，該筆 `regime` 不可當收盤結論引用，且因為
  「預測與結果同日寫入」必然拿不到防竄改保證，直接標 `exclude_from_scoring`。
- `momentum` 寬掃的月營收預設只用上市（sii）口徑（上櫃已入庫但預設排除，`--include-otc-revenue` 才放回），上櫃 `yoy` 為 null；日均額壓到 1 億會納入中小型股，
  出場流動性要自行評估。
- `market.market_index` 自 2026-07-01 起才有資料：算大盤均線前先數交易日數，不足該均線天數（例如 MA120 要 120 個交易日）就外部查。
- `market.price` 的 `change` 欄位無正負號（台積電 2,280 → 2,200 顯示 `change=80`），算漲跌用
  `close` 相減。`market.institutional` 的單位是**股**，與證交所 T86 逐欄一致
  （`foreign_net` 對外陸資買賣超股數〔不含外資自營商〕、`trust_net` 對投信、`dealer_net` 對自營商；初版與定版的差異見 `docs/market-data-pitfalls.md`），
  可直接讀本 DB，不必為了單位再打官方端點；`TwseFetcher.get_market_stats()` 的漲跌家數也對不上掛牌檔數。
- 這一層判的是**今天動不動**，不判個股出場價位——出場交給持倉管理。
