# .github/workflows — CI 與發版

> 本檔只寫本目錄增量。

- **改 `ci.yml` 先繞開上游的契約測試**：`tests/test_ci_workflow_contract.py`、`tests/test_packaging_build_scripts.py`、`tests/test_futu_distribution_contract.py` 把 job 的 `if`／`needs`、安裝指令、shard env、打包指令的原文釘住，改到就紅；改上游測試的每一行都會在 `dsa-upstream-sync` 時衝突。優先用不碰斷言的寫法（job 層 env、舊指令留作 fallback、過濾器留著不刪），非改不可才改測試並加 `fork：` 註解。
- **有些 workflow 是在 GitHub 上停用的，檔案裡看不出來**（`gh workflow list --all` 看 `disabled_manually`）：`auto-tag.yml` 必須保持停用——它見到 commit title 含 `#patch` 就打 `v*` tag，上游 commit 經 `develop` 進 `main` 時會誤觸發上游的 release／Docker Hub／桌面端 workflow。`00-daily-analysis`、`network-smoke`、`stale` 停用是因為本 fork 的每日報告在本機跑、Actions 上沒配 secrets。
