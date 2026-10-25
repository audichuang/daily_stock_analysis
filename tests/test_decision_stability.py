# -*- coding: utf-8 -*-
"""Tests for structure-aware decision stability calibration."""

from datetime import date
from types import SimpleNamespace

import pytest

import src.analyzer as analyzer_module
from src.analyzer import AnalysisResult, _capital_flow_bias, stabilize_decision_with_structure
from src.schemas.decision_action import build_action_fields
from src.schemas.decision_scale import extract_decision_guardrail_reason


def _result(
    *,
    decision_type: str,
    operation_advice: str,
    score: int,
    current_price: float,
    change_pct: float = 0.0,
) -> AnalysisResult:
    return AnalysisResult(
        code="002812",
        name="恩捷股份",
        sentiment_score=score,
        trend_prediction="看多" if decision_type == "buy" else "看空",
        operation_advice=operation_advice,
        decision_type=decision_type,
        report_language="zh",
        current_price=current_price,
        change_pct=change_pct,
        dashboard={
            "core_conclusion": {"one_sentence": "原始结论"},
            "data_perspective": {
                "price_position": {
                    "current_price": current_price,
                    "support_level": 30.0,
                    "resistance_level": 34.0,
                }
            },
        },
    )


def _fund_flow(main: float, five_day: float = 0.0, ten_day: float = 0.0) -> dict:
    return {
        "capital_flow": {
            "status": "ok",
            "data": {
                "stock_flow": {
                    "main_net_inflow": main,
                    "inflow_5d": five_day,
                    "inflow_10d": ten_day,
                }
            },
        }
    }


def _unsupported_fund_flow() -> dict:
    return {"capital_flow": {"status": "not_supported", "data": {}}}


def _failed_fund_flow() -> dict:
    # 資料源存在但抓取失敗（_build_fundamental_block("failed", {}, ...) 的形狀）
    return {"capital_flow": {"status": "failed", "data": {}}}


def _unsupported_fund_flow_caps() -> dict:
    return {"capital_flow": {"status": "NOT_SUPPORTED", "data": {"stock_flow": {"main_net_inflow": 0}}}}


def test_capital_flow_bias_is_unavailable_when_stock_flow_data_is_missing() -> None:
    assert _capital_flow_bias(_unsupported_fund_flow()) == "unavailable"
    assert _capital_flow_bias({"capital_flow": {"status": "ok", "data": {}}}) == "unavailable"


def test_capital_flow_bias_is_neutral_when_missing_main_windows_conflict() -> None:
    context = {
        "capital_flow": {
            "data": {
                "stock_flow": {
                    "inflow_5d": 2_000_000,
                    "inflow_10d": -1_000_000,
                }
            }
        }
    }

    assert _capital_flow_bias(context) == "neutral"


def test_capital_flow_bias_is_neutral_when_main_conflicts_with_windows() -> None:
    context = _fund_flow(main=-500_000, five_day=1_200_000, ten_day=2_000_000)

    assert _capital_flow_bias(context) == "neutral"


def test_downgrades_buy_near_resistance_without_fund_confirmation() -> None:
    result = _result(
        decision_type="buy",
        operation_advice="买入",
        score=65,
        current_price=33.4,
    )

    stabilize_decision_with_structure(
        result,
        SimpleNamespace(support_levels=[30.0], resistance_levels=[34.0]),
        _fund_flow(main=-1_000_000, five_day=-2_000_000),
    )

    assert result.decision_type == "hold"
    assert result.sentiment_score <= 59
    assert result.operation_advice == "震荡观望"
    assert result.dashboard["decision_stability"]["applied"] is True
    assert "不宜仅因短线反弹追买" in result.risk_warning
    assert result.dashboard["core_conclusion"]["signal_type"] == "🟡持有观望"


def test_downgrades_buy_mid_range_with_neutral_fund_flow() -> None:
    result = _result(
        decision_type="buy",
        operation_advice="买入",
        score=66,
        current_price=32.0,
    )

    stabilize_decision_with_structure(
        result,
        SimpleNamespace(support_levels=[30.0], resistance_levels=[34.0]),
        _fund_flow(main=0, five_day=0, ten_day=0),
    )

    assert result.decision_type == "hold"
    assert result.sentiment_score <= 59
    assert result.operation_advice == "震荡观望"
    assert "资金流不明确" in result.risk_warning


def test_downgrades_buy_when_capital_flow_is_unavailable() -> None:
    buy_result = _result(
        decision_type="buy",
        operation_advice="买入",
        score=66,
        current_price=32.0,
    )
    sell_result = _result(
        decision_type="sell",
        operation_advice="卖出",
        score=30,
        current_price=30.4,
        change_pct=-2.1,
    )

    stabilize_decision_with_structure(
        buy_result,
        SimpleNamespace(support_levels=[30.0], resistance_levels=[34.0]),
        _failed_fund_flow(),
    )
    stabilize_decision_with_structure(
        sell_result,
        SimpleNamespace(support_levels=[30.0], resistance_levels=[34.0]),
        _unsupported_fund_flow(),
    )

    assert buy_result.decision_type == "hold"
    assert buy_result.operation_advice == "持有观察"
    assert buy_result.confidence_level == "低"
    assert buy_result.sentiment_score <= 59
    assert buy_result.dashboard["decision_stability"]["applied"] is True
    assert "买入结论缺少资金面确认" in buy_result.dashboard["decision_stability"]["reason"]
    assert buy_result.dashboard["core_conclusion"]["signal_type"] == "🟡持有观望"
    assert sell_result.decision_type == "sell"
    assert sell_result.operation_advice == "卖出"
    assert sell_result.dashboard["decision_stability"]["applied"] is False
    assert "未使用资金流校准" in sell_result.dashboard["decision_stability"]["reason"]


def test_downgrades_buy_when_capital_flow_values_are_na() -> None:
    result = _result(
        decision_type="buy",
        operation_advice="买入",
        score=66,
        current_price=33.0,
    )

    stabilize_decision_with_structure(
        result,
        SimpleNamespace(support_levels=[30.0], resistance_levels=[34.0]),
        {
            "capital_flow": {
                "status": "ok",
                "data": {
                    "stock_flow": {
                        "main_net_inflow": "N/A",
                        "inflow_5d": "N/A",
                        "inflow_10d": "N/A",
                    }
                },
            }
        },
    )

    assert result.decision_type == "hold"
    assert result.operation_advice == "持有观察"
    assert result.dashboard["decision_stability"]["applied"] is True
    assert "资金流数据缺失" in result.dashboard["decision_stability"]["capital_flow_status"]


def test_downgrades_buy_advice_when_decision_type_is_hold_and_capital_flow_unavailable() -> None:
    result = _result(
        decision_type="hold",
        operation_advice="建议买入",
        score=68,
        current_price=32.0,
    )

    stabilize_decision_with_structure(
        result,
        SimpleNamespace(support_levels=[30.0], resistance_levels=[34.0]),
        _failed_fund_flow(),
    )

    assert result.decision_type == "hold"
    assert result.operation_advice == "持有观察"
    assert result.sentiment_score <= 59
    assert result.dashboard["decision_stability"]["applied"] is True
    assert "买入结论缺少资金面确认" in result.dashboard["decision_stability"]["reason"]


@pytest.mark.usefixtures("tw_institution_path")
def test_not_supported_capital_flow_does_not_downgrade_buy_case_insensitive() -> None:
    # 「此市場無資金流資料源」不是「資料失敗」：不降級，只標記未校準
    buy_result = _result(
        decision_type="buy",
        operation_advice="买入",
        score=66,
        current_price=32.0,
    )
    buy_result.code = "AAPL"

    stabilize_decision_with_structure(
        buy_result,
        SimpleNamespace(support_levels=[30.0], resistance_levels=[34.0]),
        _unsupported_fund_flow_caps(),
    )

    assert buy_result.decision_type == "buy"
    assert buy_result.operation_advice == "买入"
    assert buy_result.sentiment_score == 66
    assert buy_result.dashboard["decision_stability"]["applied"] is False
    assert "暂不支持" in str(buy_result.dashboard["decision_stability"]["capital_flow_status"])


@pytest.fixture
def tw_institution_path(monkeypatch):
    """顯式關掉 CAPITAL_FLOW_NOT_SUPPORTED_DOWNGRADE，啟用 not_supported 不降級＋台股法人推導的新路徑。"""
    monkeypatch.setattr(
        analyzer_module,
        "get_config",
        lambda: SimpleNamespace(capital_flow_not_supported_downgrade=False),
    )
    monkeypatch.setattr(
        analyzer_module,
        "_tw_institution_accepted_sessions",
        lambda: {date(2026, 10, 20), date(2026, 10, 21)},
    )


def _tw_result(*, current_price: float = 32.0, code: str = "2330.TW") -> AnalysisResult:
    result = _result(decision_type="buy", operation_advice="买入", score=70, current_price=current_price)
    result.code = code
    return result


def _tw_context(foreign: float, trust: float, inst_status: str = "ok", inst_date: str = "20261021") -> dict:
    return {
        "capital_flow": {"status": "not_supported", "data": {}},
        "institution": {
            "status": inst_status,
            "data": {
                "foreign_net": foreign,
                "trust_net": trust,
                "dealer_net": 0,
                "total_net": foreign + trust,
                "unit": "shares",
                "date": inst_date,
            },
        },
    }


_LEVELS = SimpleNamespace(support_levels=[30.0], resistance_levels=[34.0])


@pytest.mark.usefixtures("tw_institution_path")
@pytest.mark.parametrize("scenario", ["unavailable", "near_resistance", "outflow", "tw_institution"])
@pytest.mark.parametrize("score", [68, 55])
@pytest.mark.parametrize("initial_action", ["hold", "buy"])
def test_structure_guardrail_handles_hold_score_band_before_final_alignment(scenario, score, initial_action) -> None:
    result = _result(
        decision_type="hold", operation_advice="持有觀察", score=score,
        current_price=31.0 if scenario == "outflow" else 33.4,
    )
    result.action = initial_action
    context = {
        "unavailable": _failed_fund_flow(),
        "near_resistance": _fund_flow(main=0),
        "outflow": _fund_flow(main=-1_000_000),
        "tw_institution": _tw_context(-1_000_000, -200_000),
    }[scenario]
    if scenario == "tw_institution":
        result.code = "2330.TW"

    stabilize_decision_with_structure(result, _LEVELS, context)

    reason = extract_decision_guardrail_reason({"dashboard": result.dashboard})
    if score == 68:
        assert result.sentiment_score == 59
        assert reason
        calibration = result.dashboard["decision_score_calibration"]
        assert calibration["raw_score"] == 68
        assert calibration["guardrail_reason"]
        assert result.dashboard["decision_stability"]["applied"] is True
        assert build_action_fields(
            operation_advice=result.operation_advice,
            explicit_action=result.action,
            sentiment_score=result.sentiment_score,
            guardrail_reason=reason,
            align_with_score=True,
        )["action"] in {"hold", "watch"}
    else:
        assert result.sentiment_score == 55
        assert result.operation_advice == "持有觀察"
        assert "decision_score_calibration" not in result.dashboard
        assert not result.dashboard.get("decision_stability", {}).get("applied")
        assert reason is None
    assert result.decision_type == "hold"


@pytest.mark.parametrize("scenario", ["near_resistance", "outflow"])
def test_structure_guardrail_leaves_sell_with_buy_band_score_on_sell_path(scenario) -> None:
    # 反向檢查：分數區間只補 hold 的洞，賣出＋高分不能被送進買入校準
    result = _result(
        decision_type="sell", operation_advice="卖出", score=68,
        current_price=31.0 if scenario == "outflow" else 33.4,
    )
    context = _fund_flow(main=-1_000_000) if scenario == "outflow" else _fund_flow(main=0)

    stabilize_decision_with_structure(result, _LEVELS, context)

    assert result.decision_type == "sell"
    assert result.operation_advice == "卖出"
    assert result.sentiment_score == 68
    assert "decision_score_calibration" not in result.dashboard


@pytest.mark.usefixtures("tw_institution_path")
def test_tw_not_supported_with_institution_inflow_keeps_buy() -> None:
    # 中段價位 + 外資投信同買 → inflow，不觸發任何結構降級
    result = _tw_result()

    stabilize_decision_with_structure(result, _LEVELS, _tw_context(1_000_000, 200_000))

    assert result.decision_type == "buy"
    assert result.operation_advice == "买入"
    assert result.sentiment_score == 70


@pytest.mark.usefixtures("tw_institution_path")
def test_tw_institution_inflow_near_resistance_keeps_buy() -> None:
    # 近壓力只有 inflow 能放行；證明 inflow 有實際接上既有邏輯而非僅僅跳過
    result = _tw_result(current_price=33.4)

    stabilize_decision_with_structure(result, _LEVELS, _tw_context(1_000_000, 200_000))

    assert result.decision_type == "buy"


@pytest.mark.usefixtures("tw_institution_path")
def test_tw_institution_outflow_downgrades_buy_via_existing_outflow_rule() -> None:
    result = _tw_result()

    stabilize_decision_with_structure(result, _LEVELS, _tw_context(-1_000_000, -200_000))

    assert result.decision_type == "hold"
    assert result.operation_advice == "震荡观望"
    assert result.sentiment_score <= 59
    assert result.dashboard["decision_stability"]["capital_flow_bias"] == "outflow"


@pytest.mark.usefixtures("tw_institution_path")
def test_tw_institution_mixed_is_neutral_and_mid_range_rule_applies() -> None:
    result = _tw_result()

    stabilize_decision_with_structure(result, _LEVELS, _tw_context(1_000_000, -200_000))

    assert result.decision_type == "hold"
    assert result.dashboard["decision_stability"]["capital_flow_bias"] == "neutral"


@pytest.mark.usefixtures("tw_institution_path")
def test_tw_not_supported_without_institution_marks_unavailable_without_downgrade() -> None:
    result = _tw_result()

    stabilize_decision_with_structure(result, _LEVELS, _tw_context(0, 0, inst_status="failed"))

    assert result.decision_type == "buy"
    assert result.sentiment_score == 70
    assert result.dashboard["decision_stability"]["applied"] is False
    assert result.dashboard["decision_stability"]["capital_flow_bias"] == "unavailable"


@pytest.mark.usefixtures("tw_institution_path")
def test_tw_failed_capital_flow_still_downgrades_even_with_institution_inflow() -> None:
    # 過度修正守門：資料源存在但失敗時，不得拿法人資料替代而放行
    result = _tw_result()
    context = _tw_context(1_000_000, 200_000)
    context["capital_flow"] = {"status": "failed", "data": {}}

    stabilize_decision_with_structure(result, _LEVELS, context)

    assert result.decision_type == "hold"
    assert result.operation_advice == "持有观察"
    assert result.sentiment_score <= 59


@pytest.mark.usefixtures("tw_institution_path")
def test_non_tw_code_ignores_institution_when_capital_flow_not_supported() -> None:
    # 法人推導只限台股；非台股 not_supported 一律只標記未校準
    result = _tw_result(code="AAPL")

    stabilize_decision_with_structure(result, _LEVELS, _tw_context(-1_000_000, -200_000))

    assert result.decision_type == "buy"
    assert result.dashboard["decision_stability"]["capital_flow_bias"] == "unavailable"


@pytest.mark.usefixtures("tw_institution_path")
def test_us_not_supported_capital_flow_does_not_downgrade_buy() -> None:
    result = _tw_result(code="AAPL")

    stabilize_decision_with_structure(result, _LEVELS, _unsupported_fund_flow())

    assert result.decision_type == "buy"
    assert result.sentiment_score == 70
    assert result.dashboard["decision_stability"]["applied"] is False


@pytest.mark.parametrize("config", [
    SimpleNamespace(capital_flow_not_supported_downgrade=True),
    SimpleNamespace(),  # 設定物件沒有這個欄位時也要回到舊行為
], ids=["explicit_true", "attr_missing"])
@pytest.mark.parametrize("code", ["AAPL", "2330.TW"])
def test_default_flag_keeps_old_not_supported_downgrade(monkeypatch, code, config) -> None:
    monkeypatch.setattr(analyzer_module, "get_config", lambda: config)
    result = _tw_result(code=code)

    stabilize_decision_with_structure(result, _LEVELS, _tw_context(1_000_000, 200_000))

    assert result.decision_type == "hold"
    assert result.operation_advice == "持有观察"
    assert result.sentiment_score <= 59


def test_skips_downgrade_when_only_generic_risk_warning_and_sell_near_support() -> None:
    result = _result(
        decision_type="sell",
        operation_advice="卖出",
        score=30,
        current_price=30.4,
        change_pct=1.0,
    )
    result.risk_warning = "注意常见回撤风险，建议关注仓位。"

    stabilize_decision_with_structure(
        result,
        SimpleNamespace(support_levels=[30.0], resistance_levels=[34.0]),
        _fund_flow(main=500_000, five_day=300_000),
    )

    assert result.decision_type == "hold"
    assert result.operation_advice == "洗盘观察"
    assert "价格贴近支撑且未见资金持续流出" in result.risk_warning


def test_stability_can_infer_decision_from_natural_chinese_phrases_in_analyzer_path() -> None:
    result = _result(
        decision_type="建议卖出",
        operation_advice="建议卖出",
        score=30,
        current_price=30.4,
        change_pct=1.0,
    )

    stabilize_decision_with_structure(
        result,
        SimpleNamespace(support_levels=[30.0], resistance_levels=[34.0]),
        _fund_flow(main=500_000, five_day=300_000),
    )

    assert result.decision_type == "hold"
    assert result.operation_advice == "洗盘观察"
    assert result.dashboard["decision_stability"]["applied"] is True


def test_downgrades_sell_near_support_without_sustained_outflow() -> None:
    result = _result(
        decision_type="sell",
        operation_advice="卖出",
        score=30,
        current_price=30.4,
        change_pct=-2.1,
    )

    stabilize_decision_with_structure(
        result,
        SimpleNamespace(support_levels=[30.0], resistance_levels=[34.0]),
        _fund_flow(main=800_000, five_day=1_200_000),
    )

    assert result.decision_type == "hold"
    assert result.sentiment_score >= 45
    assert result.operation_advice == "洗盘观察"
    assert "不宜仅因单日下跌直接卖出" in result.risk_warning


def test_preserves_sell_signal_when_significant_risk_exists_near_support() -> None:
    result = _result(
        decision_type="sell",
        operation_advice="卖出",
        score=30,
        current_price=30.4,
        change_pct=-2.1,
    )
    result.risk_warning = "重大利空消息：公司发布重大减持计划"
    result.dashboard["intelligence"] = {"risk_alerts": ["股东高位减持预告"]}

    stabilize_decision_with_structure(
        result,
        SimpleNamespace(support_levels=[30.0], resistance_levels=[34.0]),
        _fund_flow(main=800_000, five_day=1_200_000),
    )

    assert result.decision_type == "sell"
    assert result.operation_advice == "卖出"


def test_refines_hold_pullback_near_support_as_shakeout_watch() -> None:
    result = _result(
        decision_type="hold",
        operation_advice="持有",
        score=52,
        current_price=30.5,
        change_pct=-1.6,
    )

    stabilize_decision_with_structure(
        result,
        SimpleNamespace(support_levels=[30.0], resistance_levels=[34.0]),
        _fund_flow(main=0, five_day=500_000),
    )

    assert result.decision_type == "hold"
    assert result.operation_advice == "洗盘观察"
    assert "更适合按洗盘观察处理" in result.risk_warning


@pytest.mark.usefixtures("tw_institution_path")
def test_tw_sell_near_support_unchanged_when_capital_flow_not_supported() -> None:
    # 法人代入只限買入：台股賣出（紅 K、近支撐、法人同買）仍維持賣出，不被改成洗盤觀察
    result = _result(decision_type="sell", operation_advice="卖出", score=30, current_price=30.4, change_pct=-2.1)
    result.code = "2330.TW"

    stabilize_decision_with_structure(result, _LEVELS, _tw_context(1_000_000, 200_000))

    assert result.decision_type == "sell"
    assert result.operation_advice == "卖出"
    assert result.sentiment_score == 30
    assert result.dashboard["decision_stability"]["applied"] is False
    assert result.dashboard["decision_stability"]["capital_flow_bias"] == "unavailable"


@pytest.mark.usefixtures("tw_institution_path")
def test_tw_hold_with_buy_advice_uses_institution_bias() -> None:
    # decision_type=hold 但建議寫「建议买入」也算買入結論：上櫃代碼、法人一買一賣 → neutral，走區間中段校準
    result = _result(decision_type="hold", operation_advice="建议买入", score=58, current_price=32.0)
    result.code = "6488.TWO"

    stabilize_decision_with_structure(result, _LEVELS, _tw_context(1_000_000, -200_000))

    assert result.dashboard["decision_stability"]["capital_flow_bias"] == "neutral"
    assert result.dashboard["decision_stability"]["applied"] is True


@pytest.mark.usefixtures("tw_institution_path")
def test_cn_not_supported_capital_flow_still_downgrades_buy() -> None:
    # A 股有資金流資料源：akshare 抓不到時也標 not_supported（實為失敗），仍須降級
    result = _result(decision_type="buy", operation_advice="买入", score=66, current_price=32.0)

    stabilize_decision_with_structure(result, _LEVELS, _unsupported_fund_flow())

    assert result.code == "002812"
    assert result.decision_type == "hold"
    assert result.operation_advice == "持有观察"
    assert result.sentiment_score <= 59


@pytest.mark.parametrize("env, expected", [({}, True), ({"CAPITAL_FLOW_NOT_SUPPORTED_DOWNGRADE": "false"}, False)])
def test_config_capital_flow_not_supported_downgrade_defaults_to_old_behavior(env, expected) -> None:
    # 使用者未選擇前預設維持舊行為（not_supported 照舊降級）；只有顯式設 false 才走新路徑
    from unittest.mock import patch

    from src.config import Config

    assert Config.__dataclass_fields__["capital_flow_not_supported_downgrade"].default is True
    with patch("src.config.setup_env"), patch.object(Config, "_parse_litellm_yaml", return_value=[]), \
            patch.dict("os.environ", env, clear=True):
        cfg = Config._load_from_env()
    assert cfg.capital_flow_not_supported_downgrade is expected


@pytest.mark.usefixtures("tw_institution_path")
@pytest.mark.parametrize("inst_date", ["20240105", "", "not-a-date"])
def test_tw_stale_or_undated_institution_is_ignored(inst_date) -> None:
    # 凍結的舊法人賣超不得把買入壓成持有：資料日不在最近兩場就當沒有法人資料
    result = _tw_result()

    stabilize_decision_with_structure(result, _LEVELS, _tw_context(-1_000_000, -200_000, inst_date=inst_date))

    assert result.decision_type == "buy"
    assert result.sentiment_score == 70
    assert result.dashboard["decision_stability"]["applied"] is False


@pytest.mark.usefixtures("tw_institution_path")
def test_tw_previous_session_institution_is_still_used() -> None:
    # 收盤後到 T86 發布前，資料日是前一場：仍採用（避免把新鮮度收得過嚴）
    result = _tw_result()

    stabilize_decision_with_structure(result, _LEVELS, _tw_context(-1_000_000, -200_000, inst_date="20261020"))

    assert result.dashboard["decision_stability"]["capital_flow_bias"] == "outflow"


def test_tw_institution_rejected_when_calendar_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        analyzer_module, "get_config", lambda: SimpleNamespace(capital_flow_not_supported_downgrade=False)
    )
    monkeypatch.setattr(analyzer_module, "_tw_institution_accepted_sessions", lambda: None)
    result = _tw_result()

    stabilize_decision_with_structure(result, _LEVELS, _tw_context(-1_000_000, -200_000))

    assert result.sentiment_score == 70
    assert result.dashboard["decision_stability"]["applied"] is False


def test_accepted_sessions_are_last_two_completed_sessions(monkeypatch) -> None:
    import pandas as pd
    import src.core.trading_calendar as cal

    monkeypatch.setattr(cal, "get_effective_trading_date", lambda market: date(2026, 10, 21))
    monkeypatch.setattr(
        cal, "get_trading_dates",
        lambda market, s, e: pd.DatetimeIndex(["2026-10-16", "2026-10-19", "2026-10-20", "2026-10-21"]),
    )
    assert analyzer_module._tw_institution_accepted_sessions() == {date(2026, 10, 20), date(2026, 10, 21)}

    # 日曆查不到或最後一場不是有效交易日 → 不可判定
    monkeypatch.setattr(cal, "get_trading_dates", lambda market, s, e: None)
    assert analyzer_module._tw_institution_accepted_sessions() is None
    monkeypatch.setattr(cal, "get_trading_dates", lambda market, s, e: pd.DatetimeIndex(["2026-10-17", "2026-10-20"]))
    assert analyzer_module._tw_institution_accepted_sessions() is None
