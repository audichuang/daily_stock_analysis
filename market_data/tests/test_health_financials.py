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


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _RecordingConn:
    """同 `test_hardening.py` 的形狀:`report()` 自己被執行,所以接線本身也守得到。"""

    def __init__(self, plan, calls):
        self.plan, self.calls = plan, calls

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.calls.append((sql, params))
        for needle, rows in self.plan:
            if needle in sql:
                return _FakeResult(rows)
        return _FakeResult([])


def test_report_wires_the_financial_audit_into_integrity():
    """純函式綠、但 `report()` 忘了接它,整份稽核還是不會喊。

    這一格擋的是接線:把 `report()` 裡那個 key 刪掉（或漏掉 SELECT）時必須紅。
    """
    calls = []
    plan = [
        ("count(*), min(", [(1, datetime.date(2019, 5, 15), datetime.date(2019, 8, 14))]),
        ("SELECT DISTINCT date FROM market.financial_statement",
         [(datetime.date(2019, 5, 15),), (datetime.date(2019, 8, 14),),
          (datetime.date(2020, 3, 31),)]),
    ]

    class _Engine:
        def connect(self):
            return _RecordingConn(plan, calls)

    from market_data import health

    result = health.report(engine=_Engine())

    assert any("FROM market.financial_statement" in sql for sql, _ in calls)
    stale = result["integrity"]["stale_financial_quarters"]
    # 2019-11-14（2019Q3）在涵蓋範圍內卻沒有列 → 必須被點名。
    assert (2019, 3, "2019-11-14") in stale
    # 範圍兩端不能誤報:2019Q1／Q2／Q4 都在庫裡。
    assert not [q for q in stale if q[2] in ("2019-05-15", "2019-08-14", "2020-03-31")]
