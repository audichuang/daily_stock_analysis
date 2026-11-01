# -*- coding: utf-8 -*-
"""基金 API 追加欄位：今日損益、持股資料月份、與帳本的重疊、加權指數比較序列。"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from fastapi.testclient import TestClient  # noqa: E402

import src.auth as auth  # noqa: E402
from api.app import create_app  # noqa: E402
from market_data import funds as market_funds  # noqa: E402
from src.config import Config  # noqa: E402
from src.services import fund_service  # noqa: E402
from src.services.fund_service import FundGateway  # noqa: E402
from src.storage import DatabaseManager  # noqa: E402
from tests.test_fund_api import INFO, FakeMarket, _series, _today  # noqa: E402

FUND_ID = INFO["fund_id"]
OTHER_FUND_ID = "99990001"


class FundsAppendTests(unittest.TestCase):
    def setUp(self) -> None:
        auth._auth_enabled = None
        self.temp_dir = tempfile.TemporaryDirectory()
        data_dir = Path(self.temp_dir.name)
        env_path = data_dir / ".env"
        db_path = data_dir / "funds_append_test.db"
        env_path.write_text(f"ADMIN_AUTH_ENABLED=false\nDATABASE_PATH={db_path}\n", encoding="utf-8")
        self._env = patch.dict(os.environ, {"ENV_FILE": str(env_path), "DATABASE_PATH": str(db_path)})
        self._env.start()
        Config.reset_instance()
        DatabaseManager.reset_instance()
        self.market = FakeMarket()
        self.market.other_infos[OTHER_FUND_ID] = {**INFO, "fund_id": OTHER_FUND_ID, "name": "另一檔基金"}
        self.recent = {}
        self.index_rows = []
        self.index_error = None
        self.top_items = [{"name": "創意", "sector": "科技", "weight": 7.65, "country": "台灣"}]
        self._gw = patch.object(FundGateway, "default", classmethod(lambda cls: self._gateway()))
        self._gw.start()
        self.client = TestClient(create_app(static_dir=data_dir / "static"))

    def tearDown(self) -> None:
        self._gw.stop()
        DatabaseManager.reset_instance()
        Config.reset_instance()
        self._env.stop()
        self.temp_dir.cleanup()

    def _gateway(self) -> FundGateway:
        gateway = self.market.gateway()
        gateway.recent_navs = lambda ids: self.recent
        gateway.top_holdings = lambda fund_id: self.top_items

        def index_history(index_id, start=None, end=None):
            if self.index_error:
                raise self.index_error
            self.index_args = (index_id, start, end)
            return pd.DataFrame(self.index_rows)

        gateway.index_history = index_history
        return gateway

    def _create(self, fund_id=FUND_ID, platform="國泰世華", units=100.0):
        response = self.client.post("/api/v1/funds/holdings", json={
            "fund_id": fund_id, "units": units, "cost_total": 1000, "as_of": str(_today()), "platform": platform,
        })
        self.assertEqual(response.status_code, 200, response.text)

    def _set_nav(self, fund_id, nav, prev, nav_date=None):
        nav_date = nav_date or _today()
        navs = self.market.navs or {}
        navs[fund_id] = (nav, nav_date)
        self.market.navs = navs
        rows = [(nav, nav_date)]
        if prev is not None:
            rows.append((prev, nav_date - timedelta(days=1)))
        self.recent[fund_id] = rows

    def test_day_pnl_and_nav_change_use_previous_nav(self):
        self._create()
        self._set_nav(FUND_ID, 110.0, 100.0)
        body = self.client.get("/api/v1/funds/holdings").json()
        item = body["items"][0]
        self.assertAlmostEqual(item["nav_change_pct"], 10.0)
        self.assertAlmostEqual(item["day_pnl"], 1000.0)
        self.assertAlmostEqual(body["totals"][0]["day_pnl"], 1000.0)

    def test_day_pnl_is_null_with_only_one_nav(self):
        self._create()
        self._set_nav(FUND_ID, 110.0, None)
        item = self.client.get("/api/v1/funds/holdings").json()["items"][0]
        self.assertIsNone(item["nav_change_pct"])
        self.assertIsNone(item["day_pnl"])
        self.assertIsNotNone(item["market_value"])  # 市值不受影響

    def test_day_pnl_is_null_for_stale_nav(self):
        self._create()
        old = _today() - timedelta(days=fund_service.STALE_AFTER_DAYS + 1)
        self._set_nav(FUND_ID, 110.0, 100.0, nav_date=old)
        item = self.client.get("/api/v1/funds/holdings").json()["items"][0]
        self.assertTrue(item["is_stale"])
        self.assertIsNone(item["day_pnl"])

    def test_day_pnl_kept_for_nav_at_stale_boundary(self):
        self._create()
        edge = _today() - timedelta(days=fund_service.STALE_AFTER_DAYS)
        self._set_nav(FUND_ID, 110.0, 100.0, nav_date=edge)
        item = self.client.get("/api/v1/funds/holdings").json()["items"][0]
        self.assertFalse(item["is_stale"])
        self.assertAlmostEqual(item["day_pnl"], 1000.0)

    def test_total_day_pnl_is_voided_when_one_fund_is_missing(self):
        self._create()
        self._create(fund_id=OTHER_FUND_ID, platform="鉅亨買基金")
        self._set_nav(FUND_ID, 110.0, 100.0)
        self._set_nav(OTHER_FUND_ID, 50.0, None)
        body = self.client.get("/api/v1/funds/holdings").json()
        self.assertIsNone(body["totals"][0]["day_pnl"])
        self.assertIsNotNone(body["totals"][0]["market_value"])

    def test_recent_nav_failure_keeps_market_value(self):
        self._create()
        self._set_nav(FUND_ID, 110.0, 100.0)
        original = self._gateway

        def failing_gateway():
            gateway = original()
            gateway.recent_navs = lambda ids: (_ for _ in ()).throw(RuntimeError("boom"))
            return gateway

        self._gateway = failing_gateway
        body = self.client.get("/api/v1/funds/holdings").json()
        self.assertIsNone(body["items"][0]["day_pnl"])
        self.assertAlmostEqual(body["items"][0]["market_value"], 11000.0)
        self.assertIsNone(body["nav_error"])

    def test_top_holdings_month_uses_taipei_date(self):
        # 1790697600 是 UTC 9/29 16:00、台北 9/30 00:00；再加一天是台北 10/1 00:00，UTC 仍在九月
        self.top_items = [{**self.top_items[0], "portfolio_date": 1790697600}]
        body = self.client.get(f"/api/v1/funds/{FUND_ID}/holdings").json()
        self.assertEqual(body["as_of_month"], "2026-09")

        self.top_items = [{**self.top_items[0], "portfolio_date": 1790697600 + 86400}]
        body = self.client.get(f"/api/v1/funds/{FUND_ID}/holdings").json()
        self.assertEqual(body["as_of_month"], "2026-10")

    def test_top_holdings_month_null_when_source_omits_it(self):
        body = self.client.get(f"/api/v1/funds/{FUND_ID}/holdings").json()
        self.assertIsNone(body["as_of_month"])

    def _top_holdings_with_ledger(self, identities, names):
        with patch(
            "src.repositories.portfolio_repo.PortfolioRepository.list_cached_position_identities",
            return_value=identities,
        ), patch("src.data.stock_index_loader.get_index_stock_name", side_effect=names.get):
            return self.client.get(f"/api/v1/funds/{FUND_ID}/holdings").json()

    def test_overlap_marks_ledger_match(self):
        body = self._top_holdings_with_ledger([("tw", "3443.TW")], {"3443.TW": "創意"})
        self.assertEqual(body["items"][0]["ledger_symbol"], "3443.TW")
        self.assertEqual(body["overlap"], [{"symbol": "3443.TW", "name": "創意", "weight": 7.65}])

    def test_overlap_not_marked_without_exact_name(self):
        body = self._top_holdings_with_ledger([("tw", "2330.TW")], {"2330.TW": "台積電"})
        self.assertIsNone(body["items"][0]["ledger_symbol"])
        self.assertEqual(body["overlap"], [])

    def test_overlap_not_marked_when_substring_only(self):
        body = self._top_holdings_with_ledger([("tw", "9999.TW")], {"9999.TW": "創意電子"})
        self.assertEqual(body["overlap"], [])

    def test_overlap_not_marked_when_name_is_ambiguous(self):
        body = self._top_holdings_with_ledger(
            [("tw", "3443.TW"), ("us", "GUC")], {"3443.TW": "創意", "GUC": "創意"},
        )
        self.assertEqual(body["overlap"], [])

    def test_overlap_ledger_failure_only_drops_marks(self):
        with patch(
            "src.repositories.portfolio_repo.PortfolioRepository.list_cached_position_identities",
            side_effect=RuntimeError("boom"),
        ):
            body = self.client.get(f"/api/v1/funds/{FUND_ID}/holdings").json()
        self.assertEqual(body["items"][0]["name"], "創意")
        self.assertEqual(body["overlap"], [])

    def test_benchmark_covers_the_nav_range(self):
        self.market.series = _series(365 * 5 + 30)
        first = self.market.series[-30]["date"]
        self.index_rows = [{"date": first, "close": 20000.0}]
        body = self.client.get(f"/api/v1/funds/{FUND_ID}/nav", params={"period": "m1", "benchmark": "taiex"}).json()
        self.assertEqual(body["benchmark"]["index_id"], "TAIEX")
        self.assertEqual(body["benchmark"]["points"][0]["close"], 20000.0)
        index_id, start, end = self.index_args
        self.assertEqual(index_id, "TAIEX")
        self.assertEqual(str(start), body["points"][0]["date"])
        self.assertEqual(str(end), body["points"][-1]["date"])

    def test_benchmark_absent_unless_requested(self):
        self.index_error = AssertionError("should not query index")
        body = self.client.get(f"/api/v1/funds/{FUND_ID}/nav", params={"period": "m1"}).json()
        self.assertIsNone(body["benchmark"])
        self.assertIsNone(body["benchmark_error"])

    def test_benchmark_failure_keeps_nav_points(self):
        self.index_error = RuntimeError("boom")
        body = self.client.get(f"/api/v1/funds/{FUND_ID}/nav", params={"period": "m1", "benchmark": "taiex"}).json()
        self.assertTrue(body["points"])
        self.assertIsNone(body["benchmark"])
        self.assertEqual(body["benchmark_error"], "source_unavailable")

    def test_benchmark_unknown_value_is_rejected(self):
        response = self.client.get(f"/api/v1/funds/{FUND_ID}/nav", params={"benchmark": "spx"})
        self.assertEqual(response.status_code, 422)


class TopHoldingsParsingTests(unittest.TestCase):
    def test_portfolio_date_is_carried_on_every_row(self):
        payload = {"items": {"portfolioDate": 1790697600, "data": [
            {"name": "創意", "sector": "科技", "value": 7.65, "country": "台灣"},
            {"name": "欣興", "sector": "科技", "value": 6.28, "country": "台灣"},
        ]}}
        with patch.object(market_funds, "_cnyes_json", return_value=payload):
            rows = market_funds.fetch_top_holdings("A36004")
        self.assertEqual([r["portfolio_date"] for r in rows], [1790697600, 1790697600])
        self.assertEqual(rows[0]["weight"], 7.65)


if __name__ == "__main__":
    unittest.main()
