from sqlalchemy import text

from market_data import market_repo

# 自種資料(隨 pg_conn rollback 清除),不依賴庫內既有資料——CI 的 ephemeral
# Postgres 是空庫。market_repo 的 engine 參數收 Connection 即可同交易讀到種子。


def test_price_history_reads_seeded_rows(pg_conn):
    pg_conn.execute(text(
        "INSERT INTO market.price (stock_id, date, open, high, low, close, volume) "
        "VALUES ('2330', '1900-04-02', 585, 593, 585, 593, 100), "
        "       ('2330', '1900-04-03', 593, 595, 590, 594, 200)"))
    df = market_repo.price_history("2330", start="1900-04-02", end="1900-04-05",
                                   engine=pg_conn)
    assert list(df["date"].astype(str)) == ["1900-04-02", "1900-04-03"]
    assert float(df.iloc[0]["close"]) == 593.0
    assert {"open", "high", "low", "close", "volume"} <= set(df.columns)


def test_price_history_unknown_stock_is_empty(pg_conn):
    df = market_repo.price_history("ZZZZZ", engine=pg_conn)
    assert df.empty


def test_stock_info_returns_single_record(pg_conn):
    # 用不存在的代碼:本地跑在真實 DB(1101 等已存在),CI 跑在空庫,都要能過
    pg_conn.execute(text(
        "INSERT INTO market.stock_info (stock_id, name) VALUES ('ZZ01', '測試泥')"))
    info = market_repo.stock_info("ZZ01", engine=pg_conn)
    assert info is not None
    assert info["name"] == "測試泥"


def test_to_daily_frame_maps_to_dashboard_columns():
    import pandas as pd

    df = pd.DataFrame([{"date": "2024-01-02", "open": 585.0, "high": 593.0,
                        "low": 589.0, "close": 590.0, "change": 5.0,
                        "volume": 100, "turnover": 5000}])
    out = market_repo.to_daily_frame(df)
    assert set(out.columns) == {"date", "open", "high", "low", "close",
                                "volume", "amount", "pct_chg"}
    assert out.iloc[0]["amount"] == 5000
    # pct_chg from 漲跌價差: change / prev_close * 100, prev = 590 - 5 = 585
    assert round(float(out.iloc[0]["pct_chg"]), 4) == round(5.0 / 585.0 * 100, 4)


def test_to_daily_frame_empty_stays_empty():
    import pandas as pd

    assert market_repo.to_daily_frame(pd.DataFrame()).empty


def test_institutional_reader_returns_ordered_net_columns(pg_conn):
    pg_conn.execute(text(
        "INSERT INTO market.institutional "
        "(stock_id, date, foreign_net, trust_net, dealer_net, total_net) VALUES "
        "('2330', '1900-04-03', 200, 10, -5, 205), "
        "('2330', '1900-04-02', 100, 0, 0, 100)"))
    df = market_repo.institutional("2330", start="1900-04-01", end="1900-04-05",
                                   engine=pg_conn)
    assert list(df.columns) == ["date", "foreign_net", "trust_net", "dealer_net", "total_net"]
    assert list(df["date"].astype(str)) == ["1900-04-02", "1900-04-03"]  # ORDER BY date
    assert int(df.iloc[0]["foreign_net"]) == 100


def test_institutional_unknown_stock_is_empty(pg_conn):
    assert market_repo.institutional("ZZZZZ", engine=pg_conn).empty
