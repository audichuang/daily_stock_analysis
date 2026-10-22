# 台股操作手冊：這套系統該怎麼用、每天怎麼操作

> 本檔是**操作手冊**：回答「每天幾點做什麼、報告怎麼讀、什麼能信、什麼不能信」。契約細節、量測數字與
> 推導過程都有各自的正本，這裡只指過去，不重抄一份：
>
> - 波段流水線四層契約與全部數字：`docs/tw-swing-pipeline.md`
> - 決策日誌欄位：`journal/README.md`
> - 事後對帳與「該改／不該改」：`docs/tw-swing-hindsight-2026-08.md`
> - 每日報告回驗：`docs/daily-report-backtest-2026-07.md`
> - 大盤位階與部署方式：`docs/tw-market-position.md`
> - 交易成本：`docs/tw-trading-costs.md`
> - 資料庫爬取與踩雷：`docs/market-data-pitfalls.md`（改 code 的不變式在 `market_data/AGENTS.md`）
>
> **這不是投資建議。** 以下每一個「有沒有用」的結論都照 repo 自己的證據寫；證據不夠的地方一律寫
> inconclusive，不寫方向。

---

## 0. 先記住三句話

1. **核心部位放 0050（或同類大盤 ETF），一次投入、長期持有、不擇時。** 波段流程到目前為止**沒有**
   證明能贏過它（見 §4）。「0050 當核心、波段當衛星」原本就寫在 2026-08-04／08-05 的盤前判讀裡。
2. **每日 AI 報告不是交易指令。** 它每天重新判一次，沒有持有期；照「買入／賣出」標籤機械執行在回驗裡
   是 −8.38%，同期 0050 是 +3.46%（見 §2）。
3. **波段是研究，不是提款機。** 目前 4 筆決策、0 筆到期。重新開跑的目的是累積 ≥20 筆可回驗的樣本，
   不是已知會賺的方法。

---

## 1. 系統裡有三條線，不要混在一起

| 線 | 誰寫的 | 產出 | 持有期 | 證據狀態 |
| --- | --- | --- | --- | --- |
| **A. 每日 AI 個股報告＋大盤複盤** | 上游原作者 | 個股儀表板（評級、狙擊點位、檢查清單），大盤「明日交易計畫」 | **沒有**；系統內部當成約 3 天的訊號 | 回驗 inconclusive，機械執行輸 0050 |
| **B. 台股波段流程** | 本 fork | `screen_tw` 候選 → `tw-morning-call` 判盤勢 → `tw-swing-research` 判進場 → `journal/` | **固定 60 個交易日** | 組合層風險調整後輸 0050；第 2 層是否加值待驗 |
| **C. 價值研究** | 本 fork | `industry-funnel` → `value-research` → `earnings-review` | 長期，靠論題失效條件 | 沒有量化回驗 |

A 線的投資觀是**趨勢追蹤＋回踩低吸**，規則寫死在 prompt 與程式裡：

- 只做多頭排列 MA5 > MA10 > MA20，空頭排列一律不碰。
- 乖離率 > 5% 嚴禁追高，< 2% 是最佳買點。
- 首選縮量回踩 MA5，其次 MA10；跌破 MA20 觀望或停損。
- 重大利空一票否決；不因單日漲跌在買和賣之間翻轉。

`strategies/` 下有 15 支策略，但在預設設定（`AGENT_SKILLS` 留空、`AGENT_MODE=false`）下**實際只跑
`bull_trend`**。多策略路由與依績效調權的程式碼存在，預設沒有生效。

---

## 2. 每日 AI 報告怎麼讀（A 線）

### 2.1 你說的「每天最後那段提醒」是什麼

| 位置 | 內容 | 正確用法 |
| --- | --- | --- |
| 大盤複盤 §六「明日交易計畫」 | 進攻／均衡／防守、倉位區間、關注與迴避方向、一個失效條件 | 調整**今天要多積極、放幾成**，不是下單指令 |
| 個股報告「作戰計畫」 | 理想買點（MA5 附近）、次優買點（MA10）、停損（破 MA20）、目標位、倉位幾成、6 項檢查清單 | 當**掛單價位**：價格回到那裡、檢查清單仍成立時才買，不是「現在市價買」 |

### 2.2 讀的順序

1. **先看一句話結論與作戰計畫的價位，忽略買賣標籤。** 回驗裡 7 個「買入」訊號的文字結論全是
   「觀望／等回踩」，理想買點都在市價下方；−8.38% 主要來自照標籤執行、而不是照它文字上說的做。
   結構化標籤與文字結論互相矛盾，一致性檢查**還沒實作**。
2. **「空倉者／持倉者」兩句是通用假設，不是針對你的持倉。** 分析器不讀你的實際部位
   （`portfolio_context` 不進 prompt）。你有沒有持股、成本在哪，要自己帶進判斷。
3. **沒有持有期。** 盤後產生的訊號系統預設 `3d`（`decision_signal_service._default_horizon`），
   `expires_at` 用日曆天算。報告不會告訴你「買了抱多久」，那是 B 線的事。
4. **個股報告刻意沒有免責聲明**，只有大盤複盤結尾有「僅供參考」，不要因此以為它比較有把握。
5. **看作戰計畫下方的「💸 成本檢核」那一行**（只有台股報告有，2026-09-28 起）：
   - 它把這組價位扣掉來回成本（手續費、證交稅、滑價，個股約 0.88%）後，算出目標價淨賺幾 %、停損淨賠幾 %、
     淨風報比多少。標「⚠️ 不划算」就代表賺的比賠的少，照這組價位掛單長期是虧的；買入結論也會因此被降為觀望。
   - 標「停損比一天正常波動（ATR14）還近」時，這個停損很可能被日常波動掃掉。這一項只提示、不改結論。
   - 沒出現這一行，代表價位不完整、沒辦法檢核，**不等於通過**。
   - 門檻與手續費折扣可以用 `TRADE_COST_MIN_NET_RR`、`TW_BROKER_FEE_DISCOUNT` 調（見 `.env.example`）。
   - 為什麼要有它：照價位掛單的回測（`docs/daily-report-backtest-2026-07.md` 第二種口徑）含成本 −8.50%，
     其中約 8pp 是成本；不計成本也是 −0.88%。這個檢核只能擋掉成本造成的虧損，**不會讓價位變得有預測力**。
6. **不要天天照新報告搬動停損。** 同一份回測裡，把價位鎖在進場那天、停損放寬到 2 倍 ATR，虧損從 −8.50%
   回到約 0，但仍沒贏 0050，也沒贏「不看報告買點」的對照組。放慢只是少虧，不是變成會賺。
7. **2026-10 起台股 prompt 多了幾段資訊，都不進分數**（位置與用字見 `docs/analysis-context-pack.md`）：
   - 「大盤狀態」與「月營收動能」：只有回測區間排除零的格子會附數字；3～5 日期距下大盤狀態對突破候選全部
     inconclusive，所以報告若因「大盤偏保守」就不給買進，那不是回測支持的理由。依據見 `docs/tw-signal-research-2026-10.md`。
   - 「處置／注意股與事件日曆」（`TW_LIVE_EVENTS_ENABLED`，預設開）：寫「未確認」代表名單證明不了新鮮，**不等於沒有**；
     法說會一律附「未列不代表沒有」。處置股是分盤撮合、流動性差，報告應列為首要風險。
   - 「賣方共識」（`ANALYST_CONSENSUS_ENABLED`，預設關）：目標價系統性偏多，台股沒有驗證過；看 EPS 修正方向就好，
     不要拿隱含上漲當買進理由。年底指數目標（`TW_BROKER_INDEX_TARGETS`）只是人工維護的一行情緒背景。
   - `TW_MA_ALIGNMENT_WEIGHTED`（預設關）把多頭排列改成加分項；開了的報告會標 `prompt_variant=tw-ma-weighted`。
     效果沒有驗證，開的時候同時設 `TW_MA_ALIGNMENT_AB_RATIO=0.5`：依「代號＋台北日期」雜湊，一半台股報告套加權
     （`tw-ma-weighted`）、一半照舊（`tw-ma-control`），同一檔同一天重跑不換組。再用 `scripts/shadow_buy_eval.py --by-variant`
     比這兩組（不要拿實驗前的 `baseline`／`untagged` 當對照），區間跨零就維持關閉。比例設 1（預設）＝全部套用、沒有對照組。

### 2.3 什麼時候跑

- **平日 18:00 自動**：Orca automation「每日台股報告」跑 `make daily-report-detached`（脫離呼叫它的 agent session，
  agent 被收掉也照樣跑完；同一時間只會有一輪）——更新並健檢台股資料 →
  `STOCK_LIST` 自選股分析 + 大盤複盤（`MARKET_REVIEW_REGION`）→ 推 Bark。資料更新、健檢或 LLM 預檢沒過就
  **不出報告**，改推一則「每日報告失敗」；個股一檔都沒成功也推失敗（LLM 失效時 `main.py` 仍以 0 退出、
  照推一份只有模板的複盤，別把那則當成報告）。分析內容由本機已登入的 Claude Code CLI 產生（`GENERATION_BACKEND=claude_code_cli`），不需 API key。非交易日由 `main.py` 自己跳過。手動補跑同一條指令即可。
- `make review-tw`：台股大盤複盤，推 Bark。13:30 收盤後跑；法人與融資 T+1 才補齊，盤後當天的籌碼數字
  不完整。
- `make analyze STOCKS=2330.TW,2317.TW`：個股分析。**這個 target 不經 Doppler**——少了它不報錯，只會沒 Bark、
  台股新聞退回通用搜尋。要推播就手動包兩層（外層 `finmind` 注入 `FINMIND_TOKEN_*`，內層 `shioaji` 的 `BARK_URL`
  映射成 `CUSTOM_WEBHOOK_URLS`）；非交易日加 `--force-run`：

  ```bash
  doppler run -p finmind -c dev -- doppler run -p shioaji -c dev -- \
    bash -c 'CUSTOM_WEBHOOK_URLS="$BARK_URL" uv run python main.py --stocks 2330.TW'
  ```
- 代碼一定要帶 `.TW`／`.TWO`，裸 `2330` 不會進台股語義。
- `.env` 的 `SCHEDULE_ENABLED` 是服務內建排程，與上面的 Orca 排程無關（本機為 `false`，避免同一天跑兩份）。GitHub Actions 的每日任務
  沒有設 `DATABASE_URL`，`MarketDBFetcher` 會退回下一個資料源（yfinance），台股日線可能跟本機不同。

---

## 3. 每天的波段操作（B 線）

### 3.1 盤前 07:00–08:30

1. **`make morning`**：補資料 → `health --strict`（資料不齊就停，不要硬跑）→ 隔夜國際盤 → 期交所籌碼
   （外資台指期淨未平倉、P/C 未平倉比；回應日期不等於預期場次就只印 ⚠ 不印數字）→ 列出已留檔、
   還在等觸發的計畫 → `screen_tw` 產出今日候選（附處置／注意股旗標與事件日曆，來源失敗時標「未經檢查」）。
   隔夜國際盤那步任一序列失敗時表裡該列印「失敗」，`make morning` 照樣往下跑，失敗的數字要自己補查。
2. **手動補腳本抓不到的三個數字**：台指期夜盤 05:00 收盤（期交所區塊只有法人籌碼，沒有夜盤價格）、美股期貨與 VIX、韓股 08:00 開盤後的 SK 海力士。
   做法、驗算規則與不能用的時段見 skill `tw-morning-call` Step 1–2。
3. **跑 skill `tw-morning-call`** 判 regime（順風／輪動／全面承壓／宣洩），動作只能選一個：
   buy／reduce／hold／wait，並附一個可觀察的翻轉條件，寫一行到 `journal/morning-calls.jsonl`。
   - 標籤門檻沒過就不要掛那個標籤；不要自創四種以外的標籤。
   - 每行明寫 `exclude_from_scoring`。
   - **寫完就 commit 那一行**，事後補的 `outcome` 另開一個 commit。
4. **動作是 buy 才進 skill `tw-swing-research`**，標的只能來自 breakout 池。每一檔（包括 pass）各寫一行到
   `journal/swing-decisions.jsonl`，**當天 commit**。
   - `invalidation` 的每一腿都要有查得到的來源，寫入當下不能已經成立；逐腿寫進 `invalidation_legs`。
   - `E[R] = exp_upside × confidence + exp_downside × (1 − confidence)`，是加號；E[R] 為負就 pass。

**候選 0 檔**是常態，不是故障。看漏斗每一層剩幾檔，就知道卡在哪一關；不要為了有貨去放寬門檻
（門檻的來由與「不要重試」的對照組見 `scripts/screen_tw.py` 的 `BREAKOUT` 註解）。

### 3.2 盤中

- 看板：`/board`（永豐 Shioaji）。金鑰沒注入時會**靜默降級**成延遲報價，辨識方式是 `source` 變成
  `fallback`（`docs/realtime-board.md`）。
- 即時 breadth 用 `scripts/intraday_breadth.py`。**盤中值不等於收盤值**：2026-08-03 盤中中位 +3.37%，
  收盤只剩 +0.66%。盤中寫下的判讀一律 `exclude_from_scoring: true`。

### 3.3 持有期間與出場

- 契約是**固定持有到第 60 個交易日收盤**，流程裡沒有賣出決策點。
- 不設固定百分比停損：實測進場價 −10% 停損讓單筆期望值由 +9.8% 降到 +6.3%，先跌後漲的贏家會被砍掉。
- 期間**人工**逐檔對照 `invalidation`。`make morning` 列的「待觸發計畫」會把均線門檻用當日數字重算，
  別照日誌裡寫的舊值判斷。
- 部位規則沒有公式，只有這幾條：5 個空位等權；輪動 regime 降一級；同主題第二檔起降一級；日均額
  < 2 億的標的部位要小到能一次市價出清。

### 3.4 每月

- `make verify-decisions`：回驗已到期的判斷。它看的是 `E[R|enter] − E[R|全收]`、`E[R|pass]`、Brier 與
  5 空位可成交口徑，**不是命中率**；已到期少於 20 筆一律 inconclusive。
- `make shadow-buy`（`scripts/shadow_buy_eval.py`，只對應用庫下 SELECT）：被護欄壓掉的 LLM 原判買進照做的
  1/2/3/5 日淨報酬，對照其他報告與 0050。報告日隔日開盤進場；出場算「第 h 日收盤」與「先碰停損／停利」兩種，
  觸發與損益都在還原價空間比（報告價位乘報告日因子，報告日到出場之間除權息／分割都不誤觸），成本走 `round_trip_return`。看護欄有沒有壓錯要看「僅被護欄降級者」那列
  （raw-buy 另含 LLM 自己給 hold 但分數 ≥ 60 的報告）。已知盲區：LLM 在文字裡自己降級的報告回推不出原分、
  會落進對照組；跨檔同日相關性沒處理，區間偏窄。目前沒有上漲行情樣本，
  結果一律當 inconclusive，不要寫成結論。要比較提示詞版本時，在實驗那一輪設 `PROMPT_VARIANT=<名稱>`，再直接跑
  `uv run --env-file .env python scripts/shadow_buy_eval.py --by-variant`；沒有標籤的舊報告歸 `untagged`，不要拿來當對照組。
- `make measure`／`make portfolio` 只在改過門檻、補過歷史資料時重跑；改變池子（例如放入上櫃）要直接帶旗標跑腳本，見 §5。

---

## 4. 目前的證據狀態（別拿來當賣點）

| 問題 | 答案 | 出處 |
| --- | --- | --- |
| 每日報告的訊號有預測力嗎？ | inconclusive：按訊號日分群重抽後，5／10／20 日 CI 全部跨零 | `docs/daily-report-backtest-2026-07.md` |
| 照報告標籤機械執行？ | −8.38%，同期 0050 +3.46%；但所有類別（含中性）都輸，是股票池本身輸 0050 | 同上 |
| 波段池子本身是正期望值嗎？ | 事件層均值 +9.93%，block bootstrap +3.14%~+16.69%；中位只有 +0.83%，靠右尾 | `docs/tw-swing-pipeline.md` |
| 組合層贏 0050 嗎？ | 沒有：5 空位 Sharpe 1.19 對 1.23，回撤 −45.7% 對 −34.0%；走前選參 0.73 | 同上 |
| 候選的排序有用嗎？ | 沒觀察到：200 次亂序對照落在第 46 百分位 | 同上 |
| 第 2 層事件研究有加值嗎？ | 待驗：4 筆決策、0 筆到期，照現在的速度要約一年才夠樣本 | `docs/tw-swing-hindsight-2026-08.md` |
| 盤前 regime 判讀有加值嗎？ | 待驗：5 筆裡只有 1 筆可計分 | 同上 |
| 大盤偏保守要壓低買進嗎？ | 沒有根據：3～5 日期距，0050 季線、寬度、融資背離對突破候選的差異 CI 全部跨零（2011–2026，3,866 日）；寬度高反而較差、極端超賣是反向訊號 | `docs/tw-signal-research-2026-10.md` |
| 營收轉弱要擋進場或出場嗎？ | 不要：突破候選進場 5～20 日 inconclusive；強勢股大幅降速只在 20 日相對落後 −1.08pp（CI −1.83～−0.35），降速後續抱剩餘報酬仍為正 | 同上 |
| 法人目標價比我們準嗎？ | 不比較準（全部偏多、中位隱含 +34.8%）；EPS 修正方向在台股未驗證，inconclusive | 同上 |
| 現在是相對低點嗎？ | 截至 2026-08 的評估：不是，加權指數距 5 年線落在第 99 百分位；等回撤再進場是最差的部署方式（要用前先重算） | `docs/tw-market-position.md` |

樣本期幾乎是單一段大牛市，優勢集中在少數年份。

---

## 5. 資料面的已知限制

- **上櫃月營收**：2026-09 起爬取端也抓上櫃（`/otc/`），但 `screen_tw` 與三支量測腳本**預設排除上櫃營收**，
  因為 §4 的每個數字都是上市口徑量的。要放進來：
  1. 逐月補上櫃歷史：`uv run --env-file .env python -m market_data.cli revenue --month YYYY-MM`
     （MOPS 密集請求會封 IP，月與月之間要留間隔）。上櫃版面只實測過 2026-08；很舊的月份（上市端約
     2013 年前版面不同）能不能解析**未驗證**，補完先看列數與 `**WARN`。
  2. 帶同一旗標重跑量測，取得新池子的基準。`make measure`／`make portfolio` **不帶旗標**，量的仍是舊池子，
     要直接跑：`uv run --env-file .env python scripts/measure_signal_forward.py --include-otc-revenue`，以及
     `uv run --env-file .env python scripts/portfolio_walkforward.py --include-otc-revenue`。
  3. 之後才讓 `screen_tw --include-otc-revenue` 進日常流程。旗標打開時 JSON 不再給 `measured_base_rate`，
     這是刻意的：舊錨點 20.2% 不適用新池子。
- **`financial_statement` 有資料、沒有讀取端**：價值線（C 線）目前不讀它。要不要接是設計取捨，還沒做。
- **`gap_expected` 要對 TWSE 官方加權指數日資料驗**（`MI_5MINS_HIST`），`market.market_index` 沒有開盤價。
- **資料更新失敗常常是靜默的**：exit code 正常、只印 `**WARN`。判斷有沒有補齊用 `health --strict`，
  流程見 skill `update-market-data`。

---

## 6. 一張表看完每天的動作

| 時段 | 指令／skill | 產出 | 要 commit |
| --- | --- | --- | --- |
| 07:00–08:30 | `make morning` → `tw-morning-call` | 一個動作＋翻轉條件，寫入 `morning-calls.jsonl` | 寫完就 commit |
| 動作是 buy 時 | `tw-swing-research` | 每檔一行，寫入 `swing-decisions.jsonl` | 當天 commit |
| 09:00–13:30 | `/board`、`intraday_breadth.py` | 只看，不改盤前判讀 | — |
| 13:30 之後 | `make review-tw`、需要時 `make analyze` | 大盤複盤、個股儀表板 | — |
| 持有期間 | `make morning` 的「待觸發計畫」 | 人工對照 `invalidation` | outcome 另開 commit |
| 每月 | `make verify-decisions` | 已到期判斷的回驗 | — |
