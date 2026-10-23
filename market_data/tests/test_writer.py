from datetime import date

import pandas as pd
import pytest
from sqlalchemy import text

from market_data.models import Margin, Price
from market_data.writer import upsert


def test_upsert_inserts_then_updates_same_key(pg_conn):
    rows = [{"stock_id": "TESTX", "date": date(2024, 1, 2), "close": 100}]
    n = upsert(pg_conn, Price.__table__, rows, ["stock_id", "date"])
    assert n == 1
    got = pg_conn.execute(
        text("SELECT close FROM market.price WHERE stock_id='TESTX'")
    ).scalar()
    assert float(got) == 100.0

    # same PK, new value -> update in place (no duplicate row)
    upsert(pg_conn, Price.__table__,
           [{"stock_id": "TESTX", "date": date(2024, 1, 2), "close": 200}],
           ["stock_id", "date"])
    rows_now = pg_conn.execute(
        text("SELECT close FROM market.price WHERE stock_id='TESTX'")
    ).fetchall()
    assert len(rows_now) == 1
    assert float(rows_now[0][0]) == 200.0


def test_upsert_empty_is_noop(pg_conn):
    assert upsert(pg_conn, Price.__table__, [], ["stock_id", "date"]) == 0


# --- 上市／上櫃共表的撞號防護（PK 不含 market）--------------------------------------
# 實例：TPEx 融資 2016-09-26 把 ETF 006201 吐成 '6201'，整列蓋掉同日上市亞弘電並改標 tpex。
# 種子用 1900 年：本機 pg_conn 連正式庫（rollback 交易），遠離真實資料。

_MD = date(1900, 1, 3)
_MPK = ["stock_id", "date"]


def _margin(conn, sid="6201"):
    return conn.execute(text(
        "SELECT margin_balance, market FROM market.margin WHERE stock_id = :s AND date = :d"),
        {"s": sid, "d": _MD}).fetchone()


def test_upsert_market_guard_keeps_row_owned_by_other_market(pg_conn, capsys):
    upsert(pg_conn, Margin.__table__, [{"stock_id": "6201", "date": _MD, "margin_balance": 1022}],
           _MPK, market_guard=True)
    n = upsert(pg_conn, Margin.__table__,
               [{"stock_id": "6201", "date": pd.Timestamp(_MD), "margin_balance": 14, "market": "tpex"},
                {"stock_id": "6488", "date": pd.Timestamp(_MD), "margin_balance": 7, "market": "tpex"}],
               _MPK, market_guard=True)
    assert tuple(_margin(pg_conn)) == (1022, None), "上市列被上櫃撞號蓋掉"
    assert tuple(_margin(pg_conn, "6488")) == (7, "tpex"), "沒撞號的列照常寫入"
    assert n == 1, "回傳值要扣掉被擋下的列"
    out = capsys.readouterr().out
    assert "**WARN margin: 1 rows skipped" in out and "6201/1900-01-03(tpex)" in out, out


def test_upsert_market_guard_blocks_listed_overwriting_otc_too(pg_conn, capsys):
    upsert(pg_conn, Margin.__table__,
           [{"stock_id": "6201", "date": _MD, "margin_balance": 14, "market": "tpex"}],
           _MPK, market_guard=True)
    assert upsert(pg_conn, Margin.__table__,
                  [{"stock_id": "6201", "date": _MD, "margin_balance": 1022}],
                  _MPK, market_guard=True) == 0
    assert tuple(_margin(pg_conn)) == (14, "tpex")
    assert "6201/1900-01-03(twse)" in capsys.readouterr().out


@pytest.mark.parametrize("market", [None, "tpex"])
def test_upsert_market_guard_still_updates_same_market(pg_conn, capsys, market):
    """反向：同市場重爬（上市 NULL→NULL 也算同市場）照常更新，不印 WARN。"""
    row = {"stock_id": "6201", "date": _MD, "margin_balance": 1, "market": market}
    upsert(pg_conn, Margin.__table__, [row], _MPK, market_guard=True)
    n = upsert(pg_conn, Margin.__table__,
               [{**row, "date": pd.Timestamp(_MD), "margin_balance": 2}], _MPK, market_guard=True)
    assert n == 1
    assert tuple(_margin(pg_conn)) == (2, market)
    assert "**WARN" not in capsys.readouterr().out


def test_upsert_without_market_guard_lets_market_change(pg_conn):
    """stock_info 這類 market 會隨轉市場改變的表不開防護：預設行為維持整列覆蓋。"""
    upsert(pg_conn, Margin.__table__, [{"stock_id": "6201", "date": _MD, "margin_balance": 1}], _MPK)
    upsert(pg_conn, Margin.__table__,
           [{"stock_id": "6201", "date": _MD, "margin_balance": 2, "market": "tpex"}], _MPK)
    assert tuple(_margin(pg_conn)) == (2, "tpex")
