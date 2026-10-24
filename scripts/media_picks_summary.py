#!/usr/bin/env python
"""整理一輪媒體點名／PTT 標的文的新列，當作排程 Claude 判讀的證據（唯讀 journal，不連網、不碰 DB）。

只看 ``extracted_at`` 不早於 ``--since`` 的列（``scripts/media_picks_job.sh`` 傳本輪開始時刻；跨午夜的一輪也不會漏）。
本腳本只整理、不下結論：好壞由 Claude 讀這份證據、再對挑出來的個股跑 ``tw_stock_dossier`` 後判斷。輸出三塊：

- ``review``：代號沒把握的點名（``resolve`` 為 ``code_mismatch``／``fuzzy``／``unresolved``），附逐字稿路徑與已有的覆核
  結論，讓 Claude 判斷語音誤字；覆核結果另寫 ``journal/media-picks-review.jsonl``（原 journal 不改）。
- ``stocks``：本輪被點名的每一檔，看多、看空、中性都收。``voices`` 是每位講者的原話（理由、條件、題材、引述）；
  多空人數依**講者**去重（同台投顧在不同節目各記一次，用節目計數會偏高；沒有講者才退回節目）。``history`` 是本輪之前
  journal 裡的紀錄：首次被點名的日期與當時收盤、近 7 天被點名幾天，用來分辨「新出現」和「已經被喊了一陣子」。
- ``ptt``：本輪新的 PTT 標的文，附作者的理由與進退場條件。

    uv run --no-project python scripts/media_picks_summary.py --since 2026-10-26T23:00:00+08:00
    uv run --no-project python scripts/media_picks_summary.py --since 2026-10-26T23:00:00+08:00 --json
"""
import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JOURNAL_DIR = ROOT / "journal"
TRANSCRIPT_DIR = ROOT / "data" / "media_picks"
REVIEW_RESOLVES = ("code_mismatch", "fuzzy", "unresolved")
BULLISH = "bullish"
BEARISH = ("bearish", "avoid")
RECENT_DAYS = 7
VOICE_FIELDS = ("speaker", "show", "kind", "stance", "theme", "reason", "condition", "quote")


def _read_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _extracted_at(r: dict, tz):
    try:
        at = datetime.fromisoformat(r.get("extracted_at") or "")
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=tz)


def _split(rows: list, since: datetime) -> tuple[list, list]:
    """(本輪, 本輪之前)；沒有 extracted_at 的列兩邊都不算。"""
    now, before = [], []
    for r in rows:
        at = _extracted_at(r, since.tzinfo)
        if at is None:
            continue
        (now if at >= since else before).append(r)
    return now, before


def _voice(r: dict) -> str:
    # 同一位投顧在瘋狂股市福利社、理周TV 各記一次時 speaker 相同；沒有講者才用節目當單位
    return (r.get("speaker") or "").strip() or f"[{r.get('show')}]"


def _display_path(p: Path) -> str:
    return str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)


def review_key(r: dict) -> tuple:
    return (r.get("video_id"), r.get("name_said"), r.get("stock_code"))


def _pct(a, b):
    return round((a / b - 1) * 100, 1) if a and b else None


def _history(prior: list, since: datetime, close_now) -> dict | None:
    """本輪之前的點名紀錄。`date` 是節目播出日；收盤取該列 data（播出當時已知的資料）。"""
    if not prior:
        return None
    prior = sorted(prior, key=lambda r: (r.get("date") or "", r.get("extracted_at") or ""))
    recent_from = (since.date() - timedelta(days=RECENT_DAYS)).isoformat()
    first_px = next((r["data"] for r in prior if (r.get("data") or {}).get("close")), None)
    return {
        "first_named": prior[0].get("date"),
        "named_days_7d": len({r.get("date") for r in prior if (r.get("date") or "") >= recent_from}),
        "prior_bull_voices": len({_voice(r) for r in prior if r.get("stance") == BULLISH}),
        "prior_bear_voices": len({_voice(r) for r in prior if r.get("stance") in BEARISH}),
        "first_close": first_px and first_px.get("close"),
        "first_close_as_of": first_px and first_px.get("as_of"),
        "since_first_pct": _pct(close_now, first_px and first_px.get("close")),
    }


def summarize(since: datetime, journal_dir: Path = JOURNAL_DIR, transcript_dir: Path = TRANSCRIPT_DIR) -> dict:
    media, media_before = _split(_read_jsonl(journal_dir / "media-picks.jsonl"), since)
    ptt, _ = _split(_read_jsonl(journal_dir / "ptt-picks.jsonl"), since)
    reviewed = {review_key(r) for r in _read_jsonl(journal_dir / "media-picks-review.jsonl")}

    picks = [r for r in media if r.get("resolve") != "no_picks"]
    review = []
    for r in picks:
        if r.get("resolve") not in REVIEW_RESOLVES:
            continue
        transcript = transcript_dir / f"{r.get('video_id')}.txt"
        review.append({
            "video_id": r.get("video_id"),
            "show": r.get("show"),
            "date": r.get("date"),
            "name_said": r.get("name_said"),
            "name": r.get("name"),
            "code_llm": r.get("code_llm"),
            "stock_code": r.get("stock_code"),
            "resolve": r.get("resolve"),
            "stance": r.get("stance"),
            "quote": r.get("quote"),
            "transcript": _display_path(transcript) if transcript.exists() else None,
            "already_reviewed": review_key(r) in reviewed,
        })

    by_code: dict[str, list] = {}
    for r in picks:
        if r.get("stock_code"):
            by_code.setdefault(r["stock_code"], []).append(r)
    prior_by_code: dict[str, list] = {}
    for r in media_before:
        if r.get("stock_code") in by_code:
            prior_by_code.setdefault(r["stock_code"], []).append(r)
    ptt_by_code: dict[str, list] = {}
    for r in ptt:
        if r.get("stock_code"):
            ptt_by_code.setdefault(r["stock_code"], []).append(r.get("article_id"))

    stocks = []
    for code, rows in by_code.items():
        data = next((r["data"] for r in reversed(rows) if r.get("data")), None)
        bull = {_voice(r) for r in rows if r.get("stance") == BULLISH}
        bear = {_voice(r) for r in rows if r.get("stance") in BEARISH}
        other = {_voice(r) for r in rows} - bull - bear
        stocks.append({
            "code": code,
            "name": rows[-1].get("name") or rows[-1].get("name_said"),
            "bull_voices": len(bull),
            "bear_voices": len(bear),
            "neutral_voices": len(other),
            "kinds": sorted({r.get("kind") or "tv" for r in rows}),
            "voices": [{k: r.get(k) for k in VOICE_FIELDS} for r in rows],
            "data": data,
            "history": _history(prior_by_code.get(code, []), since, (data or {}).get("close")),
            "ptt": ptt_by_code.get(code, []),
        })
    stocks.sort(key=lambda s: (-(s["bull_voices"] + s["bear_voices"] + s["neutral_voices"]),
                               -s["bull_voices"], s["code"]))

    ptt_rows = [
        {k: r.get(k) for k in ("article_id", "url", "title", "author", "target", "stock_code", "resolve",
                               "category", "stance", "reason", "condition", "push_up", "push_down", "data")}
        | {"edited": bool(r.get("edited_at")), "has_statement": bool(r.get("has_statement"))}
        for r in ptt
    ]

    return {
        "since": since.isoformat(),
        "media": {
            "episodes": len({r.get("video_id") for r in media}),
            "picks": len(picks),
            "resolved": sum(1 for r in picks if r.get("stock_code")),
        },
        "review": review,
        "stocks": stocks,
        "ptt": ptt_rows,
    }


def _fmt_data(d) -> str:
    if not d:
        return "數據：無"
    yoy = "/".join("—" if v is None else f"{v:g}" for v in d.get("revenue_yoy_3m") or [])
    return (f"數據({d.get('as_of')})：收 {d.get('close')}｜距 MA20 {d.get('vs_ma20_pct')}%、MA60 {d.get('vs_ma60_pct')}%"
            f"｜距 60 日高 {d.get('from_60d_high_pct')}%｜5 日 {d.get('ret_5d_pct')}%｜近 3 月營收 YoY {yoy or '—'}"
            f"｜外資 5 日 {d.get('foreign_5d_lots')} 張、投信 5 日 {d.get('trust_5d_lots')} 張")


def _fmt_history(h) -> str:
    if not h:
        return "之前沒被點名過"
    s = f"首次 {h['first_named']}、近 {RECENT_DAYS} 天另有 {h['named_days_7d']} 天被點名（之前看多 {h['prior_bull_voices']} 位、看空 {h['prior_bear_voices']} 位）"
    if h["since_first_pct"] is not None:
        s += f"、首次至今 {h['since_first_pct']:+}%（{h['first_close_as_of']} 收 {h['first_close']}）"
    return s


def _text(s: dict) -> str:
    side = {"bullish": "多", "bearish": "空", "avoid": "避"}
    m = s["media"]
    lines = [f"# 本輪（{s['since']} 起）新增 {m['episodes']} 集、{m['picks']} 筆點名、{m['resolved']} 筆對到代號",
             "", f"## 待覆核代號 {sum(not r['already_reviewed'] for r in s['review'])} 筆"]
    for r in s["review"]:
        mark = "（已覆核）" if r["already_reviewed"] else ""
        lines.append(f"- {r['show']} {r['name_said']} → {r['stock_code'] or '未對到'}（{r['resolve']}，LLM {r['code_llm']}）{mark}")
    lines += ["", f"## 個股證據（{len(s['stocks'])} 檔，依講者數排序）"]
    for st in s["stocks"]:
        ptt = f"｜PTT 也有 {len(st['ptt'])} 篇" if st["ptt"] else ""
        lines += ["", f"### {st['name']} {st['code']}｜多 {st['bull_voices']}、空 {st['bear_voices']}、中性 {st['neutral_voices']}"
                      f"｜{','.join(st['kinds'])}{ptt}",
                  _fmt_data(st["data"]), "歷史：" + _fmt_history(st["history"])]
        for v in st["voices"]:
            who = f"{v['speaker'] or '（無講者）'}／{v['show']}／{v['kind'] or 'tv'}"
            parts = [f"題材：{v['theme']}" if v["theme"] else "", f"理由：{v['reason']}" if v["reason"] else "",
                     f"條件：{v['condition']}" if v["condition"] else "", f"「{v['quote']}」" if v["quote"] else ""]
            lines.append(f"- [{side.get(v['stance'], '中')}] {who}｜" + "｜".join(p for p in parts if p))
    lines += ["", f"## PTT 新文章 {len(s['ptt'])} 篇"]
    for p in s["ptt"]:
        flags = [f for f, on in (("代號待確認", p["resolve"] in REVIEW_RESOLVES), ("有編輯", p["edited"]),
                                 ("附對帳單", p["has_statement"])) if on]
        lines += ["", f"### {p['title']}（{p['stock_code'] or p['resolve']}，{p['category']}，推 {p['push_up']} 噓 {p['push_down']}）"
                      + (f"｜{'、'.join(flags)}" if flags else ""),
                  _fmt_data(p["data"]), f"理由：{p['reason'] or '—'}", f"進退場：{p['condition'] or '—'}"]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", required=True, help="本輪開始時刻（ISO 8601，帶時區）")
    ap.add_argument("--json", action="store_true", help="輸出 JSON（排程用）")
    args = ap.parse_args(argv)
    since = datetime.fromisoformat(args.since)
    if since.tzinfo is None:
        since = since.astimezone()
    s = summarize(since)
    print(json.dumps(s, ensure_ascii=False, indent=1) if args.json else _text(s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
