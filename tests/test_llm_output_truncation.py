# -*- coding: utf-8 -*-
"""輸出截斷（finish_reason=length）的專屬路徑。

假回應都打在 `_dispatch_litellm_completion` 這個接縫：串流消費、finish_reason 判讀、
驗證器、重試迴圈、落帳全部跑真的，不會因 mock 提前 return 而假綠。
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.analyzer import ANALYSIS_MAX_OUTPUT_TOKENS, GeminiAnalyzer  # noqa: E402

# 故意塞滿看多關鍵字：若走到文字 fallback 會被算成假的「買入」
TRUNCATED_FENCED = '```json\n{"sentiment_score": 90, "analysis_summary": "看多 买入 上涨 突破 强势 利好 bullish buy'
# 沒有圍欄的截斷 JSON：json-repair 救得回來，不看 finish_reason 就會被當成完整結果
TRUNCATED_BARE = '{"sentiment_score": 90, "operation_advice": "买入", "analysis_summary": "看多'
COMPLETE = '{"sentiment_score": 61, "trend_prediction": "震荡", "operation_advice": "持有", "analysis_summary": "完整結果"}'
USAGE = {"prompt_tokens": 100, "completion_tokens": 16000, "total_tokens": 16100}


def _stream(text, finish_reason, usage=USAGE):
    """結束原因與用量放在最後一個空 delta，與 LiteLLM 的實際形狀相同。"""
    def chunks():
        if text:
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=text), finish_reason=None)],
                usage=None,
            )
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content=""), finish_reason=finish_reason)],
            usage=SimpleNamespace(**usage),
        )
    return chunks()


def _non_stream(text, finish_reason):
    message = SimpleNamespace(content=text, content_blocks=None)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason, content_blocks=None)
    return SimpleNamespace(choices=[choice], usage=SimpleNamespace(**USAGE), model="", _hidden_params={})


def _make_analyzer(language="zh-TW", integrity=False, fallback_models=None):
    analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
    analyzer._router = None
    analyzer._litellm_available = True
    analyzer._config_override = SimpleNamespace(
        gemini_request_delay=0,
        report_language=language,
        litellm_model="anthropic/claude-sonnet-5-5",
        litellm_fallback_models=fallback_models or [],
        llm_model_list=[],
        llm_temperature=0.2,
        report_integrity_enabled=integrity,
        report_integrity_retry=1 if integrity else 0,
    )
    return analyzer


def _run_analyze(analyzer, responses, *, integrity_results=None):
    """回傳 (result, 每次送出的 kwargs, persist mock, _parse_text_response spy)。"""
    sent = []
    queue = list(responses)

    def dispatch(_model, kwargs, **_ignored):
        sent.append(kwargs)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    text_fallback = MagicMock(wraps=analyzer._parse_text_response)
    with patch.object(analyzer, "is_available", return_value=True), \
         patch.object(analyzer, "_get_analysis_system_prompt", return_value="system"), \
         patch.object(analyzer, "_get_skill_prompt_sections", return_value=("", "", False)), \
         patch.object(analyzer, "_format_prompt", return_value="ORIGINAL PROMPT"), \
         patch.object(analyzer, "_dispatch_litellm_completion", side_effect=dispatch), \
         patch.object(analyzer, "_parse_text_response", text_fallback), \
         patch.object(analyzer, "_build_market_snapshot", return_value={}), \
         patch.object(
             analyzer,
             "_check_content_integrity",
             side_effect=integrity_results or [(True, [])] * 5,
         ), \
         patch("src.analyzer.persist_llm_usage") as persist:
        result = analyzer.analyze({"code": "GOOGL", "stock_name": "Alphabet"})
    assert not queue, "假回應沒有被用完，流程比預期早結束"
    return result, sent, persist, text_fallback


def _user_prompt(kwargs):
    return kwargs["messages"][-1]["content"]


def test_analysis_requests_the_raised_output_limit():
    assert ANALYSIS_MAX_OUTPUT_TOKENS == 16000
    _result, sent, _persist, _fallback = _run_analyze(_make_analyzer(), [_stream(COMPLETE, "stop")])
    assert sent[0]["max_tokens"] == 16000


@pytest.mark.parametrize("reason", ["length", "max_tokens"])
@pytest.mark.parametrize("draft", [TRUNCATED_FENCED, TRUNCATED_BARE])
def test_truncated_then_complete_resends_original_prompt(reason, draft):
    result, sent, persist, text_fallback = _run_analyze(
        _make_analyzer(),
        [_stream(draft, reason), _stream(COMPLETE, "stop")],
    )

    assert result.success is True
    assert result.sentiment_score == 61
    assert [_user_prompt(k) for k in sent] == ["ORIGINAL PROMPT", "ORIGINAL PROMPT"]
    text_fallback.assert_not_called()
    # 被截斷那次也入帳：兩次都要有
    assert persist.call_count == 2
    assert persist.call_args_list[0].args[0]["completion_tokens"] == 16000
    assert persist.call_args_list[0].kwargs == {"call_type": "analysis", "stock_code": "GOOGL"}


@pytest.mark.parametrize("draft", [TRUNCATED_FENCED, TRUNCATED_BARE])
def test_truncated_twice_fails_explicitly_without_fake_conclusion(draft):
    result, sent, persist, text_fallback = _run_analyze(
        _make_analyzer(),
        [_stream(draft, "length"), _stream(draft, "length")],
    )

    assert result.success is False
    assert "超過上限" in result.error_message
    assert "16000" in result.error_message
    assert "超過上限" in result.analysis_summary  # 外層只留前 100 字，訊息不能被切掉
    assert result.sentiment_score == 50
    assert result.decision_type != "buy"
    assert len(sent) == 2
    text_fallback.assert_not_called()
    assert persist.call_count == 2


def test_failure_message_follows_report_language():
    result, _sent, _persist, _fallback = _run_analyze(
        _make_analyzer(language="en"),
        [_stream(TRUNCATED_FENCED, "length"), _stream(TRUNCATED_FENCED, "length")],
    )
    assert "exceeded the limit" in result.error_message


def test_truncated_integrity_retry_drops_the_draft_prompt():
    """完整性重試帶草稿的 prompt 被截斷時，下一次要回到原 prompt。"""
    incomplete = '{"sentiment_score": 61, "analysis_summary": "缺欄位的草稿"}'
    result, sent, _persist, text_fallback = _run_analyze(
        _make_analyzer(integrity=True),
        [_stream(incomplete, "stop"), _stream(TRUNCATED_FENCED, "length"), _stream(COMPLETE, "stop")],
        integrity_results=[(False, ["analysis_summary"]), (True, [])],
    )

    assert result.success is True
    assert "缺欄位的草稿" in _user_prompt(sent[1])
    assert _user_prompt(sent[2]) == "ORIGINAL PROMPT"
    text_fallback.assert_not_called()


def test_truncated_draft_is_never_placed_into_integrity_retry_prompt():
    """截斷後重送的結果若仍缺欄位，補全 prompt 也只能帶完整那份，不能帶截斷草稿。"""
    incomplete = '{"sentiment_score": 61, "analysis_summary": "第二次"}'
    _result, sent, _persist, _fallback = _run_analyze(
        _make_analyzer(integrity=True),
        [_stream(TRUNCATED_FENCED, "length"), _stream(incomplete, "stop"), _stream(COMPLETE, "stop")],
        integrity_results=[(False, ["analysis_summary"]), (True, [])],
    )

    assert "第二次" in _user_prompt(sent[2])
    assert all("看多 买入" not in _user_prompt(k) for k in sent)


def test_empty_stream_with_length_counts_as_truncation():
    """預算全燒在思考：沒有可見文字也是截斷，且不多打一次非串流。"""
    result, sent, persist, _fallback = _run_analyze(
        _make_analyzer(),
        [_stream("", "length"), _stream("", "length")],
    )

    assert result.success is False
    assert "超過上限" in result.error_message
    assert all(k.get("stream") is True for k in sent)
    assert persist.call_count == 2


def _stream_then_disconnect(text, finish_reason=None, usage=None):
    """先送出內容（可含結束原因與用量），接著 iterator 拋錯。"""
    def chunks():
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content=text), finish_reason=None)],
            usage=None,
        )
        if finish_reason or usage:
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=""), finish_reason=finish_reason)],
                usage=SimpleNamespace(**usage) if usage else None,
            )
        raise ConnectionError("connection reset")
    return chunks()


def test_disconnect_after_length_is_still_truncation():
    """收到 length＋usage 後才斷線：不多打非串流、重試上限不被繞過、每次用量都入帳。"""
    result, sent, persist, text_fallback = _run_analyze(
        _make_analyzer(),
        [
            _stream_then_disconnect(TRUNCATED_FENCED, "length", USAGE),
            _stream_then_disconnect(TRUNCATED_FENCED, "length", USAGE),
        ],
    )

    assert result.success is False
    assert "超過上限" in result.error_message
    assert len(sent) == 2
    assert all(k.get("stream") is True for k in sent)
    text_fallback.assert_not_called()
    assert persist.call_count == 2
    assert all(c.args[0]["completion_tokens"] == 16000 for c in persist.call_args_list)


def test_plain_disconnect_keeps_non_stream_fallback():
    """沒收到結束原因的一般中斷不是截斷：仍走既有 partial_received 路徑改打非串流。"""
    result, sent, persist, _fallback = _run_analyze(
        _make_analyzer(),
        [_stream_then_disconnect(TRUNCATED_FENCED), _non_stream(COMPLETE, "stop")],
    )

    assert result.success is True
    assert result.sentiment_score == 61
    assert sent[0].get("stream") is True
    assert sent[1].get("stream") is None
    persist.assert_called_once()


def test_disconnect_after_normal_finish_is_not_truncation():
    """收到 stop 後才斷線同樣不算截斷，維持既有的非串流重試。"""
    result, sent, _persist, _fallback = _run_analyze(
        _make_analyzer(),
        [_stream_then_disconnect(COMPLETE, "stop", USAGE), _non_stream(COMPLETE, "stop")],
    )

    assert result.success is True
    assert sent[1].get("stream") is None


def test_non_stream_truncation_takes_the_same_path():
    """串流中斷後改走非串流時，同樣要辨識截斷。"""
    result, sent, persist, text_fallback = _run_analyze(
        _make_analyzer(),
        [
            RuntimeError("stream unavailable"),
            _non_stream(TRUNCATED_FENCED, "length"),
            _stream(COMPLETE, "stop"),
        ],
    )

    assert result.success is True
    assert sent[1].get("stream") is None
    text_fallback.assert_not_called()
    assert persist.call_count == 2


def test_fallback_model_success_still_accounts_for_truncated_call():
    """既有的模型鏈照走；第一個模型被截斷的費用不能因為第二個成功就消失。"""
    result, sent, persist, _fallback = _run_analyze(
        _make_analyzer(fallback_models=["anthropic/claude-opus-5-5"]),
        [_stream(TRUNCATED_FENCED, "length"), _stream(COMPLETE, "stop")],
    )

    assert result.success is True
    assert [k["model"] for k in sent] == ["anthropic/claude-sonnet-5-5", "anthropic/claude-opus-5-5"]
    assert [c.args[1] for c in persist.call_args_list] == [
        "anthropic/claude-sonnet-5-5",
        "anthropic/claude-opus-5-5",
    ]


# --- 反向：沒有截斷時不能走專屬路徑 ---


@pytest.mark.parametrize("reason", ["stop", "end_turn", "", None, "tool_calls"])
def test_other_finish_reasons_are_not_truncation(reason):
    result, sent, persist, _fallback = _run_analyze(_make_analyzer(), [_stream(COMPLETE, reason)])

    assert result.success is True
    assert len(sent) == 1
    persist.assert_called_once()


def test_invalid_json_without_truncation_keeps_text_fallback():
    """非法 JSON 是另一種失敗：仍走原本的文字 fallback，不被當成截斷重送。"""
    result, sent, _persist, text_fallback = _run_analyze(
        _make_analyzer(),
        [_stream("這不是 JSON", "stop")],
    )

    assert len(sent) == 1
    text_fallback.assert_called_once()
    assert result.success is False
    assert "超過上限" not in (result.error_message or "")


def test_truncation_flag_describes_only_the_last_model():
    """第一個模型截斷、第二個回非法 JSON：最後一次不是截斷，走非法 JSON 的路。"""
    result, sent, _persist, text_fallback = _run_analyze(
        _make_analyzer(fallback_models=["anthropic/claude-opus-5-5"]),
        [_stream(TRUNCATED_FENCED, "length"), _stream("這不是 JSON", "stop")],
    )

    assert len(sent) == 2
    text_fallback.assert_called_once()
    assert result.success is False


def test_callers_without_the_callback_keep_truncated_text():
    """大盤複盤這類自由文字呼叫端沒有選用：截斷文字照舊回傳，不算失敗。"""
    analyzer = _make_analyzer()
    with patch.object(analyzer, "_dispatch_litellm_completion", return_value=_non_stream("半篇複盤", "length")):
        text, _model, _usage = analyzer._call_litellm_impl("p", {"max_tokens": 10})
    assert text == "半篇複盤"

    validator = MagicMock()
    with patch.object(analyzer, "_dispatch_litellm_completion", return_value=_stream("半篇", "length")):
        text, _model, _usage = analyzer._call_litellm_impl(
            "p", {"max_tokens": 10}, stream=True, response_validator=validator,
        )
    assert text == "半篇"
    validator.assert_called_once_with("半篇")


def test_validator_is_skipped_when_truncated():
    """截斷判斷要在驗證器之前：否則 json-repair 修好的半截 JSON 會被當完整結果。"""
    analyzer = _make_analyzer()
    validator = MagicMock()
    callback = MagicMock()
    from src.analyzer import _AllModelsFailedError

    with patch.object(analyzer, "_dispatch_litellm_completion", return_value=_stream(TRUNCATED_BARE, "length")):
        with pytest.raises(_AllModelsFailedError) as caught:
            analyzer._call_litellm_impl(
                "p",
                {"max_tokens": 10, "on_output_truncated": callback},
                stream=True,
                response_validator=validator,
            )

    validator.assert_not_called()
    callback.assert_called_once()
    assert caught.value.output_truncated is True
    assert caught.value.last_response_text is None
