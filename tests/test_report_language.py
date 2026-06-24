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
    localize_trend_prediction,
    localize_bias_status,
    normalize_report_language,
)


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

    def test_infer_decision_type_from_advice_matches_chinese_phrases(self) -> None:
        self.assertEqual(infer_decision_type_from_advice("建议买入"), "buy")
        self.assertEqual(infer_decision_type_from_advice("建议持有"), "hold")
        self.assertEqual(infer_decision_type_from_advice("建议减仓"), "sell")
        self.assertEqual(infer_decision_type_from_advice("继续持有"), "hold")
        self.assertEqual(infer_decision_type_from_advice("建议洗盘观察"), "hold")
        self.assertEqual(infer_decision_type_from_advice("洗盘观察", default=""), "hold")
        self.assertEqual(infer_decision_type_from_advice("观察", default=""), "hold")
        self.assertEqual(infer_decision_type_from_advice("不建议买入"), "hold")
        self.assertEqual(
            infer_decision_type_from_advice("当前不跌破支撑位继续持有"),
            "hold",
        )
        self.assertEqual(
            infer_decision_type_from_advice("不破支撑后仍可持有"),
            "hold",
        )


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


if __name__ == "__main__":
    unittest.main()
