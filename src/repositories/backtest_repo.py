# -*- coding: utf-8 -*-
"""Backtest repository.

Provides database access helpers for backtest tables.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple

from sqlalchemy import String, and_, delete, desc, func, or_, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement

from src.core.backtest_engine import OVERALL_SENTINEL_CODE
from src.market_phase_summary import extract_market_phase_summary
from src.repositories.stock_repo import StockRepository
from src.services.backtest_price_basis import is_usable_entry_window, resolve_backtest_entry_window
from src.services.stock_code_utils import resolve_daily_stock_identity
from src.services.stock_daily_start_resolver import resolve_stock_daily_start
from src.services.stock_daily_window_resolver import resolve_stock_daily_window

from src.storage import BacktestResult, BacktestSummary, DatabaseManager, AnalysisHistory

logger = logging.getLogger(__name__)


class _snapshot_market(FunctionElement):
    """``context_snapshot`` 内 ``market_phase_summary.market``；非法 JSON 视为缺值。

    fork: 应用库在 Postgres（dsa schema），SQLite 的 json_valid／json_extract 在那里不存在，
    按方言编译成等价 SQL。
    """

    type = String()
    inherit_cache = True
    name = "snapshot_market"


@compiles(_snapshot_market)
def _compile_snapshot_market(element, compiler, **kw):
    arg = compiler.process(element.clauses, **kw)
    return (
        f"json_extract(CASE WHEN json_valid({arg}) THEN {arg} ELSE '{{}}' END, "
        f"'$.market_phase_summary.market')"
    )


@compiles(_snapshot_market, "postgresql")
def _compile_snapshot_market_pg(element, compiler, **kw):
    arg = compiler.process(element.clauses, **kw)
    return (
        f"(CASE WHEN pg_input_is_valid({arg}, 'json') "
        f"THEN ({arg})::json #>> '{{market_phase_summary,market}}' END)"
    )

MARKET_REVIEW_REPORT_TYPE = "market_review"
BacktestResultContextRow = Tuple[
    BacktestResult,
    Optional[str],
    Optional[str],
    Optional[datetime],
    Optional[str],
    Optional[str],
    Optional[str],
    Optional[int],
]


class BacktestRepository:
    """DB access layer for backtesting."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    def get_candidates(
        self,
        *,
        code: Optional[str],
        min_age_days: int,
        limit: int,
        offset: int = 0,
        eval_window_days: int,
        engine_version: str,
        force: bool,
    ) -> List[AnalysisHistory]:
        """Return AnalysisHistory rows eligible for backtest."""
        if limit <= 0:
            return []
        cutoff_dt = datetime.now() - timedelta(days=min_age_days)

        with self.db.get_session() as session:
            conditions = [AnalysisHistory.created_at <= cutoff_dt]
            if code:
                conditions.extend(self._build_code_conditions(AnalysisHistory.code, code))
            conditions.append(
                or_(
                    AnalysisHistory.report_type.is_(None),
                    AnalysisHistory.report_type != MARKET_REVIEW_REPORT_TYPE,
                )
            )

            query = select(AnalysisHistory).where(and_(*conditions))

            if force:
                return list(session.execute(
                    query.order_by(desc(AnalysisHistory.created_at), desc(AnalysisHistory.id))
                    .offset(offset).limit(limit)
                ).scalars().all())

            result_key = and_(
                BacktestResult.analysis_history_id == AnalysisHistory.id,
                BacktestResult.eval_window_days == eval_window_days,
                BacktestResult.engine_version == engine_version,
            )
            query = (
                query.add_columns(BacktestResult.eval_status)
                .outerjoin(BacktestResult, result_key)
                .where(or_(BacktestResult.id.is_(None), BacktestResult.eval_status == "insufficient_data"))
                .order_by(desc(AnalysisHistory.created_at), desc(AnalysisHistory.id))
            )
            stock_repo = StockRepository(self.db)
            eligible = []
            skipped = 0
            # 先排除無法重試的本地窗口再套分頁，避免永久缺資料佔滿最新 200 筆額度。
            for analysis, status in session.execute(query).yield_per(max(limit, 200)):
                if status == "insufficient_data" and not self._retry_window_ready(
                    analysis, stock_repo=stock_repo, eval_window_days=eval_window_days,
                ):
                    continue
                if skipped < offset:
                    skipped += 1
                    continue
                eligible.append(analysis)
                if len(eligible) >= limit:
                    break
            return eligible

    def _retry_window_ready(self, analysis, *, stock_repo: StockRepository, eval_window_days: int) -> bool:
        """只重試已由本地匯入修復的資料；強制執行仍可明確要求重新連網回補。"""
        analysis_date = self.parse_analysis_date_from_snapshot(analysis.context_snapshot)
        if analysis_date is None and analysis.created_at is not None:
            analysis_date = analysis.created_at.date()
        start = resolve_stock_daily_start(
            stock_code=analysis.code, context_snapshot=analysis.context_snapshot, analysis_date=analysis_date,
        )
        if start.identity is None or start.backtest_start_date is None:
            return False
        window = resolve_stock_daily_window(
            stock_repo=stock_repo, code_candidates=start.identity.code_candidates,
            expected_start_date=start.backtest_start_date, eval_window_days=eval_window_days,
        )
        if window is None:
            return False
        summary = extract_market_phase_summary(analysis.context_snapshot) or {}
        phase = str(summary.get("phase") or "").strip().lower() or None
        _, bars = resolve_backtest_entry_window(
            stock_repo=stock_repo, daily_window=window, analysis_date=analysis_date,
            phase=phase, eval_window_days=eval_window_days, context_snapshot=analysis.context_snapshot,
        )
        return is_usable_entry_window(bars, eval_window_days)

    def align_existing_result_dates(
        self,
        *,
        code: Optional[str],
        min_age_days: int,
        eval_window_days: int,
        engine_version: str,
        analysis_date_from: Optional[date],
        analysis_date_to: Optional[date],
    ) -> int:
        """Align legacy result dates to their linked analysis snapshot date.

        Older backtest rows may have stored the trading/start daily date instead
        of the historical analysis snapshot date. When a date-filtered run skips
        already-existing rows, those legacy rows would remain invisible to the
        same date-filtered result query. Updating the stored result date keeps
        rerun and query semantics aligned without inserting duplicate rows.
        """
        cutoff_dt = datetime.now() - timedelta(days=min_age_days)

        with self.db.get_session() as session:
            conditions = [
                AnalysisHistory.created_at <= cutoff_dt,
                BacktestResult.eval_window_days == eval_window_days,
                BacktestResult.engine_version == engine_version,
                or_(
                    AnalysisHistory.report_type.is_(None),
                    AnalysisHistory.report_type != MARKET_REVIEW_REPORT_TYPE,
                ),
            ]
            if code:
                conditions.extend(self._build_code_conditions(AnalysisHistory.code, code))

            rows = session.execute(
                select(BacktestResult, AnalysisHistory)
                .join(AnalysisHistory, AnalysisHistory.id == BacktestResult.analysis_history_id)
                .where(and_(*conditions))
            ).all()

            updated = 0
            for result, analysis in rows:
                analysis_date = self.parse_analysis_date_from_snapshot(analysis.context_snapshot)
                if analysis_date is None and analysis.created_at is not None:
                    analysis_date = analysis.created_at.date()
                if analysis_date is None:
                    continue
                if analysis_date_from is not None and analysis_date < analysis_date_from:
                    continue
                if analysis_date_to is not None and analysis_date > analysis_date_to:
                    continue
                if result.analysis_date != analysis_date:
                    result.analysis_date = analysis_date
                    updated += 1

            if updated:
                session.commit()
            return updated

    def save_result(self, result: BacktestResult) -> None:
        with self.db.get_session() as session:
            session.add(result)
            session.commit()

    def save_results_batch(self, results: List[BacktestResult], *, replace_existing: bool = False) -> int:
        if not results:
            return 0

        with self.db.get_session() as session:
            try:
                # 本地窗口恢復可用後，重試結果取代 insufficient_data；其他狀態僅由 force 取代。
                analysis_ids = sorted({r.analysis_history_id for r in results if r.analysis_history_id is not None})
                key_pairs = sorted({(r.eval_window_days, r.engine_version) for r in results})

                if analysis_ids and key_pairs:
                    for window_days, engine_version in key_pairs:
                        conditions = [
                            BacktestResult.analysis_history_id.in_(analysis_ids),
                            BacktestResult.eval_window_days == window_days,
                            BacktestResult.engine_version == engine_version,
                        ]
                        if not replace_existing:
                            conditions.append(BacktestResult.eval_status == "insufficient_data")
                        session.execute(delete(BacktestResult).where(and_(*conditions)))

                session.add_all(results)
                session.commit()
                return len(results)
            except Exception as exc:
                session.rollback()
                logger.error(f"批量保存回测结果失败: {exc}")
                raise

    def get_results_paginated(
        self,
        *,
        code: Optional[str],
        eval_window_days: Optional[int] = None,
        engine_version: Optional[str] = None,
        analysis_date_from: Optional[date] = None,
        analysis_date_to: Optional[date] = None,
        days: Optional[int],
        offset: int,
        limit: int,
        code_candidates: Optional[Tuple[str, ...]] = None,
    ) -> Tuple[List[BacktestResultContextRow], int]:
        with self.db.get_session() as session:
            conditions = self._build_result_conditions(
                code=code,
                eval_window_days=eval_window_days,
                engine_version=engine_version,
                analysis_date_from=analysis_date_from,
                analysis_date_to=analysis_date_to,
                days=days,
                code_candidates=code_candidates,
            )

            where_clause = and_(*conditions) if conditions else True

            total = session.execute(
                select(func.count(BacktestResult.id))
                .select_from(BacktestResult)
                .join(AnalysisHistory, AnalysisHistory.id == BacktestResult.analysis_history_id)
                .where(where_clause)
            ).scalar() or 0
            rows = session.execute(
                select(
                    BacktestResult,
                    AnalysisHistory.name,
                    AnalysisHistory.trend_prediction,
                    AnalysisHistory.created_at,
                    AnalysisHistory.context_snapshot,
                    AnalysisHistory.raw_result,
                    AnalysisHistory.report_type,
                    AnalysisHistory.sentiment_score,
                )
                .join(AnalysisHistory, AnalysisHistory.id == BacktestResult.analysis_history_id)
                .where(where_clause)
                .order_by(desc(BacktestResult.analysis_date), desc(BacktestResult.evaluated_at))
                .offset(offset)
                .limit(limit)
            ).all()
            return list(rows), int(total)

    def get_results_with_context_batch(
        self,
        *,
        code: Optional[str],
        eval_window_days: Optional[int] = None,
        engine_version: Optional[str] = None,
        analysis_date_from: Optional[date] = None,
        analysis_date_to: Optional[date] = None,
        days: Optional[int],
        offset: int,
        limit: int,
    ) -> List[BacktestResultContextRow]:
        """Return result rows plus AnalysisHistory.context_snapshot for dynamic filtering."""
        with self.db.get_session() as session:
            conditions = self._build_result_conditions(
                code=code,
                eval_window_days=eval_window_days,
                engine_version=engine_version,
                analysis_date_from=analysis_date_from,
                analysis_date_to=analysis_date_to,
                days=days,
            )
            where_clause = and_(*conditions) if conditions else True
            rows = session.execute(
                select(
                    BacktestResult,
                    AnalysisHistory.name,
                    AnalysisHistory.trend_prediction,
                    AnalysisHistory.created_at,
                    AnalysisHistory.context_snapshot,
                    AnalysisHistory.raw_result,
                    AnalysisHistory.report_type,
                    AnalysisHistory.sentiment_score,
                )
                .join(AnalysisHistory, AnalysisHistory.id == BacktestResult.analysis_history_id)
                .where(where_clause)
                .order_by(desc(BacktestResult.analysis_date), desc(BacktestResult.evaluated_at))
                .offset(offset)
                .limit(limit)
            ).all()
            return list(rows)

    def list_results_with_context(
        self,
        *,
        code: Optional[str],
        eval_window_days: Optional[int] = None,
        engine_version: Optional[str] = None,
        analysis_date_from: Optional[date] = None,
        analysis_date_to: Optional[date] = None,
        days: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> List[Tuple[BacktestResult, Optional[str]]]:
        with self.db.get_session() as session:
            conditions = self._build_result_conditions(
                code=code,
                eval_window_days=eval_window_days,
                engine_version=engine_version,
                analysis_date_from=analysis_date_from,
                analysis_date_to=analysis_date_to,
                days=days,
            )
            where_clause = and_(*conditions) if conditions else True
            query = (
                select(BacktestResult, AnalysisHistory.context_snapshot)
                .join(AnalysisHistory, AnalysisHistory.id == BacktestResult.analysis_history_id)
                .where(where_clause)
                .order_by(desc(BacktestResult.analysis_date), desc(BacktestResult.evaluated_at))
            )
            if limit is not None:
                query = query.limit(limit)
            return list(session.execute(query).all())

    def count_results(
        self,
        *,
        code: Optional[str],
        eval_window_days: Optional[int] = None,
        engine_version: Optional[str] = None,
        analysis_date_from: Optional[date] = None,
        analysis_date_to: Optional[date] = None,
        days: Optional[int] = None,
    ) -> int:
        """Return the number of matching BacktestResult rows without loading them."""
        with self.db.get_session() as session:
            conditions = self._build_result_conditions(
                code=code,
                eval_window_days=eval_window_days,
                engine_version=engine_version,
                analysis_date_from=analysis_date_from,
                analysis_date_to=analysis_date_to,
                days=days,
            )
            where_clause = and_(*conditions) if conditions else True
            count = session.execute(
                select(func.count(BacktestResult.id))
                .select_from(BacktestResult)
                .where(where_clause)
            ).scalar() or 0
            return int(count)

    def list_results(
        self,
        *,
        code: Optional[str],
        eval_window_days: Optional[int] = None,
        engine_version: Optional[str] = None,
        analysis_date_from: Optional[date] = None,
        analysis_date_to: Optional[date] = None,
        days: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> List[BacktestResult]:
        with self.db.get_session() as session:
            conditions = self._build_result_conditions(
                code=code,
                eval_window_days=eval_window_days,
                engine_version=engine_version,
                analysis_date_from=analysis_date_from,
                analysis_date_to=analysis_date_to,
                days=days,
            )
            where_clause = and_(*conditions) if conditions else True
            query = (
                select(BacktestResult)
                .where(where_clause)
                .order_by(desc(BacktestResult.analysis_date), desc(BacktestResult.evaluated_at))
            )
            if limit is not None:
                query = query.limit(limit)
            rows = session.execute(query).scalars().all()
            return list(rows)

    def upsert_summary(self, summary: BacktestSummary) -> None:
        """Insert or replace summary row by unique key."""
        with self.db.get_session() as session:
            existing = session.execute(
                select(BacktestSummary)
                .where(
                    and_(
                        BacktestSummary.scope == summary.scope,
                        BacktestSummary.code == summary.code,
                        BacktestSummary.eval_window_days == summary.eval_window_days,
                        BacktestSummary.engine_version == summary.engine_version,
                    )
                )
                .limit(1)
            ).scalar_one_or_none()

            if existing:
                for attr in (
                    "computed_at",
                    "total_evaluations",
                    "completed_count",
                    "insufficient_count",
                    "long_count",
                    "cash_count",
                    "win_count",
                    "loss_count",
                    "neutral_count",
                    "direction_accuracy_pct",
                    "win_rate_pct",
                    "neutral_rate_pct",
                    "avg_stock_return_pct",
                    "avg_simulated_return_pct",
                    "stop_loss_trigger_rate",
                    "take_profit_trigger_rate",
                    "ambiguous_rate",
                    "avg_days_to_first_hit",
                    "advice_breakdown_json",
                    "diagnostics_json",
                ):
                    setattr(existing, attr, getattr(summary, attr))
                session.commit()
                return

            session.add(summary)
            session.commit()

    def get_summary(
        self,
        *,
        scope: str,
        code: Optional[str],
        eval_window_days: Optional[int] = None,
        engine_version: str,
        code_candidates: Optional[Tuple[str, ...]] = None,
    ) -> Optional[BacktestSummary]:
        with self.db.get_session() as session:
            conditions = [
                BacktestSummary.scope == scope,
                BacktestSummary.engine_version == engine_version,
            ]
            if code or code_candidates is not None:
                conditions.extend(self._build_code_conditions(BacktestSummary.code, code, code_candidates))
            numeric = tuple(value for value in code_candidates or () if value.isdigit())
            if numeric:
                # A numeric rollup has no identity column of its own. Its
                # contributing results must witness this identity, without a
                # conflicting numeric source in the same rollup bucket.
                same_bucket = (
                    BacktestResult.eval_window_days == BacktestSummary.eval_window_days,
                    BacktestResult.engine_version == BacktestSummary.engine_version,
                )
                owned = self._strict_result_code_condition(code_candidates)
                witness = select(BacktestResult.id).where(*same_bucket, owned).correlate(BacktestSummary).exists()
                conflict = select(BacktestResult.id).where(
                    *same_bucket, BacktestResult.code.in_(numeric), ~owned,
                ).correlate(BacktestSummary).exists()
                conditions.append(or_(BacktestSummary.code.not_in(numeric), and_(witness, ~conflict)))
            if eval_window_days is not None:
                conditions.append(BacktestSummary.eval_window_days == eval_window_days)

            row = session.execute(
                select(BacktestSummary)
                .where(and_(*conditions))
                .order_by(desc(BacktestSummary.computed_at))
                .limit(1)
            ).scalar_one_or_none()
            return row

    @staticmethod
    def parse_analysis_date_from_snapshot(context_snapshot: Optional[str]) -> Optional[date]:
        if not context_snapshot:
            return None

        try:
            payload = json.loads(context_snapshot)
        except Exception:
            return None

        if not isinstance(payload, dict):
            return None

        enhanced = payload.get("enhanced_context")
        if not isinstance(enhanced, dict):
            return None

        date_str = enhanced.get("date")
        if not date_str:
            return None

        try:
            return datetime.strptime(str(date_str)[:10], "%Y-%m-%d").date()
        except Exception:
            return None

    def get_distinct_eval_windows(
        self,
        *,
        code: Optional[str],
        engine_version: Optional[str] = None,
        analysis_date_from: Optional[date] = None,
        analysis_date_to: Optional[date] = None,
    ) -> List[int]:
        """Return sorted distinct eval_window_days for matching results."""
        with self.db.get_session() as session:
            conditions = self._build_result_conditions(
                code=code,
                eval_window_days=None,
                engine_version=engine_version,
                analysis_date_from=analysis_date_from,
                analysis_date_to=analysis_date_to,
                days=None,
            )
            where_clause = and_(*conditions) if conditions else True
            rows = session.execute(
                select(BacktestResult.eval_window_days)
                .where(where_clause)
                .distinct()
                .order_by(BacktestResult.eval_window_days)
            ).scalars().all()
            return [int(w) for w in rows if w is not None]

    @staticmethod
    def _build_result_conditions(
        *,
        code: Optional[str],
        eval_window_days: Optional[int],
        engine_version: Optional[str],
        analysis_date_from: Optional[date],
        analysis_date_to: Optional[date],
        days: Optional[int],
        code_candidates: Optional[Tuple[str, ...]] = None,
    ) -> List[object]:
        conditions = []
        if code_candidates is not None:
            conditions.append(BacktestRepository._strict_result_code_condition(code_candidates))
        elif code:
            conditions.extend(BacktestRepository._build_code_conditions(BacktestResult.code, code))
        if eval_window_days is not None:
            conditions.append(BacktestResult.eval_window_days == eval_window_days)
        if engine_version:
            conditions.append(BacktestResult.engine_version == engine_version)
        if analysis_date_from is not None:
            conditions.append(BacktestResult.analysis_date >= analysis_date_from)
        if analysis_date_to is not None:
            conditions.append(BacktestResult.analysis_date <= analysis_date_to)
        if days:
            cutoff = datetime.now() - timedelta(days=int(days))
            conditions.append(BacktestResult.evaluated_at >= cutoff)
        return conditions

    @staticmethod
    def _strict_result_code_condition(code_candidates: Tuple[str, ...]):
        """Use the fixed storage namespace and existing source FK, not an index.

        Qualified keys retain their existing identity. Numeric CN writer keys
        additionally require a same-object source code and no contrary persisted
        market. Missing market uses the writer's bare-CN storage convention.
        """
        numeric = tuple(value for value in code_candidates if value.isdigit())
        if not numeric:
            return BacktestResult.code.in_(code_candidates)
        qualified = tuple(value for value in code_candidates if not value.isdigit())
        market = _snapshot_market(AnalysisHistory.context_snapshot)
        source = select(AnalysisHistory.id).where(
            AnalysisHistory.id == BacktestResult.analysis_history_id,
            AnalysisHistory.code.in_(code_candidates),
            or_(market.is_(None), func.lower(market) == "cn"),
        ).correlate(BacktestResult).exists()
        return or_(BacktestResult.code.in_(qualified), and_(BacktestResult.code.in_(numeric), source))

    @staticmethod
    def _build_code_conditions(column, code: Optional[str], code_candidates: Optional[Tuple[str, ...]] = None) -> List[object]:
        if code_candidates is not None:
            # An empty explicit constraint means no matches, not legacy/all rows.
            return [column.in_(code_candidates)]
        if not code:
            return []

        raw_code = str(code).strip()
        if raw_code.lower() == OVERALL_SENTINEL_CODE.lower():
            raw_code = OVERALL_SENTINEL_CODE
        else:
            raw_code = raw_code.upper()

        if raw_code == OVERALL_SENTINEL_CODE:
            candidates = [OVERALL_SENTINEL_CODE]
        else:
            identity = resolve_daily_stock_identity(raw_code)
            candidates = list(identity.code_candidates) if identity is not None else []
        if not candidates:
            return [column.in_([])]

        if len(candidates) == 1:
            return [column == candidates[0]]

        unique = list(dict.fromkeys(candidates))
        return [or_(*[column == candidate for candidate in unique])]
