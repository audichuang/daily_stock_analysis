# NAS 上的 Web 服務與發版

本 fork 的 Web／API 服務正式跑在 NAS（Komodo stack `dsa`），本機不再常駐；每日報告等 LLM 重活仍在本機（見 `docs/daily-report-ops.md`）。映像怎麼建見 `docs/DEPLOY.md`「本 fork 的预建镜像（GHCR main）」。

## 不要在本機再起一份

本機 launchd `com.audichuang.dsa` 已 `disable`，不要重新啟用：兩邊會同時登入 Shioaji，且共用同一個應用庫（`STORAGE_DATABASE_URL` 的 `dsa` schema）。

## 發版流程（手動，打 tag 不會自動部署）

日常改動合進 `develop`；`main` 只代表已發版。

1. `develop` fast-forward 進 `main` 並 push，在 `main` 上打 annotated tag `rel-YYYY.MM.DD`（同日第二版加 `.2`）並 push tag → `.github/workflows/ghcr-main.yml` 產出映像，job summary 印出 `git-<sha7>@sha256:<digest>`，另有同名 tag。
2. 照 ops repo `nas-ops`（本機 clone 在 `~/Project/nas-ops`）裡 `hosts/<NAS>/dsa/manifest.md`，把 compose 的 `image:` 釘到新 digest、鎖 SHA，經 Komodo 部署。
3. 記入同目錄的 `deployments.md`。

NAS 一直跑的是釘住的舊 digest，直到走完上面三步。**不要在 NAS 上用 SSH 跑 compose**——會和 Komodo 搶同一個 project。

## NAS 上的問股

問股 Agent 只能走 LiteLLM（本機 Claude Code CLI 是 generation-only）：NAS 用 Anthropic key（Periphery secret）＋ NAS `config/.env` 的 `LITELLM_MODEL`。本機 `.env` 沒有 key，本機問股不可用。

## 唯讀查看線上狀態

部署現況以 ops repo 的 `hosts/<NAS>/dsa/manifest.md`（設計）與 `deployments.md`（每次發版的 image、驗收、回滾點）為準；要看 live 狀態用 skill `nas-container`（DSM 連線設定在本機 `~/.config/synology-container.env`），只做看的動作：

- 容器：`dsa-server-1`，compose project `dsa`，working dir 在 Komodo Periphery 的 stacks 目錄底下；`docker ps`／`inspect` 對照 image tag（`git-<sha7>`）與 `RestartCount`，`logs --tail` 看最近請求。容器在 audinas（不在 ttnas），SSH 上要用 `sudo -n /usr/local/bin/docker` 才看得到。uvicorn 的 access log 只記已送出回應的請求：某支請求在 log 裡缺席，代表客戶端在回應前就斷線（踩過：iOS 下拉更新時報價請求被 App 自己取消）。
- 健康檢查：`curl http://<NAS>:7777/api/health` 回 200。
- 秘密不在 NAS 的 `.env`：DB 密碼與各金鑰是 Periphery `[secrets]` 插進 stack environment；Web 可改的非秘密設定在主機 `config/.env`。看 env 只比對 key，不印值。
- 改任何東西（重啟、換 image、改 env）都走 Komodo，不用 SSH 跑 compose。

## 直接查資料庫

兩個 schema 在同一顆 NAS Postgres、同一個 `stock` 庫，連線字串就是 `.env` 的兩個 URL（psql 不認 `+psycopg`，要去掉）：

```bash
U=$(grep '^DATABASE_URL=' .env | cut -d= -f2- | sed 's/+psycopg//')
psql "$U" -c "select max(date), count(distinct stock_id) from market.price"   # 行情
psql "$U" -c "select count(*), max(created_at) from dsa.analysis_history"    # 應用庫
uv run --env-file .env python -m market_data.cli health                      # 資料健檢
```

- `market`：台股行情／籌碼／財報／基金淨值（`price`、`institutional`、`margin`、`valuation`、`monthly_revenue`、`financial_statement`、`fund_nav`…），唯一數據源、無本機備份（NAS 端由 ttnas 每日 `pg_dump`）。
- `dsa`：分析歷史、回測、決策訊號、LLM 用量，和 NAS 正式 Web 共用——只讀；臨時腳本要寫入先把 `STORAGE_DATABASE_URL` 設成空字串隔離。

## 第二台開發機

Linux 開發機（`~/research/daily_stock_analysis`）是 Mac 主 checkout 的鏡像：gitignore 的 `.env`、`.memory/`、`data/`、`reports/`、`logs/` 從 Mac rsync 過來（`.claude/settings.local.json` 的 `autoMemoryDirectory` 改成本機路徑），`.venv` 照 Mac 的 `uv pip freeze` 重建（`shioaji` 例外：Linux 沒有同版 wheel）。這台只做開發與查資料：**不設排程、不跑 `make serve`**——排程（含 07:30 commit＋push `journal/`）只在 Mac，兩邊都跑會重複 commit、重複登入 Shioaji、重複寫應用庫。
