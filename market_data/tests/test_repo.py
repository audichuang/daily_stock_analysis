from market_data import market_repo


def test_price_history_reads_real_migrated_data(engine):
    df = market_repo.price_history("2330", start="2024-01-02", end="2024-01-05",
                                   engine=engine)
    assert not df.empty
    assert list(df["date"].astype(str))[0] == "2024-01-02"
    # 2330 2024-01-02 close was 593 (verified during migration)
    assert float(df.iloc[0]["close"]) == 593.0
    assert {"open", "high", "low", "close", "volume"} <= set(df.columns)


def test_price_history_unknown_stock_is_empty(engine):
    df = market_repo.price_history("ZZZZZ", engine=engine)
    assert df.empty


def test_stock_info_returns_single_record(engine):
    info = market_repo.stock_info("1101", engine=engine)
    assert info is not None
    assert info["name"] == "台泥"


def test_monthly_revenue_history_nonempty_for_known_stock(engine):
    df = market_repo.monthly_revenue("2330", engine=engine)
    assert not df.empty
    assert {"revenue_month", "revenue"} <= set(df.columns)


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
