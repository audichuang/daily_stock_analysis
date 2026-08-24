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

    df = pd.DataFrame([{"date": "2024-01-01", "open": 580.0, "high": 586.0,
                        "low": 578.0, "close": 585.0, "change": 3.0,
                        "volume": 90, "turnover": 4000},
                       {"date": "2024-01-02", "open": 585.0, "high": 593.0,
                        "low": 589.0, "close": 590.0, "change": 5.0,
                        "volume": 100, "turnover": 5000}])
    out = market_repo.to_daily_frame(df)
    assert set(out.columns) == {"date", "open", "high", "low", "close",
                                "volume", "amount", "pct_chg"}
    assert out.iloc[1]["amount"] == 5000
    # pct_chg 由 close 自己 shift 得出（`change` 對上市股票無正負號，不可用來回推昨收）
    assert round(float(out.iloc[1]["pct_chg"]), 4) == round((590.0 / 585.0 - 1) * 100, 4)
    # 視窗第一列沒有前一日 ⇒ 缺資料
    assert pd.isna(out.iloc[0]["pct_chg"])


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


def test_adjustment_multipliers_returns_one_unique_factor_per_event_date(pg_conn):
    """每檔每事件日一個因子，且 **index 必須唯一**、**不得跨日累乘**。

    同日多事件（除息 + 減資）不可能出現在這個回傳值裡：`price_adjustment` 的 PK 是
    `(stock_id, date)`，而寫入端 `adjust.merge_adjustment_rows` 用
    `drop_duplicates(keep="first")` 按來源優先序收斂。所以這裡能守的是另外三件事：

    - **只取該檔**：漏掉 `stock_id = :sid` 會把別檔的事件日混進來
    - **不跨日累乘**：寫成 `.cumprod()` 會讓 04-05 變成 0.45×0.9
    - **index 唯一**：`to_daily_frame` 用 `Series.map`，重複 index 直接抛
      `InvalidIndexError`（所以 `.prod()` 不能改成不做 groupby 的 `set_index`）
    """
    import pandas as pd
    import pytest

    pg_conn.execute(text(
        "INSERT INTO market.price_adjustment (stock_id, date, factor, kind, source) "
        "VALUES ('ZZ30', '1900-04-02', 0.45, 'dividend', 'twse_twt49u'), "
        "       ('ZZ30', '1900-04-05', 0.9,  'reduction', 'twse_twtauu'), "
        "       ('ZZ05', '1900-04-03', 0.99, 'dividend', 'tpex_exdailyq')"))
    s = market_repo.adjustment_multipliers("ZZ30", engine=pg_conn)

    assert float(s[pd.Timestamp("1900-04-02")]) == pytest.approx(0.45)
    # 不是 0.45×0.9——每個事件日各自獨立，跨日累乘是 factors_to_panel 的事
    assert float(s[pd.Timestamp("1900-04-05")]) == pytest.approx(0.9)
    assert s.index.is_unique, "重複 index 會讓 to_daily_frame 的 Series.map 抛错"
    # 只回該檔的事件日；別檔的列不會混進來
    assert pd.Timestamp("1900-04-03") not in s.index
    assert len(s) == 2


def test_adjustment_multipliers_unknown_stock_is_empty(pg_conn):
    """查無事件 ⇒ 空 Series，`to_daily_frame` 的 `len(event_factors)` 判 0 走未還原。"""
    s = market_repo.adjustment_multipliers("ZZNONE", engine=pg_conn)
    assert len(s) == 0
