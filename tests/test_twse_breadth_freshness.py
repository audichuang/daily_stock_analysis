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
from unittest import mock

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


# rwd 版 FMTQIK「当月尚无资料」的真实回应（月初收盘前）。既有测试登记它，
# 让参照日期只由 OpenAPI 那份决定，维持各测试原本的语意。
_RWD_NO_DATA = {"stat": "很抱歉，沒有符合條件的資料!"}


def _fmtqik_rwd_payload(*slash_dates, trade_value="824,692,107,481"):
    """rwd 版 FMTQIK 回应形状（实测 2026-09-29）：民国斜线日期、千分位逗号。"""
    return {"stat": "OK",
            "fields": ["日期", "成交股數", "成交金額", "成交筆數", "發行量加權股價指數", "漲跌點數"],
            "data": [[d, "9,651,142,036", trade_value, "4,112,337", "48,318.52", "293.92"]
                     for d in slash_dates]}


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
            twse_fetcher._TRADE_VALUE_RWD_URL: _RWD_NO_DATA,
            twse_fetcher._TRADE_VALUE_URL: _fmtqik_rows(fmtqik_roc),
        })
        return f

    def test_fresh_snapshot_uses_the_stock_row_not_the_whole_market(self):
        """「整體市場」含權證／ETN(分母約 13,181)，會主導寬度判讀。

        反向守門：改回取「整體市場」會讓這個測試紅在 3144 vs 342。
        """
        f = self._fetcher("1150821")
        self.assertEqual(
            f._fetch_breadth(datetime.date(2026, 8, 21)),
            {"up_count": 342, "down_count": 671, "flat_count": 59,
             "limit_up_count": 19, "limit_down_count": 10},
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
            twse_fetcher._TRADE_VALUE_RWD_URL: _RWD_NO_DATA,
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
            # 上櫃兩支必須是真的有資料：成交額與三大法人是「上市+上櫃合計」，
            # 少一邊就整格作廢（見 SummedFieldCoverageTestCase），那樣就測不到
            # 本類真正想測的事——**家數守門不影響其餘欄位組**。
            twse_fetcher._TPEX_TRADE_VALUE_URL: _tpex_trade_rows("1150821"),
            twse_fetcher._TPEX_INSTITUTIONAL_URL: _tpex_inst_rows("1150821"),
        })
        return f

    def test_stale_breadth_zeroes_counts_but_keeps_turnover(self):
        """本地 DB 也拿不到时：家数全 0（下游判成缺资料），其余字段照常。"""
        f = self._fetcher("1150605")
        with mock.patch("data_provider.tw_breadth.closing_breadth", return_value=None):
            stats = f.get_market_stats()
        self.assertEqual(stats["up_count"], 0)
        self.assertEqual(stats["down_count"], 0)
        self.assertEqual(stats["limit_down_count"], 0)
        # 成交额（元 -> 亿）与法人不受家数守门影响；两者都是上市+上柜之和
        self.assertAlmostEqual(
            stats["total_amount"], (754905335886 + 132226012483) / 1e8, places=4)
        self.assertAlmostEqual(stats["total_net"], 33000958884 / 1e8, places=4)
        self.assertAlmostEqual(
            stats["foreign_net"], (27605193619 - 700227366) / 1e8, places=4)

    def test_stale_breadth_falls_back_to_local_market_schema(self):
        """端点过期 ⇒ 改用本地前复权收盘自算；**漲跌停家数不得凭空生出来**。"""
        f = self._fetcher("1150605")
        with mock.patch(
            "data_provider.tw_breadth.closing_breadth",
            return_value={"up_count": 589, "down_count": 382, "flat_count": 104},
        ) as local:
            stats = f.get_market_stats()
        local.assert_called_once_with(datetime.date(2026, 8, 21))
        self.assertEqual(stats["up_count"], 589)
        self.assertEqual(stats["down_count"], 382)
        self.assertEqual(stats["flat_count"], 104)
        # 本地来源没有涨跌停口径，必须保持 0（= has_limit 判成缺资料）
        self.assertEqual(stats["limit_up_count"], 0)
        self.assertEqual(stats["limit_down_count"], 0)

    def test_local_fallback_is_not_used_when_the_endpoint_is_fresh(self):
        """反向守门：端点新鲜时不该退回本地，否则会丢掉涨跌停家数。"""
        f = self._fetcher("1150821")
        with mock.patch("data_provider.tw_breadth.closing_breadth") as local:
            stats = f.get_market_stats()
        local.assert_not_called()
        self.assertEqual(stats["limit_down_count"], 10)

    def test_fresh_breadth_still_flows_through(self):
        """反向守门：把守门写得过头（一律拒收）会让这个测试红。"""
        stats = self._fetcher("1150821").get_market_stats()
        self.assertEqual(stats["up_count"], 342)
        self.assertEqual(stats["down_count"], 671)
        self.assertEqual(stats["limit_down_count"], 10)


def _bfi82u_payload(west_date, *, foreign=2, trust=1, dealer=0, total=3):
    """BFI82U 回應形狀（實測 2026-08-21）：`date` 是西元 yyyymmdd，金額單位為元。"""
    return {"stat": "OK", "date": west_date, "fields": ["單位名稱", "買進金額",
            "賣出金額", "買賣差額"],
            "data": [["自營商(自行買賣)", "1", "1", str(dealer)],
                     ["投信", "2", "1", str(trust)],
                     ["外資及陸資(不含外資自營商)", "3", "1", str(foreign)],
                     ["合計", "6", "3", str(total)]]}


def _tpex_trade_rows(roc_date, amount="132226012483"):
    """tpex_daily_trading_index 每列帶民國 Date（1150821）。"""
    return [{"Date": roc_date, "TradeAmount": amount}]


def _tpex_inst_rows(roc_date, *, foreign=-700227366, trust=1327087116,
                    dealer=0, total=0):
    """tpex_3insti_summary：頂層彙總列（帶前導全角空格的細分子項不在這裡）。"""
    return [{"Date": roc_date, "Investor": "外資及陸資合計", "Net": str(foreign)},
            {"Date": roc_date, "Investor": "投信", "Net": str(trust)},
            {"Date": roc_date, "Investor": "自營商合計", "Net": str(dealer)},
            {"Date": roc_date, "Investor": "三大法人合計", "Net": str(total)}]


class EndpointFreshnessTestCase(unittest.TestCase):
    """BFI82U／TPEx 兩端點與 twtazu_od 同一形狀：停更仍回 200 ⇒ 一律比對日期。

    漲跌家數凍結 79 天的事故不能在其他四個欄位重演：法人買超差一天就是錯的
    歸屬，報告會寫「今日外資買超 X 億」。
    """

    EXPECTED = datetime.date(2026, 8, 21)

    def _fetcher(self, bfi="20260821", tpex_trade="1150821", tpex_inst="1150821"):
        f = TwseFetcher()
        f._session = _FakeSession({
            twse_fetcher._INSTITUTIONAL_URL: _bfi82u_payload(bfi),
            twse_fetcher._TPEX_TRADE_VALUE_URL: _tpex_trade_rows(tpex_trade),
            twse_fetcher._TPEX_INSTITUTIONAL_URL: _tpex_inst_rows(tpex_inst),
        })
        return f

    def test_fresh_institutional_passes_and_converts_units(self):
        stats = self._fetcher()._fetch_institutional(self.EXPECTED)
        self.assertEqual(stats["foreign_net"], 2 / 1e8)   # 差額 2 元 -> 亿
        self.assertEqual(stats["trust_net"], 1 / 1e8)

    def test_stale_institutional_is_rejected(self):
        self.assertIsNone(
            self._fetcher(bfi="20260605")._fetch_institutional(self.EXPECTED))

    def test_institutional_without_reference_date_fails_closed(self):
        self.assertIsNone(self._fetcher()._fetch_institutional(None))

    def test_institutional_with_unparseable_date_is_rejected(self):
        self.assertIsNone(
            self._fetcher(bfi="not-a-date")._fetch_institutional(self.EXPECTED))

    def test_fresh_tpex_amount_passes(self):
        amount = self._fetcher()._fetch_tpex_total_amount(self.EXPECTED)
        self.assertEqual(amount, 132226012483 / 1e8)

    def test_stale_tpex_amount_is_rejected(self):
        self.assertIsNone(
            self._fetcher(tpex_trade="1150605")._fetch_tpex_total_amount(self.EXPECTED))

    def test_mixed_day_tpex_institutional_is_rejected(self):
        rows = (_tpex_inst_rows("1150820") + _tpex_inst_rows("1150821"))
        f = self._fetcher()
        f._session = _FakeSession({twse_fetcher._TPEX_INSTITUTIONAL_URL: rows})
        self.assertIsNone(f._fetch_tpex_institutional(self.EXPECTED))

    def test_stale_tpex_institutional_is_rejected(self):
        self.assertIsNone(
            self._fetcher(tpex_inst="1150803")._fetch_tpex_institutional(self.EXPECTED))


class SummedFieldCoverageTestCase(unittest.TestCase):
    """成交額與三大法人是**上市 + 上櫃合計**，單邊和不得冒充合計。

    實測 2026-08-21：上市外資淨額 **+283.05 億**、上櫃 **-7.00 億**、合計 +276.05 億
    ——兩側**反向**。舊寫法是「把活著的那幾份相加」，所以 BFI82U 凍結時
    `foreign_net` 會變成 -7.00 億，報告照著寫「外資賣超 7 億」，而事實是買超 276 億。
    欄位名與報告標籤都宣稱「上市+上櫃合計」，於是這個數字**標籤說謊而且方向相反**。

    成交額同理：缺上櫃是 -21%、缺上市是 -79%，LLM 會讀成「量能急凍」。

    端點新鮮度檢查（`EndpointFreshnessTestCase`）讓這個舊契約從罕見變常態觸發
    ——FMTQIK 通常比 BFI82U 與 TPEx 兩支早發布。所以這一組釘住 all-or-nothing：
    任一邊缺，整格作廢，讓 `_breadth_availability` 判成沒有資料。
    """

    TWSE_AMOUNT = 754905335886      # 元，實測 2026-08-21
    TPEX_AMOUNT = 197673237762
    TWSE_FOREIGN = 28305420985      # 上市外資買超
    TPEX_FOREIGN = -700227366       # 上櫃外資賣超（與上市反向，這是本組的重點）
    TWSE_TOTAL = 33329451747
    TPEX_TOTAL = 1126859750

    def _fetcher(self, *, bfi="20260821", tpex_trade="1150821", tpex_inst="1150821"):
        f = TwseFetcher()
        f._session = _FakeSession({
            twse_fetcher._BREADTH_URL: _breadth_rows("1150821"),
            twse_fetcher._TRADE_VALUE_RWD_URL: _RWD_NO_DATA,
            twse_fetcher._TRADE_VALUE_URL: _fmtqik_rows(
                "1150821", trade_value=str(self.TWSE_AMOUNT)),
            twse_fetcher._INSTITUTIONAL_URL: _bfi82u_payload(
                bfi, foreign=self.TWSE_FOREIGN, total=self.TWSE_TOTAL),
            twse_fetcher._TPEX_TRADE_VALUE_URL: _tpex_trade_rows(
                tpex_trade, amount=str(self.TPEX_AMOUNT)),
            twse_fetcher._TPEX_INSTITUTIONAL_URL: _tpex_inst_rows(
                tpex_inst, foreign=self.TPEX_FOREIGN, total=self.TPEX_TOTAL),
        })
        return f

    def test_both_sides_fresh_are_summed(self):
        """正向守門：雙邊齊全時必須是**和**，寫成任一單邊都會紅。"""
        stats = self._fetcher().get_market_stats()

        self.assertAlmostEqual(
            stats["total_amount"], (self.TWSE_AMOUNT + self.TPEX_AMOUNT) / 1e8, places=4)
        self.assertAlmostEqual(
            stats["foreign_net"], (self.TWSE_FOREIGN + self.TPEX_FOREIGN) / 1e8, places=4)
        self.assertAlmostEqual(
            stats["total_net"], (self.TWSE_TOTAL + self.TPEX_TOTAL) / 1e8, places=4)

    def test_stale_twse_institutional_drops_the_whole_group(self):
        """上市法人凍結 ⇒ 整組缺席，**不得**退化成上櫃單邊（那會讓方向反轉）。"""
        stats = self._fetcher(bfi="20260605").get_market_stats()

        for key in ("foreign_net", "trust_net", "dealer_net", "total_net"):
            self.assertNotIn(key, stats, f"{key} 不該以單邊值出現")
        # 釘住這次事故的具體形狀：買超 276 億絕不能被寫成賣超 7 億
        self.assertNotAlmostEqual(
            stats.get("foreign_net", 0.0), self.TPEX_FOREIGN / 1e8, places=4)

    def test_stale_tpex_institutional_drops_the_whole_group(self):
        """反向：換成上櫃過期也一樣作廢，不能只擋一個方向。"""
        stats = self._fetcher(tpex_inst="1150605").get_market_stats()

        for key in ("foreign_net", "trust_net", "dealer_net", "total_net"):
            self.assertNotIn(key, stats, f"{key} 不該以單邊值出現")

    def test_stale_tpex_amount_drops_turnover_instead_of_reporting_one_side(self):
        """缺上櫃成交額 ⇒ `total_amount` 保持 0（下游按 truthiness 判成缺資料），
        而不是送一個少了 21% 的「兩市成交額」。"""
        stats = self._fetcher(tpex_trade="1150605").get_market_stats()

        self.assertEqual(stats["total_amount"], 0.0)
        self.assertNotAlmostEqual(
            stats["total_amount"], self.TWSE_AMOUNT / 1e8, places=4)

    def test_field_groups_still_degrade_independently(self):
        """分組降級沒被改壞：法人整組作廢時，家數與成交額照常。"""
        stats = self._fetcher(bfi="20260605").get_market_stats()

        self.assertEqual(stats["up_count"], 342)
        self.assertEqual(stats["limit_down_count"], 10)
        self.assertAlmostEqual(
            stats["total_amount"], (self.TWSE_AMOUNT + self.TPEX_AMOUNT) / 1e8, places=4)


if __name__ == "__main__":
    unittest.main()


class TradingDayReferenceTestCase(unittest.TestCase):
    """新鲜度参照取 OpenAPI／rwd 两版 FMTQIK 中日期较新的一份。

    实测 2026-09-29 17:05：OpenAPI 版最后一列仍是 09-24，rwd 版已有 09-29。旧写法只看
    OpenAPI，于是当日新鲜的 BFI82U（date=20260929）被判「相差 -5 天」拒收，上柜两支同样被拒，
    成交金额印成 09-24 的——一份写着今天日期的复盘，法人栏全空、量能是上一个交易日的。
    """

    def setUp(self):
        # 家数端点是冻结的那份，会触发本地宽度 fallback；这里不测它，也不让它连 DB。
        patcher = mock.patch("data_provider.tw_breadth.closing_breadth", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _fetcher(self, *, openapi_roc="1150924", rwd=None, bfi="20260929"):
        f = TwseFetcher()
        f._session = _FakeSession({
            twse_fetcher._BREADTH_URL: _breadth_rows("1150605"),
            twse_fetcher._TRADE_VALUE_RWD_URL: rwd if rwd is not None else _RWD_NO_DATA,
            twse_fetcher._TRADE_VALUE_URL: _fmtqik_rows(openapi_roc),
            twse_fetcher._INSTITUTIONAL_URL: _bfi82u_payload(bfi),
            twse_fetcher._TPEX_TRADE_VALUE_URL: _tpex_trade_rows("1150929"),
            twse_fetcher._TPEX_INSTITUTIONAL_URL: _tpex_inst_rows("1150929"),
        })
        return f

    def test_lagging_openapi_does_not_reject_todays_data(self):
        """回归守门：退回「只看 OpenAPI」会让这个测试红。"""
        f = self._fetcher(rwd=_fmtqik_rwd_payload("115/09/24", "115/09/29"))
        day, amount = f._fetch_total_amount()
        self.assertEqual(day, datetime.date(2026, 9, 29))
        self.assertAlmostEqual(amount, 8246.92107481)
        stats = f.get_market_stats()
        self.assertIsNotNone(stats.get("foreign_net"), "当日 BFI82U 被落后的参照误判过期")

    def test_newer_openapi_wins_over_older_rwd(self):
        """反向守门：写成「一律用 rwd」会让这个测试红。"""
        f = self._fetcher(openapi_roc="1150929", rwd=_fmtqik_rwd_payload("115/09/24"))
        self.assertEqual(f._fetch_total_amount()[0], datetime.date(2026, 9, 29))

    def test_rwd_without_current_month_falls_back_to_openapi(self):
        f = self._fetcher(openapi_roc="1150930")
        self.assertEqual(f._fetch_total_amount()[0], datetime.date(2026, 9, 30))

    def test_unexpected_rwd_fields_fall_back_instead_of_raising(self):
        f = self._fetcher(rwd={"stat": "OK", "fields": ["日期"], "data": [["115/09/29"]]})
        self.assertEqual(f._fetch_total_amount()[0], datetime.date(2026, 9, 24))

    def test_rwd_network_error_falls_back_to_openapi(self):
        f = self._fetcher()
        real_get = f._session.get

        def get(url, **kwargs):
            if url.startswith(twse_fetcher._TRADE_VALUE_RWD_URL):
                raise twse_fetcher.requests.ConnectionError("boom")
            return real_get(url, **kwargs)

        f._session.get = get
        self.assertEqual(f._fetch_total_amount()[0], datetime.date(2026, 9, 24))

    def test_stale_both_sides_still_rejects_institutional(self):
        """两份参照都落后时守门照旧：不是把守门拆掉。"""
        f = self._fetcher(bfi="20260929", rwd=_fmtqik_rwd_payload("115/09/24"))
        self.assertIsNone(f.get_market_stats().get("foreign_net"))
