# -*- coding: utf-8 -*-
"""Tests for Issue #1381 daily market context decision guardrail."""

from __future__ import annotations

import pytest

from src.analyzer import AnalysisResult
from src.daily_market_context_guardrail import apply_daily_market_context_guardrail


def _result() -> AnalysisResult:
    return AnalysisResult(
        code="600519",
        name="贵州茅台",
        sentiment_score=82,
        trend_prediction="看多",
        operation_advice="立即买入并积极加仓",
        decision_type="buy",
        confidence_level="高",
        analysis_summary="个股信号强势",
        dashboard={
            "operation_advice": "立即买入并积极加仓",
            "decision_type": "buy",
            "core_conclusion": {
                "one_sentence": "立即买入并积极加仓",
                "position_advice": {
                    "no_position": "立即买入并积极加仓",
                    "has_position": "继续加仓",
                },
            },
            "battle_plan": {
                "position_strategy": {
                    "suggested_position": "满仓买入",
                    "entry_plan": "突破后立即买入",
                    "risk_control": "回踩继续加仓",
                },
            },
            "phase_decision": {
                "data_limitations": [],
                "confidence_reason": "趋势强",
            },
        },
    )


def test_conservative_market_context_softens_aggressive_buy() -> None:
    result = _result()

    adjustments = apply_daily_market_context_guardrail(
        result,
        daily_market_context={
            "region": "cn",
            "trade_date": "2026-06-06",
            "summary": "大盘退潮，高风险，建议观望，仓位上限30%。",
            "risk_tags": ["high_risk", "low_position_cap"],
        },
        report_language="zh",
    )

    assert "daily_market_context_buy_softened" in adjustments
    assert result.decision_type == "hold"
    assert result.operation_advice == "观望"
    assert len(result.operation_advice) <= 20
    assert result.confidence_level == "中"
    assert result.sentiment_score == 52
    assert result.dashboard["operation_advice"] == result.operation_advice
    assert result.dashboard["decision_type"] == "hold"
    assert result.dashboard["sentiment_score"] == 52
    core = result.dashboard["core_conclusion"]
    assert core["one_sentence"] == result.operation_advice
    assert core["position_advice"] == {
        "no_position": "大盘环境偏谨慎，暂不开新仓，等待风险缓解或确认信号。",
        "has_position": "仅保留小仓观察，暂不扩大仓位；若跌破风控位优先降低仓位。",
    }
    position_strategy = result.dashboard["battle_plan"]["position_strategy"]
    assert position_strategy == {
        "suggested_position": "小仓/低仓位",
        "entry_plan": "大盘环境偏谨慎，暂不开新仓，等待风险缓解或确认信号。",
        "risk_control": "大盘风险未缓解前不扩大仓位，严格控制回撤。",
    }
    phase_decision = result.dashboard["phase_decision"]
    assert any("大盘环境" in item for item in phase_decision["data_limitations"])
    assert "大盘环境" in phase_decision["confidence_reason"]


def test_position_cap_only_market_context_softens_aggressive_buy() -> None:
    cases = [
        ("zh", "市场震荡，仓位不超过30%。", "立即买入并积极加仓", "高", "观望"),
        ("en", "Major indices are mixed. Position limit 30%.", "Buy now and add aggressively.", "High", "Watch"),
    ]
    for language, summary, advice, confidence, expected_advice in cases:
        result = _result()
        result.operation_advice = advice
        result.confidence_level = confidence

        adjustments = apply_daily_market_context_guardrail(
            result,
            daily_market_context={
                "region": "us" if language == "en" else "cn",
                "trade_date": "2026-06-06",
                "summary": summary,
                "risk_tags": [],
                "position_cap": "30%",
            },
            report_language=language,
        )

        assert "daily_market_context_buy_softened" in adjustments
        assert result.decision_type == "hold"
        assert result.operation_advice == expected_advice


def test_neutral_market_context_leaves_hold_unchanged() -> None:
    result = _result()
    result.decision_type = "hold"
    result.operation_advice = "持有观察"
    result.confidence_level = "中"

    adjustments = apply_daily_market_context_guardrail(
        result,
        daily_market_context={
            "region": "cn",
            "trade_date": "2026-06-06",
            "summary": "市场震荡，结构分化。",
            "risk_tags": [],
        },
        report_language="zh",
    )

    assert adjustments == []
    assert result.decision_type == "hold"
    assert result.operation_advice == "持有观察"


def test_conservative_tag_alone_no_longer_softens_buy() -> None:
    """「謹慎／觀望」是中性措辭，單獨出現不該把買進壓成觀望。"""
    result = _result()

    adjustments = apply_daily_market_context_guardrail(
        result,
        daily_market_context={
            "region": "tw",
            "trade_date": "2026-10-05",
            "summary": "加權指數創高，留意短線謹慎觀望。",
            "risk_tags": ["conservative"],
        },
        report_language="zh",
    )

    assert adjustments == []
    assert result.decision_type == "buy"
    assert result.sentiment_score == 82



@pytest.mark.parametrize(
    "risk_tags,position_cap",
    [
        (["high_risk"], ""),
        (["market_cooling"], ""),
        (["low_position_cap"], ""),
        ([], "30%"),
    ],
)
def test_each_remaining_trigger_alone_still_softens_buy(risk_tags, position_cap) -> None:
    """收窄後剩下的每條觸發路徑都要單獨有效：摘要用中性措辭，避免被文字路徑救回。"""
    result = _result()

    adjustments = apply_daily_market_context_guardrail(
        result,
        daily_market_context={
            "region": "tw",
            "trade_date": "2026-10-05",
            "summary": "加權指數震盪整理。",
            "risk_tags": risk_tags,
            "position_cap": position_cap,
        },
        report_language="zh",
    )

    assert "daily_market_context_buy_softened" in adjustments
    assert result.decision_type == "hold"


_RISKY_CONTEXT = {"summary": "大盘退潮，高风险。", "risk_tags": ["high_risk"]}


def test_softening_persists_pre_guardrail_score_for_shadow_eval() -> None:
    # 護欄前的 LLM 原判要落庫，scripts/shadow_buy_eval.py 才數得到被大盤護欄壓掉的買進
    result = _result()

    apply_daily_market_context_guardrail(result, daily_market_context=_RISKY_CONTEXT, report_language="zh")

    calibration = result.dashboard["decision_score_calibration"]
    assert calibration["raw_score"] == 82
    assert calibration["raw_decision_type"] == "buy"
    assert calibration["canonical_decision_type"] == "buy"
    assert calibration["adjusted_score"] == 52 == result.sentiment_score
    assert calibration["final_action"] == "hold"
    assert "大盘环境" in calibration["guardrail_reason"]


def test_softening_keeps_earlier_guardrail_raw_score_and_updates_adjusted() -> None:
    # 前一個護欄（R1）已記下 LLM 原分 70：不得被本護欄看到的中間分數覆蓋，但 adjusted 要更新
    result = _result()
    result.sentiment_score = 59
    result.dashboard["decision_score_calibration"] = {
        "raw_score": 70, "canonical_decision_type": "buy", "adjusted_score": 59,
        "final_action": "watch", "guardrail_reason": "R1 原因",
    }

    apply_daily_market_context_guardrail(result, daily_market_context=_RISKY_CONTEXT, report_language="zh")

    calibration = result.dashboard["decision_score_calibration"]
    assert calibration["raw_score"] == 70
    assert "raw_decision_type" not in calibration
    assert calibration["guardrail_reason"] == "R1 原因"
    assert calibration["adjusted_score"] == 52
    # final_action 也要跟著本護欄更新，否則影子評估的最終動作會停在 R1
    assert calibration["final_action"] == "hold"


def test_softening_fills_raw_score_when_calibration_has_only_llm_reason() -> None:
    # LLM 自述降級時 _parse_response 只放 guardrail_reason：仍要補上 raw_score
    result = _result()
    result.dashboard["decision_score_calibration"] = {"guardrail_reason": "LLM 自述"}

    apply_daily_market_context_guardrail(result, daily_market_context=_RISKY_CONTEXT, report_language="zh")

    calibration = result.dashboard["decision_score_calibration"]
    assert calibration["raw_score"] == 82
    assert calibration["guardrail_reason"] == "LLM 自述"


def test_unsoftened_buy_records_no_calibration() -> None:
    # 反向：護欄沒觸發就不能記，否則影子評估會把正常報告算成「被護欄降級」
    result = _result()

    assert apply_daily_market_context_guardrail(
        result, daily_market_context={"summary": "指數震盪。"}, report_language="zh"
    ) == []
    assert "decision_score_calibration" not in result.dashboard


_HIGH_RISK_TW = {"region": "tw", "trade_date": "2026-10-05", "summary": "大盤高風險。", "risk_tags": ["high_risk"]}



_HIGH_RISK_TW = {"region": "tw", "trade_date": "2026-10-05", "summary": "大盤高風險。", "risk_tags": ["high_risk"]}
_LANGS = ["zh", "zh-TW", "en", "ko"]


def _typed(decision_type: str, advice: str, language: str = "zh-TW") -> AnalysisResult:
    result = _result()
    result.decision_type = decision_type
    result.operation_advice = advice
    result.report_language = language
    return result


_ADVERSARIAL_ADVICE = [
    "建議買進", "逢低加碼", "立即買入並積極加倉", "不宜追高但可分批買入", "沒有理由不加倉", "何不加倉",
    "Buy now and add aggressively.", "즉시 매수",
    "減碼，跌破500再進場", "減倉，待站回MA5後再分批買進", "賣出，回測500可再買進",
    "Reduce; re-enter after reclaiming MA5", "비중 축소, 지지 확인 후 재매수",
]


@pytest.mark.parametrize("language", _LANGS)
@pytest.mark.parametrize("decision_type", ["hold", "sell"])
@pytest.mark.parametrize("advice", _ADVERSARIAL_ADVICE)
def test_non_buy_decision_type_is_never_softened_whatever_the_text(language, decision_type, advice) -> None:
    result = _typed(decision_type, advice, language)

    adjustments = apply_daily_market_context_guardrail(
        result, daily_market_context=_RISKY_CONTEXT, report_language=language
    )

    assert adjustments == []
    assert result.decision_type == decision_type
    assert result.operation_advice == advice
    assert result.sentiment_score == 82
    assert result.confidence_level == "高"
    assert "decision_score_calibration" not in result.dashboard


@pytest.mark.parametrize("language,expected", [("zh", "观望"), ("zh-TW", "觀望"), ("en", "Watch"), ("ko", None)])
@pytest.mark.parametrize("advice", [
    "立即买入", "暫不加倉，繼續持有觀察", "不建議買入", "No buy now; avoid adding.", "매수하지 마세요",
])
def test_buy_decision_type_is_always_softened_whatever_the_text(language, expected, advice) -> None:
    from src.report_language import localize_operation_advice

    result = _typed("buy", advice, language)

    adjustments = apply_daily_market_context_guardrail(
        result, daily_market_context=_RISKY_CONTEXT, report_language=language
    )

    assert "daily_market_context_buy_softened" in adjustments
    assert result.decision_type == "hold"
    assert result.operation_advice == localize_operation_advice("观望", language)
    if expected:
        assert result.operation_advice == expected
    assert result.confidence_level != "高"
    assert result.sentiment_score <= 52
    assert result.dashboard["decision_type"] == "hold"
    assert result.dashboard["decision_score_calibration"]["raw_decision_type"] == "buy"


def test_score_lifted_action_buy_does_not_trigger() -> None:
    # Prod id 125 (2317.TW): LLM said hold/watch, score alignment lifted action to buy
    result = _typed("hold", "觀望", "zh-TW")
    result.sentiment_score = 62
    result.action = "buy"

    adjustments = apply_daily_market_context_guardrail(
        result, daily_market_context=_HIGH_RISK_TW, report_language="zh-TW"
    )

    assert adjustments == []
    assert result.sentiment_score == 62
    assert result.decision_type == "hold"


@pytest.mark.parametrize("context", [
    {"summary": "指數震盪。", "risk_tags": ["conservative"]},
    {"summary": "指數震盪。", "risk_tags": []},
    {"summary": "加權指數創高，留意短線謹慎觀望。"},
])
def test_buy_without_real_risk_context_is_not_softened(context) -> None:
    result = _typed("buy", "建議買進")

    assert apply_daily_market_context_guardrail(result, daily_market_context=context, report_language="zh-TW") == []
    assert result.decision_type == "buy"


@pytest.mark.parametrize("decision_type", ["", "unknown"])
@pytest.mark.parametrize("advice", ["买入", "Buy"])
def test_fallback_to_shared_advice_map_when_decision_type_invalid(decision_type, advice) -> None:
    result = _typed(decision_type, advice, "zh")

    adjustments = apply_daily_market_context_guardrail(
        result, daily_market_context=_RISKY_CONTEXT, report_language="zh"
    )

    assert "daily_market_context_buy_softened" in adjustments


@pytest.mark.parametrize("advice", ["減碼，跌破500再進場", "觀望", "隨便寫的文字"])
def test_fallback_does_not_treat_unrecognised_text_as_buy(advice) -> None:
    result = _typed("", advice, "zh-TW")

    assert apply_daily_market_context_guardrail(
        result, daily_market_context=_RISKY_CONTEXT, report_language="zh-TW"
    ) == []
    assert result.operation_advice == advice
