#!/usr/bin/env python
"""媒體點名逐檔判斷：一檔一個 ``claude -p``，平行跑完才返回（23:00 排程的主 agent 在前景呼叫）。

為什麼不用 Agent 工具開子 agent：在 Orca 排程裡 Agent 工具是背景執行，主 agent 一結束回合等通知，Orca 的 Stop hook
就當成排程做完、收掉 terminal，子 agent 跟著被砍（2026-10-25 實跑：連前一步的背景等待都這樣斷掉）。所以改由這支腳本
在同一個前景指令裡等全部回來。

每檔的證據由本腳本先備好、整份塞進提示詞：``media_picks_summary.py --code`` 的講者原話與 PTT 文，加上
``tw_stock_dossier.py --no-branch`` 的資料包。``claude -p`` 不給工具、不載 MCP、關掉所有 hook，並拿掉 ``ORCA_*``
環境變數（子程序結束時若觸發 Orca 的 Stop hook，會把排程的 terminal 收掉，見 ``docs/daily-report-ops.md``）。

挑哪幾檔、檢查回來的 JSON、research 上限、寫 journal 仍由主 agent 做；本腳本只負責「備證據＋問＋收」，不寫任何檔。
輸出（stdout）是 JSON 陣列，順序同輸入代號：``{"code", "ok", "result"}`` 或 ``{"code", "ok": false, "error", "raw"}``。

    uv run --no-project python scripts/media_picks_judge.py --since 2026-10-26T23:00:12+0800 3037.TW 2330.TW
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_CODES = 8
VERDICTS = ("research", "watch", "avoid")
REQUIRED = ("code", "verdict", "thesis", "evidence", "risks", "flip", "data_as_of")

BRIEF = """你在分析一檔台股，判斷財經節目／PTT 對它的看法站不站得住。下面附了兩份證據，只能根據它們判斷，不要假設你查得到別的資料。

一、講者原話：每位講者的題材、理由、條件、引述，播出當時的數據，之前被點名的紀錄，以及談到這檔的 PTT 文。
二、資料包：13 個月營收與 YoY、8 季毛利率／營益率／EPS、合約負債、法人 5 日與 20 日買賣超、融資融券、千張大戶、本益比與 3 年百分位，以及 SMC 結構，資料到最近一個交易日。

逐項想清楚再下判斷：
- 看多的理由是什麼？資料包支不支持？例如「訂單滿」要看合約負債和營收走勢，「EPS 上修」要看毛利率是否在擴張。
- 講者有說條件的話（「站回季線」「拉回 4500 以下」），現在符不符合。
- 看空或要避開的講者說了什麼，有沒有道理。
- 來源可不可信：投顧頻道在招攬會員，有利益衝突。好幾個不同節目的講者各自講，比同一位投顧在好幾個節目重複講更有份量。research 類通常比較有根據。PTT 作者是匿名網友，文章編輯過的話，內容可能在發文後改過。
- 時機：首次被點名到現在已經漲了多少？近 7 天是不是天天被點名（可能已經太熱）？股價現在在結構的哪裡？估值百分位高不高？法人 5 日和 20 日的方向是不是一致？融資有沒有暴增？
- 什麼事發生，你的看法就會改變。

判斷：`research`（值得隔天做完整研究）、`watch`（有道理但時機或證據不夠，要寫出缺了哪個證據）、`avoid`（理由站不住、太熱或有明顯風險）。拿不準就給 `watch`。這是研究判斷，不是買進建議：不要給價位，也不要說「買」。

最後只回一個 JSON 物件，不要有其他文字：
{"code": "<代號>", "verdict": "research|watch|avoid", "thesis": "兩三句：講者的邏輯是什麼、資料支不支持", "evidence": ["引用的關鍵數字，寫出數值與日期"], "risks": ["…"], "flip": "什麼變化會改變看法", "data_as_of": "資料包的基準日 YYYY-MM-DD"}
"""


def _load_summary():
    spec = importlib.util.spec_from_file_location("media_picks_summary", ROOT / "scripts" / "media_picks_summary.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def child_env(env=None) -> dict:
    """拿掉 ORCA_*：子程序的 Stop hook 帶著這些變數會讓 Orca 收掉排程的 terminal。"""
    return {k: v for k, v in (os.environ if env is None else env).items() if not k.startswith("ORCA_")}


def claude_cmd(model=None) -> list:
    cmd = [os.environ.get("MEDIA_PICKS_CLAUDE_BIN", "claude"), "-p", "--settings", '{"disableAllHooks":true}',
           "--tools", "", "--strict-mcp-config", "--no-session-persistence", "--output-format", "text"]
    return cmd + (["--model", model] if model else [])


def dossier(code: str, timeout: int) -> str:
    cmd = ["uv", "run", "--env-file", ".env", "python", "scripts/tw_stock_dossier.py", code, "--no-branch"]
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout, env=child_env())
    except subprocess.TimeoutExpired:
        return f"（資料包逾時 {timeout} 秒，沒有取到）"
    if p.returncode != 0 or not p.stdout.strip():
        return f"（資料包失敗 rc={p.returncode}：{p.stderr.strip()[-300:]}）"
    return p.stdout


def parse_verdict(text: str, code: str) -> dict:
    """取回應裡第一個 { 到最後一個 } 當 JSON，檢查欄位；不合格丟 ValueError（主 agent 會看到原因）。"""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("回應裡沒有 JSON 物件")
    obj = json.loads(text[start:end + 1])
    missing = [k for k in REQUIRED if k not in obj]
    if missing:
        raise ValueError(f"缺欄位 {missing}")
    if obj["verdict"] not in VERDICTS:
        raise ValueError(f"verdict 不合法：{obj['verdict']!r}")
    if obj["code"] != code:
        raise ValueError(f"code 對不上：回 {obj['code']!r}，問的是 {code}")
    return obj


def judge_one(code: str, media_text: str, dossier_text: str, model, timeout: int) -> dict:
    prompt = f"{BRIEF}\n代號：{code}\n\n## 一、講者原話\n{media_text}\n\n## 二、資料包\n{dossier_text}\n"
    try:
        p = subprocess.run(claude_cmd(model), input=prompt, capture_output=True, text=True, timeout=timeout,
                           env=child_env(), cwd="/tmp")
    except subprocess.TimeoutExpired:
        return {"code": code, "ok": False, "error": f"claude 逾時 {timeout} 秒", "raw": ""}
    if p.returncode != 0:
        return {"code": code, "ok": False, "error": f"claude rc={p.returncode}：{p.stderr.strip()[-300:]}",
                "raw": p.stdout[-500:]}
    try:
        return {"code": code, "ok": True, "result": parse_verdict(p.stdout, code)}
    except ValueError as e:  # json.JSONDecodeError 也是 ValueError
        return {"code": code, "ok": False, "error": str(e), "raw": p.stdout[-500:]}


def run(since: datetime, codes: list, jobs: int = MAX_CODES, model=None, timeout: int = 420,
        dossier_fn=dossier, summary_mod=None) -> list:
    mod = summary_mod or _load_summary()
    s = mod.summarize(since)

    def one(code):
        return judge_one(code, mod.stock_detail(s, code), dossier_fn(code, 180), model, timeout)

    with ThreadPoolExecutor(max_workers=max(1, min(jobs, len(codes)))) as ex:
        return list(ex.map(one, codes))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", required=True, help="本輪開始時刻（log 的 RESULT since= 那個值）")
    ap.add_argument("codes", nargs="+", help=f"要判斷的代號，帶 .TW／.TWO，最多 {MAX_CODES} 檔")
    ap.add_argument("--model", default=os.environ.get("MEDIA_PICKS_JUDGE_MODEL") or None,
                    help="claude -p 的模型；不給就用 CLI 預設（也可設 MEDIA_PICKS_JUDGE_MODEL）")
    ap.add_argument("--timeout", type=int, default=420, help="每檔 claude -p 的逾時秒數")
    args = ap.parse_args(argv)
    if len(args.codes) > MAX_CODES:
        ap.error(f"最多 {MAX_CODES} 檔")
    since = datetime.fromisoformat(args.since)
    if since.tzinfo is None:
        since = since.astimezone()
    print(json.dumps(run(since, args.codes, model=args.model, timeout=args.timeout), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
