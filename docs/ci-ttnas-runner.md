# CI 自架 runner（ttnas）：設定由來與排障

`ci.yml` 的每個 job 都跑在 ttnas 上的 6 個自架 runner（label `ttnas`，只註冊在本 repo）。runner 本身是 Komodo stack `gh-runners`：compose、manifest、部署紀錄在 nas-ops 的 `hosts/ttnas/gh-runners/`，換版、加 runner、重新註冊照那份 manifest 做。這份文件記 2026-10-22 搬上去時的除錯過程，CI 在 ttnas 上出錯時先對症狀表。

## 先分清楚是哪一種紅

| 症狀 | 原因 | 判別／處理 |
|---|---|---|
| 一大批子程序測試回 `127`，stderr 是 `libpython3.11.so.1.0: cannot open shared object file` | `setup-python` 的 Python 是預先編譯的，libpython 的 rpath 寫死在 `/opt/hostedtoolcache`。工具快取放在別處時，主程序靠 `LD_LIBRARY_PATH` 還能跑，測試用清掉環境變數的子程序就起不來 | runner 的 `RUNNER_TOOL_CACHE`／`AGENT_TOOLSDIRECTORY` 必須是 `/opt/hostedtoolcache`（compose 已設）。換 runner 映像或新開 runner 時檢查這兩個變數 |
| 個別測試逾時或「資源沒收乾淨」，每次是不同的測試（`test_codex_tool_process`、`test_provider_cache`、`test_local_cli_backend`、Playwright `Test timeout of 30000ms`） | NAS 負載過高。12 執行緒還要分給其他 35 個容器，6 片 shard 同時跑時負載平均衝到 16 | 到 runner 容器裡單跑那個檔，會綠就是負載型假紅（`tests/AGENTS.md` 的判讀表）。別加 shard；跟被測性質無關的 timeout 照 `tests/AGENTS.md` 放寬 |
| Playwright fixture 一批逾時 | runner 容器看得到主機全部 12 執行緒，Playwright 預設開 6 個 worker，容器實際只分到 4 核，Vite dev server 首次編譯就逾時 | `playwright.fixture.config.ts` 在 CI 固定 2 個 worker。新加會依 CPU 數開 worker 的工具，一樣要在 CI 固定數量 |
| Postgres service 起不來 | ttnas 本機的 5432 已被佔用 | service 用隨機 host port（`ports: ['5432']`），連線埠在 step 裡從 `job.services.postgres.ports['5432']` 寫進 `GITHUB_ENV`；job 層 `env` 拿不到 `job` context，寫在那裡整個 workflow 會「workflow file issue」 |
| 測試偶爾卡 10 秒以上，卡在 SQLite 建表或 commit | ttnas 的系統碟與 `/vol1`（btrfs，和資料庫容器共用）fsync 都會卡數秒 | `_work`、`/tmp` 放 tmpfs（compose 已設），Postgres service 也加 `--tmpfs /var/lib/postgresql/data`。實測同 4 個測試檔：系統碟 127 秒、tmpfs 19 秒 |
| 所有 step 都綠，GitHub 上的 job 卻一直「執行中」 | GitHub 端的狀態更新落後（Actions degraded 時會落後好幾分鐘） | 看 runner 容器的 log：`docker logs gh-runner-N` 有 `Job … completed with result` 就是已跑完，等 GitHub 補上。日誌要等 GitHub 那邊標完成才拿得到 |
| `setup-python` 報 `version '3.11' … was not found for Debian 12` | runner 直接跑在 ttnas 主機（fnOS 是 Debian 12）而不是容器裡 | runner 一律跑在 `actions-runner` 容器（Ubuntu），不要在主機上裸跑 |
| shard 開機就失敗：`Invalid duration for …: 0.0` | 舊版 `ci_durations_from_junit.py` 在快機器上把整個檔四捨五入成 `0.0`，`ci_test_shard.py` 只收大於 0 的時長 | 已修（下限 0.001 秒）。重算時長表後先在本機跑 `tests/test_ci_test_shard.py` |
| 某一片永遠比其他片長很多 | 分片以整個檔為單位，`test_agent_active_stock_integration.py` 一個檔就約 360 秒，比平均每片還長，只能獨占一片 | 預期行為，重算時長表解決不了；要更快只能拆那個檔 |

## 為什麼是這些設定

- **4 片 shard**：3、6、4 片都跑過。3 片時 runner 不夠，加上 docker-build 要排隊；6 片把 NAS 跑滿，每片反而變慢、出假紅；4 片整輪約 7 分半，和 GitHub 託管的約 6 分鐘相當。片數是**每個 run** 的：同時推好幾個工作分支（或分支 push 撞上 develop 合併後的 run）等於 8～16 片一起跑，一樣滿載出假紅（2026-10-25 四次，都是 Codex process-group 類測試逾時，單獨重跑即綠）。多張 PR 依序推、一次一條 CI。
- **docker-build 用 `driver: docker`**：直接用 ttnas daemon 的層快取。原本的 `type=gha` 快取每次要經家用網路下載整份映像層，實測 456 秒，改完 7 秒。build 與兩個 smoke 步驟共用 job 層的 `CI_IMAGE_TAG`（`stock-analysis:test-${{ github.run_id }}-${{ github.run_attempt }}`），讓並行 run 與重跑不會互相覆寫；最後以 `always()` 執行 `docker image rm "$CI_IMAGE_TAG"`，只移除本次標籤。daemon 其餘快取的清理方式見 manifest。
- **不用 `setup-python`／`setup-node` 的 `cache:`**：那是從 GitHub 下載。runner 的 uv／pip／npm／Playwright 快取放在 6 台共用的 volume；Python 本體與裝好的套件放在每台自己的 volume（第一次跑約 1.5 分鐘，之後幾秒）。
- **安全邊界**：runner 掛 `docker.sock`，等於 NAS root。repo 公開期間靠兩件事擋外人：`ci.yml` 只收 push、不收 `pull_request`；fork PR 的 workflow 核准設成 `all_external_contributors`。要暫停就在 Komodo 對 `gh-runners` 執行 StopStack。

## 排障常用指令

在 ttnas 上：

```bash
docker ps --filter name=gh-runner                                  # 6 個 runner 是否都在跑
docker logs --tail 50 gh-runner-1                                  # 有沒有接到 job、job 的結果
docker stats --no-stream gh-runner-1 gh-runner-2                   # 單台的 CPU／記憶體
cat /proc/loadavg                                                  # CI 期間的負載；長時間超過 12 就是滿載
docker exec -w /home/runner/_work/daily_stock_analysis/daily_stock_analysis gh-runner-1 \
  bash -c 'PY=$(ls -d /opt/hostedtoolcache/Python/3.11*/x64/bin/python | head -1); $PY -m pytest -q tests/<檔名>'
                                                                   # 在 runner 的環境裡單跑一個檔，判斷負載型假紅
```

在本機：

```bash
gh api repos/audichuang/daily_stock_analysis/actions/runners -q '.runners[]|"\(.name) \(.status) busy=\(.busy)"'
```

runner 都 `offline` 時先看 Komodo 上 `gh-runners` 的狀態；註冊憑證遺失要照 manifest 重新註冊。
