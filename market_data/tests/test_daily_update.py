from datetime import date

import pytest

from market_data import adjust, crawl, funds


@pytest.fixture(autouse=True)
def _no_fund_network(monkeypatch):
    """daily 的基金段會連公會與鉅亨；本檔只驗股票段，一律換成不連外的假函式。"""
    calls = []
    monkeypatch.setattr(funds, "daily_update", lambda eng, asof=None: calls.append(asof))
    return calls


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
                        lambda conn, dates=None: calls.append(("idx", dates)) or 0)
    monkeypatch.setattr(crawl, "crawl_stock_info",
                        lambda conn: calls.append(("info",)) or 0)
    monkeypatch.setattr(crawl, "crawl_monthly_revenue",
                        lambda conn, month: calls.append(("rev", month)) or 0)
    monkeypatch.setattr(crawl, "crawl_ex_dividend",
                        lambda conn, start, end, require=False: calls.append(("exd", start, end, require)) or 0)
    monkeypatch.setattr(adjust, "refresh_recent",
                        lambda engine, start, end: calls.append(("adjust", start, end)))
    # 只記錄再委派給真品:不這樣做的話,`daily_update` 退回「直接呼叫那三個函式」
    # 也會通過所有斷言,共用入口就白抽了(而共用入口正是「印出」不會再被漏掉的保證)
    real_snapshots = crawl.crawl_snapshots
    monkeypatch.setattr(crawl, "crawl_snapshots",
                        lambda eng, dates=None: calls.append(("snapshots", dates))
                        or real_snapshots(eng, dates))

    monkeypatch.setattr(crawl, "refresh_range",
                        lambda eng, src, dates: calls.append(("refresh", src, tuple(dates))))

    crawl.daily_update(engine=_Eng(), asof=date(2024, 6, 5), days=3)

    assert [c[1] for c in calls if c[0] == "refresh"] == ["institutional"]

    ranged = {c[1] for c in calls if c[0] == "range"}
    # valuation 也走 crawl_range（BWIBBU_d 補窗口內缺日）；但不進 REVISED_SOURCES
    assert ranged == {"price", "institutional", "margin", "valuation"}
    snaps = [c for c in calls if c[0] == "snapshots"]
    assert len(snaps) == 1                          # 走共用入口,不是三個直接呼叫
    # daily 把回補窗口交給快照段,index 才能依窗口逐月抓(月底漏跑補得回上月)
    window = snaps[0][1]
    assert window and date(2024, 6, 5) in window
    assert ("idx", window) in calls                 # crawl_snapshots 把同一份 dates 轉給 crawl_index
    assert ("val",) in calls and ("info",) in calls
    # 上月營收(asof 6/5 -> 5 月)與除權息滾動窗(-30d ~ +90d)
    assert ("rev", date(2024, 5, 1)) in calls
    assert ("exd", date(2024, 5, 6), date(2024, 9, 3), True) in calls   # daily 以 require=True 呼叫
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
    monkeypatch.setattr(crawl, "crawl_snapshots", lambda eng, dates=None: {})
    monkeypatch.setattr(crawl, "crawl_monthly_revenue", lambda conn, month: 0)
    monkeypatch.setattr(crawl, "crawl_ex_dividend",
                        lambda conn, start, end, require=False: 0)
    monkeypatch.setattr(adjust, "refresh_recent", lambda engine, start, end: None)

    crawl.daily_update(engine=_RecentEng(), asof=date(2024, 6, 5), days=3)

    assert refreshed == [("institutional", [date(2024, 6, 3), date(2024, 6, 4)])]


def _wire_ex_dividend(monkeypatch, returns, events):
    """daily_update 的其他段全換成空操作,只留 月營收 → 除權息 → refresh_recent 的順序記錄。
    ``returns`` 依序是 sources.crawl_ex_dividend 每次呼叫的回傳值。"""
    import pandas as pd

    seq = iter(returns)
    monkeypatch.setattr(crawl, "_EX_DIVIDEND_RETRY_SECONDS", 0)
    monkeypatch.setattr(crawl, "crawl_range", lambda eng, src, dates, resume=True: None)
    monkeypatch.setattr(crawl, "refresh_range", lambda eng, src, dates: None)
    monkeypatch.setattr(crawl, "crawl_snapshots", lambda eng, dates=None: {})
    monkeypatch.setattr(crawl, "crawl_monthly_revenue",
                        lambda conn, month: events.append("rev") or 0)

    def fake_source(start, end):
        events.append("fetch")
        return next(seq)

    monkeypatch.setattr(crawl.sources, "crawl_ex_dividend", fake_source)
    monkeypatch.setattr(crawl, "_store", lambda *a, **k: 0)   # 只驗失敗判定,不碰 DB
    monkeypatch.setattr(adjust, "refresh_recent",
                        lambda engine, start, end: events.append("adjust"))
    return pd


class _TrackedEng(_Eng):
    """記錄每個交易的 commit(離開 `begin()` 且沒有例外),驗月營收先於除權息提交。"""

    def __init__(self, events):
        self.events = events

    def begin(self):
        events = self.events

        class _Tx(_Conn):
            def __exit__(self, exc_type, *a):
                if exc_type is None:
                    events.append("commit")
                return False
        return _Tx()


def test_daily_update_raises_when_twt49u_fails_twice_and_skips_adjustment(monkeypatch, capsys):
    """TWT49U 連兩次 None:daily 要報錯(不能 0 列繼續),refresh_recent 不得被呼叫,
    而月營收已在自己的交易 commit 並印出,不被除權息的失敗連帶回滾。"""
    events = []
    _wire_ex_dividend(monkeypatch, [None, None], events)

    with pytest.raises(RuntimeError, match="TWT49U"):
        crawl.daily_update(engine=_TrackedEng(events), asof=date(2024, 6, 5), days=3)

    assert "adjust" not in events
    assert events.count("fetch") == 2                       # 重試恰好一次
    # 月營收那個交易先 commit(rev 之後緊接 commit),然後才抓除權息
    assert events[events.index("rev") + 1] == "commit"
    assert events.index("rev") + 1 < events.index("fetch")
    assert "monthly_revenue 2024-05 0 rows" in capsys.readouterr().out


def test_daily_update_retries_twt49u_once_then_completes(monkeypatch, capsys):
    import pandas as pd

    events = []
    _wire_ex_dividend(monkeypatch, [None, pd.DataFrame()], events)

    crawl.daily_update(engine=_TrackedEng(events), asof=date(2024, 6, 5), days=3)

    assert events.count("fetch") == 2
    assert events[-1] == "adjust"
    assert "ex_dividend 0 rows" in capsys.readouterr().out


def test_daily_update_empty_ex_dividend_window_is_not_a_failure(monkeypatch):
    """窗口內真的 0 事件(空 DataFrame)與抓取失敗(None)不同:不 raise、不重試。"""
    import pandas as pd

    events = []
    _wire_ex_dividend(monkeypatch, [pd.DataFrame()], events)

    crawl.daily_update(engine=_TrackedEng(events), asof=date(2024, 6, 5), days=3)

    assert events.count("fetch") == 1
    assert "adjust" in events


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


def test_daily_update_runs_fund_step_with_same_asof(monkeypatch, _no_fund_network):
    _stub_stock_steps(monkeypatch)
    crawl.daily_update(engine=_Eng(), asof=date(2024, 6, 5), days=3)
    assert _no_fund_network == [date(2024, 6, 5)]


def test_fund_source_failure_does_not_fail_stock_daily(monkeypatch, capsys):
    adjusted = []
    _stub_stock_steps(monkeypatch, adjusted)

    def boom(eng, asof=None):
        raise funds.FundSourceError("SITCA nav.csv: HTTP 503")

    monkeypatch.setattr(funds, "daily_update", boom)
    crawl.daily_update(engine=_Eng(), asof=date(2024, 6, 5), days=3)
    assert adjusted, "基金失敗不該擋掉之後的復權刷新"
    assert "**WARN fund_nav: SITCA nav.csv: HTTP 503" in capsys.readouterr().out


def _stub_stock_steps(monkeypatch, adjusted=None):
    monkeypatch.setattr(crawl, "crawl_range", lambda eng, src, dates, resume=True: None)
    monkeypatch.setattr(crawl, "refresh_range", lambda eng, src, dates: None)
    monkeypatch.setattr(crawl, "crawl_snapshots", lambda eng, dates=None: {})
    monkeypatch.setattr(crawl, "crawl_monthly_revenue", lambda conn, month: 0)
    monkeypatch.setattr(crawl, "crawl_ex_dividend", lambda conn, s, e, require=False: 0)
    monkeypatch.setattr(adjust, "refresh_recent",
                        lambda engine, start, end: (adjusted if adjusted is not None else []).append(1))
