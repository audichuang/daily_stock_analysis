#!/usr/bin/env python
"""整理一輪媒體點名／PTT 標的文的新列，給排程的 Claude 判讀與寫 Bark 用（唯讀 journal，不連網、不碰 DB）。

只看 ``extracted_at`` 不早於 ``--since`` 的列（``scripts/media_picks_job.sh`` 傳本輪開始時刻；跨午夜的一輪也不會漏）。
輸出三塊：

- ``review``：代號沒把握的點名（``resolve`` 為 ``code_mismatch``／``fuzzy``／``unresolved``），附逐字稿路徑與已有的覆核
  結論，讓 Claude 判斷語音誤字；覆核結果另寫 ``journal/media-picks-review.jsonl``（原 journal 不改）。
- ``bullish``：看多排行，依**講者**去重（同台投顧在不同節目各記一次，用 ``show`` 計數會偏高；沒有講者才退回節目）。
- ``ptt``：本輪新的 PTT 標的文。

``data_ok``＝站上 MA20／MA60 且最近一個月營收 YoY ≥20%、沒比三個月前降超過 10 個百分點；未回測，只是研究名單。

    uv run --no-project python scripts/media_picks_summary.py --since 2026-10-26T23:00:00+08:00
    uv run --no-project python scripts/media_picks_summary.py --since 2026-10-26T23:00:00+08:00 --json
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JOURNAL_DIR = ROOT / "journal"
TRANSCRIPT_DIR = ROOT / "data" / "media_picks"
REVIEW_RESOLVES = ("code_mismatch", "fuzzy", "unresolved")
BULLISH = "bullish"
BEARISH = ("bearish", "avoid")


def _read_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _extracted_since(rows: list, since: datetime) -> list:
    out = []
    for r in rows:
        try:
            at = datetime.fromisoformat(r.get("extracted_at") or "")
        except ValueError:
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=since.tzinfo)
        if at >= since:
            out.append(r)
    return out


def data_ok(d) -> bool:
    if not d:
        return False
    yoy = [v for v in d.get("revenue_yoy_3m") or [] if v is not None]
    above = (d.get("vs_ma20_pct") or -99) > 0 and (d.get("vs_ma60_pct") or -99) > 0
    return above and len(yoy) == 3 and yoy[-1] >= 20 and yoy[-1] >= yoy[0] - 10


def _voice(r: dict) -> str:
    # 同一位投顧在瘋狂股市福利社、理周TV 各記一次時 speaker 相同；沒有講者才用節目當單位
    return (r.get("speaker") or "").strip() or f"[{r.get('show')}]"


def _display_path(p: Path) -> str:
    return str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)


def review_key(r: dict) -> tuple:
    return (r.get("video_id"), r.get("name_said"), r.get("stock_code"))


def summarize(since: datetime, journal_dir: Path = JOURNAL_DIR, transcript_dir: Path = TRANSCRIPT_DIR) -> dict:
    media = _extracted_since(_read_jsonl(journal_dir / "media-picks.jsonl"), since)
    ptt = _extracted_since(_read_jsonl(journal_dir / "ptt-picks.jsonl"), since)
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

    bull, bear, kinds, shows, name, data = {}, {}, {}, {}, {}, {}
    for r in picks:
        code = r.get("stock_code")
        if not code:
            continue
        name[code] = r.get("name") or r.get("name_said")
        data[code] = r.get("data") or data.get(code)
        if r.get("stance") == BULLISH:
            bull.setdefault(code, set()).add(_voice(r))
            shows.setdefault(code, set()).add(r.get("show"))
            kinds.setdefault(code, set()).add(r.get("kind") or "tv")
        elif r.get("stance") in BEARISH:
            bear.setdefault(code, set()).add(_voice(r))
    bullish = [
        {
            "code": c,
            "name": name[c],
            "bull_voices": len(bull[c]),
            "bear_voices": len(bear.get(c, ())),
            "shows": sorted(s for s in shows[c] if s),
            "kinds": sorted(kinds[c]),
            "data_ok": data_ok(data[c]),
            "data": data[c],
        }
        for c in sorted(bull, key=lambda c: (-len(bull[c]), c))
    ]

    ptt_rows = [
        {
            "article_id": r.get("article_id"),
            "url": r.get("url"),
            "target": r.get("target"),
            "stock_code": r.get("stock_code"),
            "resolve": r.get("resolve"),
            "stance": r.get("stance"),
            "push_up": r.get("push_up"),
            "push_down": r.get("push_down"),
            "edited": bool(r.get("edited_at")),
            "has_statement": bool(r.get("has_statement")),
            "data_ok": data_ok(r.get("data")),
            "data": r.get("data"),
        }
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
        "bullish": bullish,
        "ptt": ptt_rows,
    }


def _text(s: dict) -> str:
    m = s["media"]
    lines = [f"本輪（{s['since']} 起）新增 {m['episodes']} 集、{m['picks']} 筆點名、{m['resolved']} 筆對到代號",
             f"待覆核代號 {sum(not r['already_reviewed'] for r in s['review'])} 筆"]
    for r in s["review"]:
        mark = "（已覆核）" if r["already_reviewed"] else ""
        lines.append(f"  {r['show']} {r['name_said']} → {r['stock_code'] or '未對到'}（{r['resolve']}，LLM {r['code_llm']}）{mark}")
    lines.append("看多排行（講者去重）")
    for b in s["bullish"][:15]:
        lines.append(f"  {b['name']}({b['code']}) 看多{b['bull_voices']} 看空{b['bear_voices']} "
                     f"數據{'✓' if b['data_ok'] else '✗'} {','.join(b['kinds'])}")
    lines.append(f"PTT 新文章 {len(s['ptt'])}")
    for p in s["ptt"]:
        side = {"bullish": "多", "bearish": "空"}.get(p["stance"], "中性")
        flags = [f for f, on in (("待確認", p["resolve"] in ("code_mismatch", "fuzzy", "unresolved")),
                                 ("有編輯", p["edited"]), ("附對帳單", p["has_statement"])) if on]
        lines.append(f"  {(p['target'] or '')[:16]} {p['stock_code'] or p['resolve']} {side} "
                     f"推{p['push_up']}噓{p['push_down']} 數據{'✓' if p['data_ok'] else '✗'} {' '.join(flags)}".rstrip())
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
