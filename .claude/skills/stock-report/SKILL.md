---
name: "stock-report"
description: "台股個股四維度分析報告（HTML 網頁，botbook 風格）：基本面 × 合約負債 × 籌碼面 × 估值 × SMC 技術結構，附四維度結論卡與追蹤重點。當使用者要看某檔台股的綜合分析、深度報告、個股網頁報告時使用。"
---

# 台股個股分析報告

```text
/stock-report <代號>               # 例：/stock-report 3324、/stock-report 2330.TW
/stock-report <代號> <YYYY-MM-DD>  # 指定資料基準日
```

Web 首頁的個股詳情有「四維度分析」按鈕，會產生同一份報告，解讀由伺服器上設定的 LLM 自動撰寫。這個 skill 是在本機用 Claude Code 撰寫解讀的版本。

數字全部由程式從本地 `market` schema（另加富邦分點）產出，你只負責寫**解讀 JSON**。撰寫規則與 JSON 格式只有一份，就是 `src/services/tw_stock_report.py` 的 `NARRATIVE_RULES`；Web 版與本 skill 共用，不要另寫一份。資料包各欄位的限制見 `docs/tw-stock-dossier.md`。

## 步驟

1. 取資料包和 prompt（唯讀；分點查詢會連網）：

   ```bash
   S=<scratchpad>
   uv run --frozen --env-file .env python scripts/tw_stock_report.py <代號> [--date D] --dump-data $S/<id>.json
   uv run --frozen python scripts/tw_stock_report.py <代號> --data $S/<id>.json --print-prompt > $S/<id>.prompt.txt
   ```

2. 讀完 `$S/<id>.prompt.txt`（規則加上完整資料包），照規則寫 `$S/<id>.narrative.json`。

3. 渲染：

   ```bash
   uv run --frozen python scripts/tw_stock_report.py <代號> --data $S/<id>.json \
     --narrative $S/<id>.narrative.json -o reports/dossier/<id>_<as_of>.html
   ```

   使用者要分享連結時，再用 Artifact 發布這個 HTML。
