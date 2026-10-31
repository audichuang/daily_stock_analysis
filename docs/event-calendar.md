# 事件行事曆

Web 入口 `/calendar`；iOS「工具 → 事件行事曆」為原生月曆、當日清單，個股頁顯示下次財報，來源市場的當日至 7 天內加強提示。美股日期是 **美東 ET 的日曆日期**，不轉成手機時區；台股為台北日期。

## 資料與語意

`GET /api/v1/calendar/events?from=YYYY-MM-DD&to=YYYY-MM-DD`（含首尾，最多相差 366 日）。名單是目前自選設定加啟用帳戶的非零持股，帳本唯讀重播、不取即時報價、不保存快照。可傳 `code` 只取名單內的個股；BRK-B／BRK.B 統一為 BRK.B。不是名單內的代號回空集合。沒有逐使用者帳戶隔離的新語意，沿用現有管理員／共用帳本與自選模式，認證仍走 `/api/v1/*` 中介層。

回傳追加式契約：

- `events[]`：`id/type/code/name/date/status/detail/source_url/timezone/date_kind/updated_at`。`code=null` 為總經／市場一般法定節點。`status` 為 `confirmed`（已確認）或 `estimated`（推估／官方暫定）；`date_kind=statutory_deadline` 必須顯示「法定期限」，不能當發布日。
- `undated[]`：`code/name/detail`，沒有可靠未來日期、尚未更新或財報快取逾 3 天。日期在查詢範圍外但仍有新鮮快取的公司，不誤標未定。
- `cache_updated_at`：查詢範圍內快取的最近更新時間；人工表的查核日另見事件 detail／updated_at。空庫可讀人工表並顯示公司未定。

美股先取 Nasdaq `analyst/{symbol}/earnings-date`，有日期再取 `calendar/earnings?date=`，回應 `asOf` 同日且同代號列出時附盤前／盤後、EPS（若有）。Nasdaq 說明其日期由歷史申報日演算法推導，所以一律標推估；只有 Yahoo `isEarningsDateEstimate=false` 才標已確認，且以該日期為準。Nasdaq 無日期／失敗才用既有 yfinance calendar，永遠標推估。兩者都沒有日期就未定，不以去年日期或季節推算。Nasdaq 明確沒有日期會清掉舊未來日期；兩來源皆故障保留舊快取，但逾 3 天不再當新事件。單一公司失敗不阻斷其他公司、總經或分析。

總經重用本 repo `market_data/macro.py` 的 FOMC、FRED/BEA/Census、ISM 與央行日程抓取／解析；不讀寫 `market` schema。FOMC 人工表覆蓋 2026–2027、查核日 **2026-11-01**，來源 [Fed 官網](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm)（頁面 Last Update 2026-10-28）；2027 遠期場次標推估／官方暫定，不推算超出表的年份。ISM 沿用規則推估。官網日期抓取成功後寫應用庫快取。

## 台股官方查證（2026-11-01）

本次實際 HTTP 查證，不只檢查 200：

| 官方來源 | 實際結果 | 採用方式 |
| --- | --- | --- |
| TWSE `/v1/opendata/t187ap05_L`、TPEx `/openapi/v1/mopsfin_t187ap05_O` | 均 200，出表日期 1151017、資料年月 11509 | 已發生月營收，不能推成未來發布日 |
| TWSE `t187ap31_L`、TPEx `mopsfin_t187ap31_O` | 均 200，自帶日期 1151030／1151031 | 監察人承認資料，沒有未來財報發布日 |
| MOPS 舊站 `https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1` | POST `TYPEK=sii/otc&year=115&month=11&step=1&firstin=1&off=1` 回未來法說（2026-11 實測上市 71、上櫃 22 筆）；沒有出表日期。主站相同 GET 轉錯誤頁仍 200 | 接成 `investor_conference` 事件；法說可能回顧已發布財報，不當成財報日。以「列日期落在查詢月份」與表頭判斷回應有效，失敗保留舊快取 |
| TWSE／TPEx OpenAPI Swagger | 200，未列直接法說會預告 API | 不臆造介接 |

因此台股個股的財報實際發布日維持「未定」，法說會另列日期；公司只在開會前一段時間才申報，所以持股本月查無法說會是常態，不代表沒有財報。名單含台股時另顯示 **市場一般法定節點**，`code=null`、標「法定期限」；不把 ETF 或未分類發行人逐股套用期限。[證交法第36條](https://twse-regulation.twse.com.tw/TW/law/DOC01.aspx?FLCODE=FL007009&FLNO=36)的一般曆年制節點為月營收次月10日、前三季終了45日、年度終了3個月。[特殊適用範圍辦法](https://twse-regulation.twse.com.tw/TW/law/DAT0201.aspx?FLCODE=FL067432)有百億元資本額上市櫃年度75日、第一上市櫃Q2兩個月、2026起保險業及具保險子公司月營收得延至15日等例外；金融業、假日及核准展延亦須依公司規定，不自動算出個股到期日。

## 快取與操作

新表 `calendar_events` 在應用庫（`STORAGE_DATABASE_URL`，未設則 SQLite）保存事件與無日期狀態。`DatabaseManager._ensure_calendar_event_schema` 是可重入追加 migration，建立表並記 `schema_migrations.version=2026-11-01-calendar-events`；不動既有 API 欄位與 `market` 庫。更新財報用公司固定 id 覆寫，改期不留下另一個未來事件；總經按成功取得的類型原子替換。

`CALENDAR_REFRESH_ENABLED=false` 預設停用外部刷新。排程路徑：Mac 每日報告（`scripts/daily_report.sh`）每天跑一次 `scripts/refresh_calendar.py`，寫進與 NAS 共用的應用庫，NAS 不必開排程。開啟且 `SCHEDULE_ENABLED=true`，既有 API runtime 或 `main.py --schedule` 的背景工作每 6 小時更新，啟動時跑一次；不新增部署或排程 infra。只開行事曆／分析不發外部請求。也可手動 `uv run --frozen python scripts/refresh_calendar.py`（會寫設定中的應用庫；正式操作前先確認目標）。本次開發未對正式庫執行。

隔離 smoke 範例（需在隔離 env 內提供 `STOCK_LIST`，不可複製正式秘密）：

```bash
STORAGE_DATABASE_URL='' DATABASE_URL='' ENV_FILE=/tmp/dsa-calendar.env DATABASE_PATH=/tmp/dsa-calendar.sqlite3 \
  uv run --frozen python scripts/refresh_calendar.py
```

分析的傳統與 agent 路徑都讀快取 `next_earnings`，傳入來源、狀態與時區作日期風險證據，提示明定不改評分；沒有改評分器或交易決策後處理。無日期與快取讀取失敗仍可分析。尚未對真實 LLM 作評分一致性量測。

回滾：關閉 `CALENDAR_REFRESH_ENABLED` 並回退此功能 commit；舊版忽略新增表／欄位，保留快取表即可，毋須刪表或動既有資料。

## 本輪已知限制

人工 FOMC 表與官方快取以日期 id 合併；目前查核的兩者一致。若未來同場會議改期，人工表舊日期可能與新日期並列，需要同步人工表；本輪沒有已發生改期證據，未另加狀態或防禦分支。年度人工表亦需持續維護。

README 未改：這是功能模組契約與操作細節，入口已放 Web 側欄、iOS 工具與文件索引；未涉及雙語首頁內容。
