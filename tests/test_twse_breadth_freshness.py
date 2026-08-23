# -*- coding: utf-8 -*-
"""台股涨跌家数的新鲜度守门。

`openapi.twse.com.tw/v1/opendata/twtazu_od` 会停止更新却照样回 HTTP 200 与结构
正确的 JSON：2026-08-23 实测 `出表日期` 仍是 `1150605`（2026-06-05，冻结 79 天），
而同一支 fetcher 的另外四个端点都是最新交易日。不比对日期的后果不是报错，是台股
大盘复盘连续 20 份印着同一组家数，LLM 再在上面叠出虚构叙事。

这些测试全部把 `_session` 换成假的，绝不连外。
"""

import datetime
import unittest

from data_provider import twse_fetcher
from data_provider.twse_fetcher import TwseFetcher, _roc_date


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeSession:
    """按 URL 派发；任何未登记的 URL 直接炸，避免测试悄悄连外。"""

    def __init__(self, by_url):
        self._by_url = by_url
        self.headers = {}

    def get(self, url, **_kwargs):
        for prefix, payload in self._by_url.items():
            if url.startswith(prefix):
                return _FakeResp(payload)
        raise AssertionError(f"test would have hit the network: {url}")


def _breadth_rows(roc_date):
    return [
        {"出表日期": roc_date, "類型": "整體市場", "上漲": "3144", "漲停": "43",
         "下跌": "9578", "跌停": "355", "持平": "459"},
        {"出表日期": roc_date, "類型": "股票", "上漲": "342", "漲停": "19",
         "下跌": "671", "跌停": "10", "持平": "59"},
    ]


def _fmtqik_rows(roc_date, trade_value="754905335886"):
    return [{"Date": roc_date, "TAIEX": "45224.29", "Change": "290.55",
             "TradeValue": trade_value}]


class RocDateTestCase(unittest.TestCase):
    def test_parses_seven_digit_roc_date(self):
        self.assertEqual(_roc_date("1150605"), datetime.date(2026, 6, 5))
        self.assertEqual(_roc_date("1150821"), datetime.date(2026, 8, 21))

    def test_rejects_garbage_instead_of_guessing(self):
        for bad in (None, "", "  ", "abc", "115", "115063x", "1151332"):
            with self.subTest(bad=bad):
                self.assertIsNone(_roc_date(bad))


class BreadthFreshnessTestCase(unittest.TestCase):
    def _fetcher(self, breadth_roc, fmtqik_roc="1150821"):
        f = TwseFetcher()
        f._session = _FakeSession({
            twse_fetcher._BREADTH_URL: _breadth_rows(breadth_roc),
            twse_fetcher._TRADE_VALUE_URL: _fmtqik_rows(fmtqik_roc),
        })
        return f

    def test_fresh_snapshot_is_accepted(self):
        f = self._fetcher("1150821")
        self.assertEqual(
            f._fetch_breadth(datetime.date(2026, 8, 21)),
            {"up_count": 3144, "down_count": 9578, "flat_count": 459,
             "limit_up_count": 43, "limit_down_count": 355},
        )

    def test_stale_snapshot_is_rejected(self):
        """2026-08-23 的真实情形：家数停在 2026-06-05，成交额是 2026-08-21。"""
        f = self._fetcher("1150605")
        self.assertIsNone(f._fetch_breadth(datetime.date(2026, 8, 21)))

    def test_one_day_stale_is_also_rejected(self):
        """报告会写「今日上漲 X 家」，差一天就是错的归属，不是可接受的近似。"""
        f = self._fetcher("1150820")
        self.assertIsNone(f._fetch_breadth(datetime.date(2026, 8, 21)))

    def test_unparseable_snapshot_date_is_rejected(self):
        f = self._fetcher("not-a-date")
        self.assertIsNone(f._fetch_breadth(datetime.date(2026, 8, 21)))

    def test_missing_reference_date_fails_closed(self):
        """成交额端点挂掉 ⇒ 无从证明家数新鲜 ⇒ 拒收，而不是照收。"""
        f = self._fetcher("1150821")
        self.assertIsNone(f._fetch_breadth(None))


class MarketStatsDegradationTestCase(unittest.TestCase):
    """守门触发时其余字段必须照常，家数保持 0（下游按 truthiness 判成缺资料）。"""

    def _fetcher(self, breadth_roc):
        f = TwseFetcher()
        f._session = _FakeSession({
            twse_fetcher._BREADTH_URL: _breadth_rows(breadth_roc),
            twse_fetcher._TRADE_VALUE_URL: _fmtqik_rows("1150821"),
            twse_fetcher._INSTITUTIONAL_URL: {
                "stat": "OK", "date": "20260821",
                # 单位名称必须用真实字面：BFI82U 的合计列是「合計」，
                # 外资主数字是「外資及陸資(不含外資自營商)」。
                "data": [["外資及陸資(不含外資自營商)", "1", "2", "27605193619"],
                         ["投信", "1", "2", "3428550227"],
                         ["自營商(自行買賣)", "1", "2", "1967215038"],
                         ["合計", "1", "2", "33000958884"]],
            },
            twse_fetcher._TPEX_TRADE_VALUE_URL: [],
            twse_fetcher._TPEX_INSTITUTIONAL_URL: [],
        })
        return f

    def test_stale_breadth_zeroes_counts_but_keeps_turnover(self):
        stats = self._fetcher("1150605").get_market_stats()
        self.assertEqual(stats["up_count"], 0)
        self.assertEqual(stats["down_count"], 0)
        self.assertEqual(stats["limit_down_count"], 0)
        # 成交额（元 -> 亿）与法人不受家数守门影响
        self.assertAlmostEqual(stats["total_amount"], 754905335886 / 1e8, places=4)
        self.assertGreater(stats["total_net"], 0)

    def test_fresh_breadth_still_flows_through(self):
        """反向守门：把守门写得过头（一律拒收）会让这个测试红。"""
        stats = self._fetcher("1150821").get_market_stats()
        self.assertEqual(stats["up_count"], 3144)
        self.assertEqual(stats["down_count"], 9578)
        self.assertEqual(stats["limit_down_count"], 355)


if __name__ == "__main__":
    unittest.main()
