# -*- coding: utf-8 -*-
"""T-report：固定預測題 p_5d_beat_0050、版本／雜湊／重試原文落庫、TW_MACRO_CONTEXT_AB_RATIO 總經 A/B。"""

import copy
import hashlib
import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import pytest

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    from tests.litellm_stub import ensure_litellm_stub

    ensure_litellm_stub()

from src import analyzer as analyzer_module
from src.analyzer import (
    GeminiAnalyzer,
    _parse_forecast_probability,
    _tw_forecast_question,
    _tw_ma_ab_treated,
    _tw_macro_ab_treated,
)
from src.services import tw_macro_context
from src.services.tw_macro_context import (
    MACRO_BLOCK_HEADINGS,
    format_macro_context_block,
    has_macro_block,
    summarize_series,
)
from tests.test_analyzer_prompt_language import _make_analyzer, _rich_context

FIXED_SENTENCE_ZH_TW = "只當資訊，不得據此調整分數或動作；未經回測"
_ROWS = [
    {"id": "^TNX", "name": "美10年殖利率", "kind": "yield", "as_of": date(2026, 10, 26), "value": 4.2,
     "chg5": 5.0, "chg20": None, "stale": False},
    {"id": "GC=F", "name": "黃金", "kind": "index", "as_of": date(2026, 10, 20), "value": 4000.0,
     "chg5": -1.5, "chg20": 3.2, "stale": True},
]


def _cfg(**extra):
    base = dict(
        tw_ma_alignment_weighted=False, bias_threshold=5.0, news_max_age_days=3, news_strategy_profile="short",
        prompt_variant="baseline", generation_backend="litellm", generation_fallback_backend="litellm",
        litellm_model="ollama/qwen3:14b", litellm_fallback_models=[], llm_model_list=[], report_language="zh-TW",
        gemini_request_delay=0, llm_temperature=0.7, report_integrity_enabled=False, report_integrity_retry=0,
        tw_macro_context_ab_ratio=0.0,
    )
    base.update(extra)
    return SimpleNamespace(**base)


def _response(**top):
    data = {
        "stock_name": "台積電", "sentiment_score": 62, "trend_prediction": "看多", "operation_advice": "買入",
        "decision_type": "buy", "confidence_level": "中", "dashboard": {"core_conclusion": {"one_sentence": "x"}},
        "analysis_summary": "x",
    }
    data.update(top)
    return json.dumps(data, ensure_ascii=False)


def _analyzer(**cfg):
    analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
    analyzer._router = None
    analyzer._litellm_available = True
    analyzer._skill_instructions_override = ""
    analyzer._default_skill_policy_override = ""
    analyzer._use_legacy_default_prompt_override = True
    analyzer._config_override = _cfg(**cfg)
    return analyzer


def _analyze(responses, code="2330.TW", usage=None, model="m", **cfg):
    """跑一次 analyze()；responses 依序是每一輪 LLM 回應。回 (result, 送出的 prompts)。"""
    analyzer = _analyzer(**cfg)
    sent, queue = [], list(responses)
    context = copy.deepcopy(_rich_context())
    context["code"] = code

    def fake_generate(prompt, *a, **k):
        sent.append(prompt)
        return queue.pop(0), model, (usage if usage is not None else {})

    with patch("src.analyzer.get_config", return_value=analyzer._config_override), \
            patch.object(GeminiAnalyzer, "_tw_institutional_trend_lines", return_value=""), \
            patch("src.analyzer.load_macro_context", return_value=list(_ROWS)), \
            patch.object(analyzer, "generate", create=True, side_effect=fake_generate):
        result = analyzer.analyze(context, news_context="n")
    return result, sent


# ---------------------------------------------------------------- 分組

CODES = [f"{n:04d}.TW" for n in range(1000, 1200)]


def test_macro_split_is_stable_and_follows_ratio():
    day = "2026-10-27"
    assert _tw_macro_ab_treated("2330.TW", 1.0, day) is True
    assert _tw_macro_ab_treated("2330.TW", 0.0, day) is False
    picks = [_tw_macro_ab_treated(c, 0.5, day) for c in CODES]
    assert picks == [_tw_macro_ab_treated(c, 0.5, day) for c in CODES]
    assert 0.4 < sum(picks) / len(picks) < 0.6


def test_macro_and_ma_experiments_are_not_correlated():
    """同一天 200 檔：兩個實驗的組別一致率要接近 50%。沒有 salt 會是 100%（兩邊吃同一個雜湊）。"""
    day = "2026-10-27"
    same = sum(_tw_macro_ab_treated(c, 0.5, day) == _tw_ma_ab_treated(c, 0.5, day) for c in CODES)
    assert 0.35 < same / len(CODES) < 0.65


def test_ma_hash_string_is_frozen():
    # 進行中的均線實驗不可換組：字串必須維持 "{code}|{day}"
    digest = hashlib.sha256("2330.TW|2026-10-27".encode()).hexdigest()
    assert _tw_ma_ab_treated("2330.TW", 0.5, "2026-10-27") == (int(digest[:8], 16) / 0x100000000 < 0.5)


# ---------------------------------------------------------------- 區塊與標籤

@pytest.mark.parametrize("ratio,expect_block,label", [(0.0, False, None), (1.0, True, "on")])
def test_ratio_zero_and_one(ratio, expect_block, label):
    result, sent = _analyze([_response()], tw_macro_context_ab_ratio=ratio)
    assert has_macro_block(sent[0]) is expect_block
    assert result.dashboard.get("experiments", {}).get("macro_ctx") == label
    if ratio == 0.0:
        assert "experiments" not in result.dashboard   # 沒設定的執行不可被誤當實驗資料


@pytest.mark.parametrize("treated,label", [(True, "on"), (False, "off")])
def test_ratio_half_label_follows_the_prompt_actually_sent(treated, label):
    with patch("src.analyzer._tw_macro_ab_treated", return_value=treated):
        result, sent = _analyze([_response()], tw_macro_context_ab_ratio=0.5)
    assert has_macro_block(sent[0]) is treated
    assert result.dashboard["experiments"]["macro_ctx"] == label
    assert "prompt_variant" not in result.dashboard   # 不串接 prompt_variant，--by-variant 才不會被拆組


def test_label_is_off_when_treated_but_data_unavailable():
    with patch("src.analyzer._tw_macro_ab_treated", return_value=True), \
            patch("src.analyzer.load_macro_context", return_value=None):
        analyzer = _analyzer(tw_macro_context_ab_ratio=0.5)
        context = copy.deepcopy(_rich_context())
        context["code"] = "2330.TW"
        with patch("src.analyzer.get_config", return_value=analyzer._config_override), \
                patch.object(GeminiAnalyzer, "_tw_institutional_trend_lines", return_value=""), \
                patch.object(analyzer, "generate", create=True, side_effect=lambda *a, **k: (_response(), "m", {})):
            result = analyzer.analyze(context, news_context="n")
    assert result.dashboard["experiments"]["macro_ctx"] == "off"   # 標籤看實際送出的 prompt，fail-open 算 off


@pytest.mark.parametrize("code,language", [("AAPL", "zh-TW"), ("2330.TW", "en")])
def test_ineligible_gets_no_block_and_no_label(code, language):
    result, sent = _analyze([_response()], code=code, tw_macro_context_ab_ratio=1.0, report_language=language)
    assert not has_macro_block(sent[0])
    assert "experiments" not in result.dashboard


def test_macro_block_never_enters_daily_market_context():
    from src.daily_market_context_guardrail import apply_daily_market_context_guardrail

    analyzer = _analyzer(tw_macro_context_ab_ratio=1.0)
    context = copy.deepcopy(_rich_context())
    context["code"] = "2330.TW"
    context["daily_market_context"] = {"summary": "大盤轉弱，市場降溫", "status": "ok"}
    before = copy.deepcopy(context["daily_market_context"])
    with patch("src.analyzer.get_config", return_value=analyzer._config_override), \
            patch.object(GeminiAnalyzer, "_tw_institutional_trend_lines", return_value=""), \
            patch("src.analyzer.load_macro_context", return_value=list(_ROWS)):
        prompt = analyzer._format_prompt(context, "台積電", news_context="n", report_language="zh-TW")
    assert has_macro_block(prompt)
    assert context["daily_market_context"] == before
    serialized = json.dumps(context["daily_market_context"], ensure_ascii=False)
    assert FIXED_SENTENCE_ZH_TW not in serialized and not any(h in serialized for h in MACRO_BLOCK_HEADINGS)
    # 護欄只吃 daily_market_context：呼叫它不會把總經字串帶進結果
    res = SimpleNamespace(decision_type="buy", operation_advice="買入", sentiment_score=70, dashboard={},
                          report_language="zh-TW", action="buy", analysis_summary="x", risk_warning="")
    apply_daily_market_context_guardrail(res, daily_market_context=context["daily_market_context"],
                                         report_language="zh-TW")
    assert FIXED_SENTENCE_ZH_TW not in json.dumps(res.__dict__, ensure_ascii=False, default=str)


def test_macro_block_comes_after_regime_block():
    analyzer = _analyzer(tw_macro_context_ab_ratio=1.0)
    context = copy.deepcopy(_rich_context())
    context["code"] = "2330.TW"
    regime = {"as_of": "2026-10-26", "above_ma60": True, "ma60_up": True, "breadth20": 0.5, "breadth60": 0.5}
    with patch("src.analyzer.get_config", return_value=analyzer._config_override), \
            patch.object(GeminiAnalyzer, "_tw_institutional_trend_lines", return_value=""), \
            patch("src.analyzer.load_tw_regime", return_value=regime), \
            patch("src.analyzer.load_macro_context", return_value=list(_ROWS)):
        prompt = analyzer._format_prompt(context, "台積電", news_context="n", report_language="zh-TW")
    assert prompt.index("### 大盤狀態") < prompt.index(MACRO_BLOCK_HEADINGS[0])


# ---------------------------------------------------------------- 區塊內容與 fail-open

@pytest.mark.parametrize("language", ["zh-TW", "zh", "en", "ko"])
def test_block_has_fixed_sentence_and_stale_flag_in_every_language(language):
    block = format_macro_context_block(_ROWS, language)
    assert has_macro_block(block)
    fixed = {"zh-TW": FIXED_SENTENCE_ZH_TW, "zh": "只当资讯，不得据此调整分数或动作；未经回测",
             "en": "do not adjust the score or the action"}[language if language != "ko" else "en"]
    assert fixed in block
    assert ("資料過期" if language == "zh-TW" else "数据过期" if language == "zh" else "stale") in block
    assert "+5.00bp" in block and "N/A" in block
    if language in ("en", "ko"):
        assert not any("一" <= ch <= "鿿" for ch in block.replace("美10年殖利率", "").replace("黃金", ""))


def test_empty_rows_give_no_block():
    assert format_macro_context_block(None, "zh-TW") == "" and format_macro_context_block([], "zh-TW") == ""


def test_summarize_series_changes_and_staleness():
    rows = [(date(2026, 10, 1 + i), 100.0 + i) for i in range(21)]
    s = summarize_series("X", "x", "index", rows, today=date(2026, 10, 22))
    assert s["value"] == 120.0 and s["chg5"] == pytest.approx((120 / 115 - 1) * 100)
    assert s["chg20"] == pytest.approx(20.0) and s["stale"] is False
    short = summarize_series("X", "x", "index", rows[-3:], today=date(2026, 10, 30))
    assert short["chg5"] is None and short["chg20"] is None and short["stale"] is True   # 回看不足不拿 0 充數
    y = summarize_series("Y", "y", "yield", [(date(2026, 10, 1), 4.0), (date(2026, 10, 2), 4.1)],
                         today=date(2026, 10, 2))
    assert y["chg5"] is None
    y5 = summarize_series("Y", "y", "yield", [(date(2026, 10, 1 + i), 4.0 + 0.01 * i) for i in range(6)],
                          today=date(2026, 10, 6))
    assert y5["chg5"] == pytest.approx(5.0)   # bp
    assert summarize_series("Z", "z", "index", [(date(2026, 10, 1), float("nan"))], today=date(2026, 10, 2)) is None


def test_load_macro_context_fails_open_and_caches_failure():
    tw_macro_context._load_cached.cache_clear()
    with patch("market_data.db.get_engine", side_effect=RuntimeError("no db")) as eng:
        assert tw_macro_context.load_macro_context(date(2026, 10, 27)) is None
        assert tw_macro_context.load_macro_context(date(2026, 10, 27)) is None
    assert eng.call_count == 1
    tw_macro_context._load_cached.cache_clear()


# ---------------------------------------------------------------- 固定預測題

def test_forecast_question_only_for_tw_and_every_language():
    for language in ("zh-TW", "zh", "en", "ko"):
        q = _tw_forecast_question(language)
        assert "p_5d_beat_0050" in q and "0050" in q
    result, sent = _analyze([_response()])
    assert "p_5d_beat_0050" in sent[0]
    _, sent_us = _analyze([_response()], code="AAPL")
    assert "p_5d_beat_0050" not in sent_us[0]


@pytest.mark.parametrize("value,expected", [
    (0.73, 0.73), (0, 0.0), (1, 1.0), ("0.4", 0.4),
    ("73%", None), (1.5, None), (-0.1, None), (float("nan"), None), (float("inf"), None),
    (None, None), (True, None), ([0.5], None), ("", None),
])
def test_parse_forecast_probability_is_strict(value, expected):
    assert _parse_forecast_probability(value) == expected


def test_parse_response_reads_p_into_result_dashboard_and_to_dict():
    result, _ = _analyze([_response(p_5d_beat_0050=0.73)])
    assert result.p_5d_beat_0050 == 0.73
    assert result.dashboard["forecast"] == {
        "question": "p_5d_beat_0050", "p": 0.73, "horizon_sessions": 5, "benchmark": "0050"}
    assert result.to_dict()["p_5d_beat_0050"] == 0.73


@pytest.mark.parametrize("bad", ["73%", 1.5, float("nan"), "missing"])
def test_bad_or_missing_p_is_none_not_half_and_triggers_no_placeholder(bad):
    top = {} if bad == "missing" else {"p_5d_beat_0050": bad}
    result, sent = _analyze([_response(**top)])
    assert result.p_5d_beat_0050 is None
    assert "forecast" not in result.dashboard
    assert len(sent) == 1   # 缺值不觸發完整性重試
    analyzer = _analyzer()
    ok, missing = analyzer._check_content_integrity(result)
    assert "p_5d_beat_0050" not in missing and not any("p_5d" in m for m in missing)


def test_non_tw_response_ignores_p():
    result, _ = _analyze([_response(p_5d_beat_0050=0.9)], code="AAPL")
    assert result.p_5d_beat_0050 is None and "forecast" not in (result.dashboard or {})


def test_forecast_value_untouched_by_guardrails():
    # 護欄壓分／改動作不會碰機率：p 是模型對「5 日勝過 0050」的獨立讀數
    result, _ = _analyze([_response(p_5d_beat_0050=0.31, sentiment_score=85)])
    assert result.p_5d_beat_0050 == 0.31 and result.dashboard["forecast"]["p"] == 0.31


# ---------------------------------------------------------------- 版本／雜湊／重試原文

def test_hashes_and_model_version_from_cli_model():
    result, sent = _analyze([_response()], usage={"cli_model": "claude-fable-5-1"}, model="claude_code_cli")
    analyzer = _analyzer()
    system_prompt = analyzer._get_analysis_system_prompt("zh-TW", stock_code="2330.TW")
    assert result.model_version == "claude-fable-5-1" and result.model_used == "claude_code_cli"
    assert result.input_snapshot_hash == hashlib.sha256(sent[0].encode()).hexdigest()
    assert result.prompt_hash == hashlib.sha256(system_prompt.encode()).hexdigest()
    assert len(result.prompt_hash) == len(result.input_snapshot_hash) == 64


def test_model_version_falls_back_to_model_used_for_litellm():
    result, _ = _analyze([_response()], usage={}, model="anthropic/claude-sonnet-5-5")
    assert result.model_version == "anthropic/claude-sonnet-5-5"


def test_integrity_retry_records_every_round_and_snapshot_hash_is_first_prompt():
    incomplete = _response(p_5d_beat_0050=0.2, dashboard={"core_conclusion": {}}, operation_advice="")
    complete = _response(p_5d_beat_0050=0.6)
    with patch.object(GeminiAnalyzer, "_check_content_integrity",
                      side_effect=[(False, ["operation_advice"]), (True, [])]):
        result, sent = _analyze([incomplete, complete], report_integrity_enabled=True, report_integrity_retry=1)
    assert len(sent) == 2 and sent[0] != sent[1]
    assert [a["attempt"] for a in result.llm_attempts] == [1, 2]
    assert [a["response_text"] for a in result.llm_attempts] == [incomplete, complete]
    assert result.raw_response == complete                       # 舊行為不變：raw_response 留最後一輪
    assert result.input_snapshot_hash == hashlib.sha256(sent[0].encode()).hexdigest()
    assert result.p_5d_beat_0050 == 0.6


def test_single_round_still_records_one_attempt():
    result, _ = _analyze([_response()])
    assert len(result.llm_attempts) == 1 and result.llm_attempts[0]["attempt"] == 1


def test_failure_path_returns_fields_unset():
    analyzer = _analyzer()
    context = copy.deepcopy(_rich_context())
    context["code"] = "2330.TW"
    with patch("src.analyzer.get_config", return_value=analyzer._config_override), \
            patch.object(GeminiAnalyzer, "_tw_institutional_trend_lines", return_value=""), \
            patch.object(analyzer, "generate", create=True, side_effect=RuntimeError("boom")):
        result = analyzer.analyze(context, news_context="n")
    assert result.success is False
    assert result.p_5d_beat_0050 is None and result.prompt_hash is None and result.llm_attempts is None
