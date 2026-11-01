# -*- coding: utf-8 -*-
"""B04：大盤複盤 analysis_summary 取結論段第一句，不取模板標題。"""

from __future__ import annotations

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.core.market_review import _summarize_market_review  # noqa: E402

# Shape persisted for a multi-region run (DB row 1299): region title, dated
# heading, then the one-line conclusion blockquote.
_REPORT = (
    "# 台股大盤複盤\n\n"
    "## 📉 2026-10-30 大盤複盤\n\n"
    "> 加權跌 2.49%，外資賣超，短線偏空。明日先看 45,000 點能否守住。\n\n"
    "### 一、盤面總覽\n"
    "加權指數收 45,211.83 點。\n"
)


def test_summary_is_first_sentence_of_conclusion_not_title() -> None:
    summary = _summarize_market_review(_REPORT, "zh-TW")
    assert summary != "台股大盤複盤"
    assert summary == "加權跌 2.49%，外資賣超，短線偏空。"


def test_summary_english_sentence_ignores_decimal_point() -> None:
    report = "## 2026-10-30 Market Review\n\n> TAIEX fell 2.49% on foreign selling. Watch 45,000 tomorrow.\n"
    assert _summarize_market_review(report, "en") == "TAIEX fell 2.49% on foreign selling."


def test_summary_single_sentence_without_terminator_kept_whole() -> None:
    report = "## 標題\n\n> 加權跌 2.49%，外資賣超，短線偏空\n"
    assert _summarize_market_review(report, "zh-TW") == "加權跌 2.49%，外資賣超，短線偏空"


def test_summary_without_conclusion_falls_back_to_current_value() -> None:
    assert _summarize_market_review("# 台股大盤複盤\n\n### 一、盤面總覽\n內容", "zh-TW") == "台股大盤複盤"
