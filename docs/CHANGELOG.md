# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

> For user-friendly release highlights, see the [GitHub Releases](https://github.com/ZhuLinsen/daily_stock_analysis/releases) page.

## [Unreleased]
- [新功能] 台股 SMC 價位警報（**預設關閉**，`TW_LEVEL_ALERTS_ENABLED=false`）：開啟後，盯盤看板展開列可把最近的支撐／壓力建成 `price_cross` 規則（跌破支撐下緣、站上壓力上緣；同一檔重建前先刪舊規則；一天只推一次），觸發時推 Markdown 訊息（價位、結構、下一個價位、近一日變化）。新增 `POST /api/v1/stocks/{code}/level-alerts`（關閉時只能 `dry_run`），`dossier-summary` 回應追加 `level_alerts_enabled`；`AlertService.create_rule` 可指定 `source`。設計與啟用前檢查清單見 `docs/tw-level-alerts.md`
- [新功能] 盯盤看板（`/board`）新增台股「結構」欄與展開列的四維度摘要：最新 SMC 結構、最近支撐／壓力（距離用即時價計算）、最近一個交易日的變化提示（結構轉向、月營收新公告、外資 5 日與 20 日轉向、千張大戶週變化），並可直接開啟四維度報告；後端新增 `GET /api/v1/stocks/dossier-summary`（批次、不查分點、不呼叫 LLM）。說明見 `docs/realtime-board.md`
- [新功能] 台股個股四維度分析報告：Web 首頁個股詳情新增「四維度分析」按鈕（只限 `.TW`／`.TWO`），開啟抽屜顯示四維度結論卡、月營收、季度三率、分點、法人、估值、SMC 價位階梯與追蹤重點；後端新增 `GET /api/v1/stocks/{code}/dossier`（HTML，`narrative=true` 由設定的 LLM 撰寫解讀，依資料基準日快取在 `data/dossier_narratives/`，失敗時退回只列數字；解讀中核對不到資料包的數字會標示且不快取；資料包各段獨立容錯；LLM 用量另記為「四維度分析」）；本機另有 `scripts/tw_stock_report.py` 與 skill `/stock-report`。資料包實作移到 `src/services/tw_stock_dossier.py`（`scripts/` 改為 CLI 包裝），上櫃股改從股票索引補公司名稱
- [新功能] `make media-picks`（`scripts/tw_media_picks.py`）：每天抓錢線百分百、理財達人秀／兆華艾綸說、鈔錢部署的 YouTube 完整版，丟進當天的 NotebookLM notebook 取得逐字稿並逐集列出點名個股（方向、來賓、理由、題材、價位條件），股名對照股票索引轉代號，附播出當天的均線位置、離 60 日高、月營收 YoY、法人 5 日，追加到 `journal/media-picks.jsonl`；當候選來源用，不是買進訊號
- [新功能] `make media-picks`（`scripts/tw_media_picks.py`）：每天抓 21 個固定 YouTube 頻道的完整版（電視財經節目 9 個、投顧分析師每日解盤 10 個、財報狗與 MoneyDJ，以 `kind` 區分），丟進當天的 NotebookLM notebook 取得逐字稿並逐集列出點名個股（方向、來賓、理由、題材、價位條件），股名對照股票索引轉代號，附播出當天的均線位置、離 60 日高、月營收 YoY、法人 5 日，追加到 `journal/media-picks.jsonl`；當候選來源用，不是買進訊號
- [chore] CI 移除 `desktop-futu-package-macos`：本 fork 只發 NAS 的 Docker 映像、不發桌面版，這支 job 只在替上游驗證，又是 Linux 10 倍計價的 macOS runner；打包需要時手動觸發 `desktop-release.yml`
- [chore] CI 提速：backend-tests 改用 uv 安裝相依（失敗退回 pip）、每個 shard 上傳 junit，新增 `scripts/ci_durations_from_junit.py` 重算過期的 `.github/ci-test-durations.json`（舊表停在 08-09、缺 107 個測試檔，三個 shard 實測 148／296／409 秒嚴重失衡）
- [chore] 改用 develop／main 分流：日常 PR 合進 `develop`（CI 只跑 `develop` 與工作分支），發版時 `develop` fast-forward 進 `main` 再打 `rel-YYYY.MM.DD` tag，`ghcr-main.yml` 改由 `rel-*` tag 觸發建映像；盤前判讀的 journal 與上游同步改對 `develop`；`auto-tag.yml` 停用
- [文件] `docs/INDEX.md` 新增「台股（本 fork）」專區（先讀／流程與資料／研究與對帳／研究紀錄／維運）；新增 `docs/research/` 收錄 2026-10-22 零買進診斷與台灣財經媒體掃描的研究紀錄；`AGENTS.md` 指向台股分析現況總覽
- [文件] 新增 `docs/tw-analysis-overview.md`：台股每日分析的數據來源、護欄順序、開關建議與 2026-10-22 診斷／回測已回答的問題
- [chore] CI 不再監聽 `pull_request`，只由 push 觸發（PR checks 就是工作分支的 push run），同一改動不再跑兩次；GitHub 上的每日分析、network-smoke、stale 排程以 `gh workflow disable` 停用
- [修復] 美股名稱改用 NASDAQ Trader 官方清單（股票索引）的英文名，查無顯示代號；不再用上游寫死的簡體中文名（英伟达、微软）。已存進歷史的舊名在讀取時一併換成官方名，資料庫不改
- [修復] 問股頁、搜尋下拉的市場／比對標籤、首頁重複任務與輸入錯誤提示改走介面語言（繁中／英文不再顯示簡體）；後端回來的股名、策略名、對話內容不翻
- [修復] 盯盤大盤指數條改取永豐指數快照（加權＋櫃買），失敗才退本地官方收盤、最後才用 yfinance；原本收盤後顯示前一日收盤、漲跌 0.00%，櫃買指數也抓不到
- [改進] 首頁搜尋建議用滑鼠點選只填入代碼，按「分析」或 Enter 才送出（鍵盤選取仍直接送出）；選取後下拉不再自己重新打開；「推送通知」記住上次的勾選
- [修復] 首頁個股欄與自選列每 30 秒背景刷新（及切回分頁）時不再整個換成「載入中」再掛回：原本每次閃約 0.4 秒、捲動位置與點擊會落空；手動刷新仍顯示載入中以免點到舊資料
- [新功能] 上櫃（TPEx）三大法人、融資融券、估值入本地庫：與上市共用 `market.institutional`／`margin`／`valuation`，新增 `market` 欄（NULL＝上市、`'tpex'`＝上櫃），`daily` 每晚一起抓，回補用 `market_data.cli backfill institutional_tpex|margin_tpex|valuation_tpex`（法人自 2018-01-15 起）；resume、整日換血與 `health` 稽核都分市場，上櫃缺日只報不擋。個股報告的上櫃三大法人趨勢與融資融券改讀本地歷史，不再印「上櫃無歷史」；選股 momentum 的法人篩選從此不再一律剔除上櫃
- [新功能] 集保股權分散表 `market.holding_dist`：`daily` 抓開放資料最新一週（全市場，只報不擋），`market_data.cli holding-history <代號…>` 從 TDCC 個股查詢頁補近一年
- [新功能] `scripts/tw_stock_dossier.py` 個股四維度資料包（基本面、合約負債、籌碼含券商分點前 15 名與 HHI、估值百分位、SMC 結構），新增 `data_provider/tw_broker_branch.py`（富邦 DJ 分點，按需查詢不入庫）與 `src/services/smc_structure.py`；說明見 `docs/tw-stock-dossier.md`
- [新功能] 新增 `PROMPT_VARIANT`（預設 `baseline`）：提示詞版本標籤，所有護欄跑完後寫進 `dashboard.prompt_variant`（上游已標記的不覆蓋），只是標籤、不改提示詞；`scripts/shadow_buy_eval.py` 新增 `--by-variant` 依版本分表，沒有標籤的舊報告歸 `untagged`、不冒充 baseline
- [改進] 大盤環境護欄與交易成本護欄壓分時，把護欄前的 `raw_score`、`raw_decision_type` 與 `guardrail_reason` 寫進 `dashboard.decision_score_calibration`（已有的原分只補不蓋）；修正多個護欄連續壓分時 `adjusted_score`／`final_action` 停在第一個護欄的值；`shadow_buy_eval` 的原始動作改依序取 `raw_decision_type`→`canonical_decision_type`→`decision_type`
- [新功能] 台股個股 prompt 新增「大盤狀態」（0050 季線與季線斜率、市場寬度20／60）與「月營收動能」（前 3 月平均 YoY 與本月差）資訊區塊，讀本地 `market` schema：只當資訊、不進分數；只有回測 95% CI 排除零的格子附數字，其餘寫「僅供參考，回測未證實」；本地行情停更或營收缺月就不出。純計算在 `src/services/tw_backtest_context.py`，與兩支量測腳本共用
- [新功能] 新增 `TW_MA_ALIGNMENT_WEIGHTED`（預設 `false`，關閉時提示詞一字不改）：只限台股＋中文報告，多頭排列由必要條件改為加權項（空頭排列仍不做多），乖離 `BIAS_THRESHOLD`～2 倍限放量突破＋ATR14 停損、超過 2 倍嚴禁追高，另加 60–69 分短波段買入段；報告標 `prompt_variant=tw-ma-weighted`（有設 `PROMPT_VARIANT` 時為 `<值>+tw-ma-weighted`）供影子評估分組；英文報告與 Agent 模式不生效
- [新功能] 台股個股 prompt 納入處置／注意股與未來 10 個交易日的法說會、除權息（`TW_LIVE_EVENTS_ENABLED`，預設 `true`）：重用 `market_data.risk_flags`／`events` 的官方名單與新鮮度判準，只在分析日 ≥ 預期場次時抓、每個基準日抓一次；用字分「是／否（已查）／未確認」，名單證明不了新鮮就寫未確認；法說會（MOPS）無法自證新鮮，一律附註「未列不代表沒有」；失敗略過不擋分析
- [新功能] 新增 `ANALYST_CONSENSUS_ENABLED`（預設 `false`）：個股 prompt 可選附賣方共識（`data_provider/analyst_consensus.py`，yfinance；台股＋美股），依序列 EPS 修正方向、分歧、評級，目標價只當背景，並固定警語不得據此提高 confidence 或放寬進場；寫進 `fundamental_context.consensus`、不計入 coverage；n<3 標 thin、價格日期過舊或與現價差 >3% 標 stale；Agent 模式不帶這段
- [新功能] 新增 `TW_BROKER_INDEX_TARGETS`（人工維護一行「YYYY-MM-DD 內容」）：台股大盤背景顯示法人年底指數目標，標「情緒/beta 背景，不是選股訊號」；空值或超過 30 天沒更新就不顯示
- [新功能] 新增唯讀研究腳本 `scripts/measure_market_regime.py`（大盤狀態對 3/5/10 日前瞻淨報酬）與 `scripts/measure_revenue_momentum.py`（月營收轉弱訊號對 5/10/20/60 日前瞻淨報酬），輸出到 `reports/`
- [文件] 新增 `docs/tw-signal-research-2026-10.md`：大盤狀態與月營收動能回測、賣方共識調查的結論（3～5 日大盤狀態對突破候選全部 inconclusive、寬度高反而較差、極端超賣是反向訊號、營收降速只在強勢股 20 日相對落後、目標價不比較準）
- [測試] 新增 `test_measure_market_regime.py`、`test_measure_revenue_momentum.py`、`test_tw_backtest_context.py`、`test_tw_ma_weighted_prompt.py`、`test_tw_live_events_prompt.py`、`test_analyst_consensus.py`；`tests/conftest.py` 在 import 時關掉 `TW_LIVE_EVENTS_ENABLED`、`ANALYST_CONSENSUS_ENABLED` 並清空 `TW_BROKER_INDEX_TARGETS`，避免本機 `.env` 讓測試連外
- [新功能] 新增 `CAPITAL_FLOW_NOT_SUPPORTED_DOWNGRADE`（預設 `true`＝維持舊行為，資金流 `not_supported` 照舊把買入降級）；設 `false` 才啟用新路徑：資金流 `not_supported`（市場沒有這種資料源）不再把買入降級為持有觀察，台股的買入改以三大法人（外資＋投信同買→inflow、同賣→outflow、其餘→neutral）推導資金面再走既有結構校準，賣出與一般持有不受影響；美股等非 A 股市場（含 `ENABLE_FUNDAMENTAL_PIPELINE=false`、指數、非 A 股 ETF）只標 `applied=False` 不降級；資金流 `failed`／空資料／N/A，以及 A 股的 `not_supported`（akshare 抓不到也回這個狀態）照舊降級
- [修復] 大盤紅綠燈為 yellow 時不再自動打 `conservative` 風險標籤（10 月 84% 的報告都帶這個標籤，含創新高日）；red 日照常注入 `high_risk`
- [改進] 每日大盤環境護欄只在 `high_risk`、`market_cooling`、`low_position_cap` 標籤或明確倉位上限時軟化買入，摘要單獨出現「謹慎／觀望」不再把買進壓成觀望
- [修復] 每日大盤環境的風險標籤、倉位上限、激進買進詞與否定詞補上繁體，zh-TW 報告不再靜默漏判
- [新功能] 新增 `scripts/shadow_buy_eval.py`（`make shadow-buy`）：唯讀影子評估被護欄壓掉的 LLM 原判買進，照做的 1/2/3/5 日淨報酬對照其他報告與 0050（另列「僅被護欄降級者」），以 code 群聚 bootstrap，區間跨零標 inconclusive；輸出到 `reports/`
- [新功能] 即時盯盤加「全部／自選／持股」切換：持股取自帳本全部帳戶（含美股複委託），跨帳戶合併、以即時價顯示股數與未實現損益；下方另列基金持倉卡（淨值、淨值日、持有報酬）。賣光的持股自動消失，不必改 `STOCK_LIST`
- [chore] CI 移除 `desktop-futu-package-windows`（本 fork 不發 Windows 桌面版）；macOS 打包檢查保留，`scripts/build-backend.ps1` 未刪
- [文档] 根 `AGENTS.md` 分層精簡（31,344 → 約 11,600 bytes），只留每個任務都用得到的硬規則、驗證矩陣與跨領域踩雷；維運流程移到新文件 `docs/daily-report-ops.md`（排程一覽、每日報告逾時／鎖／完成標記）與 `docs/nas-deploy.md`（NAS 發版），單一目錄的規則下放 `src/`、`tests/`、`scripts/` 的 `AGENTS.md`，PR 標題與截圖規則移入 skill `analyze-pr`／`fix-issue`，`make analyze` 的 Doppler 手動包法移到 `docs/tw-operating-guide.md` §2.3；§6／§9 改為 CI 也跑 push 分支、合入前看 `gh run` 綠燈
- [文件] `market_data/AGENTS.md` 精簡為改 code 時的不變式（92 行 → 約 40 行）；踩雷案例與實測數字搬到新的 `docs/market-data-pitfalls.md`，操作指令（`revenue-pit`、`adjust`、模組測試、`make pg-scratch`）併入 skill `update-market-data`
- [修復] `src` 套件載入時預設 `LITELLM_MODE=PRODUCTION`，關掉 LiteLLM import 時對工作目錄 `.env` 的 `load_dotenv()`：臨時腳本 unset 掉的 `STORAGE_DATABASE_URL` 不會再被補回正式應用庫；`.env` 一律由 `setup_env()` 讀，明確設了 `LITELLM_MODE` 的照用
- [chore] CI 除了對 `main` 開 PR，也在 push `main` 與 `feat/`、`fix/`、`chore/`、`docs/`、`refactor/`、`test/` 分支時跑（本 fork 不開 PR，原本阻斷 job 從未執行）
- [chore] 新增 `make pg-scratch`／`make pg-scratch-stop`（`scripts/pg_scratch.sh`）：一鍵起本機臨時 Postgres 並把 `market` schema 升到 Alembic head，新增表時不必碰正式庫就能跑 `market_data/tests`
- [新功能] 支援台灣境內基金：投信投顧公會每日淨值與基本資料入庫（`market.fund_info`／`market.fund_nav`，併入 `market_data.cli daily`，另有 `funds`、`fund-history` 子指令），鉅亨補歷史淨值與前十大持股（非官方，不覆蓋官方值）；新增 `/api/v1/funds`（搜尋、詳情含報酬與一年回撤／波動、淨值歷史、前十大持股、基金持倉增刪改查）與 Web `/funds` 頁；基金持倉存在股票帳本之外的 `portfolio_fund_holdings`，以最新淨值估值、缺淨值時市值為 null，`portfolio-check` 快照併入全資產合併表。說明見 `docs/tw-funds.md`
- [新功能] 台股篩選（`screen_tw`）即時標出處置股／注意股（上市 TWSE、上櫃 TPEx）：候選標籤（⚠處置中／⚠即將處置／⚠注意股）、§5 待查清單與 JSON 的 `risk_flag`／`risk_flag_sources` 都看得到；只標記不剔除，候選池與基準數字不變。名單無法證明新鮮時標「未經檢查」（JSON 為 null）並附人工查詢連結，不當成沒有；只在未帶 `--date` 且基準日＝預期場次時抓，`--no-risk-flags` 可關閉；`python -m market_data.risk_flags <代號>` 可單查一檔（裸代號或帶 `.TW`／`.TWO` 皆可）
- [新功能] `screen_tw` 報告新增「事件日曆」：逐檔列出未來 N 個交易日（`--event-days`，預設 5）的法說會（MOPS）與除權息預告（TWT48U／TPEx），並標月營收法定期限；JSON 逐檔 `events`（命中清單，否則 `null`＝未經檢查）與 `events_checked`（確實查過的類別，例如 `["除權息"]`）、頂層 `event_sources`（含 `proven`；沒抓時為 `[]`）／`event_window`／`revenue_deadlines`（沒抓時為 `null`）；候選標籤欄與 JSON `tags` 加上 `📅法說10/23`／`📅除息10/22` 短標（每種取最早一次，券商論壇不標）。MOPS 表上沒有資料日期、新鮮度無法自證，狀態標「可用（未證明新鮮）」且不算查過，所以沒命中的候選是 `null` 不是 `[]`；四個來源並行抓；來源失敗只標註、不影響篩選，`--no-events` 可關閉；`--no-risk-flags`／`--date` 時只在 §0 寫一行原因，不逐檔列「未經檢查」
- [新功能] `make morning` 新增期交所籌碼區塊（另有 `make taifex`）：外資台指期（大台 TXF）淨未平倉與日變化、臺指選擇權 P/C 未平倉比；回應最新一列日期≠預期場次時不印數字，日變化只在前一列正好是前一交易日時才算，兩個端點各自降級、資料問題不擋 morning 後續步驟。只列數字不給門檻；台指期夜盤價格仍需人工查。`scripts/taifex_positions.py --json` 直接印 journal 欄位（`foreign_fut_oi`／`foreign_fut_oi_chg`／`pc_oi_ratio`，不可用為 null 並附原因）
- [改進] `make morning` 的隔夜國際盤（`overnight.py`）任一序列失敗時不再中止整個流程：失敗照樣在表中標「失敗」，之後的期交所籌碼／待觸發計畫／今日候選繼續跑，失敗的數字需人工補查
- [修復] 上市處置名單在盤前判成不可用：證交所處置 API 的標題只在某些時段附「資訊更新日期」（10-21 07:30 盤前沒有），原規則因此每天早上都拒收、改人工查。現在沒有更新日期時改看旁證（有基準日公布的列，或同輪上市注意名單可用），有更新日期但早於基準日仍拒收
- [修復] 新聞情報寫入前依欄位長度截斷字串：應用庫在 Postgres 上會強制 VARCHAR 長度，社群貼文把整篇內文當標題（超過 300 字）時，同一批新聞會整批回滾、全部沒存到
- [修復] 台股估值快照（BWIBBU_ALL）對沒配息股票留空的殖利率改存 0，與帶日期的 BWIBBU_d 及 2020~2025 歷史一致；本益比空白仍為 NULL
- [測試] `test_tw_institution_report_wiring.py` 補上 TWSE 估值／月營收 mock，不再真的連 TWSE（端點失敗時全量偶發紅）
- [chore] 合併上游 `6cb86d6e`..`7a21cd76`（6 個 commit，上游發版 v3.33.0；實質程式改動只有 #2406 問股把完整註冊名稱視為一個標的，#2395／#2396 已被上游 #2418 revert）；台股／繁體問股抽查不受影響，裁決見 `docs/upstream-sync-2026-10-19.md`
- [修復] 法人、融資與估值回補以價格交易日曆為準，保留補班週六交易日；日曆以外的日期不抓取，price 本身仍只抓平日
- [修復] 個股報價與官方日線同場次時，成交量／額不再縮小，盤前與休市日也適用；量比與提示詞同步採用修正值，新場次仍保留即時量
- [修復] Claude CLI 非零退出改讀 JSON 結構判斷用量上限與權限拒絕，空的 `permission_denials` 不再誤報需批准；錯誤保留脫敏後的限額與重設時間，不重試同一 CLI
- [修復] 法人整日替換前檢查 T86 必要欄位與 NULL 比例，回應降級時保留既有資料並印警告；自動重抓不中止，人工回補仍可修復殘缺日
- [修復] 沒有可用即時報價時，個股提示詞仍採用成功趨勢分析的前復權均線與均線形態，報告顯示價維持原始價格
- [修復] 每日報告步驟逾時時，一併終止該步驟啟動、另開 session 的本機 CLI 與其子行程，再釋放報告鎖
- [修復] 財報未知幣別保留 ISO 代碼，不再套用交易市場幣別；已支援幣別的金額格式維持原樣
- [修復] 台股大盤本地寬度計算失敗時不再連帶丟掉成交額與三大法人；本地資料庫讀取加逾時（寬度計算 5 秒、個股日線 15 秒，逾時改走降級來源）
- [改進] 資料健檢會列出歷史上整天缺資料的日子（附回補指令）與各表只涵蓋上市的覆蓋率，只提示不擋流程：`market_data.health` 新增 `full-history gaps`（法人／融資／估值自各表首日起、price 有而整天沒列的日子，最近 10 筆附 `backfill` 指令）、`coverage vs price`（三張表只收上市，上櫃為設計上的缺）與非交易日復權事件數（約 242 筆屬預期且永久、勿刪列），三者皆不進 `--strict`；同步 `market_data/AGENTS.md` 與 `docs/tw-swing-pipeline.md`（momentum 因子比較含宇宙差異）
- [改進] 融資融券解析改核對表頭順序，官方改欄位會直接報錯而非靜默錯位；「尚未發布／查無資料」（TWSE 短文字回覆）與「疑似被封鎖／改版」的警告訊息分開，三大法人與融資共用
- [修復] 上市除權息公告抓取失敗時每日更新重試一次後直接報錯並推播，不再靜默用舊事件重算還原因子；月營收改為獨立交易，不受連帶回滾
- [修復] 月底漏跑或指數晚發布時，下一輪每日更新會補回上個月的加權指數，健檢不再卡住好幾天
- [改進] 個股提示詞的營收／淨利／營運現金流改用帶單位與幣別的金額格式（負值正確顯示負號，不再印原始浮點數），並標明單季、近四季或近四季推算口徑（財報幣別與交易幣別不同時跟財報走）；同步 `data_provider/AGENTS.md` 取數地圖的台股家數降級鏈與財報口徑說明
- [修復] 台股均線、RSI、MACD、量比等技術指標改用還原後價格與量計算，除權息與分割不再讓訊號連錯好幾週（報告顯示的價格不變）
- [新功能] 台股個股分析加入融資融券餘額與變化（標資料日與單位張）：提示詞新增融資餘額、較 5／20 個場次前的變化（場次不足不印）、融券餘額與券資比，不論當日三大法人是否取得成功都出現；上櫃股票明講沒有本地融資融券資料、不得推論融資動向（資料庫只收錄上市）
- [修復] 台股日線在本地資料庫失效、改用 yfinance 時不再套現金股利還原，減少與資料庫日線混用兩種基準（Yahoo 的收盤價仍含分割調整，備援列並非純未還原，須以 data_source 區分）
- [改進] 台股本益比／淨值比標示資料日期與「近四季」口徑，交易所殖利率一併提供；官方快照凍結或單邊失敗時不再沿用舊值數小時：估值每列帶資料日期（整包最新日期落後超過 10 曆日即拒收）、上市與上櫃分開快取（一邊失敗下次重打、不連坐另一邊）、重抓失敗最多回退舊快取 24 小時；prompt 的 PE 列改為「本益比（近四季，YYYY-MM-DD）」、PB 附日期並新增「殖利率（交易所公告）」列，其他市場不變
- [修復] 每日更新會自動補回近 5 個交易日缺的估值（本益比／淨值比／殖利率），且只收日期相符的官方回應；健檢也開始檢查估值缺日：`daily` 的 `crawl_range` 加入 valuation（BWIBBU_d，原本只靠無日期的 BWIBBU_ALL 快照，某晚沒跑那天就永久缺，09-22、10-12 已缺），`crawl_valuation_day` 比對回應自帶日期與請求日、不符或缺日期欄就拒收並印 `**WARN`（backfill 同受惠）；`health` 新增 `missing valuation dates`（容忍最新一日，其餘缺日 `--strict` 擋）。Rollout 注意：本票若沒在 2026-10-19 那輪 daily 前合入並跑過，10-12 會滑出窗口，需改列手動回補
- [修復] 每日報告改以「同一天且同一交易場次」判斷是否重跑，盤中手動跑不會再擋掉收盤後的正式報告、台股休市日仍會跑美股；個股有失敗時另推一則通知列出代碼
- [改進] 台股大盤複盤恢復漲停／跌停家數（證交所帶日期的官方表）：`twtazu_od` 自 2026-06-05 凍結後家數只剩本地寬度（無漲跌停），market light 的漲跌停維度永久不可用（10-15 有 21 檔跌停卻印成沒有資料）。`TwseFetcher` 在 `twtazu_od` 被拒收時改取 `MI_INDEX?type=MS` 的「漲跌證券數合計」表「股票」欄（`200(4)` 解析為 200 家、漲停 4），回應 `date` 必須等於最新交易日，日期不符或格式不符一律放棄並退回本地寬度；`twtazu_od` 仍可用時不多打請求，凍結時每次複盤多一個 TWSE 請求
- [改進] 台股日線歷史落後已收盤交易日時，分析會標成資料過期並降低信心，不再靜默用舊 K 線（停牌股會長期標過期、臨時休市隔天可能誤標一次；只降信心不擋分析）
- [文件] 台股盤前與波段研究 skill 更正法人單位與指數長度、標明寬掃只涵蓋上市、同業報酬須先還原、基準率待重測：`tw-morning-call` 的 `market.institutional` 單位是股（與 T86 逐欄一致）、`market_index` 自 2026-07-01 起約 74 個交易日（夠算季線、不夠半年線），並註明 momentum 寬掃的法人／融資只涵蓋上市；`tw-swing-research` 的同業報酬查詢須先套 `adjust.load_factors` 前復權、不讀 `price.change`，20.2% 基準率旁標「休市日復權修正後待重測」
- [修復] 盤中分析的「較昨日漲跌」不再拿即時價比前天收盤，與即時漲跌幅一致：DB 最新列是 T-1 時，報價屬於今天（交易日且非開盤前）才把原 today 平移成 yesterday，量比同一基準，即時有漲跌幅時直接用它（實測 3008 10-16 10:53：漲跌幅 -5.67 被算成 -9.45）；開盤前、非交易日與收盤後 DB 已有今天都不平移。台股除權息日的較昨日漲跌改用還原後漲跌幅（非即時路徑不再以未還原收盤相減）
- [新功能] 台股個股分析的提示詞加入最新月營收（金額、年增、月增、累計年增，標明月份與單月口徑）：「財報與股利」表多一列「月營收（YYYY-MM，單月，非年度）」，月增與累計年增可為負；月 YoY 仍不回填通用 `revenue_yoy`；無月營收或非台股不出現此列
- [修復] 台股資料健檢新增「應有場次」檢查：收盤後今天的行情與加權指數都沒入庫時直接擋下報告，不再拿昨天的資料出今天的報告（交易日 17:00 後要求當天、之前要求前一交易日；日曆不可用時跳過；颱風等臨時休市日會被擋）
- [修復] 每日報告任何一步卡住超過 90 分鐘會被終止並推播（含 bash 函式步驟，整個 process group 一併收掉），前一輪卡死時後續排程也會推播而不是默默跳過
- [改進] 選股報告明講三大法人／融資／估值只涵蓋上市（momentum 的法人篩選等同排除上櫃）、印出法人／融資／估值的實際資料日與近 5 日統計實際涵蓋的場次數（與基準日不同才標註），缺值顯示「—」（0 照印，原本上櫃印成 `nan張 nan天`）；參考價表「20日高」實為 60 日高，欄名改正；估值改取基準日以前 7 曆日內最近一個有資料的交易日（原本只認基準日當天，18:00 幾乎必為空），所以 18:00 的高息／低估值標籤會開始觸發，候選清單文字會變
- [修復] 收盤後分析不再用即時快照把官方日成交量覆蓋成較小的數字：DB 已有當日 K 時，`_augment_historical_with_realtime` 與 `_enhance_context` 的量／額改取 max（累計量單調不減；Shioaji 不含零股與盤後定價，實測 3008 官方 4,812,882 股、快照只有 4,441,000 股，少 7.7%）。盤中 DB 為部分 K 時仍會更新成較大的即時量；DB 還沒有今天（追加分支）行為不變
- [修復] 當日三大法人抓不到時，個股報告仍提供本地資料庫的法人歷史趨勢並註明當日取得失敗：台股 institution 區塊在抓取失敗（逾時／熔斷／stage 預算用完／紀錄缺欄／fetcher 初始化失敗）時標 `failed` 並在 `errors` 寫實際原因（原本一律寫「not supported for offshore market」掩蓋網路失敗），prompt 先寫「當日三大法人：取得失敗（原因）；以下僅本地歷史」再附截至 DB 最後一天的趨勢，歷史也沒有時寫「不可用、不得推論籌碼面」；`FUNDAMENTAL_FETCH_TIMEOUT_SECONDS=0` 關閉抓取仍為 `not_supported`；非台股不變；整體 `status` 與推播報告（只渲染 `ok`）不受影響
- [修復] 台股大盤複盤恢復櫃買指數（改用櫃買中心官方資料，日期不符就不採用）：yfinance `^TWOII` 自 7 月中起回 No data，複盤每份都寫「沒有櫃買指數」。`TwseFetcher` 在取上櫃成交額的同一次請求、同一道日期比對中一併產出 `stats['tpex_index']`，複盤在場次日期相符時併入指數表（取代 yfinance 同代碼列）；盤中官方尚未發布，複盤仍只有加權指數並記 WARNING
- [修復] 台股大盤複盤恢復櫃買指數（改用櫃買中心官方資料，日期不符就不採用）：yfinance `^TWOII` 自 7 月中起回 No data，複盤每份都寫「沒有櫃買指數」。`TwseFetcher` 在取上櫃成交額的同一次請求、同一道日期比對中一併產出 `stats['tpex_index']`，複盤在場次日期相符時併入指數表（取代 yfinance 同代碼列）；盤中官方尚未發布，複盤仍只有加權指數（盤中場次比對就整批拒收，只記 `status=session_mismatch`）；場次相符但官方沒有 TPEx 當日列時才記 WARNING `configured TW index TPEX missing`
- [修復] 永豐 Shioaji 即時成交量由「張」換算成「股」：原本 `volume` 直接是張，與日線（股）差 1000 倍，pipeline 覆蓋／追加後量比≈0.001，所有台股被判成縮量、下跌日誤得「縮量回調洗盤」滿分。換算在 `_snap_to_quote` 邊界完成（委買委賣量維持張、成交額不動）。看板「成交量」欄數字會放大 1000 倍（與 yfinance 備援一致）；NAS 需重新部署才生效
- [修復] 波段決策回驗的可成交組合口徑改用判斷時點後的進場日並保留信心排序，進場區間以未還原開盤判定（舊的組合臂結論待重算）：組合臂原本以日誌的 `date` 當訊號日，無視 `decided_at`（2408 在 08-14 09:40 才決定，卻用 08-14 開盤 532 買進，高於區間上界 525；2615、6166 同樣用了高於區間的 07-27 開盤），改成以逐筆路徑的 `entry_date` 前一個交易日當訊號日，`confidence` 排序鍵隨之改用該日（原本訊號日一動就全查成 0）；進場區間比對改用未還原開盤，除權息後不再把沒成交算成成交。進場日不在價格面板內或為面板首日的決策不進組合並印出跳過筆數
- [修復] 上櫃股票的三大法人不再把單日買賣超標成「近 20 日累計」，報告會明講上櫃沒有歷史資料：累計（近 5／20 日）改成窗口內每一場都有值才印，不足 20 場但滿 5 場只印近 5 日；本地歷史停更（最後一天早於上一個交易日）時不算連續買賣超並揭露停在哪天；總計欄缺值但外資／投信／自營商齊全時以三者之和補上
- [修復] 盤中跑台股大盤複盤時，不再把前一天的漲跌家數、成交額與三大法人當成今天的數字（避免虛構背離敘事），並在提示詞明講該場次統計尚未發布：`get_market_stats` 回傳 `trade_date`，複盤端與 `overview.date` 不同日（或缺 `trade_date`）就整批不採用並記 `status=session_mismatch`；三大法人在複盤日為台北今天時標「盤後初版，官方稍後可能修正」。盤中與 13:30 後官方發布前的複盤會沒有家數／法人（NAS 需重新部署）
- [修復] 颱風休市日公告的除權息因子改套到下一個交易日，報酬、均線與回測不再出現假跌幅（歷史回測數字待重測、暫不可比）：復權事件日落在休市日時原本被直接跳過（242 筆、15 個休市日，如 2891 在 2026-07-13 被當成 -4.9%、還原後應為 -1.32%）；現由 `adjust.snap_events_to_sessions` 統一對齊，`load_factors`、`MarketDBFetcher` 的 `pct_chg` 都套用，並新增 `market_repo.front_adjust_multipliers` 供技術指標前復權使用
- [修復] 大盤複盤失敗（含多市場中台股那份沒產出，以及分析流程例外）時每日報告改以失敗結束並推播通知，不再顯示完成；個股報告照常推送，`--serve` 模式維持不變
- [修復] 台股三大法人歷史停在證交所的初版：T86 在 18:00 前後先出初版、之後才修正（投信欄、外幣 ETF 晚到，偶有外資數字變動），而 daily 只要某天已有資料就跳過，所以當晚抓到的初版永遠不會被換掉。2026-09-29～10-16 這 11 個當晚入庫的交易日，每天有 14～52 檔與官方定版不一致（3189 景碩 09-30 外資買賣超方向相反）。`market_data.cli daily` 改成每輪把近期已入庫的法人資料重抓並整日換成定版（不重抓當天；抓不到就保留舊資料、只印 WARN）；整日換血有改動時印 `**REVISED <source> <date>: N rows differ`。歷史資料已回補到與官方逐檔一致
- [新功能] 台股個股新聞改由 FinMind 提供：設定 `FINMIND_TOKEN_1..N` 後，`.TW`/`.TWO` 的新聞搜尋（個股分析、問股、每日報告共用）先查 FinMind `TaiwanStockNews`（以代號查、繁中來源），濾掉 CMoney「股市爆料同學會」貼文與個股概覽頁、標題去重，查不到再退回原本的搜尋；多組 token 輪流使用，遇 402/429 換下一組；未設定時不發請求。`make serve`／`make review-tw`／每日報告外層多疊一層 Doppler `finmind` 專案注入 token
- [修復] 問股（Agent）認不出台股／美股：繁體問法（「怎麼看」「換成」「別看」「哪個好」）先逐字折成簡體再比對謂語；整句只指向單一可解析標的時（「2330.TW 台積電現在價格多少？」「AAPL 最近怎麼樣」）直接以它為本輪對象。原本這類問句落到空範圍，工具全被擋，Agent 回答「只支援 A 股」
- [修復] 問股首輪還沒有對象時不再預設 A 股：系統提示改用不分市場的角色與說明，依使用者給的代碼判斷市場；工具參數範例補上台股代碼
- [新功能] 每日分析可自动纳入持仓：新配置 `ANALYZE_PORTFOLIO_HOLDINGS=true` 时，未指定 `--stocks`/`--portfolio` 的运行会把持仓账本里的持股去重后附加到 `STOCK_LIST` 之后一起分析（默认关闭；持仓由账本流水唯读重播、不依赖持仓页缓存；代码无法判定为账户市场的持仓会跳过并记 warning；读不到账本时退回只分析自选股）
- [改进] 持仓明细显示股票名称：`PortfolioPositionItem` 新增可选字段 `name`（取自本地股票索引，查不到为 `null`），持仓页在代码下方显示名称
- [修复] 持仓页台股不再整列缺价：快照估值的历史收盘原本只查应用库 `stock_daily`（只有被分析过的股票才有），Web 持仓页又固定不拉实时价，没分析过的台股一律显示缺价、无报酬率并从市值汇总排除；`.TW`/`.TWO` 现在同时查 `market.price`，两边取较新的一天（fail-open，查不到退回原结果）
- [修复] 非人民币帐户的汇总不再以 1:1 冒充人民币：快照跨帐户汇总统一换算成 CNY，但「刷新汇率」只抓交易币别→帐户币别，从不抓帐户币别→CNY，台币／美元帐户的汇总因此走 1:1 回退（台币数字标成 CNY、整页标记汇率过期）；刷新现在会一并抓这一对
- [修复] 持仓帐本在 Postgres 应用库上可写入：`portfolio_write_session` 原本写死 SQLite 的 `BEGIN IMMEDIATE`，Postgres 上每一笔交易／现金流水／公司行为的新增与删除都 SyntaxError（含 Web 手动录入与 CSV 导入）；改按方言分派，Postgres 用交易范围的 `pg_advisory_xact_lock` 串行化，卖出可用量校验仍在同一写锁内
- [新功能] 持仓页新增「粘贴持仓导入」：每行「名称或代号 股数 平均成本 [日期]」（新接口 `POST /api/v1/portfolio/imports/text/parse|commit`），台股名称与裸代号按账户市场经股票索引解析（`00631L` 等带尾字母代号、上柜 `.TWO` 均可）；可直接粘贴券商库存表，缺成本的行列出待补、不会以现价入帐
- [chore] 合并上游 `c3349de4`..`6cb86d6e`（3 个 commit：#2403 Modelflare 单 Key 接入、#2407 三语赞助横幅、#2399 引导按钮聚焦 `STOCK_LIST`）；不影响走本机 Claude Code CLI 的生成设定，裁决见 `docs/upstream-sync-2026-10-14.md`
- [修复] 台股自动补全补齐带尾字母的代号与特别股：`fetch_tw_stock_list.py` 原本只收纯数字代号与 CFI `ES`/`CE`，槓桿／反向／债券／主动式 ETF（`00631L`、`00632R`、`00679B`、`00400A`）与特别股（CFI `EP`/`EF`，如 `8349A`）全数漏收；官方页改用 cp950 解码，修正 `宏碁`、`建碁`、`恒耀` 等 14 档名称乱码（原本索引里 `宏碁` 只剩「宏」，按名称搜不到）。台股索引 2124 → 2366 档。Web `normalizeStockCode` 同步把 `00631l.tw` 正规化为 `00631L.TW`；分享图标题不再把 `00631L.TW` 截成 `00631`
- [修复] 每日报告不再被筹码分布卡死：`DataFetcherManager.get_chip_distribution` 对非 A 股（台/美/港/日/韩）直接跳过，所有筹码源（AkShare／Tushare／妙想）均为 A 股专属；AkShare 的 `ak.stock_cyq_em` 改经 `_akshare_call_with_timeout` 有界等待——akshare 内部 `requests.get` 未带 timeout，东方财富握手无响应时会永久阻塞并占住 `AkshareFetcher` 调用锁（2026-10-12 实测卡在 2383.TW）
- [修复] 上游问股对象状态（#2397）在 Postgres 应用库上可运行：`conversation_session_states` 新增 9 栏只有 SQLite 迁移，Postgres 补 `ADD COLUMN IF NOT EXISTS`（否则 `DatabaseManager` 初始化即 `UndefinedColumn`）；用户回合 upsert 改按方言；严格回测的 `json_valid`／`json_extract` 在 Postgres 编译为 `pg_input_is_valid`＋`#>>`；对象状态 CAS 读取加 `FOR UPDATE`，Postgres 并发提交不再双双成功
- [修复] 问股对象辨识认得台股上柜 `.TWO` 与带字母代码（`00631L.TW`、`2887A.TW`）
- [chore] 合并上游 `ce364e45`..`c3349de4`（1 个 commit：#2397 问股服务端保存已确认讨论对象），补 Web zh-TW 文案 5 键；裁决与已知缺口见 `docs/upstream-sync-2026-10-11.md`
- [测试] 测试行程不再连到本机 `.env` 的 `STORAGE_DATABASE_URL`（正式 Postgres 应用库）：`tests/conftest.py` 载入时把它钉成空字串，并让 `create_engine` 拒绝该 URL；此前全量离线测试会把告警、持仓、决策信号等 fixture 写进正式库
- [chore] 合并上游 `be148f39`..`ce364e45`（22 个 commit：ETF 双动量轮动、数据能力中心、妙想数据源、持仓风险看板、自选股下一步、共享排程去重等），补齐 Web zh-TW 文案 58 键与持仓风险看板繁体字典；裁决与已知台股缺口见 `docs/upstream-sync-2026-10-08.md`
- [修复] 合并上游 #2368（`REPORT_LANGUAGE=en` 改用完整英文 prompt）后保住 zh-TW 繁体：英文分支用上游、非英文分支保留繁／简 `L()`；fork 增量的台股区块（三大法人近期趋势、台股交易成本与 ATR14 提示）补英文版，英文 prompt 不再夹中文；`_format_amount` 改为 `(amount, market, report_language)`，币别仍跟着市场走
- [修复] Web 深色主题下盯盘页「大盘指数」点数隐形：Tailwind 颜色 token `base`（= 背景色）与字级 `text-base` 同名，没另外指定文字色的 `text-base` 被解析成「文字色 = 背景色」且不带字级；`base` 改为只登记在 `backgroundColor`，`bg-base` 不变
- [新功能] fork 新增 `.github/workflows/ghcr-main.yml`：push 到 `main`（或手动触发）时构建 `linux/amd64` 镜像推到 GHCR，标签 `git-<sha>` 与 `main`，job summary 印出可固定的 `…:git-<sha>@sha256:<digest>`；`docker/Dockerfile` 补拷 `market_data/*.py`（原本缺失，容器内台股 `market` schema 读取一律 `ModuleNotFoundError`，各调用点多半静默降级而不报错）与 `templates/`（`REPORT_RENDERER_ENABLED=true` 时的 Jinja2 模板）
- [新功能] 新增可选的 `STORAGE_DATABASE_URL`：应用库（分析历史、回测、决策信号、LLM 用量等）可改存 PostgreSQL，供多台机器共用同一份历史；不设定时仍是 `DATABASE_PATH` 的 SQLite。附 `scripts/migrate_storage_to_postgres.py` 把既有 SQLite 搬到指定 schema
- [修复] 应用库在 PostgreSQL 上可建表与写入：会话状态、会话摘要、技能观点样本的 upsert 改按方言分派（原本写死 SQLite 语法）；三个超过 63 字元的 `decision_signals` index 名在 Postgres 上自动截断（SQLite 不变）；`backtest_results.eval_status` 放宽到 24 字元（`insufficient_data` 有 17 字元，SQLite 不检查长度所以一直没发现）
- [修复] 数据库初始化日志不再印出连线 URL 里的密码；`*DATABASE_URL` 设定项在 Web 设定页改判为敏感栏位
- [修复] 本地 CLI 生成后端的子进程环境 allowlist 补上 `USER`／`LOGNAME`：macOS 上 `claude` 靠 `USER` 找 login keychain，缺了会回「Not logged in」并被判成 `login_required`，即使本机已登录，`GENERATION_BACKEND=claude_code_cli` 因此在 macOS 无法使用
- [修复] 台股大盘复盘的「最新交易日」参照改取 OpenAPI／rwd 两版 FMTQIK 中较新的一份：OpenAPI 版盘后常落后（2026-09-29 17:05 仍停在 09-24），旧写法因此把当日新鲜的三大法人、上柜成交额与本地涨跌家数全判过期拒收，成交金额也印成前一交易日
- [新功能] 新增 `make daily-report`（`scripts/daily_report.sh`）：更新并健检台股资料 → 自选股分析 + 大盘复盘 → Bark；资料更新、健检或 LLM 预检失败时不出报告、改推「每日報告失敗」Bark；个股一档都没成功也视为失败（LLM 失效时 `main.py` 仍以 0 退出）。`make daily-report-detached` 以 setsid 脱离呼叫者在背景跑完（Orca 叫起的 agent 结束一轮后 terminal 会被收掉，连同背景子行程一起砍），并以锁避免两轮重叠；本机以 Orca automation 平日 18:00 触发（取代已失效的 15:00 crontab 资料更新）；个股分析改由本机 Claude Code CLI 生成
- [改进] 台股报告新增价位成本检核（`src/trade_cost_guardrail.py`）：以狙击点位扣掉双边手续费、卖出证交税与买卖滑价后的净风报比写入 `dashboard.battle_plan.cost_check`，并在作战计划下方显示一行；低于 `TRADE_COST_MIN_NET_RR`（默认 1.0）时标注「不划算」，买入结论降级为观望（诊断来源 `trade_cost`）。台股 prompt 同步注入来回成本与 ATR14，要求目标价扣成本后仍划算、止损不窄于日常波动。新增 `TRADE_COST_MIN_NET_RR`、`TW_BROKER_FEE_DISCOUNT`；技术分析新增 `atr14_pct` 栏位（additive）
- [chore] 台股交易成本模组真源由 `scripts/tw_trade_costs.py` 移到 `src/utils/tw_trade_costs.py`（原路径保留为转出 shim），让每日报告与研究脚本共用同一组费率
- [文档] `docs/daily-report-backtest-2026-07.md` 新增「照报告价位挂单」回测（2026-07-06 ~ 09-24）与脚本 `scripts/backtest_daily_report_levels.py`：照价位 -8.50%、不计成本 -0.88%、同池持有 +0.42%、0050 +3.62%；停损 89% 落在 ATR14 以内；放慢节奏（锁价位、停损 ≥2×ATR、持有 N 日）最好约 +0.8%，与「不看买点」对照组差距在 ±2pp 内，无一赢 0050（inconclusive）；成本过滤的 in-sample 结果与其限制
- [文档] 新增 `docs/tw-operating-guide.md` 台股操作手册：盘前／盘中／盘后／每月的动作、每日报告的正确读法（买卖标签与文字结论矛盾时以文字与狙击点位为准；`position_advice` 不读实际持仓；没有持有期）、三条线的证据状态；`docs/INDEX.md` 加入口；FAQ 中英文 Q16 的 `--market-only` 改为实际存在的 `--market-review`
- [改进] 月营收爬取加入上柜：`crawl_monthly_revenue` 上市（`/sii/`）＋上柜（`/otc/`）各抓一份彙总报表、逐市场各自写入，一边失败只少那一边；`screen_tw`、`measure_signal_forward`、`portfolio_walkforward`、`backtest_screen` **预设排除上柜营收**以维持既有基准的上市口径，新增 `--include-otc-revenue` 放回（`screen_tw` 放回时 JSON 不再给上市口径的 `measured_base_rate`）；上柜历史需逐月 `cli revenue --month` 补
- [改进] skill `tw-swing-research`：`invalidation` 每一腿要有可查来源、写入当下不得已成立，逐腿写进新栏位 `invalidation_legs`（`invalidation` 文字格式不变，回验仍解析其中的 `MA<n>`）；skill `tw-morning-call`：`gap_expected` 改对 TWSE `MI_5MINS_HIST` 官方开盘指数验（`market.market_index` 没有开盘价）、标签门槛未过不得挂标签、每行明写 `exclude_from_scoring`、判读与 outcome 分开 commit；`journal/README.md` 同步
- [文档] 新增五份模组级 `AGENTS.md`（`data_provider/`、`tests/`、`scripts/`、`api/`、`src/`，各附一行 `@AGENTS.md` 的 `CLAUDE.md`），只写从程式码推断不出的约束与踩雷；根 `AGENTS.md` §10 里只跟单一目录有关的细节下放到对应模组档（27,329 → 23,654 bytes），并修正四处已过时的内容：`tests/test_alphasift_api.py` 已随上游改名为 `tests/test_screening_api.py`、`refresh_us_stock_index.py` 已有 argparse（真正没有的是 `merge_tw_into_index.py` 与会 `TRUNCATE` 的 `migrate_sqlite_to_pg.py`）、经 `ci_gate.sh` 的单测 timeout 是 120 秒而非 300、`test_python_version_compat.py` 借不到 CI 版本时是 skip 不是 fail
- [文档] 修正与执行路径不符的说明：`docs/realtime-board.md`（降级时名称不会变英文；涨跌停价是由昨收自算、contract 值只是退路；美日韩的 `source` 已改标 `yfinance`、台股刻意维持 `fallback`）、`docs/market-support.md`（台股日线优先读本地 DB、实时优先走 Shioaji；月营收 YoY 不回填 `revenue_yoy`）、`market_data/AGENTS.md`（`price.change` 的历史列已回补，且方向不能用 `close - lag(close)` 重算；「面板走 DB」的 smoke 测试在两条 CI 都不会真的断言；DB 测试必须用会 rollback 的 `pg_conn` 并自己种资料）、`apps/dsa-web/AGENTS.md`（同上名称一条，另补时间相关测试用相对日期）、`.github/copilot-instructions.md`（不再写死已停用的模型名）、`data_provider/base.py` 一行与下方程式码相反的注解
- [测试] `DecisionSignalsPage` 的「过期信号续期後刷新 active views」测试改用相对时间：fixture 的 `createdAt` 写死 `2026-06-17`，而时间轴预设只取最近 90 天，自 2026-09-15 起该笔被滤出时间轴、测试必红（与改动无关）；改为与同档其他时间轴测试一致的 `Date.now() - 1 天`。已把整套 vitest 拨到 2026-12-31 / 2027 / 2030 各跑一次，没有其他随日期到期的测试
- [修复] REST 分析入口接受注册指数的带点 alias：`000016.SH` / `SH.000016` 原本 `is_code_like` 判 False（裸数字不符合交易所的**股票**位数规则），掉过闸门後死在无效输入检查变成 400，即使 `parse_analysis_target` 解得出 `sh000016`；改为在 `is_code_like` 之前问一次 parser，**只有 INDEX 才短路**，个股与股票名的既有路径不变
- [修复] 自选股的等价键改为 asset-aware：`000016.SH`（上证50）与同码个股 `000016` 原本都被 `normalize_stock_code` 塌成 `000016`，加了指数後再加同码个股会被静默丢弃、删其中一个会删掉另一个；同时修正 add/remove 用正规化後的值算键（`.SH` 在算键前就被剥掉），改用原始输入，与既有条目的算法对称
- [修复] 台股带尾字母的代码（槓桿 `00631L.TW` / 反向 `00632R.TW` / 债券 ETF `00679B.TWO` / 特别股 `2887A.TW`）现在可加入自选、可取得个股档案、可在对话中被识别：后端 `_STOCK_CODE_RE`、前端 `validation.ts` 与 `chatStockCode.ts` 三处一起放宽为「4~6 位数字 + 至多一个字母」，`normalize_stock_code` 的台股分支委派共用的 `is_suffix_market_symbol`，避免 `00631l.tw` 与 `00631L.TW` 两种写法并存
- [修复] 选股历史的时间显示改用当前介面语系（原本写死 `zh-CN` 且写在函式体内，呼叫端覆写不了；本页另两个日期 helper 早就走 `getIntlLocale(language)`）
- [chore] 移除零呼叫者的 `getPopularStocks` 与其测试（loader 不再全域过滤 index row 之後，它的 stock-only 契约只写在注解里、实作没有兑现）
- [修复] 股票代码校验闸门（`api/v1/endpoints/stocks.py` 的 `_STOCK_CODE_RE`）改为只认 ASCII 数字与字母：Python 的 `\d` 预设 Unicode-aware，而它对齐的前端 `validateStockCode` 用的 JS `\d` 只认 ASCII，全角与阿拉伯-印度数字（`６００５１９`、`００７００.HK`、`٠٠٦٣١.TW`）因此穿过每一条数字分支并被正规化后送进下游 fetcher，抓取失败时 pipeline fail-open 产出静默缺资料的报告而非明确 400
- [修复] 补齐 `apps/dsa-web/src/i18n/uiText.ts` 的 zh-TW 文案键 `watchlist.batchSubmittedWithRejected` 与 `watchlist.batchPartiallySubmittedWithRejected`（上游新增时只加了 zh/en，`Record<UiTextKey, string>` 使前端构建 tsc 失败）
- [文档] 新增 `docs/upstream-sync-2026-09-05.md`（上游 v3.31.0 → 2026-09-04 共 10 个 commit 的合并记录、冲突裁决与验证）
- [文档] 新增 `docs/daily-report-backtest-2026-07.md`：每日分析报告机械化执行的回验（2026-07-06 ~ 09-04），含成本口径、与 0050 的成对比较，以及「结构化 verdict 与同一区块的文字结论互相矛盾」这一发现

- [文档] 三语 README 分别使用 Modelflare 简体中文、英文及繁体中文赞助横幅，保持现有版式与链接。

- [改进] Modelflare 只需 MODELFLARE_KEY，后端、Web、筛选及 Actions 统一自动识别渠道并补齐默认地址与模型，保留显式 YAML／渠道配置优先级和高级渠道 Key 兼容。

- [改进] 单 Modelflare 渠道未填写主模型及渠道模型列表时默认使用 gpt-6.1-sol，只需渠道名与 API Key；三语 README 横幅恢复 720px、图片与文案紧接显示，并在 Modelflare 与 SerpAPI 之间添加分隔线。

- [改进] 单 Modelflare 渠道可直接复用现有 LITELLM_MODEL 与 OpenAI 备用模型，后端统一推导模型声明，显式列表及多渠道规则保持优先；三语 README 赞助文案合为重点单段。
- [修复] 模型设置预览、冒烟及保存的配置校验失败显示具体字段与修正提示，避免仅显示笼统请求失败；Modelflare 渠道说明补充客户端专属注册链接，与快速添加按钮共用 app UTM。
- [改进] 新增首位 Modelflare LLM 渠道预设及条件注册链接，统一后端默认接入地址、简化三项配置，同步三语 README 紧凑赞助区（默认展开、可折叠，保留运营主体、模型范围、缓存补偿及充值优惠）和配置指南，保留 Anspire LLM 兼容、新闻搜索及 SerpAPI 赞助入口。
- [修复] 当前 Bot 与 Web 交替问股复用服务端已确认对象及严格工具范围，普通追问／比较保留确认状态，切股进入待确认；Bot 提交校验快照版本及用户锚点，保留真正旧代码／旁路写入的保守失效边界。
- [修复] 严格回测读取兼容正常 CN 写入器生成的数字汇总／明细键，按已验证对象与关联分析来源约束 SQL，保留跨市场隔离及总数／分页一致性。
- [修复] 问股条件切股跨逗号保持澄清，否定比较不扩大工具范围；个股回测汇总及明细按已验证市场身份查询，保留同身份存储别名，不回退读取其他市场数据。
- [修复] 问股实时与旧历史共享对象决策，否定／询问／引用不误确认；现有标的工具共用身份与适用性检查，向数据入口传递已验证目标，防止同码股票／指数混用与模型名称改变新闻对象。
- [修复] 问股明确切股按操作词确认目的地，重复发送不反向切股；普通分析追问维持原对象并正常执行，旧历史恢复共享方向规则且仅由明确代码建立事实。
- [修复] 问股混合代码／名称正确建立比较范围，明确切股排除旧对象；日线缓存读取保留股票／指数身份，Bot 回复绑定原会话实例，迟到初始列表不清空新接受状态或取消流。
- [新功能] 问股由服务端保存已确认的主讨论对象，刷新、重开和会话切换可恢复；明确切股更新对象，比较与执行失败不覆盖确认状态，保留股票／指数和跨市场身份。
- [修复] 问股接受事务统一保存消息、显式 Skill 与对象状态；拒绝旧会话实例和并发冲突，保护迟到摘要／回复，并保留显式空 Skill 的内置默认执行语义。
- [文档] 补充问股对象确认、旧历史恢复、非破坏升级／回滚／再次升级及真实 Codex 门禁的边界说明。

- [修复] ETF 轮动按真实 A 股交易日历保留全池缺报价日期及末尾缺口，防止调仓顺延、周末信号提前和动量窗口缩短；历史日历不可用时明确停止计算。

- [修复] ETF 轮动回测在行情缺口后结算完整持仓损益，缺报价日不虚构成交，防守资产缺报价时使用现金；统一参数扫描与主回测的行情处理，限定前复权来源，并跳过无关个股列表校验。
- [修复] 选股旧版缓存无时区获取时间回退文件 mtime，避免跨时区迁移后误用过期盘中日线；yfinance 日线按美东日期将排他的 end 推进至下一自然日，避免收盘后漏取当日 K 线。逐行核验带有效收盘价的交易日期，拒绝夹杂休市日或缺失/无法解析日期的来源、DSA 和缓存行情。

- [修复] 选股日线通过交易日期验证后才记录来源成功，非法行情累计失败可触发现有熔断，冷却后合法响应正常恢复。

- [修复] 选股全源仅有非法交易日或盘前占位行情时走聚合取数失败路径，DSA 与缓存同样不作为非法降级候选。

- [修复] 选股全源降级时将休市及未来日期的日线排在合法陈旧数据之后，避免非法日期抢占备用来源或缓存。

- [修复] 选股在全源陈旧时统一选择最新有效日线，同日保留来源优先级，并拒绝盘前占位 K 线在盘中继续作为新鲜缓存。

- [修复] 选股响应及历史保留实际因子权重中的零值，候选解释仍仅使用正权重，确保当次策略配置完整可追溯。

- [修复] 选股缓存以持久化获取时间判断新鲜度，防止桌面恢复改写 mtime 误用盘中数据，并拒绝周末与休市日期的伪日线，包括重新开盘后的盘中阶段。

- [修复] 选股日线全部降级时比较文件缓存与实时陈旧数据的最新有效日期，保留更新缓存及降级诊断，不覆盖 last-good。

- [修复] 选股日线全源失败时向 DSA 降级结果传递逐来源错误、顺序和健康状态，避免聚合错误少算质量扣分与低质量风险。
- [修复] 选股 DSA 日线与所有备用来源均陈旧时保留 DSA 优先结果，并保留备用请求错误和降级信息，避免旧备用日线覆盖原有较新数据。
- [改进] 选股 LLM 重排前按既有候选上限补充新闻与事件，提示词保留来源及发布时间；同次运行复用查询结果，缺失、空结果和失败不视为无风险，因子降级及既有风险规则保持兼容。
- [改进] 选股 LLM 重排前按既有候选上限补充新闻与事件，提示词保留来源及发布时间并隔离不可信资料与排序指令；同次运行复用查询结果，缺失、空结果和失败不视为无风险，因子降级及既有风险规则保持兼容。
- [改进] 选股 LLM 重排前按既有候选上限补充新闻与事件，保留上游来源、发布及检索时间并隔离不可信资料与排序指令；同次运行复用查询结果，缺失、空结果和失败不视为无风险，因子降级及既有风险规则保持兼容。
- [测试] 补充真实搜索入口的选股检索时间回归，仅模拟 HTTP 响应，覆盖新闻与事件首次采集、缓存命中和过期重取，以及排序提示词、最终响应和历史记录中的时间一致性。
- [修复] 真实搜索结果记录实际检索完成时间，并在归一化、日期过滤、相关性排序及缓存复用中保留，避免选股事件证据一直缺失检索时间；缓存读取不刷新时间。

- [改进] 选股 LLM 重排前按既有候选上限补充新闻与事件，保留上游来源、发布及检索时间并隔离不可信资料与排序指令，长度预算包含 system 消息及重试提示；同次运行复用查询结果，缺失、空结果和失败不视为无风险，因子降级及既有风险规则保持兼容。
- [改进] Web 始终保留选股导航入口；未开启时提供开启提示，状态加载与请求失败不再误报未开启，失败可重试且不会自动启用或提交任务。
- [修复] Web 设置页统一保护普通配置、模型渠道与调度草稿，重置和成功导入清理全部旧草稿，保存及导入期间避免编辑和离开竞态；登录后保留安全站内目标及 query/hash。

- [修复] 选股快照或日线过滤后无候选时仍保存当次策略的实际归一化因子权重，避免使用策略目录中的原始或后续修改的权重补填运行历史。
- [修复] 选股日线缓存增加交易日与收盘时段新鲜度核验，旧 DSA 日线先尝试原生来源，auto 模式继续尝试滞后来源之后的备用来源；所有陈旧来源均不覆盖 last-good 缓存，降级结果进入现有质量评分和风险提示；运行历史保留策略版本、类别与实际因子权重。
- [测试] 补充选股 auto 日线连续陈旧来源（含 Tushare）降级与 DSA 桥接回归，验证新鲜备用日线写入缓存、参与技术因子计算且不产生陈旧数据风险惩罚。

- [修复] 妙想补充查询采用跨实例/筹码与资金流共享的非阻塞准入及超时隔离，避免过期后台请求排队消耗额度；明确排除日线能力，并统一列表型 nameMap 的选表与解析。
- [修复] 默认 Web smoke 排除独立 fixture 目录，避免无密码且未启动 Web 服务时错误收集选股用例；CI 同时验收默认和 fixture 入口。
- [测试] 强化无理由 LLM 排序回归，验证双候选实际重排（含缺省和零分、risk-only 响应）后保留本地 observed 因子、模型 inferred 标记与 partial 综合质量。
- [修复] 选股时点证据标题为空白但摘要有效时复用近期缓存，Why Now 展示有效摘要，避免误刷新和证据丢失。
- [测试] 补充预填过期/无日期新闻与事件的 screen 入口回归，覆盖真实搜索响应归一化、单类刷新、历史持久化及有效缓存跳过补充。
- [修复] 无入选理由的合法 LLM 排序保留 inferred 参与标记，避免仅展示本地因子而误报全 observed；风险文本保持独立。
- [修复] 选股预补充新闻/事件与 Why Now 共用时效及来源校验，单独刷新无效缓存，失败保持 unknown 与告警。
- [修复] 选股后分析器完成非零调分但未提供摘要（含 null 和空白摘要）时，Why Selected 保留分析器来源、质量与调分说明，并在归一化、服务响应和历史记录中保留完成状态及分差。
- [测试] 补充仅返回 thesis 的 LLM 排序回归，验证真实重排后模型论点与本地因子、后分析摘要共存，并完整保留在服务响应及历史记录中。
- [测试] 补充选股后分析真实调分与重排回归，验证显式 LLM 排名理由与 scorecard、DSA、external_http 摘要来源共存，以及服务返回和历史持久化一致。

- [改进] Web 首页自选股列表新增“变化 / 状态 / 下一步”三段信号，按今日分析、历史报告、运行任务和详情查询状态提示下一步操作；“仅未分析”复用计数与提交规则，排除运行中任务，兼容股票/指数身份。
- [改进] 研究证据保留来源观测与抓取时间，数据可用不再自动标为 fresh；缺少明确时效判定时返回 unknown，保留上游 stale 与旧报告兼容。
- [新功能] Web Chat 意图识别层新增主解析器 `web_intent_resolver`（六步流水线，消费分词模块产物）：一条用户消息解析为按表达顺序保序的任务列表（`resolve` 返回二维组结构，组=子消息）；消息级多任务切分（消费型标点 + 顺序连接词，token 元素恒不变），同句平权分解（个股/泛市场·指数·纯市场词/板块/追问继承/存疑代码主体判定梯，未被主体消费的板块与组合语境独立成任务）；跨市场同名歧义聚合为 `confirm_stock` 确认（组级 pending：市场词/候选全名/唯一子串/裸数字逐组消解，点名市场词不串扰他组，矛盾回复整轮判新话题，拒绝词取消全链），任一任务待确认即整链短路；LLM 多意图兜底协议（`intents` 数组保序拆分、`followup` 伪标签转继承、`stock_code` 三道防幻觉闸门、板块/未解名"原文出现"闸门；豁免需视野完备+置信≥0.8+无多意图信号三证齐全）；会话簿记 `recent_stocks`/`pending_actions`/`last_intent`/`last_resolutions`（确认消费与跨轮追问继承的数据源）。意图枚举 `WebIntent`（五互斥意图 + 上下文继承）与任务结构 `WebIntentResolution` 随本 PR 落入 `web_intent_types`。
- [测试] 新增 407 个意图解析器单元测试：三判别测试意图边界矩阵（与 `web_intent_types` docstring 对照表互为基线）、多意图切分与平权分解、确认消费完整生命周期（消歧/矛盾/拒绝/新话题/模糊回应）、LLM 合并闸门与坏输出回退、会话簿记与跨轮追问继承。

- [修复] 妙想资金流按明确金额指标选表选列，防止收盘价或占比被误当作主力净流入金额；缺失值保留在交易日窗口中，避免较早数据被误当作最新值或完整窗口。

- [修复] AkShare 基本面财务包、资金流和龙虎榜超时后，在真实后台任务结束前按操作跨管理器抑制重复请求，避免连续分析不断占用后台槽位；正常并发与其他数据块继续执行，任务退出后自动恢复。

- [修复] 基本面请求诊断用单调时钟记录实际等待耗时，线程池拒绝和超时不再把完整超时预算写入 duration_ms。
- [改进] Web 持仓页新增“风险与暴露看板”，聚合个股集中、行业集中、回撤、止损、AI 信号、价格质量、市场暴露和币种暴露。
- [修复] 组合风险看板在快照失败时保持金额、数量和汇率状态未知，统一个股/行业集中度排序与摘要校验，同时接受四位舍入后的零权重尾行，避免误标 Top1 或隐藏有效风险。
- [测试] 告警来源提示改用无后台、无密钥的确定性浏览器验收，CI 保存桌面与窄屏截图。
- [修复] macOS 后端显式收集选股策略 YAML 资源，并以真实 Bash 参数构造测试保护 PyInstaller 隐藏导入和入口参数。

- [修复] 个股资金流按沪深北市场请求并取最新有效交易日的主力净流入金额；去掉默认股票和市场排名的错误降级，行业排名仅使用有限金额，行业金额全部缺失或非有限时仍保留有效个股结果。

- [修复] 组合集中度统一校验全部持仓报价；缺价来源或非有限、非正价格即使标记为可用，也不展示集中度告警、权重或饼图，避免零市值占位误报 100% 集中；价格质量旗标同步识别不可用报价，且不重复计为过期价。
- [修复] `REPORT_LANGUAGE=en` 时个股决策仪表盘的 system/user prompt 改用完整英文模板（`ko` 复用英文骨架并保留韩文输出指令），不再在中文模板末尾追加英文约束，避免本地小模型（如 `ollama/qwen3:14b`）受主语言影响仍输出中文；JSON 键名、`decision_type`/`action` 枚举与解析契约不变，中文模板保持逐字不变（Fixes #2352）。
- [修复] 组合暴露看板复用逐账户聚合币种市值，正常展示混合币种及零市值账户暴露，缺价、过期汇率或异常估值显示暴露不可用；行业集中度要求完整分类覆盖，未分类、失败或缺少覆盖证据时显示不可用。

- [修复] 基本面适配按明确报告期调用 AkShare 业绩预告、快报及机构持股，修正十大股东市场代码并限制结果为目标股票；按真实指标生成快报摘要，避免旧默认日期、公告日期冒充摘要和跨指标错误降级。
- [修复] 基本面财务摘要按“指标行 + 报告期列”解析最新报告期，兼容 AkShare 带单位的指标名及“归属净利润”口径，区分同比百分比与财务金额；全空指标和仅日期的结果不再标记成功，不跨报告期补值。
- [修复] 财务摘要补齐新浪实网返回的收入增长率、归母利润增长率、ROE 和经营现金流四个明确指标别名，避免已有数据被误标为缺失。

- [修复] 桌面后端打包完整收集 MiniRacer 原生运行文件，并在 Windows/macOS 冻结产物中实际执行 JavaScript，防止筹码分布因漏包或版本错配永久失败。

- [修复] yfinance 基本面适配器按日期匹配去年同季度计算报表同比，不再固定取 `iloc[4]`；当 yfinance 缺少某一季度列时，不会再把更早一季误当作去年同期，找不到同期时回退到 `info` 同比。
- [新功能] 支持 Multi-Agent 分阶段轨迹评估：保留既有扁平工具指标并增加阶段快照、局部/累计步数、完成/失败/跳过状态与可选期望阶段命中率，单 Agent 输出保持兼容（Refs #2347）。
- [修复] Multi-Agent 各阶段的 `tool_metrics` 仅统计阶段本地调用，不再将样例级工具期望和步数预算错误应用到每个阶段。
- [修复] Multi-Agent 顶层轨迹步数改由阶段快照累计，避免将 orchestrator 阶段数误判为 agent-loop 步数并漏报全局预算超限。
- [修复] 腾讯日线对科创板（688/689）返回的成交量单位是「股」而非「手」，此前统一乘以 100 导致科创板 `volume` 偏大 100 倍；现按号段区分换算。已入库的历史数据需限定 `data_source = 'TencentFetcher'` 迁移修正（Fixes #2350）。
- [新功能] Web/API runtime scheduler 硬超时后扫描已落库分析历史，**默认发送**部分完成通知（`DSA_TIMEOUT_PARTIAL_NOTIFY` 未设置或为 true；此前超时不推送已落库个股），并在 `last_error` 中记录 `completed/pending` 摘要；可用 `DSA_TIMEOUT_PARTIAL_NOTIFY=false` 关闭推送（Refs #2328）。
- [测试] 修复股票名称解析冷启动超时并发测试的同步竞态：在放行后台抓取前确认两个等待者均已结束并返回空结果，避免 Docker 发布门禁偶发失败。
- [文档] 新增 `docs/upstream-sync-2026-09-12.md`（上游 v3.31.0 → v3.32.0 共 3 个 commit 的合并记录、`stocks.index.json` 冲突裁决，以及上游把「单一 token 不支援就跳过」改成「整批拒绝」的入口契约变更说明）
- [测试] 釘住美股复盘日期守门的盘别：`test_us_recap_uses_the_new_york_session_not_the_taipei_date` 只 mock 了 `get_effective_trading_date` 却没釘 `infer_market_phase`，而 `_resolve_overview_date` 在盘中／午休／收盘集合竞价／盘後四个 phase 会短路回 `now.date()` 根本不问它，等於拿真牆钟当输入——台北清晨（纽约盘後）跑全量必红、其余时段必绿；改为与同档 `test_overview_date_*` 一致釘成 `PREMARKET`，生产程式码未改
- [文档] 将仓库内所有 SerpApi 链接统一更新为新的赞助转化追踪地址。
- [修复] Codex 问股将当前激活的交易 Skill 指令传入最终请求，保留会话继承、显式清空及默认技能语义；限定在三个已保存数据工具内执行，缺失数据或能力时明确披露。
- [修复] 智能导入兼容带 UTF-8 BOM 的 CSV 与剪贴板文本，避免 `code` 表头被误当成数据并丢失有效股票代码。
- [新功能] Agent 新增 FXMacroData 官方宏观数据工具；USD 基础数据无需密钥，`00-daily-analysis.yml` 已映射可选的 `FXMACRODATA_API_KEY` Secret；Windows/macOS 桌面构建收集客户端内置操作目录，并在冻结产物中校验 Agent 工具注册表。
- [修复] 为 AkShare 大盘涨跌统计的东财与新浪降级调用增加可强制终止的子进程超时，避免外部接口无响应时长期占用分析线程（Fixes #2340）。
- [新功能] 新增 `python main.py --etf-rotation` 规则化 ETF 双动量轮动：输出最新调仓信号、扣成本回测、分年度对比、参数平原检验与数据质量告警（截断历史/异常跳变/混用数据源），不调用 LLM；配置见 `ETF_ROTATION_*` 与 `docs/etf-rotation.md`。
- [新功能] 新增 Requesty（OpenAI Compatible 聚合网关）渠道预设：Web 模板、`.env.example` 示例、`00-daily-analysis.yml` 的 `LLM_REQUESTY_*` 映射与服务商文档同步补齐；`requesty.ai` Base URL 下「获取模型」返回的 vendor/model ID 自动保留 `openai/` 网关路由，避免被误判为 LiteLLM 直连 provider。

- [修复] CLI 与 Web/API 每日调度共享 SQLite 计划时刻认领，避免同一数据库上的并发或错峰定时推送重复；保留不同时间点/分析范围及手动补跑，明确失败后的至多一次派发语义（Fixes #2349）。
- [修复] 告警列表披露有效环境规则及后台去重后的数量，提示页面删除或禁用不会停用环境规则；保留原有加载、执行和通知语义。
- [修复] 告警来源统计以只读方式展开持仓，避免列表请求查询实时行情或重写持仓缓存、批次和每日快照，保留后台优先级、数量上限及去重语义。
- [修复] 告警来源统计在单次列表请求内复用相同目标的展开结果及失败，避免多条持仓规则重复回放账本；缓存不跨请求，保留最新持仓、失败重试与原有去重数量语义。
- [新功能] 新增 `/api/v1/screening/screen/check`，对调用方提供的单条快照逐项解释策略硬过滤条件、阈值、当前值与通过/失败/缺失状态，不抓取行情、不调用模型、不改变既有选股结果。

- [文档] 新增 `docs/upstream-sync-2026-09-29.md`（上游 `f9e7b778` → `d3fee51a` 共 8 个 commit 的合并记录、4 个冲突档的裁决与静默降级排查）
- [文档] 新增 `docs/upstream-sync-2026-09-20.md`（上游 v3.32.0 → `f9e7b778` 共 4 个 commit 的合并记录、静默降级排查，以及超时部分完成通知写死简体文案对 `REPORT_LANGUAGE=zh-TW` 的影响说明）

- [改进] `market_data.health` 新增财报稽核：`financial_statement` 进入表清单（skill `update-market-data` 早就叫人看它的 `end`，但 health 从来没印过），并新增 `stale financial quarters` 一行列出**已过公告截止日却一列都没有**的季与对应的 `financials` 指令；财报季更不在 `daily` 里，漏一季原本完全静默。只报不挡（整季 IFRS html 包 1-2 GB，不该挡住 `make morning`）

- [修复] 台股大盘复盘的表头加权指数改用 `market` schema 中**该场次**的官方收盘，不再直接采信没有场次身分的即时报价：非交易日 yfinance 的 `hist.iloc[-1]` 会回一根幽灵 K 棒（2026-09-20 实测 `47368.04 / +0.40%`，而该份报告复盘的 2026-09-18 官方收盘是 `47180.75 / +1.93%`），14:00 排程则相反——指数已有当日、TWSE 官方统计还停在前一场次，于是同一份报告的指数与涨跌家数分属两天；查无该场次的列时保留即时值并 warning（fail-open），仅作用于台股与表头那一档

- [修复] 汇总报告表头新增失败揭露：过去表头的档数一直是 `len(results)`（= 成功数），掉一档的那一轮推出去的报告读起来是完整的——2026-09-18 排程请求 14 档、2308.TW 因 LLM 连两次回非法 JSON 被丢弃，`reports/report_20260918.md` 写「共分析 **13** 檔股票」且整份不含 `2308`，Bark 推送成功、持有人零讯号；现在 dashboard 与 brief 两种 `REPORT_TYPE` 都会在表头加一行「⚠️ 本輪有 N 檔未產出結果：<代码>」，成功数不被窜改，无失败时报告逐字元与先前相同；分组报告不带整轮清单

- [测试] 补 `market_data.health` 的接线守门：纯函式 `stale_financial_quarters` 本来就有测试，但 `report()` 里把它接进 `integrity` 的那一行没有任何测试覆盖（删掉整套仍全绿）；改用 `test_hardening.py` 既有的假连线形状让 `report()` 真的被执行，删接线或把 SELECT 指到别张表都会红（该测试随 `0c75512d` 一起入库，该 commit 讯息只写了文档部分）

<!-- 新条目格式：- [类型] 描述（类型取值：新功能/改进/修复/文档/测试/chore）-->
<!-- 每条独立一行追加到本段末尾，无需分类标题，合并时冲突最小 -->
- [chore] 合併上游 `7a21cd76`..`ec66bf46`（1 個 commit：#2419 Telegram 推送改以 UTF-16 長度判斷與分段；本 fork 通知走 Bark，不受影響），裁決見 `docs/upstream-sync-2026-10-21.md`
- [修复] Telegram 推送按 UTF-16 长度判断与分段，修复含大量 emoji 的报告超出 4096 限制导致发送失败的问题。

## [3.33.0] - 2026-10-15

### 发布亮点

- feat: 问股讨论对象由服务端保存，刷新、重开及 Bot/Web 交替使用可恢复；修复完整股票名称被内部短别名误判的问题。
- feat: 新增规则化 ETF 双动量轮动，提供最新调仓信号、扣成本回测、年度对比及数据质量告警，无需 LLM。
- feat: Web 新增只读数据中心和持仓风险与暴露看板，自选股列表提供“变化 / 状态 / 下一步”提示。
- feat: 选股提供带来源与质量状态的入选理由和时点证据，补齐新闻事件，并修复日线新鲜度、交易日期及缓存降级判断。
- feat: 简化 Modelflare 单 Key 配置，补充已合入的 Requesty 渠道、妙想筹码与资金流数据及 FXMacroData 宏观工具。
- fix: 修复基本面与资金流解析、科创板成交量单位、重复定时派发和桌面 MiniRacer 资源打包；调度超时可推送已完成的部分结果。

### 新功能

- 问股由服务端保存已确认的主讨论对象，刷新、重开和会话切换可恢复；Bot/Web 交替问股共享已确认对象，保留股票/指数、跨市场身份及严格工具范围（#2397、#2406）。
- 新增 `python main.py --etf-rotation` 规则化 ETF 双动量轮动，输出最新调仓信号、扣成本回测、分年度对比、参数平原检验和数据质量告警；不调用 LLM，配置与数据边界见 [ETF 轮动](etf-rotation.md)（#2376）。
- Web 新增只读数据中心，展示 Provider 能力、数据集质量和运行时优先级，不展示 API Key 或原始配置值；短窗口中的导航列表可滚动，并保留主题、语言与退出控件（#2304）。
- Web 持仓页新增风险与暴露看板，聚合个股/行业集中度、回撤、止损、AI 信号、价格质量、市场及币种暴露（#2297）。
- 选股候选新增后端生成的 Why Selected / Why Now 解释、来源与质量状态；保留模型 reason/thesis 和逐条 provenance，区分真实零值与缺失占位值，旧历史不重新评分或回写（#2305）。
- 新增 `/api/v1/screening/screen/check`，对调用方提供的单条快照解释策略硬过滤条件、阈值、当前值及通过/失败/缺失状态，不抓取行情、不调用模型、不改变既有选股结果（#2382）。
- 新增单票决策信号复盘只读接口 `GET /api/v1/decision-signals/stocks/{stock_code}/review`，返回样本量、命中率、常见 miss 原因和置信度调整方向；启用 `AGENT_MEMORY_ENABLED` 时作为独立记忆段注入，样本不足或数据质量弱时仅供观察（#2331）。
- 新增妙想补充数据源 `MX_APIKEY` / `MX_PRIORITY`，用于筹码分布和个股资金流降级，接入 Web 配置与每日 Actions；不提供日线能力，调用受剩余阶段预算和跨实例非阻塞准入约束（#2387、#2388）。
- Agent 新增 FXMacroData 官方宏观数据工具，USD 基础数据无需密钥；每日 Actions 映射可选 `FXMACRODATA_API_KEY`，Windows/macOS 冻结产物收集操作目录并校验工具注册（#2336）。
- 新增 Requesty 聚合网关预设，补齐 Web、环境示例、Actions 的 `LLM_REQUESTY_*` 映射与配置说明；模型发现返回的 vendor/model ID 保留 OpenAI-compatible 网关路由（#2367）。

### 改进

- Modelflare 支持只配置 `MODELFLARE_KEY`，后端、Web、选股及 Actions 自动识别渠道并补齐默认地址和模型；单渠道未声明模型时可复用主模型与 OpenAI 备用模型，否则使用默认模型，显式 YAML、模型列表和多渠道规则保持优先（#2403）。
- 模型设置预览、连接测试及保存失败时显示具体字段与修正提示；Modelflare 预设提供条件注册链接和说明，同步简化三语 README 赞助区并使用对应语言横幅（#2403、#2407）。
- Web 自选股新增“变化 / 状态 / 下一步”信号，结合今日分析、历史报告、运行任务和详情状态提示操作；“仅未分析”排除运行中任务，兼容股票/指数身份（#2293）。
- Web 始终保留选股导航，未开启时提供开启提示；状态加载失败可重试，不误报功能未开启，也不自动启用或提交任务（#2392）。
- 选股 LLM 重排前按候选上限补充新闻与事件，保留来源、发布时间和检索时间，隔离不可信资料与排序指令；长度预算包含 system 消息和重试提示，同次运行复用查询，缺失/失败不视为无风险（#2390）。
- 研究与搜索证据保留来源观测和实际检索完成时间，在归一化、时效过滤、排序及缓存中持续传递；缓存命中不刷新检索时间，没有明确时效证据时保持 unknown（#2381、#2390）。
- 新增意图解析器基础模块，支持二维任务组、多意图解析、跨市场候选消歧、LLM 兜底及确认状态簿记；本版本尚未将其接入 Web SSE 执行入口（#2385）。
- Multi-Agent 轨迹评估增加阶段快照、阶段本地工具指标、局部/累计步数及完成/失败/跳过状态；顶层步数由阶段快照累计，单 Agent 既有指标保持兼容（#2351）。

### 修复

- 问股将完整注册名称视为一个标的，避免“长电科技”中的“长电”或“京东方A”中的代码片段触发错误澄清；独立别名、跨市场同名和名称/代码真正冲突仍沿用确认规则（#2406）。
- 问股实时请求与旧历史恢复共用对象决策，正确处理明确切股、重复输入、普通追问、比较、否定、条件句及引用；工具和缓存保留股票/指数及跨市场身份，防止同码误读与模型名称改变新闻目标（#2397）。
- 问股接受事务统一保存消息、显式 Skill 和对象状态，校验会话实例、版本及用户锚点；迟到列表、摘要或回复不覆盖新状态，比较或执行失败不改写已确认对象，显式空 Skill 保留默认执行语义（#2397）。
- 严格回测按已验证身份和关联分析来源查询，兼容正常 CN 写入器的数字键及同身份存储别名，保持跨市场隔离、总数与分页一致性（#2397）。
- Codex 问股向最终请求传递当前交易 Skill 指令，保留会话继承、显式清空及默认技能语义；能力边界限定于三个已保存数据工具，缺失数据或能力时明确披露（#2371）。
- ETF 轮动按真实 A 股交易日历保留全池缺报价日及尾部缺口，防止调仓顺延或信号提前；缺价不虚构成交，报价恢复后计入完整持仓损益，防守资产不可买入时保留现金；日历不可用时停止计算，主回测与参数扫描共用前复权行情（#2376）。
- 选股日线核验交易日期、有效收盘价及收盘时段，拒绝休市/未来日期、非法日期与盘前占位行情；缓存使用持久化获取时间，无时区旧时间回退文件 mtime，避免跨时区或桌面恢复误判新鲜度（#2389）。
- 选股全源陈旧时优先保留最新合法日线，同日保留来源优先级；比较 DSA、备用来源及文件缓存，不以陈旧/非法结果覆盖 last-good，完整传递各来源错误和健康状态以参与质量评分（#2389）。
- 选股来源仅在行情通过日期验证后记录成功，非法响应参与既有熔断和恢复；yfinance 按美东日期推进排他的 end 边界，避免收盘后漏取当日 K 线（#2389）。
- 选股响应和历史保留当次实际因子权重（含零值），无候选时也不使用策略目录原始或后续变更权重补填；入选解释仍只消费正权重（#2389）。
- 选股时点证据与预补充共用时效和来源校验，按新闻/事件分别刷新无效缓存，有效摘要可用于 Why Now；失败保持 unknown 和告警，无理由或仅 thesis 的 LLM 结果仍保留 inferred 标记、真实重排与风险说明（#2390、#2305）。
- 选股后分析器完成非零调分却未给出有效摘要时，仍保留来源、质量、完成状态及分差；模型理由、本地因子和各后分析来源可同时保存在响应与历史中（#2305）。
- Web 设置保护普通配置、模型渠道及调度未保存草稿，重置/成功导入清理旧草稿，保存及导入期间防止编辑与离开竞态；登录后保留安全站内目标及 query/hash，首次引导可滚动聚焦 `STOCK_LIST`（#2386、#2399）。
- 持仓看板缺价、过期汇率、异常估值或行业分类覆盖不足时保持不可用，不展示误导的集中度、权重或饼图；兼容舍入后的零权重尾行，并正确聚合混合币种和零市值账户（#2297）。
- 妙想按明确金额指标选表选列并规范列表型 nameMap，避免价格/占比被当成资金流金额；缺失值保留在交易日窗口中，超时任务结束前抑制重复请求，避免排队消耗额度（#2387、#2388）。
- AkShare 基本面、资金流及龙虎榜超时后按操作跨管理器抑制重复后台请求；大盘统计降级调用使用可终止子进程超时，诊断耗时按实际等待记录，避免线程拒绝或超时虚报完整预算（#2345、#2372、#2380）。
- 基本面按明确报告期与目标股票读取业绩预告、快报、机构持股和十大股东，修正市场代码；财务宽表按最新报告期与真实指标解析，补齐新浪收入/利润增长、ROE、经营现金流别名，不跨报告期补值或把空结果标成功（#2362、#2370、#2373）。
- yfinance 财报同比按日期匹配去年同季度，缺同期时回退 info 同比，避免固定行偏移把更早季度误当作去年同期（#2365）。
- 腾讯科创板（688/689）日线成交量按“股”保留，不再统一乘以 100；存量数据修正要求见下方升级注意事项（#2360，Fixes #2350）。
- `REPORT_LANGUAGE=en` 使用完整英文 system/user 模板，`ko` 复用英文骨架并保留韩文指令；JSON 键名、枚举和解析契约保持不变，中文模板不变（#2368）。
- CLI 与 Web/API 每日调度共享 SQLite 计划时刻认领，避免同一数据库上的并发或错峰重复派发；不同时间/分析范围及手动补跑独立执行，认领后失败不会自动重派（#2379）。
- Web/API 调度硬超时后记录已完成/待完成摘要，并可推送已落库的部分结果；默认通知行为及关闭方式见下方（#2338）。
- 告警列表披露有效环境规则和去重后数量，明确页面删除/禁用不停止环境规则；来源统计只读且请求内复用，不查实时行情或改写持仓快照；规则变更后的刷新保留当前筛选和分页（#2374、#2378）。
- Windows/macOS 桌面后端完整收集 MiniRacer 原生运行文件并实际执行 JavaScript 检查；macOS 补齐选股策略 YAML 资源及 Bash 参数构造校验（#2361、#2384）。
- 智能导入兼容带 UTF-8 BOM 的 CSV 与剪贴板文本，避免表头误判或有效代码丢失；默认 Web smoke 排除独立 fixture，避免错误收集需特定环境的用例（#2333、#2390）。

### 升级注意事项

- **默认行为变化**：Web/API 调度硬超时后，`DSA_TIMEOUT_PARTIAL_NOTIFY` 默认开启，可能新增部分完成通知；设为 `false` 可关闭。该能力不保证通知送达，也不会自动重试已认领的整轮任务。
- **历史行情**：科创板成交量修复不自动重写已有数据；修正旧记录时须限定 `data_source = 'TencentFetcher'` 及受影响的 688/689 股票，不能统一调整其他来源或市场。
- **会话升级与回滚**：升级前备份数据库及配置；回滚时先停止新后端，保留新增可空列与数据库版本默认值，不删列或重建数据库，避免旧新写入后端并行。旧版写入后再次升级需重新确认讨论对象，已有消息及 Skill 保留，详见 [问股事件与回滚边界](agent-stream-events.md#rollback)。
- **功能范围**：新意图解析器仍为基础模块，尚未接入 Web SSE 执行入口；CLI 启动分析行为保持现状。ETF 轮动及可选数据/模型渠道按各自配置启用。

### 测试与文档

- 补充真实索引下完整名称、HTTP/SSE、会话恢复与重复确认回归；意图解析器覆盖任务切分、确认消费、LLM 结果校验及状态簿记。
- 补充选股新鲜度、备用来源、缓存、检索时间、真实重排及响应/历史一致性验证，保留风险与缺失数据反例。
- 告警来源和页面交互采用无后台、无密钥的确定性浏览器验收，CI 保存桌面与窄屏证据；修复名称解析冷启动并发测试竞态。
- 同步模型、数据源、ETF 轮动、数据中心、问股升级/回滚及桌面指南，更新三语赞助说明和 SerpAPI 链接，修复文档锚点。

## [3.32.0] - 2026-09-06

### 发布亮点

- feat: 已登记 A 股指数贯通 Web/API、Bot、CLI 与 GitHub Actions 分析入口，注册表扩展至 33 项，并统一指数身份、任务去重、历史与 Chat 上下文。
- feat: 新增个股研究聚合 API、ResearchArtifact 结构化研究产物，以及数据源能力与数据集质量只读接口。
- feat: 完善 Futu OpenD 港股数据源接入，新增 Web Chat 分词基础模块与 Agent 轨迹评估入口。
- feat: 自建 SearXNG 搜索超时可配置，Tavily 改用 basic 搜索以降低 credit 消耗。
- fix: 定时分析采用独立进程与硬超时保护，选股结果支持历史恢复，桌面端增加全局更新入口，并修复 Linux/Docker 分享图中韩文字体缺失。
- fix: 收敛 LiteLLM 兼容版本窗口，更新 Web/桌面依赖，并修复美股数据源优先级与股票名称归一问题。

### 变更明细

- [修复] 入口分类的模式边界修复（PR3 review）：不消费个股列表的模式（`--backtest`/`--market-review`/`--serve-only`/`--webui-only`/`--portfolio`/`--schedule`/`config.schedule_enabled`）在模式分发前整体跳过 `--stocks` 与 GitHub Actions `STOCK_LIST` 的分类与索引刷新，未登记 `.CSI` 等坏 token 不再拦截这些模式（此前 `GITHUB_ACTIONS=true` 下 `--backtest`、`--portfolio futu`、`--schedule` 配坏 watchlist 会在进入模式主体前被整批拒绝）；`--schedule --stocks` 的"警告后忽略启动快照"语义保留；`--stocks` 与 GitHub Actions 入口的指数分类与整批拒绝契约不回归，文档同步把指数自选股配置收窄为仅这两类入口（本地 `.env`/Docker 无参数默认运行保持股票语义，分析指数请配 `--stocks`）。
- [新功能] 指数注册表新增国证粮食（`sz399365`）与中证钢铁（`csi930606`）：已登记 seed（`scripts/stock_index_seeds/index_registry.csv`）与 bundled 指数清单（`apps/dsa-web/public/stocks.index.json`）由 31 项扩展到 33 项，已登记指数的 `sh`/`sz`/`csi` 前缀与 `.SH`/`.SZ`/`.CSI` 显式形态均可作为自选股指数目标；ETF 与美股指数不进 CN 注册表，路由语义不变。
- [文档] 中英 full-guide 新增「指数自选股配置」小节：说明已登记指数前缀/显式后缀规则、未登记 `.CSI` 整批拒绝、裸码不自动提升为指数、NDX 等美股指数裸码即正确路由、ETF 走股票路径，并同步补充 README / DEPLOY 的 `STOCK_LIST` 提示；修正 full-guide 中已过期的「已登记 5 个沪深指数」表述。
- [新功能] GitHub Actions 每日工作流支持已登记指数入口：`GITHUB_ACTIONS=true` 下无参数 `python main.py` 把 `STOCK_LIST` 按与一次性 `--stocks` 相同的判型规则分类为结构化 target（显式指数 token 进入指数路径、个股 token 保持既有 legacy 路径），指数与个股同批复用同一 Pipeline，不新增第二条能力矩阵；本地与 `--schedule` 热刷新默认路径不在入口构造 target，语义不变。
- [修复] `main.py --stocks` 对未登记 `.CSI` 目标在入口明确报错并整批拒绝本轮运行（此前被静默按股票 token 交给 provider），拒绝发生在任何 provider 请求之前，与 API 层"provider 调用前明确拒绝"的边界对齐；CLI/Actions 整批拒绝与 API 异步批量仅拒绝该目标的差异已在文档中说明。
- [测试] 新增 Bot 指数入口 transport-independent 在线 E2E smoke（`scripts/smoke_bot_index_entry.py`）：worker 子进程经真实 `CommandDispatcher.dispatch_async` 提交并在同进程轮询 `TaskService` 贯穿到 `StockAnalysisPipeline`，父进程只负责 deadline、进程树清理（Windows `taskkill /T /F`、POSIX 杀进程组）与退出码（0=成功/1=失败/124=超时），输出单行 `E2E_EVENT {json}` 事件（`phase=submitted|completed|failed|timeout`）；smoke 覆盖 `SH.000016`/`上证50`/`930955.CSI` 矩阵，期望 code/name 取脚本内置权威映射（不信任响应/结果自报身份，提交 code mismatch 输出含期望值与实际值的显式错误并携带结构化实际 `stock_code`，dispatcher 路由错误也失败），矩阵外 target 与非正 `--timeout` 在提交与 spawn 之前即被拒绝（退出码 2），completed 须 exact canonical code、exact 注册名称且 `analysis_summary`/`operation_advice`/`trend_prediction` 非空（仅空白视为空），失败或结果不完整即非零退出；超时清理进程树（Windows `taskkill /T /F`、POSIX 杀进程组），清理成功输出 `timeout` 事件并退出 124、清理失败输出含清理错误的 `failed` 事件并退出 1，不回滚 DB/报告/通知副作用；用户 Ctrl-C 中止时父进程同样先清理进程树，清理成功透传中断、清理失败输出含清理错误的 `failed` 事件并退出 1，绝不静默吞掉清理失败；worker 意外异常输出 `failed` 事件并退出 1（stderr 保留异常证据，`KeyboardInterrupt` 不按普通失败处理），父进程将 worker 任意其他退出码归一化为 1（运行时契约只暴露 0/1/124）；父进程以内部 `--worker` flag 显式拉起子进程（不依赖环境变量，防外部预置绕过硬超时）；不 mock 在线依赖、不 dry-run、不修 transport，不加入离线 gate。
- [新功能] Bot `/analyze` 支持已登记指数入口：显式代码（`sh000016`）、CSI alias（`930955.CSI` 收敛为 `csi930955`）与注册中文名（`上证50`）均可提交，指数以结构化 `AnalysisTarget` 经 `TaskService` 贯穿到 Pipeline `process_single_stock`（`sh000016` 不再被改写为 `SH000016`）；注册名称查询独立于 parser identity alias（中文名不进入 `find_by_explicit_key`/`parse_analysis_target`），同名歧义返回明确错误并要求显式代码，未登记 CSI 与未知名称返回明确错误且不提交任务；个股代码（A/HK/US）保持既有 legacy code 路径不变，股票名称输入（如 `贵州茅台`）由本次 Bot 入口新暴露——复用既有名称解析器（`resolve_name_to_code`）解析后提交 legacy code，不携带结构化 target；提交成功响应在 `BotResponse.extra` 暴露内部任务 identity（`task_id`/`stock_code`）供在线验收等内部流程使用，文本与错误路径不变、平台适配器可忽略 `extra`。
- [新功能] 新增最小 Agent 轨迹评估入口 `evals/agent_trajectory/`(Refs #1956):纯函数指标层只消费真实 `tool_calls_log + AgentResult`,冻结最小指标契约(工具命中、冗余/缓存、失败/重试、总步数/max_steps),`run_eval.py` 经 `build_agent_executor` 真实执行并输出文本摘要 + 结构化 JSON 报告;评估为 reporter 非 gate,零 `src/` 改动

- [修复] 将 litellm 依赖窗口上界收敛到 `<1.99.0`：1.99.0 起把 `prompt_cache_key` 透传给 OpenAI provider，破坏 provider 缓存测试对不透传行为的既有断言（CI backend-tests 3/3 与 backend-gate 失败）；保留历史最低版本与 `!=1.82.7`/`!=1.82.8` 事故排除，同时同步更新各 LLM 兼容文档中写死的依赖约束表述，避免文档与 requirements.txt 漂移

- [新功能] 新增 `SEARXNG_TIMEOUT_SECONDS` 配置自建 SearXNG 单次搜索超时（默认 10 秒），已接线全部 SearchService 构造入口（含题材搜索子进程重建）与默认 GitHub Actions 工作流

- [修复] 美股日线路由现按各数据源当前优先级排序，单项 `*_PRIORITY` 配置（如 `YFINANCE_PRIORITY=0`）对美股即时生效；指数固定首选与 Longbridge preferred 语义保持不变

- [新功能] 新增个股研究聚合 API，以统一 canonical code 返回行情、历史、研究产物、资讯、缓存持仓关系和监控规则，并对每个块独立标记 fresh/partial/unavailable。
- [修复] 个股研究聚合拒绝交易所冲突的股票身份，在市场限定后无历史候选时保持空结果，兼容市场限定裸码与混合大小写旧数据，并从独立基本面快照补齐 ResearchArtifact 的财报与分红证据。

- [新功能] 支持通过 `main.py --stocks` 一次性分析已登记板块指数，自动使用指数适用的数据与分析能力，并保持报告、历史和决策信号兼容。
- [修复] `main.py --stocks` 在解析股票列表前先 best-effort 刷新股票索引注册表，保证首次运行能吃到刷新后的指数 alias/身份；刷新失败、超时或禁用不阻断分析。
- [修复] 交易日过滤对市场未知的指数 code（如 `sh000016`/`csi930955`/`930955.CSI`）按 `market=cn` 参与 A 股休市过滤，避免休市日指数被 fail-open 保留；市场仍未知的非指数 code 继续保留。
- [修复] 指数分析将实际命中的日线数据源归因保存到历史记录，并由 Dashboard/Brief aggregate 报告展示；来源无效时保持原有输出。
- [文档] 在中英繁 README 顶部关联 DSA arXiv 论文，并新增 `CITATION.cff` 统一项目引用信息。
- [新功能] 新增数据源能力与数据集质量只读契约，提供 `/api/v1/data/overview` 和 `/api/v1/data/capabilities`，为大盘看板、数据中心、个股详情和自选 2.0 统一暴露 provider capability、dataset quality 和 source priority。
- [修复] 统一美股指数实时行情与数据能力概览为 YFinance-only 路由，避免 YFinance 失败后误用 Longbridge fallback。
- [改进] PR CI 增加文档路径检测：仅修改普通文档、非治理 Markdown 或 LICENSE 时跳过后端测试分片、Docker、Web 与桌面打包，保留轻量治理和门禁汇总；契约文档、静态 API 规格与测试 fixture 仍执行后端回归。
- [新功能] 新增 ResearchArtifact 结构化研究产物契约，在 `AnalysisReport.structured_report` 中承载 Thesis、Evidence、Invalidation Conditions、Next Actions 和 Data Quality，并提供从现有报告生成结构化产物的后端 helper 与 Web 类型。
- [修复] 同步 ResearchArtifact 与 `AnalysisReport.structured_report` 到静态 OpenAPI，避免公开 API 规格与运行时契约漂移。
- [修复] Linux/Docker 分享图补齐 Noto CJK 字体与中韩文字体栈，避免 PNG 只显示数字和英文、中文或韩文内容消失。
- [修复] 股票名称归一：AkShare 部分名称带无意义内嵌空格（“五 粮 液”、“万  科Ａ”）与全角宽度拼写（“京东方Ａ” 的全角 Ａ），统一经 `_normalize_stock_name()` 做 NFKC 宽度归一 + 去空白（原 `_compact_stock_name` 仅去空白）：本地映射初值、`_build_name_map_from_df()` 构建与 `extend_AkShare()` 合并、磁盘缓存加载三个入库口（含归一后为空的条目守卫）与 `resolver_name_to_code_list()` / `is_known_stock_name()` / `resolve_name_to_code()` 三个查询入口同源归一；消除空格/全角拼写与本地无空格半角拼写比较不相等造成的假性改名别名，源形态输入（带空格/全角）与常规拼写同样可解析，覆盖 `/analyze` API、按名称导入与 Bot 文本解析等全部调用路径；全角拼写此前与分词管道 NFKC 归一后的半角输入（“京东方A”）永不相等——全名精确匹配落空且会被更短库内名误切出错误实体（“京东”），归一后半角/全角输入产出一致、展示名统一为归一拼写；磁盘缓存中的历史未归一数据（带空格/全角）经合并与加载入口自动归一，无需迁移。
- [新功能] Web Chat 意图识别层新增分词模块：`web_intent_tokenizer` 六步管道（多股票全名实体扫描 → 标点/空白切分 → 代码形提取 → 市场关键词 → 无歧义关键词 → 残存 gap 多策略 DFS 匹配）把用户消息切分为携带语义标签的 Token 序列；配套 `web_intent_types` 数据字典（Token 结构、Market 枚举、21 个语义 tag、clean/extend 双词池与正则机器）。核心原则"宁可不做，不可做错"：Step 1~5 只做精确匹配，Step 6 要求整段 TAG 全覆盖（交叉验证）才产出，未覆盖片段保持空 tag 交下游 LLM 兜底；代码形 token 辨认为 `stock_code`（附 code/name/market 三元组）/ `wrong_{market}_code` / `unknown_{market}_code` 三态，token 层代码拼写统一 canonical 归一（a=6 位裸数字、hk=HK+5 位、us=大写 ticker）。意图枚举与意图识别结果随后续 `web_intent_resolver` PR 引入。新增 183 个分词单元测试。
- [修复] 指数注册表在本 fork 曾整个载入失败：上游新增的 `_load_active_index_rows` 会对每个索引候选跑资产类型校验，而本 fork 美股索引有 18083 笔刻意标记的 `asset_type="unknown"`（对官方清单查无的 OTC 代码，留 `stock` 会让下游误判"不是 ETF"），导致 bundled 索引被整份拒收、`--stocks` 板块指数与 CSI 路由静默失效。校验器白名单加入 `unknown`（不授予任何指数身分）。
- [修复] 美股普通日线链路的首选来源恢复锚定 yfinance：上游按 `*_PRIORITY` 重排会把 AlphaVantage 排到 yfinance 之前，而 AlphaVantage 回未复权价且单次上限 100 根，设了金钥后会印出错的 `pct_chg`。兜底段仍按 `*_PRIORITY` 生效。
- [文档] 新增 `docs/upstream-sync-2026-08-30.md`：v3.30 → v3.31.0 的 17 个 commit 同步记录、6 档冲突裁决、保留的 fork 分歧与找到的静默降级。
- [修复] 台股带字母尾的代码（槓桿 `00631L.TW`、反向 `00632R.TW`、债券 ETF `00679B.TW`、特别股 `2887A.TW`）不再被判为 unsupported：`get_suffix_market` 与显式交易所后缀校验对台股先剥掉一个尾字母再判位数，`YfinanceFetcher._is_yahoo_suffix_stock` 的手写重复实作改为委派共用规则。此前上游新增的 unsupported 硬守门会在任何数据源跑起来之前就抛错。
- [测试] `stop()` 的 process-tree 终止恢复守门：blocking worker 与其 descendant 的自然寿命拉到远超观察窗，否则它们自己睡完就退出，删掉终止调用测试照样绿。
- [修复] 桌面端更新入口不再使用原生 `title` 属性（键盘与读屏都拿不到，且违反 Web UI governance 守门）：稳定的可及名称保留在 `aria-label`，版本与下载百分比等动态细节改由 `aria-describedby` 指向的 sr-only 文字承载。
- [测试] TickFlow 本地化断言改绑 `getFieldDescriptionZh` 真源，不再重抄描述字面——上游改过该文案却未同步断言，导致该测试在上游即为红。
- [修复] 台股代码校验改为逐字 ASCII 比对：`str.isalpha()` / `str.isdigit()` 都是 Unicode-aware，此前 `2330甲.TW`、`00631Ｌ.TW`、`００６３１.TW` 会被判成合法代码并带着无效字元送进 yfinance，抓取失败时 pipeline fail-open 产出静默缺资料的报告。jp/kr 同步收紧。
- [测试] 指数日线来源的持久化顺序改由 `save_analysis_history` 的 side_effect 当场抓快照：原断言比对的是同一个可变物件的两个参照，恒真，把 `_append_daily_data_source` 挪到写入之後也不会红。
- [文档] `docs/tw-swing-pipeline.md` 追加 2026-08-30 回验状态反思：第 2 层决策日志 0 笔到期、无法评估，并记录日志停摆、产出率算术（近期不会有可评估样本）、失效条件快照陷阱的实际重演，以及 Q2 财报补齐後唯一实仓的失效条件逐条判定。
- [新功能] 完善 Futu OpenD 港股数据源接入：系统设置支持 OpenD 地址、端口和港股实时数据源优先级，保留 Longbridge、AkShare、YFinance fallback。
- [测试] 增加 Futu 配置 schema、港股实时路由和 fallback 契约覆盖。

- [新功能] 建立唯一、可生成、可校验、可降级的指数身份注册表：由 `scripts/stock_index_seeds/index_registry.csv` 的 31 项 manifest 确定性合并进 `apps/dsa-web/public/stocks.index.json`，运行时唯一真源为 JSON 中通过校验的 `active=true`/`assetType=index` 行，移除 `stock_list_parser` 的 5 项硬编码白名单；支持 `--index-only` 生成与字节稳定输出。
- [新功能] 补齐显式 SH/SZ/CSI 指数 alias 收敛与 CSI 身份：`sh000300`/`000300.SH`/`sz399300`/`399300.SZ`/`000300.CSI` 均解析到 `sh000300`，`csi930955`/`930955.CSI` 解析到 `csi930955`；未登记 `.CSI` 输入返回 `unsupported`；裸数字恒为 stock 并仅通过 `matched_index` 暴露歧义。
- [新功能] 数据管理器按 SH/SZ/CSI 支持矩阵映射 provider symbol：CSI 仅 AkShare 支持（`csi{code}`），Tencent/TickFlow/Yahoo 返回空 symbol 并记录 `unsupported` provider-run，不触发指数健康熔断。
- [改进] 存储层 `_derive_canonical_id` 统一为 parser 推导（裸码=stock、显式指数=index），并新增幂等分批修复历史裸码错误 canonical 串桶（`000001`/`000016`/`000688`/`930955` 等），显式指数行与正确 stock 行不受影响，registry 为空时修复 no-op。
- [改进] Web loader 完整解压含 index 的共享 payload，但在返回给 autocomplete/popular/group 消费面前过滤 `assetType=index`，股票与 ETF 行为保持不变。
- [测试] 为生成器、loader、parser、provider 路由、存储修复与 Web 门槛补充 TDD 回归锚点。
- [修复] PR #2267 review 收敛 CSI 显式身份：将 `csi` prefix（canonical）与 `.CSI` suffix（显式 alias）在 parser/build/runtime 规范化器中分离，未登记显式 `csiNNNNNN`/`NNNNNN.CSI` 一律返回 `unsupported`（不再落入美股或猜测 SH/SZ），并防止未登记 `csi000300` 被等价成已登记 `000300.CSI` alias；存储 `_derive_canonical_id` 对 unsupported 输入返回 NULL，避免进入持久化 canonical 桶。
- [修复] 在 seed、build entry 与 runtime candidate 三层严格校验 alias 唯一性与整数 popularity：NFKC/casefold 等价 alias 跨条目冲突被拒绝（无静默覆盖），非负整数之外（小数/布尔/负值/字符串）popularity 一律拒绝，整数 `100` 保持有效。
- [修复] 收敛已登记 CSI 显式身份在 resolver、任务去重键与历史候选中的分裂：`csi930955`/`930955.CSI`/`CSI930955` 统一解析为 parser canonical `csi930955`，未登记 `csi930956`/`930956.CSI` 保持既有降级语义；`is_code_like()`、REST/watchlist 输入边界与完整 Pipeline 透传不变。
- [修复] 阻止任意更新的非 bundled 指数候选（含 legacy `static` 子集）在 remote 缺失/损坏时以 active-index 子集覆盖 bundled baseline：所有非 bundled 候选必须为 bundled active-index canonical 集合的合法超集，否则回退 bundled 并记录 WARNING。
- [新功能] 桌面端全局右上角增加更新入口，与设置页共用更新状态；普通浏览器 WebUI 不展示，且不会在挂载时重复触发后台检查。
- [修复] 桌面端右上角更新入口与设置页共用检查中状态，避免一侧检查时另一侧仍可重复触发 GitHub Releases 检查；主进程手动检查路径同步增加 in-flight 防重。
- [新功能] Web 自动补全与搜索放行已登记指数（注册中文名/`sh`/`sz` 前缀/`csi`/`.CSI` 显式形式均可检索与提交），热门候选仍仅股票；`/analyze` API 对显式指数输入构造结构化 `AnalysisTarget`（INDEX 用 `canonical_id` 去重，与同码个股互不折叠，CSI alias 收敛），未登记 CSI 单请求返回明确 4xx、异步批量仅该目标进入响应 `rejected` 列表；指数 target 经任务队列贯穿到 Pipeline `process_single_stock`，`DecisionSignal` 以 `market_override="cn"` 落库并有真实分支测试。
- [修复] `/analyze` 在解析前按 strip 后非空原始 token 数限制 50 上限，rejected/duplicate token 也计入，防止用拒绝或重复 token 绕过批量上限；以唯一 `is_single = len(stock_codes) == 1 and not rejected_entries` 统一驱动 metadata、409 与单任务 202，duplicate+rejected 混合批次不再误返 legacy 409（单 duplicate 仍 409、部分 rejected 仍 202、全 rejected 仍 400）。
- [新功能] 报告 meta 补充可选 `asset_type`（`stock`/`index`），由后端 canonical code 经 `parse_analysis_target` 生成权威类型；指数报告在 Web 报告页与 Chat 自选入口隐藏 stock-only 自选操作，裸同码股票（如 `000016`）保持股票行为，market review 与旧客户端可缺省。
- [修复] Web 批量分析把 accepted/duplicates/rejected 三类计入确认数，含 rejected 的完整 chunk 继续提交下一 chunk 而非误报 incomplete，最终以 warning 展示拒绝数量与首个拒绝原因（中英文文案）。
- [修复] 历史筛选/删除/计数与 stock-bar 对已登记指数按 parser canonical 身份隔离：`sh000016`/`SH000016`/`000016.SH` 等显式形态互相可达（lowercase canonical + uppercase legacy canonical + 显式 alias），但永远不命中同码裸股票，裸码查询也不会命中指数记录；同一指数多条显式形态旧记录在 `/history/stocks` 合并为一行并计数全部形态，无记录删除仍返回 `deleted=0`。SH/SZ/CSI 共用同一 parser 分支，股票 alias、港股与海外市场行为不变。历史列表、历史详情与 stock-bar 对已登记指数（含旧 uppercase/显式 alias 持久化记录，如 `SZ399300`、`000300.CSI`）的 API `stock_code` 一律输出 parser canonical（`sh000300`/`csi930955`）。
- [改进] 任务列表/SSE 事件、历史列表项与 stock-bar 项追加可选 `asset_type`（`stock`/`index`）：任务侧从已提交的 `analysis_target` 透传（不重新猜测），历史与 stock-bar 侧由持久化 `record.code` 经 `parse_analysis_target` 生成；旧客户端与 market review 可缺省，字段可选追加不破坏既有契约。
- [修复] Web 首页与自选工作区改用资产感知身份键：任务/报告/历史的 `assetType` 优先，且被后端保证为 parser canonical 的代码只做**大小写折叠**（`SH000016`→`sh000016`），禁止再用前缀/后缀正则猜 canonical（否则 `000300.CSI` 会被误猜成 `csi000300`、`sz399300` 被误当成独立 canonical，违反注册表唯一判型真源）；仅 watchlist 原始字符串缺少类型时，才用已加载 `stocks.index.json` 的 `assetType=index` 行 canonical/display/显式 alias 精确命中（不先 normalize、不用前缀正则猜测；加载期间禁用批量分析，加载失败或请求超过 10 秒时按既有股票语义 fail-open）；行选中、active task 与完成自动选中按资产类型分桶，`sh000016` 指数行与 `000016` 股票行状态独立，完成后自动选中正确 canonical 指数报告。
- [修复] Chat 消息恢复、发送与报告追问对显式 SH/SZ/CSI 已登记指数统一按注册表 canonical 判型并覆盖默认 LiteLLM 与 Codex：所有 Chat 后端首帧加载 registry，加载期间延迟 URL/历史恢复并禁用发送，settle 后 `sh000016`/`sz399001`/`000016.SH`/`930955.CSI`/`csi930955` 只产出一个 lowercase canonical；后端 `resolve_stock_scope`、工具守卫与 cache key 复用 parser `INDEX` 身份，保持指数与裸同码股票隔离；未登记、空 registry 或加载失败时维持既有股票 fail-open，绝不按前缀猜指数。
- [修复] 选股结果持久化恢复：选股页新增历史记录区块，任务完成后保留 run_id，刷新页面可从历史 API 恢复上次选股结果（此前刷新后结果丢失）。
- [修复] Web/API runtime scheduler 使用跨平台独立进程执行分析，并在默认 45 分钟硬超时或服务停止后清理进程树；停止返回后不再派发新的自动任务，避免一次卡死阻断后续调度。
- [改进] Tavily 搜索深度由 `advanced` 调整为 `basic`，降低搜索 credit 消耗（#2314）。
- [修复] Web 的 axios 依赖升级至 `^1.18.0`，桌面端通过 override 固定 js-yaml 为 `4.3.1`，纳入依赖安全更新（#2256、#2254）。

## [3.31.0] - 2026-08-23

### 发布亮点

- feat: Agent 工具调用新增按类别和单工具配置的超时契约，并补齐防重试、协作取消、并发预算与热重载一致性。
- feat: 股票名称解析、`canonical_id` 双写和 A 股指数多数据源路由共同完善股票身份与行情降级链路。
- improve: 新闻检索为空时在报告中如实披露证据边界，Anspire 默认覆盖全球区域，公共 SearXNG 实例改为显式启用。
- fix: 定时任务恢复、无报告失败反馈、通知发送和大盘复盘历史/诊断信息进一步收敛，减少静默失败与误导展示。
- security: 桌面端升级 `builder-util-runtime`，修复 CVE-2026-54673 涉及的重定向凭据头信息泄露风险。
- docs: 增加 xAI Grok 的 LiteLLM 配置示例、Grok Bot 集成说明与可复用 Skill。

### 变更明细

> **台股波段流水线的数字只认一处**：本段的「逐笔新台币现金流」条目与 `docs/tw-swing-pipeline.md`。
> 本段其余条目里的 headline 数字（`+10.30%`／`+10.47%`／`20.7%`／`20.9%`／集中度 `106%`／
> 固定 `0.6%` 来回成本／`Sharpe 1.22`／`12.34x` 等）是**开发过程中被后续修正推翻的旧版，一律作废**，
> 保留只为记录踩过什么。**不要引用它们**；引用前一律回上述两处对齐。
> 已删除的 `backtest_screen --idle-to-bench` 相关叙述已从本段移除（该 flag 已不存在）。

- [修复] **排程器的 signal handler 会自我死锁，而失败完全无声。**`GracefulShutdown._signal_handler` 在 handler 里 `with self._lock` 并呼叫 `logger.info`——signal 是在主执行绪递送的，`threading.Lock` 不可重入，而 `logging` 的 per-handler 锁虽然是 **RLock**（对持有者可重入，所以单执行绪不会死锁——实测重现不出来），跨执行绪仍会等。**确切机制需要两条执行绪**：背景执行绪持有 logging 的 RLock 后想要 `self._lock`，主执行绪在 handler 里持有 `self._lock` 后想要那把 RLock ⇒ 互等。卡死行程的 12 条执行绪全停在 `futex_do_wait`、零对外连线，与此相符；两执行绪重现脚本实测旧版卡死且对后续 SIGTERM 无反应、本版 0.00s 乾净退出。推论是**光把 logging 移出 handler 不够，`self._lock` 也必须移除**。**实际发生过**：2026-08-23 10:35:33 `dsa-schedule.service` 收到 SIGTERM，印出「收到退出信号 (15)」之后行程再无下文，systemd 仍报 `active (running)`，当天 14:00 与 2026-08-24 14:00 的排程都没有触发，「调度器已停止」也从未印出。handler 现在只设旗标与 `shutdown_signal`，讯息移到主迴圈观察到旗标之后再印；`should_shutdown` 也不再取锁（读一个 bool）。新增 `tests/test_scheduler_signal_safety.py`——`GracefulShutdown` 之前**零覆盖**。
- [修复] **`scripts/backfill_price_change_sign.py` 逐年切窗时漏掉每档每年的第一个交易日。**`lag(close)` 在每个年度窗口内对第一列是 NULL，被 `prev_close is not null` 滤掉 ⇒ 实测漏 **6,526 列**（2013-01 ~ 2026-01，几乎全部落在一月头几天）。修法与 `market_data/adjust.py::infer_rows` 同款：读取视窗往前多含 30 天算 `lag`，**更新仍只限目标区间**（`market_data/AGENTS.md` 早就记过这个坑）。已重跑补上那 6,526 列，重跑后 dry-run 为 0；独立复核 2013+ 全期已无错正号。新增 `market_data/tests/test_backfill_change_sign_sql.py`——这支脚本之前**零覆盖**，这正是年度边界能漏掉的原因。已知范围限制写进 docstring：pre-2013 有 283,482 列符号仍错，刻意不补（那段没有复权因子，硬补会让除权息日拿到已知是错的方向）。
- [修复] `_augment_historical_with_realtime` 向时钟问两次。它先 `get_market_now(market)` 取交易日，再让 `infer_market_phase(market)` 内部**又读一次**——跨盘别／跨午夜边界时两次答案可能不一致，而且测试 patch 掉 `src.core.pipeline.get_market_now` 之后仍然控制不住第二次。现在只读一次并把 `market_now` 传进去。**这不只是洁癖**：`tests/test_pipeline_realtime_indicators.py` 有两个测试因此在平日凌晨必红、周末必绿（2026-08-23 週日 CI 绿 / 2026-08-24 週一 01:40 本机红，main 上同样红），因为北京 00:00~09:30 对 `cn` 是 PREMARKET，函数直接早退。
- [测试] 补上 PREMARKET guard 自己的覆盖（`TestPremarketGuard`）。那道 guard 之前**零覆盖**，这正是上面那个漏 mock 能一直没被发现的原因。两个案例成对：PREMARKET 不得凭空造出当日 K 棒（盘前的「即时价」其实是昨收），POSTMARKET **仍要**补（那笔即时价就是当日收盘，DB 日线还没进来）——把 guard 写成「非盘中一律挡」会让后者红。
- [修复] **台股大盘复盘走不到大盘海报分支。**`src/share_image.py` 的 `_MARKET_RE` 只认简体「大盘复盘」，而 zh-TW 实际输出是「大盤**複**盤」（複 U+8907，不是復 U+5FA9——只补「復」修不到任何真实报告，输出见 `src/core/market_review.py` 的 zh-TW 标题表）；`_MARKET_SCOPE_RE` 与 `_market_label_for_region` 也都不认 `台股` / `tw`。三处补齐。`tw` 用 lookbehind `(?<![.\w])tw\b` 挡掉代码后缀——裸 `\btw\b` 会命中「台積電 2330.TW 分析報告」，让个股标题被判成有市场范围、连带改变 `_market_segments` 的分段行为；上游那串 `cn|hk|us|jp|kr` 原样不动（它同样会命中 `0700.HK`，但那是既有行为）。新增 `tests/test_share_image_tw_market.py`——这条路之前是**零 zh-TW 覆盖**。
- [修复] `name_to_code_resolver` 的市场推断补上 tw/jp/kr。上游 #2245 引进的 `_infer_code_market` / `_MARKET_ORDER` 只有 a/hk/us，而 `_find_codes_for_name` 对 market 为 `None` 的代码是**直接丢弃**——台股与日韩代码在那条路上等于不存在。后缀判定复用 `market_symbol_utils.get_suffix_market`（唯一真源，不另写一份），裸 4 位→tw（上游三个市场都不用 4 位，不冲突）。**裸 6 位维持 `a`**：无法区分 A 股与韩股（005930 与 000001 都是 0 开头），猜错方向比不猜更糟。新市场**附加在排序表尾端**而不是插队，既有三个市场的相对顺序不动。已知未覆盖：带字母的台股 ETF（`00631L` / `00631L.TW`）仍回 None，原因与修法写在 docstring。
- [修复] `ReportMeta.report_language` 的 OpenAPI 描述漏 zh-TW；改由 `SUPPORTED_REPORT_LANGUAGES` 推导，同型的另两处（`src/analyzer.py` 栏位注解、`src/market_analyzer.py` docstring）一起改成不写死字面。
- [测试] `tests/test_storage.py` 两个冷启动测试的 `join(timeout=5)` 放宽到 60s。那 5 秒是墙钟上界、不是被验证的性质（release 之后跑的是真的 `create_all`，忙机器上 9.07s），实测 load 4.10 红 / 2.63 绿。**`competitor_done.wait(timeout=0.2)` 刻意不动**——那条断言的是「竞争者此刻仍被挡住」，值越大越严格。判别负载假红与回归的方法已记入 AGENTS.md §10。
- [文档] `src/search_service.py` 的 Anspire `region_mode` 补上取值语意（0 国内／1 海外／2 混合，官方文档）。上游 v3.30 把默认从 0 改成 2，方向是**放宽**覆盖面——限制版反而是合并前的值。本 fork 未配 key，该 provider 不会进 `_providers`。
- [修复] **分享图被印上上游作者的个人小红书账号与可扫的追踪 QR。**上游 v3.30 的 `share_image_branding_from_config()` 在没有任何 `SHARE_IMAGE_XIAOHONGSHU_*` 设定时会套用内置预设 `@霸天土小豆` + `src/assets/share_image/xiaohongshu_qr.jpg`，本 fork 一项都没设 ⇒ **每一张**分享图都带第三方账号，包含合并前就存在的 Web「分享」按钮（`apps/dsa-web/src/api/history.ts`）——那条路的输出在合并后静默改变了，而上游测试自己断言这个预设，所以没有任何测试会抓到。已把 `DEFAULT_XIAOHONGSHU_HANDLE` 与 `DEFAULT_XIAOHONGSHU_QR_PATH` 留空（**不删那两行**：留着，下次上游改动这里会撞成看得见的冲突，而不是静默把账号接回来），atomic-pair 逻辑原样保留，设了自己的 `SHARE_IMAGE_XIAOHONGSHU_*` 照样画。行为分歧：全部留空时上游显示作者账号、本 fork **不画这张卡片**。`.env.example` 同步改掉那个拿别人账号当范例的注释；`PROJECT_URL`/`PROJECT_REPOSITORY` 指向上游 repo 是既有的项目出处标注，刻意不动。
- [改进] **涨跌家数改取 `twtazu_od` 的「股票」列，不再取「整體市場」。**后者含权证／ETN，分母约 13,181，而权证带杠杆又不受涨跌幅限制，会主导寬度判读——同一份快照「整體市場」是 `3144 漲 / 9578 跌 / 355 跌停`，「股票」是 `342 / 671 / 10`。报告写的是「市场宽度」，那指的是股票，不是股票的衍生品。
- [新功能] **端点过期时改由 `market` schema 自算涨跌家数**（`data_provider/tw_breadth.py`）。上一版加了日期比对之后，`twtazu_od` 冻结期间台股大盘复盘就完全没有寬度资料；现在退回本地前复权收盘自算（实测 2026-08-21：上市普通股 1,075 檔，漲 589 / 跌 382 / 平 104——与当日指数 +0.65% 一致，而被拒收的冻结值是 `3144/9578` 那组反向的数字）。**口径与端点不同，刻意不掩盖**：范围是上市普通股（`price.market` 全为 NULL，上市名单只能取 `stock_info`），基准是 `price_adjustment` 前复权收盘（等效于官方参考价），且**不提供漲跌停家数**——判定漲跌停需要当日官方参考价与 ±10% 规则，而 ETF/ETN 不受限制，用「日变动 ≥ ±9.5%」代理的数量级与官方对不上（实测 2026-07-31 官方 64 檔、代理 217 檔），宁可留空让 `has_limit` 判成缺资料。`market.price` 自己停更时也一律拒收，不重犯 `twtazu_od` 那个错。
- [chore] 新增 `scripts/backfill_price_change_sign.py` 并已回补 **1,608,127 列**（2013~2026 上市）。只改符号不动绝对值（绝对值是官方公告值），方向取 `sign(close - prev_close × factor)`——`prev_close × factor` 就是官方参考价，所以除权息当天的方向与官方一致；用 `close - lag(close)` 重算会把那些天改错。上柜列本来就带号，`change > 0` 的条件天然把它们排除。幂等（重跑 dry-run 为 0 列），且目前没有任何程式码读这一栏（`to_daily_frame` 已改成不读），所以这是资料卫生而非修正行为。
- [修复] **台股大盘复盘的涨跌家数冻结在 2026-06-05，连续 20 份报告印同一组数字。**`data_provider/twse_fetcher.py::_fetch_breadth` 打的 `openapi.twse.com.tw/v1/opendata/twtazu_od` 会停止更新却照样回 HTTP 200 与结构正确的 JSON（实测 `出表日期=1150605`，冻结 79 天），而程式完全不检查该栏。`reports/market_review_*.md` 自 2026-07-11 起 20 份都印 `3144/9578/459`、`43/355`，LLM 在上面叠出「跌停 355 家恐触发融资断头」这类完全虚构的叙事——2026-08-21 那份说「上涨家数占比 25%、亏钱效应较强」，当天加权指数其实 +290.55 点。现在以同一次调用里 FMTQIK 给出的最新交易日逐次比对，不符即拒收；**拿不到参照日期时一律拒收（fail closed）**。家数缺失时保持 0，`_build_stats_block` 的 `has_advance_decline` 按 truthiness 判定会正确渲染成「没有资料」而不是「资料是零」。成交额与三大法人不受影响（实测仍为最新交易日）。
- [修复] **`market.price.change` 对上市股票遗失正负号，害每个下跌日被算成上涨。**TWSE `MI_INDEX?type=ALLBUT0999` 的 `漲跌價差` 只有绝对值，方向在独立的 `漲跌(+/-)` 栏（实测 2026-08-21：`+` 706 / `-` 521 / 空 139 / `X` 11）；`market_data/crawler.py::crawl_price` 的 `to_numeric(errors="coerce")` 把该栏变 NaN 后再被 dropna-all 丢掉 ⇒ 符号永久遗失。2026 年至今 95,211/353,563 列（27%）与 `close - lag(close)` 反号；上柜走 TPEx JSON（`漲跌` 本身带号）未受影响。下游 `market_repo.to_daily_frame` 用 `close - change` 回推昨收，于是 `pct_chg` 在上市股票的下跌日全部翻正（2330 於 2026-08-19 收 2350、前日 2380，实际 -1.26% 被算成 +1.29%），而这个栏位会进台股个股分析的 LLM prompt。两处都修：crawler 保留符号（`X` 无比价落 NULL，不是 0），`to_daily_frame` 改用 `close.shift(1)` 推昨收、**不再读 `change`**，因此历史列的旧值不影响结果、无须回补 740 万列。视窗第一列没有前一日 ⇒ `pct_chg` 为 NaN（缺资料）。
- [修复] 日线序列 API 把 NaN 送进 JSON。`src/services/stock_service.py` 的 `float(x) if x else None` 对 NaN 是 True（`bool(nan)` 为真），而 0 是合法读数不能当缺资料；改用 `_opt_float`（NaN/None → null，0 保留）。上一条让视窗第一列的 `pct_chg` 必然是 NaN，这条是它的必要配套。
- [修复] **缺资料的涨跌停家数一路以 0 泄漏进 LLM，害它写出「涨跌停皆為0，顯示市場情緒溫和」的虚构结论。**2026-08-24 的台股复盘（`reports/market_review_20260824.md` 第 11、24 行）实证：本地宽度来源 `tw_breadth.closing_breadth()` 刻意不提供涨跌停家数（docstring），渲染层的 `_build_stats_block` 用 `has_limit` truthiness 判定、正确没印那一列，但 **餵 LLM 的 prompt 区块（中英两版）与结构化 payload 都无条件印 `limit_up_count`/`limit_down_count`**，于是零值从那一层漏进去。抽出 `_breadth_availability()` 一组判定，报告表格、prompt 区块、payload 三处共用：缺资料的键直接不给（而不是给 0），web 端字段全 optional 渲染成 `-`、分享图按 truthiness 过滤少一张卡。新增 `tests/test_us_market_path.py` 两例（缺资料不出键 + 有读数照常流出）。
- [修复] **`to_daily_frame` 的 `pct_chg` 用未还原价，除权息日的价格断崖被算成真实下跌。**PR #7 把公式从 `change/(close-change)` 改成 `close.shift(1)`（修符号反向），但没套 `market.price_adjustment` 因子；`market_data/AGENTS.md` 明写「`price` 是未还原价，算报酬前一律先套因子」。现在 `market_repo.adjustment_multipliers(stock_id)` 按檔取事件日因子（`price_adjustment` 的 PK 是 `(stock_id, date)`，同日多事件在写入端由 `merge_adjustment_rows` 按来源优先序收敛）、`to_daily_frame(df, event_factors=...)` 以 `close / (prev_close × factor) − 1` 还原（无事件日乘 1，行为同旧版）；`MarketDBFetcher` 取因子失败会 raise 让链 fallback yfinance（不默默回未还原报酬）。2458 义隆 2026-08-21：未还原 -3.77% → 还原后约 -0.72%。新增 `market_data/tests/test_market_db_fetcher.py` 与 `test_price_change_sign.py` 因子案例。
- [修复] **三大法人（BFI82U）与两支上柜（TPEx）端点没有日期检查。**涨跌家数 `twtazu_od` 冻结 79 天的事故只能发生在它身上是因为只有它加了比对（PR #7），剩下三个端点都是「端点的东西直接收」。现在三者都比对 FMTQIK 的最新交易日（BFI82U 带西元 `date`、TPEx 两支带民国 `Date`），不符/缺参照一律拒收（fail closed），部分降级语义不变。新增 `tests/test_twse_breadth_freshness.py::EndpointFreshnessTestCase`。
- [修复] **`_resolve_overview_date` 读三次时钟。**先 `infer_market_phase`（内部读一次）再 `get_market_now`/`get_effective_trading_date`（各读一次）——跨午夜/跨盘边界时 phase 与日期可能自相矛盾，与 PR #12 修 `_augment_historical_with_realtime` 同一形状。现在读一次 `now` 再显式传给每个判定（两个函数本就收 `current_time`）。新增 `test_overview_date_reads_the_clock_once`，并更新钉旧签名的既有测试。
- [修复] **韩文多市场海报静默丢掉中国段。**`src/share_image.py::_MARKET_SCOPE_RE` 的韩文 A 股选项写成「中国\s*A주」（简体「中国」+韩文「A주」混种），而 `market_review` 实际输出全韩文「중국 A주 시황 리뷰」，判定回 False、`_market_segments` 退回 fallback。改为 `(?:중국|中国)\s*A주`。新增 `test_korean_cn_scope_matches_the_real_korean_heading`。
- [修复] **`_MARKET_LABEL_PATTERNS` 漏补台股，`_market_label('台股大盤複盤')` 回空字串。**PR #11 补了 scope regex 与 `_market_label_for_region`，漏了这张表；补「台股」条目（`台\s*股|台灣|taiwan|대만`）并在 `_market_region_for_segment` 的 label→region 表加 `"台股": "tw"`。新增 `test_tw_label_resolves_from_the_report_title_alone` 与 `test_tw_segment_resolves_to_a_region`。
- [修复] **备援价格路径把「无比价」写成 0。**`crawler.crawl_price` 对 `漲跌(+/-)=X` 写 NULL（0 是平盘、是读数），但 `sources.crawl_price_backup`（STOCK_DAY_ALL）把那些列渲染成 `Change='0.0000'`、直接 to_numeric 入库。实测 2026-08-21 的 2458：官方 MI_INDEX 是 `X`/`0.00`，备援源给 `0.0000`。现在 `crawl._price_all` 在采纳备援后按 DB 前根收盘辨識：Change==0 且收盘相对前根有动（或该股当日无前根＝新上市首日）⇒ 视同 X 改 NULL；真平盘必有前根且收盘不动、不受影响。新增 `test_price_guard.py` 三例 + 一条验证 conn 确实传进遮罩的链路测试。
- [修复] **成交额与三大法人的单边和冒充「上市+上柜合计」，外资净额方向会反过来。**`TwseFetcher.get_market_stats` 原本「把活着的那几份相加」——实测 2026-08-21 上市外资净额 **+283.05 亿**、上柜 **-7.00 亿**、合计 +276.05 亿，两侧反向；BFI82U 冻结时 `foreign_net` 就变成 -7.00 亿，报告照着写「外资卖超 7 亿」，而事实是买超 276 亿，**而这是复盘里最常被引用的那个数**。成交额同理：缺上柜 -21%、缺上市 -79%，LLM 会读成「量能急冻」。这个部分降级契约本身是既有的（原本只有网路失败会触发，罕见），但上一条的端点新鲜度检查让它变成常态触发（FMTQIK 通常比 BFI82U 与 TPEx 两支早发布）。现在这两组各自要求上市与上柜**双边齐全**，任一边缺就整格作废，让 `_breadth_availability` 判成没有资料；家数、成交额、三大法人三组之间仍各自独立降级。`tests/test_twse_breadth_freshness.py` 的 `StatsPartialDegradationTestCase` 原本把单边和断言成正确行为，已整个重写为 `SummedFieldCoverageTestCase`（正向和、两个方向的过期各自作废、分组降级仍成立）。
- [修复] 缺资料的栏位只是从 prompt 消失，LLM 分不出「缺资料」与「读数是 0」。`_build_review_prompt` 的资料边界区块原本只看 profile 能力旗标（整个市场有没有这类资料），现在有能力旗标但个别栏位当场缺席时也逐栏明说（如「本場次無漲跌停家數資料，視為未知，**不得當成 0 家**」），对齐 prompt 顶端本来就有的「未提供…不要编造或过度解读」那条纪律。三大法人刻意不列：profile 没有 `has_institutional` 旗标，无法区分「结构上没有」与「今天缺」。
- [修复] 三大法人是唯一读数时，prompt 的市场概况区块会变成没有标头的裸 bullet（`stats_block` 只在其他栏位非空时才被赋成带标头的字串，法人却是 `+=` 接上去）。中英两版都改成先并进 `stats_lines` 再统一组装。
- [测试] `adjustment_multipliers` 的「同日因子相乘」测试是假守门：`price_adjustment` 的 PK 是 `(stock_id, date)`，同日两列根本存不进去，所以 `.prod()` 恒等于 `.first()`——把它改成 `.last()`/`.first()`/`.max()` 测试全绿。改为钉住三件真正会坏的事（只取该檔、不跨日累乘、index 唯一——`to_daily_frame` 用 `Series.map`，重复 index 直接抛 `InvalidIndexError`），并把函式 docstring 的「该日全部事件的 factor 积」改写成实际契约。
- [文档] `market_data/AGENTS.md` 踩雷区补一条：`price.change` 全历史里约 3.2 万列「说平盘但有动」是旧爬虫把上游 `X`（无比价）列存成绝对值 0 的结果（12/12 抽样复核 MI_INDEX 均为 `X`/`0.00`），非爬取层新问题；`to_daily_frame` 与任何报酬计算都不读这一栏，修复是资料卫生。
- [文档] 新增 `docs/tw-swing-hindsight-2026-08.md`：2026-07-24 ~ 08-05 的 4 笔波段决策、5 笔盘前 regime 与 7 档筛选候选量到 2026-08-21 的中途对帐。**4 笔全部未到期**（60 交易日 horizon），所有跨笔聚合标为 inconclusive；文件的「不该改」段刻意长于「该改」段。
- [新功能] 合并上游 v3.30.0（`ed848da6`..`b4770225`，22 commits／104 檔）：新闻检索为空时在报告中如实标注、大盘复盘记录实际生成后端（provider/model 身分解析贯穿 LLM transport）、`stock_daily` 新增 `canonical_id` 列与自愈迁移、股票实体解析增强、agent 分类别工具超时与优雅降级、SearXNG 公共实例发现改为默认关闭、持久化排程恢复，以及 CVE-2026-54673 安全修复。裁决与移植细节见 `docs/upstream-sync-2026-08-23.md`。
- [修复] **上游新模組 `src/services/empty_news.py` 的语言集合不含 `zh-TW`，在本 fork import 即抛 `RuntimeError`。**该模块自带 `set(_DISCLOSURES) != set(SUPPORTED_REPORT_LANGUAGES)` 的硬性守门，而本 fork 的受支持语言含 `zh-TW`。已补齐 zh-TW 两条披露文案（未设定搜寻管道／零命中），并在 `tests/test_notification_empty_news_disclosure.py` 的 `EXPECTED` 补上对应字面——该测试逐 renderer、逐 template 验证文案真的输出，补之前 7 red、补之后 38 passed。
- [修复] 上游 #2241 对 `_call_litellm` / `_AllModelsFailedError` 的改动移植到本 fork 的 `src/llm/client.py`（这两者已随 `GeminiAnalyzer(LLMClient)` 拆分下移）：`return_generation_result` 参数、`last_provider` 栏位、fallback 路由身分提升。缺 `return_generation_result` 会让 auto-merge 进 `analyzer.py` 的 `generate_text_with_metadata`（大盘复盘后端记录）在执行期直接 TypeError。
- [新功能] 合并上游 v3.28.0 + v3.29.0（`aa68d45d`..`a8f084bf`，28 commits／233 檔）：AlphaSift 选股内化为 `src/services/screening/`、Web/API 按市场触发大盘复盘（新增请求级 `region` 栏位）、报告分享图与 Web 一键分享、offline pytest watchdog，以及 longbridge 位置参数、yfinance 裸港股码、腾讯日 K 兜底等修复。裁决原则与逐项分歧见 `docs/upstream-sync-2026-08-05.md`。
- [修复] **合并上游後台股大盘复盘静默失去盘面信号。** 上游 v3.29 把 `_build_stats_block` 的盘面信号改成由 `_supports_market_light()` 闸住（合并前是无条件产生），而 `MARKET_LIGHT_REGIONS` 不含 `tw` ⇒ 台股复盘整组失去「盘面信号／信号依据／操作建议」，`tw,us` 组合还会误取美股分数当 primary，且 `build_current_snapshot("tw")` 直接抛 `ValueError`。**报告照样生成、测试照样绿**，是典型的静默降级。`tw` 已加入 `src/schemas/market_light.py` 与 `src/services/market_light_service.py` 的市场集合（告警范围 `MARKET_LIGHT_ALERT_REGIONS` 维持 `cn/hk/us` 不变）；实测台股快照 score=45／data_quality=ok。
- [修复] **缺资料被渲染成 0。** 大盘复盘只有三大法人而无涨跌家数时（台股常见），`_build_stats_block` 会印出 `上涨/下跌/平盘 0 / 0 / 0` 与 `两市成交额 0 亿`，把「没有资料」表达成「资料是零」。拆成 `has_breadth` / `has_institutional` 两组独立判定，表头在任一表格列存在时才输出；en 路径同步修正（不再输出 `Advancers 0 / Decliners 0`）。
- [修复] **`field_validator` 抛 `ValueError` 的欄位拿不到 422，一律回 500。** `api/middlewares/error_handler.py` 把 `exc.errors()` 直接塞进 `JSONResponse`，而 `value_error` 类型的项带着**原始 `ValueError` 物件**（不是字串）⇒ 序列化失败後被 general handler 接成 500。上游新增的 `region` 是这条链上第一个会抛 `ValueError` 的 validator，所以文件明写的 4xx 实际回 500（实测 `region=eu`／`tw,,us`／`both,tw` 全为 500）。改用 `jsonable_encoder`（与 FastAPI 自带 handler 同一套），一处修掉所有现有与未来的 validator。
- [修复] **`screening_service` 的 `except BaseException` 会吞掉离线测试的连外守门。** `_fetch_constituent_sources` 在 `future.result()` 外围捕 `BaseException`，连带吞掉 `tests/test_screening_api.py` 刻意继承 `BaseException` 的 `_OutboundBlocked` ⇒ 未来漏一格 mock 仍然全绿，只有对方收了连线不回时才在 CI 挂死。收窄为 `except Exception`，一般外部来源失败仍照常隔离降级。
- [改进] `MARKET_REVIEW_REGION` 与请求级 `region` 支援 `tw`，`both` 展开为 `cn,hk,us,tw,jp,kr`；Web 市场选择器、`MarketReviewRegion` 型别与 zh-TW 文案同步补齐台股。两条路径的顺序语义**刻意不同**：持久化设定保留输入顺序（`tw,us` = 台股先复盘），请求层按 canonical 排序（Web 选择器送的是 checkbox 状态、与点击顺序无关），已写进 docstring 与 OpenAPI 描述。
- [修复] **无读数的 Market Light 快照会流进结构化契约与决策上下文。** 评分器在三个维度都不可用时仍回一个分数为**预设 50** 的完整快照；`build_market_review_payload` 又会在参数为 None 时自己补建一个（`or` 直接抵销呼叫端的过滤），于是那个 50 一路进 `payload["market_light"]`、`market_review_payload` API、历史纪录，并被 `daily_market_context` 读成「conservative／等待确认」——一个没人量过的市场判断。闸门改放在结构化契约的**唯一入口**，下游三条路径一次全对。判准是「有没有任何维度 available」而不是 `data_quality`：后者只要 index 维度缺就标 unavailable，会误杀「只有涨跌停」这种真读数（limit 维度评出 10/100）。
- [修复] **`NaN`／`±inf` 的指数涨跌幅会通过可用性检查并把分数钉在 100 或 0。** `index_available` 只排除 `None`；`NaN` 因比较恒假而落在 `min()` 上界得 100，`+inf` 得 100、`-inf` 得 0，而这些看起来都像真读数。加 `isfinite` 过滤。
- [修复] **共用 validation handler 仍能透过 `loc` 回吐并放大输入。** 只截 `msg` 不截 `loc` 等于把路径从值搬到键——mapping 型别栏位的**非法 key** 会被 pydantic 原样放进 `loc`，送 100,000 字元的 key 就得到 100KB 回应。`loc` 现在限 16 段 × 128 字元。
- [修复] **`WatchlistRequest.stock_code` 没有长度上限**，`_validate_and_normalize_stock_code` 会把整个非法代码嵌进 HTTPException 讯息，送 100,000 字元得到 100KB 的 400 回应。补 `max_length=32`（与 `decision_signals` 的既有约定一致；最长合法形态远在 32 以内）。
- [测试] 新增 `tests/test_error_handler_validation.py`（7 个：422 而非 500、不回吐 `input`、不随输入放大、只暴露 allowlist 栏位、笔数上限、`loc` 不外泄）、`tests/test_screening_api.py::OutboundGuardPropagationTestCase`（2 个）、`TestBuildStatsBlockRegionAndDataSplit`（13 个：台股市场集合、逐列资料可用性、评不出来就不给分，含 en/zh 两语）、`TestMarketLightReachesEveryConsumer`（4 个：无读数快照不得进 result／structured payload，含 NaN/inf）与 `test_normalize_market_region_accepts_tw`。**每一组都做过 mutation 检查**——把修法改回旧写法必须立刻红，没过这关的测试不算守门。
- [文档] `docs/tw-swing-pipeline.md` 新增「族群代理」量测（2026-08-03，739 交易日）：**费半不是记忆体的代理**——台湾记忆体篮子（华邦电／南亚科／旺宏／晶豪科／群联等权，前复权日报酬）对费半同日 **r=0.123**，对韩国记忆体（SK海力士＋三星等权）**r=0.577**、对 SK海力士 0.554、对**隔夜美光 t−1 r=0.364**；韩台是**同步不是领先**（同时段交易，落後项 r=0.060、领先项 r=−0.115）。条件分布「韩国单日 ≤−3%／−5%／−7% 後台湾次日」均值 −0.43%／−0.56%／−1.35%（基准 +0.23%），方向一致为负且随跌幅加深更负，但三个门槛的 bootstrap CI **全部跨零**、下跌比仅 52~57%（基准 50%）⇒ **判 inconclusive，只能当「不下注」的理由，不能当方向性预测**。另记录「韩跌>5% 同日台涨>5%」在 739 日里 **0 例**（放宽 ±3% 仍 0 例）⇒ 2026-08-03 的 19pp 单日反向**无样本外前例、收敛方向不可预测**。这一条是使用者指出的缺口，不是流程自己发现的。
- [修复] **`YfinanceFetcher` 的即时行情把美股个股的涨跌幅算成反向。** `fast_info` 有两个前收栏位，实作取的 `previousClose` 对**美股个股**在盘後／週末会退化成接近 `lastPrice` 的值：2026-08-03 实测 MU 用它算出 **+1.30%** 而真值是 **−5.90%**（正规前收 `regularMarketPreviousClose` 874.66），AAPL **+0.51% vs −7.35%**（差 7.86pp）。**不报错、不缺栏位，只给一个反向的数字**，而下游拿它当「隔夜美股方向」判 regime。抽出 `_prev_close_from_fast_info()` 优先取 `regularMarketPreviousClose`，**两处呼叫点（美股指数路径与个股路径）一起改**——原本是同一段程式码複制两份。修完六檔实测误差全为 0.00pp。顺带修正**原油 `CL=F`**（`previousClose` 79.79 vs 正规 84.67，差 **−5.76%**）与 A 股 `600519.SS`（+0.13%）；港股、台股、`^VIX`、四大指数两个栏位本来就相同，不受影响。另记录一个 API 形状陷阱：`fast_info` 是 **dict-like**，camelCase 只能用 `[]` 取、属性存取要 snake_case，所以原本 `getattr(info, 'previousClose')` 一直回 None，真正生效的是後面那个 snake_case 候选。
- [修复] **`US_INDEX_MAPPING` 缺费半，导致 `SOX` 静默取到别家公司的报价。** `SOX` 符合美股 1-5 字母 pattern ⇒ 被判成个股，而 Yahoo 上 `SOX` 真的存在一档 **Scanbox Asia Pacific Ltd** ⇒ 不报错、有价格、有名字，标的却完全不对；同时 `^SOX` 走不到指数路径会被转成 `$SOX` 而回 None（实测两者皆已复现）。费半是台股盘前判读的核心指标（台股是半导体权重市场），补进映射後 `SOX`／`^SOX`／`sox` 都正确解析为 `^SOX` 费城半导体指数。
- [测试] 新增 `tests/test_yfinance_prev_close.py`（5 个）钉住前收栏位的选择顺序（两者并存时必须取正规收盘、缺失时回 None 让上层走 history 兜底、0 不得盖掉真候选），以及 `tests/test_us_index_mapping.py` 新增 `TestSoxIsAnIndexNotAStock`（费半必须判成指数而非个股，否则会取到 Scanbox）。两个测试都不碰网路。
- [改进] `scripts/overnight.py` 的 `SERIES` 新增**记忆体代理四檔**（`MU` 美光、`000660.KS` SK海力士、`005930.KS` 三星、`^KS11` KOSPI），并按市场分三组输出（`us` 美股昨晚收盘／`kr` 韩股同时段／`cont` 连续与盘前报价）。**原本的 8 檔结构上不可能给出记忆体的正确代理**——只有费半，而费半对台湾记忆体同日 r 仅 0.123（韩国 0.577、隔夜美光 0.364），2026-08-03 就因此把「美光 −5.90%＋SK海力士 −8.79%」的族群崩跌读成「杀盘局限」。同时**修掉一个一直在假告警的日期一致性检查**：旧版把所有序列混在一组比、只排除 `TWD=X`，於是**原油与 VIX 每天都触发「各序列日期不一致」**（两者盘前就报价、日期正常领先美股一天；实测 08-03 报 `[07-31, 08-03]`），而每天都报的警告等於没有警告。现在 `date_warnings()` 只在 `us`／`kr` **组内**比，韩股晚美股一个日历日属正常不告警。记忆体那段**刻意不设 alert 门槛**（不像费半的 −2%）：条件分布 CI 全部跨零 ⇒ 设门槛等於假装它有预测力，只印方向并提示「代理与台股同日反向时不下注」。
- [测试] `tests/test_overnight.py` 从 2 个测试补到 5 个，钉住两类**静默出错**：新增 `date_warnings()` 的分组行为（韩股晚一天不告警／组内不一致仍告警）与「记忆体代理必须在 `SERIES` 里」。原本只测 ADR 折算方向。
- [改进] skill `tw-morning-call` Step 2 新增「每个族群配自己的代理」小节与必查列（`MU`／`000660.KS`／`005930.KS`／`^KS11`），完成条件加上「今天要判的每个族群各自的代理数字」；Step 3 新增「代理与台股背离时不下注」；边界新增盘中判读条目。**修的是 skill 层缺陷不只是漏查**：原 regime 表用「费半连续两日下跌逾 2%」当半导体门槛，对记忆体标的近乎无效（r=0.123）。2026-08-03 实际後果是费半 +0.07% 判「杀盘局限於族群」，而同时间美光 −5.90%、SanDisk −5.09%、SK海力士 −8.79%、三星 −8.76%，台湾记忆体却全数涨停。
- [新功能] 新增 `scripts/intraday_breadth.py`：盘中即时 breadth（Shioaji 批次 snapshot × `market` schema 前复权均线），印流动性池的即时涨跌家数、站上 MA20／MA60、中位涨跌、距 60 日高中位、**涨停锁死档数**；`--codes` 切换成指定族群的逐檔明细。补的是「盘前判读的数字全是前一交易日收盘，但被问『今天怎麼买』时需要现在」这一格。**盘中值不是收盘值**：2026-08-03 盘中 09:50 中位 +3.37%、上涨 445／下跌 100，收盘变成 +0.66%、1229／595（衝高回落把讯号翻面）⇒ 盘中留檔要标时点、`regime` 不可当收盘结论引用，且因预测与结果同日写入必然拿不到防竄改保证，直接标 `exclude_from_scoring`。
- [新功能] 新增 `scripts/kr_tw_memory_watch.py`：盘中监看**台韩记忆体同日背离**（韩 yfinance `lastPrice` × 台 Shioaji snapshot），每 N 分钟採样一次写 JSONL，只在门槛触发时推 Bark（韩国个股 ±3pp／KOSPI ±2pp／台韩价差 ±3pp，用「级距只升不降」去重，同一件事不重推）。补的是 skill `tw-morning-call` Step 2 唯一人工的那一格——韩台**同时段**交易（韩 08:00-14:30 台北时间），`scripts/overnight.py` 只给到韩股前一交易日收盘，而台湾记忆体对韩国记忆体同日 **r=0.577**、对费半只有 0.123 ⇒ 韩国开盘後的方向是记忆体标的当日第一顺位输入，且必须盘中才拿得到。**新记录一个 yfinance 韩股陷阱**：`000660.KS` 的日 K 会整根缺（2026-08-04 实测最後一根停在 07-31、08-03 不见），`previousClose` 也跟著停在 07-31 ⇒ 拿它算涨跌会得到 **−8.79%，那是前一日的跌幅**；只有 `fast_info['lastPrice']` 正确。因此 baseline 一律在**韩股开盘前**用 `lastPrice` 锁住（此时它就是前一交易日收盘），开盘後才启动会拿到当日盘中值当基准 ⇒ 脚本直接拒跑而不是给一个错的数字。
- [文档] `docs/tw-market-position.md` 新增 §三之二「主动式 ETF 能不能当核心：00981A vs 0050」（284 个共同交易日、前复权含配息）：总报酬 +175.2% vs +136.1%，但**报酬／波动 3.92 < 4.19**、最大回撤 **−26.3% vs −15.4%**、beta 1.15 ⇒ **右尾拿得到、风险调整後输**（与 `screen_tw` 组合层 Sharpe 1.07 vs 1.15 同一形状）。累积超额 +18.9% 但 bootstrap 95% CI **[−20.2%, +74.5%] 跨零**、样本仅 **1.1 个独立年** ⇒ inconclusive，而**费用差 1.14pp/年（1.49% vs 0.35%）是确定的**（20 年复利 25.5% 拖累）。季度分解显示超额来源：前四季全赢（+3.7／+11.0／+5.7／+14.9pp），**2026 Q3 第一次遇到下跌就吐回 −12.5pp**。两个天花板：整段历史只活在同期 0050 年化 +113.6% 的极端多头里（无空头样本）；同期 8 檔主动式台股 ETF 有 **00980A +116.7%、00982A +124.9% 都输 0050、00983A 只 +12.9%** ⇒ 00981A 是事後挑出的赢家（存活偏误）。
- [文档] `docs/realtime-board.md` 的「数据来源与时效」表扩成**六市场实测表**（台／美／韩／日／港／A，含各市场的个股代码格式与「指数即时能不能取」），并注明这张表是 2026-08-03 实测而非从代码结构推的；同时记录该路径的两个限制：`source` 一律回 `fallback`、`provider_timestamp`／`is_stale` 恒为 `None`（**给不出报价有多新**，盘中引用要自己标时点），以及盘前要的「隔夜收盘＋近 5 日」仍走 `scripts/overnight.py`（单点报价给不了序列）。踩雷段新增一条**只有美股指数走得通实时路径**：`US_INDEX_MAPPING` 只收美股，`KS11`／`N225`／`TWII` 会落到 A 股路由 → 连问腾讯／新浪／efinance 失败 → **三个 fetcher 熔断 300s、污染後续真正的 A 股请求**（实测）；`HSI` 被判成美股个股回空 quote、`^HSI` 被转成 `^HSI.SZ`。并澄清一个会误导人的矛盾：`get_main_indices(market)` **能列出**各市场主要指数代码，但实时路径取不到它们，两件事不同。修法需新增一张非美股指数映射，属设计决策，**决定先记录不修**。`AGENTS.md` §3 的 `data_provider/` 条目加一行指针指向本档（走 `market_data/` 那条既有的指针模式，**不摘要内容**——doc 是正本，摘要会两处漂移）。
- [文档] `docs/realtime-board.md` 踩雷段补 Shioaji snapshot 五项：**`api.snapshots()` 回 `builtins.Snapshot`、没有 `_asdict()`**（写 `dict(s._asdict())` 会 AttributeError，被 `except` 包住就整批静默回空——实测印出表头後零列资料）；`json.dumps` 会因 enum 栏位炸而 `default=str` 挡不住；**`limit_up`／`limit_down` 在 contract 上不在 snapshot 上**；**「涨停锁死」的可判条件是 `close == limit_up` 且 `sell_volume == 0`**（比涨幅有用得多——2026-08-03 华邦电锁 143、委买排队 13,533 张而委卖 0 张，就是「现在下单买不到」的直接证据；锁板时 `buy_price`／`sell_price` 同时回 `0.0`，别当报价）；加权指数与台指期走同一个 `snapshots()`（`Indexs.TSE["001"]`／`Futures.TXF["TXFR1"]`）。
- [文档] 新增 `docs/tw-market-position.md`：台股**大盤层**位阶与长期进场时点的量测记录（个股 60/250 日讯号仍在 `tw-swing-pipeline.md`）。**① 唯一 CI 三期一致不跨零的位阶指标是「距 5 年线（60 月均）」**——Q1（低於 5 年线）在 1/3/5 年超额 **+10.0／+12.6／+13.0pp**、亏损机率 5%／**0%**／4%、有 5~6 个独立事件；Q5 最差（1 年 +1.4%、亏损机率 50%）；但**不通过严格单调性**，定位为「两端有意义、中间噪音」；**② 2026-07 的当前位置是第 99 百分位**（距 5 年线 **+86.3%**、过去 3 年报酬 **+132.9%**），距 5 年线历史前 8 高**有 7 个是 2026 年本身尚未到期**，唯一有後续的前例 2021-04 +59% → 之後 1 年 −5.5%，而 Q5 上缘只到 +59% ⇒ 现在超出整个历史测试区间、**不能据此预测方向，只能说「相对低点现在不存在」**；**③ 推翻「跌越深未来越好」**——回撤深度三期**都是 U 型**（两端好中间差），5 年期 **Q5 买在高点附近 +63.7% 胜过 Q1 跌最深 +48.7%**，而**浅到中度回撤 −15%~−39% 是所有持有期最差的进场区**；回撤 Q1 只有 **3 个独立危机事件**；**④ 部署方式：等回撤三期都最差**（1 年内回撤 10%/15%/20% 只有 **64%/44%/35%** 机率出现，中位数因此是 0.0%；「安全」是空手的假象），一次全押 > 分 2/3/6/12 批，且**分 2/3/6 批的最差情境比一次全押更差**；**⑤ 关键更正：「分批代价 8pp」是曝险时间不是择时效应**——12 期平均曝险 134.5/250 = **53.8%**，而 9.3/17.3 = **53.8%** 完全吻合，正常 6% 超额报酬下只会是约 2.8pp；**⑥ 有效样本 ≈ N/H**：1 年 ≈15 个独立周期、3 年 ≈4、5 年 ≈2 ⇒ 3/5 年的「亏损机率近 0」不可信；**⑦ 月份季节性 12 月弱正但与其他月份无法区分**（12 月 vs 其他月 |t| 1.19／1.78／1.84，三期都没过 1.96；上涨比例 79% 但真样本外只有 67%），并记录一个再犯的推论错误：把「异於零」当成「异於其他月份」。
- [文档] `docs/tw-market-position.md` §五记录台指期与 yfinance 的取得方式与**五个会让结论反转的陷阱**：**① 期交所「盘後」列的交易日期是归属日（次一营业日）**，`盤後(D)` 实际是 D−1 15:00~D 05:00、**在 `一般(D)` 开盘前已知**，误判会把领先指标当成落後；**② 结算价 ≠ 收盘价**（2026-07-31 TX 202608 收盘 43,678／结算 43,727，外部报价的涨跌常以结算价为基准而「昨收」却是上一场夜盘收盘）；**③ 必须滤掉价差交易列**（到期月份含 `/`）；**④ yfinance 的 `0050.TW` 2014-01 还原价错误（单月 −75.5%）**，单独造成 0050 的 1 月均值 −2.05%，剔除後 +3.11% ⇒ 用 yfinance 的 0050 月报酬须先滤 |月报酬|>35%；**⑤ `^TWII` 不含股息**，绝对报酬低估约 3%/年。另记录端点与历史长度：`futDataDown` 的 TX 日行情 **1998/07/21 起 28 年**（含未冲销契约数与交易时段、**单月为上限**）、`futContractsDateDown` 的三大法人期货未平仓**仅 2023/09 起 2.9 年**（样本不足）、年度 ZIP **404 不通**；以及开盘缺口三种算法的实测误差（**skill `tw-morning-call` 的夜盘公式系统性高估 0.62pp**，因含既有正价差；**ADR×指数权重自下而上误差仅 0.10pp**，建议改以後者为主）。
- [文档] `docs/tw-swing-pipeline.md` 的「站不住的部分」新增 2026-07-31 三轮追加量测（现行成本口径、事件级去重、block bootstrap 2000 次）：**① 持有期边界**——同一个冻结 breakout 讯号定义把前瞻由 60 拉到 **250 交易日**後优势消失且三项输基准（中位 -3.98% vs 有营收基准 +0.87%、胜率 46.6% vs 51.2%、P(≤-20%) 30.3% vs 24.0%），均值 +19.54% 由右尾主导（拿掉报酬 >100% 的 53 个事件後变 **-1.54%**），**这是 60 天波段工具、不是长期进场讯号**；**② 三个「买相对低点」定义全部输给 breakout**（P(≥30%) 16.1%／15.8%／11.0% vs 19.4%），其中「超卖反转 RSI<30」CI 与基准逐位重叠、**等於随机**，且它是唯一不用月营收因而无存活偏误的一组，否决最可信；**③ 外资／法人讯号无加值**——八组简单与复合讯号 CI 全部与基准重叠，「外资买+首次站回 MA60」（1,126 事件、中位 +0.33%）反而**比基准更差**，而决定性对照是 PB<1+外资买／PB<1 单独／PB<1+外资**卖**超 三臂中位数 +13.62%／+13.80%／+13.42% 几乎逐位相同 ⇒ **外资贡献为零**；**④ PB 分层五指标全单调（PB<0.7 中位 +27.78%／胜率 75.5% → PB≥2.0 中位 -4.11%／胜率 44.4%），但同日经对抗性复核已被推翻、数字作废**——单调性**只在绝对门槛成立**，换成时间中性的每日横断面五分位就消失（均值变 U 型），机制是 `PB<0.7` 的 106 个事件有 **38 个落在 2020 年** COVID 崩盘底部、前瞻 250 日吃到 V 型反弹，**它是伪装成选股因子的择时讯号**；**⑤ 因子层正式定论：11 个价值／基本面臂的同窗口成对超额点估计全部为负**（`PB<0.7` 超额中位 -11.31%、仅 38.7% 赢过 0050，同窗 0050 自己就是 +43.94%），`ROE`／`营益率`／`应计`／`月营收 YoY`／产业内 PB rank／PB 自身 3 年百分位全判噪音，`负债比` 与 `毛利率` **反向单调**（高杠杆低毛利＝产业循环押注非品质溢价），多因子 rank 合成全部没赢过单独 PB，唯一稳定加值是殖利率且**只加在下尾**（`PB<1&DY≥4` 把 P(≤-20%) 由 23.8% 压到 5.7%）；**⑥ 一个必须记住的方法论错误**：比较基准必须**同窗口成对**——用 0050 的 2010-2026 长期基准（1 年期中位 +14.6%）去比只在 2020-2025 发生的讯号会系统性高估，0050 在**同期**是中位 **+28.61%**／胜率 **79.6%**／P(≤-20%) **2.8%**（该段年化 +27.4% vs 2010-2018 约 +7.7%）；**⑦ 事件级去重只消除同一股票内部的重叠、未处理跨股票同期聚集**，加上 `market.valuation` 仅 2020-01 起（约 5.3 个独立年）、`block=250` 在 1,863 交易日上仅约 7 个独立区块，**所有 CI 都可能过窄**——这是所有区间跨零的根本原因，不是抽样运气。同时澄清 `screen_tw.py` 的 MA200 註解是「不要加大盤 regime 过滤」的论证，**不是**「等 0050 跌破 MA200 再进场」的择时规则。
- [新功能] 新增 skill `tw-morning-call`：台股每日盤前判讀，把量化層定位成 **supplier 而不是 gate**——它供應數字，不決定今天能不能動。動機是一次实测缺口：2026-07-30 早上 `breakout` 池 **0 檔**（前一日大盤 -3.76%，突破新高的股票结构上不存在），而同一份 DB 用宽门槛掃得出 **48 檔「逆勢抗跌 + 法人買超」**，於是「0 檔」被当成「今天没事做」，同时漏掉那 48 檔携带的族群资讯与持仓今天该不该减。流程四步：`make morning` 一键取数 → 补美股即时期貨與台指期夜盤（`overnight.py` 只给收盘，期貨要的是「现在」）→ 判 **regime**（順風／rotation 輪動／broad selloff 全面承壓／capitulation 宣洩，用 breadth + VIX 水位 + 隔夜族群分化定位，**不用指數漲跌幅**——同樣的 -2% 可以是輪動也可以是崩盤）→ 給 **buy / reduce / hold / wait** 恰好一個動作 + 一個**可觀察的**翻轉條件，并追加一行到 `journal/morning-calls.jsonl`。`buy` 的標的只能來自 `breakout` 池並交棒 skill `tw-swing-research`；`momentum` 寬掃只當「資金往哪去」的觀測，**不讀它的 `score` 排序**（它在 13 年回測是十個因子裡同曝險超額最差的一個，-13.44%）。
- [新功能] `journal/morning-calls.jsonl`（進版控）記錄每日 regime 判讀與動作，欄位語意見 `journal/README.md`。**回驗程式尚未寫**，所以欄位刻意全是事後可用 DB 算對錯的觀測值（`regime`／`gap_expected` 可對次日 `market.market_index` 驗）；累積到 20 筆再寫回驗，在那之前不聲稱 regime 判讀有經驗證的優勢。
- [改进] `scripts/overnight.py` 加入 **VIX**（`^VIX`）並按水位分級：≥30 判系統性 risk-off、<20 判「殺盤仍侷限在族群」、其間待觀察。**看水位不看漲跌**——費半兩日崩 9.6% 而 VIX 只到 20.66 是族群殺盤，同樣的費半跌幅配 VIX 35 是系統性風險，兩者的正確動作相反。同一輪**試過又移除**標普／納指／日經期貨三檔：yfinance 日線在台北早上還沒切到次日場次，拿到的是「昨天的期貨」（實測標普期 -1.18%，而當時即時電子盤是 +0.26%，方向相反）且與現貨欄位高度重複，正確做法留在 skill 用即時來源人工查；輸出末尾改為明說腳本只給收盤數字，並附開盤缺口公式。
- [修复] skill `tw-swing-research` 的 Step 0a 要求 agent 手動搜尋隔夜五項數字，**從未指向已存在的 `scripts/overnight.py` / `make overnight`**——於是實際執行時走了該腳本 docstring 明文警告的那條路（用搜尋湊數字），並踩到它已經處理好的三個坑：首頁表格欄位錯位（道瓊點差被讀成 1.00）、`▼-683` 被讀成「上漲 683」、兩篇報導數字相同卻標不同日期。現在 Step 0a 直接給 `make overnight` 命令，只保留腳本抓不到的兩項（台指期夜盤收盤、地緣事件）並附期交所連結，淨減 6 行。
- [改进] `tw-swing-research` 的 description 交出盤前入口觸發詞（「問今天／下個交易日買什麼」）給 `tw-morning-call`，自己收斂為「逐檔研究候選」，並加 reach clause 指回前者。此前 `screen-tw` 與 `tw-swing-research` 搶同一句話已踩過雷（見下方同類條目），這次的分工是**單一入口**：盤前問句一律先到 `tw-morning-call`，判出 regime 有貨才交棒，避免兩個平行入口再次分裂路由。
- [修复] 独立审查（Codex，gpt-5.6-sol xhigh）指出 1 High + 4 Medium + 2 Low，其中 High 与两个 Medium 是本轮**新引入**的，全部修掉：(1) **`_adj_close_panel` 的 `ffill` 会让 MA 吃到合成 K 棒**——面板 index 是多档股票的**联集**交易日，某档停牌那天会被 ffill 补值，取「最后 n 列」时合成值占掉名额、把最旧的真实 K 棒推出视窗，算出来不是 n 根真实资料的均线且不报错，足以再一次翻转「已跌破／未跌破」。现在面板不补值，需要真实 K 棒的 `_ma_check` 用 `dropna()`，需要「最后有效报价」的 `_last_close` 自己 ffill。(2) **`crawl_snapshots` 印在 commit 之前**：三步共用一个交易时，前两步印完「写了 N 列」而第三步 raise，`engine.begin()` 会把前两步一起回滚——log 宣称写入、DB 其实没有。改成收 engine、**每步一个交易**，印出的行代表已 commit；三步互相独立且 upsert 幂等，拆开没有原子性损失（index 成功不该被 stock_info 失败抹掉）。(3) **`_snapshot_latest` 吞掉例外会毒化交易**：在写入交易里跑 `SELECT max(date)` 失败时 Postgres 会把整个交易标成 aborted，`except` 住并不会修复它，只会让下一句 upsert 以「current transaction is aborted」失败并回滚全部；现在走 `engine.connect()` 独立连线、在 commit 之后。
- [修复] 同一轮的两项：`crawl_institutional`／`crawl_margin`／`crawl_ex_dividend` 的 `except ValueError` 静默吞掉解析失败——HTTP 200 但回封锁页或坏 CSV 时上层只看到 `0 rows`，与「当日未发布」无法区分，现在各印一行带端点与异常讯息的 WARN；`_MA_RE` 补 `(?<![A-Za-z])` 边界与千分位处理——少了边界 `跌破EMA10(136.7)` 会被读成 `MA10`（指数与简单移动平均是两个门槛，重算成 SMA 等于换了条件还宣称验过），少了逗号处理 `MA20(1,234.5)` 只匹配到裸 `MA20`，静默丢掉门槛连翻转警告都不会出现。
- [测试] 补强审查点出的 4 个弱测试：`test_daily_update` 原本退回「三个直接呼叫」也照样通过（现在 spy `crawl_snapshots` 本身再委派真品，并断言五段输出都有行）；`_snapshot_latest` 的假 conn 模拟不了 PG 的 aborted transaction（改成断言它走 `engine.connect()`、写入交易开了 3 次而稽核连线 2 次）；`_ma_check` 的翻转案例只喂刚好 n 根，「用全部列」或「n+1 列」的实作也会过（补第 11 根离群值）；新增 `test_adj_close_panel_does_not_forward_fill`。**自己写的第一版 ffill 测试是套套逻辑**：它直接喂 `_ma_check` 一个自造面板，`_adj_close_panel` 根本没被呼叫，把 ffill 加回去照样全绿；现已改成 monkeypatch `read_sql`／`load_factors` 直接测 `_adj_close_panel`，并实测「重新引入 ffill → 红、还原 → 绿」确认它真的会失败。
- [修复] `verify_swing_decisions.py` 的待触发计划把 `invalidation` **原文照印**，而里面的均线门槛是**做判断当天的快照值**，MA 每天在动——隔几天照旧值判就会判错。实测踩到：6166 在 2026-07-28 收 137.0，照日志里的 `跌破MA10(136.7)` 看是「未跌破」，但当天真正的 MA10 已经漂到 **138.70**，其实**已经跌破**（结论正好相反）。现在把文字里每个 `MA<n>` 门槛即时重算并印出 `MA10 现在 138.70（日志写的是 136.70），现价 137.00 **已跌破**`，且只在「照旧值会得到相反结论」时才加 ⚠——每笔都告警就没人看了。**只处理均线**：`SCFI 连续第三週下跌`、`法人由买转卖`、`费半连续两日下跌逾2%` 要外部资料或人工判断，不假装能自动判定（把没验的条件印成「未触发」比不印更糟）。
- [改进] `_last_close` 拆成 `_adj_close_panel()` + `_last_close(panel)`：**「现价」与重算的均线必须落在同一个复权基准**上。`market.price` 是未还原价，拿它算的 MA 去比还原后的现价，区间只要横跨一次除权息就差一个因子，而且不报错、只给一个看起来合理的错判（实测 2615 的 MA20 未还原是 81.32、前复权是 **80.74**）。窗口同时由 10 曆日放宽到 150 曆日（约 100 个交易日）以算得到 MA60。
- [测试] `tests/test_verify_swing_decisions.py` 新增 5 例（不碰 DB／网路）覆盖 `_ma_check`：旧值翻转结论时要告警、旧值与重算一致时不告警、非均线条件一律不碰、历史不足 n 根要说不足而不是拿短窗均值冒充、无括号的 `MA10` 与查不到的代号都不炸。
- [修复] `market_data.cli snapshot` 与 `crawl.daily_update` 的快照段**完全静默**：两条路径各自直接呼叫 `crawl_valuation`／`crawl_index`／`crawl_stock_info` 并把回传的 upsert 列数**丢弃**，成功与失败的可观测结果一模一样（什么都不印、DB 没变）。踩到才发现：2026-07-28 18:10 跑 `snapshot` 全无输出、`market.market_index` 仍停在 07-27，得逐层读 `cli.snapshot` → `crawl.crawl_index` → `sources._openapi_json` 三处原始码才确认真因是 **TWSE FMTQIK 当日尚未发布**，而不是 IP 被封或端点改版——这三种情况的处置完全不同（等入夜重跑／换 IP／改程式）。现在新增 `crawl.crawl_snapshots()` 作为**唯一**快照入口，两条路径共用，逐个印出 `<name> <n> rows`（对齐 `crawl_range` 的格式，同一份 cron log 可一起 grep）；`daily_update` 的月营收与除权息两笔也一并报数。**注意列数本身不够**：这两个端点回的是近月／全市场整包，当日未发布时照样回一样多的列（实测拿到 `index 18 rows` 而最新一列仍是 07-27），所以有日期维度的 `valuation`／`market_index` 会一并印 `latest <date>`。
- [修复] `sources._openapi_json`／`_valid_rows`／`_twse_csv` 把「连线失败或 IP 被封」「HTTP 非 200」「回应不是 JSON」「空 list（当日未发布）」「缺栏位（端点改版）」五种情况全塌缩成同一个 `None`。现在每个分支印出**可区分**的原因并点名端点 URL 与缺哪些 key；`_openapi_json` 补上 HTTP status 检查（原本 500 会走成 `r.json()` 的 `ValueError`，与「没发布」殊途同归）。回传契约不变（仍是 `None`），故上层 `if not rows: return 0` 与 `crawl_day` 的既有空档防护都不受影响。
- [测试] 新增 `market_data/tests/test_snapshot_not_silent.py`（6 例，不碰网路与 DB）：钉住三种 HTTP 失败模式的讯息**互不相同**、「未发布」与「端点改版」分得开、`_openapi_json` 已报过原因时 `_valid_rows` 不重复报、快照 **0 列也要印**（少这一行就退回全静默，而 0 列正是该去查的讯号）、稽核用的 `max(date)` 查询自己失败时只降级成 `latest unknown` 而不拖垮爬取。`crawl_snapshots` 的对应表刻意建在函式内——建在模组层会在 import 时绑定函式物件，让 `monkeypatch.setattr(crawl, "crawl_index", …)` 蓋不到（改的过程中真的让 `test_daily_update` 红过一次）。

- [修复] 台股波段事件量测、筛选回测、组合模拟与决策回验统一改用逐笔新台币现金流：买卖双边券商手续费默认 0.1425%（每笔最低 20 元）、卖出另收 0.3% 证交税，研究成交价统一买进 +0.15%／卖出 -0.15% 滑价；不再用固定扣 0.6% 或脚本各自成本。20 万元重跑 974 个事件后均值 +9.93%，block-bootstrap 95% +3.14%~+16.69%。
- [修复] 0050 基准的证交税改用 **ETF 卖方税率 0.1%**（个股仍 0.3%）。沿用个股税率会高估基准成本，而本流水线的结论正是「风险调整后输给 0050」——偏误方向对策略有利。重跑后 0050 全期总报酬 +407.6% → **+408.6%**、走前窗口年化 +25.9% → **+26.0%**，结论方向不变。依据：TWSE ETF 交易规则与财政部证交税规定。
- [修复] `health --strict` 的近期视窗与 `crawl.daily_update` 的自动修复视窗共用同一个常数（`RECENT_SESSIONS`，除权息因子视窗共用 `ADJUSTMENT_WINDOW_DAYS`）。旧版 daily 只补最近 5 个交易日、health 却检查 10 个，第 6~10 日的缺口会**擋住流程但重跑 daily 永远补不到**。同时把全历史 thin day 降为只报不擋（strict 只擋 daily 修得到的视窗）——否则 2014 年的一个半日交易会让 `make morning` 每天早上死在门口。
- [修复] `portfolio_walkforward` 的排序检定与逐年表改以**原始本金**为基准（`metrics()` 早已如此），不再用第一列权益当分母把首日进场成本抵掉。重跑：0050 逐年 2020 30.2% → **29.8%**、2026 57.2% → **57.6%**；排序检定 200 次乱序的结论不变（score 11.46x 落在乱序中位 11.92x 以下、第 46 百分位、p=0.547）。
- [修复] `tests/test_alphasift_api.py` 的 5 个测试**会真的连中国的行情端点**（eastmoney / akshare / sina，实测单一测试尝试 5 次连外，其中 `120.76.218.228` = `push2.eastmoney.com` 正是挂整夜的那个）。根因两类：(1) 三个 hotspots 测试没有 patch `_resolve_hotspot_provider`，`provider="akshare"` 于是造出**真的** `DsaEastMoneyHotspotProvider`，后续 thin-rows fallback 与 metric enrichment 各自连外；(2) 两个 detail 测试的 `FakeProvider` **继承**真 provider，覆写 `_find_board_change` 挡不到继承来的 `_is_industry_hotspot` 子树（先打 akshare board-change，失败再退 `stock_board_industry_name_em` → `_fetch_rankings`，两条都连外）。**每个网路失败都被 `except` 接住再 fallback，所以这些测试不管有没有网路都是绿的**——漏一格没人会发现，直到某天对方收了连线却不回。修法：补上缺的 mock，并加一个 autouse fixture 让本档任何测试一连外就红（刻意继承 `BaseException`，否则会被满地的 `except Exception` 吞掉——正是它揪出后面那两个原先被吞掉的漏点）。修完该档 37s → **15s**，因为不再有网路往返。
- [测试] 离线套件加上 `--timeout=300`（`setup.cfg` 的 `addopts`，`pytest-timeout` 同步进 `.github/requirements-ci.txt` 与 AGENTS.md 的安装指令——缺 plugin 会让 pytest 以 unrecognized arguments 直接中止）。动机是一次实测：`tests/test_alphasift_api.py` 里一个**没有 `network` marker、却会真的连外网**的测试在离线套件里挂了 **6 小时 21 分**（行程 `S` 状态、6 小时只用 30 秒 CPU、对 `120.76.218.228:443` 的连线 ESTABLISHED 但对方不回），全程没有任何东西会砍它，隔天才发现。有 timeout 之后同样的情况会红在该测试上并印出当时的堆叠。
- [修复] 年化用的交易日数从两处写死统一到 `tw_trade_costs.TRADING_DAYS_PER_YEAR`（**245**）：`backtest_screen` 原本用美股惯例 **252**、`portfolio_walkforward` 用 245，于是**同一段 0050 买进持有被两支脚本报成 +29.37% 与 +28.44%**（差 0.93pp，纯粹来自 denominator；实测 2020-01-02~2026-07-24 是 242.8 交易日/年）。超额报酬几乎不受影响（两臂共用同一个 `years`），但绝对 CAGR 与 Sharpe 会被高估、且两支脚本无法互相对帳。已加测试钉住三处相等。
- [修复] `backtest_screen.py --help` 直接 ValueError 崩掉：`--include-tib` 的 help 里有裸 `%`（`+1015%`、`85%`），而 argparse 会对 help 字串做 `%` 格式化。与 `portfolio_walkforward --skip-limit-gap` 是同一个坑——上一轮只修了一支、只给那一支加测试，第二支就漏掉了，而它**从头到尾没被执行过**所以没人看到。现在回归测试改成一次扫五支管线脚本的 `--help`（子行程跑真入口，`--help` 在 argparse 阶段结束、不碰 DB）。
- [修复] `screen_tw` 的 `momentum` 排序在**估值缺日时整栏 NaN**：`pe_ratio` 整栏缺值时 `fillna(median())` 的 median 自己是 NaN → rank 全 NaN → 每一档 `score` 都是 NaN，而 `sort_values` 维持原顺序（SQL 是代号序），于是 `--top N` **静默退化成「代号最小的 N 档」**（2026-07-30 实测：`valuation` 覆盖 0 檔、momentum 候选 37 檔，旧实作 37 檔的 `score` 全为 NaN 且顺序完全是代号升冪，修正后 37 檔全部有效）。而 `valuation` 走无日期参数的当日快照端点 `BWIBBU_ALL`，官方常盤後才发布，所以缺日是常态。修法是 `_pe_score()` 整栏缺值时回中性 0.5，保住其余四项仍然有效排序。**只影响 `momentum`**——`breakout` 排序是 `yoy + 0.5×量比 + 0.5×d5`、没有 PE 项，200 次乱序检定实作的也是 breakout 公式，故该检定不受影响。
- [文档] `docs/tw-swing-pipeline.md` 补上 strict gate **不涵盖** `valuation`／月营收的原因：把当日快照端点纳入 strict 会让盘后跑的 `make morning` 每天先红一次；代价是当天 PE/PB/殖利率整栏为空，已由上一条处理掉它唯一的实质後果。
- [改进] bootstrap 改为**完整交易日历上的 paired circular block** 重抽（同日事件绑在一起、缺一臂的配对丢弃而不补零），资料不足时回 `None` 并印 inconclusive 而不是回 `nan`；`measure_signal_forward --bootstrap` 预设由 500 提到 **2000**，并新增 `--bootstrap-seed`（预设 42）。区间会因此与旧版不可直接比较——旧的 `+1.6%~+11.6%`／`+3.66%~+16.93%` 一律作废。
- [文档] 新增 `docs/tw-trading-costs.md`，明确二代健保补充保费不是卖出费用，而是符合条件的股利给付由给付单位扣取；历史资料缺个人身分与实际给付资料，因此回测标示为「含交易成本、未扣个人补充保费」，并附 TWSE 与健保署官方依据。
- [修复] 只有带校准 prior 的 `breakout` 可写正式决策日志；`momentum` 明确仅供探索。删除未完成且口径不可比的 `backtest_screen --idle-to-bench`，不再保留永远不可达的 CLI／核心分支。
- [修复] 组合层进出场与期末未平仓清算统一计入滑價、雙邊手續費和賣出稅，並保留原始起始資本避免首日成本被歸一化；當前資料重跑後，全期 5 空位年化 +45.5%、Sharpe 1.19、最大回撤 -45.7%，0050 同成本基準為 +28.4%／1.23／-34.0%。
- [修复] `market_data.cli daily` 会连续修复近期缺日并在同一 transaction 刷新近期除权息复权事件；`make morning` 与 `make swing` 新增 `health --strict`，近期 price、TAIEX、法人、融资日期或复权事件不完整时停止筛选，避免把 missing 当成 0。
- [修复] TAIEX 改以可指定日期的 TWSE FMTQIK 报表为主、延迟的 OpenAPI 为 fallback；health 的 price/TAIEX 比较共用同一起始日，并按 T+1 契约略过法人／融资最新交易日，消除边界错位与正常发布延迟的假阳性。
- [测试] 新增交易成本、最低手续费、股利补充保费 opt-in、资料缺日/复权、row-shaped 决策日志、合法进场日期、full-calendar paired circular block bootstrap 与 CLI help 回归；组合与分布证据已用当前 Postgres 只读重跑。
- [新功能] 新增 `scripts/overnight.py` 与 `make overnight`：用 yfinance 直接取昨晚国际盘的**数字**（道琼/标普/纳指/**费半 ^SOX**/**台积电 ADR**/WTI 油价/USDTWD），每笔带日期戳，并直接判定「费半有没有跌逾 2%」（`semi_linked` 剔除门槛）与「台积电开盘约几 %」，各序列日期不一致时出警告。**动机是一次实测错误**：用新闻搜寻补这一段时引到的「台积电 ADR -4.74%」标题其实是另一天，当日实际是 **-1.07%**，差 3.7pp 足以把「台积电要开 -5%」讲成「开 -1%」，而搜寻结果不会告诉你它是哪一天的。规则因此定为**数字走脚本、叙事才用搜寻**。台指期夜盘（05:00 收盘）yfinance 取不到，仍需人工查，脚本会提醒 17:00~21:30 的夜盘报价不含美股资讯。
- [测试] `tests/test_overnight.py`（2 例，纯数学不碰网路）钉住 ADR 折算公式的方向：`ADR × 汇率 ÷ 5`。写反成 `÷ 汇率` 会得到 61.8 元——**不会抛例外、不会告警，只会产出一个看起来像价格的数字**（同一个 session 里真的写反过一次）。
- [改进] skill `tw-swing-research` 新增 **Step 0a「先查昨晚的國際盤（無條件執行）」**：DB 只到台股 13:30 收盤，之後到隔日開盤還有約 20 小時，只用 DB 下的結論等於拿過期資訊決定今天的動作。规则写成**候选 0 档不是跳过的理由**——隔夜盘还决定「已留档但待触发的计划」今天成不成立、以及回答市场方向时的依据（踩过：0 档候选就直接回「今天没东西买」，没查昨晚美股，结论碰巧对但推导过程是坏的）。要求拿到五个数字并附来源：道琼/标普/纳指、**费半**、**台积电 ADR**、**台指期夜盘收盘**、油价汇率地缘；完成条件是能说出「压力集中在哪个族群、哪个族群反而有支撑」，不是只给涨跌。附**时点陷阱**：台指期夜盘 17:00 就开始但美股 21:30 才开盘，17~21 点的夜盘报价完全不含美股资讯（踩过：差点拿一个作废的 +311 点去算开盘缺口），且搜寻结果常把上周五与昨天的收盘混在一起，先对日期再引用。Step 3 第 4 问改为引用 Step 0a 的结果不再重复；边界补一条「量化层只负责产生候选，不负责判断——只把数字重新排列组合再说一遍，等于没有做第二层」。
- [改进] skill 层的触发衝突修掉：`screen-tw` 的 description 宣称「當使用者要台股進場推薦、要掃全市場找標的、或問**下個交易日買什麼**時使用」，但它是**决策日志之前的旧流程**（Step 4 产出「分批进场计划」就结束，全文没有 `journal`、没有 `confidence`、没有期望值闸门、没有回验）——于是问「今天买什么」会被路由到旧契约，实际发生过：只跑了第 1 层硬指标再引用一份旧日志当今天的答案。现在 `tw-swing-research` 收下那组触发词并合并 `screen-tw` 独有的 5 条操作规则（`make swing`／放宽门槛的代价、资料新鲜度检查、**台指期夜盘 ÷ 前一交易日收盘 = 次日开盘预期缺口、所有价位照比例修正**、**费半跌逾 2% 时 `semi_linked` 标的优先剔除**、日均额 <2 亿的部位压到能一次市价出清），新增 Step 0（取得候选 + 时点：盘前拿到的必然是前一交易日的讯号），Step 4 完成条件加上「提醒使用者 commit `journal/`」。`.claude/skills/screen-tw/` 已删除。
- [改进] `tw-swing-research` 前段原本重述 `docs/tw-swing-pipeline.md` 的验证数字约 20 行（doc 是正本，摘要它＝两处维护必漂移），改为只留 `confidence` 锚点真正会用到的数字（P(≥30%)=20.7%、右尾 106%、左尾 14.6%）＋指向该 doc。净效果：加 19 行操作规则、砍 19 行重述。
- [新功能] 决策日志搬进版控：新增 `journal/`（`swing-decisions.jsonl` + `README.md`），`make swing`（更新台股资料 → 全市场筛选 → 产出候选 JSON）串起每日流程第 1 步，第 2 层由 skill `tw-swing-research` 接手并把判断追加到日志。**原本放 `.claude/reviews/` 是留不住的**：`.gitignore` 忽略 `.claude/*`，而 `scripts/check_ai_assets.py` 会挡掉 skills 以外任何被追踪的 `.claude/` 文件——等于这份记录不进版本库。而且 `confidence` 是对未来的预测，**只有在结果出来之前就已 commit 才有意义**，git history 就是防篡改机制，所以规则是当天研究完就 commit。`verify_swing_decisions.py` 的预设路径同步改到 `journal/swing-decisions.jsonl`。
- [改进] `verify_swing_decisions.py` 增加「哪一类判断比较准」的拆解：按 `catalyst_type`／`durable`／`digested`／`theme`／`peer_confirm` 分组给筆数、均值、勝率、命中率。回验要回答的不只是「赚不赚」，而是**哪一种理由撑得住**（可延续的催化剂真的比较好吗、「已消化」是不是真的该躲、主题有没有押太集中）；样本不足时每张表都会标「别当结论」。
- [文档] 2026-07-26 那一轮的两笔判断移到 `journal/swing-decisions-v0-superseded.jsonl` 只留稽核轨迹、不进回验：它们是在 skill 修正前做的（期望值公式符号写错、缺 `decided_at`／`exp_upside`／`exp_downside`／`theme`、`peer_recent_12m` 空白）。2026-07-27 开盘前用现行契约重做，两档都判 `pass`（萬海 E[R] -0.044：SCFI 已连两周回落而股价背离追高；凌华 E[R] -0.105：PE 46 倍、d5 +39.3% 过热且周五费半重挫 -4.25% 直接命中 `semi_linked`）。
- [修复] 第三轮独立审查（Codex，gpt-5.6-sol xhigh）指出 9 项、全部成立，其中一项**直接翻转结论**：组合模拟的股票池**没有排除创新板**，而 live 的 `screen_tw.funnel` 排除它（一般帐户要签风险预告书并符合资格条件）——于是组合买进了 live 永远不会买的 7610（10 倍股）。排除后全期 Sharpe 由 1.30 掉到 **1.22**、同窗口由 1.16 掉到 **1.07**，「风险调整后与 0050 打平」变成「**输给 0050**」。修法是 `--include-tib` 预设关闭；严格版应建 point-in-time 板别／投资资格表让 live、事件量测、组合回测共用同一个 universe helper（现在用「今天的名称後缀」近似，方向保守）。
- [修复] 同一轮的另外 4 项 High/Medium 会让数字说谎：(1) **第 4 层忽略 `decided_at` 与 `entry_range`**——週五的候选若到週一晚间才研究完，用週一开盘成交等于用当天白天还不存在的判断下单；开盘跳空穿过建议区间上界的那笔其实**没成交**却被算成有成交。现在进场日取「讯号日与 `decided_at` 两者较晚者」的次一交易日，跳空未成交标为 `no_fill` 单独列出。(2) **第 4 层的结论门槛是空话**：差值 >1e-9 就印「有加值」、Brier 小一点就印「比较准」；改成 bootstrap 95% 区间不跨零**且**已到期 ≥20 笔才给结论，否则一律 inconclusive。(3) **第 4 层只算事件均值，不是可投资报酬**——20 个同日同题材的讯号可以让均值很漂亮，但真实帐户只拿得到 5 档；新增 `paired_portfolio()` 用同一个 `simulate()` 跑「全收 vs 只收 enter」两本帐。(4) **排挤成本两侧口径不同**：买到的一侧因持有 60 日天然接近事件去重，没买到的一侧每天重复追加；现在两侧都做 60 日事件去重（名目 3,048 笔 → **908 个事件**，均值由 +13.37% 变 +10.34%），并分别记录 `entries/closed/open_at_end/already_held`（此前把「130 次进场」写成「成交 125 笔」）。
- [修复] 同一轮的 3 项时序／口径问题（本轮 headline 未受影响，但会在别的资料上出错）：(1) **月营收保鲜期口径**——量测的 `ffill(limit=45)` 数的是 45 个**交易列**（约 63 曆日），live SQL 是 45 个**曆日**；而且「forward 到下一交易日再 shift(1)」让週六公告晚一天可见（live 的週一就看得到）。改成公告日面板算实际天龄遮罩 + `allow_exact_matches=False`，实测 44 个 signal cell 不同、事件 973 → **974**、均值 +10.47% → **+10.30%**、P(≥30%) 20.9% → **20.7%**、bootstrap 区间 +3.66%~**+16.93%**。**踩到一个单位陷阱**：本机 pandas 的 datetime 是 `[us]` 不是 `[ns]`，自己除 epoch 常数会把公告日算成 20（而非 20456）让遮罩全部失效——天数换算一律走 `Timedelta`。(2) **停牌／下市判定含前视**：旧版用「这一列或之后还有没有成交价」，等于在第一个缺价日就知道样本内不会再有报价而提前释放资金；改成出场日停牌**顺延到下一个可成交日**、连续 20 个交易日无报价才判下市。(3) **排序分数在剔除已持股後才算 pct-rank**，与 live 在完整当日 pool 上算不同（会改变其余个股的百分位间距甚至翻转排序）；改为 `daily_scores()` 先在完整候选池算好再套持仓限制。
- [文档] 一并修掉 skill 的**期望值公式符号错误**（会直接翻转 enter/pass）：`exp_downside` 范例是负数，公式却写「减去 downside」——`p=0.20、up=+0.45、down=-0.18` 在错的公式下得 +0.234（判 enter），正确是 **-0.054（应 pass）**。现在明确定义 `exp_upside`/`exp_downside` 是**条件均值**（命中／未命中各自的平均报酬），公式统一为 `up × p + down × (1−p)`，与回验程式同一条。另把「排序已验过没有价值」改为「200 次乱序里没有观察到优势」，把「优势必须来自事件面研究」改为**待验的假设**（第 1 层打不赢 0050 只证明「别自动下单」，不证明第 2 层能补上差距）。
- [测试] 新增 6 例覆盖上述修复：出场日停牌顺延而非用旧价卖、长期停牌满 20 交易日才判下市、排序分数在完整候选池上算、涨停跳空可跳过的敏感度、`decided_at` 决定第一个合法进场日、跳空穿过 `entry_range` 算未成交；月营收面板改测三件事（週六公告週一可见、公告日当天不可见、保鲜期是曆日而非交易列）。
- [文档] 新增 `docs/tw-swing-pipeline.md`（并挂进 `docs/INDEX.md`）：台股波段候选流水线四层（量化预筛 → AI 事件面研究 → 分布量测 → 回验）的唯一契约文档——冻结的讯号定义与「live 必须逐格相同」的理由、前瞻报酬分布与 circular block bootstrap 区间、组合层三个结论、回验的三个差值指标，以及**明确站不住的部分**（量比上限是同样本选模、上柜全无月营收、存活偏误 -0.33pp、YoY 与命中率不单调、创新板排除、时期依赖）。此前这些结论只存在于 gitignore 的 `.claude/reviews/`，仓库里没有可交接的记录。
- [新功能] **【本条数字已作废，见本段首条】**新增 `scripts/portfolio_walkforward.py` 与 `make portfolio` / `make portfolio-wf`：把讯号的前瞻分布压成**有限资金真能拿到的权益曲线**（T+1 开盘买、固定持有 60 交易日、等权、买卖各扣 0.30%、**排除创新板**），回答四件事。(1) **资金竞争没有杀掉优势**：3,939 笔名目讯号 → 进场 130 次（已平仓 125、期末仍持有 5、另 372 笔落在已持股），两侧都做 60 日事件去重后买到的 125 笔均值 +13.19% 对没买到的 908 个事件 +10.34%（排挤成本 **-2.85pp**），三个设定下都 ≤0，且不依赖涨停成交假设（`--skip-limit-gap` 跳过 57 笔开盘跳空 ≥9.5% 的进场后年化 47.2% → 47.1%、Sharpe 不变）。(2) **风险调整后输给 0050**：年化 +47.2% 对 0050 +28.6% 看似大胜，但 Sharpe **1.22 对 1.24**、最大回撤 -45.3% 对 -34.0%；同一段 2021-04 起窗口换 3/5/10 个空位 Sharpe 是 1.07／1.07／0.99（0050 1.15），**完全不随分散改善**。(3) **`screen_tw` 的 breakout 排序尚未观察到优势**：用 live 公式（在**当日完整候选池**取 pct-rank）对照同池乱序 **200 次**，score 期末权益 12.34x 落在乱序中位 12.82x **以下**、5~95 百分位 8.00x~22.30x（单尾 p ≥ 0.5）——不能说已证明零价值，但排名不是进场理由。(4) **走前选参更差**：扩张窗每折只用该折之前（且报酬已实现、往前砍 60 交易日）的资料从 18 组网格挑门槛，样本外年化 +24.7%／Sharpe 0.76／回撤 -58.5%，同窗口冻结门槛是 +41.3%／1.07；**这 16.6pp 是「两套规则的样本外绩效差」，不是选参偏误的规模**（只扫三个参数、用事件均值选参却用组合 CAGR/Sharpe 评分，不构成 paired optimism 比较）。结论：**量化层的产出只能当候选名单，而且它机械式全收在风险调整后打不赢 0050**。
- [修复] `.gitignore` 的 `verify_*.py`（用于挡一次性验证脚本）会**静默吞掉** `scripts/verify_swing_decisions.py`——一个常驻工具就这样不会进版本库、在新 clone 上直接消失；补 `!scripts/verify_swing_decisions.py` 例外并注明理由。
- [新功能] **【本条数字与路径已作废，见本段首条；日志已移到 `journal/`】**新增 `scripts/verify_swing_decisions.py` 与 `make verify-decisions`：读 `.claude/reviews/swing-decisions.jsonl` 回验 `tw-swing-research` 的判断，报酬定义与 `measure_signal_forward` 逐格一致（决策日往前对齐到最近交易日 → 次一交易日开盘买 → 第 60 个交易日收盘卖 → 扣 0.6%）。刻意不看命中率（候选池本来就是正期望值，「进场的那些赚钱」证明不了任何事），只看三个差值：`E[R|enter] − E[R|全收]`、`E[R|pass]`（放弃机会的成本）、`Brier(confidence)` 对照「一律报基准率 20.7%」；另附校准分格、期望值估计偏差与主题集中度。未满 60 交易日的决策列为 pending 并显示剩余天数，已到期少于 20 笔时整份结论标为杂讯。
- [修复] 第二轮独立审查（Codex，gpt-5.6-sol xhigh）指出的 9 项全部修复，其中 4 项 High：(1) **量测的不是会下单的那个讯号**——live 的 `hi60_prior` 是 `high.iloc[-66:-5]`＝61 根／视窗 t-65…t-5，量测写成 `shift(6).rolling(55)`＝55 根 t-60…t-6，多排除一根、视窗也短 6 根，且月营收保鲜期两边不同（live 120 天 vs 量测 45 天），实测 918→894 事件、只有 859 重叠；现在两边都对齐到 `shift(5).rolling(61)` 与 45 天公告日保鲜期（`screen_tw.load()` 的月营收查询改为 `announce_date >= as_of - 45d and announce_date < as_of`），并加端到端验证：量测在 2026-07-24 发的讯号 = live 候选名单 {2615, 6166}。(2) **区块 bootstrap 的起点母体错**——只从「有事件的日子」抽起点、截尾又用事件日数而非交易日数，重抽中心值 7.09% 与样本均值 10.47% 不符、换 seed 上下界漂移逾 1pp；改成 circular block、母体用完整交易日历后区间 **+3.66%~+17.49%**，与审查方独立重算的 3.78%~17.25% 对上（旧的 +1.6%~+11.6% 作废）。(3) **回补器把四种失败混成同一个 `None`**（HTTP 失败／解析失败／单月无资料／真正的不继续公开发行），公司第一次遇到任一种就被标成 dead、剩余月份全跳过，「82 档补不回」的统计因此可能虚胖；改成回 `(record, reason)`，只有 `not_public`／`foreign_exempt` 是硬边界，其余留在 `retryable`。(4) **`parse_company_monthly_revenue` 不核对回应页的年月**，直接拿呼叫参数当 PK，MOPS 回旧页就会用错月份污染 `monthly_revenue`——而原本的测试正好证明了这个漏洞（用显示「民国109年06月」的 fixture 以 `(2020, 12)` 呼叫并期待写成 2020-12）；现在核对页面声明的民国年月，对不上回 `month_mismatch`，该测试改为断言拒收。
- [修复] 同一轮的 3 项 Medium：事件去重改为「与上一个**保留的事件**相隔 > h」而非与上一个名目讯号相隔 > h（0/50/100 日、h=60 这种序列旧版只留第 0 日，即使第 100 日的报酬窗口并不重叠；实测 918 → **973 个事件**）；`--emit-revenue-gaps` 补到讯号当月的**前三月**（12 月营收次年 1/10 公告，经 `ffill(45).shift(1)` 最晚可影响约 3/17 的讯号）；下市结算改用 `close.ffill().shift(-h)`＝窗口内最后成交价（旧版 `close.ffill()` 未 shift，取到的是**讯号日**收盘），且单日暂停交易之后复牌不再被误判为下市（用 `notna()[::-1].cummax()[::-1]` 判定「这一列或之后还有没有成交价」）。存活偏误上界也改了口径：**「全部併入」不是上界**，未知的营收条件可以只让较差的那些通过，真正的历史最差子集是逐一加入最差事件取均值最低者——15 笔全併是 -0.27pp，**最差 11 笔子集是 -0.33pp**。
- [修复] 一个 pandas 陷阱（自测时抓到）：`shift` 会把 bool 栏位转成 object dtype，此时 `~True` 得到整数 **-2**（真值）而不是 `False`，下市判定曾整条反过来；`no_future` 计算补 `.astype(bool)`，并加测试锁住。
- [改进] `measure_signal_forward.build_signals` 拆成 `factors()`（四个因子面板）+ `apply_thresholds()`（门槛比较），让组合模拟可以扫 18 组参数而不重算 rolling；`build_signals` 保留为薄包装，讯号定义仍是单一真源。
- [测试] 新增 `tests/test_portfolio_walkforward.py`（5 例：无讯号时权益不动、同日三档只有一个空位 → 一笔成交两笔列入排挤、成交报酬＝开盘买／收盘卖扣两边成本、下市部位立刻结算且 `zero` 给 -100%、走前验证的训练区间内不得有讯号）与 `tests/test_verify_swing_decisions.py`（6 例：持有窗口逐格对齐、决策落在非交易日往前对齐、未到期回报剩余天数而非假报酬、日誌解析容忍空行与注解、坏行整份拒收、尾部统计）；`tests/test_measure_signal_forward.py` 补 3 例（`hi60_prior` 与 live 逐格相同且旧公式必须不同、去重比对最后保留事件、单日停牌不算下市）。
- [文档] **【本条数字已作废，见本段首条】**`.claude/skills/tw-swing-research` 的基准数字全部换成定版（974 个事件、均值 +10.30%、P(≥30%) **20.7%**、bootstrap +3.66%~+16.93%、集中度前 12% 占 106%、存活偏误 -0.33pp），并补两件组合层验证出来的事实：**机械式全收在风险调整后打不赢 0050**（所以事件面研究是全部的价值来源）、**排序已验过没有价值**（乱序中位数还更高，排名不是理由）。航运数字重算：34 个事件均值 +32.5%，但扣掉 2021 后 20 个只有 +1.9%／勝率 45%、2022 起逐年全负。月营收 YoY 与命中率**不单调**（20~30% 21.3%、30~50% 20.6%、50~80% 掉到 14.9%、>80% 回到 27.0%），所以「YoY 很高」本身不是理由。`pass` 规则与 `confidence` 语意的自相矛盾一并修掉：`confidence` 是可校准的预测栏位、**不是部位大小**，部位另看 `exp_upside`／`exp_downside`／`theme`（同主题第二档起降级）。
- [新功能] `measure_signal_forward.py` 新增 `--emit-revenue-gaps`（产出 `cli revenue-pit --only-file` 吃的 CSV）：月营收只在**价格条件成立那几天**会被用到，所以只需补「已下市且符合价格条件」的股票在讯号当月与前两月（`ffill(limit=45)` 让讯号可能用到最多两个月前的公告）。缺口从 3,102 个（84 档、4.7 小时）缩到 **79 个（14 档、15 分钟）**。
- [文档] **【本条数字已作废，见本段首条】**存活偏误量化完成：补回 5 档（2809/2823/6288/6452/6806），**82 档补不回**（被吸收合并後 MOPS 回「不继续公开发行」）。那 82 档只产生 **15 个**符合价格条件的事件、均值 **-7.01%**、勝率 33.3%、P(≥30%) 6.7%；最差子集併入让候选池均值由 +10.30% → **+9.98%（-0.33pp）**。偏误真实存在但不足以翻转结论——**走向下市的公司通常在跌，很少去突破 60 日新高**（84 档下市股里只有 14 档在样本期内符合过价格条件）。定版分布（讯号定义、bootstrap 与月营收口径全部修正后）：**974 个事件**、均值 +10.30%、中位 +1.13%、勝率 51.5%、损益两平 30.8%、P(≥30%) 20.7%、circular block bootstrap 95% 区间 **+3.66%~+16.93%**（IID 区间 +7.89%~+12.72% 是假精度）；对等基准（同池、有月营收）7,319 个事件、均值 +5.00%。集中度仍极端：前 12% 的事件贡献总报酬 **106%**，拿掉 29 个报酬 >100% 的事件後均值降到 **+5.93%**。
- [修复] 月营收有**静默的存活偏误**，独立审查（Codex）指出后确认成立：`crawler.crawl_monthly_report` 走的 `t21sc03_<民国年>_<月>.html` 看起来是按月存档，实际是**动态产生**的，只列出目前仍在申报的公司。实测 2020-06 那份 979 家里完全没有 6452 康友、2448 晶电、2456 奇力新、5305 敦南、3698 隆达——这五档当时全部还在交易。用它回补历史，后来下市的公司会永久缺席，任何「要求营收成长」的选股条件都会把负尾系统性移除（实测 2020 后停止交易的 70 档普通股：0 档有 2020 后月营收、0 档在 current `stock_info`；反向 100% 有月营收的公司都还在市）。
- [新功能] 新增 `sources.crawl_company_monthly_revenue`／`parse_company_monthly_revenue`（MOPS 个别公司查询 `ajax_t05st10_ifrs`）与 `crawl.pit_revenue_gaps`／`backfill_pit_revenue`、CLI `revenue-pit`：逐公司逐月补下市公司的月营收。解析踩两个坑——表格是**转置**的（项目在第 0 栏），且有两个「增减百分比」列（第一个是本月 YoY、第二个是累计），靠「本月」列的位置定位才不会取错；KY 公司多一个功能性货币栏，一律取新台币栏。只补得回**仍公开发行**的公司，被吸收合并的回「该公司不继续公开发行」（2448 晶电併入富采），那部分是硬边界。**判定「已下市」用 `price` 表最后交易日而非「不在 `stock_info` 里」**——`stock_info` 只含上市约 1,100 档，用它判定会把全部上柜公司都算成下市（实测缺口从 70 档暴增到 973 档）。`crawler.py` 补 `requests_post`（MOPS 只吃 POST，共用既有 session／重试逻辑）。
- [新功能] 新增 `scripts/measure_signal_forward.py`：量测选股讯号的**前瞻报酬分布**而非组合回测——回测会把答案绑在部位管理、成本、出场规则上，换一组出场规则结论就翻。四个让数字不虚胖的处理：(1) 宇宙用 `market.price` 判定而非 `stock_info`（后者只有现存 1,100 档，用它过滤历史等于前视 + 存活偏误）；(2) **区分样本右端截断与真下市**——前者报酬未知一律 NaN 排除，后者要结算（`--delisting last|zero`）。踩过：把两者混在一起处理，2.5 年样本里有 409 笔右端截断被捏造报酬，而样本末端的讯号往往落在同一波行情、会整批偏向同一方向；(3) **事件级去重**（同档 h 个交易日内连续触发是同一个事件，实测 3,654 笔名目讯号只对应 855 个事件）；(4) **区块 bootstrap** 而非 IID 区间（事件在时间上聚集，IID 是假精度——实测 2024 起 372 个事件的 IID 区间 +10.1%~+18.8%，区块 bootstrap 是 **-3.8%~+14.8%**，跨零）。`--survivorship-bound` 给补不回月营收那部分的偏误上界。
- [修复] `screen_tw.py` 的 `funnel()` 换成经前瞻报酬量测的「营收转强 + 刚突破」（`--strategy breakout`，预设）：日均额≥2亿、排除 ETF 与创新板、收盘 > 不含最近 5 天的 60 日高、5 日涨幅≥5%、5/60 日量比 1.3~2.0、月营收 YoY≥20%。旧的「多头排列 + 法人买超」保留为 `--strategy momentum` 仅供对照——它在 13 年回测里是十个因子中同曝险超额最差的一个（-13.44%）。`compute_factors` 新增 `hi60_prior`（**不含最近 5 天**的 60 日高，含最近 5 天的话今天必然是自己的高点、比不出突破）、`break_pct`、`vol_ratio5`；`MIN_BARS` 60→66。新增 `--json` 输出 34 个栏位 + `why_selected` + `measured_base_rate` 给 agent 消费。**门槛只加了量比上限 2.0**（四个分位单调递减），突破幅度与 5 日涨幅刻意不设上限、月营收门槛不提高、不加大盘 regime 过滤——三者的实测结果都与直觉相反，理由写在 `BREAKOUT` 的注解里。
- [新功能] 新增 skill `tw-swing-research`：对 `screen_tw --json` 的候选逐档做事件面研究，找出**催化剂**并判断可否延续（一次性的匯兑／业外／低基期是最常见也最没续航力的），判断写进 `.claude/reviews/swing-decisions.jsonl` 供 60 天后回验。`confidence` 的语意锁死为「进场后第 60 个交易日收盘净报酬 ≥ +30%」的主观机率（不是「期间曾涨逾 30%」——后者基准高 15pp，语意飘掉回验就对不上）。
- [测试] 新增 `tests/test_measure_signal_forward.py`（5 例）覆盖右端截断不得被结算、真下市要结算、事件去重、成本扣除、公告日落在非交易日要顺延；`market_data/tests/test_etl_valuation.py` 补 3 例覆盖 MOPS 个别公司页的转置表格与「本月 vs 累计」YoY 取值、不继续公开发行回 None、年末 announce_date 跨年；`tests/test_screen_tw.py` 补 4 例覆盖 `hi60_prior` 排除最近 5 天、`vol_ratio5`、量比上下限、营收条件必要性。
- [修复] 独立审查（Codex，gpt-5.6-sol xhigh）指出的资料污染与结论失效路径共 13 项，全部修复。资料层四项：(1) `adjust._fetch_by_year` 任一年度 chunk 回 `None` 就 raise——旧版只在「所有年度都失败」时才回空，于是「2018 那段失败、其他年成功」的结果仍非空，`rebuild()` 会先删整段再写入缺 2018 的资料，缺一年官方除权息足以让该年之后所有报酬计算全错且无声。(2) `--no-reductions` 不再是破坏性操作：新增 `adjust.existing_official_rows()`，离线模式改为**沿用 DB 既有的 `tpex_exdailyq`/`twse_twtauu` 列**再一起写回；旧版跳过抓取但仍 `delete where date >= start`，按说明「离线重算推导」使用会清掉 10,879 笔上柜除权息与 347 笔减资。(3) `parse_valuation_day` 的 NULL-wash 守卫补两层：单栏改名（不只三栏全消失）也 raise，且 PB／殖利率的非空率低于 50% 时整批不发布（实测 1,592 个真实交易日的最低非空率为 PB 99.8%、殖利率 78.3%，门槛不误挡）。(4) `crawl_range` 的连续零列门槛依有无交易日历分流：`price` 自己就是日历来源、无法过滤假日，门槛放宽到 10（2024 春节休市 2/6~2/14 是连续 7 个平日，用 4 会把跨春节的 price 回补误判成 IP 封锁而中止）。
- [修复] `adjust.infer_rows` 两项边界错误：(1) 查询改为多读 60 天历史再算 `seq`/`gap`，事件仍只收 `>= start`——旧版先截 `date >= start` 才计 `seq`，任何**既有**股票在起点后前 6 根 K 的公司行动都被 `MIN_BARS_BEFORE` 当成「新上市」永久漏记（实测回补 7 笔）。(2) 新增 `MAX_SPLIT_GAP_DAYS=60`：精确 1/N 比例可越过 `STALE_GAP_DAYS`，但停牌越久「复牌价恰好落在 1/N 附近」越可能只是真实重估碰巧撞上比例，而推导错一笔就把该档之前全部历史价乘错；6222（停牌 195 天）与 6131（328 天）因此改为不推导，需人工对官方公告后进 `VERIFIED_ACTIONS`。
- [修复] `crawl.daily_update` 的 `days` 由曆日改为**交易日**（从 `market.price` 取最近 N 个交易日 + `asof`）：旧版 5 个曆日遇到週末＋连假实际只回补 2~3 个交易日，而法人／融资是 T+1 才补齐的，窗口太窄会让那几天永久缺。
- [修复] `backtest_screen.run()` 四项会直接污染绩效的记帐错误：(1) **停牌持仓不再按零估值**（新增 `_mark()` 退回最后已知收盘价）——缺价当 0 会让当日净值凭空掉一个部位、制造假回撤，还连带缩小下一批部位（台股 2013 起流动性合格股共 1,288 个停牌交易日）。(2) **期末平仓的卖出成本回写 ledger**：旧版只写进 `trades`，而 `stats()` 读的是 ledger，期末净值与 CAGR 被高估。(3) **T+1 无开盘价的卖单改为顺延而非丢弃**：旧版直接清空 `pending_sell`，已决定出场的部位会无声继续持有（`--regime-exit` 更明显——隔日 regime 恢复就永不重排）。
- [修复] `backtest_screen` 另三项：`ind["pe"]` 补 `ffill(limit=10)` 保鲜期（PB／殖利率早就有，PE 漏了——公司转亏后 `pe_ratio` 为 NULL，无上限 ffill 会让最后一个正 PE 沿用数月甚至数年继续参与排名）；`--null-trials` 剔除零成交试验产生的 NaN 并回报有效试验数（`NaN >= real` 算 False 却仍占分母，会压低经验 p 并让 mean/sd/z 全变 NaN）；`--regime-exit` 未搭 `--regime-ma` 改为 argparse 报错（旧版静默 no-op）。
- [修复] `load_panel` 在前复权覆盖率低于 20% 时 **raise 而非只印 WARN**：一份印了 WARN 但照样输出的绩效表与正确的看不出差别，而未还原会让 0050 分割显示 -65.79%、上柜除息造成约 20pp/年偏差。报酬集中度在总损益 <= 0 时不再印无意义的佔比。
- [测试] 新增数例覆盖上述修复：`_mark` 的停牌退回与从未有价、停牌持仓不归零、期末平仓成本入帐一致性、未成交卖单顺延、`crawl_range` 无日历时的宽门槛。`test_run_position_size_compounds_with_equity` 改看倒数第二列（最后一列是期末平仓后的全现金状态）。
- [修复] 选股与回测的股票池排除**创新板**（TWSE Innovation Board，名称后缀 `-创`；`screen_tw.funnel` 与 `backtest_screen` 的 `--include-tib` 可放回）：一般帐户要签风险预告书并符合资格条件才能买，把它算进来的绩效一般人执行不了。实务冲击更关键——全库 25 档创新板只有 1 档（7610 联友金属-创）过得了 2 亿流动性门槛，而它 2026-01~07 涨 10 倍，**单一笔交易就占 13 年总损益的 85%**，13 年年化超额 +6.66% 基本上押在这一张彩票上。
- [新功能] `backtest_screen.py` 新增 `--regime-exit`（大盘 regime 关闭时连持仓一起清）：只挡进场对回撤几乎无效（实测 2013-2026 由 -61.6% 只降到 -60.6%），因为回撤来自**抱着部位穿越下跌**而不是新开仓。
- [改进] `backtest_screen.py` 的报酬集中度改为同时输出**单笔最大占比**与前 10 笔占比：「这是策略还是彩票」需要单笔占比才看得出来（实测单笔可占 13 年总损益逾三成）。
- [改进] `--null-trials` 的对照组由「全池随机」改为「本因子自己的 filter + 随机排序」：`monthly_revenue` 只覆盖 1,152/2,679 档（几乎全是上市；流动性合格股里占 61%），拿全池随机当对照的话「revenue 赢随机」有一部分只是上市大型股赢上柜小型股的宇宙差异，不是排序能力。
- [修复] 上柜股票的前复权此前几乎完全缺漏：新增 `sources.crawl_tpex_ex_dividend`／`parse_tpex_ex_dividend`（TPEx 官方「除权除息计算结果表」`bulletin/exDailyQ`，自 2008-01-02 起）并接进 `adjust.rebuild` 作为官方来源 `tpex_exdailyq`。原本上柜除权息只能靠价格推导，而推导门槛是单日跳空 >11%、除息通常只跳 1~5%，所以官方 10,892 笔上柜除权息里只有 481 笔被抓到（4.4%），其余 10,411 笔完全没有还原——上柜小型股的历史报酬被系统性低估。已取代的 481 笔推导值与官方值对表：相对误差中位 1.16%、最大 9.98%，61 笔误差 >5%。**跨越此修复的回测数字不可互相比较。** 找端点踩过四个坑：openapi `/tpex_exright_daily` 只回当日 13 笔、`/tpex_exright_prepost` 是预告表无参考价、`bulletin/exDailyQHis` 只涵盖民国 89/9~96/12、旧版 `exDailyQ_result.php` 忽略日期参数；通法是抓旧 php URL（302 到新页）后在新页 HTML grep `action:"..."`。
- [修复] `adjust.infer_rows` 的停牌 gap 规则漏掉最常见的上柜减资：`STALE_GAP_DAYS=14` 原本一刀切排除所有「距前一笔交易 ≥14 天」的跳空，但减资的停止买卖窗口本来就是 2~3 周——实测被排除的 152 笔里有 13 笔吸附到精确 1/N 或 N 倍比例、其中 11 笔的 gap 落在 14~28 天（2719、3339、4303、5205、6228 等减资后复牌的 2~4 倍跳升）。现改为「比例精确时不受 gap 限制」，非精确比例仍照原规则排除。
- [修复] `crawl_range` 只对 `market.price` 已存在的交易日发请求，并在连续 4 个交易日回零列时 raise 中止。此前逐日迭代日历天，周末与假日各占一次请求与一次 delay（约 30% 请求全浪费）；而单日零列分不出「非交易日」与「被 TWSE 封锁」，被挡之后会安静跳完剩下几百天、exit code 仍为 0。踩雷：2024 春节休市 2/6~2/14 是连续 7 个平日，光靠 weekday 过滤挡不掉，所以交易日历取自 price 表本身。
- [修复] `parse_valuation_day` 在三个估值栏（本益比／股价净值比／殖利率）全部消失时 raise 而非产出全 NULL 列：`valuation` 的 upsert 不做 coalesce，端点改版会把既有的 PE/PB/殖利率整批洗成 NULL。
- [新功能] `backtest_screen.py` 新增虚无分布检验 `--null-trials N`（含对照因子 `random`：同一组流动性门槛、同一出场规则下纯随机选股）：「超额 +15% 是选股力还是运气」只有虚无分布能回答，输出真因子的经验 p 值与 z 分数。实测 2020 起 revenue+chandelier3+10 槽：同曝险超额 +28.36%，而随机选股为 -8.70%。
- [新功能] `backtest_screen.py` 新增大盘 regime 闸门 `--regime-ma N`（0050 收盘低于自身 MA(N) 的日子不开新仓，既有部位照原出场规则走；用 T 日收盘判断、T+1 开盘成交，与讯号同一时序）。动机是三个最佳出场规则的回撤都在 -53~-58%，个股层停损管不到「整个市场一起跌」。面板暖机窗口由 200 天放宽到 400 天，否则 MA200 在样本前段是 NaN、比较为 False 会安静地整段不开仓。
- [新功能] `backtest_screen.py` 新增两个组合因子 `revenue_lowvol`（波动门槛取当日横断面中位数，固定值在高波动年会筛掉全部）与 `revenue_momentum`。实测 2020 起均未胜过单纯 revenue：`revenue_lowvol` 回撤由 -53.4% 收敛到 -23.3% 但年化仅 +17.32%、Calmar 0.74（revenue 为 1.09）。
- [测试] 新增 `market_data/tests/test_adjust_infer.py`（4 例，用 2100 年合成价格与真实资料隔离）覆盖 gap 例外的三个分支；`test_hardening.py` 补 `crawl_range` 的交易日过滤与连续零列中止；`test_etl_valuation.py` 补 `parse_valuation_day` 的动态栏位定位与 schema 守卫、`parse_tpex_ex_dividend` 的民国斜线日期解析。
- [新功能] 新增台股全市场选股扫描 `scripts/screen_tw.py` 与 `make screen`（可调 `TOP`/`MIN_TURNOVER`）：直读 market schema 算全市场价量／均线／法人／融资／估值／月营收因子，三层漏斗（排除 ETF → 流动性 → 多头排列 → 法人净买）后按 rank 综合分排序，输出 markdown 到 `.claude/reviews/screen-tw-<date>.md`。补上此前缺口——主流程只有「给代码 → 出报告」，没有「扫全市场 → 给名单」。脚本刻意不碰网路、不下结论：报告第 5 节列出 DB 看不到的事件面（美股盘后／费半／台指期夜盘／FOMC 与财报行事历）作为待查清单，并标出费半连动（产业代码 24/26/28/25/31）与量能偏薄标的，由 skill `screen-tw` 指引 agent 补查后修正进场价位。**结构性盲区已在报告与 skill 内显式标注**：DB 资料截止台股当日 13:30 收盘，脚本给的价位一律是未计入隔夜盘的锚点。综合分纳入当日涨跌（权重 0.8），否则只看 20 日动能会把「当日爆量长黑」的高位股排到前列（实测 1810 和成 -7.0% 曾排第 2、6505 台塑化 -7.9% 排第 7）。
- [修复] 独立审查（Codex，gpt-5.6 xhigh）指出的三个 P0 正确性问题：(1) `scripts/screen_tw.py` **完全没套前复权**——直接读未还原价就算均线/RSI/ATR，实测候选池 44→58 檔、Top25 仅 17 檔重叠、331 檔的 20 日报酬差逾 1pp（最大 223.91pp）；现于 `load()` 内套 `load_factors()`。(2) 价格推导对 **ETF/ETN/TDR 制造假事件**：00887 在 2024-10-08、10-14 的真实 -48%/-51% 崩跌（海外休市、溢价逾 200% 的价格异常）被判成两次 1:2 分割；现由 `is_common_stock()` 一律排除非普通股，ETF 真分割改走 `VERIFIED_ACTIONS` 白名单。**踩雷：TDR 有四位数代号**（9103/9105/9110/9136），而 9802/9904/9921 是普通股，只能用 `91` 前缀区分。
- [修复] `market_data/adjust.py` 另修三项：`rebuild()` 改为真正重建（先 `delete where date >= start` 再写，否则被新逻辑否决的错事件永久残留）；因子加 `isfinite` 检查（原本只挡 `>0` 与 not-null，`inf` 仍可通过）；`screen_tw.py` 的月营收与大盘指数 SQL 补 `<= as_of` 上界（指定历史日期做回顾扫描时会直接读到未来资料），法人视窗由 `> dates[-n]` 改 `>= dates[-n]`（原本 `inst_5` 实际只算 4 日）。
- [修复] 重爬修复 6 个 TWSE 髒资料日的错误价格（2017-07-10/11、2020-04-13/14、2013-12-02/03、2025-11-27/28、2025-04-07）：MI_INDEX 回过「截断但非空」的回应，写入的价格整批错位（2020-04-13 台积电存 227.00、实际 278.5；鸿海存 93.60、实际 73.1，已用 yfinance 与官方重爬双向验证）。这些日子各有 34-39% 的股票单日变动超过 ±10% 涨跌幅限制，属物理上不可能。修复后「未由 ex_dividend 解释的价格跳空」从 4,115 笔降到 1,164 笔。截断防护是后来才加的，这批脏资料写在防护之前。
- [新功能] 新增 `market.price_adjustment` 表（Alembic `a1c4f9e27b31`）与 `market_data/adjust.py` + `cli adjust` 子命令：把除权息、减资、股票分割三类公司行动收敛成单一前复权因子表，`load_factors()` 为算报酬/均线前套用因子的唯一入口。回填 15,788 笔（官方除权息 14,908、官方减资 347、推导 505、分割 28）。**修复了一个会污染所有报酬计算的缺口**：原先前复权只读 `ex_dividend`，那张表走 TWSE 的 TWT49U，只有上市除权息，缺上柜（TPEx）全部、面额变更（分割）与减资——0050 的 1:4 分割（2025-06-18，188.65→47.57）不在表中，导致回测的 0050 基准在 2025 年显示 -65.79%。推导的理论依据是台股 ±10% 涨跌幅限制：非 ETF 的单日 >15% 跳空必为公司行动；ETF 不适用（追踪海外指数者无涨跌幅限制，2025-04-07 杠杆 ETF 单日 -28% 是真实波动），故 ETF 只认吸附成 1/N 的分割。`source` 栏标明官方值或推导值，官方永远优先。
- [新功能] `valuation` 支援歷史回补：新增 `sources.crawl_valuation_day`／`parse_valuation_day`（TWSE `BWIBBU_d`，带 date 参数），注册进 `crawl.DAILY` 并让 `cli backfill` 的 source choices 接受 `valuation`。原本 `daily` 走的 `BWIBBU_ALL` 无 date 参数、只给当日，所以这张表只能从第一次跑 daily 起累积（实际只有 3 週），PB 与殖利率完全没有历史。栏位顺序随年代变动（2015 五栏、2026 八栏且殖利率排到本益比之前），一律依回应的 `fields` 动态对应——用固定索引会让旧资料的 PE 与 PB 整栏错位。
- [修复] `crawl_range` 新增 `delay` 参数、`cli backfill` 新增 `--delay`：TWSE 密集请求会暂时封锁 IP，而失败是**静默**的（`requests_get` 回 None → `crawl_day` 跳过该日、不报错、exit code 仍为 0）。踩过：回补 1,600 天 valuation 只写进 40 天就被挡，stdout 全空看起来像成功。长区间回补一律给 `--delay 3`。
- [新功能] `sources.py` 新增 `crawl_reduction`／`parse_reduction`（TWSE TWTAUU 减资恢复买卖参考价）：这是 `ex_dividend` 没有的事件类型，减资会让股价跳升，不还原会被当成真实暴涨。栏位依回应的 `fields` 动态定位而非硬编索引（TWSE 各表栏序随年代变动）；日期用新增的 `_roc_slash_to_date`——TWTAUU 是「113/01/22」斜线格式，与 TWT49U 的「113年01月22日」不同，用错会让每列 parse 失败。全数列都失败时 raise 而非静默回空，避免减资事件永久缺漏。
- [修复] `scripts/backtest_screen.py` 交易成本未计入净值曲线：手续费与证交税只写在交易明细的 `ret` 栏，`cash` 只扣了滑价，导致 equity 系统性高估（以每年 6.6 个资金轮次计约 1.2pp/年，高频规则更严重）。改为逐笔从现金扣：买进 `buy_cost()` 加手续费、卖出 `sell_net()` 扣手续费与证交税，两者都套用单笔最低 20 元（小额交易的实际成本远高于费率），期末强制平仓一并扣卖出成本与滑价。新增 `--fee-discount`（券商折扣）与 `--max-new-per-day`（限制每日开仓数）。注：二代健保补充保费课的是**股利所得**（单笔 ≥ 2 万收 2.11%）而非交易税，本回测用前复权价、股息隐含在价格里无法逐笔分离，故未扣，此简化对策略与基准同方向。
- [新功能] `backtest_screen.py` 新增两个对等基准：`exposure_matched_cagr()` 让 0050 承受与策略相同的每日曝险（策略平均只用约 5 成资金，拿它去比「第一天全额买进」的 0050 并不对等，抽掉曝险差异后剩下的才是选股能力），以及 `dca_benchmark()` 每日定额买 0050 并以 IRR 衡量（资金逐步投入，不能用 CAGR）。实测 2020-2026：`revenue` 因子 vs 一次买进 0050 为 -1.22%，vs 同曝险 0050 为 **+15.71%**——瓶颈在资金利用率而非选股。
- [新功能] `backtest_screen.py` 新增 7 个进场因子对照（`--factor`／`--all-factors`）：`momentum`（现况）、`pure_momentum`、`revenue`（月营收 YoY）、`lowvol`、`value`、`value_momentum`、`inst`。月营收用 `announce_date` 而非 `revenue_month` 对齐（次月 10 日前才公布，用所属月份会提前看到未发布数字）；`_pit()` 的 ffill 带保鲜期上限，否则 valuation 的历史缺口会让 2020 年初的 PB 一路延用到 2026 年——讯号数看似正常但值是过期的，比没讯号更危险。
- [新功能] 新增 `scripts/backtest_screen.py`：screen_tw 选股策略的事件驱动回测，18 种出场规则对照（均线 `ma10/20/60` 及其 ATR 缓冲与 grace 变体、移动停损 `trail10/15/20`、吊灯 `chandelier3`、固定停损停利 `stop8`/`stop8_take20/30`、固定持有 `hold5/10/20/60`，以及只在期末平仓的对照组 `none`）、参数扫描、`--exclude-industry` 报酬归因，与 `--periods` 跨样本期稳健性检验（同一份讯号只换起点，输出规则×期别的年化超额矩阵与平均排名；单期第一名常是运气，跨期都在前段才可信）。三处防前视偏误写死在实现里：讯号 T 日收盘产生、成交 T+1 开盘；法人／估值资料 shift 1 个交易日（market_data cron 15:00 跑，当日法人常要 T+1 才补齐，T 日盘后取用属未来资讯）；全部价格前复权（回测期 6 月 272 檔、7 月 373 檔除息，不还原会把除息跳空当成下跌而误触停损、并漏计股息）。成本按来回 0.585%（手续费未打折 + 证交税）加单边 0.15% 滑价计。
- [测试] 新增 `tests/test_backtest_screen.py`（5 例，纯计算层）：覆盖前复权因子的单次／累积／脏资料忽略，与法人资料 lag、指标面板对齐到价格表栏位（法人/估值表覆盖标的少于价格表，不对齐会在选股时 KeyError）。
- [测试] 新增 `tests/test_screen_tw.py`（7 例，纯计算层、不碰 DB／网路）：覆盖 `compute_factors` 的均线／报酬／回撤位置／爆量比，与 `tag` 的当日重挫、费半连动、量能薄、相对大盘抗跌、PE 异常分支。
- [测试] `tests/test_tw_institution_report_wiring.py` 的共享 `_OFFSHORE_CFG` 时间预算由 stage 1.5s / fetch 0.8s 放宽到 30s / 15s：三个「tw 有数据 → institution coverage 'ok'」用例的 fetcher 全被 mock、瞬时返回，这两个预算对断言语义没有贡献，却紧到让负载中的 GitHub Actions runner 把 stage 超时、fail-open 把 institution collapse 成 `not_supported`（CI 三红、本地全绿；把预算压到 2ms/1ms 可精确复现同样三个失败与报错文案）。真正断言超时行为的用例各自带独立预算，不受影响。
- [chore] `ci.yml` 的 change-detection job 补 `permissions: contents/pull-requests: read`：本仓库 `default_workflow_permissions=read` 只涵盖 contents 与 packages，`dorny/paths-filter` 在 `pull_request` 事件下要经 API 读 changed files，缺权限会以 `Resource not accessible by integration` 失败，连带 `web-gate` 与 `desktop-futu-package-*` 全部 skip。按最小权限收敛到单个 job，不抬升仓库默认权限。
- [chore] 同步上游 main（`487e49e5`→`aa68d45d`，20 commits，含 v3.27.0）：采纳多策略审议 Phase 1/2（`skills/deliberation|synthesis|scheduler|engine`）、skill opinion 样本持久化、决策风格历史表现校准、Codex App Server 问股后端、富途持仓导入、Pipeline 最终分歧解释，以及三项与本 fork 直接相关的修复——`get_stock_info` 工具描述由「A 股专用」改为多市场（原本台股/美股问股不会调用基本面工具）、外股中文名导致英文新闻相关性漏判、yfinance 美股实时行情补 `pe_ratio`/`pb_ratio`。fork 侧收敛七处：恢复上游 `tool_surface.py`（此前按「零 caller 死代码」删除，Codex 后端使其重新有 caller）；上游对 `analyzer.py` 的 MiniMax reasoning wrapper 修复移植到本 fork 的 `src/llm/client.py`（这些方法已随 `GeminiAnalyzer(LLMClient)` 拆分下移）；上游 agent 路径的 guardrail action 追踪与 skill opinion 持久化接入共享 `_finalize_and_persist_result`（新增可选 `runtime_facts` 参数，legacy 路径传 None 保持零行为变化）；补齐 `report_language.py` 与前端 `uiText.ts`/`AnalysisContextSummary.tsx` 共 84 个 `zh-TW` 缺键（上游只加 zh/en/ko，缺键会 tsc build 失败）；删除上游针对本 fork 已移除的零调用方别名 `generate_wechat_summary` 的测试；丢弃上游 `src/agent/strategies/` 兼容 shim 测试（shim 已删）。
- [文档] AI 协作资产按「每件事只有一个家」重整，规则总量不变、只移到按需加载的位置：`AGENTS.md` §8 的 PR 审查维度顺序 / 合入阻断条件 / `fix` 类四项要求搬进 skill `analyze-pr`（落成 Step 6「合入判定」），§8.1「Review 反馈处理与补丁堆叠禁止」整节搬进新增 skill `respond-to-review`（§1.2 保留底线宣告并指向它），四处重复的「基线同步」（§8 加三个 skill 各一份）收敛到 `.claude/skills/shared/baseline-sync.md`、由各 skill 相对路径指向；§5 默认工作流删去三步（AI 默认已遵守、或与 §1 及文件开头重复）。`AGENTS.md` 307→252 行。同时修正 `.claude/skills/README.md` 的错误说明——原写 `CLAUDE.md`「应为指向 `AGENTS.md` 的软链接」，与 §2 的软链接禁令及 `check_ai_assets.py` 的 symlink 校验直接矛盾。八个 skill 的 description 收敛同义 trigger，方法论出处移入 body。
- [文档] `AGENTS.md` 审计精简并修正两处会实际误导的验证门槛：§6 原写「优先执行 `./scripts/ci_gate.sh`」实际等于跑 30+ 分钟全量离线套件（与 §10「不要把全量当快速门槛」自相矛盾），改为暴露脚本本就支持的 phase 参数 `all|syntax|flake8|deterministic|offline-tests`（实测 syntax 0.7s / flake8 4s）并标注**本机必须带 `uv run`**（脚本内部调用裸 `python`，本 fork 无全局 python，直接跑会 `command not found`）；§10 Shioaji 由「optional 依赖、需手动 `uv pip install`」改为「已列入 `requirements.txt`，真正触发静默降级 yfinance 的是缺金钥」。另：§3 结构清单降级为角色导览（补漏记的 `src/agent/` + `strategies/*.yaml`，删纯目录名零信息条目）、§1 补权限边界（装依赖/删档/改 infra/跑全量需先确认）、去重 §1.2↔§8.1 与 §5↔§9 的逐字重复、§2 收敛为指向 checker。同一门槛口径同步至 `.github/copilot-instructions.md`、`.github/instructions/backend.instructions.md` 与 `analyze-pr`/`fix-issue` skill；并补齐 copilot 镜像缺失的 fork 约定（`uv`、`LITELLM_MODEL` 须显式设、`STOCK_INDEX_REMOTE_UPDATE_ENABLED` 必须 `false`）。
- [chore] `scripts/check_ai_assets.py` 新增 skill frontmatter 校验：扫描全部 `.claude/skills/*/SKILL.md`，缺 YAML frontmatter 或 `name`/`description` 为空即 fail（CI job `ai-governance` 阻断）。此前 `analyze-issue`/`analyze-pr`/`fix-issue` 三个 skill 完全没有 frontmatter，description 退化成 H1 标题、实务上不会被自动触发，使 `AGENTS.md` §8「任务命中时优先按 skill 执行」形同失效；已补齐三者 frontmatter。
- [文档] `AGENTS.md` 同步近期重构与 fork 工作流踩雷：`src/llm/` 补 `client.py::LLMClient` transport 编排、通知渠道补 `Sender` protocol + `_senders` 注册契约、skill 列表去路径化（防目录漂移）、补 `make analyze` 不含 Doppler 包装与全量离线测试时长/flaky 判定原则、标注 `.env.example` 的 `STOCK_INDEX_REMOTE_UPDATE_ENABLED=true` 勿照抄。
- [修复] Bark（自定义 Webhook `api.day.app`）推送改按 UTF-8 字节截断 body（上限 2800 字节并附截断提示）：原按字符截 4000，中文报告实际可达 ~12KB，超出 APNs ~4KB 整包上限被 Bark 以 `PayloadTooLarge`/HTTP 500 拒绝，导致完整分析报告推送必败；现超长内容自动截断送达。
- [chore] 重构三件（无用户可见行为变更）：pipeline 双路径收尾去重为共享 `_finalize_and_persist_result`；通知 14 渠道由 mixin 多重继承改 `Sender` protocol + 组合注册表（`src/notification_sender/base.py`）；`GeminiAnalyzer` 的 LLM transport 抽出为 `src/llm/client.py::LLMClient`（继承式兼容）。新增回归测试约 60 个，全量离线套件零新增失败。
- [文档] `apps/dsa-web/AGENTS.md` 修正误导说明：UI 文案 `uiText.ts`/`locales/*.ts` 多为严格 `Record<UiLanguage, …>` 型别，漏一语 zh-TW 键会 **tsc build 失败**（非原文所称「不会编译错、仅画面缺字」）——本 session 合并上游新增文案时踩过两次。
- [chore] 跟进上游后续增量 `01ebf70a` #1984（首页自选股工作区 home watchlist workspace）：`git merge upstream/main` 并进 main；补齐 fork 的 `zh-TW` 字典 38 个 `watchlist.*` 繁体键（维持 zh↔zh-TW 键数对齐、tsc 绿）。上游同步基线更新至 `01ebf70a`，记录见 `docs/upstream-sync-2026-07-11.md`。
- [chore] 清理约 2.8k 行已验证死代码/重复：删除未接线的 `src/agent/tool_surface.py`、`src/agent/strategies/` 兼容 shim、`scripts/generate_stock_index.py`、`scripts/e2e_test_feishu_app.py`、未注册的 `bot/platforms/discord.py`（DiscordPlatform，非 ALL_PLATFORMS 成员）及多处零调用方的私有方法/别名/webhook 包装；将两份逐字复制的 `_enforce_rate_limit` 上提至 `BaseFetcher`、`_extract_guardrail_reason` 收敛到 `src/utils/data_processing.py`。均为内部实现，无用户可见行为、API/Schema/通知/报告结构变更。
- [文档] `market_data/AGENTS.md` 更新 market_repo 消费者踩雷：Phase 3 后 `institutional()`/`stock_info()` 已被 analyzer 三大法人历史趋势 prompt 消费（历史趋势走本 DB；估值/月营收/当日三大法人仍走即时 API/网路），修正原「market_repo 尚无消费者」的过时说明。
- [修复] 合并上游后收敛两处 vitest 回归：即时看板大盘指数「延迟」提示由原生 `title=` 改 `aria-label` 满足 UI governance 守卫；告警市场区域下拉测试对齐后端 `MARKET_LIGHT_ALERT_REGIONS`（仅 cn/hk/us，不含 jp/kr）。
- [文档] 新增 `docs/upstream-sync-2026-07-11.md` 上游同步记录（v3.24→v3.25 基线/裁决原则/保留增量/采纳功能/关键裁决/回滚/下次同步备忘）。
- [新功能] 台股個股分析 LLM prompt 追加三大法人歷史趨勢（外資/投信/自營/合計 連 N 日買賣超、近 5/20 日累計、合計佔股本比）：DB（`market.institutional` 14 年歷史）+ 當日網路值於 prompt 組裝層（`analyzer._format_prompt`）即時計算，tw-only、fail-open、僅進 prompt 不入持久化 context/schema/Web。新增 `market_repo.institutional()` reader（含 statement_timeout engine）與純函式 `data_provider/tw_institutional_trend.py`。
- [chore] 同步上游 `ZhuLinsen/daily_stock_analysis` main（v3.24→v3.25，62 commits）。合并 50 个冲突文件，裁决原则：以上游为 base、重放 fork 台股(tw)与 zh-TW 繁体增量。保留 fork 关键增量：`stocks.index.json` 台股种子（并入上游 30 支日股 `.T` 种子）、`TwseFetcher` 大盘复盘台股统计路由、`MarketDBFetcher` priority=1、收盘集合竞价 `tw:5`、`split_stock_list` 自选股解析；采纳上游：三大法人 fetcher+institution wiring、评分收敛/信号归因/决策信号 profiles 等 decision-signal 家族、jp/kr 大盘复盘与市场支持、ko 报告语言、AlphaSift 加固、TickFlow A 股源。报告/UI 语言统一为 `{zh, zh-TW, en, ko}`（zh↔zh-TW 键数对齐），大盘复盘市场并为 `cn/hk/us/tw/jp/kr`。`longbridge` 改用上游 platform-conditional pin（Docker py3.11→0.2.74，dev py3.12→4.x），保留 `shioaji`。
- [改进] 为 multi-agent DecisionAgent 增加内部低敏分歧摘要输入管线，作为 #1904 P1 解释输出的前置 plumbing；不改变 public API、dashboard schema 或最终解释字段。
- [修复] 推送报告、Jinja 报告与历史 Markdown 导出复用 Web/API 的评分-action 口径：高分但旧 `operation_advice` 仍为持有且无降级原因时，建议文案与三类统计展示为买入；有明确 guardrail reason 时继续保留持有/观望。
- [改进] GitHub Actions 每日分析工作流补齐 TickFlow 数据源环境变量映射，并收敛 README 数据源稳定性说明到完整指南。
- [修复] WebUI 启动时显式 `--host` / `--port` 不再被 `.env` 中的 `WEBUI_HOST` / `WEBUI_PORT` 覆盖，未传 CLI 参数时统一使用解析后的运行时配置。
- [改进] Web 首页个股栏新增历史 / 自选 / 今日切换，保留历史分析默认视图，并支持在自选页一键分析全部或仅分析今日未覆盖股票、在今日页按评分查看当天分析排行；分块提交部分失败时保留已确认计数、停止后续提交并刷新任务列表。
- [修复] Web 首页今日状态与排行使用带时区偏移的历史时间戳和完整分页数据，在查询失败、跨服务器时区边界或任务完成刷新时保持安全且准确。
- [修复] Web 首页 stock bar 刷新序列化：并发/乱序返回时仅最新请求可清除 `stockBarRefreshFailed`，避免旧响应覆盖任务完成后的刷新结果。
- [改进] GitHub Actions: 每日分析工作流（`00-daily-analysis.yml`）新增钉钉通知环境变量映射，支持在云端定时任务中直接使用钉钉机器人。
- [修复] Web 持仓页首屏快照改用 `include_realtime=false` 快速估值，跳过逐票实时行情预取后先展示持仓列表，避免外部实时行情源变慢时长时间空白等待。
- [修复] 修复任务状态接口重建报告动作字段时把合法情绪分 `0` 当成空值的问题，确保低分报告能按评分口径纠正为卖出建议。
- [修复] 修复 Agent 流式回复在未收到完成事件就断开时被显示为“（无内容）”的问题，改为提示流式响应中断并保留用户消息，避免误判为空回答。
- [修复] 修复桌面端 `WEBUI_HOST=*` / `WEBUI_HOST=[::]` 会被原样传给端口探测和后端启动导致无法监听的问题，启动前分别规范化为 `0.0.0.0` / `::`。
- [改进] `STOCK_LIST` 自选股解析支持中文逗号、顿号、分号、空格和换行等常见粘贴分隔符，运行时、定时热刷新、CLI `--stocks`、Web 设置保存和自选 API 统一识别，并在写回时规范为英文逗号。
- [改进] 新增 `NEWS_INTEL_AUTO_FETCH_ENABLED` 单开关，开启后个股分析、Agent 分析和大盘复盘会 fail-open 自动初始化并刷新 RSS/Atom/NewsNow 本地资讯池。
- [改进] Web AI 建议页新增主股票上下文，复用最近分析和股票索引候选，并改进表现统计零样本说明。
- [改进] DecisionSignal 将 `decision_profile` 升级为正式 nullable 字段，统一 same-profile 查询、去重、续期和失效语义，并保持 create metadata `null` 兼容与 SQLite 幂等回填诊断。
- [改进] 补充本次设置页布局收敛：移动端分类导航改为横向滚动列表并保证设置内容首屏可见，桌面端保留分类说明并收紧字段布局层级与间距，提升首屏效率与可配置信息密度。
- [文档] 在 README 快速开始中补充行情数据源配置说明（TUSHARE_TOKEN / Longbridge），明确未配置时仍可走 AkShare、Baostock、YFinance 等免费兜底源，日志中相关提示不影响运行。同步更新docs下的中英双份 README
- [改进] 新增 #1743 Phase 6a 内部 DSA Tool Surface 契约，统一工具 schema、stock scope fail-closed guard、结构化错误、审计摘要和脱敏诊断边界，并明确外部 AgentBackend 工具能力仍需 wire-level probe 证明。

- [修复] yfinance 分红解析：yfinance 1.2.x 将 `Ticker.dividends` 返回为单列 DataFrame（而非 Series），适配器按 Series 迭代 `.items()` 导致每笔分红被丢弃、TTM 每股分红与分红次数静默退回 `trailingAnnualDividendRate` 年率估算（如 24.0 / 分红次数 0，而非真实 TTM 合计）；现在迭代前强制转为 Series。影响所有 yfinance 后缀市场（美股/港股/日韩股/台股）。
- [修复] Discord 长报告推送按 2000 字符上限分片逐段发送，遇到 429 限流会按 `retry_after`/`Retry-After` 有限重试，避免中途失败后只收到前半段报告。
- [修复] 修复 Web 设置页定时任务“立即执行一次”后台线程未传 `stock_codes` 导致任务崩溃的问题。
- [修复] 回测日线补全将 `605066.SH`、`SS605066`、`SS.605066` 等 A 股等价代码归一为裸代码抓取和写入，避免误向数据源请求 `SS605066` 导致回测数据不足。
- [修复] 修复 Agent 流式回复在未收到完成事件就断开时被显示为“（无内容）”的问题，改为提示流式响应中断并保留用户消息，避免误判为空回答。
- [改进] `STOCK_LIST` 自选股解析支持中文逗号、顿号、分号、空格和换行等常见粘贴分隔符，运行时、定时热刷新、CLI `--stocks`、Web 设置保存和自选 API 统一识别，并在写回时规范为英文逗号。

- [新功能] 台股财报季更 CLI：`python -m market_data.cli financials --year YYYY --season N` 下载当季 IFRS 财报 html 包、解析后以长格式 upsert 进 Postgres `market.financial_statement`（Q4 单季损益由「年报累计 − 库内 Q3 累计」推导），取代已退役 finlab repo 的 sqlite/pickle 管线；finlab 本地数据（sqlite + 34G 原始 html）经逐表/逐季与 Postgres 零差异核对后删除，Postgres 为台股历史数据唯一数据源。
- [新功能] 台股 price 爬取新增截断防护与备援源：单日 TWSE+TPEx 合计低于附近 5 个交易日中位数九成时，先以 TWSE openapi `STOCK_DAY_ALL` 备援替换上市侧（仅最新交易日、全列同日才收、缺本益比栏以 COALESCE 保留旧值），仍不足则整天跳过等 resume 重试——消除「截断但非空」响应写入脏数据的事故类别（曾实际发生：单日少写 300+ 笔且数值错位）。
- [修复] market schema 历史数据清理：对 health 揪出的 32 个异常日逐日与官方源核对——7 个真 partial 日（price 3 / institutional 3 / margin 1）`--force` 换血为完整数据、13 个非交易日垃圾列（周末/春节假日却有固定 908 列的 finlab 时代残留）删除、10 个补班日经源头核对确认为合法稀疏（法人活动天然少）进入 health 白名单（`_VERIFIED_THIN`）；修复后 price/institutional/margin thin days 全部归零。
- [测试] CI backend-gate 挂 ephemeral Postgres（postgres:16 service + Alembic `upgrade head` 建 market schema），market_data 的 DB-backed 测试在 CI 真实执行而非 skip；`test_repo.py` 由依赖真实迁移数据改为自种数据（本地真实库与 CI 空库皆可跑），关闭上轮审查遗留的 CI hermetic open item。
- [改进] market_data 全模组稽核加固（Codex 全模组审查 7 项 finding + 复验 2 轮全部收敛）：`backfill --force` 整日换血修 partial/脏日（先验后删：转换过滤+PK 去重后有效列 ≥ 既有 50% 才 DELETE，来源回垃圾/严重缩水拒绝替换）；财报季更完整性 fail-fast（解析不足 1000 档或 Q4 缺同年 Q3 累计即失败、全季回滚、保留下载档）；重复键去重下沉 `writer.upsert` 本体；`health` thin-day 改局部中位数并扩至 price/institutional/margin 三表（立刻抓出旧版全域中位数漏报的 3+24+2 个既往隐形异常日）；CLI `revenue --month` 于 argparse 层验证；测试 conftest 无 DATABASE_URL 时明确 skip。新增 11 支加固回归测试（49 passed）。已知 open item：CI 无 ephemeral Postgres，DB-backed 测试在 CI 环境为 skip。
- [测试] market_data 新增 network smoke（`pytest -m network`）：TWSE/TPEx 双市场与备援/筹码端点活性、以及「面板台股历史必须走 MarketDBFetcher(Postgres) 而非静默降级 yfinance」全链验证；离线套件同步补守门/备援回归测试（38 passed）。经 Codex 审查 5 项 finding 全部修复并复验通过。
- [新功能] 补齐月营收/除权息更新路径：`market_data.cli` 新增 `revenue --month YYYY-MM`（MOPS 月营收，仅上市口径，与历史数据一致）与 `ex-dividend --start --end`（TWSE 除权息公告）；`daily` 例行更新顺带保鲜上月营收与除权息滚动窗（-30d~+90d），upsert 幂等。
- [新功能] 即时盯盘页面新增「大盘指数」列（台股加权指数 TWII + 柜买指数 TPEX），载入时抓一次并沿用页面既有 30 秒轮询 timer 一起刷新（不另开 timer）；后端新增 `GET /api/v1/stocks/indices?region=tw`（数据走 `DataFetcherManager.get_main_indices`），盯盘辅助资料失败 fail-open 回空列表、前端空资料整列不显示，均不报错；涨跌沿用台股红涨绿跌惯例并标「延迟」提示（指数走 yfinance 约延迟 15-20 分，非个股 Shioaji 即时）。
- [改进] 个股分析 LLM prompt 本体在 `report_language == "zh-TW"` 时整段改用繁体中文（台湾用语）——此前 prompt 标签/区块标题/规则说明硬写简体，DeepSeek 跟着简体 context 仍输出简体；现 `_format_prompt`/`_phase_aware_quote_labels`/`_sanitize_trend_analysis_for_prompt` 依语言取值，zh-TW 出繁体、zh/en 路径 byte-for-byte 不变，JSON 键名/`decision_type` 契约不变；`_legacy_audit_marker_specs` 的 quote/news 标记同步复用共享 `_format_prompt_tech_section_title`，避免 prompt 与 audit 重建不一致（实测 2330.TW zh-TW 输出全繁体、600519 zh 仍简体）。
- [修复] 台股即时看板涨跌停价改由 live 参考价(pre_close)算 ±10% + tick 对齐(`tw_price_limits`)，取代可能与当日参考价不同步的 shioaji `contract.limit_up/limit_down` 静态值（实测 2330 contract 给 2625/2155，昨收 2340 的正确板价应为 2570/2110）；连带修正「距涨跌停」距离与展开明细的板价显示。
- [改进] 即时看板「距涨跌停」仅在距任一侧板 ≤3% 时显示（常态离板远是噪音，当冲接近板才有意义）；走势图 X 轴补回时间刻度（日→时:分 / 月→月/日 / 年→年/月），tooltip 日期改用主题色（修复深色模式下日期文字看不到）。

- [新功能] 新增互动式价值研究 skill（`.claude/skills/value-research`）与 `scripts/financial_rigor.py` 验算工具（vendor 自 xbtlin/ai-berkshire，MIT，纯 stdlib）：对单档做价值投资式深度研究，强制 financial_rigor 验算估值（市值勾稽/PE-PB-ROE/三情境/多源交叉/Benford）、套四大师视角，结论可接回既有 alert 监控。仅互动模式、不进每日排程，不改动 data_provider/agent/pipeline。
- [新功能] 台股(.TW/.TWO)月营收补全：`TwseFundamentalAdapter` 新增 `get_growth`，用 TWSE `t187ap05_L`（上市）+ TPEx `mopsfin_t187ap05_O`（上柜）免金钥月营收快照，为台股 growth 区块**一律并列** `monthly_revenue`/`monthly_revenue_yoy`/`revenue_month`（月营收是台股最受重视的即时指标，与 yfinance 年度成长并存），并在 yfinance 缺 `revenue_yoy` 时用月营收 YoY 兜底。走 `_run_with_retry` 受 stage 预算约束、fail-open、4h 缓存。
- [改进] 价值研究相关 skill（industry-funnel / earnings-review）补充服务前置说明（用到 `curl localhost:8000` 的步骤需先 `make serve`）。
- [新功能] 台股(.TW/.TWO)基本面估值补全：新增 `data_provider/twse_fundamental_adapter.py`，用 TWSE BWIBBU_ALL（上市）与 TPEx peratio_analysis（上柜）免金钥全市场快照补上 yfinance 缺失的 PE/PB/殖利率（全市场一次抓取 + 4h TTL 缓存，一次覆盖当批所有台股；fail-open、不影响其他市场与看板路径）。`get_fundamental_context` 的台股 valuation 阶段在 quote 无 PE/PB 时叠加 TWSE/TPEx 数据，source_chain 标记 `twse_fundamental`。ETF 与不存在代码正确回空。让价值研究 skill 在台股有真实估值基准（有股价即可反推 EPS/BVPS）。
- [新功能] 价值研究闭环补全 推荐→研究→监控：新增 `.claude/skills/industry-funnel`（行业漏斗选股，套既有 AlphaSift 选股 + 价值视角排序产候选池）、`.claude/skills/earnings-review`（财报复盘，验证/推翻既有投资论题并更新监控）；新增 `scripts/value_thesis_to_monitoring.py` 把价值论题一键转成 DecisionSignal（重用既有 invalidation/watch_conditions/target_price/stop_loss 栏位）+ price_cross 告警规则。零 schema 变更、零契约变更、预设 dry-run，仅互动模式。
- [改进] 效能盘点续修三处（经两个独立 codex 审查）：①个股栏 `GET /history/stocks` 去 N+1——原每只去重股票各发 2 次 SQL（COUNT + 丢弃整列重字段）只为取分析次数，现折成一次 `SELECT code,COUNT(*) WHERE code IN(本页候选) GROUP BY code` + 内存按候选 code 求和，并先截到 `limit` 再构建（聚合范围=展示范围，避免高基数全表扫描）；②`GET /alerts/rules` 去 N+1——每条规则一次 cooldown 查询+各自 session，现一次按 `rule_id IN(...)` 批量取最新冷却记录，预取失败回退逐条；③警示 price/price_change 多目标试跑前对 `.TW/.TWO` 子集 `prime_snapshots` 一次（仅价格类规则，volume/technical 走日线不预热）。计数/冷却语义与原实现逐条等价。：①`/trend` 月/年线走 `get_history_data(include_name=False)`，不再为被丢弃的名称调用 `get_stock_name`（未入本地索引的美/港代码原会触发一次 ~1-3s 实时行情仅为取名）；②Portfolio `/snapshot` 持仓实时价改 `skip_supplement=True`，台股有 Shioaji 报价时跳过仅补市值（快照不展示）的 yfinance 往返。皆为丢弃无用工作、行为不变（Shioaji 无报价仍降级 yfinance）。
- [改进] 实时看板批量取价大幅提速（6 档 ~2.4s → 休市 ~0.06s / 盘中预估 ~0.4-0.7s）：①`StockService.get_realtime_quotes` 由逐档 sequential 改 bounded ThreadPoolExecutor(max 8) 并发；②`YfinanceFetcher.get_realtime_quote` 取名逻辑重排——本地索引/映射有名即不再调用重量级 `ticker.info`(quoteSummary ~1-3s)，仅本地查无名才回退；③`ShioajiFetcher.prime_snapshots` 一次 `api.snapshots([全部台股])` 预热短 TTL 缓存，per-code 取价命中即零网络/零锁/零熔断交互（取代被 `_SNAPSHOT_LOCK` 逐档序列化的单档快照）；④台股 Shioaji 已有报价时看板路径 `skip_supplement` 跳过仅补市值（看板不展示）的 yfinance 往返。Shioaji 不可用/无报价时仍自动降级 yfinance；单档/分析路径默认仍补充市值，行为不变。
- [新功能] 台股盘中看盘细节增强（白天看盘视角）：实时看板/报价 API 接上 Shioaji snapshot/contract 已返回但此前丢弃的关键字段——均价(VWAP，站上偏多/跌破偏空的多空分界)、涨跌停价 limit_up/limit_down 及距板%(±10% 板，触及板诚实显示「触及涨/跌停」而非「锁死」)、最佳一档委买委卖价+量(top-of-book，非五档)、最后一笔内外盘方向(last-tick，非累计内外盘比)、量比(开盘初段偏低失真，前端附提示)、振幅、现股当沖资格 day_trade(Yes/OnlyBuy/No)。看板新增「均价」列(多空着色)、价格列距板角标、名称旁「不可当沖/仅现沖买」示警角标，展开列新增「盘口明细」区块；贯穿 realtime_types→shioaji_fetcher→stock_service→StockQuote schema→web。
- [新功能] 台股交易时段感知：`trading_calendar` 收盘集合竞价窗口加入 `tw:5`，13:25–13:30 收盘前集合竞价正确标记为 CLOSING_AUCTION（XTAI 13:30 收盘、无午休）；`decision_signal_service` intraday TTL 加入 `tw:4.5`（连续竞价 ~4.42h），避免信号在收盘集合竞价前过早过期。
- [改进] 台股 LLM 分析提示新增当沖资格护栏：当 `day_trade` 为 `OnlyBuy`/`No`/未知时，不得给出（先卖／双向）当沖策略建议，避免对不可当沖标的推荐当沖。
- [修复] zh-TW 补齐上游首次启动设定检查卡（#1788）缺失的 30 个 `settings.setupGuide*`/`setupStatus*` i18n key（合并后 zhTW 词典缺键导致 web 构建 TS 报错）；`RealtimeBoardPage` 分析按钮 `title` 改 `aria-label` 以满足 UI governance。
- [chore] 同步上游 `ZhuLinsen/daily_stock_analysis` main（14 个 commit）。合并时保留 fork 增量：台股实时行情走 Shioaji 优先（不并入上游新增的 jp/kr/tw「yfinance-only」实时早退分支）、zh-TW 在地化分支（`_MARKET_LABELS_ZHTW`、analyzer 解析默认值、台股指数固定繁体名 + `TPEX` key）、日/韩市场标签；采纳上游：`_extract_analysis_json_object` JSON 抽取重构、`_infer_cn_exchange` 交易所推断、台股 DecisionSignal/Portfolio/Intelligence 服务层与 API 一级支持、longbridge docker 兼容版本钉定。
- [修复] 大盘复盘修好三个失效摘要卡：①「市场情绪」不再永远写死 50，改用真实 Market Light 盘面分数（多市场按 region 输入顺序取主市场）；②「轮动与资金」「风险与观察」不再显示「查看复盘/大盘复盘」占位字，改填 Market Light 的操作指引与温度读数。
- [修复] 大盘复盘盘面分数修正两处计分缺陷：①美股指数池含 VIX（恐慌指数），原先并入指数均值会让「恐慌飙升」被误判为 risk-on，现已将 VIX 排除在方向性指数评分之外；②指数型市场（美股，无涨跌家数/涨跌停）原先被固定 50 的缺失维度拉向中性、分数锁在 ~32.5–67.5，现按「可用维度」权重归一化重分配，使其覆盖完整 0–100 区间；全维度可用市场（A 股）分数与原公式完全一致。Market Light 的 label/guidance/temperature 补 zh-TW 繁体分支。
- [新功能] 大盘复盘 `MARKET_REVIEW_REGION` 支持逗号组合并保留输入顺序（如 `tw,us` = 台股在前、美股在后），不再只能单市场或 `both`(全部)。`config._parse_market_review_region` 接受逗号清单（去重、过滤非法值）；`market_review._resolve_market_review_regions` 与多市场合并报告均按输入顺序输出；config_registry 选项新增 `tw,us`。`both` 行为不变。
- [新功能] #1595 P1.5 新增 Provider Cache Capability Registry，按 provider、api surface、gateway 和 verification status 建模 prompt cache 能力，未知 OpenAI-compatible route 默认 telemetry only。
- [改进] #1595 P1 新增 prompt cache telemetry / analysis-path hints / diagnostics 最小配置，默认不改变 provider 请求 shape，并复用 LLM usage HMAC secret 做 domain-separated cache hint 派生。
- [新功能] 新增台股 Yahoo 后缀代码（`.TW` / `.TWO`）分析支持，接入 YFinance 日线/基础行情、市场语境、交易日历、API/Web 校验与文档边界说明。
- [改进] 台股 suffix 代码识别由仅 4 位放宽至 4~6 位，支持 `00878.TW`、`006208.TW` 等 5~6 位 ETF 代码（后端 + Web 校验同步）。
- [新功能] 新增台股全量自动补全索引（约 2100 档上市櫃个股与 ETF，来源为台湾证交所/柜买中心官方公开清单），Web 搜索可按代码/中文名称/别名提示台股标的；新增 `scripts/fetch_tw_stock_list.py`（抓官方清单生成种子 CSV）与 `scripts/merge_tw_into_index.py`（合并进索引），索引生成器同步支持 `.TW`/`.TWO` 后缀与 `TW` 市场标签。
- [新功能] 大盘复盘支持台股市场：`MARKET_REVIEW_REGION` 新增 `tw` 选项，复盘加权指数/柜买指数并接入台股策略蓝图（三大法人买卖超、新台币汇率、半导体电子权值股）；`both` 由 A股+港股+美股 扩展为 A股+港股+美股+台股；交易日历 `compute_effective_region`/`get_open_markets_today` 与个股大盘语境 region 标签同步支持 tw。
- [改进] 新增 `scripts/refresh_us_stock_index.py`：从 NASDAQ Trader 官方清单（免 key）增量补进缺失的美股新上市代码（如 SPCX），修复自动补全美股代码过时问题。
- [新功能] 台股大盘复盘接入真实市场数据：新增 `data_provider/twse_fetcher.py`（免 key，TWSE 官方 OpenAPI/rwd），复盘报告新增上市涨跌家数、成交金额与三大法人（外资/投信/自营商）买卖超净额；`get_market_stats` 按 `market_review:<region>` 路由（tw 走 TwseFetcher、跳过 A 股统计源），`TW_PROFILE.has_market_stats` 改为 True，其他市场口径不变。
- [改进] 台股大盘复盘补入上柜（TPEx）数据：成交金额与三大法人改为上市+上柜合计（上柜无公开涨跌家数端点，家数仍为上市口径）；三大法人买卖超同时注入 LLM 复盘 prompt，使复盘正文据实引用法人动向。
- [chore] 新增 `Makefile`（全部以 `uv run` 执行：serve/review-tw/analyze/test/lint 等）与 `pyproject.toml` 的 `[tool.ruff]` 配置；通知走 Doppler 注入（`make serve` 将 `BARK_URL` 映射为 `CUSTOM_WEBHOOK_URLS`，secret 不落地 .env）。`make lint` 使用 ruff（E/F/W/I）。
- [文档] 修正 `AGENTS.md` 仓库速览：市场覆盖补上日/韩/台股、移除不存在的 `src/reports/`（改列实际的 `src/notification_sender/`、`src/llm/`）、常用命令指向 `Makefile`。
- [文档] `AGENTS.md` 新增「本 fork 专属约定」段：uv/Makefile、台股 TWSE/TPEx 免 key 数据源、自动补全索引须关闭远端更新、DeepSeek 须显式设 LITELLM_MODEL、Bark 走 Doppler 注入等上游没有的约定与踩雷。
- [新功能] 新增 zh-TW(繁体中文)报告语言与 Web UI 界面语言，覆盖报告、通知、API 与前端固定文案。
- [修复] 修复通知 Markdown 表格转换在空单元格后将后续内容错配到错误表头的问题。
- [修复] 将 Docker 可安装的 Longbridge SDK 版本固定为 0.2.75，避免 `longbridge>=0.2.77` 从包索引消失后导致 docker-build 失败。
- [修复] 持仓快照今日估值改为受限并发预取多只持仓实时价，减少持仓较多时 Web 组合页面刷新超时。
- [修复] Web 首页重新分析完成后自动切换到同一股票最新生成的报告，避免仍停留在旧报告内容。

- [修复] 默认通知报告补充展示 `dashboard.phase_decision` 盘中决策护栏字段，避免与模板渲染路径展示不一致。
- [修复] 修复 Windows 环境下 Web/Desktop 静态 JS 资源可能被识别为 `text/plain` 导致前端黑屏的问题。
- [改进] Web 设置页新增首次启动配置检查卡，串联基础配置状态、自选股入口、模型配置入口和一次简短试跑。
- [改进] 通知报告的分析结果摘要不再展开 AI 决策信号明细，完整信号保留在个股详情和单股报告中。
- [新功能] #1595 P1.5 新增 Provider Cache Capability Registry，按 provider、api surface、gateway 和 verification status 建模 prompt cache 能力，未知 OpenAI-compatible route 默认 telemetry only。
- [改进] #1595 P1 新增 prompt cache telemetry / analysis-path hints / diagnostics 最小配置，默认不改变 provider 请求 shape，并复用 LLM usage HMAC secret 做 domain-separated cache hint 派生。
- [改进] 将 Docker Compose 默认内存建议从 512M 提升到 1G，并补充低配部署说明。
- [改进] 每日分析 workflow 兼容误将 `STOCK_LIST` 配到同名 Environment variables 的场景，同时保留 Repository variables 作为推荐配置入口。
- [新功能] #1772 新增台湾（台股）suffix-only 个股分析 MVP（**市场识别与数据路由层**）：手输 `.TW`（TWSE 上市）/ `.TWO`（TPEx 上柜）代码可走 YFinance 日线与近实时行情，补充市场识别、交易日历（XTAI / Asia/Taipei）、Prompt 语义与能力边界文档；加权指数 `^TWII`、柜买指数 `^TWOII`。台股股票索引/种子、Web 自动补全与告警（大盘红绿灯）市场放行作为后续 PR。
- [文档] #1772 明确本次为台股 suffix 仅路由兼容改造，对齐 #1718 日韩模式；不涉及 provider/model/base URL/运行时配置变更；回退方式为 revert 本次改动或移除 tw 入口恢复既有行为。
- [新功能] #1772 台股 `tw` 纳入 DecisionSignal / Portfolio / Intelligence 服务层与 API 市场枚举（VALID_MARKETS / _ALLOWED_MARKETS + Pydantic Literal + api_spec.json），修复数据层 MVP 下 tw 分析在 pipeline 自动抽取 DecisionSignal 时被 _normalize_market 静默丢弃的缺陷，并同步放行 DecisionSignal/Portfolio 前端市场类型与筛选及相关专题文档，对齐 #1720 日韩；告警（大盘红绿灯）市场仍为 cn/hk/us。
- [修复] 桌面与 Docker 发布显式安装 `orjson`，桌面 PyInstaller 产物同时冻结并执行运行时导入探针，避免 LiteLLM 调用时报 `No module named 'orjson'`。
- [改进] 个股报告不再单独展示“题材主线与个股位置”卡片，相关市场结构数据仍保留在分析上下文、模型 Prompt 与决策信号提取链路中。
- [改进] 通知推送与完整 Markdown/微信报告不再重复附加“AI 决策信号”摘要，DecisionSignal 的存储、告警和 Web AI 建议页保持不变。
- [改进] TickFlow 新增基于申万一级行业池的行业涨跌排行 fallback，并将基本面/市场结构单能力默认超时由 3 秒调整为 8 秒，降低正常慢响应被提前降级的概率。
- [chore] 同步上游 `ZhuLinsen/daily_stock_analysis` main 至 v3.26.1（7 commits：市场结构上下文、历史按代码批次删除、Telegram 长消息按转义后 payload 分段、orjson/AkShare calendar 发行加固、概念排行负结果复用等）。合并保留 fork 增量（Sender protocol、LLMClient、Bark 字节截断、台股三大法人趋势 prompt、pipeline finalize-and-persist）；修复合并后 CHANGELOG 中 35 条 Unreleased 条目错位到 3.26.0 段后的问题。上游同步基线更新至 `e8a9ca77`，记录见 `docs/upstream-sync-2026-07-13.md`。
- [文档] 新增 `docs/upstream-sync-2026-07-13.md` 上游同步记录（v3.25→v3.26.1 基线/裁决原则/保留增量/采纳功能/冲突处置/验证/回滚/下次同步备忘）。
- [修复] 修复日股/韩股历史列表重建市场阶段摘要时将 non_trading 等结果阶段误传为 analysis_phase 导致列表查询失败的问题。
- [新功能] 支持 SCHEDULE_TIMES 多时间定时推送，并让 Web/API/Desktop 长运行进程保存调度配置后热启停或重建 runtime scheduler。
- [改进] Web 桌面侧边栏 rail 由「图标+标签整组居中」改为左对齐固定图标列，消除各项图标左缘参差不齐的问题，并将宽度由 136px 放宽至 172px 让标签更透气（仅样式与布局，不影响导航项与路由）。
- [修复] 修复台股等经 yfinance 兜底的标的，在报告/即时看板显示 Yahoo 英文名（如 HANNSTAR DISPLAY CORP）而非本地索引中文名（彩晶）的问题：yfinance 实时行情名称优先取本地策划索引的本地化名称；分析流程不再用实时行情名称覆盖已取得的有效中文名称。注：已生成的历史报告名称为当时持久化结果，需重新分析后才会更新。
- [新功能] 大盘复盘补齐 zh-TW（繁体中文/台湾用语）在地化：此前复盘子系统仅有 en 与简体两套分支，zh-TW 会落到简体。现 `_build_review_prompt` 新增 zh-TW 分支并注入「必须使用繁体中文（台湾用语），不得使用简体字」最高优先指示，市场范围名/成交额单位/复盘标题、`market_review.py` 复盘标题与历史标签、market-review API 提交提示，以及台股指数名（台灣加權指數/櫃買指數）均补 zh-TW。报告语言由全局 `REPORT_LANGUAGE` 控制（与 UI 语言解耦，沿用既有设计），设为 `zh-TW` 即输出繁体复盘。
- [改进] Web 设置页以“定时任务”面板维护多时间定时推送、状态刷新和立即执行一次，不再向用户直接暴露 SCHEDULE_TIMES 等内部配置键。
- [修复] 修复 `--serve --schedule` 下 CLI 调度器与 Web/API runtime scheduler 状态脱节的问题，并避免设置页把失败执行时间显示为上次成功。
- [修复] runtime scheduler 的立即执行接口在已有分析运行时返回 409 忙碌状态，Web 设置页不再把未排队的请求提示为已提交。
- [修复] 避免 runtime scheduler 重建定时任务时重复立即运行事件监控，减少重复告警和后台任务状态丢失。
- [修复] Web/API runtime scheduler 接管 `--serve --schedule` 后保留 `--dry-run`、`--no-notify` 等启动参数语义。
- [改进] Web 历史报告详情不再内嵌展示 AI 建议卡片，结构化决策信号集中在 AI 建议页查询，并保留按来源报告 ID 筛选或 URL 参数精确定位入口。
- [改进] 新增 GenerationBackend Phase 1 抽象与 LiteLLM backend 配置，默认保持普通分析、`generate_text()` 和 Agent Chat 的 LiteLLM 行为不变。
- [新功能] #1743 Phase 2 新增显式 opt-in 的 `codex_cli` 本地 CLI generation backend，固定安全 preset、结构化错误、fallback、stream 降级和 usage unavailable contract。
- [改进] `GENERATION_BACKEND=codex_cli` 下普通分析与大盘复盘不再因缺少 LiteLLM API Key 被误判不可用，local CLI 失败会暴露结构化错误或按配置回退 LiteLLM。
- [改进] `codex_cli` preset 改用 `--output-last-message` 文件读取最终响应，stdout/stderr 仅作为诊断预览，避免 Codex CLI session 元数据混入主分析 JSON。
- [修复] `codex_cli` preset 不再把 Codex CLI 同时打印到 stdout 的最终响应重复计入输出上限，也不在 `stdout_preview` 暴露重复的最终响应内容。
- [修复] 恢复主分析 JSON 解析的宽松 schema fallback 语义，完整报告 schema 校验失败时继续按 raw JSON 解析，避免有效字段被错误降级为文本 fallback。
- [改进] 本地 CLI backend 对诊断 stdout/stderr 与最终响应实行执行期总量上限，并为新增 generation backend 数字配置补齐最大值校验。
- [文档] 补充本地 CLI backend 隐私边界、非离线模型说明、Docker/CI 登录态限制，以及 `codex_cli` experimental/limited 状态。
- [修复] unsupported `GENERATION_BACKEND` 在 `generate_text()` 与大盘复盘路径中显式报配置错误，避免被当成空响应或模板报告 fallback。
- [改进] Web 设置页明确 `AGENT_GENERATION_BACKEND=auto` 当前使用 LiteLLM 工具调用路径，避免暗示已有动态 backend 选择。
- [改进] Web 首页“任务已存在”重复分析提示新增手动关闭按钮与 5 秒后自动消失。
- [修复] `main.py --serve-only` 在低配主机上因 uvicorn 在 3.0s 启动自检窗口内才惰性 import 应用（litellm + 整个 app 树）导致超时退出、容器反复重启；改为在计时前于调用线程预先 import app 对象再交给 uvicorn，启动自检不再误杀慢启动。
- [修复] Docker 镜像预置 efinance 缓存目录（efinance/data）属主给非 root 运行用户 dsa，修复 A 股 efinance 数据源因写 search-cache.json 触发 PermissionError 而每次抓取失败降级的问题。
- [修复] Docker 部署中 Web 设置页保存自定义 Webhook 模板时自动转义 `$content_json` 等应用占位符，并在运行时还原，避免 Compose 重新部署将其展开为空。
- [新功能] 新增「实时盯盘」看板页（Web `/board`）与批次行情接口 `GET /api/v1/stocks/quotes?codes=...`，复用自选队列，前端 30s 轮询 + 手动刷新，按 source/staleness 诚实标示实时/延迟/不可用。
- [新功能] 新增台股 Shioaji 真即时行情数据源 `data_provider/shioaji_fetcher.py`（仅 realtime_quote，持久 session + 登入熔断），台股行情改为 Shioaji 优先、yfinance 补充/兜底；未安装 shioaji 套件或无金钥时自动降级 yfinance。
- [改进] `StockQuote` schema 追加 `source`/`as_of`/`is_stale` 字段（additive，旧客户端忽略即可），单股与批次行情接口同时带出行情来源与时效；台股 yfinance 来源显式标记延迟。
- [文档] `.env.example` 补充可选的 `SHIOAJI_API_KEY` / `SHIOAJI_SECRET_KEY` 占位（由 Doppler 注入，勿写真值），新增 `docs/realtime-board.md` 说明看板与 fallback 真值表。
- [新功能] 盯盘看板新增个股价格走势折线图（点列内联展开，日/月/年切换）；新增 `GET /api/v1/stocks/{code}/trend?range=day|month|year`。台股 day/month 走 Shioaji kbars 真资料（day 今日分钟、month 近30天 resample 日线，受 kbars 30 天/次上限），year 与非台股回 yfinance 日线。
- [改进] 看板刷新改为分批并发 + 按代码就地合并（不再整页等最慢的批次、不清空重画），并加世代守卫丢弃迟到的旧轮询结果。
- [修复] 修正 Shioaji `snapshot.ts` / `kbars.ts` 时区：其为台北裸值（非 UTC），改按 +08:00 还原绝对时刻，修复行情 `as_of`/走势时间轴差 8 小时、`is_stale` 恒为 0（假新鲜）的问题；`shioaji_trend` 取日期改用台北日期，kbars resample 先按时间排序。
- [修复] 修复 Web 回测运行未传分析日期范围、股票代码未归一化导致后端成功返回但结果为空的问题，并为空候选和行情不足返回诊断信息。
- [文档] 补充回测请求链路说明：`analysis_date_from/analysis_date_to` 与 `code` 的输入边界、归一化与筛选顺序，以及历史行情不足或候选集为空时回测返回成功响应，在 `message` 与 `diagnostics`（含 `empty_reason`）中提供可诊断信息，并同步更新 `docs/full-guide.md`、`docs/full-guide_EN.md` 示例。
- [修复] 回测代码匹配新增非法市场后缀/长度兜底：如 `600519.HK`、`600519.SZ`、`SH000001` 不再静默回落到其它有效代码，并在日期筛选重跑时对齐旧回测结果的分析日期，避免历史快照日期命中但结果列表仍为空。
- [文档] 补充 macOS 未签名、未公证 DMG 被 Gatekeeper 拦截时的架构选择、安全排查与官方安装包临时放行步骤。
- [新功能] Web AI 建议页支持确认保存基于历史报告快照重算的决策风格信号，以 created/existing/refreshed 区分新建、原样复用和既有记录续期或维度补齐，复用 profile-aware 去重与失效语义，将历史信号的创建时间、有效期和相反信号失效顺序锚定来源报告时间，并提供可审计 guardrail 提示与阻断。
- [chore] 暂停 PR Review 的自动触发，仅保留 `workflow_dispatch` 手动入口，避免辅助评审重复运行及评论权限失败产生误导性红灯；正式 CI 检查保持不变。
- [新功能] Multi-Agent specialist 运行在分析历史保存成功后，按独立 skill 持久化版本化、低敏且幂等的有效 opinion 样本，为后续后验评估提供真实数据；本阶段不计算 outcome、不统计表现、不调整权重。
- [新功能] AI 建议页在既有后验统计中增加决策风格历史表现，按每个分组独立的 30 个已完成样本门槛展示命中、区间涨跌、无法评估和最大不利波动，并保持旧统计接口兼容。
- [新功能] Multi-Agent 报告按八态用户 action 追踪 Pipeline 最终调整，排除非法 Agent 意见；仅在 canonical action 可唯一解析时生成 explanation 与 DecisionSignal，并以同一个 `final_action` 统一最终动作契约。
- [新功能] 新增 `--portfolio futu`，只读导入 Futu OpenD 真实账户的沪深 A 股、港股、美股 LONG 正股持仓作为分析列表。
- [新功能] 多策略综合新增受控 deliberation v0、可注入 mediator/self-review v1-v2、只读 revision projection v3 与 multi-round v4；所有增强层相对上一层 baseline 只能保持或继续 softened，不覆盖权威最终信号。
- [新功能] `specialist` 模式最多选择 4 个策略专家，并通过 `AGENT_SKILL_CONCURRENCY` 控制 1–4 个 worker 并发；worker 继承主管线冻结的 target date 等 `ContextVar` 状态，失败 skill 进入权威 Diagnostics 计数且不阻断其它策略或最终决策。
- [新功能] Agent Chat 按会话持久化 Skill 选择，支持刷新和会话切换恢复，并区分省略 `skills`、显式空列表与非空选择；无持久化状态的历史会话继续使用运行时默认且不会被静默转为显式选择，复用分析 `context` 中残留的 legacy `skills` / `strategies` 也不会覆盖顶层三态或会话状态，非空但全部无效的 Skill 请求不会被当成显式空列表并清空既有选择
- [改进] 后端 CI 在不跳过离线测试的前提下按完整测试文件分成三个独立 runner 并行执行，由单一 `backend-gate` 汇总门禁结果；实测文件耗时和首分片静态检查成本共同参与负载平衡，新测试文件自动纳入，现有 pip 安装和测试参数保持不变，避免 xdist 进程内并发的全局状态竞态。
- [测试] 后端 CI 默认覆盖所有非 Web 改动，仅对已证明安全的纯 Web 路径跳过，并将整个 Web public 目录及前端渠道模板、设置帮助视为跨层运行合同；补充纯 Web、共享 Web 资产及 Web/非 Web 混合改动的过滤语义回归，明确 `predicate-quantifier: every` 按单文件匹配全部规则、再以任一匹配文件触发门禁。Docker CI 继续按构建输入过滤。离线测试保留稳定的串行执行与慢用例摘要，并移除重复用例和测试内真实等待。

- [修复] Web 分享图改为用户点击“分享”后才按需生成，不再在报告加载时自动请求
- [修复] 将 `SCREENING_ENABLED` 及 Web 选股功能开关归入“基础设置”，选股导航入口继续由该开关控制
- [修复] 飞书交互机器人在 `FEISHU_DOMAIN=lark` 时让 Stream 长连接与消息回复统一使用 Lark 国际版 API 域名，避免 SDK 默认连接飞书国内域名并返回 `Incorrect domain name`（fixes #937）。
- [修复] `scripts/ci_gate.sh` 的 `offline_test_suite` 给 `pytest -m "not network"` 加 `--timeout=120 -o timeout_method=thread` 与 `-o faulthandler_timeout=300`：单个测试（含其 teardown）超过 2 分钟直接 fail，单个测试（含其 teardown）超过 5 分钟时 dump 全部线程栈到 stderr。配合 `.github/requirements-ci.txt` 新增 `pytest-timeout>=2.3.0` 依赖。issue #2131 报告过 backend-gate 在 AlphaSift hotspot 用例附近间歇性无 traceback 卡住直到被 GitHub Actions 取消，此次修复让任何未来 CI hang 都会留下可定位的失败信息或 post-mortem 栈，而不是静默消亡。同步修正 `.github/workflows/docker-publish.yml` 的 `Install backend gate dependencies` 与 `setup-python cache-dependency-path` 对齐 `ci.yml` 的 backend-gate 依赖安装方式，避免发布流程跑同一个 `./scripts/ci_gate.sh` 时因缺少 `pytest-timeout` 而直接 fail。

- [修复] 选股策略栏稳定展示完整中文策略列表，并保留自定义策略 ID 入口
- [修复] 选股热点详情统一使用中文业务文案，不再显示内部类名、字段名和原始数据源错误
- [改进] 选中热点后先展示榜单已有摘要和核心股，后台再补充完整详情，并将单次热点源等待上限收紧为 8 秒
- [修复] 刷新热点榜单并保留当前题材时同步绕过详情缓存重拉该题材，避免新榜单继续搭配旧路线与成分股；详情质量可用且字段完整时不再展示底层数据源尝试失败
- [改进] 热点成分股并行获取东方财富与同花顺数据，并按固定数据源优先级合并；AkShare 调用复用 DSA 的可终止子进程 timeout，同花顺 HTTP 调用设置 connect/read timeout，并以进程级并发槽限制活跃任务、在返回前回收 worker；题材详情可按需复用 DSA 原生搜索服务的数据源优先级、时效过滤、缓存与同请求合并补充安全且带链接的近期消息，真实供应商调用使用限流且可终止回收的子进程，并在本地压缩摘要以避免额外 LLM 等待与降级提示；显式搜索增强不写入热点详情共享缓存或 Web 页面缓存
- [修复] 选股尾部轮换以分析器输入顺序为权威并保留并列分候选顺序；热点消息增强分别追加 `route` 与原始 `timeline`，同键搜索只允许缓存 owner 启动供应商链，子进程启动或清理失败也会释放全局容量；热点默认 provider 的正数超时配置覆盖板块、成分股及直接详情 fallback 并传递剩余硬截止，关闭外层预算仍保留单源安全上限；主动新闻搜索以同一绝对 deadline 覆盖缓存等待、重新竞争和 provider 执行，并区分有效空结果与运行失败
- [改进] 精简选股页面的重复说明，将任务标识、快照统计和排序诊断折叠到运行详情
- [新功能] SkillAggregator 基于独立满足 30 条 evaluated 门槛的真实 Skill Outcome bucket，使用 Beta 先验收缩、unable 惩罚和多周期证据加权生成有界运行时权重；缺失、低样本或异常统计保持中性。
- [改进] 将参考 AlphaSift 实现的选股核心与策略正式纳入 DSA，统一使用 `ScreeningService`、`SCREENING_ENABLED` 和 `/api/v1/screening`，并保留 Apache-2.0 归因与来源版本记录。
- [新功能] 选股结果按 `run_id` 持久化到 DSA 数据库，新增运行历史和数据源历史 API，接入公告事件上下文及其搜索缓存，并支持将候选连同筛选策略映射的 skill 交给单股深度分析。
- [修复] Outcome 候选按上次尝试时间公平调度，避免持续新增的缺失 key 使旧 `pending` outcome 永久得不到重试。
- [新功能] 新增按 skill、horizon 与 outcome engine version 独立聚合的只读 Skill Opinion 表现统计；少于 30 条 evaluated 样本时仅返回观察性计数，不输出表现指标或调整运行时权重。
- [修复] 选股主模型返回空内容、非 JSON 或低覆盖结构时继续尝试备用模型；全部失败时明确展示确定性因子排序状态。最终 JSON 必须在 `content` 或 `output` 块中；`reasoning_content`（链式思考）被视为内部辅助，不作为最终结果。
- [改进] Web 选股使用浏览器匿名种子与运行 ID 在最终评分后的有界近分池中生成每次运行的候选组合；Web Storage 不可用时在页面会话内存中复用同一临时种子；本地评分覆盖完整短名单，远程分析继续遵守数量上限，且只有完成相同后置分析的候选可参与轮换；原 Top-N 前半部分、明显领先候选、硬过滤、风险否决和得分保持不变。
- [改进] 热点榜单刷新与选股长流程解除双向串行等待，热点详情改为选中后按需加载；选股默认复用 5 分钟内且数据源优先级一致的成功全市场快照，同一来源链中的后备源结果也可复用，并在后台任务中展示快照、候选上下文、LLM 重排、最终评分和新闻事件增强阶段。
- [修复] 选股日线增强改用请求级 DSA-first fetcher 注入，不再临时替换进程级函数，避免重叠请求泄漏 wrapper 或重复执行 fallback；多个后置分析器按最新分数逐级重排，远程分析状态跟随实际提交候选，超限候选统一记录为 `skipped`，外部响应也不能改写未提交候选。
- [修复] 统一等价股票代码的本地日线候选与同源窗口解析；冲突沪深交易所代码不再降级匹配裸码，回测仅接受快照或交易日历确认的起点，并在同一起点中优先完整的单一代码窗口。
- [新功能] 新增按 individual SkillAgent 自身 signal、版本化 engine 与本地已存同源日线窗口计算并持久化 `skill_opinion_outcomes` 的核心服务。
- [修复] #1970 关闭认证属于高风险操作，即使携带有效 session cookie 也强制要求再次输入当前管理员密码二次确认；后端 `auth_update_settings` 的 disable 分支统一走 currentPassword 校验，命中 rate limit 时与 enable 路径一致返回 429，前端 `AuthSettingsCard` 在关闭认证时如有缺失当前密码将阻止提交并给出内联提示。
- [改进] 优化首页侧栏任务面板与自选股工作区：支持折叠任务摘要、自选股直接打开最新详情，并压缩头部操作以释放窄侧栏列表空间。
- [修复] 收敛自选股行交互与今日状态语义：详情与移除操作使用独立可访问按钮，详情提示从当前行状态实时派生并区分查找中、查找失败和确认无详情，任何 stock-bar 请求及完成任务后的数据刷新都会在开始时进入待确认状态，旧 stock-bar 或 fallback 报告在重新确认或未知期间不会作为最新详情开放；刷新失败时不再把旧历史记录误标为今日分析，自选股刷新会显式重试列表、stock-bar 与逐股票详情查询，逐股票 fallback 使用固定 worker 并发上限并取消已失效的查询批次。
- [新功能] 新增按 individual SkillAgent 自身 signal、版本化 engine 与本地已存同源日线窗口计算并持久化 `skill_opinion_outcomes` 的核心服务；本阶段不提供管理员 API、表现统计、样本充足度或权重调整。
- [新功能] STOCK_LIST 解析新增 `parse_analysis_target()` 单条目解析契约，支持 sh/sz/bj/hk/us 前缀校验、裸码默认归股票、未命中前缀降级为股票三段语义；保留现有 `split_stock_list()`/`serialize_stock_list()` 行为不变，并对外暴露 `IndexRegistry`、`AnalysisTarget`、`ParseStatus`、`default_index_registry()` 以便上层注入自定义指数白名单（关联 issue #2063 Phase 1）
- [修复] `parse_analysis_target()` 在显式交易所后缀输入被规范化层拒绝时（如 `600519.BJ`、`600000.HK`、`1234567.SH`、`abc.SH`），不再静默改写为 `sh<digits>` 或继续走裸码分类导致误判为 US，而是直接返回 `unsupported` 并携带可定位原因；保留 `000300.SH` / `sh000300.SH` 等已知 INDEX alias 的索引命中路径（关闭 PR #2122 review blocker OR-COR-607f1395 / OR-COR-26596201 / OR-COR-d6afd0d6）
- [修复] `parse_analysis_target()` 收敛显式交易所后缀输入的 3 个新 correctness blocker：畸形混合 alias（如 `sh0x00300.SH`）不再被数字过滤后重建为已注册指数；dotted-prefix 形态（如 `SH.000999`）在 invalid base 时不被 strict-suffix 误拒，亦不静默降级为畸形 canonical stock，统一返回 `unsupported`（白名单交易所的合法 alias 通过 `sz399001.SZ` / `sz399006.SZ` 等命中 INDEX）；外盘半显式 suffix（.T/.KS/.KQ/.TW/.TWO）非法 base 不再静默回退到 US stock，而是返回 `unsupported` 并标记外盘 suffix（关闭 PR #2129 review blocker OR-COR-d83a3580 / OR-COR-b3e32200 / OR-COR-e21e9de5）
- [修复] `parse_analysis_target()` 在 `us` 前缀分支按 Phase 1 contract（issue #2063 maintainer clarification 2026-08-01）统一收紧：`us` 前缀本身大小写不敏感（`us`/`US`/`uS`/`Us` 均可），但 ticker base 必须为 canonical uppercase US symbol 形态（regex `^[A-Z]{1,5}(\.[A-Z]{1,2})?$`，与 `data_provider/us_index_mapping.py` 和 `stock_code_utils._normalize_code_and_exchange` 一致）。`us` 前缀输入只要 base 不 match 该 regex——含任意小写字母（`usfd` / `usm` / `usibm` / `usamd` / `usge` / `usbk` / `usaapl` / `usshop` 全小写、`Usfd` / `USibm` / `Usaapl` / `uSfd` / `USaapl` mixed-case prefix + lowercase base）、含标点（`usbrk.b` / `usshop.us` lowercase base with punctuation）、含数字（`us1` / `us1a` / `us12a` lowercase base with digits、`US1` / `US12345` all-uppercase but invalid US shape）一律直接返回 `unsupported` 并提示用户使用 uppercase base（如 `usAAPL` / `usBRK.B` / `usSHOP.US`）或 bare 大写形态（如 `USFD`）。docstring 同步更新明确「exchange 前缀大小写不敏感，但 `us` 后 base 必须 match canonical US symbol shape」契约。该 contract 一致规则同时关闭 PR #2129 review blocker OR-COR-9c3d2c44（`usfd`/`usm` 全 lower 静默大写）、OR-COR-2f0d1a7e（`usibm`/`usge`/`usbk`/`usaapl` 长度依赖剥前缀分叉）、OR-COR-7b45f5c1（`Usfd`/`USibm`/`Usaapl` mixed-case prefix + lowercase base 绕过 lowercase-only guard）与 OR-COR-us-prefix-nonalpha-guard-gap（`usbrk.b`/`usshop.us`/`us1` lowercase/non-alphabetic base 绕过早期 `raw.isalpha()`-gated guard 走到 `_split_prefix` 异常剥前缀），无需 US ticker 白名单。mixed-case `usBRK` / `UsBRK` / `uSBRK` / `usFD` / `usM`（prefix any case + upper base）与全 upper `USAAPL` 等仍按显式前缀剥前缀；`USFD`/`USM` 等 ≤5 字母全 upper 仍按 bare ticker 保留
- [修复] `_split_prefix()` 对带 `.US` 后缀的 bare 美股代码（`SHOP.US` / `HKD.US` / `BJRI.US` / `USFD.US` / `BRK.B` / `AAPL.US`）应用与裸 1-5 字母代码（`USFD` / `SHAK` / `AAPL`）相同的 short-circuit：只要 token 严格 match canonical US symbol shape regex `^[A-Z]{1,5}(\.[A-Z]{1,2})?$`，就不进入 `_KNOWN_PREFIXES_SORTED` 扫描。此前 short-circuit 只对纯字母 (1-5 ASCII uppercase letters) 生效，导致前两字符碰巧撞上 `sh` / `hk` / `bj` / `us` 已知前缀的 dotted `.US` 代码（`SHOP.US -> sh`+`OP.US`、`HKD.US -> hk`+`D.US`、`BJRI.US -> bj`+`RI.US`、`USFD.US -> us`+`FD.US`）被错误拆分，exchange 与 canonical_id 双双错位。mixed-case 显式前缀代码（`usAAPL` / `hk00700`）仍按原 prefix 路径处理。关闭 PR #2129 round-4 review blocker OR-COR-bare-us-suffix-prefix-collision
<!-- 新条目格式：- [类型] 描述（类型取值：新功能/改进/修复/文档/测试/chore）-->
<!-- 每条独立一行追加到本段末尾，无需分类标题，合并时冲突最小 -->
- [文档] FAQ 补充 macOS 桌面应用被 Gatekeeper quarantine 阻止启动时的受信任安装包临时放行步骤（refs #2113）。
- [新功能] LLM 渠道新增显式 Chat Completions / Responses API Surface，支持 Anspire GPT-5.6 系列等 Responses-only 模型，并统一连接测试、主分析、筛选、图片识别与状态诊断路由；所有运行路径先按同一规则解析协议再校验 Surface，混合 Surface 的同名路由按未知能力保守处理；显式 Anspire 渠道独占共享 Key，非法 Surface 或协议不匹配时不会把该 Key 回退为旧版 Chat 部署，同时保留无关的 Gemini/OpenAI 等 legacy provider；本地 loopback 渠道可在图片识别路径继续无 Key 调用，远端渠道仍要求凭据；禁用渠道不会因残留 Surface 配置阻断其他兼容 fallback；Web 编辑器不会静默改写非法历史值，并允许将 Hermes 非法 Surface 修复为 Chat Completions。
- [修复] 将 Responses 渠道的协议、模型 provider、公开 route alias 与 wire-model 构造收敛为统一路由契约，保存校验、运行时加载、状态诊断、选股入口和 Web 编辑器共同使用当前安装的 LiteLLM provider registry，拒绝 `openai` 协议下显式非 OpenAI provider 的模型、拒绝同一 alias 混用 Chat/Responses，并保留 OpenAI-compatible 网关自有的带斜杠模型 ID。
- [chore] 合并上游 `a8f084bf..ed848da6`（5 commits）：backend 测试 3-way 分片、选择性测试门槛、Responses API 显式路由、watchlist workspace 状态修复、Agent Chat skill 按 session 持久化。两处冲突的裁决与合并後修掉的静默降级见 `docs/upstream-sync-2026-08-05.md` 的「追加同步」段。
- [修复] **上游的 CI 分片把 `market_data/tests` 整组排除在离线套件外。** `setup.cfg` 的 `testpaths` 被上游从 `.` 改成 `tests`，`scripts/ci_test_shard.py::discover_test_files` 又把 `tests` 写死——本 fork 的 13 个台股 DB 测试档不报错、不变红，只是**不再跑**。改回双 root（`tests market_data/tests`）并抽出 `TEST_ROOTS`；新增 `test_shard_roots_match_the_pytest_testpaths_contract` 直接读 `setup.cfg` 做差集守门。
- [修复] **美股类别股（`BRK.B`／`BF.B`）整档静默消失。** Yahoo 用 `BRK-B`，传 `BRK.B` 回「possibly delisted」＋0 笔，而 0 笔在上游各层都被当成正常降级 ⇒ 不报错、不缺栏位，只是那档股票不见了（实测 0 笔 → 521.80／28.52）。**两份**转换器都要改：`YfinanceFetcher._convert_stock_code` 与 `yfinance_fundamental_adapter._convert_to_yf_symbol`（後者 docstring 自称是前者的 "lightweight inline reproduction"，只修一份的话行情有了、基本面全空）。後者用 `is_us_stock_code` 判定而非「有没有点」，`2330.TW`／`600519.SS`／`0700.HK` 照样原样通过；新增测试断言两份转换器一致，避免第三份漂移。
- [修复] **`BRK-B`（Yahoo 自己用的写法）被判成 A 股。** 三处美股 regex（`us_index_mapping`／`market_context.detect_market`／`stock_code_utils`）都只认点不认连字号 ⇒ 落到 A 股预设，prompt 开头写「你是一位 A 股投资分析师」并要模型按 ±10% 涨跌停与 T+1 交割推理一档美股。三处一起补上连字号；分隔符後仍只允许**一个**字母，以免 `.US` 这种交易所後缀被当成类别股而造出 Yahoo 不认得的 `AAPL-US`。
- [修复] **`UNH` 被判成 ETF。** ETF 名称关键词用子字串匹配，`UNIT` 命中 `UNITEDHEALTH` ⇒ 公司风险／财报／竞争三组检索查询整组被换成指数式查询，报告照出、只是不再看公司本身。改整词匹配（`\b(?:ETFS?|FUNDS?|TRUSTS?|INDEX|TRACKERS?|UNITS?)\b`），真 ETF（SPY／QQQ／VOO／TRACKER FUND）仍照常判出。
- [修复] **个股 prompt 与报告把所有市场都标成人民币。** AAPL 会以「收盤價 231.5 元」「成交額 115.75 亿元」进 prompt，而同一份 prompt 另一段说这是美股。币别改为跟着 `detect_market()` 走（us/hk/tw/jp/kr 各自币别）；**A 股与未知市场输出逐字未变**。
- [修复] **大盘复盘用伺服器（台北）日期盖章。** 台北时间任何时刻，美股最近收完的那场都是纽约的前一天 ⇒ 每份美股复盘都比它自己的资料早一天，而这个日期一路进报告标题、`payload['date']`、`market_light.trade_date` 与历史纪录。改用 `get_effective_trading_date(region)`（pipeline 其他地方本来就用它）。
- [修复] **指数表格的成交额栏位写死「亿」**，而 `_format_turnover_value` 对 us/hk/jp/kr 除的是 1e9 ⇒ 单位差 10 倍且币别错。改用 `_get_turnover_unit_label()`，并补 zh-TW 表头（原本连 zh-TW 也走简体表头）。
- [修复] **Market Light 的分数与它自己的依据互相矛盾。** 评分器已排除 VIX（波动率指数不是方向性指数），但两处 reason 文案没有 ⇒ risk-off 当天报告印出「盘面信号 24/100（偏弱）」的同时写「主要指数平均涨跌幅 +6.83%」。抽出 `_directional_index_changes()` 供三处共用（同时统一非有限值过滤）。
- [修复] **`zh-TW` 复盘 prompt 不看市场能力旗标。** 它把章节写死，所以 `REPORT_LANGUAGE=zh-TW`（本 fork 设定）跑美股时，模型被要求分析「漲跌停結構」与「板塊主線」——美股两样都没有资料，其中一样根本不存在这个制度——且缺少告诉它「这些资料没有」的资料边界区块 ⇒ 模型会编。zh-TW 改走与 zh/en 同一套 `_build_output_template_sections()` 能力判定，并补上 `data_limits_block` 与繁中版边界要求。
- [修复] **美股估值比率全是 null 但 `valuation.status` 回报 `ok`。** 成因是两个最佳化互撞：yfinance 行情路径**只在本地查不到股票名称时**才抓 `ticker.info`（为保住看板零网络快路径），而本 fork 补齐美股名称索引後名称一律本地命中 ⇒ `ticker_info` 恒为空 ⇒ pe/pb（与 currency）跟着消失。**索引补得越好、估值掉得越多。** 基本面 bundle 阶段本来就抓了同一个 `info`，改从那里读 `trailingPE`／`priceToBook` 并在 quote 缺值时回填、重算 status（零额外请求，与上方 tw 走 TWSE 补 pe/pb 同一形状）。实测 AAPL 35.97／42.57、NVDA 34.24／27.75；`2330.TW`（31.86／10.43）与 `600519`（19.79／7.03）未变。
- [修复] **估值比率进了 payload 却没进 prompt。** 上一条把 pe/pb 补进 `fundamental_context`，但 prompt 的估值列读的是 **quote**（`src/analyzer.py` 的 `rt.get('pe_ratio')`），而 quote 正是缺值的那一半 ⇒ 模型看到的仍是「本益比 N/A」，正确数字就在同一个 context 的另一个 key 里。prompt 改为 quote 缺值时退到基本面区块。
- [修复] **美股行情被自己标成 `FALLBACK`，导致每次美股分析都无条件判为「核心行情受限」。** yfinance 是美股（与日股／韩股）在 `base.py` 即时行情路由里的**指定主来源**，却硬编 `source=RealtimeSource.FALLBACK` ⇒ `analysis_context_builder` 判定降级、品质分 65、报告印出限制说明、LLM 的「高」信心被改写成「中」，而实际上什么都没降级（真正降级的 Stooq EOD 反而得 100 分）。新增 `RealtimeSource.YFINANCE`，只用于 `us/jp/kr`；**台股刻意维持 `fallback`**——`source` 由 `shioaji` 变成它正是本 fork 用来辨识「金钥没注入、已静默降级成延迟报价」的信号（AGENTS.md §10），`tests/test_tw_realtime_fallback.py` 把它钉成契约，实测 2330.TW 仍是 `source=fallback`／`is_stale=True`。
- [修复] **`DJIA` 的报告标题与数字差三个数量级。** `DJIA` 同时是道琼斯的通用缩写与一档挂牌 ETF（Global X Dow 30 Covered Call）。行情走 `US_INDEX_MAPPING` 取到 `^DJI` 的五万多点，名称却从 `stocks.index.json` 取到那档 ETF（约 $22.85）⇒ 标题写 ETF、数字是指数，两边都「有值」。名称解析改为美股指数别名优先于股票索引，与行情走同一个判定。
- [修复] **AlphaVantage 排在 yfinance 前面**（`data_provider/base.py` 的美股日线链）。它回**未复权**价且单次上限 100 根，而 manager 只要拿到非空 DataFrame 就收下、`storage` 又按 `(code, date)` UPSERT ⇒ 设了金钥之後，最近 100 根里的除权除息会印出错的 `pct_chg`，同一天收盘价还会随执行次数变动。目前 `.env` 没金钥所以是潜伏的，但 `.env.example` 邀请你设。改回 yfinance 优先（与 `docs/data-source-stability.md` 本来的叙述一致）。
- [修复] zh-TW 复盘 prompt 的资料边界区块改用繁体（`## 資料邊界`）——它是**要模型照做的指令**，不是注入的行情资料，得跟着报告语言走。
- [测试] 新增 `tests/test_us_market_path.py`（37 项，断言可观察输出而非内部状态）。**十项修法逐一做过 mutation 检查**：把任一修法改回旧写法必须立刻红，没过这关的测试不算守门。
- [修复] `.github/ci-test-durations.json` 移除 `tests/test_discord_platform.py`——该测试与 `bot/platforms/discord.py`（不在 `ALL_PLATFORMS` 的死代码）已在 `26b373c2` 删除，上游基准表仍列着它，导致 `test_duration_file_tracks_current_baseline_and_valid_paths` 失败。通知渠道 `discord_sender.py` 不受影响。
- [修复] 大盘复盘历史列表与详情统一展示持久化短摘要；旧记录缺少摘要时从完整 Markdown 生成无内部标记的纯文本节选。
- [修复] 大盘复盘按实际执行的生成后端和模型记录诊断，避免 Codex CLI 或 fallback 被误显示为配置模型。
- [修复] 已配置钉钉 Webhook 时不再误报“未配置通知渠道”；钉钉 Stream 仍仅用于交互，不作为定时静态推送渠道。
- [修复] WebUI/API/Desktop 以 `--serve-only` 重启后会恢复已启用的定时任务，同时保持启动时不立即执行分析；通知路由示例补充钉钉 Webhook 渠道。
- [改进] AIHubMix 注册与引流链接统一使用 inferera.com，改善中国大陆网络直连体验。
- [修复] 单股推送模式在未配置通知渠道时仍会落盘本地个股报告；CLI 启动分析若因空股票列表、个股结果全失败或本地报告保存失败而未生成报告，会显式返回失败并记录原因。
- [修复] 合并推送模式下即使个股汇总报告落盘失败，仍会先发送已有的合并通知；仅启用大盘复盘但最终未生成任何复盘内容时，分析任务会显式返回失败。
- [修复] SearXNG 公共实例发现的默认值由启用改为关闭：公共实例普遍存在限流、下线或不返回 JSON 的情况，默认开启会让未配置搜索 key 的用户每次分析多耗 30~60 秒且新闻面最终为空。运行时默认值、配置模板、中英文档与工作流诊断同步调整；显式设为 true 的用户行为不变。
- [改进] 新闻检索未执行或零命中时，报告中如实标注结论未纳入新闻面证据：零命中与「未配置搜索渠道」使用各自独立的文案，覆盖日报 / dashboard / brief / 个股 / 企业微信与模板渲染的详细与摘要分支、历史报告与分享导出、报告详情 API 与 Web 报告详情页，并按 `zh` / `en` / `ko` 分别本地化。此前该情况下消息面章节直接消失，读者无从区分「确实没有新闻」与「检索静默失败」。披露以本次分析实际收到的消息面证据为准，涵盖实时检索、社交情绪与本地已落库的资讯池三路来源；搜索命中数仅用于在确无证据时说明原因（未配置渠道 / 检索零命中），避免把已用到本地或社交证据的分析误报成「未纳入新闻面证据」。Agent 模式的命中数取自 Agent 实际消费的搜索工具结果，而非分析结束后为持久化情报而补打的查询。

- [新功能] Agent 工具调用支持按类别（data/search/analysis/action/market）配置默认超时，并允许单工具声明 `timeout_seconds`；有效超时按 first-wins 优先级解析（显式 per-run `tool_call_timeout_seconds` > 单工具显式 `timeout_seconds` > 类别默认 > 无限制），剩余 wall-clock 预算仅作不可突破的外层 cap，超时后返回结构化 `{"timeout": true}` 错误（标记 `retriable: false` 并写入 `non_retriable_tool_results` 防重试重复执行）供 Agent 继续执行而非中断循环（fixes #1890）。
- [修复] Agent 工具注册表（`src/agent/factory.get_tool_registry`）由模块级缓存改为按「类别超时映射的值」比对失效，规避 CPython 回收对象后地址复用（`id(config)` 相同）导致配置 reload 后的 `Config` 被误判为未变、沿用过期超时的真 bug；新增 `_coerce_config_timeout` 类型白名单，使调用方传入 `MagicMock` / 缺属性 stub / 脏字符串（如 `float(MagicMock())` 静默得到 1.0）时降级为「无类别限制」而非崩溃或强加 1 秒超时；`build_agent_executor(config)` / `build_agent_chat_executor(config)` 现已把调用方 `config` 透传给 `get_tool_registry(config)`（不再无参调用冻结首构 registry）；`main._reload_runtime_config` 与 `SystemConfigService._reload_runtime_singletons`（及 `update()`→`reload_now` 路径）在配置热重载时调用 `reset_tool_registry()` 强制重建；回归测试补充「传入新 config 后 registry 重建」「reload 后新超时应生效」及「builder 透传 config」三类场景（#1890 的 review follow-up，闭环 OR-COM-dd1e8fa7 / OR-COM-bff42110）
- [修复] Agent 工具超时 review 闭环（fixes #1890 的 4 个 blocker）：超时解析由 min 契约改为 first-wins（显式 per-run `tool_call_timeout_seconds` > 单工具 `ToolDefinition.timeout_seconds` > 类别默认 > 无限制，剩余 wall-clock 预算只作不可突破的外层 cap；research 路径不再传 `tool_call_timeout_seconds` 以免覆盖类别限制）；超时结果标记 `retriable: false` 并写入 `non_retriable_tool_results` 阻断 LLM 同调用重试重入，且超时触发时为仍在后台运行的 handler 武装协作取消信号（`is_tool_cancellation_requested()` 与既有 `check_tool_execution()` 检查点均响应，handler 从不轮询则行为不变），作为 review 要求的「handler 内协作取消」缓解，规避 Python 线程无法 force-stop 导致的重复执行与副作用；`_coerce_config_timeout` 对 `inf`/`nan`/负数降级为「无限制」，根绝 `future.result(timeout=inf)` 触发 `OverflowError`；`get_tool_registry` / `reset_tool_registry` 加 `threading.Lock` 双检锁，且重建后返回本次构建的局部 registry（而非全局缓存），消除并发重建竞态与跨调用超时串扰；`@tool` 装饰器将 `ToolPolicy.timeout_seconds` 折叠进 `ToolDefinition` 单一来源；统一单/并行工具超时包装（单一 executor + deadline 驱动的 wait loop，消除并行路径嵌套 executor 与线程翻倍，duration 精确到各工具自身超时值），并新增快慢工具混合并行回归；同步 `docs/full-guide_EN.md` 的超时环境变量文档；测试覆盖 first-wins、non-retriable、协作取消接线、finite 校验、缓存线程安全与快慢混合并行。
- [修复] 按最新 review 复核收敛 3 处正确性问题（OR-COM-7f3d3f5b / 3d6b61f8 / a1e8b0c2）：`BaseAgent._filtered_registry()` 携带源 registry 的类别超时映射（工具子集仍生效类别上限，不再绕过 #1890 类别超时）；并行批次 >5 时排队调用的 per-tool 超时自 worker 实际开始起算（不再提交即烧预算导致对未启动调用的假超时）；`get_tool_registry()` 缓存命中快路径在锁内读取一致对（消除与 `reset_tool_registry()` 竞态返回 `None` 或错配 registry）。新增对应回归测试。
- [新功能] 股票名称解析引擎重构增强：新增 `resolver_name_to_code_list()` 公开 API，返回按市场排序（A 股→港股→美股）的 `Stock` 候选列表（最多 5 个），新增 `US_stock_code_match()` 匹配美股 ticker（1~5 位字母且仅限本地库已存在代码，避免 hello/open 等英文词误判为股票）；AkShare 全量 A 股数据经幂等 `extend_AkShare()` 合并进全局 `stockDB`（30 分钟缓存 + 失败 5 分钟退避 + Future 单飞：TTL 过期 stale-while-revalidate 零等待、冷启动等待上界由拉取超时推导（拉取经子进程封顶 25s）、worker 先清账唤醒等待者再做日志/落盘（finally 兜底 BaseException）、成功拉取落盘 `data/cache` 跨重启复用，非中文输入跳过网络扩展），匹配策略升级为「精确→子串（≥2 汉字）→拼音子串（≥5 字母）→difflib 模糊（0.8，单字误写 0.7 兜底）」；`resolve_name_to_code()` 保持既有本地优先语义（本地精确命中零网络，调用方离线低延迟契约不变），跨市场候选能力由 `resolver_name_to_code_list()` 独立提供；解析全链路线程安全（`stockDB` 读写加锁、名称/拼音索引随库变更自动失效），新增 40 个单元测试覆盖精确/跨市场排序/子串/拼音/模糊/幂等扩展/失败退避/多候选场景。
- [改进] `StockDaily` 表新增可空 `canonical_id` 列并支持双写（Expand-Contract PR2，issue #2207）：自愈式迁移幂等加列 + 普通索引 `ix_stock_daily_canonical_id`，存量行与 `save_daily_data` 未显式传参时均经 index-aware 推导（裸指数码命中注册表时统一到指数 `canonical_id`，避免同一指数按输入形态分裂到不同桶——例如裸 `000300` 与显式 `sh000300` 现在都收敛到 `sh000300`，而非裸码被推导为 `sz000300`），推导失败写 NULL 降级；读路径仍用 `code` 列，`(code, date)` 唯一约束保留不变。显式登记契约漂移：PRD Glossary/FR-1/DD-3 与架构 AD-1/AD-7 中 canonical_id 的点分格式描述（`000016.SH`）已被 Phase 1 已合入代码的前缀格式（`sh000016`）取代，本变更遵循代码，PRD/架构文档的同步修正留待后续 PR 统一收敛。
- [新功能] 当前注册表已识别的 5 个沪深 A 股指数以显式市场输入按 canonical 身份路由：名称优先使用注册表并以 Tencent、AkShare、TickFlow 兜底，日线固定使用 Tencent、AkShare、TickFlow、yfinance 多源降级链，不读取普通 A 股日 K 的 `*_PRIORITY` 配置；裸代码仍按股票处理，并隔离同码股票名称缓存。
- [修复] Anspire 搜索默认切换为全球区域模式（`region_mode=2`），使海外股票新闻检索能够覆盖境外信息。
- [修复] 桌面端将 `builder-util-runtime` 升级至 9.7.0，修复 CVE-2026-54673 涉及的 HTTP 重定向凭据头信息泄露风险。
- [文档] 增加 xAI Grok 的 LiteLLM 配置示例、Grok Bot 集成指南和异步分析 Skill，明确分析模型与 AI teammate 两类接入边界。
- [测试] 固定 yfinance 股息 TTM 与单股报告文件名的时间夹具，消除跨日期和合并后时间基准冲突造成的 CI 波动。

## [3.30.0] - 2026-08-09

### 发布亮点

- feat: LLM 渠道新增显式 Chat Completions / Responses API Surface，统一连接测试、分析、选股、图片识别与状态诊断的协议路由。
- feat: Agent Chat 按会话持久化 Skill 选择，刷新和切换会话后可恢复，并完整保留省略、显式空列表与非空选择三态。
- feat: Electron 桌面端恢复历史报告、市场复盘和完整报告分享图；未配置自定义品牌时，统一使用随包二维码与默认“小红书@霸天土小豆”账号文案。
- feat: 新增单条分析目标解析契约，收紧交易所后缀、指数别名及美股代码的规范化边界。
- fix: 修复移动端侧栏滚动、自选股详情状态、长通知标题分片及 Lark 国际域名等用户可见稳定性问题。
- improve: 后端 CI 按测试文件分成三个 runner 并行执行，并收紧 Web 共享资产与跨层契约的门禁范围。

### 新功能

- LLM 渠道支持显式选择 Chat Completions 或 Responses API Surface，兼容 Responses-only 模型，并让连接测试、主分析、选股、图片识别和状态诊断复用统一路由契约。
- Agent Chat 将 Skill 选择按会话持久化，刷新或切换会话后恢复；历史会话继续保留运行时默认，非法 Skill 请求不会误清空已有选择。
- Electron 桌面端复用安装包自带 Chromium，为历史个股报告、市场复盘和完整报告生成 PNG 分享图；Web 与桌面端统一使用随包分发的小红书二维码。
- `STOCK_LIST` 新增 `parse_analysis_target()` 单条目解析契约，并对外暴露可注入的指数注册表及解析结果类型。

### 改进

- 优化首页侧栏任务面板和自选股工作区，支持折叠任务摘要、自选股直接打开最新详情，并压缩头部操作以释放列表空间。
- 后端 CI 按完整测试文件拆分为三个 runner 并行执行，由统一 `backend-gate` 汇总结果；继续保留稳定的离线测试语义并降低全局状态竞态风险。

### 修复

- 固定分享图小红书二维码下方的账号文案格式为“小红书@昵称”，未配置自定义昵称时默认显示“小红书@霸天土小豆”；不再渲染数字 ID，历史 ID 配置不会改变分享图模板。
- 修复首页移动端历史、自选和今日列表无法稳定纵向触摸滚动的问题，同时保持桌面端卡片裁剪行为。
- 长通知包含一级 Markdown 标题时按对应标题边界正确分片，避免错误递归耗尽长度预算并中断发送。
- 收敛自选股详情与今日状态语义：刷新和查询期间不再开放过期报告，失败时不会将旧历史误标为今日分析，并限制逐股票 fallback 并发及取消失效批次。
- 收敛 Responses 渠道的协议、provider、route alias 与 wire-model 契约，拒绝协议不匹配、同名 alias 混用 Surface 及非法历史配置。
- 飞书交互机器人在 `FEISHU_DOMAIN=lark` 时让 Stream 长连接和消息回复统一使用 Lark 国际版 API 域名，避免连接国内域名后返回 `Incorrect domain name`。
- 显式交易所后缀、畸形混合 alias、dotted-prefix 及外盘半显式后缀的非法输入不再静默改写或降级为错误市场。
- `us` 前缀保持大小写不敏感，但 ticker base 必须满足规范的大写美股代码形态；非法小写、标点或数字输入直接返回 `unsupported`。
- 带 `.US` 后缀的规范美股代码不再因前两字符碰撞 `sh`、`hk`、`bj` 或 `us` 前缀而被错误拆分。

### 测试

- 非 Web 改动默认执行完整后端门禁；纯 Web、共享 public 资产、渠道模板和设置帮助的过滤语义补充回归测试，Docker 构建继续按实际输入过滤。

### 文档

- FAQ 补充 macOS 桌面应用被 Gatekeeper quarantine 阻止启动时，对受信任安装包进行临时放行的步骤。

## [3.29.0] - 2026-08-02

### 发布亮点

- feat: 将参考 AlphaSift 实现的选股核心与策略正式纳入 DSA，新增选股运行历史、数据源历史和候选深度分析链路。
- feat: 新增 1080px 个股决策卡与高密度市场复盘分享图，支持 Web 原生分享和下载回退。
- feat: 新增 Skill Opinion Outcome 计算、表现统计与基于真实样本的有界运行时权重。
- improve: 优化选股快照复用、热点按需加载、多源并发和候选轮换，缩短长流程等待并提升结果多样性。
- fix: 加固关闭认证、短凭证诊断脱敏、CI 超时取证和桌面冻结包启动链路。
- fix: 修复 Longbridge 量比、股票代码窗口解析、选股后置重排及分享图交互等稳定性问题。

### 新功能

- SkillAggregator 基于独立满足 30 条 evaluated 门槛的真实 Skill Outcome bucket，使用 Beta 先验收缩、unable 惩罚和多周期证据加权生成有界运行时权重；缺失、低样本或异常统计保持中性。
- 选股结果按 `run_id` 持久化到 DSA 数据库，新增运行历史和数据源历史 API，接入公告事件上下文及其搜索缓存，并支持将候选连同筛选策略映射的 skill 交给单股深度分析。
- 新增按 skill、horizon 与 outcome engine version 独立聚合的只读 Skill Opinion 表现统计；少于 30 条 evaluated 样本时仅返回观察性计数，不输出表现指标或调整运行时权重。
- 新增按 individual SkillAgent 自身 signal、版本化 engine 与本地已存同源日线窗口计算并持久化 `skill_opinion_outcomes` 的核心服务。

### 改进

- 选中热点后先展示榜单已有摘要和核心股，后台再补充完整详情，并将单次热点源等待上限收紧为 8 秒。
- 热点成分股并行获取东方财富与同花顺数据，并按固定数据源优先级合并；真实供应商调用增加限流、可终止 timeout、并发槽和 worker 回收，题材详情可按需复用 DSA 原生搜索服务补充安全且带链接的近期消息。
- 精简选股页面的重复说明，将任务标识、快照统计和排序诊断折叠到运行详情。
- 将参考 AlphaSift 实现的选股核心与策略正式纳入 DSA，统一使用 `ScreeningService`、`SCREENING_ENABLED` 和 `/api/v1/screening`，并保留 Apache-2.0 归因与来源版本记录。
- Web 选股使用浏览器匿名种子与运行 ID 在最终评分后的有界近分池中生成每次运行的候选组合；本地评分覆盖完整短名单，远程分析继续遵守数量上限，硬过滤、风险否决和得分保持不变。
- 热点榜单刷新与选股长流程解除双向串行等待，热点详情改为选中后按需加载；选股默认复用 5 分钟内且数据源优先级一致的成功全市场快照，并展示快照、候选上下文、LLM 重排、最终评分和新闻事件增强阶段。
- 图片报告改用独立的 1080px 个股决策卡和高密度市场复盘卡，优先从结构化 payload 精确填充数据并保留 Markdown 回退；小红书账号与二维码支持关闭或替换，Web 支持原生分享与下载回退。

### 修复

- Web 分享图在按需生成完成后通过第二次用户点击同步打开系统分享，避免首次异步生成使原生分享退化为下载。
- Web 分享图改为用户点击“分享”后才按需生成，不再在报告加载时自动请求。
- 移除基础设置选股卡片中仍跳转到“数据源”的过期“查看配置项”按钮，并将 `SCREENING_ENABLED` 及 Web 选股功能开关归入“基础设置”。
- `scripts/ci_gate.sh` 的离线测试增加单测 timeout 与 faulthandler 取证，并同步 Docker 发布流程的 CI 依赖，避免无 traceback 卡住或发布门禁缺少 `pytest-timeout`。
- 选股策略栏稳定展示完整中文策略列表，并保留自定义策略 ID 入口。
- 选股热点详情统一使用中文业务文案，不再显示内部类名、字段名和原始数据源错误。
- 刷新热点榜单并保留当前题材时同步绕过详情缓存重拉该题材，避免新榜单继续搭配旧路线与成分股。
- 选股尾部轮换以分析器输入顺序为权威并保留并列分候选顺序；热点消息增强、共享缓存 owner、全局并发容量和新闻搜索 deadline 统一收敛。
- Outcome 候选按上次尝试时间公平调度，避免持续新增的缺失 key 使旧 `pending` outcome 永久得不到重试。
- 选股主模型返回空内容、非 JSON 或低覆盖结构时继续尝试备用模型；全部失败时明确展示确定性因子排序状态，且不把 `reasoning_content` 当作最终结果。
- 选股日线增强改用请求级 DSA-first fetcher 注入，多个后置分析器按最新分数逐级重排，远程分析状态跟随实际提交候选，避免重叠请求泄漏 wrapper 或改写未提交候选。
- 统一等价股票代码的本地日线候选与同源窗口解析；冲突沪深交易所代码不再降级匹配裸码，回测仅接受快照或交易日历确认的起点。
- 关闭认证时强制再次校验当前管理员密码，命中 rate limit 时返回 429，前端在当前密码缺失时阻止提交并显示内联提示（#1970）。
- 本地 CLI 的 `stdout_preview` / `stderr_preview` 按环境变量、JSON、YAML/日志标量与 URL 的独立契约脱敏短凭证，避免 API key、secret 或 token 进入诊断（refs #1784）。
- PyInstaller 冻结包在 NLTK 3.10 导入保护下误判内置 `_internal` 标准库时不再启动失败；Windows/macOS 打包脚本统一接入兼容 runtime hook。
- 分享图按字段合并历史结构化数据与 Markdown，多市场逐区域复用持久化 payload，隐藏不可用市场灯号维度并保留配色方案；中英韩模板跟随报告语言，原生分享失败时自动回退下载。
- 飞书文件报告在写入或上传前清理隐藏的市场 metadata；桌面运行时默认隐藏未随包提供 renderer 的 Web 分享按钮。
- `redact_diagnostic_text()` 的命令替换扫描不再吞掉尾随非敏感诊断字段，并统一 `export FOO=$(...)` 与 `FOO=$(...)` 的脱敏行为。
- Longbridge 量比改用 adaptive keyword args 调用 `history_candlesticks_by_offset`，兼容 0.2.74 与 4.x SDK 参数顺序（fixes #2100）。

## [3.28.0] - 2026-07-26

### 发布亮点

- feat: Multi-Agent 多策略综合支持分层 deliberation、mediator/self-review、revision projection 与 multi-round，并统一最终动作和解释契约。
- feat: AI 建议页新增按决策风格分组的历史表现，specialist opinion 样本可持久化并用于后验评估。
- feat: 新增 `--portfolio futu`，可只读导入 Futu OpenD 真实账户的沪深 A 股、港股和美股 LONG 正股持仓。
- feat: Web 首页与 API 支持按单个或多个市场临时触发大盘复盘，不修改全局配置。
- feat: Tushare 支持通过 `TUSHARE_HTTP_URL` 接入自建网关或兼容镜像。
- fix: 改进港股行情路由与缓存、外股英文新闻匹配、数据源兜底顺序及桌面端发包稳定性。

### 新功能

- Multi-Agent 多策略综合新增受控 deliberation v0、可注入 mediator/self-review v1-v2、只读 revision projection v3 与 multi-round v4；增强层相对上一层 baseline 只能保持或继续 softened，不覆盖权威最终信号。
- `specialist` 模式最多选择 4 个策略专家，并通过 `AGENT_SKILL_CONCURRENCY` 控制 1–4 个 worker 并发；worker 继承主管线冻结的 target date 等上下文，单个 skill 失败不阻断其它策略或最终决策。
- Multi-Agent 报告按八态用户 action 追踪 Pipeline 最终调整，排除非法 Agent 意见；仅在 canonical action 可唯一解析时生成 explanation 与 DecisionSignal，并以同一个 `final_action` 统一最终动作契约。
- specialist 在分析历史保存成功后持久化版本化、低敏且幂等的有效 opinion 样本，为后续后验评估提供真实数据；本阶段不计算 outcome、不统计表现、不调整权重。
- AI 建议页新增决策风格历史表现，按每个分组独立的 30 个已完成样本门槛展示命中、区间涨跌、无法评估和最大不利波动，并保持旧统计接口兼容。
- 新增 `--portfolio futu`，只读导入 Futu OpenD 真实账户的沪深 A 股、港股和美股 LONG 正股持仓作为分析列表。
- Web 首页与 `POST /api/v1/analysis/market-review` 支持用严格校验的 `region` 临时选择单个或多个复盘市场；一次性覆盖不读写全局配置，并贯穿任务提交、状态、SSE、结果与历史记录。
- Tushare 数据源支持通过 `TUSHARE_HTTP_URL` 自定义接入地址；留空时继续使用官方默认地址（fixes #1985）。

### 改进

- 暂停 PR Review 的自动触发，仅保留 `workflow_dispatch` 手动入口，避免辅助评审重复运行及评论权限失败产生误导性红灯；正式 CI 检查保持不变。
- `.env.example` 与每日分析 workflow 同步映射 `TUSHARE_HTTP_URL`，保持本地和云端配置入口一致。

### 修复

- 修复外股代码映射到中文显示名时英文新闻相关性漏判，统一外股代码、英文名和别名解析，并对展开后的检索词去重（fixes #2026）。
- 特权 `pull_request_target` 流程不再检出 fork PR head；敏感步骤仅执行主分支可信脚本，PR 元数据与 diff 通过 GitHub API 读取（fixes #2051）。
- PR Review 事件载荷缺失、不可读或 JSON 非法时输出可定位且不泄露载荷的警告，并保留原有降级行为（fixes #2070）。
- 修复 Windows 上 `mimetypes` 冷启动读取注册表导致进程卡死的问题。
- 统一 `DataFetcherManager`、AkShare 与 Longbridge 对 4–5 位裸港股码的识别，避免 4 位代码被错误路由或静默失败（fixes #2091）。
- AkShare 港股实时行情增加 20 分钟全市场缓存与并发冷启动 single-flight，热缓存命中不再等待网络限速，主接口异常时仍保留新浪备用接口降级（refs #1852）。
- 将 `TencentFetcher` 默认优先级调整为 A 股日 K 数据源的最终兜底，并新增 `TENCENT_PRIORITY` 显式覆盖项（refs #2032）。
- Web 设置页和通知测试入口补齐普通钉钉群机器人配置，支持安全遮罩保存 webhook 与 secret、查看帮助并发送测试通知（refs #1957）。
- Agent Chat 普通与流式接口在请求未指定 `report_language` 时继承全局 `REPORT_LANGUAGE`，显式请求值仍优先。
- WebUI 分开展示发布版本、代码版本与构建时间，并用构建输入摘要避免复用时间戳未变化的旧静态资源（fixes #2093）。
- macOS unsigned 打包显式禁用 Electron 签名与 Hardened Runtime，在冻结后端和 electron-builder 阶段清理残缺签名，并审计原始应用与 DMG 产物；该缓解不替代 Apple Developer 签名与公证（refs #2075）。

### 文档

- 修复文档中的失效相对链接。
- [修复] #2026 外股代码映射到中文显示名时英文新闻相关性判定漏判：新增同源 STOCK_ENGLISH_NAME_MAP 单一真源、canonicalize_foreign_stock_code 规范化入口与 _foreign_english_query_terms 别名解析，使 AAPL/00700/BABA 等 ticker 即使 stock_name 为中文也能在查询构建、相关性打分与多维度情报路径上复用 canonical 英文名，并补齐 .US/.HK suffix / HK 前缀全形式的归类与回归用例；同时在 _score_news_relevance 对 alias 展开 term 做去重，避免 legal alias 展开短名与显式 short alias 重复计分。
- [新功能] Tushare 数据源支持通过 `TUSHARE_HTTP_URL` 环境变量自定义接入地址，便于网络无法直达 `api.tushare.pro` 时切换自建网关或第三方兼容镜像；留空保持官方默认地址不变（fixes #1985）
- [文档] `.env.example` 与 `.github/workflows/00-daily-analysis.yml` 同步映射 `TUSHARE_HTTP_URL`，避免出现"配置项有但 workflow 漏映射"的半修状态
- [修复] #2051 PR Review 的特权 `pull_request_target` 流程不再检出 fork PR head：敏感文件、标签、报告与 AI 审查统一通过 GitHub API 将 PR 元数据和 diff 作为数据读取，只执行主分支可信脚本；Python 语法、Flake8、确定性检查和离线测试继续由无 secrets 的 `pull_request` CI / `backend-gate` 执行，兼容 `actions/checkout` 新增的 fork checkout 安全保护。
- [修复] 修复 Windows 上 mimetypes 冷启动时读取注册表导致的进程卡死

## [3.27.0] - 2026-07-19

### 发布亮点

- feat: 新增 Codex App Server single-agent 问股实验原型，并保持 LiteLLM、Multi Agent、普通报告和定时任务等默认链路不变。
- feat: Web AI 建议页支持保存基于历史报告快照重算的决策风格信号，补齐去重、续期、失效和可审计 guardrail 语义。
- feat: 引入多策略观点结构化输出第一阶段契约，覆盖观点标准化、基础冲突检测、聚合元数据和报告兼容边界。
- improve: 报告页明确展示输入数据状态、来源、异常影响、处理建议和诊断码，并区分页面资讯与本次分析输入。
- fix: 修复 MiniMax 推理内容污染最终 JSON、字符串 `<think>` 包装兼容及多 Agent 风险覆盖后结论未按最终信号收敛的问题。
- fix: 补齐美股实时行情 PE/PB 估值字段、多市场工具描述和 macOS Gatekeeper 安装排障说明。

### 新功能

- 新增 #1743 Phase 6 Codex App Server single-agent 问股实验原型，仅开放三个既有只读 Tool Surface 工具；默认 LiteLLM、Multi Agent、Deep Research、普通报告、定时任务与 Phase 1/2 `codex_cli` 路径保持不变。
- Web AI 建议页支持确认保存基于历史报告快照重算的决策风格信号，以 created/existing/refreshed 区分新建、原样复用和既有记录续期或维度补齐，并复用 profile-aware 去重与失效语义。
- 多策略观点结构化输出第一版新增策略观点标准化、基础冲突检测与聚合 metadata，作为 #1964 的阶段性基础契约；本版本不声明完成并发执行、完整策略调度 MVP 或前端完整多语言展示。

### 改进

- Codex 设置页仅检查配置、命令和所需协议是否允许尝试，用户保存后可直接提问；Chat 以服务端 `accepted` 事件提交问题并按实际 backend 停止。
- Web 报告页输入数据块沿用状态、来源、告警和说明字段，在说明中补充异常影响、处理建议与诊断码，并区分报告页资讯和本次分析输入。
- 更新 Anspire 数据源的项目展示信息，并将 `get_stock_info` 工具说明从 A 股限定修正为覆盖 A 股、港股和美股。

### 修复

- 修复 MiniMax 分析与渠道 JSON 测试把推理内容和最终文本拼接后导致结果无法解析、无法持久化的问题；字符串响应仅剥离开头完整的 `<think>` 包装，并保留 JSON 内容中的同名字面标签。
- 修正多 Agent 内部 runtime facts 的 timeout 归因，并让 risk application 覆盖后的 dashboard 决策字段及一句话核心结论基于 post-risk signal 完成 finalization。
- 收敛多策略综合器语义：正确处理 Signal 枚举、缺失 signal、有效 opinion_count 和 deterministic synthesis，并兼容历史与外部 dashboard 的宽松字段形状。
- Codex 问股只接受 App Server 明确完成的终态回答，并统一整体时限、累计输出、事件、工具预算和进程回收边界。
- `codex_cli` 普通分析显式固定无人值守批准策略与只读沙箱，避免新版 Codex 在非交互任务中因请求人工批准而中断。
- yfinance 美股实时行情补齐 `pe_ratio` 和 `pb_ratio`，供估值分析和下游报告使用。

### 文档

- 补充 macOS 未签名、未公证 DMG 被 Gatekeeper 拦截时的架构选择、安全排查与官方安装包临时放行步骤。

## [3.26.1] - 2026-07-12

### 发布亮点

- feat: Web 首页新增历史、自选与今日工作区，支持批量分析、今日覆盖判断和评分排行。
- feat: 新增 A 股市场结构与题材主线上下文，并贯通报告、Agent、DecisionSignal 与 Web 展示。
- feat: 飞书支持文件形式推送报告，多 Agent 支持子 Agent 独立超时钳位。
- feat: 补齐内部 DSA Tool Surface、DecisionAgent 分歧摘要和 DecisionSignal profile 契约。
- fix: 统一报告动作口径，修复按股票代码批量删除历史记录和通知理由静默截断问题。
- fix: 改进 Web、桌面端、数据源缓存及发行包资源的稳定性。

### 新功能

- 新增 A 股市场结构与题材主线上下文，并在报告、Agent、DecisionSignal 和 Web 市场位置卡中复用。
- 飞书推送新增文件上传能力：`FeishuSender.send_feishu_file(file_path)` 通过 App Bot SDK (`im.v1.file.create`) 上传文件并发送文件消息；Webhook 模式回退为发送文件内容文本；新增 `FEISHU_SEND_AS_FILE=true` 配置开关，开启后飞书以文件形式发送报告而非文字消息。
- 多 Agent 编排 Pipeline 新增子 Agent 独立超时钳位：支持 6 个环境变量为 TechnicalAgent、IntelAgent、RiskAgent、DecisionAgent、PortfolioAgent、SkillAgent 各自配置独立硬上限，互不挤占配额；默认 0 表示关闭钳位。

### 改进

- 为 multi-agent DecisionAgent 增加内部低敏分歧摘要输入管线，作为 #1904 P1 解释输出的前置 plumbing；不改变 public API、dashboard schema 或最终解释字段。
- GitHub Actions 每日分析工作流补齐 TickFlow 数据源环境变量映射，并收敛 README 数据源稳定性说明到完整指南。
- Web 首页个股栏新增历史 / 自选 / 今日切换，保留历史分析默认视图，并支持在自选页一键分析全部或仅分析今日未覆盖股票、在今日页按评分查看当天分析排行；分块提交部分失败时保留已确认计数、停止后续提交并刷新任务列表。
- GitHub Actions 每日分析工作流新增钉钉通知环境变量映射，支持在云端定时任务中直接使用钉钉机器人。
- `STOCK_LIST` 自选股解析支持中文逗号、顿号、分号、空格和换行等常见粘贴分隔符，运行时、定时热刷新、CLI `--stocks`、Web 设置保存和自选 API 统一识别，并在写回时规范为英文逗号。
- 新增 `NEWS_INTEL_AUTO_FETCH_ENABLED` 单开关，开启后个股分析、Agent 分析和大盘复盘会 fail-open 自动初始化并刷新 RSS/Atom/NewsNow 本地资讯池。
- Web AI 建议页新增主股票上下文，复用最近分析和股票索引候选，并改进表现统计零样本说明。
- DecisionSignal 将 `decision_profile` 升级为正式 nullable 字段，统一 same-profile 查询、去重、续期和失效语义，并保持 create metadata `null` 兼容与 SQLite 幂等回填诊断。
- 设置页移动端分类导航改为横向滚动列表并保证设置内容首屏可见，桌面端保留分类说明并收紧字段布局层级与间距。
- 新增 #1743 Phase 6a 内部 DSA Tool Surface 契约，统一工具 schema、stock scope fail-closed guard、结构化错误、审计摘要和脱敏诊断边界，并明确外部 AgentBackend 工具能力仍需 wire-level probe 证明。
- `src/services/analysis_service.py` 在 `report` 详情层新增 `details.raw_result` 回填，补齐与 API/历史详情的报告载荷一致性；不改变 provider、model、Base URL 或配置迁移语义。

### 修复

- 按股票代码删除历史记录时分批清理全部匹配项，并拒绝空白代码，避免超过 10000 条后残留记录或无筛选删除。
- 市场结构概念排行为空或超时时复用本轮负结果，避免批量个股分析重复请求同一概念排行数据源。
- Windows/macOS 桌面后端打包显式收集并校验 AkShare `file_fold/calendar.json`，避免发行包因缺少交易日历 package data 导致热点题材和选股日线增强降级。
- 邮件、Telegram 与报告共享的 DecisionSignal 摘要完整展示已脱敏的理由，避免固定 120 字符在句中无提示截断；Telegram 按最终 Markdown payload 长度安全分片。
- 推送报告、Jinja 报告与历史 Markdown 导出复用 Web/API 的评分-action 口径：高分但旧 `operation_advice` 仍为持有且无降级原因时，建议文案与三类统计展示为买入；有明确 guardrail reason 时继续保留持有/观望。
- WebUI 启动时显式 `--host` / `--port` 不再被 `.env` 中的 `WEBUI_HOST` / `WEBUI_PORT` 覆盖，未传 CLI 参数时统一使用解析后的运行时配置。
- Web 首页今日状态与排行使用带时区偏移的历史时间戳和完整分页数据，在查询失败、跨服务器时区边界或任务完成刷新时保持安全且准确。
- Web 首页 stock bar 刷新序列化：并发或乱序返回时仅最新请求可清除 `stockBarRefreshFailed`，避免旧响应覆盖任务完成后的刷新结果。
- Web 持仓页首屏快照改用 `include_realtime=false` 快速估值，跳过逐票实时行情预取后先展示持仓列表，避免外部实时行情源变慢时长时间空白等待。
- 修复任务状态接口重建报告动作字段时把合法情绪分 `0` 当成空值的问题，确保低分报告能按评分口径纠正为卖出建议。
- 修复 Agent 流式回复在未收到完成事件就断开时被显示为“（无内容）”的问题，改为提示流式响应中断并保留用户消息。
- 修复桌面端 `WEBUI_HOST=*` / `WEBUI_HOST=[::]` 会被原样传给端口探测和后端启动导致无法监听的问题，启动前分别规范化为 `0.0.0.0` / `::`。

### 文档

- 在 README 快速开始中补充行情数据源配置说明（`TUSHARE_TOKEN` / Longbridge），明确未配置时仍可使用 AkShare、Baostock、YFinance 等免费兜底源，并同步中英文完整指南。

## [3.25.0] - 2026-07-03

### 发布亮点

- feat: 新增 `claude_code_cli`、`opencode_cli` generation-only 本地 CLI backend，并补齐生成后端状态诊断、预览、冒烟测试 API 和 Web 状态面板。
- feat: 台股报告完整接入三大法人资料，覆盖报告渲染、LLM prompt、TWD 币别标示、收盘集合竞价识别和 fetcher 韧性加固。
- feat: 新增钉钉群机器人通知、韩语报告输出和 AI 建议决策风格重评估预览。
- feat: Agent `/chat/stream` 标准化 progress event，新增阶段开始/完成、pipeline timeout 和预算跳过语义。
- fix: 修复桌面端 WebUI host/port 绑定、macOS Homebrew CLI PATH 诊断、Discord 长报告分片、AlphaSift 超时、yfinance 分红解析、A 股回测代码归一化等稳定性问题。

### 新功能

- 钉钉群机器人通知支持 `DINGTALK_WEBHOOK_URL` 和 `DINGTALK_SECRET`，并对长文本自动切片以适配 20KB 限制。
- 报告输出语言新增韩语（`REPORT_LANGUAGE=ko`），覆盖个股报告、大盘复盘、Prompt 输出语言、决策护栏、通知模板标签与 Web 报告详情页文案。
- 新增 `claude_code_cli` 与 `opencode_cli` generation-only 本地 CLI backend，保留 LiteLLM 默认路径、Agent 工具调用边界、per-preset extractor、最小 env allowlist 与结构化错误。
- 新增生成后端状态、预览和冒烟测试 API，以及 Web 生成后端状态面板，区分轻量检查与 JSON 冒烟测试，并保持本地 CLI “仅生成、不支持问股工具调用”的边界。
- Agent `/chat/stream` progress event 新增 `stage_start`、`stage_done`、`pipeline_timeout`、`pipeline_budget_skipped`，补齐阶段进度、超时和预算跳过语义。
- 台股个股报告的 institution 区块展示 TWSE T86 / TPEx 三大法人原始买卖超净额，并将三大法人净买卖超表格注入 LLM 分析 prompt 作为台股筹码过滤器。
- 新增 AI 建议决策风格重评估预览接口与页面预览。

### 改进

- 台股三大法人 fetcher 增加并发缓存防击穿、TWSE/TPEx 分市场熔断、TPEx 日期保护和剩余 stage 预算复用，降低限流、端点故障和冷抓取超时带来的降级概率。
- AlphaSift 默认依赖 pin 更新到 `9f522747caafd3c0b1ddb7e14d5cf44c8580b6cf`，接入 wrapper 数据源 caller-side timeout、东财直连限速/抖动、策略目录元数据和防守策略。
- 选股任务状态轮询遇到可恢复超时时提示后台任务仍会自动重试，`.env.example` 补充相关超时调优项。
- 收敛个股分析评分与 DecisionSignal action 口径，统一 80/60/40/20 分段，并在风控降级时记录 raw/adjusted score、final action 与原因。
- Web 设置页左侧分类切换时仅在相关分类展示首次启动检查和 AlphaSift 辅助卡片，减少跨分类残留。

### 修复

- 修复 Windows 桌面端启动后端时固定传入 `--host 127.0.0.1` 导致 `.env` 中 `WEBUI_HOST=0.0.0.0` 不生效、局域网无法访问 WebUI 的问题；桌面端仍默认使用 `127.0.0.1`，仅在显式配置 `WEBUI_HOST` 后按配置绑定。
- 修复桌面端启动时 `.env` 中 `WEBUI_PORT` 与 Electron 自动选择端口不一致，导致窗口继续等待旧端口并连接超时的问题。
- 修复 macOS 桌面端从 Finder/Dock 启动时后端 PATH 看不到 Homebrew Codex CLI 的问题，并明确 Codex CLI 主分析与 Agent LiteLLM 工具调用分流诊断。
- 修复 Discord 长报告推送按 2000 字符上限分片逐段发送，遇到 429 限流会按 `retry_after`/`Retry-After` 有限重试，避免中途失败后只收到前半段报告。
- 修复日股、韩股和台股 `market_phase` 收盘集合竞价识别，避免临近收盘阶段仍被标记为普通 `intraday`。
- 修复 A 股个股分析遇到空 `belong_boards` 占位时不会继续补查所属板块、关联板块模块展示不稳定的问题。
- 修复大盘复盘在 LLM 标题漂移或正文缺少板块段时，Web 与推送报告偶发缺少板块主线的问题。
- 修复 Web 大盘复盘结构化数据成交额、指数点位、涨跌幅和高/低值格式化，避免浮点长尾或缺失值 `0.00` 直接展示。
- 修复 Web 首页个股栏在 stock-bar 摘要字段缺失或动作建议无法归类时隐藏情绪分与建议标识的问题。
- 修复 Web 设置页定时任务“立即执行一次”后台线程未传 `stock_codes` 导致任务崩溃的问题。
- 修复 `opencode_cli` 静态指令，避免全局 JSON-only 约束影响 `generate_text()` 与大盘复盘自由文本输出。
- 修复 yfinance 1.2.x 将 `Ticker.dividends` 返回为单列 DataFrame 时分红解析被丢弃的问题，恢复 TTM 每股分红与分红次数计算。
- 修复台股财务金额币别标示，将 TWD 金额标注为“新台币”，避免在 A 股语境下误读为人民币。
- 修复回测日线补全将 `605066.SH`、`SS605066`、`SS.605066` 等 A 股等价代码误向数据源请求 `SS605066`，导致回测数据不足的问题。

### 文档

- 新增 Agent `/chat/stream` progress event 契约文档，说明新增事件字段语义、Web 兼容边界、验证方式和回滚方式。
- 同步本地 CLI backend 隐私/部署边界，明确 local CLI 不是离线模型，Docker/CI/远端需自行安装登录，DSA 不读取 Claude/OpenCode credential 文件。
- 更新 README 三语入口和市场支持边界，说明台股 `.TW` / `.TWO`、三大法人报告区块、TWD 标注与收盘竞价识别能力边界。

### 测试

- 台股三大法人 fetcher 新增 live-smoke 脚本与 `@pytest.mark.network` 漂移检测测试，用于非阻断 network-smoke 定时任务核对 TWSE T86 / TPEx 核心字段与解析结果。

## [3.24.1] - 2026-06-28

### 修复

- 修正 Longbridge SDK 版本约束为按平台选择可安装版本，避免桌面与 Docker 发布在 `pip install -r requirements.txt` 时因不存在的 `0.2.75` 版本失败。

## [3.24.0] - 2026-06-28

### 发布亮点

- feat: 扩展台股、日股、韩股市场支持，覆盖台股 suffix-only 分析、台股三大法人资料层、JP/KR 大盘复盘和跨服务市场枚举。
- feat: 新增 GenerationBackend 抽象、`codex_cli` 本地 CLI backend、reserved Hermes 本地 HTTP 渠道和 prompt cache capability registry。
- feat: Web/API/Desktop 支持多时间定时推送与 runtime scheduler 热重建，Web 设置页补齐首次启动检查与定时任务面板。
- feat: 报告链路补齐信号归因、单股信号时间线、概念板块排行和通知/报告关联板块展示。
- fix: 修复 Docker/启动探针、静态资源 MIME、回测空结果、组合估值、通知 Markdown、AlphaSift 数据源和测试环境隔离等稳定性问题。

### 新功能

- 新增台股 suffix-only 个股分析 MVP：`.TW`/`.TWO` 代码可走 YFinance 日线与近实时行情，并补齐市场识别、交易日历和 Prompt 能力边界。
- 台股 `tw` 纳入 DecisionSignal、Portfolio、Intelligence 服务层、API 枚举和 Web 筛选，避免台股分析信号被市场归一化静默丢弃。
- 新增台股三大法人资料层 fetcher `TwInstitutionalFetcher`，支持 TWSE/TPEx 来源、日期转换、单日缓存和 fail-open 退化。
- 大盘复盘新增 `jp`/`kr` 市场，支持日经225/TOPIX、KOSPI/KOSDAQ 指数复盘，并扩展 `MARKET_REVIEW_REGION`、交易日过滤和 Web 设置枚举。
- 新增 GenerationBackend Phase 1 抽象和显式 opt-in 的 `codex_cli` 本地 CLI generation backend，提供结构化错误、fallback、stream 降级和 usage unavailable contract。
- 新增 reserved Hermes 本地 HTTP generation 渠道，提供 JSON generation、no-proxy 本地调用和 saved secret endpoint 绑定。
- 新增 Provider Cache Capability Registry，按 provider、API surface、gateway 与 verification status 建模 prompt cache 能力。
- 支持 `SCHEDULE_TIMES` 多时间定时推送，长运行 Web/API/Desktop 进程保存调度配置后可热启停或重建 runtime scheduler。
- 新增信号归因分析和 Web AI 建议页单股信号时间线，并为自动生成与历史回填的 DecisionSignal 写入默认 `decision_profile` metadata。
- 大盘复盘、Web 报告页和通知关联板块补齐概念板块排行与概念信号展示。

### 改进

- TickFlow 扩展为可选 A 股日 K、实时行情、股票列表/名称数据源，并增加 count、完整性校验和批量预取缓存保护。
- 硬化 JP/KR/TW suffix 识别、日韩股票种子索引、YFinance 报价/基本面上下文，以及 JP/KR Portfolio 与 Market Light 边界。
- Web 设置页新增首次启动配置检查卡与定时任务面板，隐藏内部 `SCHEDULE_TIMES` 键，并改善重复任务提示的关闭与自动消失体验。
- Web 历史报告详情不再内嵌 AI 建议卡片，结构化决策信号集中到 AI 建议页，并保留来源报告 ID/URL 参数精确定位。
- `GENERATION_BACKEND=codex_cli` 下普通分析与大盘复盘不再因缺少 LiteLLM API Key 被误判不可用，并改用 `--output-last-message` 文件读取最终响应。
- 本地 CLI backend 对 stdout/stderr 诊断预览和最终响应实行执行期总量上限，并补齐新增 generation backend 数字配置最大值校验。
- AlphaSift 默认依赖 pin 更新到 `0a7b9cd59e81718f851890535241bc105d4ddc64`，并默认走 DSA EastMoney 兜底 provider、暴露 source health 诊断。
- Docker Compose 默认内存建议提升到 1G；每日分析 workflow 兼容误将 `STOCK_LIST` 配到同名 Environment variables 的场景。
- Agent 路径同步 signal attribution prompt，通知报告摘要不再展开 AI 决策信号明细，完整信号保留在个股详情与单股报告。

### 修复

- API 异步批量分析共享概念板块排行缓存，避免同批多股重复拉取全市场概念排行。
- 修复通知 Markdown 表格转换在空单元格后将后续内容错配到错误表头的问题。
- 修复 Market Light 区域归一化拒绝 `jp`/`kr`、日韩历史列表市场阶段摘要误传 `analysis_phase` 和默认通知报告缺少 `dashboard.phase_decision` 的问题。
- 固定 Docker 可安装的 Longbridge SDK 版本为 0.2.75，并修复 Docker 镜像中 efinance 缓存目录属主导致 A 股数据源降级的问题。
- 持仓快照今日估值改为受限并发预取实时价，减少持仓较多时 Web 组合页面刷新超时。
- Web 首页重新分析完成后自动切换到同一股票最新报告，并修复 Windows 环境下 Web/Desktop 静态 JS 资源可能以 `text/plain` 返回导致黑屏的问题。
- 修复 `--serve --schedule` 与 Web/API runtime scheduler 状态脱节、立即执行忙碌状态误提示、重建定时任务重复监听和启动参数语义丢失。
- 修复 `main.py --serve-only` 在低配主机上因惰性 import 应用超出 uvicorn 启动自检窗口而反复重启的问题。
- 修复 Web 回测未传分析日期范围、股票代码未归一化导致成功响应但结果为空的问题，并为空候选、行情不足和非法后缀提供诊断信息。
- 修复 unsupported `GENERATION_BACKEND` 被当成空响应/模板 fallback、`codex_cli` stdout 重复计入输出上限和主分析 JSON schema fallback 语义回退的问题。
- Docker 部署中 Web 设置页保存自定义 Webhook 模板时会转义 `$content_json` 等占位符，并在运行时还原，避免 Compose 重新部署展开为空。

### 文档

- 补齐概念板块排行字段契约、通知报告行业/概念类型列展示和数据源稳定性与故障处理图示。
- 补充 JP/KR/TW suffix-only MVP、`MARKET_REVIEW_REGION` 保存/校验/回退矩阵、Market Light 边界和 PR 提交流程约束。
- 补充本地 CLI backend 隐私边界、非离线模型说明、Docker/CI 登录态限制和 `codex_cli` experimental/limited 状态。
- 补充回测请求链路说明，并同步更新 `docs/full-guide.md` 与 `docs/full-guide_EN.md` 示例。

### 测试

- 新增/更新台股、JP/KR 大盘复盘、GenerationBackend、`codex_cli`、Hermes、本地 CLI、runtime scheduler、回测和概念板块排行相关回归测试。
- 加强 `tests/test_analysis_api_contract.py`、`tests/test_analysis_history.py` 与 `tests/test_backtest_service.py` 的临时 `.env` 隔离，避免本地真实 `.env` 污染系统配置测试。

## [3.23.0] - 2026-06-20

### 发布亮点

- feat: DecisionSignal 贯通报告提取、Web 展示、反馈/后验、告警通知和组合风险，AI 建议信号进入可追踪闭环。
- feat: 新增合规 RSS/Atom 与 NewsNow 资讯源情报池，分析、Agent 和大盘复盘可 fail-open 复用本地资讯 evidence。
- feat: 新增日本/韩国 suffix-only 个股分析 MVP，支持 `.T`、`.KS`、`.KQ` 标的通过 YFinance 获取行情与技术上下文。
- feat: 新增 Token 用量监控看板、legacy LLM usage telemetry 和 message stability audit，增强 LLM 调用可观测性。
- fix: 修复运行流 live 状态、AlphaSift 缓存/字段兼容、发布说明诊断和日韩股票输入/历史展示等稳定性问题。

### 新功能

- 个股分析历史成功保存后会从最终报告 best-effort 提取 `DecisionSignal` 决策信号，复用现有信号去重、计划质量计算和脱敏契约。
- 新增 Web AI 建议页、持仓页 latest active 信号摘要、历史报告信号展示和更完整的信号详情卡片，展示评分、置信度、价格计划、催化、风险与失效条件。
- 新增 DecisionSignal 用户反馈、信号级日线后验评估、统计 API 与 Web 展示，使用 outcome/feedback sidecar 表并保留主信号表契约。
- 将 DecisionSignal 复用到告警、通知和组合风险：告警触发关联 latest active 信号或创建最小 alert 信号，通知追加低敏信号摘要，持仓风险聚合 active sell/reduce/alert 信号并保持 fail-open。
- 新增合规 RSS/Atom 资讯源配置、拉取、去重、入库、查询、retention 与基础安全校验 API，作为个股/市场资讯情报池基线。
- 资讯源新增 `newsnow` 类型、`NEWSNOW_BASE_URL` 配置和 `/api/v1/intelligence/sources/defaults` 默认源初始化接口，内置财联社热门、雪球热门股票、华尔街见闻快讯、金十数据和格隆汇事件等财经热点源。
- 个股分析、Agent 分析和大盘复盘会 fail-open 读取本地资讯/情报池，并把来源链接作为新闻上下文和 evidence 输入。
- 新增日本/韩国 suffix-only 个股分析 MVP：手输 `.T` / `.KS` / `.KQ` 代码可走 YFinance 日线与近实时行情，补充市场识别、交易日历、Prompt 语义、Web/API 类型和能力边界文档。
- 新增 Token 用量监控看板与 `/api/v1/usage/dashboard` 接口，展示 LLM 调用总量、Prompt/Completion 拆分、模型用量、调用类型分布和最近调用明细。

### 改进

- 为 `DecisionSignal` 补齐默认生命周期、同源窄 relaxed 去重、相反 active 信号自动 invalidated、terminal 状态不可 PATCH 复活和低敏 market phase hints 提取。
- 补充 Web decision-signals typed API wrapper 与契约隔离测试，并将历史报告 AI 建议查询收口到精确报告懒提取。
- DSA 数据源链路新增 Tencent 日 K 直连 fetcher、daily source health 短期熔断，并升级 AlphaSift 默认 pin/runtime bridge。
- 默认启用 `DAILY_SOURCE=auto`、Sina snapshot 优先级、候选级 quote context 与 LLM ranking timeout/max tokens 边界。
- 新增 legacy LLM usage provider/cache telemetry、message HMAC 诊断字段和普通个股分析 legacy message stability audit，不改变公开 Usage API、prompt 或 provider 参数。
- 问股页移动端策略选择改为默认收起的按钮入口，展开后仍可多选策略并在发送后自动收起，减少对对话内容的遮挡。

### 修复

- 修复运行流 live SSE 脱敏、后期 LLM/通知卡片重复、数据源聚合卡片过早成功、Web 首页窄侧栏挤压股票信息，以及个股分析自动生成大盘上下文时运行诊断互相串扰的问题。
- 修复 AlphaSift 热点题材 EastMoney 瞬断且无缓存时的空态、桌面更新热点缓存保留，以及 `leader_stocks` / `stocks` 双字段兼容问题。
- 修复 Web AI 建议页筛选/状态更新分页、价格计划单边入场价展示、持仓 latest 信号刷新、详情 JSON 安全渲染和卡片交互语义问题。
- 仅允许历史报告存在明确 `action` 或可解析动作时才触发决策信号懒回填，避免 `decision_type=hold` 等统计口径在建议不明确场景误回填。
- 修复 #1390 P6 DecisionSignal 在组合风险快照语义和默认聚合通知展示中的遗漏。
- 默认禁用 `/api/v1/intelligence/sources/defaults` 新建源，避免公开示例 NewsNow 实例被默认启用，同时统一 500 响应细节仅入日志、响应返回通用错误信息。
- Web 股票自动补全、输入校验、历史/任务展示和筛选补齐日韩 Yahoo 后缀代码、常用日韩股票索引与股票池裸码解析，避免 `000660`、`005930`、`7203.T`、`005930.KS`、`035720.KQ` 等场景崩溃、误入 A 股语义或历史分裂展示。
- 日韩个股分析在本地历史上下文缺失时会用 YFinance 日线兜底构造 K 线与技术指标上下文，避免报告误称日股/韩股核心行情和技术数据不可用。
- 发布说明生成查询 PR 作者失败时保留降级并输出包含 PR 编号和异常类型的 warning，便于排查 token、权限、网络或 GitHub API 异常。

### 文档

- README、完整指南和市场支持文档补充日股/韩股示例（`7203.T`、`005930.KS`），并明确 `.T/.KS/.KQ` 当前为 YFinance-only MVP。
- 新增 DecisionSignal 决策信号专题文档，补齐字段/API/Web/告警通知/组合风险/后验评估、脱敏、迁移与回滚说明，并收口 Web i18n 显示边界。
- 补充 AlphaSift 迁移与回退边界：明确 `ALPHASIFT_INSTALL_SPEC` 显式覆盖语义、`requirements.txt + DEFAULT_ALPHASIFT_INSTALL_SPEC` 与运行时兼容边界。
- 补充资讯源基线文档，说明 `NEWS_INTEL_*` 配置、NewsNow 自建建议、模型/provider/base URL 不变更边界，以及禁用或移除情报源变量的回退路径。

### 测试

- 新增/更新 DecisionSignal 服务、提取、反馈/后验、摘要、文档、通知、告警、持仓风险、Web 展示和 label 的回归覆盖。
- 新增/更新 RSS/Atom / NewsNow 情报源服务、API、安全校验、分析接入和配置兼容测试。
- 新增/更新日韩市场识别、股票索引、YFinance 行情兜底、Web 自动补全和输入校验测试。
- 新增/更新 LLM usage、运行流、AlphaSift、发布说明生成和移动端交互相关回归。


## [3.22.0] - 2026-06-13

### 发布亮点

- feat: 新增 DecisionSignal 独立存储与 API、运行流快照 API 和 Web 运行流视图，补齐建议动作结构化字段与历史/回测展示链路。
- feat: AlphaSift 热点题材链路升级为新版合约，支持热点榜单、题材详情、发酵路线、概念股详情、缓存与兜底数据源。
- feat: 个股分析默认注入当日大盘环境摘要，并在高风险/退潮环境下软化激进买入建议。
- fix: 修复问股历史追问标的上下文、自选股等价代码匹配、低质量新闻过滤、运行流脱敏与 AlphaSift 热点详情展示等稳定性问题。

### 新功能

- 新增独立 `DecisionSignal` 存储、Repository、Service 与 `/api/v1/decision-signals` API，支持来源/市场/股票/动作/期限/阶段去重、查询、续期、状态更新、懒过期、持仓过滤和敏感信息脱敏。
- 新增分析任务与历史报告运行流快照 API，提供 lanes、nodes、edges、events、summary 等统一契约，并从任务队列、运行诊断和 AnalysisContextPack overview 构建脱敏数据流/信息流。
- Web 端为活跃任务、历史报告和大盘复盘报告补充运行流视图入口，支持查看运行摘要、拓扑节点、事件流和基础排障详情。
- 新增 AlphaSift 热点题材链路：后端提供 `/api/v1/alphasift/hotspots` 与 `/api/v1/alphasift/hotspots/{topic}` API，Web 选股页新增热点题材区域并支持发酵路线与概念股查看。

### 改进

- 个股分析新增按当日/市场复用的大盘环境摘要，普通 Pipeline 与 Agent 分析 Prompt 可读取低敏大盘背景；新增默认开启的 `DAILY_MARKET_CONTEXT_ENABLED` 配置，用户仍可显式关闭。
- 个股分析与历史/回测展示新增可选八态 `action` / `action_label` 建议动作字段，保留 `operation_advice` 自由文本和 `decision_type=buy|hold|sell` 统计口径。
- 补充 Web decision-signals typed API wrapper 与契约隔离测试，暂不接入 UI。
- 完善运行时日志上下文，补充 logger name、触发来源、市场统计与实时行情预取链路状态，便于排查调度、API、Bot 和数据源降级路径。
- 持仓管理页新增持仓账户删除入口，复用现有账户软删除接口，误建账户会从默认列表、快照、风险、录入入口和事件列表隐藏且不物理清理历史流水。
- AlphaSift 依赖锁定更新到 `d038c52c468543726fc1fd830b53c27d3f09d6da`，并为新版 last-good snapshot、日线历史、行业/概念 provider cache、hotspot 榜单、题材发酵路线、概念股详情、上次成功热点缓存与 post-analysis 元信息补齐 DSA 运行期和 Web 适配。
- AlphaSift 热点题材读取默认优先使用上次成功缓存，手动刷新才实时拉取并覆盖缓存，实时拉取失败时尽量回退旧缓存。
- AlphaSift 热点题材区域改为默认折叠，展开并选中具体题材后再读取详情；发酵路线改为带时间标记的时间线展示，概念股可点击进入首页并直接启动分析。
- AlphaSift 热点题材数据链路复用同一次东方财富板块异动快照，并从真实涨跌幅、异动次数和高频个股推导趋势分、持续分、阶段与龙头样本。
- AlphaSift 热点题材刷新在合约层返回少量或缺少关键字段时改用 DSA 东方财富板块异动直连榜单，忽略少于 3 条的本地热点缓存，并补齐板块兜底字段。
- AlphaSift 热点题材卡片改为更紧凑的多列布局，概念股列表改为独立“分析”按钮触发个股分析；详情优先合并东方财富成分股、同花顺解析和板块异动龙头兜底并按日聚合发酵时间线。
- AlphaSift 热点题材详情新增 DSA 侧 30 分钟磁盘缓存，重复点开同一题材时复用发酵时间线与概念股详情；题材事件仅展示 AlphaSift 合约时间线、同花顺摘要、已配置新闻搜索或东财板块异动等真实来源。
- AlphaSift 热点题材消息催化改为摘要展示：配置 LLM 时优先压缩为一句题材催化摘要，未配置或调用失败时回退本地短摘要。
- AlphaSift 热点题材列表新增可选 `include_details` 详情预取，Web 默认随热点列表批量带回 Top 题材发酵路线与概念股并复用前端内存缓存；新闻催化在 LLM 不可用时改为本地事件归纳。
- 改造 `main.py --webui-only` 启动行为：若 FastAPI 监听端口已被占用，启动即 fail-fast 抛出明确错误并退出。

### 修复

- 问股从历史报告进入后的追问会持续携带当前标的，切回或重载已有会话时可从历史消息恢复基础当前标的，并由后端阻断未明确切换时的错误股票工具调用、交易所片段和指标缩写误路由。
- 自选股加入和删除按等价股票代码匹配港股及大小写美股变体，避免 `00700`、`HK00700`、`00700.HK` 或 `aapl`、`AAPL` 被误判为不同标的。
- 收紧建议动作 legacy fallback：否定/回避表达、中文金融上下文、`buy or sell`、多 guard 歧义文本以及英文复合词不再误渲染成 action badge；有结构化 `action` 时回测/历史趋势等入口按界面语言显示 action 标签。
- 股票新闻与多维情报搜索在相关度排序后新增域名无关的准入过滤，剔除下载/安装包/应用评分页及成人/招嫖服务垃圾页，并在同批已有有效标的/行业候选时移除 `score=0` 背景填充项。
- 修复历史报告运行流快照在混合时区事件时间戳下返回 500 的问题。
- 修复运行流 live SSE 事件未复用快照层递归脱敏规则的问题，避免本地路径、prompt/raw response、代理头等敏感诊断字段在 refetch 前短暂暴露。
- AlphaSift 热点题材默认加载在无缓存且旧适配层缺少 `alphasift.hotspot` 模块时返回空态，不再一打开选股页就显示 AlphaSift 未就绪；手动刷新仍会提示依赖需更新。
- 为 THS 发酵路线补充列名兜底：当 `stock_board_concept_summary_ths` 返回缺列时仅跳过该来源富化，不影响热点题材详情 API 返回。
- 桌面发布打包改用冻结可执行文件运行时探针校验 `alphasift.dsa_adapter`，避免 macOS PyInstaller 将模块内嵌进可执行文件时被文件系统/zip 扫描误判为缺失。
- AlphaSift 热点题材详情展示改为优先使用后端融合后的 `route`，避免旧 `timeline` 覆盖新闻/LLM 摘要；手动刷新热点榜单时会同步绕过同题材详情缓存。

### 文档

- README 与繁中 README 快速开始入口补充视频教程链接，并将桌面客户端入口文案调整为客户端配置教程。
- 补充 `docs/alphasift-integration.md`：明确 AlphaSift 锁定 commit 来源、Hotspot 契约边界、LLM/LiteLLM 兼容语义与关闭开关下回退路径。
- 补充 #1381 运行时范围、兼容边界、官方语义依据与常规发布回滚说明。

### 测试

- 覆盖 #1381 后端 runtime 与兼容核验：`tests/test_main_schedule_mode.py`、`tests/test_pipeline_daily_market_context.py`、`tests/test_daily_market_context.py`、`tests/test_daily_market_context_guardrail.py`、`tests/test_agent_executor.py`、`tests/test_config_env_compat.py`、`tests/test_config_registry.py` 与 `apps/dsa-web/tests/system_config_i18n.test.ts`。
- 新增/更新 AlphaSift 后端回归：`python -m pytest tests/test_alphasift_api.py -q`、`python -m pytest tests/test_docker_entrypoint.py -q`、`python -m pytest tests/test_main_schedule_mode.py -q -k "start_api_server_fails_before_thread_when_port_is_busy"`。

## [3.21.0] - 2026-06-07

### 发布亮点

- feat: 新增 Web UI 中英文界面语言切换和飞书 App Bot 通知模式，提升多人部署和企业通知场景体验。
- feat: 大盘复盘报告、历史入口和个股栏继续收口到结构化数据与统一 Markdown/GFM 渲染，Web/API 人工触发入口不再被交易日 gate 短路。
- feat: AlphaSift 选股链路改为可恢复后台任务，并完善 DSA LLM runtime bridge、默认适配层预置和兼容回归。
- fix: 修复英文界面残留中文、诊断展示、运行时环境变量展示、健康检查、桌面更新路径、工作流变量读取和多处 Web 窄布局问题。

### 新功能

- WebUI 新增独立界面语言状态与中英文切换入口，覆盖主导航、首页、登录、设置页和通用控件文案；UI 语言与 `report_language` 解耦，不改写报告语言链路。
- 飞书通知新增应用机器人（App Bot）模式，支持通过 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_CHAT_ID` 配置，无需额外创建自定义机器人。
- Web 大盘复盘报告新增专用展示视图，历史入口和首页即时结果统一使用 Markdown/GFM 渲染并隐藏个股专属模块。
- 大盘复盘新增结构化 `market_review_payload`，Web、历史详情和推送统一基于结构化数据渲染，并保留 Markdown 兼容展示。
- 新增默认关闭的 AlphaSift 选股页签，通过 `ALPHASIFT_ENABLED` 明确控制，并保留 `/install` 作为显式修复路径。

### 改进

- Web/API 大盘复盘人工触发入口不再因交易日检查或相关市场休市而短路跳过；定时任务、GitHub Actions 手动运行和 CLI 默认入口仍保持原交易日 gate。
- AlphaSift Web 选股改为后台任务提交与状态轮询，新增可恢复任务状态展示，避免外部快照、行情或 LLM 变慢时浏览器长请求超时。
- AlphaSift 选股 API 与服务层收敛到 `AlphaSiftService`，endpoint 仅做路由参数接收与错误映射。
- AlphaSift 与 DSA 的运行时 LLM 兼容桥接改为调用期注入，保留 `provider/model/base_url/custom headers/fallback` 语义链路，不做持久化迁移。
- Web 首页侧栏不再单独展示大盘复盘历史集合，最新大盘复盘作为 `MARKET` 并入个股栏，按最近分析时间参与排序，并复用个股栏的选择、删除、完整报告与历史趋势查看能力。
- 多股通知报告将市场阶段收敛为总览下方单行 `市场状态`，不再在每只股票摘要下重复展示数据质量和限制详情。
- API 错误响应构造收敛到共享 helper，保持既有错误 envelope 形状并降低 endpoint 重复代码。
- WebUI 绑定公网地址或 CORS 全开放且未启用管理员认证时新增运行时 warning；仅增加可观测性，不阻断启动、不改写配置。
- 数据库初始化新增 `schema_migrations` baseline 标记表与幂等记录，用于后续 schema 演进追踪；不迁移、不清理、不改写既有业务表数据。
- #1386 P6 复用市场阶段与 AnalysisContextPack 公开摘要联动告警、持仓手动分析、历史、回测和通知展示，不新增数据库迁移。

### 修复

- Web 英文界面补齐回测、组合风险与告警规则相关文案本地化，避免英文模式下残留中文筛选器、按钮和枚举标签。
- 综合情报搜索中的机构分析与业绩预期维度改用 180 天 provider 请求窗口，避免默认短新闻窗口漏掉财报、研报等周期性财经材料。
- Web 个股栏和历史卡片在窄布局下不再让市场阶段标签遮挡股票名称。
- 问股自由文本追问不再将 TTM、PE、YOY 等金融缩写误识别为新股票代码。
- [修复] GitHub Actions 每日分析工作流读取 SearXNG 自建实例地址时支持 Variables 优先、Secrets 回退，修复仅配置 Variables 时 URL 不生效的问题。
- Web/桌面端左侧导航选中态改用 border 实现，避免蓝色竖条指示器溢出侧栏边界；侧栏展开宽度 116px -> 136px，新增 rail 紧凑模式。
- Windows 桌面端自动更新安装目录不再预先加引号，避免带空格路径在自动安装时触发“缺少快捷方式 / 找不到 Daily Stock Analysis.exe”的系统弹窗。
- Agent 分析路径生成 AnalysisContextPack overview 前复用已落库日线分析上下文，避免日线已抓取成功仍显示 `daily_bars_missing`。
- 修正大盘复盘结构化 `breadth` 的可用性判断：当市场不支持或抓取失败时不下发 `breadth`，前端展示“暂无数据”，避免误导性 0 值。
- 大盘复盘语言行为遵循全局 `report_language`，并在美股中文场景下本地化市场标签与策略蓝图，避免混入英文策略段落。
- Docker Web 设置页读取配置时在活跃 `.env` 文件缺项时回退展示启动注入的同名环境变量，并补清相关挂载边界文档。
- 报告页运行诊断会区分数据源抓取成功与进入 LLM 分析输入，相关新闻区标注为报告页补充/后续检索资讯，避免与输入数据块状态互相误读。
- `/health` 根路径健康检查现在始终返回 JSON，避免静态 Web fallback 吞掉健康探针；`/api/health` 与 `/api/v1/health` 继续保持兼容。
- `ALPHASIFT_ENABLED` 关闭时不触发 `alphasift` 运行时注入；开启后优先复用已配置的 DSA/provider 配置并注入 `LITELLM_*` 与 `LLM_*` 运行时变量。
- 补齐 openai-compatible 场景下 base URL、`extra_headers` 与 `LITELLM_FALLBACK_MODELS` 的兼容路径与回退链验证。
- 桌面/镜像打包链路保持与运行时一致的 AlphaSift 适配层预置，避免 `pip install` 作为线上修复依赖。

### 文档

- 明确 Issue #777 UI 语言切换采用仓内 `UiLanguageContext` + `uiText` 实现，持久化 key 为 `dsa.uiLanguage`，并补充对应可视化验收指引。
- 明确大盘复盘展示链路、结构化 payload、语言行为、交易日 gate 差异和回滚边界。
- 补充 LLM / LiteLLM 兼容键在 Settings 展示与校验上下文中的回退边界，说明不改写、不迁移、不清理用户现有 provider/model/base URL 持久化配置。
- 补齐 #1602 运行诊断口径修复覆盖范围，说明仅统一输入与展示口径，回滚方式为常规发布回滚。
- 明确 AnalysisContextPack P6 文档、迁移与回滚边界，并同步既有 `SAVE_CONTEXT_SNAPSHOT` 到 `.env.example`、配置注册表、Web 设置帮助和完整指南。
- 补齐 #1386 P7 盘前/盘中/盘后分析的入口、迁移、回滚和用户可见说明。
- 为 AlphaSift runtime bridge 增加官方兼容依据落点，明确 provider/model/base_url/extra_headers/fallback 与回退边界。

### 测试

- Web 方向执行 `npm run lint`、`npm run build`、相关 Vitest 和 smoke 命令；未设置 `DSA_WEB_SMOKE_PASSWORD` 时 smoke 用例按设计 skip。
- Web 测试运行时声明 Node `>=20.19.0 <27` 与 npm `>=10`，并补 localStorage 测试兜底以稳定 Vitest。
- 增补 AlphaSift runtime bridge 与打包脚本静态验证，覆盖 `LLM_CHANNELS`、`LITELLM_FALLBACK_MODELS`、`alphasift.dsa_adapter`、`--collect-all alphasift`。

### chore

- 移除随 issue / PR 验收流程误入库的截图资产，并明确一次性截图证据应保留在 PR 描述、评论、附件或 artifact 中，不作为仓库文件合入。

## [3.20.0] - 2026-06-03

### 发布亮点

- feat: 新增 AlphaSift 选股入口、自动安装与稳定适配层，支持 Web 策略执行、LLM 重排展示和默认关闭的可控启用。
- feat: 完善个股历史、自选队列、市场阶段与 AnalysisContextPack 可见性，增强 Web 报告和 API 的结构化上下文能力。
- feat: MiniMax 默认模型升级到 `MiniMax-M3`，并补齐相关价格、预设和测试覆盖。
- fix: 修复健康检查、Windows 桌面更新与首次运行编码、ETF 日线 secid、LLM base_url 校验和 Agent 日线上下文误判等稳定性问题。

### 新功能

- 新增默认关闭的 AlphaSift 选股页签，通过 `ALPHASIFT_ENABLED` 开启后经由稳定适配层读取策略并执行选股。
- Web 首页左侧栏改为个股栏，按股票去重展示，大盘复盘置顶，点击个股加载最新报告，支持按代码变体（.SZ/.SH/.SS）归一化去重合并。保留全选、批量删除和删除确认入口；新增按股票代码批量删除 API `DELETE /api/v1/history/by-code/{stock_code}`。
- 报告详情右侧栏新增自选操作入口，支持查看当前股票是否在自选队列、一键加入或移除；大盘复盘报告不显示该操作。
- 问股页面输入区上方新增自选操作按钮，用户发送包含股票代码的消息后自动显示加入自选/从自选删除入口。
- Web 报告页新增同股历史趋势抽屉入口，历史列表摘要补充趋势、摘要、模型和分析时行情字段，支持按当前股票查看历史分析并加载更多。
- AnalysisContextPack P4 低敏 overview 接入历史详情、同步分析响应、completed 任务状态和 Web 报告页，展示数据块状态、来源、缺失原因与降级摘要。
- #1386 P5 为个股分析报告新增 `dashboard.phase_decision` 盘中决策护栏，并在保存历史前按市场阶段与数据质量限制高置信盘中买卖结论。
- #1386 P4a 新增 `analysis_phase=auto|premarket|intraday|postmarket` API 参数，并在异步任务 accepted、内存 status、list、SSE 与分析 pipeline 中透传请求阶段。
- #1386 P4b Web 报告页新增最终市场阶段标签，任务面板展示请求阶段，并复用 AnalysisContextPack 低敏数据质量摘要。
- MiniMax 渠道模型列表升级：新增 `MiniMax-M3` 并作为默认，按官方 OpenAI-compatible 文档支持 1M 输入上下文（项目保守注册为 `<=512K` 价格档：context_window 512K、`max_tokens` 128K，对应 $0.6/M 输入、$2.4/M 输出，>512K 输入价格档未建模），保留 `MiniMax-M2.7` 与 `MiniMax-M2.7-highspeed`，并保留 `MiniMax-M2.5` legacy 价格条目以兼容现有用户配置的成本估算。Web 设置页 MiniMax 预设模型与价格按 M3 刷新。
- 新增 AnalysisContextPack P1 内部契约与脱敏序列化测试。
- 市场阶段低敏摘要接入历史详情、同步分析响应和 completed 任务状态的 report metadata。

### 改进

- 首次运行配置校验补充缺失 AI Key、空 STOCK_LIST、Telegram/邮件成对字段和 Webhook URL 前缀诊断。
- AlphaSift 选股入口在 Web 侧边栏中移动到“问股”下方，贴近 Agent/研究辅助工作流。
- Docker 镜像构建阶段预置默认 AlphaSift 适配层，与桌面发布包一样避免运行期额外安装。
- AlphaSift 选股改为依赖 `alphasift.dsa_adapter` 的稳定接口，Web 策略列表由 AlphaSift 动态提供，不再在前端硬编码。
- AlphaSift 选股页补充 Run ID、快照数、过滤后数量、因子和风险详情，展开候选时展示真实明细，并暂时仅开放当前支持的 A 股市场。
- Web 设置页新增 AlphaSift 选股开关卡片，可直接开启或关闭选股页签。
- 开启 AlphaSift 选股时先切换 `ALPHASIFT_ENABLED` 并检查适配层可用性，缺失时自动调用受控安装接口，不再要求用户额外点击安装。
- AlphaSift 已开启但适配层缺失时，策略列表和选股接口会串行化自动安装锁定来源，并强制重装以覆盖旧版 `alphasift` 包。
- AlphaSift 选股页合并重复的快照源 fallback 提示，并保留 AlphaSift 自身的 Tushare 优先快照源逻辑。
- AlphaSift 选股页在 LLM 重排降级时展示 warning/source error/parse error，并避免把本地因子评分误显示为 LLM 判断。
- Web 设置页不再把 `ALPHASIFT_ENABLED` 作为普通数据源配置项重复展示，该值仅作为“开启选股”按钮背后的持久化状态。
- AlphaSift 关闭时隐藏 Web 左侧“选股”导航入口，避免误导未开启用户。
- 补充 AlphaSift 选股自定义策略显示逻辑，避免未匹配预设项时误显示“均衡多因子”。
- 新增 GET /api/v1/history/stocks 端点按 code 分组返回不重复个股列表；新增 GET /api/v1/stocks/watchlist、POST /api/v1/stocks/watchlist/add、POST /api/v1/stocks/watchlist/remove 端点支持自选队列增删查。STOCK_LIST 读写保持原样，不做自动归一化；add/remove 时归一化比较判断等价代码变体。
- 新增 useWatchlist hook 统一管理自选队列前端状态，复用 SystemConfigService 的 STOCK_LIST 配置项实现持久化。
- AnalysisContextPack P5 增加数据质量评分、`fetch_failed` 状态、Prompt 数据限制区块和 Web 低敏质量展示。
- #1386 P2-full 在 AnalysisContextPack Prompt 数据限制中追加市场阶段与降级数据的交叉约束，并修正中文分析 Prompt 的阶段化行情标签。
- 通知报告默认发送路径恢复既有渠道兼容转换与分片逻辑，新增 renderer 能力仅保留为未来扩展基础。
- 关联板块缺少类型数据时改为单行展示板块名称，避免生成整列 `N/A` 的板块表格。
- 优化 Web 报告详情页信息层级，将输入数据块和运行诊断下移为主体内容后的折叠辅助信息。
- 盘中分析补齐实时行情获取时间、provider 时间、stale、fallback 与 partial/estimated 标记，供 AnalysisContextPack 映射输入数据限制。

### 修复

- Agent 分析路径生成 AnalysisContextPack overview 前复用已落库日线分析上下文，避免日线已抓取成功仍显示 `daily_bars_missing`。
- 注册 /api/v1/health 路由并加入认证豁免，修复该路径返回 404 以及开启 ADMIN_AUTH_ENABLED 后健康探针收到 401 的问题。
- Windows 本地首次运行环境检查兼容非 UTF-8 控制台输出，并将 `requirements.txt` 注释改为 ASCII 以降低默认代码页下的依赖安装失败概率。
- AlphaSift DSA 适配层默认开启 LLM 重排，后端显式请求 `use_llm=True`，选股页展示 LLM 分数、判断、覆盖率和关注项。
- AlphaSift 嵌入 DSA 时复用 DSA 已解析的 LLM 模型、渠道和密钥配置，避免 Web 已配置 LLM 但选股 LLM 重排仍因缺少 provider key 降级。
- AlphaSift 选股复用 DSA LLM 路由时过滤未声明的托管 provider 备选模型，并把已声明渠道模型补入回退链，避免残留 Gemini fallback 覆盖可用的 DSA 渠道。
- AlphaSift 默认安装来源改为锁定 commit 的受信任 GitHub 地址；桌面模式自动安装不要求管理员会话，非桌面部署要求管理员认证会话，并继续限制安装来源。
- 修复 Web 开启 AlphaSift 时先安装后写配置导致默认关闭状态无法开启的问题。
- AlphaSift 状态与安装接口不再返回 `install_spec` 明文，仅返回 `install_spec_is_default` 等非敏感状态字段。
- AlphaSift 状态探测区分可选依赖缺失与非预期异常，异常场景记录 warning 并返回非敏感诊断信息。
- 调整 AlphaSift 筛选调用兼容：`screen` 以 `max_results` 为主并支持历史 `max_output` 关键词，同时允许策略透传以对齐前端手动策略参数。
- AlphaSift Web 选股请求使用独立长超时，避免开启 LLM 重排后被通用 30 秒 API 超时提前中断。
- 桌面端打包阶段预置 AlphaSift 并收集适配层，避免发布包运行时再要求管理员自动安装。
- AlphaSift 自动安装仅在 `status` 诊断为 `missing_module` 时触发（仅模块缺失场景）；适配层可导入但运行时异常不再自动 `pip install`，而是返回 `424` 并保留诊断，避免把真实运行时故障掩盖为重装。
- 收口 Web 中文界面残留英文文案与设置页 help 缺口，回测页改为中文展示，并让 Web 设置页仅展示已注册且带说明的配置项。
- Windows 桌面端自动更新静默安装时显式复用当前安装目录，避免自定义安装目录场景下卸载旧版本文件失败。
- Windows 安装器重试旧卸载器时对 `_?=` 安装目录参数加引号，修复旧版本安装在带空格路径时返回 2 导致自动更新失败。
- Windows 桌面端自动更新传给 NSIS 的 `/D=` 目录参数在包含空格时自动加引号，避免安装位置注册表被截断。
- 加固 LLM channel base_url 校验，避免解析差异导致 SSRF 绕过。
- 修正 efinance ETF 日线 Eastmoney secid 路由，避免沪市 ETF 被按深市 quote id 查询导致日线为空。

### 文档

- 明确 AlphaSift 与 LiteLLM 兼容边界：仅桥接 DSA 已声明 provider/model/base URL 为调用期注入，不对 `.env` 做 provider/model 路由迁移；回退方式为关闭 AlphaSift 并恢复原有 `LITELLM_*`/`LLM_*` 配置。
- 明确 AlphaSift 仅复用 DSA 现有 LLM/LiteLLM 配置语义，不新增 `LITELLM_MODEL`、`OPENAI_MODEL`、`OPENAI_BASE_URL`、`LLM_TIMEOUT_SEC` 等模型语义迁移；失败提示与回退路径统一沿用既有系统配置链路，仅影响 AlphaSift 选股能力本身。
- 明确 AlphaSift 自动安装来源锁定、`missing_module` 与运行时异常行为边界，以及 LLM/provider/base URL 与自定义通道回退路径，便于问题溯源与回滚到原有 LLM 配置。
- 明确同股历史趋势新增模型字段为历史快照展示元数据，不影响运行时 LLM Provider/Model/Base URL 路由与配置迁移清理；回退方式为按常规发布回滚本变更。
- 明确 #1311 的兼容性边界：渲染层仅消费分析结果 `model_used` 展示字段，未改动 `wechat/slack/feishu/telegram` sender 发送链路，不触发 provider/model/base_url 兼容迁移。
- 明确 AlphaSift 锁定 commit 的 `alphasift.dsa_adapter` 契约依据，以及当前 DSA API/Web 调用结构的兼容边界。
- 明确 Settings 页面对 LLM 配置仅做展示分组与字段归并，不改写或触发 LLM 迁移/回退路径；兼容现有 `LLM` 配置保存与回退语义。
- 新增 AnalysisContextPack P0 上下文盘点。
- 补齐告警中心 P8 文档与配置收口说明，明确 legacy JSON、高级规则、Web/API、Docker、GitHub Actions 与 Desktop 边界。

### 测试

- 同步更新 `llmProviderTemplates`、LiteLLM fallback pricing 与 MiniMax 预设相关单测，断言新默认模型。
- 补充 ETF 日线数据源路由、输入变体、fallback 与 MA 字段回归覆盖。

### chore

- 新增通知报告渠道能力画像、PreparedMessage 与结构感知 Markdown 分片基础设施，为 #1311 全渠道渲染适配打底。
- 预置企业微信、飞书、Telegram、钉钉、Slack 平台 renderer 元数据，暂不改变默认推送报告入口和可见版式。

## [3.19.0] - 2026-05-29

### 新功能

- 落地 #1391 Phase 1 运行诊断最小链路：任务/SSE 追加 trace_id，并记录日线与实时行情 ProviderRun 快照。
- 告警中心新增 P7 大盘红绿灯结构化规则，支持 `market_light_status` 与 `market_light_score_drop` 并复用现有 worker、触发历史、通知和冷却链路。
- 落地 #1391 Phase 2 运行诊断摘要：生成用户可读 RunDiagnosticSummary，提供历史报告诊断 API 与脱敏复制文本。
- 落地 #1391 Phase 3 运行诊断可见性：报告详情和任务面板默认折叠展示运行状态、trace 与可复制排障信息；后端通过 `api/v1/history/{record_id}/diagnostics` 与 `context_snapshot.diagnostics` 提供历史链路回填。
- 新增 AnalysisContextPack P1 内部契约与脱敏序列化测试。
- 新增 AnalysisContextPack P2 builder，从普通分析 pipeline 已有 artifacts 组装内部上下文包。
- 问股新增默认关闭的可见对话上下文压缩，支持 Web 开关、Agent 高级 preset、滚动摘要和最近轮次原文保护，降低长会话 token 消耗。
- 股票自动补全索引默认支持从 GitHub main 远程刷新并缓存到本地，Web/CLI 分析入口失败时自动降级到内置索引，降低摘帽和更名后旧简称污染分析的概率。
- 普通分析与 Agent 运行时 Prompt 接入 AnalysisContextPack 低敏摘要，保持 history/API/Web 输出兼容。

### 改进

- `scripts/fetch_tushare_stock_list.py` 可对 A 股中带 `XD`/`XR`/`DR`/`N`/`C` 前缀的名称进行回填修正，供自动补全刷新流程默认使用。
- Web 路由页面改为按需加载，降低首包体积并增加路由加载失败恢复提示。
- Web 完整报告 Markdown 抽屉改为按需加载。
- 新增市场阶段推断基线并明确盘前、盘中、午休、临近收盘、盘后和非交易日语义。
- 新增运行态市场阶段上下文构造与降级测试。
- 设置页配置帮助阶段性补齐 Web 设置页实际展示/可配置字段的中英双语文案，覆盖 Agent、回测、报告、通知路由、系统运行时、AI legacy、数据源和通知高级配置。
- P2-min：LLM Prompt 注入市场阶段上下文。

### 修复

- 股票自动补全索引生成缺少 `pypinyin` 时改为直接失败，避免写出缺失拼音字段的降级索引。
- 归一腾讯实时行情成交量为股口径，避免量能变化倍数被放大并误导分析报告。
- Docker 默认部署移除 `.env` 单文件挂载，避免 WebUI 保存配置时因 `os.replace` 更新挂载点触发 `Device or resource busy`。
- 收敛 #1391 Phase 0 A 股代码归属边界：补齐 `SH`/`SZ` 前缀场景的归属一致性，明确 `data_provider/baostock_fetcher.py`、`data_provider/pytdx_fetcher.py`、`data_provider/tushare_fetcher.py` 的本轮修复范围。
- 修复 `STOCK_LIST` 使用裸 A 股代码时 Baostock 等数据源 fallback 的内部格式转换，保持用户配置继续使用 6 位股票编号。
- Windows 桌面端自动更新在用户确认重启安装后改为静默执行安装器，并在停止内置后端后清理进程引用，降低安装器提示“每日股票分析无法关闭”的概率。
- macOS 桌面端将运行时配置迁移到用户数据目录，并在旧 `.app` 包内文件仍可访问时迁移 `.env`、数据库和日志，避免后续替换升级后重新配置。
- 恢复 Agent/历史兼容快照中的关联板块与板块联动字段提取，修复新版首页报告缺少“板块联动”的回归问题。
- 修正 Web 设置帮助中 legacy 告警 JSON 字段名与静默时段投递语义说明。
- 修复 Web 中文设置页在数据源、通知、系统与 Agent 区域的配置标题、说明和关键下拉选项漏翻问题。
- 修复问股会话切换和首页任务重连后可能残留 Agent/分析任务进行中状态的问题。
- 问股 single-agent 新增 provider-aware trace 分轨，跨轮保留 DeepSeek V4 thinking + tool-call 的 `reasoning_content` 与工具协议材料。
- 为 Akshare 新浪/腾讯 A 股历史兜底接口增加调用级超时，并补齐 Tushare `605xxx` 沪市代码路由回归测试，避免定时分析因数据源无响应而挂起。
- 将 `exchange-calendars` 依赖下限提升到 `4.13.0`，避免 pandas 3 环境导入交易日历时因 Timedelta 单位 `T` 失效导致分析失败。
- 交互式命令（钉钉会话、飞书会话、Telegram）触发的分析结果只回到来源会话，不再同时广播到静态通知渠道。
- 适配 Longbridge OAuth 2.0 认证与 token 缓存恢复，避免新后台无 Legacy Access Token 时长桥数据源被误判为未配置。
- Longbridge OAuth 路径在当前 SDK 不支持 `OAuthBuilder` / `Config.from_oauth` 时明确日志降级，避免 Linux/Docker 仅可安装旧 SDK 时构建失败。
- 兼容 YFinance 日线返回未命名日期索引的场景，避免标准化后缺少 `date` 列导致美股日线 fallback 中断。

### 文档

- 新增 #1391 Phase 0 运行诊断契约文档，明确 trace_id、诊断摘要、关键链路范围与脱敏/fail-open/retention 边界。
- 补齐告警中心 P8 文档与配置收口说明，明确 legacy JSON、高级规则、Web/API、Docker、GitHub Actions 与 Desktop 边界。
- 说明本次桌面修复仅覆盖 Windows NSIS 更新安装链路与后端进程生命周期清理；未改动设置项保存/模型运行时清理语义。移除此前误入的 `docker/Dockerfile` `npm registry` 变更，恢复部署构建与更新修复的职责隔离。
- 新增 AnalysisContextPack P0 上下文盘点，明确字段质量状态、现有状态映射和首版 pack 边界。
- 明确 #1391 Phase 2 的结构化检测告警为非配置迁移信号：`agent_max_steps`/`agent_orchestrator_timeout_s` 非法值会 fallback 至默认并产生日志告警，新增诊断链路仅新增 `context_snapshot`/`RunDiagnosticSummary` 读写字段，不改写 `litellm_model`、`agent_litellm_model`、`openai_base_url`、LLM channel 路由或配置迁移语义。
- 补充 #1391 Phase 3 兼容性说明：记录后端诊断持久化、历史查询与通知回写链路变更边界与回滚策略，并补齐后端门禁级验证要求。

### 测试

- 收敛 #1391 Phase 3 后端/API 与 Web 回归检查：`./scripts/ci_gate.sh`、`test_pipeline_market_phase_context.py`、`test_analysis_api_contract.py`、`test_analysis_history.py`、`npm run lint`、`npm run build`。
- 执行 `python -c "import exchange_calendars as xcals; xcals.get_calendar('XSHG'); print('ok')"` 通过验证，以覆盖导入与交易日历初始化兼容性。

## [3.18.0] - 2026-05-21

### 发布亮点

- feat: 告警中心扩展到 P2-P6，补齐后台评估、真实通知结果、业务冷却、技术指标规则，以及自选股 / 持仓 / 账户联动规则。
- feat: 个股分析支持策略选择，新增热点题材、事件驱动、成长质量和预期重估策略，并为 HK/US 报告补充基本面、财务摘要、股东回报和关联板块。
- feat: 新增 Finnhub / AlphaVantage 美股数据源适配器，扩展美股日线 failover 链，提升美股行情获取韧性。
- fix: 修复桌面端发布打包、分析状态接口、AlphaVantage 涨跌幅、持仓实时估值、告警历史去重、数据库冷启动和 fallback pricing 注册等稳定性问题。

### What's Changed

- feat: Add alert-center P2-P6, Web strategy selection, HK/US fundamental context, static-report financial sections, and Finnhub / AlphaVantage US-market fallback.
- improve: Refine LiteLLM parameter recovery, yfinance currency/dividend handling, RSI calculation, market-review presentation, stock-news relevance ranking, and report table rendering.
- fix: Harden desktop packaging/update assets, completed analysis-status responses, AlphaVantage pct_chg routing, portfolio realtime snapshots, alert trigger dedupe, DatabaseManager cold start, and fallback pricing registration.
- docs/tests: Add beginner setup and settings-help docs, document compatibility/rollback boundaries, and extend regression coverage for API, alert, packaging, and release paths.

## [3.17.1] - 2026-05-16

### 发布亮点

- fix: 桌面端 Windows / macOS 打包脚本显式关闭 electron-builder 自动发布，避免 tag 构建时因缺少 `GH_TOKEN` 在本地打包完成后失败；Release workflow 继续负责上传和发布产物。

### What's Changed

- fix: Add `--publish never` to the Windows and macOS Electron packaging scripts so tag builds only create local artifacts and GitHub Actions handles release upload/publish.

## [3.17.0] - 2026-05-16

### 发布亮点

- feat: 新增 Alert API MVP，支持告警规则 CRUD、启停、一次性测试以及触发/通知结果查询，首版覆盖 `price_cross` / `price_change_percent` / `volume_spike` 并保持 legacy 配置兼容。
- feat: 通知网关新增 ntfy 与 Gotify 一等渠道，并补齐通知降噪、静态渠道隔离、诊断、Web 测试和 GitHub Actions env 对照校验。
- feat: Windows 桌面安装版接入自动更新安装链路，支持后台下载、确认重启安装、运行时文件备份/恢复和发布产物元数据校验。
- improve: 大盘复盘新增概念排行、人气股、涨停池等底层数据源，支持指数涨跌颜色语义配置，并将复盘结果写入历史记录。
- improve: Web 设置页支持 `.env` 配置备份导入/导出和通知/Agent 区域局部错误兜底；报告新增 `REPORT_SHOW_LLM_MODEL` 开关控制模型信息展示。
- improve: Docker 启动入口自动修复挂载目录权限并在日志目录不可写时降级到控制台，减少普通部署的手动修复步骤。
- fix: 数据源缺凭据或连接失败时更温和降级，Longbridge / Pytdx 加入冷却，资金流缺失时避免输出高置信买入结论。
- fix: 分析与报告链路兼容 OpenAI-compatible `content_blocks` 响应，归一策略价格字段，并修复大盘复盘滚动和历史记录丢失问题。
- docs: 补齐通知、告警中心、桌面打包、README / 指南和 PR title 治理说明，明确多处配置兼容边界与回滚路径。
- test: 增加 Alert API、通知降噪/路由、Docker entrypoint、数据源预取、桌面更新链路和分析历史等回归覆盖。

### What's Changed

- feat: Add an Alert API MVP with rule CRUD, enable/disable, one-shot testing, trigger history, notification results, and legacy config compatibility.
- feat: Promote ntfy and Gotify to first-class notification channels with Web tests, routing, Actions integration, diagnostics, and noise control.
- feat: Add the Windows desktop auto-update install flow with runtime state backup/restore and release artifact metadata verification.
- improve: Extend market review data sources, add configurable index color semantics, and persist market review results into analysis history.
- improve: Add Web `.env` backup import/export, local settings panel error boundaries, and a report model visibility toggle.
- improve: Harden Docker startup by repairing mounted directory permissions and falling back to console logging when mounted logs are not writable.
- fix: Cool down unavailable optional fetchers, reduce noisy Longbridge/Pytdx retries, and downgrade buy advice when capital flow data is missing.
- fix: Handle OpenAI-compatible `content_blocks`, normalize strategy price fields, and recover market review scrolling/history behavior.
- docs/tests: Update notification, alert, desktop packaging, README/guide, and governance docs; add focused regression coverage for the new release paths.

## [3.16.0] - 2026-05-10

### 发布亮点

- feat: Web 首页新增“大盘复盘”触发入口、任务轮询与完成后报告直出；首次启动配置状态可提示缺口并引导到系统设置。
- feat: 新增通知路由策略，支持按 report、alert、system_error 将通知收窄到指定渠道；Web 设置页支持通知渠道一键测试。
- feat: 系统设置页新增配置项帮助入口与多语言帮助文案基础设施，首批覆盖自选股、LLM 主模型、LLM 渠道、飞书 Webhook 与 WebUI 监听地址。
- improve: 大盘复盘 API、CLI、Bot 共用 `build_market_review_runtime` 装配路径，补齐 `litellm_model` / `llm_model_list` 与 legacy key 回退说明。
- improve: 个股报告操作建议结合支撑/压力、量能、筹码与主力资金流校准，减少买入/卖出剧烈切换，并补强 Agent 决策兜底。
- improve: Docker 镜像支持非 root 用户运行，LiteLLM 依赖约束放宽到后续安全 1.x 修复版本。
- fix: 修正 LLM 渠道测试中 `Model disabled`、provider blocked 等错误分类，避免被误报为网络异常。
- fix: 港股日线跳过不支持港股的内置历史数据源；北交所 `BJ` 前缀与 `.BJ` 后缀代码校验保持一致。
- fix: Web 大盘复盘按钮可观测性、Windows fallback 锁进程探测和催化线索展示更稳健。
- docs: 新增文档中心与配置帮助维护说明，清理 README、完整指南与配置指南中的临时 PR/文档同步说明。

### What's Changed

- feat: Add a Web home market-review trigger with task polling and inline report display; setup status now points users to missing configuration.
- feat: Add notification routing by report, alert, and system_error; add one-click notification channel testing in Web settings.
- feat: Add settings field help infrastructure with multilingual help text for the first batch of core configuration fields.
- improve: Share `build_market_review_runtime` across API, CLI, and Bot market review paths; document `litellm_model` / `llm_model_list` and legacy key fallback behavior.
- improve: Calibrate stock advice with support/resistance, volume, chips, and main-force capital flow; strengthen Agent decision fallback behavior.
- improve: Run Docker images as a non-root user and relax LiteLLM constraints to allow safe future 1.x fixes.
- fix: Classify `Model disabled`, provider blocked, and related LLM channel test errors more accurately instead of reporting them as generic network failures.
- fix: Avoid unsupported built-in historical providers for Hong Kong daily data; align Beijing Stock Exchange `BJ` prefix and `.BJ` suffix validation.
- fix: Improve Web market-review observability, Windows fallback lock probing, and market catalyst snippet rendering.
- docs: Add the documentation index and settings-help maintenance guide; remove temporary PR/doc-sync notes from README and user-facing guides.

## [3.15.0] - 2026-05-05

### 发布亮点

- LLM 渠道配置体验继续升级：新增 Anspire OpenAI-compatible 网关接入，并补齐常用服务商预设、官方来源、能力标签、配置注意事项和 GitHub Actions 显式映射。
- Web LLM 配置检测更可诊断：细分错误 reason，并支持用户显式触发 JSON、tools、vision、stream 运行时 smoke。
- LLM 运行时配置清理更稳健：只清理托管 provider 的失效运行时选择，并保留 `cohere/*`、`google/*`、`xai/*` 等直连 provider 兼容语义。
- 通知与 Bot 状态可观测性增强：自定义 Webhook 支持 JSON body 模板，Bot `/status` 展示更完整的 LLM、Agent 与通知渠道状态。
- 大盘复盘、实时告警、Agent weak 兜底和持仓估值继续补强，降低默认值覆盖、缺价污染和配置排障成本。

### 新功能

- 支持 `ANSPIRE_API_KEYS` 默认接入 Anspire OpenAI-compatible 大模型网关，并在 LLM 渠道编辑器补充 Anspire Open 预设。
- 自定义 Webhook 支持 `CUSTOM_WEBHOOK_BODY_TEMPLATE` JSON body 模板，便于适配 AstrBot、NapCat 和自建推送服务。
- 大盘复盘结构化区块新增大盘红绿灯结论，基于盘面温度输出 green/yellow/red、核心原因和操作建议。
- EventMonitor 支持 `price_change_percent` 涨跌幅阈值规则，可按上涨或下跌方向触发实时告警。
- Web LLM 渠道编辑器新增常用服务商配置模板与预设，覆盖 MiniMax、火山方舟、OpenAI、Claude、Gemini、Kimi、Qwen、GLM、豆包等入口。

### 改进

- Web LLM 配置检测补充细分错误分类，并新增显式触发的 JSON/tools/vision/stream 运行时 smoke；默认测试和保存流程不变，检测结果仅作为当前配置的一次 best-effort 诊断。
- Bot `/status` 展示统一 LLM 主模型、Agent 模型、渠道模式、YAML 配置和更多通知渠道状态。
- Web LLM 渠道编辑器展示 provider 能力标签、官方来源链接和配置注意事项提示；这些标签仅用于配置参考，不代表运行时能力已验证通过。
- 抽出 Web LLM provider preset 单一模板数据源，保持现有配置保存语义不变。
- 补齐 LLM provider channel 在 GitHub Actions 中的显式映射，并同步 `.env` 示例与配置文档。

### 修复

- Agent weak 完整性兜底在模型缺少评分、趋势、操作建议或 dashboard 关键块时优先保留本地趋势分析结果，并只补齐真正缺失的仪表盘字段，避免首页评分被默认 50 覆盖。
- 统一持仓快照输出现价、市值、浮盈亏、收益率与价格元信息，避免缺价或 stale 价格污染持仓估值。
- LLM 渠道测试补充结构化诊断与设置页排障提示，便于定位 provider、模型、Base URL 和鉴权配置问题。
- 明确 runtime 清理兼容边界：仅对托管 provider（`gemini`、`vertex_ai`、`anthropic`、`openai`、`deepseek`）触发保存前失效值清理，`cohere/*`、`google/*`、`xai/*` 直连值按 legacy 兼容路径保留，不做无提示迁移或覆写。
- 将 MiniMax 预设调整为官方 OpenAI-compatible Base URL 和当前模型示例，并补充 MiniMax、火山方舟、LiteLLM 兼容来源与回退说明。
- 移除截图识别对 Gemini 3 Vision 模型的过时降级逻辑，默认推断改用当前 Gemini 模型配置。

### 文档

- 完善 LLM provider 配置文档，补充配置方式选择、Actions 变量对照、运行时检测边界、错误 reason 排障和回滚路径（#1180）。
- 补充 LLM 渠道编辑器的官方来源、依赖兼容窗口、保存时的运行时模型清理规则，以及旧配置回退路径说明。
- 为 `cohere/*`、`google/*`、`xai/*` 直连语义补充官方 provider/model 说明、`litellm>=1.80.10,<1.82.7` 兼容依据引用，并明确示例模型名仅为配置保留行为说明而非可用性背书。
- 明确 `price_change_percent` 事件告警仅为配置与运行时规则扩展，未变更模型/provider/base URL/LiteLLM 兼容语义；回退路径为关闭/移除 Event Monitor 配置。
- 同步 README、DEPLOY、full-guide、Anspire、AIHubMix 与 SerpAPI 相关说明，统一外链、配置口径和评审一致性说明。

### 测试

- 补齐 AI 配置页与 `task_queue` 的 LLM 运行时清理/同步回归证据：恢复渠道模型时保留 fallback、编辑模型列表期间不静默清空运行时选择，渠道无可用模型时清理失效 runtime 引用，并覆盖 legacy key 与 `cohere/*`、`google/*`、`xai/*` 直连 provider 保留语义。
- 覆盖 Web LLM 配置检测的细分错误分类，以及 JSON、tools、vision、stream 运行时 smoke 的显式触发路径。

## [3.14.2] - 2026-04-30

### 发布亮点

- 大盘复盘扩展到港股，并让 Bot `/market` 与 CLI/调度入口使用一致的交易日过滤语义。
- 问股与 Agent 链路增强配置缺失、决策 fallback 和多策略选择体验。
- LLM 与分析报告链路提升稳定性：非法 JSON 响应会继续尝试备用模型，LiteLLM DEBUG 日志默认降噪。
- 新增只读首次启动配置状态接口，为后续配置向导和 smoke run 奠定基础。

### 新功能

- 大盘复盘支持港股市场：`MARKET_REVIEW_REGION` 新增 `hk` 选项；`both` 扩展为 A股+港股+美股，并新增港股指数（HSI/HSTECH/HSCEI）复盘链路。
- 新增只读首次启动配置状态接口 `GET /api/v1/system/config/setup/status`，用于识别 LLM、Agent、自选股、通知和本地存储配置缺口；该接口不会重载运行时、写入 `.env` 或创建数据库文件。

### 改进

- 问股页面支持组合选择多个 Agent 策略。

### 修复

- Bot `/market` 命令复用 `get_open_markets_today()` / `compute_effective_region()` 做交易日过滤：结果作为 `override_region` 透传给 `run_market_review`；若结果为空字符串则跳过复盘并推送“今日相关市场休市”，与 CLI/调度入口行为一致。
- 问股 Agent 在未配置可用 LLM 时保留后端真实错误原因并维持 `done.success=false` 失败语义，避免前端把配置缺失误当成成功回答。
- Agent 模式未生成有效决策仪表盘时保留本地趋势分析的评分、趋势和操作建议，并将强买/强卖 fallback 归一到兼容的 `buy`/`sell` 决策类型，避免首页结果被 `50 / 观望 / 未知` 缺省值覆盖。
- 持仓快照现价缺失时不再静默回退为持仓成本；当天快照优先使用历史收盘价，仅在缺失时使用实时价 fallback，缺价持仓不再污染市值与未实现盈亏汇总，并为持仓明细返回价格来源、日期、stale 与缺价状态。
- 分析 Prompt 在注入 `trend_analysis` 前按最终 `trend_status` / `ma_alignment` 清洗互斥理由：空头结构移除看多理由、多头结构移除空头结构风险，并在事件/技术冲突与异常放量（>10 倍）时强制提示“事件先行、技术待确认”与量能降权。
- LLM 返回非 JSON 响应时同样触发备用模型切换：主模型成功返回但无法解析 JSON 时，不再立即降级为纯文本 fallback，而是依次尝试 `LITELLM_FALLBACK_MODELS` 中的备用模型；所有模型均无法返回合法 JSON 时，再降级为文本 fallback。
- LiteLLM 内部 DEBUG 日志默认压低到 WARNING，避免流式生成时 token 级日志污染 `stock_analysis_debug_*.log`；如需排查 LiteLLM 内部细节，可临时设置 `LITELLM_LOG_LEVEL=DEBUG`（Fixes #1156）。

### 文档

- 补充 LLM 配置指南与 FAQ，明确问股 Agent 对 `LITELLM_CONFIG` / `LLM_CHANNELS` / legacy `GEMINI_*` `OPENAI_*` `ANTHROPIC_*` 的兼容优先级、回退路径与“不静默迁移旧配置”的结论。

### 测试

- 新增 `tests/test_bot_market_command.py`，覆盖 `MARKET_REVIEW_REGION=both` + open markets `{"cn","us"}` / `{"cn","hk"}` 的 `override_region` 透传断言，并覆盖全市场休市跳过与关闭交易日检查路径；新增 `tests/test_yfinance_hk_indices.py` 覆盖港股指数符号映射与部分/全部失败降级路径。
- 补齐 `task_queue` 轻量导入 stub 的股票代码规范化函数，恢复 `tests/test_task_queue_config_sync.py` 收集与运行。

## [3.14.1] - 2026-04-26
- [测试] 修正大盘复盘 prompt 测试对“明日交易计划”标题的断言，并同步桌面端版本号，恢复发布 gate。

## [3.14.0] - 2026-04-26

### 发布亮点

- 📊 **大盘复盘升级为盘后工作台式结构** — A 股复盘固定输出盘面温度、指数明细、板块 Top 表、新闻催化、明日交易计划和风险提示，减少纯文字复盘的重复与空泛。
- 🖥️ **桌面端新增 GitHub Release 更新提醒** — Windows/macOS 桌面端启动后自动检测新版本，也可从设置页手动检查并跳转下载页。
- 🤖 **Pipeline Agent 数据加载大幅降噪** — K 线工具改为 DB-first 并预热 240 天历史数据，避免同一只股票重复 HTTP 请求。
- 🐳 **Docker 发布链路整理** — 发布工作流收敛为正式发布与手动补发两条路径，官方 Docker Hub 镜像名统一为 `zhulinsen/daily_stock_analysis`。
- 🔧 **LLM 渠道与 DeepSeek V4 配置补强** — GitHub Actions 定时分析补齐多渠道变量透传，DeepSeek 官方渠道预设与示例同步到 V4。
- 🧩 **桌面端静态资源一致性校验** — 打包链路和运行时都能更早发现静态资源错配，降低 Release 包白屏排查成本。

### 新功能

- 🏠 **Web 首页历史报告区新增重新分析入口** — 支持基于原始 prompt 重做同一只股票同日期的分析。
- 🖥️ **Windows/macOS 桌面端新增 GitHub Release 更新提醒** — 启动后自动检测新版本，并支持从设置页手动检查后跳转下载页。

### 改进

- 📊 **A 股大盘复盘报告改为结构化盘后工作台版式** — 固定输出盘面温度、指数明细、板块 Top 表、新闻催化和明日交易计划。
- 🐳 **Docker 发布工作流收敛** — 更清晰地区分正式发布与手动补发链路，并统一官方 Docker Hub 镜像名为 `zhulinsen/daily_stock_analysis`。
- 🤖 **Agent 日线工具优先复用本地缓存** — 同时持久化新获取的日线与新闻情报，减少重复数据源调用。

### 修复

- 🤖 **Pipeline Agent K 线工具 DB-first 加载** — `get_daily_history` / `analyze_trend` / `calculate_ma` / `get_volume_analysis` / `analyze_pattern` 改为优先读取本地 DB，消除同一只股票 9x5=45 次重复 HTTP 请求（Fixes #1066）。
- 🤖 **Pipeline Agent 执行前按需预热 240 天 K 线历史到 DB** — 正常情况下 K 线工具调用无需重复网络请求。
- 🕒 **冻结 `target_date` 并通过 ContextVar 透传到 Pipeline Agent K 线工具线程** — 消除跨收盘边界时间漂移。
- 🪟 **Windows 桌面端后端日志转抄编码修复** — 转抄 stdout/stderr 时优先使用 UTF-8，并兼容本地代码页回退，避免中文日志乱码。
- ⚙️ **GitHub Actions 每日分析工作流补齐 LLM 渠道变量透传** — 支持 `LLM_CHANNELS`、多 Key 与常用 `LLM_<NAME>_*`，避免本地可用的多模型配置在云端定时任务中失效（Fixes #1063, #872）。
- 📈 **历史报告详情接口修正 `change_pct` 取值** — 使用 `is None` 判断避免把 0.0（平盘）当作缺失值丢弃，移除错误的 `change_60d` 兜底，并在缺失时回退到原始实时行情字段（Fixes #1084）。
- 🔧 **DeepSeek 官方渠道预设与示例配置同步到 V4** — 保留 legacy `deepseek-chat` 默认值并增加废弃提示，同时修正模型发现后旧运行时选择导致保存失败的问题（Fixes #1108, #1109）。
- 🧩 **桌面端打包链路新增静态资源一致性检查** — `scripts/check_static_assets.py` 会在源 `static/` 与 PyInstaller 产物中校验 `index.html` 引用的资源是否真实存在，运行时也会在错配时写入明确日志，避免重现 Release 包打开后白屏（Refs #1064 / #1065 / #1050）。
- 🧩 **后端 `/assets/*` 改为显式路由托管** — 资源缺失时返回与请求扩展名匹配的 `text/javascript` / `text/css` 404，减少默认 JSON 错误响应带来的排查误导（Refs #1064）。
- 🌙 **`kimi-k2.6` 自动使用固定温度** — 主分析、大盘复盘和 Agent 调用该模型时自动使用 `temperature=1.0`，避免模型拒绝默认温度请求（Fixes #1102）。

### 文档

- 🐳 **补充官方 Docker 镜像使用说明** — 增加镜像拉取、`docker run` 用法与 `.env` / 数据目录映射说明，不再只覆盖 Compose 部署路径。
- 📨 **修正飞书自定义机器人 Webhook 示例** — `feishu_sender.py` 中的示例改为 interactive card JSON，并补充飞书自动化 Webhook 触发器配置教程。
- 📚 **优化根 README 结构** — 保留首页级功能特性、技术栈、快速开始、推送效果、Web、Agent、赞助商和新闻源入口，将细配置、交易纪律和基本面语义收口到完整指南，并将 Docker 徽章指向官方镜像页。
- 🌐 **同步英文与繁中 README 的精简入口结构** — 同时补齐完整指南中的 LLM 用量 API 与持仓管理说明。
- 🤝 **调整 AI 协作与 PR 模板中的 README 维护规则** — 明确 README 非必要不更新，细节优先进入专题文档。

### 测试

- 🧪 **稳定市场复盘相关测试的 LiteLLM stub 行为** — 避免本机安装的 LiteLLM 在测试收集顺序变化时影响市场复盘单元测试。
- 🧪 **pytest 默认跳过前端依赖目录** — 本地存在 `apps/dsa-web/node_modules` 时不再被后端测试递归扫描，避免发布前 gate 被无关目录拖慢。

## [3.13.0] - 2026-04-21

### 发布亮点

- 🌉 **长桥 OpenAPI 数据源接入** — 美股/港股行情优先使用 Longbridge，YFinance / AkShare 自动兜底；未配置时行为不变。
- 📈 **Tushare 港股全链路扩展** — 港股日线通过 `hk_daily` 获取；筹码分布对港股返回 `None`；换算单位跟随港股口径，不再套用 A 股手/千元规则。
- 🔍 **Anspire Search 语义搜索接入** — 配置 `ANSPIRE_*` 后即可使用 Anspire Search 获取实时行情及资讯，未配置时完全透明。
- 🚀 **普通分析链路支持 LLM 流式生成** — 首页任务 SSE 新增 `task_progress` 事件，进度更细化；不支持流式的 provider 自动回退到非流式调用。
- 🤖 **Web 渠道编辑器支持按需拉取可用模型列表** — `/v1/models` 统一模型发现入口，多选写回 `LLM_{CHANNEL}_MODELS`，拉取失败时保留手动输入降级。
- 🛡️ **Agent 稳定性与预算护栏全面补强** — `AGENT_MAX_STEPS` 语义统一、技能降级不中断管线、SSE 异常透传、技能加载 warning 日志补齐。
- 🛠️ **SQLite 写入链路原子化** — 批量原子 upsert + WAL + `busy_timeout` + 有限写入重试，显著降低批量分析并发锁竞争。

### 新功能

- 🌉 **集成 Longbridge OpenAPI 作为美股/港股可选数据源**（fixes #981）— 配置 `LONGBRIDGE_*` 后优先使用长桥获取日线与实时行情，YFinance / AkShare 兜底；未配置时行为与此前一致。联调使用 `tests/longbridge_live_smoke.py`（手动脚本，不参与 pytest 收集）。
- 📈 **Tushare 支持港股日线查询** — 配置 Tushare 凭证后调用 `hk_daily` 接口获取港股数据；权限不足时抛出异常，与原流程一致。
- 🔍 **集成 Anspire Search 可选语义搜索后端** — 配置 `ANSPIRE_*` 可使用 Anspire Search 获取实时行情及新闻资讯；未配置时行为与此前一致。联调使用 `tests/test_anspire_search.py`（手动脚本）。
- 🚀 **普通分析链路支持 LiteLLM 流式生成与更细任务进度** — 股票分析在 LLM 阶段优先尝试 `stream=True` 并在服务端累积 chunk，首页任务 SSE 新增 `task_progress` 事件与更细的 `message/progress` 更新；仅在最终 JSON 解析成功后持久化历史报告；不支持流式的 provider 自动回退到非流式调用。
- 🤖 **Web AI 模型配置支持按渠道获取可用模型列表** — 渠道编辑器支持调用 `/v1/models` 拉取可用模型，并以多选方式写回 `LLM_{CHANNEL}_MODELS`；拉取失败时保留手动输入作为降级路径。

### 改进

- 🔎 **SerpAPI 正文补抓范围收敛** — 自然搜索结果不再逐条同步抓取网页正文；仅对极少数高位且摘要不足的结果做延迟补抓，优先复用 SerpAPI 已返回的结构化摘要，降低搜索链路尾延迟与慢站点放大风险。
- 🤖 **LLM 接入体验简化** — 面向用户的 AI 模型接入文案统一为"主模型 / Agent 主模型 / 备选模型 / 模型渠道"，不再把 LiteLLM 当作普通用户必学概念，现有 `LITELLM_*` / `LLM_CHANNELS` 配置键保持兼容。
- 🧠 **IntelAgent 新增公司公告搜索与主力资金流工具** — 增加上交所/深交所/cninfo 公告搜索维度与 `get_capital_flow` 工具，修复 Agent 模式下公告和资金流数据经常缺失的问题。
- 📦 **后端股票名称解析优先复用 `stocks.index.json`** — 懒加载缓存前端静态索引，纯后端/缺失静态资源场景静默降级回 `STOCK_NAME_MAP` 与原有数据源回退链路。
- 📊 **TushareFetcher 港股单位适配** — `get_chip_distribution` 对港股直接返回 `None`（港股暂不支持筹码分布）；`_normalize_data` 对港股（`hk_daily`）不再做 A 股手→股、千元→元的缩放，与 Tushare 港股字段语义一致。
- ⏱️ **Agent 超步数错误增加 `AGENT_MAX_STEPS` 调整提示** — 帮助用户自助排查步数限制问题。
- ⚙️ **GitHub Actions 分析任务超时支持 `vars` 配置** — `daily_analysis.yml` 任务超时从 repository variables 读取，无需修改代码即可调整运行超时上限（fixes #1014）。

### 修复

- 📣 **大盘复盘链路接入 `REPORT_LANGUAGE`** — `REPORT_LANGUAGE=en` 时，A 股/合并复盘的 Prompt、章节标题、模板兜底文案与通知包装标题统一输出英文，避免英文正文搭配中文标题的混排问题。
- 📈 **EfinanceFetcher 指数开盘价映射兼容**（fixes #1043）— `get_main_indices()` 的开盘价映射改为兼容 `今开 → 开盘 → open`，修复部分 efinance 版本下指数开盘价被读成缺失值的问题。
- 🤖 **AGENT_MAX_STEPS 语义统一**（fixes #1026）— 在 orchestrator 多 Agent 模式下明确为"各子 Agent 步数上限而非硬覆盖"；TechnicalAgent 等高默认值 Agent 会被封顶，低默认值 Agent 保持原值；用户主动调高（>10）时统一覆盖所有子 Agent。修复了用户设置 12 但 TechnicalAgent 仍以默认 6 步运行并报 "Agent exceeded max steps" 的问题。
- 🛡️ **Specialist（Skill）Agent 失败改为优雅降级** — 技能 Agent 失败不再中断整个分析管线，与 intel/risk 保持相同的降级策略。
- 🔧 **MiniMax-M2.7 连接测试修复** — 修复 LLM 通道连接测试在 MiniMax-M2.7 下返回 "Empty response" 的问题；将 `max_tokens` 上限从 8 提升至 256 以容纳思考过程，并添加 `content_blocks` 格式解析逻辑。
- 📊 **移除 `sentiment_score` 范围约束**（fixes #942）— 移除 `HistoryItem` 与 `ReportSummary` 响应 Schema 中 `sentiment_score` 的 `ge=0/le=100` 约束，历史库中存储的超范围值不再触发 Pydantic ValidationError。
- 🖥️ **WebUI 前端资源缺失时发出明确警告** — `webui_frontend.py` 在 `static/index.html` 存在但 `static/assets/` 缺失时发出 warning，避免 CSS/JS 资源缺失导致页面异常变大却无从排查（fixes #944）。
- 🔗 **分析管线可选服务降级初始化** — `StockAnalysisPipeline` 搜索服务与社交舆情服务任一初始化异常时，记录 warning 并以禁用状态继续运行，避免外部依赖抖动阻塞主分析链路。
- 🖥️ **桌面端版本展示统一读取 `package.json`** — 统一读取 `apps/dsa-desktop/package.json`，移除 preload 中硬编码的 `0.1.0`，设置页展示真实桌面端版本；修复版本号显示错误（fixes #1048）。
- 🐋 **港股名称获取失败修复**（fixes #940）— 修复主数据源字段缺失时无法正确回退到备用字段获取港股名称的问题。
- 🔄 **SSE 任务流断开时 `CancelledError` 正确 re-raise**（fixes #967）— 修复 SSE 流中断时异常被静默吞掉导致故障无日志可查的问题。
- 🔄 **Agent SSE 清理阶段后台任务异常正确上报**（fixes #969）— 流结束时后台执行器异常现在正确记录并上报，避免错误无法感知。
- 🔇 **技能加载异常补充 `logger.warning` 日志**（fixes #970）— 在 `ask.py`、`skills/aggregator.py`、`skills/router.py` 的静默 except 块补充日志，确保技能列表为空时有日志可查。
- 🛠️ **SQLite 写入链路原子化**（fixes #878）— `stock_daily(code,date)` 使用批量原子 upsert；文件型 SQLite 连接默认启用 WAL + `busy_timeout` + 有限写入重试；"新增数"改按本次真正插入窗口计算。
- 💰 **多 Agent / 单 Agent 预算护栏语义统一** — 剩余预算低于最小阈值时主动跳过并降级；已完成阶段可构建降级报告时返回 `success=True` 并携带非空内容，否则返回 `success=False`。
- ⚙️ **GitHub Actions `daily_analysis.yml` 补齐 `REPORT_LANGUAGE` 注入**（fixes #1013）— 修复用户在 Secrets/Variables 中配置 `REPORT_LANGUAGE` 后不生效的问题。
- 📊 **任务状态 API 补齐实时价格字段**（fixes #983）— `GET /api/v1/analysis/status/{task_id}` 从数据库回填已完成任务时补齐 `current_price` / `change_pct`，修复首页报告股票名旁不显示实时价格的问题。
- 📅 **非交易日数据返回最近交易日**（fixes #1009）— 修复非交易日（周末/节假日）筹码分布与板块排行返回倒数第二个交易日数据的问题，现在正常返回最近交易日数据。
- 🔍 **A 股资讯搜索恢复中文优先** — `search_stock_news()` 在首个 provider 主要返回英文资讯时继续尝试后续引擎，并将同批结果中的中文资讯排到前面；非美股查询不再默认沿用 Brave 的 `en/US` 区域语言偏好。
- 📨 **飞书群机器人通知支持签名校验** — 飞书通知现在支持 `FEISHU_WEBHOOK_SECRET` / `FEISHU_WEBHOOK_KEYWORD`；Web 设置与文档明确区分 Webhook 推送模式和 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` 应用模式，降低误配风险。
- ⚡ **LLM 适配层新增 `RateLimitError` 和 `ContextWindowExceeded` 检测** — 识别并处理速率限制与上下文窗口超出错误，提升分析链路在高负载或长文本场景下的健壮性（fixes #1002）。

### 测试

- 🧪 **TushareFetcher 港股相关单元测试** — 新增 `get_chip_distribution` 筹码分布获取与 `_normalize_data` 港股/A 股/ETF 单位处理的单元测试，覆盖港股特殊路径。

### 文档

- 📘 **DEPLOY.md 补充 UI 元素异常变大排查步骤** — 新增重建 Docker 镜像或手动执行 `npm run build` 的排查指南；`deploy-webui-cloud.md` 同步更新。
- 📨 **飞书 Webhook 配置说明补全** — 强调 `FEISHU_WEBHOOK_URL` 是群通知必填项、签名校验须两端同时启用或关闭、`FEISHU_APP_SECRET` 仅用于应用/Stream Bot 模式；`.env.example` 补充内联注释；同步英文指南。
- 🤝 **FAQ 补充 Ollama 连接失败排障条目（Q12c）** — 覆盖服务未启动、URL 配置错误、模型前缀缺失、模型未下载、远程防火墙等 5 个检查点（fixes #854）。
- 🌉 **README 补充长桥数据源使用说明** — 中/英/繁 README 明确长桥"首选 / 兜底 / 未配置不调用"边界；`docs/` 内相对路径链接修复；`LONGBRIDGE_PRINT_QUOTE_PACKAGES` 配置与代码及 `.env.example` 对齐。
- 🐋 **Docker 安装场景版本说明** — 补充最小化文档，明确 Docker 安装场景下应以 Git tag / 镜像 tag 判断版本（fixes #1091）。

## [3.12.0] - 2026-04-01

### 发布亮点

- 📊 **回测页新增"次日验证"视图** — 可按股票与日期范围查看 AI 预测 vs 次日实际涨跌，复用历史分析与 1 日回测结果，快速验证分析准确率。
- 🔧 **LLM 接入体验简化** — 用户侧文案统一收口为"主模型 / 备选模型 / 模型渠道"，不再把 LiteLLM 当作普通用户必学概念，现有配置键保持兼容。
- 🐳 **Docker / WebUI 运行时稳态补强** — 修复系统设置保存后配置不生效、启动早期日志缺失、预构建静态资源复用等问题，降低容器化部署的运维摩擦。
- 🔒 **安全与并发稳定性同步增强** — Discord 入站 Webhook 补齐 Ed25519 验签，修复并发执行时共享状态未加锁、单股推送模式通知并发复用等问题。
- 🖥️ **桌面端与定时任务细节打磨** — Windows 安装器支持自选安装目录，内置定时调度器感知运行中 SCHEDULE_TIME 变更，断点续传改按市场时区判断。

### 新功能

- 📊 **回测页新增"次日验证 / 1 日窗口"视图** — 可按股票代码与分析日期范围查看 AI 预测、次日实际涨跌及筛选区间准确率，复用历史分析与 1 日回测结果实现。
- 🏷️ **Web 设置页新增版本信息卡片** — `apps/dsa-web` 现在会在构建时注入前端包版本与构建时间，系统设置页新增只读"版本信息"区块，展示 `WebUI 版本 / 构建标识 / 构建时间`；当 `package.json` 仍为占位版本 `0.0.0` 时，会自动回退为构建标识，方便 Docker 重建后快速确认当前静态资源是否已经生效。
- 🪟 **Windows 桌面安装器支持自选安装目录** — 安装器改为支持在安装向导中自定义安装目录，安装到非默认盘符后仍沿用现有打包态目录逻辑在安装目录旁读写 `.env`、`data/stock_analysis.db` 和 `logs/desktop.log`，同时保留 `win-unpacked` 免安装分发方式。安装器仅支持当前用户安装、已禁用管理员提权（`allowElevation: false`），并通过 NSIS `.onVerifyInstDir` 阻止选择系统保护目录。

### 改进

- 🔎 **SerpAPI 正文补抓范围收敛** — 自然搜索结果不再逐条同步抓取网页正文；现在仅对极少数高位且摘要明显不足的结果，在更短超时预算内做延迟补抓，并优先复用 SerpAPI 已返回的结构化摘要，降低搜索链路尾延迟与慢站点放大风险。
- 🤖 **LLM 接入体验简化** — 面向用户的 AI 模型接入文案已统一收口为"主模型 / Agent 主模型 / 备选模型 / 模型渠道 / 高级模型路由配置"；Web 设置页、配置元数据、校验提示与中英文文档不再把 LiteLLM 当作普通用户默认必学概念，现有 `LITELLM_*` / `LLM_CHANNELS` 配置键仍保持兼容。

### 修复

- 🚀 **启动早期失败时暴露真实根因** — `python main.py` 现在通过 stderr 暴露真实根因，bootstrap 阶段不再向硬编码 `logs/` 目录写入文件日志，文件日志推迟到 `config.log_dir` 可用后创建，避免健康启动在非预期路径残留日志文件。
- 🐳 **Docker WebUI 运行时优先复用预构建静态资源** — `prepare_webui_frontend_assets()` 现在会先检查镜像内已有的 `static/index.html` 是否可直接复用；当容器运行时不包含 `apps/dsa-web` 源码目录且未安装 `npm` 时，也不会误报"未找到前端项目，无法自动构建"，从而恢复 Docker 部署后的 WebUI 打开能力。
- 🐳 **Docker WebUI 系统设置保存后配置生效** — Docker 场景下 WebUI 保存 `STOCK_LIST`、`SCHEDULE_ENABLED`、`SCHEDULE_TIME`、`SCHEDULE_RUN_IMMEDIATELY`、`RUN_IMMEDIATELY` 后，`Config` 会优先读取持久化 `.env` 中的新值，避免被容器创建时注入的旧环境变量覆盖。
- 📈 **市场复盘 LLM max_tokens 提升** — 市场复盘生成链路将 LLM `max_tokens` 从 `2048` 提升到 `8192`，降低长复盘输出因 `MAX_TOKENS` 提前截断导致内容未完成的概率。
- ⏰ **内置定时调度器感知 SCHEDULE_TIME 运行时变更** — 调度器现在会在运行中感知 WebUI 保存后的 `SCHEDULE_TIME` 变化，并在下一轮检查时重绑 daily job。
- 🪟 **Windows Release 渠道编辑器保留 MiniMax 模型前缀** — 渠道模式下填写 `minimax/<模型名>` 时，后端归一化与 Web 设置页运行时模型列表都会保留该值原样，不再误改写成 `openai/minimax/<模型名>`。
- 🤖 **Discord 入站 Webhook 补齐 Ed25519 验签** — `DiscordPlatform` 现在会基于 `X-Signature-Ed25519`、`X-Signature-Timestamp` 和原始请求体校验 Discord Interaction 签名；缺失签名头、公钥格式非法或签名不匹配时直接拒绝请求，同时对 timestamp 做 ±5 分钟时效窗口校验以防御重放攻击。
- ⚙️ **STOCK_GROUP_N / EMAIL_GROUP_N 配置关系明确化** — 明确与 `STOCK_LIST` 的关系，并在配置校验中对超出 `STOCK_LIST` 的邮件分组给出 warning。
- 🗓️ **断点续传改按市场时区和交易日历判断**（fixes #880）— 股票数据存在性检查不再直接使用服务器自然日，而是按 A 股 / 港股 / 美股各自市场时区解析"最新可复用交易日"。
- 📨 **单股推送模式不再并发复用共享通知实例** — `StockAnalysisPipeline.run()` 现在会保留个股分析并发，但把 `SINGLE_STOCK_NOTIFY=true` 下的即时通知挪到结果收集侧串行发送。
- 🔇 **实时行情降级提示收口为单次告警** — 分析主流程获取股票名称时不再提前触发一次实时行情查询，只有在全部数据源都不可用时才提示已降级为历史收盘价继续分析。
- 🔍 **A 股中文资讯搜索恢复中文优先** — `search_stock_news()` 现在会在首个 provider 主要返回英文资讯时继续尝试后续引擎，并将同批结果中的中文资讯排到前面。
- 🔒 **并发执行时共享状态补齐统一加锁** — 修复并发执行时共享状态缺少统一加锁的问题，避免多线程场景下的数据竞争。

### 测试

- 🧪 **补充设置页版本信息回归测试** — 新增 Web 设置页版本信息渲染断言，并覆盖占位版本 `0.0.0` 自动回退为构建标识的逻辑。
- 🧪 **UI 治理与关键路径回归补强** — 补充 `SidebarNav`、`ChatPage`、`BacktestPage` 等组件测试，并新增 UI governance 守卫，持续防止交互元素重新引入原生 `title` 属性或旧 `input-terminal` 样式回流。同步更新 smoke / markdown drawer 相关验证，覆盖主题升级后的关键主链路。

## [3.11.0] - 2026-03-27

### 发布亮点

- 🎨 **Web 工作台完成一轮 UI 统一与双主题升级** — 首页、问股、回测、持仓和设置页进一步收口到统一设计 token、输入表面和状态表达；新增完整浅色主题，并支持浅色 / 深色一键切换与持久化保存。
- 🤖 **Bot / Agent 能力重新补回主分支** — 恢复 `/history`、`/strategies`、`/research` 等命令，`/ask` 继续支持多股对比与组合视角；Deep Research、事件监控与 schedule 轮询链路重新接回主线能力。
- 🔒 **安全性与运行稳态同步补强** — 修复 `X-Forwarded-For` 限流绕过风险，恢复 LiteLLM 官方 PyPI 安装路径，Tushare 初始化不再依赖本地 SDK，降低 Docker、桌面打包和环境重建时的脆弱点。
- 🖥️ **日常使用细节继续打磨** — 修复首页港股自动补全提交、登录页首屏主题闪烁、历史长股票名重叠，以及 Telegram Markdown 解析失败时整条通知发送中断等问题。

### 新功能

- 🎨 **全新浅色主题与双主题切换上线** — Web 工作台新增完整浅色主题，并支持在侧边栏中一键切换浅色 / 深色模式；主题选择会持久化保存，刷新页面后仍保持当前偏好。此次升级不是局部配色微调，而是对卡片层级、边界对比、输入表面、状态提示和页面背景做了一整套 light theme 重绘。
- 🤖 **补回主分支缺失的 Agent / Bot 能力** — `#648` / `#649` 已重新补回 `main`：Bot 恢复 `/history`、`/strategies`、`/research`，`/ask` 保留多股对比与组合视角；Deep Research 与 Event Monitor 的配置重新在 Web 设置页可见并可编辑，schedule 模式也重新接入事件告警轮询。

### 改进

- 🖥️ **核心页面统一到同一套工作台视觉语言** — `Home / Chat / Backtest / Portfolio / Settings` 进一步收口到共享设计 token、`input-surface` 输入体系、空态/错误态表达和抽屉遮罩语义，减少页面之间的视觉割裂与局部私有样式漂移。
- 💬 **问股交互可达性与反馈增强** — 问股页补强了会话导出、通知发送、消息复制、历史删除与追问上下文提示；AI 回复操作不再过度依赖 hover，触屏设备和小屏场景下也能直接触达关键按钮。
- 📊 **回测与持仓页表面和状态表达继续标准化** — 回测页筛选控件、布尔状态、结果表格与汇总卡片统一到共享输入/状态原语；持仓页的导入反馈、汇率刷新提示、空态与警示信息进一步归口到共享组件，减少页面级重复实现。
- 🧭 **导航与页面壳层协同优化** — 侧边栏主题切换、问股完成角标、移动端抽屉遮罩和主内容滚动契约进一步统一，首页、问股和回测在桌面端与移动端的切页体验更稳定。

### 测试

- 🧪 **UI 治理与关键路径回归补强** — 补充 `SidebarNav`、`ChatPage`、`BacktestPage` 等组件测试，并新增 UI governance 守卫，持续防止交互元素重新引入原生 `title` 属性或旧 `input-terminal` 样式回流。同步更新 smoke / markdown drawer 相关验证，覆盖主题升级后的关键主链路。

### 修复

- 🌗 **Web 首屏默认主题预设为深色** — `apps/dsa-web/index.html` 现在会在 React 挂载前读取本地保存的主题偏好；若没有已保存值，则立即给 `<html>` 预设 `dark` 并同步 `color-scheme`，避免首页和登录页首屏先闪出浅色主题。
- 🔐 **登录页独立主题层收口** — 登录页输入框、标签、切换按钮和按钮文案现在使用独立的 `--login-*` 视觉 token，不再继承全局浅/深主题文字色；即使浏览器缓存了浅色主题，登录页仍保持稳定的深色视觉与青色密码输入表现，避免密码圆点和文案落成黑色。
- 🖥️ **首页港股代码输入修复** — Web 首页分析输入框现在可正确接受港股代码与自动完成选中的港股项，补齐 `00700.HK` / `HK00700` 等格式识别，避免提交时误报“请输入有效的股票代码或股票名称”。

- 🔒 **认证限流 X-Forwarded-For 取值修复（CWE-345）**（#841 / #842）— `get_client_ip()` 从取 `X-Forwarded-For` 最左值改为最右值，防止攻击者通过伪造首部旋转限流桶绕过暴力破解保护；仅影响 `TRUST_X_FORWARDED_FOR=true` 且单层可信反向代理的部署场景，多级代理环境需按部署文档评估配置。
- 📦 **恢复 LiteLLM 官方 PyPI 安装并锁定安全上限** — `requirements.txt` 重新使用 `pip install litellm` 的官方 PyPI 安装路径，并在保留历史最低要求 `>=1.80.10` 的同时增加 `<1.82.7` 的安全上限，避免误装已被移除的 `1.82.7` / `1.82.8` 风险版本；Windows 桌面打包脚本也同步回退到标准 `pip install -r requirements.txt` 链路，减少特殊下载分支带来的维护成本。
- 📨 **Telegram Markdown 解析失败回退纯文本**（fixes #850）— `src/notification_sender/telegram_sender.py` 现在会在 Telegram 返回 `HTTP 400` 且包含 `can't parse entities` / Markdown 解析错误时，自动去掉 `parse_mode` 后重试纯文本发送，避免 `*ST` 等正文内容直接导致整条通知失败。
- 🔢 **A 股同码实时行情保留交易所提示**（fixes #852）— `DataFetcherManager` 与 `TushareFetcher` 现在会保留 `SZ000001` / `000001.SZ` 这类显式沪深提示，旧版 Tushare 实时行情降级分支不再把深市 `000001` 误判成 `sh000001` 上证指数。
- 🎯 **多 Agent 次优买点不再盲目复制理想买点**（fixes #851）— 当多智能体结果缺少独立 `secondary_buy` 时，仪表盘现在优先展示 `N/A` 而不是把 fallback 值硬拷贝成与 `ideal_buy` 完全相同，减少误导性的双买点展示。
- 🧩 **Tushare 初始化不再强依赖本地 SDK 包** — `TushareFetcher` 现在直接使用内置 HTTP client 访问 Tushare Pro，不再在启动阶段先 `import tushare` 才能初始化；修复了 Docker、桌面打包或环境重建后因缺少 `tushare` 包而提前报 `No module named 'tushare'` 的问题，并补充对应回归测试。
- ⚙️ **`daily_analysis` 工作流补齐 `DEEPSEEK_API_KEY` 映射** — GitHub Actions 每日分析工作流现在会正确透传 `DEEPSEEK_API_KEY`，避免云端任务配置了密钥却在运行时拿不到对应环境变量。
- 🖥️ **历史列表过长股票名称截断与悬停展示**（fixes #815）— 历史列表中过长的股票名称, 现在会按字符类型自动截断（英文15/中文8/混合10字符），默认显示截断结果，悬停时展示完整名称；解决 1920x1080 分辨率下股票名称与右侧状态标签文字重叠的问题。新增 `stockName.ts` 工具函数并补充对应测试。

### 文档

- 🧾 **README 捐赠入口更新为小红书二维码** — README 及中英文说明中的赞助入口更新为小红书二维码素材，保持展示口径一致。

## [3.10.1] - 2026-03-24

### 新功能

- 🔔 **Web 端分析推送通知开关**（#808）— 首页分析按钮旁新增「推送通知」复选框，默认勾选；取消勾选时本次分析不发送 Telegram/企业微信等推送。API `POST /api/v1/analysis/analyze` 新增 `notify` 字段（`bool`，默认 `true`），不传时行为与修改前一致，Bot 和定时任务不受影响。

### 改进

- 🖥️ **问股 / 回测页面布局与壳层协同优化** — 统一 Chat / Backtest 页面容器、共享 UI 状态和跟随问答交互路径，移除部分硬编码高度限制，让导航框架内的填充与滚动行为更连贯。
- 🎨 **全局视觉与共享组件继续收敛** — Light theme 引入动态 HSL 阴影体系，统一侧边栏激活态、告警组件对比度和聊天气泡样式，并把部分零散内联样式收口为语义化 CSS 变量，提升一致性与可维护性。

### 修复

- 🖼️ **系统设置智能导入文件选择恢复** — 修复了“系统设置 > 基础设置 > 智能导入”模块中 “选择图片 / 选择文件” 两个按钮点击无响应的问题。
- 🖥️ **移动端滚动与交互层级修复** — 解决主题切换菜单在移动端被主内容遮挡的 z-index 冲突，并恢复首页长报告场景下的正常纵向滚动，不影响其他页面现有滚动行为。
- 🧾 **Markdown 纯文本复制清洗增强** — 改进纯文本导出算法，复制分析报告时会更稳定地清除表格分隔符等 Markdown 痕迹，提升分享和归档内容的纯净度。
- 🧠 **Trading philosophy injection 覆盖 legacy + Agent 全链路**（#810）— `GeminiAnalyzer`、单 Agent 模式和 skill-aware Prompt 现在共享同一套策略注入状态；只有隐式回落到内置默认 `bull_trend` 时才保留旧的趋势型提示，显式策略选择或自定义默认 skill 不再被偷偷叠加 `MA5>MA10>MA20` 多头基线。
- 🛠️ **后端 CI 依赖安装链路稳态化**（#835）— 拆分 backend gate 阶段、为依赖安装增加重试，并把 CI 用的 `litellm` 安装来源调整为更稳定的 GitHub 源，降低依赖解析抖动导致的 backend gate 偶发失败。
- 🪟 **Windows 桌面发版构建恢复 LiteLLM 安装兼容性** — `scripts/build-backend.ps1` 现在会先过滤 `requirements.txt` 中的 LiteLLM GitHub 源包，再下载对应 tag 的 zipball 到本地移除上游可选 `enterprise/` 目录后安装，绕过 Windows runner 上 Poetry 构建 wheel 时把目录误当文件打包导致的失败；同时补上 `pip install` 退出码检查，避免依赖安装失败后只在后续 `python-multipart` 校验阶段才暴露成次生报错。

### 测试

- 🧪 **问股 / 回测 / 智能导入回归覆盖补齐** — 同步更新 E2E 冒烟期望，补充 `DashboardStateBlock`、Chat 页、智能导入文件选择与相关交互回归断言，确保近期 UI 调整后的关键路径仍可稳定通过。

## [3.10.0] - 2026-03-24

### 发布亮点

- 🔎 **自动补全与索引工具扩展到三市场** — 补全索引生成链路现在同时覆盖 A 股、港股、美股，配套新增 Tushare 股票列表抓取工具与更完整的静态索引数据，让首页搜索入口从“能用”走向“更全、更稳”。
- 🖥️ **Dashboard 与报告查看体验继续收口** — 首页 Dashboard 面板、状态边界、字体层级和完整报告表格密度完成一轮统一；报告详情也补齐了 Markdown/纯文本复制与更可靠的按钮交互，减少历史报告查看与分享时的摩擦。
- 🤖 **Agent skill 与市场语义边界更清晰** — skill bundle、默认策略、回测汇总语义和兼容接口进一步收敛；同时分析 Prompt 不再默认写死 A 股上下文，美股和港股分析也能按各自市场规则生成更贴切的内容。
- ⏰ **定时与桌面配置能力更贴近真实使用场景** — 桌面端支持 `.env` 导入导出；`python main.py --schedule --stocks ...` 也不再把启动时股票快照错误带入后续计划执行，定时任务会跟随最新保存的 `STOCK_LIST`。
### 新功能

- 💾 **桌面端 `.env` 备份/恢复入口**（#754）— 桌面模式下的系统设置页新增 `导出 .env` / `导入 .env` 按钮，可直接备份当前已保存配置，或把备份文件中的键值合并恢复到当前桌面端 `.env`；导入沿用现有 `config_version` 冲突保护与运行时重载链路，不改变现有桌面端便携模式路径。
- 📊 **Tushare 股票列表获取工具** — 新增 `scripts/fetch_tushare_stock_list.py`，支持从 Tushare Pro 获取 A股、港股、美股列表信息并保存为 CSV，配有分页读取、智能限流、错误处理和进度提示；新增对应使用文档 `docs/TUSHARE_STOCK_LIST_GUIDE.md`。
- 🔎 **索引生成脚本多市场支持** — `generate_index_from_csv.py` 重构为支持 Tushare 和 AkShare 双数据源，同时覆盖 A股、港股、美股三个市场；新增按市场分类的别名映射（A股、港股常见别名，美股常用股票英文缩写）；添加 `--source` 参数切换数据源、`--test` 参数验证模式；严格过滤美股 DUMMY 记录。
- 🔎 **索引生成脚本增强** — `generate_stock_index.py` 新增 `--test`/`-t` 测试模式和 `--verbose`/`-v` 详细输出模式，添加市场分布统计，优化 JSON 输出格式。
- 📋 **首页完整报告支持双模式复制** — 历史报告详情头部新增“复制 Markdown 源码”和“复制纯文本”工具按钮；前者保留原始 Markdown 结构，后者去除常见 Markdown 格式符号，方便分享、归档和跨报告比对。复制按钮文案会跟随 `REPORT_LANGUAGE` 保持中英文一致，避免英文报告页出现中文固定文案。
- 🧩 **个股分析页补齐关联板块展示**（#669）— A 股分析写路径现在会把 `belong_boards` 一次性写入 `fundamental_context` / `fundamental_snapshot`，结构化报告详情同步新增 `belong_boards` 与 `sector_rankings` 字段，Web 个股分析页首屏可直接展示所属板块及其是否命中当日板块涨跌榜；无数据时保持 fail-open 隐藏，不影响现有分析主流程。

### 改进

- 🖥️ **Dashboard 面板统一化（PR7-2）** — 新增 `DashboardPanelHeader` 和 `DashboardStateBlock` 作为历史、报告、资讯、任务和透明度等面板的通用组件；统一了各面板标题层级、加载/空态/错误态和 CSS 变量 token。
- 🖥️ **HomePage 状态边界收口（PR7-2）** — 引入 `useHomeDashboardState` hook，集中 `stockPoolStore` 状态选取逻辑，移除 `HomePage` 中重复的本地状态派生和回调定义。
- 🧭 **Agent skill 统一到单一配置语义** — Multi-Agent runtime、API、Web chat 和配置元数据统一围绕 `skill` 概念收敛；`/api/v1/agent/skills` 成为主发现入口，`AGENT_SKILL_*` 成为主配置面，内置 skill 元数据也开始声明默认启用、排序优先级、market regime tag 等信息，减少默认策略散落在代码里的隐式耦合。
- 🔎 **自动补全索引数据更新** — 重新生成 `stocks.index.json`，涵盖 A股、港股、美股三个市场，提升自动补全覆盖率。
- 🧾 **Dashboard 字体与完整报告表格密度微调** — 收敛首页侧栏、空状态、历史操作区的字体层级，并将完整 Markdown 报告表格 `th/td` 的内边距调整到更紧凑的 4-6px 区间，让信息密度与现有 Dashboard 视觉节奏更一致。

### 修复

- ⏰ **定时模式不再锁定启动时 CLI 股票快照** — `python main.py --schedule --stocks ...` 现在不会让后续计划执行沿用启动时的旧股票列表；定时任务每次触发前都会重新读取最新保存的 `STOCK_LIST`，确保 WebUI 或 `.env` 更新后的自选股配置能参与后续推送。
- 🌍 **LLM Prompt 按股票市场动态注入上下文** — 分析链路不再把市场规则写死成 A 股；系统 Prompt 会根据股票代码识别 A 股、港股或美股，并注入对应的角色描述与交易规则提示，减少跨市场分析出现口径错位或结论失真的问题。
- 🔎 **美股自动补全复用 ticker 去重** — `generate_index_from_csv.py` 在导入 Tushare `us_basic` CSV 时会先按 `ts_code` 折叠复用的美股 ticker，优先保留更可能仍在使用的记录，避免 `stocks.index.json` 出现重复 `canonicalCode` 后让 Web 自动补全展示历史名称或提交歧义代码。
- 🧾 **Web 报告详情复制交互稳定性修复**（#749）— `ReportDetails` 中“原始分析结果 / 分析快照”的复制按钮补齐可点击层级，避免被下方 JSON 内容覆盖；两个面板的复制提示也改为各自独立，不再出现复制一个后两个按钮同时显示“已复制”的误导反馈。
- 📊 **Agent skill 回测与兼容接口语义收敛** — `get_skill_backtest_summary` 现在要求显式传入 `skill_id`，缺失时返回明确校验提示；仓库尚未持久化真实 skill 级汇总时会返回明确的 unsupported/info 响应，并保留 `normalized` 与 `*_pct` 兼容字段，避免沿用 overall 指标误导 Agent 或用户。
- 🔧 **Skill 默认选择与兼容层行为加固** — `allowed-tools` 会继续仅作为 `SKILL.md` bundle 元数据保留，不再泄露到运行时工具选择；`/api/v1/agent/strategies` 恢复旧 payload 形状；显式传入 `skills: []` 时会清空陈旧上下文；当用户明确选择策略 skill 时不再偷偷叠加默认 bull-trend，而在 `AGENT_SKILLS` 为空时则统一只回落到单一主默认 skill。

### 测试

- 🧪 **Dashboard 组件测试覆盖率扩展（PR7-2）** — 新增 `ReportNews` 和 `TaskPanel` 测试；对 `HistoryList`、`ReportDetails`、`HomePage`、`useDashboardLifecycle` 和 `stockPoolStore` 增强了断言覆盖，包括删除回退、移动端抽屉和任务生命周期等场景。
- 🧪 **多市场索引生成测试补齐** — 新增 `tests/test_generate_index_from_csv.py`，覆盖 Tushare/AkShare 双数据源解析、多市场判断、美股 DUMMY 过滤与重复 ticker 去重等核心路径。
- 🧪 **关联板块写入与 API 契约回归** — 新增 `tests/test_pipeline_related_boards.py`，并补充分析历史与分析接口契约测试，确保 `belong_boards` / `sector_rankings` 只做增量扩展且保持 fail-open。
- 🧪 **定时模式股票列表语义回归测试** — 新增 `tests/test_main_schedule_mode.py`，覆盖定时模式忽略启动时 `--stocks` 快照、单次运行仍保留 CLI 股票覆盖的边界场景。

### 文档

- 📘 **新增 Tushare 股票列表工具文档** — 新增 `docs/TUSHARE_STOCK_LIST_GUIDE.md`，说明股票列表抓取工具的使用方法、数据格式和常见问题。
- 🌍 **补齐定时模式与关联板块的双语说明** — `docs/full-guide.md` / `docs/full-guide_EN.md` 现在明确说明 scheduled mode 会在每次执行前重新读取 `STOCK_LIST`，并同步补充个股关联板块展示能力说明，减少配置预期偏差。
- 🧭 **调整 Agent 术语兼容文案** — README、双语文档、设置页与问股界面继续以“策略”作为用户入口主称呼，同时补充 `skill` 作为内部统一命名，降低迁移期理解成本。

## [3.9.0] - 2026-03-20

### 发布亮点

- 🤖 **模型链路与报告语言更灵活** — Agent 现在可以通过 `AGENT_LITELLM_MODEL` 独立选择模型链路，普通分析与 Agent 报告也可通过 `REPORT_LANGUAGE=zh|en` 输出统一语言，减少“英文内容 + 中文壳子”这类混排问题，并允许团队分别权衡主分析与 Agent 的成本、速度和能力。
- 🔎 **首页分析体验完成一轮闭环优化** — 首页新增 A 股自动补全，支持代码、中文名、拼音和别名检索；同时 Dashboard 状态收口到统一 store，历史、报告、新闻与 Markdown 抽屉的交互更稳定，“Ask AI” 追问也会优先携带当前报告上下文。
- 💬 **通知与检索能力继续外扩** — 新增 Slack 一等通知渠道；SearXNG 在未配置自建实例时可以自动发现公共实例并按受控轮询降级；Tavily 时效新闻链路修复后，严格时效过滤不再错误丢光有效结果。
- 💼 **持仓与市场复盘链路更稳** — A 股 market review 可选接入 TickFlow 强化指数与涨跌统计；持仓账本写入改为串行化以缩小并发超卖窗口；汇率刷新入口和禁用态提示也更加清晰，减少用户误判。

### 新功能

- 🔎 **Web 股票自动补全 MVP** — 首页分析输入框新增本地索引驱动的自动补全，支持股票代码、中文名、拼音和别名匹配；选中候选后会提交 canonical code，并透传 `stock_name`、`original_query`、`selection_source` 到分析请求、任务状态和 SSE 事件；索引加载失败时自动退回旧输入模式，不阻断原有提交流程。同步补充了静态索引加载器、索引生成脚本和前后端契约测试。分阶段进行开发，第一阶段仅支持 A 股。
- 💬 **Slack 一等通知渠道** — 新增 Slack 原生通知支持，同时支持 Bot Token 和 Incoming Webhook 两种接入方式；同时配置时优先使用 Bot API，确保文本与图片发送到同一频道；Bot Token 模式支持图片上传（raw body POST，不使用 multipart）；新增 `SLACK_BOT_TOKEN`、`SLACK_CHANNEL_ID`、`SLACK_WEBHOOK_URL` 配置项，GitHub Actions 工作流同步补齐对应 Secrets 传递。
- 🌍 **报告输出语言可配置**（Issue #758）— 新增 `REPORT_LANGUAGE=zh|en`，默认 `zh`；语言设置会同步注入普通分析与 Agent Prompt，并覆盖 Markdown/Jinja 模板、通知 fallback、历史/API `report_language` 元数据及 Web 报告页固定文案，避免“英文内容 + 中文壳子”的混合输出。
- 🚀 **Agent 与普通分析模型解耦**（Issue #692）— 新增 `AGENT_LITELLM_MODEL`（留空继承 `LITELLM_MODEL`，无前缀按 `openai/<model>` 归一）；Agent 执行链路与 `/api/v1/agent/models` 的 `is_primary/is_fallback` 标记改为基于 Agent 实际模型链路；系统配置与启动期校验补齐 `AGENT_LITELLM_MODEL` 的 `unknown_model/missing_runtime_source` 检查；Web 设置页新增 Agent 主模型选择并与渠道模式运行时配置同步。
- 🔎 **SearXNG 公共实例自动发现与受控轮询**（#752）— 新增 `SEARXNG_PUBLIC_INSTANCES_ENABLED`，在未配置 `SEARXNG_BASE_URLS` 时默认从 `searx.space` 拉取公共实例列表，并按受控轮询顺序选择实例；同次请求内遇到超时、连接错误、HTTP 非 200 或无效 JSON 会自动切换到下一个实例。已配置自建实例的用户保持原有优先级与语义不变；`daily_analysis` GitHub Actions 工作流也已支持显式透传该开关并在启动日志中展示当前状态。
- 📈 **TickFlow market review enhancement** (#632) — 新增可选 `TICKFLOW_API_KEY`；配置后，A 股大盘复盘的主要指数行情优先尝试 TickFlow；若当前 TickFlow 套餐支持标的池查询，市场涨跌统计也会优先尝试 TickFlow。失败或权限不足时立即回退到现有 `AkShare / Tushare / efinance` 链路；板块涨跌榜回退顺序保持不变。接入层同时适配了真实 SDK 契约：主指数查询按单次请求上限分批拉取，并将 TickFlow 返回的比例型 `change_pct` / `amplitude` 统一转换为项目内部的百分比口径。

### 改进

- **Dashboard state slice and workspace closure** — moved Home / Dashboard state into `stockPoolStore`, consolidated history selection, report loading, task syncing, polling refresh, and markdown drawer handling under a single state slice.
- **Dashboard panel standardization** — kept the current dashboard layout contract stable while unifying history, report, news, and markdown presentation with shared tokens, standardized states, and bounded in-panel scrolling for the history list.
- **Dashboard-to-chat follow-up bridge** — routed “Ask AI” follow-ups through report-context hydration instead of direct cross-page state coupling, while keeping chat sends usable when enriched history context is still loading.
- 💼 **持仓账本并发写入串行化**（#742）— 持仓源事件写入/删除现在会在 SQLite 下先获取串行化写锁，减少并发卖出把超售流水写入账本的窗口；直接持仓写接口在锁竞争时返回 `409 portfolio_busy`，CSV 导入保持逐条提交并把 busy 计入 `failed_count`。
- 💱 **持仓页汇率手动刷新入口补齐**（#748）— Web `/portfolio` 页面现在会在“汇率状态”卡片中展示“刷新汇率”按钮，直接调用现有 `POST /api/v1/portfolio/fx/refresh` 接口；刷新后会仅重载快照与风险数据，并以内联摘要反馈“已更新 / 仍 stale / 刷新失败”的结果，减少用户对 `fxStale` 长时间停留的误解。

### 修复

- 🔎 **Web 自动补全 Enter 提交语义修正** — 股票自动补全在搜索命中候选时不再默认高亮第一项；候选列表展开但用户尚未用方向键或鼠标明确选中时，按 Enter 会继续提交原始输入，避免手动输入被第一条候选静默覆盖。
- 🌍 **补齐 `REPORT_LANGUAGE` 启动解析与历史展示本地化边界** — `Config` 在启动时继续遵循“真实环境变量优先、`.env` 兜底”的既有语义，并在两者冲突时输出显式告警，减少 `REPORT_LANGUAGE` 来源不清带来的误判；同时 `/api/v1/history/{id}` 英文详情响应会同步本地化 `sentiment_label`，历史 Markdown 也会正确识别英文 `bias_status` 的风险等级 emoji，避免出现 `乐观` 或 `🚨Safe` 这类中英混排/误报展示。
- 📰 **Tavily 时效新闻检索发布时间映射修复**（#782）— Tavily 在股票新闻和严格时效的情报维度中现在会显式使用 `topic="news"`，并兼容 `published_date` / `publishedDate` 两种发布时间字段；修复了 Tavily 明明返回结果却在后续硬过滤阶段被全部记为 `drop_unknown` 丢弃的问题，同时将机构分析、业绩预期、行业分析等分析型维度恢复为宽源搜索，不再被统一压缩成新闻模式。
- 💱 **持仓页汇率刷新禁用语义修正**（#772）— 当 `PORTFOLIO_FX_UPDATE_ENABLED=false` 时，`POST /api/v1/portfolio/fx/refresh` 现在会返回显式 `refresh_enabled=false` 与 `disabled_reason`，Web `/portfolio` 页面会明确提示“汇率在线刷新已被禁用”，不再误报“当前范围无可刷新的汇率对”。
- 🤖 **Agent timeout and config hardening** — `AGENT_ORCHESTRATOR_TIMEOUT_S` now also protects the legacy single-agent ReAct loop, parallel tool batches stop waiting once the remaining budget is exhausted, and invalid numeric `.env` values fall back to safe defaults with warnings instead of crashing startup.
- 🌐 **CORS wildcard + credentials compatibility** — `CORS_ALLOW_ALL=true` no longer combines `allow_origins=["*"]` with credentialed requests, avoiding browser-side cross-origin failures in demo/development setups.
- 🧭 **Unavailable Agent settings hidden from Web UI** — Deep Research / Event Monitor controls are now treated as compatibility-only metadata in the current branch and are removed from the Settings page to avoid exposing non-functional toggles.

### 文档

- 新增 Ollama 本地模型配置说明，同步更新 `README.md` 与 `docs/README_EN.md`（Fixes #690）
- 完善 Ollama 配置说明：`docs/full-guide.md` / `docs/full-guide_EN.md` 环境变量表与 Note 补充 `OLLAMA_API_BASE`，避免英文用户误以为 Ollama 不能作为独立配置入口；合并重复的 `OLLAMA_API_BASE` 条目为单一条目
- 明确文档同步治理边界：补充 `README.md`、专题文档、双语文档与交付说明之间的默认同步规则，减少后续文档漂移

## [3.8.0] - 2026-03-17

### 发布亮点

- 🎨 **Web 界面完成一轮骨架升级** — 新的 App Shell、侧边导航、主题能力、登录与系统设置流程已经串成统一体验，桌面端加载背景也完成对齐。
- 📈 **分析上下文继续补强** — 美股新增社交舆情情报，A 股补齐财报与分红结构化上下文，Tushare 新接入筹码分布和行业板块涨跌数据。
- 🔒 **运行稳定性与配置兼容性提升** — 退出登录会立即让旧会话失效，定时启动兼容旧配置，运行中的 `MAX_WORKERS` 调整和新闻时效窗口反馈更清晰。
- 💼 **持仓纠错链路更完整** — 超售会被前置拦截，错误交易/资金流水/公司行为可以直接删除回滚，便于修复脏数据。

### 新功能

- 📱 **美股社交舆情情报** — 新增 Reddit / X / Polymarket 社交媒体情绪数据源，为美股分析提供实时社交热度、情绪评分和提及量等补充指标；完全可选，仅在配置 `SOCIAL_SENTIMENT_API_KEY` 后对美股生效。
- 📊 **A 股财报与分红结构化增强**（Issue #710）— `fundamental_context.earnings.data` 新增 `financial_report` 与 `dividend` 字段；分红统一按“仅现金分红、税前口径”计算，并补充 `ttm_cash_dividend_per_share` 与 `ttm_dividend_yield_pct`；分析/历史 API 的 `details` 追加 `financial_report`、`dividend_metrics` 可选字段，保持 fail-open 与向后兼容。
- 🔍 **接入 Tushare 筹码与行业板块接口** — 新增筹码分布、行业板块涨跌数据获取能力，并统一纳入配置化数据源优先级；默认按上海时间区分盘中/盘后交易日取数，优先使用 Tushare 同花顺接口，必要时降级到东财。
- 🧱 **Web UI 基础骨架升级** — 重建共享设计令牌与通用组件，新增 App Shell、Theme Provider、侧边导航，并同步调整 Electron 加载背景，为 Web / Desktop 的统一体验打底。
- 🔐 **登录与系统设置流程重做** — 重构 Login、Settings 与 Auth 管理流程，补上显式的认证 setup-state 处理，并让 Web 端与运行时认证配置 API 行为对齐。
- 🧪 **前端回归与冒烟覆盖补强** — 新增并扩展登录、首页、聊天、移动端 Shell、设置页、回测入口等关键路径的组件测试与 Playwright smoke coverage。

### 变更

- 🧭 **页面接入新 Shell 布局契约** — Home、Chat、Settings、Backtest 已统一接入新的页面容器、抽屉和滚动约定，降低 UI 迁移期间的页面行为不一致。
- 💾 **设置页状态同步更稳** — 优化草稿保留、直接保存同步与冲突处理，减少模块级保存后前后端配置状态不一致的问题。
- 🎭 **登录页视觉基线回归** — 登录页恢复到既有 `006` 分支的视觉基线，同时保留新的认证状态逻辑和统一表单交互模型。
- 🏛️ **AI 协作治理资产加固** — 收敛并加强 `AGENTS.md`、`CLAUDE.md`、Copilot 指令和校验脚本的一致性约束，降低治理资产长期漂移风险。

### Added

- **Web UI foundation refresh** — rebuilt shared design tokens and common primitives, introduced the app shell, theme provider, sidebar navigation, and Electron loading background alignment for the upgraded desktop/web experience
- **Settings and auth workflow overhaul** — rebuilt the Login, Settings, and Auth management flows, added explicit auth setup-state handling, and aligned the Web UI with the runtime auth configuration APIs
- **UI regression coverage and smoke checks** — expanded targeted frontend tests and added Playwright smoke coverage for login, home, chat, mobile shell, settings, and backtest entry flows

### Changed

- **Shell-driven page integration** — aligned Home, Chat, Settings, and Backtest with the new shell layout contract so routing, drawer behavior, and page-level scrolling are consistent during the UI migration
- **Settings state consistency** — refined draft preservation, direct-save synchronization, and conflict handling so module-level saves no longer leave the page out of sync with backend config state
- **Login visual baseline** — restored the login page visual treatment to the established `006` branch baseline while keeping the newer auth-state logic and unified form interaction model

### 修复

- ⏰ **定时启动立即执行兼容旧配置**（Issue #726）— `SCHEDULE_RUN_IMMEDIATELY` 未设置时会回退读取 `RUN_IMMEDIATELY`，修复升级后旧 `.env` 在定时模式下的兼容性问题；同时澄清 `.env.example` / README 中两个配置项的适用范围，并注明 Outlook / Exchange 强制 OAuth2 暂不支持。
- 🧵 **运行期 `MAX_WORKERS` 配置生效与可解释性增强**（#633）— 修复异步分析队列未按 `MAX_WORKERS` 同步的问题；新增任务队列并发 in-place 同步机制（空闲即时生效、繁忙延后），并在设置保存反馈与运行日志中明确输出 `profile/max/effective`，减少“参数未生效”误解。
- 🔐 **退出登录立即失效现有会话** — `POST /api/v1/auth/logout` 现在会轮换 session secret，避免旧 cookie 在退出后仍可继续访问受保护接口；同浏览器标签页和并发页面会被同步登出。认证开启时，该接口也不再属于匿名白名单，未登录请求会返回 `401`，避免匿名请求触发全局 session 失效。
- 🧮 **Tushare 板块/筹码调用限流与跨日缓存修复** — 新增的 `trade_cal`、行业板块排行、筹码分布链路统一接入 `_check_rate_limit()`；交易日历缓存改为按自然日刷新，避免服务跨天运行后继续沿用旧交易日判断取数日期。
- 💼 **持仓超售拦截与错误流水恢复**（#718）— `POST /api/v1/portfolio/trades` 现在会在写入前校验可卖数量，超售返回 `409 portfolio_oversell`；持仓页新增交易 / 资金流水 / 公司行为删除能力，删除后会同步失效仓位缓存与未来快照，便于从错误流水中直接恢复。
- 📧 **邮件中文发件人名编码**（#708）— 邮件通知现在会对包含中文的 `EMAIL_SENDER_NAME` 自动做 RFC 2047 编码，并在异常路径补充 SMTP 连接清理，修复 GitHub Actions / QQ SMTP 下 `'ascii' codec can't encode characters` 导致的发送失败。
- 🐛 **港股 Agent 实时行情去重与快速路由** — 统一 `HK01810` / `1810.HK` / `01810` 等港股代码归一规则；港股实时行情改为直接走单次 `akshare_hk` 路径，避免按 A 股 source priority 重复触发同一失败接口；Agent 运行期对显式 `retriable=false` 的工具失败增加短路缓存，减少同轮分析中的重复失败调用。
- 📰 **新闻时效硬过滤与策略分窗**（#697）— 新增 `NEWS_STRATEGY_PROFILE`（`ultra_short/short/medium/long`）并与 `NEWS_MAX_AGE_DAYS` 统一计算有效窗口；搜索结果在返回后执行发布时间硬过滤（时间未知剔除、超窗剔除、未来仅容忍 1 天），并在历史 fallback 链路追加相同约束，避免旧闻再次进入“最新动态/风险警报”。

### 文档

- ☁️ **新增云服务器 Web 界面部署与访问教程**（Fixes #686）— 补充从云端部署到外部访问的落地说明，降低远程自托管门槛。
- 🌍 **补齐英文文档索引与协作文档** — 新增英文文档索引、贡献指南、Bot 命令文档，并补充中英双语 issue / PR 模板，方便中英文协作与外部贡献者理解项目入口。
- 🏷️ **本地化 README 补充 Trendshift badge** — 在多语言 README 中同步补上新版能力入口标识，减少中英文说明面不一致。

## [3.7.0] - 2026-03-15

### 新功能

- 💼 **持仓管理 P0 全功能上线**（#677，对应 Issue #627）
  - **核心账本与快照闭环**：新增账户、交易、现金流水、企业行为、持仓缓存、每日快照等核心数据模型与 API 端点；支持 FIFO / AVG 双成本法回放；同日事件顺序固定为 `现金 → 企业行为 → 交易`；持仓快照写入采用原子事务。
  - **券商 CSV 导入**：支持华泰 / 中信 / 招商首批适配，含列名别名兼容；两阶段接口（解析预览 + 确认提交）；`trade_uid` 优先、key-field hash 兜底的幂等去重；前导零股票代码完整保留。
  - **组合风险报告**：集中度风险（Top Positions + A 股板块口径）、历史回撤监控（支持回填缺失快照）、止损接近预警；多币种统一换算 CNY 口径；汲取失败时回退最近成功汇率并标记 stale。
  - **Web 持仓页**（`/portfolio`）：组合总览、持仓明细、集中度饼图、风险摘要、全组合 / 单账户切换；手工录入交易 / 资金流水 / 企业行为；内嵌账户创建入口；CSV 解析 + 提交闭环与券商选择器。
  - **Agent 持仓工具**：新增 `get_portfolio_snapshot` 数据工具，默认紧凑摘要，可选持仓明细与风险数据。
  - **事件查询 API**：新增 `GET /portfolio/trades`、`GET /portfolio/cash-ledger`、`GET /portfolio/corporate-actions`，支持日期过滤与分页。
  - **可扩展 Parser Registry**：应用级共享注册，支持运行时注册新券商；新增 `GET /portfolio/imports/csv/brokers` 发现接口。

- 🎨 **前端设计系统与原子组件库**（#662）
  - 引入渐进式双主题架构（HSL 变量化设计令牌），清理历史 Legacy CSS；重构 Button / Card / Badge / Collapsible / Input / Select 等 20+ 核心组件；新增 `clsx` + `tailwind-merge` 类名合并工具；提升历史记录、LLM 配置等页面可读性。

- ⚡ **分析 API 异步契约与启动优化**（#656）
  - 规范 `POST /api/v1/analysis/analyze` 异步请求的返回契约；优化服务启动辅助逻辑；修复前端报告类型联合定义与后端响应对齐问题。

### 修复

- 🔔 **Discord 环境变量向后兼容**（#659）：运行时新增 `DISCORD_CHANNEL_ID` → `DISCORD_MAIN_CHANNEL_ID` 的 fallback 读取；历史配置用户无需修改即可恢复 Discord Bot 通知；全部相关文档与 `.env.example` 对齐。
- 🔧 **GitHub Actions Node 24 升级**（#665）：将所有 GitHub 官方 actions 升级至 Node 24 兼容版本，消除 CI 日志中的 Node.js 20 deprecation warning（影响 2026-06-02 强制升级窗口）。
- 📅 **持仓页默认日期本地化**：手工录入表单默认日期改用本地时间（`getFullYear/Month/Date`），修复 UTC-N 时区用户在当天晚间出现日期偏移的问题。
- 🔁 **CSV 导入去重逻辑加固**：dedup hash 纳入行序号作为区分因子，确保同字段合法分笔成交不被误折叠；同时在 `trade_uid` 存在时也持久化 hash，防止混合来源重复写入。

### 变更

- `POST /api/v1/portfolio/trades` 在同账户内 `trade_uid` 冲突时返回 `409`。
- 持仓风险响应新增 `sector_concentration` 字段（增量扩展），原有 `concentration` 字段保持不变。
- 分析 API `analyze` 接口异步行为契约文档化；前端报告类型联合更新。

### 测试

- 新增持仓核心服务测试（FIFO / AVG 部分卖出、同日事件顺序、重复 `trade_uid` 返回 409、快照 API 契约）。
- 新增 CSV 导入幂等性、合法分笔成交不误去重、去重边界、风险阈值边界、汇率降级行为测试。
- 新增 Agent `get_portfolio_snapshot` 工具调用测试。
- 新增分析 API 异步契约回归测试。

## [3.6.0] - 2026-03-14

### Added
- 📊 **Web UI Design System** — implemented dual-theme architecture and terminal-inspired atomic UI components
- 📊 **UI Components Refactoring** — integrated `clsx` and `tailwind-merge` for robust class composition across Web UI

- 🗑️ **History batch deletion** — Web UI now supports multi-selection and batch deletion of analysis history; added `POST /api/v1/history/batch-delete` endpoint and `ConfirmDialog` component.
- 🔐 **Auth settings API** — new `POST /api/v1/auth/settings` endpoint to enable or disable Web authentication at runtime and set the initial admin password when needed
- openclaw Skill 集成指南 — 新增 [docs/openclaw-skill-integration.md](openclaw-skill-integration.md)，说明如何通过 openclaw Skill 调用 DSA API
- ⚙️ **LLM channel protocol/test UX** — `.env` and Web settings now share the same channel shape (`LLM_CHANNELS` + `LLM_<NAME>_PROTOCOL/BASE_URL/API_KEY/MODELS/ENABLED`); settings page adds per-channel connection testing, primary/fallback/vision model selection, and protocol-aware model prefixing
- 🤖 **Agent architecture Phase 0+1** — shared protocols (`AgentContext`, `AgentOpinion`, `StageResult`), extracted `run_agent_loop()` runner, `AGENT_ARCH` switch (`single`/`multi`), config registry entries
- 🔍 **Bot NL routing** — two-layer natural-language routing: cheap regex pre-filter (stock codes + finance keywords) → lightweight LLM intent parsing; controlled by `AGENT_NL_ROUTING=true`; supports multi-stock and strategy extraction
- 💬 **`/ask` multi-stock analysis** — comma or `vs` separated codes (max 5), parallel thread execution with 150s timeout (preserves partial results), Markdown comparison summary table at top
- 📋 **`/history` command** — per-user session isolation via `{platform}_{user_id}:{scope}` format (colon delimiter prevents prefix collision); lists both `/chat` and `/ask` sessions; view detail or clear
- 📊 **`/strategies` command** — lists available strategy YAML files grouped by category (趋势/形态/反转/框架) with ✅/⬜ activation status
- 🔧 **Backtest summary tools** — `get_strategy_backtest_summary` and `get_stock_backtest_summary` registered as read-only Agent tools
- ⚙️ **Agent auto-detection** — `is_agent_available()` auto-detects from `LITELLM_MODEL`; explicit `AGENT_MODE=true/false` takes full precedence
- 🏗️ **Multi-Agent orchestrator (Phase 2)** — `AgentOrchestrator` with 4 modes (`quick`/`standard`/`full`/`strategy`); drop-in replacement for `AgentExecutor` via `AGENT_ARCH=multi`; `BaseAgent` ABC with tool subset filtering, cached data injection, and structured `AgentOpinion` output
- 🧩 **Specialised agents (Phase 2-4)** — `TechnicalAgent` (8 tools, trend/MA/MACD/volume/pattern analysis), `IntelAgent` (news & sentiment, risk flag propagation), `DecisionAgent` (synthesis into Decision Dashboard JSON), `RiskAgent` (7 risk categories, two-level severity with soft/hard override)
- 📈 **Strategy system (Phase 3)** — `StrategyAgent` (per-strategy evaluation from YAML skills), `StrategyRouter` (rule-based regime detection → strategy selection), `StrategyAggregator` (weighted consensus with backtest performance factor)
- 🔬 **Deep Research agent (Phase 5)** — `ResearchAgent` with 3-phase approach (decompose → research sub-questions → synthesise report); token budget tracking; new `/research` bot command with aliases (`/深研`, `/deepsearch`)
- 🧠 **Memory & calibration (Phase 6)** — `AgentMemory` with prediction accuracy tracking, confidence calibration (activates after minimum sample threshold), strategy auto-weighting based on historical win rate
- 📊 **Portfolio Agent (Phase 7)** — `PortfolioAgent` for multi-stock portfolio analysis (position sizing, sector concentration, correlation risk, cross-market linkage, rebalance suggestions)
- 🔔 **Event-driven alerts (Phase 7)** — `EventMonitor` with `PriceAlert`, `VolumeAlert`, `SentimentAlert` rules; async checking, callback notifications, serializable persistence
- ⚙️ **New config entries** — `AGENT_ORCHESTRATOR_MODE`, `AGENT_RISK_OVERRIDE`, `AGENT_DEEP_RESEARCH_BUDGET`, `AGENT_MEMORY_ENABLED`, `AGENT_STRATEGY_AUTOWEIGHT`, `AGENT_STRATEGY_ROUTING` — all registered in `config.py` + `config_registry.py` (WebUI-configurable)

### Changed
- 🔐 **Auth password state semantics** — stored password existence is now tracked independently from auth enablement; when auth is disabled, `/api/v1/auth/status` returns `passwordSet=false` while preserving the saved password for future re-enable
- 🔐 **Auth settings re-enable hardening** — re-enabling auth with a stored password now requires `currentPassword`, and failed session creation rolls back the auth toggle to avoid lockout
- ♻️ **AgentExecutor refactored** — `_run_loop` delegates to shared `runner.run_agent_loop()`; removed duplicated serialization/parsing/thinking-label code
- ♻️ **Unified agent switch** — Bot, API, and Pipeline all use `config.is_agent_available()` instead of divergent `config.agent_mode` checks
- 📖 **README.md** — expanded Bot commands section (ask/chat/strategies/history), added NL routing note, updated agent mode description
- 📖 **.env.example** — added `AGENT_ARCH` and `AGENT_NL_ROUTING` configuration documentation
- 🔌 **Analysis API async contract** — `POST /api/v1/analysis/analyze` now documents distinct async `202` payloads for single-stock vs batch requests, and `report_type=full` is treated consistently with the existing full-report behavior

### Fixed
- 🐛 **Analysis API blank-code guardrails** — `POST /api/v1/analysis/analyze` now drops whitespace-only entries before batch enqueue and returns `400` when no valid stock code remains
- 🐛 **Bare `/api` SPA fallback** — unknown API paths now return JSON `404` consistently for both `/api/...` and the exact `/api` path
- 🎮 **Discord channel env compatibility** — runtime now accepts legacy `DISCORD_CHANNEL_ID` as a fallback for `DISCORD_MAIN_CHANNEL_ID`, and the docs/examples now use the same variable name as the actual workflow/config implementation
- 🐛 **Session secret rotation on Windows** — use atomic replace so auth toggles invalidate existing sessions even when `.session_secret` already exists
- 🐛 **Auth toggle atomicity** — persist `ADMIN_AUTH_ENABLED` before rotating session secret; on rotation failure, roll back to the previous auth state
- 🔧 **LLM runtime selection guardrails** — YAML 模式下渠道编辑器不再覆盖 `LITELLM_MODEL` / fallback / Vision；系统配置校验补上全部渠道禁用后的运行时来源检查，并修复 `vertexai/...` 这类协议别名模型被重复加前缀的问题
- 🐛 **Multi-stock `/ask` follow-up regressions** — portfolio overlay now shares the same timeout budget as the per-stock phase and is skipped on timeout instead of blocking the bot reply; `/history` now stores the readable per-stock summary instead of raw dashboard JSON; condensed multi-stock output now renders numeric `sniper_points` values
- 🐛 **Decision dashboard enum compatibility** — multi-agent `DecisionAgent` now keeps `decision_type` within the legacy `buy|hold|sell` contract and normalizes stray `strong_*` outputs before risk override, pipeline conversion, and downstream统计/通知汇总
- 🛟 **Multi-Agent partial-result fallback** — `IntelAgent` now caches parsed intel for downstream reuse, shared JSON parsing tolerates lightly malformed model output, and the orchestrator preserves/synthesizes a minimal dashboard on timeout or mid-pipeline parse failure instead of always collapsing to `50/观望/未知`
- 🐛 **Shared LiteLLM routing restored** — bot NL intent parsing and `ResearchAgent` planning/synthesis now reuse the same LiteLLM adapter / Router / fallback / `api_base` injection path as the main Agent flow, so `LLM_CHANNELS` / `LITELLM_CONFIG` / OpenAI-compatible deployments behave consistently
- 🐛 **Bot chat session backward compatibility** — `/chat` now keeps using the legacy `{platform}_{user_id}` session id when old history already exists, and `/history` can still list / view / clear those pre-migration sessions alongside the new `{platform}_{user_id}:chat` format
- 🐛 **EventMonitor unsupported rule rejection** — config validation/runtime loading now reject or skip alert types the monitor cannot actually evaluate yet, so schedule mode no longer silently accepts permanent no-op rules
- 🐛 **P0 基本面聚合稳定性修复** (#614) — 修复 `get_stock_info` 板块语义回归（新增 `belong_boards` 并保留 `boards` 兼容别名）、引入基本面上下文精简返回以控制 token、为基本面缓存增加最大条目淘汰，并补齐 ETF 总体状态聚合与 NaN 板块字段过滤，保证 fail-open 与最小入侵。
- 🔧 **GitHub Actions 搜索引擎环境变量补充** — 工作流新增 `MINIMAX_API_KEYS`、`BRAVE_API_KEYS`、`SEARXNG_BASE_URLS` 环境变量映射，使 GitHub Actions 用户可配置 MiniMax、Brave、SearXNG 搜索服务（此前 v3.5.0 已添加 provider 实现但缺少工作流配置）
- 🤖 **Multi-Agent runtime consistency** — `AGENT_MAX_STEPS` now propagates to each orchestrated sub-agent; added cooperative `AGENT_ORCHESTRATOR_TIMEOUT_S` budget to stop overlong pipelines before they cascade further
- 🔌 **Multi-Agent feature wiring** — `AGENT_RISK_OVERRIDE` now actively downgrades final dashboards on hard risk findings; `AGENT_MEMORY_ENABLED` now injects recent analysis memory + confidence calibration into specialised agents; multi-stock `/ask` now runs `PortfolioAgent` to add portfolio-level allocation and concentration guidance
- 🔔 **EventMonitor runtime wiring** — schedule mode can now load alert rules from `AGENT_EVENT_ALERT_RULES_JSON`, poll them at `AGENT_EVENT_MONITOR_INTERVAL_MINUTES`, and send triggered alerts through the existing notification service
- 🛠️ **Follow-up stability fixes** — multi-stock `/ask` now falls back to usable text output when dashboard JSON parsing fails; EventMonitor skips semantically invalid rules instead of aborting schedule startup; background alert polling now runs independently of the main scheduled analysis loop
- 🧪 **Multi-Agent regression coverage** — added orchestrator execution tests for `run()`, `chat()`, critical-stage failure, graceful degradation, and timeout handling
- 🧹 **PortfolioAgent cleanup** — `post_process()` now reuses shared JSON parsing and removed stale unused imports
- 🚦 **Bot async dispatch** — `CommandDispatcher` now exposes `dispatch_async()`; NL intent parsing and default command execution are offloaded from the event loop, DingTalk stream awaits async handlers directly, and Feishu stream processing is moved off the SDK callback thread
- 🌐 **Async webhook handler** — new `handle_webhook_async()` function in `bot/handler.py` for use from async contexts (e.g. FastAPI); calls `dispatch_async()` directly without thread bridging
- 🧵 **Feishu stream ThreadPoolExecutor** — replaced unbounded per-message `Thread` spawning with a capped `ThreadPoolExecutor(max_workers=8)` to prevent thread explosion under message bursts
- 🔒 **EventMonitor safety** — `_check_volume()` now safely handles `get_daily_data` returning `None` (no tuple-unpacking crash); `on_trigger` callbacks support both sync and async callables via `asyncio.to_thread`/`await`
- 🧹 **ResearchAgent dedup** — `_filtered_registry()` now delegates to `BaseAgent._filtered_registry()` instead of duplicating the filtering logic
- 🧹 **Bot trailing whitespace cleanup** — removed W291/W293 whitespace issues across `bot/handler.py`, `bot/dispatcher.py`, `bot/commands/base.py`, `bot/platforms/feishu_stream.py`, `bot/platforms/dingtalk_stream.py`
- 🐛 **Dispatcher `_parse_intent_via_llm` safety** — replaced fragile `'raw' in dir()` with `'raw' in locals()` for undefined-variable guard in `JSONDecodeError` handler
- 🐛 **筹码结构 LLM 未填写时兜底补全** (#589) — DeepSeek 等模型未正确填写 `chip_structure` 时，自动用数据源已获取的筹码数据补全，保证各模型展示一致；普通分析与 Agent 模式均生效
- 🐛 **历史报告狙击点位显示原始文本** (#452) — 历史详情页现优先展示 `raw_result.dashboard.battle_plan.sniper_points` 中的原始字符串，避免 `analysis_history` 数值列把区间、说明文字或复杂点位压缩成单个数字；保留原有数值列作为回退
- 🐛 **Session prefix collision** — user ID `123` could see sessions of user `1234` via `startswith`; fixed with colon delimiter in session_id format
- 🐛 **NL pre-filter false positives** — `re.IGNORECASE` caused `[A-Z]{2,5}` to match common English words like "hello"; removed global flag, use inline `(?i:...)` only for English finance keywords
- 🐛 **Dotted ticker in strategy args** — `_get_strategy_args()` didn't recognize `BRK.B` as a stock code, leaving it in strategy text; now accepts `TICKER.CLASS` format
- ⏱️ **efinance 长调用挂起修复** (#660) — 为所有 efinance API 调用引入 `_ef_call_with_timeout()` 包装（默认 30 秒，可通过 `EFINANCE_CALL_TIMEOUT` 配置）；使用 `executor.shutdown(wait=False)` 确保超时后不再阻塞主线程，彻底消除 81 分钟挂起问题
- 🛡️ **类型安全内容完整性检查** (#660) — `check_content_integrity()` 现在将非字符串类型的 `operation_advice` / `analysis_summary` 视为缺失字段，避免下游 `get_emoji()` 因 `dict.strip()` 崩溃
- 📄 **报告保存与通知解耦** (#660) — `_save_local_report()` 不再依赖 `send_notification` 标志触发，`--no-notify` 模式下本地报告照常保存
- 🔄 **operation_advice 字典归一化** (#660) — Pipeline 和 BacktestEngine 现在将 LLM 返回的 `dict` 格式 `operation_advice` 通过 `decision_type`（不区分大小写）映射为标准字符串，防止因模型输出格式变化导致崩溃
- 🛡️ **runner.py usage None 防护** (#660) — `response.usage` 为 `None` 时不再抛出 `AttributeError`，回退为 0 token 计数
- 📋 **orchestrator 静默失败改为日志警告** (#660) — `IntelAgent` / `RiskAgent` 阶段失败现在记录 `WARNING` 而非静默跳过，便于诊断

### Notes
- ⚠️ **Multi-worker auth toggles** — runtime auth updates are process-local; multi-worker deployments must restart/roll workers to keep auth state consistent

## [3.5.0] - 2026-03-12

### Added
- 📊 **Web UI full report drawer** (Fixes #214) — history page adds "Full Report" button to display the complete Markdown analysis report in a side drawer; new `GET /api/v1/history/{record_id}/markdown` endpoint
- 📊 **LLM cost tracking** — all LLM calls (analysis, agent, market review) recorded in `llm_usage` table; new `GET /api/v1/usage/summary?period=today|month|all` endpoint returns aggregated token usage by call type and model
- 🔍 **SearXNG search provider** (Fixes #550) — quota-free self-hosted search fallback; priority: Bocha > Tavily > Brave > SerpAPI > MiniMax > SearXNG
- 🔍 **MiniMax web search provider** — `MiniMaxSearchProvider` with circuit breaker (3 failures → 300s cooldown) and dual time-filtering; configured via `MINIMAX_API_KEYS`
- 🤖 **Agent models discovery API** — `GET /api/v1/agent/models` returns available model deployments (primary/fallback/source/api_base) for Web UI model selector
- 🤖 **Agent chat export & send** (#495) — export conversation to .md file; send to configured notification channels; new `POST /api/v1/agent/chat/send`
- 🤖 **Agent background execution** (#495) — analysis continues when switching pages; badge notification on completion; auto-cancel in-progress stream on session switch
- 📝 **Report Engine P0** — Pydantic schema validation for LLM JSON; Jinja2 templates (markdown/wechat/brief) with legacy fallback; content integrity checks with retry; brief mode (`REPORT_TYPE=brief`); history signal comparison
- 📦 **Smart import** — multi-source import from image/CSV/Excel/clipboard; Vision LLM extracts code+name+confidence; name→code resolver (local map + pinyin + AkShare); confidence-tiered confirmation
- ⚙️ **GitHub Actions LiteLLM config** — workflow supports `LITELLM_CONFIG`/`LITELLM_CONFIG_YAML` for flexible AI provider configuration
- ⚙️ **Config engine refactor & system API** (#602) — unified config registry, validation and API exposure
- 📖 **LLM configuration guide** — new `docs/LLM_CONFIG_GUIDE.md` covering 3-tier config, quick start, Vision/Agent/troubleshooting

### Fixed
- 🐛 **analyze_trend always reports No historical data** (#600) — now fetches from DB/DataFetcher instead of broken `get_analysis_context`
- 🐛 **Chip structure fallback when LLM omits it** (#589) — auto-fills from data source chip data for consistent display across models
- 🐛 **History sniper points show raw text** (#452) — prioritizes original strings over compressed numeric values
- 🐛 **GitHub Actions ENABLE_CHIP_DISTRIBUTION configurable** (#617) — no longer hardcoded, supports vars/secrets override
- 🐛 **`.env` save preserves comments and blank lines** — Web settings no longer destroys `.env` formatting
- 🐛 **Agent model discovery fixes** — legacy mode includes LiteLLM-native providers; source detection aligned with runtime; fallback deployments no longer expanded per-key
- 🐛 **Stooq US stock previous close semantics** — no longer misuses open price as previous close
- 🐛 **Stock name prefetch regression** — prioritizes local `STOCK_NAME_MAP` before remote queries
- 🐛 **AkShare limit-up/down calculation** (#555) — fixed market analysis statistics
- 🐛 **AkShare Tencent source field index & ETF quote mapping** (#579)
- 🐛 **Pytdx stock name cache pagination** (#573) — prevents cache overflow
- 🐛 **PushPlus oversized report chunking** (#489) — auto-segments long content
- 🐛 **Agent chat cancel & switch** (#495) — cancel no longer misreports as failure; fast switch no longer overwrites stream state
- 🐛 **MiniMax search status in `/status` command** (#587)
- 🐛 **config_registry duplicate BOCHA_API_KEYS** — removed duplicate dict entry that silently overwrote config

### Changed
- 🔎 **Fetcher failure observability** — logs record start/success/failure with elapsed time, failover transitions; Efinance/Akshare include upstream endpoint and classified failure categories
- ♻️ **Data source resilience & cleanup** (#602) — fallback chain optimization
- ♻️ **Image extract API response extension** — new `items` field (code/name/confidence); `codes` preserved for backward compatibility
- ♻️ **Import parse error messages** — specific failure reasons for Excel/CSV; improved logging with file type and size

### Docs
- 📖 LLM config guide refactored for clarity (#583)
- 📖 `image-extract-prompt.md` with full prompt documentation
- 📖 AkShare fallback cache TTL documentation
## [3.4.10] - 2026-03-07

### Fixed
- 🐛 **EfinanceFetcher ETF OHLCV data** (#541, #527) — switch `_fetch_etf_data` from `ef.fund.get_quote_history` (NAV-only, no OHLCV, no `beg`/`end` params) to `ef.stock.get_quote_history`; ETFs now return proper open/high/low/close/volume/amount instead of zeros; remove obsolete NAV column mappings from `_normalize_data`
- 🐛 **tiktoken 0.12.0 `Unknown encoding cl100k_base`** (#537) — pin `tiktoken>=0.8.0,<0.12.0` in requirements.txt to avoid plugin-registration regression introduced in 0.12.0
- 🐛 **Web UI API error classification** (#540) — frontend no longer treats every HTTP 400 as the same "server/network" failure; now distinguishes Agent disabled / missing params / model-tool incompatibility / upstream LLM errors / local connection failures
- 🐛 **北交所代码识别失败** (#491, #533) — 8/4/92 开头的 6 位代码现正确识别为北交所；Tushare/Akshare/Yfinance 等数据源支持 .BJ 或 bj 前缀；Baostock/Pytdx 对北交所代码显式切换数据源；避免误判上海 B 股 900xxx
- 🐛 **狙击点位解析错误** (#488, #532) — 理想买入/二次买入等字段在无「元」字时误提取括号内技术指标数字；现先截去第一个括号后内容再提取

### Added
- **Markdown-to-image for dashboard report** (#455, #535) — 个股日报汇总支持 markdown 转图片推送（Telegram、WeChat、Custom、Email），与大盘复盘行为一致
- **markdown-to-file engine** (#455) — `MD2IMG_ENGINE=markdown-to-file` 可选，对 emoji 支持更好，需 `npm i -g markdown-to-file`
- **PREFETCH_REALTIME_QUOTES** (#455) — 设为 `false` 可禁用实时行情预取，避免 efinance/akshare_em 全市场拉取
- **Stock name prefetch** (#455) — 分析前预取股票名称，减少报告中「股票xxxxx」占位符
- 📊 **分析报告模型标记** (#528, #534) — 在分析报告 meta、报告末尾、推送内容中展示 `model_used`（完整 LLM 模型名）；Agent 多轮调用时记录并展示每轮实际使用的模型（支持 fallback 切换）

### Changed
- **Enhanced markdown-to-image failure warning** (#455) — 转图失败时提示具体依赖（wkhtmltopdf 或 m2f）
- **WeChat-only image routing optimization** (#455) — 仅配置企业微信图片时，不再对完整报告做冗余转图，避免误导性失败日志
- **Stock name prefetch lightweight mode** (#455) — 名称预取阶段跳过 realtime quote 查询，减少额外网络开销

## [3.4.9] - 2026-03-06

### Added
- 🧠 **Structured config validation** — `ConfigIssue` dataclass and `validate_structured()` with severity-aware logging; `CONFIG_VALIDATE_MODE=strict` aborts startup on errors
- 🖼️ **Vision model config** — `VISION_MODEL` and `VISION_PROVIDER_PRIORITY` for image stock extraction; provider fallback (Gemini → Anthropic → OpenAI → DeepSeek) when primary fails
- 🚀 **CLI init wizard** — `python -m dsa init` 3-step interactive bootstrap (model → data source → notification), 9 provider presets, incremental merge by default
- 🔧 **Multi-channel LLM support** with visual channel editor (#494)

### Changed
- ♻️ **Vision extraction** — migrated from gemini-3 hardcode to `litellm.completion()` with configurable model and provider fallback; `OPENAI_VISION_MODEL` deprecated in favor of `VISION_MODEL`
- ♻️ **Market analyzer** — uses `Analyzer.generate_text()` for LLM calls; fixes bypass and Anthropic `AttributeError` when using non-Router path
- ♻️ **Config validation refinements** — test_env output format syncs with `validate_structured` (severity-aware ✓/✗/⚠/·); Vision key warning when `VISION_MODEL` set but no provider API key; market_analyzer test covers `generate_market_review` fallback when `generate_text` returns None
- ⚙️ **Auto-tag workflow defaults to NO tag** — only tags when commit message explicitly contains `#patch`, `#minor`, or `#major`
- ♻️ **Formatter and notification refactor** (#516)

### Fixed
- 🐛 **STOCK_LIST not refreshed on scheduled runs** — `.env` or WebUI changes to `STOCK_LIST` now hot-reload before each scheduled analysis (#529)
- 🐛 **WebUI fails to load with MIME type error** — SPA fallback route now resolves correct `Content-Type` for JS/CSS files (#520)
- 🐛 **AstrBot sender docstring misplaced** — `import time` placed before docstring in `_send_astrbot`, causing it to become dead code
- 🐛 **Telegram Markdown link escaping** — `_convert_to_telegram_markdown` escaped `[]()` characters, breaking all Markdown links in reports
- 🐛 **Duplicate `discord_bot_status` field** in Config dataclass — second declaration silently shadowed the first
- 🧹 **Unused imports** — removed `shutil`/`subprocess` from `main.py`
- 🔧 **Config validation and Vision key check** (#525)

### Docs
- 📝 Clarified GitHub Actions non-trading-day manual run controls (`TRADING_DAY_CHECK_ENABLED` + `force_run`) for Issue #461 / PR #466

## [3.4.8] - 2026-03-02

### Fixed
- 🐛 **Desktop exe crashes on startup with `FileNotFoundError`** — PyInstaller build was missing litellm's JSON data files (e.g. `model_prices_and_context_window_backup.json`). Added `--collect-data litellm` to both Windows and macOS build scripts so the files are correctly bundled in the executable.

### CI
- 🔧 Cache Electron binaries on macOS CI runners to prevent intermittent EOF download failures when fetching `electron-vX.Y.Z-darwin-*.zip` from GitHub CDN
- 🔧 Fix macOS DMG `hdiutil Resource busy` error during desktop packaging

### Docs
- 📝 Clarify non-trading-day manual run controls for GitHub Actions (`TRADING_DAY_CHECK_ENABLED` + `force_run`) (#474)

## [3.4.7] - 2026-02-28

### Added
- 🧠 **CN/US Market Strategy Blueprint System** (#395) — market review prompt injects region-specific strategy blueprints with position sizing and risk trigger recommendations

### Fixed
- 🐛 **`TRADING_DAY_CHECK_ENABLED` env var and `--force-run` for GitHub Actions** (#466)
- 🐛 **Agent pipeline preserved resolved stock names** (#464) — placeholder names no longer leak into reports
- 🐛 **Code cleanup** (#462, Fixes #422)
- 🐛 **WebUI auto-build on startup** (#460)
- 🐛 **ARCH_ARGS unbound variable** (#458)
- 🐛 **Time zone inconsistency & right panel flash** (#439)

### Docs
- 📝 Clarify potential ambiguities in code (#343)
- 📝 ENABLE_EASTMONEY_PATCH guidance for Issue #453 (#456)

## [3.4.0] - 2026-02-27

### Added
- 📡 **LiteLLM Direct Integration + Multi API Key Support** (#454, Fixes #421 #428)
  - Removed native SDKs (google-generativeai, google-genai, anthropic); unified through `litellm>=1.80.10`
  - New config: `LITELLM_MODEL`, `LITELLM_FALLBACK_MODELS`, `GEMINI_API_KEYS`, `ANTHROPIC_API_KEYS`, `OPENAI_API_KEYS`
  - Multi-key auto-builds LiteLLM Router (simple-shuffle) with 429 cooldown
  - **Breaking**: `.env` `GEMINI_MODEL` (no prefix) only for fallback; explicit config must include provider prefix

### Changed
- ♻️ **Notification Refactoring** (#435) — extracted 10 sender classes into `src/notification_sender/`

### Fixed
- 🐛 LLM NoneType crash, history API 422, sniper points extraction
- 🐛 Auto-build frontend on WebUI startup — `WEBUI_AUTO_BUILD` env var (default `true`)
- 🐛 Docker explicit project name (#448)
- 🐛 Bocha search SSL retry (#445, #446) — transient errors retry up to 3 times
- 🐛 Gemini google-genai SDK migration (Fixes #440, #444)
- 🐛 Mobile home page scrolling (Fixes #419, #433)
- 🐛 History list scroll reset (#431)
- 🐛 Settings save button false positive (fixes #417, #430)

## [3.3.22] - 2026-02-26

### Added
- 💬 **Chat History Persistence** (Fixes #400, #414) — `/chat` page survives refresh, sidebar session list
- 🎨 Project VI Assets — logo icon set, PSD, vector, banner (#425)
- 🚀 Desktop CI Auto-Release (#426) — Windows + macOS parallel builds

### Fixed
- 🐛 Agent Reasoning 400 & LiteLLM Proxy (fixes #409, #427)
- 🐛 Discord chunked sending (#413) — `DISCORD_MAX_WORDS` config
- 🐛 yfinance shared DataFrame (#412)
- 🐛 sniper_points parsing (#408)
- 🐛 Agent framework category missing (#406)
- 🐛 Date inconsistency & query id (fixes #322, #363)

## [3.3.12] - 2026-02-24

### Added
- 📈 **Intraday Realtime Technical Indicators** (Issue #234, #397) — MA calculated from realtime price, config: `ENABLE_REALTIME_TECHNICAL_INDICATORS`
- 🤖 **Agent Strategy Chat** (#367) — full ReAct pipeline, 11 YAML strategies, SSE streaming, multi-turn chat
- 📢 PushPlus Group Push — `PUSHPLUS_TOPIC` (#402)
- 📅 Trading Day Check (Issue #373, #375) — `TRADING_DAY_CHECK_ENABLED`, `--force-run`

### Fixed
- 🐛 DeepSeek reasoning mode (Issue #379, #386)
- 🐛 Agent news intel persistence (Fixes #396, #405)
- 🐛 Bare except clauses replaced with `except Exception` (#398)
- 🐛 UUID fallback for HTTP non-secure context (fixes #377, #381)
- 🐛 Docker DNS resolution (Fixes #372, #374)
- 🐛 Agent session/strategy bugs — multiple follow-up fixes for #367
- 🐛 yfinance parallel download data filtering

### Changed
- Market review strategy consistency — unified cn/us template
- Agent test assertions updated (`6 -> 11`)


## [3.2.11] - 2026-02-23

### 修复（#patch）
- 🐛 **StockTrendAnalyzer 从未执行** (Issue #357)
  - 根因：`get_analysis_context` 仅返回 2 天数据且无 `raw_data`，pipeline 中 `raw_data in context` 始终为 False
  - 修复：Step 3 直接调用 `get_data_range` 获取 90 日历天（约 60 交易日）历史数据用于趋势分析
  - 改善：趋势分析失败时用 `logger.warning(..., exc_info=True)` 记录完整 traceback

## [3.2.10] - 2026-02-22

### 新增
- ⚙️ 支持 `RUN_IMMEDIATELY` 配置项，设为 `true` 时定时任务触发后立即执行一次分析，无需等待首个定时点

### 修复
- 🐛 修复 Web UI 页面居中问题
- 🐛 修复 Settings 返回 500 错误

## [3.2.9] - 2026-02-22

### 修复
- 🐛 **ETF 分析仅关注指数走势**（Issue #274）
  - 美股/港股 ETF（如 VOO、QQQ）与 A 股 ETF 不再纳入基金公司层面风险（诉讼、声誉等）
  - 搜索维度：ETF/指数专用 risk_check、earnings、industry 查询，避免命中基金管理人新闻
  - AI 提示：指数型标的分析约束，`risk_alerts` 不得出现基金管理人公司经营风险

## [3.2.8] - 2026-02-21

### 修复
- 🐛 **BOT 与 WEB UI 股票代码大小写统一**（Issue #355）
  - BOT `/analyze` 与 WEB UI 触发分析的股票代码统一为大写（如 `aapl` → `AAPL`）
  - 新增 `canonical_stock_code()`，在 BOT、API、Config、CLI、task_queue 入口处规范化
  - 历史记录与任务去重逻辑可正确识别同一股票（大小写不再影响）

## [3.2.7] - 2026-02-20

### 新增
- 🔐 **Web 页面密码验证**（Issue #320, #349）
  - 支持 `ADMIN_AUTH_ENABLED=true` 启用 Web 登录保护
  - 首次访问在网页设置初始密码；支持「系统设置 > 修改密码」和 CLI `python -m src.auth reset_password` 重置

## [3.2.6] - 2026-02-20
### ⚠️ 破坏性变更（Breaking Changes）

- **历史记录 API 变更 (Issue #322)**
  - 路由变更：`GET /api/v1/history/{query_id}` → `GET /api/v1/history/{record_id}`
  - 参数变更：`query_id` (字符串) → `record_id` (整数)
  - 新闻接口变更：`GET /api/v1/history/{query_id}/news` → `GET /api/v1/history/{record_id}/news`
  - 原因：`query_id` 在批量分析时可能重复，无法唯一标识单条历史记录。改用数据库主键 `id` 确保唯一性
  - 影响范围：使用旧版历史详情 API 的所有客户端需同步更新

### 修复
- 修复美股（如 ADBE）技术指标矛盾：akshare 美股复权数据异常，统一美股历史数据源为 YFinance（Issue #311）
- 🐛 **历史记录查询和显示问题 (Issue #322)**
  - 修复历史记录列表查询中日期不一致问题：使用明天作为 endDate，确保包含今天全天的数据
  - 修复服务器 UI 报告选择问题：原因是多条记录共享同一 `query_id`，导致总是显示第一条。现改用 `analysis_history.id` 作为唯一标识
  - 历史详情、新闻接口及前端组件已全面适配 `record_id`
  - 新增后台轮询（每 30s）与页面可见性变更时静默刷新历史列表，确保 CLI 发起的分析完成后前端能及时同步，使用 `silent` 模式避免触发 loading 状态
- 🐛 **美股指数实时行情与日线数据** (Issue #273)
  - 修复 SPX、DJI、IXIC、NDX、VIX、RUT 等美股指数无法获取实时行情的问题
  - 新增 `us_index_mapping` 模块，将用户输入（如 SPX）映射为 Yahoo Finance 符号（如 ^GSPC）
  - 美股指数与美股股票日线数据直接路由至 YfinanceFetcher，避免遍历不支持的数据源
  - 消除重复的美股识别逻辑，统一使用 `is_us_stock_code()` 函数

### 优化
- 🎨 **首页输入栏与 Market Sentiment 布局对齐优化**
  - 股票代码输入框左缘与历史记录 glass-card 框左对齐
  - 分析按钮右缘与 Market Sentiment 外框右对齐
  - Market Sentiment 卡片向下拉伸填满格子，消除与 STRATEGY POINTS 之间的空隙
  - 窄屏时输入栏填满宽度，响应式对齐保持一致

## [3.2.5] - 2026-02-19

### 新增
- 🌍 **大盘复盘可选区域**（Issue #299）
  - 支持 `MARKET_REVIEW_REGION` 环境变量：`cn`（A股）、`us`（美股）、`both`（两者）
  - us 模式使用 SPX/纳斯达克/道指/VIX 等指数；both 模式可同时复盘 A 股与美股
  - 默认 `cn`，保持向后兼容

## [3.2.4] - 2026-02-18

### 修复
- 🐛 **统一美股数据源为 YFinance**（Issue #311）
  - akshare 美股复权数据异常，统一美股历史数据源为 YFinance
  - 修复 ADBE 等美股股票技术指标矛盾问题

## [3.2.3] - 2026-02-18

### 修复
- 🐛 **标普500实时数据缺失**（Issue #273）
  - 修复 SPX、DJI、IXIC、NDX、VIX、RUT 等美股指数无法获取实时行情的问题
  - 新增 `us_index_mapping` 模块，将用户输入（如 SPX）映射为 Yahoo Finance 符号（如 `^GSPC`）
  - 美股指数与美股股票日线数据直接路由至 YfinanceFetcher，避免遍历不支持的数据源

## [3.2.2] - 2026-02-16

### 新增
- 📊 **PE 指标支持**（Issue #296）
  - AI System Prompt 增加 PE 估值关注
- 📰 **新闻时效性筛查**（Issue #296）
  - `NEWS_MAX_AGE_DAYS`：新闻最大时效（天），默认 3，避免使用过时信息
- 📈 **强势趋势股乖离率放宽**（Issue #296）
  - `BIAS_THRESHOLD`：乖离率阈值（%），默认 5.0，可配置
  - 强势趋势股（多头排列且趋势强度 ≥70）自动放宽乖离率到 1.5 倍

## [3.2.1] - 2026-02-16

### 新增
- 🔧 **东财接口补丁可配置开关**
  - 支持 `EFINANCE_PATCH_ENABLED` 环境变量开关东财接口补丁（默认 `true`）
  - 补丁不可用时可降级关闭，避免影响主流程

## [3.2.0] - 2026-02-15

### 新增
- 🔒 **CI 门禁统一（P0）**
  - 新增 `scripts/ci_gate.sh` 作为后端门禁单一入口
  - 主 CI 改为 `backend-gate`、`docker-build`、`web-gate` 三段式
  - CI 触发改为所有 PR，避免 Required Checks 因路径过滤缺失而卡住合并
  - `web-gate` 支持前端路径变更按需触发
  - 新增 `network-smoke` 工作流承载非阻断网络场景回归
- 📦 **发布链路收敛（P0）**
  - `docker-publish` 调整为 tag 主触发，并增加发布前门禁校验
  - 手动发布增加 `release_tag` 输入与 semver/changelog 强校验
  - 发布前新增 Docker smoke（关键模块导入）
- 📝 **PR 模板升级（P0）**
  - 增加背景、范围、验证命令与结果、回滚方案、Issue 关联等必填项
- 🤖 **AI 审查覆盖增强（P0）**
  - `pr-review` 纳入 `.github/workflows/**` 范围
  - 新增 `AI_REVIEW_STRICT` 开关，可选将 AI 审查失败升级为阻断

## [3.1.13] - 2026-02-15

### 新增
- 📊 **仅分析结果摘要**（Issue #262）
  - 支持 `REPORT_SUMMARY_ONLY` 环境变量，设为 `true` 时只推送汇总，不含个股详情
  - 默认 `false`，多股时适合快速浏览

## [3.1.12] - 2026-02-15

### 新增
- 📧 **个股与大盘复盘合并推送**（Issue #190）
  - 支持 `MERGE_EMAIL_NOTIFICATION` 环境变量，设为 `true` 时将个股分析与大盘复盘合并为一次推送
  - 默认 `false`，减少邮件数量、降低被识别为垃圾邮件的风险

## [3.1.11] - 2026-02-15

### 新增
- 🤖 **Anthropic Claude API 支持**（Issue #257）
  - 支持 `ANTHROPIC_API_KEY`、`ANTHROPIC_MODEL`、`ANTHROPIC_TEMPERATURE`、`ANTHROPIC_MAX_TOKENS`
  - AI 分析优先级：Gemini > Anthropic > OpenAI
- 📷 **从图片识别股票代码**（Issue #257）
  - 上传自选股截图，通过 Vision LLM 自动提取股票代码
  - API: `POST /api/v1/stocks/extract-from-image`；支持 JPEG/PNG/WebP/GIF，最大 5MB
  - 支持 `OPENAI_VISION_MODEL` 单独配置图片识别模型
- ⚙️ **通达信数据源手动配置**（Issue #257）
  - 支持 `PYTDX_HOST`、`PYTDX_PORT` 或 `PYTDX_SERVERS` 配置自建通达信服务器

## [3.1.10] - 2026-02-15

### 新增
- ⚙️ **立即运行配置**（Issue #332）
  - 支持 `RUN_IMMEDIATELY` 环境变量，`true` 时定时任务启动后立即执行一次
- 🐛 修复 Docker 构建问题

## [3.1.9] - 2026-02-14

### 新增
- 🔌 **东财接口补丁机制**
  - 新增 `patch/eastmoney_patch.py` 修复 efinance 上游接口变更
  - 不影响其他数据源的正常运行

## [3.1.8] - 2026-02-14

### 新增
- 🔐 **Webhook 证书校验开关**（Issue #265）
  - 支持 `WEBHOOK_VERIFY_SSL` 环境变量，可关闭 HTTPS 证书校验以支持自签名证书
  - 默认保持校验，关闭存在 MITM 风险，仅建议在可信内网使用

## [3.1.7] - 2026-02-14

### 修复
- 🐛 修复包导入错误（package import error）

## [3.1.6] - 2026-02-13

### 修复
- 🐛 修复 `news_intel` 中 `query_id` 不一致问题

## [3.1.5] - 2026-02-13

### 新增
- 📷 **Markdown 转图片通知**（Issue #289）
  - 支持 `MARKDOWN_TO_IMAGE_CHANNELS` 配置，对 Telegram、企业微信、自定义 Webhook（Discord）、邮件发送图片格式报告
  - 邮件为内联附件，增强对不支持 HTML 客户端的兼容性
  - 需安装 `wkhtmltopdf` 和 `imgkit`

## [3.1.4] - 2026-02-12

### 新增
- 📧 **股票分组发往不同邮箱**（Issue #268）
  - 支持 `STOCK_GROUP_N` + `EMAIL_GROUP_N` 配置，不同股票组报告发送到对应邮箱
  - 大盘复盘发往所有配置的邮箱

## [3.1.3] - 2026-02-12

### 修复
- 🐛 修复 Docker 内运行时通过页面修改配置报错 `[Errno 16] Device or resource busy` 的问题

## [3.1.2] - 2026-02-11

### 修复
- 🐛 修复 Docker 一致性问题，解决关键批次处理与通知 Bug

## [3.1.1] - 2026-02-11

### 变更
- ♻️ `API_HOST` → `WEBUI_HOST`：Docker Compose 配置项统一

## [3.1.0] - 2026-02-11

### 新增
- 📊 **ETF 支持增强与代码规范化**
  - 统一各数据源 ETF 代码处理逻辑
  - 新增 `canonical_stock_code()` 统一代码格式，确保数据源路由正确

## [3.0.5] - 2026-02-08

### 修复
- 🐛 修复信号 emoji 与建议不一致的问题（复合建议如"卖出/观望"未正确映射）
- 🐛 修复 `*ST` 股票名在微信/Dashboard 中 markdown 转义问题
- 🐛 修复 `idx.amount` 为 None 时大盘复盘 TypeError
- 🐛 修复分析 API 返回 `report=None` 及 ReportStrategy 类型不一致问题
- 🐛 修复 Tushare 返回类型错误（dict → UnifiedRealtimeQuote）及 API 端点指向

### 新增
- 📊 大盘复盘报告注入结构化数据（涨跌统计、指数表格、板块排名）
- 🔍 搜索结果 TTL 缓存（500 条上限，FIFO 淘汰）
- 🔧 Tushare Token 存在时自动注入实时行情优先级
- 📰 新闻摘要截断长度 50→200 字

### 优化
- ⚡ 补充行情字段请求限制为最多 1 次，减少无效请求

## [3.0.4] - 2026-02-07

### 新增
- 📈 **回测引擎** (PR #269)
  - 新增基于历史分析记录的回测系统，支持收益率、胜率、最大回撤等指标评估
  - WebUI 集成回测结果展示

## [3.0.3] - 2026-02-07

### 修复
- 🐛 修复狙击点位数据解析错误问题 (PR #271)

## [3.0.2] - 2026-02-06

### 新增
- ✉️ 可配置邮件发送者名称 (PR #272)
- 🌐 外国股票支持英文关键词搜索

## [3.0.1] - 2026-02-06

### 修复
- 🐛 修复 ETF 实时行情获取、市场数据回退、企业微信消息分块问题
- 🔧 CI 流程简化

## [3.0.0] - 2026-02-06

### 移除
- 🗑️ **移除旧版 WebUI**
  - 删除基于 `http.server.ThreadingHTTPServer` 的旧版 WebUI（`web/` 包）
  - 旧版 WebUI 的功能已完全被 FastAPI（`api/`）+ React 前端替代
  - `--webui` / `--webui-only` 命令行参数标记为弃用，自动重定向到 `--serve` / `--serve-only`
  - `WEBUI_ENABLED` / `WEBUI_HOST` / `WEBUI_PORT` 环境变量保持兼容，自动转发到 FastAPI 服务
  - `webui.py` 保留为兼容入口，启动时直接调用 FastAPI 后端
  - Docker Compose 中移除 `webui` 服务定义，统一使用 `server` 服务

### 变更
- ♻️ **服务层重构**
  - 将 `web/services.py` 中的异步任务服务迁移至 `src/services/task_service.py`
  - Bot 分析命令（`bot/commands/analyze.py`）改为使用 `src.services.task_service`
  - Docker 环境变量 `WEBUI_HOST`/`WEBUI_PORT` 更名为 `API_HOST`/`API_PORT`（旧名仍兼容）

## [2.3.0] - 2026-02-01

### 新增
- 🇺🇸 **增强美股支持** (Issue #153)
  - 实现基于 Akshare 的美股历史数据获取 (`ak.stock_us_daily()`)
  - 实现基于 Yfinance 的美股实时行情获取（优先策略）
  - 增加对不支持数据源（Tushare/Baostock/Pytdx/Efinance）的美股代码过滤和快速降级

### 修复
- 🐛 修复 AMD 等美股代码被误识别为 A 股的问题 (Issue #153)

## [2.2.5] - 2026-02-01

### 新增
- 🤖 **AstrBot 消息推送** (PR #217)
  - 新增 AstrBot 通知渠道，支持推送到 QQ 和微信
  - 支持 HMAC SHA256 签名验证，确保通信安全
  - 通过 `ASTRBOT_URL` 和 `ASTRBOT_TOKEN` 配置

## [2.2.4] - 2026-02-01

### 新增
- ⚙️ **可配置数据源优先级** (PR #215)
  - 支持通过环境变量（如 `YFINANCE_PRIORITY=0`）动态调整数据源优先级
  - 无需修改代码即可优先使用特定数据源（如 Yahoo Finance）

## [2.2.3] - 2026-01-31

### 修复
- 📦 更新 requirements.txt，增加 `lxml_html_clean` 依赖以解决兼容性问题

## [2.2.2] - 2026-01-31

### 修复
- 🐛 修复代理配置区分大小写问题 (fixes #211)

## [2.2.1] - 2026-01-31

### 修复
- 🐛 **YFinance 兼容性修复** (PR #210, fixes #209)
  - 修复新版 yfinance 返回 MultiIndex 列名导致的数据解析错误

## [2.2.0] - 2026-01-31

### 新增
- 🔄 **多源回退策略增强**
  - 实现了更健壮的数据获取回退机制 (feat: multi-source fallback strategy)
  - 优化了数据源故障时的自动切换逻辑

### 修复
- 🐛 修复 analyzer 运行后无法通过改 .env 文件的 stock_list 内容调整跟踪的股票

## [2.1.14] - 2026-01-31

### 文档
- 📝 更新 README 和优化 auto-tag 规则

## [2.1.13] - 2026-01-31

### 修复
- 🐛 **Tushare 优先级与实时行情** (Fixed #185)
  - 修复 Tushare 数据源优先级设置问题
  - 修复 Tushare 实时行情获取功能

## [2.1.12] - 2026-01-30

### 修复
- 🌐 修复代理配置在某些情况下的区分大小写问题
- 🌐 修复本地环境禁用代理的逻辑

## [2.1.11] - 2026-01-30

### 优化
- 🚀 **飞书消息流优化** (PR #192)
  - 优化飞书 Stream 模式的消息类型处理
  - 修改 Stream 消息模式默认为关闭，防止配置错误运行时报错

## [2.1.10] - 2026-01-30

### 合并
- 📦 合并 PR #154 贡献

## [2.1.9] - 2026-01-30

### 新增
- 💬 **微信文本消息支持** (PR #137)
  - 新增微信推送的纯文本消息类型支持
  - 添加 `WECHAT_MSG_TYPE` 配置项

## [2.1.8] - 2026-01-30

### 修复
- 🐛 修正日志中 API 提供商显示错误 (PR #197)

## [2.1.7] - 2026-01-30

### 修复
- 🌐 禁用本地环境的代理设置，避免网络连接问题

## [2.1.6] - 2026-01-29

### 新增
- 📡 **Pytdx 数据源 (Priority 2)**
  - 新增通达信数据源，免费无需注册
  - 多服务器自动切换
  - 支持实时行情和历史数据
- 🏷️ **多源股票名称解析**
  - DataFetcherManager 新增 `get_stock_name()` 方法
  - 新增 `batch_get_stock_names()` 批量查询
  - 自动在多数据源间回退
  - Tushare 和 Baostock 新增股票名称/列表方法
- 🔍 **增强搜索回退**
  - 新增 `search_stock_price_fallback()` 用于数据源全部失败时
  - 新增搜索维度：市场分析、行业分析
  - 最大搜索次数从 3 增加到 5
  - 改进搜索结果格式（每维度 4 条结果）

### 改进
- 更新搜索查询模板以提高相关性
- 增强 `format_intel_report()` 输出结构

## [2.1.5] - 2026-01-29

### 新增
- 📡 新增 Pytdx 数据源和多源股票名称解析功能

## [2.1.4] - 2026-01-29

### 文档
- 📝 更新赞助商信息

## [2.1.3] - 2026-01-28

### 文档
- 📝 重构 README 布局
- 🌐 新增繁体中文翻译 (README_CHT.md)

### 修复
- 🐛 修复 WebUI 无法输入美股代码问题
  - 输入框逻辑改成所有字母都转换成大写
  - 支持 `.` 的输入（如 `BRK.B`）

## [2.1.2] - 2026-01-27

### 修复
- 🐛 修复个股分析推送失败和报告路径问题 (fixes #166)
- 🐛 修改 CR 错误，确保微信消息最大字节配置生效

## [2.1.1] - 2026-01-26

### 新增
- 🔧 添加 GitHub Actions auto-tag 工作流
- 📡 添加 yfinance 兜底数据源及数据缺失警告

### 修复
- 🐳 修复 docker-compose 路径和文档命令
- 🐳 Dockerfile 补充 copy src 文件夹 (fixes #145)

## [2.1.0] - 2026-01-25

### 新增
- 🇺🇸 **美股分析支持**
  - 支持美股代码直接输入（如 `AAPL`, `TSLA`）
  - 使用 YFinance 作为美股数据源
- 📈 **MACD 和 RSI 技术指标**
  - MACD：趋势确认、金叉死叉信号（零轴上金叉⭐、金叉✅、死叉❌）
  - RSI：超买超卖判断（超卖⭐、强势✅、超买⚠️）
  - 指标信号纳入综合评分系统
- 🎮 **Discord 推送支持** (PR #124, #125, #144)
  - 支持 Discord Webhook 和 Bot API 两种方式
  - 通过 `DISCORD_WEBHOOK_URL` 或 `DISCORD_BOT_TOKEN` + `DISCORD_MAIN_CHANNEL_ID` 配置
- 🤖 **机器人命令交互**
  - 钉钉机器人支持 `/分析 股票代码` 命令触发分析
  - 支持 Stream 长连接模式
- 🌡️ **AI 温度参数可配置** (PR #142)
  - 支持自定义 AI 模型温度参数
- 🐳 **Zeabur 部署支持**
  - 添加 Zeabur 镜像部署工作流
  - 支持 commit hash 和 latest 双标签

### 重构
- 🏗️ **项目结构优化**
  - 核心代码移至 `src/` 目录，根目录更清爽
  - 文档移至 `docs/` 目录
  - Docker 配置移至 `docker/` 目录
  - 修复所有 import 路径，保持向后兼容
- 🔄 **数据源架构升级**
  - 新增数据源熔断机制，单数据源连续失败自动切换
  - 实时行情缓存优化，批量预取减少 API 调用
  - 网络代理智能分流，国内接口自动直连
- 🤖 Discord 机器人重构为平台适配器架构

### 修复
- 🌐 **网络稳定性增强**
  - 自动检测代理配置，对国内行情接口强制直连
  - 修复 EfinanceFetcher 偶发的 `ProtocolError`
  - 增加对底层网络错误的捕获和重试机制
- 📧 **邮件渲染优化**
  - 修复邮件中表格不渲染问题 (#134)
  - 优化邮件排版，更紧凑美观
- 📢 **企业微信推送修复**
  - 修复大盘复盘推送不完整问题
  - 增强消息分割逻辑，支持更多标题格式
  - 增加分批发送间隔，避免限流丢失
- 👷 **CI/CD 修复**
  - 修复 GitHub Actions 中路径引用的错误

## [2.0.0] - 2026-01-24

### 新增
- 🇺🇸 **美股分析支持**
  - 支持美股代码直接输入（如 `AAPL`, `TSLA`）
  - 使用 YFinance 作为美股数据源
- 🤖 **机器人命令交互** (PR #113)
  - 钉钉机器人支持 `/分析 股票代码` 命令触发分析
  - 支持 Stream 长连接模式
  - 支持选择精简报告或完整报告
- 🎮 **Discord 推送支持** (PR #124)
  - 支持 Discord Webhook 推送
  - 添加 Discord 环境变量到工作流

### 修复
- 🐳 修复 WebUI 在 Docker 中绑定 0.0.0.0 (fixed #118)
- 🔔 修复飞书长连接通知问题
- 🐛 修复 `analysis_delay` 未定义错误
- 🔧 启动时 config.py 检测通知渠道，修复已配置自定义渠道情况下仍然提示未配置问题

### 改进
- 🔧 优化 Tushare 优先级判断逻辑，提升封装性
- 🔧 修复 Tushare 优先级提升后仍排在 Efinance 之后的问题
- ⚙️ 配置 TUSHARE_TOKEN 时自动提升 Tushare 数据源优先级
- ⚙️ 实现 4 个用户反馈 issue (#112, #128, #38, #119)

## [1.6.0] - 2026-01-19

### 新增
- 🖥️ WebUI 管理界面及 API 支持（PR #72）
  - 全新 Web 架构：分层设计（Server/Router/Handler/Service）
  - 核心 API：支持 `/analysis` (触发分析), `/tasks` (查询进度), `/health` (健康检查)
  - 交互界面：支持页面直接输入代码并触发分析，实时展示进度
  - 运行模式：新增 `--webui-only` 模式，仅启动 Web 服务
  - 解决了 [#70](https://github.com/ZhuLinsen/daily_stock_analysis/issues/70) 的核心需求（提供触发分析的接口）
- ⚙️ GitHub Actions 配置灵活性增强（[#79](https://github.com/ZhuLinsen/daily_stock_analysis/issues/79)）
  - 支持从 Repository Variables 读取非敏感配置（如 STOCK_LIST, GEMINI_MODEL）
  - 保持对 Secrets 的向下兼容

### 修复
- 🐛 修复企业微信/飞书报告截断问题（[#73](https://github.com/ZhuLinsen/daily_stock_analysis/issues/73)）
  - 移除 notification.py 中不必要的长度硬截断逻辑
  - 依赖底层自动分片机制处理长消息
- 🐛 修复 GitHub Workflow 环境变量缺失（[#80](https://github.com/ZhuLinsen/daily_stock_analysis/issues/80)）
  - 修复 `CUSTOM_WEBHOOK_BEARER_TOKEN` 未正确传递到 Runner 的问题

## [1.5.0] - 2026-01-17

### 新增
- 📲 单股推送模式（[#55](https://github.com/ZhuLinsen/daily_stock_analysis/issues/55)）
  - 每分析完一只股票立即推送，不用等全部分析完
  - 命令行参数：`--single-notify`
  - 环境变量：`SINGLE_STOCK_NOTIFY=true`
- 🔐 自定义 Webhook Bearer Token 认证（[#51](https://github.com/ZhuLinsen/daily_stock_analysis/issues/51)）
  - 支持需要 Token 认证的 Webhook 端点
  - 环境变量：`CUSTOM_WEBHOOK_BEARER_TOKEN`

## [1.4.0] - 2026-01-17

### 新增
- 📱 Pushover 推送支持（PR #26）
  - 支持 iOS/Android 跨平台推送
  - 通过 `PUSHOVER_USER_KEY` 和 `PUSHOVER_API_TOKEN` 配置
- 🔍 博查搜索 API 集成（PR #27）
  - 中文搜索优化，支持 AI 摘要
  - 通过 `BOCHA_API_KEYS` 配置
- 📊 Efinance 数据源支持（PR #59）
  - 新增 efinance 作为数据源选项
- 🇭🇰 港股支持（PR #17）
  - 支持 5 位代码或 HK 前缀（如 `hk00700`、`hk1810`）

### 修复
- 🔧 飞书 Markdown 渲染优化（PR #34）
  - 使用交互卡片和格式化器修复渲染问题
- ♻️ 股票列表热重载（PR #42 修复）
  - 分析前自动重载 `STOCK_LIST` 配置
- 🐛 钉钉 Webhook 20KB 限制处理
  - 长消息自动分块发送，避免被截断
- 🔄 AkShare API 重试机制增强
  - 添加失败缓存，避免重复请求失败接口

### 改进
- 📝 README 精简优化
  - 高级配置移至 `docs/full-guide.md`


## [1.3.0] - 2026-01-12

### 新增
- 🔗 自定义 Webhook 支持
  - 支持任意 POST JSON 的 Webhook 端点
  - 自动识别钉钉、Discord、Slack、Bark 等常见服务格式
  - 支持配置多个 Webhook（逗号分隔）
  - 通过 `CUSTOM_WEBHOOK_URLS` 环境变量配置

### 修复
- 📝 企业微信长消息分批发送
  - 解决自选股过多时内容超过 4096 字符限制导致推送失败的问题
  - 智能按股票分析块分割，每批添加分页标记（如 1/3, 2/3）
  - 批次间隔 1 秒，避免触发频率限制

## [1.2.0] - 2026-01-11

### 新增
- 📢 多渠道推送支持
  - 企业微信 Webhook
  - 飞书 Webhook（新增）
  - 邮件 SMTP（新增）
  - 自动识别渠道类型，配置更简单

### 改进
- 统一使用 `NOTIFICATION_URL` 配置，兼容旧的 `WECHAT_WEBHOOK_URL`
- 邮件支持 Markdown 转 HTML 渲染

## [1.1.0] - 2026-01-11

### 新增
- 🤖 OpenAI 兼容 API 支持
  - 支持 DeepSeek、通义千问、Moonshot、智谱 GLM 等
  - Gemini 和 OpenAI 格式二选一
  - 自动降级重试机制

## [1.0.0] - 2026-01-10

### 新增
- 🎯 AI 决策仪表盘分析
  - 一句话核心结论
  - 精确买入/止损/目标点位
  - 检查清单（✅⚠️❌）
  - 分持仓建议（空仓者 vs 持仓者）
- 📊 大盘复盘功能
  - 主要指数行情
  - 涨跌统计
  - 板块涨跌榜
  - AI 生成复盘报告
- 🔍 多数据源支持
  - AkShare（主数据源，免费）
  - Tushare Pro
  - Baostock
  - YFinance
- 📰 新闻搜索服务
  - Tavily API
  - SerpAPI
- 💬 企业微信机器人推送
- ⏰ 定时任务调度
- 🐳 Docker 部署支持
- 🚀 GitHub Actions 零成本部署

### 技术特性
- Gemini AI 模型（gemini-3-flash-preview）
- 429 限流自动重试 + 模型切换
- 请求间延时防封禁
- 多 API Key 负载均衡
- SQLite 本地数据存储

---

[Unreleased]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.32.0...HEAD
[3.32.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.31.0...v3.32.0
[3.31.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.30.0...v3.31.0
[3.30.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.29.0...v3.30.0
[3.29.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.28.0...v3.29.0
[3.28.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.27.0...v3.28.0
[3.27.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.26.1...v3.27.0
[3.26.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.25.0...v3.26.1
[3.25.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.24.1...v3.25.0
[3.24.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.24.0...v3.24.1
[3.24.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.23.0...v3.24.0
[3.23.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.22.0...v3.23.0
[3.22.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.21.1...v3.22.0
[3.21.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.21.0...v3.21.1
[3.21.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.20.0...v3.21.0
[3.20.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.19.0...v3.20.0
[3.19.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.18.0...v3.19.0
[3.18.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.17.1...v3.18.0
[3.17.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.17.0...v3.17.1
[3.17.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.16.0...v3.17.0
[3.16.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.15.0...v3.16.0
[3.15.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.14.2...v3.15.0
[3.14.2]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.14.1...v3.14.2
[3.14.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.14.0...v3.14.1
[3.14.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.13.0...v3.14.0
[3.13.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.12.0...v3.13.0
[3.12.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.11.0...v3.12.0
[3.11.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.10.1...v3.11.0
[3.10.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.10.0...v3.10.1
[3.10.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.9.0...v3.10.0
[3.9.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.8.0...v3.9.0
[3.8.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.7.0...v3.8.0
[3.7.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.6.0...v3.7.0
[3.6.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.5.0...v3.6.0
[3.5.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.10...v3.5.0
[3.4.10]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.9...v3.4.10
[3.4.9]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.8...v3.4.9
[3.4.8]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.7...v3.4.8
[3.4.7]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.0...v3.4.7
[3.4.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.3.22...v3.4.0
[3.3.22]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.3.12...v3.3.22
[3.3.12]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.2.11...v3.3.12
[3.2.11]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.2.10...v3.2.11
[2.3.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.5...v2.3.0
[2.2.5]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.4...v2.2.5
[2.2.4]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.3...v2.2.4
[2.2.3]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.2...v2.2.3
[2.2.2]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.1...v2.2.2
[2.2.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.0...v2.2.1
[2.2.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.14...v2.2.0
[2.1.14]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.13...v2.1.14
[2.1.13]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.12...v2.1.13
[2.1.12]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.11...v2.1.12
[2.1.11]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.10...v2.1.11
[2.1.10]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.9...v2.1.10
[2.1.9]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.8...v2.1.9
[2.1.8]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.7...v2.1.8
[2.1.7]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.6...v2.1.7
[2.1.6]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.5...v2.1.6
[2.1.5]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.4...v2.1.5
[2.1.4]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.3...v2.1.4
[2.1.3]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.2...v2.1.3
[2.1.2]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.1...v2.1.2
[2.1.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.0...v2.1.1
[2.1.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.6.0...v2.0.0
[1.6.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.5.0...v1.6.0
[1.5.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.4.0...v1.5.0
[1.4.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/ZhuLinsen/daily_stock_analysis/releases/tag/v1.0.0
