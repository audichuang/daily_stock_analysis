"""匯率 worker 的資源上限與 deadline 回歸測試。"""

import threading
import time
from unittest.mock import patch

import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

import src.services.portfolio_service as ps


def test_fx_workers_remain_bounded_across_deadlines_and_recover(monkeypatch):
    # 每次呼叫都有新預算；逾時工作仍存活時，也不能因刷新重試而突破程序上限。
    limit = getattr(ps, "FX_MAX_IN_FLIGHT_REQUESTS", 4)
    monkeypatch.setattr(ps, "_FX_IN_FLIGHT", threading.BoundedSemaphore(limit), raising=False)
    monkeypatch.setattr(ps, "FX_REQUEST_TIMEOUT_SECONDS", 0.02)
    release = threading.Event()
    workers = []

    def blocked(*, timeout):
        workers.append(threading.current_thread())
        release.wait(30)
        return "late"

    try:
        started = time.monotonic()
        for _ in range(limit + 3):
            token = ps._FX_DEADLINE.set(time.monotonic() + 30)
            try:
                assert ps._fx_call(blocked) is None
            finally:
                ps._FX_DEADLINE.reset(token)
        assert len(workers) == limit
        assert all(worker.is_alive() and worker.daemon for worker in workers)
        assert time.monotonic() - started < 1.0
    finally:
        release.set()
        for worker in workers:
            worker.join(30)
            assert not worker.is_alive()

    # 完成後必須歸還所有名額，不能把逾時誤當成永久停用網路。
    assert ps._fx_call(lambda *, timeout: "recovered") == "recovered"
    for _ in range(limit):
        assert ps._FX_IN_FLIGHT.acquire(blocking=False)
    assert not ps._FX_IN_FLIGHT.acquire(blocking=False)


def test_fx_worker_deadline_skips_network_and_preserves_remaining_timeout(monkeypatch):
    monkeypatch.setattr(ps, "_FX_IN_FLIGHT", threading.BoundedSemaphore(1), raising=False)
    seen = []

    def fetch(*, timeout):
        seen.append(timeout)
        return "ok"

    token = ps._FX_DEADLINE.set(5.0)
    try:
        with patch.object(ps.time, "monotonic", return_value=6.0):
            assert ps._fx_call(fetch) is None
        assert seen == []
        with patch.object(ps.time, "monotonic", return_value=2.0):
            assert ps._fx_call(fetch) == "ok"
        assert seen == [3.0]
    finally:
        ps._FX_DEADLINE.reset(token)


def test_fx_worker_exception_releases_admission_slot(monkeypatch):
    monkeypatch.setattr(ps, "_FX_IN_FLIGHT", threading.BoundedSemaphore(1), raising=False)

    def fail(*, timeout):
        raise ValueError("upstream failed")

    with pytest.raises(ValueError, match="upstream failed"):
        ps._fx_call(fail)
    assert ps._fx_call(lambda *, timeout: "ok") == "ok"


def test_fx_worker_start_failure_releases_admission_slot(monkeypatch):
    monkeypatch.setattr(ps, "_FX_IN_FLIGHT", threading.BoundedSemaphore(1), raising=False)
    with patch.object(threading.Thread, "start", side_effect=RuntimeError("cannot start")):
        with pytest.raises(RuntimeError, match="cannot start"):
            ps._fx_call(lambda *, timeout: "unreachable")
    assert ps._fx_call(lambda *, timeout: "ok") == "ok"
