# -*- coding: utf-8 -*-
"""Unit tests for report language helpers."""

import unittest

from src.report_language import (
    SUPPORTED_REPORT_LANGUAGES,
    _OPERATION_ADVICE_TRANSLATIONS,
    _TREND_PREDICTION_TRANSLATIONS,
    _CONFIDENCE_LEVEL_TRANSLATIONS,
    _CHIP_HEALTH_TRANSLATIONS,
    _BIAS_STATUS_TRANSLATIONS,
    get_bias_status_emoji,
    get_localized_stock_name,
    get_report_labels,
    get_sentiment_label,
    get_signal_level,
    infer_decision_type_from_advice,
    is_supported_report_language_value,
    localize_operation_advice,
    localize_trend_prediction,
    localize_bias_status,
    normalize_report_language,
    report_table_rows,
)
from src.utils.zh_s2t import localize_template, to_traditional


class ReportLanguageTestCase(unittest.TestCase):
    def test_get_signal_level_handles_compound_sell_advice(self) -> None:
        signal_text, emoji, signal_tag = get_signal_level("卖出/观望", 60, "zh")

        self.assertEqual(signal_text, "卖出")
        self.assertEqual(emoji, "🔴")
        self.assertEqual(signal_tag, "sell")

    def test_get_signal_level_handles_compound_buy_advice_in_english(self) -> None:
        signal_text, emoji, signal_tag = get_signal_level("Buy / Watch", 40, "en")

        self.assertEqual(signal_text, "Buy")
        self.assertEqual(emoji, "🟢")
        self.assertEqual(signal_tag, "buy")

    def test_get_signal_level_score_fallback_uses_canonical_scale(self) -> None:
        self.assertEqual(get_signal_level("", 28, "zh"), ("减仓", "🟠", "reduce"))
        self.assertEqual(get_signal_level("", 38, "zh"), ("减仓", "🟠", "reduce"))
        self.assertEqual(get_signal_level("", 42, "zh"), ("观望", "⚪", "watch"))
        self.assertEqual(get_signal_level("", 55, "zh"), ("观望", "⚪", "watch"))
        self.assertEqual(get_signal_level("", 60, "zh"), ("买入", "🟢", "buy"))
        self.assertEqual(get_signal_level("", 66, "zh"), ("买入", "🟢", "buy"))
        self.assertEqual(get_signal_level("", 72, "zh"), ("买入", "🟢", "buy"))

    def test_get_localized_stock_name_replaces_placeholder_for_english(self) -> None:
        self.assertEqual(
            get_localized_stock_name("股票AAPL", "AAPL", "en"),
            "Unnamed Stock",
        )

    def test_get_sentiment_label_preserves_higher_band_thresholds(self) -> None:
        self.assertEqual(get_sentiment_label(80, "en"), "Very Bullish")
        self.assertEqual(get_sentiment_label(60, "en"), "Bullish")
        self.assertEqual(get_sentiment_label(40, "zh"), "中性")
        self.assertEqual(get_sentiment_label(20, "zh"), "悲观")

    def test_localize_trend_prediction_preserves_fine_grain_zh_states(self) -> None:
        self.assertEqual(localize_trend_prediction("多头排列", "zh"), "多头排列")
        self.assertEqual(localize_trend_prediction("弱势空头", "zh"), "弱势空头")

    def test_localize_trend_prediction_still_translates_english_input_for_zh(self) -> None:
        self.assertEqual(localize_trend_prediction("bullish", "zh"), "看多")
        self.assertEqual(localize_trend_prediction("very bearish", "zh"), "强烈看空")

    def test_bias_status_helpers_support_english_values(self) -> None:
        self.assertEqual(localize_bias_status("Safe", "en"), "Safe")
        self.assertEqual(localize_bias_status("警戒", "en"), "Caution")
        self.assertEqual(get_bias_status_emoji("Safe"), "✅")
        self.assertEqual(get_bias_status_emoji("Caution"), "⚠️")

    def test_infer_decision_type_from_advice_accepts_canonical_labels(self) -> None:
        cases = {
            "强烈买入": "buy", "买入": "buy", "加仓": "buy",
            "持有": "hold", "洗盘观察": "hold", "观察": "hold", "观望": "hold",
            "减仓": "sell", "卖出": "sell", "强烈卖出": "sell",
            " Buy ": "buy", "strong_buy": "buy", "Hold": "hold", "Sell": "sell",
        }
        for label, expected in cases.items():
            with self.subTest(label=label):
                self.assertEqual(infer_decision_type_from_advice(label, default=""), expected)

    def test_infer_decision_type_from_advice_does_not_split_separated_text(self) -> None:
        # 整段才算標籤：不可依 /|,，、 拆段後逐段查表，否則否定句會被讀成買入
        for advice in (
            "不建议买入、加仓", "不宜追高/买入", "Buy / Watch", "卖出/观望", "观望，买入",
        ):
            for default in ("", "hold"):
                with self.subTest(advice=advice, default=default):
                    self.assertEqual(infer_decision_type_from_advice(advice, default=default), default)

    def test_infer_decision_type_from_advice_free_text_uses_caller_default(self) -> None:
        for advice in (
            "建议买入", "建議現在買入", "建议持有", "建议减仓", "继续持有",
            "建议洗盘观察", "不建议买入", "当前不跌破支撑位继续持有",
            "不破支撑后仍可持有", "Buy now", "Do not sell", "즉시 매수", None, "",
        ):
            for default in ("", "hold", "sell"):
                with self.subTest(advice=advice, default=default):
                    self.assertEqual(infer_decision_type_from_advice(advice, default=default), default)


class ZhTWLanguageNormalizationTestCase(unittest.TestCase):
    """測試繁體中文語言代碼的正規化與支援。"""

    def test_normalize_zh_tw_lowercase_dash(self) -> None:
        self.assertEqual(normalize_report_language("zh-tw"), "zh-TW")

    def test_normalize_zh_tw_lowercase_underscore(self) -> None:
        self.assertEqual(normalize_report_language("zh_tw"), "zh-TW")

    def test_is_supported_report_language_value_zh_TW(self) -> None:
        self.assertTrue(is_supported_report_language_value("zh-TW"))

    def test_supported_report_languages_contains_zh_TW(self) -> None:
        self.assertIn("zh-TW", SUPPORTED_REPORT_LANGUAGES)

    def test_operation_advice_translations_contain_zh_TW(self) -> None:
        for canonical_key, translations in _OPERATION_ADVICE_TRANSLATIONS.items():
            self.assertIn(
                "zh-TW",
                translations,
                msg=f"_OPERATION_ADVICE_TRANSLATIONS['{canonical_key}'] 缺少 'zh-TW'",
            )

    def test_trend_prediction_translations_contain_zh_TW(self) -> None:
        for canonical_key, translations in _TREND_PREDICTION_TRANSLATIONS.items():
            self.assertIn(
                "zh-TW",
                translations,
                msg=f"_TREND_PREDICTION_TRANSLATIONS['{canonical_key}'] 缺少 'zh-TW'",
            )

    def test_localize_trend_prediction_translates_simplified_sideways_for_zh_TW(self) -> None:
        self.assertEqual(localize_trend_prediction("震荡", "zh-TW"), "震盪")
        self.assertEqual(localize_trend_prediction("震荡", "zh"), "震荡")

    def test_confidence_level_translations_contain_zh_TW(self) -> None:
        for canonical_key, translations in _CONFIDENCE_LEVEL_TRANSLATIONS.items():
            self.assertIn(
                "zh-TW",
                translations,
                msg=f"_CONFIDENCE_LEVEL_TRANSLATIONS['{canonical_key}'] 缺少 'zh-TW'",
            )

    def test_chip_health_translations_contain_zh_TW(self) -> None:
        for canonical_key, translations in _CHIP_HEALTH_TRANSLATIONS.items():
            self.assertIn(
                "zh-TW",
                translations,
                msg=f"_CHIP_HEALTH_TRANSLATIONS['{canonical_key}'] 缺少 'zh-TW'",
            )

    def test_bias_status_translations_contain_zh_TW(self) -> None:
        for canonical_key, translations in _BIAS_STATUS_TRANSLATIONS.items():
            self.assertIn(
                "zh-TW",
                translations,
                msg=f"_BIAS_STATUS_TRANSLATIONS['{canonical_key}'] 缺少 'zh-TW'",
            )

    def test_get_report_labels_zh_TW_key_count_matches_zh(self) -> None:
        labels_zh = get_report_labels("zh")
        labels_zh_tw = get_report_labels("zh-TW")
        self.assertEqual(
            set(labels_zh.keys()),
            set(labels_zh_tw.keys()),
            msg="get_report_labels('zh-TW') 的鍵數與 'zh' 不一致",
        )

    def test_get_sentiment_label_zh_TW_returns_traditional_chinese(self) -> None:
        label = get_sentiment_label(85, "zh-TW")
        self.assertEqual(label, "極度樂觀")

    def test_get_sentiment_label_zh_TW_all_bands(self) -> None:
        self.assertEqual(get_sentiment_label(85, "zh-TW"), "極度樂觀")
        self.assertEqual(get_sentiment_label(65, "zh-TW"), "樂觀")
        self.assertEqual(get_sentiment_label(50, "zh-TW"), "中性")
        self.assertEqual(get_sentiment_label(30, "zh-TW"), "悲觀")
        self.assertEqual(get_sentiment_label(10, "zh-TW"), "極度悲觀")

    def test_zh_TW_sentiment_labels_are_traditional_not_simplified(self) -> None:
        """確認繁體標籤不含僅出現於簡體的字形（如「乐」→「樂」、「极」→「極」）。"""
        # 只列出繁簡有字形差異的字：乐→樂、极→極（悲、观 兩岸相同，不列入）
        simplified_only_chars = set("乐极")
        for score in (85, 65, 50, 30, 10):
            label = get_sentiment_label(score, "zh-TW")
            for ch in simplified_only_chars:
                self.assertNotIn(
                    ch,
                    label,
                    msg=f"get_sentiment_label({score}, 'zh-TW') = '{label}' 含簡體字 '{ch}'",
                )

    def test_operation_advice_zh_TW_values_are_traditional(self) -> None:
        """確認操作建議翻譯不含僅出現於簡體的字形。
        只列繁簡有字形差異的字：买→買、卖→賣、减→減、仓→倉、观→觀、强→強。
        「烈」兩岸字形相同，不列入。
        """
        simplified_only_chars = set("买卖减仓观强")
        for canonical_key, translations in _OPERATION_ADVICE_TRANSLATIONS.items():
            zh_tw_value = translations.get("zh-TW", "")
            for ch in simplified_only_chars:
                self.assertNotIn(
                    ch,
                    zh_tw_value,
                    msg=(
                        f"_OPERATION_ADVICE_TRANSLATIONS['{canonical_key}']['zh-TW'] = "
                        f"'{zh_tw_value}' 含簡體字 '{ch}'"
                    ),
                )


class KoreanReportLanguageTestCase(unittest.TestCase):
    def test_korean_is_supported(self) -> None:
        self.assertIn("ko", SUPPORTED_REPORT_LANGUAGES)

    def test_normalize_korean_aliases(self) -> None:
        self.assertEqual(normalize_report_language("ko"), "ko")
        self.assertEqual(normalize_report_language("korean"), "ko")
        self.assertEqual(normalize_report_language("ko-KR"), "ko")
        self.assertEqual(normalize_report_language("kr"), "ko")

    def test_unknown_language_falls_back_to_default(self) -> None:
        self.assertEqual(normalize_report_language("fr"), "zh")
        self.assertEqual(normalize_report_language(None), "zh")

    def test_korean_labels_cover_full_english_key_set(self) -> None:
        ko_labels = get_report_labels("ko")
        en_labels = get_report_labels("en")
        zh_labels = get_report_labels("zh")
        self.assertEqual(set(ko_labels.keys()), set(en_labels.keys()))
        self.assertEqual(set(zh_labels.keys()), set(en_labels.keys()))
        self.assertEqual(ko_labels["dashboard_title"], "결정 대시보드")
        self.assertEqual(ko_labels["risk_alerts_label"], "리스크 경보")

    def test_data_sources_label_is_localized(self) -> None:
        self.assertEqual(get_report_labels("zh")["data_sources_label"], "数据来源")
        self.assertEqual(get_report_labels("en")["data_sources_label"], "Data Sources")
        self.assertEqual(get_report_labels("ko")["data_sources_label"], "데이터 출처")

    def test_korean_sentiment_label_bands(self) -> None:
        self.assertEqual(get_sentiment_label(80, "ko"), "매우 낙관")
        self.assertEqual(get_sentiment_label(40, "ko"), "중립")
        self.assertEqual(get_sentiment_label(0, "ko"), "매우 비관")

    def test_korean_operation_advice_and_trend(self) -> None:
        self.assertEqual(localize_operation_advice("买入", "ko"), "매수")
        self.assertEqual(localize_operation_advice("strong sell", "ko"), "적극 매도")
        self.assertEqual(localize_trend_prediction("bullish", "ko"), "상승")

    def test_korean_localized_stock_name_placeholder(self) -> None:
        self.assertEqual(
            get_localized_stock_name("股票AAPL", "AAPL", "ko"),
            "미확인 종목",
        )

    def test_existing_languages_unchanged(self) -> None:
        self.assertEqual(get_sentiment_label(80, "en"), "Very Bullish")
        self.assertEqual(get_sentiment_label(40, "zh"), "中性")

    def test_korean_advice_canonicalizes_to_decision_type(self) -> None:
        self.assertEqual(infer_decision_type_from_advice("매수"), "buy")
        self.assertEqual(infer_decision_type_from_advice("매도"), "sell")
        self.assertEqual(infer_decision_type_from_advice("보유"), "hold")
        self.assertEqual(infer_decision_type_from_advice("관망"), "hold")

    def test_korean_advice_resolves_signal_level(self) -> None:
        self.assertEqual(get_signal_level("매수", 72, "ko"), ("매수", "🟢", "buy"))
        self.assertEqual(get_signal_level("매도", 30, "ko"), ("매도", "🔴", "sell"))

    def test_korean_values_canonicalize_back_for_other_languages(self) -> None:
        self.assertEqual(localize_trend_prediction("상승", "en"), "Bullish")
        self.assertEqual(localize_operation_advice("적극 매도", "zh"), "强烈卖出")


if __name__ == "__main__":
    unittest.main()


class TestZhTwVocabulary(unittest.TestCase):
    def test_new_labels_follow_glossary(self) -> None:
        for canonical, label in (("买入", "買進"), ("持有", "續抱"), ("减仓", "減碼"), ("强烈买入", "強烈買進")):
            self.assertEqual(localize_operation_advice(canonical, "zh-TW"), label)

    def test_legacy_and_new_words_keep_resolving(self) -> None:
        # 舊報告的詞與新詞都要解析得回來；移除別名這裡會紅。
        cases = {
            "減倉": "sell", "減碼": "sell", "买进": "buy", "買進": "buy", "買入": "buy",
            "加碼": "buy", "加倉": "buy", "續抱": "hold", "觀望": "hold", "賣出": "sell",
        }
        for word, expected in cases.items():
            self.assertEqual(infer_decision_type_from_advice(word, default="unknown"), expected, word)

    def test_legacy_reduce_displays_as_new_label(self) -> None:
        self.assertEqual(localize_operation_advice("減倉", "zh-TW"), "減碼")
        self.assertEqual(localize_operation_advice("買入", "zh-TW"), "買進")
        self.assertEqual(get_signal_level("減倉", 50, "zh-TW"), ("減碼", "🟠", "reduce"))

    def test_other_languages_keep_their_labels(self) -> None:
        self.assertEqual(localize_operation_advice("減碼", "zh"), "减仓")
        self.assertEqual(localize_operation_advice("減碼", "en"), "Reduce")
        self.assertEqual(localize_operation_advice("減碼", "ko"), "비중축소")

    def test_table_headers_per_language(self) -> None:
        expected = {
            "zh-TW": ("項目", "數值", "點位", "價格"),
            "zh": ("项目", "数值", "点位", "价格"),
            "en": ("Item", "Value", "Level", "Price"),
            "ko": ("항목", "수치", "가격대", "가격"),
        }
        for language, headers in expected.items():
            labels = get_report_labels(language)
            self.assertEqual(
                (
                    labels["table_item_label"], labels["table_value_label"],
                    labels["table_level_label"], labels["table_price_label"],
                ),
                headers,
            )

    def test_report_table_rows_omits_only_missing_values(self) -> None:
        rows = report_table_rows([
            ("A", None), ("B", float("nan")), ("C", "N/A"), ("D", "nan"), ("E", 0), ("F", "12.5"),
        ])
        self.assertEqual(rows, ["| E | 0 |", "| F | 12.5 |"])


class TestZhS2T(unittest.TestCase):
    def test_converts_template_text_and_taiwan_terms(self) -> None:
        self.assertEqual(to_traditional("空仓者的止损价位"), "空手者的停損價位")
        self.assertEqual(to_traditional("买入后减仓，持仓数据"), "買進後減碼，持股資料")
        self.assertEqual(to_traditional("10.00 亿新台币"), "10.00 億新台幣")

    def test_one_to_many_chars_use_phrases(self) -> None:
        self.assertEqual(to_traditional("大盘复盘与恢复"), "大盤複盤與恢復")
        self.assertEqual(to_traditional("重复，回复，发布"), "重複，回覆，發布")

    def test_already_traditional_text_and_ascii_are_untouched(self) -> None:
        text = "### 台股短波段買入（60-69分，均線加權）：`action=buy` {market}"
        self.assertEqual(to_traditional(text), text)
        self.assertEqual(to_traditional(to_traditional("减仓")), "減碼")

    def test_localize_template_only_touches_zh_tw(self) -> None:
        self.assertEqual(localize_template("减仓", "zh-TW"), "減碼")
        for language in ("zh", "en", "ko", ""):
            self.assertEqual(localize_template("减仓", language), "减仓")
