"""期交所 TXF 未平倉入庫：官方 fixture → 共用解析 → 真實 Alembic migration 與 writer；只用記憶體 SQLite。

`market_data/tests/test_taifex.py` 攔掉 `taifex.store`、upsert 只在有 market Postgres 時跑；
這裡補離線也能跑的真寫入：冪等 upsert、官方修正覆蓋、commit 失敗不報成功、migration 欄位與降版護欄。
"""

import datetime as dt
from contextlib import contextmanager
from importlib import import_module
from pathlib import Path

import pytest
import requests
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from market_data import models, taifex
from market_data import tw_official_http as http

FIXTURES = Path(__file__).parent / "fixtures"
FUT_OK = (FIXTURES / "taifex_fut_txf_20261013_20261020.bin").read_bytes()
SESSION = dt.date(2026, 10, 20)
TPE = dt.timezone(dt.timedelta(hours=8))
EVENING = dt.datetime(2026, 10, 20, 20, 0, tzinfo=TPE)
TABLE = "taifex_fut_oi"
migration = import_module("market_data.migrations.versions.e4f7a2c9b1d3_add_taifex_fut_oi")
# taifex_fut_oi 之後的 migration 鏈：f2a7（建 rate_expectations／event_calendar，b8d2 要改它）→ a6c1 → b8d2（head，
# 加 first_seen_at／captured_at）。中間的 e8f6（market_index 加欄）與本表無關、SQLite 也沒有該表，不跑。
_CHAIN = [import_module(f"market_data.migrations.versions.{name}") for name in (
    "f2a7c4d8e913_add_macro_rates_events", "a6c1e3f5b7d9_add_event_release_fields",
    "b8d2f4a6c0e1_add_snapshot_tables")]
head = _CHAIN[-1]


class _OutboundBlocked(BaseException):
    """守門例外不能被生產碼的來源降級吞掉。"""


def _is_session(day):
    return day.weekday() < 5 and day not in {dt.date(2026, 10, 9), dt.date(2026, 10, 10)}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def blocked(*args, **kwargs):
        raise _OutboundBlocked("測試不得連外或取得正式 DB engine")

    monkeypatch.setattr("socket.socket.connect", blocked)
    monkeypatch.setattr("market_data.db.get_engine", blocked)


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
    # 執行真實 Alembic upgrade，完全不讀 DATABASE_URL；同基金 migration 的測試接縫。
    engine = sa.create_engine("sqlite://")
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS market")
            with Operations.context(MigrationContext.configure(conn)):
                migration.upgrade()
                for step in _CHAIN:
                    step.upgrade()
                conn.commit()
                yield engine, conn
    finally:
        engine.dispose()


def _update(engine, out=None, now=EVENING):
    return taifex.update(engine, asof=SESSION, now=now, is_session=_is_session,
                         out=out if out is not None else (lambda line: None))


def stored(conn):
    t = models.TaifexFutOI.__table__
    return conn.execute(sa.select(t.c.date, t.c.identity, t.c.net_oi).order_by(t.c.date, t.c.identity)).all()


def test_real_upsert_is_idempotent_and_takes_official_corrections(oi_schema, official):
    engine, conn = oi_schema
    route, calls = official
    lines = []
    assert _update(engine, lines.append) == 18
    first = stored(conn)
    assert len(first) == 18 and (SESSION, "foreign", -89748) in first
    conn.commit()
    # 同場次重跑要吃進官方修正，不能凍結初值，也不能累加成重複列。
    route["body"] = FUT_OK.replace(b"-89748", b"-88748")
    assert _update(engine, lines.append) == 18
    second = stored(conn)
    assert len(second) == 18
    assert (SESSION, "foreign", -88748) in second and (SESSION, "foreign", -89748) not in second
    assert calls == [{"queryStartDate": "2026/10/06", "queryEndDate": "2026/10/20",
                      "commodityId": "TXF"}] * 2
    assert sum(f"{TABLE} 18 rows, latest {SESSION}" in line for line in lines) == 2


@pytest.mark.parametrize("bad", ["future", "missing_date", "invalid_date", "out_of_window",
                                 "header", "no_data", "date_error", "connection"])
def test_unproven_payload_never_starts_a_write_transaction(official, bad):
    route, _ = official
    bodies = {
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
    lines = []
    # object() 沒有 begin()：只要嘗試開交易就會 AttributeError，證明拒收發生在寫入之前。
    assert _update(object(), lines.append) == 0
    assert any(line.startswith(f"**WARN {TABLE}") for line in lines)


def test_failed_commit_rolls_back_and_never_reports_success(official, oi_schema):
    engine, conn = oi_schema

    class FailCommit:
        @contextmanager
        def begin(self):
            with engine.begin() as tx:
                yield tx
                raise RuntimeError("fixture commit failed")

    lines = []
    with pytest.raises(RuntimeError, match="fixture commit failed"):
        _update(FailCommit(), lines.append)
    assert stored(conn) == []
    assert not any(f"{TABLE} 18 rows" in line for line in lines)


def test_migration_schema_matches_model(oi_schema):
    _, conn = oi_schema
    model = models.TaifexFutOI.__table__
    inspector = sa.inspect(conn)
    columns = inspector.get_columns(TABLE, schema="market")
    assert model.schema == "market" and model.name == TABLE
    assert {c["name"] for c in columns} == {c.name for c in model.columns}
    assert {"first_seen_at", "captured_at"} <= {c.name for c in model.columns}
    assert [c.name for c in model.primary_key] == ["date", "commodity_id", "identity"]
    assert inspector.get_pk_constraint(TABLE, schema="market")["constrained_columns"] == \
        ["date", "commodity_id", "identity"]
    nullable = {c["name"]: c["nullable"] for c in columns}
    assert all(nullable[c.name] == c.nullable for c in model.columns)


def _unwind_newer_migrations():
    """把 e4f7 之後的 migration 依序降回去（表是空的就會過），好單獨驗 e4f7 自己的降版護欄。"""
    for step in reversed(_CHAIN):
        step.downgrade()


def test_nonempty_downgrade_refuses_before_any_ddl(oi_schema):
    _, conn = oi_schema
    conn.execute(sa.insert(models.TaifexFutOI).values(
        date=dt.date(1900, 1, 1), commodity_id="TXF", identity="foreign", net_oi=-1))
    _unwind_newer_migrations()       # 新兩欄都是 NULL，b8d2 的降版護欄放行
    before = conn.exec_driver_sql("SELECT type, name, sql FROM market.sqlite_master ORDER BY name").all()
    with pytest.raises(RuntimeError, match="拒絕降版"):
        migration.downgrade()
    assert stored(conn) == [(dt.date(1900, 1, 1), "foreign", -1)]
    assert conn.exec_driver_sql("SELECT type, name, sql FROM market.sqlite_master ORDER BY name").all() == before


def test_empty_downgrade_succeeds_and_ignores_other_schemas(oi_schema):
    _, conn = oi_schema
    conn.exec_driver_sql(f"CREATE TABLE main.{TABLE} (value INTEGER)")
    conn.exec_driver_sql(f"INSERT INTO main.{TABLE} VALUES (1)")
    _unwind_newer_migrations()
    migration.downgrade()
    assert conn.exec_driver_sql("SELECT name FROM market.sqlite_master").all() == []
    assert conn.exec_driver_sql(f"SELECT value FROM main.{TABLE}").scalar_one() == 1


def _row(day, net):
    return {"date": day, "commodity_id": "TXF", "identity": "foreign", "long_oi": 1, "short_oi": 2,
            "net_oi": net, "long_oi_amount": 3, "short_oi_amount": 4, "net_oi_amount": 5}


def _stamps(conn):
    t = models.TaifexFutOI.__table__
    return conn.execute(sa.select(t.c.net_oi, t.c.first_seen_at, t.c.captured_at)).one()


def test_rerun_keeps_first_seen_at_and_moves_captured_at(oi_schema):
    _, conn = oi_schema
    first, second = dt.datetime(2026, 10, 20, 10, 0), dt.datetime(2026, 10, 21, 10, 0)   # SQLite 讀回 naive
    taifex.store(conn, [_row(SESSION, -1)], now=first.replace(tzinfo=dt.timezone.utc))
    assert _stamps(conn) == (-1, first, first)
    # 期交所事後更正數值：first_seen_at 保留第一次、captured_at 換成最後一次抓取
    taifex.store(conn, [_row(SESSION, -2)], now=second.replace(tzinfo=dt.timezone.utc))
    assert _stamps(conn) == (-2, first, second)


def test_rerun_fills_a_null_first_seen_at_once(oi_schema):
    """舊程式寫的列（欄位剛加、first_seen_at 為 NULL）第一次被新程式重抓時補上，之後不再動。"""
    _, conn = oi_schema
    conn.exec_driver_sql(
        "INSERT INTO market.taifex_fut_oi (date, commodity_id, identity, net_oi) VALUES ('2026-10-20', 'TXF', 'foreign', 0)")
    t1, t2 = dt.datetime(2026, 10, 21, 1, 0), dt.datetime(2026, 10, 22, 1, 0)
    taifex.store(conn, [_row(SESSION, -1)], now=t1.replace(tzinfo=dt.timezone.utc))
    taifex.store(conn, [_row(SESSION, -2)], now=t2.replace(tzinfo=dt.timezone.utc))
    assert _stamps(conn) == (-2, t1, t2)


def test_update_stamps_rows_with_real_clock(oi_schema, official):
    engine, conn = oi_schema
    assert _update(engine) == 18
    stamps = conn.execute(sa.select(models.TaifexFutOI.__table__.c.first_seen_at,
                                    models.TaifexFutOI.__table__.c.captured_at)).all()
    assert len(stamps) == 18 and all(a is not None and a == b for a, b in stamps)


def test_downgrade_refuses_when_stamped_rows_exist_before_any_ddl(oi_schema):
    _, conn = oi_schema
    taifex.store(conn, [_row(SESSION, -1)])
    before = conn.exec_driver_sql("SELECT type, name, sql FROM market.sqlite_master ORDER BY name").all()
    with pytest.raises(RuntimeError, match="拒絕降版.*first_seen_at"):
        head.downgrade()
    assert conn.exec_driver_sql("SELECT type, name, sql FROM market.sqlite_master ORDER BY name").all() == before
