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


class Engine:
    def __init__(self, existing=()):
        self.existing = existing
        self.statements = []
        self.committed = 0

    @contextmanager
    def begin(self):
        yield self
        self.committed += 1

    def execute(self, statement, parameters=None):
        self.statements.append((statement, parameters))
        return [(d,) for d in self.existing]


def test_backfill_uses_months_bounds_resume_and_committed_progress(report, monkeypatch, capsys):
    engine = Engine(existing=[date(2010, 1, 5)])
    fetched, pauses, written = [], [], []

    def fetch(asof):
        fetched.append(asof)
        if asof.month == 2:
            return None
        return sources.parse_index_ohlc_report(report, asof)

    monkeypatch.setattr(sources, "fetch_index_ohlc", fetch)
    monkeypatch.setattr("time.sleep", pauses.append)

    def upsert(conn, table, records, pk, **kwargs):
        assert conn is engine and table is models.MarketIndex.__table__
        assert pk == ["index_id", "date"]
        assert set(kwargs["coalesce"]) == {"open", "high", "low", "change", "turnover"}
        written.extend(records)
        return len(records)

    monkeypatch.setattr(crawl, "upsert", upsert)
    total = crawl.backfill_index(engine, date(2010, 1, 5), date(2010, 2, 3), delay=3)
    assert total == len(written) == 18
    assert fetched == [date(2010, 1, 1), date(2010, 2, 1)]
    assert pauses == [3]
    assert min(r["date"].date() for r in written) == date(2010, 1, 6)
    assert max(r["date"].date() for r in written) == date(2010, 1, 29)
    assert engine.committed >= 1
    query, params = engine.statements[0]
    assert "index_id = 'TAIEX'" in str(query)
    for field in ("open", "high", "low", "close"):
        assert f"{field} IS NOT NULL" in str(query)
    assert params == {"start": date(2010, 1, 5), "end": date(2010, 2, 3)}
    out = capsys.readouterr().out
    assert "index 2010-01 18 rows, latest 2010-01-29" in out
    assert "**WARN index 2010-02" in out


def test_force_refreshes_existing_day_without_deleting_other_fields(report, monkeypatch):
    engine = Engine(existing=[date(2010, 1, 4)])
    monkeypatch.setattr(sources, "fetch_index_ohlc",
                        lambda asof: sources.parse_index_ohlc_report(report, asof))
    assert crawl.backfill_index(engine, date(2010, 1, 4), date(2010, 1, 4), resume=False) == 1
    assert len(engine.statements) == 1
    compiled = str(engine.statements[0][0].compile(dialect=postgresql.dialect()))
    assert compiled.startswith("INSERT INTO market.market_index")
    for col in ("open", "high", "low", "change", "turnover"):
        assert f"{col} = coalesce(excluded.{col}, market.market_index.{col})" in compiled
    assert "close = excluded.close" in compiled


def test_failed_month_does_not_block_a_later_month(monkeypatch):
    engine = Engine()
    fetched = []

    def fetch(asof):
        fetched.append(asof)
        if asof.month == 2:
            return None
        return [{"Date": f"099{asof.month:02d}01", "Open": "8000", "High": "8001",
                 "Low": "7999", "TAIEX": "8000"}]

    monkeypatch.setattr(sources, "fetch_index_ohlc", fetch)
    assert crawl.backfill_index(engine, date(2010, 1, 1), date(2010, 3, 1), delay=0) == 2
    assert fetched == [date(2010, m, 1) for m in (1, 2, 3)]
    assert len(engine.statements) == 3


def test_resume_of_complete_ohlc_does_not_write(report, monkeypatch):
    engine = Engine(existing=[date(2010, 1, 4)])
    monkeypatch.setattr(sources, "fetch_index_ohlc",
                        lambda asof: sources.parse_index_ohlc_report(report, asof))
    assert crawl.backfill_index(engine, date(2010, 1, 4), date(2010, 1, 4)) == 0
    assert len(engine.statements) == 1
    assert str(engine.statements[0][0]).startswith("SELECT")


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


@pytest.mark.parametrize("start,end,delay", [(date(2010, 2, 1), date(2010, 1, 1), 0),
                                           (date(2010, 1, 1), date(2010, 2, 1), -1)])
def test_invalid_backfill_bounds_do_not_fetch_or_write(start, end, delay, monkeypatch):
    monkeypatch.setattr(sources, "fetch_index_ohlc", lambda d: pytest.fail("unexpected request"))
    with pytest.raises(ValueError):
        crawl.backfill_index(Engine(), start, end, delay=delay)


@pytest.mark.parametrize("force", [False, True])
def test_cli_dispatches_index_to_monthly_backfill(monkeypatch, force):
    engine = object()
    calls = []
    monkeypatch.setattr(cli, "get_engine", lambda: engine)
    monkeypatch.setattr(crawl, "backfill_index", lambda *a, **kw: calls.append((a, kw)))
    monkeypatch.setattr(crawl, "crawl_range", lambda *a, **kw: pytest.fail("daily date loop used"))
    cli.main(["backfill", "index", "--start", "2010-01-01", "--end", "2010-02-03",
              "--delay", "3"] + (["--force"] if force else []))
    assert calls == [((engine, date(2010, 1, 1), date(2010, 2, 3)),
                      {"resume": not force, "delay": 3.0})]
