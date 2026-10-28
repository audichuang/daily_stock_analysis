# 功能驗證地圖

先讀上層 `SKILL.md`，按 scope 選全部入口與子功能；全面驗證涵蓋下列九份 map。
map 是 recipe，沒有預設通過項；結果取自本輪 `coverage.jsonl`、原始 action／畫面／API／DB 與清理證據。
`passed` 需達到該子功能終態；`observed` 只是觀察，缺前置記 `blocked`、未執行記 `not-run`、執行未達終態記 `failed`。

| 功能 | 真實入口與地圖 | 關鍵前置／終態 |
|---|---|---|
| 持股帳本 | `/portfolio`：[portfolio.md](portfolio.md) | 空庫帳戶／入金可獨立驗；交易、匯率、曝險、匯入另驗 |
| 分析與歷史 | `/`：[analysis-history.md](analysis-history.md) | 線上真生成、task→history、同股切換、Markdown／海報 |
| 即時看板 | `/board`：[realtime.md](realtime.md) | 真行情 source／日期、範圍／合併、走勢與摘要 |
| 研究資料 | `/data`、四維度抽屜與 CLI：[research-cli.md](research-cli.md) | 線上市場資料、數字／真解讀分開核對、唯讀 guard |
| 每日作業 | Makefile／排程：[daily-ops.md](daily-ops.md) | 更新、journal／Git、通知各自依許可；dry-run 不替代全流程 |
| 設定與認證 | `/settings`、`/login`：[settings-auth.md](settings-auth.md) | 本輪 ENV_FILE、真 CLI smoke、登入／登出／redirect |
| 問股與用量 | `/chat`、`/usage`：[chat-usage.md](chat-usage.md) | 真 Agent backend、追問／歷史／匯出；usage 有無各自取證 |
| 告警與訊號 | `/alerts`、`/decision-signals`：[alerts-signals.md](alerts-signals.md) | 規則 CRUD／dry test、真報告產生訊號、回饋／關閉 |
| 選股、回測、基金 | `/screening`、`/backtest`、`/funds`：[screening-backtest-funds.md](screening-backtest-funds.md) | 真 provider／樣本／NAV；不足窗口與回補限制原樣留證 |

跨功能沿用同一 TaskSpace，先建必要真資料再走相依功能；全部完成才 finish。
`portfolio.mjs` 會自行 finish，僅供單獨空庫 scope，不插入跨功能 run。
設定／認證變更後 Doctor 以 runtime ENV_FILE 核對；正式庫或正式設定不能作可刪種子。
Doctor 的 storage 是啟動快照；保存設定後另以已知基金搜尋的真列核對市場連線。報告分享缺渲染器保留 blocked，截圖不能替代海報匯出。
未被這九份 map 定義的新入口先依 source 補 journey，再驗；桌面端封裝目前另缺專屬 map。
路由來源是 `apps/dsa-web/src/App.tsx`、`api/v1/router.py`；CLI 真入口是 Makefile 與各 script 的 argparse／main。

來源與紀錄：

- 根 `AGENTS.md`、`docs/tw-operating-guide.md`、`docs/daily-report-ops.md` 是操作與邊界真源。
- 各 map 引用對應 UI／API source 與專題文件；變更時同步核對 selectors、契約與副作用。
- 既有 Playwright API fixture 截圖只證明固定 payload 的 UI；正式 provider／LLM／送達需真操作證據。
- 本輪 `RUN_NOTES` 是交接線索，通過紀錄只引用同 run 的 coverage 與 artifacts；長期摘要在 `docs/verification.md`。
- 先前對話「研究持股趨勢與年底停利策略」（thread `01a180d4-5306-7da2-820b-12335e53b66d`）
  要求分清帳本／自選、盤中價／昨收籌碼、來源／日期；只作設計依據，不是本輪測試通過證據。
