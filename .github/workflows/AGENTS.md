# .github/workflows — CI 與發版

- **改 `ci.yml` 先繞開上游的契約測試**：`tests/test_ci_workflow_contract.py`、`tests/test_packaging_build_scripts.py`、`tests/test_futu_distribution_contract.py` 把 job 的 `if`／`needs`、安裝指令、shard env、打包指令的原文釘住，改到就紅；改上游測試的每一行都會在 `dsa-upstream-sync` 時衝突。優先用不碰斷言的寫法（job 層 env、舊指令留作 fallback、過濾器留著不刪），非改不可才改測試並加 `fork：` 註解。
- **有些 workflow 是在 GitHub 上停用的，檔案裡看不出來**（`gh workflow list --all` 看 `disabled_manually`）：`auto-tag.yml` 必須保持停用——它見到 commit title 含 `#patch` 就打 `v*` tag，上游 commit 經 `develop` 進 `main` 時會誤觸發上游的 release／Docker Hub／桌面端 workflow。`00-daily-analysis`、`network-smoke`、`stale` 停用是因為本 fork 的每日報告在本機跑、Actions 上沒配 secrets。
- **CI 跑在 ttnas 自架 runner（label `ttnas`，Komodo stack `gh-runners`，設定在 nas-ops `hosts/ttnas/gh-runners/manifest.md`）**；要暫停 CI 就在 Komodo 對 `gh-runners` 執行 StopStack。
- **job 跑在自架 runner 的容器裡，容器看得到 ttnas 全部執行緒、實際只分到 `cpus` 限額**：會依 CPU 數自己決定 worker 數的工具（Playwright 等）要在 CI 固定數量，否則開太多、互搶到逾時（踩過：fixture Playwright 開 6 個 Chromium 搶 4 核）。加 shard 或新的重 job 前，先估同時在跑的總量——6 片時 NAS 滿載、出負載型假紅。
