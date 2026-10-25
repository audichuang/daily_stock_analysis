# -*- coding: utf-8 -*-
"""H2：回測／DecisionSignal 後驗改用 T+1 開盤進場、台股還原報酬與台股淨報酬。

全部用注入的 factor_loader，不連 market schema。
"""

from __future__ import annotations

import json
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.config import Config
from src.core.backtest_engine import (
    BacktestEngine,
    EvaluationConfig,
    effective_backtest_engine_version,
)
from src.services.backtest_price_basis import (
    PRICE_BASIS_ADJUSTED,
    PRICE_BASIS_AS_STORED,
    PRICE_BASIS_RAW,
    compute_tw_net_return_pct,
    resolve_entry_basis,
    tw_stock_id,
)
from src.services.backtest_service import BacktestService
from src.services.decision_signal_outcome_service import (
    DECISION_SIGNAL_OUTCOME_ENGINE_VERSION,
    RETRYABLE_UNABLE_REASONS,
    DecisionSignalOutcomeService,
)
from src.storage import (
    AnalysisHistory,
    BacktestResult,
    DatabaseManager,
    DecisionSignalOutcomeRecord,
    DecisionSignalRecord,
    StockDaily,
)

MDB = "MarketDBFetcher"
# 台股一般股票（非 ETF）手續費 0.1425%、證交稅 0.3%、預設滑價 0.15%，獨立寫死不呼叫被測函式。
STOCK_BUY_MULT = (1 + 0.0015) * (1 + 0.001425)
STOCK_SELL_MULT = (1 - 0.0015) * (1 - 0.001425 - 0.003)
ETF_SELL_MULT = (1 - 0.0015) * (1 - 0.001425 - 0.001)


def _bar(d, *, open_, high=None, low=None, close, source=MDB):
    return SimpleNamespace(
        date=d,
        open=open_,
        high=high if high is not None else max(open_ or close, close),
        low=low if low is not None else min(open_ or close, close),
        close=close,
        data_source=source,
    )


def _loader_from(mults):
    calls = []

    def loader(stock_id, dates):
        calls.append((stock_id, list(dates)))
        return {d: mults.get(d, 1.0) for d in dates}

    loader.calls = calls
    return loader


def _never_loader(stock_id, dates):  # pragma: no cover - 被呼叫即失敗
    raise AssertionError(f"factor loader must not be called for {stock_id}")


ANCHOR = date(2024, 7, 1)
D1, D2, D3 = date(2024, 7, 2), date(2024, 7, 3), date(2024, 7, 4)
# 7/3 除息 3.5%：之前的乘數 0.965、之後 1。
EX_DIV_MULTS = {ANCHOR: 0.965, D1: 0.965, D2: 1.0, D3: 1.0}


def _ex_div_window():
    return [
        _bar(D1, open_=100.0, high=100.5, low=99.5, close=100.0),
        _bar(D2, open_=96.5, high=97.0, low=96.0, close=96.5),
        _bar(D3, open_=96.5, high=97.0, low=96.0, close=96.5),
    ]


def _eval_single(advice, bars, basis, *, stop=None, take=None, start=None):
    return BacktestEngine.evaluate_single(
        operation_advice=advice,
        analysis_date=ANCHOR,
        start_price=bars[0].open if start is None else start,
        forward_bars=bars,
        stop_loss=stop,
        take_profit=take,
        config=EvaluationConfig(eval_window_days=len(bars), engine_version="v1-t1o-adj"),
        price_context=basis,
    )


# ---------------------------------------------------------------------------
# 純計算（engine + basis）
# ---------------------------------------------------------------------------


def test_ex_dividend_in_window_flat_price_is_neutral_not_loss():
    bars = _ex_div_window()
    basis = resolve_entry_basis(
        code="2330.TW", anchor_date=ANCHOR, window_bars=bars, factor_loader=_loader_from(EX_DIV_MULTS)
    )
    result = _eval_single("买入", bars, basis)

    assert basis.price_basis == PRICE_BASIS_ADJUSTED
    assert result["stock_return_pct"] == pytest.approx(0.0, abs=1e-9)
    assert result["outcome"] == "neutral"
    assert result["direction_correct"] is None
    # 存檔價位是原始價。
    assert result["end_close"] == 96.5
    assert result["start_price"] == 100.0
    assert result["simulated_exit_price"] == pytest.approx(96.5)
    assert result["simulated_return_pct"] == pytest.approx(0.0, abs=1e-9)


def test_ex_dividend_does_not_hand_sell_advice_a_free_win():
    bars = _ex_div_window()
    basis = resolve_entry_basis(
        code="2330.TW", anchor_date=ANCHOR, window_bars=bars, factor_loader=_loader_from(EX_DIV_MULTS)
    )
    result = _eval_single("卖出", bars, basis)
    assert result["outcome"] == "neutral"
    assert result["direction_correct"] is None


def test_ex_date_on_entry_day_is_not_adjusted_again():
    # 進場那天就是除息日：開盤已是除息後價格，窗口內不該再還原（過度修正會變 +3.6%）。
    bars = [
        _bar(D1, open_=96.5, close=96.5),
        _bar(D2, open_=96.5, close=96.5),
        _bar(D3, open_=96.5, close=96.5),
    ]
    mults = {ANCHOR: 0.965, D1: 1.0, D2: 1.0, D3: 1.0}
    basis = resolve_entry_basis(
        code="2330.TW", anchor_date=ANCHOR, window_bars=bars, factor_loader=_loader_from(mults)
    )
    result = _eval_single("买入", bars, basis)
    assert result["stock_return_pct"] == pytest.approx(0.0, abs=1e-9)
    assert basis.level_factor == pytest.approx(0.965)


def test_net_return_for_tw_long_applies_round_trip_costs_once():
    bars = [_bar(D1, open_=100.0, close=105.0), _bar(D2, open_=105.0, close=110.0)]
    basis = resolve_entry_basis(
        code="2330.TW", anchor_date=ANCHOR, window_bars=bars, factor_loader=_loader_from({})
    )
    result = _eval_single("买入", bars, basis)
    expected = (1.10 * STOCK_SELL_MULT / STOCK_BUY_MULT - 1) * 100
    assert result["simulated_return_pct"] == pytest.approx(10.0)
    assert result["simulated_net_return_pct"] == pytest.approx(expected, rel=1e-12)
    # 毛報酬才拿來分類，成本不影響。
    assert result["stock_return_pct"] == pytest.approx(10.0)


def test_net_return_etf_uses_lower_tax_and_cash_and_non_tw():
    bars = [_bar(D1, open_=100.0, close=105.0), _bar(D2, open_=105.0, close=110.0)]
    etf_basis = resolve_entry_basis(
        code="0050.TW", anchor_date=ANCHOR, window_bars=bars, factor_loader=_loader_from({})
    )
    etf = _eval_single("买入", bars, etf_basis)
    assert etf["simulated_net_return_pct"] == pytest.approx(
        (1.10 * ETF_SELL_MULT / STOCK_BUY_MULT - 1) * 100, rel=1e-12
    )
    stock_basis = resolve_entry_basis(
        code="2330.TW", anchor_date=ANCHOR, window_bars=bars, factor_loader=_loader_from({})
    )
    assert etf["simulated_net_return_pct"] > _eval_single("买入", bars, stock_basis)["simulated_net_return_pct"]

    cash = _eval_single("卖出", bars, stock_basis)
    assert cash["simulated_net_return_pct"] == 0.0

    us_basis = resolve_entry_basis(
        code="AAPL", anchor_date=ANCHOR, window_bars=bars, factor_loader=_never_loader
    )
    assert _eval_single("买入", bars, us_basis)["simulated_net_return_pct"] is None


def test_compute_tw_net_return_pct_none_inputs():
    assert compute_tw_net_return_pct(None, (1.0, 1.0)) is None
    assert compute_tw_net_return_pct(5.0, None) is None


def test_non_tw_never_loads_factors_and_matches_raw_open_to_close():
    bars = [_bar(D1, open_=105.0, close=104.0), _bar(D2, open_=104.0, close=110.0)]
    basis = resolve_entry_basis(
        code="600519", anchor_date=ANCHOR, window_bars=bars, factor_loader=_never_loader
    )
    assert basis.price_basis == PRICE_BASIS_AS_STORED
    assert basis.adjustment_reason is None
    result = _eval_single("买入", bars, basis)
    assert result["stock_return_pct"] == pytest.approx((110.0 - 105.0) / 105.0 * 100)
    assert result["entry_date"] == D1


def test_factor_loader_failure_falls_back_to_raw():
    def boom(stock_id, dates):
        raise RuntimeError("DATABASE_URL is not set")

    bars = _ex_div_window()
    basis = resolve_entry_basis(code="2330.TW", anchor_date=ANCHOR, window_bars=bars, factor_loader=boom)
    assert basis.price_basis == PRICE_BASIS_RAW
    assert basis.adjustment_reason == "factor_unavailable"
    result = _eval_single("买入", bars, basis)
    assert result["eval_status"] == "completed"
    assert result["stock_return_pct"] == pytest.approx(-3.5)


def test_invalid_factors_fall_back_to_raw():
    bars = _ex_div_window()
    basis = resolve_entry_basis(
        code="2330.TW",
        anchor_date=ANCHOR,
        window_bars=bars,
        factor_loader=lambda sid, dates: {d: float("nan") for d in dates},
    )
    assert (basis.price_basis, basis.adjustment_reason) == (PRICE_BASIS_RAW, "invalid_factors")


def test_non_marketdb_bar_falls_back_to_raw_without_loading():
    bars = _ex_div_window()
    bars[1] = _bar(D2, open_=96.5, close=96.5, source="YfinanceFetcher")
    basis = resolve_entry_basis(
        code="2330.TW", anchor_date=ANCHOR, window_bars=bars, factor_loader=_never_loader
    )
    assert (basis.price_basis, basis.adjustment_reason) == (PRICE_BASIS_RAW, "non_marketdb_bars")


def test_working_loader_with_marketdb_bars_is_adjusted():
    loader = _loader_from(EX_DIV_MULTS)
    basis = resolve_entry_basis(
        code="2330.TW", anchor_date=ANCHOR, window_bars=_ex_div_window(), factor_loader=loader
    )
    assert basis.price_basis == PRICE_BASIS_ADJUSTED
    assert loader.calls == [("2330", [ANCHOR, D1, D2, D3])]


@pytest.mark.parametrize(
    "code, expected",
    [("00631L.TWO", "00631L"), ("2887A.TW", "2887A"), ("2330.tw", "2330"), ("2330", None), ("AAPL", None)],
)
def test_tw_stock_id_mapping(code, expected):
    assert tw_stock_id(code) == expected


def test_bare_tw_digits_get_no_factors():
    basis = resolve_entry_basis(
        code="2330", anchor_date=ANCHOR, window_bars=_ex_div_window(), factor_loader=_never_loader
    )
    assert basis.price_basis == PRICE_BASIS_AS_STORED


def test_gap_below_stop_exits_at_open_not_stop():
    bars = [_bar(D1, open_=100.0, high=100.0, low=99.0, close=99.5), _bar(D2, open_=95.0, high=96.0, low=94.0, close=95.5)]
    basis = resolve_entry_basis(code="600519", anchor_date=ANCHOR, window_bars=bars)
    result = _eval_single("买入", bars, basis, stop=97.0)
    assert result["first_hit"] == "stop_loss"
    assert result["simulated_exit_price"] == pytest.approx(95.0)
    assert result["simulated_return_pct"] == pytest.approx(-5.0)


def test_intraday_stop_without_gap_exits_at_stop():
    bars = [_bar(D1, open_=100.0, high=100.5, low=96.0, close=99.0)]
    basis = resolve_entry_basis(code="600519", anchor_date=ANCHOR, window_bars=bars)
    result = _eval_single("买入", bars, basis, stop=97.0)
    assert result["simulated_exit_price"] == pytest.approx(97.0)


def test_gap_above_take_profit_exits_at_open():
    bars = [_bar(D1, open_=100.0, high=101.0, low=99.0, close=100.5), _bar(D2, open_=112.0, high=113.0, low=111.0, close=112.0)]
    basis = resolve_entry_basis(code="600519", anchor_date=ANCHOR, window_bars=bars)
    result = _eval_single("买入", bars, basis, take=110.0)
    assert result["first_hit"] == "take_profit"
    assert result["simulated_exit_price"] == pytest.approx(112.0)


def test_stop_level_is_rescaled_when_entry_day_is_ex_date():
    # 錨點日訂的停損 97 是除息前的名目價；T+1 除息 3.5% 後等價停損約 93.6，低點 95 不該觸發。
    bars = [_bar(D1, open_=96.5, high=97.0, low=95.0, close=96.0)]
    basis = resolve_entry_basis(
        code="2330.TW",
        anchor_date=ANCHOR,
        window_bars=bars,
        factor_loader=_loader_from({ANCHOR: 0.965, D1: 1.0}),
    )
    result = _eval_single("买入", bars, basis, stop=97.0)
    assert result["hit_stop_loss"] is False
    assert result["simulated_exit_reason"] == "window_end"


def test_stop_hit_after_ex_date_stores_raw_exit_price():
    # 進場 100，D2 除息 3.5%；D3 跌破還原後停損 → 存檔出場價要是 D3 的原始價位。
    bars = [
        _bar(D1, open_=100.0, high=100.5, low=99.5, close=100.0),
        _bar(D2, open_=96.5, high=97.0, low=96.0, close=96.5),
        _bar(D3, open_=96.0, high=96.0, low=90.0, close=91.0),
    ]
    basis = resolve_entry_basis(
        code="2330.TW", anchor_date=ANCHOR, window_bars=bars, factor_loader=_loader_from(EX_DIV_MULTS)
    )
    result = _eval_single("买入", bars, basis, stop=95.0)
    assert result["first_hit"] == "stop_loss"
    # 停損 95 換到 D3 的原始價位是 95 × 0.965 = 91.675。
    assert result["simulated_exit_price"] == pytest.approx(95.0 * 0.965)
    assert result["simulated_return_pct"] == pytest.approx(-5.0)


def test_engine_without_price_context_keeps_legacy_shape():
    bars = [_bar(D1, open_=105.0, close=110.0)]
    result = BacktestEngine.evaluate_single(
        operation_advice="买入",
        analysis_date=ANCHOR,
        start_price=100.0,
        forward_bars=bars,
        stop_loss=None,
        take_profit=None,
        config=EvaluationConfig(eval_window_days=1),
    )
    assert result["stock_return_pct"] == pytest.approx(10.0)
    assert "price_basis" not in result


def test_effective_engine_version():
    assert effective_backtest_engine_version("v1") == "v1-t1o-adj"
    assert effective_backtest_engine_version("v1-t1o-adj") == "v1-t1o-adj"
    assert effective_backtest_engine_version(None) == "v1-t1o-adj"
    long_version = effective_backtest_engine_version("experiment-2026-10")
    assert len(long_version) <= 16
    assert long_version.endswith("-t1o-adj")
    assert DECISION_SIGNAL_OUTCOME_ENGINE_VERSION == "decision-signal-v2"


# ---------------------------------------------------------------------------
# BacktestService（SQLite 暫存庫）
# ---------------------------------------------------------------------------


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("STOCK_LIST=600519\n", encoding="utf-8")
    monkeypatch.setenv("ENV_FILE", str(env_path))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "h2.db"))
    monkeypatch.setenv("BACKTEST_ENGINE_VERSION", "v1")
    Config._instance = None
    DatabaseManager.reset_instance()
    db = DatabaseManager.get_instance()
    yield db
    DatabaseManager.reset_instance()
    Config._instance = None


def _snapshot(analysis_date, *, phase, market, effective_date=None):
    summary = {"phase": phase, "market": market}
    if effective_date is not None:
        summary["effective_daily_bar_date"] = effective_date.isoformat()
    return json.dumps(
        {"enhanced_context": {"date": analysis_date.isoformat()}, "market_phase_summary": summary}
    )


def _seed_history(db, *, code, advice="买入", analysis_date=ANCHOR, phase="postmarket", market="tw",
                  effective_date=ANCHOR, stop_loss=None, take_profit=None):
    with db.get_session() as session:
        row = AnalysisHistory(
            query_id=f"q-{code}-{phase}-{analysis_date}",
            code=code,
            name="test",
            report_type="simple",
            sentiment_score=70,
            operation_advice=advice,
            trend_prediction="看多",
            analysis_summary="h2",
            stop_loss=stop_loss,
            take_profit=take_profit,
            created_at=datetime.combine(analysis_date, datetime.min.time()),
            context_snapshot=_snapshot(analysis_date, phase=phase, market=market, effective_date=effective_date),
        )
        session.add(row)
        session.commit()
        return row.id


def _seed_daily(db, code, rows, source=MDB):
    with db.get_session() as session:
        for d, o, h, low, c in rows:
            session.add(StockDaily(code=code, date=d, open=o, high=h, low=low, close=c, data_source=source))
        session.commit()


def _run(service, code, window=3):
    return service.run_backtest(code=code, force=False, eval_window_days=window, min_age_days=0, limit=10)


def _results(db, code):
    with db.get_session() as session:
        rows = session.query(BacktestResult).filter(BacktestResult.code == code).all()
        session.expunge_all()
        return rows


EX_DIV_DAILY = [
    (ANCHOR, 100.0, 100.5, 99.5, 100.0),
    (D1, 100.0, 100.5, 99.5, 100.0),
    (D2, 96.5, 97.0, 96.0, 96.5),
    (D3, 96.5, 97.0, 96.0, 96.5),
]


def test_service_ex_dividend_window_is_neutral_and_persists_basis(isolated_db):
    _seed_history(isolated_db, code="2330.TW")
    _seed_daily(isolated_db, "2330.TW", EX_DIV_DAILY)
    service = BacktestService(isolated_db, factor_loader=_loader_from(EX_DIV_MULTS))

    stats = _run(service, "2330.TW")

    assert stats["completed"] == 1
    (row,) = _results(isolated_db, "2330.TW")
    assert row.engine_version == "v1-t1o-adj"
    assert row.outcome == "neutral"
    assert row.stock_return_pct == pytest.approx(0.0, abs=1e-9)
    assert row.price_basis == "adjusted"
    assert row.adjustment_reason is None
    assert row.entry_date == D1
    assert row.start_price == 100.0
    assert row.end_close == 96.5
    assert row.simulated_net_return_pct == pytest.approx(
        (STOCK_SELL_MULT / STOCK_BUY_MULT - 1) * 100, rel=1e-9
    )
    item = BacktestService._result_to_dict(row)
    assert item["price_basis"] == "adjusted"
    assert item["entry_date"] == D1.isoformat()


def test_service_enters_at_t_plus_1_open_not_anchor_close(isolated_db):
    _seed_history(isolated_db, code="600519", market="cn")
    _seed_daily(
        isolated_db,
        "600519",
        [
            (ANCHOR, 99.0, 100.0, 98.0, 100.0),
            (D1, 105.0, 106.0, 104.0, 104.0),
            (D2, 104.0, 105.0, 103.0, 104.5),
            (D3, 104.5, 106.0, 104.0, 105.0),
        ],
        source="AkshareFetcher",
    )
    service = BacktestService(isolated_db, factor_loader=_never_loader)

    _run(service, "600519")

    (row,) = _results(isolated_db, "600519")
    assert row.entry_date == D1
    assert row.start_price == 105.0
    assert row.stock_return_pct == pytest.approx(0.0)
    assert row.outcome == "neutral"
    assert row.price_basis == "as_stored"
    assert row.simulated_net_return_pct is None


def test_service_missing_entry_open_is_insufficient_after_one_refill(isolated_db):
    _seed_history(isolated_db, code="600519", market="cn")
    _seed_daily(
        isolated_db,
        "600519",
        [
            (ANCHOR, 99.0, 100.0, 98.0, 100.0),
            (D1, None, 106.0, 104.0, 105.0),
            (D2, 105.0, 106.0, 104.0, 105.0),
            (D3, 105.0, 106.0, 104.0, 105.0),
        ],
    )
    service = BacktestService(isolated_db, factor_loader=_never_loader)
    with patch.object(service, "_try_fill_daily_data") as refill:
        stats = _run(service, "600519")

    refill.assert_called_once()
    assert stats["insufficient"] == 1
    assert stats["completed"] == 0
    (row,) = _results(isolated_db, "600519")
    assert row.eval_status == "insufficient_data"
    assert row.start_price is None


def test_service_intraday_analysis_enters_after_analysis_day(isolated_db):
    # 7/2 盤中分析：錨點是 7/1，但分析時已看到 7/2 開盤 → 進場改 7/3 開盤。
    _seed_history(
        isolated_db, code="600519", market="cn", analysis_date=D1, phase="intraday", effective_date=ANCHOR
    )
    _seed_daily(
        isolated_db,
        "600519",
        [
            (ANCHOR, 99.0, 100.0, 98.0, 100.0),
            (D1, 100.0, 101.0, 99.0, 100.0),
            (D2, 110.0, 111.0, 109.0, 110.0),
            (D3, 110.0, 111.0, 109.0, 110.0),
            (date(2024, 7, 5), 110.0, 111.0, 109.0, 110.0),
        ],
    )
    service = BacktestService(isolated_db, factor_loader=_never_loader)
    _run(service, "600519", window=2)

    (row,) = _results(isolated_db, "600519")
    assert row.entry_date == D2
    assert row.start_price == 110.0


def test_service_premarket_analysis_enters_at_same_day_open(isolated_db):
    _seed_history(
        isolated_db, code="600519", market="cn", analysis_date=D1, phase="premarket", effective_date=ANCHOR
    )
    _seed_daily(
        isolated_db,
        "600519",
        [
            (ANCHOR, 99.0, 100.0, 98.0, 100.0),
            (D1, 100.0, 101.0, 99.0, 100.0),
            (D2, 110.0, 111.0, 109.0, 110.0),
        ],
    )
    service = BacktestService(isolated_db, factor_loader=_never_loader)
    _run(service, "600519", window=2)

    (row,) = _results(isolated_db, "600519")
    assert row.entry_date == D1
    assert row.start_price == 100.0


@pytest.mark.parametrize("phase", ["intraday", "lunch_break", "closing_auction", "postmarket", "premarket"])
@pytest.mark.parametrize("session_fields", [
    {"session_date": "2026-10-26", "market_local_time": "2026-10-23T10:00:00+08:00"},
    {"market_local_time": "2026-10-26T10:00:00+08:00"},
    {"session_date": "invalid", "market_local_time": "2026-10-26T10:00:00+08:00"},
])
def test_service_entry_cutoff_uses_persisted_session_after_quote_failure(isolated_db, phase, session_fields):
    anchor, session_day, next_day = date(2026, 10, 23), date(2026, 10, 26), date(2026, 10, 27)
    history_id = _seed_history(isolated_db, code="2330.TW", analysis_date=anchor, phase=phase, effective_date=anchor)
    with isolated_db.session_scope() as session:
        history = session.get(AnalysisHistory, history_id)
        snapshot = json.loads(history.context_snapshot)
        snapshot["market_phase_summary"].update(session_fields)
        history.context_snapshot = json.dumps(snapshot)
    _seed_daily(isolated_db, "2330.TW", [
        (anchor, 100.0, 101.0, 99.0, 100.0),
        (session_day, 100.0, 101.0, 99.0, 100.0),
        (next_day, 110.0, 111.0, 109.0, 110.0),
        (date(2026, 10, 28), 110.0, 111.0, 109.0, 110.0),
    ])
    loader = _loader_from({anchor: 0.9})
    service = BacktestService(isolated_db, factor_loader=loader)
    with patch.object(service, "_try_fill_daily_data") as refill:
        stats = _run(service, "2330.TW", window=2)

    assert stats["completed"] == 1
    refill.assert_not_called()
    (row,) = _results(isolated_db, "2330.TW")
    guarded = phase in {"intraday", "lunch_break", "closing_auction"}
    assert row.entry_date == (next_day if guarded else session_day)
    assert row.start_price == (110.0 if guarded else 100.0)
    assert row.analysis_date == anchor
    # 執行截止日不能取代停損停利的價格錨點，因子仍須讀取 10/23。
    assert loader.calls == [("2330", [anchor, next_day, date(2026, 10, 28)] if guarded
                            else [anchor, session_day, next_day])]


@pytest.mark.parametrize("session_fields", [{}, {"session_date": "invalid", "market_local_time": "invalid"}])
@pytest.mark.parametrize("analysis_date,expected_entry", [(ANCHOR, D1), (D1, D2)])
def test_service_entry_cutoff_keeps_legacy_fallback(isolated_db, session_fields, analysis_date, expected_entry):
    history_id = _seed_history(
        isolated_db, code="600519", market="cn", analysis_date=analysis_date, phase="intraday"
    )
    with isolated_db.session_scope() as session:
        history = session.get(AnalysisHistory, history_id)
        snapshot = json.loads(history.context_snapshot)
        snapshot["market_phase_summary"].update(session_fields)
        history.context_snapshot = json.dumps(snapshot)
    _seed_daily(isolated_db, "600519", [
        (ANCHOR, 100.0, 101.0, 99.0, 100.0),
        (D1, 100.0, 101.0, 99.0, 100.0),
        (D2, 110.0, 111.0, 109.0, 110.0),
    ])

    stats = _run(BacktestService(isolated_db, factor_loader=_never_loader), "600519", window=1)

    assert stats["completed"] == 1
    (row,) = _results(isolated_db, "600519")
    assert row.entry_date == expected_entry


def test_service_entry_cutoff_keeps_later_analysis_date(isolated_db):
    history_id = _seed_history(isolated_db, code="600519", market="cn", analysis_date=D2, phase="intraday")
    with isolated_db.session_scope() as session:
        history = session.get(AnalysisHistory, history_id)
        snapshot = json.loads(history.context_snapshot)
        snapshot["market_phase_summary"]["session_date"] = D1.isoformat()
        history.context_snapshot = json.dumps(snapshot)
    _seed_daily(isolated_db, "600519", [
        (ANCHOR, 100.0, 101.0, 99.0, 100.0),
        (D1, 100.0, 101.0, 99.0, 100.0),
        (D2, 100.0, 101.0, 99.0, 100.0),
        (D3, 110.0, 111.0, 109.0, 110.0),
    ])

    stats = _run(BacktestService(isolated_db, factor_loader=_never_loader), "600519", window=1)

    assert stats["completed"] == 1
    (row,) = _results(isolated_db, "600519")
    assert row.entry_date == D3


def test_service_entry_cutoff_checks_entry_open_before_refill(isolated_db):
    history_id = _seed_history(isolated_db, code="600519", market="cn", phase="intraday")
    with isolated_db.session_scope() as session:
        history = session.get(AnalysisHistory, history_id)
        snapshot = json.loads(history.context_snapshot)
        snapshot["market_phase_summary"]["session_date"] = D1.isoformat()
        history.context_snapshot = json.dumps(snapshot)
    _seed_daily(isolated_db, "600519", [
        (ANCHOR, 100.0, 101.0, 99.0, 100.0),
        (D1, 100.0, 101.0, 99.0, 100.0),
        (D2, None, 111.0, 109.0, 110.0),
    ])
    service = BacktestService(isolated_db, factor_loader=_never_loader)
    with patch.object(service, "_try_fill_daily_data") as refill:
        stats = _run(service, "600519", window=1)

    refill.assert_called_once()
    assert stats["insufficient"] == 1
    assert stats["completed"] == 0
    (row,) = _results(isolated_db, "600519")
    assert row.eval_status == "insufficient_data"


def test_service_broker_fee_discount_preserves_zero_and_defaults(isolated_db):
    _seed_history(isolated_db, code="2330.TW")
    _seed_daily(isolated_db, "2330.TW", EX_DIV_DAILY)
    service = BacktestService(isolated_db, factor_loader=_loader_from(EX_DIV_MULTS))
    returns = {}
    for label, fields in [("zero", {"tw_broker_fee_discount": 0.0}),
                          ("full", {"tw_broker_fee_discount": 1.0}),
                          ("none", {"tw_broker_fee_discount": None}), ("missing", {})]:
        with patch("src.services.backtest_service.get_config", return_value=SimpleNamespace(**fields)):
            stats = service.run_backtest(code="2330.TW", force=True, eval_window_days=3, min_age_days=0)
        assert stats["completed"] == 1
        (row,) = _results(isolated_db, "2330.TW")
        returns[label] = row.simulated_net_return_pct
        assert row.stock_return_pct == pytest.approx(0.0)

    assert returns["zero"] > returns["full"]
    assert returns["zero"] == pytest.approx(((1 - 0.0015) * (1 - 0.003) / (1 + 0.0015) - 1) * 100)
    expected_full = (STOCK_SELL_MULT / STOCK_BUY_MULT - 1) * 100
    for label in ("full", "none", "missing"):
        assert returns[label] == pytest.approx(expected_full)


def test_service_factor_failure_falls_back_to_raw_and_completes(isolated_db):
    def boom(stock_id, dates):
        raise RuntimeError("no market schema")

    _seed_history(isolated_db, code="2330.TW")
    _seed_daily(isolated_db, "2330.TW", EX_DIV_DAILY)
    stats = _run(BacktestService(isolated_db, factor_loader=boom), "2330.TW")

    assert stats["completed"] == 1
    (row,) = _results(isolated_db, "2330.TW")
    assert (row.price_basis, row.adjustment_reason) == ("raw", "factor_unavailable")
    assert row.stock_return_pct == pytest.approx(-3.5)


def test_service_keeps_legacy_v1_rows_and_writes_new_version(isolated_db):
    history_id = _seed_history(isolated_db, code="600519", market="cn")
    _seed_daily(
        isolated_db,
        "600519",
        [(ANCHOR, 99.0, 100.0, 98.0, 100.0), (D1, 100.0, 101.0, 99.0, 101.0),
         (D2, 101.0, 102.0, 100.0, 101.0), (D3, 101.0, 102.0, 100.0, 101.0)],
    )
    with isolated_db.get_session() as session:
        session.add(BacktestResult(
            analysis_history_id=history_id, code="600519", analysis_date=ANCHOR, eval_window_days=3,
            engine_version="v1", eval_status="completed", start_price=100.0, end_close=96.5,
            stock_return_pct=-3.5, outcome="loss",
        ))
        session.commit()

    _run(BacktestService(isolated_db, factor_loader=_never_loader), "600519")

    versions = sorted(row.engine_version for row in _results(isolated_db, "600519"))
    assert versions == ["v1", "v1-t1o-adj"]


# ---------------------------------------------------------------------------
# DecisionSignalOutcomeService
# ---------------------------------------------------------------------------


def _add_signal(db, *, code="2330.TW", action="buy", horizon="3d", session_date=ANCHOR, market="tw"):
    with db.session_scope() as session:
        signal = DecisionSignalRecord(
            source_type="analysis",
            source_agent="h2-test",
            stock_code=code,
            stock_name="test",
            market=market,
            market_phase="postmarket",
            trigger_source="manual",
            action=action,
            action_label=action,
            horizon=horizon,
            reason="h2",
            metadata_json=json.dumps({"market_phase_summary": {"session_date": session_date.isoformat()}}),
            plan_quality="complete",
            status="active",
        )
        session.add(signal)
        session.flush()
        return signal.id


def test_signal_ex_dividend_buy_is_neutral_and_stores_adjusted_mae(isolated_db):
    signal_id = _add_signal(isolated_db)
    _seed_daily(isolated_db, "2330.TW", EX_DIV_DAILY)
    service = DecisionSignalOutcomeService(db_manager=isolated_db, factor_loader=_loader_from(EX_DIV_MULTS))

    item = service.run_outcomes(signal_id=signal_id)["items"][0]

    assert item["engine_version"] == "decision-signal-v2"
    assert item["eval_status"] == "completed"
    assert item["outcome"] == "neutral"
    assert item["stock_return_pct"] == pytest.approx(0.0, abs=1e-9)
    assert item["price_basis"] == "adjusted"
    assert item["entry_date"] == D1.isoformat()
    assert item["start_price"] == 100.0
    assert item["min_low"] == 96.0  # 原始價
    # 還原後最低 96 / 0.965 ≈ 99.48 → 不利偏移約 0.52%，不是原始價的 4%。
    assert item["max_adverse_excursion_pct"] == pytest.approx((100.0 - 96.0 / 0.965) / 100.0 * 100)


def test_signal_missing_entry_open_is_retryable_unable(isolated_db):
    signal_id = _add_signal(isolated_db, code="600519", market="cn")
    _seed_daily(
        isolated_db,
        "600519",
        [(ANCHOR, 99.0, 100.0, 98.0, 100.0), (D1, None, 101.0, 99.0, 101.0),
         (D2, 101.0, 102.0, 100.0, 101.0), (D3, 101.0, 102.0, 100.0, 101.0)],
    )
    service = DecisionSignalOutcomeService(db_manager=isolated_db, factor_loader=_never_loader)
    item = service.run_outcomes(signal_id=signal_id)["items"][0]

    assert item["eval_status"] == "unable"
    assert item["unable_reason"] == "missing_entry_open"
    assert "missing_entry_open" in RETRYABLE_UNABLE_REASONS
    assert "invalid_entry_open" in RETRYABLE_UNABLE_REASONS


def test_signal_short_window_reports_insufficient_before_missing_open(isolated_db):
    signal_id = _add_signal(isolated_db, code="600519", market="cn")
    _seed_daily(isolated_db, "600519", [(ANCHOR, 99.0, 100.0, 98.0, 100.0), (D1, None, 101.0, 99.0, 101.0)])
    service = DecisionSignalOutcomeService(db_manager=isolated_db, factor_loader=_never_loader)
    item = service.run_outcomes(signal_id=signal_id)["items"][0]
    assert item["unable_reason"] == "insufficient_forward_bars"


def test_signal_enters_at_t_plus_1_open(isolated_db):
    signal_id = _add_signal(isolated_db, code="600519", market="cn")
    _seed_daily(
        isolated_db,
        "600519",
        [(ANCHOR, 99.0, 100.0, 98.0, 100.0), (D1, 105.0, 106.0, 104.0, 105.0),
         (D2, 105.0, 106.0, 104.0, 105.0), (D3, 105.0, 106.0, 104.0, 105.0)],
    )
    service = DecisionSignalOutcomeService(db_manager=isolated_db, factor_loader=_never_loader)
    item = service.run_outcomes(signal_id=signal_id)["items"][0]
    assert item["start_price"] == 105.0
    assert item["stock_return_pct"] == pytest.approx(0.0)
    assert item["price_basis"] == "as_stored"


def test_mae_prefers_stored_column_and_falls_back_for_legacy_rows():
    stored = DecisionSignalOutcomeRecord(
        action="buy", start_price=100.0, min_low=90.0, max_high=101.0, max_adverse_excursion_pct=0.5
    )
    legacy = DecisionSignalOutcomeRecord(action="buy", start_price=100.0, min_low=90.0, max_high=101.0)
    assert DecisionSignalOutcomeService._row_max_adverse_excursion_pct(stored) == pytest.approx(0.5)
    assert DecisionSignalOutcomeService._row_max_adverse_excursion_pct(legacy) == pytest.approx(10.0)


def test_default_factor_loader_is_fail_soft_without_database_url(monkeypatch):
    # 沒有 DATABASE_URL（或 market schema 不可達）時退回 raw，不拋例外。
    monkeypatch.delenv("DATABASE_URL", raising=False)
    import market_data.db as mdb

    def no_url(*args, **kwargs):
        raise RuntimeError("DATABASE_URL not set")

    monkeypatch.setattr(mdb, "get_engine", no_url)
    basis = resolve_entry_basis(code="2330.TW", anchor_date=ANCHOR, window_bars=_ex_div_window())
    assert (basis.price_basis, basis.adjustment_reason) == (PRICE_BASIS_RAW, "factor_unavailable")


def test_default_factor_loader_reuses_market_repo_helper_with_three_second_timeout(monkeypatch):
    # 預設因子來源必須重用 market_repo.front_adjust_multipliers（不另寫一份），並帶 3 秒 statement timeout。
    import pandas as pd

    import market_data.db as mdb
    import market_data.market_repo as repo
    from src.services.backtest_price_basis import default_factor_loader

    engine = object()
    calls = {}

    def fake_get_engine(*args, **kwargs):
        calls["get_engine"] = (args, kwargs)
        return engine

    def fake_helper(stock_id, dates, engine=None):
        calls["helper"] = (stock_id, list(dates), engine)
        return pd.Series([1.25, 1.0], index=pd.to_datetime(list(dates)))

    monkeypatch.setattr(mdb, "get_engine", fake_get_engine)
    monkeypatch.setattr(repo, "front_adjust_multipliers", fake_helper)
    days = [date(2024, 7, 1), date(2024, 7, 2)]

    assert default_factor_loader("00631L", days) == {days[0]: 1.25, days[1]: 1.0}
    assert calls["get_engine"] == ((), {"statement_timeout_ms": 3000})
    assert calls["helper"] == ("00631L", days, engine)
