# -*- coding: utf-8 -*-
"""只跑監控的開關、開盤時段閘門、通知來源行與狀態端點的守門測試。"""

from __future__ import annotations

import os
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from src.agent.events import PriceAlert, VolumeAlert
from src.notification import NotificationDispatchResult
from src.services import alert_worker as alert_worker_module
from src.services.alert_messages import format_generic_alert_markdown
from src.services.alert_worker import (
    ALERT_MONITOR_RUN_STATE,
    AlertMonitorThread,
    AlertWorker,
    RuntimeAlertRule,
    alert_monitor_channels,
    build_alert_monitor_status,
    run_recorded_cycle,
    start_alert_monitor_worker,
)
from src.services.data_capability_service import DataCapabilityService
from src.services.market_light_alerts import MarketLightAlert
from src.services.runtime_scheduler import RuntimeSchedulerService
from src.services.tw_level_alerts import format_level_alert_markdown


TAIPEI = timezone(timedelta(hours=8))


def _config(**overrides) -> SimpleNamespace:
    values = {
        "agent_event_monitor_enabled": True,
        "agent_event_monitor_without_schedule": True,
        "agent_event_monitor_interval_minutes": 5,
        "schedule_enabled": False,
        "schedule_time": "18:00",
        "schedule_times": [],
        "agent_event_alert_rules_json": "",
        "notification_alert_channels": [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class StartMonitorWorkerTests(unittest.TestCase):
    def test_both_switches_start_thread(self) -> None:
        with patch.object(AlertMonitorThread, "start", lambda self: self):
            handle = start_alert_monitor_worker(_config())
        self.assertIsInstance(handle, AlertMonitorThread)

    def test_default_off_returns_none(self) -> None:
        self.assertIsNone(start_alert_monitor_worker(_config(agent_event_monitor_without_schedule=False)))

    def test_monitor_flag_off_returns_none(self) -> None:
        self.assertIsNone(start_alert_monitor_worker(_config(agent_event_monitor_enabled=False)))

    def test_config_default_keeps_switch_off(self) -> None:
        from src.config import Config

        self.assertFalse(Config.__dataclass_fields__["agent_event_monitor_without_schedule"].default)

    def test_thread_keeps_running_after_a_failed_cycle(self) -> None:
        second_cycle = threading.Event()
        calls = []

        def run_once():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("db down")
            second_cycle.set()
            return {}

        worker = SimpleNamespace(run_once=run_once)
        handle = AlertMonitorThread(config_provider=_config, worker=worker)
        with patch.object(alert_worker_module, "_alert_monitor_interval_seconds", return_value=0):
            handle.start()
            self.assertTrue(second_cycle.wait(30))
        self.assertTrue(handle.is_active())
        handle.stop()
        self.assertFalse(handle.is_active())


class SchedulerOwnershipTests(unittest.TestCase):
    def _service(self, config) -> RuntimeSchedulerService:
        return RuntimeSchedulerService(config_provider=lambda: config, owns_schedule=True)

    def test_switch_on_keeps_monitor_out_of_scheduler(self) -> None:
        """排程與開關都開時只能有一份監控，否則重複推播。"""
        service = self._service(_config(schedule_enabled=True))
        with patch("src.services.runtime_scheduler.build_agent_event_monitor_background_tasks") as build:
            self.assertEqual(service._current_background_tasks(_config(schedule_enabled=True)), [])
        build.assert_not_called()

    def test_switch_off_scheduler_still_registers_monitor(self) -> None:
        config = _config(agent_event_monitor_without_schedule=False, schedule_enabled=True)
        service = self._service(config)
        entry = {"task": lambda: None, "interval_seconds": 300, "run_immediately": True, "name": "agent_event_monitor"}
        with patch(
            "src.services.runtime_scheduler.build_agent_event_monitor_background_tasks", return_value=[entry],
        ):
            tasks = service._current_background_tasks(config)
        self.assertEqual([task["name"] for task in tasks], ["agent_event_monitor"])

    def test_switch_on_does_not_start_daily_analysis_scheduler(self) -> None:
        service = self._service(_config())
        with patch("src.services.runtime_scheduler.Scheduler") as scheduler_cls:
            service.reconcile_from_config()
        scheduler_cls.assert_not_called()
        self.assertFalse(service.status()["enabled"])

    def test_lifespan_starts_thread_without_scheduler(self) -> None:
        from api.app import create_app

        started = MagicMock()
        scheduler_instance = MagicMock()
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "api.app.RuntimeSchedulerService", return_value=scheduler_instance,
        ), patch("api.app.SystemConfigService"), patch(
            "api.app._schedule_stock_index_background_refresh",
        ), patch("src.services.alert_worker.start_alert_monitor_worker", return_value=started) as start:
            app = create_app(static_dir=Path(temp_dir))
            with TestClient(app):
                self.assertIs(app.state.alert_monitor_thread, started)
        start.assert_called_once()
        started.stop.assert_called_once()

    def test_lifespan_skips_thread_when_cli_owns_schedule(self) -> None:
        from api.app import create_app
        from src.services.runtime_scheduler import CLI_SCHEDULER_OWNER_ENV

        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {CLI_SCHEDULER_OWNER_ENV: "true"}, clear=False,
        ), patch("api.app.RuntimeSchedulerService", return_value=MagicMock()), patch(
            "api.app.SystemConfigService",
        ), patch("api.app._schedule_stock_index_background_refresh"), patch(
            "src.services.alert_worker.start_alert_monitor_worker",
        ) as start:
            app = create_app(static_dir=Path(temp_dir))
            with TestClient(app):
                pass
        start.assert_not_called()


class SessionGateTests(unittest.TestCase):
    def _worker(self, rule, *, gate: bool):
        service = MagicMock()
        service._evaluate_rule = AsyncMock(return_value={
            "rule_id": 1, "record_status": None, "triggered": False, "status": "not_triggered",
        })
        worker = AlertWorker(
            config_provider=lambda: _config(),
            service=service,
            decision_signal_service=MagicMock(),
            notifier=MagicMock(),
            realtime_session_gate=gate,
        )
        worker._load_runtime_rules = lambda config: [RuntimeAlertRule(key="k", rule=rule, source="db")]
        return worker, service

    def test_closed_market_skips_realtime_rule_without_quote_or_write(self) -> None:
        worker, service = self._worker(PriceAlert(stock_code="2330.TW", direction="above", price=1), gate=True)
        with patch.object(alert_worker_module, "is_market_polling_window", return_value=False) as window:
            stats = worker.run_once()
        self.assertEqual(window.call_args.args[0], "tw")
        service._evaluate_rule.assert_not_called()
        service.repo.create_trigger.assert_not_called()
        self.assertEqual(stats["off_session"], 1)
        self.assertEqual(stats["evaluated"], 0)

    def test_open_market_evaluates(self) -> None:
        worker, service = self._worker(PriceAlert(stock_code="2330.TW", direction="above", price=1), gate=True)
        with patch.object(alert_worker_module, "is_market_polling_window", return_value=True) as window:
            stats = worker.run_once()
        service._evaluate_rule.assert_awaited_once()
        self.assertEqual(stats["evaluated"], 1)
        # 警報不沿用看板提前 5 分鐘的放行
        self.assertEqual(window.call_args.kwargs["before"], timedelta(0))

    def test_scheduler_path_without_gate_is_unchanged(self) -> None:
        worker, service = self._worker(PriceAlert(stock_code="2330.TW", direction="above", price=1), gate=False)
        with patch.object(alert_worker_module, "is_market_polling_window", return_value=False) as window:
            worker.run_once()
        window.assert_not_called()
        service._evaluate_rule.assert_awaited_once()

    def test_daily_data_rule_is_not_gated(self) -> None:
        worker, service = self._worker(VolumeAlert(stock_code="2330.TW", multiplier=2.0), gate=True)
        with patch.object(alert_worker_module, "is_market_polling_window", return_value=False):
            worker.run_once()
        service._evaluate_rule.assert_awaited_once()

    def _market_rule(self, *, market_is_open: bool) -> MarketLightAlert:
        return MarketLightAlert(
            target_scope="market", target="tw", alert_type="market_light_status",
            parameters={"statuses": ["red"]},
            metadata={"persisted_rule_id": 1, "trading_day_check_enabled": True, "market_is_open": market_is_open},
        )

    def test_market_rule_on_closed_day_writes_no_skipped_row(self) -> None:
        worker, service = self._worker(self._market_rule(market_is_open=False), gate=True)
        stats = worker.run_once()
        service._evaluate_rule.assert_not_called()
        self.assertEqual(stats["off_session"], 1)

    def test_market_rule_on_trading_day_evaluates(self) -> None:
        worker, service = self._worker(self._market_rule(market_is_open=True), gate=True)
        worker.run_once()
        service._evaluate_rule.assert_awaited_once()

    def test_monitor_thread_worker_turns_gate_on(self) -> None:
        handle = AlertMonitorThread(config_provider=_config)
        captured = {}

        def fake_worker(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(run_once=lambda: {})

        with patch.object(alert_worker_module, "AlertWorker", fake_worker):
            handle._run_cycle()
        self.assertTrue(captured["realtime_session_gate"])


class NotificationSourceTests(unittest.TestCase):
    def _result(self, **overrides):
        result = {
            "observed_value": 1010.0,
            "threshold": 1000.0,
            "reason": "2330.TW price above 1000",
            "data_source": "realtime_quote",
            "diagnostics": {"quote_source": "shioaji"},
        }
        result.update(overrides)
        return result

    def test_price_message_is_markdown_with_source(self) -> None:
        text = format_generic_alert_markdown(
            target="台積電 2330.TW",
            rule=PriceAlert(stock_code="2330.TW", direction="above", price=1000.0),
            result=self._result(),
            quote_source="shioaji",
        )
        self.assertIn("**🔺 台積電 2330.TW 站上 1,000**", text)
        self.assertIn("現價 **1,010**（觸發價 1,000，+1.0%）", text)
        self.assertIn("報價來源：永豐即時（Shioaji）", text)

    def test_fallback_source_is_visible(self) -> None:
        text = format_generic_alert_markdown(
            target="2330.TW",
            rule=PriceAlert(stock_code="2330.TW", direction="below", price=1000.0),
            result=self._result(observed_value=990.0),
            quote_source="yfinance",
        )
        self.assertIn("🔻", text)
        self.assertIn("報價來源：yfinance（可能延遲）", text)
        self.assertNotIn("Shioaji", text)

    def test_missing_source_says_unknown(self) -> None:
        text = format_generic_alert_markdown(
            target="2330.TW",
            rule=PriceAlert(stock_code="2330.TW", direction="above", price=1000.0),
            result=self._result(diagnostics=None),
        )
        self.assertIn("報價來源：未知", text)

    def test_price_evaluation_carries_real_quote_source(self) -> None:
        """data_source 維持舊值；實際來源從報價物件帶進 diagnostics，通知才讀得到。"""
        import asyncio

        from src.services.alert_service import AlertService

        monitor = MagicMock()
        monitor._get_realtime_quote = AsyncMock(return_value=SimpleNamespace(
            price=1010.0, source=SimpleNamespace(value="yfinance"),
        ))
        result = asyncio.run(AlertService(db_manager=MagicMock())._evaluate_price(
            PriceAlert(stock_code="2330.TW", direction="above", price=1000.0), monitor,
        ))
        self.assertEqual(result["data_source"], "realtime_quote")
        self.assertEqual(result["diagnostics"], {"quote_source": "yfinance"})

    def test_level_message_carries_source(self) -> None:
        meta = {"side": "support", "low": 100.0, "high": 110.0, "label": "多頭 OB", "code": "3324.TWO", "name": "雙鴻"}
        self.assertIn("報價來源：yfinance", format_level_alert_markdown(meta, 99.0, None, quote_source="yfinance"))
        self.assertNotIn("報價來源", format_level_alert_markdown(meta, 99.0, None))

    def test_worker_sends_source_from_quote_result_on_alert_route(self) -> None:
        notifier = MagicMock()
        notifier.send_with_results.return_value = NotificationDispatchResult(
            dispatched=True, success=True, status="ok", channel_results=[], message="",
        )
        worker = AlertWorker(
            config_provider=_config, service=MagicMock(), decision_signal_service=MagicMock(), notifier=notifier,
        )
        runtime_rule = RuntimeAlertRule(
            key="k",
            rule=PriceAlert(stock_code="2330.TW", direction="above", price=1000.0),
            source="db",
            effective_target="2330.TW",
            display_target="2330.TW",
        )
        worker._build_analysis_visibility = lambda *_: {}
        worker._send_notification(runtime_rule, self._result())
        text = notifier.send_with_results.call_args.args[0]
        self.assertEqual(notifier.send_with_results.call_args.kwargs["route_type"], "alert")
        self.assertIn("永豐即時", text)
        self.assertIn("台積電", text)


class MonitorStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        ALERT_MONITOR_RUN_STATE.reset()
        self.addCleanup(ALERT_MONITOR_RUN_STATE.reset)
        patcher = patch.object(alert_worker_module, "alert_monitor_channels", return_value=["telegram"])
        patcher.start()
        self.addCleanup(patcher.stop)

    def _thread(self, active: bool):
        return SimpleNamespace(is_active=lambda: active, next_run_at="2099-01-01T00:00:00")

    def test_flag_on_but_scheduler_idle_is_not_running(self) -> None:
        """只讀開關會誤報；serve-only 下開了旗標排程器也沒在跑。"""
        scheduler = SimpleNamespace(is_background_task_active=lambda name: False)
        status = build_alert_monitor_status(
            _config(agent_event_monitor_without_schedule=False), runtime_scheduler=scheduler,
        )
        self.assertFalse(status["running"])
        self.assertEqual(status["reason"], "schedule_not_running")

    def test_scheduler_task_active_is_running(self) -> None:
        scheduler = SimpleNamespace(is_background_task_active=lambda name: name == "agent_event_monitor")
        status = build_alert_monitor_status(
            _config(agent_event_monitor_without_schedule=False), runtime_scheduler=scheduler,
        )
        self.assertTrue(status["running"])
        self.assertEqual(status["mode"], "scheduler")

    def test_monitor_only_requires_live_thread(self) -> None:
        running = build_alert_monitor_status(_config(), monitor_thread=self._thread(True))
        self.assertEqual((running["running"], running["mode"]), (True, "monitor_only"))
        self.assertEqual(running["interval_seconds"], 300)
        stopped = build_alert_monitor_status(_config(), monitor_thread=self._thread(False))
        self.assertEqual((stopped["running"], stopped["reason"]), (False, "monitor_thread_not_running"))

    def test_disabled_at_runtime_overrides_live_thread(self) -> None:
        status = build_alert_monitor_status(
            _config(agent_event_monitor_enabled=False), monitor_thread=self._thread(True),
        )
        self.assertEqual((status["running"], status["reason"]), (False, "monitor_disabled"))

    def test_run_recorded_exposes_last_run(self) -> None:
        run_recorded_cycle(SimpleNamespace(run_once=lambda: {"evaluated": 2}))
        status = build_alert_monitor_status(_config(), monitor_thread=self._thread(True))
        self.assertLess(abs(datetime.fromisoformat(status["last_run_at"]) - datetime.now()), timedelta(minutes=1))
        self.assertEqual(status["last_stats"], {"evaluated": 2})
        self.assertIsNone(status["last_error"])

    def test_run_recorded_keeps_error_and_reraises(self) -> None:
        with self.assertRaises(RuntimeError):
            run_recorded_cycle(SimpleNamespace(run_once=MagicMock(side_effect=RuntimeError("boom"))))
        self.assertEqual(ALERT_MONITOR_RUN_STATE.snapshot()["last_error"], "RuntimeError")

    def test_data_center_sees_monitor_thread(self) -> None:
        service = DataCapabilityService(
            config=MagicMock(agent_event_monitor_enabled=True),
            runtime_scheduler=SimpleNamespace(is_background_task_active=lambda name: False),
            alert_monitor_thread=self._thread(True),
        )
        self.assertEqual(service._alert_monitor_dataset()["warnings"], [])
        service.alert_monitor_thread = self._thread(False)
        self.assertEqual(service._alert_monitor_dataset()["warnings"], ["agent_event_monitor_not_running"])


class MonitorThreadEndToEndTests(unittest.TestCase):
    """真的執行緒＋真的規則與暫存庫：評估、寫紀錄、送通知（通知層換假的，不發真訊息）。"""

    def setUp(self) -> None:
        from src.config import Config
        from src.storage import DatabaseManager

        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        db_path = Path(self.temp_dir.name) / "monitor.db"
        env_path = Path(self.temp_dir.name) / ".env"
        env_path.write_text(f"DATABASE_PATH={db_path}\n", encoding="utf-8")
        env = patch.dict(os.environ, {"ENV_FILE": str(env_path), "DATABASE_PATH": str(db_path)}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        Config.reset_instance()
        DatabaseManager.reset_instance()
        self.addCleanup(Config.reset_instance)
        self.addCleanup(DatabaseManager.reset_instance)

    def test_thread_evaluates_rule_records_trigger_and_notifies(self) -> None:
        from src.services.alert_service import AlertService

        service = AlertService()
        rule = service.create_rule({
            "name": "台積電站上", "target_scope": "single_symbol", "target": "2330.TW",
            "alert_type": "price_cross", "parameters": {"direction": "above", "price": 1000},
            "severity": "warning", "enabled": True,
        })
        sent = threading.Event()
        texts = []

        def fake_send(text, route_type=None):
            texts.append((text, route_type))
            sent.set()
            return NotificationDispatchResult(
                dispatched=True, success=True, status="ok", channel_results=[], message="",
            )

        config = _config(trading_day_check_enabled=False)
        worker = AlertWorker(
            config_provider=lambda: config,
            service=service,
            decision_signal_service=MagicMock(),
            notifier=SimpleNamespace(send_with_results=fake_send),
            realtime_session_gate=True,
            last_trade_time_provider=lambda code: datetime.now(TAIPEI),
        )
        quote = SimpleNamespace(price=1010.0, source=SimpleNamespace(value="yfinance"))
        handle = AlertMonitorThread(config_provider=lambda: config, worker=worker)
        with patch(
            "src.agent.events.EventMonitor._get_realtime_quote", new=AsyncMock(return_value=quote),
        ), patch.object(alert_worker_module, "is_market_polling_window", return_value=True), patch.object(
            alert_worker_module, "quote_in_current_session", return_value=True,
        ):
            handle.start()
            self.assertTrue(sent.wait(30))
            handle.stop()
            handle._thread.join(30)

        text, route = texts[0]
        self.assertEqual(route, "alert")
        self.assertIn("站上 1,000", text)
        self.assertIn("報價來源：yfinance", text)
        triggers = service.list_triggers(rule_id=rule["id"])
        self.assertEqual(triggers["summary"]["triggered"], 1)
        self.assertEqual(triggers["items"][0]["quote_source"], "yfinance")


class PremarketRegressionTests(unittest.TestCase):
    """盤前昨收不得通知、不得寫冷卻；開盤後當日報價仍要通知（真日曆＋真規則＋暫存庫）。"""

    def setUp(self) -> None:
        from src.config import Config
        from src.core.trading_calendar import get_next_trading_date
        from src.storage import DatabaseManager

        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        db_path = Path(self.temp_dir.name) / "premarket.db"
        env_path = Path(self.temp_dir.name) / ".env"
        env_path.write_text(f"DATABASE_PATH={db_path}\n", encoding="utf-8")
        env = patch.dict(os.environ, {"ENV_FILE": str(env_path), "DATABASE_PATH": str(db_path)}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        Config.reset_instance()
        DatabaseManager.reset_instance()
        self.addCleanup(Config.reset_instance)
        self.addCleanup(DatabaseManager.reset_instance)
        self.session = get_next_trading_date("tw", datetime.now(TAIPEI).date())
        self.assertIsNotNone(self.session)

    def _at(self, hour: int, minute: int) -> datetime:
        return datetime(self.session.year, self.session.month, self.session.day, hour, minute, tzinfo=TAIPEI)

    def _harness(self, target: str = "2330.TW", last_trade_time=None):
        from src.notification import ChannelAttemptResult
        from src.services.alert_service import AlertService

        service = AlertService()
        rule = service.create_rule({
            "name": "站上", "target_scope": "single_symbol", "target": target,
            "alert_type": "price_cross", "parameters": {"direction": "above", "price": 1000},
            "severity": "warning", "enabled": True,
        })
        notifier = MagicMock()
        notifier.send_with_results.return_value = NotificationDispatchResult(
            dispatched=True, success=True, status="ok", message="",
            channel_results=[ChannelAttemptResult(channel="telegram", success=True)],
        )
        self.clock = self._at(8, 56)
        config = _config(trading_day_check_enabled=False)
        worker = AlertWorker(
            config_provider=lambda: config, service=service, decision_signal_service=MagicMock(),
            notifier=notifier, now_provider=lambda: self.clock.timestamp(), realtime_session_gate=True,
            last_trade_time_provider=last_trade_time or MagicMock(side_effect=AssertionError("不該另查成交時間")),
        )
        return worker, service, notifier, rule

    def _run(self, worker, when: datetime, quote_time, *, source="shioaji", trade_date=None, price=1010.0):
        self.clock = when
        quote = SimpleNamespace(
            price=price, source=SimpleNamespace(value=source),
            provider_timestamp=quote_time.isoformat() if quote_time else None,
            quote_trade_date=trade_date,
        )
        fetch = AsyncMock(return_value=quote)
        with patch("src.agent.events.EventMonitor._get_realtime_quote", new=fetch):
            return worker.run_once(), fetch

    def test_premarket_close_price_does_not_notify_and_open_quote_still_does(self) -> None:
        worker, service, notifier, rule = self._harness()
        yesterday_close = self._at(13, 30) - timedelta(days=1)

        stats, fetch = self._run(worker, self._at(8, 56), yesterday_close)
        fetch.assert_not_awaited()
        self.assertEqual(stats["off_session"], 1)
        notifier.send_with_results.assert_not_called()

        # 開盤了但還沒有今日成交：報價仍是昨收，不通知、不寫紀錄、不進冷卻
        stats, fetch = self._run(worker, self._at(9, 1), yesterday_close)
        fetch.assert_awaited()
        self.assertEqual(stats["stale_quote"], 1)
        notifier.send_with_results.assert_not_called()
        self.assertEqual(service.list_triggers(rule_id=rule["id"])["summary"]["triggered"], 0)

        stats, _ = self._run(worker, self._at(9, 6), self._at(9, 5))
        self.assertEqual(stats["notified"], 1)
        self.assertEqual(stats["cooldown_suppressed"], 0)
        notifier.send_with_results.assert_called_once()

    def test_fallback_old_price_never_passes_on_elapsed_time_then_today_notifies(self) -> None:
        """Shioaji 退回 yfinance：開盤超過 30 分鐘、最後成交仍是前一場，不通知也不進冷卻。"""
        bars = MagicMock(return_value=self._at(13, 30) - timedelta(days=3))
        worker, service, notifier, rule = self._harness(last_trade_time=bars)
        for when in (self._at(9, 31), self._at(12, 0)):
            stats, _ = self._run(worker, when, None, source="fallback")
            self.assertEqual(stats["stale_quote"], 1)
        notifier.send_with_results.assert_not_called()
        self.assertEqual(service.list_triggers(rule_id=rule["id"])["summary"]["triggered"], 0)
        self.assertFalse(service.get_rule(rule["id"])["cooldown_active"])

        bars.return_value = self._at(12, 4)
        stats, _ = self._run(worker, self._at(12, 5), None, source="fallback")
        self.assertEqual(stats["notified"], 1)
        self.assertEqual(stats["cooldown_suppressed"], 0)
        bars.assert_called_with("2330.TW")

    def test_unknown_last_trade_time_does_not_notify(self) -> None:
        worker, _, notifier, _ = self._harness(last_trade_time=MagicMock(return_value=None))
        stats, _ = self._run(worker, self._at(11, 0), None, source="fallback")
        self.assertEqual(stats["stale_quote"], 1)
        notifier.send_with_results.assert_not_called()

    def test_history_fallback_row_date_decides_without_extra_call(self) -> None:
        worker, _, notifier, _ = self._harness()
        previous = (self._at(10, 0) - timedelta(days=3)).date().isoformat()
        stats, _ = self._run(worker, self._at(10, 0), None, source="fallback", trade_date=previous)
        self.assertEqual(stats["stale_quote"], 1)
        notifier.send_with_results.assert_not_called()
        stats, _ = self._run(worker, self._at(10, 5), None, source="fallback", trade_date=self.session.isoformat())
        self.assertEqual(stats["notified"], 1)

    def test_untriggered_quote_makes_no_extra_call(self) -> None:
        bars = MagicMock(return_value=None)
        worker, _, _, _ = self._harness(last_trade_time=bars)
        self._run(worker, self._at(10, 0), None, source="fallback", price=900.0)
        bars.assert_not_called()

    def test_us_yfinance_today_notifies_and_prior_close_does_not(self) -> None:
        from zoneinfo import ZoneInfo

        from src.core.trading_calendar import get_next_trading_date

        new_york = ZoneInfo("America/New_York")
        session = get_next_trading_date("us", datetime.now(new_york).date())
        at = lambda hour, minute: datetime(session.year, session.month, session.day, hour, minute, tzinfo=new_york)  # noqa: E731
        bars = MagicMock(return_value=at(16, 0) - timedelta(days=3))
        worker, _, notifier, _ = self._harness(target="AAPL", last_trade_time=bars)
        stats, _ = self._run(worker, at(10, 31), None, source="yfinance")
        self.assertEqual(stats["stale_quote"], 1)
        notifier.send_with_results.assert_not_called()

        bars.return_value = at(10, 35)
        stats, _ = self._run(worker, at(10, 36), None, source="yfinance")
        self.assertEqual(stats["notified"], 1)
        self.assertIn("yfinance", notifier.send_with_results.call_args.args[0])

    def test_unparseable_quote_time_is_not_treated_as_missing(self) -> None:
        worker, _, notifier, _ = self._harness()
        self.clock = self._at(10, 0)
        quote = SimpleNamespace(price=1010.0, source=None, provider_timestamp="not-a-time")
        with patch("src.agent.events.EventMonitor._get_realtime_quote", new=AsyncMock(return_value=quote)):
            stats = worker.run_once()
        self.assertEqual(stats["stale_quote"], 1)
        notifier.send_with_results.assert_not_called()

    def test_quote_after_close_of_same_session_still_counts(self) -> None:
        worker, _, notifier, _ = self._harness()
        stats, _ = self._run(worker, self._at(13, 35), self._at(13, 30))
        self.assertEqual(stats["notified"], 1)
        notifier.send_with_results.assert_called_once()


class YfinanceSessionSourceTests(unittest.TestCase):
    def _bars(self, *days: str):
        import pandas as pd

        index = pd.DatetimeIndex(days, tz="Asia/Taipei")
        return pd.DataFrame(
            {"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1}, index=index,
        )

    def _fetcher_with(self, ticker):
        fake = SimpleNamespace(Ticker=lambda symbol: ticker)
        return patch.dict("sys.modules", {"yfinance": fake})

    def test_history_fallback_keeps_last_row_date_outside_to_dict(self) -> None:
        from data_provider.yfinance_fetcher import YfinanceFetcher

        ticker = SimpleNamespace(fast_info=None, history=lambda period: self._bars("2026-10-29", "2026-10-30"))
        with self._fetcher_with(ticker):
            quote = YfinanceFetcher().get_realtime_quote("2330.TW")
        self.assertEqual(quote.quote_trade_date, "2026-10-30")
        self.assertIsNone(quote.provider_timestamp)
        self.assertNotIn("quote_trade_date", quote.to_dict())

    def test_fast_info_path_makes_no_history_call(self) -> None:
        from data_provider.yfinance_fetcher import YfinanceFetcher

        history = MagicMock()
        info = SimpleNamespace(last_price=10.0, previous_close=9.0, open=9.5, day_high=10.0, day_low=9.0, last_volume=1, market_cap=1)
        with self._fetcher_with(SimpleNamespace(fast_info=info, history=history)):
            quote = YfinanceFetcher().get_realtime_quote("2330.TW")
        self.assertEqual(quote.price, 10.0)
        self.assertIsNone(quote.quote_trade_date)
        history.assert_not_called()

    def test_last_trade_time_uses_last_real_bar(self) -> None:
        import math

        from data_provider.yfinance_fetcher import YfinanceFetcher

        bars = self._bars("2026-10-30 13:29", "2026-10-30 13:30")
        bars.loc[bars.index[-1], "Close"] = math.nan
        with self._fetcher_with(SimpleNamespace(history=lambda period, interval: bars)):
            result = YfinanceFetcher().get_last_trade_time("2330.TW")
        self.assertEqual((result.hour, result.minute), (13, 29))

    def test_last_trade_time_is_none_when_unavailable(self) -> None:
        from data_provider.yfinance_fetcher import YfinanceFetcher

        def boom(period, interval):
            raise RuntimeError("down")

        with self._fetcher_with(SimpleNamespace(history=boom)):
            self.assertIsNone(YfinanceFetcher().get_last_trade_time("2330.TW"))
        with self._fetcher_with(SimpleNamespace(history=lambda period, interval: self._bars())):
            self.assertIsNone(YfinanceFetcher().get_last_trade_time("2330.TW"))


class ChannelTests(unittest.TestCase):
    def test_route_filters_configured_channels(self) -> None:
        config = SimpleNamespace(telegram_bot_token="t", telegram_chat_id="c", notification_alert_channels=["discord"])
        self.assertEqual(alert_monitor_channels(config), [])
        config.notification_alert_channels = ["telegram"]
        self.assertEqual(alert_monitor_channels(config), ["telegram"])
        config.notification_alert_channels = []
        self.assertEqual(alert_monitor_channels(config), ["telegram"])
