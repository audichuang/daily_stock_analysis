"""台股個股四維度資料包：基本面 × 合約負債 × 籌碼 × 估值 × SMC 技術結構。

唯讀本地 `market` schema（`.env` 的 `DATABASE_URL`），券商分點另即時查富邦 DJ 前 15 名
（`--no-branch` 關閉）。只輸出數字與出處，不下結論——給人或 LLM 寫報告用；查不到的欄位
一律印「無資料」，不估算。

    uv run --env-file .env python scripts/tw_stock_dossier.py 3324
    uv run --env-file .env python scripts/tw_stock_dossier.py 3324.TWO --date 2026-08-28 --json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from decimal import ROUND_HALF_UP, Decimal
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
from sqlalchemy import text

from data_provider.tw_institutional_trend import compute_institutional_trend
from data_provider.tw_margin_trend import compute_margin_trend
from market_data import market_repo
from market_data.db import get_engine
from market_data.financial_statement import afterIFRS
from market_data.revenue_deadline import effective_announce_dates
from src.services.market_symbol_utils import split_suffix_symbol

logger = logging.getLogger(__name__)

NA = "無資料"
# income_sheet 的 date 是公告截止日，反查 afterIFRS（唯一真源）：(月, 日) -> 季
_QUARTER_OF = {(d.month, d.day): q for q in (1, 2, 3, 4) for d in [afterIFRS(2001, q)]}
_INCOME = {"revenue": "營業收入合計", "gross": "營業毛利（毛損）", "op": "營業利益（損失）",
           "net": "本期淨利（淨損）", "eps": "基本每股盈餘合計"}
_CONTRACT = ("合約負債－流動", "合約負債－非流動")


def _sql(engine, sql, **params):
    return pd.read_sql(text(sql), engine, params=params)


def _opt(v):
    """NaN／None -> None，其餘轉 float（JSON 與「無資料」判斷都靠 None）。"""
    return None if v is None or pd.isna(v) else float(v)


def _half_up_1dp(x):
    """四捨五入到小數 1 位（half-up）。float 的 66.95 會因二進位表示被 f-string 印成 67.0 或 66.9，先在這裡定案。"""
    return float(Decimal(str(x)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _revenue_yoy(r, by_month):
    """月營收年增率（%，1 位小數）：有去年同月營收就自己算，否則退回庫裡存的 yoy（本身已四捨五入到 2 位）。"""
    prev = by_month.get((r.revenue_month.year - 1, r.revenue_month.month))
    cur, prev = _opt(r.revenue), _opt(prev)  # revenue 可為 NULL（NaN）：不能用真值判斷
    if cur is not None and prev is not None and prev > 0:
        return _half_up_1dp(Decimal(int(cur)) / Decimal(int(prev)) * 100 - 100)
    y = _opt(r.yoy)
    return None if y is None else _half_up_1dp(y)


def _quarter_label(d):
    d = pd.Timestamp(d)
    q = _QUARTER_OF.get((d.month, d.day))
    if q is None:
        return str(d.date())
    return f"{d.year - 1 if q == 4 else d.year}Q{q}"


def fundamentals(engine, sid, as_of, *, pit=False):
    """``pit=True``（歷史基準日回放）時，月營收改以法定公告期限（`market_data.revenue_deadline`，
    含保險類 15 日與休市順延）判斷 as_of 當天看不看得到；live 照 DB 佔位公告日（有就是已公告）。"""
    # 多抓 2 列：pit 篩掉的最多是最新一個月（有效公告日最多晚約兩週），篩完仍要有 36 列給 24 個月 TTM 與 13 個月明細
    rev = _sql(engine, "SELECT revenue_month, revenue, yoy, announce_date FROM market.monthly_revenue "
                       "WHERE stock_id = :s AND (announce_date IS NULL OR announce_date <= :d) "
                       "ORDER BY revenue_month DESC LIMIT 38", s=sid, d=as_of)
    if pit and len(rev):
        eff = effective_announce_dates(pd.Series([sid] * len(rev), index=rev.index),
                                       rev["announce_date"], rev["revenue_month"])
        rev = rev[eff.isna() | (eff <= pd.Timestamp(as_of))]
    rev = rev.head(36)
    by_month = {(r.revenue_month.year, r.revenue_month.month): r.revenue for r in rev.itertuples()}
    months = [{"month": f"{r.revenue_month:%Y-%m}",
               "revenue_k": None if pd.isna(r.revenue) else int(r.revenue),
               "yoy_pct": _revenue_yoy(r, by_month),
               "announced": None if pd.isna(r.announce_date) else str(r.announce_date)}
              for r in rev.head(13).itertuples()][::-1]
    ttm_yoy = None
    rev = rev.head(24)
    # 要連續 24 個月才算：中間缺月時兩個 12 列窗口會錯開，算出來不是「近 12 個月」
    span = None if len(rev) != 24 or rev.revenue.isna().any() else (
        (rev.revenue_month.iloc[0].year - rev.revenue_month.iloc[-1].year) * 12
        + rev.revenue_month.iloc[0].month - rev.revenue_month.iloc[-1].month)
    if span == 23:
        last, prev = rev.revenue.iloc[:12].sum(), rev.revenue.iloc[12:].sum()
        ttm_yoy = round((last / prev - 1) * 100, 1) if prev else None
    inc = _sql(engine, "SELECT date, account, value FROM market.financial_statement "
                       "WHERE stock_id = :s AND statement_type = 'income_sheet' AND date <= :d "
                       "AND account = ANY(:a) ORDER BY date", s=sid, d=as_of, a=list(_INCOME.values()))
    quarters = []
    if not inc.empty:
        wide = inc.pivot_table(index="date", columns="account", values="value", aggfunc="last")
        for d, r in wide.tail(8).iterrows():
            revenue = r.get(_INCOME["revenue"])

            def pct(key, r=r, revenue=revenue):
                v = r.get(_INCOME[key])
                return None if revenue in (None, 0) or pd.isna(revenue) or pd.isna(v) else round(v / revenue * 100, 2)

            eps = r.get(_INCOME["eps"])
            quarters.append({"quarter": _quarter_label(d), "gross_margin": pct("gross"),
                             "op_margin": pct("op"), "net_margin": pct("net"),
                             "eps": _opt(eps)})
    return {"monthly_revenue": months, "ttm_revenue_yoy_pct": ttm_yoy, "quarters": quarters}


def contract_liabilities(engine, sid, as_of):
    df = _sql(engine, "SELECT date, sum(value) AS v FROM market.financial_statement "
                      "WHERE stock_id = :s AND statement_type = 'balance_sheet' AND date <= :d "
                      "AND account = ANY(:a) GROUP BY date ORDER BY date", s=sid, d=as_of, a=list(_CONTRACT))
    return [{"quarter": _quarter_label(r.date), "contract_liabilities_k": float(r.v)}
            for r in df.tail(8).itertuples()]


# 集保每週五一筆，遇假日提前（實測相鄰兩筆隔 6~8 天）；超過這個間隔代表中間缺週
_MAX_WEEK_GAP_DAYS = 9


def holding_summary(hd):
    """holding_dist 的 level 15／17 列 -> 千張大戶比率、週變化、股東數；無資料回 None。

    週變化只在最新兩筆是**相鄰週**時才給：回補會跳過解析失敗的週，直接相減會把兩週的
    變化標成「週變化」。"""
    if hd is None or hd.empty:
        return None
    w = hd.pivot_table(index="date", columns="level", values=["pct", "holders"]).sort_index()
    cur = w.iloc[-1]
    wow = None
    if len(w) > 1:
        gap = (pd.Timestamp(w.index[-1]) - pd.Timestamp(w.index[-2])).days
        if gap <= _MAX_WEEK_GAP_DAYS:
            wow = round(float(cur[("pct", 15)] - w.iloc[-2][("pct", 15)]), 2)
    return {"as_of": str(w.index[-1]), "big_holder_pct": float(cur[("pct", 15)]),
            "big_holder_pct_wow": wow,
            "total_holders": int(cur[("holders", 17)]) if not pd.isna(cur.get(("holders", 17))) else None}


def chips(engine, sid, as_of, sessions, branch=True):
    start = (pd.Timestamp(as_of) - pd.Timedelta(days=60)).date()
    out = {"institutional": None, "margin": None, "holding": None, "branch": None}
    # 累計與變化沿用個股報告 prompt 的同一套算法（窗口內有缺值就不給）
    inst = market_repo.institutional(sid, start=start, end=as_of, engine=engine)
    trend = compute_institutional_trend(inst.to_dict("records"), None, None)
    if trend:
        def lots(v):
            return None if v is None else round(v / 1000)

        out["institutional"] = {"as_of": trend["as_of"],
                                **{f"{a}_{k}d_lots": lots(trend[a][f"cum_{k}d"])
                                   for a in ("foreign", "trust", "dealer", "total") for k in (5, 20)}}
    mg = market_repo.margin(sid, start=start, end=as_of, engine=engine)
    out["margin"] = compute_margin_trend(mg.to_dict("records")) or None
    try:
        hd = _sql(engine, "SELECT date, level, holders, pct FROM market.holding_dist WHERE stock_id = :s "
                          "AND date <= :d AND level IN (15, 17) ORDER BY date DESC LIMIT 4", s=sid, d=as_of)
    except pd.errors.DatabaseError:     # 表還沒 migration（holding_dist 是 2026-10 新增）
        hd = pd.DataFrame()
    out["holding"] = holding_summary(hd)
    if branch and sessions:
        from data_provider.tw_broker_branch import fetch_branch_flows

        last = pd.Timestamp(sessions[-1]).date()
        five = pd.Timestamp(sessions[-5:][0]).date()
        with ThreadPoolExecutor(max_workers=2) as pool:      # 兩個互不相依的富邦請求，同時發
            day, week = pool.map(lambda span: fetch_branch_flows(sid, *span), [(last,), (five, last)])
        out["branch"] = {"day": day, "five_sessions": week,
                         "note": "富邦 DJ 前 15 名買超／賣超分點；HHI 只在前 15 名買超分點內計算"}
    return out


def valuation(engine, sid, as_of):
    df = _sql(engine, "SELECT date, pe_ratio, pb_ratio, dividend_yield FROM market.valuation "
                      "WHERE stock_id = :s AND date <= :d AND date >= :st ORDER BY date",
              s=sid, d=as_of, st=(pd.Timestamp(as_of) - pd.DateOffset(years=3)).date())
    if df.empty:
        return None
    last = df.iloc[-1]
    pe = df.pe_ratio.dropna()
    pct = None
    if len(pe) >= 120 and pd.notna(last.pe_ratio):
        pct = round(float((pe <= last.pe_ratio).mean() * 100), 1)
    return {"as_of": str(last.date), "pe": _opt(last.pe_ratio), "pb": _opt(last.pb_ratio),
            "dividend_yield": _opt(last.dividend_yield),
            "pe_percentile_3y": pct, "pe_samples_3y": int(len(pe))}


def technicals(engine, sid, as_of):
    from src.services import smc_structure

    start = (pd.Timestamp(as_of) - pd.Timedelta(days=400)).date()
    px = market_repo.price_history(sid, start=start, end=as_of, engine=engine)
    if px.empty:
        return None, []
    px["date"] = pd.to_datetime(px["date"])
    mult = market_repo.front_adjust_multipliers(sid, px["date"], engine=engine).to_numpy()
    for c in ("open", "high", "low", "close"):
        px[c] = pd.to_numeric(px[c], errors="coerce") * mult
    smc = smc_structure.analyze(px[["date", "open", "high", "low", "close"]])
    return smc, list(px["date"].dt.date)


def _check_suffix(code):
    """後綴寫錯市場（2330.TWO）就拒絕，避免靜默回傳另一個市場同代號的資料；索引裡兩邊都查不到時放行（新掛牌）。"""
    parts = split_suffix_symbol(code)
    if not parts or parts[1] not in ("TW", "TWO"):
        return
    from src.data.stock_index_loader import get_stock_name_index_map

    names = get_stock_name_index_map()
    sid, suffix = parts
    other = f"{sid}.{'TWO' if suffix == 'TW' else 'TW'}"
    if f"{sid}.{suffix}" not in names and other in names:
        raise LookupError(f"{code} 應為 {other}")


def build(code, as_of=None, branch=True, engine=None):
    _check_suffix(code)
    sid = (split_suffix_symbol(code) or (code.strip().upper(),))[0]
    engine = engine or get_engine()
    d = _sql(engine, "SELECT max(date) AS d FROM market.price WHERE stock_id = :s"
             + (" AND date <= :a" if as_of else ""), s=sid, a=as_of).d.iloc[0]
    if d is None or pd.isna(d):
        raise LookupError(f"{sid}: market.price 查無資料")
    pit = as_of is not None   # 指定基準日＝歷史回放；Web／看板不帶日期，走 live
    as_of = pd.Timestamp(d).date()
    errors = []

    def safe(label, fn, empty):
        """單段失敗只讓該段變「無資料」並記在 errors，不拖垮整份資料包。"""
        try:
            return fn()
        except Exception as exc:
            logger.warning("[tw_stock_dossier] %s %s 讀取失敗: %s", sid, label, exc)
            errors.append(label)
            return empty

    smc, sessions = safe("技術面", lambda: technicals(engine, sid, as_of), (None, []))
    p = {"stock_id": sid, "name": safe("名稱", lambda: stock_name(sid, engine), None), "as_of": str(as_of),
         "fundamentals": safe("基本面", lambda: fundamentals(engine, sid, as_of, pit=pit),
                              {"monthly_revenue": [], "ttm_revenue_yoy_pct": None, "quarters": []}),
         "contract_liabilities": safe("合約負債", lambda: contract_liabilities(engine, sid, as_of), []),
         "chips": safe("籌碼面", lambda: chips(engine, sid, as_of, sessions, branch=branch),
                       {"institutional": None, "margin": None, "holding": None, "branch": None}),
         "valuation": safe("估值", lambda: valuation(engine, sid, as_of), None), "smc": smc,
         "errors": errors}
    # 轉成 JSON 安全的型別（日期 -> 字串），CLI --json、HTML 渲染與 Web 快取共用同一個形狀
    return json.loads(json.dumps(p, ensure_ascii=False, default=str))


def stock_name(sid, engine=None):
    name = (market_repo.stock_info(sid, engine=engine) or {}).get("name")
    # ponytail: stock_info 只有上市，上櫃名稱退回前端股票索引；crawl_stock_info 補抓上櫃後可拿掉
    if not name:
        from src.data.stock_index_loader import get_stock_name_index_map

        names = get_stock_name_index_map()
        name = names.get(f"{sid}.TWO") or names.get(f"{sid}.TW")
    return name


def _f(v, spec="", suffix=""):
    return NA if v is None or (isinstance(v, float) and pd.isna(v)) else f"{v:{spec}}{suffix}"


def render(p):
    w = []
    w.append(f"# {p['stock_id']} {p['name'] or ''} 四維度資料包（資料基準日 {p['as_of']}）\n")
    if p.get("errors"):
        w.append(f"> 讀取失敗、以「無資料」呈現的段落：{'、'.join(p['errors'])}\n")
    f = p["fundamentals"]
    w.append("## 基本面\n\n| 月份 | 營收(千元) | YoY% | 公告日 |\n|---|---:|---:|---|")
    w += [f"| {m['month']} | {_f(m['revenue_k'], ',')} | {_f(m['yoy_pct'], '+.1f')} | {m['announced'] or NA} |"
          for m in f["monthly_revenue"]] or [f"| {NA} | | | |"]
    w.append(f"\n近 12 個月累計營收年增：{_f(f['ttm_revenue_yoy_pct'], '+.1f', '%')}\n")
    w.append("| 季度 | 毛利率% | 營益率% | 淨利率% | EPS |\n|---|---:|---:|---:|---:|")
    w += [f"| {q['quarter']} | {_f(q['gross_margin'], '.2f')} | {_f(q['op_margin'], '.2f')} | "
          f"{_f(q['net_margin'], '.2f')} | {_f(q['eps'], '.2f')} |" for q in f["quarters"]] or [f"| {NA} | | | | |"]
    cl = p["contract_liabilities"]
    w.append("\n## 合約負債（訂單能見度）\n")
    w.append(" / ".join(f"{c['quarter']} {c['contract_liabilities_k']:,.0f} 千元" for c in cl)
             if cl else "資產負債表沒有單獨列示合約負債科目（可能併入其他流動負債），無法評估。")
    c = p["chips"]
    w.append("\n## 籌碼面\n")
    i = c["institutional"]
    w.append(f"- 三大法人（截至 {i['as_of']}，張）：外資 5 日 {_f(i['foreign_5d_lots'], '+,')}／20 日 "
             f"{_f(i['foreign_20d_lots'], '+,')}；投信 5 日 {_f(i['trust_5d_lots'], '+,')}／20 日 "
             f"{_f(i['trust_20d_lots'], '+,')}；自營 5 日 {_f(i['dealer_5d_lots'], '+,')}"
             if i else f"- 三大法人：{NA}")
    m = c["margin"]
    w.append(f"- 融資餘額 {m['margin_balance']:,} 張（5 場 {_f(m['margin_chg_5'], '+,')}、20 場 "
             f"{_f(m['margin_chg_20'], '+,')}）；融券餘額 {_f(m['short_balance'], ',')} 張、券資比 "
             f"{_f(m['short_margin_ratio'], '.2f', '%')}，截至 {m['as_of']}"
             if m else f"- 融資融券：{NA}")
    h = c["holding"]
    w.append(f"- 千張大戶持股 {h['big_holder_pct']:.2f}%（週變化 {_f(h['big_holder_pct_wow'], '+.2f', 'pp')}），"
             f"總股東 {_f(h['total_holders'], ',')} 人，集保資料日 {h['as_of']}"
             if h else f"- 集保股權分散：{NA}（未回補；`market_data.cli holding-history {p['stock_id']}`）")
    b = c["branch"]
    if b:
        for label, x in (("當日", b["day"]), ("近 5 日", b["five_sessions"])):
            if not x:
                w.append(f"- 分點（{label}）：{NA}")
                continue
            top = "、".join(f"{r['branch']} +{r['net']:,.0f}" for r in x["buy"][:5])
            bot = "、".join(f"{r['branch']} -{r['net']:,.0f}" for r in x["sell"][:5])
            w.append(f"- 分點（{label} {x['start']}~{x['end']}）買超：{top}；賣超：{bot}；"
                     f"前 15 名買超 HHI {_f(x.get('hhi_buy_top15'), ',.0f')}、平均買超成本 {_f(x['avg_buy_cost'], ',.2f')}")
        w.append(f"  - 註：{b['note']}")
    v = p["valuation"]
    w.append("\n## 估值\n")
    w.append(f"- 本益比 {_f(v['pe'], '.2f')}（近 3 年百分位 {_f(v['pe_percentile_3y'], '.1f', '%')}，"
             f"樣本 {v['pe_samples_3y']} 日）、股價淨值比 {_f(v['pb'], '.2f')}、殖利率 {_f(v['dividend_yield'], '.2f', '%')}，"
             f"截至 {v['as_of']}" if v else f"- {NA}")
    s = p["smc"]
    w.append("\n## 技術面（SMC，前復權日 K；定義見 src/services/smc_structure.py）\n")
    if not s:
        w.append(NA)
    else:
        w.append(f"- 現價 {s['price']:,.2f}")
        for e in s["events"]:
            w.append(f"- {pd.Timestamp(e['date']).date()} {e['kind']} {e['direction']}（{'突破' if e['direction'] == 'bullish' else '跌破'} {e['level']:,.2f}）")
        if s["fib"]:
            fb = s["fib"]
            last = s.get("last_event")
            ote = "OTE" if not last else "OTE 多方" if last["direction"] == "bullish" else "OTE 空方"   # 與 HTML 報告同一套標籤
            w.append(f"- Fib 位置 {fb['position'] * 100:.1f}%（{fb['zone']}，區間 {fb['range_low']:,.2f}~"
                     f"{fb['range_high']:,.2f}）；{ote} {fb['ote_low']:,.2f}~{fb['ote_high']:,.2f}"
                     f"（{'在內' if fb['in_ote'] else '不在內'}）")
        w += [f"- 有效 OB（{o['direction']}）{o['low']:,.2f}~{o['high']:,.2f}（{pd.Timestamp(o['date']).date()}）"
              for o in s["order_blocks"]]
        w += [f"- 未回補 FVG（{g['direction']}）{g['low']:,.2f}~{g['high']:,.2f}（{pd.Timestamp(g['date']).date()}）"
              for g in s["fvgs"]]
        w.append(f"- 上方流動性 BSL：{', '.join(f'{x:,.2f}' for x in s['bsl']) or NA}；"
                 f"下方流動性 SSL：{', '.join(f'{x:,.2f}' for x in s['ssl']) or NA}")
    return "\n".join(w) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("code", help="台股代號，可帶 .TW／.TWO")
    ap.add_argument("--date", default=None, help="資料基準日 YYYY-MM-DD，預設 price 最新一日")
    ap.add_argument("--json", action="store_true", help="輸出 JSON")
    ap.add_argument("--no-branch", action="store_true", help="不連網查分點")
    args = ap.parse_args(argv)
    try:
        p = build(args.code, as_of=args.date, branch=not args.no_branch)
    except LookupError as exc:
        sys.exit(str(exc))
    print(json.dumps(p, ensure_ascii=False, indent=1) if args.json else render(p))


if __name__ == "__main__":
    main()
