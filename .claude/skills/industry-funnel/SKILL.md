---
name: "industry-funnel"
description: "行業漏斗選股：從一個行業/主題篩出候選池，逐層用基本面與價值視角過濾、排序，產出值得深挖的候選清單。當使用者想『在某行業裡找標的』『選股』『篩出值得研究的公司』時調用。方法論移植自 ai-berkshire 的 industry-funnel。"
---

# 行業漏斗選股 (Industry Funnel)

從一個行業/主題出發，**漏斗式逐層收斂**成「值得深挖的候選清單」，是「推薦」支柱的入口。產出的候選交給 `/value-research` 深挖、再用 `value_thesis_to_monitoring.py` 接進監控，形成 推薦→研究→監控 閉環。

## Usage

```text
/industry-funnel <行業或主題> [市場]   # 例：/industry-funnel 半導體 tw   或   /industry-funnel AI算力 us
```

## Instructions

> **前置**：用到 `curl localhost:8000/api/...` 的步驟需先啟動服務（`make serve`，本 fork 走 doppler 注入）；`main.py --debug` 取數步驟是 CLI、不需服務。服務未開時請改用對應 CLI 或先 `make serve`。

### Step 1: 取候選池（先用 AlphaSift，缺再補）

優先用 repo 既有 AlphaSift 選股（外部 optional 套件，未裝會降級）：

```bash
# 列可用策略
curl -s http://localhost:8000/api/v1/alphasift/strategies
# 跑篩選（strategy/market/max_results）
curl -s -X POST http://localhost:8000/api/v1/alphasift/screen \
  -H 'Content-Type: application/json' \
  -d '{"strategy":"dual_low","market":"<市場>","max_results":30}'
```

- AlphaSift 不可用（未裝/未注入）→ 改用 WebSearch + 行業龍頭知識，手動列出該行業 15-30 檔候選（含代碼），並在報告標明「候選來源：人工」。
- 台股優先用本地種子（`scripts/stock_index_seeds/stock_list_tw.csv`）核對代碼正確性。

### Step 2: 粗篩（量化門檻，砍掉明顯不合格）

對候選逐檔取基本面，用硬門檻過濾（缺資料的標「資料不足」另列，不直接淘汰）：

```bash
uv run python main.py --stocks <代碼> --debug   # 取 valuation/growth/earnings
```

粗篩門檻（依行業調整）：市值下限、近年獲利為正、ROE 門檻、負債/現金流不惡化。**海外股 valuation 常為空**，缺的用 WebSearch 補並標來源。

### Step 3: 中篩（價值視角排序）

對通過粗篩的，用簡版價值視角打分排序（不做完整四大師，留給 Step 4 的深挖）：
- 護城河跡象（市占/品牌/轉換成本/規模）
- 成長品質（收入利潤同向、現金流匹配）
- 估值承受力（PE/PB vs 成長，是否已透支）
- 用 `scripts/financial_rigor.py verify-valuation` 對前段候選快速驗算 PE/PB/殖利率，剔除數字兜不攏的。

### Step 4: 細篩 → 候選清單

輸出**漏斗結果**：

1. **漏斗統計**：候選池 N → 粗篩剩 M → 中篩剩 K。
2. **Top 候選表**（按價值分排序）：代碼/名稱/一句話亮點/估值/主要風險/資料完整度。
3. **建議深挖順序**：點名前 3-5 檔值得 `/value-research` 深挖，附理由。
4. **資料限制**：哪些候選因資料層不足只能淺評（誠實標明）。

### Step 5（建議）: 串接深挖

對 Top 候選逐一執行 `/value-research <代碼>`；得出「值得買/觀察」結論後，用 Step 5 of value-research 把論題接進監控。
