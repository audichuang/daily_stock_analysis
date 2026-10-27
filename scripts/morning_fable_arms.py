#!/usr/bin/env python3
"""盤前判讀的 Fable 獨立臂：只看凍結的 `make morning` 輸出（evidence_pack），不讀 Claude 臂與 journal。

流程（final-decision 第 7 項流程 B）：外部基準率 → 初始機率 → 上調／下調的證據 → 07:30 最終機率，
最後輸出一個 JSON 物件（`p_close_up`／`p_oc_up`／`p_gap_up`）。結果一臂一列追加到
`journal/morning-arms.jsonl`（append-only，鍵＝(date, model_version)，同鍵不重寫）。

隔離：`claude -p` 不載入任何全域指示、MCP、skills、工具，cwd 是空暫存目錄；user prompt 走 stdin。
單臂失敗（CLI 非 0、逾時、is_error、解析失敗）也寫一列 error 非空、p 全 null 的紀錄，結束碼仍是 0，
不得讓盤前流程失敗。`MORNING_FABLE_MODEL` 沒設就跳過（不配置也可運行）。

用法：
    uv run python scripts/morning_fable_arms.py              # 讀今天最早一份 pack，呼叫並寫一列
    uv run python scripts/morning_fable_arms.py --dry-run    # 印 prompt 與 hash，不呼叫、不寫檔
    uv run python scripts/morning_fable_arms.py --print-hash # 只印 pack 的 sha256（給 Claude 臂抄進 morning-calls）
"""

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACK_DIR = ROOT / "reports" / "morning-packs"
ARMS = ROOT / "journal" / "morning-arms.jsonl"
MODEL_ENV = "MORNING_FABLE_MODEL"
MODEL_VERSION = "fable"
TAIPEI = dt.timezone(dt.timedelta(hours=8))
CUTOFF_HOUR = 9           # 台北時間過 09:00 才寫入的判讀不計分
REASON_MAX = 1500
TARGETS = ("p_close_up", "p_oc_up", "p_gap_up")

SYSTEM_PROMPT = (
    "你是台股盤前機率預測員。你沒有任何工具、檔案或網路，只能依使用者提供的證據包推論。"
    "只依證據包與你自己的一般知識作答，不要假設還有其他資訊。"
)

# 三個目標的定義與 skill tw-morning-call Step 4「機率輸出」逐字相同（測試比對）。
USER_TEMPLATE = """以下是今天 07:30 凍結的盤前證據包（`make morning` 的完整輸出）。請預測三個目標的機率。

三個 0~1 小數（不是百分數）的機率：

- `p_close_up`：收盤高於前一日收盤（**主目標**）
- `p_oc_up`：收盤高於當日官方開盤（**主目標**）
- `p_gap_up`：09:05 加權指數高於前一日收盤（次要）

機率要先列基準率再調整，順序固定：
1. 外部基準率（例如近一年該目標的上漲頻率；證據包有就用，沒有就用你的一般知識並註明）
2. 初始機率（等於基準率）
3. 上調／下調的證據（每條寫方向與大約幅度）
4. 07:30 最終機率

沒有證據支持就停在基準率附近，不要為了顯得有觀點而離開基準率。三個機率各自獨立估，不必互相加總。

最後輸出一個 JSON 物件（放在回答最後，之後不要再寫任何文字），格式：
{{"p_close_up": 0.0, "p_oc_up": 0.0, "p_gap_up": 0.0, "reason": "基準率→調整的簡述"}}

===== 證據包開始 =====
{pack}
===== 證據包結束 =====
"""


def prompt_hash():
    """模板（system＋user，不含 pack）的 sha256。"""
    return hashlib.sha256((SYSTEM_PROMPT + "\n\x00\n" + USER_TEMPLATE).encode("utf-8")).hexdigest()


def pack_hash(pack_bytes):
    return hashlib.sha256(pack_bytes).hexdigest()


def build_user_prompt(pack_text):
    return USER_TEMPLATE.format(pack=pack_text)


def taipei_now():
    return dt.datetime.now(TAIPEI)


def find_pack(day, pack_dir=PACK_DIR):
    """該日最早一份 pack：`<date>.txt` 先於 `<date>.<HHMM>.txt`（07:30 那份才是凍結的）。"""
    first = Path(pack_dir) / f"{day}.txt"
    if first.exists():
        return first
    later = sorted(Path(pack_dir).glob(f"{day}.*.txt"))
    return later[0] if later else None


def _last_json_object(text):
    """文字裡最後一個頂層 JSON 物件（dict）；沒有回 None。"""
    dec, i, last, end = json.JSONDecoder(), 0, None, 0
    while True:
        i = text.find("{", max(i, end))
        if i < 0:
            return last
        try:
            obj, stop = dec.raw_decode(text, i)
        except ValueError:
            i += 1
            continue
        if isinstance(obj, dict):
            last, end = (obj, text[:i]), stop
        else:
            end = stop


def parse_result(text):
    """模型回答 → (p dict, reason, error)。三個 p 必須是 0~1 有限小數，否則該欄 None 並記原因。"""
    found = _last_json_object(text or "")
    ps = {k: None for k in TARGETS}
    if found is None:
        return ps, (text or "").strip()[:REASON_MAX], "回答裡找不到 JSON 物件"
    obj, before = found
    bad = []
    for k in TARGETS:
        v = obj.get(k)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1:
            bad.append(f"{k}={v!r}")
        else:
            ps[k] = float(v)
    reason = obj.get("reason") if isinstance(obj.get("reason"), str) else before
    return ps, reason.strip()[:REASON_MAX], ("機率欄不合法（要 0~1 小數）：" + "、".join(bad)) if bad else None


def call_claude(model, pack_text, timeout):
    """跑一次隔離的 claude -p；回 (cli_json dict | None, error | None)。"""
    exe = shutil.which("claude")
    if not exe:
        return None, "找不到 claude 可執行檔"
    argv = [exe, "-p", "--model", model, "--output-format", "json", "--tools", "", "--strict-mcp-config",
            "--no-session-persistence", "--setting-sources", "", "--system-prompt", SYSTEM_PROMPT]
    env = {k: v for k, v in os.environ.items() if not k.startswith("ORCA_")}
    with tempfile.TemporaryDirectory(prefix="morning-fable-") as cwd:
        try:
            proc = subprocess.run(argv, input=build_user_prompt(pack_text), capture_output=True, text=True,
                                  cwd=cwd, timeout=timeout, env=env)
        except subprocess.TimeoutExpired:
            return None, f"逾時（{timeout}s）"
        except OSError as exc:
            return None, f"無法執行 claude：{exc}"
    if proc.returncode != 0:
        return None, f"claude 結束碼 {proc.returncode}：{(proc.stderr or proc.stdout or '').strip()[:300]}"
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        return None, "claude 輸出不是 JSON"
    if not isinstance(data, dict):
        return None, "claude 輸出不是 JSON 物件"
    if data.get("is_error"):
        return None, f"claude is_error：{str(data.get('result'))[:300]}"
    return data, None


def build_row(day, pack_bytes, *, ps, reason, error, cli_model, latency_s, cost_usd, now):
    cutoff = dt.datetime.combine(dt.date.fromisoformat(day), dt.time(CUTOFF_HOUR), tzinfo=TAIPEI)
    return {"date": day, "model_version": MODEL_VERSION, "cli_model": cli_model, **ps, "reason": reason,
            "input_snapshot_hash": pack_hash(pack_bytes), "prompt_hash": prompt_hash(),
            "latency_s": latency_s, "cost_usd": cost_usd,
            "decided_at": now.isoformat(timespec="seconds"),
            "exclude_from_scoring": now > cutoff, "error": error}


def has_row(path, day):
    path = Path(path)
    if not path.exists():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("date") == day and r.get("model_version") == MODEL_VERSION:
            return True
    return False


def append_row(path, row):
    """鍵 (date, model_version) 已存在就不寫；回是否寫入。檢查與寫入在同一把 flock 底下。"""
    path = Path(path)
    with path.open("a+", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            if has_row(path, row["date"]):
                return False
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description="盤前判讀的 Fable 獨立臂（只看凍結的 make morning 輸出）")
    ap.add_argument("--date", default=None, help="判讀日 YYYY-MM-DD（預設台北今天）")
    ap.add_argument("--pack", default=None, help="evidence_pack 路徑（預設 reports/morning-packs 那天最早一份）")
    ap.add_argument("--dry-run", action="store_true", help="印 prompt 與 hash，不呼叫、不寫檔")
    ap.add_argument("--print-hash", action="store_true", help="只印 pack bytes 的 sha256")
    ap.add_argument("--timeout", type=int, default=300, help="claude 呼叫逾時秒數（預設 300）")
    ap.add_argument("--journal", default=str(ARMS), help="輸出 jsonl（預設 journal/morning-arms.jsonl）")
    a = ap.parse_args(argv)

    day = a.date or taipei_now().date().isoformat()
    model = os.environ.get(MODEL_ENV, "").strip()
    if not a.dry_run and not a.print_hash and not model:
        print(f"{MODEL_ENV} 未設，跳過 Fable 臂")
        return 0
    pack = Path(a.pack) if a.pack else find_pack(day)
    if pack is None or not pack.exists():
        print(f"找不到 {day} 的 evidence_pack（reports/morning-packs/），跳過 Fable 臂")
        return 1 if a.print_hash else 0
    pack_bytes = pack.read_bytes()
    if a.print_hash:
        print(pack_hash(pack_bytes))
        return 0
    pack_text = pack_bytes.decode("utf-8", errors="replace")
    if a.dry_run:
        print(f"# system\n{SYSTEM_PROMPT}\n\n# user\n{build_user_prompt(pack_text)}")
        print(f"pack={pack} input_snapshot_hash={pack_hash(pack_bytes)} prompt_hash={prompt_hash()}")
        return 0
    if has_row(a.journal, day):
        print(f"{day} 已有 {MODEL_VERSION} 臂紀錄，不重寫")
        return 0

    t0 = time.monotonic()
    data, error = call_claude(model, pack_text, a.timeout)
    latency = round(time.monotonic() - t0, 1)
    ps, reason, cli_model, cost = {k: None for k in TARGETS}, "", None, None
    if data is not None:
        ps, reason, error = parse_result(str(data.get("result") or ""))
        usage = data.get("modelUsage")
        cli_model = next(iter(usage), None) if isinstance(usage, dict) and usage else None
        cost = data.get("total_cost_usd")
    row = build_row(day, pack_bytes, ps=ps, reason=reason, error=error, cli_model=cli_model,
                    latency_s=latency, cost_usd=cost, now=taipei_now())
    wrote = append_row(a.journal, row)
    print(f"Fable 臂 {day}：{'已寫入' if wrote else '已有同鍵紀錄，不重寫'}"
          + (f"；error：{error}" if error else f"；p_close_up={ps['p_close_up']} p_oc_up={ps['p_oc_up']} "
                                             f"p_gap_up={ps['p_gap_up']}")
          + f"（{latency}s、名目 ${cost}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
