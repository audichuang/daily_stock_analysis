#!/usr/bin/env python
"""整理一輪媒體點名／PTT 標的文的新列，當作排程 Claude 判讀的證據（唯讀 journal，不連網、不碰 DB）。

只看 ``extracted_at`` 不早於 ``--since`` 的列（``scripts/media_picks_job.sh`` 傳本輪開始時刻；跨午夜的一輪也不會漏）。
本腳本只整理、不下結論：好壞由 Claude 讀這份證據、再對挑出來的個股跑 ``tw_stock_dossier`` 後判斷。一輪約 160 檔、
全文約 160 KB，所以分兩層給：``--index`` 是精簡索引（約 20 KB，主 agent 用來挑檔），``--code`` 是單一檔的完整證據
（交給逐檔分析的子 agent）；``--json`` 是同一份資料的機器可讀版。三者必選其一（沒有全文模式）。輸出三塊：

- ``review``：代號沒把握的點名（``resolve`` 為 ``code_mismatch``／``fuzzy``／``unresolved``），附逐字稿路徑與已有的覆核
  結論，讓 Claude 判斷語音誤字；覆核結果另寫 ``journal/media-picks-review.jsonl``（原 journal 不改），下次執行時
  回灌：``correct`` 改掛到更正後的代號（本輪與歷史列都改，``voices`` 的 ``corrected_from`` 留原代號）、``not_stock`` 不計入個股。
- ``stocks``：本輪被點名的每一檔，看多、看空、中性都收。``voices`` 是每位講者的原話（理由、條件、題材、引述）；
  多空人數依**講者**去重（同台投顧在不同節目各記一次，用節目計數會偏高；沒有講者才退回節目）。``history`` 是本輪之前
  journal 裡的紀錄：首次被點名的日期與當時收盤、近 7 天被點名幾天，用來分辨「新出現」和「已經被喊了一陣子」。
- ``ptt``：本輪新的 PTT 標的文，附作者的理由與進退場條件。

    uv run --no-project python scripts/media_picks_summary.py --since 2026-10-26T23:00:00+08:00 --json
    uv run --no-project python scripts/media_picks_summary.py --since 2026-10-26T23:00:00+08:00 --index
    uv run --no-project python scripts/media_picks_summary.py --since 2026-10-26T23:00:00+08:00 --code 2330.TW
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
STOCK_INDEX = ROOT / "apps" / "dsa-web" / "public" / "stocks.index.json"
# 立場表：計數（bull／bear／neutral）與顯示標籤共用這一份，新增立場只改這裡
STANCES = {"bullish": ("bull", "多"), "bearish": ("bear", "空"), "avoid": ("bear", "避")}
UNRESOLVED = "未對到"  # corrected_from 的佔位：原本沒對到代號
RECENT_DAYS = 7
INDEX_FULL_VOICES = 2  # 講者數達到這個值的檔在索引裡給完整一行；只有一位講者的壓成短行
VOICE_FIELDS = ("speaker", "show", "kind", "stance", "theme", "reason", "condition", "quote", "corrected_from")


def _side(stance) -> str:
    """bull／bear／neutral：不在表裡的立場（neutral、缺值）都算中性。"""
    return STANCES.get(stance, ("neutral", "中"))[0]


def _label(stance) -> str:
    return STANCES.get(stance, ("neutral", "中"))[1]


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


def _official_names(index_path: Path) -> dict:
    """代號 -> 官方名稱（只收 .TW／.TWO；列格式 [code, bare_code, name, ...]）。"""
    with index_path.open(encoding="utf-8") as f:
        return {r[0]: r[2] for r in json.load(f) if r[0].endswith((".TW", ".TWO"))}


def _apply_reviews(rows: list, verdicts: list, stock_index: Path) -> list:
    """把覆核結論套到每一列（本輪與歷史都套，歷史才看得到更正後的代號）；回傳拷貝，不動輸入。

    比對鍵用原始 stock_code；同鍵多筆以最後一筆為準（檔案是 append-only）。
    只有 correct 且 corrected_code 非空才改代號，not_stock 清掉代號，confirm／unclear 不動。"""
    latest = {review_key(v): v for v in verdicts}
    if not any(review_key(r) in latest for r in rows):
        return rows
    names = None
    out = []
    for r in rows:
        v = latest.get(review_key(r))
        verdict = v and v.get("verdict")
        fixed = ((v.get("corrected_code") or "").strip() or None) if verdict == "correct" else None
        if verdict == "not_stock" or fixed:
            r = dict(r, stock_code=fixed, corrected_from=r.get("stock_code") or UNRESOLVED)
            if fixed:
                if names is None:  # 索引約 4 萬列，只在真的有更正時才載
                    names = _official_names(stock_index) if stock_index.exists() else {}
                r["name"] = names.get(fixed) or r.get("name_said")
        out.append(r)
    return out


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
        "first_named": next((r["date"] for r in prior if r.get("date")), None),  # 缺 date 的列排最前，要跳過
        "named_days_7d": len({r.get("date") for r in prior if (r.get("date") or "") >= recent_from}),
        "prior_bull_voices": len({_voice(r) for r in prior if _side(r.get("stance")) == "bull"}),
        "prior_bear_voices": len({_voice(r) for r in prior if _side(r.get("stance")) == "bear"}),
        "first_close": first_px and first_px.get("close"),
        "first_close_as_of": first_px and first_px.get("as_of"),
        "since_first_pct": _pct(close_now, first_px and first_px.get("close")),
    }


def _voices(st: dict) -> int:
    return st["bull_voices"] + st["bear_voices"] + st["neutral_voices"]


def summarize(since: datetime, journal_dir: Path = JOURNAL_DIR, transcript_dir: Path = TRANSCRIPT_DIR,
              stock_index: Path = STOCK_INDEX) -> dict:
    all_media = _read_jsonl(journal_dir / "media-picks.jsonl")
    ptt, _ = _split(_read_jsonl(journal_dir / "ptt-picks.jsonl"), since)
    verdicts = _read_jsonl(journal_dir / "media-picks-review.jsonl")
    reviewed = {review_key(r) for r in verdicts}

    # review 清單要顯示「原始」代號（覆核的比對鍵），所以用未套用覆核的列；個股統計用套用後的列
    raw_picks = [r for r in _split(all_media, since)[0] if r.get("resolve") != "no_picks"]
    media, media_before = _split(_apply_reviews(all_media, verdicts, stock_index), since)

    picks = [r for r in media if r.get("resolve") != "no_picks"]
    review = []
    for r in raw_picks:
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
        bull = {_voice(r) for r in rows if _side(r.get("stance")) == "bull"}
        bear = {_voice(r) for r in rows if _side(r.get("stance")) == "bear"}
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
    stocks.sort(key=lambda s: (-_voices(s), -s["bull_voices"], s["code"]))

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
    s = f"首次 {h['first_named'] or '?'}、近 {RECENT_DAYS} 天另有 {h['named_days_7d']} 天被點名（之前看多 {h['prior_bull_voices']} 位、看空 {h['prior_bear_voices']} 位）"
    if h["since_first_pct"] is not None:
        s += f"、首次至今 {h['since_first_pct']:+}%（{h['first_close_as_of']} 收 {h['first_close']}）"
    return s


def _header(s: dict) -> list:
    m = s["media"]
    lines = [f"# 本輪（{s['since']} 起）新增 {m['episodes']} 集、{m['picks']} 筆點名、{m['resolved']} 筆對到代號",
             "", f"## 待覆核代號 {sum(not r['already_reviewed'] for r in s['review'])} 筆"]
    for r in s["review"]:
        mark = "（已覆核）" if r["already_reviewed"] else ""
        lines.append(f"- {r['show']} {r['name_said']} → {r['stock_code'] or '未對到'}（{r['resolve']}，LLM {r['code_llm']}）{mark}")
    return lines


def _stock_block(st: dict) -> list:
    ptt = f"｜PTT 也有 {len(st['ptt'])} 篇" if st["ptt"] else ""
    lines = [f"### {st['name']} {st['code']}｜多 {st['bull_voices']}、空 {st['bear_voices']}、中性 {st['neutral_voices']}"
             f"｜{','.join(st['kinds'])}{ptt}",
             _fmt_data(st["data"]), "歷史：" + _fmt_history(st["history"])]
    for v in st["voices"]:
        who = f"{v['speaker'] or '（無講者）'}／{v['show']}／{v['kind'] or 'tv'}"
        if v["corrected_from"]:
            who += "（原未對到代號，覆核更正）" if v["corrected_from"] == UNRESOLVED else f"（原對到 {v['corrected_from']}，覆核更正）"
        parts = [f"題材：{v['theme']}" if v["theme"] else "", f"理由：{v['reason']}" if v["reason"] else "",
                 f"條件：{v['condition']}" if v["condition"] else "", f"「{v['quote']}」" if v["quote"] else ""]
        lines.append(f"- [{_label(v['stance'])}] {who}｜" + "｜".join(p for p in parts if p))
    return lines


def _ptt_flags(p: dict, with_resolve: bool = True) -> list:
    """索引與完整區塊共用；索引的代號已顯示在行內，不重複標「代號待確認」。"""
    return [f for f, on in (("代號待確認", with_resolve and p["resolve"] in REVIEW_RESOLVES), ("有編輯", p["edited"]),
                            ("附對帳單", p["has_statement"])) if on]


def _ptt_block(p: dict) -> list:
    flags = _ptt_flags(p)
    return [f"### {p['title']}（{p['stock_code'] or p['resolve']}，{p['category']}，推 {p['push_up']} 噓 {p['push_down']}）"
            + (f"｜{'、'.join(flags)}" if flags else ""),
            _fmt_data(p["data"]), f"理由：{p['reason'] or '—'}", f"進退場：{p['condition'] or '—'}"]


def _short(text, n=24) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[:n] + "…"


def _index_line(st: dict) -> str:
    """索引的一行：挑檔要用的事實（多空人數、來源類型、數據、熱度、題材），不放原話。"""
    d, h = st["data"] or {}, st["history"]
    yoy = (d.get("revenue_yoy_3m") or [None])[-1]
    heat = (f"首次 {h['first_named'][5:] if h['first_named'] else '?'}、7 天 {h['named_days_7d']} 天" + (
        f"、至今 {h['since_first_pct']:+}%" if h["since_first_pct"] is not None else "")) if h else "新出現"
    themes = list(dict.fromkeys(_short(v["theme"], 16) for v in st["voices"] if v["theme"]))[:3]
    ptt = f"｜PTT {len(st['ptt'])}" if st["ptt"] else ""
    if _voices(st) < INDEX_FULL_VOICES:
        (v,) = st["voices"][:1]
        return (f"- {st['name']} {st['code']}｜{_label(v['stance'])}｜{v['kind'] or 'tv'}"
                f"｜{_short(v['theme'], 16) or '—'}｜{heat}{ptt}")
    return (f"- {st['name']} {st['code']}｜多 {st['bull_voices']} 空 {st['bear_voices']} 中 {st['neutral_voices']}"
            f"｜{','.join(st['kinds'])}｜MA20 {d.get('vs_ma20_pct')}% MA60 {d.get('vs_ma60_pct')}% 5 日 {d.get('ret_5d_pct')}%"
            f" 營收 YoY {yoy}｜{heat}｜{'；'.join(themes) or '—'}{ptt}")


def _index(s: dict) -> str:
    """主 agent 挑檔用：多位講者的檔一行含數據與題材，只有一位講者的壓成短行；原話用 --code 取。"""
    multi = [st for st in s["stocks"] if _voices(st) >= INDEX_FULL_VOICES]
    single = [st for st in s["stocks"] if _voices(st) < INDEX_FULL_VOICES]
    lines = _header(s) + ["", f"## {len(multi)} 檔有 {INDEX_FULL_VOICES} 位以上講者（依講者數排序）"]
    lines += [_index_line(st) for st in multi]
    lines += ["", f"## {len(single)} 檔只有 1 位講者"] + [_index_line(st) for st in single]
    lines += ["", f"## PTT 新文章 {len(s['ptt'])} 篇"]
    for p in s["ptt"]:
        flags = "".join(f"｜{f}" for f in _ptt_flags(p, with_resolve=False))
        lines.append(f"- {_short(p['title'], 30)}｜{p['stock_code'] or p['resolve']}｜{_label(p['stance'])}"
                     f"｜推 {p['push_up']} 噓 {p['push_down']}{flags}")
    lines += ["", "單一檔的完整原話與 PTT 全文：media_picks_summary.py --since <同上> --code <代號>"]
    return "\n".join(lines)


def stock_detail(s: dict, code: str) -> str:
    """單一檔的完整證據（子 agent 用）：每位講者的原話、數據、歷史，以及談到這檔的 PTT 文。"""
    st = next((x for x in s["stocks"] if x["code"] == code), None)
    posts = [p for p in s["ptt"] if p["stock_code"] == code]
    if st is None and not posts:
        return f"本輪沒有人點名 {code}"
    lines = (_stock_block(st) if st else [f"### {code}（節目沒點名，只有 PTT）"])
    for p in posts:
        head, *rest = _ptt_block(p)
        lines += ["", "PTT：" + head.lstrip("# ")] + rest
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", required=True, help="本輪開始時刻（ISO 8601，帶時區）")
    out = ap.add_mutually_exclusive_group(required=True)
    out.add_argument("--json", action="store_true", help="輸出 JSON（排程用）")
    out.add_argument("--index", action="store_true", help="精簡索引（主 agent 挑檔用）")
    out.add_argument("--code", help="只輸出這一檔的完整證據，帶 .TW／.TWO（子 agent 用）")
    args = ap.parse_args(argv)
    since = datetime.fromisoformat(args.since)
    if since.tzinfo is None:
        since = since.astimezone()
    s = summarize(since)
    if args.json:
        print(json.dumps(s, ensure_ascii=False, indent=1))
    elif args.index:
        print(_index(s))
    else:
        print(stock_detail(s, args.code))
    return 0


if __name__ == "__main__":
    sys.exit(main())
