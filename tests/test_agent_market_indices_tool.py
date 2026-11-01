"""台股大盤問題要能走 get_market_indices(region='tw')，不必拿指數代號去呼叫受股票範圍限制的工具。"""
from unittest.mock import MagicMock, patch

from src.agent.tools import market_tools
from src.agent.tools.market_tools import get_market_indices_tool


def test_region_enum_offers_taiwan():
    region = next(p for p in get_market_indices_tool.parameters if p.name == "region")
    assert "tw" in region.enum


def test_taiwan_region_reaches_data_layer():
    manager = MagicMock()
    manager.get_main_indices.return_value = [{"code": "^TWII", "name": "台灣加權指數", "current": 45211.83}]
    with patch.object(market_tools, "_get_fetcher_manager", return_value=manager):
        result = get_market_indices_tool.handler(region="tw")
    manager.get_main_indices.assert_called_once_with(region="tw")
    assert result["region"] == "tw"
    assert result["indices_count"] == 1
