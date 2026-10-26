# -*- coding: utf-8 -*-
"""Tests for scripts/measure_signal_forward.py 的前瞻報酬與事件去重（不碰 DB／網路）。

只測會讓整份量測失效的兩件事：右端截斷有沒有被當成真報酬、事件去重有沒有把同一件事
算成多個樣本。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from measure_signal_forward import (  # noqa: E402
    DEFAULT_POSITION_NOTIONAL,
    block_bootstrap,
    forward_returns,
    hit_rate_bootstrap,
    paired_block_bootstrap,
    pit_revenue_panel,
    to_events,
)
from tw_trade_costs import round_trip_return  # noqa: E402


def test_measurement_filters_every_panel_with_the_shared_universe(monkeypatch):
    import measure_signal_forward as msf
    from market_data.adjust import is_common_stock

    codes = ["2330", "6488", "5305", "9802", "9904", "9921", "9105", "912000",
             "00878", "0050", "00631L", "2887A", "70001"]
    days = pd.bdate_range("2026-01-01", periods=3)
    panel = pd.DataFrame(100.0, index=days, columns=codes)
    piv = {k: panel.copy() for k in ("open", "high", "close", "volume", "turnover")}
    monkeypatch.setattr(msf, "get_engine", lambda: object())
    monkeypatch.setattr(msf, "load", lambda *a: (piv, pd.DataFrame(), pd.DataFrame()))
    seen = []
    captured = {}

    def checked(sid):
        seen.append(sid)
        return is_common_stock(sid)

    class PanelsCaptured(Exception):
        pass

    def capture(filtered, yoy, *args):
        captured.update(filtered)
        captured["yoy"] = yoy
        raise PanelsCaptured

    # 先釘住腳本綁的就是共用謂詞；否則下面的 spy 會蓋掉錯誤的本地綁定，守門形同虛設。
    assert msf.is_common_stock is is_common_stock
    monkeypatch.setattr(msf, "is_common_stock", checked)
    monkeypatch.setattr(msf, "build_signals", capture)
    with pytest.raises(PanelsCaptured):
        msf.main([])

    assert seen == codes
    assert set(captured) == {*piv, "yoy"}
    for value in captured.values():
        assert value.columns.tolist() == ["2330", "6488", "5305", "9802", "9904", "9921"]


def _piv(n_days=20, price=100.0):
    days = pd.bdate_range("2026-01-01", periods=n_days)
    cols = pd.Index(["1111", "2222"])
    close = pd.DataFrame({c: [price + i for i in range(n_days)] for c in cols}, index=days)
    return {"close": close, "open": close.copy(), "high": close.copy(),
            "volume": close * 0 + 1000, "turnover": close * 0 + 3e8}


def test_right_censored_signals_return_nan_not_a_settled_price():
    """樣本最後 h 天的訊號報酬是**未知**，不能拿不足 h 天的報酬冒充。

    這是實際踩過的 bug：把右端截斷與真下市混在一起處理，2.5 年樣本裡有 409 筆被
    捏造報酬，而樣本末端的訊號往往落在同一波行情，會整批偏向同一方向。
    """
    piv = _piv(n_days=20)
    h = 5
    ret, delisted = forward_returns(piv, h, "last")
    # 最後 h 列的 T+h 超出面板 → 全 NaN
    assert ret.iloc[-h:].isna().all().all()
    assert ret.iloc[:-h].notna().all().all()
    assert not delisted.any().any()          # 沒有任何真下市


def test_delisting_within_horizon_is_settled_not_dropped():
    """真下市要結算——丟掉等於把最壞的結果排除在分布外。"""
    piv = _piv(n_days=20)
    piv["close"].iloc[10:, 0] = float("nan")     # 1111 第 11 天起停止交易
    piv["open"].iloc[10:, 0] = float("nan")
    h = 5
    last, dl = forward_returns(piv, h, "last")
    zero, _ = forward_returns(piv, h, "zero")
    # 第 6~9 列（T+5 落在停牌後、但面板還有更晚的日期）要被判定為下市並結算
    assert dl.iloc[5:10, 0].any()
    hit = dl.iloc[:, 0].idxmax()
    assert pd.notna(last.at[hit, "1111"])
    assert zero.at[hit, "1111"] == pytest.approx(-1.0)      # -100%
    assert last.at[hit, "1111"] > zero.at[hit, "1111"]      # 最後成交價比歸零樂觀


def test_events_dedupe_consecutive_triggers_of_same_stock():
    """同一檔在 h 個交易日內連續觸發是同一個事件，不是多個樣本。"""
    piv = _piv(n_days=40)
    ret, _ = forward_returns(piv, 5, "last")
    sig = pd.DataFrame(False, index=piv["close"].index, columns=piv["close"].columns)
    sig.iloc[10:14, 0] = True        # 1111 連續 4 天觸發 → 1 個事件
    sig.iloc[30, 0] = True           # 相隔 >5 個交易日 → 第 2 個事件
    sig.iloc[10, 1] = True           # 2222 獨立 1 個事件
    raw, ev = to_events(sig, ret, 5, {})
    assert len(raw) == 6
    assert len(ev) == 3
    assert list(ev[ev["stock_id"] == "1111"]["ti"]) == [10, 30]


def test_events_use_exact_buy_and_sell_cashflows():
    piv = _piv(n_days=20)
    ret, _ = forward_returns(piv, 5, "last")
    sig = pd.DataFrame(False, index=piv["close"].index, columns=piv["close"].columns)
    sig.iloc[3, 0] = True
    raw, _ = to_events(sig, ret, 5, {})
    expected = round_trip_return(
        1.0, 1.0 + ret.iloc[3, 0], entry_notional=DEFAULT_POSITION_NOTIONAL
    )
    assert raw["r"].iloc[0] == pytest.approx(expected)


def test_paired_bootstrap_identical_arms_have_exact_zero_interval():
    calendar = pd.bdate_range("2026-01-05", periods=12)
    events = pd.DataFrame({
        "date": [calendar[1], calendar[1], calendar[8], calendar[8]],
        "diff": [0.0, 0.0, 0.0, 0.0],
    })

    assert paired_block_bootstrap(
        events, calendar, n=200, block=3, seed=7
    ) == (0.0, 0.0)


def test_paired_bootstrap_is_inconclusive_when_events_fit_in_one_block():
    calendar = pd.bdate_range("2026-01-05", periods=20)
    events = pd.DataFrame({
        "date": [calendar[2], calendar[4]],
        "diff": [0.1, -0.2],
    })

    assert paired_block_bootstrap(
        events, calendar, n=200, block=5, seed=7
    ) is None


def test_paired_bootstrap_keeps_the_same_day_cross_section_together():
    calendar = pd.bdate_range("2026-01-05", periods=24)
    events = pd.DataFrame({
        "date": [calendar[1], calendar[1], calendar[18], calendar[18]],
        "diff": [0.3, -0.3, 0.8, -0.8],
    })

    assert paired_block_bootstrap(
        events, calendar, n=200, block=5, seed=11
    ) == pytest.approx((0.0, 0.0), abs=1e-15)


def test_paired_bootstrap_drops_unmatched_rows_instead_of_filling_zero():
    calendar = pd.bdate_range("2026-01-05", periods=24)
    events = pd.DataFrame({
        "date": [calendar[1], calendar[1], calendar[18], calendar[18]],
        "diff": [0.5, float("nan"), 0.5, float("nan")],
    })

    assert paired_block_bootstrap(
        events, calendar, n=200, block=5, seed=11
    ) == pytest.approx((0.5, 0.5))


def test_paired_bootstrap_seed_is_reproducible():
    calendar = pd.bdate_range("2026-01-05", periods=30)
    events = pd.DataFrame({
        "date": [calendar[1], calendar[1], calendar[12], calendar[25]],
        "diff": [0.4, -0.2, -0.3, 0.2],
    })

    first = paired_block_bootstrap(events, calendar, n=200, block=5, seed=19)
    second = paired_block_bootstrap(events, calendar, n=200, block=5, seed=19)

    assert first == second


def test_existing_bootstrap_report_is_inconclusive_when_blocks_are_insufficient():
    events = pd.DataFrame({
        "ti": [2, 4],
        "r": [0.1, -0.2],
    })

    assert block_bootstrap(
        events, range(20), n=200, block=5, seed=7
    ) is None


def test_existing_bootstrap_report_uses_ti_when_event_frame_also_has_date():
    events = pd.DataFrame({
        "date": pd.to_datetime(["2026-01-07", "2026-01-26"]),
        "ti": [2, 15],
        "stock_id": ["1111", "2222"],
        "r": [0.1, -0.2],
    })

    result = block_bootstrap(events, range(20), n=200, block=5, seed=7)

    assert result is not None


def _hit_events(r):
    return pd.DataFrame({
        "date": pd.to_datetime(["2026-01-06", "2026-01-06", "2026-01-26", "2026-01-26"]),
        "ti": [1, 1, 15, 15],
        "stock_id": ["1111", "2222", "3333", "4444"],
        "r": [r] * 4,
    })


def test_hit_rate_bootstrap_counts_exactly_thirty_percent_as_a_hit():
    """錨點是「淨報酬 ≥ +30%」的機率：區間要落在命中率（0~1）上，不是報酬均值。"""
    assert hit_rate_bootstrap(
        _hit_events(0.30), range(20), n=200, block=5, seed=7
    ) == pytest.approx((1.0, 1.0))


def test_hit_rate_bootstrap_does_not_count_returns_below_thirty_percent():
    assert hit_rate_bootstrap(
        _hit_events(0.2999), range(20), n=200, block=5, seed=7
    ) == (0.0, 0.0)


def test_hit_rate_bootstrap_is_inconclusive_when_blocks_are_insufficient():
    events = pd.DataFrame({"ti": [2, 4], "r": [0.5, 0.1]})

    assert hit_rate_bootstrap(events, range(20), n=200, block=5, seed=7) is None


def test_revenue_announcement_on_non_trading_day_is_visible_next_trading_day():
    """週六公告在 live 的週一就看得到（SQL 是 `announce_date < as_of`），量測不能晚一天。

    舊版「forward 到週一再 shift(1)」讓它變成週二才可見，與 live 差一天。
    """
    days = pd.bdate_range("2026-01-05", periods=10)          # 週一起算的營業日
    rv = pd.DataFrame({"stock_id": ["1111"], "date": [pd.Timestamp("2026-01-10")],
                       "yoy": [35.0]})                        # 2026-01-10 是週六
    panel = pit_revenue_panel(rv, days, pd.Index(["1111"]))
    assert panel.loc[pd.Timestamp("2026-01-12"), "1111"] == 35.0      # 週一
    assert pd.isna(panel.loc[pd.Timestamp("2026-01-09"), "1111"])     # 公告前不可見


def test_revenue_visible_on_announce_day_itself_would_be_lookahead():
    """公告日當天不可見——live 是嚴格 `announce_date < as_of`（盤中才公告）。"""
    days = pd.bdate_range("2026-01-05", periods=10)
    rv = pd.DataFrame({"stock_id": ["1111"], "date": [pd.Timestamp("2026-01-07")],
                       "yoy": [35.0]})                        # 週三，本身是交易日
    panel = pit_revenue_panel(rv, days, pd.Index(["1111"]))
    assert pd.isna(panel.loc[pd.Timestamp("2026-01-07"), "1111"])
    assert panel.loc[pd.Timestamp("2026-01-08"), "1111"] == 35.0


def test_revenue_staleness_is_calendar_days_not_trading_rows():
    """保鮮期 45 天是**曆日**：`ffill(limit=45)` 數交易列約等於 63 個曆日,會多看 18 天。"""
    days = pd.bdate_range("2026-01-05", periods=60)
    rv = pd.DataFrame({"stock_id": ["1111"], "date": [pd.Timestamp("2026-01-06")],
                       "yoy": [35.0]})
    panel = pit_revenue_panel(rv, days, pd.Index(["1111"]))
    v = panel["1111"]
    assert v.loc[pd.Timestamp("2026-02-19")] == 35.0     # 公告後 44 天
    assert pd.isna(v.loc[pd.Timestamp("2026-02-23")])    # 公告後 48 天 → 過期
    assert int(v.notna().sum()) < 45                     # 交易列口徑會給 45 列


def test_hi60_prior_matches_live_screen_definition():
    """量測與 live 的突破基準必須逐格相同，否則量到的不是會下單的訊號。

    live 是 `high.iloc[-66:-5]`＝61 根、視窗 t-65…t-5。舊版量測寫 `shift(6).rolling(55)`
    是 55 根 t-60…t-6，多排除一根、視窗也短 6 根（實測 918→894 事件、只有 859 重疊）。
    """
    import numpy as np
    from screen_tw import compute_factors

    n = 90
    # 把最高點刻意放在 t-5：live 的視窗含它、舊的錯誤公式（到 t-6）不含,兩者才會不同。
    closes = [100.0 + (i % 7) for i in range(n)]
    closes[n - 1 - 5] = 500.0
    g = pd.DataFrame({
        "date": pd.bdate_range("2026-01-01", periods=n),
        "open": closes, "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes], "close": closes,
        "volume": [1000.0] * n, "turnover": [3e8] * n,
    })
    g["high"] = [c * 1.01 for c in closes]
    live = compute_factors(g)["hi60_prior"]
    high = pd.DataFrame({"X": g["high"].to_numpy()}, index=g["date"])
    panel = high.shift(5).rolling(61).max().iloc[-1]["X"]
    assert panel == pytest.approx(live)
    # 舊的錯誤公式必須真的不同，否則這個測試沒有鑑別力
    assert high.shift(6).rolling(55).max().iloc[-1]["X"] != pytest.approx(live)
    _ = np


def test_events_dedupe_compares_against_last_kept_event():
    """去重是「與上一個**保留的事件**相隔 > h」，不是與上一個名目訊號相隔 > h。

    0/50/100 日、h=60：第 100 日與已保留的第 0 日相隔 100 > 60，是新事件。用 diff() 比
    名目訊號的話（100-50=50）會被吃掉（實測差別 918 vs 1,003 個事件）。
    """
    piv = _piv(n_days=200)
    ret, _ = forward_returns(piv, 60, "last")
    sig = pd.DataFrame(False, index=piv["close"].index, columns=piv["close"].columns)
    for i in (0, 50, 100):
        sig.iloc[i, 0] = True
    _, ev = to_events(sig, ret, 60, {})
    assert list(ev["ti"]) == [0, 100]


def test_single_day_suspension_is_not_treated_as_delisting():
    """單日暫停交易之後復牌，不能用最後成交價結算——那會低估。"""
    piv = _piv(n_days=30)
    piv["close"].iloc[10, 0] = float("nan")      # 只缺一天，之後照常
    h = 5
    ret, delisted = forward_returns(piv, h, "last")
    assert not delisted.iloc[:, 0].any()
    assert pd.isna(ret.iloc[5, 0])               # T+5 剛好落在缺價日 → 報酬未知
