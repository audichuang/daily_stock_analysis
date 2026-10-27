# -*- coding: utf-8 -*-
"""事件前一日延後進場研究（`scripts/research_pre_event_delay.py`）的純函式測試，不碰 DB／網路。"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from research_pre_event_delay import (  # noqa: E402
    clean_release_dates,
    delayed_arm_returns,
    parse_alfred_dates,
    parse_fed_historical,
    pre_event_context,
    pre_event_sessions,
    pre_event_verdict,
    set_session_read_only,
    tightening_flags,
    trade_max_drawdown,
)
from tw_trade_costs import round_trip_return  # noqa: E402

# 2026-03-02（一）起 15 個台股交易日，03-11（三）當成休市日拿掉
DAYS = pd.bdate_range("2026-03-02", periods=16).delete(7)
D = lambda s: datetime.date.fromisoformat(s)  # noqa: E731


def _pos(day):
    return int(DAYS.get_loc(pd.Timestamp(day)))


# ── 事件前一個台股交易日 T 的對齊 ────────────────────────────────────


def test_release_on_trading_day_maps_to_that_day():
    """CPI 03-10（二）20:30 台北公布：03-10 收盤時還沒公布，T＝03-10 本身。"""
    t_map = pre_event_sessions(DAYS, {"cpi": [D("2026-03-10")]})
    assert t_map == {_pos("2026-03-10"): {"cpi"}}


def test_fomc_us_date_maps_to_same_taipei_session():
    """FOMC 03-18（三）14:00 ET＝台北 03-19 02:00：T 仍是 03-18（台北日期加一天不能再往後挪）。"""
    t_map = pre_event_sessions(DAYS, {"fomc": [D("2026-03-18")]})
    assert t_map == {_pos("2026-03-18"): {"fomc"}}


def test_release_on_taiwan_holiday_moves_to_previous_session():
    t_map = pre_event_sessions(DAYS, {"nfp": [D("2026-03-11")]})
    assert t_map == {_pos("2026-03-10"): {"nfp"}}


def test_release_on_weekend_moves_to_friday():
    t_map = pre_event_sessions(DAYS, {"nfp": [D("2026-03-07")]})
    assert t_map == {_pos("2026-03-06"): {"nfp"}}


def test_two_events_same_session_merge_types():
    t_map = pre_event_sessions(DAYS, {"cpi": [D("2026-03-10")], "fomc": [D("2026-03-11")]})
    assert t_map == {_pos("2026-03-10"): {"cpi", "fomc"}}


def test_release_without_next_session_or_before_panel_is_skipped():
    t_map = pre_event_sessions(DAYS, {"cpi": [D("2026-02-27"), DAYS[-1].date()]})
    assert t_map == {}


def _ev(tis, stock="1111"):
    return pd.DataFrame({"stock_id": [stock] * len(tis), "ti": tis,
                         "date": [DAYS[t] for t in tis], "r": [0.0] * len(tis)})


def test_signal_day_before_t_is_affected_and_delay_uses_t_as_signal_day():
    """訊號日 D 的下一個交易日＝T（正常臂在 T 開盤進場、抱著事件）才受影響；延後臂以 T 為訊號日。"""
    t = _pos("2026-03-10")
    ctx = pre_event_context(_ev([t - 2, t - 1, t]), {t: {"cpi"}})
    assert ctx["affected"].tolist() == [False, True, False]
    assert ctx.at[1, "t_idx"] == t
    assert ctx.at[1, "types"] == "cpi"


def test_c8_flag_marks_restriction_window_without_excluding():
    days = pd.DatetimeIndex(["2025-04-03", "2025-04-07", "2025-05-23", "2025-05-26"])
    ev = pd.DataFrame({"stock_id": ["1111"] * 4, "ti": [0, 1, 2, 3], "date": days, "r": 0.0})
    ctx = pre_event_context(ev, {2: {"cpi"}, 3: {"cpi"}, 4: {"nfp"}})
    assert ctx["c8"].tolist() == [False, True, True, False]
    assert ctx["affected"].tolist() == [False, True, True, True]


def test_delayed_arm_reads_return_at_t_row_net_of_cost():
    t = _pos("2026-03-10")
    ret = pd.DataFrame(np.nan, index=DAYS, columns=["1111"])
    ret.iloc[t - 1, 0] = 0.10    # 正常臂（不該被讀到）
    ret.iloc[t, 0] = 0.20        # 延後臂：T 當訊號日 → T+1 開盤進場
    ret.iloc[t + 1, 0] = 0.30    # 延後兩天（不該被讀到）
    ev = _ev([t - 1])
    ctx = pre_event_context(ev, {t: {"cpi"}})
    arm = delayed_arm_returns(ev, ctx, ret)
    assert arm.iloc[0] == pytest.approx(round_trip_return(1.0, 1.20, entry_notional=200_000.0))


def test_delayed_arm_censored_is_nan():
    t = _pos("2026-03-10")
    ret = pd.DataFrame(np.nan, index=DAYS, columns=["1111"])
    ev = _ev([t - 1])
    arm = delayed_arm_returns(ev, pre_event_context(ev, {t: {"cpi"}}), ret)
    assert arm.isna().all()


# ── 事件日來源 ────────────────────────────────────────────────────────


ALFRED_FIXTURE = """Release: Consumer Price Index
-------------------------------  ---------------  ----------
Name                             Real Time Start  Period End
Consumer Price Index             1955-05-06       2026-10-02
2024-01-11
2024-02-09
2024-02-13
2024-03-12
"""


def test_parse_alfred_dates_takes_only_bare_date_rows():
    assert parse_alfred_dates(ALFRED_FIXTURE) == [D("2024-01-11"), D("2024-02-09"),
                                                  D("2024-02-13"), D("2024-03-12")]


def test_parse_alfred_dates_raises_on_empty():
    with pytest.raises(ValueError):
        parse_alfred_dates("Release: x\nName  Real Time Start\n")


def test_cpi_keeps_last_date_of_month_and_drops_seasonal_revision():
    kept, dropped = clean_release_dates(parse_alfred_dates(ALFRED_FIXTURE), "last")
    assert kept == [D("2024-01-11"), D("2024-02-13"), D("2024-03-12")]
    assert dropped == [D("2024-02-09")]


def test_nfp_keeps_first_date_of_month_and_drops_benchmark_preview():
    kept, dropped = clean_release_dates([D("2024-08-02"), D("2024-08-21"), D("2024-09-06")], "first")
    assert kept == [D("2024-08-02"), D("2024-09-06")]
    assert dropped == [D("2024-08-21")]


FED_HIST_FIXTURE = """
<h5 class="panel-heading panel-heading--shaded">January 28-29 Meeting - 2020</h5>
<h5 class="panel-heading panel-heading--shaded">March 2 (unscheduled) Meeting - 2020</h5>
<h5 class="panel-heading panel-heading--shaded">March 15 (unscheduled) Meeting - 2020</h5>
<h5 class="panel-heading panel-heading--shaded">March 17-18 (cancelled) Meeting - 2020</h5>
<h5 class="panel-heading panel-heading--shaded">November 4-5 Meeting - 2020</h5>
"""


def test_fed_historical_keeps_scheduled_meetings_last_day_only():
    assert parse_fed_historical(FED_HIST_FIXTURE) == [D("2020-01-29"), D("2020-11-05")]


# ── 大局緊縮日 ────────────────────────────────────────────────────────


def _macro(chg_sign, dates):
    rows = []
    for sid, sign in chg_sign.items():
        for i, d in enumerate(dates):
            rows.append({"series_id": sid, "date": d, "value": 100.0 + sign * i})
    return pd.DataFrame(rows)


def test_tightening_needs_all_three_up_and_only_prior_us_dates():
    us = pd.bdate_range("2026-01-01", periods=30)
    sessions = pd.DatetimeIndex([us[19], us[20], us[21]])
    up = _macro({"FRED:DGS10": 1, "BZ=F": 1, "DX-Y.NYB": 1}, us)
    # us[19] 盤前只看得到 us[18]（20 日變化還算不出來）；us[20] 看得到 us[19]（同樣算不出來）；
    # us[21] 看得到 us[20]（第一個有 20 日變化的觀測）
    assert tightening_flags(up, sessions).tolist() == [False, False, True]
    one_down = _macro({"FRED:DGS10": 1, "BZ=F": -1, "DX-Y.NYB": 1}, us)
    assert not tightening_flags(one_down, sessions).any()


def test_tightening_missing_series_is_false():
    us = pd.bdate_range("2026-01-01", periods=30)
    two = _macro({"FRED:DGS10": 1, "BZ=F": 1}, us)
    assert not tightening_flags(two, pd.DatetimeIndex([us[25]])).any()


def test_tightening_flat_twenty_day_change_is_false():
    # DGS10 只到小數兩位，20 日持平常見；持平不是緊縮
    us = pd.bdate_range("2026-01-01", periods=30)
    flat = _macro({"FRED:DGS10": 0, "BZ=F": 1, "DX-Y.NYB": 1}, us)
    assert not tightening_flags(flat, pd.DatetimeIndex([us[25]])).any()
    # 反向：小數兩位的最小上升（4.00→4.01）仍算緊縮。用實際 DGS10 量級，
    # 4.01 - 4.00 在浮點上略小於 0.01，門檻誤寫成 > 0.01 時這裡才會紅
    dgs10 = pd.DataFrame({
        "series_id": "FRED:DGS10",
        "date": us,
        "value": [4.00] * 20 + [4.01] * (len(us) - 20),
    })
    tiny_up = pd.concat([dgs10, _macro({"BZ=F": 1, "DX-Y.NYB": 1}, us)], ignore_index=True)
    assert tightening_flags(tiny_up, pd.DatetimeIndex([us[25]])).all()


def test_tightening_handles_mixed_datetime_resolutions():
    # 實跑踩過：面板交易日是 [us]、CSV 讀進來的日期是 [s]，merge_asof 直接 MergeError
    us = pd.bdate_range("2026-01-01", periods=30)
    macro = _macro({"FRED:DGS10": 1, "BZ=F": 1, "DX-Y.NYB": 1}, us)
    macro["date"] = pd.to_datetime(macro["date"]).astype("datetime64[s]")
    sessions = pd.DatetimeIndex([us[20], us[21]]).astype("datetime64[us]")
    assert tightening_flags(macro, sessions).tolist() == [False, True]


# ── 判準與回撤 ────────────────────────────────────────────────────────


def test_verdict_requires_both_cis_above_zero():
    assert pre_event_verdict(120, (0.001, 0.02), (0.01, 0.05)) == "支持"
    assert pre_event_verdict(120, (0.001, 0.02), (-0.01, 0.05)) == "inconclusive"
    assert pre_event_verdict(120, (-0.001, 0.02), (0.01, 0.05)) == "inconclusive"
    assert pre_event_verdict(120, (-0.02, -0.001), (-0.05, -0.01)) == "較差"
    assert pre_event_verdict(120, (-0.02, -0.001), (-0.05, 0.01)) == "inconclusive"


def test_verdict_small_n_or_missing_ci_is_inconclusive():
    assert pre_event_verdict(29, (0.01, 0.02), (0.01, 0.05)) == "inconclusive"
    assert pre_event_verdict(30, (0.01, 0.02), (0.01, 0.05)) == "支持"
    assert pre_event_verdict(120, None, (0.01, 0.05)) == "inconclusive"


def test_trade_max_drawdown_from_entry_open():
    idx = pd.bdate_range("2026-01-01", periods=6)
    o = pd.DataFrame({"1111": [9, 10, 99, 99, 99, 99]}, index=idx, dtype=float)
    c = pd.DataFrame({"1111": [9, 12, 9, 13, 50, 50]}, index=idx, dtype=float)
    # 訊號日 0、h=3：第 1 列開盤 10 進場，收盤路徑 12、9、13 → 最大回撤 9/12−1
    assert trade_max_drawdown(o, c, 0, "1111", 3) == pytest.approx(9 / 12 - 1)


# ── 唯讀護欄 ──────────────────────────────────────────────────────────


class _FakePgConn:
    """模擬 Postgres 非 autocommit 連線：SET 跟著交易走，rollback 會撤銷；
    交易的唯讀與否在交易開始時由 session 預設決定。"""

    def __init__(self):
        self.default_ro = False  # 已生效（committed）的 session 預設
        self._pending_ro = None
        self.in_tx = False
        self.tx_read_only = None

    def _begin_if_needed(self):
        if not self.in_tx:
            self.in_tx = True
            self.tx_read_only = self.default_ro

    def cursor(self):
        conn = self

        class _Cur:
            def execute(self, sql):
                conn._begin_if_needed()
                if sql.strip().lower() == "set default_transaction_read_only = on":
                    conn._pending_ro = True

            def close(self):
                pass

        return _Cur()

    def commit(self):
        if self._pending_ro is not None:
            self.default_ro = self._pending_ro
        self._pending_ro = None
        self.in_tx = False

    def rollback(self):
        self._pending_ro = None
        self.in_tx = False


def test_read_only_listener_covers_first_and_reused_transactions():
    conn = _FakePgConn()
    set_session_read_only(conn, None)
    # 首次連線的第一筆交易
    conn.cursor().execute("SELECT 1")
    assert conn.tx_read_only is True
    # 歸還 pool 時的 rollback 不能撤銷唯讀預設；重用後的交易也要唯讀
    conn.rollback()
    conn.cursor().execute("SELECT 1")
    assert conn.tx_read_only is True
    assert conn.default_ro is True
