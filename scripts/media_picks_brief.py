#!/usr/bin/env python
"""07:30 盤前判讀用的「最近一輪媒體點名」簡報：讀 journal/media-picks-verdicts.jsonl 最近一輪的判斷，濃縮成一小塊給 morning agent。

唯讀、不連網、不跑 LLM、不下結論：只挑列、對持股、截短文字。同一 (date, code) 有多列時以檔案裡最後一列為準。
最近一輪的日期比 ``--today`` 早超過 ``--max-age-days``（預設 4 個日曆天，週五晚上的一輪週一早上還看得到；剛好 4 天
不算過期）就只印一行「已過期」。持股清單預設以子行程跑 ``scripts/portfolio_codes.py``（``uv run --env-file .env``，
60 秒逾時；它唯讀應用庫），也可用 ``--holdings <json>`` 直接給檔。取不到只印「持股清單取不到」、其餘照印。

    uv run --env-file .env python scripts/media_picks_brief.py
    uv run python scripts/media_picks_brief.py --holdings logs/media_picks_job_<id>.holdings.json --json

這是參考資料，不是買進訊號；research 列要進候選還得過 tw-swing-research 自己的進場規則。
"""
import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JOURNAL_DIR = ROOT / "journal"
HOLDINGS_TIMEOUT_SECONDS = 60
THESIS_MAX = 60
FLIP_MAX = 80
VERDICT_ORDER = {"avoid": 0, "research": 1, "watch": 2}
TAIPEI = timezone(timedelta(hours=8))


def _read_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue  # 壞列略過，簡報不因單列中斷
    return rows


def _short(text, limit: int) -> str:
    t = " ".join(str(text or "").split())
    return t if len(t) <= limit else t[:limit].rstrip() + "…"


def _valid_date(value) -> bool:
    """date 欄必須是 YYYY-MM-DD；壞列略過，不能讓整份簡報崩掉。"""
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError):
        return False
    return True


def latest_round(rows: list) -> tuple[str | None, list]:
    """最近一個 date 的列；同 (date, code) 以最後一列為準。"""
    dated = [r for r in rows if _valid_date(r.get("date")) and r.get("code")]
    if not dated:
        return None, []
    latest = max(r["date"] for r in dated)
    by_code: dict = {}
    for r in dated:
        if r["date"] == latest:
            by_code[r["code"]] = r  # 後面的列覆蓋前面
    return latest, list(by_code.values())


def build(rows: list, today: date, max_age_days: int, held) -> dict:
    """held：{code: {...}} 或 None（取不到）。回傳純資料，render() 再排版。"""
    latest, picked = latest_round(rows)
    if latest is None:
        return {"status": "empty"}
    age = (today - date.fromisoformat(latest)).days
    if age > max_age_days:
        return {"status": "stale", "date": latest, "age_days": age}

    def item(r):
        return {"code": r["code"], "name": r.get("name") or "", "verdict": r.get("verdict"),
                "thesis": _short(r.get("thesis"), THESIS_MAX), "flip": _short(r.get("flip"), FLIP_MAX)}

    rows_ = [item(r) for r in picked]
    held_codes = set(held or {})
    held_rows = sorted((r for r in rows_ if r["code"] in held_codes),
                       key=lambda r: (VERDICT_ORDER.get(r["verdict"], 9), r["code"]))
    rest = [r for r in rows_ if r["code"] not in held_codes]
    return {
        "status": "ok", "date": latest, "holdings_available": held is not None,
        "held": held_rows,
        "research": [r for r in rest if r["verdict"] == "research"],
        "watch": [r for r in rest if r["verdict"] == "watch"],
        "avoid": [r for r in rest if r["verdict"] == "avoid"],
    }


def render(b: dict) -> str:
    if b["status"] == "empty":
        return "沒有媒體點名判斷"
    if b["status"] == "stale":
        return f"（最近一輪媒體點名判斷是 {b['date']}，已過期）"
    lines = [f"===== 最近一輪媒體點名（{b['date']}，僅供參考，不是買進訊號）====="]
    if not b["holdings_available"]:
        lines.append("持股清單取不到")
    if b["held"]:
        lines.append("【持股相關】")
        lines += [f"- {r['name']} {r['code']}｜{r['verdict']}｜{r['thesis']}｜翻轉：{r['flip']}" for r in b["held"]]
    if b["research"]:
        lines.append("【research】")
        lines += [f"- {r['name']} {r['code']}｜{r['thesis']}｜翻轉：{r['flip']}" for r in b["research"]]
    if b["watch"]:
        lines.append("【watch 的翻轉條件】")
        lines += [f"- {r['name']} {r['code']}｜{r['flip']}" for r in b["watch"]]
    if b["avoid"]:
        lines.append("避開：" + "、".join(r["name"] or r["code"] for r in b["avoid"]))
    return "\n".join(lines)


def fetch_holdings():
    """子行程跑 portfolio_codes.py；成功回 {code: row}，任何失敗回 None。"""
    try:
        p = subprocess.run(["uv", "run", "--env-file", ".env", "python", "scripts/portfolio_codes.py"],
                           cwd=ROOT, capture_output=True, text=True, timeout=HOLDINGS_TIMEOUT_SECONDS)
        data = json.loads(p.stdout.strip().splitlines()[-1])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None
    return _held_map(data)


def _held_map(data):
    if not isinstance(data, dict) or data.get("error") or not isinstance(data.get("codes"), list):
        return None
    return {c["code"]: c for c in data["codes"] if isinstance(c, dict) and c.get("code")}


def load_holdings_file(path: Path):
    try:
        return _held_map(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def main(argv=None, holdings_fn=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--journal-dir", type=Path, default=JOURNAL_DIR)
    ap.add_argument("--today", help="YYYY-MM-DD，預設今天（台北）")
    ap.add_argument("--max-age-days", type=int, default=4)
    ap.add_argument("--holdings", type=Path, help="portfolio_codes.py 輸出的 JSON；不給就跑子行程")
    ap.add_argument("--json", action="store_true", help="機器可讀輸出")
    args = ap.parse_args(argv)
    today = date.fromisoformat(args.today) if args.today else datetime.now(TAIPEI).date()
    rows = _read_jsonl(args.journal_dir / "media-picks-verdicts.jsonl")
    held = None
    if rows:  # 沒有判斷就不必查持股
        if args.holdings:
            held = load_holdings_file(args.holdings)
        else:
            held = (holdings_fn or fetch_holdings)()
    b = build(rows, today, args.max_age_days, held)
    print(json.dumps(b, ensure_ascii=False) if args.json else render(b))
    return 0


if __name__ == "__main__":
    sys.exit(main())
