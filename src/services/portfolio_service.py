# -*- coding: utf-8 -*-
"""Portfolio service for P0 account/events/snapshot workflow."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

from data_provider.base import canonical_stock_code, normalize_stock_code
from src.config import get_config
from src.data.stock_index_loader import get_index_stock_name
from src.repositories.portfolio_repo import (
    DuplicateTradeDedupHashError,
    DuplicateTradeUidError,
    PortfolioBusyError as RepoPortfolioBusyError,
    PortfolioRepository,
)

logger = logging.getLogger(__name__)

PortfolioBusyError = RepoPortfolioBusyError

try:
    import yfinance as yf
except Exception:  # pragma: no cover - optional dependency path
    yf = None

EPS = 1e-8
VALID_MARKETS = {"cn", "hk", "us", "jp", "kr", "tw"}
PARTIAL_VALUATION_MARKETS = {"jp", "kr", "tw"}
VALID_COST_METHODS = {"fifo", "avg"}
VALID_SIDES = {"buy", "sell"}
VALID_CASH_DIRECTIONS = {"in", "out"}
VALID_CORPORATE_ACTIONS = {"cash_dividend", "split_adjustment"}
PORTFOLIO_FX_REFRESH_DISABLED_REASON = "portfolio_fx_update_disabled"
PORTFOLIO_REALTIME_QUOTE_MAX_WORKERS = 4
# 跨帐户汇总（快照 total_* 与风险页）统一换算到这个币别。
PORTFOLIO_AGGREGATE_CURRENCY = "CNY"
# 匯率快取超過這麼多天（以 rate_date 對快照日）就算過期。`is_stale` 只在寫入時決定，
# 手動刷新一次之後就一直是 False——8 天前的匯率照樣顯示「最新」。3 天涵蓋週末。
PORTFOLIO_FX_MAX_AGE_DAYS = 3
FX_FALLBACK_SOURCE = "fallback_1_to_1"
# Sources written by the automated FX refresh; any other non-stale row is a manual entry and is never touched.
FX_AUTO_SOURCES = ("yfinance", "yfinance_backfill", "yfinance_cross")
FX_REFRESH_BUDGET_SECONDS = 20.0  # whole-refresh network budget; the web client gives up at 30s
FX_REQUEST_TIMEOUT_SECONDS = 10.0  # per yfinance request, capped by the remaining budget
# 逾時的 daemon 無法強制中止；所有刷新共用名額，直到工作真正結束才歸還。
FX_MAX_IN_FLIGHT_REQUESTS = 4
_FX_IN_FLIGHT = threading.BoundedSemaphore(FX_MAX_IN_FLIGHT_REQUESTS)
_FX_DEADLINE: ContextVar[Optional[float]] = ContextVar("fx_refresh_deadline", default=None)
FX_OUTLIER_MAX_DEVIATION = 0.02  # a bar this far (relative) from its reference counts as deviating



def _fx_request_timeout() -> Optional[float]:
    """Seconds a yfinance request may take, or None when the refresh budget is spent (skip the request)."""
    deadline = _FX_DEADLINE.get()
    if deadline is None:
        return FX_REQUEST_TIMEOUT_SECONDS
    remaining = deadline - time.monotonic()
    return min(FX_REQUEST_TIMEOUT_SECONDS, remaining) if remaining > 0 else None

def _fx_call(fn: Any, /, *args: Any, **kwargs: Any) -> Any:
    """Run a yfinance call in a daemon thread and give up when the refresh budget runs out.

    yfinance's cookie/crumb handshake ignores `timeout`, so a single history() can outlive the budget.
    On expiry the result is discarded (the thread only returns a value, it writes nothing) and None
    comes back. The budget is computed here, in the caller's thread: ContextVars do not reach new threads.
    """
    timeout = _fx_request_timeout()
    if timeout is None:
        return None
    limiter = _FX_IN_FLIGHT
    if not limiter.acquire(blocking=False):
        logger.warning("匯率請求已達程序併發上限，沿用快取")
        return None
    box: Dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = fn(*args, timeout=timeout, **kwargs)
        except BaseException as exc:  # re-raised in the caller below
            box["error"] = exc
        finally:
            limiter.release()

    try:
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
    except BaseException:
        limiter.release()
        raise
    worker.join(timeout)
    if worker.is_alive():
        logger.warning("yfinance 請求超過剩餘時限 %.1fs，放棄此次結果", timeout)
        return None
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _ticker_history(symbol: str, **kwargs: Any) -> Any:
    """Build the yfinance Ticker and fetch history in one call, so _fx_call bounds both.

    Ticker construction can block on yfinance's shared locks (an abandoned cookie request
    holding them while a concurrent yf.download waits), so it must not run outside the budget.
    """
    return yf.Ticker(symbol).history(**kwargs)


def _london_date(ts: Any) -> date:
    """Calendar date of a yfinance bar timestamp in London (naive timestamps are taken as London already)."""
    import pandas as pd  # local: only reached with yfinance data, which already depends on pandas

    ts = pd.Timestamp(ts)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("Europe/London")
    return ts.date()


def _format_fx_pair(pair: Tuple[str, str]) -> str:
    return f"{pair[0]}/{pair[1]}"


def _fx_rates_deviate(value: float, reference: float) -> bool:
    """抓價、快取失效與交叉修補共用同一個偏離門檻。"""
    return abs(value / reference - 1.0) > FX_OUTLIER_MAX_DEVIATION


def _portfolio_limitations_for_market(market: str) -> List[str]:
    """Return explicit snapshot limitations for markets with partial valuation semantics."""

    if market not in PARTIAL_VALUATION_MARKETS:
        return []
    return [
        "realtime_quote_best_effort",
        "fx_and_cost_basis_partial",
        "sector_and_risk_metrics_limited",
    ]


def _merge_portfolio_limitations(*groups: Iterable[str]) -> List[str]:
    merged: List[str] = []
    seen: Set[str] = set()
    for group in groups:
        for item in group:
            if item and item not in seen:
                seen.add(item)
                merged.append(item)
    return merged


class PortfolioConflictError(Exception):
    """Raised when request conflicts with existing portfolio state."""


class PortfolioOversellError(ValueError):
    """Raised when a sell would exceed the available position quantity."""

    def __init__(
        self,
        *,
        symbol: str,
        trade_date: Optional[date],
        requested_quantity: float,
        available_quantity: float,
    ) -> None:
        self.symbol = symbol
        self.trade_date = trade_date
        self.requested_quantity = float(requested_quantity)
        self.available_quantity = max(0.0, float(available_quantity))
        date_hint = f" on {trade_date.isoformat()}" if trade_date is not None else ""
        super().__init__(
            "Oversell detected for "
            f"{symbol}{date_hint}: requested={round(self.requested_quantity, 8)}, "
            f"available={round(self.available_quantity, 8)}"
        )


@dataclass
class _AvgState:
    quantity: float = 0.0
    total_cost: float = 0.0


@dataclass(frozen=True)
class _ResolvedPositionPrice:
    price: float
    source: str
    price_date: Optional[date]
    is_stale: bool
    is_available: bool
    provider: Optional[str] = None


class PortfolioService:
    """Business logic for account CRUD, event writes, and snapshot replay."""

    def __init__(self, repo: Optional[PortfolioRepository] = None):
        self.repo = repo or PortfolioRepository()
        # 本次換算中查無匯率（走 1:1 回退）的幣別對，get_portfolio_snapshot 逐帳戶收集。
        self._fx_missing_pairs: Set[Tuple[str, str]] = set()
        # 快照估值日用到的匯率超過 PORTFOLIO_FX_MAX_AGE_DAYS 的幣別對（只在 get_portfolio_snapshot
        # 期間收集，見 _note_fx_rate_age）。
        self._fx_aged_pairs: Set[Tuple[str, str]] = set()
        self._fx_view_date: Optional[date] = None

    # ------------------------------------------------------------------
    # Account CRUD
    # ------------------------------------------------------------------
    def create_account(
        self,
        *,
        name: str,
        broker: Optional[str],
        market: str,
        base_currency: str,
        owner_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        name_norm = (name or "").strip()
        if not name_norm:
            raise ValueError("name is required")
        market_norm = self._normalize_market(market)
        base_currency_norm = self._normalize_currency(base_currency)
        row = self.repo.create_account(
            name=name_norm,
            broker=(broker or "").strip() or None,
            market=market_norm,
            base_currency=base_currency_norm,
            owner_id=(owner_id or "").strip() or None,
        )
        return self._account_to_dict(row)

    def list_accounts(self, include_inactive: bool = False) -> List[Dict[str, Any]]:
        rows = self.repo.list_accounts(include_inactive=include_inactive)
        return [self._account_to_dict(r) for r in rows]

    def update_account(
        self,
        account_id: int,
        *,
        name: Optional[str] = None,
        broker: Optional[str] = None,
        market: Optional[str] = None,
        base_currency: Optional[str] = None,
        owner_id: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        fields: Dict[str, Any] = {}
        if name is not None:
            name_norm = name.strip()
            if not name_norm:
                raise ValueError("name is required")
            fields["name"] = name_norm
        if broker is not None:
            fields["broker"] = broker.strip() or None
        if market is not None:
            fields["market"] = self._normalize_market(market)
        if base_currency is not None:
            fields["base_currency"] = self._normalize_currency(base_currency)
        if owner_id is not None:
            fields["owner_id"] = owner_id.strip() or None
        if is_active is not None:
            fields["is_active"] = bool(is_active)
        if not fields:
            raise ValueError("No fields provided for update")

        row = self.repo.update_account(account_id, fields)
        if row is None:
            return None
        return self._account_to_dict(row)

    def deactivate_account(self, account_id: int) -> bool:
        return self.repo.deactivate_account(account_id)

    # ------------------------------------------------------------------
    # Event writes
    # ------------------------------------------------------------------
    def record_trade(
        self,
        *,
        account_id: int,
        symbol: str,
        trade_date: date,
        side: str,
        quantity: float,
        price: float,
        fee: float = 0.0,
        tax: float = 0.0,
        market: Optional[str] = None,
        currency: Optional[str] = None,
        trade_uid: Optional[str] = None,
        dedup_hash: Optional[str] = None,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        side_norm = (side or "").strip().lower()
        if side_norm not in VALID_SIDES:
            raise ValueError("side must be buy or sell")
        if quantity <= 0 or price <= 0:
            raise ValueError("quantity and price must be > 0")
        if fee < 0 or tax < 0:
            raise ValueError("fee and tax must be >= 0")
        symbol_norm = self._normalize_symbol_for_storage(symbol)
        if not symbol_norm:
            raise ValueError("symbol is required")
        trade_uid_norm = (trade_uid or "").strip() or None
        dedup_hash_norm = (dedup_hash or "").strip() or None
        try:
            with self.repo.portfolio_write_session() as session:
                account = self._require_active_account_in_session(session=session, account_id=account_id)
                market_norm = self._normalize_market(market or account.market)
                currency_norm = self._normalize_currency(currency or self._default_currency_for_market(market_norm))
                self._validate_trade_identity(
                    account_id=account_id,
                    trade_uid=trade_uid_norm,
                    dedup_hash=dedup_hash_norm,
                    session=session,
                    )
                if side_norm == "sell":
                    self._validate_sell_quantity(
                        account_id=account_id,
                        symbol=symbol,
                        market=market_norm,
                        currency=currency_norm,
                        trade_date=trade_date,
                        quantity=float(quantity),
                        session=session,
                    )
                row = self.repo.add_trade_in_session(
                    session=session,
                    account_id=account_id,
                    trade_uid=trade_uid_norm,
                    symbol=symbol_norm,
                    market=market_norm,
                    currency=currency_norm,
                    trade_date=trade_date,
                    side=side_norm,
                    quantity=float(quantity),
                    price=float(price),
                    fee=float(fee),
                    tax=float(tax),
                    note=(note or "").strip() or None,
                    dedup_hash=dedup_hash_norm,
                )
                return {"id": int(row.id)}
        except (DuplicateTradeUidError, DuplicateTradeDedupHashError) as exc:
            raise PortfolioConflictError(str(exc)) from exc

    def record_cash_ledger(
        self,
        *,
        account_id: int,
        event_date: date,
        direction: str,
        amount: float,
        currency: Optional[str] = None,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        direction_norm = (direction or "").strip().lower()
        if direction_norm not in VALID_CASH_DIRECTIONS:
            raise ValueError("direction must be in or out")
        if amount <= 0:
            raise ValueError("amount must be > 0")
        with self.repo.portfolio_write_session() as session:
            account = self._require_active_account_in_session(session=session, account_id=account_id)
            currency_norm = self._normalize_currency(currency or account.base_currency)
            row = self.repo.add_cash_ledger_in_session(
                session=session,
                account_id=account_id,
                event_date=event_date,
                direction=direction_norm,
                amount=float(amount),
                currency=currency_norm,
                note=(note or "").strip() or None,
            )
            return {"id": int(row.id)}

    def record_corporate_action(
        self,
        *,
        account_id: int,
        symbol: str,
        effective_date: date,
        action_type: str,
        market: Optional[str] = None,
        currency: Optional[str] = None,
        cash_dividend_per_share: Optional[float] = None,
        split_ratio: Optional[float] = None,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        action_type_norm = (action_type or "").strip().lower()
        if action_type_norm not in VALID_CORPORATE_ACTIONS:
            raise ValueError("action_type must be cash_dividend or split_adjustment")

        if action_type_norm == "cash_dividend":
            if cash_dividend_per_share is None or cash_dividend_per_share < 0:
                raise ValueError("cash_dividend_per_share must be >= 0 for cash_dividend")
        if action_type_norm == "split_adjustment":
            if split_ratio is None or split_ratio <= 0:
                raise ValueError("split_ratio must be > 0 for split_adjustment")
        with self.repo.portfolio_write_session() as session:
            account = self._require_active_account_in_session(session=session, account_id=account_id)
            market_norm = self._normalize_market(market or account.market)
            currency_norm = self._normalize_currency(currency or self._default_currency_for_market(market_norm))
            symbol_norm = self._normalize_symbol_for_storage(symbol)
            if not symbol_norm:
                raise ValueError("symbol is required")
            row = self.repo.add_corporate_action_in_session(
                session=session,
                account_id=account_id,
                symbol=symbol_norm,
                market=market_norm,
                currency=currency_norm,
                effective_date=effective_date,
                action_type=action_type_norm,
                cash_dividend_per_share=cash_dividend_per_share,
                split_ratio=split_ratio,
                note=(note or "").strip() or None,
            )
            return {"id": int(row.id)}

    def delete_trade_event(self, trade_id: int) -> bool:
        with self.repo.portfolio_write_session() as session:
            return self.repo.delete_trade_in_session(session=session, trade_id=trade_id)

    def delete_cash_ledger_event(self, entry_id: int) -> bool:
        with self.repo.portfolio_write_session() as session:
            return self.repo.delete_cash_ledger_in_session(session=session, entry_id=entry_id)

    def delete_corporate_action_event(self, action_id: int) -> bool:
        with self.repo.portfolio_write_session() as session:
            return self.repo.delete_corporate_action_in_session(session=session, action_id=action_id)

    def list_trade_events(
        self,
        *,
        account_id: Optional[int] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        symbol: Optional[str] = None,
        side: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        if account_id is not None:
            self._require_active_account(account_id)
        page, page_size = self._validate_paging(page=page, page_size=page_size)
        if date_from is not None and date_to is not None and date_from > date_to:
            raise ValueError("date_from must be <= date_to")

        symbol_filters: Optional[List[str]] = None
        if symbol is not None and symbol.strip():
            symbol_filters = self._build_symbol_filter_values(symbol)
            if not symbol_filters:
                raise ValueError("symbol is invalid")

        side_norm: Optional[str] = None
        if side is not None and side.strip():
            side_norm = side.strip().lower()
            if side_norm not in VALID_SIDES:
                raise ValueError("side must be buy or sell")

        rows, total = self.repo.query_trades(
            account_id=account_id,
            date_from=date_from,
            date_to=date_to,
            symbols=symbol_filters,
            side=side_norm,
            page=page,
            page_size=page_size,
        )
        return {
            "items": [self._trade_row_to_dict(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def list_cash_ledger_events(
        self,
        *,
        account_id: Optional[int] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        direction: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        if account_id is not None:
            self._require_active_account(account_id)
        page, page_size = self._validate_paging(page=page, page_size=page_size)
        if date_from is not None and date_to is not None and date_from > date_to:
            raise ValueError("date_from must be <= date_to")

        direction_norm: Optional[str] = None
        if direction is not None and direction.strip():
            direction_norm = direction.strip().lower()
            if direction_norm not in VALID_CASH_DIRECTIONS:
                raise ValueError("direction must be in or out")

        rows, total = self.repo.query_cash_ledger(
            account_id=account_id,
            date_from=date_from,
            date_to=date_to,
            direction=direction_norm,
            page=page,
            page_size=page_size,
        )
        return {
            "items": [self._cash_ledger_row_to_dict(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def list_corporate_action_events(
        self,
        *,
        account_id: Optional[int] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        symbol: Optional[str] = None,
        action_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        if account_id is not None:
            self._require_active_account(account_id)
        page, page_size = self._validate_paging(page=page, page_size=page_size)
        if date_from is not None and date_to is not None and date_from > date_to:
            raise ValueError("date_from must be <= date_to")

        symbol_filters: Optional[List[str]] = None
        if symbol is not None and symbol.strip():
            symbol_filters = self._build_symbol_filter_values(symbol)
            if not symbol_filters:
                raise ValueError("symbol is invalid")

        action_norm: Optional[str] = None
        if action_type is not None and action_type.strip():
            action_norm = action_type.strip().lower()
            if action_norm not in VALID_CORPORATE_ACTIONS:
                raise ValueError("action_type must be cash_dividend or split_adjustment")

        rows, total = self.repo.query_corporate_actions(
            account_id=account_id,
            date_from=date_from,
            date_to=date_to,
            symbols=symbol_filters,
            action_type=action_norm,
            page=page,
            page_size=page_size,
        )
        return {
            "items": [self._corporate_action_row_to_dict(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    # ------------------------------------------------------------------
    # Snapshot replay
    # ------------------------------------------------------------------
    def get_portfolio_snapshot(
        self,
        *,
        account_id: Optional[int] = None,
        as_of: Optional[date] = None,
        cost_method: str = "fifo",
        include_realtime: bool = True,
        read_only: bool = False,
    ) -> Dict[str, Any]:
        """Replay holdings; read-only callers skip live quotes and snapshot writes."""
        as_of_date = as_of or date.today()
        method = self._normalize_cost_method(cost_method)

        if account_id is not None:
            account = self._require_active_account(account_id)
            account_rows = [account]
        else:
            account_rows = self.repo.list_accounts(include_inactive=False)

        self._fx_view_date = as_of_date
        try:
            return self._build_portfolio_snapshot(
                account_rows=account_rows,
                as_of_date=as_of_date,
                method=method,
                include_realtime=include_realtime,
                read_only=read_only,
            )
        finally:
            self._fx_view_date = None

    def _build_portfolio_snapshot(
        self,
        *,
        account_rows: List[Any],
        as_of_date: date,
        method: str,
        include_realtime: bool,
        read_only: bool,
    ) -> Dict[str, Any]:
        accounts_payload: List[Dict[str, Any]] = []
        aggregate_currency = PORTFOLIO_AGGREGATE_CURRENCY
        aggregate = {
            "total_cash": 0.0,
            "total_market_value": 0.0,
            "total_equity": 0.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "fee_total": 0.0,
            "tax_total": 0.0,
            "fx_stale": False,
            "limitations": [],
        }

        aggregate_missing_pairs: Set[Tuple[str, str]] = set()
        for account in account_rows:
            self._fx_missing_pairs = set()
            self._fx_aged_pairs = set()
            account_snapshot = self._replay_account(
                account=account,
                as_of_date=as_of_date,
                cost_method=method,
                include_realtime=include_realtime and not read_only,
            )
            # 帳戶內（交易幣別 → 帳戶幣別）查無匯率：帳戶自己的金額就已經是 1:1 冒充。
            account_missing_pairs = sorted(self._fx_missing_pairs)
            account_snapshot["public"]["fx_missing"] = bool(account_missing_pairs)
            account_snapshot["public"]["fx_missing_pairs"] = [
                _format_fx_pair(pair) for pair in account_missing_pairs
            ]

            if not read_only:
                self.repo.replace_positions_lots_and_snapshot(
                    account_id=account.id,
                    snapshot_date=as_of_date,
                    cost_method=method,
                    base_currency=account.base_currency,
                    total_cash=account_snapshot["total_cash"],
                    total_market_value=account_snapshot["total_market_value"],
                    total_equity=account_snapshot["total_equity"],
                    unrealized_pnl=account_snapshot["unrealized_pnl"],
                    realized_pnl=account_snapshot["realized_pnl"],
                    fee_total=account_snapshot["fee_total"],
                    tax_total=account_snapshot["tax_total"],
                    fx_stale=account_snapshot["fx_stale"],
                    payload=json.dumps(account_snapshot["payload"], ensure_ascii=False),
                    positions=account_snapshot["positions_cache"],
                    lots=account_snapshot["lots_cache"],
                    valuation_currency=account.base_currency,
                )

            # 匯率年齡只影響「現在看」的旗標，不寫進 daily snapshot 的 fx_stale（上面已落庫）：落庫的列會被回撤
            # 監控逐日 OR 180 天，把「當時匯率舊」存進去會讓回撤卡半年不可用。
            account_snapshot["public"]["fx_stale"] = bool(
                account_snapshot["fx_stale"] or self._fx_aged_pairs
            )
            accounts_payload.append(account_snapshot["public"])
            aggregate["limitations"] = _merge_portfolio_limitations(
                aggregate["limitations"],
                account_snapshot["public"].get("limitations", []),
            )

            cash_cny, stale_cash, _ = self._convert_amount(
                amount=account_snapshot["total_cash"],
                from_currency=account.base_currency,
                to_currency=aggregate_currency,
                as_of_date=as_of_date,
            )
            mv_cny, stale_mv, _ = self._convert_amount(
                amount=account_snapshot["total_market_value"],
                from_currency=account.base_currency,
                to_currency=aggregate_currency,
                as_of_date=as_of_date,
            )
            # 帳戶幣別換不到彙總幣別時，換算後的市值是假數字：給 null，不給 1:1 的值。
            account_snapshot["public"]["total_market_value_aggregate"] = (
                None
                if (self._normalize_currency(account.base_currency), aggregate_currency)
                in self._fx_missing_pairs
                else round(mv_cny, 6)
            )
            eq_cny, stale_eq, _ = self._convert_amount(
                amount=account_snapshot["total_equity"],
                from_currency=account.base_currency,
                to_currency=aggregate_currency,
                as_of_date=as_of_date,
            )
            realized_cny, stale_realized, _ = self._convert_amount(
                amount=account_snapshot["realized_pnl"],
                from_currency=account.base_currency,
                to_currency=aggregate_currency,
                as_of_date=as_of_date,
            )
            unrealized_cny, stale_unrealized, _ = self._convert_amount(
                amount=account_snapshot["unrealized_pnl"],
                from_currency=account.base_currency,
                to_currency=aggregate_currency,
                as_of_date=as_of_date,
            )
            fee_cny, stale_fee, _ = self._convert_amount(
                amount=account_snapshot["fee_total"],
                from_currency=account.base_currency,
                to_currency=aggregate_currency,
                as_of_date=as_of_date,
            )
            tax_cny, stale_tax, _ = self._convert_amount(
                amount=account_snapshot["tax_total"],
                from_currency=account.base_currency,
                to_currency=aggregate_currency,
                as_of_date=as_of_date,
            )

            aggregate["total_cash"] += cash_cny
            aggregate["total_market_value"] += mv_cny
            aggregate["total_equity"] += eq_cny
            aggregate["realized_pnl"] += realized_cny
            aggregate["unrealized_pnl"] += unrealized_cny
            aggregate["fee_total"] += fee_cny
            aggregate["tax_total"] += tax_cny
            aggregate["fx_stale"] = aggregate["fx_stale"] or any(
                [
                    stale_cash,
                    stale_mv,
                    stale_eq,
                    stale_realized,
                    stale_unrealized,
                    stale_fee,
                    stale_tax,
                ]
            ) or bool(self._fx_aged_pairs)
            aggregate_missing_pairs |= self._fx_missing_pairs

        return {
            "as_of": as_of_date.isoformat(),
            "cost_method": method,
            "currency": aggregate_currency,
            "account_count": len(account_rows),
            "total_cash": round(aggregate["total_cash"], 6),
            "total_market_value": round(aggregate["total_market_value"], 6),
            "total_equity": round(aggregate["total_equity"], 6),
            "realized_pnl": round(aggregate["realized_pnl"], 6),
            "unrealized_pnl": round(aggregate["unrealized_pnl"], 6),
            "fee_total": round(aggregate["fee_total"], 6),
            "tax_total": round(aggregate["tax_total"], 6),
            "fx_stale": aggregate["fx_stale"],
            # 有任一幣別對查無匯率時 total_* 含 1:1 冒充的金額，消費端要當成不可用。
            # 數值欄位保留（契約是 float），以這兩欄判斷。
            "fx_missing": bool(aggregate_missing_pairs),
            "fx_missing_pairs": [_format_fx_pair(pair) for pair in sorted(aggregate_missing_pairs)],
            "data_quality": "partial" if aggregate["limitations"] else "ok",
            "limitations": aggregate["limitations"],
            "accounts": accounts_payload,
        }

    def refresh_fx_rates(
        self,
        *,
        account_id: Optional[int] = None,
        as_of: Optional[date] = None,
    ) -> Dict[str, Any]:
        """Refresh account FX pairs online with stale fallback when fetch fails."""
        as_of_date = as_of or date.today()
        config = get_config()
        refresh_enabled = bool(getattr(config, "portfolio_fx_update_enabled", True))
        if account_id is not None:
            account_rows = [self._require_active_account(account_id)]
        else:
            account_rows = self.repo.list_accounts(include_inactive=False)

        summary = {
            "as_of": as_of_date.isoformat(),
            "account_count": len(account_rows),
            "refresh_enabled": refresh_enabled,
            "disabled_reason": None if refresh_enabled else PORTFOLIO_FX_REFRESH_DISABLED_REASON,
            "pair_count": 0,
            "updated_count": 0,
            "stale_count": 0,
            "error_count": 0,
        }
        token = _FX_DEADLINE.set(time.monotonic() + FX_REFRESH_BUDGET_SECONDS)
        try:
            for account in account_rows:
                item = self._refresh_account_fx_rates(
                    account=account,
                    as_of_date=as_of_date,
                    refresh_enabled=refresh_enabled,
                )
                summary["pair_count"] += item["pair_count"]
                summary["updated_count"] += item["updated_count"]
                summary["stale_count"] += item["stale_count"]
                summary["error_count"] += item["error_count"]
        finally:
            _FX_DEADLINE.reset(token)
        return summary

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _validate_trade_identity(
        self,
        *,
        account_id: int,
        trade_uid: Optional[str],
        dedup_hash: Optional[str],
        session: Optional[Any] = None,
    ) -> None:
        if trade_uid and self._has_trade_uid(account_id=account_id, trade_uid=trade_uid, session=session):
            raise PortfolioConflictError(f"Duplicate trade_uid for account_id={account_id}: {trade_uid}")
        if dedup_hash and self._has_trade_dedup_hash(account_id=account_id, dedup_hash=dedup_hash, session=session):
            raise PortfolioConflictError(f"Duplicate dedup_hash for account_id={account_id}: {dedup_hash}")

    def _validate_sell_quantity(
        self,
        *,
        account_id: int,
        symbol: str,
        market: str,
        currency: str,
        trade_date: date,
        quantity: float,
        session: Optional[Any] = None,
    ) -> None:
        key = (
            self._normalize_symbol_for_position(symbol),
            self._normalize_market(market),
            self._normalize_currency(currency),
        )
        available_quantity = self._calculate_available_quantity(
            account_id=account_id,
            key=key,
            as_of_date=trade_date,
            session=session,
        )
        if available_quantity + EPS < quantity:
            raise PortfolioOversellError(
                symbol=key[0],
                trade_date=trade_date,
                requested_quantity=quantity,
                available_quantity=available_quantity,
            )

    def _calculate_available_quantity(
        self,
        *,
        account_id: int,
        key: Tuple[str, str, str],
        as_of_date: date,
        session: Optional[Any] = None,
    ) -> float:
        if session is None:
            trades = self.repo.list_trades(account_id, as_of=as_of_date)
            corporate_actions = self.repo.list_corporate_actions(account_id, as_of=as_of_date)
        else:
            trades = self.repo.list_trades_in_session(session=session, account_id=account_id, as_of=as_of_date)
            corporate_actions = self.repo.list_corporate_actions_in_session(
                session=session,
                account_id=account_id,
                as_of=as_of_date,
            )

        events = []
        for row in corporate_actions:
            event_key = (
                self._normalize_symbol_for_position(row.symbol),
                self._normalize_market(row.market),
                self._normalize_currency(row.currency),
            )
            if event_key == key:
                events.append(("corp", row.effective_date, row.id, row))
        for row in trades:
            event_key = (
                self._normalize_symbol_for_position(row.symbol),
                self._normalize_market(row.market),
                self._normalize_currency(row.currency),
            )
            if event_key == key:
                events.append(("trade", row.trade_date, row.id, row))

        # Quantity validation only depends on position-changing events for one symbol.
        # Cash ledger entries do not affect shares held, so we keep the same corp->trade
        # ordering as full replay without pulling unrelated cash events into this path.
        event_priority = {"corp": 1, "trade": 2}
        events.sort(key=lambda item: (item[1], event_priority[item[0]], item[2]))

        quantity_held = 0.0
        for event_type, event_date, _, event in events:
            if event_type == "corp":
                action_type = (event.action_type or "").strip().lower()
                if action_type != "split_adjustment":
                    continue
                split_ratio = float(event.split_ratio or 0.0)
                if split_ratio <= 0:
                    raise ValueError(f"Invalid split_ratio for {key[0]}")
                if abs(split_ratio - 1.0) <= EPS:
                    continue
                quantity_held *= split_ratio
                continue

            qty = float(event.quantity or 0.0)
            if qty <= 0:
                raise ValueError(f"Invalid trade quantity for {key[0]}")
            side = (event.side or "").strip().lower()
            if side == "buy":
                quantity_held += qty
                continue
            if side != "sell":
                raise ValueError(f"Unsupported trade side: {event.side}")
            if quantity_held + EPS < qty:
                raise PortfolioOversellError(
                    symbol=key[0],
                    trade_date=event_date,
                    requested_quantity=qty,
                    available_quantity=quantity_held,
                )
            quantity_held -= qty
            if quantity_held <= EPS:
                quantity_held = 0.0

        return quantity_held

    def _replay_account(
        self,
        *,
        account: Any,
        as_of_date: date,
        cost_method: str,
        include_realtime: bool,
    ) -> Dict[str, Any]:
        trades = self.repo.list_trades(account.id, as_of=as_of_date)
        cash_ledger = self.repo.list_cash_ledger(account.id, as_of=as_of_date)
        corporate_actions = self.repo.list_corporate_actions(account.id, as_of=as_of_date)

        events = []
        for row in cash_ledger:
            events.append(("cash", row.event_date, row.id, row))
        for row in trades:
            events.append(("trade", row.trade_date, row.id, row))
        for row in corporate_actions:
            events.append(("corp", row.effective_date, row.id, row))

        # Same-day deterministic ordering: cash -> corporate action -> trade.
        event_priority = {"cash": 0, "corp": 1, "trade": 2}
        events.sort(key=lambda item: (item[1], event_priority[item[0]], item[2]))

        cash_balances: Dict[str, float] = defaultdict(float)
        fees_total_base = 0.0
        taxes_total_base = 0.0
        realized_pnl_base = 0.0
        fx_stale = False

        fifo_lots: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)
        avg_state: Dict[Tuple[str, str, str], _AvgState] = defaultdict(_AvgState)

        for event_type, event_date, _, event in events:
            if event_type == "cash":
                currency = self._normalize_currency(event.currency)
                amount = float(event.amount or 0.0)
                if event.direction == "in":
                    cash_balances[currency] += amount
                elif event.direction == "out":
                    cash_balances[currency] -= amount
                else:
                    raise ValueError(f"Unsupported cash direction: {event.direction}")
                continue

            if event_type == "trade":
                key = (
                    self._normalize_symbol_for_position(event.symbol),
                    self._normalize_market(event.market),
                    self._normalize_currency(event.currency),
                )
                qty = float(event.quantity or 0.0)
                price = float(event.price or 0.0)
                fee = float(event.fee or 0.0)
                tax = float(event.tax or 0.0)
                if qty <= 0 or price <= 0:
                    raise ValueError(f"Invalid trade quantity or price for {event.symbol}")

                gross = qty * price
                side = (event.side or "").lower().strip()
                if side == "buy":
                    cash_balances[key[2]] -= (gross + fee + tax)
                    if cost_method == "fifo":
                        unit_cost = (gross + fee + tax) / qty
                        fifo_lots[key].append(
                            {
                                "symbol": key[0],
                                "market": key[1],
                                "currency": key[2],
                                "open_date": event_date,
                                "remaining_quantity": qty,
                                "unit_cost": unit_cost,
                                "source_trade_id": event.id,
                            }
                        )
                    else:
                        state = avg_state[key]
                        state.quantity += qty
                        state.total_cost += (gross + fee + tax)
                elif side == "sell":
                    cash_balances[key[2]] += (gross - fee - tax)
                    proceeds_net = gross - fee - tax
                    if cost_method == "fifo":
                        cost_basis = self._consume_fifo_lots(
                            fifo_lots[key],
                            qty,
                            key[0],
                            event_date,
                        )
                    else:
                        cost_basis = self._consume_avg_position(
                            avg_state[key],
                            qty,
                            key[0],
                            event_date,
                        )
                    realized_local = proceeds_net - cost_basis
                    realized_base, stale_realized, _ = self._convert_amount(
                        amount=realized_local,
                        from_currency=key[2],
                        to_currency=account.base_currency,
                        as_of_date=event_date,
                    )
                    realized_pnl_base += realized_base
                    fx_stale = fx_stale or stale_realized
                else:
                    raise ValueError(f"Unsupported trade side: {event.side}")

                fee_base, stale_fee, _ = self._convert_amount(
                    amount=fee,
                    from_currency=key[2],
                    to_currency=account.base_currency,
                    as_of_date=event_date,
                )
                tax_base, stale_tax, _ = self._convert_amount(
                    amount=tax,
                    from_currency=key[2],
                    to_currency=account.base_currency,
                    as_of_date=event_date,
                )
                fees_total_base += fee_base
                taxes_total_base += tax_base
                fx_stale = fx_stale or stale_fee or stale_tax
                continue

            if event_type == "corp":
                key = (
                    self._normalize_symbol_for_position(event.symbol),
                    self._normalize_market(event.market),
                    self._normalize_currency(event.currency),
                )
                action_type = (event.action_type or "").strip().lower()
                if action_type == "cash_dividend":
                    per_share = float(event.cash_dividend_per_share or 0.0)
                    if per_share <= 0:
                        continue
                    qty_held = self._held_quantity(
                        key=key,
                        cost_method=cost_method,
                        fifo_lots=fifo_lots,
                        avg_state=avg_state,
                    )
                    if qty_held > EPS:
                        cash_balances[key[2]] += qty_held * per_share
                elif action_type == "split_adjustment":
                    split_ratio = float(event.split_ratio or 0.0)
                    if split_ratio <= 0:
                        raise ValueError(f"Invalid split_ratio for {event.symbol}")
                    if abs(split_ratio - 1.0) <= EPS:
                        continue
                    if cost_method == "fifo":
                        for lot in fifo_lots[key]:
                            lot["remaining_quantity"] *= split_ratio
                            lot["unit_cost"] /= split_ratio
                    else:
                        state = avg_state[key]
                        state.quantity *= split_ratio
                else:
                    raise ValueError(f"Unsupported corporate action type: {event.action_type}")

        position_rows, lot_rows, market_value_base, total_cost_base, stale_pos = self._build_positions(
            account=account,
            as_of_date=as_of_date,
            cost_method=cost_method,
            fifo_lots=fifo_lots,
            avg_state=avg_state,
            include_realtime=include_realtime,
        )
        fx_stale = fx_stale or stale_pos

        total_cash_base = 0.0
        for currency, amount in cash_balances.items():
            converted, stale, _ = self._convert_amount(
                amount=amount,
                from_currency=currency,
                to_currency=account.base_currency,
                as_of_date=as_of_date,
            )
            total_cash_base += converted
            fx_stale = fx_stale or stale

        unrealized_pnl_base = market_value_base - total_cost_base
        total_equity_base = total_cash_base + market_value_base
        position_limitations = [
            limitation
            for position in position_rows
            for limitation in position.get("limitations", [])
        ]
        limitations = _merge_portfolio_limitations(
            _portfolio_limitations_for_market(account.market),
            position_limitations,
        )

        account_payload = {
            "account_id": account.id,
            "account_name": account.name,
            "owner_id": account.owner_id,
            "broker": account.broker,
            "market": account.market,
            "base_currency": account.base_currency,
            "as_of": as_of_date.isoformat(),
            "cost_method": cost_method,
            "total_cash": round(total_cash_base, 6),
            "total_market_value": round(market_value_base, 6),
            "total_equity": round(total_equity_base, 6),
            "realized_pnl": round(realized_pnl_base, 6),
            "unrealized_pnl": round(unrealized_pnl_base, 6),
            "fee_total": round(fees_total_base, 6),
            "tax_total": round(taxes_total_base, 6),
            "fx_stale": fx_stale,
            "data_quality": "partial" if limitations else "ok",
            "limitations": limitations,
            "positions": position_rows,
        }

        return {
            "public": account_payload,
            "payload": account_payload,
            "positions_cache": position_rows,
            "lots_cache": lot_rows,
            "total_cash": float(total_cash_base),
            "total_market_value": float(market_value_base),
            "total_equity": float(total_equity_base),
            "realized_pnl": float(realized_pnl_base),
            "unrealized_pnl": float(unrealized_pnl_base),
            "fee_total": float(fees_total_base),
            "tax_total": float(taxes_total_base),
            "fx_stale": fx_stale,
        }

    def _build_positions(
        self,
        *,
        account: Any,
        as_of_date: date,
        cost_method: str,
        fifo_lots: Dict[Tuple[str, str, str], List[Dict[str, Any]]],
        avg_state: Dict[Tuple[str, str, str], _AvgState],
        include_realtime: bool = True,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], float, float, bool]:
        position_rows: List[Dict[str, Any]] = []
        lot_rows: List[Dict[str, Any]] = []
        market_value_base = 0.0
        total_cost_base = 0.0
        fx_stale = False

        keys: Iterable[Tuple[str, str, str]]
        if cost_method == "fifo":
            keys = list(fifo_lots.keys())
        else:
            keys = list(avg_state.keys())

        active_symbols: List[str] = []
        if include_realtime and as_of_date == date.today():
            for key in sorted(keys):
                symbol, _, _ = key
                if cost_method == "fifo":
                    qty = sum(
                        float(lot["remaining_quantity"])
                        for lot in fifo_lots[key]
                        if lot["remaining_quantity"] > EPS
                    )
                else:
                    qty = float(avg_state[key].quantity)
                if qty > EPS:
                    active_symbols.append(symbol)
        realtime_prices = (
            self._prefetch_realtime_position_prices(active_symbols)
            if active_symbols
            else None
        )

        for key in sorted(keys):
            symbol, market, currency = key

            if cost_method == "fifo":
                active_lots = [lot for lot in fifo_lots[key] if lot["remaining_quantity"] > EPS]
                qty = sum(float(lot["remaining_quantity"]) for lot in active_lots)
                if qty <= EPS:
                    continue
                total_cost = sum(float(lot["remaining_quantity"]) * float(lot["unit_cost"]) for lot in active_lots)
                avg_cost = total_cost / qty
                lot_rows.extend(active_lots)
            else:
                state = avg_state[key]
                qty = float(state.quantity)
                total_cost = float(state.total_cost)
                if qty <= EPS:
                    continue
                avg_cost = total_cost / qty
                lot_rows.append(
                    {
                        "symbol": symbol,
                        "market": market,
                        "currency": currency,
                        "open_date": as_of_date,
                        "remaining_quantity": qty,
                        "unit_cost": avg_cost,
                        "source_trade_id": None,
                    }
                )

            price_info = self._resolve_position_price(
                symbol=symbol,
                as_of_date=as_of_date,
                realtime_prices=realtime_prices,
                include_realtime=include_realtime,
            )
            last_price = price_info.price
            limitations = _portfolio_limitations_for_market(market)

            if price_info.is_available:
                local_market_value = qty * float(last_price)
                market_base, stale_market, _ = self._convert_amount(
                    amount=local_market_value,
                    from_currency=currency,
                    to_currency=account.base_currency,
                    as_of_date=as_of_date,
                )
                cost_base, stale_cost, _ = self._convert_amount(
                    amount=total_cost,
                    from_currency=currency,
                    to_currency=account.base_currency,
                    as_of_date=as_of_date,
                )
                unrealized_base = market_base - cost_base
                fx_stale = fx_stale or stale_market or stale_cost
            else:
                market_base = 0.0
                cost_base = 0.0
                unrealized_base = 0.0

            unrealized_pct = None
            if abs(cost_base) > EPS:
                unrealized_pct = unrealized_base / cost_base * 100.0

            position_rows.append(
                {
                    "symbol": symbol,
                    "name": get_index_stock_name(symbol),
                    "market": market,
                    "currency": currency,
                    "quantity": round(qty, 8),
                    "avg_cost": round(avg_cost, 8),
                    "total_cost": round(total_cost, 8),
                    "last_price": round(float(last_price), 8),
                    "market_value_base": round(market_base, 8),
                    "unrealized_pnl_base": round(unrealized_base, 8),
                    "unrealized_pnl_pct": round(unrealized_pct, 8) if unrealized_pct is not None else None,
                    "valuation_currency": account.base_currency,
                    "price_source": price_info.source,
                    "price_provider": price_info.provider,
                    "price_date": price_info.price_date.isoformat() if price_info.price_date else None,
                    "price_stale": price_info.is_stale,
                    "price_available": price_info.is_available,
                    "data_quality": "partial" if limitations else "ok",
                    "limitations": limitations,
                }
            )

            market_value_base += market_base
            total_cost_base += cost_base

        return position_rows, lot_rows, market_value_base, total_cost_base, fx_stale

    def _resolve_position_price(
        self,
        *,
        symbol: str,
        as_of_date: date,
        realtime_prices: Optional[Dict[str, Tuple[Optional[float], Optional[str]]]] = None,
        include_realtime: bool = True,
    ) -> _ResolvedPositionPrice:
        today = date.today()

        if include_realtime and as_of_date == today:
            if realtime_prices is None:
                realtime_price, provider = self._fetch_realtime_position_price(symbol)
            else:
                realtime_price, provider = realtime_prices.get(symbol, (None, None))
            if realtime_price is not None and realtime_price > 0:
                return _ResolvedPositionPrice(
                    price=float(realtime_price),
                    source="realtime_quote",
                    price_date=today,
                    is_stale=False,
                    is_available=True,
                    provider=provider,
                )

        close = self.repo.get_latest_close_with_date(symbol=symbol, as_of=as_of_date)
        if close is not None:
            close_price, close_date = close
            if close_price > 0:
                return _ResolvedPositionPrice(
                    price=float(close_price),
                    source="history_close",
                    price_date=close_date,
                    is_stale=close_date < as_of_date,
                    is_available=True,
                )

        return _ResolvedPositionPrice(
            price=0.0,
            source="missing",
            price_date=None,
            is_stale=True,
            is_available=False,
        )

    def _prefetch_realtime_position_prices(
        self,
        symbols: Iterable[str],
    ) -> Dict[str, Tuple[Optional[float], Optional[str]]]:
        unique_symbols = sorted({symbol for symbol in symbols if symbol})
        if not unique_symbols:
            return {}

        # Bulk prefetch (when applicable) only warms the fetcher-module-level realtime cache;
        # the manager itself is discarded so per-symbol workers cannot serialize through its
        # per-fetcher call locks when individual reads still need a live fetch (e.g. mixed
        # markets, cache miss, or bulk source returning fewer rows than requested).
        if len(unique_symbols) >= 5:
            try:
                from data_provider.base import DataFetcherManager

                DataFetcherManager().prefetch_realtime_quotes(unique_symbols)
            except Exception as exc:
                logger.warning("Failed to prefetch realtime portfolio quotes: %s", exc)

        if len(unique_symbols) == 1:
            symbol = unique_symbols[0]
            return {symbol: self._fetch_realtime_position_price(symbol)}

        results: Dict[str, Tuple[Optional[float], Optional[str]]] = {}
        max_workers = min(PORTFOLIO_REALTIME_QUOTE_MAX_WORKERS, len(unique_symbols))
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="portfolio-quote") as executor:
            futures = {
                executor.submit(self._fetch_realtime_position_price, symbol): symbol
                for symbol in unique_symbols
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    results[symbol] = future.result()
                except Exception as exc:  # pragma: no cover - defensive guard for patched fetchers
                    logger.warning("Failed to prefetch realtime portfolio price for %s: %s", symbol, exc)
                    results[symbol] = (None, None)

        return results

    @staticmethod
    def _fetch_realtime_position_price(symbol: str) -> Tuple[Optional[float], Optional[str]]:
        try:
            from data_provider.base import DataFetcherManager

            fetcher_manager = DataFetcherManager()
            # 持仓快照只读 price + source（见下），跳过仅补市值的 yfinance 往返（台股有 Shioaji 报价时）；
            # 与看板 /quotes 同一 skip 模式。Shioaji 无报价时 base.py 仍自动降级 yfinance 取价。
            quote = fetcher_manager.get_realtime_quote(
                symbol, log_final_failure=False, skip_supplement=True
            )
        except Exception as exc:
            logger.warning("Failed to fetch realtime portfolio price for %s: %s", symbol, exc)
            return None, None

        if quote is None:
            return None, None

        price = getattr(quote, "price", None)
        try:
            numeric_price = float(price)
        except (TypeError, ValueError):
            return None, None

        if numeric_price <= 0:
            return None, None

        source = getattr(quote, "source", None)
        provider = getattr(source, "value", None) or (str(source) if source is not None else None)
        return numeric_price, provider

    @staticmethod
    def _normalize_symbol_for_storage(symbol: str) -> str:
        return canonical_stock_code(symbol)

    @staticmethod
    def _normalize_symbol_for_position(symbol: str) -> str:
        if not (symbol or "").strip():
            return ""

        raw = canonical_stock_code(symbol)
        if len(raw) >= 8 and raw[:2] in {"SH", "SZ", "BJ"} and raw[2:].isdigit():
            return raw

        if "." in raw:
            base, suffix = raw.rsplit(".", 1)
            if base.isdigit() and suffix in {"SH", "SS", "SZ", "BJ"}:
                exchange = "SH" if suffix == "SS" else suffix
                return f"{exchange}{base}"

        return canonical_stock_code(normalize_stock_code(symbol))

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """
        Canonicalization for symbol filtering with exchange-qualified input preservation.

        Keep explicit A-share exchange annotations (SH/SZ/BJ) intact to avoid collapsing
        different exchange variants of the same 6-digit core code.
        """
        raw = canonical_stock_code(symbol)
        if not raw:
            return ""

        if len(raw) >= 8 and raw[:2] in {"SH", "SZ", "BJ"} and raw[2:].isdigit():
            return raw

        if "." in raw:
            base, suffix = raw.rsplit(".", 1)
            if base.isdigit() and suffix in {"SH", "SS", "SZ", "BJ"}:
                exchange = "SH" if suffix == "SS" else suffix
                return f"{exchange}{base}"

        return canonical_stock_code(normalize_stock_code(symbol))

    @classmethod
    def _build_symbol_filter_values(cls, symbol: str) -> List[str]:
        original = (symbol or "").strip().upper()
        normalized = cls._normalize_symbol(original)
        if not normalized:
            return []

        seen: Set[str] = set()
        values: List[str] = []

        def _add(value: Optional[str]) -> None:
            candidate = (value or "").strip().upper()
            if candidate and candidate not in seen:
                seen.add(candidate)
                values.append(candidate)

        _add(original)
        _add(normalized)

        if normalized.startswith("HK"):
            hk_digits = normalized[2:]
            if hk_digits.isdigit() and len(hk_digits) == 5:
                legacy_hk_digits = str(int(hk_digits))
                _add(f"HK{hk_digits}")
                _add(f"HK{legacy_hk_digits}")
                _add(f"{hk_digits}.HK")
                _add(f"{legacy_hk_digits}.HK")
            return values

        explicit_exchange: Optional[str] = None
        if len(original) >= 8 and original[:2] in {"SH", "SZ", "BJ"} and original[2:].isdigit():
            explicit_exchange = original[:2]
            explicit_code = original[2:]
        elif "." in original:
            base, suffix = original.rsplit(".", 1)
            if base.isdigit() and suffix in {"SH", "SS", "SZ", "BJ"}:
                explicit_exchange = "SH" if suffix == "SS" else suffix
                explicit_code = base
            else:
                explicit_code = None
        else:
            explicit_code = None

        if normalized.isdigit():
            if len(normalized) == 6:
                exchanges = [explicit_exchange] if explicit_exchange else ["SH", "SZ", "BJ"]
                for exchange in exchanges:
                    if exchange is None:
                        continue
                    _add(f"{exchange}{normalized}")
                    _add(f"{normalized}.{'SS' if exchange == 'SH' else exchange}")
                    if exchange == "SH":
                        _add(f"{normalized}.SH")
            return values

        if explicit_exchange is not None and explicit_code is not None and explicit_code.isdigit():
            if len(explicit_code) == 6:
                _add(f"{explicit_exchange}{explicit_code}")
                _add(f"{explicit_code}.{'SS' if explicit_exchange == 'SH' else explicit_exchange}")
                if explicit_exchange == "SH":
                    _add(f"{explicit_code}.SH")
            elif len(normalized) == 5:
                _add(f"HK{normalized}")
                _add(f"{normalized}.HK")

        return values

    @staticmethod
    def _consume_fifo_lots(
        lots: List[Dict[str, Any]],
        quantity: float,
        symbol: str,
        trade_date: Optional[date] = None,
    ) -> float:
        remaining = quantity
        cost_basis = 0.0
        while remaining > EPS:
            if not lots:
                raise PortfolioOversellError(
                    symbol=symbol,
                    trade_date=trade_date,
                    requested_quantity=quantity,
                    available_quantity=quantity - remaining,
                )
            head = lots[0]
            take = min(remaining, float(head["remaining_quantity"]))
            cost_basis += take * float(head["unit_cost"])
            head["remaining_quantity"] = float(head["remaining_quantity"]) - take
            remaining -= take
            if head["remaining_quantity"] <= EPS:
                lots.pop(0)
        return cost_basis

    @staticmethod
    def _consume_avg_position(
        state: _AvgState,
        quantity: float,
        symbol: str,
        trade_date: Optional[date] = None,
    ) -> float:
        if state.quantity + EPS < quantity:
            raise PortfolioOversellError(
                symbol=symbol,
                trade_date=trade_date,
                requested_quantity=quantity,
                available_quantity=state.quantity,
            )
        if state.quantity <= EPS:
            raise PortfolioOversellError(
                symbol=symbol,
                trade_date=trade_date,
                requested_quantity=quantity,
                available_quantity=0.0,
            )
        avg_cost = state.total_cost / state.quantity
        cost_basis = avg_cost * quantity
        state.quantity -= quantity
        state.total_cost -= cost_basis
        if state.quantity <= EPS:
            state.quantity = 0.0
            state.total_cost = 0.0
        return cost_basis

    @staticmethod
    def _held_quantity(
        *,
        key: Tuple[str, str, str],
        cost_method: str,
        fifo_lots: Dict[Tuple[str, str, str], List[Dict[str, Any]]],
        avg_state: Dict[Tuple[str, str, str], _AvgState],
    ) -> float:
        if cost_method == "fifo":
            return sum(float(lot["remaining_quantity"]) for lot in fifo_lots.get(key, []))
        return float(avg_state.get(key, _AvgState()).quantity)

    def _convert_amount(
        self,
        *,
        amount: float,
        from_currency: str,
        to_currency: str,
        as_of_date: date,
    ) -> Tuple[float, bool, str]:
        from_norm = self._normalize_currency(from_currency)
        to_norm = self._normalize_currency(to_currency)
        if abs(amount) <= EPS:
            return 0.0, False, "zero"
        if from_norm == to_norm:
            return float(amount), False, "identity"

        direct = self.repo.get_latest_fx_rate(
            from_currency=from_norm,
            to_currency=to_norm,
            as_of=as_of_date,
        )
        if direct is not None and direct.rate > 0:
            self._note_fx_rate_age(direct, (from_norm, to_norm), as_of_date)
            return float(amount) * float(direct.rate), bool(direct.is_stale), "direct_rate"

        inverse = self.repo.get_latest_fx_rate(
            from_currency=to_norm,
            to_currency=from_norm,
            as_of=as_of_date,
        )
        if inverse is not None and inverse.rate > 0:
            self._note_fx_rate_age(inverse, (from_norm, to_norm), as_of_date)
            return float(amount) / float(inverse.rate), bool(inverse.is_stale), "inverse_rate"

        # P0 fallback: keep pipeline available even when FX cache is missing.
        # 金額沒有換算，記下這一對讓快照把彙總標成不可用（見 get_portfolio_snapshot）。
        missing_pairs = getattr(self, "_fx_missing_pairs", None)
        if missing_pairs is not None:
            missing_pairs.add((from_norm, to_norm))
        return float(amount), True, FX_FALLBACK_SOURCE

    @staticmethod
    def _is_fx_date_aged(rate_date: Any, as_of_date: date) -> bool:
        """日期距 as_of_date 超過 PORTFOLIO_FX_MAX_AGE_DAYS（拿不到日期也算）。"""
        if isinstance(rate_date, datetime):
            rate_date = rate_date.date()
        if not isinstance(rate_date, date):
            return True
        return (as_of_date - rate_date).days > PORTFOLIO_FX_MAX_AGE_DAYS

    @classmethod
    def _is_fx_rate_aged(cls, rate_row: Any, as_of_date: date) -> bool:
        """匯率日期距 as_of_date 超過 PORTFOLIO_FX_MAX_AGE_DAYS（拿不到日期也算）。"""
        return cls._is_fx_date_aged(getattr(rate_row, "rate_date", None), as_of_date)

    def _note_fx_rate_age(self, rate_row: Any, pair: Tuple[str, str], as_of_date: date) -> None:
        """快照估值日的換算用到舊匯率時記下幣別對；回傳的 stale 仍只看寫入時的 is_stale。

        `is_stale` 只在寫入時決定，手動刷新一次之後就一直是 False——8 天前的匯率照樣顯示「最新」，
        所以「現在看」的快照要再看匯率年齡。但這個年齡判定只對估值日成立：歷史日期（交易日的
        已實現損益、回撤監控逐日換算）查得到的永遠是當時之前最後一次刷新的匯率，刷新只會寫
        今天的日期，套年齡會讓它們永遠過期、按「刷新匯率」也救不回來。
        """
        view_date = getattr(self, "_fx_view_date", None)
        aged_pairs = getattr(self, "_fx_aged_pairs", None)
        if view_date is None or aged_pairs is None or as_of_date != view_date:
            return
        if self._is_fx_rate_aged(rate_row, as_of_date):
            aged_pairs.add(pair)

    def convert_amount(
        self,
        *,
        amount: float,
        from_currency: str,
        to_currency: str,
        as_of_date: date,
    ) -> Tuple[float, bool, str]:
        """Public conversion entry for cross-service consumers."""
        return self._convert_amount(
            amount=amount,
            from_currency=from_currency,
            to_currency=to_currency,
            as_of_date=as_of_date,
        )

    def _list_account_refresh_fx_currencies(
        self,
        *,
        account: Any,
        as_of_date: date,
        strict: bool = True,
    ) -> List[str]:
        """Return distinct non-base currencies participating in refresh for one account."""
        base_currency = self._normalize_currency(account.base_currency)
        currencies: Set[str] = set()
        rows = list(self.repo.list_trades(account.id, as_of=as_of_date))
        rows.extend(self.repo.list_cash_ledger(account.id, as_of=as_of_date))
        for row in rows:
            try:
                currency = self._normalize_currency(row.currency)
            except ValueError:
                if strict:
                    raise
                logger.warning(
                    "Skip invalid FX refresh currency for account %s on %s: %r",
                    account.id,
                    as_of_date.isoformat(),
                    getattr(row, "currency", None),
                )
                continue
            if currency != base_currency:
                currencies.add(currency)
        return sorted(currencies)

    def _refresh_account_fx_rates(
        self,
        *,
        account: Any,
        as_of_date: date,
        refresh_enabled: bool,
    ) -> Dict[str, int]:
        """Refresh FX pairs for one account and keep stale fallback on failures."""
        refresh_currencies = self._list_account_refresh_fx_currencies(
            account=account,
            as_of_date=as_of_date,
            strict=refresh_enabled,
        )
        base_currency = self._normalize_currency(account.base_currency)
        pairs = [(currency, base_currency) for currency in refresh_currencies]
        # 快照汇总要把帐户币别换成 CNY；不刷新这一对，非 CNY 帐户（如台币、美元）的汇总
        # 只能走 1:1 回退，台币数字被标成人民币、整页标记汇率过期。
        if base_currency != PORTFOLIO_AGGREGATE_CURRENCY:
            pairs.append((base_currency, PORTFOLIO_AGGREGATE_CURRENCY))
        if not refresh_enabled:
            return {
                "pair_count": len(pairs),
                "updated_count": 0,
                "stale_count": 0,
                "error_count": 0,
            }

        summary = {
            "pair_count": len(pairs),
            "updated_count": 0,
            "stale_count": 0,
            "error_count": 0,
        }
        for from_currency, to_currency in pairs:
            # `accepted` is only set after the outlier filter succeeds; raw downloads never reach the fallback.
            accepted: List[Tuple[date, float]] = []
            repairs: Dict[date, float] = {}
            all_rejected = False
            try:
                # One download feeds both today's rate and the history backfill.
                fetched = self._fetch_fx_closes_from_yfinance(
                    from_currency=from_currency,
                    to_currency=to_currency,
                    as_of_date=as_of_date,
                )
                fetched_last = fetched[-1] if fetched else None
                # Nothing downloaded means nothing to check: skip the four USD-leg requests.
                cross_closes = (
                    self._fetch_fx_cross_closes(
                        from_currency=from_currency, to_currency=to_currency, as_of_date=as_of_date
                    )
                    if fetched
                    else {}
                )
                rejected_references: Dict[date, Tuple[float, ...]] = {}
                closes = accepted = self._filter_fx_outliers(
                    from_currency=from_currency,
                    to_currency=to_currency,
                    as_of_date=as_of_date,
                    closes=fetched,
                    cross_closes=cross_closes,
                    rejected_references=rejected_references,
                )
                all_rejected = bool(fetched) and not closes
                kept_dates = {d for d, _ in closes}
                # Bars the cross check rejected: their stored auto rows may hold the same junk (see backfill).
                repairs = {d: cross_closes[d] for d, _ in fetched if d not in kept_dates and d in cross_closes}
                # 拒收日期的自動列也不可信；先清除，避免回退或下一次快照重新選中舊垃圾列。
                self._discard_auto_fx_rates(
                    from_currency=from_currency,
                    to_currency=to_currency,
                    dates={d for d, _ in fetched} - kept_dates,
                    references=rejected_references,
                )
                # If the newest bar was rejected, today's rate must not silently become an older bar.
                rate = None
                if closes and closes[-1] == fetched_last:
                    bar_date, last_rate = closes[-1]
                    # 以資料本身的日期判斷年齡；刷新日期不能讓凍結來源重新變新鮮。
                    if not self._is_fx_date_aged(bar_date, as_of_date):
                        rate = last_rate
                    else:
                        logger.warning(
                            "匯率 %s/%s 最新K棒停在 %s，距 %s 超過 %d 天，視為過期",
                            from_currency, to_currency, bar_date.isoformat(), as_of_date.isoformat(),
                            PORTFOLIO_FX_MAX_AGE_DAYS,
                        )
                # Backfill the bars that passed the filter even when the newest one was rejected, so the
                # stale carry below starts from the latest accepted value instead of an older stored one.
                self._backfill_fx_history(
                    from_currency=from_currency,
                    to_currency=to_currency,
                    as_of_date=as_of_date,
                    closes=closes,
                    repairs=repairs,
                )
                if rate is not None and rate > 0:
                    self.repo.save_fx_rate(
                        from_currency=from_currency,
                        to_currency=to_currency,
                        rate_date=as_of_date,
                        rate=rate,
                        source="yfinance",
                        is_stale=False,
                    )
                    summary["updated_count"] += 1
                    continue
            except Exception as exc:
                logger.warning(
                    "FX online fetch failed for %s/%s on %s: %s",
                    from_currency,
                    to_currency,
                    as_of_date.isoformat(),
                    exc,
                )

            carry: Optional[Tuple[date, float]] = accepted[-1] if accepted else None
            # A repaired (cross-rate) day newer than the last accepted bar is the freshest known value.
            last_finished = min(as_of_date, self._london_today())
            for repair_date, repair_rate in repairs.items():
                if (carry is None or carry[0] < repair_date) and repair_date < last_finished:
                    carry = (repair_date, repair_rate)
            if carry is not None:
                # Carry from the newest accepted/repaired bar, not from an older same-day carry row.
                fallback = SimpleNamespace(rate=carry[1], source="yfinance")
            elif all_rejected:
                # 已清掉拒收日期的自動列；只從其餘非 stale 實值回退，保留手動來源。
                last_real = self._last_real_stored_rate(
                    from_currency=from_currency, to_currency=to_currency, before=as_of_date
                )
                fallback = SimpleNamespace(rate=last_real, source="yfinance") if last_real else None
                if fallback is None:
                    # No clean value to carry: drop today's automated (junk) row so conversion reports the
                    # pair as missing instead of using it. Manual rows are never touched.
                    self._discard_auto_fx_rates(
                        from_currency=from_currency, to_currency=to_currency,
                        dates={as_of_date},
                    )
            else:
                fallback = self.repo.get_latest_fx_rate(
                    from_currency=from_currency,
                    to_currency=to_currency,
                    as_of=as_of_date,
                )
            if fallback is not None and float(fallback.rate or 0.0) > 0:
                self.repo.save_fx_rate(
                    from_currency=from_currency,
                    to_currency=to_currency,
                    rate_date=as_of_date,
                    rate=float(fallback.rate),
                    source=(fallback.source or "cache_fallback"),
                    is_stale=True,
                )
                summary["stale_count"] += 1
            else:
                summary["error_count"] += 1
        return summary

    def _discard_auto_fx_rates(
        self, *, from_currency: str, to_currency: str, dates: Iterable[date],
        references: Optional[Dict[date, Tuple[float, ...]]] = None,
    ) -> None:
        """使不可信自動列失效；已符合任一拒收參考值的實值與手動來源保留。

        中間K棒須同時偏離前後鄰居才拒收，因此參考值可有多個；存值只要符合其一就能通過同一判定，不可刪。
        """
        for rate_date in sorted(set(dates)):
            candidates = (references or {}).get(rate_date) or ()
            if candidates:
                existing = self.repo.get_latest_fx_rate(
                    from_currency=from_currency, to_currency=to_currency, as_of=rate_date,
                )
                if (
                    existing is not None and existing.rate_date == rate_date and not existing.is_stale
                    and any(not _fx_rates_deviate(float(existing.rate), ref) for ref in candidates)
                ):
                    continue
            removed = self.repo.delete_fx_rate(
                from_currency=from_currency, to_currency=to_currency,
                rate_date=rate_date, only_sources=FX_AUTO_SOURCES,
            )
            if removed:
                logger.warning(
                    "匯率 %s/%s %s 無可信自動值，已刪除自動來源列",
                    from_currency, to_currency, rate_date.isoformat(),
                )

    @staticmethod
    def _fetch_fx_closes_from_yfinance(
        *,
        from_currency: str,
        to_currency: str,
        as_of_date: date,
    ) -> List[Tuple[date, float]]:
        """Fetch FX closes as (london_date, close) for [as_of-7d, as_of], NaN, non-positive, Saturday and weekend-daily bars dropped.

        yfinance 1d FX bars are dated on the London calendar and their Close is roughly the 00:00 London
        open (USDTWD 2026-10-22: 1d Close 32.366 vs the 23:00 hourly bar 32.597), i.e. a day behind. So a
        London day's close is its last 1h bar; without hourly data use the next daily bar's Open, and only
        as a last resort the daily Close (logged).
        """
        if yf is None:
            return []
        symbol = f"{from_currency}{to_currency}=X"
        start = (as_of_date - timedelta(days=7)).isoformat()
        closes: Dict[date, float] = {}
        try:
            hourly = _fx_call(
                _ticker_history, symbol,
                start=start, end=(as_of_date + timedelta(days=1)).isoformat(), interval="1h", auto_adjust=False,
            )
            if hourly is not None and not hourly.empty and "Close" in hourly:
                for ts, value in hourly["Close"].dropna().items():
                    # Bars are chronological, so the last assignment per day is the day's last bar.
                    # Saturday has no session; Sunday-evening bars are the real FX reopening and must stay
                    if float(value) > 0 and _london_date(ts) <= as_of_date and _london_date(ts).weekday() != 5:
                        closes[_london_date(ts)] = float(value)
        except Exception as exc:
            logger.warning("匯率 1h 資料取得失敗 %s，改用日K：%s", symbol, exc)

        # Daily bars fill London days without hourly data; the end is a few days past as_of only to get the
        # successor bar's Open (output stays <= as_of).
        try:
            daily = _fx_call(
                _ticker_history, symbol,
                start=start, end=(as_of_date + timedelta(days=4)).isoformat(), interval="1d", auto_adjust=False,
            )
            if daily is not None and not daily.empty and "Close" in daily:
                # 主匯率與 USD 交叉腿共用此處：目標與後繼日 K 都只能來自平日。
                rows = [(_london_date(ts), row) for ts, row in daily.iterrows() if _london_date(ts).weekday() < 5]
                for i, (bar_date, row) in enumerate(rows):
                    # No daily close on London weekends; Yahoo's Saturday bar repeats stale junk (10-24: 0.1963)
                    if bar_date > as_of_date or bar_date in closes or bar_date.weekday() >= 5:
                        continue
                    value = rows[i + 1][1].get("Open") if i + 1 < len(rows) else None
                    if value is None or value != value or float(value) <= 0:
                        value = row.get("Close")
                        logger.warning("匯率 %s %s 無 1h 也無次日開盤，退回日K收盤（可能落後一天）", symbol, bar_date)
                    if value is not None and value == value and float(value) > 0:
                        closes[bar_date] = float(value)
        except Exception as exc:
            logger.warning("匯率日K資料取得失敗 %s：%s", symbol, exc)
        return sorted(closes.items())

    @staticmethod
    def _fetch_fx_cross_rate(*, from_currency: str, to_currency: str) -> Optional[float]:
        """Latest from->to rate implied by the two USD legs (TWDCNY ~ USDCNY / USDTWD); None if unavailable."""
        # A USD leg is just the same USDxxx=X ticker the newest bar came from, so it cannot cross-check it.
        if yf is None or from_currency == to_currency or "USD" in (from_currency, to_currency):
            return None

        def leg(currency: str) -> Optional[float]:
            if currency == "USD":
                return 1.0
            history = _fx_call(_ticker_history, f"USD{currency}=X", period="5d", interval="1d", auto_adjust=False)
            close = history["Close"].dropna() if history is not None and not history.empty else None
            return float(close.iloc[-1]) if close is not None and len(close) and float(close.iloc[-1]) > 0 else None

        try:
            src, dst = leg(from_currency), leg(to_currency)
        except Exception as exc:
            logger.warning("交叉匯率取得失敗 %s/%s：%s", from_currency, to_currency, exc)
            return None
        return dst / src if src and dst else None

    @classmethod
    def _fetch_fx_cross_closes(
        cls, *, from_currency: str, to_currency: str, as_of_date: date
    ) -> Dict[date, float]:
        """Per London day from->to rate implied by the two USD legs, same window and close rule as the pair.

        Empty when either side is USD (the leg is the pair's own ticker, so it cannot check itself), when
        yfinance is missing, or on any failure; days missing from either leg are simply absent.
        """
        if yf is None or from_currency == to_currency or "USD" in (from_currency, to_currency):
            return {}
        try:
            src = dict(cls._fetch_fx_closes_from_yfinance(from_currency="USD", to_currency=from_currency, as_of_date=as_of_date))
            dst = dict(cls._fetch_fx_closes_from_yfinance(from_currency="USD", to_currency=to_currency, as_of_date=as_of_date))
        except Exception as exc:
            logger.warning("交叉匯率序列取得失敗 %s/%s：%s", from_currency, to_currency, exc)
            return {}
        return {d: dst[d] / src[d] for d in src.keys() & dst.keys() if src[d] > 0 and dst[d] > 0}

    def _last_real_stored_rate(
        self, *, from_currency: str, to_currency: str, before: date
    ) -> Optional[float]:
        """Latest stored non-stale rate dated before `before`, however long the stale streak is."""
        row = self.repo.get_latest_fx_rate(
            from_currency=from_currency,
            to_currency=to_currency,
            as_of=before - timedelta(days=1),
            real_only=True,
        )
        return float(row.rate) if row is not None else None

    def _filter_fx_outliers(
        self,
        *,
        from_currency: str,
        to_currency: str,
        as_of_date: date,
        closes: List[Tuple[date, float]],
        cross_closes: Optional[Dict[date, float]] = None,
        rejected_references: Optional[Dict[date, Tuple[float, ...]]] = None,
    ) -> List[Tuple[date, float]]:
        """Drop junk bars (TWDCNY=X once printed 0.1962 against ~0.2047 from the USD cross).

        Only an isolated spike is rejected: a bar that deviates from both neighbours by more than
        FX_OUTLIER_MAX_DEVIATION. A real jump has the next bar on the new level and passes. The newest bar has
        no next neighbour, so it is compared with the cross rate (or, without one, the previous real value,
        walking back past stale carries); no reference at all means accept.

        For a pair with no USD side, every bar whose London day has a cross rate (`cross_closes`, fetched when
        None) is checked against it instead: junk can repeat on consecutive bars, so two bad neighbours would
        vouch for each other under the neighbour rule. Days without a cross rate fall back to the rules above.

        rejected_references 若有提供，帶回拒收時的全部參考值（中間K棒為前後兩個鄰居），讓快取清理沿用同一判定而不再抓價。
        """
        if cross_closes is None:
            cross_closes = self._fetch_fx_cross_closes(
                from_currency=from_currency, to_currency=to_currency, as_of_date=as_of_date
            )

        kept: List[Tuple[date, float]] = []
        for i, (bar_date, value) in enumerate(closes):
            references: Tuple[float, ...] = ()
            if bar_date in cross_closes:
                reference = cross_closes[bar_date]
                bad = _fx_rates_deviate(value, reference)
                references = (reference,)
            elif i + 1 < len(closes):
                prev = kept[-1][1] if kept else self._last_real_stored_rate(
                    from_currency=from_currency, to_currency=to_currency, before=bar_date
                )
                # Prefer the next bar's cross rate: its raw value may itself be rejected below.
                nxt_date, nxt_raw = closes[i + 1]
                nxt = cross_closes.get(nxt_date, nxt_raw)
                bad = prev is not None and _fx_rates_deviate(value, prev) and _fx_rates_deviate(value, nxt)
                reference = prev
                # 拒收條件是兩個鄰居都偏離，任一鄰居都是可接受值的依據。
                references = (prev, nxt) if prev is not None else ()
            else:
                # The cross rate is today's value; it is meaningless for a historical as_of.
                reference = (
                    self._fetch_fx_cross_rate(from_currency=from_currency, to_currency=to_currency)
                    if as_of_date >= self._london_today()
                    else None
                )
                if reference is None:
                    reference = kept[-1][1] if kept else self._last_real_stored_rate(
                        from_currency=from_currency, to_currency=to_currency, before=bar_date
                    )
                bad = reference is not None and _fx_rates_deviate(value, reference)
                references = (reference,) if reference is not None else ()
            if bad:
                if rejected_references is not None:
                    rejected_references[bar_date] = references
                logger.warning(
                    "匯率離群值拒收 %s/%s %s：%s（參考值 %s，偏離超過 %.0f%%）",
                    from_currency, to_currency, bar_date.isoformat(), value, reference,
                    FX_OUTLIER_MAX_DEVIATION * 100,
                )
                continue
            kept.append((bar_date, value))
        return kept

    @staticmethod
    def _london_today() -> date:
        """Today's date in London; yfinance FX daily bars are dated on that calendar."""
        return datetime.now(ZoneInfo("Europe/London")).date()

    def _backfill_fx_history(
        self,
        *,
        from_currency: str,
        to_currency: str,
        as_of_date: date,
        closes: List[Tuple[date, float]],
        repairs: Optional[Dict[date, float]] = None,
    ) -> None:
        """Save finished daily bars under their own dates.

        Rows from manual entries are never touched; stale carries and automated
        yfinance rows (possibly intraday values) are replaced by the finished close.

        `repairs` maps days whose bar the cross check rejected to the cross rate. An earlier run (before the
        check existed) may have stored the junk bar as a non-stale row; keeping it would feed bad rates to
        snapshots, and a stale carry would just propagate it. The cross rate comes from the two real USD legs,
        so a stored automated row (or a missing one) that deviates from it is rewritten as 'yfinance_cross'.
        """
        try:
            last_finished = min(as_of_date, self._london_today())
            for bar_date, cross in (repairs or {}).items():
                if bar_date >= last_finished:
                    continue
                existing = self.repo.get_latest_fx_rate(
                    from_currency=from_currency, to_currency=to_currency, as_of=bar_date
                )
                if existing is not None and existing.rate_date == bar_date:
                    manual = not existing.is_stale and existing.source not in FX_AUTO_SOURCES
                    # A stale carry is never a real close for this day, however close it is to the cross rate
                    if manual or (
                        not existing.is_stale and not _fx_rates_deviate(float(existing.rate), cross)
                    ):
                        continue
                self.repo.save_fx_rate(
                    from_currency=from_currency,
                    to_currency=to_currency,
                    rate_date=bar_date,
                    rate=cross,
                    source="yfinance_cross",
                    is_stale=False,
                )
            for bar_date, value in closes:
                # A bar dated today (London) or later may still be open.
                if bar_date >= last_finished:
                    continue
                existing = self.repo.get_latest_fx_rate(
                    from_currency=from_currency, to_currency=to_currency, as_of=bar_date
                )
                if (
                    existing is not None
                    and existing.rate_date == bar_date
                    and not existing.is_stale
                    and existing.source not in FX_AUTO_SOURCES
                ):
                    continue
                self.repo.save_fx_rate(
                    from_currency=from_currency,
                    to_currency=to_currency,
                    rate_date=bar_date,
                    rate=value,
                    source="yfinance_backfill",
                    is_stale=False,
                )
        except Exception as exc:
            logger.warning("FX history backfill failed for %s/%s: %s", from_currency, to_currency, exc)

    def _require_active_account(self, account_id: int) -> Any:
        account = self.repo.get_account(account_id, include_inactive=False)
        if account is None:
            raise ValueError(f"Active account not found: {account_id}")
        return account

    def _require_active_account_in_session(self, *, session: Any, account_id: int) -> Any:
        account = self.repo.get_account_in_session(
            session=session,
            account_id=account_id,
            include_inactive=False,
        )
        if account is None:
            raise ValueError(f"Active account not found: {account_id}")
        return account

    def _has_trade_uid(self, *, account_id: int, trade_uid: str, session: Optional[Any] = None) -> bool:
        if session is None:
            return self.repo.has_trade_uid(account_id, trade_uid)
        return self.repo.has_trade_uid_in_session(session=session, account_id=account_id, trade_uid=trade_uid)

    def _has_trade_dedup_hash(
        self,
        *,
        account_id: int,
        dedup_hash: str,
        session: Optional[Any] = None,
    ) -> bool:
        if session is None:
            return self.repo.has_trade_dedup_hash(account_id, dedup_hash)
        return self.repo.has_trade_dedup_hash_in_session(
            session=session,
            account_id=account_id,
            dedup_hash=dedup_hash,
        )

    @staticmethod
    def _account_to_dict(row: Any) -> Dict[str, Any]:
        return {
            "id": row.id,
            "owner_id": row.owner_id,
            "name": row.name,
            "broker": row.broker,
            "market": row.market,
            "base_currency": row.base_currency,
            "is_active": bool(row.is_active),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    @staticmethod
    def _trade_row_to_dict(row: Any) -> Dict[str, Any]:
        return {
            "id": int(row.id),
            "account_id": int(row.account_id),
            "trade_uid": row.trade_uid,
            "symbol": row.symbol,
            "market": row.market,
            "currency": row.currency,
            "trade_date": row.trade_date.isoformat() if row.trade_date else "",
            "side": row.side,
            "quantity": float(row.quantity),
            "price": float(row.price),
            "fee": float(row.fee),
            "tax": float(row.tax),
            "note": row.note,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    @staticmethod
    def _cash_ledger_row_to_dict(row: Any) -> Dict[str, Any]:
        return {
            "id": int(row.id),
            "account_id": int(row.account_id),
            "event_date": row.event_date.isoformat() if row.event_date else "",
            "direction": row.direction,
            "amount": float(row.amount),
            "currency": row.currency,
            "note": row.note,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    @staticmethod
    def _corporate_action_row_to_dict(row: Any) -> Dict[str, Any]:
        return {
            "id": int(row.id),
            "account_id": int(row.account_id),
            "symbol": row.symbol,
            "market": row.market,
            "currency": row.currency,
            "effective_date": row.effective_date.isoformat() if row.effective_date else "",
            "action_type": row.action_type,
            "cash_dividend_per_share": (
                float(row.cash_dividend_per_share) if row.cash_dividend_per_share is not None else None
            ),
            "split_ratio": float(row.split_ratio) if row.split_ratio is not None else None,
            "note": row.note,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    @staticmethod
    def _validate_paging(*, page: int, page_size: int) -> Tuple[int, int]:
        if page < 1:
            raise ValueError("page must be >= 1")
        if page_size < 1 or page_size > 100:
            raise ValueError("page_size must be in [1, 100]")
        return page, page_size

    @staticmethod
    def _normalize_market(value: str) -> str:
        market = (value or "").strip().lower()
        if market not in VALID_MARKETS:
            raise ValueError("market must be one of: cn, hk, us, jp, kr, tw")
        return market

    @staticmethod
    def _normalize_currency(value: str) -> str:
        currency = (value or "").strip().upper()
        if not currency:
            raise ValueError("currency is required")
        return currency

    @staticmethod
    def _normalize_cost_method(value: str) -> str:
        method = (value or "").strip().lower()
        if method not in VALID_COST_METHODS:
            raise ValueError("cost_method must be fifo or avg")
        return method

    @staticmethod
    def _default_currency_for_market(market: str) -> str:
        if market == "hk":
            return "HKD"
        if market == "us":
            return "USD"
        if market == "tw":
            return "TWD"
        return "CNY"
