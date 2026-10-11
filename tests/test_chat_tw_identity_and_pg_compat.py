"""fork 增量：问股对象辨识覆盖台股代码；严格回测条件可在 Postgres 方言编译。"""

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite

from src.agent.chat_object_decision import validate_chat_identity
from src.agent.stock_scope import extract_stock_code_spans
from src.repositories.backtest_repo import BacktestRepository
from src.services.stock_list_parser import default_index_registry


@pytest.mark.parametrize(
    "message, token, canonical",
    [
        ("分析 2330.TW", "2330.TW", "2330.TW"),
        ("看看 6488.TWO 走势", "6488.TWO", "6488.TWO"),
        ("00631L.TW 怎么样", "00631L.TW", "00631L.TW"),
        ("2887A.tw 能买吗", "2887A.tw", "2887A.TW"),
    ],
)
def test_tw_codes_are_whole_token_mentions(message, token, canonical):
    spans = extract_stock_code_spans(message)
    assert [raw for _start, _end, raw in spans] == [token]
    identity = validate_chat_identity(token, default_index_registry(), {"codes": {}, "names": {}})
    assert identity.canonical_id == canonical


@pytest.mark.parametrize("message", ["2330.TWX", "x2330.TW", "2330.TW.", "1234AB.TW"])
def test_tw_pattern_keeps_token_boundaries(message):
    assert extract_stock_code_spans(message) == []


def test_strict_backtest_condition_compiles_for_postgres():
    condition = BacktestRepository._strict_result_code_condition(("600519", "sh600519"))
    pg_sql = str(select(condition).compile(dialect=postgresql.dialect()))
    assert "json_extract" not in pg_sql and "json_valid" not in pg_sql
    assert "pg_input_is_valid" in pg_sql
    sqlite_sql = str(select(condition).compile(dialect=sqlite.dialect()))
    assert "json_extract" in sqlite_sql and "json_valid" in sqlite_sql
