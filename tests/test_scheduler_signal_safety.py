# -*- coding: utf-8 -*-
"""`GracefulShutdown` 的 signal handler 必須是 async-signal-safe。

踩過（2026-08-23 10:35:33，`dsa-schedule.service`）：舊版在 handler 裡 `with self._lock`
並呼叫 `logger.info`。訊息印出來了，然後行程**再無下文**——卡在第二個 logging handler
的鎖上。systemd 仍報 `active (running)`，當天與隔天 14:00 的排程都沒觸發，
「调度器已停止」也從未印出。這種失敗完全無聲。

這個檔案守住兩件事：handler 不搶鎖、不記 log。它之前是**零覆蓋**。
"""

import logging
import threading
import unittest

from src.scheduler import GracefulShutdown


def _call_handler_with_timeout(handler, seconds=5.0):
    """在另一條執行緒呼叫 handler，回傳它是否在時限內返回。"""
    done = threading.Event()

    def run():
        handler(15, None)
        done.set()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return done.wait(timeout=seconds)


class SignalHandlerSafetyTestCase(unittest.TestCase):
    def setUp(self):
        # register_signals=False：不要動到跑測試這個行程的 signal disposition。
        self.gs = GracefulShutdown(register_signals=False)

    def test_handler_sets_the_flag_and_records_the_signal(self):
        self.assertFalse(self.gs.should_shutdown)
        self.assertIsNone(self.gs.shutdown_signal)
        self.gs._signal_handler(15, None)
        self.assertTrue(self.gs.should_shutdown)
        self.assertEqual(self.gs.shutdown_signal, 15)

    def test_handler_returns_while_a_logging_handler_lock_is_held(self):
        """這就是真實死鎖的形狀：signal 打在主執行緒持有 logging 鎖的瞬間。

        反向守門：把 `logger.info` 放回 handler，這條會卡到 timeout 而紅。
        """
        target = logging.getLogger("src.scheduler")
        held = [h for h in logging.getLogger().handlers + target.handlers if h is not None]
        self.assertTrue(held, "需要至少一個 logging handler 才能重現這個情境")
        for h in held:
            h.acquire()
        try:
            self.assertTrue(
                _call_handler_with_timeout(self.gs._signal_handler),
                "signal handler 在 logging 鎖被持有時沒有返回——就是 2026-08-23 那次死鎖",
            )
        finally:
            for h in held:
                h.release()
        self.assertTrue(self.gs.should_shutdown)

    def test_handler_does_not_acquire_any_non_reentrant_lock_of_its_own(self):
        """反向守門：把 `with self._lock` 放回去，這條會卡到 timeout。

        模擬「主執行緒已持有那把鎖」——signal 在主執行緒遞送，所以這是真實情境。
        """
        lock = getattr(self.gs, "_lock", None)
        if lock is not None:
            lock.acquire()
            try:
                self.assertTrue(
                    _call_handler_with_timeout(self.gs._signal_handler),
                    "handler 搶了自己的非可重入鎖",
                )
            finally:
                lock.release()
        else:
            # 沒有那把鎖就是修好的樣子；明確斷言而不是靜默跳過
            self.assertFalse(hasattr(self.gs, "_lock"))

    def test_repeated_signals_are_idempotent(self):
        self.gs._signal_handler(15, None)
        self.gs._signal_handler(2, None)
        self.assertTrue(self.gs.should_shutdown)
        # 最後一個訊號會覆寫，這是刻意的：主迴圈只印一次，印最新那個即可
        self.assertEqual(self.gs.shutdown_signal, 2)


if __name__ == "__main__":
    unittest.main()
