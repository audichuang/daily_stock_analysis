"""回測讀取端都要套共用的月營收法定期限（market_data.revenue_deadline）。

DB 的 announce_date 是佔位「次月 10 日」：2020-01 營收展延到 2/15、2026 起保險類
（保守口徑 28xx）期限是 15 日，讀取端沒套就會在法定期限前「看到」還沒公布的營收。
每個讀取端各自的可見日語意不變，所以斷言寫成「該讀取端第一個看得到的交易日」：
- msf.pit_revenue_panel：公告日之後第一個交易日（嚴格 <）。
- backtest_screen._pit：forward 到交易日（含當日）再 shift(1)。
2020-02-15 是週六、2026-04-15 是週三、2026-04-10 是週五。
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import backtest_screen as bs  # noqa: E402
import measure_signal_forward as msf  # noqa: E402
from measure_revenue_momentum import (  # noqa: E402
    candidate_yoy_frame,
    correct_pit_dates,
    effective_announce,
)

SIDS = ["2881", "2330"]
DAYS = pd.bdate_range("2020-01-02", "2020-03-31").append(pd.bdate_range("2026-03-02", "2026-05-29"))

# DB 現況：彙總報表寫入的佔位公告日一律是次月 10 日
REV = pd.DataFrame({
    "stock_id": ["2881", "2330", "2881", "2330"],
    "revenue_month": pd.to_datetime(["2026-03-01", "2026-03-01", "2020-01-01", "2020-01-01"]),
    "date": pd.to_datetime(["2026-04-10", "2026-04-10", "2020-02-10", "2020-02-10"]),
    "yoy": [50.0, 30.0, 20.0, 25.0],
})


def _fake_read_sql(sql, con, params=None, parse_dates=None):
    q = str(sql)
    if "market.monthly_revenue" in q:
        cols = ["stock_id", "date", "yoy"] + (["revenue_month"] if "revenue_month" in q else [])
        return REV[cols].copy()
    if "market.price" in q:
        rows = [{"stock_id": s, "date": d, "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0,
                 "volume": 1000.0, "turnover": 1e9, "pe_ratio": 10.0} for d in DAYS for s in SIDS]
        return pd.DataFrame(rows)
    if "market.institutional" in q:
        return pd.DataFrame([{"stock_id": s, "date": d, "foreign_net": 0, "trust_net": 0,
                              "dealer_net": 0} for d in DAYS for s in SIDS])
    if "market.valuation" in q:
        return pd.DataFrame(columns=["stock_id", "date", "pb_ratio", "dividend_yield"])
    if "market.stock_info" in q:
        return pd.DataFrame({"stock_id": SIDS, "industry": ["金融", "半導體"], "name": ["富邦金", "台積電"]})
    raise AssertionError(q)


class _Engine:
    @contextmanager
    def connect(self):
        yield None


@pytest.fixture
def fake_db(monkeypatch):
    monkeypatch.setattr(pd, "read_sql", _fake_read_sql)
    half = lambda engine, idx, cols: pd.DataFrame(0.5, index=idx, columns=cols)  # noqa: E731
    monkeypatch.setattr(bs, "load_factors", half)
    monkeypatch.setattr(msf, "load_factors", half)


def _first_visible(panel, sid, after):
    s = panel[sid]
    s = s[(s.index > pd.Timestamp(after)) & s.notna()]
    return s.index[0].strftime("%Y-%m-%d")


def _assert_visibility(panel, *, fin_2026, gen_2026, gen_2020):
    assert _first_visible(panel, "2881", "2026-03-31") == fin_2026
    assert _first_visible(panel, "2330", "2026-03-31") == gen_2026
    assert _first_visible(panel, "2330", "2020-01-31") == gen_2020
    assert _first_visible(panel, "2881", "2020-01-31") == gen_2020


def test_measure_signal_forward_load_applies_deadline(fake_db):
    piv, rv, _ = msf.load(_Engine(), "2020-02-01", "2026-05-29", include_otc_revenue=True)
    panel = msf.pit_revenue_panel(rv, piv["close"].index, piv["close"].columns)
    assert pd.isna(panel.at[pd.Timestamp("2026-04-13"), "2881"])   # 富邦金 04-13 還看不到
    _assert_visibility(panel, fin_2026="2026-04-16", gen_2026="2026-04-13", gen_2020="2020-02-17")


def test_backtest_screen_load_applies_deadline(fake_db):
    piv, inst, val, rev = bs.load_panel(_Engine(), "2020-02-01", "2026-05-29", include_otc_revenue=True)
    ind = bs.build_indicators(piv["close"], piv["turnover"], inst, piv["pe_ratio"],
                              piv["high"], piv["low"], lag_days=1, val=val, rev=rev)
    panel = ind["rev_yoy"]
    assert pd.isna(panel.at[pd.Timestamp("2026-04-13"), "2881"])
    _assert_visibility(panel, fin_2026="2026-04-16", gen_2026="2026-04-13", gen_2020="2020-02-18")


def test_measure_revenue_momentum_readers_apply_deadline():
    idx, cols = DAYS, pd.Index(SIDS)
    # effective_announce（revenue_features 形狀，有 revenue_month）
    rv = REV.rename(columns={"date": "announce_date"})
    panel = msf.pit_revenue_panel(candidate_yoy_frame(effective_announce(rv)), idx, cols)
    _assert_visibility(panel, fin_2026="2026-04-16", gen_2026="2026-04-13", gen_2020="2020-02-17")
    # correct_pit_dates（measure_market_regime 走的路）：有無 revenue_month 欄都要對
    for frame in (REV, REV.drop(columns=["revenue_month"])):
        panel = msf.pit_revenue_panel(correct_pit_dates(frame), idx, cols)
        _assert_visibility(panel, fin_2026="2026-04-16", gen_2026="2026-04-13", gen_2020="2020-02-17")
