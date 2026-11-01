# -*- coding: utf-8 -*-
"""台股預篩：從 market schema 算每檔因子，並組成選股 pipeline 用的快照。

`scripts/screen_tw.py` 與 Web 選股共用這裡。Docker 映像不含 `scripts/`，serve 路徑不能 import
腳本，所以計算放在這個平面模組（`COPY market_data/*.py`）。

映像裡也沒有種子檔：`exclude_otc_revenue` 會因此拒絕執行，`seed_market_map` 回空。Web 選股
不做月營收篩選，一律 `include_otc_revenue=True`，市場別改讀 `valuation`／`institutional` 的
`market` 欄與 `stock_info`。
"""

import sys
import threading
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

from market_data.adjust import factors_to_panel, is_common_stock, load_factors
from market_data.db import get_engine
from market_data.revenue_deadline import (
    MAX_DEADLINE_LAG_DAYS,
    apply_revenue_deadline,
    is_historical_replay,
)

REPO = Path(__file__).resolve().parent.parent
SEED_CSV = REPO / "scripts" / "stock_index_seeds" / "stock_list_tw.csv"

# TWSE 產業別代碼（stock_info.industry；上櫃股為 NULL）
INDUSTRY = {
    "01": "水泥", "02": "食品", "03": "塑膠", "04": "紡織", "05": "電機機械",
    "06": "電器電纜", "08": "玻璃陶瓷", "09": "造紙", "10": "鋼鐵", "11": "橡膠",
    "12": "汽車", "14": "建材營造", "15": "航運", "16": "觀光餐旅", "17": "金融保險",
    "18": "貿易百貨", "19": "綜合", "20": "其他", "21": "化學", "22": "生技醫療",
    "23": "油電燃氣", "24": "半導體", "25": "電腦及週邊", "26": "光電", "27": "通信網路",
    "28": "電子零組件", "29": "電子通路", "30": "資訊服務", "31": "其他電子",
    "32": "文化創意", "33": "農業科技", "34": "電子商務", "35": "綠能環保",
    "36": "數位雲端", "37": "運動休閒", "38": "居家生活", "91": "存託憑證",
}


# 月營收保鮮期，**45 個曆日、以公告日計**（不是 45 個交易日／交易列）。
# **改這裡就要同步 `scripts/measure_signal_forward.py` 的 `REVENUE_STALE_DAYS` 與
# `pit_revenue_panel`**——兩邊口徑一差，量測到的就不是會下單的那組訊號，而那份數字是
# 決策依據（獨立審查實測：視窗差 918 vs 925 個事件只有 877 重疊；交易列 vs 曆日差 44 個
# signal cell、並改變一個事件——**當時那兩個池子均值是舊固定成本口徑，已作廢**，
# 現行數字見 `docs/tw-swing-pipeline.md`）。同時公告日取**嚴格小於** as_of：月營收常在
# 盤後才上 MOPS。契約與已驗證到什麼程度見 `docs/tw-swing-pipeline.md`。
REVENUE_STALE_DAYS = 45

MIN_BARS = 66  # 算 hi60_prior（不含最近 5 天的 60 日高）需要的最少 K 棒


def exclude_otc_revenue(rev: pd.DataFrame, seed_csv: Path | None = None) -> pd.DataFrame:
    """拿掉**目前上櫃**公司的月營收列，讓營收條件維持上市口徑。

    `market.monthly_revenue` 自 2026-09 起也收上櫃（`crawl_monthly_revenue` 抓 sii+otc），
    但 `docs/tw-swing-pipeline.md` 的每一個基準數字（974 個事件、`confidence` 錨點 20.4%、
    組合 Sharpe）都是在「上櫃 yoy 全為 null」的池子上量的。讓上櫃直接流進 live 漏斗等於
    換了池子卻沿用舊池子的錨點——所以預設排除，要放進來得帶 `--include-otc-revenue`，
    而且要先帶同一旗標重跑 `scripts/measure_signal_forward.py`（`make measure` 不帶旗標，量的還是舊池子）
    取得新池子的基準，才能引用任何數字。

    上櫃名單取種子檔的 `.TWO`（`price.market` 全為 NULL、`stock_info` 只有上市）。已下市的
    上櫃公司不在種子檔裡，它們由 `cli revenue-pit` 補進來的列照舊保留——與修改前的池子逐列相同。
    """
    seed_csv = SEED_CSV if seed_csv is None else seed_csv
    if not seed_csv.exists():
        # 分不出誰是上櫃就不能宣稱池子沒變；靜默放行會讓錨點失效而沒人知道
        raise FileNotFoundError(f"{seed_csv} 不存在，無法排除上櫃月營收（或改帶 --include-otc-revenue）")
    otc = {sid for sid, market in seed_market_map(seed_csv).items() if market == "tpex"}
    return rev[~rev["stock_id"].astype(str).isin(otc)]


_SUFFIX_MARKET = {"TW": "twse", "TWO": "tpex"}


def seed_market_map(seed_csv: Path | None = None) -> dict:
    """``{代號: "twse"|"tpex"}``，依種子檔的 ``.TW``／``.TWO``；種子檔不存在回空 dict。

    市場別只能從這裡拿：`price.market` 全為 NULL、`stock_info` 只有上市。種子檔沒有的代號
    （已下市）就是市場未知。"""
    seed_csv = SEED_CSV if seed_csv is None else seed_csv
    if not seed_csv.exists():
        return {}
    codes = pd.read_csv(seed_csv, usecols=["ts_code"])["ts_code"].astype(str)
    out = {}
    for code in codes:
        sid, _, suffix = code.partition(".")
        market = _SUFFIX_MARKET.get(suffix)
        if market:
            out[sid] = market
    return out


# 估值只取 as_of 以前這個窗口內最近一天（曆日）。窗口夠涵蓋連假，又短到不會拿很舊的值當今天的
VALUATION_WINDOW_DAYS = 7
# 篩選用的「近 5 日」統計窗口（inst_5、margin_chg5 的場次數）
STAT_SESSIONS = 5


def data_freshness(px, inst, mgn, val) -> dict:
    """三張表各自的實際最新資料日，以及近 5 日統計實際涵蓋幾個場次。

    18:00 時 T86（法人）與融資常常還停在前一天，`inst_5`／`margin_chg5` 其實只涵蓋 4 個場次
    卻標「5 日」；呼叫端比對 as_of 決定要不要揭露。
    場次數的算法與 `build()` 的統計窗口一致：法人是窗口內**有資料的日數**（inst_5 就是加這些日），
    融資是 margin_ago 基準日之後到最新融資日之間的**價量場次**（margin_chg5 是兩端餘額相比）。
    """
    dates = sorted(px["date"].unique())
    out = {"inst_last": None, "inst_sessions": 0, "margin_last": None, "margin_sessions": 0,
           "val_date": None}
    if len(inst):
        out["inst_last"] = pd.Timestamp(inst["date"].max())
        if len(dates) >= STAT_SESSIONS:
            out["inst_sessions"] = int(
                inst.loc[inst["date"] >= dates[-STAT_SESSIONS], "date"].nunique())
    if len(mgn):
        out["margin_last"] = pd.Timestamp(mgn["date"].max())
        if len(dates) > STAT_SESSIONS:
            base = dates[-(STAT_SESSIONS + 1)]
            out["margin_sessions"] = sum(1 for d in dates if base < d <= out["margin_last"])
    if len(val) and "date" in val.columns and val["date"].notna().any():
        out["val_date"] = pd.Timestamp(val["date"].max())
    return out


def compute_factors(g: pd.DataFrame) -> dict:
    """單一標的的因子計算。g 需含 date/open/high/low/close/volume/turnover，且已按 date 升序。

    純函數、不碰 DB，方便測試（見 tests/test_screen_tw.py）。
    """
    close = g["close"]
    c0 = float(close.iloc[-1])
    ma = {n: float(close.rolling(n).mean().iloc[-1]) for n in (5, 10, 20, 60)}

    def ret(n):
        return c0 / float(close.iloc[-1 - n]) - 1 if len(g) > n else np.nan

    tr = pd.concat([
        g["high"] - g["low"],
        (g["high"] - close.shift()).abs(),
        (g["low"] - close.shift()).abs(),
    ], axis=1).max(axis=1)
    delta = close.diff()
    up = delta.clip(lower=0).tail(14).mean()
    down = (-delta.clip(upper=0)).tail(14).mean()
    hi20, lo20 = float(g["high"].tail(20).max()), float(g["low"].tail(20).min())
    vol20 = float(g["volume"].tail(20).mean())
    # 「剛起漲」要用**不含最近 5 天**的 60 日高當突破基準——含最近 5 天的話今天必然
    # 就是自己的高點，比不出「突破」。實測（前瞻報酬分布）以此定義的候選池 60 日內
    # 漲逾 30% 的機率是 20.4%（2026-10-26 重測），同池有月營收的基準率只有 12.0%。
    # 視窗是 61 根、t-65…t-5。**改這裡要同步 `measure_signal_forward.factors()` 的
    # `high.shift(5).rolling(61)`**：差一根就是量了一個不會下單的訊號（見 §REVENUE_STALE_DAYS
    # 上方的同步規則）。
    hi60_prior = float(g["high"].iloc[-66:-5].max()) if len(g) >= 66 else np.nan
    vol5 = float(g["volume"].tail(5).mean())
    vol60 = float(g["volume"].tail(60).mean())

    return {
        "close": c0,
        "ma5": ma[5], "ma10": ma[10], "ma20": ma[20], "ma60": ma[60],
        "d1": ret(1), "d5": ret(5), "d20": ret(20), "d60": ret(60),
        "bias20": c0 / ma[20] - 1,
        "atr_pct": float(tr.tail(14).mean()) / c0,
        "rsi14": 100 - 100 / (1 + up / down) if down else 100.0,
        "pos20": (c0 - lo20) / (hi20 - lo20) if hi20 > lo20 else np.nan,
        "from_hi60": c0 / float(g["high"].tail(60).max()) - 1,
        "turnover20": float(g["turnover"].tail(20).mean()),
        "vol_ratio": float(g["volume"].iloc[-1]) / vol20 if vol20 else np.nan,
        "hi60_prior": hi60_prior,
        "break_pct": c0 / hi60_prior - 1 if hi60_prior and hi60_prior > 0 else np.nan,
        "vol_ratio5": vol5 / vol60 if vol60 else np.nan,
    }


def load(engine, as_of: pd.Timestamp | None, include_otc_revenue: bool = False,
         *, exclude_fn=None, load_factors_fn=None):
    """拉基準日前 200 天的資料。**所有查詢都以 as_of 為上界**——指定歷史日期做回顧掃描時，
    少一個上界就是直接讀到未來資料（月營收與大盤指數都踩過）。指定 as_of 早於全市場最新
    價格日時，月營收另以法定公告期限（`market_data.revenue_deadline`）判斷可見。
    """
    with engine.connect() as c:
        latest = c.execute(text("select max(date) from market.price")).scalar()
        replay = is_historical_replay(as_of, latest)
        as_of = pd.Timestamp(as_of or latest)
        start = (as_of - pd.Timedelta(days=200)).date()
        px = pd.read_sql(text(
            "select stock_id, date, open, high, low, close, volume, turnover from market.price "
            "where date between :s and :e order by stock_id, date"
        ), c, params={"s": start, "e": as_of.date()}, parse_dates=["date"])
        inst = pd.read_sql(text(
            "select stock_id, date, foreign_net, trust_net, dealer_net from market.institutional "
            "where date between :s and :e"
        ), c, params={"s": (as_of - pd.Timedelta(days=45)).date(), "e": as_of.date()}, parse_dates=["date"])
        mgn = pd.read_sql(text(
            "select stock_id, date, margin_balance from market.margin where date between :s and :e"
        ), c, params={"s": (as_of - pd.Timedelta(days=20)).date(), "e": as_of.date()}, parse_dates=["date"])
        # 估值取 as_of 以前 7 曆日內「最近一天」整包：18:00 當日的 BWIBBU 通常還沒入庫，
        # 原本 `date = as_of` 查到 0 列、PE／PB／殖利率整欄 NaN（高息／低估值標籤永不觸發）。
        # 在 Python 取最新日而不用子查詢，才能用假 read_sql 驗窗口與挑日。
        val = pd.read_sql(text(
            "select stock_id, date, market, pe_ratio, pb_ratio, dividend_yield from market.valuation "
            "where date <= :d and date > :lo"
        ), c, params={"d": as_of.date(),
                      "lo": (as_of - pd.Timedelta(days=VALUATION_WINDOW_DAYS)).date()},
            parse_dates=["date"])
        if len(val):
            # 上市、上櫃各自發布，最新日可能差一天：分市場各取最新一天（NULL＝上市）
            mkt = val["market"].fillna("twse") if "market" in val else pd.Series("twse", index=val.index)
            val = val[val["date"] == val.groupby(mkt)["date"].transform("max")]
        val = val.drop(columns=["market"], errors="ignore")
        # 用 announce_date 設上界:營收在次月才公布,以 revenue_month 篩會提前看到未發布的數字
        rev_lo = as_of - pd.Timedelta(days=REVENUE_STALE_DAYS)
        # 指定日期早於最新場次時，DB 的佔位公告日（次月 10 日）早於法定期限（保險類 15 日、休市順延），
        # 改用共用的有效公告日（market_data.revenue_deadline，與 measure_signal_forward 同口徑）；
        # 有效公告日只會更晚，所以 SQL 下界放寬、上界照舊當預篩。live 不套：DB 有的就是已公告。
        sql_lo = rev_lo - pd.Timedelta(days=MAX_DEADLINE_LAG_DAYS) if replay else rev_lo
        rev = pd.read_sql(text(
            "select stock_id, revenue_month, announce_date, yoy, mom from market.monthly_revenue "
            "where announce_date >= :s and announce_date < :e"
        ), c, params={"s": sql_lo.date(), "e": as_of.date()},
            parse_dates=["revenue_month", "announce_date"])
        if replay and len(rev):
            ann = apply_revenue_deadline(rev, date_col="announce_date")["announce_date"]
            rev = rev[(ann >= rev_lo) & (ann < as_of)]
        rev = rev.drop(columns=["announce_date"], errors="ignore")
        if not include_otc_revenue:
            rev = (exclude_fn or exclude_otc_revenue)(rev)
        info = pd.read_sql(text("select stock_id, name, industry from market.stock_info"), c)
        idx = pd.read_sql(text(
            "select date, close, change from market.market_index where date <= :e order by date"
        ), c, params={"e": as_of.date()}, parse_dates=["date"])
    for col in ("open", "high", "low", "close", "volume", "turnover"):
        px[col] = px[col].astype(float)

    # 前復權:price 是未還原價,不套因子的話除息/分割跳空會被當成真實漲跌。
    # 實測未套與套用的差異:候選池 44→58 檔、Top25 僅 17 檔重疊、331 檔的 20 日報酬差逾 1pp。
    piv = px.pivot(index="date", columns="stock_id", values="close")
    adj = (load_factors_fn or load_factors)(engine, piv.index, piv.columns)
    if (adj == 1.0).all().all():
        print("**WARN price_adjustment 為空,價格未還原——先跑 market_data.cli adjust", file=sys.stderr)
    long_adj = adj.stack().rename("adj").reset_index()
    long_adj.columns = ["date", "stock_id", "adj"]
    px = px.merge(long_adj, on=["date", "stock_id"], how="left")
    px["adj"] = px["adj"].fillna(1.0)
    for col in ("open", "high", "low", "close"):
        px[col] = px[col] * px["adj"]
    px = px.drop(columns=["adj"])
    return as_of, px, inst, mgn, val, rev, info, idx


def build(as_of, px, inst, mgn, val, rev, info, idx, min_turnover, *, seed_csv: Path | None = None):
    dates = sorted(px["date"].unique())
    rows = []
    for sid, g in px.groupby("stock_id", sort=False):
        if g["date"].iloc[-1] != as_of or len(g) < MIN_BARS:
            continue
        rows.append({"stock_id": sid, **compute_factors(g)})
    df = pd.DataFrame(rows)

    for col in ("foreign_net", "trust_net", "dealer_net"):
        inst[col] = inst[col].astype(float)
    inst["ft"] = inst["foreign_net"] + inst["trust_net"] + inst["dealer_net"]
    for n in (5, 10, 20):
        if len(dates) >= n:
            # 用 >= dates[-n] 而非 > ——後者會排除第 n 天，讓 inst_5 實際只算 4 日
            agg = inst[inst["date"] >= dates[-n]].groupby("stock_id")["ft"].sum().rename(f"inst_{n}")
            df = df.merge(agg.reset_index(), on="stock_id", how="left")
    # 連續買超天數（含當日往前數）
    piv = inst.pivot_table(index="date", columns="stock_id", values="ft").sort_index()
    streak = (piv.tail(15) > 0).iloc[::-1].cummin().sum().rename("inst_streak")
    df = df.merge(streak.reset_index(), on="stock_id", how="left")

    mgn = mgn.sort_values("date")
    now = mgn.groupby("stock_id")["margin_balance"].last().rename("margin_now")
    ago = mgn[mgn["date"] <= dates[-6]].groupby("stock_id")["margin_balance"].last().rename("margin_ago")
    df = df.merge(now.reset_index(), on="stock_id", how="left").merge(ago.reset_index(), on="stock_id", how="left")
    df["margin_chg5"] = df["margin_now"].astype(float) / df["margin_ago"].astype(float).replace(0, np.nan) - 1

    df = df.merge(val[["stock_id", "pe_ratio", "pb_ratio", "dividend_yield"]], on="stock_id", how="left")
    last_rev = rev.sort_values("revenue_month").groupby("stock_id").last()[["revenue_month", "yoy", "mom"]]
    df = df.merge(last_rev.reset_index(), on="stock_id", how="left")
    df = df.merge(info[["stock_id", "industry"]], on="stock_id", how="left")

    names = dict(zip(info["stock_id"], info["name"]))
    seed_csv = SEED_CSV if seed_csv is None else seed_csv
    if seed_csv.exists():  # stock_info 只有上市 ~1100 檔，上櫃名稱靠種子檔補
        seed = pd.read_csv(seed_csv)
        seed_names = dict(zip(seed["ts_code"].str.split(".").str[0], seed["name"]))
        names = {**seed_names, **names}
    df["name"] = df["stock_id"].map(names).fillna("")
    df["industry"] = df["industry"].fillna("")
    df["is_etf"] = df["stock_id"].str.startswith("00")
    # 創新板（名稱後綴「-創」）：一般帳戶要簽風險預告書並符合資格條件才能買，不該出現在
    # 「下個交易日買什麼」的名單裡。全庫 25 檔只有 1 檔過得了 2 億門檻（7610），而它
    # 2026-01~07 漲 10 倍——在回測裡一筆就佔 13 年總損益的 85%，是最容易誤導的一類標的。
    df["is_tib"] = df["stock_id"].map(
        {s: str(n).endswith("-創") for s, n in names.items()}).fillna(False)

    market_d1 = float(idx["change"].iloc[-1] / (idx["close"].iloc[-1] - idx["change"].iloc[-1])) if len(idx) else 0.0
    return df, market_d1


# 快照窗口夠涵蓋連假，又不會把已下市很久的市場別帶進來。
_MARKET_LOOKUP_DAYS = 45
_MARKET_SUFFIX = {"twse": "TW", "tpex": "TWO"}
_DAILY_MIN_ROWS = 30


def resolve_markets(engine, as_of: pd.Timestamp, stock_ids) -> dict:
    """``{代號: "twse"|"tpex"}``。`price.market` 全為 NULL，只能從其他表推。

    種子檔優先（本機有、最完整）；映像裡沒有種子檔時，`market='tpex'` 的估值或法人列算上櫃，
    `stock_info` 算上市。都查不到就不收，不猜後綴：`.TW` 配到上櫃股會查不到報價。
    """
    wanted = {str(s) for s in stock_ids}
    out = {sid: market for sid, market in seed_market_map().items() if sid in wanted}
    missing = wanted - set(out)
    if not missing:
        return out
    since = (as_of - pd.Timedelta(days=_MARKET_LOOKUP_DAYS)).date()
    with engine.connect() as c:
        tpex = c.execute(text(
            "select stock_id from market.valuation where market = 'tpex' and date >= :s "
            "union select stock_id from market.institutional where market = 'tpex' and date >= :s"
        ), {"s": since}).scalars().all()
        listed = c.execute(text("select stock_id from market.stock_info")).scalars().all()
    tpex_ids, listed_ids = {str(s) for s in tpex}, {str(s) for s in listed}
    for sid in missing:
        if sid in tpex_ids:
            out[sid] = "tpex"
        elif sid in listed_ids:
            out[sid] = "twse"
    return out


def snapshot_frame(as_of, factors: pd.DataFrame, px: pd.DataFrame, shares: dict, markets: dict) -> pd.DataFrame:
    """把 `build()` 的因子表轉成選股快照欄位（純函式，方便測試）。

    只留普通股、排除創新板，與 `funnel` 同一個宇宙。缺股本（上櫃）時市值與週轉率留 NaN，
    不補 0：0 是真實讀數，會被 `*_max` 門檻放行。
    """
    pool = factors[factors["stock_id"].map(is_common_stock).astype(bool) & ~factors["is_tib"].astype(bool)].copy()
    last = px[px["date"] == as_of].set_index("stock_id")
    rows = []
    for _, r in pool.iterrows():
        sid = str(r["stock_id"])
        market = markets.get(sid)
        if market is None or sid not in last.index:
            continue
        volume = float(last.at[sid, "volume"])
        amount = float(last.at[sid, "turnover"])
        share_count = shares.get(sid)
        share_count = float(share_count) if share_count else np.nan
        price = float(r["close"])
        rows.append({
            "code": f"{sid}.{_MARKET_SUFFIX[market]}",
            "name": str(r["name"] or ""),
            "price": price,
            "change_pct": round(float(r["d1"]) * 100, 2) if pd.notna(r["d1"]) else np.nan,
            "amount": amount,
            "total_mv": price * share_count,
            "circ_mv": price * share_count,
            "pe_ratio": r["pe_ratio"],
            "pb_ratio": r["pb_ratio"],
            "volume_ratio": r["vol_ratio"],
            "turnover_rate": volume / share_count * 100,
            "industry": INDUSTRY.get(str(r["industry"]), ""),
        })
    out = pd.DataFrame(rows, columns=[
        "code", "name", "price", "change_pct", "amount", "total_mv", "circ_mv",
        "pe_ratio", "pb_ratio", "volume_ratio", "turnover_rate", "industry",
    ])
    for col in out.columns.difference(["code", "name", "industry"]):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def load_tw_snapshot(engine=None, as_of=None) -> pd.DataFrame:
    """全市場選股快照；``attrs`` 帶資料日與實際母體來源。查不到價量就 raise，讓呼叫端回報失敗。"""
    engine = engine or get_engine(read_only=True)
    as_of, px, inst, mgn, val, rev, info, idx = load(engine, as_of, include_otc_revenue=True)
    if px.empty:
        raise RuntimeError("market.price 查無資料")
    factors, _ = build(as_of, px, inst, mgn, val, rev, info, idx, 0)
    with engine.connect() as c:
        shares = dict(c.execute(text(
            "select stock_id, shares_outstanding from market.stock_info where shares_outstanding is not null"
        )).all())
    df = snapshot_frame(as_of, factors, px, shares, resolve_markets(engine, as_of, factors["stock_id"]))
    df.attrs["snapshot_source"] = "market_db"
    df.attrs["universe_source"] = "market_db"
    df.attrs["snapshot_date"] = f"{as_of:%Y-%m-%d}"
    return df


def make_daily_history_fetcher(engine=None):
    """回傳選股日線 fetcher：讀 `market.price` 並套前復權，不連外。

    復權事件只讀一次（`load_factors` 每次讀全表，候選數十檔平行時很重）；一次選股建一個。
    """
    engine = engine or get_engine(read_only=True)
    lock = threading.Lock()
    adj_cache: list[pd.DataFrame] = []

    def adjustments() -> pd.DataFrame:
        with lock:
            if not adj_cache:
                with engine.connect() as c:
                    adj_cache.append(pd.read_sql(
                        text("select stock_id, date, factor, source from market.price_adjustment"),
                        c, parse_dates=["date"],
                    ))
            return adj_cache[0]

    def fetch(code: str, *, lookback_days: int = 120, **_ignored) -> pd.DataFrame:
        sid = str(code).split(".")[0]
        rows = max(int(lookback_days), _DAILY_MIN_ROWS)
        with engine.connect() as c:
            hist = pd.read_sql(text(
                "select date, open, high, low, close, volume from market.price "
                "where stock_id = :sid and close is not null order by date desc limit :n"
            ), c, params={"sid": sid, "n": rows}, parse_dates=["date"])
        if hist.empty:
            raise RuntimeError(f"market.price 查無 {code}")
        hist = hist.sort_values("date").reset_index(drop=True)
        for col in ("open", "high", "low", "close", "volume"):
            hist[col] = pd.to_numeric(hist[col], errors="coerce")
        all_adj = adjustments()
        factor = factors_to_panel(all_adj[all_adj["stock_id"].astype(str) == sid],
                                  pd.DatetimeIndex(hist["date"]), [sid])[sid].to_numpy()
        for col in ("open", "high", "low", "close"):
            hist[col] = hist[col] * factor
        hist.attrs["daily_source"] = "market_db"
        return hist

    return fetch
