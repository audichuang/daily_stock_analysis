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


# 動作只來自結構化 enum 或「整段就是一個動作標籤」的建議；不做片語、否定或子字串判讀。
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # 八態 enum 與既有英文別名
        ("buy", "buy"), ("add", "add"), ("hold", "hold"), ("reduce", "reduce"),
        ("sell", "sell"), ("watch", "watch"), ("avoid", "avoid"), ("alert", "alert"),
        ("strong_buy", "buy"), ("strong-buy", "buy"), ("strong sell", "sell"),
        ("accumulate", "add"), ("trim", "reduce"), ("wait", "watch"),
        (" BUY ", "buy"), ("Hold", "hold"),
        # 各語系顯示標籤（去頭尾空白後完全相等）
        ("买入", "buy"), ("加仓", "add"), ("持有", "hold"), ("减仓", "reduce"),
        ("卖出", "sell"), ("观望", "watch"), ("回避", "avoid"), ("预警", "alert"),
        ("買入", "buy"), ("加倉", "add"), ("減倉", "reduce"), ("賣出", "sell"),
        # 詞彙表的新標籤
        ("買進", "buy"), ("續抱", "hold"), ("迴避", "avoid"), ("警報", "alert"), ("強烈買進", "buy"),
        ("觀望", "watch"), ("預警", "alert"), ("  減倉  ", "reduce"),
        ("매수", "buy"), ("추가 매수", "add"), ("보유", "hold"), ("비중축소", "reduce"),
        ("매도", "sell"), ("관망", "watch"), ("회피", "avoid"), ("경고", "alert"),
        # operation_advice 列舉的強烈買入／賣出，與台灣用語的加碼／減碼
        ("强烈买入", "buy"), ("強烈買入", "buy"), ("强烈卖出", "sell"), ("強烈賣出", "sell"),
        ("Strong Buy", "buy"), ("적극 매수", "buy"), ("적극 매도", "sell"),
        ("加碼", "add"), ("加码", "add"), ("減碼", "reduce"), ("减码", "reduce"),
    ],
)
def test_normalize_decision_action_accepts_enum_and_exact_labels(value: str, expected: str) -> None:
    assert normalize_decision_action(value) == expected


# 反向檢查：任何句子（含否定、肯定、混合或財經複合詞）都不解析，回 None 交給呼叫端既有預設。
# 若有人把片語表或子字串比對加回來，這裡會立刻紅。
@pytest.mark.parametrize(
    "value",
    [
        "", None, "   ", "观察", "普通复盘说明",
        "建議買入", "建议买入", "Buy now.", "buy after sell-off", "sell after buy-back rumor",
        "不建議現在買入", "不建议现在买入", "不建議買入", "暫不買入", "避免买入",
        "do not buy", "don't buy", "not a buy yet", "no need to sell", "avoid selling into weakness",
        "waiting to buy", "等待突破后买入", "买入或卖出", "buy or sell", "買入或賣出", "加倉後減倉",
        "买盘增强，继续观察", "卖方评级分歧", "no buyback announced", "sell-off risk remains low",
        "risk alert, avoid buying", "风险预警，避免买入", "风险预警", "触发告警", "警惕",
        "持有观察", "洗盘观察", "持有觀察", "洗盤觀察", "震盪觀望", "持有/观望待回踩",
        "布局", "建仓", "增持", "清仓", "规避", "等待",
        "跌幅不大，建議買入", "未來看好，建議買入", "暫不加碼，建議賣出", "沒有不買入的理由",
        "观望（原建议已被风控下调）", "减仓/卖出", "等待盘中确认，禁止追高。",
    ],
)
def test_normalize_decision_action_free_text_returns_none(value: str | None) -> None:
    assert normalize_decision_action(value) is None
    assert build_action_fields(operation_advice=value) == {"action": None, "action_label": None}


def test_build_action_fields_structured_watch_wins_over_negated_buy_sentence() -> None:
    # 「不建議現在買入」含「買入」字樣；動作必須取自 LLM 的結構化 watch，不能被句子帶偏
    fields = build_action_fields(
        operation_advice="不建議現在買入",
        explicit_action="watch",
        report_language="zh-TW",
    )
    assert fields == {"action": "watch", "action_label": "觀望"}


def test_build_action_fields_free_sentence_without_structured_action_is_none() -> None:
    assert build_action_fields(operation_advice="建議逢低買入，停損設在月線") == {
        "action": None,
        "action_label": None,
    }


def test_build_action_fields_bare_label_without_structured_action() -> None:
    assert build_action_fields(operation_advice="減倉", report_language="zh-TW") == {
        "action": "reduce",
        "action_label": "減碼",
    }


def test_exact_labels_cover_every_localized_action_label() -> None:
    from src.schemas import decision_action as module
    from src.utils.zh_fold import TRAD_TO_SIMP

    simp_to_trad = {chr(simp): chr(trad) for trad, simp in TRAD_TO_SIMP.items()}
    checked = 0
    for action, labels in module._ACTION_LABELS.items():
        for label in labels.values():
            assert normalize_decision_action(label) == action, label
            traditional = "".join(simp_to_trad.get(ch, ch) for ch in label)
            assert normalize_decision_action(traditional) == action, traditional
            checked += 1
    assert checked == 32


def test_decision_action_module_has_no_phrase_or_negation_tables() -> None:
    from src.schemas import decision_action as module

    for name in (
        "_ACTION_PHRASES", "_NEGATED_ACTION_PHRASES", "_ZH_NEGATION_TOKENS",
        "_ZH_NEGATED_ACTION_RE", "_ENGLISH_NEGATED_ACTION_TERMS", "_has_zh_negated_action",
    ):
        assert not hasattr(module, name), name


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
        explicit_action="watch",
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


def test_decision_action_and_backtest_share_one_fold_table() -> None:
    from src.core.backtest_engine import BacktestEngine
    from src.utils.zh_fold import TRAD_TO_SIMP

    assert BacktestEngine._TRAD_TO_SIMP is TRAD_TO_SIMP


def test_build_action_fields_traditional_advice_for_zh_tw_report() -> None:
    fields = build_action_fields(operation_advice="觀望", report_language="zh-TW")

    assert fields == {"action": "watch", "action_label": "觀望"}


@pytest.mark.parametrize("explicit_action", [None, "hold", "reduce"])
def test_chinese_negated_advice_preserves_structured_action_and_legacy_fallback(explicit_action: str | None) -> None:
    result = type("Result", (), {
        "operation_advice": "不建議現在買入", "action": explicit_action,
        "decision_type": "hold", "sentiment_score": 50, "report_language": "zh-TW",
    })()
    assert display_action_fields_for_result(result)["action"] == explicit_action
    assert display_decision_type_for_result(result) == ("sell" if explicit_action == "reduce" else "hold")


def test_zh_tw_labels_follow_glossary() -> None:
    expected = {
        "buy": "買進", "add": "加碼", "hold": "續抱", "reduce": "減碼",
        "sell": "賣出", "watch": "觀望", "avoid": "迴避", "alert": "警報",
    }
    for action, label in expected.items():
        assert localize_action_label(action, "zh-TW") == label
        assert normalize_decision_action(label) == action
