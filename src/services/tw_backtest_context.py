"""台股個股 prompt 的「回測脈絡」資訊區塊：大盤狀態與月營收動能。

只當背景資訊：不進買進分數、不做濾網、不做硬性出場。用字規則——只有回測 95% CI
排除零的那幾格可以對 LLM 說「歷史上有差」，其餘一律寫「僅供參考，回測未證實」，並寫明是哪個期距未證實：
0050 季線兩格在 10 日期距對突破候選 CI 排除零（+2.16%／+1.97%，單一期距），只能說「3～5 日未證實」；
營收動能的「降速＜0」在強勢股 h10／h20 排除零，但對買進篩選（突破候選池）5～20 日全部跨零。
數字來源：scripts/measure_market_regime.py 與 scripts/measure_revenue_momentum.py
（2026-10-22 的量測；重跑後數字變了要同步改這裡的文案）。

資料一律讀本地 market schema（唯讀），任何失敗都回 None／''（fail-open），並比對資料
自己的日期：大盤看行情最後一天是否到「今天之前最後一個交易日」，月營收看本地是否有
官方最新月份那一列；拿不到參照就不出區塊。
"""

import logging
from datetime import date, timedelta
from functools import lru_cache
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
from sqlalchemy import text

logger = logging.getLogger(__name__)

PROXY = "0050"
# 與 scripts/measure_market_regime.py --min-turnover 預設（2 億）相同，改一邊要改兩邊
LIQUID_MIN_TURNOVER = 2e8
REGIME_LOOKBACK_DAYS = 150   # MA60＋季線斜率 shift(10)＋20 日均額，約 75 個交易日
RECORD_MIN_HISTORY = 24      # 「創新高」至少要有 24 個月歷史才算數
STRONG_YOY3 = 20.0           # 強勢股：前 3 月平均 YoY 下限（與量測腳本 --strong-yoy3 相同）
DECEL_PP = 20.0              # 大幅降速門檻（百分點，與量測腳本 --decel-pp 相同）


# ---------------------------------------------------------------- 純計算（量測腳本共用）

def regime_states(proxy_close, close, liquid, margin_delta):
    """t 日收盤後可知的二元狀態；NaN 代表當天資料不足、不分組。"""
    # 0050 在 2025-06-11~17 分割停牌 5 天：直接在完整日曆上 rolling 會讓之後 60 天的 MA60
    # 全變 NaN，所以均線與 5 日報酬在 0050 自己的交易日上算，再對回完整日曆（停牌日留 NaN）
    own = proxy_close.dropna()
    ma60 = own.rolling(60).mean().reindex(proxy_close.index)
    slope_ref = own.rolling(60).mean().shift(10).reindex(proxy_close.index)
    r5 = own.pct_change(5).reindex(proxy_close.index)

    def b(cond, valid):
        return cond.astype(float).where(valid)

    breadth = {}
    for w in (20, 60):
        ma = close.rolling(w).mean()
        ok = liquid & ma.notna() & close.notna()
        breadth[w] = (close > ma).where(ok).sum(axis=1) / ok.sum(axis=1).replace(0, np.nan)
    return pd.DataFrame({
        "0050>季線": b(proxy_close > ma60, ma60.notna() & proxy_close.notna()),
        "季線上彎": b(ma60 > slope_ref, ma60.notna() & slope_ref.notna()),
        "寬度20>50%": b(breadth[20] > 0.5, breadth[20].notna()),
        "寬度60>50%": b(breadth[60] > 0.5, breadth[60].notna()),
        "寬度20<20%": b(breadth[20] < 0.2, breadth[20].notna()),
        "融資增+指數跌": b((margin_delta > 0) & (r5 < 0), margin_delta.notna() & r5.notna()),
    }), breadth


def revenue_features(rv, decel_pp=DECEL_PP):
    """逐檔依營收月算動能旗標；旗標是 1.0/0.0，資料不足為 NaN（不當成「沒轉弱」）。

    每檔先補成連續月份，月份有缺時 shift 會自然變 NaN，不會把隔兩個月當成上個月。
    """
    out = []
    for sid, g in rv.sort_values("revenue_month").groupby("stock_id", sort=False):
        g = g.set_index("revenue_month").asfreq("MS")
        yoy, rev = g["yoy"].astype(float), g["revenue"].astype(float)
        yoy3 = yoy.shift(1).rolling(3).mean()
        decel = yoy - yoy3
        prior_max = rev.shift(1).expanding(min_periods=RECORD_MIN_HISTORY).max()
        rec = (rev > prior_max).where(prior_max.notna() & rev.notna())
        r1, r2 = rec.shift(1), rec.shift(2)
        broke = ((r1 == 1) & (r2 == 1) & (rec == 0)).astype(float).where(
            rec.notna() & r1.notna() & r2.notna())
        turn = ((yoy.shift(1) > 0) & (yoy < 0)).astype(float).where(
            yoy.notna() & yoy.shift(1).notna())
        f = pd.DataFrame({
            "stock_id": sid, "announce_date": g["announce_date"], "yoy": yoy,
            "yoy3": yoy3, "decel": decel,
            "decel_lt0": (decel < 0).astype(float).where(decel.notna()),
            "decel_le20": (decel <= -decel_pp).astype(float).where(decel.notna()),
            "mom_neg": (g["mom"].astype(float) < 0).astype(float).where(g["mom"].notna()),
            "broke_record_streak": broke, "yoy_turn_neg": turn,
        })
        out.append(f[g["revenue"].notna()].reset_index())
    return pd.concat(out, ignore_index=True)


def latest_regime(proxy_close, close, turnover, expected_session) -> Optional[Dict[str, Any]]:
    """最後一個交易日的大盤狀態；`expected_session` 是今天之前最後一個台股交易日。

    行情最後一天早於 expected_session → 回 {"as_of", "stale_expected"}（停更，不給狀態）。
    """
    if close is None or close.empty:
        return None
    as_of = pd.Timestamp(close.index[-1]).date()
    if expected_session is None:
        return None  # 沒有參照日就不知道是否停更：拒收
    if as_of < expected_session:
        return {"as_of": as_of, "stale_expected": expected_session}
    liquid = (turnover.rolling(20).mean() >= LIQUID_MIN_TURNOVER).fillna(False)
    no_margin = pd.Series(np.nan, index=close.index)  # 融資背離未接進 prompt（效果小於成本）
    states, breadth = regime_states(proxy_close.reindex(close.index), close, liquid, no_margin)
    last = states.iloc[-1]

    def flag(name):
        v = last.get(name)
        return None if pd.isna(v) else bool(v)

    def ratio(w):
        v = breadth[w].iloc[-1]
        return None if pd.isna(v) else float(v)

    return {
        "as_of": as_of,
        "above_ma60": flag("0050>季線"),
        "ma60_up": flag("季線上彎"),
        "breadth20": ratio(20),
        "breadth60": ratio(60),
    }


def latest_revenue_momentum(rows: pd.DataFrame, anchor_month) -> Optional[Dict[str, Any]]:
    """單檔營收列 → 官方最新月份（anchor_month）的動能；本地沒有那一列或前 3 月不足回 None。"""
    if rows is None or rows.empty or anchor_month is None:
        return None
    feat = revenue_features(rows)
    hit = feat[feat["revenue_month"] == pd.Timestamp(anchor_month)]
    if hit.empty:
        return None  # 本地營收還沒到官方最新月份：停更，不拿舊月份充數
    r = hit.iloc[-1]
    if pd.isna(r["decel"]) or pd.isna(r["yoy3"]):
        return None
    return {
        "month": pd.Timestamp(anchor_month).strftime("%Y-%m"),
        "yoy": float(r["yoy"]),
        "yoy3": float(r["yoy3"]),
        "decel": float(r["decel"]),
        "strong_decel": bool(r["yoy3"] >= STRONG_YOY3 and r["decel"] <= -DECEL_PP),
    }


# ---------------------------------------------------------------- 讀本地 market schema

def _expected_prev_session(today: date) -> Optional[date]:
    from src.core.trading_calendar import get_trading_dates

    sessions = get_trading_dates("tw", today - timedelta(days=15), today)
    if sessions is None:
        return None
    prev = [d.date() for d in sessions if d.date() < today]
    return prev[-1] if prev else None


@lru_cache(maxsize=4)
def _load_regime_cached(today_iso: str) -> Optional[Dict[str, Any]]:
    # 每個執行期每天只算一次（失敗也快取 None，避免每檔股票重打一次全市場查詢）。
    # ponytail: 並行分析剛開始時可能重複算一兩次，量大再加鎖
    try:
        from market_data.adjust import is_common_stock, load_factors
        from market_data.db import get_engine

        today = date.fromisoformat(today_iso)
        start = today - timedelta(days=REGIME_LOOKBACK_DAYS)
        eng = get_engine(statement_timeout_ms=15000)
        with eng.connect() as conn:
            px = pd.read_sql(text(
                "SELECT stock_id, date, close::float8 AS close, turnover::float8 AS turnover "
                "FROM market.price WHERE date >= :s AND date <= :e"), conn,
                params={"s": start, "e": today}, parse_dates=["date"])
        if px.empty:
            return None
        close = px.pivot(index="date", columns="stock_id", values="close").sort_index()
        turnover = px.pivot(index="date", columns="stock_id", values="turnover").reindex(close.index)
        close = close * load_factors(eng, close.index, close.columns, start=start)
        proxy = close[PROXY] if PROXY in close.columns else pd.Series(np.nan, index=close.index)
        keep = [s for s in close.columns if is_common_stock(s)]
        return latest_regime(proxy, close[keep], turnover[keep], _expected_prev_session(today))
    except Exception as exc:  # noqa: BLE001 - prompt enrichment is strictly fail-open
        logger.warning("[tw-regime] fail-open: %s", exc)
        return None


def load_tw_regime(today: Optional[date] = None) -> Optional[Dict[str, Any]]:
    return _load_regime_cached((today or date.today()).isoformat())


def load_tw_revenue_momentum(code: str, anchor_month_iso: Any) -> Optional[Dict[str, Any]]:
    try:
        from data_provider.market_db_fetcher import _stock_id
        from market_data.db import get_engine

        if not anchor_month_iso:
            return None
        anchor = pd.Timestamp(str(anchor_month_iso)[:7] + "-01")
        with get_engine(statement_timeout_ms=3000).connect() as conn:
            rows = pd.read_sql(text(
                "SELECT stock_id, revenue_month, announce_date, revenue, yoy, mom "
                "FROM market.monthly_revenue WHERE stock_id = :sid AND revenue_month >= :s "
                "ORDER BY revenue_month"), conn,
                params={"sid": _stock_id(code), "s": (anchor - pd.DateOffset(months=8)).date()},
                parse_dates=["revenue_month", "announce_date"])
        return latest_revenue_momentum(rows, anchor)
    except Exception as exc:  # noqa: BLE001 - prompt enrichment is strictly fail-open
        logger.warning("[tw-revenue-momentum] fail-open code=%s: %s", code, exc)
        return None


# ---------------------------------------------------------------- prompt 文案

def _tr(language: str):
    english = language in ("en", "ko")

    def T(zh_tw: str, zh: str, en: str) -> str:
        if english:
            return en
        return zh_tw if language == "zh-TW" else zh

    return T


def format_regime_block(regime: Optional[Dict[str, Any]], language: str) -> str:
    if not regime:
        return ""
    T = _tr(language)
    if regime.get("stale_expected"):
        return "\n" + T(
            f"大盤狀態：本地行情停在 {regime['as_of']}、應到 {regime['stale_expected']}，本次不提供大盤狀態。",
            f"大盘状态：本地行情停在 {regime['as_of']}、应到 {regime['stale_expected']}，本次不提供大盘状态。",
            f"Market regime: local price data stops at {regime['as_of']} (expected {regime['stale_expected']}); no regime is provided this run.",
        ) + "\n"

    def yn(v, yes, no):
        return "N/A" if v is None else (yes if v else no)

    def pct(v):
        return "N/A" if v is None else f"{v * 100:.0f}%"

    b20, b60 = regime.get("breadth20"), regime.get("breadth60")
    lines = [
        T(
            f"\n### 大盤狀態（本地行情計算，截至 {regime['as_of']}；僅資訊，不進分數）",
            f"\n### 大盘状态（本地行情计算，截至 {regime['as_of']}；仅资讯，不进分数）",
            f"\n### Market Regime (computed from local prices, as of {regime['as_of']}; information only, not scored)",
        ),
        T(
            f"- 0050 收盤{yn(regime.get('above_ma60'), '高於', '低於')}季線（MA60）、季線{yn(regime.get('ma60_up'), '上彎', '下彎')}：僅供參考，3～5 日回測未證實。",
            f"- 0050 收盘{yn(regime.get('above_ma60'), '高于', '低于')}季线（MA60）、季线{yn(regime.get('ma60_up'), '上弯', '下弯')}：仅供参考，3～5 日回测未证实。",
            f"- 0050 close is {yn(regime.get('above_ma60'), 'above', 'below')} its MA60 and the MA60 is {yn(regime.get('ma60_up'), 'rising', 'falling')}: for reference only, not confirmed by backtest at 3-5 days.",
        ),
        T(
            f"- 市場寬度：流動股收盤高於 MA20 的比例 {pct(b20)}、高於 MA60 的比例 {pct(b60)}。",
            f"- 市场宽度：流动股收盘高于 MA20 的比例 {pct(b20)}、高于 MA60 的比例 {pct(b60)}。",
            f"- Breadth: {pct(b20)} of liquid stocks close above MA20, {pct(b60)} above MA60.",
        ),
    ]
    if b20 is not None and b20 < 0.2:
        lines.append(T(
            "- 寬度20<20%（極端超賣）：歷史上流動股等權後續 5 日報酬較高（+1.33%，95% CI +0.51%～+2.21%，2011–2026，210 天、69 個連續段），屬逢低反向訊號；不得據此否決買進，也不得據此放大突破的分數。",
            "- 宽度20<20%（极端超卖）：历史上流动股等权后续 5 日报酬较高（+1.33%，95% CI +0.51%～+2.21%，2011–2026，210 天、69 个连续段），属逢低反向讯号；不得据此否决买进，也不得据此放大突破的分数。",
            "- Breadth20 < 20% (extreme oversold): historically the equal-weight liquid pool returned more over the next 5 days (+1.33%, 95% CI +0.51% to +2.21%, 2011-2026, 210 days in 69 separate runs). It is a contrarian signal: do not veto a buy because of it, and do not inflate a breakout score because of it.",
        ))
    elif b20 is not None and b20 > 0.5:
        lines.append(T(
            "- 寬度20>50%：僅供參考，回測未證實。",
            "- 宽度20>50%：仅供参考，回测未证实。",
            "- Breadth20 > 50%: for reference only, not confirmed by backtest.",
        ))
    if b60 is not None and b60 > 0.5:
        lines.append(T(
            "- 寬度60>50%：歷史上流動股等權後續 3 日報酬反而較低（−0.35%，95% CI −0.64%～−0.11%，2011–2026），寬度高不是買進確認。",
            "- 宽度60>50%：历史上流动股等权后续 3 日报酬反而较低（−0.35%，95% CI −0.64%～−0.11%，2011–2026），宽度高不是买进确认。",
            "- Breadth60 > 50%: historically the equal-weight liquid pool returned less over the next 3 days (-0.35%, 95% CI -0.64% to -0.11%, 2011-2026); high breadth is not a buy confirmation.",
        ))
    lines.append(T(
        "> 回測（2011–2026，3866 個交易日）：在 3～5 日期距，上述任何大盤狀態對突破候選報酬的差異 95% CI 全部跨零。大盤偏保守本身不是否決個股買進或扣分的理由；本區塊只作背景，不得用來加減買進分數。",
        "> 回测（2011–2026，3866 个交易日）：在 3～5 日期距，上述任何大盘状态对突破候选报酬的差异 95% CI 全部跨零。大盘偏保守本身不是否决个股买进或扣分的理由；本区块只作背景，不得用来加减买进分数。",
        "> Backtest (2011-2026, 3,866 sessions): at 3-5 day horizons, every regime state above has a 95% CI crossing zero for breakout-candidate returns. A cautious market alone is not a reason to veto or downgrade a stock's buy; this block is background only and must not add to or subtract from the buy score.",
    ))
    return "\n".join(lines) + "\n"


def format_revenue_momentum_row(mom: Optional[Dict[str, Any]], language: str) -> str:
    """財報表格中的一列（接在月營收列後面）；無資料回 ''。"""
    if not mom:
        return ""
    T = _tr(language)
    value = T(
        f"前 3 月平均年增 {mom['yoy3']:+.2f}%，本月較其 {mom['decel']:+.2f} 個百分點（本地庫口徑）",
        f"前 3 月平均年增 {mom['yoy3']:+.2f}%，本月较其 {mom['decel']:+.2f} 个百分点（本地库口径）",
        f"prior-3-month average YoY {mom['yoy3']:+.2f}%, this month {mom['decel']:+.2f}pp vs that (local DB basis)",
    )
    if mom.get("strong_decel"):
        note = T(
            "營收動能轉弱（強勢股大幅降速）：歷史上後 20 日相對落後約 1.08 個百分點（95% CI −1.83～−0.35，2019–2026 上市，n=2,194/5,224；僅 20 日單一期距，10 日跨零），但絕對報酬仍為正；持有中可下修信心，不得當作賣出理由；對買進篩選 5～20 日皆未證實，不得據此否決買進",
            "营收动能转弱（强势股大幅降速）：历史上后 20 日相对落后约 1.08 个百分点（95% CI −1.83～−0.35，2019–2026 上市，n=2,194/5,224；仅 20 日单一期距，10 日跨零），但绝对报酬仍为正；持有中可下修信心，不得当作卖出理由；对买进筛选 5～20 日皆未证实，不得据此否决买进",
            "Revenue momentum weakening (strong grower decelerating sharply): historically lagged by about 1.08pp over the next 20 days (95% CI -1.83 to -0.35, 2019-2026 TWSE, n=2,194/5,224; 20-day horizon only, 10-day crosses zero) while absolute returns stayed positive; while holding it may lower confidence but is not a sell reason; for buy screening it is unconfirmed at 5-20 days and must not veto a buy",
        )
    else:
        note = T("僅供參考，對買進篩選 5～20 日回測未證實", "仅供参考，对买进筛选 5～20 日回测未证实",
                 "For reference only, not confirmed by backtest for buy screening at 5-20 days")
    label = T(f"月營收動能（{mom['month']}）", f"月营收动能（{mom['month']}）",
              f"Monthly revenue momentum ({mom['month']})")
    return f"| {label} | {value} | {note} |\n"
