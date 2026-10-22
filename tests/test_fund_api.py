# -*- coding: utf-8 -*-
"""境內基金 API 與服務：報酬計算、持倉估值、錯誤碼。market schema 以假 gateway 取代。"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pandas as pd

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from fastapi.testclient import TestClient  # noqa: E402

import src.auth as auth  # noqa: E402
from api.app import create_app  # noqa: E402
from src.config import Config  # noqa: E402
from src.services import fund_service  # noqa: E402
from src.services.fund_service import (  # noqa: E402
    FundGateway,
    FundService,
    compute_returns,
    compute_risk,
)
from src.storage import DatabaseManager  # noqa: E402

INFO = {
    "fund_id": "18480065", "name": "安聯台灣科技基金", "company": "安聯投信", "isin": "TW000T3604Y3",
    "sitca_code": "DDO04", "type_code": "AA1", "type_name": "國內投資股票型", "invest_area": "台灣",
    "currency": "TWD", "inception_date": date(2001, 4, 3), "aum": 325001709959, "aum_currency": "台幣",
    "aum_date": date(2026, 9, 30), "dividend_policy": "不分配", "cnyes_id": "A36004",
}


def _today() -> date:
    # 每次呼叫時取：模組 import 時取的日期在跨午夜的長跑全量裡會落後服務端
    return date.today()


def _series(days: int, end: Optional[date] = None, start_nav: float = 100.0, step: float = 0.1):
    end = end or _today()
    return [{"date": end - timedelta(days=days - 1 - i), "nav": start_nav + step * i,
             "change": step, "change_pct": None, "source": "sitca"} for i in range(days)]


class FakeMarket:
    def __init__(self, series=None, info=INFO, navs=None, fail=False):
        # 預設給超過五年的歷史（已涵蓋全期，不會觸發補歷史）
        self.series = series if series is not None else _series(365 * 5 + 30)
        self.info_row = info
        # 其他基金代號 → info，給「同通路有別檔基金」這類情境用
        self.other_infos = {}
        self.navs = navs
        self.fail = fail
        self.backfills = []

    def _check(self):
        if self.fail:
            raise RuntimeError('relation "market.fund_nav" does not exist')

    def gateway(self) -> FundGateway:
        def history(fund_id, start=None):
            self._check()
            rows = [p for p in self.series if start is None or p["date"] >= start]
            return pd.DataFrame(rows)

        def latest_navs(ids):
            self._check()
            if self.navs is not None:
                return self.navs
            last = self.series[-1]
            return {i: (last["nav"], last["date"]) for i in ids}

        def backfill(fund_id):
            self.backfills.append(fund_id)
            self.series = _series(400)

        return FundGateway(
            search=lambda q, limit: (self._check(), pd.DataFrame([{**INFO, "nav": 783.21, "nav_date": _today()}]))[1],
            info=lambda fund_id: (self._check(), self.info_row if fund_id == INFO["fund_id"]
                                  else self.other_infos.get(fund_id))[1],
            history=history, latest_navs=latest_navs, backfill=backfill,
            top_holdings=lambda fund_id: [{"name": "創意", "sector": "科技", "weight": 7.65, "country": "台灣"}],
        )


class ComputeTests(unittest.TestCase):
    def test_returns_use_nav_on_or_before_period_start(self):
        series = [{"date": date(2026, 1, 2), "nav": 100.0}, {"date": date(2026, 9, 18), "nav": 110.0},
                  {"date": date(2026, 10, 19), "nav": 121.0}]
        out = compute_returns(series)
        # 1m 起點 9/19 當日沒有淨值，取之前最後一筆 9/18
        self.assertAlmostEqual(out["m1"], 10.0)
        self.assertIsNone(out["y1"])            # 期間不足就回 None，不用 0 冒充
        self.assertIsNone(out["ytd"])           # 去年底之前沒有資料

    def test_returns_empty_series_are_all_none(self):
        self.assertTrue(all(v is None for v in compute_returns([]).values()))

    def test_risk_drawdown_is_negative_and_needs_enough_points(self):
        series = _series(100, step=1.0) + [{"date": _today() + timedelta(days=1), "nav": 150.0}]
        risk = compute_risk(series)
        self.assertLess(risk["max_drawdown"], 0)
        self.assertIsNotNone(risk["volatility"])
        self.assertIsNone(compute_risk(_series(5))["max_drawdown"])


class FundApiTests(unittest.TestCase):
    def setUp(self) -> None:
        auth._auth_enabled = None
        self.temp_dir = tempfile.TemporaryDirectory()
        data_dir = Path(self.temp_dir.name)
        env_path = data_dir / ".env"
        db_path = data_dir / "fund_api_test.db"
        env_path.write_text(f"ADMIN_AUTH_ENABLED=false\nDATABASE_PATH={db_path}\n", encoding="utf-8")
        self._env = patch.dict(os.environ, {"ENV_FILE": str(env_path), "DATABASE_PATH": str(db_path)})
        self._env.start()
        Config.reset_instance()
        DatabaseManager.reset_instance()
        self.market = FakeMarket()
        self._gw = patch.object(FundGateway, "default", classmethod(lambda cls: self.market.gateway()))
        self._gw.start()
        self.client = TestClient(create_app(static_dir=data_dir / "static"))

    def tearDown(self) -> None:
        self._gw.stop()
        DatabaseManager.reset_instance()
        Config.reset_instance()
        self._env.stop()
        self.temp_dir.cleanup()

    def _create(self, **overrides):
        body = {"fund_id": "18480065", "units": 588.2, "cost_total": 232000, "as_of": str(_today()),
                "platform": "國泰世華", **overrides}
        return self.client.post("/api/v1/funds/holdings", json=body)

    def test_detail_returns_latest_nav_date_and_returns(self):
        r = self.client.get("/api/v1/funds/18480065")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["nav_date"], str(_today()))
        self.assertFalse(body["is_stale"])
        self.assertIn("y1", body["returns"])
        self.assertIsNotNone(body["returns"]["y1"])
        self.assertEqual(self.market.backfills, [])    # 歷史夠長就不補

    def test_detail_backfills_short_history_once(self):
        self.market.series = _series(3)
        body = self.client.get("/api/v1/funds/18480065").json()
        self.assertEqual(self.market.backfills, ["18480065"])
        self.assertEqual(body["history_points"], 400)

    def test_detail_backfills_when_only_sitca_rows_accumulated(self):
        # 公會每日值累積到 30 筆以上，但只有入庫以來的短歷史：仍要補全期
        self.market.series = _series(45)
        body = self.client.get("/api/v1/funds/18480065").json()
        self.assertEqual(self.market.backfills, ["18480065"])
        self.assertEqual(body["history_points"], 400)
        self.assertIsNotNone(body["returns"]["y1"])

    def test_detail_skips_backfill_when_history_reaches_inception(self):
        # 新成立的基金：歷史起點貼近成立日就已是全期，不要每次打開都打鉅亨
        self.market.series = _series(45)
        self.market.info_row = {**INFO, "inception_date": _today() - timedelta(days=50)}
        self.client.get("/api/v1/funds/18480065")
        self.assertEqual(self.market.backfills, [])

    def test_detail_backfills_when_history_starts_long_after_inception(self):
        # 起點離成立日很遠、又不滿五年：缺前段歷史，要補
        self.market.series = _series(400)
        self.client.get("/api/v1/funds/18480065")
        self.assertEqual(self.market.backfills, ["18480065"])

    def test_detail_backfills_when_gap_to_inception_just_exceeds_grace(self):
        # 起點比成立日晚、剛超過寬限期：前段歷史仍缺，要補（防寬限被放寬過頭）
        self.market.series = _series(45)
        first = self.market.series[0]["date"]
        gap = fund_service.INCEPTION_GRACE_DAYS + 15
        self.market.info_row = {**INFO, "inception_date": first - timedelta(days=gap)}
        self.client.get("/api/v1/funds/18480065")
        self.assertEqual(self.market.backfills, ["18480065"])

    def test_detail_skips_backfill_when_gap_to_inception_within_grace(self):
        # 起點在寬限期內（公會晚幾週才有第一筆淨值）：視為全期，不補（防寬限被收得過緊）
        self.market.series = _series(45)
        first = self.market.series[0]["date"]
        gap = fund_service.INCEPTION_GRACE_DAYS - 5
        self.market.info_row = {**INFO, "inception_date": first - timedelta(days=gap)}
        self.client.get("/api/v1/funds/18480065")
        self.assertEqual(self.market.backfills, [])

    def test_create_holding_backfills_sitca_only_history(self):
        self.market.series = _series(45)
        self.assertEqual(self._create().status_code, 200)
        self.assertEqual(self.market.backfills, ["18480065"])

    def test_stale_nav_is_flagged(self):
        self.market.series = _series(365 * 5 + 30, end=_today() - timedelta(days=fund_service.STALE_AFTER_DAYS + 1))
        self.assertTrue(self.client.get("/api/v1/funds/18480065").json()["is_stale"])

    def test_recent_nav_is_not_stale(self):
        self.market.series = _series(365 * 5 + 30, end=_today() - timedelta(days=fund_service.STALE_AFTER_DAYS))
        self.assertFalse(self.client.get("/api/v1/funds/18480065").json()["is_stale"])

    def test_unknown_fund_is_404_with_code(self):
        r = self.client.get("/api/v1/funds/NOPE1")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()["error"], "fund_not_found")

    def test_non_ascii_fund_id_is_rejected(self):
        self.assertEqual(self.client.get("/api/v1/funds/１８４８").status_code, 422)

    def test_market_db_down_is_503_with_code(self):
        self.market.fail = True
        r = self.client.get("/api/v1/funds/search", params={"q": "安聯"})
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["error"], "fund_data_unavailable")

    def test_holding_valued_with_latest_nav(self):
        self.assertEqual(self._create().status_code, 200)
        self.market.navs = {"18480065": (766.59, _today())}
        body = self.client.get("/api/v1/funds/holdings").json()
        item = body["items"][0]
        self.assertAlmostEqual(item["market_value"], 588.2 * 766.59)
        self.assertAlmostEqual(item["pnl"], 588.2 * 766.59 - 232000)
        self.assertEqual(body["totals"][0]["currency"], "TWD")
        self.assertAlmostEqual(body["totals"][0]["market_value"], 588.2 * 766.59)

    def test_holding_without_nav_has_null_value_not_zero(self):
        self._create()
        self.market.navs = {}
        body = self.client.get("/api/v1/funds/holdings").json()
        self.assertIsNone(body["items"][0]["market_value"])
        self.assertIsNone(body["items"][0]["pnl"])
        self.assertTrue(body["items"][0]["is_stale"])
        self.assertIsNone(body["totals"][0]["market_value"])    # 有一檔缺值，合計不能假裝完整

    def test_holdings_survive_market_db_outage(self):
        self._create()
        self.market.fail = True
        body = self.client.get("/api/v1/funds/holdings").json()
        self.assertEqual(len(body["items"]), 1)
        self.assertIsNotNone(body["nav_error"])

    def test_duplicate_holding_is_409_and_update_delete_work(self):
        hid = self._create().json()["id"]
        r = self._create()
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["error"], "duplicate_holding")
        r = self.client.put(f"/api/v1/funds/holdings/{hid}", json={"units": 600})
        self.assertEqual(r.json()["units"], 600)
        self.assertEqual(self.client.delete(f"/api/v1/funds/holdings/{hid}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/v1/funds/holdings/{hid}").status_code, 404)

    def test_update_platform_to_existing_one_is_409(self):
        first = self._create(platform="國泰世華").json()["id"]
        self._create(platform="鉅亨買基金")
        r = self.client.put(f"/api/v1/funds/holdings/{first}", json={"platform": "鉅亨買基金"})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["error"], "duplicate_holding")
        # 交易已回滾，原本那筆不受影響
        platforms = sorted(i["platform"] for i in self.client.get("/api/v1/funds/holdings").json()["items"])
        self.assertEqual(platforms, ["國泰世華", "鉅亨買基金"])

    def test_update_keeping_own_platform_or_moving_to_free_one_succeeds(self):
        first = self._create(platform="國泰世華").json()["id"]
        self._create(platform="鉅亨買基金")
        r = self.client.put(f"/api/v1/funds/holdings/{first}", json={"platform": "國泰世華", "units": 600})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["units"], 600)
        r = self.client.put(f"/api/v1/funds/holdings/{first}", json={"platform": "基富通"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["platform"], "基富通")

    def test_update_platform_to_one_holding_only_other_fund_succeeds(self):
        # 目標通路上只有「別檔」基金：不是重複持倉，查重必須連基金代號一起比
        self.market.other_infos["99990001"] = {**INFO, "fund_id": "99990001", "name": "另一檔基金"}
        mine = self._create(platform="國泰世華").json()["id"]
        self.assertEqual(self._create(fund_id="99990001", platform="鉅亨買基金").status_code, 200)
        r = self.client.put(f"/api/v1/funds/holdings/{mine}", json={"platform": "鉅亨買基金"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["platform"], "鉅亨買基金")
        items = self.client.get("/api/v1/funds/holdings").json()["items"]
        self.assertEqual(sorted((i["platform"], i["fund_id"]) for i in items),
                         [("鉅亨買基金", "18480065"), ("鉅亨買基金", "99990001")])

    def test_holding_for_unknown_fund_is_404(self):
        self.assertEqual(self._create(fund_id="NOPE1").status_code, 404)

    def test_top_holdings(self):
        body = self.client.get("/api/v1/funds/18480065/holdings").json()
        self.assertEqual(body["items"][0]["name"], "創意")
        self.assertIsNone(body["error"])


class ServiceUnitTests(unittest.TestCase):
    def test_top_holdings_source_failure_is_reported_not_raised(self):
        market = FakeMarket()
        gw = market.gateway()
        gw.top_holdings = lambda fund_id: (_ for _ in ()).throw(RuntimeError("boom"))
        out = FundService(gateway=gw).get_top_holdings("18480065")
        self.assertEqual(out["error"], "source_unavailable")
        self.assertEqual(out["items"], [])


if __name__ == "__main__":
    unittest.main()
