"""期交所 OI 累積：官方 fixture → 共用解析 → 真實 writer；只用記憶體 DB。"""

import datetime as dt
from contextlib import contextmanager
from importlib import import_module
from pathlib import Path

import pytest
import requests
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from market_data import health, models, taifex
from market_data import tw_official_http as http

FIXTURES = Path(__file__).parent / "fixtures"
FUT_OK = (FIXTURES / "taifex_fut_txf_20261013_20261020.bin").read_bytes()
SESSION = dt.date(2026, 10, 20)
TABLE = "taifex_foreign_futures_oi"
migration = import_module(
    "market_data.migrations.versions.e4b7c2a91f06_add_taifex_foreign_futures_oi"
)


class _OutboundBlocked(BaseException):
    """守門例外不能被生產碼的來源降級吞掉。"""


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def blocked(*args, **kwargs):
        raise _OutboundBlocked("測試不得連外或取得正式 DB engine")

    monkeypatch.setattr("socket.socket.connect", blocked)
    monkeypatch.setattr("market_data.db.get_engine", blocked)
    monkeypatch.setattr(health, "_xtai_session_checker", lambda: lambda d: d.weekday() < 5)
    monkeypatch.setenv("TAIFEX_OI_ACCUMULATE_ENABLED", "true")


@pytest.fixture
def official(monkeypatch):
    route = {"body": FUT_OK}
    calls = []

    def send(method, url, **kwargs):
        assert method == "POST" and url == taifex.FUT_URL
        calls.append(kwargs["data"].copy())
        if isinstance(route["body"], Exception):
            raise route["body"]
        response = requests.Response()
        response.status_code = 200
        response._content = route["body"]
        response.headers["Content-Type"] = "text/html;charset=MS950"
        return response

    monkeypatch.setattr(http, "_send", send)
    return route, calls


@pytest.fixture
def oi_schema():
    # 執行真實 Alembic／SQL，完全不讀 DATABASE_URL；同基金 migration 的測試接縫。
    engine = sa.create_engine("sqlite://")
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS market")
            with Operations.context(MigrationContext.configure(conn)):
                migration.upgrade()
                conn.commit()
                yield engine, conn
    finally:
        engine.dispose()


def stored(conn):
    return conn.execute(sa.select(models.TaifexForeignFuturesOi).order_by(
        models.TaifexForeignFuturesOi.date)).all()


def test_accumulates_actual_payload_dates_and_updates_without_duplicates(oi_schema, official, capsys):
    engine, conn = oi_schema
    route, calls = official
    expected = taifex.parse_fut(FUT_OK.decode("cp950"))

    assert taifex.daily_update(engine, asof=SESSION) == 6
    assert stored(conn) == expected
    conn.commit()
    # 同場次重跑要吃進官方修正，不能凍結初值，也不能累加成重複列。
    route["body"] = FUT_OK.replace(b"-89748", b"-88748")
    assert taifex.daily_update(engine, asof=SESSION) == 6
    assert stored(conn) == expected[:-1] + [(SESSION, -88748)]
    assert calls == [{"queryStartDate": "2026/10/06", "queryEndDate": "2026/10/20",
                      "commodityId": "TXF"}] * 2
    assert capsys.readouterr().out.count(f"{TABLE} 6 rows, latest {SESSION}") == 2


@pytest.mark.parametrize("value", [0, 23456, -23456])
def test_single_valid_level_is_stored_without_previous_session(oi_schema, official, value):
    engine, conn = oi_schema
    route, _ = official
    header = FUT_OK.split(b"\r\n")[0].decode("cp950")
    route["body"] = (header + f"\r\n2026/10/20,臺股期貨,外資及陸資,1,1,1,1,0,0,1,1,1,1,{value},1\r\n").encode("cp950")
    assert taifex.daily_update(engine, asof=SESSION) == 1
    assert stored(conn) == [(SESSION, value)]


@pytest.mark.parametrize("bad", ["stale", "future", "missing_date", "invalid_date",
                                 "out_of_window", "header", "no_data", "date_error", "connection"])
def test_unproven_payload_never_starts_a_write_transaction(official, capsys, bad):
    route, _ = official
    bodies = {
        "stale": b"\r\n".join(r for r in FUT_OK.split(b"\r\n") if not r.startswith(b"2026/10/20")),
        "future": FUT_OK.replace(b"2026/10/20", b"2026/10/21"),
        "missing_date": FUT_OK.replace(b"2026/10/20", b""),
        "invalid_date": FUT_OK.replace(b"2026/10/20", b"2026/99/99"),
        "out_of_window": FUT_OK.replace(b"2026/10/13", b"1900/01/01"),
        "header": FUT_OK.replace("多空未平倉口數淨額".encode("cp950"), b"changed"),
        "no_data": (FIXTURES / "taifex_fut_nodata.bin").read_bytes(),
        "date_error": (FIXTURES / "taifex_fut_dateerror.bin").read_bytes(),
        "connection": requests.ConnectionError("fixture"),
    }
    route["body"] = bodies[bad]
    assert taifex.daily_update(object(), asof=SESSION) == 0
    assert f"**WARN {TABLE}:" in capsys.readouterr().out


@pytest.mark.parametrize("flag", [None, "false", "", "0", "typo"])
def test_disabled_does_not_fetch_or_open_a_transaction(monkeypatch, flag, official):
    _, calls = official
    if flag is None:
        monkeypatch.delenv("TAIFEX_OI_ACCUMULATE_ENABLED")
    else:
        monkeypatch.setenv("TAIFEX_OI_ACCUMULATE_ENABLED", flag)
    assert taifex.daily_update(object(), asof=SESSION) == 0
    assert calls == []


def test_no_calendar_skips_without_fetching(monkeypatch, official, capsys):
    _, calls = official
    monkeypatch.setattr(health, "_xtai_session_checker", lambda: None)
    assert taifex.daily_update(object(), asof=SESSION) == 0
    assert calls == []
    assert "交易日曆不可用" in capsys.readouterr().out


def test_default_uses_expected_session(monkeypatch, official, oi_schema):
    # 未提供 asof 時要沿用 expected_session 的盤前／盤後判斷。
    seen = []

    def expected(now=None, is_session=None):
        seen.append(now)
        return SESSION

    monkeypatch.setattr(health, "expected_session", expected)
    assert taifex.daily_update(oi_schema[0]) == 6
    assert seen == [None]
    assert official[1][0]["queryEndDate"] == "2026/10/20"


def test_asof_weekend_uses_previous_session(official, oi_schema):
    route, calls = official
    route["body"] = FUT_OK.replace(b"2026/10/20", b"2026/10/23")
    assert taifex.daily_update(oi_schema[0], asof=dt.date(2026, 10, 24)) == 6
    assert calls[0]["queryEndDate"] == "2026/10/23"
    assert stored(oi_schema[1])[-1] == (dt.date(2026, 10, 23), -89748)


def test_failed_commit_rolls_back_and_never_reports_success(official, oi_schema, capsys):
    engine, conn = oi_schema

    class FailCommit:
        @contextmanager
        def begin(self):
            with engine.begin() as tx:
                yield tx
                raise RuntimeError("fixture commit failed")

    with pytest.raises(RuntimeError, match="fixture commit failed"):
        taifex.daily_update(FailCommit(), asof=SESSION)
    assert stored(conn) == []
    assert f"{TABLE} 6 rows" not in capsys.readouterr().out


def test_migration_schema_matches_model(oi_schema):
    _, conn = oi_schema
    model = models.TaifexForeignFuturesOi.__table__
    columns = sa.inspect(conn).get_columns(TABLE, schema="market")
    assert model.schema == "market" and model.name == TABLE
    assert [c.name for c in model.primary_key] == ["date"]
    assert {c["name"] for c in columns} == {c.name for c in model.columns} == {"date", "foreign_fut_oi"}
    assert all(not c["nullable"] for c in columns)
    assert isinstance(model.c.foreign_fut_oi.type, sa.BigInteger)
    assert isinstance(next(c["type"] for c in columns if c["name"] == "foreign_fut_oi"), sa.BigInteger)
    assert sa.inspect(conn).get_pk_constraint(TABLE, schema="market")["constrained_columns"] == ["date"]


def test_nonempty_downgrade_refuses_before_any_ddl(oi_schema):
    _, conn = oi_schema
    conn.execute(sa.insert(models.TaifexForeignFuturesOi).values(date=dt.date(1900, 1, 1), foreign_fut_oi=-1))
    before = conn.exec_driver_sql("SELECT type, name, sql FROM market.sqlite_master ORDER BY name").all()
    with pytest.raises(RuntimeError, match="拒絕降版"):
        migration.downgrade()
    assert stored(conn) == [(dt.date(1900, 1, 1), -1)]
    assert conn.exec_driver_sql("SELECT type, name, sql FROM market.sqlite_master ORDER BY name").all() == before


def test_empty_downgrade_succeeds_and_ignores_other_schemas(oi_schema):
    _, conn = oi_schema
    conn.exec_driver_sql(f"CREATE TABLE main.{TABLE} (value INTEGER)")
    conn.exec_driver_sql(f"INSERT INTO main.{TABLE} VALUES (1)")
    migration.downgrade()
    assert conn.exec_driver_sql("SELECT name FROM market.sqlite_master").all() == []
    assert conn.exec_driver_sql(f"SELECT value FROM main.{TABLE}").scalar_one() == 1
