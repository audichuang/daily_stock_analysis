import pandas as pd

from market_data import etl


def test_transform_price_renames_to_english():
    df = pd.DataFrame([{
        "stock_id": "2330", "date": "2024-01-02",
        "開盤價": 585.0, "最高價": 593.0, "最低價": 589.0, "收盤價": 590.0,
        "漲跌價差": 5.0, "成交股數": 27997826, "成交金額": 16549619798,
        "成交筆數": 20667, "本益比": 17.17, "名稱": "台積電",
    }])
    out = etl.transform_price(df)
    r = out.iloc[0]
    assert r["close"] == 590.0 and r["open"] == 585.0
    assert r["volume"] == 27997826 and r["transactions"] == 20667
    assert set(out.columns) >= {"stock_id", "date", "open", "high", "low",
                                "close", "change", "volume", "turnover",
                                "transactions", "pe_ratio", "market"}


def test_transform_institutional_coalesces_foreign_net():
    # new format: 外陸資買賣超(不含外資自營商) present -> preferred
    new = pd.DataFrame([{"stock_id": "2330", "date": "2024-06-03",
                         "外陸資買賣超股數(不含外資自營商)": 100, "外資買賣超股數": None,
                         "投信買賣超股數": 5, "自營商買賣超股數": 3,
                         "三大法人買賣超股數": 108}])
    assert etl.transform_institutional(new).iloc[0]["foreign_net"] == 100
    # old format: only 外資買賣超股數 -> fallback
    old = pd.DataFrame([{"stock_id": "1101", "date": "2013-01-02",
                         "外資買賣超股數": 42, "投信買賣超股數": 1,
                         "自營商買賣超股數": 0, "三大法人買賣超股數": 43}])
    assert etl.transform_institutional(old).iloc[0]["foreign_net"] == 42


def test_transform_monthly_revenue_derives_revenue_month_and_announce():
    df = pd.DataFrame([{"stock_id": "2330", "date": "2024-02-10",
                        "當月營收": 2000000, "去年同月增減(%)": 12.3,
                        "上月比較增減(%)": -1.1}])
    r = etl.transform_monthly_revenue(df).iloc[0]
    assert str(r["revenue_month"])[:10] == "2024-01-01"   # 營收所屬月
    assert str(r["announce_date"])[:10] == "2024-02-10"   # 公告日
    assert r["revenue"] == 2000000 and r["yoy"] == 12.3


def test_melt_financial_wide_to_long_drops_nulls():
    df = pd.DataFrame([{"stock_id": "2330", "date": "2024-05-15",
                        "營業收入合計": 100.0, "營業成本合計": None, "資產總計": 500.0}])
    out = etl.melt_financial(df, "balance_sheet")
    assert set(out.columns) == {"stock_id", "date", "statement_type", "account", "value"}
    accounts = set(out["account"])
    assert "營業收入合計" in accounts and "資產總計" in accounts
    assert "營業成本合計" not in accounts          # null 值被丟棄
    assert (out["statement_type"] == "balance_sheet").all()


def test_transform_stock_info_parses_listed_date():
    df = pd.DataFrame([{"stock_id": "1101", "公司簡稱": "台泥", "產業別": "01",
                        "上市日期": "19940905", "普通股每股面額": "10.0000",
                        "實收資本額": "70000000000",
                        "已發行普通股數或TDR原股發行股數": "7000000000"}])
    r = etl.transform_stock_info(df).iloc[0]
    assert r["name"] == "台泥" and r["industry"] == "01"
    assert str(r["listed_date"])[:10] == "1994-09-05"
    assert r["shares_outstanding"] == 7000000000
