# -*- coding: utf-8 -*-
"""台股複盤的表頭指數必須屬於複盤的那個場次。

即時報價沒有場次身分,而複盤要的正是那個。實測過的兩個反向失真:

- 非交易日 yfinance 回幽靈 K 棒:2026-09-20（週日）`get_main_indices(region="tw")`
  回 `current=47368.04 / +0.40%`,而那份報告複盤的 2026-09-18 官方收盤是
  `47180.75 / +1.93%`,連漲跌幅量級都不對。
- 14:00 排程反過來:即時源已有當日、TWSE 官方統計還停在前一場次,於是同一份報告的
  指數與漲跌家數分屬兩天。

守的是 `MarketAnalyzer._pin_tw_indices_to_session`:台股、表頭那一檔、fail-open。
"""

from contextlib import contextmanager
from unittest.mock import patch

from src.market_analyzer import MarketAnalyzer, MarketIndex

# 2026-09-18 的官方值,逐欄取自 market.market_index。
OFFICIAL_CLOSE = 47180.75
OFFICIAL_CHANGE = 892.75
OFFICIAL_TURNOVER = 1142321910407
# 同一天 yfinance 在週日回的幽靈 K 棒（prev_close 才是真收盤）。
PHANTOM_CURRENT = 47368.0390625


def _analyzer(region="tw"):
    """繞過 __init__（它會建 DataFetcherManager）——這支方法只用到 region。"""
    inst = MarketAnalyzer.__new__(MarketAnalyzer)
    inst.region = region
    return inst


@contextmanager
def _official(row=None, error=None):
    """Patch 讀取面與引擎。引擎一併釘住,是因為**逾時參數是契約的一部分**——
    少了它,一個沒回應的 DB 會把整份複盤卡在這裡,而複盤本來就該 fail-open。"""
    kwargs = {"side_effect": error} if error is not None else {"return_value": row}
    with patch("market_data.db.get_engine", return_value="ENGINE") as engine, \
            patch("market_data.market_repo.market_index", **kwargs) as reader:
        yield reader, engine


def _phantom_index():
    return MarketIndex(
        code="TWII", name="台灣加權指數",
        current=PHANTOM_CURRENT, change=187.2890625, change_pct=0.39696,
        open=47200.0, high=47400.0, low=47100.0,
        prev_close=OFFICIAL_CLOSE, volume=0.0, amount=0.0, amplitude=0.63,
    )


def test_headline_uses_the_official_close_not_the_phantom_realtime_bar():
    idx = _phantom_index()
    row = {"close": OFFICIAL_CLOSE, "change": OFFICIAL_CHANGE, "turnover": OFFICIAL_TURNOVER}

    with _official(row) as (reader, engine):
        _analyzer()._pin_tw_indices_to_session([idx], "2026-09-18")

    reader.assert_called_once()
    assert reader.call_args.args[0] == "TAIEX"
    assert reader.call_args.args[1] == "2026-09-18"
    assert engine.call_args.kwargs == {"statement_timeout_ms": 3000}
    assert idx.current == OFFICIAL_CLOSE
    assert idx.change == OFFICIAL_CHANGE
    assert round(idx.change_pct, 2) == 1.93          # 幽靈 K 棒說的是 +0.40%
    assert round(idx.prev_close, 2) == 46288.00      # 09-17 的官方收盤
    assert idx.amount == float(OFFICIAL_TURNOVER)
    # 官方表沒有這四欄,留著幽靈 K 棒的值等於繼續發佈假讀數。
    assert idx.open is None and idx.high is None and idx.low is None
    assert idx.amplitude is None


def test_a_down_session_keeps_its_negative_sign():
    """`price.change` 對上市股票只有絕對值;`market_index.change` 帶號。

    搞錯這一格會把 -1.93% 印成 +1.93%,比原本的 bug 更糟。
    """
    idx = _phantom_index()
    # 2026-09-15：45511.49，前一場次 45862.52。
    row = {"close": 45511.49, "change": -351.03, "turnover": 634706804618}

    with _official(row):
        _analyzer()._pin_tw_indices_to_session([idx], "2026-09-15")

    assert idx.change == -351.03
    assert idx.change_pct < 0
    assert round(idx.change_pct, 2) == -0.77


def test_a_session_with_no_official_row_keeps_the_realtime_value():
    """fail-open:複盤照出,只是回到舊行為。"""
    idx = _phantom_index()

    with _official(None):
        _analyzer()._pin_tw_indices_to_session([idx], "2026-09-19")

    assert idx.current == PHANTOM_CURRENT
    assert idx.open == 47200.0


def test_a_database_failure_does_not_break_the_recap():
    idx = _phantom_index()

    with _official(error=RuntimeError("db down")):
        _analyzer()._pin_tw_indices_to_session([idx], "2026-09-18")

    assert idx.current == PHANTOM_CURRENT


def test_other_markets_are_never_touched():
    """反向:這是台股專屬修正,擴大到其他市場會把美股指數指到 TAIEX 的收盤。"""
    idx = MarketIndex(code="TWII", name="不該被改", current=1.0, change=2.0, change_pct=3.0)

    with _official(row=None) as (reader, _):
        _analyzer(region="us")._pin_tw_indices_to_session([idx], "2026-09-18")

    reader.assert_not_called()
    assert idx.current == 1.0


def test_non_headline_indices_are_left_alone():
    """只改加權指數那一檔;櫃買等其他指數沒有官方列,不能被 TAIEX 的收盤覆蓋。"""
    otc = MarketIndex(code="TWOII", name="櫃買指數", current=222.5, change=1.0, change_pct=0.45)
    row = {"close": OFFICIAL_CLOSE, "change": OFFICIAL_CHANGE, "turnover": OFFICIAL_TURNOVER}

    with _official(row) as (reader, _):
        _analyzer()._pin_tw_indices_to_session([otc], "2026-09-18")

    reader.assert_not_called()
    assert otc.current == 222.5
