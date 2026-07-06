from market_data import models
from market_data.db import MARKET_SCHEMA


def test_price_table_is_in_market_schema_with_composite_pk():
    t = models.Price.__table__
    assert t.name == "price"
    assert t.schema == MARKET_SCHEMA
    assert [c.name for c in t.primary_key.columns] == ["stock_id", "date"]
    # core OHLCV columns present with English names
    for col in ("open", "high", "low", "close", "volume", "turnover", "market"):
        assert col in t.columns


def test_stock_info_keyed_by_stock_id_only():
    t = models.StockInfo.__table__
    assert t.name == "stock_info"
    assert t.schema == MARKET_SCHEMA
    assert [c.name for c in t.primary_key.columns] == ["stock_id"]
    for col in ("name", "industry", "listed_date", "shares_outstanding"):
        assert col in t.columns


def test_all_market_tables_have_expected_keys():
    expected = {
        "valuation": ["stock_id", "date"],
        "market_index": ["index_id", "date"],
        "institutional": ["stock_id", "date"],
        "margin": ["stock_id", "date"],
        "ex_dividend": ["stock_id", "date"],
        "monthly_revenue": ["stock_id", "revenue_month"],
        "financial_statement": ["stock_id", "date", "statement_type", "account"],
    }
    tables = models.Base.metadata.tables
    for name, pk in expected.items():
        t = tables[f"{MARKET_SCHEMA}.{name}"]
        assert t.schema == MARKET_SCHEMA
        assert [c.name for c in t.primary_key.columns] == pk


def test_financial_statement_is_long_format_not_wide():
    # long/EAV shape: one row per (account) -> no per-account columns
    cols = {c.name for c in models.FinancialStatement.__table__.columns}
    assert cols == {"stock_id", "date", "statement_type", "account", "value"}
