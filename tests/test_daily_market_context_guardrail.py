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


def test_conservative_market_context_does_not_soften_negative_buy_language() -> None:
    result = _result()
    result.decision_type = "buy"
    result.operation_advice = "暂不加仓，继续持有观察。"
    result.confidence_level = "高"

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

    assert adjustments == []
    assert result.decision_type == "buy"
    assert result.operation_advice == "暂不加仓，继续持有观察。"


def test_conservative_market_context_does_not_soften_no_action_in_english() -> None:
    result = _result()
    result.decision_type = "hold"
    result.operation_advice = "No add now; keep watching for confirmation."

    adjustments = apply_daily_market_context_guardrail(
        result,
        daily_market_context={
            "region": "us",
            "trade_date": "2026-06-06",
            "summary": "Market cooling and elevated risk. Cautious on new positions."
        },
        report_language="en",
    )

    assert adjustments == []
    assert result.decision_type == "hold"
    assert result.operation_advice == "No add now; keep watching for confirmation."


def test_conservative_market_context_does_not_soften_explicit_negative_add_position() -> None:
    result = _result()
    result.decision_type = "buy"
    result.operation_advice = "不建议加仓，等待窗口更清晰。"
    result.confidence_level = "高"

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

    assert adjustments == []
    assert result.decision_type == "buy"
    assert result.operation_advice == "不建议加仓，等待窗口更清晰。"


def test_conservative_market_context_softens_generic_buy_advice_phrase() -> None:
    result = _result()
    result.operation_advice = "回踩买入，强支撑上攻。"
    result.confidence_level = "高"

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


def test_conservative_market_context_softens_when_risk_warning_then_recommend_buy() -> None:
    result = _result()
    result.decision_type = "buy"
    result.operation_advice = "风险不能忽视，但建议买入等待确认信号。"
    result.confidence_level = "高"

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


def test_conservative_market_context_softens_when_negated_chase_then_recommend_buy() -> None:
    result = _result()
    result.decision_type = "buy"
    result.operation_advice = "不建议追高，但建议分批买入。"
    result.confidence_level = "高"

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


def test_conservative_market_context_does_not_soften_buy_when_negated_explicitly_in_english() -> None:
    result = _result()
    result.decision_type = "buy"
    result.operation_advice = "No buy now; avoid adding."

    adjustments = apply_daily_market_context_guardrail(
        result,
        daily_market_context={
            "region": "cn",
            "trade_date": "2026-06-06",
            "summary": "大盘退潮，高风险，建议观望，仓位上限30%。",
            "risk_tags": ["high_risk", "low_position_cap"],
        },
        report_language="en",
    )

    assert adjustments == []
    assert result.decision_type == "buy"
    assert result.operation_advice == "No buy now; avoid adding."


def test_conservative_market_context_does_not_soften_do_not_buy_in_english() -> None:
    result = _result()
    result.decision_type = "buy"
    result.operation_advice = "Do not buy now; sell into strength."

    adjustments = apply_daily_market_context_guardrail(
        result,
        daily_market_context={
            "region": "us",
            "trade_date": "2026-06-06",
            "summary": "Market cooling and elevated risk. Cautious on new positions.",
        },
        report_language="en",
    )

    assert adjustments == []
    assert result.decision_type == "buy"
    assert result.operation_advice == "Do not buy now; sell into strength."


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


def test_traditional_risky_summary_softens_traditional_aggressive_buy() -> None:
    result = _result()
    result.decision_type = "hold"
    result.operation_advice = "立即買入並積極加倉"

    adjustments = apply_daily_market_context_guardrail(
        result,
        daily_market_context={
            "region": "tw",
            "trade_date": "2026-10-05",
            "summary": "大盤高風險，量縮下跌。",
            "risk_tags": [],
        },
        report_language="zh",
    )

    assert "daily_market_context_buy_softened" in adjustments
    assert result.operation_advice == "观望"


def test_traditional_negated_buy_is_not_softened() -> None:
    result = _result()
    result.decision_type = "hold"
    result.operation_advice = "暫不建議買入"

    adjustments = apply_daily_market_context_guardrail(
        result,
        daily_market_context={
            "region": "tw",
            "trade_date": "2026-10-05",
            "summary": "大盤高風險。",
            "risk_tags": ["high_risk"],
        },
        report_language="zh",
    )

    assert adjustments == []
    assert result.operation_advice == "暫不建議買入"


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


@pytest.mark.parametrize("decision_type,advice", [
    ("sell", "不建議買入"), ("hold", "不建議買入"), ("hold", "不加倉"), ("sell", "不建議加倉"),
])
def test_negation_sharing_chars_with_buy_marker_is_not_softened(decision_type, advice) -> None:
    # 「不建議買入」的回看窗只剩「不」：舊判斷當成積極買進，把賣出改成觀望、分數壓到 52
    result = _result()
    result.decision_type = decision_type
    result.operation_advice = advice
    result.dashboard["decision_type"] = decision_type

    adjustments = apply_daily_market_context_guardrail(result, daily_market_context=_HIGH_RISK_TW, report_language="zh")

    assert adjustments == []
    assert result.operation_advice == advice
    assert result.dashboard["decision_type"] == decision_type


@pytest.mark.parametrize("advice", [
    "持有，不需要加倉", "持有，無需加倉", "持有，毋須加倉", "持有，不再加倉", "持有，不急於加倉",
    "持有，不考慮加倉", "持有，不必加倉", "持有，不用加倉", "現階段不適合加倉", "持有，沒必要加倉",
    "持有，无需加仓", "持有，不需要加仓",
    # 整詞否定與買進詞之間只隔極短虛詞仍是否定
    "持有，不需要再加倉", "持有，不必急著加倉", "持有，無需急於加倉", "持有，不必積極加倉", "持有，不用再去加倉",
])
def test_hold_with_spelled_out_refusal_is_not_softened(advice) -> None:
    # 否定詞不緊貼買進詞（「不需要加倉」）：舊判斷只認緊貼單字，把持有當成積極買進、改寫成觀望並記 raw_score
    result = _result()
    result.decision_type = "hold"
    result.operation_advice = advice
    result.dashboard["decision_type"] = "hold"

    adjustments = apply_daily_market_context_guardrail(result, daily_market_context=_HIGH_RISK_TW, report_language="zh")

    assert adjustments == []
    assert result.operation_advice == advice
    assert "decision_score_calibration" not in result.dashboard


@pytest.mark.parametrize("decision_type", ["buy", "hold"])
@pytest.mark.parametrize("advice", [
    "回測不再破底即可加倉", "站穩後不再破底即加倉", "不再觀望積極加倉", "不用等回檔直接加倉",
    "不必等拉回分批買入", "不需等待立即買入", "不考慮停損積極加倉",
    # 頓號不切子句：「不必追高、」否定的是追高，後面的買進仍要過護欄
    "不必追高、分批買入", "無需追高、逢低加倉", "賣壓不再建議加倉", "不用擔心短線震盪建議買入", "不需觀望積極買入",
])
def test_spelled_out_negation_of_other_verb_does_not_shield_buy(decision_type, advice) -> None:
    # 「不再／不用／不必／不需／不考慮」修飾的是別的動詞（破底、等回檔、追高）時不是否定買進：
    # 若在子句任意位置出現就算否定，保守大盤日的買進會原封不動放行
    result = _result()
    result.decision_type = decision_type
    result.operation_advice = advice
    result.dashboard["decision_type"] = decision_type

    adjustments = apply_daily_market_context_guardrail(result, daily_market_context=_HIGH_RISK_TW, report_language="zh-TW")

    assert "daily_market_context_buy_softened" in adjustments


@pytest.mark.parametrize("advice", [
    "特別建議買入", "股價不貴，建議買入", "股價不貴建議買入",
    # 「不追高」否定的是追價、不是買進；提示詞本身就要求 LLM 寫「不追高」
    "逢低買進，不追高", "建議買進，但不追高", "買入，不追高",
    # 雙重否定與反問仍是要買
    "沒有理由不加倉", "不得不加倉", "何不加倉", "並無不加倉之理", "並非不建議買入",
    # 雙重否定套在整詞否定上（「並非不需要」）也是要買：整詞否定的判斷不能略過雙重否定
    "並非不需要加倉", "並非無需加倉", "並非不必再加倉", "沒有理由不需要加倉",
    # 不帶否定字的「需要／必要／考慮／適合」不是否定：否定詞表只能收整詞
    "持有，需要加倉", "持有，有必要加倉", "持有，考慮加倉", "現階段適合加倉", "急於加倉",
])
def test_non_negating_words_do_not_shield_buy(advice) -> None:
    # 「特別」的「別」、句中不貼著買進詞的「不」都不是否定：保守市況仍要降級
    result = _result()
    result.operation_advice = advice

    adjustments = apply_daily_market_context_guardrail(result, daily_market_context=_HIGH_RISK_TW, report_language="zh")

    assert "daily_market_context_buy_softened" in adjustments


@pytest.mark.parametrize("advice", ["無論如何不加倉", "无论如何不建议买入", "不管如何不加倉", "為何不建議買入", "無論如何勿加倉"])
def test_explicit_refusal_ending_in_he_is_not_rhetorical(advice) -> None:
    # 「何不」才是反問；「無論如何不／為何不」是明確否定，賣出不能被改寫成觀望
    result = _result()
    result.decision_type = "sell"
    result.operation_advice = advice
    result.dashboard["decision_type"] = "sell"

    adjustments = apply_daily_market_context_guardrail(result, daily_market_context=_HIGH_RISK_TW, report_language="zh")

    assert adjustments == []
    assert result.operation_advice == advice


@pytest.mark.parametrize("decision_type", ["buy", "hold"])
@pytest.mark.parametrize("advice", [
    # 提示型否定管的是別的動詞或被轉折／頓號切開，後面的買進仍要降級
    "不宜追高但可分批買入", "避免追高、分批買入", "為避免踏空建議加倉", "別猶豫加倉", "千萬別錯過加倉機會",
    "告別盤整建議加倉", "量縮不要緊加倉", "避免追高，分批买入", "不宜追高 分批買入", "不建議追高惟可加倉",
    # 雙重否定（枚舉以外）與反問仍是要買
    "沒理由不加倉", "不能不加倉", "不可不加倉", "不是不需要加倉", "無法不加倉",
    # 台灣慣用買進詞
    "建議買進", "逢低加碼", "積極佈局", "逢低布局", "分批進場", "建议买进", "逢低加码",
])
def test_hint_negation_gaps_and_taiwan_buy_terms_are_softened(decision_type, advice) -> None:
    result = _result()
    result.decision_type = decision_type
    result.operation_advice = advice
    result.dashboard["decision_type"] = decision_type

    adjustments = apply_daily_market_context_guardrail(result, daily_market_context=_HIGH_RISK_TW, report_language="zh")

    assert result.operation_advice == "观望"
    assert result.dashboard["decision_type"] == "hold"
    assert adjustments


@pytest.mark.parametrize("decision_type", ["buy", "hold"])
@pytest.mark.parametrize("advice", [
    "不建議買入", "不加倉", "暫不買進", "暫不加碼", "不建議買進", "避免加倉", "避免積極佈局", "不宜加碼", "別加倉",
    "別急著買進", "不宜貿然加倉", "不要加倉", "不應逢低加碼", "暂不建议买进", "不建議分批進場",
])
def test_true_negation_of_buy_is_not_softened(decision_type, advice) -> None:
    result = _result()
    result.decision_type = decision_type
    result.operation_advice = advice
    result.dashboard["decision_type"] = decision_type

    adjustments = apply_daily_market_context_guardrail(result, daily_market_context=_HIGH_RISK_TW, report_language="zh")

    assert adjustments == []
    assert result.operation_advice == advice


@pytest.mark.parametrize("decision_type", ["buy", "hold"])
@pytest.mark.parametrize("advice", [
    # 否定詞與買進詞之間隔著一般詞語（價位、時機、幅度）仍是否定：只認固定虛詞會把這些真否定降級
    "不建議在此價位買進", "不建議此時進場", "不建議大舉加碼", "不宜過早佈局", "暫時不要追價買進",
    "不要在高檔加倉", "不建議於現價買入", "不建議大幅加倉",
])
def test_negation_separated_by_ordinary_words_is_not_softened(decision_type, advice) -> None:
    result = _result()
    result.decision_type = decision_type
    result.operation_advice = advice
    result.dashboard["decision_type"] = decision_type

    adjustments = apply_daily_market_context_guardrail(result, daily_market_context=_HIGH_RISK_TW, report_language="zh")

    assert adjustments == []
    assert result.operation_advice == advice


@pytest.mark.parametrize("advice", ["買進訊號未出現，觀望", "尚未出現買進訊號", "等待买进讯号"])
def test_bare_buy_noun_in_hold_is_not_buy_signal(advice) -> None:
    # 裸「買進」當名詞（買進訊號）不是建議：hold 不能被改寫成觀望
    result = _result()
    result.decision_type = "hold"
    result.operation_advice = advice
    result.dashboard["decision_type"] = "hold"

    adjustments = apply_daily_market_context_guardrail(result, daily_market_context=_HIGH_RISK_TW, report_language="zh")

    assert adjustments == []
    assert result.operation_advice == advice


@pytest.mark.parametrize("decision_type", ["buy", "hold"])
@pytest.mark.parametrize("advice", [
    "建議進場", "建議布局", "可以佈局", "可進場", "建議買進",
    # 雙重否定套在提示型否定上（「並非不建議」）也是要買
    "並非不建議加倉", "為避免踏空，建議進場",
])
def test_advice_context_buy_verbs_are_softened(decision_type, advice) -> None:
    result = _result()
    result.decision_type = decision_type
    result.operation_advice = advice
    result.dashboard["decision_type"] = decision_type

    adjustments = apply_daily_market_context_guardrail(result, daily_market_context=_HIGH_RISK_TW, report_language="zh")

    assert result.operation_advice == "观望"
    assert adjustments


@pytest.mark.parametrize("decision_type", ["buy", "hold"])
@pytest.mark.parametrize("advice", [
    # 否定詞與買進詞之間夾著別的動詞或連接詞：否定綁在那個動詞上，買進本身是肯定
    "不要猶豫加碼", "不要犹豫加仓", "不要遲疑加碼", "不要錯過加碼", "千萬不要錯過加碼", "不要錯過機會加碼",
    "別擔心加碼", "不要害怕直接加碼", "不建議賣出反而加碼", "不建議減碼並加碼", "不建議減碼並逢低加碼",
    "不要只是持有而要加碼", "不建議賣出而應買進", "不可錯失良機加碼", "避免踏空積極佈局",
    # 裸「買進」前面不必是固定建議詞
    "擇機買進", "現價買進", "低接買進", "可考慮買進",
])
def test_negation_of_intervening_verb_does_not_shield_buy(decision_type, advice) -> None:
    result = _result()
    result.decision_type = decision_type
    result.operation_advice = advice
    result.dashboard["decision_type"] = decision_type

    adjustments = apply_daily_market_context_guardrail(result, daily_market_context=_HIGH_RISK_TW, report_language="zh")

    assert result.operation_advice == "观望"
    assert result.dashboard["decision_type"] == "hold"
    assert adjustments
