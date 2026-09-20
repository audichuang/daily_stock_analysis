"""`stale_financial_quarters` 的守門測試(純函式,不連 DB)。

財報季更不在 `daily` 裡,所以漏一季是靜默的——這支函式是唯一會喊的地方。
"""

import datetime

from market_data.health import stale_financial_quarters

# 2019Q1 起的公告截止日(= 表上的 `date` 欄),與 `financial_statement.afterIFRS` 同源。
_ALL = [
    "2019-05-15", "2019-08-14", "2019-11-14", "2020-03-31",
    "2020-05-15", "2020-08-14", "2020-11-14", "2021-03-31",
    "2021-05-15", "2021-08-14", "2021-11-14", "2022-03-31",
    "2022-05-15",
]
_TODAY = datetime.date(2022, 6, 1)


def test_a_complete_table_reports_nothing():
    assert stale_financial_quarters(_ALL, _TODAY) == []


def test_an_interior_hole_is_reported_with_the_accounting_period_not_the_filing_year():
    """2020-03-31 是 **2019** 年的 Q4 年報——印錯年份會讓人跑錯一整季。"""
    stored = [d for d in _ALL if d != "2020-03-31"]

    assert stale_financial_quarters(stored, _TODAY) == [(2019, 4, "2020-03-31")]


def test_a_quarter_whose_deadline_has_not_passed_is_not_reported():
    """反向:2022Q1 的 5/15 還沒到,不能喊它停更(這一格擋的是「一律回報全部」)。"""
    stored = [d for d in _ALL if d != "2022-05-15"]

    assert stale_financial_quarters(stored, datetime.date(2022, 5, 14)) == []
    # 截止日當天仍算「已過」,隔天才報。
    assert stale_financial_quarters(stored, datetime.date(2022, 5, 16)) == [
        (2022, 1, "2022-05-15")]


def test_the_first_covered_quarter_is_the_lower_bound_not_an_exclusive_one():
    """邊界:庫內第一季本身要算在涵蓋範圍內,再早的才是「還沒回補」不報。"""
    assert stale_financial_quarters(_ALL[1:], _TODAY) == []

    stored = [d for d in _ALL if d != "2019-08-14"]
    assert stale_financial_quarters(stored, _TODAY) == [(2019, 2, "2019-08-14")]


def test_an_empty_table_is_not_reported_as_every_quarter_missing():
    assert stale_financial_quarters([], _TODAY) == []
