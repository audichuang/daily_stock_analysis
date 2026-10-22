"""台股回測脈絡區塊：大盤狀態／月營收動能的純計算、停更判斷、prompt 用字與台股限定。"""

import copy
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    from tests.litellm_stub import ensure_litellm_stub

    ensure_litellm_stub()

from src.analyzer import GeminiAnalyzer
from src.services.tw_backtest_context import (
    format_regime_block,
    format_revenue_momentum_row,
    latest_regime,
    latest_revenue_momentum,
)
from tests.test_analyzer_prompt_language import _make_analyzer, _rich_context

UNPROVEN = "僅供參考，回測未證實"


def _panel(n=100, breadth_up=0.1):
    """100 個交易日、10 檔流動股；最後一天只有 breadth_up 比例的股票收在均線之上。"""
    idx = pd.bdate_range("2026-05-01", periods=n)
    cols = [f"{1000 + i}" for i in range(10)]
    close = pd.DataFrame(100.0, index=idx, columns=cols)
    k = int(round(breadth_up * len(cols)))
    close.iloc[-1, :k] = 120.0
    close.iloc[-1, k:] = 80.0
    turnover = pd.DataFrame(3e8, index=idx, columns=cols)
    proxy = pd.Series(np.linspace(100, 200, n), index=idx)
    return proxy, close, turnover, idx


def test_latest_regime_flags_and_breadth():
    proxy, close, turnover, idx = _panel(breadth_up=0.1)
    r = latest_regime(proxy, close, turnover, idx[-1].date())
    assert r["above_ma60"] is True and r["ma60_up"] is True
    assert np.isclose(r["breadth20"], 0.1) and np.isclose(r["breadth60"], 0.1)


def test_illiquid_stocks_excluded_from_breadth():
    proxy, close, turnover, idx = _panel(breadth_up=0.1)
    turnover.iloc[:, 1:] = 1e7  # 只剩第一檔流動，它收在均線之上
    r = latest_regime(proxy, close, turnover, idx[-1].date())
    assert np.isclose(r["breadth20"], 1.0)


def test_regime_stale_when_prices_stop_before_expected_session():
    proxy, close, turnover, idx = _panel()
    r = latest_regime(proxy, close, turnover, (idx[-1] + pd.Timedelta(days=3)).date())
    assert r == {"as_of": idx[-1].date(), "stale_expected": (idx[-1] + pd.Timedelta(days=3)).date()}
    assert "不提供大盤狀態" in format_regime_block(r, "zh-TW")
    # 當天就是應到日：照常給狀態
    assert "stale_expected" not in latest_regime(proxy, close, turnover, idx[-1].date())


def test_regime_without_reference_session_is_rejected():
    proxy, close, turnover, _ = _panel()
    assert latest_regime(proxy, close, turnover, None) is None


def _regime(b20, b60):
    return {"as_of": date(2026, 10, 21), "above_ma60": True, "ma60_up": False,
            "breadth20": b20, "breadth60": b60}


def test_regime_wording_follows_ci():
    oversold = format_regime_block(_regime(0.15, 0.3), "zh-TW")
    assert "極端超賣" in oversold and "+0.51%～+2.21%" in oversold
    assert "不得據此否決買進" in oversold
    assert "寬度60>50%" not in oversold
    # 趨勢類狀態一律標未證實，不能帶 CI 數字
    trend_line = next(x for x in oversold.splitlines() if "季線" in x and "0050" in x)
    assert "僅供參考，3～5 日回測未證實" in trend_line and "CI" not in trend_line
    wide = format_regime_block(_regime(0.6, 0.7), "zh-TW")
    assert "寬度高不是買進確認" in wide and "極端超賣" not in wide
    assert f"寬度20>50%：{UNPROVEN}" in wide
    mid = format_regime_block(_regime(0.4, 0.4), "zh-TW")
    assert "極端超賣" not in mid and "寬度60>50%" not in mid
    for text in (oversold, wide, mid):
        assert "CI 全部跨零" in text and "不是否決個股買進或扣分的理由" in text


def test_regime_english_has_no_cjk():
    out = format_regime_block(_regime(0.15, 0.7), "en")
    assert out and not any("一" <= ch <= "鿿" for ch in out)


def _rv(yoys, start="2025-01-01", drop=()):
    months = pd.date_range(start, periods=len(yoys), freq="MS")
    df = pd.DataFrame({"stock_id": "1234", "revenue_month": months, "revenue": 100.0,
                       "yoy": yoys, "mom": 0.0,
                       "announce_date": months + pd.DateOffset(months=1) + pd.Timedelta(days=9)})
    return df.drop(index=list(drop)).reset_index(drop=True)


def test_strong_grower_sharp_deceleration_flagged():
    m = latest_revenue_momentum(_rv([40, 50, 60, 20]), "2025-04-01")
    assert np.isclose(m["yoy3"], 50) and np.isclose(m["decel"], -30)
    assert m["strong_decel"] is True
    row = format_revenue_momentum_row(m, "zh-TW")
    assert "−1.83～−0.35" in row and "單一期距" in row and "不得當作賣出理由" in row and "不得據此否決買進" in row


def test_weak_grower_or_mild_deceleration_is_unproven():
    # 前 3 月平均 10%（非強勢股），降速 30pp 也只算資訊
    weak = latest_revenue_momentum(_rv([0, 10, 20, -20]), "2025-04-01")
    assert weak["strong_decel"] is False
    # 強勢股降速 19pp：未達門檻
    mild = latest_revenue_momentum(_rv([40, 50, 60, 31]), "2025-04-01")
    assert mild["strong_decel"] is False
    for m in (weak, mild):
        row = format_revenue_momentum_row(m, "zh-TW")
        assert "僅供參考，對買進篩選 5～20 日回測未證實" in row and "CI" not in row


def test_revenue_requires_anchor_month_and_contiguous_history():
    rv = _rv([40, 50, 60, 20])
    assert latest_revenue_momentum(rv, "2025-05-01") is None  # 本地還沒到官方最新月份
    # 中間缺一個月：前 3 月平均算不出來，不能把隔月當上個月
    assert latest_revenue_momentum(_rv([40, 50, 60, 70, 20], drop=(2,)), "2025-05-01") is None
    assert latest_revenue_momentum(_rv([60, 20]), "2025-02-01") is None


_CFG = SimpleNamespace(news_max_age_days=3, news_strategy_profile="short")


def _prompt(code):
    ctx = copy.deepcopy(_rich_context())
    ctx["code"] = code
    ctx["fundamental_context"]["growth"] = {"data": {
        "monthly_revenue": 5e9, "monthly_revenue_yoy": 20.0, "revenue_month_iso": "2026-09"}}
    mom = {"month": "2026-09", "yoy": 20.0, "yoy3": 50.0, "decel": -30.0, "strong_decel": True}
    with patch("src.analyzer.get_config", return_value=_CFG), \
            patch.object(GeminiAnalyzer, "_tw_institutional_trend_lines", return_value=""), \
            patch.object(GeminiAnalyzer, "_tw_margin_lines", return_value=""), \
            patch("src.analyzer.load_tw_regime", return_value=_regime(0.4, 0.7)) as reg, \
            patch("src.analyzer.load_tw_revenue_momentum", return_value=mom) as rev:
        out = _make_analyzer(legacy=True)._format_prompt(ctx, "X", news_context="n", report_language="zh-TW")
    return out, reg, rev


def test_prompt_includes_blocks_for_tw_only():
    tw, reg, rev = _prompt("2330.TW")
    assert "### 大盤狀態（本地行情計算" in tw and "| 月營收動能（2026-09） |" in tw
    rev.assert_called_once_with("2330.TW", "2026-09")
    us, reg, rev = _prompt("AAPL")
    assert "大盤狀態（本地行情計算" not in us and "月營收動能" not in us
    reg.assert_not_called()
    rev.assert_not_called()


def test_regime_accepts_prices_newer_than_expected_session():
    # 盤後跑時本地已有今天行情（as_of > 應到日）：不是停更，照常給狀態
    proxy, close, turnover, idx = _panel()
    assert "stale_expected" not in latest_regime(proxy, close, turnover, idx[-2].date())


def test_expected_prev_session_is_strictly_before_today():
    from src.services.tw_backtest_context import _expected_prev_session

    sessions = pd.DatetimeIndex(["2026-10-20", "2026-10-21", "2026-10-22"])
    with patch("src.core.trading_calendar.get_trading_dates", return_value=sessions):
        # 07:30 盤前：今天的行情還不可能在庫，應到日是昨天
        assert _expected_prev_session(date(2026, 10, 22)) == date(2026, 10, 21)
    with patch("src.core.trading_calendar.get_trading_dates", return_value=None):
        assert _expected_prev_session(date(2026, 10, 22)) is None
