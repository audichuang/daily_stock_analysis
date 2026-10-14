# -*- coding: utf-8 -*-
"""持仓估值的台股收盘补价：应用库 stock_daily 缺价或较旧时改用 market schema。

stock_daily 只有被分析过的股票才有，持仓页又不拉实时价，没分析过的台股会整列显示缺价。
"""

from datetime import date
from unittest.mock import patch

from src.repositories.portfolio_repo import PortfolioRepository

AS_OF = date(2026, 10, 15)


def _repo():
    return PortfolioRepository.__new__(PortfolioRepository)  # 不连 DB：两个来源都 patch 掉


def _resolve(symbol, app, market):
    with patch.object(PortfolioRepository, "_get_app_latest_close", return_value=app), \
            patch.object(PortfolioRepository, "_get_tw_market_latest_close", return_value=market) as m:
        return _repo().get_latest_close_with_date(symbol, AS_OF), m


def test_tw_symbol_missing_in_app_db_uses_market_close():
    got, _ = _resolve("3380.TW", None, (31.65, date(2026, 10, 14)))
    assert got == (31.65, date(2026, 10, 14))


def test_newer_market_close_beats_stale_app_close():
    got, _ = _resolve("00631L.TW", (40.89, date(2026, 10, 12)), (39.78, date(2026, 10, 14)))
    assert got == (39.78, date(2026, 10, 14))


def test_newer_app_close_beats_older_market_close():
    got, _ = _resolve("2330.TWO", (900.0, date(2026, 10, 15)), (880.0, date(2026, 10, 14)))
    assert got == (900.0, date(2026, 10, 15))


def test_non_tw_symbol_never_queries_market_schema():
    got, market = _resolve("600519", (1500.0, date(2026, 10, 14)), (1.0, date(2026, 10, 15)))
    assert got == (1500.0, date(2026, 10, 14))
    market.assert_not_called()


def test_market_schema_failure_falls_back_to_app_close():
    with patch.object(PortfolioRepository, "_get_app_latest_close", return_value=(142.0, date(2026, 10, 14))), \
            patch("market_data.market_repo.latest_close", side_effect=RuntimeError("DATABASE_URL is not set")), \
            patch("market_data.db.get_engine"):
        assert _repo().get_latest_close_with_date("2303.TW", AS_OF) == (142.0, date(2026, 10, 14))
