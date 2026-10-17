from datetime import date

import pytest

from market_data import adjust, crawl


class _Result:
    """同時應付 `execute(...).fetchall()`(找歷史交易日)與 `.scalar()`(稽核 max(date))。"""

    def fetchall(self): return []              # 空庫 bootstrap:查不到歷史交易日
    def scalar(self): return date(2024, 6, 4)


class _Conn:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, *a, **k): return _Result()


class _Eng:
    def begin(self): return _Conn()
    def connect(self): return _Conn()          # `_snapshot_latest` 走獨立連線


def test_daily_update_crawls_daily_sources_and_snapshots(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(crawl, "crawl_range",
                        lambda eng, src, dates, resume=True: calls.append(("range", src)))
    # `or 0`:真實 crawler 都回傳 upsert 列數,而 daily_update 會把它印出來
    # (`crawl_snapshots` 與月營收/除權息兩行),回 None 的 fake 會在格式化時炸掉
    monkeypatch.setattr(crawl, "crawl_valuation",
                        lambda conn: calls.append(("val",)) or 0)
    monkeypatch.setattr(crawl, "crawl_index",
                        lambda conn: calls.append(("idx",)) or 0)
    monkeypatch.setattr(crawl, "crawl_stock_info",
                        lambda conn: calls.append(("info",)) or 0)
    monkeypatch.setattr(crawl, "crawl_monthly_revenue",
                        lambda conn, month: calls.append(("rev", month)) or 0)
    monkeypatch.setattr(crawl, "crawl_ex_dividend",
                        lambda conn, start, end: calls.append(("exd", start, end)) or 0)
    monkeypatch.setattr(adjust, "refresh_recent",
                        lambda engine, start, end: calls.append(("adjust", start, end)))
    # 只記錄再委派給真品:不這樣做的話,`daily_update` 退回「直接呼叫那三個函式」
    # 也會通過所有斷言,共用入口就白抽了(而共用入口正是「印出」不會再被漏掉的保證)
    real_snapshots = crawl.crawl_snapshots
    monkeypatch.setattr(crawl, "crawl_snapshots",
                        lambda eng: calls.append(("snapshots",)) or real_snapshots(eng))

    monkeypatch.setattr(crawl, "refresh_range",
                        lambda eng, src, dates: calls.append(("refresh", src, tuple(dates))))

    crawl.daily_update(engine=_Eng(), asof=date(2024, 6, 5), days=3)

    assert [c[1] for c in calls if c[0] == "refresh"] == ["institutional"]

    ranged = {c[1] for c in calls if c[0] == "range"}
    assert ranged == {"price", "institutional", "margin"}
    assert calls.count(("snapshots",)) == 1        # 走共用入口,不是三個直接呼叫
    assert ("val",) in calls and ("idx",) in calls and ("info",) in calls
    # 上月營收(asof 6/5 -> 5 月)與除權息滾動窗(-30d ~ +90d)
    assert ("rev", date(2024, 5, 1)) in calls
    assert ("exd", date(2024, 5, 6), date(2024, 9, 3)) in calls
    # 復權事件刷新與除權息共用 ±ADJUSTMENT_WINDOW_DAYS,不再各寫一個 90
    assert ("adjust", date(2024, 3, 7), date(2024, 9, 3)) in calls

    # 每一段都要留下可觀測的行——`daily` 全靜默正是這次要修的病
    out = capsys.readouterr().out
    for expect in ("valuation 0 rows", "index 0 rows", "stock_info 0 rows",
                   "monthly_revenue 2024-05 0 rows", "ex_dividend 0 rows"):
        assert expect in out, f"{expect!r} 沒印出來：{out!r}"


class _RecentResult(_Result):
    def fetchall(self): return [(date(2024, 6, 4),), (date(2024, 6, 3),)]


class _RecentConn(_Conn):
    def execute(self, *a, **k): return _RecentResult()


class _RecentEng(_Eng):
    def begin(self): return _RecentConn()
    def connect(self): return _RecentConn()


def test_daily_update_refreshes_recent_stored_days_but_not_asof(monkeypatch):
    """T86 當晚先出初版、之後才修正:每輪 daily 要把近期的日子重抓成定版。asof 當天剛抓
    的就是初版,重抓它只是多打一次 TWSE;它留給隔天那一輪。"""
    refreshed = []
    monkeypatch.setattr(crawl, "crawl_range", lambda eng, src, dates, resume=True: None)
    monkeypatch.setattr(crawl, "refresh_range",
                        lambda eng, src, dates: refreshed.append((src, list(dates))))
    monkeypatch.setattr(crawl, "crawl_snapshots", lambda eng: {})
    monkeypatch.setattr(crawl, "crawl_monthly_revenue", lambda conn, month: 0)
    monkeypatch.setattr(crawl, "crawl_ex_dividend", lambda conn, start, end: 0)
    monkeypatch.setattr(adjust, "refresh_recent", lambda engine, start, end: None)

    crawl.daily_update(engine=_RecentEng(), asof=date(2024, 6, 5), days=3)

    assert refreshed == [("institutional", [date(2024, 6, 3), date(2024, 6, 4)])]


def test_recovery_dates_include_a_missing_weekday_between_stored_dates():
    dates = crawl.recovery_dates(
        date(2024, 6, 5),
        [date(2024, 6, 5), date(2024, 6, 3), date(2024, 5, 31)],
    )
    assert date(2024, 6, 4) in dates
    assert dates == [date(2024, 5, 31), date(2024, 6, 1), date(2024, 6, 2),
                     date(2024, 6, 3), date(2024, 6, 4), date(2024, 6, 5)]


def test_recovery_dates_reject_a_long_implicit_backfill():
    with pytest.raises(RuntimeError, match="backfill explicitly"):
        crawl.recovery_dates(
            date(2024, 6, 5), [date(2024, 1, 2)],
        )
