---
name: dsa-upstream-sync
description: 無人值守地把上游 ZhuLinsen/daily_stock_analysis 的 main merge 進本 fork（audichuang/daily_stock_analysis）的一條待審分支：乾跑衝突、靜默降級排查、快速門檻與受影響測試、寫同步紀錄、推 chore/upstream-sync-* 分支、Bark 通知待審，不動 main。用於「dsa 上游同步」Orca 排程觸發，或使用者要跑／續跑這個同步流程時。
---

# dsa 上游同步（無人值守）

這是排程，沒有人會回答問題，不要停下來問。**產出是一條待審分支，不是合進 develop**——這是本 skill 自己的規定，不是 `AGENTS.md` 的：§1、§9 允許 agent 在 CI 綠後自己合進 `develop`，但上游 merge 改動面大、排程時沒人在場，所以無人值守跑的時候 merge 與 push `develop` 都留給使用者審過再做。使用者在場、要求收尾時，照 §9 等 CI 綠再合。repo 規則以 `$REPO/AGENTS.md` 為準，先讀 §1、§6、§10。

固定值：

- `REPO=$(git rev-parse --show-toplevel)`（排程跑在主 checkout，就是它），remote：`origin`＝fork、`upstream`＝上游
- 同步用 **merge、不 rebase、不 force push**（fork 已 push 上百個自有 commit，rebase 等於全部改寫、只能 force push）
- 工作一律在獨立 worktree 做，**不准動 `$REPO` 的 working tree 與它 checkout 的分支**：同一個 checkout 07:30／10:00／13:00 有別的排程在用

## 0. 要不要做

```bash
bash $REPO/.claude/skills/dsa-upstream-sync/scripts/precheck.sh
```

非 0 就直接結束、不推 Bark（手動 run 不會跑 precheck，所以這裡要自己再跑一次）。通過且 `~/.config/dsa-upstream-sync/force-once` 存在時，刪掉它（只作用一次）。

記下：`BASE=$(git -C $REPO merge-base origin/develop upstream/main)`、`HEAD_UP=$(git -C $REPO rev-parse upstream/main)`、`N=$(git -C $REPO rev-list --count origin/develop..upstream/main)`、`DATE=$(TZ=Asia/Taipei date +%F)`。分支名 `chore/upstream-sync-$DATE`；origin 已有同名分支就加 `-2`、`-3`。

## 1. 開 worktree、merge

```bash
WT=~/.cache/dsa-upstream-sync/$DATE
git -C $REPO worktree add -b chore/upstream-sync-$DATE $WT origin/develop
cd $WT && git merge upstream/main --no-ff --no-edit -m "chore: merge upstream main (${BASE:0:8}..${HEAD_UP:0:8})"
```

上游若剛發版（`gh api repos/ZhuLinsen/daily_stock_analysis/releases/latest --jq .tag_name`，且該 tag 在 `$BASE..$HEAD_UP` 之內；precheck 沒抓 tag，不要用 `git tag --contains`），把版本號加進 commit 標題，比照前例 `chore: merge upstream main (6cb86d6e..7a21cd76, v3.33.0)`。

有衝突時逐塊裁決，原則（跟前幾輪 `docs/upstream-sync-*.md` 一致）：

- fork 的台股／繁中／Postgres／Claude Code CLI 相關行為一律保留；上游的新能力盡量收進來，兩者都要時手工合併
- fork 沒有立場的段落（推廣連結、贊助、上游專屬文件）取上游
- `docs/CHANGELOG.md`：上游條目進它自己的段，fork 的 `[Unreleased]` 條目全數留在原段
- 拿不準的塊：選對 fork 現有行為影響最小的解法，在同步紀錄的「衝突裁決」表標 **⚠ 需人工確認**，Bark 裡也點名

解完 `git diff --check`、`git grep -nE '^(<<<<<<<|>>>>>>>)'` 都要乾淨再 commit。

## 2. 靜默降級排查（不能省，這是排程存在的理由）

對 `git diff $BASE..upstream/main` 逐項看：

- **上游新增或改寫的市場集合／語言集合常數**（`'cn'`、`'hk'`、`'us'` 並列，`zh`、`zh-CN`、`en` 並列、`SUPPORTED_*`、`*_MARKETS`、`*_LANGUAGES`、`market in (...)`）：逐個問「涵蓋 `tw` 嗎？涵蓋 `zh-TW` 嗎？」。漏掉不會報錯，只會被安靜地跳過或退回簡體
- 只比對簡體字詞、或無對象時預設 A 股的新判斷（問股踩過）
- 新的台股代碼正則或 `isdigit()` 判代碼（要能吃 `00631L`、`2887A`，見 `tests/test_tw_code_pattern_contract.py`）
- 新增頂層 package／資料夾：`docker/Dockerfile` 的 COPY 有沒有跟上（§10）
- 新設定項：`.env.example` 有沒有被改到 fork 約定（`STOCK_INDEX_REMOTE_UPDATE_ENABLED` 等）
- 新依賴（`requirements*.txt`、`pyproject.toml`、`uv.lock`、`apps/*/package.json`）：**不安裝**，只在紀錄與 Bark 寫明
- Web 新文案：zh-TW 字典有沒有缺鍵（前例 10-08 補 58 鍵、10-11 補 5 鍵）

小而確定的補洞（補 `tw`／`zh-TW` 到集合、補 zh-TW 文案鍵、Dockerfile COPY）可以直接在分支上另開 commit 修，附測試；需要設計判斷的只記錄不修。

## 3. 驗證

全部在 `$WT` 跑，借用主 checkout 的 venv、不 sync 依賴：

```bash
export PATH="$REPO/.venv/bin:$PATH"
./scripts/ci_gate.sh syntax && ./scripts/ci_gate.sh flake8
python -m pytest -m "not network" <受影響測試檔> -q
```

受影響測試：上游這輪改到的 `tests/*`，加上 import 了這輪改到之模組的測試檔（`git grep -l` 找）。**不跑全量**（§1 要先確認；交給使用者合併前決定）。

有測試紅：先照 `tests/AGENTS.md` 排除假紅（單檔重跑），再在乾淨對照組跑同一個檔：

```bash
git -C $REPO worktree add --detach ~/.cache/dsa-upstream-sync/$DATE-fork origin/develop
git -C $REPO worktree add --detach ~/.cache/dsa-upstream-sync/$DATE-up upstream/main
```

只有「merge 後紅、`origin/develop` 綠」才算本輪引入的回歸；`upstream/main` 也紅代表是上游自己的問題。兩邊的輸出都摘進同步紀錄。新依賴沒裝造成的 ImportError 記為「需安裝依賴」，不算回歸。

## 4. 同步紀錄、CHANGELOG

- 以最新一份 `docs/upstream-sync-*.md` 為模板寫 `docs/upstream-sync-$DATE.md`（繁體中文）：基線、吸收的上游改動（每個 commit 對本 fork 的意義）、衝突裁決、靜默降級排查、驗證（含**未跑全量**）、回滾
- `docs/CHANGELOG.md` 的 `[Unreleased]` 加一條扁平 `- [chore] 合併上游 ...`，格式比照既有條目
- commit message 用英文，**不加 Co-Authored-By**（§1），例如 `docs: record upstream sync $DATE`

## 5. 推分支

```bash
git push origin HEAD:refs/heads/chore/upstream-sync-$DATE
```

不開 PR：這是無人值守排程，交付物只有待審分支；要不要開 PR、何時合進 `develop` 由使用者審過後決定（本 skill 的規定，理由見開頭；使用者在場收尾時照 §9 等 CI 綠再合）。推上去的未合併分支就是下一輪 precheck 的鎖。

## 6. Bark

組內容與送出**必須在同一個 Bash 指令裡**（每次 Bash 是新 shell，空內容 Bark 也回 200）：

```bash
doppler run -p shioaji -c dev -- uv run --no-project python - <<'PY'
import json, os, sys, urllib.request
title = "上游同步待審 YYYY-MM-DD"
body = """（內容）"""
payload = json.dumps({"title": title, "body": body, "group": "dsa"}, ensure_ascii=False).encode("utf-8")
if not title.strip() or not body.strip():
    sys.exit("推播內容是空的，不送")
if len(payload) > 3500:
    sys.exit(f"推播內容 {len(payload)} bytes 超過上限，請縮短 body")
req = urllib.request.Request(os.environ["BARK_URL"], data=payload,
                             headers={"Content-Type": "application/json; charset=utf-8"})
resp = json.load(urllib.request.urlopen(req, timeout=15))
print("bark:", resp)
sys.exit(0 if resp.get("code") == 200 else 1)
PY
```

body：分支名、吸收幾個 commit（重點改動一兩句）、衝突數與 ⚠ 需人工確認的項目、靜默降級排查結果、驗證結果、新依賴，最後一行「審過後在 develop：`git fetch origin chore/upstream-sync-$DATE && git merge --ff-only FETCH_HEAD`（develop 已前進就先把 develop merge 進分支）」。origin 的 fetch refspec 只抓 `main` 與 `develop`，所以不能寫 `origin/chore/...`，那個 ref 不存在。只有印出 `code: 200` 才算成功。

任何一步失敗也推，title「上游同步失敗 YYYY-MM-DD」，body 寫哪一步、什麼錯。失敗時若分支已推，在 body 寫明，讓使用者決定刪或續。

## 7. 收尾

`git -C $REPO worktree remove --force` 掉本輪開的所有 worktree（含 `-fork`、`-up`）；本機的 `chore/upstream-sync-$DATE` 分支在推成功後 `git -C $REPO branch -D` 掉（遠端那條才是交付物）。

## 禁止

- 不改、不 push `develop`／`main`；不 force push；不刪遠端分支
- 不安裝或升級依賴；不跑全量離線測試
- 不執行 `scripts/` 底下沒有 argparse 的腳本（§10，`--help` 也不行）
- 不碰 `.env`、`journal/`、`.memory/`
