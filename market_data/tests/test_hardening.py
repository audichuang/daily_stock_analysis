"""Regressions for the audit hardening: partial-day repair, financials
fail-fast, duplicate-key dedupe, CLI validation, local-median thin days."""

import contextlib
from datetime import date, timedelta

import pandas as pd
import pytest
from sqlalchemy import text

from market_data import cli, crawl, health, sources


def _price_frame(stocks, d):
    return pd.DataFrame({
        "stock_id": stocks,
        "date": pd.to_datetime(d),
        "收盤價": [100.0] * len(stocks),
    }).set_index(["stock_id", "date"])


def test_crawl_day_replace_repairs_partial_day(pg_conn, monkeypatch):
    d = date(1900, 3, 1)  # 遠古日期,与真實資料隔離
    pg_conn.execute(text(
        "INSERT INTO market.price (stock_id, date, close) VALUES ('JUNK', :d, 227)"),
        {"d": d})
    monkeypatch.setattr(crawl, "_price_all",
                        lambda day, expected=None, conn=None: _price_frame(["2330", "2317"], day))
    n = crawl.crawl_day(pg_conn, "price", d, replace=True)
    assert n == 2
    rows = pg_conn.execute(text(
        "SELECT stock_id FROM market.price WHERE date = :d ORDER BY stock_id"),
        {"d": d}).fetchall()
    # 舊的錯位殘留列必須被換血清掉,upsert 蓋不掉鍵不同的髒列
    assert [r[0] for r in rows] == ["2317", "2330"]


def test_crawl_day_replace_keeps_data_when_fetch_fails(pg_conn, monkeypatch):
    d = date(1900, 3, 2)
    pg_conn.execute(text(
        "INSERT INTO market.price (stock_id, date, close) VALUES ('KEEP', :d, 1)"),
        {"d": d})
    monkeypatch.setattr(crawl, "_price_all",
                        lambda day, expected=None, conn=None: None)
    assert crawl.crawl_day(pg_conn, "price", d, replace=True) == 0
    kept = pg_conn.execute(text(
        "SELECT COUNT(*) FROM market.price WHERE date = :d"), {"d": d}).scalar()
    assert kept == 1  # 來源掛掉不得清掉既有資料


def test_crawl_day_replace_refuses_garbage_payload(pg_conn, monkeypatch):
    # 來源回非空但全是壞 stock_id -> 有效列為 0,不得先刪好資料
    d = date(1900, 3, 4)
    pg_conn.execute(text(
        "INSERT INTO market.price (stock_id, date, close) VALUES ('GOOD', :d, 1)"),
        {"d": d})
    monkeypatch.setattr(crawl, "_price_all",
                        lambda day, expected=None, conn=None: _price_frame(["電子工業合計指數彙總"], day))
    assert crawl.crawl_day(pg_conn, "price", d, replace=True) == 0
    assert pg_conn.execute(text(
        "SELECT COUNT(*) FROM market.price WHERE date=:d"), {"d": d}).scalar() == 1


def test_crawl_day_replace_refuses_massive_shrink(pg_conn, monkeypatch):
    d = date(1900, 3, 5)
    for s in ("A100", "A200", "A300", "A400"):
        pg_conn.execute(text(
            "INSERT INTO market.price (stock_id, date, close) VALUES (:s, :d, 1)"),
            {"s": s, "d": d})
    monkeypatch.setattr(crawl, "_price_all",
                        lambda day, expected=None, conn=None: _price_frame(["2330"], day))
    assert crawl.crawl_day(pg_conn, "price", d, replace=True) == 0  # 1 < 4*0.5
    assert pg_conn.execute(text(
        "SELECT COUNT(*) FROM market.price WHERE date=:d"), {"d": d}).scalar() == 4


def test_upsert_dedupes_at_writer_level(pg_conn):
    # 去重在 upsert 本體:valuation/index 等直呼路徑同樣受保護
    from market_data import models
    from market_data.writer import upsert

    n = upsert(pg_conn, models.Price.__table__,
               [{"stock_id": "T901", "date": "1900-03-06", "close": 1},
                {"stock_id": "T901", "date": "1900-03-06", "close": 2}],
               ["stock_id", "date"])
    assert n == 1
    val = pg_conn.execute(text(
        "SELECT close FROM market.price WHERE stock_id='T901'")).scalar()
    assert float(val) == 2.0  # keep last


def _fake_frames(stocks, d):
    df = pd.DataFrame({"stock_id": stocks, "date": pd.to_datetime(d),
                       "營業收入合計": 1.0}).set_index(["stock_id", "date"])
    cum = df.copy()
    cum.columns = ["累計營業收入合計"]
    return {"balance_sheet": df, "income_sheet": df.iloc[0:0],
            "income_sheet_cumulate": cum, "cash_flows": df}


def test_crawl_financials_q4_fails_without_q3_and_writes_nothing(
        engine, monkeypatch):
    frames = _fake_frames(["2330", "2317"], "1900-03-31")
    monkeypatch.setattr(crawl.os.path, "isdir", lambda p: True)
    monkeypatch.setattr(crawl.financial_statement, "pack_htmls",
                        lambda y, s, directory: frames)
    rmtree_calls = []
    monkeypatch.setattr(crawl.shutil, "rmtree",
                        lambda *a, **k: rmtree_calls.append(a))
    with pytest.raises(RuntimeError, match="Q3"):
        crawl.crawl_financials(engine, 1899, 4, min_stocks=0)
    assert not rmtree_calls  # 失敗必須保留下載檔
    with engine.connect() as c:
        n = c.execute(text(
            "SELECT COUNT(*) FROM market.financial_statement "
            "WHERE date = '1900-03-31'")).scalar()
    assert n == 0  # 整季回滾,不留半套資料


def test_crawl_financials_partial_quarter_fails(engine, monkeypatch):
    monkeypatch.setattr(crawl.os.path, "isdir", lambda p: True)
    monkeypatch.setattr(crawl.financial_statement, "pack_htmls",
                        lambda y, s, directory: _fake_frames(["2330"], "1900-05-15"))
    with pytest.raises(RuntimeError, match="partial"):
        crawl.crawl_financials(engine, 1900, 1)  # 預設 min_stocks=1000


def test_store_dedupes_duplicate_keys(pg_conn, monkeypatch):
    d = date(1900, 3, 3)

    def dup_fetch(day):
        return pd.DataFrame({
            "stock_id": ["2330", "2330"], "date": pd.to_datetime(d),
            "外資買賣超股數": [111, 222], "投信買賣超股數": [1, 2],
            "自營商買賣超股數": [0, 0], "三大法人買賣超股數": [112, 224],
        }).set_index(["stock_id", "date"])

    monkeypatch.setattr(crawl.sources, "crawl_institutional", dup_fetch)
    assert crawl.crawl_day(pg_conn, "institutional", d) == 1  # 去重,不炸 ON CONFLICT
    val = pg_conn.execute(text(
        "SELECT foreign_net FROM market.institutional "
        "WHERE stock_id='2330' AND date=:d"), {"d": d}).scalar()
    assert val == 222  # keep="last"


def test_cli_rejects_malformed_month():
    for bad in ("2026/06", "2026-6-1x", "junk"):
        with pytest.raises(SystemExit):  # argparse 層擋下,連 DB 都不碰
            cli.main(["revenue", "--month", bad])


def test_thin_days_uses_local_median():
    days = [(date(2026, 1, i + 1), 2000) for i in range(20)]
    days[10] = (date(2026, 1, 11), 1160)  # TPEx 整邊缺:剩 58%,舊版 0.5 門檻抓不到
    flagged = health.thin_days(days)
    assert flagged == [("2026-01-11", 1160)]


def test_missing_dates_finds_a_price_gap_in_the_recent_trading_calendar():
    reference = [date(2026, 7, 24), date(2026, 7, 27), date(2026, 7, 28)]
    observed = [date(2026, 7, 24), date(2026, 7, 28)]

    assert health.missing_dates(reference, observed) == ["2026-07-27"]


def test_fetch_index_prefers_current_rwd_report(monkeypatch):
    payload = {
        "stat": "OK",
        "fields": ["日期", "成交股數", "成交金額", "成交筆數",
                   "發行量加權股價指數", "漲跌點數"],
        "data": [["115/07/28", "1", "872,574,999,972", "2",
                  "41,603.36", "-2,030.83"]],
    }

    class _Response:
        def json(self):
            return payload

    monkeypatch.setattr(sources, "requests_get", lambda *args, **kwargs: _Response())
    monkeypatch.setattr(
        sources, "_openapi_json", lambda url: pytest.fail("stale fallback used"))
    rows = sources.fetch_index(date(2026, 7, 28))

    assert rows == [{
        "Date": "1150728",
        "TradeValue": "872,574,999,972",
        "TAIEX": "41,603.36",
        "Change": "-2,030.83",
    }]


def test_fetch_index_without_fallback_never_touches_openapi(monkeypatch, capsys):
    """過去月份 rwd 失敗時不得退到 openapi（它只給當月）:回 None 並印 WARN。"""
    monkeypatch.setattr(sources, "requests_get", lambda *a, **k: None)
    monkeypatch.setattr(
        sources, "_openapi_json", lambda url: pytest.fail("openapi fallback used"))
    assert sources.fetch_index(date(2026, 9, 30), fallback=False) is None
    assert "2026-09" in capsys.readouterr().out


def test_fetch_index_with_fallback_still_uses_openapi(monkeypatch):
    """當月仍保留 openapi 後備（預設行為不變）。"""
    monkeypatch.setattr(sources, "requests_get", lambda *a, **k: None)
    openapi = [{"Date": "1151005", "TAIEX": "1", "Change": "1", "TradeValue": "1"}]
    monkeypatch.setattr(sources, "_openapi_json", lambda url: openapi)
    assert sources.fetch_index(date(2026, 10, 5)) == openapi


def test_missing_adjustments_finds_valid_ex_dividend_without_event_factor():
    expected = [("2330", date(2026, 7, 24)), ("2317", date(2026, 7, 28))]
    stored = [("2317", date(2026, 7, 28))]

    assert health.missing_adjustments(expected, stored) == [("2330", "2026-07-24")]


def test_strict_health_returns_nonzero_for_integrity_gaps(monkeypatch):
    monkeypatch.setattr(health, "report", lambda engine, **_: {
        "tables": {},
        "thin_days": {},
        "integrity": {
            "missing_price_dates": ["2026-07-27"],
            "missing_price_adjustments": [],
        },
    })

    assert health.run(engine=object(), strict=True) == 1


def _tables():
    return {table: {"rows": 1, "start": "2026-07-27", "end": "2026-07-27"}
            for table in health._REQUIRED_TABLES}


def test_strict_health_rejects_a_thin_day_inside_the_daily_window(monkeypatch):
    monkeypatch.setattr(health, "report", lambda engine, **_: {
        "tables": _tables(),
        "thin_days": {"price": [("2026-07-27", 100)]},
        "integrity": {"thin_recent_days": [("price", "2026-07-27", 100)]},
    })

    assert health.run(engine=object(), strict=True) == 1


def test_strict_health_does_not_block_on_a_thin_day_daily_cannot_repair(monkeypatch):
    """全歷史 thin day 只報不擋——否則 2014 年的半日交易會讓 make morning 天天死在門口，
    而錯誤訊息叫你重跑的 daily 只補最近幾個交易日，永遠修不掉它。"""
    monkeypatch.setattr(health, "report", lambda engine, **_: {
        "tables": _tables(),
        "thin_days": {"price": [("2014-05-21", 100)]},
        "integrity": {"thin_recent_days": []},
    })

    assert health.run(engine=object(), strict=True) == 0


def test_recent_thin_days_keeps_only_the_repairable_window():
    thin = {"price": [("2014-05-21", 100), ("2026-07-27", 100)],
            "margin": [("2026-07-28", 90)]}

    assert health.recent_thin_days(thin, date(2026, 7, 27)) == [
        ("margin", "2026-07-28", 90), ("price", "2026-07-27", 100)]
    assert health.recent_thin_days(thin, None) == []


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _RecordingConn:
    """記錄 (壓平的 SQL, 參數) 並按 substring 回傳罐頭列。

    比 monkeypatch `report()` 更進一步：`report()` 自己會被執行，所以「查詢用錯視窗」或
    「算出來的 thin day 沒接到 integrity 欄位」這兩種 mutation 都逃不掉（獨立審查指出，
    只 patch `report()` 的版本兩者都會綠）。
    """

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


def test_report_uses_the_shared_window_and_wires_recent_thin_days_to_the_gate():
    """`report()` 必須(1)用 `RECENT_SESSIONS` 查、(2)把近期 thin day 接到 integrity。"""
    sessions = [date(2026, 7, 21 + i) for i in range(6)]        # 最後一天列數偏低
    counts = [(d, 100) for d in sessions[:-1]] + [(sessions[-1], 50)]
    old_thin = [(date(2014, 5, 21), 50)] + [(date(2014, 5, 22 + i), 100) for i in range(5)]
    calls = []
    plan = [
        ("count(*), min(", [(1, sessions[0], sessions[-1])]),
        ("FROM market.price WHERE true GROUP BY", counts),
        ("FROM market.institutional WHERE true AND market IS NULL GROUP BY", old_thin),
        ("FROM market.margin WHERE true AND market IS NULL GROUP BY", []),
        ("FROM market.price ORDER BY date DESC", [(d,) for d in reversed(sessions)]),
    ]

    class _Engine:
        def connect(self):
            return _RecordingConn(plan, calls)

    result = health.report(engine=_Engine())

    limit_params = [p for sql, p in calls if "ORDER BY date DESC LIMIT :n" in sql]
    assert limit_params == [{"n": crawl.RECENT_SESSIONS}], (
        "health 的近期視窗必須就是 daily 的修復視窗，否則 gate 會擋在 daily 補不到的缺口上")

    recent = result["integrity"]["thin_recent_days"]
    assert ("price", "2026-07-26", 50) in recent          # 視窗內 → 進 gate
    assert all(day >= str(sessions[0]) for _, day, _ in recent)
    assert ("institutional", "2014-05-21", 50) not in recent   # daily 修不到 → 只報不擋
    assert ("2014-05-21", 50) in result["thin_days"]["institutional"]  # 但仍列在稽核清單


def test_report_tolerates_latest_day_missing_valuation_but_not_older_days():
    """估值（BWIBBU_d）18:00 當天多半未發布：最新一日缺不報，次新日缺要報。"""
    sessions = [date(2026, 10, 12 + i) for i in range(5)]       # 10/12 ~ 10/16
    newest_first = [(d,) for d in reversed(sessions)]

    def run(valuation_days):
        plan = [
            ("count(*), min(", [(1, sessions[0], sessions[-1])]),
            ("AND market IS NULL GROUP BY", []),
            ("AND market = :market GROUP BY", []),
            ("FROM market.price ORDER BY date DESC", newest_first),
            ("FROM market.institutional WHERE", [(d,) for d in sessions]),
            ("FROM market.margin WHERE", [(d,) for d in sessions]),
            ("FROM market.valuation WHERE", [(d,) for d in valuation_days]),
        ]

        class _Engine:
            def connect(self):
                return _RecordingConn(plan, [])

        return health.report(engine=_Engine())["integrity"]["missing_valuation_dates"]

    assert run(sessions[:-1]) == []                              # 最新日缺 → 容忍
    assert run(sessions[:1] + sessions[2:]) == ["2026-10-13"]    # 次新日缺 → 要報
    assert run(sessions[1:]) == ["2026-10-12"]                   # 窗口最舊日缺 → 要報


def _healthy_tables():
    return {table: {"rows": 1, "start": "2026-07-27", "end": "2026-07-27"}
            for table in health._REQUIRED_TABLES}


@pytest.mark.parametrize("missing, code", [(["2026-10-12"], 1), ([], 0)])
def test_strict_gate_depends_on_missing_valuation_dates_alone(monkeypatch, missing, code):
    """下面那個 parametrize 的 tables 是空的 → empty_required 恆為真，它擋不住『gate 漏接
    某個欄位』；這裡讓其他一切健康，只有 valuation 缺日決定結果。"""
    monkeypatch.setattr(health, "report", lambda engine, **_: {
        "tables": _healthy_tables(), "thin_days": {},
        "integrity": {"missing_valuation_dates": missing},
    })

    assert health.run(engine=object(), strict=True) == code


def test_run_prints_missing_valuation_dates_line(monkeypatch, capsys):
    monkeypatch.setattr(health, "report", lambda engine, **_: {
        "tables": {}, "thin_days": {},
        "integrity": {"missing_valuation_dates": ["2026-10-12"]},
    })

    assert health.run(engine=object(), strict=False) == 0
    assert "missing valuation dates: 1 -> ['2026-10-12']" in capsys.readouterr().out


def test_health_and_daily_share_one_recent_window():
    """視窗一旦漂開，就會出現「gate 擋住、但 daily 補不到那天」的死結。"""
    import inspect

    assert health.RECENT_SESSIONS == crawl.RECENT_SESSIONS      # health 沒有自己寫死
    assert (inspect.signature(crawl.daily_update).parameters["days"].default
            == crawl.RECENT_SESSIONS)


def test_strict_health_rejects_empty_required_table(monkeypatch):
    tables = {
        table: {"rows": 1, "start": "2026-07-27", "end": "2026-07-27"}
        for table in health._REQUIRED_TABLES
    }
    tables["monthly_revenue"]["rows"] = 0
    monkeypatch.setattr(health, "report", lambda engine, **_: {
        "tables": tables,
        "thin_days": {},
        "integrity": {},
    })

    assert health.run(engine=object(), strict=True) == 1


def test_non_strict_health_reports_but_does_not_fail(monkeypatch):
    monkeypatch.setattr(health, "report", lambda engine, **_: {
        "tables": {},
        "thin_days": {"price": [("2026-07-27", 100)]},
        "integrity": {"missing_price_dates": ["2026-07-27"]},
    })

    assert health.run(engine=object(), strict=False) == 0


@pytest.mark.parametrize("gap", [
    "missing_index_dates",
    "missing_institutional_dates",
    "missing_margin_dates",
    "missing_valuation_dates",
])
def test_strict_health_rejects_stale_secondary_source(monkeypatch, gap):
    monkeypatch.setattr(health, "report", lambda engine, **_: {
        "tables": {},
        "thin_days": {},
        "integrity": {
            gap: ["2026-07-27"],
            "missing_price_adjustments": [],
        },
    })

    assert health.run(engine=object(), strict=True) == 1


def test_cli_health_strict_propagates_failure_exit(monkeypatch):
    engine = object()
    seen = []
    monkeypatch.setattr(cli, "get_engine", lambda: engine)
    monkeypatch.setattr(
        health,
        "run",
        lambda actual_engine, strict=False: seen.append((actual_engine, strict)) or 1,
    )

    with pytest.raises(SystemExit) as exc:
        cli.main(["health", "--strict"])

    assert exc.value.code == 1
    assert seen == [(engine, True)]


def test_thin_days_tolerates_slow_listing_growth():
    # 上市家數逐年成長不該誤報(全域中位數的舊病)
    from datetime import timedelta
    d0 = date(2026, 1, 1)
    days = [(d0 + timedelta(days=i), 1000 + i * 5) for i in range(60)]
    assert health.thin_days(days) == []


class _FakeEngine:
    """crawl_range 只用 engine.begin() 當 context manager。"""

    @contextlib.contextmanager
    def begin(self):
        yield None


def test_crawl_range_only_requests_known_trading_days(monkeypatch):
    seen = []
    # 2024 春節休市 2/6~2/14 是連續 7 個平日;只有 2/5、2/15 是交易日
    cal = {date(2024, 2, 5), date(2024, 2, 15)}
    monkeypatch.setattr(crawl, "_trading_dates", lambda conn, s, e: cal)
    monkeypatch.setattr(crawl, "crawl_day",
                        lambda conn, source, d, replace=False: seen.append(d) or 1)
    dates = [date(2024, 2, 5) + __import__("datetime").timedelta(days=i)
             for i in range(11)]
    crawl.crawl_range(_FakeEngine(), "valuation", dates, resume=False)
    assert seen == sorted(cal)  # 假日一個請求都不該發


@pytest.mark.parametrize("source", ["institutional", "margin", "valuation"])
def test_crawl_range_crawls_saturday_in_calendar(monkeypatch, source):
    saturday = date(1900, 1, 6)
    seen = []
    monkeypatch.setattr(crawl, "_trading_dates", lambda conn, s, e: {saturday})
    monkeypatch.setattr(crawl, "crawl_day",
                        lambda conn, src, d, replace=False: seen.append(d) or 1)

    assert crawl.crawl_range(_FakeEngine(), source, [saturday], resume=False) == 1
    assert seen == [saturday]


@pytest.mark.parametrize("source", ["institutional", "margin", "valuation"])
def test_crawl_range_skips_saturday_outside_calendar(monkeypatch, source):
    friday, saturday = date(1900, 1, 5), date(1900, 1, 6)
    seen = []
    monkeypatch.setattr(crawl, "_trading_dates", lambda conn, s, e: {friday})
    monkeypatch.setattr(crawl, "crawl_day",
                        lambda conn, src, d, replace=False: seen.append(d) or 1)

    assert crawl.crawl_range(
        _FakeEngine(), source, [friday, saturday], resume=False) == 1
    assert seen == [friday]


@pytest.mark.parametrize("source", ["institutional", "margin", "valuation"])
def test_crawl_range_empty_calendar_crawls_no_dates(monkeypatch, source):
    seen = []
    monkeypatch.setattr(crawl, "_trading_dates", lambda conn, s, e: set())
    monkeypatch.setattr(crawl, "crawl_day",
                        lambda conn, src, d, replace=False: seen.append(d) or 1)

    assert crawl.crawl_range(
        _FakeEngine(), source, [date(1900, 1, 5), date(1900, 1, 6)], resume=False) == 0
    assert seen == []


def test_crawl_range_price_without_calendar_skips_weekends(monkeypatch):
    friday = date(1900, 1, 5)
    seen = []

    def unexpected_calendar(*args):
        pytest.fail("price 不應讀取由自己建立的交易日曆")

    monkeypatch.setattr(crawl, "_trading_dates", unexpected_calendar)
    monkeypatch.setattr(crawl, "crawl_day",
                        lambda conn, src, d, replace=False: seen.append(d) or 1)

    assert crawl.crawl_range(
        _FakeEngine(), "price", [friday + timedelta(days=i) for i in range(3)],
        resume=False) == 1
    assert seen == [friday]


def test_crawl_range_raises_on_blocked_streak(monkeypatch):
    """過濾掉假日之後,連續零列只剩「被封鎖/端點改版」一種解釋,不能安靜跳完。"""
    monkeypatch.setattr(crawl, "_trading_dates",
                        lambda conn, s, e: {date(2026, 3, d) for d in range(2, 21)})
    monkeypatch.setattr(crawl, "crawl_day", lambda *a, **k: 0)
    days = [date(2026, 3, d) for d in range(2, 21)]
    with pytest.raises(RuntimeError, match="consecutive trading days returned 0"):
        crawl.crawl_range(_FakeEngine(), "valuation", days, resume=False)


def test_crawl_range_streak_threshold_is_looser_without_calendar():
    """price 自己就是日曆來源,沒有日曆可過濾假日,零列還有「國定假日」這個正常解釋。

    門檻必須高過最長的連續平日休市(2024 春節 2/6~2/14 是 7 個平日),否則跨春節回補
    price 會被誤判成 IP 封鎖而中止。
    """
    assert crawl._MAX_EMPTY_STREAK_NO_CALENDAR > 7
    assert crawl._MAX_EMPTY_STREAK_NO_CALENDAR > crawl._MAX_EMPTY_STREAK

    seen = []

    def fake_day(conn, source, d, replace=False):
        seen.append(d)
        return 0

    import unittest.mock as _m
    with _m.patch.object(crawl, "crawl_day", fake_day), \
         _m.patch.object(crawl, "_trading_dates", lambda conn, s, e: set()):
        # 2/5~2/15 共 9 個平日(含春節休市的 7 個)全部零列,不該中止
        days = [date(2024, 2, 5) + timedelta(days=i) for i in range(11)]
        crawl.crawl_range(_FakeEngine(), "price", days, resume=False)
    assert len(seen) == 9                          # 週末仍然跳過,不浪費請求
    assert all(d.weekday() < 5 for d in seen)
