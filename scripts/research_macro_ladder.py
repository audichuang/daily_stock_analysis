#!/usr/bin/env python3
"""總經模型階梯：只看美股是不是片面、多看總經有沒有增量（唯讀研究）。

對應 final-decision 第 4 項（`journal/experiment-registry.jsonl` 的 `macro-ladder` family）。
回答的問題：在 07:30 資訊集下，台股開盤缺口（CO）、盤中（OC）、1～5 日報酬，
加進總經變數相對「只看美股＋夜盤」有沒有**樣本外**增量。

資料（全部唯讀，不寫任何 DB）：
  - 台股：`market.market_index` 的 TAIEX（2010 起，含 open）、`market.price`＋`market.price_adjustment`
    的 0050（交易腿）、2330（ADR 溢價）、`market.stock_info` 電子／非電子（G2-10）。
    連線後 `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY`，並加連線層 `default_transaction_read_only`。
  - 外部長歷史：yfinance（^SOX ^NDX ^IXIC ^GSPC TSM CL=F BZ=F DX-Y.NYB ^VIX HYG TWD=X）、
    FRED fredgraph.csv（DGS10 DGS2 ICSA）、期交所 futDataDown（台指期 TX，2017-05 起逐月）。
    只在 `--refresh-cache` 或快取不存在時連網，存在 `~/.cache/dsa/research/`（csv）。

07:30 資訊集（對齊規則，見 `align_available`）：
  每個外部觀測先給 `available_at`（日期），台股交易日 t 只能用 `available_at < t`（**嚴格小於**）的最後一筆：
  - 美股／商品期貨／DXY／VIX／HYG 的 bar 日期 D：收盤在台北 D+1 清晨 04:00～06:00，`available_at = D`
    → 給台股 D+1 以後用；不是一律 shift(1)，台股連假後那天會一次吃到連假期間所有美股變化。
  - TWD=X：yfinance 外匯日線的收盤時點錯置（docs/research/2026-10-23-data-audit.md），保守設
    `available_at = D+1`（晚一天）。
  - FRED DGS10／DGS2：H.15 在下一個美國營業日才上 FRED，`available_at = D + 1 個美國營業日`（保守）。
  - FRED ICSA：觀測日是週六（週末結束日），下週四 08:30 ET 公布 ＝ 台北週四晚上，
    `available_at = 觀測日 + 5 天`（週四）→ 台股週五 07:30 才可用。修訂後值、非首發值（FRED 不存 vintage）。
  - 夜盤：期交所「盤後」列的日期 d ＝ d−1 15:00 到 d 05:00 那段，d 當天 07:30 已收 → 直接按日期 join；
    契約用 **d−1 日盤成交量最大**的月契約（不能用 d 日盤，那是 07:30 之後的資訊），
    夜盤報酬 ＝ 該契約夜盤收盤 ÷ 同契約 d−1 日盤結算價 − 1。

目標（07:30 決策，台股日 t）：
  CO ＝ open_t / close_{t−1} − 1（開盤缺口；沒有 0050 可交易腿，只過門檻 1）
  OC ＝ close_t / open_t − 1（＝1 日）
  Rh ＝ close_{t+h−1} / open_t − 1，h＝2..5（07:30 訊號、開盤進場、第 h 個交易日收盤出場）
  訓練時，第 s 列的目標要到 s+h−1 收盤才知道，所以預測 t 只用 s ≤ t−h 的列（`train_bounds`）。

模型階梯（逐層加變數；特徵定義見 `build_features`）：
  S0 只 SOX ／ B0 台股自身落後項 ／ S＝B0＋SOX ／ U＝S＋NDX、S&P、TSM、ADR 溢價 ／
  N＝U＋夜盤 ／ F＝N＋10Y、2Y、DXY、TWD、Brent、HYG、VIX、ICSA 週變化 ／
  F−N（F 去夜盤，2010 起對 U）／ 對 F 逐組刪除（利率、美元台幣、油、信用、波動、就業）。
  OLS（主）與 ridge（λ 固定、不調）；滾動窗 252／756 列（不足窗長時至少 252 列才開始預測）。

判準（事前寫定）：
  (1) 樣本外增量 R²（分母用訓練窗均值當基準預測）＝ Σ(e²_小 − e²_大) / Σ e²_基準，
      同日配對 circular block bootstrap 95% CI 下界 > 0。
  (2) 只對 OC 與 2～5 日：pred > 0 做多 0050（開盤進、第 h 日收盤出），否則空手；
      每筆淨報酬（`round_trip_return`、ETF 稅率）block bootstrap 95% CI 下界 > 0。
  唯一確認性比較：F 對 N、OC、756、OLS、2017-05 起；其餘全部探索性。
  事件規則四條（G1-14／G1-12／G1-15／G2-10）門檻固定，Bonferroni α＝0.05/4（CI 98.75%）。

用法：
    # 先抓外部資料到快取（只在這一步連網）
    uv run --frozen python scripts/research_macro_ladder.py --refresh-cache --cache-only
    # 跑研究（需要 DATABASE_URL；只讀）
    DATABASE_URL=... uv run --frozen python scripts/research_macro_ladder.py --out reports/macro_ladder.md
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

DEFAULT_CACHE = Path.home() / ".cache" / "dsa" / "research"
HIST_START = "2009-06-01"            # 外部序列多抓半年，給 20 日新高與滾動特徵暖機
TW_START = "2010-01-01"
NIGHT_START = dt.date(2017, 5, 1)    # 期交所盤後交易 2017-05-15 開始
NOTIONAL = 200_000.0
RIDGE_LAMBDA = 0.1                   # 標準化特徵上的 (1/n)·SSE + λ·Σβ²；事前固定、不調
MIN_TRAIN = 252
WINDOWS = (252, 756)
BLOCK = 20                           # 主比較的 block 長度（交易日）；敏感度 10／60
EVENT_BLOCK = 60
N_BOOT = 2000
SEED = 42
BONFERRONI_RULES = 4

# 名稱 → (來源, 代號, available_at 規則)
YF_SERIES = {
    "SOX": "^SOX", "NDX": "^NDX", "IXIC": "^IXIC", "SPX": "^GSPC", "TSM": "TSM",
    "WTI": "CL=F", "BRENT": "BZ=F", "DXY": "DX-Y.NYB", "VIX": "^VIX", "HYG": "HYG",
    "TWD": "TWD=X",
}
FRED_SERIES = {"DGS10": "DGS10", "DGS2": "DGS2", "ICSA": "ICSA"}
AVAILABLE_RULE = {k: "us_close" for k in YF_SERIES}
AVAILABLE_RULE.update({"TWD": "next_day", "DGS10": "next_us_bday", "DGS2": "next_us_bday",
                       "ICSA": "icsa_thursday"})

# 特徵組（F 的逐組刪除以這裡為單位）
B0_COLS = ["tw_cc1", "tw_oc1", "tw_cc5"]
SOX_COLS = ["sox"]
U_EXTRA = ["ndx", "spx", "tsm", "adr_prem"]
NIGHT_COLS = ["night"]
MACRO_GROUPS = {
    "利率(10Y,2Y)": ["dgs10", "dgs2"],
    "美元台幣(DXY,TWD)": ["dxy", "twd"],
    "油(Brent)": ["brent"],
    "信用(HYG)": ["hyg"],
    "波動(VIX)": ["vix"],
    "就業(ICSA)": ["icsa"],
}
MACRO_COLS = [c for cols in MACRO_GROUPS.values() for c in cols]
MODELS = {
    "S0": SOX_COLS,
    "B0": B0_COLS,
    "S": B0_COLS + SOX_COLS,
    "U": B0_COLS + SOX_COLS + U_EXTRA,
    "N": B0_COLS + SOX_COLS + U_EXTRA + NIGHT_COLS,
    "F": B0_COLS + SOX_COLS + U_EXTRA + NIGHT_COLS + MACRO_COLS,
    "F-N": B0_COLS + SOX_COLS + U_EXTRA + MACRO_COLS,
}
for _g, _cols in MACRO_GROUPS.items():
    MODELS[f"F−{_g}"] = [c for c in MODELS["F"] if c not in _cols]


def uses_night(model):
    return "night" in MODELS[model]


TARGETS = ("CO", "OC", "R2", "R3", "R4", "R5")
TRADEABLE = ("OC", "R2", "R3", "R4", "R5")

PERIODS_LONG = [("2010–16", "2010-01-01", "2016-12-31"), ("2017–19", "2017-01-01", "2019-12-31"),
                ("2020–22", "2020-01-01", "2022-12-31"), ("2023+", "2023-01-01", "2099-12-31")]
PERIODS_NIGHT = [("2017-05–19", "2017-05-01", "2019-12-31"), ("2020–22", "2020-01-01", "2022-12-31"),
                 ("2023+", "2023-01-01", "2099-12-31")]
EXPLORATORY_CUT = ("2024+（探索性，C8 台積電權重跳升）", "2024-01-01", "2099-12-31")
ELECTRONIC_INDUSTRIES = {"24", "25", "26", "27", "28", "29", "30", "31"}  # 半導體～其他電子


# ---------- 純函式：對齊（07:30 資訊集） ----------

FX_SERIES = ("TWD", "DXY")
FX_MAX_DEV = 0.5    # 匯率偏離前 5 筆中位數 >50% 才算壞價（TWD=X 有 1.80、3.9 這種錯值；2025-05 台幣真實急升約 8%，不能丟）


def drop_bad_ticks(s, max_dev, lookback=5):
    """丟掉偏離「前 lookback 筆中位數」超過 max_dev 的觀測（只看過去，不偷看）。回 (清理後, 被丟日期)。"""
    s = s.dropna()
    med = s.shift(1).rolling(lookback, min_periods=1).median()
    bad = (s / med - 1).abs() > max_dev
    return s[~bad], list(s.index[bad].date)


def available_at(dates, rule):
    """觀測日期 → 可用日期（該日期當天 07:30 之前**不可**用，台股日 t 只能用 available_at < t）。"""
    d = pd.DatetimeIndex(pd.to_datetime(dates)).normalize()
    if rule == "us_close":
        return d
    if rule == "next_day":
        return d + pd.Timedelta(days=1)
    if rule == "next_us_bday":
        return d + pd.offsets.BDay(1)
    if rule == "icsa_thursday":
        return d + pd.Timedelta(days=5)
    raise ValueError(f"unknown available_at rule: {rule}")


def align_available(tw_days, obs, rule):
    """把外部觀測（index＝觀測日期）對齊到台股交易日：取 available_at **嚴格早於** t 的最後一筆。

    `merge_asof(allow_exact_matches=False)`：available_at 剛好等於 t 的觀測（例：美股 t 日收盤，
    台北 t+1 清晨才收）在 t 的 07:30 不可得，必須排除。"""
    obs = obs.dropna()
    left = pd.DataFrame({"t": pd.DatetimeIndex(tw_days).normalize().as_unit("ns")})
    right = pd.DataFrame({"t": available_at(obs.index, rule).as_unit("ns"), "v": obs.to_numpy()})
    right = right.sort_values("t", kind="stable").drop_duplicates("t", keep="last")
    out = pd.merge_asof(left, right, on="t", direction="backward", allow_exact_matches=False)
    return pd.Series(out["v"].to_numpy(), index=pd.DatetimeIndex(tw_days))


def new_events(tw_days, flags, rule):
    """觀測層的 0/1 旗標 → 台股日 t 是否有「上一個台股日之後新變得可用」的觸發。

    用累計觸發數對齊後取差分，台股連假期間累積的多筆觀測也只算進第一個可用日。"""
    cum = flags.fillna(False).astype(int).cumsum()
    c = align_available(tw_days, cum, rule)
    prev = c.shift(1)
    return ((c - prev.fillna(0)) > 0) & c.notna()


def night_returns(rows, tw_days):
    """期交所 TX 列（`verify_morning_calls.parse_tx` 格式）→ 台股日 t 的夜盤報酬。

    盤後列日期 d 已在 d 的 07:30 收盤；契約用 d 前一個台股日的日盤成交量最大者（07:30 可得），
    但只在 d 有夜盤成交的契約裡挑（結算日當天量最大的是到期契約，它沒有 d 的夜盤；夜盤 05:00 已收，
    哪些契約有成交在 07:30 可得）。報酬＝該契約夜盤收盤 ÷ 同契約前一台股日日盤結算價 − 1。缺任一值回 NaN。"""
    days = [pd.Timestamp(x).date() for x in tw_days]
    day_session = {}
    night = {}
    for r in rows:
        if r["session"] == "一般":
            day_session.setdefault(r["date"], []).append(r)
        elif r["session"] == "盤後" and r["volume"] > 0 and r["close"]:
            night[(r["date"], r["contract"])] = r["close"]
    out = np.full(len(days), np.nan)
    for i in range(1, len(days)):
        prev_rows = [r for r in day_session.get(days[i - 1], [])
                     if r["volume"] > 0 and (days[i], r["contract"]) in night]
        if not prev_rows:
            continue
        top = max(prev_rows, key=lambda r: r["volume"])
        close = night.get((days[i], top["contract"]))
        if close and top["settle"]:
            out[i] = close / top["settle"] - 1
    return pd.Series(out, index=pd.DatetimeIndex(tw_days))


# ---------- 純函式：目標與特徵 ----------

def build_targets(tw):
    """tw: index＝台股交易日，欄 open/close（TAIEX）。回傳各目標（第 t 列＝07:30 於 t 決策的報酬）。"""
    o, c = tw["open"], tw["close"]
    out = {"CO": o / c.shift(1) - 1, "OC": c / o - 1}
    for h in range(2, 6):
        out[f"R{h}"] = c.shift(-(h - 1)) / o - 1
    return pd.DataFrame(out)


def target_horizon(name):
    """第 s 列目標在 s+h−1 收盤（CO 在 s 開盤）才知道；預測 t 只能用 s ≤ t−h 的列。"""
    return int(name[1]) if name.startswith("R") else 1


def build_features(tw, aligned, night, adr_prem):
    """tw：TAIEX open/close；aligned：已對齊到台股日的外部水準（欄名＝序列名）；
    night：夜盤報酬；adr_prem：ADR 溢價水準。回傳特徵（全部只用 t 的 07:30 可得資訊）。

    外部序列的特徵＝「這次可得水準 ÷ 上一個台股日可得水準 − 1」：期間沒有新觀測就是 0，
    連假後那天自動累積。殖利率用差分（百分點），ICSA 用最新兩次公布的週變化。"""
    c, o = tw["close"], tw["open"]
    f = pd.DataFrame(index=tw.index)
    f["tw_cc1"] = c.shift(1) / c.shift(2) - 1
    f["tw_oc1"] = c.shift(1) / o.shift(1) - 1
    f["tw_cc5"] = c.shift(1) / c.shift(6) - 1
    for name, col in (("SOX", "sox"), ("NDX", "ndx"), ("SPX", "spx"), ("TSM", "tsm"),
                      ("DXY", "dxy"), ("TWD", "twd"), ("BRENT", "brent"), ("HYG", "hyg")):
        lv = aligned[name]
        f[col] = lv / lv.shift(1) - 1
    f["vix"] = np.log(aligned["VIX"] / aligned["VIX"].shift(1))
    f["dgs10"] = aligned["DGS10"] - aligned["DGS10"].shift(1)
    f["dgs2"] = aligned["DGS2"] - aligned["DGS2"].shift(1)
    f["icsa"] = aligned["ICSA_CHG"]
    f["adr_prem"] = adr_prem
    f["night"] = night
    return f


# ---------- 純函式：滾動樣本外 ----------

def train_bounds(i, horizon, window):
    """預測第 i 列時可用的訓練列 [start, end)：end＝i−horizon+1（只含 s ≤ i−h），往前最多 window 列。"""
    end = i - horizon + 1
    return max(0, end - window), max(0, end)


def fit_predict(Xtr, ytr, x, lam):
    """標準化（只用訓練窗統計）後解 ridge 閉式解；lam=0 即 OLS。回 (預測, 訓練均值基準)。"""
    mu, sd = Xtr.mean(0), Xtr.std(0)
    sd[sd == 0] = 1.0
    Z = (Xtr - mu) / sd
    z = (x - mu) / sd
    ym = ytr.mean()
    n, k = Z.shape
    A = Z.T @ Z + lam * n * np.eye(k)
    beta = np.linalg.lstsq(A, Z.T @ (ytr - ym), rcond=None)[0]
    return float(ym + z @ beta), float(ym)


def min_train_for(window):
    """窗內至少要有幾列完整資料才預測：756 窗要 252 列；252 窗要 80%（夜盤有零星缺日，要求全滿會整段沒預測）。"""
    return min(MIN_TRAIN, int(0.8 * window))


def rolling_oos(X, y, horizon, window, lam=0.0, min_train=MIN_TRAIN):
    """X:(n,k)、y:(n,)，可含 NaN。回 (pred, bench)；bench＝同一訓練窗的 y 均值（樣本外 R² 的分母）。"""
    n = len(y)
    pred = np.full(n, np.nan)
    bench = np.full(n, np.nan)
    ok_row = np.isfinite(X).all(1) & np.isfinite(y)
    for i in range(n):
        if not np.isfinite(X[i]).all():
            continue
        s, e = train_bounds(i, horizon, window)
        idx = np.flatnonzero(ok_row[s:e]) + s
        if len(idx) < min_train:
            continue
        pred[i], bench[i] = fit_predict(X[idx], y[idx], X[i], lam)
    return pred, bench


# ---------- 純函式：bootstrap ----------

def block_weights(n, block, n_boot, seed):
    """circular block bootstrap 的權重矩陣（n_boot × n），每列是各日被抽到的次數。"""
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block))
    offs = np.arange(block)
    W = np.empty((n_boot, n))
    for b in range(n_boot):
        pos = ((rng.integers(0, n, size=n_blocks)[:, None] + offs) % n).ravel()[:n]
        W[b] = np.bincount(pos, minlength=n)
    return W


def incremental_r2(y, small, big, bench, block=BLOCK, n_boot=N_BOOT, seed=SEED, alpha=0.05):
    """大模型相對小模型的樣本外增量 R²（同日配對）＋ block bootstrap CI。輸入需已對齊同一組日期。"""
    m = np.isfinite(y) & np.isfinite(small) & np.isfinite(big) & np.isfinite(bench)
    y, small, big, bench = y[m], small[m], big[m], bench[m]
    n = len(y)
    if n < 2 * block:
        return {"n": n, "dr2": np.nan, "ci": None}
    d = (y - small) ** 2 - (y - big) ** 2
    e0 = (y - bench) ** 2
    W = block_weights(n, block, n_boot, seed)
    stats = (W @ d) / (W @ e0)
    q = 100 * alpha / 2
    return {"n": n, "dr2": float(d.sum() / e0.sum()),
            "ci": (float(np.percentile(stats, q)), float(np.percentile(stats, 100 - q)))}


def oos_r2(y, pred, bench):
    m = np.isfinite(y) & np.isfinite(pred) & np.isfinite(bench)
    if not m.any():
        return np.nan
    return float(1 - ((y[m] - pred[m]) ** 2).sum() / ((y[m] - bench[m]) ** 2).sum())


def mean_ci(values, valid, block=BLOCK, n_boot=N_BOOT, seed=SEED, alpha=0.05):
    """依日序的值（valid=False 的日不計）的均值與 block bootstrap CI（區塊以完整日曆抽）。"""
    v = np.where(valid, values, 0.0)
    cnt = valid.astype(float)
    n = len(v)
    k = int(cnt.sum())
    if k < 30 or n < 2 * block:
        return {"n": k, "mean": float(v.sum() / k) if k else np.nan, "ci": None}
    W = block_weights(n, block, n_boot, seed)
    den = W @ cnt
    ok = den > 0
    stats = (W[ok] @ v) / den[ok]
    q = 100 * alpha / 2
    return {"n": k, "mean": float(v.sum() / k),
            "ci": (float(np.percentile(stats, q)), float(np.percentile(stats, 100 - q)))}


def diff_ci(values, state, block=EVENT_BLOCK, n_boot=N_BOOT, seed=SEED, alpha=0.05):
    """state：1＝事件、0＝對照、NaN＝不計。回事件均值−對照均值與 block bootstrap CI。"""
    st = np.nan_to_num(np.asarray(state, float), nan=-1)
    vals = np.nan_to_num(values, nan=0.0)
    ok = np.isfinite(values)
    ins, out = (st == 1) & ok, (st == 0) & ok
    res = {"n_event": int(ins.sum()), "n_ctrl": int(out.sum()),
           "event_mean": float(vals[ins].mean()) if ins.any() else np.nan,
           "ctrl_mean": float(vals[out].mean()) if out.any() else np.nan}
    res["diff"] = res["event_mean"] - res["ctrl_mean"]
    n = len(vals)
    if ins.sum() < 5 or out.sum() < 30 or n < 2 * block:
        res["ci"] = None
        return res
    W = block_weights(n, block, n_boot, seed)
    ci_, co_ = W @ ins.astype(float), W @ out.astype(float)
    ok_b = (ci_ > 0) & (co_ > 0)
    stats = (W[ok_b] @ (vals * ins)) / ci_[ok_b] - (W[ok_b] @ (vals * out)) / co_[ok_b]
    q = 100 * alpha / 2
    res["ci"] = (float(np.percentile(stats, q)), float(np.percentile(stats, 100 - q)))
    return res


def onsets(trigger, gap):
    """觸發日 → 獨立事件：前一個獨立事件之後滿 gap 個交易日才再計一次。回 state（1 事件、0 對照、NaN 非獨立觸發）。"""
    trig = np.asarray(trigger, bool)
    state = np.zeros(len(trig))
    last = -10 ** 9
    for i, t in enumerate(trig):
        if t:
            if i - last >= gap:
                state[i] = 1
                last = i
            else:
                state[i] = np.nan
    return state


def event_regression_ci(y, event, control, block=EVENT_BLOCK, n_boot=N_BOOT, seed=SEED, alpha=0.05):
    """y = a + b·event + c·control 的 b 與 block bootstrap CI（只用 event∈{0,1} 且值齊全的日）。"""
    ev = np.asarray(event, float)
    m = np.isfinite(y) & np.isfinite(ev) & np.isfinite(control)
    n = len(y)
    X = np.column_stack([np.ones(n), np.nan_to_num(ev), np.nan_to_num(control)])
    yy = np.nan_to_num(y)
    w0 = m.astype(float)

    def coef(w):
        Xw = X * w[:, None]
        return np.linalg.lstsq(Xw.T @ X, Xw.T @ yy, rcond=None)[0][1]

    b = float(coef(w0))
    res = {"n_event": int(((ev == 1) & m).sum()), "n_ctrl": int(((ev == 0) & m).sum()), "b": b}
    if res["n_event"] < 5:
        res["ci"] = None
        return res
    W = block_weights(n, block, n_boot, seed)
    stats = np.array([coef(wb * w0) for wb in W])
    q = 100 * alpha / 2
    res["ci"] = (float(np.percentile(stats, q)), float(np.percentile(stats, 100 - q)))
    return res


def verdict(ci):
    if ci is None:
        return "inconclusive（樣本不足）"
    if ci[0] <= 0 <= ci[1]:
        return "inconclusive（CI 跨零）"
    return "過（下界>0）" if ci[0] > 0 else "顯著為負"


# ---------- 資料：外部快取（只有這裡連網） ----------

def _cache_path(cache, name):
    return Path(cache) / f"{name}.csv"


def fetch_yf(ticker):
    import warnings
    import yfinance as yf
    warnings.filterwarnings("ignore", module="yfinance")  # pandas 3.1 對 yfinance 內部 inplace 的棄用警告
    df = yf.download(ticker, start=HIST_START, auto_adjust=True, progress=False, threads=False)
    if df is None or df.empty:
        raise RuntimeError(f"yfinance {ticker} 回空")
    close = df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    return close.rename("value").rename_axis("date").to_frame()


def fetch_fred(series_id):
    import requests
    r = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": series_id},
                     timeout=30)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = ["date", "value"]
    df["value"] = pd.to_numeric(df["value"], errors="coerce")  # FRED 缺值是 "."
    df["date"] = pd.to_datetime(df["date"])
    return df[df["date"] >= HIST_START].set_index("date")


def fetch_taifex_month(start, end):
    from market_data import taifex
    from verify_morning_calls import TX_URL
    text, reason = taifex.fetch_csv(TX_URL, {"down_type": "1", "commodity_id": "TX",
                                             "queryStartDate": f"{start:%Y/%m/%d}",
                                             "queryEndDate": f"{end:%Y/%m/%d}"})
    return text, reason


def refresh_cache(cache, today, log=print):
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    for name, tk in YF_SERIES.items():
        fetch_yf(tk).to_csv(_cache_path(cache, name))
        log(f"yfinance {tk} → {name}.csv")
    for name, sid in FRED_SERIES.items():
        fetch_fred(sid).to_csv(_cache_path(cache, name))
        log(f"FRED {sid} → {name}.csv")
    tx_dir = cache / "taifex_tx"
    tx_dir.mkdir(exist_ok=True)
    m = NIGHT_START
    while m <= today:
        nxt = (pd.Timestamp(m) + pd.offsets.MonthBegin(1)).date()
        f = tx_dir / f"{m:%Y-%m}.csv"
        # 過去的月份抓過就不重抓；當月每次重抓
        if not f.exists() or nxt > today:
            text, reason = fetch_taifex_month(m, min(nxt - dt.timedelta(days=1), today))
            if reason or not text:
                log(f"futDataDown {m:%Y-%m}：未取得（{reason}）")
            else:
                f.write_text(text, encoding="utf-8")
            time.sleep(1.5)
        m = nxt
    log(f"快取在 {cache}")


def load_cache(cache):
    out = {}
    for name in list(YF_SERIES) + list(FRED_SERIES):
        p = _cache_path(cache, name)
        if not p.exists():
            raise FileNotFoundError(f"缺快取 {p}；先跑 --refresh-cache")
        s = pd.read_csv(p, index_col=0, parse_dates=True)["value"].astype(float)
        out[name] = s[~s.index.duplicated(keep="last")].sort_index()
    return out


def load_taifex(cache):
    from verify_morning_calls import parse_tx
    rows = []
    months = []
    for f in sorted((Path(cache) / "taifex_tx").glob("*.csv")):
        rows += parse_tx(f.read_text(encoding="utf-8"))
        months.append(f.stem)
    return rows, months


# ---------- 資料：台股（唯讀 DB） ----------

def read_only_engine():
    from sqlalchemy import create_engine, event
    from market_data.db import database_url
    eng = create_engine(database_url(), connect_args={
        "options": "-c default_transaction_read_only=on"})

    @event.listens_for(eng, "connect")
    def _ro(dbapi_conn, _rec):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
        cur.close()
        dbapi_conn.commit()

    return eng


def load_tw(engine):
    from sqlalchemy import text
    from market_data.adjust import is_common_stock, load_factors
    with engine.connect() as c:
        idx = pd.read_sql(text(
            "select date, open::float8 open, close::float8 close from market.market_index "
            "where index_id='TAIEX' and date >= :s order by date"), c,
            params={"s": TW_START}, parse_dates=["date"]).set_index("date")
        px = pd.read_sql(text(
            "select stock_id, date, open::float8 open, close::float8 close from market.price "
            "where date >= :s and (stock_id in ('0050','2330') or stock_id in "
            "(select stock_id from market.stock_info))"), c,
            params={"s": TW_START}, parse_dates=["date"])
        info = pd.read_sql(text("select stock_id, industry from market.stock_info"), c)
    idx = idx.dropna(subset=["open", "close"])
    opn = px.pivot(index="date", columns="stock_id", values="open").reindex(idx.index)
    cls = px.pivot(index="date", columns="stock_id", values="close").reindex(idx.index)
    raw_2330 = cls["2330"].copy()
    adj = load_factors(engine, cls.index, cls.columns)
    opn, cls = opn * adj, cls * adj
    info = info[info["stock_id"].map(is_common_stock)]
    return idx, opn, cls, raw_2330, info


# ---------- 報告 ----------

def pct(x, d=2):
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x * 100:+.{d}f}%"


def fmt_ci(ci, d=2):
    return "—" if ci is None else f"{pct(ci[0], d)} ~ {pct(ci[1], d)}"


def r2s(x):
    return "—" if x is None or np.isnan(x) else f"{x * 100:+.2f}"


def r2ci(ci):
    return "—" if ci is None else f"{ci[0] * 100:+.2f} ~ {ci[1] * 100:+.2f}"


def period_mask(index, lo, hi):
    return (index >= pd.Timestamp(lo)) & (index <= pd.Timestamp(hi))


def main(argv=None):
    p = argparse.ArgumentParser(
        description="總經模型階梯（07:30 資訊集）＋四條預登記事件規則（唯讀研究；不寫 DB）")
    p.add_argument("--cache-dir", default=str(DEFAULT_CACHE), help="外部資料快取目錄")
    p.add_argument("--refresh-cache", action="store_true",
                   help="重新抓 yfinance／FRED／期交所到快取（唯一會連網的路徑）")
    p.add_argument("--cache-only", action="store_true", help="只更新快取、不跑研究（不需要 DB）")
    p.add_argument("--bootstrap", type=int, default=N_BOOT)
    p.add_argument("--seed", type=int, default=SEED)
    p.add_argument("--quick", action="store_true", help="只跑 OLS、窗口 756（開發用）")
    p.add_argument("--out", default=None, help="輸出 markdown 路徑（建議 reports/…）")
    a = p.parse_args(argv)

    cache = Path(a.cache_dir).expanduser()
    today = dt.date.today()
    if a.refresh_cache:
        refresh_cache(cache, today, log=lambda m: print(m, file=sys.stderr))
    if a.cache_only:
        return 0
    os.environ.setdefault("STORAGE_DATABASE_URL", "")

    ext = load_cache(cache)
    tx_rows, tx_months = load_taifex(cache)
    eng = read_only_engine()
    tw, opn, cls, raw_2330, info = load_tw(eng)
    days = tw.index

    # 07:30 對齊
    bad_ticks = {}
    aligned = pd.DataFrame(index=days)
    for name, s in ext.items():
        if name == "ICSA":
            continue
        if name in FX_SERIES:
            s, dropped = drop_bad_ticks(s, FX_MAX_DEV)
            bad_ticks[name] = dropped
            ext[name] = s  # 事件規則（G1-15）也用清理後的序列
        aligned[name] = align_available(days, s, AVAILABLE_RULE[name])
    icsa_chg = np.log(ext["ICSA"] / ext["ICSA"].shift(1))
    aligned["ICSA_CHG"] = align_available(days, icsa_chg, AVAILABLE_RULE["ICSA"])
    night = night_returns(tx_rows, days) if tx_rows else pd.Series(np.nan, index=days)
    # ADR 溢價：TSM（美元，最近可得收盤）× 可得的 USDTWD ÷（5 × 2330 前一台股日未還原收盤）− 1。
    # TSM 是 yfinance 還原價（含息），溢價水準會隨累積股利緩慢漂移；滾動窗回歸吸收大部分。
    adr_prem = aligned["TSM"] * aligned["TWD"] / (5 * raw_2330.shift(1)) - 1
    feats = build_features(tw, aligned, night, adr_prem)
    targets = build_targets(tw)
    night_ok = night.notna()
    first_night = night_ok.idxmax() if night_ok.any() else None

    windows = (756,) if a.quick else WINDOWS
    lams = {"OLS": 0.0} if a.quick else {"OLS": 0.0, "ridge": RIDGE_LAMBDA}
    preds = {}
    t0 = time.time()
    for tgt in TARGETS:
        y = targets[tgt].to_numpy()
        h = target_horizon(tgt)
        for w in windows:
            for est, lam in lams.items():
                for mname, cols in MODELS.items():
                    X = feats[cols].to_numpy()
                    preds[(tgt, w, est, mname)] = rolling_oos(X, y, h, w, lam, min_train=min_train_for(w))
    print(f"rolling fits: {len(preds)} 組，{time.time() - t0:.0f}s", file=sys.stderr)

    # 0050 交易腿：open_t 進、close_{t+h−1} 出，`round_trip_return` ETF 稅率
    from src.utils.tw_trade_costs import ETF_TRANSACTION_TAX_RATE, round_trip_return
    o50, c50 = opn["0050"], cls["0050"]
    etf_cost = -round_trip_return(1.0, 1.0, entry_notional=NOTIONAL, tax_rate=ETF_TRANSACTION_TAX_RATE)

    def leg_net(h):
        gross = (c50.shift(-(h - 1)) / o50 - 1).to_numpy()
        out = np.full(len(gross), np.nan)
        for i, g in enumerate(gross):
            if np.isfinite(g):
                out[i] = round_trip_return(1.0, 1.0 + g, entry_notional=NOTIONAL,
                                           tax_rate=ETF_TRANSACTION_TAX_RATE)
        return out

    nets = {t: leg_net(target_horizon(t)) for t in TRADEABLE}

    L = []
    w_ = L.append
    n_specs = len(preds)
    w_("# 總經模型階梯（自動產出，數字以這份為準）\n")
    w_(f"- TAIEX {days[0].date()} ~ {days[-1].date()}（{len(days)} 個交易日，open 為 NULL 的列已丟）")
    w_(f"- 夜盤：futDataDown 月檔 {len(tx_months)} 個（{tx_months[0] if tx_months else '—'} ~ "
       f"{tx_months[-1] if tx_months else '—'}），第一個有夜盤報酬的台股日 "
       f"{first_night.date() if first_night is not None else '未取得'}，有值 {int(night_ok.sum())} 天")
    w_(f"- 0050 來回成本（`round_trip_return`，名目 {NOTIONAL:,.0f}、ETF 稅 0.1%、滑價每邊 0.15%）："
       f"{etf_cost * 100:.3f}%")
    w_(f"- 滾動擬合：{len(TARGETS)} 目標 × {len(windows)} 窗 × {len(lams)} 估計式 × {len(MODELS)} 模型 "
       f"＝ **{n_specs} 條樣本外預測序列**；ridge λ={RIDGE_LAMBDA}（固定、未調）；最少訓練列數 756 窗 {min_train_for(756)}、252 窗 {min_train_for(252)}")
    w_("- 匯率壞價（偏離前 5 筆中位數 >50%）已丟：" + "；".join(
        f"{k} {', '.join(map(str, v)) or '無'}" for k, v in bad_ticks.items()))
    w_(f"- bootstrap：circular block，主 block={BLOCK} 日、{a.bootstrap} 次、seed={a.seed}；"
       "事件規則 block=60\n")

    # 期間覆蓋（實際有值的特徵範圍）
    w_("## 特徵覆蓋（非 NaN 天數）\n")
    w_("| 特徵 | 第一天 | 天數 |")
    w_("|---|---|---|")
    for col in feats.columns:
        s = feats[col].dropna()
        w_(f"| {col} | {s.index[0].date() if len(s) else '—'} | {len(s)} |")

    # ---- 確認性主比較 ----
    def cmp(tgt, w, est, small, big, mask=None, block=BLOCK, alpha=0.05):
        y = targets[tgt].to_numpy()
        ps, bs = preds[(tgt, w, est, small)]
        pb, bb = preds[(tgt, w, est, big)]
        m = np.isfinite(ps) & np.isfinite(pb)
        if uses_night(small) or uses_night(big):
            m &= days >= pd.Timestamp(NIGHT_START)
        if mask is not None:
            m &= mask
        yy = np.where(m, y, np.nan)
        # 共同基準：大模型的訓練窗均值（同一窗、同一列集合時兩者相同）
        return incremental_r2(yy, ps, pb, bb, block=block, n_boot=a.bootstrap, seed=a.seed, alpha=alpha)

    w_("\n## 唯一確認性比較：F 對 N、OC、窗口 756、OLS、2017-05 起\n")
    w_("| block | n | 增量 R²（%） | 95% CI | 判讀 |")
    w_("|---|---|---|---|---|")
    for blk in (BLOCK, 10, 60):
        r = cmp("OC", 756, "OLS", "N", "F", block=blk)
        w_(f"| {blk}{'（主）' if blk == BLOCK else '（敏感度）'} | {r['n']} | {r2s(r['dr2'])} | "
           f"{r2ci(r['ci'])} | {verdict(r['ci'])} |")
    w_("\n分期（同規格，探索性）：\n")
    w_("| 期間 | n | 增量 R²（%） | 95% CI | 判讀 |")
    w_("|---|---|---|---|---|")
    for lab, lo, hi in PERIODS_NIGHT + [EXPLORATORY_CUT]:
        r = cmp("OC", 756, "OLS", "N", "F", mask=period_mask(days, lo, hi))
        w_(f"| {lab} | {r['n']} | {r2s(r['dr2'])} | {r2ci(r['ci'])} | {verdict(r['ci'])} |")

    # 門檻 (2)：主比較的 F 訊號交易 0050
    def trade_stats(tgt, w, est, model, mask=None, long_short=False):
        pr, _ = preds[(tgt, w, est, model)]
        net = nets[tgt]
        valid = np.isfinite(pr) & np.isfinite(net)
        valid &= days >= pd.Timestamp(NIGHT_START)  # 三個模型同一期間，才可比
        if mask is not None:
            valid &= mask
        if long_short:
            gross = (c50.shift(-(target_horizon(tgt) - 1)) / o50 - 1).to_numpy()
            vals = np.sign(pr) * gross - etf_cost
            trade = valid & (pr != 0) & np.isfinite(gross)
        else:
            vals = net
            trade = valid & (pr > 0)
        blk = max(BLOCK, 2 * target_horizon(tgt))
        return mean_ci(np.nan_to_num(vals), trade, block=blk, n_boot=a.bootstrap, seed=a.seed), int(valid.sum())

    w_("\n## 門檻 (2)：以訊號交易 0050（pred>0 做多、否則空手；每筆淨報酬）\n")
    w_("| 目標 | 窗 | 模型 | 可交易日 | 交易筆數 | 每筆淨報酬 | 95% CI | 判讀 |")
    w_("|---|---|---|---|---|---|---|---|")
    for tgt in TRADEABLE:
        for model in ("F", "N", "U"):
            r, nv = trade_stats(tgt, 756, "OLS", model)
            tag = "（確認性）" if (tgt == "OC" and model == "F") else ""
            w_(f"| {tgt}{tag} | 756 | {model} | {nv} | {r['n']} | {pct(r['mean'], 3)} | "
               f"{fmt_ci(r['ci'], 3)} | {verdict(r['ci'])} |")
    w_("\n參考：同期間每天都做多 0050（不看訊號）的每筆淨報酬：\n")
    w_("| 目標 | 期間 | 筆數 | 每筆淨報酬 | 95% CI |")
    w_("|---|---|---|---|---|")
    for tgt in TRADEABLE:
        net = nets[tgt]
        valid = np.isfinite(net) & (days >= pd.Timestamp(NIGHT_START)) & np.isfinite(
            preds[(tgt, 756, "OLS", "F")][0])
        r = mean_ci(np.nan_to_num(net), valid, block=max(BLOCK, 2 * target_horizon(tgt)),
                    n_boot=a.bootstrap, seed=a.seed)
        w_(f"| {tgt} | 2017-05 起、F 有預測的日 | {r['n']} | {pct(r['mean'], 3)} | {fmt_ci(r['ci'], 3)} |")
    w_("\n探索性：多空雙向（pred<0 放空，成本同口徑、不計借券費）：\n")
    w_("| 目標 | 模型 | 筆數 | 每筆淨報酬 | 95% CI | 判讀 |")
    w_("|---|---|---|---|---|---|")
    for tgt in TRADEABLE:
        r, _ = trade_stats(tgt, 756, "OLS", "F", long_short=True)
        w_(f"| {tgt} | F | {r['n']} | {pct(r['mean'], 3)} | {fmt_ci(r['ci'], 3)} | {verdict(r['ci'])} |")

    # ---- 探索性：階梯 ----
    ladder = [("S0", None, "對基準（訓練均值）"), ("B0", None, "對基準"), ("S", "B0", "S 對 B0"),
              ("U", "S", "U 對 S"), ("F-N", "U", "F去夜盤 對 U"), ("N", "U", "N 對 U"),
              ("F", "N", "F 對 N")] + [("F", f"F−{g}", f"{g}（F 對 F−該組）") for g in MACRO_GROUPS]
    n_cmp = 0
    w_("\n## 探索性：模型階梯全表（樣本外 R² 與增量 R²，單位 %）\n")
    w_("「對基準」列是該模型自身的樣本外 R²（基準＝訓練窗均值）；其餘是同日配對增量（正＝大模型較好）。"
       "「X（F 對 F−該組）」列＝F 相對刪掉該組的增量，正＝該組有邊際貢獻。N、F 相關比較限 2017-05 起。\n")
    for tgt in TARGETS:
        for w in windows:
            for est in lams:
                w_(f"\n### {tgt}｜窗 {w}｜{est}\n")
                w_("| 比較 | 全期 n | 全期 | 全期 95% CI | " + " | ".join(
                    lab for lab, _, _ in PERIODS_LONG) + " | 2024+（探索） |")
                w_("|---|---|---|---|" + "---|" * (len(PERIODS_LONG) + 1))
                for big, small, lab in ladder:
                    y = targets[tgt].to_numpy()
                    pb, bb = preds[(tgt, w, est, big)]
                    night_cmp = uses_night(big) or (small is not None and uses_night(small))
                    base_m = (days >= pd.Timestamp(NIGHT_START)) if night_cmp else np.ones(len(days), bool)
                    cells = []
                    for plab, lo, hi in [("全期", "1900-01-01", "2099-12-31")] + PERIODS_LONG + [EXPLORATORY_CUT]:
                        m = base_m & period_mask(days, lo, hi)
                        if small is None:
                            val = oos_r2(np.where(m, y, np.nan), pb, bb)
                            r = {"n": int((m & np.isfinite(pb)).sum()), "dr2": val, "ci": None}
                            if plab == "全期":
                                r = incremental_r2(np.where(m, y, np.nan), bb, pb, bb,
                                                   n_boot=a.bootstrap, seed=a.seed)
                        else:
                            ps, _ = preds[(tgt, w, est, small)]
                            r = incremental_r2(np.where(m & np.isfinite(ps), y, np.nan), ps, pb, bb,
                                               n_boot=a.bootstrap if plab == "全期" else 200, seed=a.seed)
                        n_cmp += 1
                        if plab == "全期":
                            cells += [str(r["n"]), r2s(r["dr2"]), r2ci(r["ci"])]
                        else:
                            mark = ""
                            if r["ci"] is not None and (r["ci"][0] > 0 or r["ci"][1] < 0):
                                mark = "＊" if r["ci"][0] > 0 else "†"
                            cells.append("—" if r["n"] < 60 else r2s(r["dr2"]) + mark)
                    w_(f"| {lab} | " + " | ".join(cells) + " |")
    w_(f"\n分期欄：＊＝該期 CI 下界 >0、†＝上界 <0（分期 bootstrap 200 次，僅參考）。"
       f"本節共 **{n_cmp} 個比較格**，全部探索性；95% 下約 {n_cmp * 0.05:.0f} 格會純屬偶然顯著。\n")

    # ---- 預登記事件規則 ----
    alpha_b = 0.05 / BONFERRONI_RULES
    c, o = tw["close"], tw["open"]
    fwd = {h: (c.shift(-(h - 1)) / o - 1).to_numpy() for h in (5, 20)}
    w_(f"\n## 四條預登記事件規則（Bonferroni α＝0.05/{BONFERRONI_RULES}，CI {100 * (1 - alpha_b):.2f}%）\n")
    w_("進場一律事件可得後第一個台股日 t 的開盤（07:30 已知），T+h＝第 h 個交易日收盤；"
       "獨立事件＝前一個獨立事件後滿 h 個交易日才再計；非獨立的觸發日不進對照組。\n")
    w_("| 規則 | 組 | h | 獨立事件 | 對照日 | 事件均值 | 對照均值 | 差 | CI | 判讀 |")
    w_("|---|---|---|---|---|---|---|---|---|---|")

    def ev_row(label, group, h, trig, values=None):
        st = onsets(trig, h)
        vals = fwd[h] if values is None else values
        r = diff_ci(vals, st, n_boot=a.bootstrap, seed=a.seed, alpha=alpha_b)
        w_(f"| {label} | {group} | {h} | {r['n_event']} | {r['n_ctrl']} | {pct(r['event_mean'])} | "
           f"{pct(r['ctrl_mean'])} | {pct(r['diff'])} | {fmt_ci(r['ci'])} | {verdict(r['ci'])} |")

    # G1-14：WTI 收盤突破前 20 日最高
    wti = ext["WTI"]
    wti_break = wti > wti.shift(1).rolling(20).max()
    trig14 = new_events(days, wti_break, AVAILABLE_RULE["WTI"]).to_numpy()
    for h in (5, 20):
        ev_row("G1-14 WTI 突破 20 日高", "全部", h, trig14)

    # G1-12：US10Y（FRED DGS10）創 20 日新高，依 SOX 是否在月線（20 日均）下分組
    d10 = ext["DGS10"].dropna()
    d10_high = d10 > d10.shift(1).rolling(20).max()
    trig12 = new_events(days, d10_high, AVAILABLE_RULE["DGS10"]).to_numpy()
    sox = ext["SOX"]
    sox_below = align_available(days, (sox < sox.rolling(20).mean()).astype(float), "us_close").to_numpy()
    for h in (5, 20):
        for grp, gmask in (("SOX 在月線下", sox_below == 1), ("SOX 在月線上", sox_below == 0)):
            ev_row("G1-12 US10Y 20 日新高", grp, h, trig12 & gmask)

    # G1-15：USDTWD 5 日貶 >1%（TWD=X 上升 >1%）→ T+20，控制 TAIEX 前 20 日報酬
    twd = ext["TWD"]
    twd_dep = twd / twd.shift(5) - 1 > 0.01
    trig15 = new_events(days, twd_dep, AVAILABLE_RULE["TWD"]).to_numpy()
    st15 = onsets(trig15, 20)
    past20 = (c.shift(1) / c.shift(21) - 1).to_numpy()
    r15 = event_regression_ci(fwd[20], st15, past20, n_boot=a.bootstrap, seed=a.seed, alpha=alpha_b)
    raw15 = diff_ci(fwd[20], st15, n_boot=a.bootstrap, seed=a.seed, alpha=alpha_b)
    w_(f"| G1-15 USDTWD 5 日貶>1% | 未控制 | 20 | {raw15['n_event']} | {raw15['n_ctrl']} | "
       f"{pct(raw15['event_mean'])} | {pct(raw15['ctrl_mean'])} | {pct(raw15['diff'])} | "
       f"{fmt_ci(raw15['ci'])} | {verdict(raw15['ci'])} |")
    w_(f"| G1-15 USDTWD 5 日貶>1% | 控制前 20 日報酬（迴歸係數） | 20 | {r15['n_event']} | "
       f"{r15['n_ctrl']} | — | — | {pct(r15['b'])} | {fmt_ci(r15['ci'])} | {verdict(r15['ci'])} |")

    # G2-10：Brent 5 日漲 >10% → 電子相對非電子 5 日（等權、還原價）
    brent = ext["BRENT"]
    brent_jump = brent / brent.shift(5) - 1 > 0.10
    trig10 = new_events(days, brent_jump, AVAILABLE_RULE["BRENT"]).to_numpy()
    elec_ids = [s for s in info.loc[info["industry"].isin(ELECTRONIC_INDUSTRIES), "stock_id"] if s in cls]
    non_ids = [s for s in info.loc[~info["industry"].isin(ELECTRONIC_INDUSTRIES), "stock_id"] if s in cls]
    r5 = cls.shift(-4) / opn - 1
    rel = (r5[elec_ids].mean(axis=1) - r5[non_ids].mean(axis=1)).to_numpy()
    ev_row("G2-10 Brent 5 日漲>10%", "電子−非電子（等權）", 5, trig10, values=rel)
    w_(f"\nG2-10 宇宙：`stock_info` 現況快照（只有上市 {len(info)} 檔普通股；電子 {len(elec_ids)}、"
       f"非電子 {len(non_ids)}）。**存活偏誤**：已下市公司不在內；**前視偏誤**：產業別是今天的分類。\n")
    w_(f"事件規則共 {2 + 4 + 2 + 1} 個檢定格（G1-14×2、G1-12×4、G1-15×2〔未控制只當描述〕、G2-10×1）。\n")

    out = "\n".join(L) + "\n"
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(out, encoding="utf-8")
        print(f"→ {a.out}", file=sys.stderr)
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
