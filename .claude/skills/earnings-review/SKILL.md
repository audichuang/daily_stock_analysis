---
name: "earnings-review"
description: "財報複盤：針對單一持有/觀察的公司，在財報發布後檢查業績是否驗證原投資論題、論題逆轉條件是否被觸發，並更新監控。當使用者想『複盤財報』『看這季財報有沒有變臉』『財報後要不要調整』時調用。方法論移植自 ai-berkshire 的 earnings-review。"
---

# 財報複盤 (Earnings Review)

針對**已有投資論題**的公司，在財報後檢查「業績是否驗證論題、論題逆轉條件是否被觸發」，是「監控」支柱的定期複查。與 `/value-research`（首次建立論題）互補：value-research 立論，earnings-review 驗證/推翻。

## Usage

```text
/earnings-review <股票代碼>     # 例：/earnings-review 2330.TW
```

## Instructions

> **前置**：用到 `curl localhost:8000/api/...` 的步驟需先啟動服務（`make serve`，本 fork 走 doppler 注入）；`main.py --debug` 取數步驟是 CLI、不需服務。服務未開時請改用對應 CLI 或先 `make serve`。

### Step 1: 拉出原論題

先找這檔的現存 DecisionSignal（含 `invalidation` 論題逆轉條件、`watch_conditions`、`target_price`、`reason`）：

```bash
curl -s "http://localhost:8000/api/v1/decision-signals?stock_code=<代碼>&status=active"
```

- 找不到既有論題 → 提示先跑 `/value-research <代碼>` 建立論題，本複盤改為「首次建檔」模式。

### Step 2: 取最新財報並驗算

```bash
uv run python main.py --stocks <代碼> --debug   # 取最新一期 earnings/growth/valuation
```

- 缺財報明細（海外股常見）用 WebSearch 補抓最新一季數字，**雙源、註明出處**。
- 用 `scripts/financial_rigor.py` 驗算：

```bash
uv run python scripts/financial_rigor.py verify-valuation --price <P> --eps <最新EPS> --bvps <BVPS>
uv run python scripts/financial_rigor.py cross-validate --field 营收 --values '{"财报":<A>,"第三方":<B>}' --unit 亿
```

### Step 3: 逐條比對論題

把最新財報 vs 原論題的每一條假設與**逆轉條件**逐項打勾：
- 成長/獲利/現金流/ROE 是否仍符合原論題？
- `invalidation`（論題逆轉條件）有沒有任何一條被觸發？
- `watch_conditions` 的觀察項變化方向？
- 估值（用三情境重算目標價）是否需要調整？

```bash
uv run python scripts/financial_rigor.py three-scenario --price <P> --eps <新EPS> --shares <股數亿> --growth 樂 中 悲 --pe 樂 中 悲
```

### Step 4: 結論與動作

輸出複盤結論，**明確定調**：
1. **論題狀態**：✅ 驗證 / ⚠️ 部分鬆動 / ❌ 逆轉（任一 invalidation 觸發即逆轉）。
2. **業績摘要**：本季關鍵數字 vs 預期/去年同期，附驗算與來源。
3. **目標價/停損調整**：三情境重算後的新目標價、是否上修/下修。
4. **動作建議**：續抱 / 加碼 / 減碼 / 出場，附理由。

### Step 5: 更新監控

依結論更新監控：
- 論題仍成立但價位調整 → 用新的 `target_price`/`stop_loss`/`thesis_breakers` 重跑：

```bash
echo '{"code":"<代碼>","market":"<市場>","action":"<buy/hold/reduce/...>","target_price":<新>,"stop_loss":<新>,"thesis_breakers":[...],"reason":"财报复盘后更新"}' \
  | uv run python scripts/value_thesis_to_monitoring.py --thesis - --apply
```

- 論題逆轉 → 提示把舊 DecisionSignal 標記 `invalidated`（`PATCH /api/v1/decision-signals/<id>/status`，body `{"status":"invalidated"}`），並考慮關閉對應告警規則。
