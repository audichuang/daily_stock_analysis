# 盤前與每日報告維運

## Sub-features

- `make morning`：更新、嚴格健檢、盤前資料、候選與凍結 evidence pack。
- `make daily-report-detached`：背景執行、鎖、完成標記、分析／複盤與失敗結果。
- journal 追加、限定檔案 commit／push，Telegram topic 路由。
- `make verify-morning` 唯讀回驗及 dry-run 不發布 pack。
- 產生報告、發通知、push 必須各有本輪證據。

## How to get to it (user POV)

終端入口正本是 `Makefile`；時間、鎖、log 與完成標記見 `docs/daily-report-ops.md`。
閱讀順序與報告判讀見 `docs/tw-operating-guide.md §2.3、§3`。
Web 結果由首頁歷史查看，另依 [analysis-history.md](analysis-history.md) 驗證。

## Driving it with ego-browser 與 CLI

1. 先讀本輪 scope：`make morning` 會更新市場庫；每日報告會寫 journal、commit／push、發訊息。
   使用者已授權相應副作用便繼續；只授權建立驗證技能時，不擴大成實際通知或正式資料更新。
2. dry-run journey 可執行 `make -n morning`，但先讀 `scripts/morning_pack.sh`：
   make 含 `$(MAKE)` 的 recipe 在 `-n` 下仍可能執行包裝器。
   保存執行前後 `reports/morning-packs/` 的檔名／hash 與 Git refs／status，
   保存 stdout／stderr／exit code；應看到 `morning_pack: make dry-run`，且無新 pack。
   此項只證明 dry-run 邊界，不代表資料更新或報告成功。
3. 改到唯讀回驗可跑 `make verify-morning`，保存完整輸出、樣本量與資料日期；
   比較 journal 前後 hash。`scripts/verify_morning_calls.py --append` 是另一個寫入 journey，
   不能因唯讀命令通過就視作追加／去重已通過。
4. 完整盤前已獲授權時執行 `make morning`，保存 log、每階段 exit、資料 freshness、
   候選 JSON 與 `reports/morning-packs/` 新 pack；失敗輪不應發布成功 pack。
5. 完整每日報告已獲授權時執行 `make daily-report-detached`，記錄它回傳的本輪識別、PID／log 路徑；
   依維運文件檢查該輪 log、鎖與完成標記，直到真正結束。只等本輪程序，不按程序名稱殺服務。
6. 真正成功須對照個股成功數、完整複盤內容、歷史 ID、journal 新增列與預期 Git ref；
   用 ego-browser 開本輪目標首頁實際點報告，保存結果畫面。exit 0 不足以作結論。
7. 只有明確獲發訊息許可時才測真實 Telegram：記主題、已送出輸出及可取得的 message ID。
   `scripts/notify.py --check --topic report` 只驗憑證／topic 前置條件，不能證明已送達。
   Secret 只記「已設定／未設定」，證據不得含 token、chat ID 或完整環境。
8. 保存證據後按上層 Cleanup；正式既有服務、正式 journal／Git refs 不作測試清理。

## Gotchas

- 預設排程與 NAS Web 共用正式 `dsa`；本機 launchd 已停用，不要啟用來滿足此 journey。
- 本輪若沒有允許所有必要副作用，完整 pipeline 記 blocked 並列缺哪個許可；可獨立完成 dry-run／唯讀項。
- `make analyze` 沒包 Doppler；`make review-tw`、`make serve` 與 daily-report 包了通知前置檢查。
  具體命令以當前 Makefile 和 `docs/daily-report-ops.md` 為準。
- 主題缺失應拒送而不是落群組預設；sender 印 `[notify] <主題>: 已送出` 且 exit 0 才是發送端成功。
- 日誌／候選為真不代表研究有預測力；回驗樣本不足仍寫 inconclusive。
- 本項無外部網路的 stand-in 或 mock sender 僅證明對應邊界，不代表正式資料或 Telegram 已驗證。
- Launch 的隔離環境只給其 child process；在 repo 根目錄執行 Makefile 不會自動沿用，
  且多個 target 明寫 `uv run --env-file .env`。隔離 CLI 需顯式核對 ENV_FILE、SQLite、唯讀 market 與產物路徑。
- 只允許唯讀 market 時，完整 `make morning`／daily-report 記 blocked：它們會執行 market_data daily 更新。
  不為取得完整排程證據而寫正式庫、正式 journal／Git refs 或發通知；已有明確相應授權才執行那些入口。
- 可獨立驗 `verify_morning_calls.py --brief --calls <副本> --outcomes <副本> --arms <副本>` 的純讀輸出，
  以及 `morning_fable_arms.py --pack <凍結 pack> --journal <本輪檔>` 的真 CLI 判讀與本輪追加／同日去重。
  後者 `--dry-run` 不呼叫模型；這些隔離 CLI 結果不等於資料更新、正式排程、journal push 或 Telegram 送達。
