"""TAIEX 月 OHLC 回補：來源日期、邊界與互補欄位不得被快照洗掉。"""

import copy
import json
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy import create_engine, select

from market_data import cli, crawl, etl, models, sources


@pytest.fixture
def report():
    return json.loads((Path(__file__).parent / "fixtures/taiex_201001.json").read_text())


class Response:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def test_official_fixture_reaches_typed_ohlc_with_own_dates(report):
    rows = sources.parse_index_ohlc_report(report, date(2010, 1, 1))
    frame = etl.transform_index(rows).xs("TAIEX")
    assert len(frame) == 20
    first, last = frame.iloc[0], frame.iloc[-1]
    assert str(frame.index[0])[:10] == "2010-01-04"
    assert str(frame.index[-1])[:10] == "2010-01-29"
    assert tuple(first[c] for c in ("open", "high", "low", "close")) == (
        8222.42, 8240.45, 8143.45, 8207.85)
    assert last["close"] == 7640.44
    assert frame[["change", "turnover"]].isna().all().all()
    # 欄位順序可調換，不能靠位置把最高、最低或收盤對錯欄。
    reordered = copy.deepcopy(report)
    reordered["fields"].reverse()
    for row in reordered["data"]:
        row.reverse()
    assert sources.parse_index_ohlc_report(reordered, date(2010, 1, 31)) == rows


@pytest.mark.parametrize("bad_day", ["98/12/31", "100/01/04", "", None, "99/02/30"])
def test_ohlc_rejects_one_bad_row_even_when_envelope_echoes_request(report, bad_day):
    report["data"][-1][0] = bad_day
    with pytest.raises(ValueError):
        sources.parse_index_ohlc_report(report, date(2010, 1, 1))


@pytest.mark.parametrize("field,value", [("收盤指數", "--"), ("最高指數", "nan"),
                                         ("最低指數", "-1"), ("開盤指數", "999999")])
def test_ohlc_rejects_invalid_values_instead_of_null_washing(report, field, value):
    report["data"][0][report["fields"].index(field)] = value
    with pytest.raises(ValueError):
        sources.parse_index_ohlc_report(report, date(2010, 1, 1))


def test_ohlc_requires_date_and_all_ohlc_headers(report):
    for field in report["fields"]:
        bad = copy.deepcopy(report)
        bad["fields"][bad["fields"].index(field)] = "未知欄"
        with pytest.raises(ValueError):
            sources.parse_index_ohlc_report(bad, date(2010, 1, 1))


def test_ohlc_accepts_flat_bar_and_preserves_a_real_zero_change(report):
    report["data"] = [["99/01/04", "8,000", "8,000", "8,000", "8,000"]]
    rows = sources.parse_index_ohlc_report(report, date(2010, 1, 1))
    rows[0].update(Change="0.00", TradeValue="0")
    row = etl.transform_index(rows).iloc[0]
    assert tuple(row[c] for c in ("open", "high", "low", "close")) == (8000,) * 4
    assert row["change"] == 0 and row["turnover"] == 0


def test_fetch_ohlc_uses_monthly_endpoint_and_accepts_row_dates_without_envelope(report, monkeypatch):
    report.pop("date")
    calls = []

    def fetch(url, **kwargs):
        calls.append((url, kwargs))
        return Response(report)

    monkeypatch.setattr(sources, "requests_get", fetch)
    rows = sources.fetch_index_ohlc(date(2010, 1, 31))
    assert len(rows) == 20
    assert calls[0][0].endswith("/rwd/zh/TAIEX/MI_5MINS_HIST")
    assert calls[0][1]["params"] == {"date": "20100131", "response": "json"}


@pytest.mark.parametrize("failure", ["http", "json", "stat", "empty", "stale", "missing_date"])
def test_fetch_ohlc_warns_and_returns_none_on_unusable_payload(report, monkeypatch, capsys, failure):
    if failure == "stat":
        report["stat"] = "沒有資料"
    elif failure == "empty":
        report["data"] = []
    elif failure == "stale":
        for row in report["data"]:
            row[0] = row[0].replace("99/", "98/")
    elif failure == "missing_date":
        report["fields"][0] = "未知欄"

    def fetch(*args, **kwargs):
        if failure == "http":
            return None
        if failure == "json":
            raise ValueError("non-JSON")
        return Response(report)

    monkeypatch.setattr(sources, "requests_get", fetch)
    assert sources.fetch_index_ohlc(date(2010, 1, 1)) is None
    out = capsys.readouterr().out
    assert "**WARN" in out and "MI_5MINS_HIST" in out and "2010-01" in out


@pytest.mark.parametrize("fallback", [False, True])
def test_fmtqik_rejects_frozen_month_from_both_network_paths(monkeypatch, capsys, fallback):
    report = {"stat": "OK", "date": "20100101",
              "fields": ["日期", "成交金額", "發行量加權股價指數", "漲跌點數"],
              "data": [["98/01/05", "1,000", "8,000", "-2"]]}
    monkeypatch.setattr(sources, "requests_get", lambda *a, **k: Response(report))
    monkeypatch.setattr(sources, "_openapi_json", lambda u: [
        {"Date": "0980105", "TradeValue": "1000", "TAIEX": "8000", "Change": "-2"}])
    assert sources.fetch_index(date(2010, 1, 1), fallback=fallback) is None
    assert "2010-01" in capsys.readouterr().out


_FMTQIK = Path(__file__).parent / "fixtures/fmtqik_rwd_201001.json"


def _fmtqik_payload():
    """2010-01 FMTQIK rwd 真實回應裁成三列(1/4~1/6,日期帶前導空白)。"""
    return json.loads(_FMTQIK.read_text(encoding="utf-8"))


@pytest.mark.parametrize("asof", [date(2010, 1, 1), date(2010, 1, 15), date(2010, 1, 31)])
def test_fmtqik_accepts_any_day_of_the_requested_month(monkeypatch, asof):
    """反向檢查:守門比的是「月」,不是請求日——同月任一天都要收(改成比日就會紅)。"""
    monkeypatch.setattr(sources, "requests_get", lambda *a, **k: Response(_fmtqik_payload()))
    rows = sources.fetch_index(asof, fallback=False)
    assert [r["Date"] for r in rows] == ["0990104", "0990105", "0990106"]
    assert rows[0]["TAIEX"] == "8,207.85" and rows[0]["TradeValue"] == "171,654,446,230"


def test_fmtqik_rejects_other_month_and_says_why(monkeypatch, capsys):
    """請求 2010-02 卻拿到 2010-01 整月表(端點停更照回 200):拒收,WARN 要帶原因而非只說失敗。"""
    monkeypatch.setattr(sources, "requests_get", lambda *a, **k: Response(_fmtqik_payload()))
    monkeypatch.setattr(sources, "_openapi_json",
                        lambda url: pytest.fail("past month must not fall back to openapi"))
    assert sources.fetch_index(date(2010, 2, 15), fallback=False) is None
    out = capsys.readouterr().out
    assert "outside requested month" in out and "2010-02" in out


def test_fmtqik_rejects_a_table_straddling_months(monkeypatch):
    payload = _fmtqik_payload()
    payload["data"].append([" 99/02/01", "1", "1", "1", "8,000.00", "1.00"])
    monkeypatch.setattr(sources, "requests_get", lambda *a, **k: Response(payload))
    assert sources.fetch_index(date(2010, 1, 15), fallback=False) is None


def test_fmtqik_wrong_month_on_current_month_still_falls_back(monkeypatch):
    """當月 rwd 回錯月份視同 rwd 失敗:照舊退到 openapi(其列日期屬當月才收)。"""
    monkeypatch.setattr(sources, "requests_get", lambda *a, **k: Response(_fmtqik_payload()))
    openapi = [{"Date": "1151026", "TAIEX": "1", "Change": "1", "TradeValue": "1"}]
    monkeypatch.setattr(sources, "_openapi_json", lambda url: openapi)
    assert sources.fetch_index(date(2026, 10, 26)) == openapi


class _Result(list):
    def fetchall(self):
        return list(self)


class Engine:
    """假 engine/conn:price 日曆查詢回 ``cal``,market_index 完整日期查詢回 ``existing``。"""

    def __init__(self, existing=(), cal=()):
        self.existing = existing
        self.cal = cal
        self.statements = []
        self.committed = 0

    @contextmanager
    def begin(self):
        yield self
        self.committed += 1

    def execute(self, statement, parameters=None):
        self.statements.append((statement, parameters))
        rows = self.cal if "market.price" in str(statement) else self.existing
        return _Result((d,) for d in rows)


def _ohlc_rows(days):
    return [{"Date": f"{d.year - 1911:03d}{d.month:02d}{d.day:02d}", "Open": "8000",
             "High": "8001", "Low": "7999", "TAIEX": "8000"} for d in days]


def _fmtqik_rows(days):
    return [{"Date": f"{d.year - 1911:03d}{d.month:02d}{d.day:02d}", "TAIEX": "8000",
             "Change": "1.5", "TradeValue": "1,000"} for d in days]


@pytest.fixture
def net(monkeypatch):
    """今天釘在 2010-03-10;兩個來源依 ``days`` 回該月的列,``fail_*`` 指定哪個月哪個來源抓不到。"""
    state = {"days": {date(2010, 1, 4), date(2010, 1, 5), date(2010, 2, 1), date(2010, 3, 1)},
             "fail_ohlc": set(), "fail_fmtqik": set(), "ohlc": [], "fmtqik": [],
             "written": [], "pauses": []}
    monkeypatch.setattr(crawl, "_today", lambda: date(2010, 3, 10))
    monkeypatch.setattr("time.sleep", state["pauses"].append)

    def month_days(asof):
        return sorted(d for d in state["days"] if (d.year, d.month) == (asof.year, asof.month))

    def ohlc(asof):
        state["ohlc"].append(asof)
        return None if asof.month in state["fail_ohlc"] else _ohlc_rows(month_days(asof))

    def fmtqik(asof=None, fallback=True):
        state["fmtqik"].append((asof, fallback))
        return None if asof.month in state["fail_fmtqik"] else _fmtqik_rows(month_days(asof))

    def upsert(conn, table, records, pk, **kwargs):
        assert table is models.MarketIndex.__table__ and pk == ["index_id", "date"]
        assert set(kwargs["coalesce"]) == {"open", "high", "low", "change", "turnover"}
        state["written"].extend(records)
        return len(records)

    monkeypatch.setattr(sources, "fetch_index_ohlc", ohlc)
    monkeypatch.setattr(sources, "fetch_index", fmtqik)
    monkeypatch.setattr(crawl, "upsert", upsert)
    return state


def test_backfill_merges_real_ohlc_with_fmtqik_change_and_turnover(report, monkeypatch):
    """MI_5MINS_HIST 沒有漲跌/成交金額:不合併 FMTQIK 的話回補列 change 為 NULL,
    `screen_tw` 回放歷史日的 market_d1 會變 NaN。反向:FMTQIK 沒有的日期照寫 OHLC,不是取交集。"""
    monkeypatch.setattr(crawl, "_today", lambda: date(2026, 10, 26))
    monkeypatch.setattr(sources, "fetch_index_ohlc",
                        lambda asof: sources.parse_index_ohlc_report(report, asof))
    monkeypatch.setattr(sources, "fetch_index",
                        lambda asof=None, fallback=True: sources.parse_index_report(_fmtqik_payload()))
    written = []
    monkeypatch.setattr(crawl, "upsert", lambda conn, t, recs, pk, **kw: written.extend(recs) or len(recs))
    cal = {date(2010, 1, 4), date(2010, 1, 5), date(2010, 1, 6)}
    res = crawl.backfill_index(Engine(cal=cal), date(2010, 1, 1), date(2010, 1, 31), delay=0)
    assert res["written"] == 20 and not res["failed"] and not res["partial"] and not res["short"]
    by_day = {r["date"].date(): r for r in written}
    first = by_day[date(2010, 1, 4)]
    assert (float(first["open"]), float(first["close"]), float(first["change"]), int(first["turnover"])) == (
        8222.42, 8207.85, 19.74, 171654446230)
    last = by_day[date(2010, 1, 29)]
    assert float(last["close"]) == 7640.44 and float(last["open"]) > 0
    assert last["change"] is None and last["turnover"] is None   # 必須是 NULL 不是 NaN:Postgres NUMERIC 收 NaN、coalesce 擋不住


def test_backfill_prefers_ohlc_close_without_losing_fmtqik_only_dates(net, monkeypatch):
    """同日收盤不一致時採 OHLC；只有 FMTQIK 的日期仍保留其收盤與互補欄位。"""
    first, second = date(2010, 1, 4), date(2010, 1, 5)
    net["days"] = {first, second}
    ohlc = _ohlc_rows([first])
    ohlc[0]["TAIEX"] = "8,000.50"
    monkeypatch.setattr(sources, "fetch_index_ohlc", lambda asof: ohlc)

    res = crawl.backfill_index(Engine(cal=net["days"]), first, second, delay=0)

    assert res["written"] == 2
    by_day = {r["date"].date(): r for r in net["written"]}
    assert tuple(float(by_day[first][c]) for c in ("open", "high", "low", "close", "change", "turnover")) == (
        8000, 8001, 7999, 8000.50, 1.5, 1000)
    assert float(by_day[second]["close"]) == 8000
    assert float(by_day[second]["change"]) == 1.5 and float(by_day[second]["turnover"]) == 1000
    assert all(by_day[second][c] is None for c in ("open", "high", "low"))
    assert res["short"] == {"2010-01": ["2010-01-05"]}


def test_backfill_keeps_dates_only_one_source_has(net, monkeypatch):
    """反向:FMTQIK 有、MI_5MINS_HIST 沒有的日子仍寫入(收盤取 FMTQIK),不因合併被丟掉。"""
    net["days"] = {date(2010, 1, 4)}
    res = crawl.backfill_index(Engine(cal={date(2010, 1, 4), date(2010, 1, 5)}),
                               date(2010, 1, 1), date(2010, 1, 31), delay=0)
    assert res["short"] == {"2010-01": ["2010-01-05"]}            # 兩來源都沒有 → 稽核抓到

    net["written"].clear()
    net["days"] = {date(2010, 1, 4), date(2010, 1, 5)}
    monkeypatch.setattr(sources, "fetch_index_ohlc", lambda asof: _ohlc_rows([date(2010, 1, 4)]))
    res = crawl.backfill_index(Engine(cal={date(2010, 1, 4), date(2010, 1, 5)}),
                               date(2010, 1, 1), date(2010, 1, 31), delay=0)
    assert res["short"] == {"2010-01": ["2010-01-05"]}            # 照寫,但 OHLC 缺這天 → 仍算缺日
    only_fmtqik = [r for r in net["written"] if r["date"].date() == date(2010, 1, 5)]
    assert len(only_fmtqik) == 1 and float(only_fmtqik[0]["close"]) == 8000
    assert only_fmtqik[0]["open"] is None and float(only_fmtqik[0]["change"]) == 1.5


@pytest.mark.parametrize("truncated", ["fetch_index_ohlc", "fetch_index"])
def test_backfill_flags_dates_missing_from_either_nonempty_source(net, monkeypatch, capsys, truncated):
    """月表被截短(當月 MI_5MINS_HIST 比 FMTQIK 晚一天、或任一表少列)但不是整個空:
    以兩來源聯集稽核會把只寫了一半欄位的日子當成補齊、exit 0。每個來源要各自對 price 交易日。"""
    net["days"] = {date(2010, 1, 4), date(2010, 1, 5)}
    if truncated == "fetch_index_ohlc":
        monkeypatch.setattr(sources, "fetch_index_ohlc", lambda asof: _ohlc_rows([date(2010, 1, 4)]))
    else:
        monkeypatch.setattr(sources, "fetch_index",
                            lambda asof=None, fallback=True: _fmtqik_rows([date(2010, 1, 4)]))
    res = crawl.backfill_index(Engine(cal={date(2010, 1, 4), date(2010, 1, 5)}),
                               date(2010, 1, 1), date(2010, 1, 31), delay=0)
    assert res["short"] == {"2010-01": ["2010-01-05"]} and not res["partial"]
    assert res["written"] == 2                                     # 拿到的欄位照寫,只是稽核不放行
    name = "MI_5MINS_HIST" if truncated == "fetch_index_ohlc" else "FMTQIK"
    assert f"{name} 缺 ['2010-01-05']" in capsys.readouterr().out


def test_backfill_short_audit_ignores_complete_dates_and_full_months(net, monkeypatch):
    """反向:兩來源都齊的月份不算缺日;已六欄齊全(resume 不重寫)的日期即使這次來源沒給也不算缺。"""
    cal = {date(2010, 1, 4), date(2010, 1, 5)}
    net["days"] = set(cal)
    res = crawl.backfill_index(Engine(cal=cal), date(2010, 1, 1), date(2010, 1, 31), delay=0)
    assert not res["short"] and not res["partial"] and res["written"] == 2

    monkeypatch.setattr(sources, "fetch_index_ohlc", lambda asof: _ohlc_rows([date(2010, 1, 5)]))
    res = crawl.backfill_index(Engine(existing={date(2010, 1, 4)}, cal=cal),
                               date(2010, 1, 1), date(2010, 1, 31), delay=0)
    assert not res["short"]


def test_backfill_months_asof_fallback_bounds_and_pauses(net, capsys):
    engine = Engine(cal=set(net["days"]))
    net["fail_ohlc"] = net["fail_fmtqik"] = {2}
    res = crawl.backfill_index(engine, date(2010, 1, 5), date(2010, 3, 1), delay=3)
    assert net["ohlc"] == [date(2010, 1, 1), date(2010, 2, 1), date(2010, 3, 1)]
    # 過去月份 asof = 月底(或 end)且不准 openapi;只有當月(今天 3/10 所在月)允許 fallback
    assert net["fmtqik"] == [(date(2010, 1, 31), False), (date(2010, 2, 28), False),
                             (date(2010, 3, 1), True)]
    assert net["pauses"] == [3] * 5                     # 每個請求之間都等,不只月與月之間
    assert sorted(r["date"].date() for r in net["written"]) == [date(2010, 1, 5), date(2010, 3, 1)]
    assert res["failed"] == ["2010-02"] and res["months"] == 2
    out = capsys.readouterr().out
    assert "index 2010-01 1 rows (price days 1)" in out and "**WARN index 2010-02" in out


def test_backfill_resume_requires_all_six_columns(net):
    """resume 的「已補齊」要六欄都有值:只看 OHLC 四欄的話,沒有漲跌的列永遠不會被補。"""
    engine = Engine(existing=set(net["days"]), cal=set(net["days"]))
    res = crawl.backfill_index(engine, date(2010, 1, 1), date(2010, 3, 1), delay=0)
    assert res["skipped"] == 3 and net["ohlc"] == [] and net["fmtqik"] == []
    sql = str(next(s for s, _ in engine.statements if "market.market_index" in str(s)))
    for col in ("open", "high", "low", "close", "change", "turnover"):
        assert f"{col} IS NOT NULL" in sql

    # 反向:缺一天的月份要重抓,但已齊全的日期不重寫
    engine = Engine(existing={date(2010, 1, 4), date(2010, 2, 1), date(2010, 3, 1)},
                    cal=set(net["days"]))
    res = crawl.backfill_index(engine, date(2010, 1, 1), date(2010, 3, 1), delay=0)
    assert net["ohlc"] == [date(2010, 1, 1)] and res["skipped"] == 2
    assert [r["date"].date() for r in net["written"]] == [date(2010, 1, 5)]


def test_backfill_month_without_price_calendar_is_fetched(net):
    """price 該月沒資料無從判斷完整:照抓,不因 expected 為空就當作已補。"""
    crawl.backfill_index(Engine(existing=set(net["days"]), cal=set()),
                         date(2010, 1, 1), date(2010, 1, 31), delay=0)
    assert net["ohlc"] == [date(2010, 1, 1)]


def test_force_refreshes_existing_day_without_deleting_other_fields(report, monkeypatch):
    engine = Engine(existing=[date(2010, 1, 4)], cal=[date(2010, 1, 4)])
    monkeypatch.setattr(crawl, "_today", lambda: date(2026, 10, 26))
    monkeypatch.setattr(sources, "fetch_index_ohlc",
                        lambda asof: sources.parse_index_ohlc_report(report, asof))
    monkeypatch.setattr(sources, "fetch_index", lambda asof=None, fallback=True: None)
    res = crawl.backfill_index(engine, date(2010, 1, 4), date(2010, 1, 4), resume=False)
    assert res["written"] == 1 and res["partial"] == ["2010-01"]
    assert not any("open IS NOT NULL" in str(s) for s, _ in engine.statements)   # 不查 resume
    compiled = str(engine.statements[-1][0].compile(dialect=postgresql.dialect()))
    assert compiled.startswith("INSERT INTO market.market_index")
    for col in ("open", "high", "low", "change", "turnover"):
        assert f"{col} = coalesce(excluded.{col}, market.market_index.{col})" in compiled
    assert "close = excluded.close" in compiled


def test_backfill_single_source_missing_is_partial_not_failed(net, capsys):
    net["fail_ohlc"] = {1}
    res = crawl.backfill_index(Engine(cal=set(net["days"])), date(2010, 1, 1), date(2010, 1, 31), delay=0)
    assert res["partial"] == ["2010-01"] and not res["failed"]
    assert all(float(r["change"]) == 1.5 for r in net["written"])
    assert "MI_5MINS_HIST 無資料" in capsys.readouterr().out


def test_backfill_stops_after_consecutive_failures(net, monkeypatch):
    monkeypatch.setattr(crawl, "_INDEX_MAX_FAILED_STREAK", 2)
    net["fail_ohlc"] = net["fail_fmtqik"] = {1, 2}
    with pytest.raises(RuntimeError, match="consecutive months"):
        crawl.backfill_index(Engine(cal=set(net["days"])), date(2010, 1, 1), date(2010, 3, 1), delay=0)
    assert net["ohlc"] == [date(2010, 1, 1), date(2010, 2, 1)]     # 第 3 個月沒有再打


def test_backfill_single_failure_resets_streak(net, monkeypatch):
    """反向:失敗中間夾一個成功月,streak 歸零,不會誤停。"""
    monkeypatch.setattr(crawl, "_INDEX_MAX_FAILED_STREAK", 2)
    net["fail_ohlc"] = net["fail_fmtqik"] = {1, 3}
    res = crawl.backfill_index(Engine(cal=set(net["days"])), date(2010, 1, 1), date(2010, 3, 1), delay=0)
    assert res["failed"] == ["2010-01", "2010-03"]


def test_backfill_clamps_end_to_today(net):
    crawl.backfill_index(Engine(cal=set(net["days"])), date(2010, 3, 1), date(2010, 12, 31), delay=0)
    assert net["ohlc"] == [date(2010, 3, 1)] and net["fmtqik"] == [(date(2010, 3, 10), True)]


def test_snapshot_preserves_ohlc_and_still_updates_present_values(monkeypatch):
    engine = Engine()
    monkeypatch.setattr(crawl, "_today", lambda: date(2010, 1, 5))
    monkeypatch.setattr(sources, "fetch_index", lambda **kw: [
        {"Date": "0990105", "TAIEX": "8,211.40", "Change": "3.55", "TradeValue": "10,000"}])
    assert crawl.crawl_index(engine) == 1
    stmt = engine.statements[0][0]
    values = stmt.compile(dialect=postgresql.dialect()).params
    assert values["close_m0"] == 8211.40
    assert values["change_m0"] == 3.55 and values["turnover_m0"] == 10000
    assert all(values[f"{col}_m0"] is None for col in ("open", "high", "low"))
    compiled = str(stmt.compile(dialect=postgresql.dialect()))
    for col in ("open", "high", "low"):
        assert f"{col} = coalesce(excluded.{col}, market.market_index.{col})" in compiled


def test_real_writer_merges_both_sources_and_allows_official_corrections(report):
    # 只用 SQLite 記憶體庫驗證共用 writer 的實際衝突更新，不讀任何正式 DB URL。
    engine = create_engine("sqlite://")
    table = models.MarketIndex.__table__
    snapshot = {"Date": "0990104", "TAIEX": "8,200", "Change": "-5", "TradeValue": "12,345"}
    history = sources.parse_index_ohlc_report(report, date(2010, 1, 1))[:1]
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS market")
            table.create(conn)
            assert crawl._store_index(conn, [snapshot]) == 1
            assert crawl._store_index(conn, history) == 1
            row = conn.execute(select(table)).mappings().one()
            assert tuple(float(row[c]) for c in ("open", "high", "low", "close", "change", "turnover")) == (
                8222.42, 8240.45, 8143.45, 8207.85, -5, 12345)
            snapshot.update(TAIEX="8,220", Change="0", TradeValue="0")
            assert crawl._store_index(conn, [snapshot]) == 1
            row = conn.execute(select(table)).mappings().one()
            assert tuple(float(row[c]) for c in ("open", "high", "low", "close", "change", "turnover")) == (
                8222.42, 8240.45, 8143.45, 8220, 0, 0)
            history[0]["Open"] = "8,223"
            assert crawl._store_index(conn, history) == 1
            row = conn.execute(select(table)).mappings().one()
            assert tuple(float(row[c]) for c in ("open", "close", "change", "turnover")) == (8223, 8207.85, 0, 0)
    finally:
        engine.dispose()


@pytest.mark.parametrize("start,end,delay", [(date(2010, 2, 1), date(2010, 1, 1), 0), (date(2010, 1, 1), date(2010, 2, 1), -1)])
def test_invalid_backfill_bounds_do_not_fetch_or_write(start, end, delay, monkeypatch):
    monkeypatch.setattr(sources, "fetch_index_ohlc", lambda d: pytest.fail("unexpected request"))
    with pytest.raises(ValueError):
        crawl.backfill_index(Engine(), start, end, delay=delay)


_CLEAN = {"written": 1, "months": 1, "skipped": 0, "failed": [], "partial": [], "short": {}}


@pytest.mark.parametrize("delay_args,pauses", [([], [2.0] * 3), (["--delay", "0"], []),
                                               (["--delay", "3"], [3.0] * 3)])
def test_cli_backfill_index_delay_defaults_and_overrides(net, monkeypatch, delay_args, pauses):
    """跑實際月回補：省略參數沿用函式預設，顯式 0 不被改回預設，跨來源與跨月都等待。"""
    days = {date(2010, 1, 4), date(2010, 1, 5), date(2010, 2, 1)}
    net["days"] = days
    monkeypatch.setattr(cli, "get_engine", lambda: Engine(cal=days))

    cli.main(["backfill", "index", "--start", "2010-01-04", "--end", "2010-02-01", *delay_args])

    assert net["pauses"] == pauses
    assert net["ohlc"] == [date(2010, 1, 1), date(2010, 2, 1)]
    assert net["fmtqik"] == [(date(2010, 1, 31), False), (date(2010, 2, 1), False)]
    assert {r["date"].date() for r in net["written"]} == days


@pytest.mark.parametrize("source", list(crawl.DAILY))
@pytest.mark.parametrize("delay_args,pauses", [([], []), (["--delay", "0"], []),
                                               (["--delay", "3"], [3.0, 3.0])])
def test_cli_backfill_daily_delay_defaults_and_overrides(net, monkeypatch, source, delay_args, pauses):
    """共享 --delay 不應替逐日來源新增等待；明確指定的間隔仍逐日生效。"""
    days = [date(2010, 1, 4), date(2010, 1, 5)]
    engine = Engine(cal=days if source != "price" else ())
    seen = []
    monkeypatch.setattr(cli, "get_engine", lambda: engine)
    monkeypatch.setattr(crawl, "crawl_day",
                        lambda conn, src, day, replace=False: seen.append((src, day, replace)) or 1)

    cli.main(["backfill", source, "--start", "2010-01-04", "--end", "2010-01-05", *delay_args])

    assert seen == [(source, day, False) for day in days]
    assert net["pauses"] == pauses


@pytest.mark.parametrize("force", [False, True])
def test_cli_dispatches_index_to_monthly_backfill(monkeypatch, force):
    engine = object()
    calls = []
    monkeypatch.setattr(cli, "get_engine", lambda: engine)
    monkeypatch.setattr(crawl, "backfill_index", lambda *a, **kw: calls.append((a, kw)) or _CLEAN)
    monkeypatch.setattr(crawl, "crawl_range", lambda *a, **kw: pytest.fail("daily date loop used"))
    cli.main(["backfill", "index", "--start", "2010-01-01", "--end", "2010-02-03",
              "--delay", "3"] + (["--force"] if force else []))
    assert calls == [((engine, date(2010, 1, 1), date(2010, 2, 3)),
                      {"resume": not force, "delay": 3.0})]


@pytest.mark.parametrize("gap", [{"failed": ["2010-02"]}, {"partial": ["2010-02"]},
                                 {"short": {"2010-02": ["2010-02-01"]}}])
def test_cli_backfill_index_exits_nonzero_on_any_gap(monkeypatch, gap):
    monkeypatch.setattr(cli, "get_engine", lambda: object())
    monkeypatch.setattr(crawl, "backfill_index", lambda *a, **kw: {**_CLEAN, **gap})
    with pytest.raises(SystemExit) as exc:
        cli.main(["backfill", "index", "--start", "2010-01-01", "--end", "2010-03-31"])
    assert exc.value.code == 1
