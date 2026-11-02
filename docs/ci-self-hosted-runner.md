# CI 自架 runner：設定由來、主機比較與排障

`ci.yml` 的每個 job 都跑在 ubuntu 工作站（audichuang-desktop，i7-12700、31 GB）上的 10 個自架 runner（label `ubuntu-desktop`，只註冊在本 repo）。runner 是 `~/gh-runners` 的 docker compose，**不歸 Komodo 管**；compose 與 manifest 正本在 nas-ops 的 `hosts/ubuntu/gh-runners/`，換版、加 runner、重新註冊照那份 manifest 做。2026-10-22 至 2026-11-01 跑在 ttnas，下面的症狀表多半是那時除錯留下的，換主機後一樣適用。

這台同時是 Mac mini 的遠端 Rust 編譯機（`rust-remote`），CI 與編譯互搶 CPU 是常態，下面的實測有把這個情況算進去。

## 主機怎麼選的（2026-11-01 實測）

同一份 `ci.yml`、同一版程式（後端測試總耗時 517 秒），只換 runner：

| 條件 | 整輪時間 | 每片測試 |
|---|---|---|
| ttnas 6 台，單獨 1 個 run | 3 分 55 秒 | 130–178s |
| ubuntu 8 台，單獨 1 個 run | 3 分 46 秒 | 119–143s |
| GitHub 託管 ubuntu-24.04，8 片 | 4 分 53 秒 | 86–253s |
| ttnas 6 台，3 個 run 同時 | 10.1／11.5／13.8 分 | 207–284s |
| ubuntu 8 台，3 個 run 同時 | 5.9／6.2／8.1 分 | 116–296s |
| ubuntu 12 台，3 個 run 同時 | 5.2／5.6／7.3 分 | 112–212s |
| ubuntu 12 台，3 個 run 同時＋背景 Rust 編譯吃滿 20 執行緒 | 6.2／6.2／8.3 分 | 177–311s |
| ubuntu 12 台，5 個 run 同時 | 5.0–10.6 分 | 156–222s |

- **ttnas 不適合**：i5-12400 只有 6 核，runner 6 台 × `cpus: 4` 已超賣一倍；而且散熱有問題，閒置就 91°C，開機 22.7 小時裡約 4 小時在降溫節流（`/sys/devices/system/cpu/cpu*/thermal_throttle/package_throttle_total_time_ms`），負載下頻率掉到 1.6–2.0 GHz。
- **GitHub 託管不划算**：單核約慢一倍，最慢那片被單一大檔卡住，加片數沒用；要贏得靠 `pytest-xdist`，實測冒出測試隔離問題（`test_usage_api` 回 401）。好處只有同時 20 個 job 不排隊。
- **10 台是折衷**：8 → 12 台在 3 個 run 時只快約 0.8 分——runner 多了、同時跑的分片也多，P 核只有 8 顆，每片變慢；runner 越多也越卡同機的 Rust 編譯。10 台沒有單獨實測。

## 先分清楚是哪一種紅

| 症狀 | 原因 | 判別／處理 |
|---|---|---|
| 一大批子程序測試回 `127`，stderr 是 `libpython3.11.so.1.0: cannot open shared object file` | `setup-python` 的 Python 是預先編譯的，libpython 的 rpath 寫死在 `/opt/hostedtoolcache`。工具快取放在別處時，主程序靠 `LD_LIBRARY_PATH` 還能跑，測試用清掉環境變數的子程序就起不來 | runner 的 `RUNNER_TOOL_CACHE`／`AGENT_TOOLSDIRECTORY` 必須是 `/opt/hostedtoolcache`（compose 已設）。換 runner 映像或新開 runner 時檢查這兩個變數 |
| `setup-python` 報 `mkdir: cannot create directory '/opt/hostedtoolcache/Python': Permission denied` | 新建的 toolcache volume 是 root 擁有 | 照 manifest 先把 volume chown 給 uid 1001 |
| 個別測試逾時或「資源沒收乾淨」，每次是不同的測試（`test_codex_tool_process`、`test_provider_cache`、`test_local_cli_backend`、Playwright `Test timeout of 30000ms`） | 主機負載過高（同時好幾個 run，或背景編譯吃滿 CPU） | 到 runner 容器裡單跑那個檔，會綠就是負載型假紅（`docs/test-triage.md` 的判讀表）。別加 shard；跟被測性質無關的 timeout 照 `tests/AGENTS.md` 放寬 |
| 整體比平常慢一倍、各片都慢，主機看起來不忙 | 分片被排到 E 核（16–19），E 核單執行緒慢約一倍 | compose 的 `cpuset: "0-15"` 只給 P 核；換主機時先用 `lscpu -e=CPU,CORE,MAXMHZ` 看哪些是 P 核 |
| DB 類測試（portfolio、analysis_history、backtest、alert）慢 4–6 倍 | 測試的 SQLite 放在 `/tmp`，每次 commit 都 fsync 到磁碟 | `_work`、`/tmp` 都要是 tmpfs（compose 已設），Postgres service 也加 `--tmpfs /var/lib/postgresql/data`。ttnas 時期實測同 4 個測試檔：系統碟 127 秒、tmpfs 19 秒 |
| web-gate 報 `http://127.0.0.1:4173 is already used` | runner 是 `network_mode: host`，全部共用主機網路；兩個 run 的 web-gate 同時跑就搶同一個 port | `ci.yml` 的 web-gate 每次挑空 port 寫進 `PLAYWRIGHT_FIXTURE_PORT`，fixture config 讀它。新加會開固定 port 的 job 照這個做 |
| Playwright fixture 一批逾時 | runner 容器看得到主機全部執行緒，Playwright 預設依此開 worker，容器實際只分到 4 核，Vite dev server 首次編譯就逾時 | `playwright.fixture.config.ts` 在 CI 固定 2 個 worker。新加會依 CPU 數開 worker 的工具，一樣要在 CI 固定數量 |
| Postgres service 起不來 | 主機的 5432 可能已被佔用 | service 用隨機 host port（`ports: ['5432']`），連線埠在 step 裡從 `job.services.postgres.ports['5432']` 寫進 `GITHUB_ENV`；job 層 `env` 拿不到 `job` context，寫在那裡整個 workflow 會「workflow file issue」 |
| 所有 step 都綠，GitHub 上的 job 卻一直「執行中」 | GitHub 端的狀態更新落後（Actions degraded 時會落後好幾分鐘） | 看 runner 容器的 log：`docker logs gh-runner-N` 有 `Job … completed with result` 就是已跑完，等 GitHub 補上。日誌要等 GitHub 那邊標完成才拿得到 |
| `setup-python` 報 `version '3.11' … was not found for Debian 12` | runner 直接跑在主機上而不是容器裡（ttnas 的 fnOS 是 Debian 12） | runner 一律跑在 `actions-runner` 容器（Ubuntu），不要在主機上裸跑 |
| shard 開機就失敗：`Invalid duration for …: 0.0` | 舊版 `ci_durations_from_junit.py` 在快機器上把整個檔四捨五入成 `0.0`，`ci_test_shard.py` 只收大於 0 的時長 | 已修（下限 0.001 秒）。重算時長表後先在本機跑 `tests/test_ci_test_shard.py` |
| 某一片永遠比其他片長很多 | 分片以整個檔為單位，`test_agent_active_stock_integration.py` 一個檔約 150 秒（2026-11-01 修掉股名 regex 前是 360 秒），只能獨占一片 | 預期行為；時長表過期（新檔沒進表）也會讓分片失衡，從最近一次 CI 的 junit 用 `scripts/ci_durations_from_junit.py` 重算 |

## 為什麼是這些設定

- **4 片 shard**：最慢那片被上面那個大檔卡住（約 150 秒），4 片時各片已接近它，再多片不會更快。片數是**每個 run** 的：同時推好幾個工作分支等於 8～16 片一起跑，排隊與 CPU 爭用都會拉長整輪。
- **docker-build 用 `driver: docker`**：直接用 runner 主機 daemon 的層快取。`type=gha` 快取每次要經家用網路下載整份映像層，實測 456 秒，改完 7 秒。代價是每次映像內容變了，會在主機留下約 1.7 GB 的 dangling image，清理方式見 manifest。所有 runner 共用這個 daemon，不同分支的 docker-build 會同時跑，所以 build 與兩個 smoke 步驟共用 job 層的 `CI_IMAGE_TAG`（`stock-analysis:test-<run_id>-<run_attempt>`），smoke 只跑自己那個 tag，job 結束（含失敗）以 `always()` 只刪自己的 tag；不要改回固定 tag，也不要在 job 裡 prune，會刪到別的 run 正在用的映像。
- **不用 `setup-python`／`setup-node` 的 `cache:`**：那是從 GitHub 下載。runner 的 uv／pip／npm／Playwright 快取放在共用的 volume；Python 本體與裝好的套件放在每台自己的 volume（第一次跑約 1.5 分鐘，之後幾秒）。
- **公開期間的限制**：`ci.yml` 只收 push、不收 `pull_request`；fork PR 的 workflow 核准設成 `all_external_contributors`；兩條都不要放寬——runner 掛著 `docker.sock`，等同主機 root。

## 排障常用指令

在 ubuntu 上：

```bash
cd ~/gh-runners && docker compose ps                               # 10 個 runner 是否都在跑
docker logs --tail 50 gh-runner-1                                  # 有沒有接到 job、job 的結果
docker stats --no-stream gh-runner-1 gh-runner-2                   # 單台的 CPU／記憶體
cat /proc/loadavg /proc/pressure/cpu                               # CI 期間的負載與 CPU 壓力
docker exec -w /home/runner/_work/daily_stock_analysis/daily_stock_analysis gh-runner-1 \
  bash -c 'PY=$(ls -d /opt/hostedtoolcache/Python/3.11*/x64/bin/python | head -1); $PY -m pytest -q tests/<檔名>'
                                                                   # 在 runner 的環境裡單跑一個檔，判斷負載型假紅
```

在本機：

```bash
gh api repos/audichuang/daily_stock_analysis/actions/runners -q '.runners[]|"\(.name) \(.status) busy=\(.busy)"'
```

runner 都 `offline` 時先看 ubuntu 是否開機、docker 是否在跑；註冊憑證遺失要照 manifest 重新註冊。
