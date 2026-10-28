# 研究資料、四維度分析與資料中心

## Sub-features

- `/data` 查看 provider、資料品質、路由與刷新。
- 首頁與看板的台股四維度分析：數字版、AI 解讀、資料日與降級提示。
- CLI 取四維度數字資料包、量化候選與唯讀回驗。
- 初始狀態：均尚未實測；不同入口各自留下結果。

## How to get to it (user POV)

導覽列進資料中心 `/data`。台股詳情或看板展開列點「四維度分析」開抽屜；
這個入口只支援 `.TW`／`.TWO`。CLI 的同類數字入口為 `scripts/tw_stock_dossier.py`。
來源：`docs/data-center-diagnostics.md`、`docs/tw-stock-dossier.md`。

## Driving it with ego-browser 與 CLI

1. 依上層 Launch／Doctor，開 `/data`，保存 snapshot；點 snapshot 中的刷新按鈕，
   等載入結束，保存前後畫面及 `GET /api/v1/data/overview` response。
   對照 provider、dataset quality 與 routing 三區；unknown／stale／unconfigured 必須原樣呈現。
2. 從首頁與看板各開一次四維度抽屜。snapshot 確認實際按鈕；保存 click receipt、
   抽屜／sandbox iframe 畫面、數字與各段資料日期。
3. 對照 `GET /api/v1/stocks/{code}/dossier`；抽屜先數字版，再背景 `narrative=true`。
   數字與 narrative 分開記結果；可用 `page.snapshot({scope:"subtree",root:當輪iframeRef})`
   讀 iframe，ref 必須來自本輪 snapshot。不要藉直接改 iframe HTML 假造成功。
4. 改到 CLI 時先閱讀入口 argparse／main 確認副作用，再在上層隔離環境執行：

   ```bash
   uv run python scripts/tw_stock_dossier.py 2330.TW --no-branch --json
   ```

   保存 stdout、stderr、exit code 與實際 DB 資料基準日。此命令需要可讀的 `market` schema；
   空市場庫缺價就記 blocked，不以應用 SQLite 填假行情通過。
5. 候選入口 `make screen` 讀市場資料並寫 `.claude/reviews/screen-tw-latest.json`；
   執行前保留該檔原有狀態，再核對漏斗計數、JSON 與 terminal 相符。零候選本身合法。
   唯讀回驗入口 `make verify-decisions`、`make shadow-buy`（後者寫 reports）；
   只在改到相應研究功能時跑，保存樣本量、區間與輸出路徑。
6. 所有產物收進本輪 evidence；上層 Cleanup 清理後，證據仍須能讀取。

## Gotchas

- 正式 `market` 是唯一無備份資料源；此 journey 僅允許已授權的唯讀存取，更新／回補另走相應流程。
- CLI 的 `--no-branch` 省分點連網；它不證明分點成功或整體離線。前後檔案／網路副作用應如實記錄。
- 四維度 narrative 可能呼叫真實 LLM、寫 `DATABASE_PATH` 同層 `dossier_narratives/` 與用量；
  隔離應用 DB 也要隔離這個快取。純數字成功不等於 AI 解讀成功。
- `narrative` 失敗退回數字版、數字核對警示、來源缺段是不同結果，不能以抽屜開得出來概括通過。
- `docs/data-center-diagnostics.md` 的 Playwright fixture 驗證固定 payload UI，並不證明 live provider 可用。
- 研究數字寫結論前依 `AGENTS.md §1.2` 對抗審查；樣本不足或區間跨零必須標 inconclusive。
