#!/usr/bin/env python3
"""台股全市場量化篩選 —— 掃 market schema，輸出候選清單交給 agent 接手查事件面。

分工刻意切死：
  - 本腳本只做「DB 算得出來的」：價量、均線、法人、融資、估值、月營收。不碰網路、不下結論。
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
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_data.adjust import load_factors  # noqa: E402
from market_data.db import get_engine  # noqa: E402

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
    但 `docs/tw-swing-pipeline.md` 的每一個基準數字（974 個事件、`confidence` 錨點 20.2%、
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
    codes = pd.read_csv(SEED_CSV, usecols=["ts_code"])["ts_code"].astype(str)
    otc = set(codes[codes.str.endswith(".TWO")].str.split(".").str[0])
    return rev[~rev["stock_id"].astype(str).isin(otc)]


def revenue_scope_note(include_otc_revenue: bool) -> str:
    if include_otc_revenue:
        return ("月營收含上櫃（--include-otc-revenue）——池子已不同於基準數字量測時的上市口徑，"
                "帶同一旗標重跑 measure_signal_forward.py 之前不要引用任何基準")
    return "月營收只用上市(sii)口徑（上櫃營收即使入庫也預設排除）——上櫃股的 yoy 為 null 會被篩掉"


# 估值只取 as_of 以前這個窗口內最近一天（曆日）。窗口夠涵蓋連假，又短到不會拿很舊的值當今天的
VALUATION_WINDOW_DAYS = 7
# 篩選用的「近 5 日」統計窗口（inst_5、margin_chg5 的場次數）
STAT_SESSIONS = 5

# 三大法人、融資、估值三張表只收上市（上櫃無本地個股歷史）。momentum 的「近 5 日法人淨買超」
# 對上櫃個股是 NaN，`inst_5 > 0` 因此把上櫃全數靜默剔除；融資減標籤對上櫃永不觸發。
LISTED_ONLY_NOTE = ("三大法人、融資、估值只涵蓋上市（上櫃無本地資料）；"
                    "momentum 的法人篩選（近 5 日法人淨買超）等同排除上櫃")


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
    # 漲逾 30% 的機率是 20.2%，同池有月營收的基準率只有 12.0%。
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
    少一個上界就是直接讀到未來資料（月營收與大盤指數都踩過）。
    """
    with engine.connect() as c:
        latest = c.execute(text("select max(date) from market.price")).scalar()
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
            "select stock_id, date, pe_ratio, pb_ratio, dividend_yield from market.valuation "
            "where date <= :d and date > :lo"
        ), c, params={"d": as_of.date(),
                      "lo": (as_of - pd.Timedelta(days=VALUATION_WINDOW_DAYS)).date()},
            parse_dates=["date"])
        if len(val):
            val = val[val["date"] == val["date"].max()]
        # 用 announce_date 設上界:營收在次月才公布,以 revenue_month 篩會提前看到未發布的數字
        rev = pd.read_sql(text(
            "select stock_id, revenue_month, yoy, mom from market.monthly_revenue "
            "where announce_date >= :s and announce_date < :e"
        ), c, params={"s": (as_of - pd.Timedelta(days=REVENUE_STALE_DAYS)).date(),
                      "e": as_of.date()},
            parse_dates=["revenue_month"])
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
    pool = df[~df["is_etf"] & ~df["is_tib"]].copy()
    steps["排除 ETF 與創新板"] = len(pool)
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


def render(as_of, df, pool, steps, market_d1, idx, top, min_turnover, include_otc_revenue=False,
           freshness=None):
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
    w("2. **未來 5 個交易日的事件**：FOMC、美國科技巨頭財報、台廠法說、月營收公布日、除權息")
    w("3. **大盤位階**：加權指數與季線／半年線的關係（本 DB 的 market_index 歷史過淺，需外部確認）")
    w("4. **國際變數**：油價、匯率、地緣衝突\n")
    semi = pool.head(top)[pool.head(top)["industry"].isin(SEMI_LINKED)]
    if len(semi):
        w(f"### ⚠ 費半連動標的（{len(semi)} 檔，隔夜美股半導體走弱時優先剔除）")
        w("　" + "、".join(f"{r['stock_id']} {r['name']}" for _, r in semi.iterrows()) + "\n")
    thin = pool.head(top)[pool.head(top)["turnover20"] < 2e8]
    if len(thin):
        w(f"### ⚠ 量能偏薄（{len(thin)} 檔，日均額 < 2 億，出場流動性需自行評估）")
        w("　" + "、".join(
            f"{r['stock_id']} {r['name']}（{r['turnover20'] / 1e8:.2f}億）"
            for _, r in thin.iterrows()
        ) + "\n")
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
        w(f"- **{r['stock_id']} {r['name']}**：" + "　".join(q))
    w("")
    return "\n".join(L)


def to_json(as_of, pool, steps, market_d1, strategy, top, include_otc_revenue=False,
            freshness=None):
    """給 agent 消費的候選資料。markdown 是給人讀的,agent 要的是可程式化的欄位 +
    「為什麼入選」——後者決定它該去查什麼,不然它只能重新猜一遍篩選邏輯。"""
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
        out.append(rec)
    return {
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
            "win_rate": 0.513, "breakeven_win_rate": 0.312, "payoff_ratio": 2.20,
            "mean_60d_net_of_cost": 0.0993, "median_60d_net_of_cost": 0.0083,
            "mean_ci95_block_bootstrap": [0.0314, 0.1669],
            "mean_excl_28_events_over_100pct": 0.0569,
            "top12pct_events_share_of_total_pnl": 1.08,
            "p_close60_up_30pct": 0.202, "p_close60_down_20pct": 0.148,
            "worst_single": -0.54,
            "matched_baseline_same_pool_with_revenue": {
                "mean": 0.0467, "win_rate": 0.485, "p_close60_up_30pct": 0.120},
            "positive_years": "6/7（僅 2022 為 -3.3%；2024 +0.8%）",
            "survivorship_bias_bound": -0.0032,
            "note": "勝率 51.3% 高於損益兩平 31.2%，**池子本身即正期望值**——agent 的目標"
                    "不是讓候選及格，而是挑右尾、避左尾、避主題集中。存活偏誤已量化:"
                    "補不回月營收的 82 檔下市公司只產生 15 個符合價格條件的事件、均值 -7.23%,"
                    "最差 11 筆併入讓均值由 +9.93% 變 +9.60%。排序尚未觀察到優勢。",
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
    a = p.parse_args(argv)

    engine = get_engine()
    as_of, px, inst, mgn, val, rev, info, idx = load(engine, a.date, a.include_otc_revenue)
    df, market_d1 = build(as_of, px, inst, mgn, val, rev, info, idx, a.min_turnover * 1e8)
    pool, steps = funnel(df, a.min_turnover * 1e8, a.strategy)
    fresh = data_freshness(px, inst, mgn, val)
    md = render(as_of, df, pool, steps, market_d1, idx, a.top, a.min_turnover,
                a.include_otc_revenue, fresh)

    out = Path(a.out) if a.out else REPO / ".claude" / "reviews" / f"screen-tw-{as_of:%Y%m%d}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    if a.json:
        jp = Path(a.json)
        jp.parent.mkdir(parents=True, exist_ok=True)
        jp.write_text(json.dumps(to_json(as_of, pool, steps, market_d1, a.strategy, a.top,
                                         a.include_otc_revenue, fresh),
                                 ensure_ascii=False, indent=1, default=float), encoding="utf-8")
        print(f"[screen_tw] JSON 已寫入 {jp}", file=sys.stderr)
    print(md)
    print(f"\n[screen_tw] 已寫入 {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
