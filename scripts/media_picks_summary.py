#!/usr/bin/env python
"""整理一輪媒體點名／PTT 標的文的新列，當作排程 Claude 判讀的證據（唯讀 journal，不連網、不碰 DB）。

只看 ``extracted_at`` 不早於 ``--since`` 的列（``scripts/media_picks_job.sh`` 傳本輪開始時刻；跨午夜的一輪也不會漏）。
本腳本只整理、不下結論：好壞由 Claude 讀這份證據、再對挑出來的個股跑 ``tw_stock_dossier`` 後判斷。一輪約 160 檔、
全文約 160 KB，所以分兩層給：``--index`` 是精簡索引（約 20 KB，主 agent 用來挑檔），``--code`` 是單一檔的完整證據
（交給 ``media_picks_judge.py`` 的逐檔判斷）；``--json`` 是同一份資料的機器可讀版；``--unjudged`` 是下面 ``unjudged`` 的完整清單。
輸出模式必選其一（沒有全文模式）。輸出這幾塊：

- ``review``：代號沒把握的點名（``resolve`` 為 ``code_mismatch``／``fuzzy``／``unresolved``），附逐字稿路徑與已有的覆核
  結論，讓 Claude 判斷語音誤字；覆核結果另寫 ``journal/media-picks-review.jsonl``（原 journal 不改），下次執行時
  回灌：``correct`` 改掛到更正後的代號（本輪與歷史列都改，``voices`` 的 ``corrected_from`` 留原代號）、``not_stock`` 不計入個股。
- ``stocks``：本輪被點名的每一檔，看多、看空、中性都收。``voices`` 是每位講者的原話（理由、條件、題材、引述）；
  多空人數依**講者**去重（同台投顧在不同節目各記一次，用節目計數會偏高；沒有講者才退回節目）。``history`` 是本輪之前
  journal 裡的紀錄：首次被點名的日期與當時收盤、近 7 天被點名幾天，用來分辨「新出現」和「已經被喊了一陣子」。
- ``ptt``：本輪新的 PTT 標的文，附作者的理由與進退場條件。
- ``holdings``（只有帶 ``--holdings`` 才有內容）：``scripts/portfolio_codes.py`` 的持股清單 × 本輪點名。每檔 ``stocks`` 帶
  ``held``；``holdings.mentioned`` 列出被節目或 PTT 點名的持股（多空中性人數、PTT 篇數、``alert``＝有看空／避開的講者
  或看空的 PTT 文）。``--index`` 第一段就是這份，``--code`` 對持股開頭標「（你持有這檔）」。
- ``unjudged``：本輪之前 7 天內被點名、判斷檔（``media-picks-verdicts.jsonl``）沒有涵蓋那次點名的檔，附點名時段、多空人數、
  上次判斷、``media_picks_judge.py --log`` 記下的判斷紀錄（成功或失敗原因），以及每一輪的點名數與判斷列數。只給事實：
  某輪只判了一部分（逾時、``ok: false``、主 agent 中途被收掉）時要不要補判、補哪幾檔，由主 agent 讀完自己決定。
  ``--index`` 只放每輪一行與「判斷過卻沒寫進判斷檔」的檔，完整清單用 ``--unjudged``。

    uv run --no-project python scripts/media_picks_summary.py --since 2026-10-26T23:00:00+08:00 --json
    uv run --no-project python scripts/media_picks_summary.py --since 2026-10-26T23:00:00+08:00 --index
    uv run --no-project python scripts/media_picks_summary.py --since 2026-10-26T23:00:00+08:00 --code 2330.TW
    uv run --no-project python scripts/media_picks_summary.py --since ... --index --holdings logs/media_picks_job_<id>.holdings.json
"""
import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JOURNAL_DIR = ROOT / "journal"
LOGS_DIR = ROOT / "logs"
TRANSCRIPT_DIR = ROOT / "data" / "media_picks"
REVIEW_RESOLVES = ("code_mismatch", "fuzzy", "unresolved")
STOCK_INDEX = ROOT / "apps" / "dsa-web" / "public" / "stocks.index.json"
# 立場表：計數（bull／bear／neutral）與顯示標籤共用這一份，新增立場只改這裡
STANCES = {"bullish": ("bull", "多"), "bearish": ("bear", "空"), "avoid": ("bear", "避")}
UNRESOLVED = "未對到"  # corrected_from 的佔位：原本沒對到代號
RECENT_DAYS = 7
INDEX_FULL_VOICES = 2  # 講者數達到這個值的檔在索引裡給完整一行；只有一位講者的壓成短行
# media_picks_judge.py --log 追加到該輪 log 的判斷紀錄：「<時刻> | JUDGE <JSON>」，JSON 是腳本自己寫的 {at, since, code, ok, error}
JUDGE_TAG = "| JUDGE "
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
                r["data"] = None  # 快照是照原（錯的）代號抓的，留著會把別檔的收盤價算進這檔的數據與歷史
        out.append(r)
    return out


def _pct(a, b):
    return round((a / b - 1) * 100, 1) if a and b else None


def _since_first(now: dict | None, first: dict | None) -> tuple:
    """首次被點名至今的漲跌 % 與是否已還原。

    快照的 close 是各自 as_of 當天的原始收盤，跨除權息／分割直接相除會把配息當成下跌（分割更會差到 -75%）。
    兩份快照都有 cum_adj_factor（上市以來到 as_of 的因子連乘）時換到同一基準：
    (close_now / F_now) / (close_first / F_first) - 1。舊列沒有這個欄位，退回原始收盤相除並標成未還原。"""
    a, b = (now or {}).get("close"), (first or {}).get("close")
    fa, fb = (now or {}).get("cum_adj_factor"), (first or {}).get("cum_adj_factor")
    if a and b and fa and fb:
        return _pct(a / fa, b / fb), True
    return _pct(a, b), False


def _history(prior: list, since: datetime, data_now) -> dict | None:
    """本輪之前的點名紀錄。`date` 是節目播出日；收盤取該列 data（播出當時已知的資料）。"""
    if not prior:
        return None
    prior = sorted(prior, key=lambda r: (r.get("date") or "", r.get("extracted_at") or ""))
    recent_from = (since.date() - timedelta(days=RECENT_DAYS)).isoformat()
    first_px = next((r["data"] for r in prior if (r.get("data") or {}).get("close")), None)
    pct, adjusted = _since_first(data_now, first_px)
    return {
        "first_named": next((r["date"] for r in prior if r.get("date")), None),  # 缺 date 的列排最前，要跳過
        "named_days_7d": len({r.get("date") for r in prior if (r.get("date") or "") >= recent_from}),
        "prior_bull_voices": len({_voice(r) for r in prior if _side(r.get("stance")) == "bull"}),
        "prior_bear_voices": len({_voice(r) for r in prior if _side(r.get("stance")) == "bear"}),
        "first_close": first_px and first_px.get("close"),
        "first_close_as_of": first_px and first_px.get("as_of"),
        "since_first_pct": pct,
        "since_first_adjusted": adjusted,  # False＝有一端是舊快照（沒有 cum_adj_factor），跨除權息會失真
    }


def _voices(st: dict) -> int:
    return st["bull_voices"] + st["bear_voices"] + st["neutral_voices"]


def load_holdings(path) -> dict | None:
    """讀 portfolio_codes.py 的輸出；沒給、檔不存在、壞掉、內含 error 一律回 None（stderr 記一行，不中斷摘要）。"""
    if not path:
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("error") or not isinstance(data.get("codes"), list):
            raise ValueError(data.get("error") if isinstance(data, dict) and data.get("error") else "格式不符")
        return {c["code"]: c for c in data["codes"] if isinstance(c, dict) and c.get("code")}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"持股清單 {path} 讀不到，略過（{exc}）", file=sys.stderr)
        return None


def _holdings_block(stocks: list, ptt_rows: list, held: dict | None) -> dict:
    """持股 × 本輪點名。available＝有讀到持股清單；mentioned 只收本輪被節目或 PTT 點名的持股。"""
    if held is None:
        return {"available": False, "count": 0, "mentioned": []}
    by_code = {st["code"]: st for st in stocks}
    ptt_stance: dict[str, list] = {}
    for p in ptt_rows:
        if p["stock_code"] in held:
            ptt_stance.setdefault(p["stock_code"], []).append(_side(p["stance"]))
    mentioned = []
    for code in sorted(held):
        st, ptt = by_code.get(code), ptt_stance.get(code, [])
        if st is None and not ptt:
            continue
        bull, bear, neutral = (st["bull_voices"], st["bear_voices"], st["neutral_voices"]) if st else (0, 0, 0)
        mentioned.append({
            "code": code,
            "name": (st and st["name"]) or held[code].get("name") or code,
            "bull_voices": bull, "bear_voices": bear, "neutral_voices": neutral,
            "ptt_articles": len(ptt),
            "ptt_bear_articles": ptt.count("bear"),
            "alert": bear > 0 or "bear" in ptt,
        })
    return {"available": True, "count": len(held), "mentioned": mentioned}


def _verdict_marks(v: dict, tz) -> tuple:
    """判斷列的 (since, written_at)：舊列可能缺 since，再缺 written_at 就退回 date（當天 00:00）；都沒有就是 (None, None)。"""
    since = _parse_since(v.get("since"), tz) if v.get("since") else None
    written = _parse_since(v.get("written_at"), tz) if v.get("written_at") else None
    if since is None and written is None and v.get("date"):
        written = _parse_since(v["date"], tz)
    return since, written


def _round_of(at: datetime, rounds: list):
    """擷取時點屬於哪一輪：不晚於它的最後一個 round since；比所有輪都早（或沒有 log）回 None。"""
    return next((r for r in reversed(rounds) if r <= at), None)


def unjudged_block(rows: list, ptt_rows: list, verdict_rows: list, rounds: list, judge_rows: list,
                   since: datetime, current_codes: set, max_days: int = RECENT_DAYS,
                   held: dict | None = None) -> dict:
    """前幾輪（[since - max_days, since)）被點名、判斷檔裡沒有涵蓋那次點名的判斷列的檔，附上查得到的事實。

    只整理事實、不決定要不要補判：要不要放進今晚的 media_picks_judge.py 由主 agent 看完自己決定。
    一次點名算「有判斷」：判斷檔有同代號、`since` 不早於那次點名所屬那一輪的 since（補判寫的是補判那一輪的 since，
    一樣晚於被補的那輪），或 `written_at` 不早於那次點名的 extracted_at；比它早的舊判斷不算，記成 last_verdict。
    judge_attempts 是 media_picks_judge.py --log 記下、在那次點名之後的判斷紀錄（ok／error）；沒帶 --log 的輪就是空的。
    rounds 的每輪統計依判斷紀錄的 `at`（實際開判時刻）歸到它落在的那一輪，不是依呼叫時傳的 since（補判會傳較早的 since）。"""
    tz = since.tzinfo
    floor = since - timedelta(days=max_days)
    rounds = sorted(set(rounds))
    marks: dict[str, list] = {}
    for v in verdict_rows:
        if v.get("code"):
            marks.setdefault(v["code"], []).append((_verdict_marks(v, tz), v))
    attempts: dict[str, list] = {}
    for j in judge_rows:
        at = _parse_since(j.get("at"), tz) if j.get("at") else None
        if at is not None and j.get("code"):
            attempts.setdefault(j["code"], []).append((at, j))

    def covered(code, at, rnd):
        return any((v_since is not None and rnd is not None and v_since >= rnd)
                   or (v_written is not None and v_written >= at)
                   for (v_since, v_written), _ in marks.get(code, []))

    named: dict[str, list] = {}
    for kind, src in (("media", rows), ("ptt", ptt_rows)):
        for r in src:
            at = _extracted_at(r, tz)
            if at is None or not floor <= at < since or not r.get("stock_code") or r.get("resolve") == "no_picks":
                continue
            rnd = _round_of(at, rounds)
            if not covered(r["stock_code"], at, rnd):
                named.setdefault(r["stock_code"], []).append((at, rnd, kind, r))

    codes = []
    for code, hits in named.items():
        hits.sort(key=lambda h: h[0])
        first_at = hits[0][0]
        media = [r for _, _, kind, r in hits if kind == "media"]
        ptt = [r for _, _, kind, r in hits if kind == "ptt"]
        bull = {_voice(r) for r in media if _side(r.get("stance")) == "bull"}
        bear = {_voice(r) for r in media if _side(r.get("stance")) == "bear"}
        older = [((v_since or v_written), v) for (v_since, v_written), v in marks.get(code, [])
                 if (v_since or v_written) is not None]
        last = max(older, key=lambda x: x[0])[1] if older else None
        codes.append({
            "code": code,
            "name": (media or ptt)[-1].get("name") or (media or ptt)[-1].get("name_said") or (media or ptt)[-1].get("target"),
            "rounds": sorted({rnd.isoformat() for _, rnd, _, _ in hits if rnd is not None}),
            "first_extracted_at": first_at.isoformat(),
            "last_extracted_at": hits[-1][0].isoformat(),
            "named_dates": sorted({r.get("date") for r in media if r.get("date")}),
            "bull_voices": len(bull), "bear_voices": len(bear),
            "neutral_voices": len({_voice(r) for r in media} - bull - bear),
            "ptt_articles": len({r.get("article_id") for r in ptt}),
            "last_verdict": last and {k: last.get(k) for k in ("date", "since", "verdict")},
            "judge_attempts": [{"at": at.isoformat(), "ok": bool(j.get("ok")), "error": j.get("error")}
                               for at, j in sorted(attempts.get(code, []), key=lambda x: x[0]) if at >= first_at],
            "named_this_round": code in current_codes,
            "held": held is not None and code in held,
            # 沒被涵蓋的那幾次點名的原話與 PTT 文：主 agent 決定補判時，--code 與逐檔判斷才拿得到舊證據
            "stock": next(iter(_stocks(media, [], ptt, held, floor)), None),
            "ptt": _ptt_rows(ptt),
        })
    codes.sort(key=lambda c: (c["last_extracted_at"], c["bull_voices"] + c["bear_voices"] + c["neutral_voices"]),
               reverse=True)

    in_window = [r for r in rounds if floor <= r < since]
    by_round = []
    for i, rnd in enumerate(in_window):
        end = in_window[i + 1] if i + 1 < len(in_window) else since
        named_here = {r["stock_code"] for src in (rows, ptt_rows) for r in src
                      if r.get("stock_code") and r.get("resolve") != "no_picks"
                      and (at := _extracted_at(r, tz)) is not None and rnd <= at < end}
        judged_here = [j for j in judge_rows
                       if j.get("at") and (at := _parse_since(j["at"], tz)) is not None and rnd <= at < end]
        by_round.append({
            "since": rnd.isoformat(),
            "codes_named": len(named_here),
            "unjudged_codes": sum(1 for c in codes if rnd.isoformat() in c["rounds"]),
            "verdict_rows": sum(1 for v in verdict_rows
                                if v.get("since") and _parse_since(v["since"], tz) == rnd),
            "judge_logged": len(judged_here),
            "judge_failed": sum(1 for j in judged_here if not j.get("ok")),
        })
    return {"from": floor.isoformat(), "rounds": by_round, "codes": codes}


def _stocks(picks: list, media_before: list, ptt: list, held: dict | None, since: datetime) -> list:
    """逐檔證據；本輪與「前幾輪沒有判斷」共用同一份欄位與講者去重方式。"""
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
            "history": _history(prior_by_code.get(code, []), since, data),
            "ptt": ptt_by_code.get(code, []),
            "held": held is not None and code in held,
        })
    stocks.sort(key=lambda s: (-_voices(s), -s["bull_voices"], s["code"]))
    return stocks


def _ptt_rows(ptt: list) -> list:
    return [
        {k: r.get(k) for k in ("article_id", "url", "title", "author", "target", "stock_code", "resolve",
                               "category", "stance", "reason", "condition", "push_up", "push_down", "data")}
        | {"edited": bool(r.get("edited_at")), "has_statement": bool(r.get("has_statement"))}
        for r in ptt
    ]


def summarize(since: datetime, journal_dir: Path = JOURNAL_DIR, transcript_dir: Path = TRANSCRIPT_DIR,
              stock_index: Path = STOCK_INDEX, holdings: Path | None = None, logs_dir: Path = LOGS_DIR,
              max_days: int = RECENT_DAYS) -> dict:
    held = load_holdings(holdings)
    all_media = _read_jsonl(journal_dir / "media-picks.jsonl")
    ptt, ptt_before = _split(_read_jsonl(journal_dir / "ptt-picks.jsonl"), since)
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

    stocks = _stocks(picks, media_before, ptt, held, since)
    ptt_rows = _ptt_rows(ptt)

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
        "holdings": _holdings_block(stocks, ptt_rows, held),
        "unjudged": unjudged_block(media_before, ptt_before, _read_jsonl(journal_dir / "media-picks-verdicts.jsonl"),
                                   round_sinces(logs_dir), judge_log(logs_dir), since,
                                   {st["code"] for st in stocks} | {p["stock_code"] for p in ptt_rows if p["stock_code"]},
                                   max_days=max_days, held=held),
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
        raw = "" if h.get("since_first_adjusted") else "，未還原除權息"
        s += f"、首次至今 {h['since_first_pct']:+}%（{h['first_close_as_of']} 收 {h['first_close']}{raw}）"
    return s


def _holdings_section(h: dict) -> list:
    """索引第一段：三種狀態——清單取不到、本輪沒點名、有點名（一檔一行，有看空加警示）。"""
    if not h["available"]:
        return ["## 持股清單取不到", "（沒有讀到持股清單，這輪無法標出你的持股；其餘照常判讀）"]
    if not h["mentioned"]:
        return ["## 你的持股本輪沒有被點名"]
    lines = [f"## 你的持股被點名 {len(h['mentioned'])} 檔"]
    for m in h["mentioned"]:
        warn = "｜⚠ 有看空" if m["alert"] else ""
        lines.append(f"- {m['name']} {m['code']}｜多 {m['bull_voices']} 空 {m['bear_voices']} 中 {m['neutral_voices']}"
                     f"｜PTT {m['ptt_articles']}{warn}")
    return lines


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
        f"、至今 {h['since_first_pct']:+}%{'' if h.get('since_first_adjusted') else '（未還原）'}"
        if h["since_first_pct"] is not None else "")) if h else "新出現"
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
    lines = _holdings_section(s["holdings"]) + [""] + _header(s) + ["", f"## {len(multi)} 檔有 {INDEX_FULL_VOICES} 位以上講者（依講者數排序）"]
    lines += [_index_line(st) for st in multi]
    lines += ["", f"## {len(single)} 檔只有 1 位講者"] + [_index_line(st) for st in single]
    lines += ["", f"## PTT 新文章 {len(s['ptt'])} 篇"]
    for p in s["ptt"]:
        flags = "".join(f"｜{f}" for f in _ptt_flags(p, with_resolve=False))
        lines.append(f"- {_short(p['title'], 30)}｜{p['stock_code'] or p['resolve']}｜{_label(p['stance'])}"
                     f"｜推 {p['push_up']} 噓 {p['push_down']}{flags}")
    lines += [""] + _unjudged_section(s["unjudged"])
    lines += ["", "單一檔的完整原話與 PTT 全文：media_picks_summary.py --since <同上> --code <代號>"]
    return "\n".join(lines)


def _hm(iso) -> str:
    """ISO 時刻 → 「MM-DD HH:MM」（顯示用）。"""
    return f"{iso[5:10]} {iso[11:16]}" if iso and len(iso) >= 16 else str(iso)


def _attempt_text(a: dict) -> str:
    return f"{_hm(a['at'])} 判斷" + ("成功、判斷檔沒有對應的列" if a["ok"] else f"失敗：{_short(a['error'] or '?', 40)}")


def _unjudged_line(c: dict) -> str:
    last = c["last_verdict"]
    seen = f"上次判斷 {last['date'] or (last['since'] or '')[:10]} {last['verdict']}" if last else "沒有判斷過"
    tries = "；".join(_attempt_text(a) for a in c["judge_attempts"]) or "沒有判斷紀錄"
    this = "｜本輪也有點名" if c["named_this_round"] else ""
    ptt = f" PTT {c['ptt_articles']}" if c["ptt_articles"] else ""
    held = "（持股）" if c.get("held") else ""
    return (f"- {c['name'] or '?'} {c['code']}{held}｜點名 {_hm(c['first_extracted_at'])}～{_hm(c['last_extracted_at'])}"
            f"（播出 {','.join(d[5:] for d in c['named_dates']) or '—'}）｜多 {c['bull_voices']} 空 {c['bear_voices']}"
            f" 中 {c['neutral_voices']}{ptt}｜{seen}｜{tries}{this}")


def _unjudged_section(u: dict) -> list:
    """索引裡的「前幾輪還沒判斷」：每輪一行統計，逐檔只列有判斷紀錄（判過卻沒寫進判斷檔）的；完整清單用 --unjudged。

    一輪約 160 檔、最多判 8 檔，前 7 天沒判斷的檔常有幾百檔，全列會撐爆索引；這裡只是切顯示，不替你挑檔。"""
    lines = [f"## 前幾輪（{_hm(u['from'])} 起）點名過、判斷檔沒有涵蓋的檔 {len(u['codes'])} 檔"]
    for r in u["rounds"]:
        lines.append(f"- 輪 {_hm(r['since'])}：點名 {r['codes_named']} 檔、判斷檔 {r['verdict_rows']} 列、"
                     f"仍沒判斷 {r['unjudged_codes']} 檔、判斷紀錄 {r['judge_logged']} 筆（失敗 {r['judge_failed']}）")
    orphan = sum(1 for c in u["codes"] if not c["rounds"])
    if orphan:
        lines.append(f"- 另有 {orphan} 檔的擷取時點對不到任何一輪 log（log 已不存在或早於現存最早一輪），只在 --unjudged 清單裡")
    tried = [c for c in u["codes"] if c["judge_attempts"]]
    if tried:
        lines.append(f"判斷過卻沒寫進判斷檔 {len(tried)} 檔：")
        lines += [_unjudged_line(c) for c in tried]
    lines.append("完整清單（每檔點名時段、多空人數、上次判斷）：media_picks_summary.py --since <同上> --unjudged")
    return lines


def unjudged_detail(s: dict) -> str:
    u = s["unjudged"]
    return "\n".join(_unjudged_section(u)[:-1] + ["", "逐檔（依最近點名時刻排序）："] + [_unjudged_line(c) for c in u["codes"]])


def stock_detail(s: dict, code: str) -> str:
    """單一檔的完整證據（逐檔判斷用）：每位講者的原話、數據、歷史，以及談到這檔的 PTT 文。"""
    st = next((x for x in s["stocks"] if x["code"] == code), None)
    posts = [p for p in s["ptt"] if p["stock_code"] == code]
    pending = next((c for c in s.get("unjudged", {}).get("codes", []) if c["code"] == code), None)
    if st is None and not posts and pending is None:
        return f"本輪沒有人點名 {code}"
    if st:
        lines = _stock_block(st)
    elif posts:
        lines = [f"### {code}（節目沒點名，只有 PTT）"]
    else:
        lines = [f"### {pending['name'] or ''} {code}（本輪沒有人點名，以下是前幾輪的證據）"]
    if code in {m["code"] for m in s["holdings"]["mentioned"]} or (pending and pending["held"]):
        lines.insert(0, "（你持有這檔）")
    for p in posts:
        head, *rest = _ptt_block(p)
        lines += ["", "PTT：" + head.lstrip("# ")] + rest
    if pending:
        # 只附事實；要不要補判、怎麼看這些舊原話由主 agent 與逐檔判斷決定
        lines += ["", "## 前幾輪點名過、判斷檔沒有涵蓋的證據", _unjudged_line(pending)]
        if pending["stock"]:
            # 舊證據沒帶更早的點名紀錄，略過「歷史」行以免誤寫成「之前沒被點名過」；完整歷史看上面的本輪區塊或 --json
            lines += [x for x in _stock_block(pending["stock"]) if not x.startswith("歷史：")]
        for p in pending["ptt"]:
            head, *rest = _ptt_block(p)
            lines += ["", "PTT：" + head.lstrip("# ")] + rest
    return "\n".join(lines)


def _parse_since(text, tz=None):
    """ISO 時刻 → 帶時區的 datetime；解析不了回 None。沒帶時區的當本機時區。"""
    try:
        at = datetime.fromisoformat(str(text).strip())
    except ValueError:
        return None
    return at if at.tzinfo else at.astimezone() if tz is None else at.replace(tzinfo=tz)


def round_sinces(logs_dir: Path = LOGS_DIR) -> list:
    """logs/media_picks_job_*.log 裡每個 `RESULT since=` 的值（解析不了的略過）。"""
    out = []
    for path in sorted(logs_dir.glob("media_picks_job_*.log")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in re.finditer(r"^.*RESULT since=(\S+)", text, re.M):
            at = _parse_since(m.group(1))
            if at is not None:
                out.append(at)
    return out


def judge_log(logs_dir: Path = LOGS_DIR) -> list:
    """logs/media_picks_job_*.log 裡 media_picks_judge.py --log 追加的判斷紀錄（JSON 解析不了的行略過）。"""
    out = []
    for path in sorted(logs_dir.glob("media_picks_job_*.log")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            if JUDGE_TAG not in line:
                continue
            try:
                row = json.loads(line.split(JUDGE_TAG, 1)[1])
            except ValueError:
                continue
            if isinstance(row, dict):
                out.append(row)
    return out


def judge_since(current: datetime, verdict_rows: list, round_sinces: list, max_days: int = 7) -> datetime:
    """本輪review與判斷該涵蓋的起點：上一輪判讀中斷時往前涵蓋。

    last＝判斷列（`since` 欄，記的是寫下那批判斷的那一輪自己的 since，不是補判的起點）裡最晚的 since；比 last 晚的各輪都沒判斷過（中斷，或那輪是空的——空輪不加內容，
    涵蓋進來無害），取其中最早的、且落在 [current - max_days, current] 的那個；沒有 last 或沒有符合的輪就用 current。
    FAILED 而沒有摘要的輪不用管：視窗是對 journal 列的 extracted_at 套的，往前涵蓋自然包含它們寫下的列。"""
    lasts = [at for at in (_parse_since(r.get("since"), current.tzinfo) for r in verdict_rows if r.get("since")) if at]
    if not lasts:
        return current
    last = max(lasts)
    floor = current - timedelta(days=max_days)
    later = [s for s in round_sinces if last < s <= current and s >= floor]
    return min(later) if later else current


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", required=True, help="本輪開始時刻（ISO 8601，帶時區）")
    out = ap.add_mutually_exclusive_group(required=True)
    out.add_argument("--json", action="store_true", help="輸出 JSON（排程用）")
    out.add_argument("--index", action="store_true", help="精簡索引（主 agent 挑檔用）")
    out.add_argument("--code", help="只輸出這一檔的完整證據，帶 .TW／.TWO（逐檔判斷用）")
    out.add_argument("--unjudged", action="store_true",
                     help="前幾輪點名過、判斷檔沒有涵蓋的檔的完整清單（主 agent 決定要不要放進今晚的判斷）")
    out.add_argument("--judge-since", action="store_true",
                     help="印出本輪review與判斷該用的起點（上一輪判讀中斷時比 --since 早）")
    ap.add_argument("--holdings", type=Path, help="portfolio_codes.py 輸出的 JSON；缺檔或壞檔只在 stderr 記一行、當作沒有")
    ap.add_argument("--logs-dir", type=Path, default=LOGS_DIR,
                    help="找各輪 RESULT since= 與 JUDGE 判斷紀錄的 log 目錄（預設 logs/）")
    ap.add_argument("--journal-dir", type=Path, default=JOURNAL_DIR, help="journal 目錄（預設 journal/）")
    args = ap.parse_args(argv)
    since = datetime.fromisoformat(args.since)
    if since.tzinfo is None:
        since = since.astimezone()
    if args.judge_since:
        verdicts = _read_jsonl(args.journal_dir / "media-picks-verdicts.jsonl")
        print(judge_since(since, verdicts, round_sinces(args.logs_dir)).isoformat())
        return 0
    s = summarize(since, journal_dir=args.journal_dir, holdings=args.holdings, logs_dir=args.logs_dir)
    if args.json:
        print(json.dumps(s, ensure_ascii=False, indent=1))
    elif args.index:
        print(_index(s))
    elif args.unjudged:
        print(unjudged_detail(s))
    else:
        print(stock_detail(s, args.code))
    return 0


if __name__ == "__main__":
    sys.exit(main())
