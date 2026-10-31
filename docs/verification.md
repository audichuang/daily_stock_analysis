# 真實使用者流程驗證

入口是 [verify skill](../.claude/skills/verify/SKILL.md)，[功能地圖](../.claude/skills/verify/features/README.md) 定義使用者入口、操作、前置資料與終態。實跑與單測／fixture 各自回報；一個主要旅程通過不代表該頁全部分支已通過。

## 2026-10-30：iOS 0.1.2 公網入口與頁面／資料審查

基線 `34b7d76c`，三輪審查已收斂。本輪修正預設網址一次性移轉、資料參考時間、空買賣盤、交易日期、K 線實體與量價對齊，以及大字級數值可讀性。證據根目錄為本機 `apps/dsa-ios/QA/public-audit/`；私人快照與報告不入庫，以下只記去敏結論。

| 層級 | 結果與證據（相對證據根目錄） |
| --- | --- |
| Core／App | `core-tests-final.log`：Core 27/27；`final-all-tools/test.log`：App 20/20，均無失敗 |
| 合成 HTTP／原生 UI | `final-all-tools`：iOS 27.0、iPhone 17 Simulator，完整旅程 1/1、202.001 秒、exit 0、xcresult 正常封存。含台美切換、六列密度、研究／自選／資產、空委買、資料參考時間、分享與本機登出；全部 11 個工具入口的 route 斷言通過。工具頁是合成 fixture，只證明路由、登入橋接與匯出，不代表真實網頁功能全部通過 |
| 認證與修法守門 | `security/auth-tests.log`：58 passed。`migration-mutations/results.json` 的 4 個錯誤版本、`orderbook-mutations/results.json` 的 2 個錯誤版本均失敗；`chart-fix/mutation-results.json` 的 8 個錯誤日期／範圍／實體版本均失敗，現行版本在台北與洛杉磯時區通過。涵蓋舊行為與修得過頭的反向案例 |
| 最大輔助字級 | `a11y-current/xxxl` 與 `final-short/xxxl`：指數、資產、帳戶、持股完整金額已實看並以 PNG OCR 核對；最後補驗 `590.03`、`12,345,678`、`無報價` 均完整，逐項捲入可見區。`final-short/xxxl` exit 0、正常 xcresult；不以 AX 的完整字串代替畫面 |
| K 線與量柱 | `final-short/chart`：1M 真繪圖截圖與像素核對，最後 K 線／量柱中心差從 24.5 px 降為 0 px；各 32 根，實體寬 20 px、影線列中位寬 3–4 px。UI test exit 0、正常 xcresult |
| 正式資料唯讀核對 | 獨立 Decimal FIFO 重建與帳本事件 147/147 一致；2026-10-29 官方 2,354 列 OHLC、成交股數、金額、筆數與市場庫一致，代碼聯集無差異；36 個台股 Shioaji 快照價格／OHLC與同日官方一致；42 個快照漲跌額／百分比重算一致。細節留在私有 `data/report.md`，沒有修改正式帳本 |
| 公網入口 | `https://dsa.audichuang.app` 的 Cloudflare Tunnel 已部署，舊私有入口保留。正常 URLSession 取得 200 JSON、無 HTML challenge；受保護 API 未登入與假 cookie 均回 401。設定與操作紀錄 commit 為 `60c6a849`、`1ae4af1d`，詳見 nas-ops 的 `operator/cloudflare/dsa-public-2026-10-29.md` |
| 交付 | `0.1.2 (202610300059)` 已簽章封存，Info.plist 的新舊預設 URL 已核對；IPA 經 `asc` uploaded／committed，Apple 已為 `VALID`／`INTERNAL_ONLY`／`IN_BETA_TESTING`，內部群組「自己」含此版，繁中測試說明已寫入；實體手機安裝仍未在本輪驗證 |

[PR #153](https://github.com/audichuang/daily_stock_analysis/pull/153) 已在 [CI run 40917582436](https://github.com/audichuang/daily_stock_analysis/actions/runs/40917582436) 通過後合入 develop（`5cc6e097`）；4 片 backend-tests、backend-gate、ai-governance 成功，Web／Docker 依改動範圍 skip。封存來源與提交 `3ab595cc` 的 35 個記錄檔案雜湊相符。

資料驗證的限制：34/36 個 Shioaji 快照成交量不同於官方全天量，來源涵蓋尚未釐清，UI只標示「來源成交量（股）」；6 個美股快照僅確認落在當日原始高低範圍，同時點即時價驗證仍為 0。歷史 API 尚未明示還原價／分割調整基準，未逐日核對全歷史；沒有券商對帳單，所以 FIFO 一致不等於券商庫存對帳。策略 `sniper_prices` 的數值欄位仍未由 Swift 解碼，現有樣本未證實文字矛盾，列 Consider 並保持未改；不將 AI 評分當勝率。

使用者公網互動登入仍待完成；未驗證成功登入後實際 Set-Cookie、正式 App→API 同時點數值、實體手機 0.1.2 安裝、VoiceOver、橫向與 iPad。早期補拍 probe 失敗／結果封裝逾時保留於 `a11y-current/xxxl-detail`，不算通過；修後只引用上述 `final-short` 與 `final-all-tools` 成功結果。字級已還原 large，專用 fixture 已停止。

回滾可改用先前有效 TestFlight build，或手動改回私有入口並啟用 Tailscale；沒有帳本 migration。公網路由回滾依 ops 紀錄，只撤回本次 hostname 設定。此次未跑全量 Python 離線測試；完整真實 Web 工具操作與使用者公網登入也未以 fixture 替代。

## 2026-10-29：Daily Stock AI iOS

### 0.1.1：實機回報後的資產幣別與緊湊版面修正

基線 `77b9ff94`。使用者實機截圖顯示CNY合計、重複英文限制碼及巨大股票卡；核對後端 `PORTFOLIO_AGGREGATE_CURRENCY` 確實固定CNY，snapshot端點沒有可切換顯示幣別的query。本次只修改iOS投影與UI，不更動正式帳本、後端或部署設定。

- Core 19/19 通過：原幣分組、真CNY帳戶、負現金、帳戶／全域FX隔離；5個正反mutation攔下舊CNY投影、跨幣混算及錯誤遮蔽。
- App單測17/17、完整UI旅程1/1通過，證據在 `apps/dsa-ios/QA/compact-portfolio/ui-02`，xcresult正常封存。驗到標準字級同屏至少6列、列高64–104pt、兩個TWD帳戶合計1,200,000與USD帳戶12,500正確分開、CNY頂層282,345.67不出現在總覽、成本／中文說明展開、兩種延遲來源提示與Shioaji反向案例。
- 中文限制及報價警告另有正反mutation；指數時間完整換行已看圖核對。第一輪UI測試因父層identifier覆蓋子層而定位失敗，依實際AX修正定位，沒有放寬金額或密度斷言。
- 審查第1輪2項finding經獨立驗證修正，第2輪最後diff無新Act on；後續只補持股金額前的「損益」文案。iOS版本升為0.1.1。

上述是合成多帳戶HTTP與原生Simulator驗收，不是真實帳本對帳；未取得正式帳本憑證，所以不宣稱正式金融數值已重新稽核。最大字級、實體iPhone／iPad仍未逐項驗收。風險是仍依後端的帳戶成本／匯率計算；回滾只需改回前一個TestFlight build，沒有資料遷移。

交付：`0.1.1 (202610292218)` 已由Apple標為 `VALID`／`INTERNAL_ONLY`／`IN_BETA_TESTING`，內部群組「自己」包含新版，本人tester狀態為 `INSTALLED`。[PR #151](https://github.com/audichuang/daily_stock_analysis/pull/151) 已於 [CI run 40889823814](https://github.com/audichuang/daily_stock_analysis/actions/runs/40889823814) 通過後合進develop（`f48a09a4`）。Xcode直傳停在取得上傳指示、Apple記為 `AWAITING_UPLOAD`；停止該次程序後，以相同簽章archive匯出IPA，再經既有 `asc builds upload` 成功送達，未重建帳本或部署後端。

### 0.1.0：首版交付

程式與邊界見 [iOS App](ios-app.md)，操作地圖見 [ios.md](../.claude/skills/verify/features/ios.md)。工作起點與隔離後端基線均為 `79025c3b`；iOS 功能修正收斂於 `6f013930`，之後只調整 XCTest 的原生關閉按鈕定位與封存腳本輸出。

| 層級 | 本輪實跑結果與證據 |
| --- | --- |
| Core | `swift test --package-path apps/dsa-ios/Core`：13/13 通過；Release Package 編譯通過 |
| App 單測 | 14/14 通過，含真 Keychain cookie 安全屬性、錯網址恢復、大小寫市場代碼、時區、空 WebKit origin、同源下載策略；守修法另做正反 mutation |
| 合成 HTTP／原生 UI | `QA/ui-fixture-06`：Xcode 27.1、iOS 27.0、iPhone 17 Simulator；1 條完整旅程通過、exit0、xcresult 正常封存、16 張 PNG。涵蓋登入、台美切換、日K呈現、AI報告／失效條件、404任務恢復、新分析、自選增減、歷史、資產、指定dossier、Web cookie、blob下載分享與本機登出 |
| 真服務 | 主 checkout 的 `.claude/reviews/verification/ios-live-20261029`：Doctor 證實獨立SQLite、排程停用、market兩層唯讀；原生App讀取台股及美股指數／報價、台股日K，並由按鈕發起真 `claude_code_cli` 分析 |
| 真模型與持久化 | task `5266d956f8d541009d43e32a11d72688` completed；API／SQLite均為個股history ID2、2330.TW，同時保存大盤ID1。個股profile回10項依據、4項失效條件；未注入新聞／券商憑證的限制如實顯示 |
| 打包／TestFlight | 準備版 `202610291347` 完成archive／IPA匯出；正式版 `0.1.0 (202610291412)` 改用Komodo入口，成功上傳，Apple回`VALID`／`INTERNAL_ONLY`。內部群組「自己」含該build，本人tester狀態`INVITED` |
| 正式連線 | 經使用者確認，沿用Komodo `ingress-ttnas` 的私有Caddy反代；TLS／health200、auth enabled、未登入history401，原Komodo／Artifacts網址仍200。85個容器比對僅Caddy重啟，DSA未變；ops設定commit `857e6ad`、部署紀錄`0b70d7a` |
| GitHub CI | [run 40826974873](https://github.com/audichuang/daily_stock_analysis/actions/runs/40826974873) 成功：4片backend-tests、backend-gate與ai-governance皆綠；Web／Docker依變更範圍skip。[PR #149](https://github.com/audichuang/daily_stock_analysis/pull/149) 已合進develop（`7b47a5bd`） |

本機 `apps/dsa-ios/QA/` 保存建置／測試日誌、xcresult、PNG與真服務核對；因含環境資訊與研究結果不入庫。早期輪次的Xcode結果封裝卡住、未簽Simulator的Keychain錯誤、搜尋及分享關閉定位失敗均保留；只以上述第06次完整通過作最終UI證據。

另以真資料操作1／6個月範圍與日K／收盤線切換。未實測：實體iPhone／iPad、iOS17 runtime、VoiceOver／最大字級、正式HTTPS登入、所有Web進階工具的真後端寫入及TestFlight安裝。拖曳讀值與研究分頁的所有邊界分支未逐項操作；不以既有Web能力或合成頁面推論這些均通過。此次沒有改後端契約，未跑本機全量Python離線套件。

隔離真服務已經由標準Cleanup停止，runtime移除，application-evidence.sqlite3與原始證據保留；fixture的本輪進程已停止。正式環境只做HTTPS與認證邊界檢查，沒有為驗收改動正式帳本。

三輪獨立審查收斂：第1輪6項修正、第2輪2項修正，第3輪最後diff無新Act on；其後封存腳本的shell變數邊界以實際archive／export驗證。回滾範圍為iOS客戶端；不需要資料庫migration。

## 執行方式

使用既有 `.venv`、uv、Node/npm、Web node_modules 與 ego-browser；不自動安裝相依。先依 `ego-browser skill` 建立本次 TaskSpace，整輪只用同一個空間。

```bash
export DSA_VERIFY_RUN="$PWD/.claude/reviews/verification/$(date +%Y%m%d-%H%M%S)"
uv run python .claude/skills/verify/scripts/instance.py launch \
  --run-dir "$DSA_VERIFY_RUN" --space-id "$DSA_VERIFY_SPACE" \
  --online --symbols 2330.TW,2317.TW
uv run python .claude/skills/verify/scripts/instance.py doctor --run-dir "$DSA_VERIFY_RUN"
```

線上 profile 用真實 CLI 登入與唯讀市場資料、獨立 SQLite／設定／cache；不帶 Telegram／Shioaji 憑證。空庫帳戶旅程移除 `--online --symbols`，使用空 HOME、不需模型與市場庫。跨功能透過 `scripts/browser.mjs` 的 `openRun()`、`act()`、安全 `snapshot()`、`capture()`、`api()`、`mark()` 留證；最後才 finish TaskSpace。

單獨空庫回歸可執行 launch 產生的 `drive-portfolio.mjs`，它自行 finish，不可插在跨功能中途。

```bash
ego-browser nodejs < "$DSA_VERIFY_RUN/drive-portfolio.mjs"
uv run python .claude/skills/verify/scripts/instance.py cleanup --run-dir "$DSA_VERIFY_RUN"
```

CLI 用同一隔離環境，先讀入口與參數確認副作用：

```bash
DSA_VERIFY_PYTHON="$(uv run python -c 'import sys; print(sys.executable)')"
uv run python .claude/skills/verify/scripts/instance.py exec --run-dir "$DSA_VERIFY_RUN" \
  --record dossier-cli -- "$DSA_VERIFY_PYTHON" scripts/tw_stock_dossier.py 2330.TW --no-branch --json
```

## 2026-10-28 跨功能實跑

本輪程式基線為 `3470e15e044096c17ec672ea285c1c203129b12a`，前一份技能 PR #145 已合入；產品原始碼未修改。工作樹有既有未追蹤 `codex-his.txt`、`journal/morning-arms.jsonl`，fetch 後沒有 pull／stash／覆蓋它們，另建驗證工作分支。

本機證據根為 `.claude/reviews/verify-live-20261028/`，不進版控。`baseline-run/` 是原技能失敗輪，`live/` 是跨功能真服務，`regression/` 是最後空庫回歸。目錄內有動作起訖、receipt、PNG／語意快照、原始去敏 API、來源 hash、模型與 task/history/session/run ID、SQLite 備份和清理紀錄。

| 功能 | 實際執行與結果 | 主要證據 |
|---|---|---|
| 個股分析 | 真 UI 提交及重新分析 `2330.TW`，兩次 Claude CLI 完成，history 2／3；模型與歷史保存診斷成功，行情／新聞缺漏照原樣顯示 | `analysis-tasks-start.json`、`history-two.json`、`15-first-report.png` |
| 人工大盤複盤 | 關閉通知、手動提交台股複盤，task `7556d270…` 完成，history 4，六段報告與 Markdown；保存的 diagnostics 為 `provider=claude_code_cli, success=true`，通知 skipped | `83-market-review-report.png`、`market-review-generation-proof.json` |
| 歷史與複製 | 30d／90d／all 各兩筆；點「查看報告」切回較早的價格／ID。UI 複製 Markdown 與 API 逐位元組一致（4995 bytes），純文字正常，原剪貼簿已恢復 | `31-history-two.png`、`33-history-old-report.png`、`clipboard-markdown-proof.json` |
| 即時看板 | 全部／自選／持股、刷新、同股合併、10 股持倉、日／月／年真圖；點數為 52／37／484。來源 `fallback`、`is_stale=true`，畫面標延遲；基金卡片也經真持倉驗證 | `11-board-expanded.png`、`chart-points-proof.json`、`24-board-fund-card.png` |
| 四維度／資料中心 | 首頁與看板兩入口、真數字與真 Claude 解讀；資料日 2026-10-27。資料中心點「重新整理」，核對 provider／quality／routing，保留 unknown／unconfigured | `14-dossier-current.png`、`38-home-dossier.png`、`17-data-center.png` |
| 持股帳本 | TWD 帳戶入金 100000、買 10 股 @1000、再買 5 股 @1400、賣 5 股 @1500；原幣現金 90500、持股 10；FIFO 已實現 2500、AVG 5500/3，符合獨立算式 | `ledger-fifo.json`、`ledger-avg.json`、`82-ledger-cost-checked.png` |
| 基金 | 真基金 18480065，1／3／5 年 NAV 為 242／726／1211 點；新增 10 單位、重整、編輯 12 單位、看板整合、確認刪除，API 空列 | `21-fund-holding-saved.png`、`23-fund-edited.png`、`fund-holdings-deleted.json` |
| 告警／訊號 | 告警建立停用→啟用→停用→重整篩選→真行情 dry test 未觸發→刪除，無通知嘗試。真報告訊號 2：篩選、詳情、有用回饋、關閉、重整查 closed | `29-alert-tested.png`、`alerts-deleted.json`、`41-signal-closed-reloaded.png` |
| 設定／生成檢查 | 真 UI 保存 Codex 問股設定及有限預算，重整與 ENV_FILE 一致；保存後仍查得到真 market 基金。AI 模型分類的 JSON 冒煙測試通過 | `settings-agent-persisted.json`、`fund-search-after-settings.json`、`69-generation-smoke-result.png` |
| 問股／對話 | 正常措辭真 Codex 呼叫 1 個工具並回答；追問正確沿用前文。新對話、切回、重整、完整 Markdown 下載成功；保留 8 則訊息 | `58-chat-real-answer.png`、`59-chat-followup.png`、`chat-real-export.md` |
| 用量 | 今日／本月／全部與刷新；兩筆真 Codex 呼叫，共 34610 tokens（33920 prompt、690 completion），UI／API／SQLite 一致。Claude generation 本身沒有被灌入假 token | `65-usage-all.png`、`usage-crosscheck.json` |
| 選股 | UI 啟用、藍籌策略，5217 筆快照→119→3 候選；真來源 em_datacenter，展開、重返頁面恢復與歷史 run 一致。資料源降級及 LLM 排序未配置有明示 | `77-screening-clean-restored.png`、`79-screening-history-selected.png`、`screening-task-second-check.json` |
| 回測 | UI 一日驗證、force，處理／保存兩筆今天真報告，兩筆 `insufficient_data`，重整後仍在；沒有後續交易日，完成數為 0，未宣稱驗到績效 | `54-backtest-result.png`、`backtest-results-correct-filter.json` |
| 登入保護 | UI 設暫時密碼／啟用→登出→保護頁 redirect→錯密碼拒絕→正確登入返回→重整 Session／保護 API 成功；最後登出 | `72-auth-protected-redirect.png`、`73-auth-wrong-password.png`、`80-auth-clean-session.png`、`auth-final-logged-out.json` |
| CLI／每日作業安全段 | dossier CLI、`verify_morning_calls.py --brief`、`market_data.cli health --strict` 真跑且 exit 0；`make -n morning` 的 journal／pack／Git refs 前後相同 | `dossier-cli.json`、`local-market-health.json`、`morning-dry-run-boundary.json` |

空庫舊旅程也用新 helper 再實跑一次：建 CNY 帳戶、入金 12345、切流水、重整、API／SQLite 核對通過。前一輪只有此旅程的證據在 `.claude/reviews/verification/20261028-verify-03/`，不能推論當時其他功能已驗證。

## 兩個已確認產品問題

1. **問股把「報告 ID」當第二個美股代號。** 兩個包含明確 `2330.TW` 的真 UI 問句都提前澄清、未跑模型。真函式 `extract_stock_code_spans` 得到 `2330.TW` 與 `ID`，`decide_chat_object` 因多標的回 clarify；改用「報告編號」後正常模型路徑通過。來源是 `src/agent/stock_scope.py:238`、`src/agent/chat_object_decision.py`、`src/services/agent_chat_session_service.py:209`。原輸入維持 failed，沒有被改句後的成功覆蓋；純函式隔離重現記在 `chat-id-parser-proof.json`。
2. **選股歷史時間少八小時。** 實際 run 於台北 14:06 建立，API 回 `06:06:39` 無 offset，UI 顯示 06:06。`ScreeningRun.created_at` 使用 UTC-naive 預設（`src/storage.py:81,335`），序列化只 `isoformat()`（:3009），`StockScreeningPage.tsx:84` 直接 `new Date(value)`。實際擷取前端函式在 Asia/Taipei 重現：原字串 06:06，明確 UTC 後 14:06。證據為 `screening-timezone-finding.json`；未推論其他欄位或排序也錯。

本次維護的是驗證資產，以上產品問題保存為失敗案例，產品邏輯仍保持原狀。

## 實跑回饋到技能的修正

- 原 profile 的真分析實測失敗 `LLM API Key 未配置`；新增線上 profile，保留真 HOME／USER／LOGNAME 的既有 CLI 登入。其使用者級快取不在完整檔案沙箱內，不能宣稱全部檔案均隔離。
- dsa 固定本輪 SQLite；market URL 僅在 process environment。SQLAlchemy connect listener 必須 commit 唯讀 SET，另以 PGOPTIONS 涵蓋直接 psycopg；兩路真連線均 SHOW on。空 source `.env` 阻止裸 dotenv 向上回填。
- UI 保存設定會 override 重載，所以線上 env 檔不能出現空的 DATABASE_URL 鍵。保存後以真基金搜尋再核對市場讀取。Doctor 明標 storage 是啟動快照，不假冒設定保存後的新 SHOW。
- 修正實際 selectors／終態：設定保存按鈕帶異動數量、登入用 submit form、資料中心「重新整理」、dossier 回 HTML、歷史 tr 只選摘要而「查看報告」才切主內容、海報原生分享兩階段、交易成功會清代碼且買賣 select 需限定 form。
- 同一 TaskSpace 跨功能，最後才 finish；原 portfolio driver 保留單獨 scope。新增共用 browser helper、安全 snapshot、機械回歸案例與九份 map 索引。
- 分析後 server SIGTERM 曾逾時：只對已驗所有權的程序群組升級 KILL。新增私有 CLI registry，沿用 producer 的 open／closed／PGID／flock 格式，處理獨立 CLI session。

## 驗證資產自己的驗證

`check_helpers.py`：6 passed、0 skipped；合成 dotenv 邊界驗 online／offline 環境與去敏，未去敏及過度刪 log 的正反 mutation 都會紅。

`check_browser.mjs`：5 passed、0 skipped；合成 Page SDK 邊界驗正常畫面、密碼遮蔽、密碼管理器提示拒絕且不寫圖文，移除 guard／過度阻擋正常頁兩種 mutation 都會紅。

`process_registry.py`：使用真正 producer 啟動自有測試程序，實測 TERM、拒 TERM 後 KILL、未登記同名程序存活、closed 拒新 spawn；漏殺與誤殺兩種 mutation 都被抓到。所有測試程序已回收。

這些是 helper 測試，與上表真服務／模型／瀏覽器驗收分開計算。本輪未跑本機全量離線套件；前一份 PR #145 的 CI 全綠也不當本輪操作證據。

## 限制與未覆蓋分支

- 分享海報真 UI 顯示「重試」，API 503 `share_image_unavailable`；主機找不到 wkhtmltoimage。未安裝相依，海報成功／原生分享送出保持 blocked，沒有用截圖冒充海報。
- Shioaji 真即時未另登入 NAS 的券商 session；本輪實測的是公開延遲報價。缺新聞／搜尋渠道、跨幣別匯率或同日市場資料的提示原樣保留。
- 今天報告尚未成熟，完整回測報酬與勝率未驗證；只有兩份同股報告，歷史載入更多／分頁沒有樣本覆蓋。
- CSV／貼上匯入及去重、帳戶刪除、所有告警型別／通知送達、其他策略與多 Agent、長對話壓縮、改密碼／設定備份、桌面封裝等條件分支沒有被主要旅程推論為通過，map 保留待驗 recipe。
- 完整 `make morning`／daily-report 會更新 market、推 journal／Git、送訊息，本輪只跑安全段。正式 NAS／Doppler／部署／遷移／排程送達沒有被本機代替驗證。
- 本輪依賴已安裝的 Python 3.12／Node；空機安裝與 Python 3.11 仍需對應環境檢查。

## 證據保全與回滾

Cleanup 後 `live/` 與 `regression/` 的程序、port、runtime 均移除；`application-evidence.sqlite3`、去敏 API／動作／畫面／coverage、解讀 cache 與清理 proof 仍存在。主 run 在 registry 加入前已起，記錄如實為 `registered:false`；最後空庫 run 已使用 registry 並成功封閉。`cleanup-proof.json` 另核對全部備份。

證據收集會遇到第三方錯誤含連線字串，以及密碼管理器的私人 iframe；本輪已去敏本機文字、移除三張不適合保留的擴充套件畫面並重拍乾淨證據。原始對話工具輸出不應分享。新 helper 阻擋已實測的 Save login 提示、遮蔽密碼欄、命令 log 遮 URL／密碼；仍需在保存及分享前核對邊界。原剪貼簿已還原，暫時密碼與原剪貼簿備份隨 runtime 移除。

只需 revert 這次驗證資產 commit 即可回滾，不涉及產品 schema 或正式資料回滾。後續以 `/maintain-verification-skill` 更新 map；缺相依或產品失敗保持獨立狀態，不為了全綠縮短旅程。

## iOS Cloudflare Access（2026-10-31）

基線：本地 HEAD 與 fetch 後的 `origin/develop` 均為 `435bd4dd`；工作分支 `feat/ios-cloudflare-access` 從同一提交開始，不需 rebase。未 push、未打 tag、未上傳 TestFlight、未變更 NAS／後端 session 年限。

- Core：`swift test --package-path apps/dsa-ios/Core`，54 tests、0 failures；還原 mutation 後同樣全綠，完整輸出 `/tmp/dsa-access-mutations/restored.log`。
- 正反 mutation：移除 Header、對所有 origin 帶 Header、漏判 Access 轉址、把一般轉址也判成 Access，四項均 exit 1 且執行完整 4 個 Access 測試；結果 `/tmp/dsa-access-mutations/results.json`，修改均已還原。
- 建置：Debug `build-for-testing` 與 Release simulator build 成功；刻意在 Release 帶 `DSA_ACCESS_UITEST`，執行檔仍沒有憑證／密碼預填及 Debug server override 的 4 個環境變數標記。log：`/tmp/dsa-access-debug-compile.log`、`/tmp/dsa-access-release-final.log`。
- HTTP fixture 契約：缺 Header 302、正確 Header 200 並簽發 cookie、錯誤 Secret 302、僅 cookie 200、工具子資源僅 cookie 200、子資源有 Header 但無 cookie 403；只驗合成伺服器行為，不代替原生或 WebKit 實測。
- UI：首輪 `bash apps/dsa-ios/scripts/test-ui.sh` 的 App unit tests 為 22 tests、0 failures；UI 執行時另一個 `testCapture` 同時操作唯一 DSA 模擬器，截圖顯示其正式服務頁，故主動中止本輪（exit 75），不列為 UI 通過。證據 `/tmp/dsa-ios-ui.t78QUr/`；新增的重啟、WebKit cookie 與原生缺 cookie bootstrap 仍需獨占模擬器重跑。
- 真實 Access 與真機：未驗證，由使用者另以 README 的環境變數入口執行。App 更新保留由同一 Keychain 身分實作，尚未做真機覆蓋安裝。回滾為 revert 本次功能提交，無資料庫異動；不會自動刪除已保存的 Access 憑證。
