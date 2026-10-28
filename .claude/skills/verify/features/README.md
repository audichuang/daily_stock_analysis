# 功能驗證地圖

每次先讀上層 `SKILL.md`，選出改動涉及的**全部入口與子功能**，逐項記錄結果。
下表是 journey 的範圍，並非通過紀錄；本次執行結果以 evidence 目錄的 manifest／報告為準。

| 功能 | Journey | 初始狀態 |
|---|---|---|
| 持股帳本、建帳戶與交易持久化 | [portfolio.md](portfolio.md) | 尚未實測 |
| 個股／大盤分析、任務、歷史與匯出 | [analysis-history.md](analysis-history.md) | 尚未實測 |
| 即時看板、來源時效與範圍 | [realtime.md](realtime.md) | 尚未實測 |
| 四維度分析、資料中心與研究 CLI | [research-cli.md](research-cli.md) | 尚未實測 |
| 盤前、每日報告、journal 與通知 | [daily-ops.md](daily-ops.md) | 尚未實測 |

`passed` 必須有真實操作及對應終態證據；缺資料、憑證或許可記 `blocked`／`unverified`，
實際執行而未達終態記 `failed`。首輪證明其中一項，不能推論其他列已通過。

尚未種完整 journey：`/chat`、`/settings`、`/backtest`、`/screening`、`/login`／認證、
`/funds`、`/alerts`、`/decision-signals`、`/usage`，以及桌面端封裝。
改到這些入口時，先依目前 source 補 journey，再實跑；不能以相鄰頁面代替。
完整 Web 路由來源：`apps/dsa-web/src/App.tsx`；API 路由來源：`api/v1/router.py`。

來源與證據層級：

- 規則與執行邊界：根 `AGENTS.md`、`docs/tw-operating-guide.md`、`docs/daily-report-ops.md`。
- 看板／四維度／資料中心：`docs/realtime-board.md`、`docs/tw-stock-dossier.md`、`docs/data-center-diagnostics.md`。
- 既有 Playwright fixture 視覺證據：`docs/portfolio-risk-exposure-dashboard.md`；它驗證固定 API payload 的 UI，並未證明真實後端或 provider。
- 可取得的先前對話：「研究持股趨勢與年底停利策略」，thread `01a180d4-5306-7da2-820b-12335e53b66d`。
  該次使用 `portfolio-check/snapshot.py`，要求區分帳本／自選、盤中價／昨收籌碼、資料日期與來源；只作 journey 設計依據，並非本次通過證據。
- 本地 `codex-his.txt` 為空；未讀到的歷史不作已查證來源。
