# -*- coding: utf-8 -*-
"""Pytest compatibility hooks."""

from __future__ import annotations

import asyncio
import concurrent.futures
import time
import threading
from collections.abc import Awaitable, Callable
from contextvars import copy_context
from functools import wraps
from typing import Any, TypeVar
from warnings import warn

import os
import subprocess
from pathlib import Path

import anyio.to_thread
import fastapi.testclient
import httpx
import pytest
import sqlalchemy
import sqlalchemy.engine
import starlette.testclient
from anyio._backends import _asyncio
from dotenv import dotenv_values

T = TypeVar("T")


# 本机 .env 的 STORAGE_DATABASE_URL 指向 NAS 与本机共用的正式 Postgres 应用库。
# 测试只把 DATABASE_PATH 指到暂存 SQLite，而 STORAGE_DATABASE_URL 优先，漏进行程
# 就整批写进正式库（2026-10-08 踩过：告警规则、持仓、决策信号、LLM 用量）。
# 两层：载入时就占住这个键（load_dotenv 不覆写已存在的键）；再在建 engine 的出口
# 拒绝正式库 URL，挡住 patch.dict(clear=True) 之后又重载 .env 的路径。
# market_data/tests 刻意連 DATABASE_URL 並以 rollback 保護；只有 worktree 自帶另一份 .env 時才擋主 checkout 的 DATABASE_URL（見下方）。
# 往上層逐層找 .env：git worktree（.claude/worktrees/<name>）自己沒有 .env，但 .venv 是連到主 repo
# 的 symlink，LiteLLM DEV 模式的 load_dotenv() 會從套件位置往上找到主 repo 的 .env，把正式庫補回來
# （2026-10-23 踩過：worktree 跑 test_portfolio_pr2 在正式庫寫入 218 個 Demo 帳戶）。
# 樹外 worktree（dsa-upstream-sync 的 ~/.cache/dsa-upstream-sync/<date>）往上找不到 .env，
# 但 PATH 用的仍是主 repo 的 .venv，LiteLLM 一樣會補回正式庫；所以往上找不到可用的 URL 時，
# 改用 `git rev-parse --git-common-dir` 定位主 checkout，讀它的 .env（找得到時一律也讀，見下方）。
def _env_value_in(env_file: Path, key: str) -> str:
    if not env_file.is_file():
        return ""
    return (dotenv_values(env_file).get(key) or "").strip()


def _storage_url_in(env_file: Path) -> str:
    return _env_value_in(env_file, "STORAGE_DATABASE_URL")


def _main_checkout_root(start_dir: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(start_dir), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    common_dir = result.stdout.strip()
    if result.returncode != 0 or not common_dir:
        return None
    common_path = Path(common_dir)
    if not common_path.is_absolute():
        common_path = start_dir / common_path
    common_path = common_path.resolve()
    # 一般 checkout 的 common dir 是 <主 repo>/.git；bare repo 沒有工作目錄，也就沒有 .env。
    if common_path.name != ".git":
        return None
    return common_path.parent


# 最近的 .env 與主 checkout 的 .env 不是同一份時（worktree 自帶 .env），兩邊的正式庫都要擋：
# LiteLLM DEV 模式的 load_dotenv() 從主 repo 的 .venv 往上找，補回來的是主 checkout 的 URL，
# 不是 worktree 那份。此時連主 checkout 的 DATABASE_URL（market schema，無備份）也一併拒絕；
# 最近的 .env 就是主 checkout 的 .env（或它自己也宣告同一條 DATABASE_URL）時不擋，
# market_data/tests 要靠它連 market 並 rollback。往上找不到 .env 的樹外 worktree 也不擋 DATABASE_URL：
# 那時沒有「另一份 .env」的情形，維持原本只擋 STORAGE_DATABASE_URL。
def _find_prod_database_urls(start: Path) -> frozenset[str]:
    start = start.resolve()
    urls: set[str] = set()
    nearest_env: Path | None = None
    for parent in start.parents:
        env_file = parent / ".env"
        if env_file.is_file():
            nearest_env = env_file
            break
    if nearest_env is not None:
        nearest_url = _storage_url_in(nearest_env)
        if nearest_url:
            urls.add(nearest_url)
    main_root = _main_checkout_root(start.parent)
    if main_root is not None:
        main_env = main_root / ".env"
        main_url = _storage_url_in(main_env)
        if main_url:
            urls.add(main_url)
        if nearest_env is not None and nearest_env.resolve() != main_env.resolve():
            main_market_url = _env_value_in(main_env, "DATABASE_URL")
            # worktree 自己的 .env 宣告同一條 DATABASE_URL 時，那是它的 market_data/tests 刻意要連的。
            if main_market_url and main_market_url != _env_value_in(nearest_env, "DATABASE_URL"):
                urls.add(main_market_url)
    return frozenset(urls)


_PROD_DATABASE_URLS = _find_prod_database_urls(Path(__file__))
os.environ["STORAGE_DATABASE_URL"] = ""
# 本机 data/ 的台股临时休市清单（market_data.closures）不能漏进测试的交易日判断。
os.environ["TW_ADHOC_CLOSED_FILE"] = os.devnull
# trading_calendar 會自動偵測今天的颱風假（連網）；測試預設關掉，要測的自己 monkeypatch 打開
os.environ["TW_CLOSURE_AUTODETECT"] = "false"
# 台股 prompt 的處置／事件即時名單會打官方端點；測試一律關掉，要測的自己注入 config
os.environ["TW_LIVE_EVENTS_ENABLED"] = "false"
# 賣方共識會連 yfinance、指數目標會多一行 prompt；擋掉 .env 漏入，要測的自己注入 config
os.environ["ANALYST_CONSENSUS_ENABLED"] = "false"
os.environ["EVENT_OUTLOOK_ENABLED"] = "false"
os.environ["TW_BROKER_INDEX_TARGETS"] = ""

_original_create_engine = sqlalchemy.create_engine


def _url_text(url) -> str:
    # sqlalchemy.URL 的 str() 會把密碼遮成 ***，比對前要還原成完整字串。
    render = getattr(url, "render_as_string", None)
    if callable(render):
        return render(hide_password=False).strip()
    return str(url).strip()


def _create_engine_refusing_prod_storage(url, *args, **kwargs):
    if _url_text(url) in _PROD_DATABASE_URLS:
        raise RuntimeError(
            "tests must not connect to a production database URL from .env "
            "(STORAGE_DATABASE_URL / main checkout DATABASE_URL)"
        )
    return _original_create_engine(url, *args, **kwargs)


sqlalchemy.create_engine = _create_engine_refusing_prod_storage
sqlalchemy.engine.create_engine = _create_engine_refusing_prod_storage


@pytest.fixture(autouse=True)
def _keep_storage_database_url_unset():
    os.environ["STORAGE_DATABASE_URL"] = ""
    os.environ["TW_LIVE_EVENTS_ENABLED"] = "false"
    yield

_original_call_soon_threadsafe = asyncio.BaseEventLoop.call_soon_threadsafe


async def _shutdown_default_executor_inline(
    self: asyncio.BaseEventLoop,
    timeout: float | None = None,
) -> None:
    """Avoid lost wakeups while asyncio.run() tears down test-only executors."""
    del timeout
    executor = getattr(self, "_default_executor", None)
    if executor is None:
        return
    self._executor_shutdown_called = True
    self._default_executor = None
    executor.shutdown(wait=True)


def _call_soon_threadsafe_with_extra_wakeup(
    self: asyncio.BaseEventLoop,
    callback,
    *args,
    context=None,
):
    """Wake the selector again for sandboxed test runs where the first wake is lost."""
    handle = _original_call_soon_threadsafe(self, callback, *args, context=context)
    write_to_self = getattr(self, "_write_to_self", None)
    if callable(write_to_self):
        write_to_self()
        threading.Timer(0.001, write_to_self).start()
    return handle


asyncio.BaseEventLoop.call_soon_threadsafe = _call_soon_threadsafe_with_extra_wakeup
asyncio.BaseEventLoop.shutdown_default_executor = _shutdown_default_executor_inline


async def _run_sync_via_asyncio_to_thread(
    func: Callable[..., T],
    *args: Any,
    abandon_on_cancel: bool = False,
    cancellable: bool | None = None,
    limiter: Any = None,
) -> T:
    """Use asyncio's executor path when AnyIO worker queues miss wakeups."""
    del abandon_on_cancel, limiter
    if cancellable is not None:
        warn(
            "The `cancellable=` keyword argument to `anyio.to_thread.run_sync` is "
            "deprecated since AnyIO 4.1.0; use `abandon_on_cancel=` instead",
            DeprecationWarning,
            stacklevel=2,
        )
    future: concurrent.futures.Future[T] = concurrent.futures.Future()
    context = copy_context()

    def runner() -> None:
        try:
            future.set_result(context.run(func, *args))
        except BaseException as exc:
            future.set_exception(exc)

    threading.Thread(target=runner, name="pytest-anyio-worker", daemon=True).start()
    while not future.done():
        await asyncio.sleep(0.001)
    return future.result()


def _wait_for_cross_thread_result(loop: asyncio.AbstractEventLoop, future: concurrent.futures.Future[T]) -> T:
    write_to_self = getattr(loop, "_write_to_self", None)
    while not future.done():
        if callable(write_to_self):
            write_to_self()
        time.sleep(0.001)
    return future.result()


def _run_sync_from_thread_with_wakeup(
    cls,
    func: Callable[..., T],
    args: tuple[Any, ...],
    token: object,
) -> T:
    @wraps(func)
    def wrapper() -> None:
        try:
            _asyncio.set_current_async_library("asyncio")
            future.set_result(func(*args))
        except BaseException as exc:
            future.set_exception(exc)
            if not isinstance(exc, Exception):
                raise

    loop = token or _asyncio.threadlocals.current_token.native_token
    if loop.is_closed():
        raise _asyncio.RunFinishedError
    future: concurrent.futures.Future[T] = concurrent.futures.Future()
    loop.call_soon_threadsafe(wrapper)
    return _wait_for_cross_thread_result(loop, future)


def _run_async_from_thread_with_wakeup(
    cls,
    func: Callable[..., Awaitable[T]],
    args: tuple[Any, ...],
    token: object,
) -> T:
    loop = token or _asyncio.threadlocals.current_token.native_token
    if loop.is_closed():
        raise _asyncio.RunFinishedError
    context = copy_context()
    context.run(_asyncio.set_current_async_library, "asyncio")
    future = context.run(asyncio.run_coroutine_threadsafe, func(*args), loop=loop)
    return _wait_for_cross_thread_result(loop, future)


anyio.to_thread.run_sync = _run_sync_via_asyncio_to_thread
_asyncio.AsyncIOBackend.run_sync_from_thread = classmethod(_run_sync_from_thread_with_wakeup)
_asyncio.AsyncIOBackend.run_async_from_thread = classmethod(_run_async_from_thread_with_wakeup)


class _ThreadlessTestClient:
    """Small TestClient replacement that avoids AnyIO's cross-thread portal."""

    def __init__(
        self,
        app,
        base_url: str = "http://testserver",
        raise_server_exceptions: bool = True,
        follow_redirects: bool = True,
        **_: Any,
    ) -> None:
        self.app = app
        self.base_url = base_url
        self.raise_server_exceptions = raise_server_exceptions
        self.follow_redirects = follow_redirects
        self.cookies = httpx.Cookies()
        self._lifespan_ctx = None
        self._lifespan_enter_count = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._async_client: httpx.AsyncClient | None = None

    def _get_lifespan_context(self):
        return getattr(getattr(self.app, "router", None), "lifespan_context", None)

    def _build_async_client(self, follow_redirects: bool) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(
            app=self.app,
            raise_app_exceptions=self.raise_server_exceptions,
        )
        return httpx.AsyncClient(
            transport=transport,
            base_url=self.base_url,
            follow_redirects=follow_redirects,
            cookies=self.cookies,
        )

    def __enter__(self):
        if self._lifespan_enter_count == 0:
            self._loop = asyncio.new_event_loop()
            lifespan_context = self._get_lifespan_context()
            if callable(lifespan_context):
                self._lifespan_ctx = lifespan_context(self.app)
                self._loop.run_until_complete(self._lifespan_ctx.__aenter__())
            self._async_client = self._build_async_client(self.follow_redirects)
        self._lifespan_enter_count += 1
        return self

    def __exit__(self, *args: Any) -> None:
        if self._lifespan_enter_count == 0:
            return None

        self._lifespan_enter_count -= 1
        if self._lifespan_enter_count == 0 and self._loop is not None:
            try:
                async def _close() -> None:
                    if self._async_client is not None:
                        await self._async_client.aclose()
                    if self._lifespan_ctx is not None:
                        await self._lifespan_ctx.__aexit__(*args)

                self._loop.run_until_complete(_close())
            finally:
                self._lifespan_ctx = None
                self._async_client = None
                self._loop.close()
                self._loop = None
        return None

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        follow_redirects = kwargs.pop("follow_redirects", self.follow_redirects)
        kwargs.pop("allow_redirects", None)

        if self._lifespan_enter_count > 0 and self._loop is not None and self._async_client is not None:
            response = self._loop.run_until_complete(
                self._async_client.request(method, url, follow_redirects=follow_redirects, **kwargs)
            )
            self.cookies = httpx.Cookies(self._async_client.cookies)
            return response

        async def _send() -> httpx.Response:
            async with self._build_async_client(follow_redirects) as client:
                response = await client.request(method, url, **kwargs)
                self.cookies = httpx.Cookies(client.cookies)
                return response

        return asyncio.run(_send())

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("PATCH", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("DELETE", url, **kwargs)

    def head(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("HEAD", url, **kwargs)


fastapi.testclient.TestClient = _ThreadlessTestClient
starlette.testclient.TestClient = _ThreadlessTestClient
