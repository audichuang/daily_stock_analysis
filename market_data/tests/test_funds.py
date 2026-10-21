"""境內基金：公會 CSV 解析、鉅亨歷史日期、寫入優先序。"""

import datetime as dt

import pytest
from sqlalchemy import text

from market_data import funds

NAV_CSV = (
    "﻿日期,會員代號,公司名稱,基金統編,基金代號,基金名稱,基金淨值,漲跌,漲跌幅,類型代號,幣別,受益憑證代號\n"
    "20991020,A0001,測試投信,T0000001,DIE02,測試債券基金,12.8756,0.1575,1.23839,AH22,TWD,00957B\n"
    "20991021,A0036,測試投信,T0000002,DDO04,測試科技基金,783.21,16.62,2.16804,AA1,TWD,T3604Y\n"
    "20991021,A0003,測試投信,T0000003B,DDO29,測試暫停級別,-,-,-,AA1,TWD,T0336A\n"
).encode("utf-8")

INFO_CSV = (
    "﻿年月,公司名稱,基金名稱,統編,基金/級別成立日期,基金規模日期,基金規模幣別,基金級別規模_金額,"
    "基金規模(依基金別)_金額,基金類型別,投資地區,基金配息規定(基金收益分配規定),基金ISIN Code,"
    "保管銀行(國內),保管銀行(國外),基金計價幣別\n"
    "209909,測試投信,測試科技基金,T0000002,20010403,20990930,台幣,325001709959,325001709959,"
    "(AA1) 國內投資股票型,台灣,不分配,TW000T3604Y3,華南,,TWD\n"
).encode("utf-8")


def test_nav_rows_keep_their_own_date_not_fetch_date():
    # 同一份公會檔混有多個淨值日：每列要用自己的日期入庫
    infos, navs = funds.parse_sitca_nav(NAV_CSV)
    by_id = {r["fund_id"]: r for r in navs}
    assert by_id["T0000001"]["date"] == dt.date(2099, 10, 20)
    assert by_id["T0000002"]["date"] == dt.date(2099, 10, 21)
    assert by_id["T0000002"]["nav"] == 783.21
    assert by_id["T0000002"]["source"] == "sitca"


def test_suspended_class_keeps_info_but_no_nav_row():
    infos, navs = funds.parse_sitca_nav(NAV_CSV)
    assert "T0000003B" in {r["fund_id"] for r in infos}
    assert "T0000003B" not in {r["fund_id"] for r in navs}


def test_nav_csv_missing_column_raises():
    broken = NAV_CSV.replace("基金淨值".encode(), "淨值".encode())
    with pytest.raises(funds.FundSourceError):
        funds.parse_sitca_nav(broken)


def test_info_splits_type_code_and_isin():
    (row,) = funds.parse_sitca_info(INFO_CSV)
    assert row["type_code"] == "AA1"
    assert row["type_name"] == "國內投資股票型"
    assert row["isin"] == "TW000T3604Y3"
    assert row["inception_date"] == dt.date(2001, 4, 3)
    assert row["aum"] == 325001709959


def test_long_strings_are_truncated_to_column_length():
    long = "很" * 300
    assert len(funds._fit(long, "invest_area")) == 128


def test_cnyes_trade_date_is_taipei_day():
    # 1792512000 = 台北 2026-10-21 00:00（UTC 10-20 16:00），與公會 20261021 為同一筆淨值
    rows = funds.parse_cnyes_chart("X", {"tradeDate": [1792512000], "nav": [783.21],
                                         "change": [16.62], "changePercent": [2.16804]})
    assert rows[0]["date"] == dt.date(2026, 10, 21)
    assert rows[0]["source"] == "cnyes"


def test_cnyes_mismatched_series_raises():
    with pytest.raises(funds.FundSourceError):
        funds.parse_cnyes_chart("X", {"tradeDate": [1, 2], "nav": [1.0]})


def test_resolve_cnyes_id_requires_exact_isin(monkeypatch):
    payload = {"data": {"quoteFunds": [
        {"cnyesId": "WRONG", "isin": "<mark>TW</mark>000T1134Y3"},
        {"cnyesId": "A36004", "isin": "<mark>TW000T3604Y3</mark>"},
    ]}}
    monkeypatch.setattr(funds, "_cnyes_json", lambda *a, **k: payload)
    assert funds.resolve_cnyes_id("TW000T3604Y3") == "A36004"
    assert funds.resolve_cnyes_id("TW000T9999Y9") is None


def _nav(conn, fund_id, day):
    return conn.execute(text("SELECT nav, source FROM market.fund_nav WHERE fund_id = :f AND date = :d"),
                        {"f": fund_id, "d": day}).fetchone()


def test_cnyes_history_never_overwrites_official_nav(pg_conn):
    infos, navs = funds.parse_sitca_nav(NAV_CSV)
    funds.store_sitca(pg_conn, infos, funds.parse_sitca_info(INFO_CSV), navs)
    day = dt.date(2099, 10, 21)
    ts = int(dt.datetime(2099, 10, 21, tzinfo=funds.TAIPEI).timestamp())
    prev = int(dt.datetime(2099, 10, 19, tzinfo=funds.TAIPEI).timestamp())
    added = funds.store_history(pg_conn, funds.parse_cnyes_chart(
        "T0000002", {"tradeDate": [ts, prev], "nav": [1.0, 700.0]}))
    assert added == 1                                   # 只補了 10/19
    assert float(_nav(pg_conn, "T0000002", day)[0]) == 783.21
    assert _nav(pg_conn, "T0000002", day)[1] == "sitca"
    assert _nav(pg_conn, "T0000002", dt.date(2099, 10, 19))[1] == "cnyes"


def test_official_nav_replaces_earlier_cnyes_row(pg_conn):
    ts = int(dt.datetime(2099, 10, 21, tzinfo=funds.TAIPEI).timestamp())
    infos, navs = funds.parse_sitca_nav(NAV_CSV)
    funds.store_sitca(pg_conn, infos, [], [])
    funds.store_history(pg_conn, funds.parse_cnyes_chart("T0000002", {"tradeDate": [ts], "nav": [1.0]}))
    funds.store_sitca(pg_conn, infos, [], navs)
    nav, source = _nav(pg_conn, "T0000002", dt.date(2099, 10, 21))
    assert (float(nav), source) == (783.21, "sitca")


def test_info_from_nav_file_does_not_erase_detail_columns(pg_conn):
    infos, navs = funds.parse_sitca_nav(NAV_CSV)
    funds.store_sitca(pg_conn, infos, funds.parse_sitca_info(INFO_CSV), navs)
    funds.store_sitca(pg_conn, infos, [], navs)       # 只有淨值檔的一輪
    isin = pg_conn.execute(text("SELECT isin FROM market.fund_info WHERE fund_id = 'T0000002'")).scalar()
    assert isin == "TW000T3604Y3"
