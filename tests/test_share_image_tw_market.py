# -*- coding: utf-8 -*-
"""台股大盤複盤要走得到大盤海報分支（zh-TW 用字 + tw 地區）。

上游的偵測 regex 只認簡體「大盘复盘」與 `cn|hk|us|jp|kr`，所以本 fork 的
zh-TW 台股複盤標題（`# 台股大盤複盤`，複 U+8907）兩關都不過，之前是零覆蓋。
"""

import unittest

from src.share_image import (
    _MARKET_RE,
    _MARKET_SCOPE_RE,
    _market_label_for_region,
    _market_region_hint,
    _plain,
)


def _is_review(title):
    return bool(_MARKET_RE.search(_plain(title)))


def _has_scope(title):
    return bool(_MARKET_SCOPE_RE.search(_plain(title)))


class TwMarketReviewTitleTestCase(unittest.TestCase):
    def test_traditional_chinese_review_titles_are_recognised(self):
        """實際輸出是「大盤複盤」——複 U+8907，不是復 U+5FA9。

        只補「復」修不到任何真實報告，所以這裡刻意用真實輸出的字。
        """
        self.assertEqual("複", "複")  # 釘住用字，避免下次有人補錯字
        for title in ("🎯 大盤複盤", "台股大盤複盤", "美股大盤複盤"):
            with self.subTest(title=title):
                self.assertTrue(_is_review(title))

    def test_simplified_titles_still_recognised(self):
        """反向守門：補繁體不能把上游的簡體判定弄壞。"""
        for title in ("🎯 大盘复盘", "A股大盘复盘", "市场复盘"):
            with self.subTest(title=title):
                self.assertTrue(_is_review(title))

    def test_english_and_korean_titles_still_recognised(self):
        self.assertTrue(_is_review("TW Market Recap"))
        self.assertTrue(_is_review("대만 시황 리뷰"))

    def test_taiwan_scope_is_recognised(self):
        for title in ("台股大盤複盤", "TW Market Recap", "대만 시황 리뷰"):
            with self.subTest(title=title):
                self.assertTrue(_has_scope(title))

    def test_stock_report_titles_are_not_market_reviews(self):
        """個股報告不能被判成大盤複盤。"""
        self.assertFalse(_is_review("台積電 2330.TW 分析報告"))
        self.assertFalse(_is_review("贵州茅台 600519 分析报告"))

    def test_tw_ticker_suffix_does_not_count_as_market_scope(self):
        """`\\btw\\b` 會命中 `2330.TW`；lookbehind 擋掉它。

        反向守門：拿掉 lookbehind，這條會紅——而它會改變 `_market_segments`
        對個股標題的分段行為。
        """
        self.assertFalse(_has_scope("台積電 2330.TW 分析報告"))
        self.assertFalse(_has_scope("環球晶 6488.TWO 分析報告"))

    def test_region_marker_maps_tw_to_a_label(self):
        """持久化 markdown 帶 `[dsa-market-region]: # (tw)`，標籤要解得出來。"""
        markdown = "[dsa-market-region]: # (tw)\n\n# 台股大盤複盤\n\n內容\n"
        self.assertEqual(_market_region_hint(markdown), "tw")
        self.assertEqual(_market_label_for_region("tw"), "台股")

    def test_upstream_region_labels_unchanged(self):
        for region, label in (("cn", "A股"), ("hk", "港股"), ("us", "美股"),
                              ("jp", "日股"), ("kr", "韩股")):
            with self.subTest(region=region):
                self.assertEqual(_market_label_for_region(region), label)


if __name__ == "__main__":
    unittest.main()
