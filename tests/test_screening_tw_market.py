# -*- coding: utf-8 -*-
"""選股開放台股與美股：策略門檻、快照欄位、母體來源、漏斗與熱點。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

from api.v1.endpoints import screening as screening_endpoint
from market_data import tw_prescreen
from src.services.screening import snapshot_us
from src.services.screening.models import HardFilterConfig
from src.services.screening.strategy import hard_filter_conditions, list_strategies, load_all_strategies
from src.services.screening_service import ScreeningService, _build_screening_funnel

OPENED = {"momentum_quality", "quality_value", "volume_breakout", "shrink_pullback"}
STRATEGIES_DIR = Path(__file__).resolve().parents[1] / "src" / "services" / "screening" / "strategies"


class _OutboundBlocked(BaseException):
    """繼承 BaseException：生產碼的 `except Exception` 不能吞掉守門。"""


@pytest.fixture(autouse=True)
def _no_outbound_network(monkeypatch):
    import socket as _socket

    real_connect = _socket.socket.connect

    def guard(self, address):
        host = address[0] if isinstance(address, tuple) and address else ""
        if isinstance(host, str) and (
            host.startswith(("127.", "10.", "192.168.", "172.")) or host in ("localhost", "::1")
        ):
            return real_connect(self, address)
        raise _OutboundBlocked(f"離線測試嘗試連外 {address}")

    monkeypatch.setattr(_socket.socket, "connect", guard)


def _strategies():
    return load_all_strategies(STRATEGIES_DIR)


def test_only_first_batch_opens_tw_and_us():
    for name, strategy in _strategies().items():
        scope = set(strategy.screening.market_scope)
        if name in OPENED:
            assert {"cn", "tw", "us"} <= scope, name
        else:
            assert scope == {"cn"}, name


@pytest.mark.parametrize("market", ["tw", "us"])
def test_opened_strategies_have_their_own_thresholds(market):
    """不能只補 scope：人民幣門檻套到台幣、美元沒有意義，exclude_st 對名稱的比對也只適用 A 股。"""
    for name in OPENED:
        screening = _strategies()[name].screening
        filters = screening.hard_filters_for(market)
        assert filters is not screening.hard_filters, name
        assert filters.exclude_st is False, name
        assert filters.amount_min is not None, name


def test_cn_thresholds_are_untouched():
    screening = _strategies()["momentum_quality"].screening
    assert screening.hard_filters_for("cn") is screening.hard_filters
    assert screening.hard_filters.exclude_st is True
    assert screening.hard_filters.amount_min == 200000000
    assert screening.hard_filters.market_cap_min == 8000000000


def test_conditions_use_traditional_labels_and_market_currency():
    filters = HardFilterConfig(exclude_st=False, amount_min=1000.0, require_ma_bullish=True)
    assert hard_filter_conditions(filters, "tw") == [
        {"key": "amount_min", "label": "成交金額下限", "value": 1000.0, "unit": "TWD"},
        {"key": "require_ma_bullish", "label": "均線多頭排列", "value": True, "unit": ""},
    ]
    assert hard_filter_conditions(filters, "us")[0]["unit"] == "USD"


def test_list_strategies_exposes_traditional_name_and_market_conditions():
    info = next(item for item in list_strategies(STRATEGIES_DIR) if item.name == "momentum_quality")
    assert info.display_name_zh_tw == "趨勢品質"
    assert {"cn", "tw", "us"} == set(info.market_conditions)
    tw_amount = next(c for c in info.market_conditions["tw"] if c["key"] == "amount_min")
    assert tw_amount["unit"] == "TWD"


def _service():
    return ScreeningService(config=SimpleNamespace(screening_enabled=True))


def test_strategy_api_filters_by_market():
    with (
        patch("src.services.screening_service._ensure_screening_available_for_use"),
        patch("src.services.screening_service.load_screening_strategies",
              side_effect=lambda: list_strategies(STRATEGIES_DIR)),
    ):
        tw = _service().strategies(market="tw")
        everything = _service().strategies()
    assert {item["id"] for item in tw["strategies"]} == OPENED
    assert all(item["conditions"] for item in tw["strategies"])
    # 反向：不帶 market 時維持舊行為，10 支都回。
    assert len(everything["strategies"]) == 10
    assert "dual_low" in {item["id"] for item in everything["strategies"]}


@pytest.mark.parametrize("market", ["tw", "us"])
def test_hotspots_are_empty_outside_cn_without_touching_the_provider(market):
    with (
        patch("src.services.screening_service._ensure_screening_available_for_use"),
        patch("src.services.screening_service._resolve_hotspot_provider", return_value=("akshare", "akshare")),
        patch("src.services.screening_service.screening_hotspot.discover_hotspots") as discover,
    ):
        payload = _service().hotspots(market=market)
    discover.assert_not_called()
    assert payload["hotspots"] == []


def test_hotspots_still_query_for_cn():
    with (
        patch("src.services.screening_service._ensure_screening_available_for_use"),
        patch("src.services.screening_service._resolve_hotspot_provider", return_value=("akshare", "akshare")),
        patch("src.services.screening_service._load_screening_hotspot_cache", return_value=None),
        patch("src.services.screening_service.screening_hotspot.discover_hotspots",
              side_effect=RuntimeError("called")) as discover,
    ):
        try:
            _service().hotspots(market="cn", refresh=True)
        except Exception:  # noqa: BLE001 - 這裡只驗有沒有查來源，查失敗怎麼回應由既有測試管
            pass
    discover.assert_called_once()


def test_check_endpoint_uses_market_thresholds():
    request = screening_endpoint.ScreeningCheckRequest(
        market="tw", strategy="momentum_quality", snapshot={"amount": 250000000.0, "name": "ST 測試"},
    )
    config = SimpleNamespace(screening_enabled=True)
    with patch.object(
        screening_endpoint.ScreeningRuntimeConfig, "from_env",
        return_value=SimpleNamespace(strategies_dir=STRATEGIES_DIR),
    ):
        response = screening_endpoint.screening_check(request, config=config)
    filters = {item.filter for item in response.checks}
    assert response.market == "tw"
    assert "exclude_st" not in filters
    assert "market_cap_min" not in filters


def test_funnel_keeps_zero_and_skips_unknown_stages():
    raw = {"snapshot_count": 900, "snapshot_filter_count": 40, "after_filter_count": 0, "daily_enriched": True}
    assert _build_screening_funnel(raw, candidate_count=0) == [
        {"stage": "snapshot", "label": "母體", "count": 900},
        {"stage": "hard_filter", "label": "條件篩選後", "count": 40},
        {"stage": "daily_filter", "label": "日線條件後", "count": 0},
        {"stage": "selected", "label": "入選", "count": 0},
    ]
    # 沒跑日線時不列那一層；舊結果沒有 snapshot_filter_count 時退回 after_filter_count。
    old = _build_screening_funnel({"snapshot_count": 900, "after_filter_count": 12}, candidate_count=3)
    assert [item["stage"] for item in old] == ["snapshot", "hard_filter", "selected"]
    assert old[1]["count"] == 12


def test_us_universe_reports_the_source_actually_used(monkeypatch):
    def broken():
        raise RuntimeError("wikipedia down")

    monkeypatch.setattr(snapshot_us, "_fetch_sp500_tickers", broken)
    monkeypatch.delenv("SCREENING_US_TICKERS", raising=False)
    tickers, source = snapshot_us.resolve_us_universe("auto")
    assert source == "default"
    assert tickers == snapshot_us._DEFAULT_US_UNIVERSE

    monkeypatch.setenv("SCREENING_US_TICKERS", "AAPL, TSM")
    assert snapshot_us.resolve_us_universe("auto") == (["AAPL", "TSM"], "env")

    monkeypatch.setattr(snapshot_us, "_fetch_sp500_tickers", lambda: ["AAPL", "MSFT"])
    assert snapshot_us.resolve_us_universe("auto") == (["AAPL", "MSFT"], "sp500")
    assert snapshot_us.fetch_us_universe("auto") == ["AAPL", "MSFT"]


AS_OF = pd.Timestamp("2099-01-05")


def _factors(**overrides):
    row = {
        "stock_id": "1101", "close": 40.0, "d1": 0.01, "vol_ratio": 1.5, "pe_ratio": 12.0, "pb_ratio": 1.2,
        "industry": "01", "name": "台泥", "is_tib": False,
    }
    row.update(overrides)
    return row


def _px(*stock_ids):
    return pd.DataFrame([
        {"stock_id": sid, "date": AS_OF, "volume": 1000.0, "turnover": 40000.0} for sid in stock_ids
    ])


def test_snapshot_frame_maps_schema_and_suffix():
    df = tw_prescreen.snapshot_frame(
        AS_OF,
        pd.DataFrame([_factors(), _factors(stock_id="6488", name="環球晶", industry="")]),
        _px("1101", "6488"),
        {"1101": 10000.0},
        {"1101": "twse", "6488": "tpex"},
    )
    listed = df[df["code"] == "1101.TW"].iloc[0]
    assert listed["amount"] == 40000.0
    assert listed["change_pct"] == 1.0
    assert listed["total_mv"] == 400000.0
    assert listed["turnover_rate"] == 10.0
    assert listed["industry"] == "水泥"
    otc = df[df["code"] == "6488.TWO"].iloc[0]
    # 沒有股本是沒有讀數，不是 0。
    assert pd.isna(otc["total_mv"]) and pd.isna(otc["turnover_rate"])


def test_snapshot_frame_drops_non_common_innovation_board_and_unknown_market():
    df = tw_prescreen.snapshot_frame(
        AS_OF,
        pd.DataFrame([
            _factors(),
            _factors(stock_id="0050", name="元大台灣50"),
            _factors(stock_id="7610", name="聯友金屬-創", is_tib=True),
            _factors(stock_id="2330", name="台積電"),
        ]),
        _px("1101", "0050", "7610", "2330"),
        {},
        {"1101": "twse", "0050": "twse", "7610": "twse"},  # 2330 查不到市場別：不猜後綴
    )
    assert df["code"].tolist() == ["1101.TW"]


def test_prescreen_module_is_in_the_flat_docker_copy():
    """Dockerfile 只 COPY market_data/*.py，子目錄進不了映像；serve 路徑也不能 import scripts/。"""
    root = Path(__file__).resolve().parents[1]
    assert "COPY market_data/*.py ./market_data/" in (root / "docker" / "Dockerfile").read_text(encoding="utf-8")
    assert Path(tw_prescreen.__file__).resolve().parent == (root / "market_data").resolve()
    source = Path(tw_prescreen.__file__).read_text(encoding="utf-8")
    assert "import screen_tw" not in source and "from screen_tw" not in source


def test_screen_tw_keeps_its_names_as_a_thin_shell():
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import screen_tw

    assert screen_tw.compute_factors is tw_prescreen.compute_factors
    assert screen_tw.REVENUE_STALE_DAYS == tw_prescreen.REVENUE_STALE_DAYS

