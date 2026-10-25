# -*- coding: utf-8 -*-
"""台股盤中（含午休、收盤集合競價）不拿部分累計量判縮放量、不給縮量回調的量能滿分。"""

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.core.pipeline import StockAnalysisPipeline  # noqa: E402
from src.core.trading_calendar import MarketPhase  # noqa: E402
from src.stock_analyzer import StockTrendAnalyzer, VolumeStatus  # noqa: E402


_NOW = datetime(2026, 10, 16, 10, 0, tzinfo=ZoneInfo("Asia/Taipei"))


def _df(last_volume_ratio=0.3, last_change_pct=-1.0, rows=30, last_date=None):
    """前面每天量 1000、價格緩漲；最後一根量＝ratio×1000、收盤較前一根 last_change_pct%。"""
    closes = [100.0 + i * 0.5 for i in range(rows - 1)]
    closes.append(closes[-1] * (1 + last_change_pct / 100))
    vols = [1000.0] * (rows - 1) + [1000.0 * last_volume_ratio]
    dates = pd.bdate_range(end=last_date or _NOW.date(), periods=rows)
    return pd.DataFrame({
        "date": dates,
        "open": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "close": closes,
        "volume": vols,
    })


def _pipeline():
    p = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    p.trend_analyzer = StockTrendAnalyzer()
    p.config = SimpleNamespace(enable_realtime_quote=True, enable_realtime_technical_indicators=True)
    return p


def _run(phase, ctx_phase=None, code="2330.TW"):
    with patch("src.core.pipeline.infer_market_phase", return_value=phase), \
         patch("src.core.pipeline.get_market_now", return_value=_NOW):
        ctx = {"phase": ctx_phase} if ctx_phase else None
        return _pipeline()._run_trend_analysis(_df(), code, ctx)


# --- 分析器本身 ------------------------------------------------------------------
def test_analyzer_intraday_flag_neutralizes_volume_judgement_and_score():
    a = StockTrendAnalyzer()
    post = a.analyze(_df(), "2330.TW")
    intra = a.analyze(_df(), "2330.TW", intraday_volume=True)

    # 反向：收盤後同一組數字照舊判縮量回調、拿 15 分
    assert post.volume_status == VolumeStatus.SHRINK_VOLUME_DOWN
    assert "✅ 缩量回调，主力洗盘" in post.signal_reasons

    assert intra.volume_status == VolumeStatus.INTRADAY_UNJUDGED
    assert "✅ 缩量回调，主力洗盘" not in intra.signal_reasons
    assert not any("缩量" in r or "縮量" in r for r in intra.signal_reasons + intra.risk_factors)
    assert "盤中" in intra.volume_trend and "不判讀" in intra.volume_trend
    # 量比照算（顯示用），只是不拿來判讀
    assert intra.volume_ratio_5d == pytest.approx(post.volume_ratio_5d)
    assert intra.volume_ratio_5d == pytest.approx(0.3)
    # 中性分＝量能正常的 10 分：比縮量回調的 15 分少 5，不多扣也不少扣
    assert post.signal_score - intra.signal_score == 5


def test_analyzer_intraday_flag_also_suppresses_heavy_volume_down():
    # 盤中不判讀是對稱的：放量下跌也不判（0 分 → 中性 10 分）
    a = StockTrendAnalyzer()
    post = a.analyze(_df(last_volume_ratio=2.0), "2330.TW")
    intra = a.analyze(_df(last_volume_ratio=2.0), "2330.TW", intraday_volume=True)
    assert post.volume_status == VolumeStatus.HEAVY_VOLUME_DOWN
    assert intra.volume_status == VolumeStatus.INTRADAY_UNJUDGED
    assert intra.signal_score - post.signal_score == 10


# --- pipeline 判定與接線 ---------------------------------------------------------
@pytest.mark.parametrize("phase", [MarketPhase.INTRADAY, MarketPhase.LUNCH_BREAK, MarketPhase.CLOSING_AUCTION])
@pytest.mark.parametrize("scenario", ["missing_quote", "quotes_disabled", "indicators_disabled", "invalid_price"])
def test_pipeline_intraday_without_today_bar_judges_completed_volume(phase, scenario):
    """報價缺失、關閉或補 K 提早返回時，昨日完整 K 仍判縮量回調並給正常分數。"""
    p = _pipeline()
    p.config.enable_realtime_quote = scenario != "quotes_disabled"
    p.config.enable_realtime_technical_indicators = scenario != "indicators_disabled"
    hist = _df(last_date=_NOW.date() - timedelta(days=1))
    quote = None if scenario == "missing_quote" else SimpleNamespace(price=0 if scenario == "invalid_price" else 100.0)
    with patch("src.core.pipeline.infer_market_phase", return_value=phase), \
         patch("src.core.pipeline.get_market_now", return_value=_NOW):
        frame = p._build_trend_input_frame(hist, quote, "2330.TW", "tw")
        r = p._run_trend_analysis(frame, "2330.TW", {"phase": phase.value})
    pd.testing.assert_frame_equal(frame, hist)
    assert frame.iloc[-1]["date"].date() == _NOW.date() - timedelta(days=1)
    assert r.volume_status == VolumeStatus.SHRINK_VOLUME_DOWN
    assert "✅ 缩量回调，主力洗盘" in r.signal_reasons
    assert r.signal_score == p.trend_analyzer.analyze(hist, "2330.TW").signal_score
    neutral = p.trend_analyzer.analyze(hist, "2330.TW", intraday_volume=True)
    assert r.signal_score - neutral.signal_score == 5


@pytest.mark.parametrize("existing_today", [False, True])
def test_pipeline_realtime_partial_bar_still_unjudged(existing_today):
    """即時報價追加或更新今日列後，量能維持不判讀。"""
    p = _pipeline()
    last_date = _NOW.date() if existing_today else _NOW.date() - timedelta(days=1)
    hist = _df(last_date=last_date)
    hist["date"] = hist["date"].dt.date
    quote = SimpleNamespace(price=float(hist.iloc[-1]["close"]) * 0.99, volume=300.0)
    with patch("src.core.pipeline.infer_market_phase", return_value=MarketPhase.INTRADAY), \
         patch("src.core.pipeline.get_market_now", return_value=_NOW), \
         patch("src.core.pipeline.is_market_open", return_value=True):
        frame = p._build_trend_input_frame(hist, quote, "2330.TW", "tw")
        r = p._run_trend_analysis(frame, "2330.TW", {"phase": "intraday"})
    assert len(frame) == len(hist) + (0 if existing_today else 1)
    assert pd.Timestamp(frame.iloc[-1]["date"]).date() == _NOW.date()
    assert r.volume_status == VolumeStatus.INTRADAY_UNJUDGED
    assert "✅ 缩量回调，主力洗盘" not in r.signal_reasons


@pytest.mark.parametrize("date_type", [date, datetime, pd.Timestamp, str])
@pytest.mark.parametrize("days_ago", [0, 1])
def test_pipeline_uses_market_session_date_across_date_types(date_type, days_ago):
    """DB 已有今日部分列也要擋；各種日期型別都用台北場次日比較。"""
    frame = _df(last_date=_NOW.date() - timedelta(days=days_ago))
    converters = {
        date: lambda d: d.date(), datetime: lambda d: d.to_pydatetime(),
        pd.Timestamp: lambda d: d, str: lambda d: d.isoformat(),
    }
    frame["date"] = pd.Series([converters[date_type](d) for d in frame["date"]], dtype=object)
    # 台北凌晨在 UTC 仍是前一天，不可用伺服器日期代替市場日期。
    now = _NOW.replace(hour=1)
    with patch("src.core.pipeline.infer_market_phase", return_value=MarketPhase.INTRADAY), \
         patch("src.core.pipeline.get_market_now", return_value=now) as market_now:
        r = _pipeline()._run_trend_analysis(frame, "2330.TW", {"phase": "intraday"})
    assert all(call.args == ("tw",) for call in market_now.call_args_list)
    expected = VolumeStatus.INTRADAY_UNJUDGED if days_ago == 0 else VolumeStatus.SHRINK_VOLUME_DOWN
    assert r.volume_status == expected


@pytest.mark.parametrize("last_date", [None, pd.NaT, float("nan"), "invalid", "missing_column"])
def test_pipeline_unknown_last_bar_date_keeps_volume_unjudged(last_date):
    """日期無法確定時保留盤中不判讀，不把未知的部分量當完整量。"""
    frame = _df()
    if last_date == "missing_column":
        frame = frame.drop(columns="date")
    else:
        frame["date"] = frame["date"].astype(object)
        frame.loc[frame.index[-1], "date"] = last_date
    p = _pipeline()
    with patch("src.core.pipeline.infer_market_phase", return_value=MarketPhase.INTRADAY), \
         patch("src.core.pipeline.get_market_now", return_value=_NOW), \
         patch.object(p.trend_analyzer, "analyze") as analyze:
        p._run_trend_analysis(frame, "2330.TW", {"phase": "intraday"})
    assert analyze.call_args.kwargs["intraday_volume"] is True


@pytest.mark.parametrize("phase", [MarketPhase.INTRADAY, MarketPhase.LUNCH_BREAK, MarketPhase.CLOSING_AUCTION])
def test_pipeline_tw_session_phases_do_not_judge_volume(phase):
    r = _run(phase)
    assert r.volume_status == VolumeStatus.INTRADAY_UNJUDGED
    assert "✅ 缩量回调，主力洗盘" not in r.signal_reasons
    post = _run(MarketPhase.POSTMARKET)
    assert post.signal_score - r.signal_score == 5


def test_pipeline_postmarket_unchanged():
    r = _run(MarketPhase.POSTMARKET, ctx_phase="postmarket")
    assert r.volume_status == VolumeStatus.SHRINK_VOLUME_DOWN
    assert "✅ 缩量回调，主力洗盘" in r.signal_reasons


def test_pipeline_context_phase_intraday_wins_over_postmarket_clock():
    r = _run(MarketPhase.POSTMARKET, ctx_phase="intraday")
    assert r.volume_status == VolumeStatus.INTRADAY_UNJUDGED


def test_pipeline_intraday_clock_wins_over_postmarket_context_phase():
    # 呼叫端 phase 說盤後、牆鐘說盤中：任一說盤中就算盤中（與 3055c531 量比標籤同語意）
    r = _run(MarketPhase.INTRADAY, ctx_phase="postmarket")
    assert r.volume_status == VolumeStatus.INTRADAY_UNJUDGED


def test_pipeline_non_tw_code_unchanged():
    # 3055c531 的判定只管台股；非台股盤中維持原行為
    r = _run(MarketPhase.INTRADAY, code="AAPL")
    assert r.volume_status == VolumeStatus.SHRINK_VOLUME_DOWN


def test_prompt_trend_row_matches_realtime_intraday_label():
    """盤中時量比列與趨勢表不再互相矛盾：兩邊都不判縮量。"""
    p = _pipeline()
    p.config = SimpleNamespace(report_language="zh-TW")
    p.search_service = SimpleNamespace(news_window_days=3)
    with patch("src.core.pipeline.infer_market_phase", return_value=MarketPhase.INTRADAY), \
         patch("src.core.pipeline.get_market_now", return_value=_NOW):
        trend = p._run_trend_analysis(_df(), "2330.TW", {"phase": "intraday"})
        quote = SimpleNamespace(code="2330.TW", name="台積電", price=100.0, volume_ratio=None, source=None)
        enhanced = p._enhance_context(
            {"code": "2330.TW", "today": {"close": 100.0}}, quote, None, trend,
            fundamental_context={}, market_phase_context={"phase": "intraday"},
        )
    assert enhanced["realtime"]["volume_ratio_basis"] == "avg5_intraday"
    ta = enhanced["trend_analysis"]
    assert ta["volume_status"] == "盤中不判讀"
    assert "缩量回调" not in ta["volume_trend"]
    assert "✅ 缩量回调，主力洗盘" not in ta["signal_reasons"]


@pytest.mark.parametrize("phase,expected", [(MarketPhase.INTRADAY, True), (MarketPhase.POSTMARKET, False)])
def test_analyze_stock_passes_intraday_flag_to_trend_analyzer(phase, expected):
    """接線：analyze_stock 的 Step 3 真的經過盤中判定，不是直接呼叫 analyze(df, code)。"""
    from unittest.mock import MagicMock

    from src.enums import ReportType
    from tests.test_pipeline_market_phase_context import _make_pipeline
    from tests.test_pipeline_trend_adjust import _history

    pipeline = _make_pipeline(agent_mode=False, save_context_snapshot=False)
    hist = _history(_NOW.date())
    pipeline.db.get_data_range.return_value = [
        SimpleNamespace(to_dict=(lambda r=r: r.to_dict())) for _, r in hist.iterrows()
    ]
    kwargs_seen = []
    pipeline.trend_analyzer = MagicMock()
    pipeline.trend_analyzer.analyze.side_effect = lambda df, c, **kw: kwargs_seen.append(kw) or MagicMock()
    hour = 10 if phase == MarketPhase.INTRADAY else 19
    with patch("src.core.pipeline.infer_market_phase", return_value=phase), \
         patch("src.core.pipeline.get_market_now", return_value=_NOW.replace(hour=hour)), \
         patch("market_data.market_repo.front_adjust_multipliers", return_value={}), \
         patch("market_data.db.get_engine", return_value=object()):
        pipeline.analyze_stock("6669.TW", ReportType.SIMPLE, "q-b2",
                               current_time=_NOW.replace(hour=hour))
    assert len(kwargs_seen) == 1
    assert kwargs_seen[0].get("intraday_volume") is expected
