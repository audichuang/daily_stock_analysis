# -*- coding: utf-8 -*-
"""TW_MA_ALIGNMENT_WEIGHTED：關閉時提示詞一字不改；開啟時台股改用均線加權規則並標記 prompt_variant。"""

import copy
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    from tests.litellm_stub import ensure_litellm_stub

    ensure_litellm_stub()

from src.agent.skills.defaults import CORE_TRADING_SKILL_POLICY_ZH
from src.analyzer import TW_MA_CONTROL_VARIANT, TW_MA_WEIGHTED_VARIANT, GeminiAnalyzer, _tw_ma_ab_treated
from tests.test_analyzer_prompt_language import _make_analyzer, _rich_context

_OLD_HARD_LINES = ("**多头排列必须条件**", '乖离率 > 5%：严禁追高！直接判定为"观望"', "坚决不买入")
_OLD_USER_LINES = ("多頭排列？", "超過5%必須標註", "🚨 超過5%，嚴禁追高！")
_NEW_MARKER = "台股短波段買入（60-69分，均線加權）"


def _cfg(weighted: bool, **extra):
    return SimpleNamespace(
        tw_ma_alignment_weighted=weighted, bias_threshold=5.0, news_max_age_days=3,
        news_strategy_profile="short", **extra,
    )


def _analyzer(weighted: bool, legacy: bool = True):
    analyzer = _make_analyzer(legacy=legacy, default_skill_policy="" if legacy else CORE_TRADING_SKILL_POLICY_ZH)
    analyzer._config_override = _cfg(weighted)
    return analyzer


def _user_prompt(analyzer, code: str, language: str = "zh-TW") -> str:
    context = copy.deepcopy(_rich_context())
    context["code"] = code
    context["trend_analysis"]["bias_ma5"] = 7.0
    with patch("src.analyzer.get_config", return_value=analyzer._config_override), \
            patch.object(GeminiAnalyzer, "_tw_institutional_trend_lines", return_value=""):
        return analyzer._format_prompt(context, "台積電", news_context="n", report_language=language)


@pytest.mark.parametrize("legacy", [True, False])
@pytest.mark.parametrize("language", ["zh", "zh-TW"])
def test_off_system_prompt_is_unchanged(legacy, language):
    off = _analyzer(False, legacy)._get_analysis_system_prompt(language, stock_code="2330.TW")
    baseline_analyzer = _make_analyzer(
        legacy=legacy, default_skill_policy="" if legacy else CORE_TRADING_SKILL_POLICY_ZH
    )
    # 不帶開關欄位的設定＝功能上線前；不能讀 get_config()，本機 .env 開著開關會讓這裡假紅
    baseline_analyzer._config_override = SimpleNamespace(bias_threshold=5.0)
    baseline = baseline_analyzer._get_analysis_system_prompt(language, stock_code="2330.TW")
    assert off == baseline
    assert off.count(CORE_TRADING_SKILL_POLICY_ZH) == 1
    assert _NEW_MARKER not in off
    for line in _OLD_HARD_LINES:
        assert line in off


def test_off_user_prompt_is_unchanged():
    baseline = _make_analyzer(legacy=True)
    baseline._config_override = SimpleNamespace(bias_threshold=5.0, news_max_age_days=3, news_strategy_profile="short")
    off = _user_prompt(_analyzer(False), "2330.TW")
    assert off == _user_prompt(baseline, "2330.TW")
    for line in _OLD_USER_LINES:
        assert line in off


@pytest.mark.parametrize("legacy", [True, False])
def test_on_tw_replaces_hard_rules_with_weighted_rules(legacy):
    prompt = _analyzer(True, legacy)._get_analysis_system_prompt("zh-TW", stock_code="2330.TW")
    assert prompt.count("### " + _NEW_MARKER) == 1
    # 插在觀望段之前，而不是只附在最後
    assert prompt.index("### " + _NEW_MARKER) < prompt.index("### 观望（40-59分）：")
    assert "**多頭排列為加權加分項（非必要條件）**" in prompt
    assert "乖離率 5~10%：僅限放量突破" in prompt
    assert "外資與投信同向買超" in prompt and "ATR14" in prompt
    for line in _OLD_HARD_LINES:
        assert line not in prompt


def test_on_legacy_watch_rubric_no_longer_contradicts_breakout_exception():
    off = _analyzer(False)._get_analysis_system_prompt("zh-TW", stock_code="2330.TW")
    on = _analyzer(True)._get_analysis_system_prompt("zh-TW", stock_code="2330.TW")
    assert "- ⚠️ 乖离率 >5%（追高风险）" in off
    assert "- ⚠️ 乖离率 >5%（追高风险）" not in on
    assert "- ⚠️ 乖離率 >5% 且非放量突破，或 >10%（追高風險）" in on


def _user_prompt_with_bias(analyzer, bias: float) -> str:
    context = copy.deepcopy(_rich_context())
    context["code"] = "2330.TW"
    context["trend_analysis"]["bias_ma5"] = bias
    with patch("src.analyzer.get_config", return_value=analyzer._config_override), \
            patch.object(GeminiAnalyzer, "_tw_institutional_trend_lines", return_value=""):
        return analyzer._format_prompt(context, "台積電", news_context="n", report_language="zh-TW")


def test_on_bias_above_upper_band_keeps_hard_no_chase_label():
    # 乖離 > 2×BT 時不得把 🚨 嚴禁追高 放寬成「須放量突破」
    prompt = _user_prompt_with_bias(_analyzer(True), 12.0)
    assert "🚨 超過5%，嚴禁追高！" in prompt
    assert "⚠️ 偏高：須放量突破" not in prompt
    # 上限內仍改寫
    assert "⚠️ 偏高：須放量突破" in _user_prompt_with_bias(_analyzer(True), 9.0)


def test_on_bias_band_follows_bias_threshold():
    analyzer = _analyzer(True)
    analyzer._config_override.bias_threshold = 4.0
    prompt = analyzer._get_analysis_system_prompt("zh", stock_code="2330.TW")
    assert "乖離率 4~8%" in prompt and "> 8% 嚴禁追高" in prompt


def test_on_user_prompt_rewrites_hard_wording():
    prompt = _user_prompt(_analyzer(True), "2330.TW")
    for line in _OLD_USER_LINES:
        assert line not in prompt
    assert "為加分項" in prompt and "須放量突破＋ATR14 停損" in prompt


@pytest.mark.parametrize("code,language", [("AAPL", "zh-TW"), ("600519", "zh"), ("2330.TW", "en")])
def test_on_does_not_touch_non_tw_or_english(code, language):
    on = _analyzer(True)._get_analysis_system_prompt(language, stock_code=code)
    off = _analyzer(False)._get_analysis_system_prompt(language, stock_code=code)
    assert on == off
    assert _user_prompt(_analyzer(True), code, language) == _user_prompt(_analyzer(False), code, language)


def _analyze_dashboard(weighted: bool, code: str = "2330.TW", prompt_variant: str = "baseline", ab_ratio: float = 1.0):
    analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
    analyzer._router = None
    analyzer._litellm_available = True
    analyzer._skill_instructions_override = ""
    analyzer._default_skill_policy_override = ""
    analyzer._use_legacy_default_prompt_override = True
    analyzer._config_override = _cfg(
        weighted, prompt_variant=prompt_variant, generation_backend="litellm",
        generation_fallback_backend="litellm", litellm_model="ollama/qwen3:14b", litellm_fallback_models=[],
        llm_model_list=[], report_language="zh-TW", gemini_request_delay=0, llm_temperature=0.7,
        report_integrity_enabled=False, report_integrity_retry=0, tw_ma_alignment_ab_ratio=ab_ratio,
    )
    response = json.dumps({
        "stock_name": "台積電", "sentiment_score": 62, "trend_prediction": "看多", "operation_advice": "買入",
        "decision_type": "buy", "confidence_level": "中", "dashboard": {"core_conclusion": {"one_sentence": "x"}},
        "analysis_summary": "x",
    }, ensure_ascii=False)
    context = copy.deepcopy(_rich_context())
    context["code"] = code
    with patch("src.analyzer.get_config", return_value=analyzer._config_override), \
            patch.object(GeminiAnalyzer, "_tw_institutional_trend_lines", return_value=""), \
            patch.object(analyzer, "generate", return_value=(response, "m", {}), create=True):
        result = analyzer.analyze(context, news_context="n")
    return result.dashboard


def test_on_stamps_prompt_variant():
    assert _analyze_dashboard(True)["prompt_variant"] == TW_MA_WEIGHTED_VARIANT
    assert _analyze_dashboard(True, prompt_variant="v2")["prompt_variant"] == f"v2+{TW_MA_WEIGHTED_VARIANT}"


def test_off_or_non_tw_leaves_prompt_variant_to_pipeline():
    assert "prompt_variant" not in _analyze_dashboard(False)
    assert "prompt_variant" not in _analyze_dashboard(True, code="AAPL")


def test_ab_split_is_stable_per_day_and_roughly_follows_ratio():
    assert _tw_ma_ab_treated("2330.TW", 1.0, "2026-10-23") is True
    assert _tw_ma_ab_treated("2330.TW", 0.0, "2026-10-23") is False
    codes = [f"{n:04d}.TW" for n in range(1000, 1400)]
    picks = [_tw_ma_ab_treated(c, 0.5, "2026-10-23") for c in codes]
    assert picks == [_tw_ma_ab_treated(c, 0.5, "2026-10-23") for c in codes]   # 同一天重跑不換組
    assert 0.4 < sum(picks) / len(picks) < 0.6
    other_day = [_tw_ma_ab_treated(c, 0.5, "2026-10-26") for c in codes]
    assert picks != other_day                                                   # 換一天重新抽
    assert sum(_tw_ma_ab_treated(c, 0.2, "2026-10-23") for c in codes) < sum(picks)


@pytest.mark.parametrize("treated,variant", [(True, TW_MA_WEIGHTED_VARIANT), (False, TW_MA_CONTROL_VARIANT)])
def test_ab_split_tags_each_arm(treated, variant):
    with patch("src.analyzer._tw_ma_ab_treated", return_value=treated):
        assert _analyze_dashboard(True, ab_ratio=0.5)["prompt_variant"] == variant
        assert _analyze_dashboard(True, prompt_variant="v2", ab_ratio=0.5)["prompt_variant"] == f"v2+{variant}"


def test_ab_control_arm_gets_unchanged_prompt():
    analyzer = _analyzer(True)
    analyzer._config_override.tw_ma_alignment_ab_ratio = 0.5
    with patch("src.analyzer._tw_ma_ab_treated", return_value=False):
        control = analyzer._get_analysis_system_prompt("zh-TW", stock_code="2330.TW")
        control_user = _user_prompt(analyzer, "2330.TW")
    assert control == _analyzer(False)._get_analysis_system_prompt("zh-TW", stock_code="2330.TW")
    assert control_user == _user_prompt(_analyzer(False), "2330.TW")


def test_ab_tag_follows_the_system_prompt_actually_sent():
    # 系統提示詞分到加權組、之後重算換組（例如跨午夜）：標籤仍要跟送出的提示詞
    with patch("src.analyzer._tw_ma_ab_treated", side_effect=[True] + [False] * 10):
        assert _analyze_dashboard(True, ab_ratio=0.5)["prompt_variant"] == TW_MA_WEIGHTED_VARIANT
