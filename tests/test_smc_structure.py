"""SMC 結構：用人工 K 線驗 ChoCH／BOS 的先後、FVG 回補與 Order Block 失效。"""

import pandas as pd

from src.services import smc_structure as smc


def _bars(closes, gap_at=None):
    """收盤序列 -> OHLC：開盤 = 前收，影線各 ±0.5。``gap_at`` 那根開高 3 點造缺口。"""
    rows, prev = [], closes[0]
    for i, c in enumerate(closes):
        o = prev + (3 if i == gap_at else 0)
        rows.append({"date": pd.Timestamp("2026-01-01") + pd.Timedelta(days=i),
                     "open": o, "high": max(o, c) + 0.5, "low": min(o, c) - 0.5, "close": c})
        prev = c
    return pd.DataFrame(rows)


# 上漲到 20 → 回檔到 14 → 突破 20 到 26（第一次多方 = ChoCH）→ 回檔 22 → 突破 26（BOS）
# → 一路跌破 22 的擺動低點（空方 ChoCH）
_UP = [10, 12, 14, 16, 18, 20, 19, 17, 15, 14, 15, 17, 19, 21, 23, 26, 25, 24, 23, 22,
       23, 25, 27, 29, 30, 29, 27, 25, 23, 21, 19, 18]


def test_first_break_is_choch_then_bos_then_bearish_choch():
    kinds = [(e["kind"], e["direction"]) for e in smc.structure_events(_bars(_UP), n=2)]
    assert kinds[:3] == [("CHOCH", "bullish"), ("BOS", "bullish"), ("CHOCH", "bearish")]


def test_breaks_need_a_close_beyond_the_swing_not_just_a_wick():
    df = _bars(_UP)
    ev = smc.structure_events(df, n=2)[0]
    assert df["close"].iloc[ev["i"]] > ev["level"]
    assert all(df["close"].iloc[k] <= ev["level"] for k in range(ev["swing_i"] + 1, ev["i"]))


def test_a_wick_above_the_swing_high_without_a_close_is_not_a_break():
    closes = [10, 12, 14, 16, 18, 20, 19, 17, 15, 14, 15, 17, 19, 18, 17, 16]
    df = _bars(closes)
    df.loc[12, "high"] = 25          # 第 12 根影線刺破 20.5 的擺動高點，收盤 19 沒站上
    assert [e for e in smc.structure_events(df, n=2) if e["direction"] == "bullish"] == []


def test_unfilled_bullish_fvg_is_reported_and_filled_one_is_not():
    closes = [10, 11, 12, 16, 17, 18, 19]
    df = _bars(closes, gap_at=3)
    gaps = smc.fair_value_gaps(df)
    assert any(g["direction"] == "bullish" for g in gaps)
    # 之後跌回缺口下緣以下 = 回補完畢
    filled = smc.fair_value_gaps(_bars(closes + [15, 11], gap_at=3))
    assert not any(g["date"] == gaps[0]["date"] for g in filled)


def test_analyze_reports_fib_zone_and_invalidates_broken_order_blocks():
    out = smc.analyze(_bars(_UP), n=2)
    assert out["last_event"]["direction"] == "bearish"
    fib = out["fib"]
    assert fib["range_low"] < out["price"] < fib["range_high"]
    assert fib["zone"] == ("premium" if fib["position"] > 0.5 else "discount")
    # 多方 OB 在之後的跌勢中被收盤跌破，不應留在輸出
    assert not any(ob["direction"] == "bullish" and out["price"] < ob["low"] for ob in out["order_blocks"])


def test_anchor_ignores_swings_not_yet_confirmed_at_the_event():
    ev = {"i": 10, "direction": "bullish"}
    # n=2：低點 9 要到第 11 根才確認，事件在第 10 根時還不能用；低點 5 在第 7 根已確認
    assert smc._last_anchor(ev, lows=[5, 9], highs=[], n=2) == 5
    assert smc._last_anchor(ev, lows=[5, 8], highs=[], n=2) == 8      # 8 + 2 = 10，當天剛確認可用
    assert smc._last_anchor({"i": 10, "direction": "bearish"}, lows=[], highs=[9], n=2) is None


def test_too_short_series_returns_none():
    assert smc.analyze(_bars([1, 2, 3, 4]), n=3) is None
