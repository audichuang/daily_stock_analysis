# -*- coding: utf-8 -*-
"""zh-TW 个股 prompt 本体必须是繁体（fork 增量，守上游 #2368 合并后的三语分流）。

上游 #2368 把 `_format_prompt` 每个区块改成「英文 / 简体」二分；本 fork 的 zh-TW 繁体
分支是在同一批位置加的。合并时任何一处取错边，zh-TW 都会静默退回简体（不报错、
测试原本也不会红），而 prompt 本体的语言会压过语言指令——模型就照样输出简体。
"""

import copy
import re
from types import SimpleNamespace
from unittest.mock import patch

import pytest

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    from tests.litellm_stub import ensure_litellm_stub

    ensure_litellm_stub()

from src.analyzer import GeminiAnalyzer, _legacy_audit_marker_specs
from tests.test_analyzer_prompt_language import _cjk_chars, _make_analyzer, _rich_context

# (繁體, 對應的簡體)：每一组都落在 #2368 合并时有冲突的区块。
_TW_MARKERS = [
    ("# 決策儀表盤分析請求", "# 决策仪表盘分析请求"),
    ("## 📈 技術面數據", "## 📈 技术面数据"),
    ("## 📰 輿情情報", "## 📰 舆情情报"),
    ("| 開盤價 |", "| 开盘价 |"),
    ("財報與股利（價值投資口徑）", "财报与分红（价值投资口径）"),
    ("主力資金流向（操作建議過濾器）", "主力资金流向（操作建议过滤器）"),
    ("三大法人動向（台股籌碼過濾器", "三大法人动向（台股筹码过滤器"),
    ("趨勢分析預判（基於交易理念）", "趋势分析预判（基于交易理念）"),
    ("### 量價變化", "### 量价变化"),
    ("量能異常提示", "量能异常提示"),
    ("⚠️ **資料缺失警告**", "⚠️ **数据缺失警告**"),
    ("指數/ETF 分析約束", "指数/ETF 分析约束"),
    ("⚠️ 重要：輸出正確的股票名稱格式", "⚠️ 重要：输出正确的股票名称格式"),
]

_FAKE_CFG = SimpleNamespace(news_max_age_days=3, news_strategy_profile="short")


def _prompt(language: str, *, code: str = "AAPL", legacy: bool = True, news: str = "n") -> str:
    context = copy.deepcopy(_rich_context())
    context["code"] = code
    context["trend_analysis"]["atr14_pct"] = 2.5  # exercises the TW trade-cost ATR line
    analyzer = _make_analyzer(legacy=legacy)
    with patch("src.analyzer.get_config", return_value=_FAKE_CFG), \
            patch.object(GeminiAnalyzer, "_tw_institutional_trend_lines", return_value=""):
        return analyzer._format_prompt(context, "Apple", news_context=news, report_language=language)


def test_zh_tw_prompt_body_is_traditional():
    prompt = _prompt("zh-TW")
    for tw, zh in _TW_MARKERS:
        assert tw in prompt, tw
        assert zh not in prompt, zh


def test_zh_prompt_body_stays_simplified():
    prompt = _prompt("zh")
    for tw, zh in _TW_MARKERS:
        assert zh in prompt, zh
        assert tw not in prompt, tw


def test_zh_tw_audit_markers_match_the_prompt_headers():
    markers = {
        m["marker_name"]: m["text"]
        for m in _legacy_audit_marker_specs(
            {"date": "2026-03-16"},
            code="AAPL",
            stock_name="Apple",
            report_language="zh-TW",
            news_context="news",
            analysis_context_pack_summary=None,
        )
    }
    prompt = _prompt("zh-TW")
    assert markers["quote"] == "## 📈 技術面數據"
    assert markers["news_context"] == "## 📰 輿情情報"
    assert markers["quote"] in prompt and markers["news_context"] in prompt


def test_tw_stock_amounts_follow_market_currency_and_language():
    # zh-TW 台股：币别跟着市场走（新台币）；en：英文量级、无中文。
    zh_tw = _prompt("zh-TW", code="2330.TW")
    assert "9.88 億新台幣" in zh_tw
    assert "### 台股交易成本（給價位前必須扣除）" in zh_tw
    assert "正常波動（ATR14）約 2.50%" in zh_tw
    en = _prompt("en", code="2330.TW")
    assert _cjk_chars(en) == ""
    assert "| Turnover | 987.65M |" in en
    assert "### Taiwan Trading Costs" in en
    assert "normal daily range (ATR14) is about 2.50%" in en


def test_format_amount_takes_market_before_language():
    analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
    assert analyzer._format_amount(1e9, "tw") == "10.00 亿新台币"
    assert analyzer._format_amount(1e9, "tw", "zh-TW") == "10.00 億新台幣"
    assert analyzer._format_amount(1e9, "us", "en") == "1.00B"


def _trend_lines(language: str) -> str:
    rows = [
        {"date": "2026-07-07", "foreign_net": 100, "trust_net": 0, "dealer_net": 0, "total_net": 100},
        {"date": "2026-07-08", "foreign_net": 200, "trust_net": 0, "dealer_net": 0, "total_net": 200},
    ]

    class _DF:
        empty = False

        def to_dict(self, orient):
            return rows

    with patch("market_data.market_repo.institutional", return_value=_DF()), \
            patch("market_data.market_repo.stock_info", return_value={"shares_outstanding": 100000}), \
            patch("market_data.db.get_engine", return_value=None):
        return GeminiAnalyzer.__new__(GeminiAnalyzer)._tw_institutional_trend_lines(
            "2330.TW",
            {"foreign_net": 300, "trust_net": 0, "dealer_net": 0, "total_net": 300, "date": "20260709"},
            language,
        )


def test_institutional_trend_lines_per_language():
    en = _trend_lines("en")
    assert en and _cjk_chars(en) == ""
    assert "Foreign investors: net buying" in en
    tw = _trend_lines("zh-TW")
    assert "三大法人近期趨勢" in tw and "外資：" in tw
    zh = _trend_lines("zh")
    assert "三大法人近期趋势" in zh and re.search(r"外资：", zh)


def test_sell_sniper_and_cost_rules_route_waiting_price_to_watch_conditions():
    # 減倉／賣出或條件未成立時買點寫「暫不設定」，等待價位改寫進 watch_conditions，停利只給一個價
    zh_tw = _prompt("zh-TW", code="2330.TW")
    assert "`ideal_buy`、`secondary_buy` 只寫「暫不設定」、不得寫任何價位" in zh_tw
    assert "`take_profit` 只寫一個價位（減倉／賣出時是仍有部位的反彈減碼價）" in zh_tw
    assert "要等的更低買點寫進 `dashboard.phase_decision.watch_conditions`" in zh_tw
    assert "說明要等哪個更低的買點" not in zh_tw
    assert "暂不设定" not in zh_tw  # zh-TW 本體不得混入簡體
    zh = _prompt("zh", code="2330.TW")
    assert "`ideal_buy`、`secondary_buy` 只写“暂不设定”、不得写任何价位" in zh
    assert "要等的更低买点写进 `dashboard.phase_decision.watch_conditions`" in zh
    assert "暫不設定" not in zh
    en = _prompt("en", code="2330.TW")
    assert '`ideal_buy` and `secondary_buy` must be exactly "N/A"' in en
    assert "`take_profit` holds exactly one price" in en
    assert "put the lower entry to wait for in `dashboard.phase_decision.watch_conditions`" in en
    assert "name the lower entry to wait for" not in en
    assert _cjk_chars(en) == ""


# 模板本體常見的簡體字；任何一個出現在 zh-TW 系統提示詞都表示語言分流失效。
_SIMPLIFIED_SAMPLE = "决仪盘数据买卖减仓观风险资讯评级预设处层总结"


def _system_prompt(language: str, *, legacy: bool) -> str:
    return _make_analyzer(legacy=legacy)._get_analysis_system_prompt(language, stock_code="2330.TW")


def test_zh_tw_system_prompt_body_is_traditional():
    for legacy in (True, False):
        prompt = _system_prompt("zh-TW", legacy=legacy)
        leftovers = sorted(set(prompt) & set(_SIMPLIFIED_SAMPLE))
        assert leftovers == [], leftovers
        assert "決策儀表盤" in prompt
        assert "減碼" in prompt and "停損" in prompt
        assert "買進、加碼、續抱" in prompt  # 詞彙表
        assert "買入、加倉、持有、減倉" in prompt  # 詞彙表的「不要寫」


def test_other_language_system_prompts_are_not_converted():
    for legacy in (True, False):
        zh = _system_prompt("zh", legacy=legacy)
        assert "决策仪表盘" in zh and "決策儀表盤" not in zh
        assert "用語（繁體中文報告必須遵守）" not in zh
        for language in ("en", "ko"):
            other = _system_prompt(language, legacy=legacy)
            assert "Decision Dashboard" in other
            assert "用語（繁體中文報告必須遵守）" not in other


@pytest.mark.parametrize("legacy", [True, False])
def test_system_prompt_scopes_summary_and_splits_watch_conditions(legacy):
    zh_tw = _system_prompt("zh-TW", legacy=legacy)
    for key in ("entry_conditions", "exit_triggers", "pending_events", "watch_conditions"):
        assert f'"{key}"' in zh_tw
    assert "不得出現“依規則”“判定為”" in zh_tw
    assert "不引用任何評分數字" in zh_tw
    assert "100字綜合分析摘要" not in zh_tw


@pytest.mark.parametrize("legacy", [True, False])
@pytest.mark.parametrize("language", ["zh", "en", "ko"])
def test_other_languages_do_not_get_zh_tw_report_contract(language, legacy):
    prompt = _system_prompt(language, legacy=legacy)
    assert '"watch_conditions"' in prompt
    for key in ("entry_conditions", "exit_triggers", "pending_events"):
        assert f'"{key}"' not in prompt
    assert "不得出现“依规则”" not in prompt and "per the rules" not in prompt


@pytest.mark.parametrize("legacy", [True, False])
@pytest.mark.parametrize("language,has_contract", [("zh-TW", True), ("zh", False), ("en", False), ("ko", False)])
def test_agent_system_prompt_applies_report_contract_only_to_zh_tw(language, has_contract, legacy):
    from unittest.mock import Mock

    from src.agent.executor import AgentExecutor

    executor = AgentExecutor.__new__(AgentExecutor)
    executor.skill_instructions = ""
    executor.default_skill_policy = ""
    executor.use_legacy_default_prompt = legacy
    executor.tool_registry = Mock()
    executor.tool_registry.to_openai_tools.return_value = []
    executor._run_loop = Mock()
    executor.run("Analyze", {"stock_code": "2330.TW", "report_language": language})
    system = executor._run_loop.call_args.args[0][0]["content"]
    assert ('"entry_conditions"' in system) is has_contract
    assert ("不引用任何評分數字" in system) is has_contract


def test_prompts_do_not_teach_role_prefixes() -> None:
    """範例寫「空仓者建议：」時模型會照抄，轉繁體後整份報告都是「空手者」「持股者」。"""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for rel in ("src/analyzer.py", "src/agent/executor.py"):
        text = (root / rel).read_text(encoding="utf-8")
        assert '"no_position": "空仓者' not in text, rel
        assert '"has_position": "持仓者' not in text, rel
        assert "时为持仓者" not in text and "時是持股者" not in text, rel
        assert not re.search(r"空仓者和持仓者给", text), rel
        assert text.count("都不用“空仓者”“持仓者”这类身份称呼") == text.count("**分持仓建议**"), rel
