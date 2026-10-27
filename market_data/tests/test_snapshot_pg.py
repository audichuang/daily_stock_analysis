"""snapshot migration 與讀取端的 Postgres 行為（SQLite 驗不了的主鍵變更、真 SQL）。

種子用 2099 年、走 rolled-back 的 ``pg_conn``。DDL 測試（降版／重新升版）只在 ``make pg-scratch`` 的
暫存庫跑——它們在 rolled-back 交易裡改表結構，不該對著正式庫做，連 URL 不是 scratch 就 skip。
"""

import datetime
import os
import sys
from importlib import import_module
from pathlib import Path

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import text

from market_data import macro

head = import_module("market_data.migrations.versions.b8d2f4a6c0e1_add_snapshot_tables")
D = datetime.date
NOW = datetime.datetime(2099, 1, 1, tzinfo=datetime.timezone.utc)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import macro_brief  # noqa: E402

scratch_only = pytest.mark.skipif("scratch@" not in os.environ.get("DATABASE_URL", ""),
                                  reason="DDL 測試只在 make pg-scratch 的暫存庫跑")


def _pk(conn, table):
    return [r[0] for r in conn.execute(text(
        "SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
        "WHERE i.indrelid = CAST(:t AS regclass) AND i.indisprimary "
        "ORDER BY array_position(i.indkey::int2[], a.attnum)"), {"t": f"market.{table}"})]


def test_rate_expectations_primary_key_includes_the_slot(pg_conn):
    assert _pk(pg_conn, "rate_expectations") == ["snapshot_date", "snapshot_slot", "meeting_date", "outcome"]
    assert pg_conn.execute(text(
        "SELECT column_default FROM information_schema.columns WHERE table_schema = 'market' "
        "AND table_name = 'rate_expectations' AND column_name = 'snapshot_slot'")).scalar() is None, \
        "server_default 'legacy' 應該已經拿掉：之後寫入必須明確帶 slot"


def _rate(slot, hike, hold, hour):
    at = datetime.datetime(2099, 1, 12, hour, tzinfo=datetime.timezone.utc)
    return [{"snapshot_date": D(2099, 1, 12), "snapshot_slot": slot, "meeting_date": D(2099, 2, 1),
             "outcome": o, "prob_mid": p, "yes_bid": None, "yes_ask": None, "last_price": None, "volume": None,
             "open_interest": None, "source_updated_at": None, "source": "test", "captured_at": at}
            for o, p in (("hike_25", hike), ("hold", hold))]


def test_print_rates_on_real_sql_does_not_sum_slots(pg_conn):
    macro.store_rates(pg_conn, _rate("premarket", 0.10, 0.88, 0) + _rate("postclose", 0.30, 0.68, 10))
    lines = []
    macro_brief.print_rates(pg_conn, out=lines.append)
    row = next(line for line in lines if line.startswith("2099-02-01"))
    assert "2099-01-12 postclose" in "\n".join(lines)
    assert "     30%" in row and "     68%" in row and "40%" not in row


@scratch_only
def test_downgrade_refuses_non_legacy_rows_then_restores_old_pk_and_upgrade_backfills_legacy(pg_conn):
    pk_new = ["snapshot_date", "snapshot_slot", "meeting_date", "outcome"]
    count = "SELECT count(*) FROM market.rate_expectations"
    pg_conn.execute(text("DELETE FROM market.rate_expectations"))
    with Operations.context(MigrationContext.configure(pg_conn)):
        # 多 slot：拒絕降版、資料原封不動
        macro.store_rates(pg_conn, _rate("premarket", 0.1, 0.9, 0) + _rate("postclose", 0.3, 0.7, 10))
        with pytest.raises(RuntimeError, match="snapshot_slot／captured_at"):
            head.downgrade()
        assert _pk(pg_conn, "rate_expectations") == pk_new
        assert pg_conn.execute(text(count)).scalar_one() == 4

        # 只剩單一非 legacy slot：照樣拒絕（Kalshi 漏抓補不回來）
        pg_conn.execute(text("DELETE FROM market.rate_expectations WHERE snapshot_slot = 'postclose'"))
        with pytest.raises(RuntimeError, match="snapshot_slot／captured_at"):
            head.downgrade()
        assert _pk(pg_conn, "rate_expectations") == pk_new
        assert pg_conn.execute(text(count)).scalar_one() == 2

        # 成功路徑：捨棄多餘 slot 後改成 legacy、清掉 captured_at 才能降版
        pg_conn.execute(text(
            "UPDATE market.rate_expectations SET snapshot_slot = 'legacy', captured_at = NULL"))
        head.downgrade()
        assert _pk(pg_conn, "rate_expectations") == ["snapshot_date", "meeting_date", "outcome"]
        assert pg_conn.execute(text(count)).scalar_one() == 2
        head.upgrade()
        assert _pk(pg_conn, "rate_expectations") == pk_new
        assert pg_conn.execute(text(
            "SELECT DISTINCT snapshot_slot FROM market.rate_expectations")).scalars().all() == ["legacy"]


def test_taifex_store_keeps_first_seen_at_on_postgres(pg_conn):
    from market_data import taifex

    row = {"date": D(2099, 1, 2), "commodity_id": "TXF", "identity": "foreign", "long_oi": 1, "short_oi": 2,
           "net_oi": -1, "long_oi_amount": 3, "short_oi_amount": 4, "net_oi_amount": 5}
    later = NOW + datetime.timedelta(days=1)
    taifex.store(pg_conn, [row], now=NOW)
    taifex.store(pg_conn, [{**row, "net_oi": -2}], now=later)
    assert pg_conn.execute(text(
        "SELECT net_oi, first_seen_at, captured_at FROM market.taifex_fut_oi WHERE date = '2099-01-02'"
    )).all() == [(-2, NOW, later)]
