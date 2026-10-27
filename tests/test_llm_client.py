# -*- coding: utf-8 -*-
"""Tests for the extracted LLM transport client (src/llm/client.py).

Covers the new ``LLMClient.generate()`` composition point, and verifies
``GeminiAnalyzer.analyze()`` delegates through an injected ``LLMClient``
without touching the real transport (Commit 3 of the deepen-core refactor).

``LLMClient`` is not independently constructible (see its module docstring:
``_get_runtime_config``/``_init_litellm``/etc. stay on ``GeminiAnalyzer`` so
existing `patch("src.analyzer.<name>")` tests keep working), so these tests
exercise ``generate()``/``_call_litellm()`` through a ``GeminiAnalyzer``
instance built via the same ``__new__`` bypass pattern already used across
tests/test_market_analyzer_generate_text.py.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.analyzer import GeminiAnalyzer  # noqa: E402
from src.llm.client import LLMClient  # noqa: E402
from src.llm.generation_backend import (  # noqa: E402
    GenerationBackend,
    GenerationError,
    GenerationErrorCode,
)


def _bare_analyzer(**config_overrides):
    """GeminiAnalyzer.__new__ bypass + minimal config, no network/Router setup."""
    analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
    analyzer._router = None
    analyzer._litellm_available = True
    analyzer._config_override = SimpleNamespace(**config_overrides)
    return analyzer


def _config(**overrides):
    """Config for a *real* GeminiAnalyzer(config=...) construction: local-CLI
    backend so __init__'s unconditional _init_litellm() never tries to build a
    real litellm Router (no API keys / network needed)."""
    defaults = {
        "litellm_model": "",
        "litellm_fallback_models": [],
        "llm_model_list": [],
        "generation_backend": "codex_cli",
        "generation_fallback_backend": "",
        "llm_channel_config_issues": [],
        "llm_blocks_legacy_fallback": False,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestLLMClientGenerate:
    """LLMClient.generate() is the public composition entry point analyze() uses.

    Exercised via GeminiAnalyzer (the only concrete, fully-usable subclass) —
    see module docstring.
    """

    def test_generate_passes_system_prompt_and_validator_to_backend(self):
        client = _bare_analyzer()
        backend = MagicMock(spec=GenerationBackend)
        backend.generate.return_value = SimpleNamespace(
            text='{"ok": true}',
            model="codex_cli",
            usage={"usage_available": False, "usage_source": "unavailable", "backend": "codex_cli"},
        )
        validator = MagicMock()

        with patch.object(client, "_get_generation_backend", return_value=backend):
            text, model, usage = client.generate(
                "prompt",
                {"max_tokens": 128},
                system_prompt="custom system prompt",
                response_validator=validator,
                audit_context={"call_type": "unit_test"},
            )

        assert text == '{"ok": true}'
        assert model == "codex_cli"
        assert usage["backend"] == "codex_cli"
        # generate() must forward system_prompt/response_validator/audit_context
        # through to whichever backend _get_generation_backend() resolves — the
        # backend itself (not generate()) is responsible for invoking the validator.
        backend.generate.assert_called_once_with(
            "prompt",
            {"max_tokens": 128},
            system_prompt="custom system prompt",
            stream=False,
            stream_progress_callback=None,
            response_validator=validator,
            audit_context={"call_type": "unit_test"},
        )

    def test_generate_falls_back_to_fallback_backend_on_generation_error(self):
        client = _bare_analyzer(generation_backend="codex_cli", generation_fallback_backend="litellm")
        primary_error = GenerationError(
            error_code=GenerationErrorCode.COMMAND_NOT_FOUND,
            stage="configuration",
            retryable=False,
            fallbackable=True,
            backend="codex_cli",
            provider="codex_cli",
        )
        primary_backend = MagicMock(spec=GenerationBackend)
        primary_backend.generate.side_effect = primary_error
        fallback_backend = MagicMock(spec=GenerationBackend)
        fallback_backend.generate.return_value = SimpleNamespace(
            text="fallback text",
            model="gemini/gemini-2.0-flash",
            usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        )

        def _backend_for(backend_id=None):
            return primary_backend if backend_id == "codex_cli" else fallback_backend

        with patch.object(client, "_get_generation_backend", side_effect=_backend_for):
            text, model, usage = client.generate("prompt", {"max_tokens": 128})

        assert text == "fallback text"
        assert model == "gemini/gemini-2.0-flash"
        assert usage == {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}
        primary_backend.generate.assert_called_once()
        fallback_backend.generate.assert_called_once()

    def test_generate_returns_text_model_usage_tuple(self):
        client = _bare_analyzer()
        backend = MagicMock(spec=GenerationBackend)
        usage = {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12}
        backend.generate.return_value = SimpleNamespace(text="hello", model="codex_cli", usage=usage)

        with patch.object(client, "_get_generation_backend", return_value=backend):
            result = client.generate("prompt", {"max_tokens": 64})

        assert result == ("hello", "codex_cli", usage)


class TestAnalyzerInjectedLLMClient:
    """GeminiAnalyzer(llm_client=...) lets analyze() delegate to a test double."""

    def test_analyze_delegates_to_injected_fake_llm_client_without_network(self):
        from src.analyzer import AnalysisResult

        config = _config(
            gemini_request_delay=0,
            report_language="zh",
            llm_temperature=0.7,
            report_integrity_enabled=False,
            report_integrity_retry=0,
        )

        parsed_result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            sentiment_score=80,
            trend_prediction="看多",
            operation_advice="持有",
            analysis_summary="fake llm client result",
        )

        fake_llm_client = MagicMock(spec=LLMClient)
        fake_llm_client.generate.return_value = (
            '{"sentiment_score": 80}',
            "fake-model",
            {"usage_available": False, "usage_source": "unavailable", "backend": "fake"},
        )

        analyzer = GeminiAnalyzer(config=config, llm_client=fake_llm_client)
        assert analyzer._llm is fake_llm_client

        with patch.object(analyzer, "is_available", return_value=True), \
             patch.object(analyzer, "get_generation_backend_config_error", return_value=None), \
             patch.object(analyzer, "_get_analysis_system_prompt", return_value="system"), \
             patch.object(analyzer, "_get_skill_prompt_sections", return_value=(None, None, True)), \
             patch.object(analyzer, "_format_prompt", return_value="prompt"), \
             patch.object(analyzer, "_parse_response", return_value=parsed_result), \
             patch.object(analyzer, "_build_market_snapshot", return_value={}), \
             patch("src.analyzer.persist_llm_usage") as mock_persist, \
             patch.object(analyzer, "_call_litellm") as mock_real_call_litellm, \
             patch.object(analyzer, "_get_generation_backend") as mock_real_get_backend:
            result = analyzer.analyze({"code": "600519", "stock_name": "贵州茅台"})

        assert result.analysis_summary == "fake llm client result"
        fake_llm_client.generate.assert_called_once()
        mock_real_call_litellm.assert_not_called()
        mock_real_get_backend.assert_not_called()
        mock_persist.assert_not_called()

    def test_analyzer_without_injection_defaults_llm_client_to_self(self):
        """No llm_client passed -> self._llm is self (own inherited transport)."""
        analyzer = GeminiAnalyzer(config=_config())
        assert analyzer._llm is analyzer
        assert analyzer._resolve_llm_client() is analyzer

    def test_bypassed_init_falls_back_to_self_for_llm_client(self):
        """GeminiAnalyzer.__new__ bypass (existing test pattern) must not crash:
        _resolve_llm_client() falls back to self via the class-level default."""
        analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
        assert analyzer._resolve_llm_client() is analyzer
