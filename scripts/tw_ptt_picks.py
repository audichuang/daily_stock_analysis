"""PTT 股票板 `[標的]` 文擷取：解析板規格式（標的／分類／分析／進退場機制）→ 對照本地數據 → journal。

`[標的]` 是板規格式的推薦文（作者要寫多空、理由與進退場），不用 LLM，直接解析原文；`Re:` 回文沒有
固定格式，不收。股名對照 `stocks.index.json` 轉代號（沿用 `tw_media_picks.resolve`），再附發文當時
已知的本地數據（同 media-picks 的 `data`），逐篇追加到 `journal/ptt-picks.jsonl`。已在 journal 的
文章跳過，可重跑。推／噓數是擷取當下的值，文章越新推文越少。

跟媒體點名一樣是**候選來源，不是買進訊號**；累積夠多再回驗。

    make ptt-picks
    uv run --env-file .env python scripts/tw_ptt_picks.py --since 2026-10-20 --dry-run
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tw_media_picks as mp  # noqa: E402

JOURNAL = mp.ROOT / "journal" / "ptt-picks.jsonl"
BOARD = "https://www.ptt.cc/bbs/Stock"
TPE = timezone(timedelta(hours=8))
CLOSE = (13, 30)
MARKET = re.compile(r"大盤|台股|台指|加權|櫃買|費半|那斯達克|標普")


# ---------- pure helpers (tested) ----------

def post_time(article_id: str) -> datetime:
    """M.1792560350.A.0E7 -> 發文時刻（檔名就是 unix 秒）。"""
    return datetime.fromtimestamp(int(article_id.split(".")[1]), TPE)


def data_cutoff(posted: datetime) -> date:
    """收盤前發的文只知道前一天的收盤。"""
    return posted.date() if (posted.hour, posted.minute) >= CLOSE else posted.date() - timedelta(days=1)


def parse_search(page: str) -> list[tuple[str, str]]:
    """搜尋結果頁 -> [(article_id, title)]；只留 `[標的]` 原文（刪文沒有連結，自然略過）。"""
    out = []
    for aid, title in re.findall(r'<a href="/bbs/Stock/(M\.\d+\.A\.[0-9A-F]+)\.html">([^<]*)</a>', page):
        title = html.unescape(title).strip()
        if title.startswith("[標的]"):
            out.append((aid, title))
    return out


# template labels at line start, optionally numbered ("2.分類：多")
_LABEL = re.compile(r"^[ \t]*(?:\d+\s*[.、]\s*)?(標的|分類|分析\s*/?\s*正文|分析|正文|進退場機制|對帳單)\s*[:：]", re.M)
_PLACEHOLDER = re.compile(r"[(（]喊多喊空者.*?[)）]", re.S)  # left over from the board template


def _sections(body: str) -> dict[str, str]:
    marks = list(_LABEL.finditer(body))
    out = {}
    for m, nxt in zip(marks, marks[1:] + [None]):
        key = re.sub(r"\s|/", "", m.group(1)).replace("分析正文", "分析").replace("正文", "分析")
        text = re.sub(r"\s+", " ", _PLACEHOLDER.sub("", body[m.end():nxt.start() if nxt else None])).strip()
        if text and key not in out:
            out[key] = text
    return out


def stance_of(category: str | None, title: str) -> str:
    """分類寫法很雜（多、多/討論、長期持有多、加碼多）：只出現多或只出現空才算表態，其餘看標題結尾。"""
    for text, whole in ((category or "", True), (re.sub(r"[?？\s]+$", "", title), False)):
        bull, bear = "多" in text, "空" in text
        if bull != bear and (whole or text.endswith(("多", "空"))):  # 「操作空間?」 is not 空
            return "bullish" if bull else "bearish"
    return "neutral"


def parse_article(page: str, title: str) -> dict:
    """文章頁 -> 標的、多空、理由、進退場、推噓。欄位缺就是 None，不猜。"""
    main = page.split('<div id="main-content"', 1)[-1].split(">", 1)[-1]
    pushes = re.findall(r'<span class="[^"]*push-tag">(推|噓|→) ?</span>', main)
    body = re.sub(r'<div class="push">.*', "", main, flags=re.S)  # comments come after the body
    body = html.unescape(re.sub(r"<[^>]+>", "", body))
    body = body.split("※ 發信站", 1)[0].rsplit("\n--\n", 1)[0]
    body = re.split(r"\n-----\n", body, maxsplit=1)[0]  # app footer ("-----\nSent from MeowPtt")
    s = _sections(body)
    free = re.sub(r"\s+", " ", body.split("\n", 1)[-1].lstrip("-\n ")).strip()  # no template: keep the text
    return {
        "target": s.get("標的") or title.replace("[標的]", "").strip(),
        "category": s.get("分類"),
        "stance": stance_of(s.get("分類"), title),
        "reason": (s.get("分析") or (free if not s else ""))[:500] or None,
        "condition": (s.get("進退場機制") or "")[:300] or None,
        "has_statement": bool(re.search(r"https?://", s.get("對帳單", ""))),
        "push_up": pushes.count("推"), "push_down": pushes.count("噓"), "push_neutral": pushes.count("→"),
    }


def split_target(target: str) -> tuple[str, str | None]:
    """「宏碁資訊-6811」「2316 楠梓電」-> (名稱, 代號)；美股代號（SOXS）留在名稱裡，resolve 會判不到。"""
    m = re.search(r"(?<![\dA-Z])(\d{4,6}[A-Z]?)(?![\dA-Z])", target.upper())
    code = m.group(1) if m else None
    name = re.sub(r"(?<![\dA-Z])\d{4,6}[A-Z]?(?![\dA-Z])", " ", target.upper() if code else target)
    name = re.sub(r"[-－_/／()（）\s]+", " ", name).strip()
    return name, code


def resolve_target(target: str, index) -> tuple[str | None, str]:
    name, code = split_target(target)
    if not code and MARKET.search(target):
        return None, "market"  # fuzzy would turn 台灣大盤 into 台灣大
    return mp.resolve(name, code, index, code)  # the author typed the code: trust it like a spoken one


def already_done(path=JOURNAL) -> set[str]:
    if not path.exists():
        return set()
    return {json.loads(line)["article_id"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


# ---------- network ----------

def _get(url: str) -> str:
    import requests

    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, cookies={"over18": "1"}, timeout=20)
    r.raise_for_status()
    return r.text


def new_articles(since: date, done: set[str], max_pages: int = 20) -> list[dict]:
    out = []
    for page in range(1, max_pages + 1):
        hits = parse_search(_get(f"{BOARD}/search?page={page}&q=%5B%E6%A8%99%E7%9A%84%5D"))
        if not hits:
            break
        older = False
        for aid, title in hits:
            posted = post_time(aid)
            if posted.date() < since:
                older = True
                continue
            if aid not in done:
                out.append({"article_id": aid, "title": title, "posted": posted, "cutoff": data_cutoff(posted),
                            "url": f"{BOARD}/{aid}.html"})
        if older:
            break  # search is newest-first
        time.sleep(0.5)
    return sorted(out, key=lambda a: a["posted"])


# ---------- main ----------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", type=date.fromisoformat, default=date.today() - timedelta(days=4),
                    help="只抓這天（含）之後發的文，預設 4 天前")
    ap.add_argument("--dry-run", action="store_true", help="只列出會處理的文章")
    ap.add_argument("--no-data", action="store_true", help="不連 market schema")
    args = ap.parse_args(argv)

    arts = new_articles(args.since, already_done())
    print(f"新文章 {len(arts)}：")
    for a in arts:
        print(f"  {a['posted']:%m-%d %H:%M} {a['article_id']} {a['title'][:60]}")
    if args.dry_run or not arts:
        return 0

    index = mp.load_index()
    engine = latest_session = None
    if not args.no_data:
        from market_data import market_repo
        from market_data.db import get_engine

        engine = get_engine()
        latest = market_repo.latest_price_date(engine=engine)
        latest_session = datetime.fromisoformat(str(latest)[:10]).date() if latest is not None else None
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    failed = 0
    for a in arts:
        if engine is not None and not mp.data_settled(a["cutoff"], latest_session):
            print(f"[defer] {a['article_id']}：{a['cutoff']} 的收盤還沒入庫，下一輪再處理", file=sys.stderr)
            continue
        try:
            page = _get(a["url"])
            p = parse_article(page, a["title"])
        except Exception as exc:  # one article failing must not stop the rest
            failed += 1
            print(f"[error] {a['article_id']}：{exc}", file=sys.stderr)
            continue
        author = re.search(r'作者</span><span class="article-meta-value">([^ <]+)', page)
        code, how = resolve_target(p["target"], index)
        data = None
        if code and engine is not None:
            try:
                data = mp.snapshot(code, a["cutoff"], engine)
            except Exception as exc:
                print(f"[warn] {code} 數據失敗：{exc}", file=sys.stderr)
        row = {"date": str(a["posted"].date()), "posted_at": a["posted"].isoformat(), "article_id": a["article_id"],
               "url": a["url"], "title": a["title"], "author": author.group(1) if author else None,
               "target": p["target"], "stock_code": code, "resolve": how, "category": p["category"],
               "stance": p["stance"], "reason": p["reason"], "condition": p["condition"],
               "has_statement": p["has_statement"], "push_up": p["push_up"], "push_down": p["push_down"],
               "push_neutral": p["push_neutral"], "data": data, "extracted_at": now}
        JOURNAL.parent.mkdir(exist_ok=True)
        with JOURNAL.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"{a['posted']:%m-%d} {p['target'][:20]} → {code or '未對到'}（{how}）{p['stance']}")
        time.sleep(0.5)
    return 1 if arts and failed == len(arts) else 0


if __name__ == "__main__":
    sys.exit(main())
