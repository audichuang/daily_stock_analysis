# -*- coding: utf-8 -*-
"""PR2 tests for portfolio CSV import, risk thresholds and FX stale fallback."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
from fastapi.testclient import TestClient

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["litellm"] = MagicMock()

import src.auth as auth
from api.app import create_app
from src.config import Config
from src.services.decision_signal_service import DecisionSignalService
from src.services.portfolio_import_service import PortfolioImportService
from src.services.portfolio_risk_service import PortfolioRiskService
from src.services.portfolio_service import PortfolioBusyError, PortfolioService
from src.storage import DatabaseManager


def _reset_auth_globals() -> None:
    auth._auth_enabled = None
    auth._session_secret = None
    auth._password_hash_salt = None
    auth._password_hash_stored = None
    auth._rate_limit = {}


# setUp patches the method away; keep the real one for tests of its own logic.
_REAL_FETCH_FX_CROSS_RATE = PortfolioService.__dict__["_fetch_fx_cross_rate"].__func__


class PortfolioPr2TestCase(unittest.TestCase):
    """End-to-end style tests for PR2 import, dedup, risk and fx behavior."""

    def setUp(self) -> None:
        _reset_auth_globals()
        self.temp_dir = tempfile.TemporaryDirectory()
        data_dir = Path(self.temp_dir.name)
        self.env_path = data_dir / ".env"
        self.db_path = data_dir / "portfolio_pr2_test.db"
        self.env_path.write_text(
            "\n".join(
                [
                    "STOCK_LIST=600519",
                    "GEMINI_API_KEY=test",
                    "ADMIN_AUTH_ENABLED=false",
                    "PORTFOLIO_RISK_CONCENTRATION_ALERT_PCT=70.0",
                    "PORTFOLIO_RISK_DRAWDOWN_ALERT_PCT=10.0",
                    "PORTFOLIO_RISK_STOP_LOSS_ALERT_PCT=25.0",
                    "PORTFOLIO_RISK_STOP_LOSS_NEAR_RATIO=0.8",
                    "PORTFOLIO_RISK_LOOKBACK_DAYS=365",
                    f"DATABASE_PATH={self.db_path}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        os.environ["ENV_FILE"] = str(self.env_path)
        os.environ["DATABASE_PATH"] = str(self.db_path)
        Config.reset_instance()
        DatabaseManager.reset_instance()

        cross_patch = patch.object(PortfolioService, "_fetch_fx_cross_rate", return_value=None)
        cross_patch.start()
        self.addCleanup(cross_patch.stop)
        self.db = DatabaseManager.get_instance()
        self.service = PortfolioService()
        self.import_service = PortfolioImportService(portfolio_service=self.service)
        self.risk_service = PortfolioRiskService(portfolio_service=self.service)
        self._board_fetch_patcher = patch.object(PortfolioRiskService, "_fetch_belong_boards", return_value=[])
        self._board_fetch_patcher.start()
        # 匯率刷新會順手補歷史日線；預設關掉 yfinance，避免測試連外。
        self._yf_patcher = patch("src.services.portfolio_service.yf", None)
        self._yf_patcher.start()
        self.client = TestClient(create_app(static_dir=data_dir / "empty-static"))

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        os.environ.pop("ENV_FILE", None)
        os.environ.pop("DATABASE_PATH", None)
        self._board_fetch_patcher.stop()
        self._yf_patcher.stop()
        self.temp_dir.cleanup()

    def _save_close(self, symbol: str, on_date: date, close: float) -> None:
        df = pd.DataFrame(
            [
                {
                    "date": on_date,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1.0,
                    "amount": close,
                    "pct_chg": 0.0,
                }
            ]
        )
        self.db.save_daily_data(df, code=symbol, data_source="portfolio-pr2-test")

    def _create_position(self, account_id: int, symbol: str, price: float = 100.0, *, market: str = "cn") -> None:
        self.service.record_trade(
            account_id=account_id,
            symbol=symbol,
            trade_date=date(2026, 1, 1),
            side="buy",
            quantity=10,
            price=price,
            market=market,
            currency="CNY" if market == "cn" else "USD",
        )
        self._save_close(symbol, date(2026, 1, 1), price)

    def _create_signal(self, symbol: str, action: str, **overrides) -> dict:
        payload = {
            "stock_code": symbol,
            "stock_name": symbol,
            "market": "cn",
            "source_type": "manual",
            "trace_id": f"signal-{symbol}-{action}-{len(overrides)}",
            "trigger_source": "api",
            "action": action,
            "reason": f"{symbol} {action} reason",
            "status": "active",
        }
        payload.update(overrides)
        return DecisionSignalService().create_signal(payload)["item"]

    @staticmethod
    def _csv_bytes(with_trade_uid: bool = True) -> bytes:
        if with_trade_uid:
            csv_text = (
                "成交日期,证券代码,买卖标志,成交数量,成交均价,成交编号,手续费,印花税\n"
                "2026-01-02,600519,买入,10,100,HT-001,1,0\n"
            )
        else:
            csv_text = (
                "成交日期,证券代码,买卖标志,成交数量,成交均价,手续费,印花税\n"
                "2026-01-02,600519,买入,10,100,1,0\n"
            )
        return csv_text.encode("utf-8")

    def test_import_dedup_trade_uid_and_hash(self) -> None:
        account = self.service.create_account(name="Main", broker="Demo", market="cn", base_currency="CNY")
        aid = account["id"]

        parsed_uid = self.import_service.parse_trade_csv(broker="huatai", content=self._csv_bytes(with_trade_uid=True))
        first_uid = self.import_service.commit_trade_records(
            account_id=aid,
            broker="huatai",
            records=parsed_uid["records"],
        )
        second_uid = self.import_service.commit_trade_records(
            account_id=aid,
            broker="huatai",
            records=parsed_uid["records"],
        )
        self.assertEqual(first_uid["inserted_count"], 1)
        self.assertEqual(second_uid["duplicate_count"], 1)

        parsed_hash = self.import_service.parse_trade_csv(
            broker="huatai",
            content=self._csv_bytes(with_trade_uid=False),
        )
        first_hash = self.import_service.commit_trade_records(
            account_id=aid,
            broker="huatai",
            records=parsed_hash["records"],
        )
        second_hash = self.import_service.commit_trade_records(
            account_id=aid,
            broker="huatai",
            records=parsed_hash["records"],
        )
        self.assertEqual(first_hash["inserted_count"], 0)
        self.assertEqual(first_hash["duplicate_count"], 1)
        self.assertEqual(second_hash["inserted_count"], 0)

    def test_import_side_parser_avoids_false_sell_match(self) -> None:
        csv_text = (
            "成交日期,证券代码,买卖标志,成交数量,成交均价,成交编号\n"
            "2026-01-02,600519,Asset Transfer,10,100,HT-002\n"
        )
        parsed = self.import_service.parse_trade_csv(
            broker="huatai",
            content=csv_text.encode("utf-8"),
        )
        self.assertEqual(parsed["record_count"], 0)

    def test_import_supported_broker_registry(self) -> None:
        items = self.import_service.list_supported_brokers()
        broker_map = {item["broker"]: item for item in items}
        self.assertIn("huatai", broker_map)
        self.assertIn("citic", broker_map)
        self.assertIn("cmb", broker_map)
        self.assertIn("zhongxin", broker_map["citic"]["aliases"])
        self.assertIn("zhaoshang", broker_map["cmb"]["aliases"])

    def test_import_preserves_leading_zero_symbol(self) -> None:
        csv_text = (
            "成交日期,证券代码,买卖标志,成交数量,成交均价,成交编号\n"
            "2026-01-02,000001,买入,10,100,HT-003\n"
        )
        parsed = self.import_service.parse_trade_csv(
            broker="huatai",
            content=csv_text.encode("utf-8"),
        )
        self.assertEqual(parsed["record_count"], 1)
        self.assertEqual(parsed["records"][0]["symbol"], "000001")

    def test_import_dry_run_counts_in_file_duplicates(self) -> None:
        account = self.service.create_account(name="Main", broker="Demo", market="cn", base_currency="CNY")
        aid = account["id"]
        csv_text = (
            "成交日期,证券代码,买卖标志,成交数量,成交均价,成交编号,手续费,印花税\n"
            "2026-01-02,600519,买入,10,100,HT-004,1,0\n"
            "2026-01-02,600519,买入,10,100,HT-004,1,0\n"
        )
        parsed = self.import_service.parse_trade_csv(
            broker="huatai",
            content=csv_text.encode("utf-8"),
        )
        result = self.import_service.commit_trade_records(
            account_id=aid,
            broker="huatai",
            records=parsed["records"],
            dry_run=True,
        )
        self.assertEqual(result["record_count"], 2)
        self.assertEqual(result["inserted_count"], 1)
        self.assertEqual(result["duplicate_count"], 1)

    def test_import_allows_identical_split_fills_without_trade_uid(self) -> None:
        account = self.service.create_account(name="Main", broker="Demo", market="cn", base_currency="CNY")
        aid = account["id"]
        csv_text = (
            "成交日期,证券代码,买卖标志,成交数量,成交均价,手续费,印花税\n"
            "2026-01-02,600519,买入,10,100,1,0\n"
            "2026-01-02,600519,买入,10,100,1,0\n"
        )
        parsed = self.import_service.parse_trade_csv(
            broker="huatai",
            content=csv_text.encode("utf-8"),
        )
        self.assertEqual(parsed["record_count"], 2)
        self.assertEqual(len({item["dedup_hash"] for item in parsed["records"]}), 2)

        first_commit = self.import_service.commit_trade_records(
            account_id=aid,
            broker="huatai",
            records=parsed["records"],
        )
        second_commit = self.import_service.commit_trade_records(
            account_id=aid,
            broker="huatai",
            records=parsed["records"],
        )

        self.assertEqual(first_commit["inserted_count"], 2)
        self.assertEqual(first_commit["duplicate_count"], 0)
        self.assertEqual(second_commit["inserted_count"], 0)
        self.assertEqual(second_commit["duplicate_count"], 2)

    def test_import_oversell_counts_failed_not_duplicate(self) -> None:
        account = self.service.create_account(name="Main", broker="Demo", market="cn", base_currency="CNY")
        aid = account["id"]
        self.service.record_trade(
            account_id=aid,
            symbol="600519",
            trade_date=date(2026, 1, 1),
            side="buy",
            quantity=10,
            price=100,
            market="cn",
            currency="CNY",
        )

        result = self.import_service.commit_trade_records(
            account_id=aid,
            broker="huatai",
            records=[
                {
                    "trade_date": "2026-01-02",
                    "symbol": "600519",
                    "side": "sell",
                    "quantity": 20,
                    "price": 90,
                    "fee": 0.0,
                    "tax": 0.0,
                    "trade_uid": "HT-SELL-001",
                    "dedup_hash": "oversell-hash-001",
                    "market": "cn",
                    "currency": "CNY",
                }
            ],
        )

        self.assertEqual(result["inserted_count"], 0)
        self.assertEqual(result["duplicate_count"], 0)
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(len(result["errors"]), 1)

    def test_import_busy_counts_failed_not_duplicate(self) -> None:
        account = self.service.create_account(name="Main", broker="Demo", market="cn", base_currency="CNY")
        aid = account["id"]

        with patch.object(
            self.import_service.portfolio_service,
            "record_trade",
            side_effect=PortfolioBusyError("Portfolio ledger is busy; please retry shortly."),
        ):
            result = self.import_service.commit_trade_records(
                account_id=aid,
                broker="huatai",
                records=[
                    {
                        "trade_date": "2026-01-02",
                        "symbol": "600519",
                        "side": "buy",
                        "quantity": 10,
                        "price": 90,
                        "fee": 0.0,
                        "tax": 0.0,
                        "trade_uid": "HT-BUSY-001",
                        "dedup_hash": "busy-hash-001",
                        "market": "cn",
                        "currency": "CNY",
                    }
                ],
            )

        self.assertEqual(result["inserted_count"], 0)
        self.assertEqual(result["duplicate_count"], 0)
        self.assertEqual(result["failed_count"], 1)
        self.assertIn("portfolio_busy", result["errors"][0])

    def test_risk_threshold_boundary(self) -> None:
        account = self.service.create_account(name="Main", broker="Demo", market="cn", base_currency="CNY")
        aid = account["id"]
        self.service.record_cash_ledger(
            account_id=aid,
            event_date=date(2026, 1, 1),
            direction="in",
            amount=20000,
            currency="CNY",
        )
        self.service.record_trade(
            account_id=aid,
            symbol="600519",
            trade_date=date(2026, 1, 1),
            side="buy",
            quantity=100,
            price=100,
            market="cn",
            currency="CNY",
        )
        self.service.record_trade(
            account_id=aid,
            symbol="000001",
            trade_date=date(2026, 1, 1),
            side="buy",
            quantity=100,
            price=20,
            market="cn",
            currency="CNY",
        )

        self._save_close("600519", date(2026, 1, 1), 100.0)
        self._save_close("000001", date(2026, 1, 1), 20.0)
        self.service.get_portfolio_snapshot(account_id=aid, as_of=date(2026, 1, 1), cost_method="fifo")

        self._save_close("600519", date(2026, 1, 2), 70.0)
        self._save_close("000001", date(2026, 1, 2), 20.0)
        report = self.risk_service.get_risk_report(account_id=aid, as_of=date(2026, 1, 2), cost_method="fifo")

        self.assertTrue(report["concentration"]["alert"])
        self.assertTrue(report["drawdown"]["alert"])
        self.assertTrue(report["stop_loss"]["near_alert"])
        self.assertGreaterEqual(report["stop_loss"]["triggered_count"], 1)
        self.assertAlmostEqual(report["thresholds"]["drawdown_alert_pct"], 10.0, places=6)

    def test_risk_drawdown_backfills_snapshot_window_on_first_call(self) -> None:
        account = self.service.create_account(name="Main", broker="Demo", market="cn", base_currency="CNY")
        aid = account["id"]
        self.service.record_cash_ledger(
            account_id=aid,
            event_date=date(2026, 1, 1),
            direction="in",
            amount=20000,
            currency="CNY",
        )
        self.service.record_trade(
            account_id=aid,
            symbol="600519",
            trade_date=date(2026, 1, 1),
            side="buy",
            quantity=100,
            price=100,
            market="cn",
            currency="CNY",
        )
        self._save_close("600519", date(2026, 1, 1), 100.0)
        self._save_close("600519", date(2026, 1, 2), 70.0)

        report = self.risk_service.get_risk_report(account_id=aid, as_of=date(2026, 1, 2), cost_method="fifo")
        self.assertGreaterEqual(report["drawdown"]["series_points"], 2)
        self.assertGreater(report["drawdown"]["max_drawdown_pct"], 10.0)
        self.assertTrue(report["drawdown"]["alert"])

    def test_concentration_preserves_positive_exposure_with_rounded_zero_weight(self) -> None:
        risk = PortfolioRiskService()
        snapshot = {"total_market_value": 10_000_001, "accounts": [{
            "base_currency": "CNY", "market": "cn", "positions": [
                {"symbol": "600519", "market_value_base": 10_000_000, "valuation_currency": "CNY"},
                {"symbol": "000001", "market_value_base": 1, "valuation_currency": "CNY"},
            ],
        }]}
        concentration = risk._build_concentration(snapshot, 30, as_of_date=date(2026, 1, 1))
        with patch.object(risk, "_resolve_primary_sector", side_effect=["白酒", "银行"]):
            sectors = risk._build_sector_concentration(snapshot, 30, as_of_date=date(2026, 1, 1))
        for block, rows_key in ((concentration, "top_positions"), (sectors, "top_sectors")):
            self.assertEqual(block["top_weight_pct"], 100)
            self.assertEqual([row["weight_pct"] for row in block[rows_key]], [100, 0])
            self.assertEqual(block[rows_key][1]["market_value_base"], 1)
            self.assertTrue(block["alert"])

    def test_concentration_uses_cny_normalized_exposure(self) -> None:
        cn_account = self.service.create_account(name="CN", broker="Demo", market="cn", base_currency="CNY")
        us_account = self.service.create_account(name="US", broker="Demo", market="us", base_currency="USD")
        cn_id = cn_account["id"]
        us_id = us_account["id"]

        self.service.record_cash_ledger(
            account_id=cn_id,
            event_date=date(2026, 1, 1),
            direction="in",
            amount=1000.0,
            currency="CNY",
        )
        self.service.record_trade(
            account_id=cn_id,
            symbol="600519",
            trade_date=date(2026, 1, 1),
            side="buy",
            quantity=10,
            price=100,
            market="cn",
            currency="CNY",
        )

        self.service.record_cash_ledger(
            account_id=us_id,
            event_date=date(2026, 1, 1),
            direction="in",
            amount=100.0,
            currency="USD",
        )
        self.service.record_trade(
            account_id=us_id,
            symbol="AAPL",
            trade_date=date(2026, 1, 1),
            side="buy",
            quantity=1,
            price=100,
            market="us",
            currency="USD",
        )
        self._save_close("600519", date(2026, 1, 1), 100.0)
        self._save_close("AAPL", date(2026, 1, 1), 100.0)
        self.service.repo.save_fx_rate(
            from_currency="USD",
            to_currency="CNY",
            rate_date=date(2026, 1, 1),
            rate=7.0,
            source="manual",
            is_stale=False,
        )
        self.service.get_portfolio_snapshot(as_of=date(2026, 1, 1), cost_method="fifo")

        report = self.risk_service.get_risk_report(as_of=date(2026, 1, 1), cost_method="fifo")
        positions = {item["symbol"]: item for item in report["concentration"]["top_positions"]}
        self.assertIn("AAPL", positions)
        self.assertAlmostEqual(positions["AAPL"]["market_value_base"], 700.0, places=6)

    def test_sector_concentration_uses_unclassified_for_non_cn(self) -> None:
        us_account = self.service.create_account(name="US", broker="Demo", market="us", base_currency="USD")
        us_id = us_account["id"]
        self.service.record_cash_ledger(
            account_id=us_id,
            event_date=date(2026, 1, 1),
            direction="in",
            amount=100.0,
            currency="USD",
        )
        self.service.record_trade(
            account_id=us_id,
            symbol="AAPL",
            trade_date=date(2026, 1, 1),
            side="buy",
            quantity=1,
            price=100,
            market="us",
            currency="USD",
        )
        self._save_close("AAPL", date(2026, 1, 1), 100.0)
        report = self.risk_service.get_risk_report(account_id=us_id, as_of=date(2026, 1, 1), cost_method="fifo")
        self.assertIn("sector_concentration", report)
        sectors = report["sector_concentration"]["top_sectors"]
        self.assertTrue(len(sectors) >= 1)
        self.assertEqual(sectors[0]["sector"], "UNCLASSIFIED")

    @patch.object(PortfolioRiskService, "_fetch_belong_boards", return_value=[{"name": "白酒", "type": "行业"}])
    def test_sector_concentration_cn_board_mapping(self, _mock_fetch) -> None:
        account = self.service.create_account(name="Main", broker="Demo", market="cn", base_currency="CNY")
        aid = account["id"]
        self.service.record_cash_ledger(
            account_id=aid,
            event_date=date(2026, 1, 1),
            direction="in",
            amount=10000.0,
            currency="CNY",
        )
        self.service.record_trade(
            account_id=aid,
            symbol="600519",
            trade_date=date(2026, 1, 1),
            side="buy",
            quantity=100,
            price=100,
            market="cn",
            currency="CNY",
        )
        self._save_close("600519", date(2026, 1, 1), 100.0)
        report = self.risk_service.get_risk_report(account_id=aid, as_of=date(2026, 1, 1), cost_method="fifo")
        sectors = report["sector_concentration"]["top_sectors"]
        self.assertTrue(len(sectors) >= 1)
        self.assertEqual(sectors[0]["sector"], "白酒")

    def test_risk_report_aggregates_active_defensive_decision_signals_for_holdings(self) -> None:
        account = self.service.create_account(name="Main", broker="Demo", market="cn", base_currency="CNY")
        aid = account["id"]
        self.service.record_cash_ledger(
            account_id=aid,
            event_date=date(2026, 1, 1),
            direction="in",
            amount=100000.0,
            currency="CNY",
        )
        for symbol in ("SH600519", "300750", "000001", "000002", "000003"):
            self._create_position(aid, symbol)

        self._create_signal("600519.SH", "sell")
        self._create_signal("300750", "reduce")
        self._create_signal("000001", "alert")
        self._create_signal("000002", "buy")
        self._create_signal("000003", "watch")
        self._create_signal("002000", "sell")
        self._create_signal("600519", "alert", status="expired", trace_id="expired-alert-600519")

        report = self.risk_service.get_risk_report(account_id=aid, as_of=date(2026, 1, 1), cost_method="fifo")

        block = report["decision_signal_risk"]
        self.assertTrue(block["available"])
        self.assertEqual(block["total"], 3)
        self.assertEqual(block["actions"], {"sell": 1, "reduce": 1, "alert": 1})
        symbols = {item["symbol"] for item in block["items"]}
        self.assertEqual(symbols, {"SH600519", "300750", "000001"})
        signal_actions = {item["symbol"]: item["signal"]["action"] for item in block["items"]}
        self.assertNotIn("000002", signal_actions)
        self.assertNotIn("000003", signal_actions)
        self.assertNotIn("002000", signal_actions)
        self.assertEqual(signal_actions["SH600519"], "sell")
        self.assertEqual(signal_actions["300750"], "reduce")
        self.assertEqual(signal_actions["000001"], "alert")

    def test_risk_report_uses_requested_snapshot_for_decision_signal_filters(self) -> None:
        account = self.service.create_account(name="Main", broker="Demo", market="cn", base_currency="CNY")
        aid = account["id"]
        self.service.record_cash_ledger(
            account_id=aid,
            event_date=date(2026, 1, 1),
            direction="in",
            amount=100000.0,
            currency="CNY",
        )
        self.service.record_trade(
            account_id=aid,
            symbol="600519",
            trade_date=date(2026, 1, 1),
            side="buy",
            quantity=10,
            price=100,
            market="cn",
            currency="CNY",
        )
        self._save_close("600519", date(2026, 1, 1), 100.0)
        self._save_close("600519", date(2026, 1, 2), 100.0)
        self.service.record_trade(
            account_id=aid,
            symbol="000001",
            trade_date=date(2026, 1, 2),
            side="buy",
            quantity=10,
            price=20,
            market="cn",
            currency="CNY",
        )
        self._save_close("000001", date(2026, 1, 2), 20.0)
        self._create_signal("000001", "sell")

        original = self.risk_service.decision_signal_service.list_signals
        with patch.object(
            self.risk_service.decision_signal_service,
            "list_signals",
            wraps=original,
        ) as spy:
            report = self.risk_service.get_risk_report(
                account_id=aid,
                as_of=date(2026, 1, 2),
                cost_method="fifo",
            )

        block = report["decision_signal_risk"]
        self.assertTrue(block["available"])
        self.assertEqual(block["total"], 1)
        self.assertEqual(block["items"][0]["symbol"], "000001")
        self.assertEqual(block["items"][0]["signal"]["action"], "sell")
        for call in spy.mock_calls:
            self.assertIsNot(call.kwargs.get("holding_only"), True)
        identity_calls = [
            call.kwargs.get("stock_identities")
            for call in spy.mock_calls
            if call.kwargs.get("stock_identities") is not None
        ]
        observed_identities = {
            identity
            for ids in identity_calls
            for identity in ids
        }
        self.assertIn(("cn", "000001"), observed_identities)
        self.assertIn(("cn", "600519"), observed_identities)

    def test_risk_report_decision_signal_fail_open(self) -> None:
        account = self.service.create_account(name="Main", broker="Demo", market="cn", base_currency="CNY")
        aid = account["id"]
        self.service.record_cash_ledger(
            account_id=aid,
            event_date=date(2026, 1, 1),
            direction="in",
            amount=10000.0,
            currency="CNY",
        )
        self._create_position(aid, "600519")

        class BrokenSignalService:
            def list_signals(self, **_kwargs):
                raise RuntimeError("decision signal unavailable")

        risk_service = PortfolioRiskService(
            portfolio_service=self.service,
            decision_signal_service=BrokenSignalService(),
        )
        report = risk_service.get_risk_report(account_id=aid, as_of=date(2026, 1, 1), cost_method="fifo")

        self.assertFalse(report["decision_signal_risk"]["available"])
        self.assertEqual(report["decision_signal_risk"]["total"], 0)
        self.assertEqual(report["decision_signal_risk"]["items"], [])

    def test_portfolio_risk_endpoint_returns_defensive_decision_signals(self) -> None:
        account = self.service.create_account(name="Main", broker="Demo", market="cn", base_currency="CNY")
        aid = account["id"]
        self.service.record_cash_ledger(
            account_id=aid,
            event_date=date(2026, 1, 1),
            direction="in",
            amount=10000.0,
            currency="CNY",
        )
        self._create_position(aid, "600519")
        self._create_signal("600519", "sell")

        response = self.client.get(
            "/api/v1/portfolio/risk",
            params={"account_id": aid, "as_of": "2026-01-01", "cost_method": "fifo"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("decision_signal_risk", payload)
        self.assertEqual(payload["decision_signal_risk"]["total"], 1)
        self.assertEqual(payload["decision_signal_risk"]["items"][0]["signal"]["action"], "sell")

    def test_snapshot_does_not_trigger_online_fx_refresh(self) -> None:
        account = self.service.create_account(name="US", broker="Demo", market="us", base_currency="CNY")
        aid = account["id"]
        self.service.record_cash_ledger(
            account_id=aid,
            event_date=date(2026, 1, 1),
            direction="in",
            amount=1000.0,
            currency="USD",
        )
        self.service.record_trade(
            account_id=aid,
            symbol="AAPL",
            trade_date=date(2026, 1, 1),
            side="buy",
            quantity=1,
            price=100,
            market="us",
            currency="USD",
        )
        self._save_close("AAPL", date(2026, 1, 1), 100.0)
        self.service.repo.save_fx_rate(
            from_currency="USD",
            to_currency="CNY",
            rate_date=date(2026, 1, 1),
            rate=7.0,
            source="manual",
            is_stale=False,
        )

        with patch.object(PortfolioService, "_fetch_fx_closes_from_yfinance", side_effect=AssertionError("should not call")):
            self.service.get_portfolio_snapshot(account_id=aid, as_of=date(2026, 1, 1), cost_method="fifo")

    def test_fx_refresh_fallback_marks_stale(self) -> None:
        account = self.service.create_account(name="US", broker="Demo", market="us", base_currency="CNY")
        aid = account["id"]
        self.service.record_cash_ledger(
            account_id=aid,
            event_date=date(2026, 1, 1),
            direction="in",
            amount=1000.0,
            currency="USD",
        )
        self.service.repo.save_fx_rate(
            from_currency="USD",
            to_currency="CNY",
            rate_date=date(2026, 1, 1),
            rate=7.0,
            source="manual",
            is_stale=False,
        )

        with patch.object(PortfolioService, "_fetch_fx_closes_from_yfinance", return_value=[]):
            summary = self.service.refresh_fx_rates(account_id=aid, as_of=date(2026, 1, 2))

        self.assertEqual(summary["pair_count"], 1)
        self.assertEqual(summary["updated_count"], 0)
        self.assertEqual(summary["stale_count"], 1)
        latest = self.service.repo.get_latest_fx_rate(
            from_currency="USD",
            to_currency="CNY",
            as_of=date(2026, 1, 2),
        )
        self.assertIsNotNone(latest)
        self.assertTrue(bool(latest.is_stale))
        self.assertAlmostEqual(float(latest.rate), 7.0, places=6)

    def test_fx_refresh_fetches_base_to_aggregate_pair_for_non_cny_account(self) -> None:
        # 只有台币帐户、交易也全是台币时，唯一需要的汇率是 TWD->CNY（快照汇总币别）。
        # 不刷新这一对，汇总就走 1:1 回退：台币数字被标成 CNY 且整页 fx_stale。
        account = self.service.create_account(name="TW", broker="Demo", market="tw", base_currency="TWD")
        aid = account["id"]
        self.service.record_cash_ledger(
            account_id=aid, event_date=date(2026, 1, 1), direction="in", amount=1000.0, currency="TWD"
        )
        calls = []

        def fake_fetch(*, from_currency, to_currency, as_of_date):
            calls.append((from_currency, to_currency))
            return [(as_of_date, 0.2)]

        with patch.object(PortfolioService, "_fetch_fx_closes_from_yfinance", side_effect=fake_fetch):
            summary = self.service.refresh_fx_rates(account_id=aid, as_of=date(2026, 1, 2))

        self.assertEqual(calls, [("TWD", "CNY")])
        self.assertEqual((summary["pair_count"], summary["updated_count"]), (1, 1))
        snapshot = self.service.get_portfolio_snapshot(as_of=date(2026, 1, 2), include_realtime=False)
        self.assertEqual(snapshot["currency"], "CNY")
        self.assertAlmostEqual(snapshot["total_cash"], 200.0, places=6)
        self.assertFalse(snapshot["fx_stale"])

    def _fx_frame(self, closes):
        index = pd.DatetimeIndex([pd.Timestamp(d, tz="Europe/London") for d, _ in closes])
        return pd.DataFrame({"Close": [c for _, c in closes]}, index=index)

    def _refresh_usd_with_frame(self, frame, as_of):
        account = self.service.create_account(name="US", broker="Demo", market="us", base_currency="CNY")
        self.service.record_cash_ledger(
            account_id=account["id"], event_date=date(2026, 1, 1), direction="in", amount=1000.0, currency="USD"
        )
        yf_mock = MagicMock()
        yf_mock.Ticker.return_value.history.return_value = frame
        with patch("src.services.portfolio_service.yf", yf_mock):
            self.service.refresh_fx_rates(account_id=account["id"], as_of=as_of)

    def _fx_row(self, on_date):
        row = self.service.repo.get_latest_fx_rate(from_currency="USD", to_currency="CNY", as_of=on_date)
        return row if row is not None and row.rate_date == on_date else None

    def test_fx_refresh_backfills_historic_bars_under_own_dates(self) -> None:
        frame = self._fx_frame([("2026-01-05", 7.01), ("2026-01-06", float("nan")), ("2026-01-07", 7.03), ("2026-01-08", 7.05)])
        self._refresh_usd_with_frame(frame, date(2026, 1, 8))
        self.assertAlmostEqual(self._fx_row(date(2026, 1, 5)).rate, 7.01)
        self.assertEqual(self._fx_row(date(2026, 1, 5)).source, "yfinance_backfill")
        self.assertIsNone(self._fx_row(date(2026, 1, 6)))  # NaN close skipped
        self.assertAlmostEqual(self._fx_row(date(2026, 1, 7)).rate, 7.03)
        today = self._fx_row(date(2026, 1, 8))  # today's row keeps the original behaviour
        self.assertAlmostEqual(today.rate, 7.05)
        self.assertEqual(today.source, "yfinance")

    def test_fx_refresh_backfill_never_overwrites_manual_rows(self) -> None:
        self.service.repo.save_fx_rate(
            from_currency="USD", to_currency="CNY", rate_date=date(2026, 1, 5), rate=6.5, source="manual", is_stale=False
        )
        frame = self._fx_frame([("2026-01-05", 7.01), ("2026-01-07", 7.03), ("2026-01-08", 7.05)])
        self._refresh_usd_with_frame(frame, date(2026, 1, 8))
        kept = self._fx_row(date(2026, 1, 5))
        self.assertAlmostEqual(kept.rate, 6.5)
        self.assertEqual(kept.source, "manual")

    def _london_frame(self, closes):
        index = pd.DatetimeIndex([pd.Timestamp(d, tz="Europe/London") for d, _ in closes])
        return pd.DataFrame({"Close": [c for _, c in closes]}, index=index)

    def _seed_fx(self, on_date, rate, source, is_stale):
        self.service.repo.save_fx_rate(
            from_currency="USD", to_currency="CNY", rate_date=on_date, rate=rate, source=source, is_stale=is_stale
        )

    def _refresh_at_london(self, frame, as_of, london_today):
        with patch.object(PortfolioService, "_london_today", return_value=london_today):
            self._refresh_usd_with_frame(frame, as_of)

    def test_fx_backfill_overwrites_stale_row_with_real_close(self) -> None:
        self._seed_fx(date(2026, 1, 5), 6.5, "manual", True)  # stale carry of an earlier rate
        frame = self._london_frame([("2026-01-05", 7.01), ("2026-01-08", 7.05)])
        self._refresh_at_london(frame, date(2026, 1, 8), date(2026, 1, 8))
        row = self._fx_row(date(2026, 1, 5))
        self.assertAlmostEqual(row.rate, 7.01)
        self.assertFalse(bool(row.is_stale))

    def test_fx_backfill_overwrites_yfinance_intraday_row_with_close(self) -> None:
        self._seed_fx(date(2026, 1, 7), 7.00, "yfinance", False)  # same-day refresh value
        frame = self._london_frame([("2026-01-07", 7.03), ("2026-01-08", 7.05)])
        self._refresh_at_london(frame, date(2026, 1, 8), date(2026, 1, 8))
        row = self._fx_row(date(2026, 1, 7))
        self.assertAlmostEqual(row.rate, 7.03)
        self.assertEqual(row.source, "yfinance_backfill")

    def test_fx_backfill_keeps_manual_row(self) -> None:
        self._seed_fx(date(2026, 1, 7), 6.5, "manual", False)
        frame = self._london_frame([("2026-01-07", 7.03), ("2026-01-08", 7.05)])
        self._refresh_at_london(frame, date(2026, 1, 8), date(2026, 1, 8))
        self.assertAlmostEqual(self._fx_row(date(2026, 1, 7)).rate, 6.5)

    def test_fx_backfill_skips_bar_still_open_in_london(self) -> None:
        # Taipei 2026-01-08 03:00 is London 2026-01-07 19:00: the 01-07 bar is still open.
        frame = self._london_frame([("2026-01-06", 7.02), ("2026-01-07", 7.04)])
        self._refresh_at_london(frame, date(2026, 1, 8), date(2026, 1, 7))
        self.assertAlmostEqual(self._fx_row(date(2026, 1, 6)).rate, 7.02)
        self.assertIsNone(self._fx_row(date(2026, 1, 7)))
        self.assertAlmostEqual(self._fx_row(date(2026, 1, 8)).rate, 7.04)  # today's rate unchanged

    # ---- outlier filter: only isolated spikes are rejected ----
    def _filter(self, closes, as_of=date(2026, 1, 8), pair=("USD", "CNY"), london_today=date(2026, 1, 8), **kw):
        with patch.object(PortfolioService, "_london_today", return_value=london_today):
            return self.service._filter_fx_outliers(
                from_currency=pair[0], to_currency=pair[1], as_of_date=as_of, closes=closes, **kw
            )

    def test_fx_outlier_isolated_spike_rejected(self) -> None:
        closes = [(date(2026, 1, 5), 7.30), (date(2026, 1, 6), 6.00), (date(2026, 1, 7), 7.31), (date(2026, 1, 8), 7.32)]
        self.assertEqual([d for d, _ in self._filter(closes)], [date(2026, 1, 5), date(2026, 1, 7), date(2026, 1, 8)])

    def test_fx_outlier_real_jump_accepted(self) -> None:
        closes = [(date(2026, 1, 5), 7.30), (date(2026, 1, 6), 7.60), (date(2026, 1, 7), 7.61)]
        self.assertEqual(self._filter(closes), closes)

    def test_fx_outlier_latest_checked_against_cross_rate(self) -> None:
        closes = [(date(2026, 1, 7), 0.2050), (date(2026, 1, 8), 0.1962)]
        kw = {"pair": ("TWD", "CNY")}
        with patch.object(PortfolioService, "_fetch_fx_cross_rate", return_value=0.2047):
            self.assertEqual(self._filter(closes, **kw), closes[:1])
        with patch.object(PortfolioService, "_fetch_fx_cross_rate", return_value=0.1963):
            self.assertEqual(self._filter(closes, **kw), closes)  # cross says the new level is real

    def test_fx_outlier_cross_rate_ignored_for_historical_as_of(self) -> None:
        closes = [(date(2026, 1, 7), 7.30), (date(2026, 1, 8), 7.31)]
        with patch.object(PortfolioService, "_fetch_fx_cross_rate", return_value=7.60):
            out = self._filter(closes, pair=("TWD", "CNY"), london_today=date(2026, 6, 1))
        self.assertEqual(out, closes)

    # ---- cross-rate check on every bar (non-USD pairs): consecutive junk cannot vouch for itself ----
    def _cross(self, *days, rate=0.2045):
        return {date(2026, 1, d): rate for d in days}

    def test_fx_outlier_consecutive_junk_rejected_with_cross_rate(self) -> None:
        closes = [(date(2026, 1, 6), 0.2054), (date(2026, 1, 7), 0.1963), (date(2026, 1, 8), 0.1963)]
        kw = {"pair": ("TWD", "CNY")}
        self.assertEqual(self._filter(closes, cross_closes={}, **kw), closes)  # neighbour rule alone is fooled
        self.assertEqual(self._filter(closes, cross_closes=self._cross(6, 7, 8), **kw), closes[:1])

    def test_fx_outlier_real_jump_accepted_when_cross_jumps_too(self) -> None:
        closes = [(date(2026, 1, 6), 0.2054), (date(2026, 1, 7), 0.2200), (date(2026, 1, 8), 0.2201)]
        cross = {date(2026, 1, 6): 0.2054, date(2026, 1, 7): 0.2199, date(2026, 1, 8): 0.2200}
        self.assertEqual(self._filter(closes, pair=("TWD", "CNY"), cross_closes=cross), closes)

    def test_fx_outlier_missing_cross_day_falls_back_to_neighbour_rule(self) -> None:
        closes = [(date(2026, 1, 6), 0.2054), (date(2026, 1, 7), 0.1963), (date(2026, 1, 8), 0.2050)]
        out = self._filter(closes, pair=("TWD", "CNY"), cross_closes=self._cross(6, 8))
        self.assertEqual([d for d, _ in out], [date(2026, 1, 6), date(2026, 1, 8)])

    def test_fx_outlier_usd_pair_ignores_cross_and_keeps_neighbour_rule(self) -> None:
        closes = [(date(2026, 1, 6), 7.30), (date(2026, 1, 7), 6.00), (date(2026, 1, 8), 6.00)]
        with patch("src.services.portfolio_service.yf", MagicMock()), patch.object(
            PortfolioService, "_fetch_fx_closes_from_yfinance", side_effect=AssertionError("no cross for USD")
        ):
            self.assertEqual(self._filter(closes), closes)  # two adjacent junk bars still pass: unchanged
            self.assertEqual(PortfolioService._fetch_fx_cross_closes(
                from_currency="USD", to_currency="CNY", as_of_date=date(2026, 1, 8)), {})

    def test_fx_cross_closes_built_from_usd_legs_per_day(self) -> None:
        legs = {
            "TWD": [(date(2026, 1, 6), 32.0), (date(2026, 1, 7), 32.5)],
            "CNY": [(date(2026, 1, 7), 6.5), (date(2026, 1, 8), 6.6)],
        }
        fake = lambda *, from_currency, to_currency, as_of_date: legs[to_currency]  # noqa: E731
        with patch("src.services.portfolio_service.yf", MagicMock()), patch.object(
            PortfolioService, "_fetch_fx_closes_from_yfinance", side_effect=fake
        ):
            out = PortfolioService._fetch_fx_cross_closes(
                from_currency="TWD", to_currency="CNY", as_of_date=date(2026, 1, 8)
            )
        self.assertEqual(list(out), [date(2026, 1, 7)])  # only the day both legs have
        self.assertAlmostEqual(out[date(2026, 1, 7)], 6.5 / 32.5)

    def _refresh_twd_cny(self, pair_closes, usd_twd, usd_cny, as_of, london_today):
        account = self.service.create_account(name="TW", broker="Demo", market="tw", base_currency="TWD")
        self.service.record_cash_ledger(
            account_id=account["id"], event_date=date(2026, 1, 1), direction="in", amount=1000.0, currency="TWD"
        )
        table = {("TWD", "CNY"): pair_closes, ("USD", "TWD"): usd_twd, ("USD", "CNY"): usd_cny}
        fake = lambda *, from_currency, to_currency, as_of_date: table[(from_currency, to_currency)]  # noqa: E731
        with patch("src.services.portfolio_service.yf", MagicMock()), patch.object(
            PortfolioService, "_fetch_fx_closes_from_yfinance", side_effect=fake
        ), patch.object(PortfolioService, "_london_today", return_value=london_today):
            self.service.refresh_fx_rates(account_id=account["id"], as_of=as_of)

    def _twd_row(self, on_date):
        row = self.service.repo.get_latest_fx_rate(from_currency="TWD", to_currency="CNY", as_of=on_date)
        return row if row is not None and row.rate_date == on_date else None

    def _junk_window(self):
        days = [date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 8)]
        pair = list(zip(days, [0.2054, 0.1963, 0.1963]))
        return pair, [(d, 32.6) for d in days], [(d, 6.665) for d in days]

    def test_fx_refresh_rewrites_stored_junk_row_from_cross_rate(self) -> None:
        pair, twd, cny = self._junk_window()
        self.service.repo.save_fx_rate(
            from_currency="TWD", to_currency="CNY", rate_date=date(2026, 1, 7), rate=0.1963,
            source="yfinance_backfill", is_stale=False,
        )
        self._refresh_twd_cny(pair, twd, cny, date(2026, 1, 8), date(2026, 1, 8))
        row = self._twd_row(date(2026, 1, 7))
        self.assertAlmostEqual(row.rate, 6.665 / 32.6)
        self.assertEqual(row.source, "yfinance_cross")
        self.assertFalse(bool(row.is_stale))
        self.assertTrue(self._twd_row(date(2026, 1, 8)).is_stale)  # rejected newest bar is a carry, not 0.1963

    def test_fx_refresh_cross_repair_fills_missing_day_but_spares_manual_and_close_rows(self) -> None:
        pair, twd, cny = self._junk_window()
        self._refresh_twd_cny(pair, twd, cny, date(2026, 1, 8), date(2026, 1, 8))
        self.assertEqual(self._twd_row(date(2026, 1, 7)).source, "yfinance_cross")  # no row before: filled
        self.service.repo.save_fx_rate(
            from_currency="TWD", to_currency="CNY", rate_date=date(2026, 1, 7), rate=0.19, source="manual", is_stale=False
        )
        self._refresh_twd_cny(pair, twd, cny, date(2026, 1, 8), date(2026, 1, 8))
        self.assertAlmostEqual(self._twd_row(date(2026, 1, 7)).rate, 0.19)  # manual untouched
        self.service.repo.save_fx_rate(
            from_currency="TWD", to_currency="CNY", rate_date=date(2026, 1, 7), rate=0.2040,
            source="yfinance_backfill", is_stale=False,
        )
        self._refresh_twd_cny(pair, twd, cny, date(2026, 1, 8), date(2026, 1, 8))
        self.assertAlmostEqual(self._twd_row(date(2026, 1, 7)).rate, 0.2040)  # within tolerance: left alone

    def test_fx_refresh_cross_repair_replaces_stale_carry_even_within_tolerance(self) -> None:
        """2026-10-16: the junk bar was rejected and the day kept a stale carry close to the cross rate."""
        pair, twd, cny = self._junk_window()
        self.service.repo.save_fx_rate(
            from_currency="TWD", to_currency="CNY", rate_date=date(2026, 1, 7), rate=6.665 / 32.6 * 1.005,
            source="yfinance", is_stale=True,
        )
        self._refresh_twd_cny(pair, twd, cny, date(2026, 1, 8), date(2026, 1, 8))
        row = self._twd_row(date(2026, 1, 7))
        self.assertAlmostEqual(row.rate, 6.665 / 32.6)
        self.assertEqual(row.source, "yfinance_cross")
        self.assertFalse(bool(row.is_stale))

    def test_fx_cross_rate_none_when_a_leg_is_usd(self) -> None:
        yf_mock = MagicMock()
        yf_mock.Ticker.return_value.history.return_value = self._fx_frame([("2026-01-08", 20.0)])
        with patch("src.services.portfolio_service.yf", yf_mock):
            self.assertIsNone(_REAL_FETCH_FX_CROSS_RATE(from_currency="USD", to_currency="TWD"))
            self.assertIsNone(_REAL_FETCH_FX_CROSS_RATE(from_currency="TWD", to_currency="USD"))
            self.assertAlmostEqual(
                _REAL_FETCH_FX_CROSS_RATE(from_currency="TWD", to_currency="CNY"), 1.0
            )

    def test_fx_refresh_rejected_latest_still_backfills_accepted_history(self) -> None:
        self._seed_fx(date(2026, 1, 2), 7.20, "yfinance", False)
        frame = self._fx_frame([("2026-01-05", 7.31), ("2026-01-06", 7.32), ("2026-01-07", 7.33), ("2026-01-08", 6.00)])
        self._refresh_at_london(frame, date(2026, 1, 8), date(2026, 1, 8))
        self.assertAlmostEqual(self._fx_row(date(2026, 1, 7)).rate, 7.33)
        today = self._fx_row(date(2026, 1, 8))
        self.assertTrue(today.is_stale)
        self.assertAlmostEqual(today.rate, 7.33)

    def test_fx_outlier_latest_garbage_rejected_when_previous_row_is_stale_carry(self) -> None:
        self._seed_fx(date(2026, 1, 5), 7.30, "yfinance", False)
        self._seed_fx(date(2026, 1, 6), 7.30, "yfinance", True)  # stale carry must not end the search
        self._seed_fx(date(2026, 1, 7), 7.30, "yfinance", True)
        self.assertEqual(self._filter([(date(2026, 1, 8), 6.00)]), [])
        self.assertEqual(self._filter([(date(2026, 1, 8), 7.31)]), [(date(2026, 1, 8), 7.31)])

    def test_fx_outlier_latest_garbage_rejected_after_long_stale_streak(self) -> None:
        self._seed_fx(date(2026, 1, 1), 7.30, "yfinance", False)
        for day in range(2, 9):  # 7 stale carries: the real row is 8 days before the newest bar
            self._seed_fx(date(2026, 1, day), 7.30, "yfinance", True)
        self.assertEqual(self._filter([(date(2026, 1, 9), 6.00)]), [])
        self.assertEqual(self._filter([(date(2026, 1, 9), 7.31)]), [(date(2026, 1, 9), 7.31)])

    def test_fx_outlier_reference_survives_arbitrarily_long_stale_streak(self) -> None:
        self._seed_fx(date(2026, 1, 1), 7.30, "yfinance", False)
        for day in range(2, 10):  # 8 stale carries; differing value proves they are skipped, not used
            self._seed_fx(date(2026, 1, day), 6.10, "yfinance", True)
        self.assertEqual(self._filter([(date(2026, 1, 10), 6.00)]), [])
        self.assertEqual(self._filter([(date(2026, 1, 10), 7.31)]), [(date(2026, 1, 10), 7.31)])
        self._seed_fx(date(2026, 1, 1), 7.30, "yfinance", False)
        for day in range(2, 40):  # a month-long streak, crossing into February
            self._seed_fx(date(2026, 1, 1) + timedelta(days=day - 1), 7.30, "yfinance", True)
        self.assertEqual(self._filter([(date(2026, 2, 10), 6.00)], as_of=date(2026, 2, 10)), [])

    def test_fx_refresh_filter_failure_does_not_carry_raw_latest_bar(self) -> None:
        self._seed_fx(date(2026, 1, 7), 7.30, "yfinance", False)
        frame = self._fx_frame([("2026-01-06", 7.31), ("2026-01-07", 7.32), ("2026-01-08", 6.00)])
        with patch.object(PortfolioService, "_last_real_stored_rate", side_effect=RuntimeError("db down")):
            self._refresh_at_london(frame, date(2026, 1, 8), date(2026, 1, 8))
        today = self._fx_row(date(2026, 1, 8))
        self.assertTrue(today.is_stale)
        self.assertAlmostEqual(today.rate, 7.30)  # last stored row, never the unchecked raw 6.00

    def test_fx_refresh_rejected_latest_carries_from_accepted_bar_over_same_day_carry(self) -> None:
        self._seed_fx(date(2026, 1, 2), 7.20, "yfinance", False)
        self._seed_fx(date(2026, 1, 8), 7.20, "yfinance", True)  # carry written by an earlier failed refresh
        frame = self._fx_frame([("2026-01-05", 7.31), ("2026-01-06", 7.32), ("2026-01-07", 7.33), ("2026-01-08", 6.00)])
        self._refresh_at_london(frame, date(2026, 1, 8), date(2026, 1, 8))
        today = self._fx_row(date(2026, 1, 8))
        self.assertTrue(today.is_stale)
        self.assertAlmostEqual(today.rate, 7.33)

    def test_fx_outlier_no_reference_accepts(self) -> None:
        self.assertEqual(self._filter([(date(2026, 1, 8), 6.00)]), [(date(2026, 1, 8), 6.00)])

    def test_fx_refresh_rejected_latest_does_not_become_today_rate(self) -> None:
        self._seed_fx(date(2026, 1, 7), 7.30, "yfinance", False)
        self._refresh_usd_with_frame(self._fx_frame([("2026-01-08", 6.00)]), date(2026, 1, 8))
        today = self._fx_row(date(2026, 1, 8))
        self.assertTrue(today.is_stale)
        self.assertAlmostEqual(today.rate, 7.30)

    # ---- close selection: 1h last bar > next daily Open > daily Close ----
    def _fetch_with(self, hourly, daily, as_of=date(2026, 1, 8)):
        def history(**kw):
            return hourly if kw["interval"] == "1h" else daily

        yf_mock = MagicMock()
        yf_mock.Ticker.return_value.history.side_effect = history
        with patch("src.services.portfolio_service.yf", yf_mock):
            return PortfolioService._fetch_fx_closes_from_yfinance(
                from_currency="USD", to_currency="CNY", as_of_date=as_of
            )

    @staticmethod
    def _ohlc(rows):
        index = pd.DatetimeIndex([pd.Timestamp(t, tz="Europe/London") for t, *_ in rows])
        return pd.DataFrame(
            {"Open": [o for _, o, _ in rows], "Close": [c for _, _, c in rows]}, index=index
        )

    def test_fx_fetch_uses_last_hourly_bar_of_london_day(self) -> None:
        hourly = self._ohlc([("2026-01-06 00:00", 7.0, 7.00), ("2026-01-06 23:00", 7.0, 7.05)])
        daily = self._ohlc([("2026-01-06", 7.0, 6.90), ("2026-01-07", 7.5, 7.5)])
        out = dict(self._fetch_with(hourly, daily))
        self.assertAlmostEqual(out[date(2026, 1, 6)], 7.05)

    def test_fx_fetch_falls_back_to_next_daily_open_then_daily_close(self) -> None:
        daily = self._ohlc([("2026-01-05", 7.0, 6.90), ("2026-01-06", 7.1, 7.2)])
        out = dict(self._fetch_with(None, daily))
        self.assertAlmostEqual(out[date(2026, 1, 5)], 7.1)  # next bar's Open
        self.assertAlmostEqual(out[date(2026, 1, 6)], 7.2)  # no successor: daily Close (warned)

    def test_fx_daily_successor_skips_weekends_but_keeps_next_weekday_open(self) -> None:
        for next_weekday in (False, True):
            with self.subTest(next_weekday=next_weekday):
                rows = [
                    ("2026-10-22", 0.2040, 0.2041),
                    ("2026-10-23", 0.2041, 0.2042),
                    ("2026-10-24", 0.1963, 0.1963),
                    ("2026-10-25", 0.1963, 0.1963),
                ]
                if next_weekday:
                    rows.append(("2026-10-26", 0.2043, 0.2044))
                closes = self._fetch_with(None, self._ohlc(rows), as_of=date(2026, 10, 23))
                self.assertEqual(closes, [
                    (date(2026, 10, 22), 0.2041),
                    (date(2026, 10, 23), 0.2043 if next_weekday else 0.2042),
                ])

    def test_fx_refresh_uses_bar_age_including_weekend_allowance(self) -> None:
        bar_date = date(2026, 1, 6)
        account = self.service.create_account(name="US", broker="Demo", market="us", base_currency="USD")
        self.service.record_cash_ledger(
            account_id=account["id"], event_date=bar_date, direction="in", amount=1000.0, currency="USD"
        )
        for age in (0, 1, 2, 3, 4, 6, 7):
            with self.subTest(age=age):
                as_of = bar_date + timedelta(days=age)
                with patch.object(PortfolioService, "_fetch_fx_closes_from_yfinance", return_value=[(bar_date, 7.05)]), patch.object(
                    PortfolioService, "_london_today", return_value=as_of
                ):
                    summary = self.service.refresh_fx_rates(account_id=account["id"], as_of=as_of)
                row = self._fx_row(as_of)
                self.assertAlmostEqual(row.rate, 7.05)
                self.assertEqual(bool(row.is_stale), age > 3)
                self.assertEqual(summary["updated_count"], int(age <= 3))
                self.assertEqual(summary["stale_count"], int(age > 3))
                snapshot = self.service.get_portfolio_snapshot(
                    account_id=account["id"], as_of=as_of, include_realtime=False
                )
                self.assertEqual(snapshot["fx_stale"], age > 3)
        self.assertFalse(self._fx_row(bar_date).is_stale)

    def test_fx_fetch_hourly_beats_daily_for_same_day(self) -> None:
        hourly = self._ohlc([("2026-01-05 22:00", 7.0, 7.33)])
        daily = self._ohlc([("2026-01-05", 7.0, 6.90), ("2026-01-06", 7.1, 7.2)])
        out = dict(self._fetch_with(hourly, daily))
        self.assertAlmostEqual(out[date(2026, 1, 5)], 7.33)

    def test_fx_fetch_drops_london_weekend_bars(self) -> None:
        """2026-10-24 (Sat): Yahoo returned a Saturday daily bar repeating junk; FX has no weekend close."""
        hourly = self._ohlc([("2026-01-09 22:00", 7.0, 7.33), ("2026-01-10 01:00", 7.0, 6.00)])
        daily = self._ohlc([("2026-01-09", 7.0, 6.90), ("2026-01-10", 6.0, 6.00), ("2026-01-11", 6.0, 6.00)])
        out = dict(self._fetch_with(hourly, daily, as_of=date(2026, 1, 11)))
        self.assertEqual(sorted(out), [date(2026, 1, 9)])
        self.assertAlmostEqual(out[date(2026, 1, 9)], 7.33)

    def test_fx_fetch_keeps_sunday_reopening_hourly_bars(self) -> None:
        """FX reopens Sunday evening London; that bar is a real price and the neighbour for Monday's check."""
        hourly = self._ohlc([("2026-01-09 22:00", 7.0, 7.05), ("2026-01-11 23:00", 7.0, 7.30), ("2026-01-12 01:00", 7.0, 7.31)])
        out = dict(self._fetch_with(hourly, None, as_of=date(2026, 1, 12)))
        self.assertEqual(sorted(out), [date(2026, 1, 9), date(2026, 1, 11), date(2026, 1, 12)])

    def test_fx_refresh_monday_after_weekend_gap_is_fresh(self) -> None:
        frame = self._london_frame([("2026-01-08", 7.03), ("2026-01-09", 7.05), ("2026-01-11 23:00", 7.30), ("2026-01-12 01:00", 7.31)])
        self._refresh_at_london(frame, date(2026, 1, 12), date(2026, 1, 12))
        today = self._fx_row(date(2026, 1, 12))
        self.assertAlmostEqual(today.rate, 7.31)
        self.assertFalse(bool(today.is_stale))

    def test_fx_refresh_on_saturday_saves_friday_close_as_fresh(self) -> None:
        frame = self._london_frame([("2026-01-08", 7.03), ("2026-01-09", 7.05), ("2026-01-10", 6.00)])
        self._refresh_at_london(frame, date(2026, 1, 10), date(2026, 1, 10))
        today = self._fx_row(date(2026, 1, 10))
        self.assertAlmostEqual(today.rate, 7.05)
        self.assertFalse(bool(today.is_stale))
        self.assertAlmostEqual(self._fx_row(date(2026, 1, 9)).rate, 7.05)

    def test_fx_refresh_downloads_pair_once(self) -> None:
        account = self.service.create_account(name="US", broker="Demo", market="us", base_currency="CNY")
        self.service.record_cash_ledger(
            account_id=account["id"], event_date=date(2026, 1, 1), direction="in", amount=1000.0, currency="USD"
        )
        yf_mock = MagicMock()
        yf_mock.Ticker.return_value.history.return_value = self._london_frame(
            [("2026-01-07", 7.03), ("2026-01-08", 7.05)]
        )
        with patch("src.services.portfolio_service.yf", yf_mock):
            self.service.refresh_fx_rates(account_id=account["id"], as_of=date(2026, 1, 8))
        self.assertEqual(yf_mock.Ticker.return_value.history.call_count, 2)  # 1h + 1d

    def test_fx_refresh_without_as_of_bar_saves_last_bar_under_its_own_date(self) -> None:
        # No bar for as_of itself: today's row takes the last close (old behaviour)
        # and that bar is also saved under its own date.
        frame = self._fx_frame([("2026-01-05", 7.01), ("2026-01-07", 7.03)])
        self._refresh_usd_with_frame(frame, date(2026, 1, 8))
        self.assertAlmostEqual(self._fx_row(date(2026, 1, 8)).rate, 7.03)
        self.assertEqual(self._fx_row(date(2026, 1, 8)).source, "yfinance")
        self.assertAlmostEqual(self._fx_row(date(2026, 1, 7)).rate, 7.03)

    def test_fx_refresh_cny_account_does_not_fetch_aggregate_pair(self) -> None:
        account = self.service.create_account(name="CN", broker="Demo", market="cn", base_currency="CNY")
        self.service.record_cash_ledger(
            account_id=account["id"], event_date=date(2026, 1, 1), direction="in", amount=1000.0, currency="CNY"
        )
        with patch.object(PortfolioService, "_fetch_fx_closes_from_yfinance", side_effect=AssertionError("should not call")):
            summary = self.service.refresh_fx_rates(account_id=account["id"], as_of=date(2026, 1, 2))
        self.assertEqual(summary["pair_count"], 0)

    def _usd_and_twd_accounts(self):
        """正式站形狀：台幣帳戶有 TWD->CNY，美元帳戶（後建）從沒刷新過 USD->CNY。"""
        tw = self.service.create_account(name="TW", broker="Demo", market="tw", base_currency="TWD")
        us = self.service.create_account(name="US", broker="Demo", market="us", base_currency="USD")
        self.service.record_cash_ledger(
            account_id=tw["id"], event_date=date(2026, 1, 1), direction="in", amount=1000.0, currency="TWD"
        )
        self.service.record_cash_ledger(
            account_id=us["id"], event_date=date(2026, 1, 1), direction="in", amount=100.0, currency="USD"
        )
        self.service.repo.save_fx_rate(
            from_currency="TWD", to_currency="CNY", rate_date=date(2026, 1, 2),
            rate=0.2, source="manual", is_stale=False,
        )
        return tw["id"], us["id"]

    def test_snapshot_flags_missing_fx_instead_of_passing_one_to_one_as_converted(self) -> None:
        _, us_id = self._usd_and_twd_accounts()

        snapshot = self.service.get_portfolio_snapshot(as_of=date(2026, 1, 2), include_realtime=False)

        self.assertTrue(snapshot["fx_missing"])
        self.assertEqual(snapshot["fx_missing_pairs"], ["USD/CNY"])
        accounts = {item["account_id"]: item for item in snapshot["accounts"]}
        # USD 帳戶自己的金額沒問題（帳戶幣別內），換到 CNY 的那個數字不能給 1:1 的假值
        self.assertFalse(accounts[us_id]["fx_missing"])
        self.assertIsNone(accounts[us_id]["total_market_value_aggregate"])
        self.assertAlmostEqual(accounts[us_id]["total_cash"], 100.0, places=6)

    def test_snapshot_without_missing_fx_keeps_flag_false(self) -> None:
        # 反向：匯率齊全時不得標成缺匯率，換算值照常給。
        _, us_id = self._usd_and_twd_accounts()
        self.service.repo.save_fx_rate(
            from_currency="USD", to_currency="CNY", rate_date=date(2026, 1, 2),
            rate=7.0, source="manual", is_stale=False,
        )

        snapshot = self.service.get_portfolio_snapshot(as_of=date(2026, 1, 2), include_realtime=False)

        self.assertFalse(snapshot["fx_missing"])
        self.assertEqual(snapshot["fx_missing_pairs"], [])
        self.assertAlmostEqual(snapshot["total_cash"], 200.0 + 700.0, places=6)
        accounts = {item["account_id"]: item for item in snapshot["accounts"]}
        self.assertIsNotNone(accounts[us_id]["total_market_value_aggregate"])
        self.assertFalse(snapshot["fx_stale"])

    def _risk_fx_fixture(self, usd_rate_date):
        """TWD 帳戶（有匯率）+ USD 帳戶持 AAPL；USD->CNY 只在 usd_rate_date 有（None 表示全程缺）。"""
        tw_id, us_id = self._usd_and_twd_accounts()
        self.service.repo.save_fx_rate(
            from_currency="TWD", to_currency="CNY", rate_date=date(2026, 1, 1),
            rate=0.2, source="manual", is_stale=False,
        )
        self.service.record_trade(
            account_id=us_id, symbol="AAPL", trade_date=date(2026, 1, 1), side="buy",
            quantity=1, price=50, market="us", currency="USD",
        )
        for day in (1, 2, 3):
            self._save_close("AAPL", date(2026, 1, day), 50.0)
        if usd_rate_date is not None:
            self.service.repo.save_fx_rate(
                from_currency="USD", to_currency="CNY", rate_date=usd_rate_date,
                rate=7.0, source="manual", is_stale=False,
            )
        return tw_id, us_id

    def test_risk_drawdown_excludes_dates_with_missing_fx_and_flags(self) -> None:
        self._risk_fx_fixture(date(2026, 1, 3))

        report = self.risk_service.get_risk_report(as_of=date(2026, 1, 3), cost_method="fifo")

        dd = report["drawdown"]
        self.assertTrue(dd["fx_missing"])
        self.assertEqual(dd["fx_missing_pairs"], ["USD/CNY"])
        # 1/1、1/2 美元帳戶沒有匯率：整天剔除，只剩 1/3 一個點，不拿 1:1 假 NAV 算回撤
        self.assertEqual(dd["fx_excluded_dates"], ["2026-01-01", "2026-01-02"])
        self.assertEqual(dd["series_points"], 1)

    def test_risk_drawdown_excludes_days_snapshot_flagged_fx_missing_in_account(self) -> None:
        # TWD 帳戶持有 USD 現金、沒有 USD/TWD：TWD->CNY 查得到，但帳戶 equity 本身已是 1:1 假數字。
        tw = self.service.create_account(name="TW", broker="Demo", market="tw", base_currency="TWD")
        self.service.record_cash_ledger(
            account_id=tw["id"], event_date=date(2026, 1, 1), direction="in", amount=1000.0, currency="TWD"
        )
        self.service.record_cash_ledger(
            account_id=tw["id"], event_date=date(2026, 1, 1), direction="in", amount=100.0, currency="USD"
        )
        self.service.repo.save_fx_rate(
            from_currency="TWD", to_currency="CNY", rate_date=date(2026, 1, 1),
            rate=0.2, source="manual", is_stale=False,
        )

        report = self.risk_service.get_risk_report(as_of=date(2026, 1, 3), cost_method="fifo")

        dd = report["drawdown"]
        # Payload flags only exclude their days; fx_missing still reflects the current rate table (TWD->CNY is present).
        self.assertFalse(dd["fx_missing"])
        self.assertEqual(dd["fx_missing_pairs"], [])
        self.assertEqual(dd["fx_excluded_dates"], ["2026-01-01", "2026-01-02", "2026-01-03"])
        self.assertEqual(dd["series_points"], 0)
        self.assertEqual(dd["data_quality"], "partial")

    def test_risk_drawdown_data_quality_partial_only_when_dates_excluded(self) -> None:
        self._risk_fx_fixture(date(2026, 1, 3))
        partial = self.risk_service.get_risk_report(as_of=date(2026, 1, 3), cost_method="fifo")["drawdown"]
        self.assertEqual(partial["data_quality"], "partial")

    def test_risk_drawdown_with_all_fx_present_is_unchanged(self) -> None:
        # 反向：匯率齊全時不剔除任何一天、不標旗標。
        self._risk_fx_fixture(date(2026, 1, 1))

        report = self.risk_service.get_risk_report(as_of=date(2026, 1, 3), cost_method="fifo")

        dd = report["drawdown"]
        self.assertFalse(dd["fx_missing"])
        self.assertEqual(dd["fx_missing_pairs"], [])
        self.assertEqual(dd["fx_excluded_dates"], [])
        self.assertEqual(dd["data_quality"], "ok")
        self.assertEqual(dd["series_points"], 3)
        self.assertFalse(report["concentration"]["fx_missing"])
        self.assertIsNotNone(report["concentration"]["top_weight_pct"])

    def test_risk_concentration_hides_weights_when_fx_missing(self) -> None:
        self._risk_fx_fixture(None)

        report = self.risk_service.get_risk_report(as_of=date(2026, 1, 2), cost_method="fifo")

        for block, rows_key in (("concentration", "top_positions"), ("sector_concentration", "top_sectors")):
            conc = report[block]
            self.assertTrue(conc["fx_missing"], block)
            self.assertEqual(conc["fx_missing_pairs"], ["USD/CNY"], block)
            self.assertIsNone(conc["top_weight_pct"], block)
            self.assertFalse(conc["alert"], block)
            self.assertTrue(all(r["weight_pct"] is None and not r["is_alert"] for r in conc[rows_key]), block)

    def test_fx_rate_older_than_max_age_reads_as_stale(self) -> None:
        # is_stale 是寫入時的旗標：10-15 刷新一次後 10-23 仍標「最新」。讀取端要看匯率日期。
        account = self.service.create_account(name="TW", broker="Demo", market="tw", base_currency="TWD")
        self.service.record_cash_ledger(
            account_id=account["id"], event_date=date(2026, 1, 1), direction="in", amount=1000.0, currency="TWD"
        )
        self.service.repo.save_fx_rate(
            from_currency="TWD", to_currency="CNY", rate_date=date(2026, 1, 1),
            rate=0.2, source="manual", is_stale=False,
        )

        fresh = self.service.get_portfolio_snapshot(as_of=date(2026, 1, 4), include_realtime=False)
        old = self.service.get_portfolio_snapshot(as_of=date(2026, 1, 9), include_realtime=False)

        # 3 天內（涵蓋週末）仍算最新，8 天前就是過期
        self.assertFalse(fresh["fx_stale"])
        self.assertTrue(old["fx_stale"])
        self.assertFalse(old["fx_missing"])

    def _twd_account_with_daily_snapshots(self, days: int):
        """正式站形狀：TWD 帳戶每天都有 daily snapshot，匯率只在第一天刷新過一次。"""
        account = self.service.create_account(name="TW", broker="Demo", market="tw", base_currency="TWD")
        self.service.record_cash_ledger(
            account_id=account["id"], event_date=date(2026, 1, 1), direction="in", amount=1000.0, currency="TWD"
        )
        self.service.repo.save_fx_rate(
            from_currency="TWD", to_currency="CNY", rate_date=date(2026, 1, 1),
            rate=0.2, source="manual", is_stale=False,
        )
        for offset in range(days):
            self.service.get_portfolio_snapshot(
                account_id=account["id"], as_of=date(2026, 1, 1) + timedelta(days=offset), include_realtime=False
            )
        return account["id"]

    def test_drawdown_fx_stale_ignores_rate_age_of_historical_rows(self) -> None:
        # 回撤逐日換算查得到的是「當天之前最後一次刷新」的匯率；刷新只寫今天，套年齡判定的話
        # 歷史列永遠過期、按「刷新匯率」也救不回來（10-15 刷新後 10-19~10-22 全被判過期）。
        aid = self._twd_account_with_daily_snapshots(12)
        as_of = date(2026, 1, 12)

        before = self.risk_service.get_risk_report(account_id=aid, as_of=as_of, cost_method="fifo", include_realtime=False)
        stale_top = self.service.get_portfolio_snapshot(
            account_id=aid, as_of=as_of, include_realtime=False, read_only=True
        )["fx_stale"]
        self.service.repo.save_fx_rate(
            from_currency="TWD", to_currency="CNY", rate_date=as_of, rate=0.2, source="manual", is_stale=False,
        )
        after = self.risk_service.get_risk_report(account_id=aid, as_of=as_of, cost_method="fifo", include_realtime=False)

        self.assertGreater(before["drawdown"]["series_points"], 1)
        self.assertFalse(before["drawdown"]["fx_stale"])
        self.assertFalse(after["drawdown"]["fx_stale"])
        # 快照頂部（估值日）仍看年齡：刷新前過期、刷新後恢復
        self.assertTrue(stale_top)
        self.assertFalse(self.service.get_portfolio_snapshot(
            account_id=aid, as_of=as_of, include_realtime=False, read_only=True)["fx_stale"])

    def test_drawdown_still_flags_rates_written_as_stale(self) -> None:
        # 反向：寫入時就標 is_stale 的匯率（線上抓取失敗、沿用舊值）仍要讓回撤標過期。
        aid = self._twd_account_with_daily_snapshots(3)
        self.service.repo.save_fx_rate(
            from_currency="TWD", to_currency="CNY", rate_date=date(2026, 1, 2),
            rate=0.2, source="cache_fallback", is_stale=True,
        )

        report = self.risk_service.get_risk_report(
            account_id=aid, as_of=date(2026, 1, 3), cost_method="fifo", include_realtime=False
        )

        self.assertTrue(report["drawdown"]["fx_stale"])

    def test_rate_age_of_past_trade_conversion_does_not_mark_current_view_stale(self) -> None:
        # 反向：交易日的手續費按「當時」匯率換算，那時的匯率本來就可能是好幾天前刷新的；
        # 估值日的匯率已刷新時，快照不能因為歷史換算而標過期。
        account = self.service.create_account(name="TW", broker="Demo", market="tw", base_currency="TWD")
        self.service.record_cash_ledger(
            account_id=account["id"], event_date=date(2026, 1, 1), direction="in", amount=10000.0, currency="USD"
        )
        self.service.record_trade(
            account_id=account["id"], symbol="AAPL", trade_date=date(2026, 1, 10), side="buy",
            quantity=1, price=100, fee=1.0, market="us", currency="USD",
        )
        for rate_date in (date(2026, 1, 1), date(2026, 1, 20)):
            self.service.repo.save_fx_rate(
                from_currency="USD", to_currency="TWD", rate_date=rate_date, rate=30.0, source="manual", is_stale=False,
            )
            self.service.repo.save_fx_rate(
                from_currency="TWD", to_currency="CNY", rate_date=rate_date, rate=0.2, source="manual", is_stale=False,
            )

        snapshot = self.service.get_portfolio_snapshot(
            account_id=account["id"], as_of=date(2026, 1, 20), include_realtime=False, read_only=True
        )

        self.assertFalse(snapshot["fx_stale"])
        self.assertFalse(snapshot["accounts"][0]["fx_stale"])

    def test_daily_snapshot_row_does_not_persist_rate_age(self) -> None:
        # 帳戶內換算（USD 現金 → TWD 帳戶）用到舊匯率：當下的快照標過期，但落庫的 daily snapshot
        # fx_stale 不能存年齡判定——回撤監控會把它 OR 180 天。
        account = self.service.create_account(name="TW", broker="Demo", market="tw", base_currency="TWD")
        self.service.record_cash_ledger(
            account_id=account["id"], event_date=date(2026, 1, 1), direction="in", amount=100.0, currency="USD"
        )
        for pair in (("USD", "TWD"), ("TWD", "CNY")):
            self.service.repo.save_fx_rate(
                from_currency=pair[0], to_currency=pair[1], rate_date=date(2026, 1, 1),
                rate=30.0 if pair[0] == "USD" else 0.2, source="manual", is_stale=False,
            )

        snapshot = self.service.get_portfolio_snapshot(
            account_id=account["id"], as_of=date(2026, 1, 10), include_realtime=False
        )
        rows = self.service.repo.list_daily_snapshots_for_risk(
            as_of=date(2026, 1, 10), cost_method="fifo", account_id=account["id"], lookback_days=30
        )

        self.assertTrue(snapshot["fx_stale"])
        self.assertTrue(snapshot["accounts"][0]["fx_stale"])
        self.assertEqual([row.fx_stale for row in rows if row.snapshot_date == date(2026, 1, 10)], [False])

    def test_fx_refresh_disabled_returns_real_pair_count_without_fetching(self) -> None:
        account = self.service.create_account(name="US", broker="Demo", market="us", base_currency="CNY")
        aid = account["id"]
        self.service.record_cash_ledger(
            account_id=aid,
            event_date=date(2026, 1, 1),
            direction="in",
            amount=1000.0,
            currency="USD",
        )

        disabled_config = SimpleNamespace(portfolio_fx_update_enabled=False)
        with patch("src.services.portfolio_service.get_config", return_value=disabled_config) as get_config_mock, patch.object(
            PortfolioService,
            "_fetch_fx_closes_from_yfinance",
            side_effect=AssertionError("should not call"),
        ), patch.object(self.service.repo, "save_fx_rate", wraps=self.service.repo.save_fx_rate) as save_fx_rate_mock:
            summary = self.service.refresh_fx_rates(account_id=aid, as_of=date(2026, 1, 2))

        self.assertFalse(summary["refresh_enabled"])
        self.assertEqual(summary["disabled_reason"], "portfolio_fx_update_disabled")
        self.assertEqual(summary["pair_count"], 1)
        self.assertEqual(summary["updated_count"], 0)
        self.assertEqual(summary["stale_count"], 0)
        self.assertEqual(summary["error_count"], 0)
        get_config_mock.assert_called_once()
        save_fx_rate_mock.assert_not_called()

    def test_fx_refresh_disabled_skips_invalid_currency_rows(self) -> None:
        account = self.service.create_account(name="US", broker="Demo", market="us", base_currency="CNY")
        aid = account["id"]

        disabled_config = SimpleNamespace(portfolio_fx_update_enabled=False)
        invalid_row = SimpleNamespace(currency="")
        valid_row = SimpleNamespace(currency="USD")
        with patch("src.services.portfolio_service.get_config", return_value=disabled_config), patch.object(
            self.service.repo,
            "list_trades",
            return_value=[invalid_row, valid_row],
        ), patch.object(
            self.service.repo,
            "list_cash_ledger",
            return_value=[],
        ), patch.object(
            PortfolioService,
            "_fetch_fx_closes_from_yfinance",
            side_effect=AssertionError("should not call"),
        ):
            summary = self.service.refresh_fx_rates(account_id=aid, as_of=date(2026, 1, 2))

        self.assertFalse(summary["refresh_enabled"])
        self.assertEqual(summary["pair_count"], 1)
        self.assertEqual(summary["updated_count"], 0)
        self.assertEqual(summary["stale_count"], 0)
        self.assertEqual(summary["error_count"], 0)

    def test_fx_refresh_endpoint_returns_disabled_status_fields(self) -> None:
        account = self.service.create_account(name="US", broker="Demo", market="us", base_currency="CNY")
        account_id = account["id"]
        self.service.record_cash_ledger(
            account_id=account_id,
            event_date=date(2026, 1, 1),
            direction="in",
            amount=1000.0,
            currency="USD",
        )

        disabled_config = SimpleNamespace(portfolio_fx_update_enabled=False)
        with patch("src.services.portfolio_service.get_config", return_value=disabled_config), patch.object(
            PortfolioService,
            "_fetch_fx_closes_from_yfinance",
            side_effect=AssertionError("should not call"),
        ):
            response = self.client.post(
                "/api/v1/portfolio/fx/refresh",
                params={"account_id": account_id, "as_of": "2026-01-02"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["refresh_enabled"])
        self.assertEqual(payload["disabled_reason"], "portfolio_fx_update_disabled")
        self.assertEqual(payload["pair_count"], 1)
        self.assertEqual(payload["updated_count"], 0)
        self.assertEqual(payload["stale_count"], 0)
        self.assertEqual(payload["error_count"], 0)

    def test_fx_refresh_endpoint_returns_enabled_status_fields(self) -> None:
        account = self.service.create_account(name="US", broker="Demo", market="us", base_currency="CNY")
        account_id = account["id"]
        self.service.record_cash_ledger(
            account_id=account_id,
            event_date=date(2026, 1, 1),
            direction="in",
            amount=1000.0,
            currency="USD",
        )

        with patch.object(PortfolioService, "_fetch_fx_closes_from_yfinance", return_value=[]):
            response = self.client.post(
                "/api/v1/portfolio/fx/refresh",
                params={"account_id": account_id, "as_of": "2026-01-02"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["refresh_enabled"])
        self.assertIsNone(payload["disabled_reason"])
        self.assertEqual(payload["pair_count"], 1)
        self.assertEqual(payload["updated_count"], 0)
        self.assertEqual(payload["stale_count"], 0)
        self.assertEqual(payload["error_count"], 1)

    def test_import_and_risk_endpoints(self) -> None:
        create_resp = self.client.post(
            "/api/v1/portfolio/accounts",
            json={"name": "Main", "broker": "Demo", "market": "cn", "base_currency": "CNY"},
        )
        self.assertEqual(create_resp.status_code, 200)
        account_id = create_resp.json()["id"]

        import_resp = self.client.post(
            "/api/v1/portfolio/imports/csv/commit",
            data={"account_id": str(account_id), "broker": "huatai", "dry_run": "false"},
            files={"file": ("huatai.csv", self._csv_bytes(with_trade_uid=True), "text/csv")},
        )
        self.assertEqual(import_resp.status_code, 200)
        self.assertEqual(import_resp.json()["inserted_count"], 1)

        self._save_close("600519", date(2026, 1, 2), 95.0)
        self.service.get_portfolio_snapshot(account_id=account_id, as_of=date(2026, 1, 2), cost_method="fifo")
        risk_resp = self.client.get(
            "/api/v1/portfolio/risk",
            params={"account_id": account_id, "as_of": "2026-01-02", "cost_method": "fifo"},
        )
        self.assertEqual(risk_resp.status_code, 200)
        payload = risk_resp.json()
        self.assertEqual(payload["cost_method"], "fifo")
        self.assertIn("concentration", payload)
        self.assertIn("sector_concentration", payload)
        self.assertIn("drawdown", payload)
        self.assertIn("stop_loss", payload)

    # ---- review follow-ups: cross rows stay automated, next-neighbour uses cross, stale carry from repairs ----
    def test_fx_refresh_overwrites_stored_cross_row_with_correct_value(self) -> None:
        days = [date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 8)]
        pair = list(zip(days, [0.2054, 0.2050, 0.2050]))
        twd = [(d, 32.6) for d in days]
        cny = [(d, 6.665) for d in days]
        self.service.repo.save_fx_rate(
            from_currency="TWD", to_currency="CNY", rate_date=days[1], rate=0.1840,
            source="yfinance_cross", is_stale=False,
        )
        self._refresh_twd_cny(pair, twd, cny, days[2], days[2])
        row = self._twd_row(days[1])
        self.assertAlmostEqual(row.rate, 0.2050)
        self.assertEqual(row.source, "yfinance_backfill")

    def test_fx_refresh_cross_row_wrong_is_repaired_again(self) -> None:
        pair, twd, cny = self._junk_window()
        self.service.repo.save_fx_rate(
            from_currency="TWD", to_currency="CNY", rate_date=date(2026, 1, 7), rate=0.1840,
            source="yfinance_cross", is_stale=False,
        )
        self._refresh_twd_cny(pair, twd, cny, date(2026, 1, 8), date(2026, 1, 8))
        self.assertAlmostEqual(self._twd_row(date(2026, 1, 7)).rate, 6.665 / 32.6)

    def test_fx_outlier_next_neighbour_uses_cross_when_next_is_rejected(self) -> None:
        closes = [(date(2026, 1, 6), 0.2054), (date(2026, 1, 7), 0.1963), (date(2026, 1, 8), 0.1963)]
        out = self._filter(closes, pair=("TWD", "CNY"), cross_closes=self._cross(6, 8))
        self.assertEqual(out, closes[:1])

    def test_fx_outlier_next_neighbour_cross_keeps_real_jump(self) -> None:
        closes = [(date(2026, 1, 6), 0.2054), (date(2026, 1, 7), 0.2200), (date(2026, 1, 8), 0.2201)]
        cross = {date(2026, 1, 6): 0.2054, date(2026, 1, 8): 0.2200}
        self.assertEqual(self._filter(closes, pair=("TWD", "CNY"), cross_closes=cross), closes)

    def test_fx_refresh_stale_carry_starts_from_newer_repaired_day(self) -> None:
        pair, twd, cny = self._junk_window()
        self._refresh_twd_cny(pair, twd, cny, date(2026, 1, 8), date(2026, 1, 8))
        today = self._twd_row(date(2026, 1, 8))
        self.assertTrue(today.is_stale)
        self.assertAlmostEqual(today.rate, 6.665 / 32.6)  # not 0.2054 from 01-06

    def test_fx_refresh_stale_carry_ignores_repair_not_older_than_accepted(self) -> None:
        days = [date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 8)]
        pair = list(zip(days, [0.1963, 0.2054, 0.1963]))  # junk on 01-06 (repaired), 01-07 accepted
        self._refresh_twd_cny(pair, [(d, 32.6) for d in days], [(d, 6.665) for d in days], days[2], days[2])
        self.assertAlmostEqual(self._twd_row(days[2]).rate, 0.2054)


    # ---- release-gate follow-ups: all-rejected carry, empty-main skips cross legs, refresh time budget ----
    def _seed_twd(self, on_date, rate, source, is_stale):
        self.service.repo.save_fx_rate(
            from_currency="TWD", to_currency="CNY", rate_date=on_date, rate=rate, source=source, is_stale=is_stale
        )

    def test_fx_refresh_all_bars_rejected_does_not_carry_stored_junk_today(self) -> None:
        days = [date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 8)]
        pair = list(zip(days, [0.1963] * 3))  # every bar is junk, cross says 0.2045
        self._seed_twd(date(2026, 1, 8), 0.1963, "yfinance", False)  # junk already stored for today
        self._refresh_twd_cny(pair, [(d, 32.6) for d in days], [(d, 6.665) for d in days], days[2], days[2])
        today = self._twd_row(days[2])
        self.assertTrue(today.is_stale)
        self.assertAlmostEqual(today.rate, 6.665 / 32.6)  # newest repaired day, never 0.1963

    def test_fx_refresh_all_bars_rejected_carries_repair_even_if_backfill_wrote_nothing(self) -> None:
        days = [date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 8)]
        self._seed_twd(days[2], 0.1963, "yfinance", False)
        with patch.object(PortfolioService, "_backfill_fx_history"):
            self._refresh_twd_cny(
                list(zip(days, [0.1963] * 3)), [(d, 32.6) for d in days], [(d, 6.665) for d in days], days[2], days[2]
            )
        self.assertAlmostEqual(self._twd_row(days[2]).rate, 6.665 / 32.6)

    def test_fx_refresh_all_bars_rejected_without_repair_uses_last_real_row_not_junk(self) -> None:
        d8 = date(2026, 1, 8)
        self._seed_twd(date(2026, 1, 3), 0.2050, "manual", False)
        self._seed_twd(d8, 0.1963, "yfinance", False)
        # Cross rate only exists for today (not repairable: today is unfinished), so nothing is repaired.
        self._refresh_twd_cny([(d8, 0.1963)], [(d8, 32.6)], [(d8, 6.665)], d8, d8)
        row = self._twd_row(d8)
        self.assertTrue(row.is_stale)
        self.assertAlmostEqual(row.rate, 0.2050)

    def test_fx_refresh_all_bars_rejected_without_any_clean_source_drops_junk_row_and_marks_missing(self) -> None:
        d8 = date(2026, 1, 8)
        self._seed_twd(d8, 0.1963, "yfinance", False)
        self._refresh_twd_cny([(d8, 0.1963)], [(d8, 32.6)], [(d8, 6.665)], d8, d8)
        self.assertIsNone(self._twd_row(d8))  # the junk row is gone, nothing replaces it
        snapshot = self.service.get_portfolio_snapshot(as_of=d8, cost_method="fifo")
        self.assertTrue(snapshot["fx_missing"])
        self.assertIn("TWD/CNY", snapshot["fx_missing_pairs"])

    def test_fx_refresh_all_bars_rejected_keeps_manual_row(self) -> None:
        d8 = date(2026, 1, 8)
        self._seed_twd(d8, 0.1963, "manual", False)
        self._refresh_twd_cny([(d8, 0.1963)], [(d8, 32.6)], [(d8, 6.665)], d8, d8)
        self.assertAlmostEqual(self._twd_row(d8).rate, 0.1963)
        self.assertEqual(self._twd_row(d8).source, "manual")

    def _refresh_rejected_friday(self):
        friday, saturday = date(2026, 10, 23), date(2026, 10, 24)
        with patch.object(PortfolioService, "_fetch_fx_cross_closes", return_value={}), patch.object(
            PortfolioService, "_fetch_fx_cross_rate", return_value=0.2045
        ):
            self._refresh_twd_cny([(friday, 0.1963)], [], [], saturday, saturday)
        return friday, saturday

    def test_fx_all_rejected_skips_stored_junk_before_as_of_and_keeps_earlier_real_rate(self) -> None:
        for safe_source in ("manual", "yfinance_backfill"):
            with self.subTest(safe_source=safe_source):
                self._seed_twd(date(2026, 10, 22), 0.2045, safe_source, False)
                self._seed_twd(date(2026, 10, 23), 0.1963, "yfinance_backfill", False)
                friday, saturday = self._refresh_rejected_friday()
                self.assertIsNone(self._twd_row(friday))
                row = self._twd_row(saturday)
                self.assertAlmostEqual(row.rate, 0.2045)
                self.assertTrue(row.is_stale)
                self.assertEqual(self._twd_row(date(2026, 10, 22)).source, safe_source)

    def test_fx_all_rejected_without_clean_rate_cannot_reuse_prior_junk_in_snapshot(self) -> None:
        self._seed_twd(date(2026, 10, 23), 0.1963, "yfinance_backfill", False)
        self._seed_twd(date(2026, 10, 24), 0.1963, "yfinance", False)
        friday, saturday = self._refresh_rejected_friday()
        self.assertIsNone(self._twd_row(friday))
        self.assertIsNone(self._twd_row(saturday))
        snapshot = self.service.get_portfolio_snapshot(as_of=saturday, include_realtime=False)
        self.assertTrue(snapshot["fx_missing"])
        self.assertEqual(snapshot["fx_missing_pairs"], ["TWD/CNY"])

    def test_fx_all_rejected_preserves_manual_and_valid_auto_rates_on_rejected_prior_date(self) -> None:
        for source, rate in (("manual", 0.1900), ("yfinance_backfill", 0.2030)):
            with self.subTest(source=source):
                self._seed_twd(date(2026, 10, 23), rate, source, False)
                friday, saturday = self._refresh_rejected_friday()
                self.assertEqual(self._twd_row(friday).source, source)
                self.assertAlmostEqual(self._twd_row(friday).rate, rate)
                self.assertAlmostEqual(self._twd_row(saturday).rate, rate)
                self.assertTrue(self._twd_row(saturday).is_stale)

    def test_fx_refresh_empty_main_series_skips_cross_legs(self) -> None:
        account = self.service.create_account(name="TW", broker="Demo", market="tw", base_currency="TWD")
        self.service.record_cash_ledger(
            account_id=account["id"], event_date=date(2026, 1, 1), direction="in", amount=1000.0, currency="TWD"
        )
        calls = []

        def fake(*, from_currency, to_currency, as_of_date):
            calls.append((from_currency, to_currency))
            return []

        with patch("src.services.portfolio_service.yf", MagicMock()), patch.object(
            PortfolioService, "_fetch_fx_closes_from_yfinance", side_effect=fake
        ):
            self.service.refresh_fx_rates(account_id=account["id"], as_of=date(2026, 1, 8))
        self.assertEqual(calls, [("TWD", "CNY")])  # no USD legs

    def test_fx_refresh_budget_exhausted_stops_network_calls_and_uses_stale_fallback(self) -> None:
        import src.services.portfolio_service as ps

        d8 = date(2026, 1, 8)
        self._seed_twd(date(2026, 1, 7), 0.2050, "yfinance", False)
        account = self.service.create_account(name="TW", broker="Demo", market="tw", base_currency="TWD")
        self.service.record_cash_ledger(
            account_id=account["id"], event_date=date(2026, 1, 1), direction="in", amount=1000.0, currency="TWD"
        )
        clock = {"now": 0.0}
        yf_mock = MagicMock()

        def slow_history(*args, **kwargs):
            clock["now"] += 100.0  # the first request eats the whole budget
            return pd.DataFrame()

        yf_mock.Ticker.return_value.history.side_effect = slow_history
        with patch("src.services.portfolio_service.yf", yf_mock), patch.object(
            ps.time, "monotonic", side_effect=lambda: clock["now"]
        ):
            summary = self.service.refresh_fx_rates(account_id=account["id"], as_of=d8)
        self.assertEqual(yf_mock.Ticker.return_value.history.call_count, 1)
        self.assertEqual(summary["stale_count"], 1)
        self.assertAlmostEqual(self._twd_row(d8).rate, 0.2050)

    def test_fx_history_passes_remaining_budget_as_timeout(self) -> None:
        import src.services.portfolio_service as ps

        yf_mock = MagicMock()
        yf_mock.Ticker.return_value.history.return_value = pd.DataFrame()
        token = ps._FX_DEADLINE.set(5.0)
        try:
            with patch("src.services.portfolio_service.yf", yf_mock), patch.object(
                ps.time, "monotonic", return_value=2.0
            ):
                PortfolioService._fetch_fx_closes_from_yfinance(
                    from_currency="USD", to_currency="CNY", as_of_date=date(2026, 1, 8)
                )
        finally:
            ps._FX_DEADLINE.reset(token)
        timeouts = [c.kwargs["timeout"] for c in yf_mock.Ticker.return_value.history.call_args_list]
        self.assertTrue(timeouts and all(abs(t - 3.0) < 1e-9 for t in timeouts))

    def _slow_yf(self, delay):
        import time as _t

        written = []

        def history(*args, **kwargs):
            _t.sleep(delay)
            written.append(1)
            return pd.DataFrame({"Close": [0.2050]}, index=pd.to_datetime(["2026-01-08 12:00"]).tz_localize("UTC"))

        yf_mock = MagicMock()
        yf_mock.Ticker.return_value.history.side_effect = history
        return yf_mock

    def test_fx_refresh_returns_within_budget_when_yfinance_hangs(self) -> None:
        import time as _t

        import src.services.portfolio_service as ps

        d8 = date(2026, 1, 8)
        self._seed_twd(date(2026, 1, 7), 0.2050, "yfinance", False)
        account = self.service.create_account(name="TW", broker="Demo", market="tw", base_currency="TWD")
        self.service.record_cash_ledger(
            account_id=account["id"], event_date=date(2026, 1, 1), direction="in", amount=1000.0, currency="TWD"
        )
        with patch("src.services.portfolio_service.yf", self._slow_yf(2.0)), patch.object(
            ps, "FX_REFRESH_BUDGET_SECONDS", 0.2
        ):
            started = _t.monotonic()
            summary = self.service.refresh_fx_rates(account_id=account["id"], as_of=d8)
            elapsed = _t.monotonic() - started
        self.assertLess(elapsed, 0.2 + 0.5)
        self.assertEqual(summary["stale_count"], 1)  # fell back to the stored 01-07 value
        self.assertTrue(self._twd_row(d8).is_stale)

    def test_fx_refresh_returns_within_budget_when_ticker_construction_blocks(self) -> None:
        # yf.Ticker() itself can wait on yfinance's shared locks; it must run inside the bounded worker.
        import time as _t

        import src.services.portfolio_service as ps

        d8 = date(2026, 1, 8)
        self._seed_twd(date(2026, 1, 7), 0.2050, "yfinance", False)
        account = self.service.create_account(name="TW", broker="Demo", market="tw", base_currency="TWD")
        self.service.record_cash_ledger(
            account_id=account["id"], event_date=date(2026, 1, 1), direction="in", amount=1000.0, currency="TWD"
        )
        yf_mock = MagicMock()
        yf_mock.Ticker.side_effect = lambda *a, **k: _t.sleep(2.0) or MagicMock()
        with patch("src.services.portfolio_service.yf", yf_mock), patch.object(ps, "FX_REFRESH_BUDGET_SECONDS", 0.2):
            started = _t.monotonic()
            summary = self.service.refresh_fx_rates(account_id=account["id"], as_of=d8)
            elapsed = _t.monotonic() - started
        self.assertLess(elapsed, 0.2 + 0.5)
        self.assertEqual(summary["stale_count"], 1)

    def test_fx_call_within_budget_is_used(self) -> None:
        import src.services.portfolio_service as ps

        token = ps._FX_DEADLINE.set(__import__("time").monotonic() + 5.0)
        try:
            with patch("src.services.portfolio_service.yf", self._slow_yf(0.05)):
                out = PortfolioService._fetch_fx_closes_from_yfinance(
                    from_currency="USD", to_currency="CNY", as_of_date=date(2026, 1, 8)
                )
        finally:
            ps._FX_DEADLINE.reset(token)
        self.assertEqual(out, [(date(2026, 1, 8), 0.2050)])


if __name__ == "__main__":
    unittest.main()
