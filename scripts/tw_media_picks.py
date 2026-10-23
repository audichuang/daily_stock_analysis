"""財經電視節目點名擷取：YouTube 完整版 → NotebookLM 逐字稿與點名 → 對照本地數據 → journal。

每天抓固定頻道的新完整版，丟進當天的 NotebookLM notebook（一天一本），請它逐集列出點名個股、
方向、理由與價位條件；股名對照 `stocks.index.json` 轉代號（聽錯的標 fuzzy／未解析），再附上
播出當天的本地數據（均線位置、離 60 日高、月營收 YoY、法人 5 日），逐筆追加到
`journal/media-picks.jsonl`。已在 journal 的影片跳過，可重跑。

媒體點名是**候選來源**，不是買進訊號（點名的事後表現 inconclusive，見
docs/research/2026-10-22-tw-media-sweep.md）。

NotebookLM 憑證走 Doppler（`make media-picks` 已包好）；CLI 路徑用 `NOTEBOOKLM_BIN` 覆寫。

    make media-picks
    uv run --env-file .env python scripts/tw_media_picks.py --since 2026-10-20 --dry-run
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import subprocess
import time
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

JOURNAL = ROOT / "journal" / "media-picks.jsonl"
TRANSCRIPTS = ROOT / "data" / "media_picks"
INDEX = ROOT / "apps" / "dsa-web" / "public" / "stocks.index.json"
NB_PREFIX = "dsa 媒體點名 "
KEEP_NOTEBOOK_DAYS = 30

# (show, kind, channel id, title regex, min seconds) — only full episodes; clips and highlights
# repeat them. kind keeps the later back-test separable: tv / advisor (投顧, sells memberships) / kol / research.
# Upload must be after the 13:30 close unless the title says 盤前 (data_cutoff only reads the title).
# Tried and dropped 2026-10-23: 劉姸希 (half the picks are past-gain promos tagged bullish), 股癌 (US-heavy, 2 neutral picks per episode).
CHANNELS = [
    ("錢線百分百", "tv", "UC_ObC9O0ZQ2FhW6u9_iFlZA", r"完整版", 1200),
    ("理財達人秀", "tv", "UCQvsuaih5lE0n_Ne54nNezg", r"【(理財達人秀|兆華艾綸說)】", 2400),
    ("鈔錢部署", "tv", "UCA_hK5eRICBdSOLlXKESvEg", r"《鈔錢部署》", 1500),
    ("財富達給厚", "tv", "UCYo8FANgeH2ONA898HbzHKg", r"《財富達給厚》", 2400),
    ("股市情報局", "tv", "UCNgcAnFU5eygSqb7Em8TScQ", r".", 2400),
    ("TVBS金臨天下", "tv", "UCYDaGPmMfSXViITpPYDKIcw", r".", 2400),
    ("賺錢放大術", "tv", "UCGSlzLzYtXQvmPrsZKAfKmA", r".", 2400),
    ("股市現場", "tv", "UCJcPWs0gpYMx_CghPdELUhw", r".", 3600),
    ("投資聊一SHOT", "tv", "UCgTGRGR1nHz_m1ZcFGfg4RQ", r"投資聊一SHOT", 1200),
    ("江國中", "advisor", "UCxhmFqqd28z04vjagnMpJpg", r".", 2100),
    ("林漢偉", "advisor", "UCleWOsRmPBhWPvQlSTy7fPw", r".", 1800),
    ("楊育華", "advisor", "UCK1TfbeSlR0jc733Ep83Xfg", r".", 1800),
    ("葉俊敏", "advisor", "UC8r0UHqwUeAArogHqgFXDVw", r".", 1800),
    ("陳昆仁", "advisor", "UCiBLyIFu3KjG2opa7uQHZbQ", r".", 1200),
    ("郭哲榮", "advisor", "UChfl3auNxAxOR3wy8a8ysQQ", r".", 2100),
    ("紀緯明", "advisor", "UCOZosuCbpzK7Optwppn0whA", r"投資明明很簡單", 2100),
    ("謝文琪", "advisor", "UCUSfi6ugUr9r-1UUS48uivw", r".", 1500),
    ("陳學進", "advisor", "UCTJBg089Av1LV8Nhd5YPDTw", r"理周TV", 1200),
    ("豐銀投顧", "advisor", "UCqLsAvnCtSU7CeSrfjy2Btw", r".", 1200),
    # roundtables of advisors listed above: the same person's call can repeat under another show
    ("瘋狂股市福利社", "tv", "UCAg1jxXzYrVSfkJyeOH2gqg", r"║", 1200),
    ("理周TV", "advisor", "UCmd2Sny4QM9zlgaD2gVn-Zg", r"^(?!.*精華)", 1100),
    ("老王愛說笑", "advisor", "UCvnLmiWt_zIVIh0zUm_j4Hw", r"老王不只三分鐘", 1800),
    # kol: independent YouTubers, no advisor licence
    ("一綺聊股", "kol", "UCuXjCbU_zwwuE0rMbJfY9aQ", r"台股", 1200),
    ("財報狗", "research", "UC2TsM2pyabGznSvB9llmsFA", r"財經時事放大鏡", 1200),
    ("MoneyDJ", "research", "UC8qLLXh5cuY_jtvOHsSYmTA", r"^Ep\.", 1200),
]

# without it YouTube may serve auto-translated English titles and the title patterns stop matching
YT_LANG = ["--extractor-args", "youtube:lang=zh-TW"]

PROMPT = """只根據這一集節目，列出每一檔被具體點名的台股（含 ETF）。只輸出一個 JSON 陣列，不要任何其他文字、不要 markdown、不要引用編號。每個元素：
{"name": 正確的上市櫃公司或 ETF 名稱, "said": 逐字稿裡的寫法, "code": 股票代號（你確定才填）否則 null, "stance": "bullish"|"bearish"|"avoid"|"neutral", "speaker": 誰說的, "reason": 推薦或不推薦的理由（一兩句，照節目內容）, "theme": 看好的題材或族群, "condition": 節目給的價位或進出場條件（照原話）否則 null, "quote": 最關鍵的一句原話}
逐字稿是語音辨識，股名常是同音錯字（例如「建頂」是健鼎、「台素化」是台塑化、「0050正2」是元大台灣50正2），name 請還原成正確名稱，無法確定就照逐字稿寫。
同一檔被不同人講到、看法不同時分成兩個元素。只列節目明確講到的，不要推測。"""


def _run(cmd, timeout=600):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=True).stdout


def nb(*args, timeout=600, attempts=3):
    # NotebookLM fails transiently (source add errored 3 of 5 in one run, then worked by hand)
    cmd = [os.environ.get("NOTEBOOKLM_BIN", "notebooklm"), *args, "--json"]
    for i in range(attempts):
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:  # ask slows down as the notebook fills up
            data = {"error": True, "message": f"timed out after {timeout}s"}
            if i + 1 < attempts:
                time.sleep(20 * (i + 1))
            continue
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            data = {"error": True, "message": (proc.stderr or proc.stdout).strip()[-300:]}
        if proc.returncode == 0 and not (isinstance(data, dict) and data.get("error")):
            return data
        if i + 1 < attempts:
            time.sleep(20 * (i + 1))
    raise RuntimeError(f"notebooklm {' '.join(args[:2])}: {data.get('message') if isinstance(data, dict) else data}")


# ---------- pure helpers (tested) ----------

def parse_answer(text: str) -> list[dict] | None:
    """NotebookLM answer -> list of picks; tolerates fences and stray citation markers.

    None means the answer wasn't a JSON array (retry next run); [] means no picks.
    """
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return None
    body = re.sub(r"\s\[\d+(?:[,\-–]\s*\d+)*\]", "", text[start:end + 1])
    try:
        items = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(items, list):
        return None
    if items and not any(isinstance(i, dict) for i in items):
        return None  # "[1]" / "[1, 2]" is a citation marker, not an answer: retry next run
    # Objects without a name ({"name": null, "reason": "本集未點名個股"}) are the model saying "no picks";
    # retrying would only drop the episode silently once it ages out of --since.
    return [i for i in items if isinstance(i, dict) and i.get("name")]


# Names the shows use that the official list does not carry, checked against stocks.index.json.
# Only add one when the company is certain: a wrong alias beats the LLM's code and resolves silently.
MEDIA_ALIASES = {
    "2330.TW": ["台灣積體電路製造"],
    "3711.TW": ["日月光投資控股"],
    "6234.TWO": ["高橋"],  # misheard 高僑; same episode had it limit-up
    "6456.TW": ["業成", "業成科技"],  # GIS-KY's former name
    "6902.TW": ["走著瞧", "走著瞧-創"],  # GOGOLOOK's Chinese brand
}


def load_index(path=INDEX) -> list[tuple[str, str, list[str]]]:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    return [(r[0], r[2], list(r[5] or []) + MEDIA_ALIASES.get(r[0], [])) for r in rows if r[6] == "TW"]


def _norm(name: str) -> str:
    return re.sub(r"-KY|\*|\s", "", name or "").upper()


def _by_code(code: str, index, pad: bool = True) -> tuple[str, str] | None:
    """-> (canonical, index name). ETFs are read out without leading zeros:
    "52" -> 0052, "850" -> 00850, "981A" -> 00981A."""
    base = str(code).strip().upper()
    digits, suffix = re.fullmatch(r"(\d*)(.*)", base).groups()
    tries = (base, *(digits.zfill(n) + suffix for n in (4, 5, 6))) if pad and digits else (base,)
    for b in dict.fromkeys(tries):
        for c, n, _ in index:
            if c.split(".")[0] == b:
                return c, n
    return None


def _by_name(parts, index) -> tuple[str, str] | None:
    for p in parts:
        for c, n, aliases in index:
            if p == _norm(n):
                return c, "exact"
        for c, n, aliases in index:
            if p in map(_norm, aliases):
                return c, "alias"
    return None


_COMPANY_SUFFIXES = ("電子", "科技", "工業")


def _is_full_name(full: str, short: str) -> bool:
    """True for 台達電子 / 聯發科技 vs 台達電 / 聯發科: the short name already uses the suffix's first char."""
    return any(full.endswith(s) and full[:-len(s)] + s[0] == short for s in _COMPANY_SUFFIXES)


def resolve(name: str, code: str | None, index, said: str | None = None) -> tuple[str | None, str]:
    """-> (canonical code like 3044.TW, how).

    Name first: the LLM-normalised name is more reliable than the code it guesses
    (live run: 宜鼎 came with 宜特's code). Exception: a number in the transcript itself
    wins, since ETFs are read out as numbers ("00927") and the LLM may pick the wrong fund.
    how: exact|alias|code|code_mismatch|fuzzy|unresolved.
    """
    said = (said or "").strip().upper()
    said_code = said
    if re.fullmatch(r"\d{2,6}[A-Z]?", said):
        hit = _by_code(said, index)
    else:
        # "6658 連測": a code read out before a misheard name. Exact codes only — the spaced
        # transcripts also yield fragments like "668 中 陽 光" (6668) or "130 連 南亞" (1303).
        # "0050正2" is a nickname, not a code.
        m = re.match(r"(\d{4,6}[A-Z]?)\s", said)
        said_code = m.group(1) if m else ""
        hit = m and _by_code(said_code, index, pad=False)
    # TV-style names: "精材（精綵）" -> try each part
    parts = [_norm(p) for p in re.split(r"[（）()/／、]", name or "") if p.strip()]
    by_name = _by_name(parts, index)
    # A number that only matched after zero-padding ("668" -> 00668) loses to the name's code, or
    # failing that the LLM's code, when that code contains those digits: it was a fragment of 6668
    # (中揚光). Otherwise the spoken number still beats the fund name the LLM filled in ("850" with
    # 國泰台灣領袖50 stays 00850).
    if hit and hit[0].split(".")[0] != said_code:
        llm_hit = code and _by_code(code, index, pad=False)
        alt = by_name or (llm_hit and (llm_hit[0], "code"))
        if alt and alt[0] != hit[0] and said_code in alt[0].split(".")[0]:
            return alt
    if hit:
        return hit[0], "code"  # a misheard number ("5000" for 0050) falls through to the name
    if by_name:
        return by_name
    hit = code and _by_code(code, index)
    if hit:
        c, n = hit
        agree = not parts or any(p in (str(code).upper(), c.split(".")[0]) or p in _norm(n) or _norm(n) in p
                                  for p in parts)
        if not agree and not any(set(p) & set(_norm(n)) for p in parts):
            # No shared character at all: the LLM's code belongs to another company (光紘 -> 3669 圓展).
            return None, "unresolved"
        return c, "code" if agree else "code_mismatch"
    names = {_norm(n): c for c, n, _ in index}
    for p in parts:
        close = difflib.get_close_matches(p, names, n=2, cutoff=0.67)
        # A name that is a strict substring of the input is a different, shorter company
        # ("三商銀" -> 三商, a bank group is not the retailer); two equally close names are a coin flip
        # ("冠電" -> 虹冠電 or 冠西電). Both stay unresolved instead of attaching the wrong quote.
        if close and close[0] != p and close[0] in p and not _is_full_name(p, close[0]):
            continue
        if len(close) > 1 and difflib.SequenceMatcher(None, p, close[0]).ratio() == \
                difflib.SequenceMatcher(None, p, close[1]).ratio():
            continue
        if close:
            # The LLM gave a code that is not in the index, so it is no evidence for this near-name
            # (live run: "期元大S&P原油正2" with 00672L came back as the gold fund 00708L).
            if code:  # a code that is in the index returned above
                continue
            return names[close[0]], "fuzzy"
    return None, "unresolved"


def already_done(path=JOURNAL) -> set[str]:
    if not path.exists():
        return set()
    return {json.loads(line)["video_id"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


# 標題裡的播出日：20261020、2026.10.20、2026/10/20、2026-10-20
_TITLE_DATE_RE = re.compile(r"(?<!\d)(20\d{2})(?:([./\-])(\d{1,2})\2(\d{1,2})|(\d{2})(\d{2}))(?!\d)")
_MAX_UPLOAD_LAG_DAYS = 14


def air_date(title: str, uploaded: date) -> tuple[date, str]:
    """-> (播出日, 來源 title|upload)。

    YouTube 的上傳日不一定是播出日（TVBS金臨天下 常隔天、甚至隔幾天才上傳完整版）；拿上傳日當基準，
    `data` 會吃到播出之後的行情。標題寫了日期就用標題的；不在上傳日之前 14 天內的日期不採用
    （可能是節目裡講的別的日子），退回上傳日。"""
    for m in _TITLE_DATE_RE.finditer(title or ""):
        y, _, mo, d, mo8, d8 = m.groups()
        try:
            day = date(int(y), int(mo or mo8), int(d or d8))
        except ValueError:
            continue
        if uploaded - timedelta(days=_MAX_UPLOAD_LAG_DAYS) <= day <= uploaded:
            return day, "title"
    return uploaded, "upload"


def data_cutoff(title: str, aired: date) -> date:
    """`data` 可以用到哪一天的收盤。盤前節目在開盤前播出，播出當天的收盤還不存在，只能用前一天以前的。"""
    return aired - timedelta(days=1) if "盤前" in (title or "") else aired


def required_session(cutoff: date) -> date:
    """cutoff（含）以前最後一個交易日：交易所日曆可用就用它（排掉國定假日），否則退回平日。"""
    try:
        from src.core.trading_calendar import get_trading_dates

        sessions = get_trading_dates("tw", cutoff - timedelta(days=20), cutoff)
    except Exception:
        sessions = None
    if sessions is not None and len(sessions):
        return sessions[-1].date()
    day = cutoff
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def data_settled(cutoff: date, latest_session: date | None) -> bool:
    """市場庫已經有 cutoff 該用的那個交易日的收盤了嗎。

    收盤資料入庫前跑（例如下午 16 點手動跑），`price_history(end=cutoff)` 只拿得到前一天，snapshot 會
    靜默把前一天收盤當成播出當天；這種集數先不寫 journal，下一輪再處理。行情最新場次晚於該交易日
    （例如颱風休市那天之後已有新場次）也算已定案，那天本來就沒有收盤。"""
    return latest_session is not None and latest_session >= required_session(cutoff)


# ---------- YouTube ----------

def new_episodes(since: date, done: set[str]) -> list[dict]:
    eps = []
    for show, kind, cid, pattern, min_sec in CHANNELS:
        try:
            out = _run(["yt-dlp", *YT_LANG, "--flat-playlist", "--playlist-end", "60",  # 錢線 uploads ~13 clips a day
                        "--print", "%(id)s\t%(duration)s\t%(title)s",
                        f"https://www.youtube.com/channel/{cid}/videos"], 180)
        except Exception as exc:  # one channel failing must not stop the others
            print(f"[warn] {show} 清單抓取失敗：{exc}", file=sys.stderr)
            continue
        for line in out.splitlines():
            vid, dur, title = (line.split("\t", 2) + ["", ""])[:3]
            if vid in done or not re.search(pattern, title):
                continue
            if not dur.replace(".", "").isdigit() or float(dur) < min_sec:
                continue
            try:
                up = _run(["yt-dlp", *YT_LANG, "--skip-download", "--print", "%(upload_date)s",
                           f"https://www.youtube.com/watch?v={vid}"], 120).strip()
                uploaded = datetime.strptime(up, "%Y%m%d").date()
            except Exception as exc:
                print(f"[warn] {vid} 取不到上傳日：{exc}", file=sys.stderr)
                continue
            if uploaded < since:
                break  # the tab is newest-first by upload; everything below is older
            aired, aired_from = air_date(title, uploaded)
            eps.append({"show": show, "kind": kind, "video_id": vid, "title": title, "aired": aired,
                        "aired_from": aired_from, "uploaded": uploaded, "cutoff": data_cutoff(title, aired),
                        "url": f"https://www.youtube.com/watch?v={vid}"})
    return sorted(eps, key=lambda e: e["aired"])


# ---------- local data ----------

def snapshot(code: str, as_of: date, engine) -> dict | None:
    """Data as of `as_of` (the episode's data cutoff: the air date, or the day before for 盤前 shows)."""
    import pandas as pd

    from market_data import market_repo
    from src.services import tw_stock_dossier as dossier

    sid = code.split(".")[0]
    px = market_repo.price_history(sid, start=as_of - timedelta(days=150), end=as_of, engine=engine)
    # Drop NULL closes before adjusting: a NaN would journal as NaN (breaks every later json.loads),
    # and adjusting first would anchor the multipliers on the dropped day.
    px = px[pd.to_numeric(px["close"], errors="coerce").notna()].copy()
    if px.empty:
        return None
    px["date"] = pd.to_datetime(px["date"])
    close = pd.to_numeric(px["close"], errors="coerce") * \
        market_repo.front_adjust_multipliers(sid, px["date"], engine=engine).to_numpy()
    last = float(close.iloc[-1])

    def pct(a, b):
        return None if b is None or pd.isna(b) or not b else round((a / b - 1) * 100, 1)

    ma = {n: (close.tail(n).mean() if len(close) >= n else None) for n in (20, 60)}
    d = px["date"].iloc[-1].date()
    out = {"as_of": str(d), "close": round(last, 2),
           "vs_ma20_pct": pct(last, ma[20]), "vs_ma60_pct": pct(last, ma[60]),
           "from_60d_high_pct": pct(last, close.tail(60).max()),
           "ret_5d_pct": pct(last, close.iloc[-6]) if len(close) > 5 else None}
    fund = dossier.fundamentals(engine, sid, d)
    out["revenue_yoy_3m"] = [m["yoy_pct"] for m in fund["monthly_revenue"][-3:]]
    inst = (dossier.chips(engine, sid, d, [], branch=False) or {}).get("institutional") or {}
    out["foreign_5d_lots"], out["trust_5d_lots"] = inst.get("foreign_5d_lots"), inst.get("trust_5d_lots")
    return out


# ---------- main ----------

def defer_unsettled(eps: list[dict], engine) -> list[dict]:
    """拿掉收盤資料還沒入庫的集數（不寫 journal，下一輪重抓），其餘照常處理。"""
    from market_data import market_repo

    # 看 market.price 本身：加權指數在 price 整天被跳過（例如上櫃行情抓失敗）時照樣入庫，拿它當代理會
    # 放行集數，snapshot 又靜默退回前一天收盤
    latest = market_repo.latest_price_date(engine=engine)
    latest_session = datetime.fromisoformat(str(latest)[:10]).date() if latest is not None else None
    keep = []
    for ep in eps:
        if data_settled(ep["cutoff"], latest_session):
            keep.append(ep)
        else:
            print(f"[defer] {ep['video_id']} {ep['show']}：{ep['cutoff']} 的收盤還沒入庫（最新場次 {latest_session}），"
                  "下一輪再處理", file=sys.stderr)
    return keep


def cleanup_notebooks(today: date):
    for n in nb("list").get("notebooks", []):
        title = n.get("title", "")
        if not title.startswith(NB_PREFIX):
            continue
        try:
            day = date.fromisoformat(title[len(NB_PREFIX):])
        except ValueError:
            continue
        if (today - day).days > KEEP_NOTEBOOK_DAYS:
            nb("delete", "-n", n["id"], "-y")
            print(f"刪除過期 notebook：{title}")


def process(ep: dict, nb_id: str, index, engine) -> list[dict]:
    src = ep.get("source_id") or nb("source", "add", ep["url"], "-n", nb_id)["source"]["id"]
    nb("source", "wait", src, "-n", nb_id, "--timeout", "600", timeout=700)
    TRANSCRIPTS.mkdir(parents=True, exist_ok=True)
    nb("source", "fulltext", src, "-n", nb_id, "-o", str(TRANSCRIPTS / f"{ep['video_id']}.txt"), "--force")
    ans = nb("ask", "-n", nb_id, "-s", src, "--new", "-y", PROMPT, timeout=600)
    picks = parse_answer(ans.get("answer", ""))
    if picks is None:  # don't journal it, so the next run retries this episode
        raise RuntimeError(f"回答不是 JSON：{ans.get('answer', '')[:120]!r}")
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    when = {"upload_date": str(ep.get("uploaded", ep["aired"])), "date_source": ep.get("aired_from", "upload")}
    rows = []
    for p in picks:
        code, how = resolve(p.get("name"), p.get("code"), index, p.get("said"))
        data = None
        if code and engine is not None:
            try:
                data = snapshot(code, ep.get("cutoff", ep["aired"]), engine)
            except Exception as exc:
                print(f"[warn] {code} 數據失敗：{exc}", file=sys.stderr)
        rows.append({"date": str(ep["aired"]), "show": ep["show"], "kind": ep["kind"], "video_id": ep["video_id"],
                     "url": ep["url"], "title": ep["title"], "name": p.get("name"), "name_said": p.get("said"),
                     "stock_code": code, "resolve": how, "code_llm": p.get("code"), "stance": p.get("stance"),
                     "speaker": p.get("speaker"), "reason": p.get("reason"), "theme": p.get("theme"),
                     "condition": p.get("condition"), "quote": p.get("quote"),
                     "data": data, "extracted_at": now, "notebook_id": nb_id, **when})
    if not rows:  # still record the episode so it isn't re-processed forever
        rows.append({"date": str(ep["aired"]), "show": ep["show"], "kind": ep["kind"], "video_id": ep["video_id"],
                     "url": ep["url"], "title": ep["title"], "stock_code": None, "resolve": "no_picks",
                     "extracted_at": now, "notebook_id": nb_id, **when})
    return rows


def _single_run_lock():
    """Non-blocking process lock; None when another run holds it. Kept open for the process lifetime."""
    import fcntl
    import tempfile

    f = open(Path(tempfile.gettempdir()) / "tw_media_picks.lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", type=date.fromisoformat, default=date.today() - timedelta(days=4),
                    help="只抓這天（含）之後上傳的集數，預設 4 天前（收盤資料還沒入庫而延後的集數，隔週一仍補得到）")
    ap.add_argument("--dry-run", action="store_true", help="只列出會處理的集數")
    ap.add_argument("--no-data", action="store_true", help="不連 market schema")
    args = ap.parse_args(argv)

    lock = _single_run_lock()
    if lock is None:
        print("另一個 media-picks 正在跑，這次不執行（重疊會把同一集寫進 journal 兩次）", file=sys.stderr)
        return 0
    eps = new_episodes(args.since, already_done())
    print(f"新集數 {len(eps)}：")
    for e in eps:
        print(f"  {e['aired']} {e['show']} {e['video_id']} {e['title'][:60]}")
    if args.dry_run or not eps:
        return 0

    index = load_index()
    engine = None
    if not args.no_data:
        from market_data.db import get_engine
        engine = get_engine()
        eps = defer_unsettled(eps, engine)
        if not eps:
            return 0
    today = date.today()
    title = f"{NB_PREFIX}{today}"
    existing = [n for n in nb("list").get("notebooks", []) if n.get("title") == title]
    nb_id = existing[0]["id"] if existing else nb("create", title)["notebook"]["id"]

    failed = 0
    JOURNAL.parent.mkdir(exist_ok=True)
    # add every source up front so NotebookLM transcribes them in parallel
    for ep in eps:
        try:
            ep["source_id"] = nb("source", "add", ep["url"], "-n", nb_id)["source"]["id"]
        except Exception as exc:  # process() retries the add
            print(f"[warn] {ep['video_id']} 預先加入失敗：{exc}", file=sys.stderr)
    for ep in eps:
        try:
            rows = process(ep, nb_id, index, engine)
        except Exception as exc:  # one episode failing must not stop the rest
            failed += 1
            print(f"[error] {ep['video_id']} {ep['show']}：{exc}", file=sys.stderr)
            continue
        with JOURNAL.open("a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        n_ok = sum(1 for r in rows if r["stock_code"])
        print(f"{ep['show']} {ep['aired']}：{len(rows)} 筆點名，{n_ok} 筆對到代號")

    try:
        cleanup_notebooks(today)
    except Exception as exc:
        print(f"[warn] 清理舊 notebook 失敗：{exc}", file=sys.stderr)
    return 1 if failed == len(eps) else 0


if __name__ == "__main__":
    sys.exit(main())
