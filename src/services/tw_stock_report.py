"""台股個股四維度分析報告（HTML）：資料包 + 解讀 -> 單一網頁。

數字一律來自 `tw_stock_dossier.build()`；文字結論來自 narrative JSON（由 LLM 依 `NARRATIVE_RULES`
撰寫：Web API 自動呼叫、CLI 用 `--narrative` 帶入）。沒有 narrative 時只渲染數字，結論欄位留白。

    uv run --env-file .env python scripts/tw_stock_report.py 3324 --dump-data /tmp/3324.json
    uv run --env-file .env python scripts/tw_stock_report.py 3324 --data /tmp/3324.json \
        --narrative /tmp/3324.narrative.json -o reports/dossier/3324.html
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import threading
import time
from datetime import datetime
from html import escape
from pathlib import Path

logger = logging.getLogger(__name__)

NA = "無資料"
TONES = {"pos": "badge-pos", "neu": "badge-neu", "watch": "badge-watch", "neg": "badge-neg"}
VERDICTS = {"fundamental": "基本面", "chips": "籌碼面", "technical": "技術面", "valuation": "估值"}


def _e(s):
    return escape(str(s)) if s not in (None, "") else ""


def _n(v, spec=",.0f", suffix=""):
    return NA if v is None else f"{v:{spec}}{suffix}"


def _signed(v, spec="+,.0f", suffix=""):
    if v is None:
        return f'<span class="muted">{NA}</span>'
    cls = "pos" if v > 0 else "neg" if v < 0 else ""
    return f'<span class="{cls}">{v:{spec}}{suffix}</span>'


def _note(text):
    return f'<div class="note">{_e(text)}</div>' if text else ""


def _sub(title):
    return f'<div class="sub">{_e(title)}</div>'


def _section(icon, title, body, n=""):
    n = f' <span class="n">{_e(n)}</span>' if n else ""
    return f'<div class="section"><div class="section-title">{icon} {_e(title)}{n}</div>{body}</div>'


def _empty():
    return f'<div class="empty">{NA}</div>'


# ---------- sections ----------

def verdicts(nar):
    v = nar.get("verdicts") or {}
    cards = []
    for key, label in VERDICTS.items():
        x = v.get(key) or {}
        badge = (f'<div class="vt-badge {TONES.get(x.get("tone"), "badge-watch")}">{_e(x.get("badge"))}</div>'
                 if x.get("badge") else "")
        cards.append(f'<div class="card verdict-card"><div class="vt-label">{label}</div>{badge}'
                     f'<div class="vt-note">{_e(x.get("note"))}</div></div>')
    return _section("📋", "四維度總覽", f'<div class="grid4">{"".join(cards)}</div>', "中立標示，非買賣訊號")


def fundamentals(p, nar):
    f, notes = p["fundamentals"], nar.get("notes") or {}
    months = f["monthly_revenue"]
    if months:
        top = max(m["revenue_k"] for m in months) or 1
        rows = "".join(
            f'<div class="bar-row"><div class="lbl">{m["month"][2:].replace("-", "/")}</div>'
            f'<div class="track"><div class="fill" style="width:{m["revenue_k"] / top * 100:.1f}%"></div></div>'
            f'<div class="val">{m["revenue_k"]:,} 千元</div>'
            f'<div class="yoy">{_signed(m["yoy_pct"], "+.1f", "%")}</div></div>' for m in months)
        rev = (rows + f'<div class="note">近 12 個月累計營收年增率 '
               f'<b>{_signed(f["ttm_revenue_yoy_pct"], "+.1f", "%")}</b>'
               f'　最新月份 {months[-1]["month"]}（公告日 {_e(months[-1]["announced"]) or NA}）</div>')
    else:
        rev = _empty()
    left = f'<div class="card">{_sub("月營收（千元）與 YoY%")}{rev}{_note(notes.get("revenue"))}</div>'

    qs = f["quarters"]
    if qs:
        def cell(v, last):
            s = _n(v, ".2f")
            return f"<td>{f'<b>{s}</b>' if last else s}</td>"

        body = "".join(
            f'<tr><td>{q["quarter"]}</td>'
            + "".join(cell(q[k], i == len(qs) - 1) for k in ("gross_margin", "op_margin", "net_margin", "eps"))
            + "</tr>" for i, q in enumerate(qs))
        table = ('<div class="table-wrap"><table><tr><th>季度</th><th>毛利率%</th><th>營益率%</th><th>淨利率%</th>'
                 f"<th>EPS</th></tr>{body}</table></div>")
    else:
        table = _empty()
    right = f'<div class="card">{_sub("季度毛利率／營益率／淨利率／EPS")}{table}{_note(notes.get("quarters"))}</div>'
    return _section("📈", "基本面", f'<div class="grid2">{left}{right}</div>', "月營收近 13 個月 + 季度損益")


def contract(p, nar):
    cl = p["contract_liabilities"]
    note = (nar.get("notes") or {}).get("contract")
    if cl:
        rows = []
        for i, c in enumerate(cl):
            prev = cl[i - 1]["contract_liabilities_k"] if i else None
            qoq = (c["contract_liabilities_k"] / prev - 1) * 100 if prev else None
            rows.append(f'<tr><td>{c["quarter"]}</td><td>{c["contract_liabilities_k"]:,.0f}</td>'
                        f'<td>{_signed(qoq, "+.1f", "%")}</td></tr>')
        body = "<table><tr><th>季度</th><th>合約負債（千元）</th><th>季增</th></tr>" + "".join(rows) + "</table>"
    else:
        body = '<div class="muted">資產負債表沒有單獨列示合約負債科目，無法評估此項訂單能見度指標。</div>'
    return _section("📦", "合約負債（訂單能見度）", f'<div class="card">{body}{_note(note)}</div>')


def _broker_bars(x):
    if not x:
        return _empty()

    def rows(items, color, sign):
        items = items[:5]
        top = max((r["net"] for r in items), default=0) or 1
        return "".join(f'<div class="bb-row"><div class="nm">{_e(r["branch"])}</div>'
                       f'<div class="bar" style="width:{r["net"] / top * 100:.0f}%;background:var(--{color})"></div>'
                       f'<div class="amt">{sign}{r["net"]:,.0f}張</div></div>' for r in items)

    return (f'<div class="broker-bars">{rows(x["buy"], "up", "+")}<div style="height:8px"></div>'
            f'{rows(x["sell"], "down", "-")}</div>'
            f'<div class="note">前 15 名買超 HHI <b>{_n(x.get("hhi_buy_top15"))}</b>'
            f'（{_hhi_label(x.get("hhi_buy_top15"))}）・買超均價 {_n(x.get("avg_buy_cost"), ",.2f")}'
            f'・賣超均價 {_n(x.get("avg_sell_cost"), ",.2f")}</div>')


def _hhi_label(h):
    if h is None:
        return NA
    return "低度集中" if h < 1000 else "中度集中" if h < 1800 else "高度集中"


def _stat(k, v):
    return f'<div class="chip-stat"><span class="k">{_e(k)}</span><span class="v">{v}</span></div>'


def chips(p, nar):
    c, notes, price = p["chips"], nar.get("notes") or {}, (p.get("smc") or {}).get("price")
    b = c.get("branch")
    panes = [(label, (b or {}).get(k)) for label, k in (("當日", "day"), ("近 5 日", "five_sessions"))]
    cards = ""
    for label, x in panes:
        span = f" {x['start']}~{x['end']}" if x else ""
        note = _note(notes.get("branch")) if label == "近 5 日" else ""
        cards += f'<div class="card">{_sub(f"分點買賣超前 5 名（{label}{span}）")}{_broker_bars(x)}{note}</div>'
    s = []
    i = c.get("institutional")
    if i:
        s.append(_stat("三大法人 近 5 日（張）",
                       f'外資 {_signed(i["foreign_5d_lots"])}／投信 {_signed(i["trust_5d_lots"])}／自營 {_signed(i["dealer_5d_lots"])}'))
        s.append(_stat("三大法人 近 20 日（張）",
                       f'外資 {_signed(i["foreign_20d_lots"])}／投信 {_signed(i["trust_20d_lots"])}／自營 {_signed(i["dealer_20d_lots"])}'))
    else:
        s.append(_stat("三大法人", f'<span class="muted">{NA}</span>'))
    m = c.get("margin")
    if m:
        s.append(_stat("融資餘額（張）", f'{m["margin_balance"]:,}（5 日 {_signed(m.get("margin_chg_5"))}、20 日 {_signed(m.get("margin_chg_20"))}）'))
        s.append(_stat("融券餘額／券資比", f'{_n(m.get("short_balance"))} 張／{_n(m.get("short_margin_ratio"), ".2f", "%")}'))
    else:
        s.append(_stat("融資融券", f'<span class="muted">{NA}</span>'))
    h = c.get("holding")
    if h:
        s.append(_stat("千張大戶持股比率", f'{h["big_holder_pct"]:.2f}%（週變化 {_signed(h["big_holder_pct_wow"], "+.2f", "pp")}）'))
        s.append(_stat("總股東人數", f'{_n(h.get("total_holders"))} 人（{_e(h["as_of"])}）'))
    else:
        s.append(_stat("千張大戶（集保）", f'<span class="muted">{NA}</span>'))
    if b and b.get("five_sessions") and price:
        cost = b["five_sessions"].get("avg_buy_cost")
        if cost:
            s.append(_stat("近 5 日主力買超均價（前 15 分點）",
                           f'{cost:,.2f}（現價 {price:,.2f}，乖離 {_signed((price / cost - 1) * 100, "+.1f", "%")}）'))
    stats = f'<div class="card" style="margin-top:14px">{_sub("法人與籌碼結構指標")}{"".join(s)}{_note(notes.get("chips"))}</div>'
    return _section("🔍", "籌碼面", f'<div class="grid2">{cards}</div>{stats}')


def valuation(p, nar):
    v, note = p.get("valuation"), (nar.get("notes") or {}).get("valuation")
    if not v:
        return _section("💰", "估值", f'<div class="card">{_empty()}{_note(note)}</div>')
    pct = v.get("pe_percentile_3y")
    gauge = (f'<div class="gauge"><div class="gauge-track"><div class="gauge-mark" style="left:{pct:.1f}%"></div></div>'
             f'<div class="gauge-lbl"><span>近 3 年最便宜</span><span>{pct:.1f} 百分位</span><span>最貴</span></div></div>'
             if pct is not None else "")
    tiles = "".join(f'<div class="tile"><div class="tile-k">{k}</div><div class="tile-v">{val}</div></div>' for k, val in (
        ("本益比", _n(v.get("pe"), ".2f", " 倍")), ("股價淨值比", _n(v.get("pb"), ".2f", " 倍")),
        ("殖利率", _n(v.get("dividend_yield"), ".2f", "%")), ("PE 3 年百分位", _n(pct, ".1f"))))
    body = (f'<div class="grid4">{tiles}</div>{gauge}'
            f'<div class="note">截至 {_e(v["as_of"])}；百分位樣本 {v["pe_samples_3y"]} 日</div>{_note(note)}')
    return _section("💰", "估值", f'<div class="card">{body}</div>')


_LEVEL_COLOR = {"bsl": "muted", "ssl": "down", "fvg": "neutral", "ote": "accent"}


def _ladder_levels(s):
    from src.services.tw_stock_watch import smc_levels

    return [(x["label"], x["low"], x["high"], _LEVEL_COLOR.get(x["kind"]) or ("down" if x["bias"] == "bull" else "up"))
            for x in smc_levels(s)]


def _ladder(s):
    price = s["price"]
    lv = _ladder_levels(s) + [("現價", price, price, "accent")]
    lv.sort(key=lambda x: (-x[2], x[0] != "現價"))
    hi = max(x[2] for x in lv) * 1.01
    lo = min(x[1] for x in lv) * 0.99
    span = hi - lo or 1
    height = 300
    out, last = [], -99.0
    for label, low, high, color in lv:
        y = (hi - high) / span * height
        h = max(2.0, (high - low) / span * height)
        ly = max(y + min(h, 16) / 2, last + 18)      # 標籤至少間隔 18px，不重疊
        last = ly
        if label == "現價":
            out.append(f'<div class="price-now" style="top:{y:.1f}px"></div>'
                       f'<div class="ltag now" style="top:{ly:.1f}px">現價</div>'
                       f'<div class="lval now" style="top:{ly:.1f}px">{price:,.1f}</div>')
            continue
        rng = f"{low:,.1f}" if low == high else f"{low:,.1f}~{high:,.1f}"
        dist = (((low + high) / 2) / price - 1) * 100
        out.append(f'<div class="band" style="top:{y:.1f}px;height:{h:.1f}px;background:var(--{color})"></div>'
                   f'<div class="ltag" style="top:{ly:.1f}px">{_e(label)}</div>'
                   f'<div class="lval" style="top:{ly:.1f}px;color:var(--{color})">{rng} '
                   f'<span class="muted">({dist:+.1f}%)</span></div>')
    return f'<div class="ladder" style="height:{max(height, last + 14):.0f}px">{"".join(out)}</div>'


def technical(p, nar):
    s, note = p.get("smc"), (nar.get("notes") or {}).get("technical")
    if not s:
        return _section("📐", "技術面（SMC 結構）", f'<div class="card">{_empty()}</div>')
    left = f'<div class="card">{_sub("關鍵價位結構（由高至低，括號為距現價）")}{_ladder(s)}</div>'
    ev = []
    for k, e in enumerate(s["events"]):
        bull = e["direction"] == "bullish"
        kind = "ChoCH" if e["kind"] == "CHOCH" else e["kind"]
        tag = "，最新結構" if k == len(s["events"]) - 1 else ""
        ev.append(_stat(e["date"][:10], f'<span class="{"pos" if bull else "neg"}">{"🔼" if bull else "🔽"} '
                                       f'{kind} {e["direction"].upper()}（突破 {e["level"]:,.1f}{tag}）</span>'))
    fb = s.get("fib")
    if fb:
        zone = {"premium": "Premium 區間", "discount": "Discount 區間"}.get(fb["zone"], fb["zone"])
        ev.append(_stat("Fib 位置", f'{fb["position"] * 100:.1f}%（{zone}，區間 {fb["range_low"]:,.1f}~{fb["range_high"]:,.1f}）'))
        ev.append(_stat("OTE 最佳進場區間", f'{fb["ote_low"]:,.1f}~{fb["ote_high"]:,.1f}（現價{"在內" if fb["in_ote"] else "不在內"}）'))
    right = f'<div class="card">{_sub("結構事件紀錄")}{"".join(ev) or _empty()}{_note(note)}</div>'
    return _section("📐", "技術面（SMC 結構）", f'<div class="grid2">{left}{right}</div>',
                    f"前復權日 K，擺動點 n={s['swing_n']}")


def footer(p, nar):
    fu = nar.get("followups") or []
    marks = "①②③④⑤⑥⑦⑧"
    items = "、".join(f"{marks[i] if i < len(marks) else i + 1} {_e(x)}" for i, x in enumerate(fu))
    c = p["chips"]
    asof = [("價格", p["as_of"]),
            ("法人", (c.get("institutional") or {}).get("as_of")), ("融資", (c.get("margin") or {}).get("as_of")),
            ("集保", (c.get("holding") or {}).get("as_of")), ("估值", (p.get("valuation") or {}).get("as_of"))]
    fresh = "・".join(f"{k} {v or NA}" for k, v in asof)
    pills = "".join(f'<span class="pill">{x}</span>' for x in
                    ("公開資訊觀測站財報", "TWSE／TPEx 官方籌碼", "富邦 DJ 券商分點", "TDCC 集保週報", "SMC 技術結構"))
    return (f'<div class="foot">{pills}<br><br>'
            + (f"後續追蹤重點：{items}<br><br>" if items else "")
            + f"各段資料日：{fresh}<br>資料基準日 {_e(p['as_of'])} | 產出時間 {datetime.now():%Y-%m-%d %H:%M}"
            "<br>本頁僅整理公開資料，不構成投資建議。</div>")


# ---------- narrative (LLM) ----------

NARRATIVE_RULES = """你是台股研究員，依下方資料包替這檔股票寫「四維度分析」的解讀。只輸出一個 JSON 物件，不要任何其他文字。

格式：
{"industry": "產業（不確定就省略）",
 "verdicts": {"fundamental": {"badge": "≤12 字標籤", "tone": "pos|neu|watch|neg", "note": "一到兩句，帶關鍵數字"},
              "chips": {...}, "technical": {...}, "valuation": {...}},
 "notes": {"revenue": "", "quarters": "", "contract": "", "branch": "", "chips": "", "valuation": "", "technical": ""},
 "followups": ["可驗證的追蹤點，含日期或價位", "..."]}

tone：pos 偏多、neg 偏空、neu 中性、watch 觀察。標示中立，不寫買賣建議。用繁體中文。

規則：
- 每個數字都要能在資料包裡找到，或由資料包的數字算出（季營收加總、TTM EPS、自算本益比、與現價乖離）；自己算的要寫「自算」。不准引用資料包以外的財務數字或新聞。
- 資料包是 null 或空的段落寫「無資料」或「回補中」，不准推測補上。文字裡不要出現 null、JSON 欄位名或英文鍵名，一律用中文描述。valuation 是 null 時可用近四季 EPS 自算 TTM 本益比，並註明沒有歷史百分位。
- 月營收以 month 欄為準；留意 announced 公告日與各段 as_of 的新鮮度。
- 分點 HHI 註明「前 15 名」口徑；「主力成本」指近 5 日前 15 分點買超均價，不要叫「大戶成本」。
- SMC：BOS 是延續確認、ChoCH 是較弱的轉折，最新一筆事件決定目前結構；距離用 (價位 / 現價 − 1)。
- 每段的觀察要點出矛盾或風險（例如營收年增但月減、法人買但價格低於主力成本），不要只複述數字。
- notes 每段以「觀察：」開頭（contract／valuation 除外），2~4 句。
- followups 3~5 條，寫成之後能驗證的條件：月營收公告日（每月 10 日）、財報截止日（5/15、8/14、11/14、3/31）、關鍵價位。
"""

def narrative_prompt(p):
    return f"{NARRATIVE_RULES}\n資料包：\n{json.dumps(p, ensure_ascii=False)}"


def parse_narrative(text):
    """LLM 回覆 -> narrative dict；格式不對回 None（呼叫端退回只列數字）。"""
    from json_repair import repair_json

    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        nar = json.loads(repair_json(m.group(0)))      # 容忍 LLM 多打的逗號、引號
    except ValueError:
        return None
    v = nar.get("verdicts") if isinstance(nar, dict) else None
    if not isinstance(v, dict) or not all(isinstance(v.get(k), dict) and v[k].get("note") for k in VERDICTS):
        return None
    if not isinstance(nar.get("notes"), dict):
        nar["notes"] = {}
    if not isinstance(nar.get("followups"), list):
        nar["followups"] = []
    return nar


_narrative_locks: dict = {}      # cache path -> Lock；同一檔同時被開兩次時只付一次 LLM


# 只核對「帶小數或千分位」的數字：整數張數、日期、天數太容易撞到，不值得核
_NUMBER_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+")
_SENTENCE_SPLIT_RE = re.compile(r"[。；;\n]")      # 「自算」常寫在同一句的前半，用整句判斷


def _payload_numbers(p):
    out = set()

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, (int, float)) and not isinstance(x, bool):
            for v in (abs(x), abs(x) * 100):      # *100：Fib 位置等 0~1 的比例常被寫成百分比
                out.update((d, round(v, d)) for d in range(4))

    walk(p)
    return out


def unverified_numbers(nar, p):
    """解讀裡在資料包找不到、句中也沒標「自算」的數字（便宜的防呆，抓抄錯，不保證全對）。"""
    known, bad = _payload_numbers(p), []

    def texts(x):
        if isinstance(x, dict):
            for v in x.values():
                yield from texts(v)
        elif isinstance(x, list):
            for v in x:
                yield from texts(v)
        elif isinstance(x, str):
            yield x

    for text in texts(nar):
        for sentence in _SENTENCE_SPLIT_RE.split(text):
            if "自算" in sentence:
                continue
            for m in _NUMBER_RE.findall(sentence):
                decimals = len(m.split(".")[1]) if "." in m else 0
                if (decimals, round(float(m.replace(",", "")), decimals)) not in known:
                    bad.append(m)
    return bad


def cached_narrative(p, generate, cache_dir):
    """同一檔、同一資料基準日只呼叫一次 LLM；結果存在 cache_dir，重啟不重算。

    解讀裡有核對不到的數字時照樣回傳（附 `unverified`）但不寫快取，下次開啟重新產生。"""
    path = Path(cache_dir) / f"{p['stock_id']}_{p['as_of']}.json"
    with _narrative_locks.setdefault(str(path), threading.Lock()):
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        nar = parse_narrative(generate(narrative_prompt(p)))
        if nar:
            bad = unverified_numbers(nar, p)
            if bad:
                logger.warning("[tw_stock_report] %s narrative has unverified numbers: %s", p["stock_id"], bad)
                nar["unverified"] = bad
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(nar, ensure_ascii=False), encoding="utf-8")
        return nar


# ---------- web entry ----------

class UnsupportedMarket(ValueError):
    """不是台股代號（API 對應 400 unsupported_market）。"""


_PAYLOAD_TTL_SECONDS = 600
_payload_cache: dict = {}      # (code, as_of) -> (monotonic, payload)；先看數字再要解讀時不重查分點


def _payload(code, as_of):
    from src.services import tw_stock_dossier

    key, now = (code, as_of), time.monotonic()
    hit = _payload_cache.get(key)
    if hit and now - hit[0] < _PAYLOAD_TTL_SECONDS:
        return hit[1]
    for k in [k for k, (t, _) in _payload_cache.items() if now - t >= _PAYLOAD_TTL_SECONDS]:
        del _payload_cache[k]      # 順手清掉過期項，任意代號／日期組合不會無限累積
    p = tw_stock_dossier.build(code, as_of=as_of)
    _payload_cache[key] = (now, p)
    return p


def _llm_generate(prompt):
    from src.analyzer import GeminiAnalyzer
    from src.config import get_config

    analyzer = GeminiAnalyzer(config=get_config())
    if not analyzer.is_available():
        raise RuntimeError("LLM 未設定或不可用")
    return analyzer.generate_text(prompt, max_tokens=4096, temperature=0.3, call_type="stock_dossier")


def _narrative_cache_dir():
    from src.config import get_config

    return Path(get_config().database_path).parent / "dossier_narratives"


def report_html(code, *, narrative=False, theme=None, as_of=None, generate=None, cache_dir=None):
    """Web 用：台股代號 -> 報告 HTML。非台股 UnsupportedMarket、查無價格 LookupError；解讀失敗只降級。"""
    from src.services.market_symbol_utils import is_tw_suffix_symbol

    code = (code or "").strip().upper()
    if not is_tw_suffix_symbol(code):
        raise UnsupportedMarket(f"{code} 不是台股代號（需帶 .TW／.TWO）")
    p = _payload(code, as_of)
    nar = notice = None
    if narrative:
        try:
            nar = cached_narrative(p, generate or _llm_generate, cache_dir or _narrative_cache_dir())
        except Exception as exc:     # LLM 失敗不拖垮頁面，退回只列數字
            logger.warning("[tw_stock_report] narrative failed for %s: %s", code, exc)
        if not nar:
            notice = "AI 解讀產生失敗，目前只列數字；稍後重新開啟可再試一次。"
        elif nar.get("unverified"):
            notice = (f"AI 解讀中有數字無法在資料包核對（{'、'.join(nar['unverified'][:6])}），"
                      "請以下方數字為準；這份解讀不會快取，重新開啟會重寫。")
    return render(p, nar, theme=theme, notice=notice)


def render(p, nar=None, theme=None, notice=None):
    nar = nar or {}
    name = p.get("name") or ""
    industry = nar.get("industry")
    title = f"{name} {p['stock_id']}".strip()
    notices = [n for n in (notice, p.get("errors") and "讀取失敗、以「無資料」呈現的段落：" + "、".join(p["errors"])) if n]
    head = (f'<div class="hd"><div class="hd-title">{_e(name)} <span class="code">{_e(p["stock_id"])}'
            f'{" · " + _e(industry) if industry else ""}</span></div>'
            f'<div class="hd-sub">資料基準日 {_e(p["as_of"])}｜基本面 × 合約負債 × 籌碼面 × 估值 × 技術面'
            f'{"" if nar else "｜（未附解讀，只列數字）"}</div>'
            f'{"".join(f"<div class=notice>{_e(n)}</div>" for n in notices)}</div>')
    body = "".join([head, verdicts(nar) if nar else "", fundamentals(p, nar), contract(p, nar), chips(p, nar),
                    valuation(p, nar), technical(p, nar), footer(p, nar)])
    theme_attr = f' data-theme="{theme}"' if theme in ("light", "dark") else ""
    return (f'<!doctype html><html lang="zh-Hant"{theme_attr}><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{_e(title)} 個股分析</title><style>{CSS}</style></head>'
            f'<body><div class="root">{body}</div></body></html>')


CSS = """
:root{color-scheme:light;--surface-1:#fcfcfb;--surface-2:#f3f2ee;--text-primary:#14130f;--text-secondary:#52514e;
--text-muted:#8b897f;--muted:#8b897f;--grid:#e1e0d9;--card-border:rgba(11,11,11,.10);--card-bg:#fff;--up:#d03b3b;
--down:#1f8a3b;--neutral:#b8860b;--accent:#2a68c9;--bar-fill:#4c8bda;--bar-track:#e7e6e0}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--surface-1:#171715;--surface-2:#1f1f1c;
--text-primary:#f4f3ef;--text-secondary:#c3c2b7;--text-muted:#8b897f;--grid:#2c2c2a;--card-border:rgba(255,255,255,.10);
--card-bg:#1d1d1a;--up:#e66767;--down:#4bc47a;--neutral:#d9ad3f;--accent:#6ea8ec;--bar-fill:#5b9bdc;--bar-track:#302f2b}}
:root[data-theme="dark"]{color-scheme:dark;--surface-1:#171715;--surface-2:#1f1f1c;--text-primary:#f4f3ef;
--text-secondary:#c3c2b7;--text-muted:#8b897f;--grid:#2c2c2a;--card-border:rgba(255,255,255,.10);--card-bg:#1d1d1a;
--up:#e66767;--down:#4bc47a;--neutral:#d9ad3f;--accent:#6ea8ec;--bar-fill:#5b9bdc;--bar-track:#302f2b}
*{box-sizing:border-box}
body{margin:0;background:var(--surface-1);color:var(--text-primary);
font-family:system-ui,-apple-system,"Segoe UI","PingFang TC","Noto Sans TC",sans-serif;line-height:1.55}
.root{max-width:1180px;margin:0 auto;padding:22px 16px 16px}
.hd{margin-bottom:14px;padding-bottom:14px;border-bottom:1px solid var(--card-border)}
.hd-title{font-size:21px;font-weight:800}.hd-title .code{color:var(--text-muted);font-weight:600;font-size:15px;margin-left:6px}
.hd-sub{font-size:12.5px;color:var(--text-secondary);margin-top:5px}
.notice{font-size:12px;color:var(--neutral);background:var(--surface-2);border-radius:8px;padding:6px 10px;margin-top:8px}
.section{margin-top:22px}.section-title{font-size:15px;font-weight:700;margin-bottom:10px;display:flex;align-items:center;gap:8px}
.section-title .n{color:var(--text-muted);font-weight:600;font-size:12px}
.card{font-size:12.5px;background:var(--card-bg);border:1px solid var(--card-border);border-radius:10px;padding:14px 16px;min-width:0}
.grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media (max-width:760px){.grid4{grid-template-columns:repeat(2,1fr)}.grid2{grid-template-columns:1fr}}
.sub{font-size:12px;color:var(--text-secondary);font-weight:600;margin-bottom:8px}
.vt-label{font-size:12px;color:var(--text-secondary);font-weight:600}
.vt-badge{display:inline-block;margin-top:6px;font-size:12.5px;font-weight:700;padding:3px 10px;border-radius:999px}
.badge-pos{background:rgba(208,59,59,.13);color:var(--up)}.badge-neg{background:rgba(31,138,59,.14);color:var(--down)}
.badge-neu{background:rgba(184,134,11,.16);color:var(--neutral)}.badge-watch{background:rgba(140,140,140,.16);color:var(--text-secondary)}
.vt-note{font-size:12px;color:var(--text-secondary);margin-top:8px}
.note{font-size:11.5px;color:var(--text-secondary);margin-top:10px;line-height:1.7}
.muted{color:var(--text-muted)}.empty{color:var(--text-muted);font-size:12.5px;padding:6px 0}
.table-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{text-align:right;color:var(--text-muted);font-weight:600;padding:5px 8px;border-bottom:1px solid var(--grid);white-space:nowrap}
th:first-child,td:first-child{text-align:left}
td{text-align:right;padding:5px 8px;border-bottom:1px solid var(--grid);font-variant-numeric:tabular-nums;white-space:nowrap}
tr:last-child td{border-bottom:none}
.pos{color:var(--up)}.neg{color:var(--down)}
.bar-row{display:flex;align-items:center;gap:8px;margin:5px 0;font-size:11.5px}
.bar-row .lbl{width:42px;color:var(--text-muted);flex-shrink:0}
.bar-row .track{flex:1;background:var(--bar-track);border-radius:4px;height:14px;position:relative;overflow:hidden;min-width:30px}
.bar-row .fill{position:absolute;left:0;top:0;bottom:0;background:var(--bar-fill);border-radius:4px}
.bar-row .val{width:104px;text-align:right;color:var(--text-secondary);flex-shrink:0;font-variant-numeric:tabular-nums}
.bar-row .yoy{width:58px;text-align:right;flex-shrink:0;font-weight:600}
.broker-bars{display:flex;flex-direction:column;gap:4px}
.bb-row{display:flex;align-items:center;gap:8px;font-size:11.5px}
.bb-row .nm{width:110px;color:var(--text-secondary);flex-shrink:0;text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bb-row .bar{height:12px;border-radius:3px;max-width:calc(100% - 180px)}.bb-row .amt{font-size:11px;color:var(--text-muted);width:62px}
.chip-stat{display:flex;justify-content:space-between;gap:12px;padding:6px 0;border-bottom:1px dashed var(--grid);font-size:12.5px}
.chip-stat:last-of-type{border-bottom:none}.chip-stat .k{color:var(--text-secondary);flex-shrink:0}
.chip-stat .v{font-weight:700;text-align:right}
.tile{background:var(--surface-2);border-radius:8px;padding:10px 12px}.tile-k{font-size:11.5px;color:var(--text-muted)}
.tile-v{font-size:18px;font-weight:800;font-variant-numeric:tabular-nums}
.gauge{margin-top:14px}.gauge-track{position:relative;height:10px;border-radius:5px;
background:linear-gradient(90deg,var(--down),var(--neutral),var(--up));opacity:.85}
.gauge-mark{position:absolute;top:-4px;width:4px;height:18px;margin-left:-2px;background:var(--text-primary);border-radius:2px}
.gauge-lbl{display:flex;justify-content:space-between;font-size:11px;color:var(--text-muted);margin-top:4px}
.ladder{position:relative;margin:10px 0 6px;border-left:2px solid var(--grid);margin-left:118px}
.ladder .band{position:absolute;left:0;width:46%;opacity:.2;border-radius:2px}
.ladder .ltag{position:absolute;left:-118px;width:110px;text-align:right;font-size:11px;color:var(--text-secondary);transform:translateY(-50%)}
.ladder .lval{position:absolute;left:8px;font-size:11px;font-weight:700;transform:translateY(-50%);white-space:nowrap}
.price-now{position:absolute;left:0;right:0;height:2px;background:var(--accent);opacity:.7}
.ladder .now{color:var(--accent);font-weight:800;font-size:12px}
.foot{margin-top:22px;padding-top:12px;border-top:1px solid var(--card-border);font-size:11.5px;color:var(--text-muted);line-height:1.7}
.pill{display:inline-block;font-size:11px;font-weight:700;padding:2px 8px;border-radius:999px;background:var(--surface-2);
color:var(--text-secondary);margin:0 6px 4px 0}
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("code", help="台股代號，可帶 .TW／.TWO")
    ap.add_argument("--date", default=None, help="資料基準日 YYYY-MM-DD，預設 price 最新一日")
    ap.add_argument("--data", help="沿用既有資料包 JSON（不重抓）")
    ap.add_argument("--dump-data", help="把資料包 JSON 寫到這個路徑後結束")
    ap.add_argument("--narrative", help="解讀 JSON（verdicts／notes／followups／industry）")
    ap.add_argument("--print-prompt", action="store_true", help="印出寫解讀用的完整 prompt（規則＋資料包）後結束")
    ap.add_argument("--no-branch", action="store_true", help="不連網查分點")
    ap.add_argument("-o", "--out", help="HTML 輸出路徑，預設印到 stdout")
    args = ap.parse_args(argv)
    if args.data:
        p = json.loads(Path(args.data).read_text(encoding="utf-8"))
    else:
        from src.services import tw_stock_dossier

        try:
            p = tw_stock_dossier.build(args.code, as_of=args.date, branch=not args.no_branch)
        except LookupError as exc:
            raise SystemExit(str(exc)) from exc
    if args.print_prompt:
        print(narrative_prompt(p))
        return
    if args.dump_data:
        Path(args.dump_data).write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")
        return
    nar = json.loads(Path(args.narrative).read_text(encoding="utf-8")) if args.narrative else None
    html = render(p, nar)
    if args.out:
        Path(args.out).write_text(html, encoding="utf-8")
    else:
        print(html)


if __name__ == "__main__":
    main()
