#!/usr/bin/env python3
"""台股全市場量化篩選 —— 掃 market schema，輸出候選清單交給 agent 接手查事件面。

分工刻意切死：
  - 本腳本只做「DB 算得出來的」：價量、均線、法人、融資、估值、月營收。不碰網路、不下結論。
    唯一例外：`main()` 可選擇即時抓官方公告（處置／注意股、事件日曆），可用 `--no-risk-flags`／
    `--no-events` 關閉；純函式與三支量測 loader 都不連網。即時名單只標記、不剔除，漏斗不變。
  - 事件面（美股盤後、費半、法說、財報、地緣、產業消息）DB 天生看不到——報告末尾會列出
    待查清單，由 agent 讀完輸出後補查再做判斷。

**結構性盲區（不要忘記）**：market schema 的資料截止在台股當日 13:30 收盤，而下一個交易日
開盤要反映的是那之後 ~20 小時的美股與國際盤。純 DB 篩選算出的進場價位必定是「未計入隔夜」
的錨點，agent 必須自行修正。

用法：
    uv run --env-file .env python scripts/screen_tw.py
    uv run --env-file .env python scripts/screen_tw.py --top 30 --min-turnover 1
    uv run --env-file .env python scripts/screen_tw.py --date 2026-07-24 --out /tmp/screen.md
"""

import argparse
import datetime
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_data.adjust import is_common_stock, load_factors  # noqa: E402
from market_data.db import get_engine  # noqa: E402
from market_data import events, risk_flags  # noqa: E402
from market_data.health import expected_session, session_before, sessions_after  # noqa: E402
from market_data.revenue_deadline import (  # noqa: E402
    MAX_DEADLINE_LAG_DAYS,
    apply_revenue_deadline,
    is_historical_replay,
)
from market_data.tw_official_http import md  # noqa: E402

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
# 這些產業直接連動費半／美系科技股，隔夜美股跌時是提款機——標出來讓 agent 優先查
SEMI_LINKED = {"24", "26", "28", "25", "31"}

# 月營收保鮮期，**45 個曆日、以公告日計**（不是 45 個交易日／交易列）。
# **改這裡就要同步 `scripts/measure_signal_forward.py` 的 `REVENUE_STALE_DAYS` 與
# `pit_revenue_panel`**——兩邊口徑一差，量測到的就不是會下單的那組訊號，而那份數字是
# 決策依據（獨立審查實測：視窗差 918 vs 925 個事件只有 877 重疊；交易列 vs 曆日差 44 個
# signal cell、並改變一個事件——**當時那兩個池子均值是舊固定成本口徑，已作廢**，
# 現行數字見 `docs/tw-swing-pipeline.md`）。同時公告日取**嚴格小於** as_of：月營收常在
# 盤後才上 MOPS。契約與已驗證到什麼程度見 `docs/tw-swing-pipeline.md`。
REVENUE_STALE_DAYS = 45

MIN_BARS = 66  # 算 hi60_prior（不含最近 5 天的 60 日高）需要的最少 K 棒


def exclude_otc_revenue(rev: pd.DataFrame) -> pd.DataFrame:
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
    if not SEED_CSV.exists():
        # 分不出誰是上櫃就不能宣稱池子沒變；靜默放行會讓錨點失效而沒人知道
        raise FileNotFoundError(f"{SEED_CSV} 不存在，無法排除上櫃月營收（或改帶 --include-otc-revenue）")
    otc = {sid for sid, market in _seed_market_map().items() if market == "tpex"}
    return rev[~rev["stock_id"].astype(str).isin(otc)]


_SUFFIX_MARKET = {"TW": "twse", "TWO": "tpex"}


def _seed_market_map() -> dict:
    """``{代號: "twse"|"tpex"}``，依種子檔的 ``.TW``／``.TWO``；種子檔不存在回空 dict。

    市場別只能從這裡拿：`price.market` 全為 NULL、`stock_info` 只有上市。種子檔沒有的代號
    （已下市）就是市場未知。"""
    if not SEED_CSV.exists():
        return {}
    codes = pd.read_csv(SEED_CSV, usecols=["ts_code"])["ts_code"].astype(str)
    out = {}
    for code in codes:
        sid, _, suffix = code.partition(".")
        market = _SUFFIX_MARKET.get(suffix)
        if market:
            out[sid] = market
    return out


def revenue_scope_note(include_otc_revenue: bool) -> str:
    if include_otc_revenue:
        return ("月營收含上櫃（--include-otc-revenue）——池子已不同於基準數字量測時的上市口徑，"
                "帶同一旗標重跑 measure_signal_forward.py 之前不要引用任何基準")
    return "月營收只用上市(sii)口徑（上櫃營收即使入庫也預設排除）——上櫃股的 yoy 為 null 會被篩掉"


# 估值只取 as_of 以前這個窗口內最近一天（曆日）。窗口夠涵蓋連假，又短到不會拿很舊的值當今天的
VALUATION_WINDOW_DAYS = 7
# 篩選用的「近 5 日」統計窗口（inst_5、margin_chg5 的場次數）
STAT_SESSIONS = 5

# 三大法人、融資、估值三張表上市與上櫃共表（上櫃 market='tpex'，法人自 2018-01-15 起）。
# 某檔缺法人資料時 momentum 的「近 5 日法人淨買超」是 NaN，`inst_5 > 0` 會把它靜默剔除——
# 上櫃回補完成前，上櫃個股仍會因此被排除。
LISTED_ONLY_NOTE = ("三大法人、融資、估值涵蓋上市與上櫃（上櫃法人自 2018-01-15 起）；"
                    "個股缺法人資料時 momentum 的法人篩選（近 5 日法人淨買超）會將其排除")


def _num(v, spec: str, suffix: str = "") -> str:
    """數值轉字串，NaN／None 印「—」，0 照印（0 是真實資料，不能和缺值混在一起）。"""
    return f"{v:{spec}}{suffix}" if pd.notna(v) else "—"


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


def freshness_notes(as_of, fresh: dict | None) -> list:
    """只在資料日與基準日不同時才出聲；同日不印，避免每份報告都帶一排無資訊的落後標註。"""
    if not fresh:
        return []
    notes = []
    for label, key, n_key in (("法人", "inst_last", "inst_sessions"),
                              ("融資", "margin_last", "margin_sessions")):
        last = fresh.get(key)
        if last is None:
            notes.append(f"{label}無資料")
        elif last != as_of:
            notes.append(f"{label}最新到 {last:%Y-%m-%d}（基準日 {as_of:%Y-%m-%d}），"
                         f"{STAT_SESSIONS} 日統計實際涵蓋 {fresh.get(n_key, 0)} 個場次")
    vd = fresh.get("val_date")
    if vd is None:
        notes.append(f"估值：基準日前 {VALUATION_WINDOW_DAYS} 日內無資料，PE／PB／殖利率全為「—」")
    elif vd != as_of:
        notes.append(f"估值取 {vd:%Y-%m-%d}（基準日 {as_of:%Y-%m-%d} 當日尚無，取前一個有資料的交易日）")
    return notes


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


def tag(r: pd.Series, market_d1: float) -> list:
    """給 agent 看的特徵標籤——腳本只描述事實，不做買賣判斷。"""
    t = []
    # 即時名單旗標（`apply_risk_flags`）；沒接即時名單的列沒有這欄，用 .get 才不會 KeyError
    flag = _flag(r)
    if flag in RISK_TAGS:
        t.append(RISK_TAGS[flag])
    # 事件短標（`apply_event_tags`）；同上，沒接事件日曆的列沒有這欄
    event_tags = r.get("event_tags")
    if isinstance(event_tags, list):
        t.extend(event_tags)
    if r["d1"] > market_d1 + 0.005:
        t.append("逆勢抗跌")
    if r["d1"] < -0.05:
        # 當日爆量長黑通常不會只跌一天；趨勢分數再高也要先標出來
        t.append("⚠⚠當日重挫" + ("爆量" if r["vol_ratio"] > 1.5 else ""))
    if r["d20"] > 0.10:
        t.append("動能強")
    if r["bias20"] > 0.12 or r["rsi14"] > 75:
        t.append("⚠短線過熱")
    if pd.notna(r["pe_ratio"]) and (r["pe_ratio"] > 100 or r["pe_ratio"] <= 0):
        t.append("⚠PE異常")
    if r["turnover20"] < 2e8:
        t.append("⚠量能薄")
    if pd.notna(r["dividend_yield"]) and r["dividend_yield"] > 4:
        t.append("高息")
    if pd.notna(r["pb_ratio"]) and pd.notna(r["pe_ratio"]) and r["pb_ratio"] < 1.5 and 0 < r["pe_ratio"] < 15:
        t.append("低估值")
    if pd.notna(r["yoy"]) and r["yoy"] > 20:
        t.append("營收強")
    if r["industry"] in SEMI_LINKED:
        t.append("⚠費半連動")
    if r["margin_chg5"] < -0.05:
        t.append("融資減")
    return t


def load(engine, as_of: pd.Timestamp | None, include_otc_revenue: bool = False):
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
            rev = exclude_otc_revenue(rev)
        info = pd.read_sql(text("select stock_id, name, industry from market.stock_info"), c)
        idx = pd.read_sql(text(
            "select date, close, change from market.market_index where date <= :e order by date"
        ), c, params={"e": as_of.date()}, parse_dates=["date"])
    for col in ("open", "high", "low", "close", "volume", "turnover"):
        px[col] = px[col].astype(float)

    # 前復權:price 是未還原價,不套因子的話除息/分割跳空會被當成真實漲跌。
    # 實測未套與套用的差異:候選池 44→58 檔、Top25 僅 17 檔重疊、331 檔的 20 日報酬差逾 1pp。
    piv = px.pivot(index="date", columns="stock_id", values="close")
    adj = load_factors(engine, piv.index, piv.columns)
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


def build(as_of, px, inst, mgn, val, rev, info, idx, min_turnover):
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
    if SEED_CSV.exists():  # stock_info 只有上市 ~1100 檔，上櫃名稱靠種子檔補
        seed = pd.read_csv(SEED_CSV)
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


# 「剛起漲」門檻源自早期固定成本探索；下列負面 prior 保留作為「不要重試」的證據，
# 現行現金流成本與滑價口徑的 headline 數字見 JSON measured_base_rate 與管線文件。
# 對照組值得記住，因為它們反直覺：
#   - 只看價格突破（不要求營收）是 16.4% 上 / 16.5% 下——**純技術訊號只把兩邊尾巴一起
#     放大，沒有方向性優勢**，這解釋了為什麼純技術回測怎麼調都打平大盤。
#   - 額外要求「起漲前基期平坦」反而降到 13.2%：安靜基期突然噴出多半是單日消息拉抬。
#   - 已經漲 20% 的多頭排列是 18.0% 上 / 17.4% 下，命中率最高但同樣對稱。
# 也就是說：**營收條件是唯一讓分布歪向右邊的東西**，價格條件負責把候選數壓到可審查的量。
#
# 逐筆檢視 2020-2026 的 9,884 筆訊號後,只加了一個上限（其餘全部維持,理由見下）：
#   - `vol_ratio5` 設 2.0 上限。四個分位單調遞減（1.3~1.5 命中 24.1% → >3 只有 18.1%），
#     扣成本後均值由 +9.8% 升到 +13.0%、慘賠率由 15.9% 降到 13.1%,7 年中 6 年為正不變。
#     爆量突破多半是消息噴出後的力竭。**單調性是採用它的理由**——不單調就當噪音。
#   - **突破幅度與 5 日漲幅不設上限**。逐筆看最慘的幾筆都是大突破,但那是尾巴不是分布:
#     實測突破 >30% 那格命中 24.7%／均值 +16.4%,反而優於 ≤3% 的 19.2%／+8.0%,加上限
#     會把好的一起砍掉（保留 65% 後命中降到 18.6%）。從極端值推規則在這個專案已經錯兩次。
#   - **月營收 YoY 門檻不提高**。20~30% 那格（命中 24.0%）優於 30~80%（17%）,但 >150%
#     又回升到 23.4%——U 型不單調,判定為噪音。
#   - **不要加大盤 regime 過濾**。訊號當日 0050 在 MA200 **之下**時均值 +17.4%／命中 27.5%,
#     之上只有 +7.3%／17.4%。大盤走弱還能破 60 日高的是真實個別利多,不是 beta。
BREAKOUT = {"d5": 0.05, "yoy": 20.0, "vol_ratio5": 1.3, "vol_ratio5_max": 2.0}


def funnel(df, min_turnover, strategy="breakout"):
    """過濾漏斗，回傳 (候選 df, 每層剩餘檔數)。

    `strategy="breakout"`（預設）是經前瞻報酬量測的「營收轉強 + 剛突破」；
    `strategy="momentum"` 是舊的多頭排列 + 法人買超，保留供對照——它在 13 年回測裡是
    十個因子中同曝險超額最差的一個（約 -13%；排序免疫於年化常數，量級不必當精確值），
    不要當預設。
    """
    steps = {"全市場有報價": len(df)}
    # 宇宙與 measure_signal_forward 共用 `is_common_stock`（四位數普通股、排除 ETF 00xx／TDR 91xx）：
    # 只排 ETF 時 TDR（9105、912000 都有月營收）會進 live 候選池，但 20.4% 錨點的母體裡沒有它。
    pool = df[df["stock_id"].map(is_common_stock).astype(bool) & ~df["is_tib"]].copy()
    steps["排除 ETF／TDR／非普通股與創新板"] = len(pool)
    pool = pool[pool["turnover20"] >= min_turnover]
    steps[f"日均額≥{min_turnover / 1e8:.1f}億"] = len(pool)

    if strategy == "breakout":
        pool = pool[pool["close"] > pool["hi60_prior"]]
        steps["突破 60 日高(不含近 5 日)"] = len(pool)
        pool = pool[pool["d5"] >= BREAKOUT["d5"]]
        steps[f"5 日漲幅≥{BREAKOUT['d5'] * 100:.0f}%"] = len(pool)
        pool = pool[pool["vol_ratio5"].between(BREAKOUT["vol_ratio5"],
                                               BREAKOUT["vol_ratio5_max"])]
        steps[f"5日/60日量比 {BREAKOUT['vol_ratio5']}~{BREAKOUT['vol_ratio5_max']}"] = len(pool)
        pool = pool[pool["yoy"] >= BREAKOUT["yoy"]]
        steps[f"月營收 YoY≥{BREAKOUT['yoy']:.0f}%"] = len(pool)
        # 排序只決定呈現順序,**未經前瞻驗證**（候選池本來就只有 3~5 檔,排序影響有限）。
        # 用營收強度與量能為主,不用 20 日動能——那是「已經漲多」的代理。
        r = pool.rank(pct=True)
        pool["score"] = r["yoy"] + r["vol_ratio5"] * 0.5 + r["d5"] * 0.5
    else:
        pool = pool[(pool["close"] > pool["ma20"]) & (pool["ma20"] > pool["ma60"])]
        steps["多頭排列(收盤>MA20>MA60)"] = len(pool)
        pool = pool[pool["inst_5"] > 0]
        steps["近5日法人淨買超"] = len(pool)
        # 分數：動能、籌碼、當日表現、位階（不過熱加分）、估值 —— 等權 rank，刻意保持鈍感。
        # d1 必須進分數：只看 20 日動能會把「當日爆量長黑」的高位股排到前面。
        r = pool.rank(pct=True)
        pool["score"] = (
            r["d20"] + r["inst_5"] + r["d1"] * 0.8 + (1 - r["bias20"]) * 0.5
            + _pe_score(pool["pe_ratio"]) * 0.5
        )
    return pool.sort_values("score", ascending=False), steps


def _pe_score(pe: pd.Series) -> pd.Series:
    """本益比項（低者高分）。**整欄缺值時回中性 0.5，不能讓它把整個 score 變 NaN。**

    `valuation` 走 `BWIBBU_ALL`——無日期參數的當日快照端點，官方常在盤後才發布，所以
    `date = as_of` 查得到 0 列是常態（實測 2026-07-30 18:00 仍只有 07-29）。此時原本的
    `fillna(median())` 的 median 自己就是 NaN，rank 全 NaN → **每一檔的 score 都變 NaN**，
    而 `sort_values` 把 NaN 排在後面且維持原順序（SQL 是代號序），於是 `--top N` 靜默退化成
    「代號最小的 N 檔」。實測 5 檔全是 score=None、順序 1101/1102/1216/1402/1476。
    回中性值才能保住其餘四項（動能／籌碼／當日／位階）仍然有效排序。
    """
    usable = pe.where(pe.between(0, 100))
    if not usable.notna().any():
        return pd.Series(0.5, index=pe.index)
    return 1 - usable.fillna(usable.median()).rank(pct=True)


# ---- 即時官方名單（只在 main() 抓；純函式與量測 loader 不連網） -----------------------------
# `live` 是傳給 render／to_json 的單一 dict：``{"risk": RiskResult|Skipped, "events": EventsResult|Skipped}``。
# ``live=None``（預設）時兩者輸出與接上即時名單前逐字相同。
RISK_TAGS = {risk_flags.DISPOSING: "⚠處置中", risk_flags.UPCOMING: "⚠即將處置",
             risk_flags.ATTENTION: "⚠注意股"}
SKIP_HISTORICAL = "歷史基準日（官方名單與事件只有當前快照，接到過去的基準日是錯的）"
SKIP_CALENDAR = "交易日曆（XTAI）不可用"
SKIP_STALE = "基準日 {as_of} 不是預期場次 {expected}（DB 可能尚未更新，先跑 market_data.cli daily）"
# DB 比預期場次新：交易日收盤後手動跑過 daily、但還沒到 `health.SESSION_COMPLETE_AFTER`。
# 這時當天的公告可能還沒出齊，所以同樣不抓；重跑 daily 沒有用，等過了那個時點再跑。
SKIP_AHEAD = ("基準日 {as_of} 晚於預期場次 {expected}（當日場次尚未視為完成，官方名單可能還沒出齊，"
              "過了場次完成時點再跑）")
REVENUE_RULE = "證交法 §36，每月 10 日前公告上月營收；全市場適用，不逐檔標"


@dataclass(frozen=True)
class Skipped:
    """這一半即時資料沒抓（或抓的當下就失敗）。``opted_out``：使用者自己要求不抓（``--no-*`` 或
    ``--date``）——報告只在 §0 寫一行原因，不再逐檔列「未經檢查」。``n`` 只有事件日曆用（窗口天數）。"""

    reason: str
    opted_out: bool
    n: int | None = None


@dataclass(frozen=True)
class RiskResult:
    flags: dict          # {代號: risk_flags.RiskHit}
    statuses: list
    next_session: datetime.date


@dataclass(frozen=True)
class EventsResult:
    window: events.EventWindow
    by_stock: dict       # {代號: [events.Event, ...]}
    statuses: list
    revenue: list


def _statuses(part):
    return [] if isinstance(part, Skipped) else part.statuses


def _flag(r):
    """列上的 ``risk_flag``：字串照回，缺欄／None／NaN 一律回 None（＝未經檢查）。"""
    flag = r.get("risk_flag")
    return flag if isinstance(flag, str) else None


def _warn(msg):
    # stdout 是 markdown 報告本身，警告一律走 stderr（比照 load() 的 WARN）
    print(f"**WARN: screen_tw {msg}", file=sys.stderr)


def _live_gate(as_of, date_given):
    """兩半共用的「抓不抓」閘門，回 ``(不抓的原因或 None, 下一個交易日)``。

    依序：帶 ``--date`` → 日曆不可用 → DB 晚於／早於預期場次 → 下一個交易日算不出來。"""
    if date_given:
        return SKIP_HISTORICAL, None
    expected = expected_session()
    if expected is None:
        return SKIP_CALENDAR, None
    if as_of.date() > expected:
        return SKIP_AHEAD.format(as_of=f"{as_of:%Y-%m-%d}", expected=expected), None
    if as_of.date() < expected:
        return SKIP_STALE.format(as_of=f"{as_of:%Y-%m-%d}", expected=expected), None
    nxt = sessions_after(as_of, 1)
    return (None, nxt) if nxt is not None else (SKIP_CALENDAR, None)


def _collect_one(fetch, *, reason, opted_out, what, n=None):
    """一半即時資料：``reason`` 為 None 才呼叫 ``fetch()``；例外、未抓與不可用的來源都只降級＋警告。

    回 ``fetch()`` 的結果或 `Skipped`。``opted_out`` 時不警告；``what`` 是警告裡的名稱。"""
    part = None
    if reason is None:
        try:
            part = fetch()
        except Exception as error:  # 防呆：模組本身不該拋，拋了也只降級
            reason = f"抓取時發生例外（{type(error).__name__}: {error}）"
    if part is None:
        part = Skipped(reason, opted_out, n)
        if not opted_out:
            _warn(f"{what}未查：{reason}")
    for s in _statuses(part):
        if not s.ok:
            _warn(f"{what}：{s.name} 不可用：{s.note}")
    return part


def collect_live(as_of, date_given, risk_on=True, events_on=True, event_days=5):
    """main() 唯一決定「抓不抓」的地方：沒帶 ``--date`` 且基準日 == `expected_session()` 才抓。

    任何失敗都只降級成 `Skipped` 或來源狀態，不擋報告。名單依序抓（上櫃處置依賴上櫃注意），
    事件日曆的四個來源在 `events.upcoming` 內並行。"""
    t0 = time.monotonic()
    gate, nxt = _live_gate(as_of, date_given) if (risk_on or events_on) else (None, None)

    def fetch_risk():
        flags, statuses = risk_flags.fetch_risk_flags(as_of.date(), nxt)
        return RiskResult(flags, statuses, nxt)

    risk = _collect_one(fetch_risk, reason=gate if risk_on else "--no-risk-flags",
                        opted_out=not risk_on or date_given, what="處置／注意股名單")
    t1 = time.monotonic()

    reason = gate if events_on else "--no-events"
    window = None
    if reason is None:
        end, prev = sessions_after(as_of, event_days), session_before(as_of)
        if end is None or prev is None:
            reason = SKIP_CALENDAR
        else:
            window = events.EventWindow(nxt, end, prev, event_days)

    def fetch_events():
        by_stock, statuses = events.upcoming(window)
        return EventsResult(window, by_stock, statuses, events.revenue_deadlines(window))

    ev = _collect_one(fetch_events, reason=reason, opted_out=not events_on or date_given,
                      what="事件日曆", n=event_days)
    t2 = time.monotonic()
    if not (isinstance(risk, Skipped) and isinstance(ev, Skipped)):
        print(f"[screen_tw] 即時名單 {t1 - t0:.1f}s、事件日曆 {t2 - t1:.1f}s", file=sys.stderr)
    return {"risk": risk, "events": ev}


def apply_live(df, live, market_map=None):
    """main() 用：依序套上 `apply_risk_flags` 與 `apply_event_tags`（都不剔除任何列）。"""
    market_map = _seed_market_map() if market_map is None else market_map
    df = apply_risk_flags(df, live["risk"], market_map)
    return apply_event_tags(df, live["events"])


def apply_risk_flags(df, risk, market_map=None):
    """在候選 df 加 ``market``／``risk_flag``／``risk_flag_detail`` 三欄（不剔除任何列）。

    ``risk_flag``：在可用名單裡 → 處置中／即將處置／注意股；該市場兩份名單都可用而不在名單
    → ``""``（查過、乾淨）；名單不可用、沒查或市場未知 → ``None``（**未經檢查，不代表沒有**）。
    市場別取種子檔（`_seed_market_map`），不用 `price.market`——那欄全為 NULL。"""
    df = df.copy()
    market_map = _seed_market_map() if market_map is None else market_map
    df["market"] = pd.Series([market_map.get(str(s)) for s in df["stock_id"]], index=df.index,
                             dtype=object)
    # 沒抓（Skipped）時沒有 statuses，checked 自然是空集合：每一列都是未經檢查
    flags = {} if isinstance(risk, Skipped) else risk.flags
    checked = risk_flags.checked_markets(_statuses(risk))
    hits = [_tristate(flags.get(str(sid)), market, checked, risk_flags.CLEAN)
            for sid, market in zip(df["stock_id"], df["market"])]
    for col, key in (("risk_flag", "flag"), ("risk_flag_detail", "detail")):
        df[col] = pd.Series([None if h is None else getattr(h, key) for h in hits], index=df.index,
                            dtype=object)
    return df


def _event_tags(found):
    """一檔的事件短標：每種事件只標最早那一次（論壇不標，見 `events.Event.short_tag`）。"""
    first = {}
    for e in sorted(found, key=lambda e: e.start):
        if e.short_tag() and e.kind not in first:
            first[e.kind] = e.short_tag()
    return list(first.values())


def apply_event_tags(df, ev):
    """加 ``event_tags`` 欄（📅法說10/23 這類短標的 list），由 `tag` 併入標籤欄與 JSON ``tags``。

    沒抓事件日曆時不加欄，`tag` 照舊；沒命中的列是空 list（標籤不代表查過，查過與否看 JSON ``events``）。"""
    if isinstance(ev, Skipped):
        return df
    df = df.copy()
    df["event_tags"] = pd.Series([_event_tags(ev.by_stock.get(str(s), [])) for s in df["stock_id"]],
                                 index=df.index, dtype=object)
    return df


def _tristate(hit, market, checked, clean):
    """逐檔三態：有命中 → ``hit``；該檔市場的來源都可用 → ``clean``（查過、沒有）；
    其餘（沒抓、來源失敗、市場未知）→ None（**未經檢查，不代表沒有**）。"""
    if hit:
        return hit
    return clean if isinstance(market, str) and market in checked else None


def _risk_status_line(risk):
    if isinstance(risk, Skipped):
        return f"- 處置／注意股名單：未查（{risk.reason}）"
    parts = [f"{s.name} {'✓' if s.ok else '✗'}" + (f"（{s.note}）" if s.note else "")
             for s in risk.statuses]
    return "- 處置／注意股名單：" + "、".join(parts)


def _render_risk(w, risk, top_rows):
    hits = [r for _, r in top_rows.iterrows() if _flag(r)]
    unchecked = [r for _, r in top_rows.iterrows() if _flag(r) is None]
    if hits:
        w(f"### ⚠ 處置／注意股（{len(hits)} 檔；處置期間分盤撮合／預收款券，進出場可成交性需自行評估）")
        for r in hits:
            w(f"- {r['stock_id']} {r['name']}（{r['risk_flag_detail']}）")
        w("")
    # 使用者自己關掉（--no-risk-flags／--date）時 §0 那行「未查（原因）」就夠了，不逐檔列
    if unchecked and not (isinstance(risk, Skipped) and risk.opted_out):
        if isinstance(risk, Skipped):
            why = risk.reason
        else:
            why = "、".join(f"{s.name}（{s.note}）" for s in risk.statuses if not s.ok) or "市場別未知"
        w(f"### ⚠ 處置／注意股名單未取得：{why}")
        w("　以下候選未經檢查，不代表沒有：" + "、".join(
            f"{r['stock_id']} {r['name']}" for r in unchecked))
        w(f"　人工查詢：上市 {risk_flags.MANUAL_LINKS['twse']}　上櫃 {risk_flags.MANUAL_LINKS['tpex']}\n")


def _render_events(w, ev, top_rows, top):
    win = ev.window
    w(f"### 事件日曆（未來 {win.n} 個交易日，{md(win.start)}~{md(win.end)}）")
    any_hit = False
    for _, r in top_rows.iterrows():
        found = ev.by_stock.get(str(r["stock_id"]))
        if found:
            any_hit = True
            w(f"- **{r['stock_id']} {r['name']}**：" + "　".join(e.label() for e in found))
    if not any(s.ok for s in ev.statuses):
        w("- 事件日曆來源全部不可用（未經檢查，不代表沒有事件，見下方來源狀態）")
    elif not any_hit:
        # 不能寫「無事件」：MOPS 證明不了新鮮，失敗的來源也看不到
        w(f"- 前 {top} 名在可用來源中未見事件（未列不代表沒有，見下方來源狀態）")
    for d in ev.revenue:
        w(f"- 月營收：窗口與 {d:%m}/01~{d:%m}/10 公告期重疊（期限 {md(d)}；{REVENUE_RULE}）")
    for s in ev.statuses:
        w(f"- 來源：{s.name} {s.label}" + (f"：{s.note}" if s.note else ""))
    w("")


def _event_question(ev, r):
    found = [e for e in ev.by_stock.get(str(r["stock_id"]), []) if e.kind != events.FORUM]
    if not found:
        return None
    kinds = "／".join(dict.fromkeys(e.kind for e in found))
    days = "、".join(dict.fromkeys(md(e.start) for e in found))
    return f"{ev.window.n} 個交易日內有{kinds}（{days}），事件前是否降部位？"


def render(as_of, df, pool, steps, market_d1, idx, top, min_turnover, include_otc_revenue=False,
           freshness=None, live=None):
    L = []
    w = L.append
    w(f"# 台股量化篩選 — {as_of:%Y-%m-%d}（收盤後）\n")
    w("> 本報告只含 DB 算得出的量價／籌碼／估值。**事件面未涵蓋**，見文末待查清單。\n")

    w("## 0. 資料新鮮度\n")
    w(f"- 基準日：**{as_of:%Y-%m-%d}**，當日有報價 **{len(df)}** 檔（含 ETF {int(df['is_etf'].sum())} 檔）")
    if len(idx):
        last = idx.iloc[-1]
        w(f"- 加權指數：**{last['close']:,.2f}**（{last['change']:+,.2f}，{market_d1 * 100:+.2f}%）")
    w(f"- 估值表覆蓋 {int(df['pe_ratio'].notna().sum())} 檔、月營收覆蓋 {int(df['yoy'].notna().sum())} 檔"
      f"（{revenue_scope_note(include_otc_revenue)}）")
    vd = (freshness or {}).get("val_date")
    if vd is not None:
        w(f"- 估值日：**{vd:%Y-%m-%d}**")
    w(f"- 範圍：{LISTED_ONLY_NOTE}")
    for n in freshness_notes(as_of, freshness):
        w(f"- ⚠ {n}")
    if live is not None:
        w(_risk_status_line(live["risk"]))
    w("")

    ind = df[~df["is_etf"]]
    w("## 1. 市場體檢\n")
    w(f"- 站上 MA20：**{(ind['close'] > ind['ma20']).mean() * 100:.1f}%**　|　"
      f"站上 MA60：**{(ind['close'] > ind['ma60']).mean() * 100:.1f}%**")
    w(f"- 當日上漲 {int((ind['d1'] > 0).sum())} 家 / 下跌 {int((ind['d1'] < 0).sum())} 家，"
      f"漲跌中位數 {ind['d1'].median() * 100:+.2f}%")
    w(f"- RSI14 中位數 **{ind['rsi14'].median():.1f}**　|　距 60 日高點中位數 "
      f"**{ind['from_hi60'].median() * 100:.1f}%**")
    w(f"- 近 20 日報酬中位數 {ind['d20'].median() * 100:+.2f}%　|　近 60 日 {ind['d60'].median() * 100:+.2f}%\n")

    w("## 2. 過濾漏斗\n")
    for k, v in steps.items():
        w(f"- {k} → **{v}** 檔")
    w("")

    w(f"## 3. 候選清單（前 {min(top, len(pool))} 名 / 共 {len(pool)} 檔通過）\n")
    w("| # | 代碼 | 名稱 | 產業 | 收盤 | 突破% | 量比 | 日%| 5日% | 20日% | 乖離20 | RSI | 日均額 | 法人5日 | 連買 | PE | PB | 殖利% | 營收YoY | 標籤 |")
    w("|--:|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|")
    for i, (_, r) in enumerate(pool.head(top).iterrows(), 1):
        # 這三格先算好再進 f-string。原本寫成同引號的巢狀 f-string（PEP 701），
        # **只有 Python 3.12+ 剖析得動**；CI 跑 3.11（`ci.yml` 的 `python-version`），
        # 本機 venv 是 3.12（AGENTS.md §10），所以這個語法錯誤在本機永遠不會顯形。
        break_pct = f"{r['break_pct'] * 100:+.1f}" if pd.notna(r['break_pct']) else '—'
        vol_ratio5 = f"{r['vol_ratio5']:.1f}" if pd.notna(r['vol_ratio5']) else '—'
        yoy = f"{r['yoy']:+.1f}" if pd.notna(r['yoy']) else '—'
        w(f"| {i} | {r['stock_id']} | {r['name']} | {INDUSTRY.get(r['industry'], '—')} | "
          f"{r['close']:.2f} | "
          f"{break_pct} | "
          f"{vol_ratio5} | "
          f"{r['d1'] * 100:+.1f} | {r['d5'] * 100:+.1f} | {r['d20'] * 100:+.1f} | "
          f"{r['bias20'] * 100:+.1f}% | {r['rsi14']:.0f} | {r['turnover20'] / 1e8:.1f}億 | "
          f"{_num(r['inst_5'] / 1000, '+,.0f', '張')} | {_num(r['inst_streak'], '.0f', '天')} | "
          f"{r['pe_ratio'] if pd.notna(r['pe_ratio']) else '—'} | {r['pb_ratio'] if pd.notna(r['pb_ratio']) else '—'} | "
          f"{r['dividend_yield'] if pd.notna(r['dividend_yield']) else '—'} | "
          f"{yoy} | {' '.join(tag(r, market_d1)) or '—'} |")
    w("")

    w("## 4. 參考價位（以基準日收盤計算，**未計入隔夜盤**）\n")
    w("| 代碼 | 名稱 | 收盤 | MA5 | MA10 | MA20 | ATR% | 60日高 | 停損參考(MA20-1%) |")
    w("|---|---|--:|--:|--:|--:|--:|--:|--:|")
    for _, r in pool.head(top).iterrows():
        hi60 = r["close"] / (1 + r["from_hi60"]) if r["from_hi60"] else r["close"]
        w(f"| {r['stock_id']} | {r['name']} | {r['close']:.2f} | {r['ma5']:.2f} | {r['ma10']:.2f} | "
          f"{r['ma20']:.2f} | {r['atr_pct'] * 100:.1f}% | {hi60:.2f} | {r['ma20'] * 0.99:.2f} |")
    w("")

    w("## 5. 待查清單（DB 看不到，agent 接手）\n")
    w(f"**基準日盲區**：本報告資料截止 {as_of:%m/%d} 13:30 收盤。下個交易日開盤要反映的是那之後的"
      "美股與國際盤，上表所有價位都是未計入隔夜的錨點。\n")
    w("### 必查（決定要不要進場）")
    w("1. **美股最近一盤收盤**：那指／費半／道瓊，以及台指期夜盤點數 → 換算次日開盤預期缺口")
    ev = None if live is None else live["events"]
    fetched = ev is not None and not isinstance(ev, Skipped)
    days = 5 if ev is None else ev.window.n if fetched else ev.n
    reminder = f"2. **未來 {days} 個交易日的事件**：FOMC、美國科技巨頭財報"
    if fetched and any(s.ok and s.proven for s in ev.statuses):
        w(reminder + "仍需自行查；台廠法說／除權息／月營收期限見下方「事件日曆」（未列不代表沒有）")
    else:
        # 沒附、全失敗、或只剩未證明新鮮的來源（MOPS）：事件日曆撐不起「改看下方」，人工待查項目原樣保留
        if ev is None:
            suffix = ""
        elif not fetched:
            suffix = f"（本報告未附事件日曆：{ev.reason}）"
        elif any(s.ok for s in ev.statuses):
            suffix = "（事件日曆只有未證明新鮮的來源可用）"
        else:
            suffix = "（事件日曆來源全部不可用）"
        w(reminder + "、台廠法說、月營收公布日、除權息" + suffix)
    w("3. **大盤位階**：加權指數與季線／半年線的關係（本 DB 的 market_index 歷史過淺，需外部確認）")
    w("4. **國際變數**：油價、匯率、地緣衝突\n")
    semi = pool.head(top)[pool.head(top)["industry"].isin(SEMI_LINKED)]
    if len(semi):
        w(f"### ⚠ 費半連動標的（{len(semi)} 檔，隔夜美股半導體走弱時優先剔除）")
        w("　" + "、".join(f"{r['stock_id']} {r['name']}" for _, r in semi.iterrows()) + "\n")
    if live is not None:
        _render_risk(w, live["risk"], pool.head(top))
    thin = pool.head(top)[pool.head(top)["turnover20"] < 2e8]
    if len(thin):
        w(f"### ⚠ 量能偏薄（{len(thin)} 檔，日均額 < 2 億，出場流動性需自行評估）")
        w("　" + "、".join(
            f"{r['stock_id']} {r['name']}（{r['turnover20'] / 1e8:.2f}億）"
            for _, r in thin.iterrows()
        ) + "\n")
    if fetched:
        _render_events(w, ev, pool.head(top), top)
    w("### 逐檔查（前 5 名）")
    for _, r in pool.head(5).iterrows():
        q = [f"近 20 日 {r['d20'] * 100:+.1f}% 的題材是什麼？是否已被消化？"]
        if r["inst_streak"] >= 3:
            q.append(f"法人連買 {r['inst_streak']:.0f} 天——主動布局還是被動調整（ETF 成分／指數調整／除權息）？")
        if r["bias20"] > 0.12 or r["rsi14"] > 75:
            q.append("已過熱，有無新增利多支撐追價？")
        if r["d1"] < -0.05:
            q.append("當日重挫的原因？是個股利空還是跟隨大盤？")
        if pd.notna(r["yoy"]) and r["yoy"] < 0:
            q.append(f"月營收 YoY {r['yoy']:+.1f}% 為負，股價上漲的依據是什麼？")
        if fetched:
            event_q = _event_question(ev, r)
            if event_q:
                q.append(event_q)
        w(f"- **{r['stock_id']} {r['name']}**：" + "　".join(q))
    w("")
    return "\n".join(L)


def to_json(as_of, pool, steps, market_d1, strategy, top, include_otc_revenue=False,
            freshness=None, live=None):
    """給 agent 消費的候選資料。markdown 是給人讀的,agent 要的是可程式化的欄位 +
    「為什麼入選」——後者決定它該去查什麼,不然它只能重新猜一遍篩選邏輯。"""
    ev_checked = None if live is None else _events_checked(live["events"])
    cols = ["stock_id", "name", "industry", "close", "break_pct", "vol_ratio5", "d1", "d5",
            "d20", "d60", "bias20", "rsi14", "atr_pct", "pos20", "from_hi60", "turnover20",
            "inst_5", "inst_20", "inst_streak", "margin_chg5", "pe_ratio", "pb_ratio",
            "dividend_yield", "yoy", "mom", "ma5", "ma10", "ma20", "ma60", "hi60_prior"]
    out = []
    for _, r in pool.head(top).iterrows():
        rec = {c: (None if c in r and pd.isna(r[c]) else r.get(c)) for c in cols}
        rec["industry_name"] = INDUSTRY.get(r["industry"], None)
        rec["semi_linked"] = r["industry"] in SEMI_LINKED
        rec["tags"] = tag(r, market_d1)
        rec["why_selected"] = {
            "breakout": (f"突破不含近 5 日的 60 日高 {r['break_pct'] * 100:+.1f}%、"
                         f"5 日漲幅 {r['d5'] * 100:+.1f}%、5/60 日量比 {r['vol_ratio5']:.1f}、"
                         f"月營收 YoY {r['yoy']:+.1f}%"),
            "momentum": (f"多頭排列、近 5 日法人淨買 {r['inst_5'] / 1000:+,.0f} 張、"
                         f"20 日 {r['d20'] * 100:+.1f}%"),
        }[strategy]
        if live is not None:
            _live_rec(rec, r, live["events"], ev_checked)
        out.append(rec)
    result = {
        "as_of": f"{as_of:%Y-%m-%d}",
        "strategy": strategy,
        "thresholds": BREAKOUT if strategy == "breakout" else None,
        "market_d1": market_d1,
        "funnel": steps,
        "pool_size": len(pool),
        # 給 agent 的作業基準。**這是一份存活偏誤未修正的樣本**——`monthly_revenue` 的覆蓋
        # 100% 條件化於「今天仍上市」（實測:2020 後停止交易的 70 檔普通股,0 檔有 2020 後
        # 月營收、0 檔在 current stock_info）,所以後來下市的公司結構上不可能進到候選池,
        # 負尾被系統性移除。下面的數字是上界,不是可配置的預期報酬。
        "measured_base_rate": {
            "sample": "2020-01 ~ 2026-04（結果資料至 2026-07-24）、974 個事件"
                      "（同股相隔 >60 交易日才算新事件）。"
                      "事件仍非獨立——不同個股集中在相同行情與產業循環。",
            "win_rate": 0.516, "breakeven_win_rate": 0.313, "payoff_ratio": 2.20,
            "mean_60d_net_of_cost": 0.1007, "median_60d_net_of_cost": 0.0113,
            "mean_ci95_block_bootstrap": [0.0322, 0.1693],
            "mean_excl_28_events_over_100pct": 0.0584,
            "top12pct_events_share_of_total_pnl": 1.07,
            # p_close60_up_30pct 2026-10-26 重測為 0.204，要與 verify_swing_decisions.BASE_RATE 同步
            "p_close60_up_30pct": 0.204, "p_close60_down_20pct": 0.149,
            "worst_single": -0.54,
            "matched_baseline_same_pool_with_revenue": {
                "mean": 0.0469, "win_rate": 0.486, "p_close60_up_30pct": 0.120},
            "positive_years": "6/7（僅 2022 為 -3.3%；2024 +0.9%）",
            "survivorship_bias_bound": -0.0032,
            "note": "勝率 51.6% 高於損益兩平 31.3%，**池子本身即正期望值**——agent 的目標"
                    "不是讓候選及格，而是挑右尾、避左尾、避主題集中。存活偏誤已量化:"
                    "補不回月營收的 82 檔下市公司只產生 15 個符合價格條件的事件、均值 -7.23%,"
                    "最差 11 筆併入讓均值由 +9.93% 變 +9.60%（此段與 survivorship_bias_bound 為重測前的數字，--survivorship-bound 未重跑）。排序尚未觀察到優勢。",
        } if strategy == "breakout" and not include_otc_revenue else None,
        "candidates": out,
        "blind_spots": [
            "資料截止基準日 13:30 收盤，未含隔夜美股／台指期夜盤",
            revenue_scope_note(include_otc_revenue),
            LISTED_ONLY_NOTE,
            "產業別僅上市有值",
            *freshness_notes(as_of, freshness),
        ],
    }
    if live is not None:
        _live_json(result, live)
    return result


def _events_checked(ev):
    """``(查過的市場集合, {市場: [查過的類別]})``，由 `to_json` 算一次給每一列用。"""
    statuses = _statuses(ev)
    return events.checked_markets(statuses), events.checked_categories(statuses)


def _live_rec(rec, r, ev, ev_checked):
    """逐檔的即時欄位。``None`` 一律代表「未經檢查」，``""``／``[]`` 才是查過沒有。

    ``events`` 比照 ``risk_flag`` 逐市場判（`_tristate`）：有命中 → 命中清單（含未證明新鮮的 MOPS
    命中）；沒命中且該檔市場（取 `apply_risk_flags` 加上的 ``market`` 欄）的每個事件來源都「可用且
    新鮮度已證明」→ ``[]``；其餘（沒抓、該市場任一來源失敗或未證明新鮮、市場未知）→ ``None``。
    MOPS 永遠未證明新鮮，所以目前 ``events`` 實務上只會是命中清單或 ``None``；哪些類別確實查過
    看 ``events_checked``（例如 ``["除權息"]``；沒抓或市場未知為 ``[]``）。"""
    rec["risk_flag"] = _flag(r)
    detail = r.get("risk_flag_detail")
    rec["risk_flag_detail"] = detail if isinstance(detail, str) else None
    found = [] if isinstance(ev, Skipped) else ev.by_stock.get(str(r["stock_id"]), [])
    markets, categories = ev_checked
    market = r.get("market")
    rec["events"] = _tristate([e.to_dict() for e in found], market, markets, [])
    rec["events_checked"] = list(categories.get(market, [])) if isinstance(market, str) else []


def _live_json(result, live):
    risk, ev = live["risk"], live["events"]
    blind = result["blind_spots"]
    risk_skipped = isinstance(risk, Skipped)
    result["risk_flag_skipped"] = risk.reason if risk_skipped else None
    result["risk_flag_sources"] = [s.to_dict() for s in _statuses(risk)]
    result["next_session"] = None if risk_skipped else risk.next_session.isoformat()
    if risk_skipped:
        blind.append(f"處置／注意股：未查（{risk.reason}），候選的 risk_flag 為 null＝未經檢查")
    for s in _statuses(risk):
        if not s.ok:
            blind.append(f"處置／注意股：{s.name} 不可用（{s.note}），該市場不在名單上的候選未經檢查")
    ev_skipped = isinstance(ev, Skipped)
    result["event_skipped"] = ev.reason if ev_skipped else None
    result["event_window"] = (None if ev_skipped else
                              {"n": ev.window.n, "start": ev.window.start.isoformat(),
                               "end": ev.window.end.isoformat()})
    result["event_sources"] = [s.to_dict() for s in _statuses(ev)]
    # 純日期推算，但沒抓事件日曆時並沒有算過窗口，維持「null＝未經檢查」
    result["revenue_deadlines"] = None if ev_skipped else [d.isoformat() for d in ev.revenue]
    if ev_skipped:
        blind.append(f"事件日曆：未附（{ev.reason}），候選的 events 為 null＝未經檢查")
    else:
        blind.append("事件日曆只含台廠法說／除權息預告／月營收期限；FOMC、美股財報仍需自行查")
    for s in _statuses(ev):
        if not s.ok:
            blind.append(f"事件日曆：{s.name} 不可用（{s.note}），該市場沒有命中的候選 events 為 null"
                         "＝未經檢查，未列不代表沒有")
        elif not s.proven:
            blind.append(f"事件日曆：{s.name} 可用但未證明新鮮（{s.note}），不算查過：該市場沒有命中的"
                         "候選 events 為 null，查過的類別見 events_checked")


def main(argv=None):
    p = argparse.ArgumentParser(description="台股全市場量化篩選（market schema）")
    p.add_argument("--top", type=int, default=25, help="輸出前 N 名候選（預設 25）")
    p.add_argument("--min-turnover", type=float, default=2.0, help="日均成交額門檻，單位億（預設 2）")
    p.add_argument("--date", default=None, help="基準日 YYYY-MM-DD（預設 DB 最新交易日）")
    p.add_argument("--out", default=None, help="輸出路徑（預設 .claude/reviews/screen-tw-<date>.md）")
    p.add_argument("--strategy", default="breakout", choices=["breakout", "momentum"],
                   help="breakout=營收轉強+剛突破（經前瞻報酬量測）；momentum=舊的多頭排列"
                        "+法人買超（13 年回測十個因子裡最差，僅供對照）")
    p.add_argument("--json", default=None, help="另存 JSON 給 agent 消費")
    p.add_argument("--include-otc-revenue", action="store_true",
                   help="月營收條件放入上櫃（預設只用上市口徑；放入後基準數字失效，需先帶同一旗標重跑 measure_signal_forward.py）")
    p.add_argument("--no-risk-flags", action="store_true",
                   help="不即時抓處置／注意股名單（預設：基準日為預期場次時抓，只標記不剔除）")
    p.add_argument("--no-events", action="store_true",
                   help="不即時抓事件日曆（法說會、除權息預告；預設：基準日為預期場次時抓）")
    p.add_argument("--event-days", type=int, default=5,
                   help="事件日曆涵蓋基準日之後幾個交易日（預設 5）")
    a = p.parse_args(argv)
    if a.event_days < 1:
        p.error("--event-days 必須 ≥ 1")

    engine = get_engine()
    as_of, px, inst, mgn, val, rev, info, idx = load(engine, a.date, a.include_otc_revenue)
    live = collect_live(as_of, a.date is not None, not a.no_risk_flags, not a.no_events,
                        a.event_days)
    df, market_d1 = build(as_of, px, inst, mgn, val, rev, info, idx, a.min_turnover * 1e8)
    df = apply_live(df, live)
    pool, steps = funnel(df, a.min_turnover * 1e8, a.strategy)
    fresh = data_freshness(px, inst, mgn, val)
    md = render(as_of, df, pool, steps, market_d1, idx, a.top, a.min_turnover,
                a.include_otc_revenue, fresh, live)

    out = Path(a.out) if a.out else REPO / ".claude" / "reviews" / f"screen-tw-{as_of:%Y%m%d}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    if a.json:
        jp = Path(a.json)
        jp.parent.mkdir(parents=True, exist_ok=True)
        jp.write_text(json.dumps(to_json(as_of, pool, steps, market_d1, a.strategy, a.top,
                                         a.include_otc_revenue, fresh, live),
                                 ensure_ascii=False, indent=1, default=float), encoding="utf-8")
        print(f"[screen_tw] JSON 已寫入 {jp}", file=sys.stderr)
    print(md)
    print(f"\n[screen_tw] 已寫入 {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
