---
name: "value-research"
description: "對單一公司做價值投資式深度研究：彙整基本面、強制用 financial_rigor 驗算估值、套用巴菲特/芒格/段永平/李錄四大師視角，產出有明確結論與買賣紀律的研究報告。當使用者想深挖一檔股票的長期投資價值（而非短線技術面）時調用。"
---

# 價值研究 (Value Research)

對單一公司做**價值投資式深度研究**，方法論移植自 [xbtlin/ai-berkshire](https://github.com/xbtlin/ai-berkshire)（MIT），驗算由本 repo 內 `scripts/financial_rigor.py` 提供。

此 skill 是**互動式深度模式**，與每日自動分析管線並存、互不影響；用 session 強模型（Opus）深挖，刻意避開每日批量管線的資料/編排限制。

## Usage

```text
/value-research <股票代碼>     # 例如 /value-research 2330.TW 或 /value-research AAPL
```

## 鐵則

1. **未經 `scripts/financial_rigor.py` 驗算，不得輸出任何目標價或估值結論。**
2. **關鍵財務數字須雙源**：至少兩個獨立來源（公司財報/交易所 + 第三方），用 `cross-validate` 比對，註明出處與口徑（幣別、單位、TTM/年度）。
3. 本系統資料層對海外股財報較淺（美/港/台/日/韓 valuation 常為空），缺的數字用 WebSearch 補抓並標來源，**不得臆造**。
4. 結論必須**收斂成定論**（值得買 / 觀察 / 不碰），並通過「鏡子測試」：投資論題能用 5 句話講清楚，否則判定為不夠格、不投。

## Instructions

### Step 1: 取基本面（先用本系統，缺再補網路）

優先用 repo 既有取數，避免重造：

```bash
# 印出該股完整 fundamental context（valuation/growth/earnings/institution/capital_flow…）
uv run python main.py --stocks <代碼> --debug
```

- A股(cn)：akshare 通常帶 PE/PB、營收/淨利/ROE/現金流，可直接用。
- **台股(.TW/.TWO)**：valuation 已由 TWSE/TPEx 免金鑰快照補上 **PE/PB/殖利率**（上市+上櫃，ETF 除外），有股價即可反推 EPS≈價/PE、BVPS≈價/PB；growth 區塊也一律附 **月營收 + 月營收 YoY**（`monthly_revenue`/`monthly_revenue_yoy`，台股關鍵即時指標）。淨利/EPS 可由 PE×股數×價反推；完整三表（資產負債/季淨利明細）仍需 WebSearch 補（MOPS 財報），註明來源。
- 美/港/日/韓：yfinance valuation 欄位常為 `None`；缺的（EPS、BVPS、股數、三表）用 WebSearch 補（macrotrends / stockanalysis / 公司財報），**每個數字註明來源**。

### Step 2: 強制驗算（financial_rigor）

對拿到的數字逐項驗算，把工具輸出貼進報告作為審計證據：

```bash
# 市值勾稽（抓出股本過期/幣別不一致）
uv run python scripts/financial_rigor.py verify-market-cap --price <P> --shares <股數> --reported <報告市值> --currency <幣別>

# 估值指標（PE/PB/ROE/FCF殖利率/股息率，精確十進位）
uv run python scripts/financial_rigor.py verify-valuation --price <P> --eps <EPS> --bvps <每股淨值> --fcf-per-share <每股FCF> --dividend <每股股息>

# 多源交叉驗證（>2% 偏差會標紅，須解釋）
uv run python scripts/financial_rigor.py cross-validate --field 营收 --values '{"年报":<A>,"第三方":<B>}' --unit 亿

# 三情境目標價（樂/中/悲 各給年增速與目標PE）
uv run python scripts/financial_rigor.py three-scenario --price <P> --eps <EPS> --shares <股數亿> --growth 0.15 0.08 0.02 --pe 22 18 14

# 財報數列造假快篩（樣本需 ≥50，僅 advisory，不可當硬拒絕）
uv run python scripts/financial_rigor.py benford --values '[...]'
```

### Step 3: 四大師視角（獨立評斷，不求共識）

分別用四個 lens 評斷，**保留分歧**（分歧本身是訊號）：

- **巴菲特**：護城河、長期 ROE/ROIC、可預測性、是否在能力圈、安全邊際。
- **芒格**：商業模式品質、反向思考（什麼會讓它崩）、避免愚蠢、誘因結構。
- **段永平**：商業本質與「本分」、是否便宜好生意、長期持有的安心度。
- **李錄**：行業空間與競爭格局、深度盡調、價值 vs 價格的錯位。

### Step 4: 產出研究報告

固定結構，**結論前置**：

1. **一句話結論 + 評級**（值得買 / 觀察 / 不碰）+ 五句話投資論題（鏡子測試）。
2. **估值驗算結果**（貼 financial_rigor 輸出 + 三情境目標價與當前位置）。
3. **基本面**（成長/品質/現金流/負債，附數據來源與雙源比對）。
4. **四大師視角**（各自結論與分歧點）。
5. **買賣紀律**：買點/加碼點、賣出/論題逆轉條件（thesis-breakers）、倉位上限。
6. **數據來源與限制**（哪些數字是網路補抓、哪些市場資料層撐不起，誠實標明）。

### Step 5: 接回監控（研究 → 監控閉環）

若結論是「值得買」或「觀察」，把結論結構化成論題 JSON，用 `scripts/value_thesis_to_monitoring.py` 一鍵建立 **DecisionSignal**（存 `invalidation` 論題逆轉條件、`watch_conditions`、`target_price`、`stop_loss`、`reason`）+ **價格告警規則**（達標價向上 info、停損/逆轉價向下 warning），接上 repo 既有 DecisionSignal 追蹤與 alert 推播（Bark）：

```bash
# 先 dry-run 看 payload，確認無誤再加 --apply 落庫
echo '{
  "code":"<代碼>","name":"<名稱>","market":"<cn/hk/us/jp/kr/tw>",
  "action":"<buy/watch/avoid/...>","confidence":0.7,"score":72,
  "target_price":<三情境中性目標價>,"stop_loss":<停損/安全邊際下緣>,
  "thesis_breakers":["逆轉條件1","逆轉條件2"],
  "watch_conditions":["觀察項1","觀察項2"],
  "reason":"五句話投資論題"
}' | uv run python scripts/value_thesis_to_monitoring.py --thesis -          # dry-run
# 確認後：在指令尾加 --apply
```

- `action` 對應：值得買→`buy`、觀察→`watch`、不碰→`avoid`。
- 之後財報季用 `/earnings-review <代碼>` 複盤，驗證或推翻論題、更新監控。
- 這是「深度研究 → 監控」閉環的落地接點，全程重用既有結構、不改 schema。
