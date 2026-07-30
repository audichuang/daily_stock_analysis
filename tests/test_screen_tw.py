# -*- coding: utf-8 -*-
"""Tests for scripts.screen_tw 的純計算層（不碰 DB / 網路）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from screen_tw import compute_factors, tag  # noqa: E402


def _bars(closes, volume=1000, turnover=3e8):
    """把收盤價序列包成 compute_factors 需要的日 K DataFrame（high/low 各 ±1%）。"""
    return pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=len(closes), freq="D"),
        "open": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "close": closes,
        "volume": [volume] * len(closes),
        "turnover": [turnover] * len(closes),
    })


def test_moving_averages_and_returns():
    # 100, 101, ... 169：等差序列讓均線與報酬可手算
    f = compute_factors(_bars([100.0 + i for i in range(70)]))
    assert f["close"] == 169.0
    assert f["ma5"] == pytest.approx((165 + 166 + 167 + 168 + 169) / 5)
    assert f["ma20"] == pytest.approx(sum(range(150, 170)) / 20)
    assert f["d1"] == pytest.approx(169 / 168 - 1)
    assert f["d20"] == pytest.approx(169 / 149 - 1)
    assert f["bias20"] > 0  # 單調上漲必然正乖離


def test_position_and_drawdown_on_pullback():
    """先漲後跌：pos20 應落在低檔、from_hi60 應為負。"""
    closes = [100.0 + i for i in range(60)] + [159.0 - 2 * i for i in range(10)]
    f = compute_factors(_bars(closes))
    assert f["pos20"] < 0.2
    assert f["from_hi60"] < 0
    assert f["rsi14"] < 50


def test_vol_ratio_flags_volume_spike():
    df = _bars([100.0] * 70)
    df.loc[df.index[-1], "volume"] = 5000  # 末日爆量 5 倍
    assert compute_factors(df)["vol_ratio"] > 3


def _row(**kw):
    base = {
        "d1": 0.0, "d5": 0.0, "d20": 0.0, "bias20": 0.0, "rsi14": 50.0,
        "turnover20": 5e8, "dividend_yield": 1.0, "pb_ratio": 3.0, "pe_ratio": 20.0,
        "yoy": 0.0, "industry": "17", "margin_chg5": 0.0, "vol_ratio": 1.0,
    }
    return pd.Series({**base, **kw})


def test_tag_marks_daily_crash():
    """回歸守門：當日爆跌必須被標記，否則只看 20 日動能會把高位長黑股排到前面。"""
    assert "⚠⚠當日重挫爆量" in tag(_row(d1=-0.07, vol_ratio=2.0), market_d1=-0.01)
    assert "⚠⚠當日重挫" in tag(_row(d1=-0.07), market_d1=-0.01)
    assert not any("當日重挫" in t for t in tag(_row(d1=-0.02), market_d1=-0.01))


def test_tag_marks_semiconductor_linkage_and_thin_volume():
    t = tag(_row(industry="24", turnover20=5e7), market_d1=0.0)
    assert "⚠費半連動" in t
    assert "⚠量能薄" in t
    assert "⚠費半連動" not in tag(_row(industry="17"), market_d1=0.0)


def test_tag_counter_trend_is_relative_to_market():
    """個股 -1% 在大盤 -3% 的日子算抗跌，在大盤持平的日子不算。"""
    assert "逆勢抗跌" in tag(_row(d1=-0.01), market_d1=-0.03)
    assert "逆勢抗跌" not in tag(_row(d1=-0.01), market_d1=0.0)


def test_tag_marks_abnormal_pe():
    assert "⚠PE異常" in tag(_row(pe_ratio=450.0), market_d1=0.0)
    assert "⚠PE異常" in tag(_row(pe_ratio=-5.0), market_d1=0.0)
    assert "⚠PE異常" not in tag(_row(pe_ratio=15.0), market_d1=0.0)


def test_hi60_prior_excludes_recent_five_bars():
    """突破基準必須是**不含最近 5 天**的 60 日高——含最近 5 天的話今天必然是自己的高點。"""
    g = _bars([100.0] * 80)
    g.loc[g.index[-3], "high"] = 999.0            # 最近 3 天內的極高點不該進基準
    f = compute_factors(g)
    assert f["hi60_prior"] < 999.0
    # break_pct 以 hi60_prior 為分母
    assert f["break_pct"] == pytest.approx(f["close"] / f["hi60_prior"] - 1)


def test_vol_ratio5_is_five_over_sixty_day_average():
    g = _bars([100.0] * 80)
    g["volume"] = [1000.0] * 75 + [3000.0] * 5     # 最近 5 天量放大
    f = compute_factors(g)
    assert f["vol_ratio5"] > 2.0


def test_breakout_funnel_applies_volume_upper_bound():
    """量比有上限：四個分位單調遞減（1.3~1.5 命中 24.1% → >3 只有 18.1%），爆量是力竭。"""
    from screen_tw import BREAKOUT, funnel
    base = {
        "is_etf": False, "is_tib": False, "turnover20": 5e8, "close": 110.0,
        "hi60_prior": 100.0, "d5": 0.10, "yoy": 30.0, "pe_ratio": 15.0,
        "d1": 0.01, "d20": 0.10, "bias20": 0.05, "inst_5": 1.0,
    }
    df = pd.DataFrame([
        {**base, "stock_id": "AAA", "vol_ratio5": 1.5},   # 在區間內
        {**base, "stock_id": "BBB", "vol_ratio5": 5.0},   # 爆量,應被剔除
        {**base, "stock_id": "CCC", "vol_ratio5": 1.0},   # 量能不足,應被剔除
    ])
    pool, steps = funnel(df, 2e8, "breakout")
    assert list(pool["stock_id"]) == ["AAA"]
    assert BREAKOUT["vol_ratio5_max"] == 2.0


def test_momentum_score_survives_a_stale_valuation_table():
    """估值缺日不能讓整個 score 變 NaN——那會讓 `--top N` 靜默退化成「代號最小的 N 檔」。

    `valuation` 走 `BWIBBU_ALL`（無日期參數的當日快照），官方常盤後才發布，所以
    `date = as_of` 查到 0 列是常態；左 join 後 `pe_ratio` 整欄 NaN，而舊版
    `fillna(median())` 的 median 自己也是 NaN → rank 全 NaN → score 全 NaN。
    實測 2026-07-30 momentum 寬掃 5 檔全是 score=None、順序 1101/1102/1216/1402/1476。
    """
    from screen_tw import funnel
    base = {
        "is_etf": False, "is_tib": False, "turnover20": 5e8, "close": 110.0,
        "ma20": 105.0, "ma60": 100.0, "inst_5": 1.0, "bias20": 0.05,
        "hi60_prior": 100.0, "d5": 0.10, "vol_ratio5": 1.5, "yoy": 30.0,
        "pe_ratio": float("nan"),                      # 估值整欄缺
    }
    df = pd.DataFrame([
        {**base, "stock_id": "9999", "d20": 0.30, "d1": 0.03},   # 動能最強、代號最大
        {**base, "stock_id": "1101", "d20": 0.05, "d1": 0.00},   # 動能最弱、代號最小
    ])

    pool, _ = funnel(df, 2e8, "momentum")

    assert pool["score"].notna().all(), "估值缺日時 score 不得為 NaN"
    # 排序必須由其餘四項決定，不能退回代號序
    assert list(pool["stock_id"]) == ["9999", "1101"]


def test_pe_score_is_neutral_only_when_every_value_is_missing():
    from screen_tw import _pe_score

    allnan = _pe_score(pd.Series([float("nan")] * 3))
    assert (allnan == 0.5).all()
    # 有可用值時仍要低本益比得高分（且部分缺值走 median 補）
    partial = _pe_score(pd.Series([10.0, 50.0, float("nan")]))
    assert partial.iloc[0] > partial.iloc[1]
    assert partial.notna().all()


def test_breakout_funnel_requires_revenue_growth():
    """營收條件是唯一讓前瞻分布歪向右邊的東西——純價格突破是 16.4% 上 / 16.5% 下。"""
    from screen_tw import funnel
    base = {
        "is_etf": False, "is_tib": False, "turnover20": 5e8, "close": 110.0,
        "hi60_prior": 100.0, "d5": 0.10, "vol_ratio5": 1.5, "pe_ratio": 15.0,
        "d1": 0.01, "d20": 0.10, "bias20": 0.05, "inst_5": 1.0,
    }
    df = pd.DataFrame([
        {**base, "stock_id": "AAA", "yoy": 25.0},
        {**base, "stock_id": "BBB", "yoy": 5.0},
        {**base, "stock_id": "CCC", "yoy": float("nan")},   # 上櫃無月營收 → 篩掉
    ])
    pool, _ = funnel(df, 2e8, "breakout")
    assert list(pool["stock_id"]) == ["AAA"]
