# NAS 上的 Web 服務與發版

本 fork 的 Web／API 服務正式跑在 NAS（Komodo stack `dsa`），本機不再常駐；每日報告等 LLM 重活仍在本機（見 `docs/daily-report-ops.md`）。映像怎麼建見 `docs/DEPLOY.md`「本 fork 的预建镜像（GHCR main）」。

## 不要在本機再起一份

本機 launchd `com.audichuang.dsa` 已 `disable`，不要重新啟用：兩邊會同時登入 Shioaji，且共用同一個應用庫（`STORAGE_DATABASE_URL` 的 `dsa` schema）。

## 發版流程（手動，push `main` 不會自動部署）

1. push `main` → `.github/workflows/ghcr-main.yml` 產出映像，job summary 印出 `git-<sha7>@sha256:<digest>`。
2. 照 ops repo `nas-ops`（本機 clone 在 `~/Project/nas-ops`）裡 `hosts/<NAS>/dsa/manifest.md`，把 compose 的 `image:` 釘到新 digest、鎖 SHA，經 Komodo 部署。
3. 記入同目錄的 `deployments.md`。

NAS 一直跑的是釘住的舊 digest，直到走完上面三步。**不要在 NAS 上用 SSH 跑 compose**——會和 Komodo 搶同一個 project。

## NAS 上的問股

問股 Agent 只能走 LiteLLM（本機 Claude Code CLI 是 generation-only）：NAS 用 Anthropic key（Periphery secret）＋ NAS `config/.env` 的 `LITELLM_MODEL`。本機 `.env` 沒有 key，本機問股不可用。
