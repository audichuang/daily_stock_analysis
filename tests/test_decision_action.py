# -*- coding: utf-8 -*-
"""Tests for Issue #1390 P0 decision action taxonomy helpers."""

import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.schemas.decision_action import (
    build_action_fields,
    display_action_fields_for_result,
    display_decision_type_for_result,
    display_operation_advice_for_result,
    localize_action_label,
    normalize_decision_action,
)
from src.schemas.decision_scale import action_for_score, decision_type_for_score, signal_key_for_score


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("strong_buy", "buy"),
        ("强烈买入", "buy"),
        ("买入", "buy"),
        ("布局", "buy"),
        ("建仓", "buy"),
        ("add", "add"),
        ("加仓", "add"),
        ("增持", "add"),
        ("accumulate", "add"),
        ("hold", "hold"),
        ("持有", "hold"),
        ("持有观察", "hold"),
        ("洗盘观察", "hold"),
        ("watch", "watch"),
        ("观望", "watch"),
        ("等待", "watch"),
        ("wait", "watch"),
        ("reduce", "reduce"),
        ("减仓", "reduce"),
        ("trim", "reduce"),
        ("sell", "sell"),
        ("卖出", "sell"),
        ("清仓", "sell"),
        ("strong_sell", "sell"),
        ("强烈卖出", "sell"),
        ("avoid", "avoid"),
        ("回避", "avoid"),
        ("规避", "avoid"),
        ("不建议买入", None),
        ("避免买入", None),
        ("do not buy", "avoid"),
        ("alert", "alert"),
        ("风险预警", "alert"),
        ("警惕", "alert"),
        ("触发告警", "alert"),
        ("risk alert", "alert"),
    ],
)
def test_normalize_decision_action_matrix(value: str, expected: str | None) -> None:
    assert normalize_decision_action(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        None,
        "观察",
        "等待突破后买入",
        "waiting to buy",
        "买入或卖出",
        "buy or sell",
        "买盘增强，继续观察",
        "卖压缓解，继续观察",
        "卖方评级分歧",
        "no buyback announced",
        "cannot buyback shares now",
        "share buy-back announced",
        "share buy back announced",
        "no selloff risk",
        "not selloff yet",
        "sell-off risk remains low",
        "sell off risk remains low",
        "no sell-off pressure",
        "risk alert, avoid buying",
        "风险预警，避免买入",
        "普通复盘说明",
    ],
)
def test_normalize_decision_action_unknown_or_ambiguous_returns_none(value: str | None) -> None:
    assert normalize_decision_action(value) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("暂不买入", None),
        ("不要买入", None),
        ("不宜买入", None),
        ("先不买入", None),
        ("无需买入", None),
        ("无须买入", None),
        ("不建议建仓", None),
        ("暂不建仓", None),
        ("无需建仓", None),
        ("无须建仓", None),
        ("不建议布局", None),
        ("先不布局", None),
        ("无需布局", None),
        ("无须布局", None),
        ("no buy", "avoid"),
        ("no need to buy", "avoid"),
        ("need not buy", "avoid"),
        ("cannot buy", "avoid"),
        ("can't buy", "avoid"),
        ("not a buy yet", "avoid"),
        ("not to buy", "avoid"),
        ("avoid buying", "avoid"),
        ("avoid buying into weakness", "avoid"),
        ("不建议加仓", None),
        ("无须加仓", None),
        ("no add", "hold"),
        ("no need to add", "hold"),
        ("need not add", "hold"),
        ("cannot add", "hold"),
        ("not to add", "hold"),
        ("no accumulate", "hold"),
        ("can't accumulate", "hold"),
        ("not to accumulate", "hold"),
        ("不建议卖出", None),
        ("无需卖出", None),
        ("无须卖出", None),
        ("不要卖出", None),
        ("暂不卖出", None),
        ("no sell", "hold"),
        ("no need to sell", "hold"),
        ("cannot sell", "hold"),
        ("can't sell", "hold"),
        ("not a sell yet", "hold"),
        ("not to sell", "hold"),
        ("无需减仓", None),
        ("无须减仓", None),
        ("no reduce", "hold"),
        ("no need to reduce", "hold"),
        ("cannot reduce", "hold"),
        ("not to reduce", "hold"),
        ("no trim", "hold"),
        ("can't trim", "hold"),
        ("not a trim yet", "hold"),
        ("not to trim", "hold"),
        ("avoid selling into weakness", "hold"),
        ("avoid trimming before earnings", "hold"),
        ("avoid reducing exposure before earnings", "hold"),
        ("不建议清仓", None),
    ],
)
def test_normalize_decision_action_handles_negated_trade_actions(value: str, expected: str | None) -> None:
    assert normalize_decision_action(value) == expected


@pytest.mark.parametrize(
    ("advice", "expected_action", "expected_label"),
    [
        ("无需买入，等待确认", None, None),
        ("无须建仓，继续观察", None, None),
        ("无需布局，等待突破", None, None),
        ("no buy until breakout", "avoid", "回避"),
        ("no need to buy before confirmation", "avoid", "回避"),
        ("cannot buy before confirmation", "avoid", "回避"),
        ("can't buy before confirmation", "avoid", "回避"),
        ("not a buy yet", "avoid", "回避"),
        ("not to buy", "avoid", "回避"),
    ],
)
def test_build_action_fields_prioritizes_negated_buy_advice_over_embedded_buy_phrase(
    advice: str, expected_action: str | None, expected_label: str | None,
) -> None:
    assert build_action_fields(operation_advice=advice) == {
        "action": expected_action,
        "action_label": expected_label,
    }


@pytest.mark.parametrize(
    ("advice", "expected_action", "expected_label"),
    [
        ("无须加仓，维持仓位", None, None),
        ("无需卖出，继续持有", None, None),
        ("无须减仓，等待确认", None, None),
        ("no add before confirmation", "hold", "持有"),
        ("cannot add before confirmation", "hold", "持有"),
        ("no need to accumulate here", "hold", "持有"),
        ("can't accumulate here", "hold", "持有"),
        ("no sell before earnings", "hold", "持有"),
        ("cannot sell before earnings", "hold", "持有"),
        ("no need to reduce exposure", "hold", "持有"),
        ("can't reduce exposure", "hold", "持有"),
        ("no trim while trend holds", "hold", "持有"),
        ("cannot trim while trend holds", "hold", "持有"),
        ("not a sell yet", "hold", "持有"),
        ("not a trim yet", "hold", "持有"),
        ("not to sell", "hold", "持有"),
        ("not to trim", "hold", "持有"),
        ("avoid selling into weakness", "hold", "持有"),
        ("avoid trimming before earnings", "hold", "持有"),
        ("avoid reducing exposure before earnings", "hold", "持有"),
    ],
)
def test_build_action_fields_prioritizes_negated_hold_advice_over_embedded_trade_phrase(
    advice: str, expected_action: str | None, expected_label: str | None,
) -> None:
    assert build_action_fields(operation_advice=advice) == {
        "action": expected_action,
        "action_label": expected_label,
    }


@pytest.mark.parametrize(
    "advice",
    [
        "risk alert, avoid buying",
        "风险预警，避免买入",
    ],
)
def test_build_action_fields_keeps_multi_guard_advice_empty(advice: str) -> None:
    assert build_action_fields(operation_advice=advice) == {
        "action": None,
        "action_label": None,
    }


@pytest.mark.parametrize(
    "advice",
    [
        "买盘增强，继续观察",
        "卖压缓解，继续观察",
        "卖方评级分歧",
    ],
)
def test_build_action_fields_keeps_chinese_financial_context_empty(advice: str) -> None:
    assert build_action_fields(operation_advice=advice) == {
        "action": None,
        "action_label": None,
    }


@pytest.mark.parametrize(
    "advice",
    [
        "no buyback announced",
        "cannot buyback shares now",
        "no selloff risk",
        "not selloff yet",
    ],
)
def test_build_action_fields_keeps_financial_compound_terms_empty(advice: str) -> None:
    assert build_action_fields(operation_advice=advice) == {
        "action": None,
        "action_label": None,
    }


@pytest.mark.parametrize(
    "advice",
    [
        "share buy-back announced",
        "share buy back announced",
        "sell-off risk remains low",
        "sell off risk remains low",
        "no sell-off pressure",
    ],
)
def test_build_action_fields_keeps_hyphenated_financial_compound_terms_empty(advice: str) -> None:
    assert build_action_fields(operation_advice=advice) == {
        "action": None,
        "action_label": None,
    }


@pytest.mark.parametrize(
    ("advice", "expected_action", "expected_label"),
    [
        ("buy after sell-off", "buy", "买入"),
        ("sell after buy-back rumor", "sell", "卖出"),
    ],
)
def test_financial_compound_mask_preserves_separate_action_terms(
    advice: str,
    expected_action: str,
    expected_label: str,
) -> None:
    assert normalize_decision_action(advice) == expected_action
    assert build_action_fields(operation_advice=advice) == {
        "action": expected_action,
        "action_label": expected_label,
    }


def test_localize_action_label_uses_report_language() -> None:
    assert localize_action_label("avoid", "zh") == "回避"
    assert localize_action_label("avoid", "en") == "Avoid"


@pytest.mark.parametrize(
    ("action", "expected_label"),
    [
        ("buy", "매수"),
        ("add", "추가 매수"),
        ("hold", "보유"),
        ("reduce", "비중축소"),
        ("sell", "매도"),
        ("watch", "관망"),
        ("avoid", "회피"),
        ("alert", "경고"),
    ],
)
def test_localize_action_label_supports_korean(action: str, expected_label: str) -> None:
    assert localize_action_label(action, "ko") == expected_label


def test_build_action_fields_respects_market_review_exclusion() -> None:
    fields = build_action_fields(
        operation_advice="买入",
        explicit_action="buy",
        report_type="market_review",
    )

    assert fields == {"action": None, "action_label": None}


def test_build_action_fields_prefers_explicit_action_over_advice() -> None:
    fields = build_action_fields(
        operation_advice="买入",
        explicit_action="watch",
        report_language="zh",
    )

    assert fields == {"action": "watch", "action_label": "观望"}


def test_build_action_fields_keeps_empty_action_without_advice_or_explicit_action() -> None:
    fields = build_action_fields(
        operation_advice=None,
        report_language="zh",
    )

    assert fields == {"action": None, "action_label": None}


@pytest.mark.parametrize(
    ("score", "expected_signal", "expected_action", "expected_decision_type"),
    [
        (28, "reduce", "reduce", "sell"),
        (38, "reduce", "reduce", "sell"),
        (42, "watch", "watch", "hold"),
        (55, "watch", "watch", "hold"),
        (60, "buy", "buy", "buy"),
        (66, "buy", "buy", "buy"),
        (72, "buy", "buy", "buy"),
    ],
)
def test_canonical_score_scale_boundaries(
    score: int,
    expected_signal: str,
    expected_action: str,
    expected_decision_type: str,
) -> None:
    assert signal_key_for_score(score) == expected_signal
    assert action_for_score(score) == expected_action
    assert decision_type_for_score(score) == expected_decision_type


def test_build_action_fields_can_align_neutral_action_with_directional_score() -> None:
    assert build_action_fields(
        operation_advice="持有",
        sentiment_score=72,
        align_with_score=True,
    ) == {"action": "buy", "action_label": "买入"}

    assert build_action_fields(
        operation_advice="观望",
        sentiment_score=28,
        align_with_score=True,
    ) == {"action": "reduce", "action_label": "减仓"}


def test_build_action_fields_keeps_neutral_score_conflict_when_guardrail_is_explicit() -> None:
    assert build_action_fields(
        operation_advice="持有/观望待回踩",
        sentiment_score=72,
        guardrail_reason="等待回踩确认",
        align_with_score=True,
    ) == {"action": "watch", "action_label": "观望"}


def test_display_helpers_share_score_aligned_action_with_report_rows_and_counts() -> None:
    result = type(
        "Result",
        (),
        {
            "operation_advice": "Hold",
            "action": None,
            "action_label": None,
            "sentiment_score": 72,
            "decision_type": "hold",
            "report_language": "en",
            "dashboard": {},
        },
    )()

    assert display_action_fields_for_result(result) == {"action": "buy", "action_label": "Buy"}
    assert display_operation_advice_for_result(result) == "Buy"
    assert display_decision_type_for_result(result) == "buy"


def test_display_helpers_preserve_neutral_action_when_guardrail_was_applied() -> None:
    result = type(
        "Result",
        (),
        {
            "operation_advice": "Hold",
            "action": "hold",
            "action_label": "Hold",
            "sentiment_score": 72,
            "decision_type": "hold",
            "report_language": "en",
            "dashboard": {
                "decision_stability": {
                    "applied": True,
                    "reason": "Wait for confirmation",
                }
            },
        },
    )()

    assert display_action_fields_for_result(result) == {"action": "hold", "action_label": "Hold"}
    assert display_operation_advice_for_result(result) == "Hold"
    assert display_decision_type_for_result(result) == "hold"


# H1：REPORT_LANGUAGE=zh-TW 時建議文字是繁體，片語表是簡體；要先逐字折成簡體才比得到。
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("強烈買入", "buy"),
        ("買入", "buy"),
        ("佈局", "buy"),
        ("建倉", "buy"),
        ("加倉", "add"),
        ("持有觀察", "hold"),
        ("洗盤觀察", "hold"),
        ("觀望", "watch"),
        ("減倉", "reduce"),
        ("賣出", "sell"),
        ("強烈賣出", "sell"),
        ("清倉", "sell"),
        ("規避", "avoid"),
        ("迴避", "avoid"),
        ("風險預警", "alert"),
        ("觸發告警", "alert"),
        # 否定建議保守回傳未知，不推算交易方向
        ("不建議買入", None),
        ("暫不買入", None),
        ("不宜買入", None),
        ("無須買入", None),
        ("暫不佈局", None),
        ("無須建倉", None),
        ("暫不加倉", None),
        ("無須加倉", None),
        ("不建議加倉", None),
        ("不建議賣出", None),
        ("暫不減倉", None),
        ("無須清倉", None),
        ("無需加倉", None),
        ("無需減倉", None),
        ("不建議減倉", None),
        ("不建議清倉", None),
        ("暫不清倉", None),
        ("不建議佈局", None),
        ("無需佈局", None),
        ("不建議建倉", None),
        ("暫不建倉", None),
    ],
)
def test_normalize_decision_action_traditional_chinese(value: str, expected: str | None) -> None:
    assert normalize_decision_action(value) == expected


@pytest.mark.parametrize("value", ["買入或賣出", "加倉後減倉"])
def test_normalize_decision_action_traditional_conflicts_stay_none(value: str) -> None:
    # 反向檢查：折疊不能讓互相衝突的繁體建議被硬判成某個動作
    assert normalize_decision_action(value) is None


def test_normalize_decision_action_traditional_matches_every_simplified_phrase() -> None:
    from src.schemas import decision_action as module
    from src.utils.zh_fold import TRAD_TO_SIMP

    simp_to_trad = {chr(simp): chr(trad) for trad, simp in TRAD_TO_SIMP.items()}
    phrase_tables = list(module._ACTION_PHRASES.values()) + list(module._NEGATED_ACTION_PHRASES.values())
    checked = 0
    for phrases in phrase_tables:
        for phrase in phrases:
            traditional = "".join(simp_to_trad.get(ch, ch) for ch in phrase)
            if traditional == phrase:
                continue
            checked += 1
            assert normalize_decision_action(traditional) == normalize_decision_action(phrase), phrase
    assert checked > 20


def test_decision_action_and_backtest_share_one_fold_table() -> None:
    from src.core.backtest_engine import BacktestEngine
    from src.utils.zh_fold import TRAD_TO_SIMP

    assert BacktestEngine._TRAD_TO_SIMP is TRAD_TO_SIMP


def test_build_action_fields_traditional_advice_for_zh_tw_report() -> None:
    fields = build_action_fields(operation_advice="觀望", report_language="zh-TW")

    assert fields == {"action": "watch", "action_label": "觀望"}


@pytest.mark.parametrize("value", [
    "不建議現在買入", "不建议现在买入",
    "暫不加碼，建議賣出", "暂不加码，建议卖出",
    "沒有不買入的理由", "没有不买入的理由",
    "不買入，觸發告警及減倉", "不买入，触发告警及减仓",
    "不建議買入", "不建议买入", "不賣出", "不卖出",
    "暫無買入點", "暂无买入点", "禁止買入", "禁止买入",
    "不應買入", "不应买入",
])
def test_chinese_negated_advice_is_unknown_before_any_action_matching(value: str) -> None:
    assert normalize_decision_action(value) is None
    assert build_action_fields(operation_advice=value) == {"action": None, "action_label": None}


@pytest.mark.parametrize("negation", [
    "不", "別", "别", "勿", "莫", "未", "沒", "没", "無", "无",
    "暫不", "暂不", "不宜", "不要", "不建議", "不建议", "避免", "禁止", "切勿", "停止",
])
def test_chinese_negation_tokens_make_nearby_actions_unknown(negation: str) -> None:
    assert normalize_decision_action(f"{negation}現在買入") is None


@pytest.mark.parametrize("action_word", [
    "買入", "賣出", "加倉", "加碼", "增持", "減倉", "減碼", "清倉", "建倉", "佈局",
    "持有", "洗盤觀察", "觀望", "等待", "回避", "規避", "風險預警", "觸發告警", "警惕",
    "买入", "卖出", "加仓", "加码", "减仓", "减码", "清仓", "建仓", "布局",
    "洗盘观察", "观望", "规避", "风险预警", "触发告警",
])
def test_chinese_negation_covers_every_action_word_before_other_advice(action_word: str) -> None:
    assert normalize_decision_action(f"暫不{action_word}") is None
    assert normalize_decision_action(f"暫不{action_word}，建議買入") is None


@pytest.mark.parametrize(("value", "expected"), [
    ("不經過完整評估買入", None),
    ("不經過完整評估後買入", "buy"),
    ("買入後不追高", "buy"),
    ("賣出後暫不追高", "sell"),
    ("買入", "buy"), ("买入", "buy"),
    ("賣出", "sell"), ("卖出", "sell"),
    ("減倉", "reduce"), ("减仓", "reduce"),
    ("加倉", "add"), ("加仓", "add"),
    ("加碼", None), ("加码", None),
])
def test_chinese_negation_window_preserves_existing_affirmative_behavior(
    value: str, expected: str | None,
) -> None:
    assert normalize_decision_action(value) == expected


@pytest.mark.parametrize("explicit_action", [None, "hold", "reduce"])
def test_chinese_negated_advice_preserves_structured_action_and_legacy_fallback(explicit_action: str | None) -> None:
    result = type("Result", (), {
        "operation_advice": "不建議現在買入", "action": explicit_action,
        "decision_type": "hold", "sentiment_score": 50, "report_language": "zh-TW",
    })()
    assert display_action_fields_for_result(result)["action"] == explicit_action
    assert display_decision_type_for_result(result) == ("sell" if explicit_action == "reduce" else "hold")


# 否定詞與動作詞須在同一子句（逗號、句號、換行為界），以下寫法同樣回未知
@pytest.mark.parametrize("value", [
    "不买入", "別急著賣出", "切勿追高買進", "暫不進場", "暫緩加倉",
    "不要等待", "無需回避", "无需卖出，继续持有", "無須減倉，等待確認",
])
def test_chinese_negation_more_forms_are_unknown(value: str) -> None:
    assert normalize_decision_action(value) is None


# 反向檢查：否定詞在另一個子句、離動作詞超過 6 字、或屬於「未來／無論／不斷」等非否定詞，維持原判
@pytest.mark.parametrize(("value", "expected"), [
    ("持有", "hold"), ("觀望", "watch"), ("回避", "avoid"),
    ("跌幅不大，建議買入", "buy"),
    ("跌幅不大，建议买入", "buy"),
    ("趨勢不變，繼續持有", "hold"),
    ("不追高，等待回檔", "watch"),
    ("切勿追高，建議減倉", "reduce"),
    ("量能不足以支撐突破後再追價，持有", "hold"),
    ("不只是短線題材而已的標的買入", "buy"),
    ("未來可逢低買入", "buy"),
    ("未來看好，建議買入", "buy"),
    ("無論如何先持有", "hold"),
    ("不斷走強，建議加倉", "add"),
    ("跌幅不大\n建議買入", "buy"),
])
def test_chinese_negation_is_clause_bound_and_skips_non_negating_words(value: str, expected: str) -> None:
    assert normalize_decision_action(value) == expected
