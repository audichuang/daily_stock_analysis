# -*- coding: utf-8 -*-
"""Backtesting evaluation engine (pure logic).

This module is intentionally DB-agnostic: it operates on plain values or
objects that look like daily OHLC bars.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import logging
import math
import re
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Protocol, Sequence

from src.utils.zh_fold import TRAD_TO_SIMP

if TYPE_CHECKING:  # pragma: no cover
    from src.services.backtest_price_basis import EntryBasis

logger = logging.getLogger(__name__)

OVERALL_SENTINEL_CODE = "__overall__"

# H2：T+1 開盤進場＋台股還原報酬。`BACKTEST_ENGINE_VERSION`（.env）只是標籤前綴，
# 實際寫進 DB 的版本一律帶這個 tag，舊口徑（收盤進場、未還原）的列以舊版本字串保留、不混算。
BACKTEST_METHOD_TAG = "t1o-adj"
_ENGINE_VERSION_MAX_LEN = 16  # BacktestResult／BacktestSummary.engine_version 是 String(16)


def resolve_long_exit(
    *,
    bar_open: Optional[float],
    stop_loss: Optional[float],
    take_profit: Optional[float],
    stop_hit: bool,
    tp_hit: bool,
) -> Optional[tuple[float, str]]:
    """共用做多成交順序：開盤觸價優先，盤中雙觸價才保守算停損。"""
    if bar_open is not None:
        if stop_loss is not None and bar_open <= stop_loss:
            return bar_open, "stop_loss"
        if take_profit is not None and bar_open >= take_profit:
            return bar_open, "take_profit"
    if stop_hit and stop_loss is not None:
        return stop_loss, "ambiguous_stop_loss" if tp_hit else "stop_loss"
    if tp_hit and take_profit is not None:
        return take_profit, "take_profit"
    return None


def effective_backtest_engine_version(label: Optional[str]) -> str:
    """`v1` → `v1-t1o-adj`；已帶 tag 的冪等；超過 16 字元時截短標籤並告警。"""
    text = str(label or "").strip() or "v1"
    suffix = f"-{BACKTEST_METHOD_TAG}"
    if text.endswith(suffix):
        base = text[: -len(suffix)]
    else:
        base = text
    max_base = _ENGINE_VERSION_MAX_LEN - len(suffix)
    if len(base) > max_base:
        logger.warning(
            "BACKTEST_ENGINE_VERSION=%r 太長，截成 %r 後加上 %r",
            base, base[:max_base], suffix,
        )
        base = base[:max_base]
    return f"{base}{suffix}"


class DailyBarLike(Protocol):
    """Protocol for objects representing a daily OHLC bar."""

    date: date
    high: Optional[float]
    low: Optional[float]
    close: Optional[float]
    # `open` 也會被讀（T+1 開盤進場、跳空成交），但以 getattr 讀，舊的測試假物件不必有。


@dataclass(frozen=True)
class _AdjustedBar:
    """進場基準下的 K 棒（只給停損停利判定用）。"""

    date: date
    open: Optional[float]
    high: Optional[float]
    low: Optional[float]


class BacktestResultLike(Protocol):
    """Protocol for objects that behave like a stored BacktestResult."""

    eval_status: str
    position_recommendation: Optional[str]
    outcome: Optional[str]
    direction_correct: Optional[bool]
    stock_return_pct: Optional[float]
    simulated_return_pct: Optional[float]
    hit_stop_loss: Optional[bool]
    hit_take_profit: Optional[bool]
    first_hit: Optional[str]
    first_hit_trading_days: Optional[int]
    operation_advice: Optional[str]


@dataclass(frozen=True)
class EvaluationConfig:
    eval_window_days: int
    neutral_band_pct: float = 2.0
    engine_version: str = "v1"


class BacktestEngine:
    """Long-only daily-bar backtesting engine."""

    # Operation advice keywords (Chinese + English)
    _BULLISH_KEYWORDS = (
        "买入",
        "买进",
        "加仓",
        "加码",
        "强烈买入",
        "增持",
        "建仓",
        "strong buy",
        "buy",
        "add",
    )
    _BEARISH_KEYWORDS = (
        "卖出",
        "减仓",
        "减码",
        "强烈卖出",
        "清仓",
        "strong sell",
        "sell",
        "reduce",
    )
    _HOLD_KEYWORDS = (
        "持有",
        "震荡观望",
        "洗盘观察",
        "持有观察",
        "hold",
        "range-bound watch",
        "shakeout watch",
        "hold and watch",
    )
    _WAIT_KEYWORDS = (
        "观望",
        "等待",
        "wait",
    )

    # Traditional -> simplified for every character the keyword tables use, so
    # TW advice such as "減碼" / "賣出" matches the simplified keywords.
    # 表本身在 src/utils/zh_fold.py，與 DecisionAction 正規化共用同一份。
    _TRAD_TO_SIMP = TRAD_TO_SIMP

    # Negation prefixes (trailing spaces stripped for suffix-matching against prefix text).
    # English patterns include trailing space in their canonical form; rstrip is
    # applied during matching so "do not" matches prefix "do not " or "do not".
    _NEGATION_PATTERNS = (
        "not", "don't", "do not", "no", "never", "avoid",  # English
        "不要", "不", "别", "勿", "没有",  # Chinese
    )

    _NEGATION_CONNECTOR_WORDS = (
        "建议",
        "应",
        "应当",
        "宜",
        "先",
        "再",
        "暂",
        "不必",
        "必须",
        "无需",
    )

    @classmethod
    def infer_direction_expected(cls, operation_advice: Optional[str]) -> str:
        """Infer expected direction: up/down/not_down/flat."""
        text = cls._normalize_text(operation_advice)
        if cls._matches_intent(text, cls._BEARISH_KEYWORDS):
            return "down"
        if cls._first_intent_position(text, cls._WAIT_KEYWORDS) is not None:
            wait_pos = cls._first_intent_position(text, cls._WAIT_KEYWORDS)
            bullish_pos = cls._first_intent_position(text, cls._BULLISH_KEYWORDS)
            hold_pos = cls._first_intent_position(text, cls._HOLD_KEYWORDS)
            if (bullish_pos is None or wait_pos < bullish_pos) and (
                hold_pos is None or wait_pos < hold_pos
            ):
                return "flat"
        if cls._matches_intent(text, cls._BULLISH_KEYWORDS):
            return "up"
        if cls._matches_intent(text, cls._HOLD_KEYWORDS):
            return "not_down"
        if cls._matches_intent(text, cls._WAIT_KEYWORDS):
            return "flat"
        return "flat"

    @classmethod
    def infer_position_recommendation(cls, operation_advice: Optional[str]) -> str:
        """Infer recommended position: long/cash (long-only system).

        Priority: bearish/wait -> cash, bullish/hold -> long, unrecognized -> cash.
        """
        text = cls._normalize_text(operation_advice)
        if cls._matches_intent(text, cls._BEARISH_KEYWORDS):
            return "cash"
        wait_pos = cls._first_intent_position(text, cls._WAIT_KEYWORDS)
        if wait_pos is not None:
            bullish_pos = cls._first_intent_position(text, cls._BULLISH_KEYWORDS)
            hold_pos = cls._first_intent_position(text, cls._HOLD_KEYWORDS)
            if (bullish_pos is None or wait_pos < bullish_pos) and (
                hold_pos is None or wait_pos < hold_pos
            ):
                return "cash"
        if cls._matches_intent(text, cls._BULLISH_KEYWORDS) or cls._matches_intent(text, cls._HOLD_KEYWORDS):
            return "long"
        if cls._matches_intent(text, cls._WAIT_KEYWORDS):
            return "cash"
        return "cash"

    @classmethod
    def evaluate_single(
        cls,
        *,
        operation_advice: Optional[str],
        analysis_date: date,
        start_price: float,
        forward_bars: Sequence[DailyBarLike],
        stop_loss: Optional[float],
        take_profit: Optional[float],
        config: EvaluationConfig,
        price_context: Optional["EntryBasis"] = None,
    ) -> Dict[str, Any]:
        """Evaluate one historical analysis against forward daily bars.

        Notes:
        - Daily bars cannot determine intraday ordering. If stop-loss and
          take-profit are both touched in the same bar, we record
          first_hit="ambiguous" and assume stop-loss first for simulated exit.
        - ``price_context`` 為 None 時行為與舊版完全相同；給了就代表
          ``start_price`` 是進場 K 棒（``forward_bars[0]``）的開盤，報酬、停損停利
          判定都換到進場日的還原基準，存檔價位仍是原始價。
        """
        if price_context is not None:
            return cls._evaluate_single_with_basis(
                operation_advice=operation_advice,
                analysis_date=analysis_date,
                start_price=start_price,
                forward_bars=forward_bars,
                stop_loss=stop_loss,
                take_profit=take_profit,
                config=config,
                basis=price_context,
            )

        if start_price is None or start_price <= 0:
            return {
                "analysis_date": analysis_date,
                "operation_advice": operation_advice,
                "position_recommendation": cls.infer_position_recommendation(operation_advice),
                "direction_expected": cls.infer_direction_expected(operation_advice),
                "eval_status": "error",
            }

        eval_days = int(config.eval_window_days)
        if eval_days <= 0:
            raise ValueError("eval_window_days must be positive")

        if len(forward_bars) < eval_days:
            return {
                "analysis_date": analysis_date,
                "operation_advice": operation_advice,
                "position_recommendation": cls.infer_position_recommendation(operation_advice),
                "direction_expected": cls.infer_direction_expected(operation_advice),
                "eval_status": "insufficient_data",
                "eval_window_days": eval_days,
            }

        window_bars = list(forward_bars[:eval_days])
        end_close = window_bars[-1].close
        highs = [b.high for b in window_bars if b.high is not None]
        lows = [b.low for b in window_bars if b.low is not None]
        max_high = max(highs) if highs else None
        min_low = min(lows) if lows else None

        stock_return_pct: Optional[float]
        if end_close is None:
            stock_return_pct = None
        else:
            stock_return_pct = (end_close - start_price) / start_price * 100

        direction_expected = cls.infer_direction_expected(operation_advice)
        position = cls.infer_position_recommendation(operation_advice)

        outcome, direction_correct = cls._classify_outcome(
            stock_return_pct=stock_return_pct,
            direction_expected=direction_expected,
            neutral_band_pct=config.neutral_band_pct,
        )

        (
            hit_stop_loss,
            hit_take_profit,
            first_hit,
            first_hit_date,
            first_hit_days,
            simulated_exit_price,
            simulated_exit_reason,
        ) = cls._evaluate_targets(
            position=position,
            stop_loss=stop_loss,
            take_profit=take_profit,
            window_bars=window_bars,
            end_close=end_close,
        )

        simulated_entry_price = start_price if position == "long" else None
        simulated_return_pct: Optional[float]
        if position != "long":
            simulated_return_pct = 0.0
        elif simulated_exit_price is None:
            simulated_return_pct = None
        else:
            simulated_return_pct = (simulated_exit_price - start_price) / start_price * 100

        return {
            "analysis_date": analysis_date,
            "eval_window_days": eval_days,
            "engine_version": config.engine_version,
            "eval_status": "completed",
            "operation_advice": operation_advice,
            "position_recommendation": position,
            "start_price": start_price,
            "end_close": end_close,
            "max_high": max_high,
            "min_low": min_low,
            "stock_return_pct": stock_return_pct,
            "direction_expected": direction_expected,
            "direction_correct": direction_correct,
            "outcome": outcome,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "hit_stop_loss": hit_stop_loss,
            "hit_take_profit": hit_take_profit,
            "first_hit": first_hit,
            "first_hit_date": first_hit_date,
            "first_hit_trading_days": first_hit_days,
            "simulated_entry_price": simulated_entry_price,
            "simulated_exit_price": simulated_exit_price,
            "simulated_exit_reason": simulated_exit_reason,
            "simulated_return_pct": simulated_return_pct,
        }

    @classmethod
    def _evaluate_single_with_basis(
        cls,
        *,
        operation_advice: Optional[str],
        analysis_date: date,
        start_price: float,
        forward_bars: Sequence[DailyBarLike],
        stop_loss: Optional[float],
        take_profit: Optional[float],
        config: EvaluationConfig,
        basis: "EntryBasis",
    ) -> Dict[str, Any]:
        from src.services.backtest_price_basis import compute_tw_net_return_pct

        position = cls.infer_position_recommendation(operation_advice)
        direction_expected = cls.infer_direction_expected(operation_advice)
        start_value = cls._finite_optional_float(start_price)
        if start_value is None or start_value <= 0:
            return {
                "analysis_date": analysis_date,
                "operation_advice": operation_advice,
                "position_recommendation": position,
                "direction_expected": direction_expected,
                "eval_status": "error",
            }

        eval_days = int(config.eval_window_days)
        if eval_days <= 0:
            raise ValueError("eval_window_days must be positive")
        if len(forward_bars) < eval_days:
            return {
                "analysis_date": analysis_date,
                "operation_advice": operation_advice,
                "position_recommendation": position,
                "direction_expected": direction_expected,
                "eval_status": "insufficient_data",
                "eval_window_days": eval_days,
            }

        window_bars = list(forward_bars[:eval_days])
        end_bar = window_bars[-1]
        end_close = cls._finite_optional_float(end_bar.close)
        highs = [h for h in (cls._finite_optional_float(b.high) for b in window_bars) if h is not None]
        lows = [v for v in (cls._finite_optional_float(b.low) for b in window_bars) if v is not None]
        max_high = max(highs) if highs else None
        min_low = min(lows) if lows else None

        # 分類用「進場開盤 → 期末收盤」的還原毛報酬；成本永遠不影響分類。
        stock_return_pct: Optional[float] = None
        if end_close is not None:
            end_adj = end_close * basis.rel(end_bar.date)
            stock_return_pct = (end_adj - start_value) / start_value * 100

        outcome, direction_correct = cls._classify_outcome(
            stock_return_pct=stock_return_pct,
            direction_expected=direction_expected,
            neutral_band_pct=config.neutral_band_pct,
        )

        level_factor = float(basis.level_factor)
        stop_adj = None if stop_loss is None else float(stop_loss) * level_factor
        take_adj = None if take_profit is None else float(take_profit) * level_factor
        adjusted_bars = [
            _AdjustedBar(
                date=b.date,
                open=cls._scaled(getattr(b, "open", None), basis.rel(b.date)),
                high=cls._scaled(b.high, basis.rel(b.date)),
                low=cls._scaled(b.low, basis.rel(b.date)),
            )
            for b in window_bars
        ]
        end_adj_close = None if end_close is None else end_close * basis.rel(end_bar.date)
        (
            hit_stop_loss,
            hit_take_profit,
            first_hit,
            first_hit_date,
            first_hit_days,
            exit_adj,
            simulated_exit_reason,
        ) = cls._evaluate_targets(
            position=position,
            stop_loss=stop_adj,
            take_profit=take_adj,
            window_bars=adjusted_bars,
            end_close=end_adj_close,
            gap_aware=True,
        )

        simulated_entry_price = start_value if position == "long" else None
        simulated_exit_price: Optional[float] = None
        simulated_return_pct: Optional[float]
        simulated_net_return_pct: Optional[float]
        if position != "long":
            simulated_return_pct = 0.0
            simulated_net_return_pct = 0.0 if basis.cost_multipliers is not None else None
        elif exit_adj is None:
            simulated_return_pct = None
            simulated_net_return_pct = None
        else:
            simulated_return_pct = (exit_adj - start_value) / start_value * 100
            simulated_net_return_pct = compute_tw_net_return_pct(
                simulated_return_pct, basis.cost_multipliers
            )
            exit_day = first_hit_date if first_hit_date is not None else end_bar.date
            # 存檔用原始價：還原價除回該日的相對乘數。
            simulated_exit_price = exit_adj / basis.rel(exit_day)

        return {
            "analysis_date": analysis_date,
            "eval_window_days": eval_days,
            "engine_version": config.engine_version,
            "eval_status": "completed",
            "operation_advice": operation_advice,
            "position_recommendation": position,
            "start_price": start_value,
            "end_close": end_close,
            "max_high": max_high,
            "min_low": min_low,
            "stock_return_pct": stock_return_pct,
            "direction_expected": direction_expected,
            "direction_correct": direction_correct,
            "outcome": outcome,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "hit_stop_loss": hit_stop_loss,
            "hit_take_profit": hit_take_profit,
            "first_hit": first_hit,
            "first_hit_date": first_hit_date,
            "first_hit_trading_days": first_hit_days,
            "simulated_entry_price": simulated_entry_price,
            "simulated_exit_price": simulated_exit_price,
            "simulated_exit_reason": simulated_exit_reason,
            "simulated_return_pct": simulated_return_pct,
            "simulated_net_return_pct": simulated_net_return_pct,
            "entry_date": basis.entry_date,
            "price_basis": basis.price_basis,
            "adjustment_reason": basis.adjustment_reason,
        }

    @classmethod
    def _scaled(cls, value: Any, factor: float) -> Optional[float]:
        number = cls._finite_optional_float(value)
        return None if number is None else number * factor

    @classmethod
    def evaluate_decision_signal(
        cls,
        *,
        direction_expected: str,
        anchor_date: date,
        start_price: float,
        forward_bars: Sequence[DailyBarLike],
        config: EvaluationConfig,
        price_context: Optional["EntryBasis"] = None,
    ) -> Dict[str, Any]:
        """Evaluate a structured DecisionSignal action without text inference.

        ``price_context`` 給了時 ``start_price`` 是 ``forward_bars[0]`` 的開盤，
        報酬與最大不利偏移用進場日還原基準計算；存檔價位仍是原始價。
        """

        start_price_value = cls._finite_optional_float(start_price)
        if start_price_value is None or start_price_value <= 0:
            return {
                "anchor_date": anchor_date,
                "direction_expected": direction_expected,
                "eval_status": "unable",
                "unable_reason": "invalid_anchor_price",
            }

        eval_days = int(config.eval_window_days)
        if eval_days <= 0:
            raise ValueError("eval_window_days must be positive")

        if len(forward_bars) < eval_days:
            return {
                "anchor_date": anchor_date,
                "eval_window_days": eval_days,
                "engine_version": config.engine_version,
                "direction_expected": direction_expected,
                "eval_status": "unable",
                "unable_reason": "insufficient_forward_bars",
            }

        window_bars = list(forward_bars[:eval_days])
        raw_end_close = window_bars[-1].close
        end_close = cls._finite_optional_float(raw_end_close)
        highs: List[float] = []
        lows: List[float] = []
        for bar in window_bars:
            high = cls._finite_optional_float(bar.high)
            low = cls._finite_optional_float(bar.low)
            if high is not None:
                highs.append(high)
            if low is not None:
                lows.append(low)
        max_high = max(highs) if highs else None
        min_low = min(lows) if lows else None

        stock_return_pct: Optional[float]
        if end_close is None:
            stock_return_pct = None
        elif price_context is not None:
            end_adj = end_close * price_context.rel(window_bars[-1].date)
            stock_return_pct = (end_adj - start_price_value) / start_price_value * 100
        else:
            stock_return_pct = (end_close - start_price_value) / start_price_value * 100

        basis_fields: Dict[str, Any] = {}
        if price_context is not None:
            basis_fields = {
                "entry_date": price_context.entry_date,
                "price_basis": price_context.price_basis,
                "adjustment_reason": price_context.adjustment_reason,
                "max_adverse_excursion_pct": cls._signal_max_adverse_excursion_pct(
                    direction_expected=direction_expected,
                    start_price=start_price_value,
                    window_bars=window_bars,
                    basis=price_context,
                ),
            }

        outcome, direction_correct = cls._classify_signal_outcome(
            stock_return_pct=stock_return_pct,
            direction_expected=direction_expected,
            neutral_band_pct=config.neutral_band_pct,
        )

        if stock_return_pct is None:
            return {
                "anchor_date": anchor_date,
                "eval_window_days": eval_days,
                "engine_version": config.engine_version,
                "direction_expected": direction_expected,
                "eval_status": "unable",
                "unable_reason": "missing_end_close" if raw_end_close is None else "invalid_end_close",
                "start_price": start_price_value,
                "end_close": end_close,
                "max_high": max_high,
                "min_low": min_low,
                **basis_fields,
            }

        return {
            "anchor_date": anchor_date,
            "eval_window_days": eval_days,
            "engine_version": config.engine_version,
            "eval_status": "completed",
            "direction_expected": direction_expected,
            "direction_correct": direction_correct,
            "outcome": outcome,
            "start_price": start_price_value,
            "end_close": end_close,
            "max_high": max_high,
            "min_low": min_low,
            "stock_return_pct": stock_return_pct,
            **basis_fields,
        }

    @classmethod
    def _signal_max_adverse_excursion_pct(
        cls,
        *,
        direction_expected: str,
        start_price: float,
        window_bars: Sequence[DailyBarLike],
        basis: "EntryBasis",
    ) -> Optional[float]:
        """進場基準下的最大不利偏移（%）：看多／持有看最低價，看空看最高價。"""
        if direction_expected in ("up", "not_down"):
            lows = [
                v for v in (cls._scaled(b.low, basis.rel(b.date)) for b in window_bars) if v is not None
            ]
            if not lows:
                return None
            return max(0.0, (start_price - min(lows)) / start_price * 100)
        if direction_expected == "not_up":
            highs = [
                v for v in (cls._scaled(b.high, basis.rel(b.date)) for b in window_bars) if v is not None
            ]
            if not highs:
                return None
            return max(0.0, (max(highs) - start_price) / start_price * 100)
        return None

    @classmethod
    def compute_summary(
        cls,
        *,
        results: Iterable[BacktestResultLike],
        scope: str,
        code: Optional[str],
        eval_window_days: int,
        engine_version: str,
    ) -> Dict[str, Any]:
        """Aggregate BacktestResult rows into summary metrics."""
        results_list = list(results)

        total = len(results_list)
        completed = [r for r in results_list if (r.eval_status or "") == "completed"]
        insufficient_count = sum(1 for r in results_list if (r.eval_status or "") == "insufficient_data")

        long_count = sum(1 for r in completed if (r.position_recommendation or "") == "long")
        cash_count = sum(1 for r in completed if (r.position_recommendation or "") == "cash")

        win_count = sum(1 for r in completed if (r.outcome or "") == "win")
        loss_count = sum(1 for r in completed if (r.outcome or "") == "loss")
        neutral_count = sum(1 for r in completed if (r.outcome or "") == "neutral")

        direction_denominator = sum(1 for r in completed if r.direction_correct is not None)
        direction_numerator = sum(1 for r in completed if r.direction_correct is True)
        direction_accuracy_pct = (
            round(direction_numerator / direction_denominator * 100, 2) if direction_denominator else None
        )

        win_loss_denominator = win_count + loss_count
        win_rate_pct = round(win_count / win_loss_denominator * 100, 2) if win_loss_denominator else None
        neutral_rate_pct = round(neutral_count / len(completed) * 100, 2) if completed else None

        avg_stock_return_pct = cls._average([r.stock_return_pct for r in completed])
        avg_simulated_return_pct = cls._average([r.simulated_return_pct for r in completed])

        stop_applicable = [
            r
            for r in completed
            if (r.position_recommendation or "") == "long" and r.hit_stop_loss is not None
        ]
        stop_loss_trigger_rate = (
            round(sum(1 for r in stop_applicable if r.hit_stop_loss is True) / len(stop_applicable) * 100, 2)
            if stop_applicable
            else None
        )

        take_profit_applicable = [
            r
            for r in completed
            if (r.position_recommendation or "") == "long" and r.hit_take_profit is not None
        ]
        take_profit_trigger_rate = (
            round(
                sum(1 for r in take_profit_applicable if r.hit_take_profit is True) / len(take_profit_applicable) * 100,
                2,
            )
            if take_profit_applicable
            else None
        )

        any_target_applicable = [
            r
            for r in completed
            if (r.position_recommendation or "") == "long"
            and (r.hit_stop_loss is not None or r.hit_take_profit is not None)
        ]
        ambiguous_rate = (
            round(
                sum(1 for r in any_target_applicable if (r.first_hit or "") == "ambiguous")
                / len(any_target_applicable)
                * 100,
                2,
            )
            if any_target_applicable
            else None
        )
        avg_days_to_first_hit = cls._average(
            [
                float(r.first_hit_trading_days)
                for r in any_target_applicable
                if r.first_hit_trading_days is not None and (r.first_hit or "") in ("stop_loss", "take_profit", "ambiguous")
            ]
        )

        advice_breakdown = cls._compute_advice_breakdown(completed)
        diagnostics = cls._compute_diagnostics(results_list)

        return {
            "scope": scope,
            "code": code,
            "eval_window_days": int(eval_window_days),
            "engine_version": engine_version,
            "total_evaluations": total,
            "completed_count": len(completed),
            "insufficient_count": insufficient_count,
            "long_count": long_count,
            "cash_count": cash_count,
            "win_count": win_count,
            "loss_count": loss_count,
            "neutral_count": neutral_count,
            "direction_accuracy_pct": direction_accuracy_pct,
            "win_rate_pct": win_rate_pct,
            "neutral_rate_pct": neutral_rate_pct,
            "avg_stock_return_pct": avg_stock_return_pct,
            "avg_simulated_return_pct": avg_simulated_return_pct,
            "stop_loss_trigger_rate": stop_loss_trigger_rate,
            "take_profit_trigger_rate": take_profit_trigger_rate,
            "ambiguous_rate": ambiguous_rate,
            "avg_days_to_first_hit": avg_days_to_first_hit,
            "advice_breakdown": advice_breakdown,
            "diagnostics": diagnostics,
        }

    @staticmethod
    def _normalize_text(value: Optional[str]) -> str:
        return str(value or "").strip().lower().translate(BacktestEngine._TRAD_TO_SIMP)

    @classmethod
    def _matches_intent(cls, text: str, keywords: Sequence[str]) -> bool:
        """Check if text expresses the intent of any keyword, accounting for negation.

        Tier 1: exact match (covers clean labels like "买入", "hold").
        Tier 2: substring match with negation guard.
        Keywords are assumed to be lowercase (matching _normalize_text output).
        """
        return cls._first_intent_position(text, keywords) is not None

    @classmethod
    def _first_intent_position(cls, text: str, keywords: Sequence[str]) -> Optional[int]:
        """Return the earliest match position for intent keywords, or None."""
        if not text:
            return None

        best_pos: Optional[int] = None

        for kw in keywords:
            if not kw:
                continue
            if text == kw:
                return 0

            keyword = kw.lower().strip()
            if not keyword:
                continue

            # Use word-boundary matching for ASCII keywords to avoid
            # false positives such as "watch" matching "wait".
            if bool(re.search(r"[a-z]", keyword)):
                for match in re.finditer(
                    rf"(?<![a-zA-Z0-9_]){re.escape(keyword)}(?![a-zA-Z0-9_])",
                    text,
                ):
                    if not cls._is_negated(text[: match.start()], keyword):
                        pos = match.start()
                        if best_pos is None or pos < best_pos:
                            best_pos = pos
                            break
                    continue

            # For non-ASCII terms (Chinese), use substring matching to keep
            # natural language phrasings like "建议买入" effective.
            if re.search(r"[\u4e00-\u9fff]", keyword):
                start = 0
                while True:
                    match_idx = text.find(keyword, start)
                    if match_idx < 0:
                        break
                    if not cls._is_negated(text[:match_idx], keyword):
                        if best_pos is None or match_idx < best_pos:
                            best_pos = match_idx
                        break
                    start = match_idx + len(keyword)
                continue

        return best_pos

    @classmethod
    def _is_negated(cls, prefix: str, keyword: str) -> bool:
        """Check if the prefix text indicates negation for a candidate intent."""
        stripped = prefix.rstrip()
        target = (keyword or "").lower().strip()
        if not target:
            return False

        if any(stripped.endswith(neg) for neg in cls._NEGATION_PATTERNS):
            return True

        # 限定“否定 + 动作动词”匹配，避免将“条件位否定”误伤核心建议意图。
        lookback = stripped[-12:]
        for neg in cls._NEGATION_PATTERNS:
            if not neg:
                continue
            neg_idx = lookback.rfind(neg)
            if neg_idx < 0:
                continue

            suffix_gap = lookback[neg_idx + len(neg):].strip()
            if not suffix_gap:
                return True
            if any(ch in suffix_gap for ch in "，,。；;:!?！？"):
                continue

            if cls._contains_keyword(suffix_gap, target):
                return True

            # Keep English short-gap behavior where negation words are followed by
            # connector words such as "to" (e.g. "not to sell").
            if not any(ch >= "\u4e00" and ch <= "\u9fff" for ch in suffix_gap):
                if len(suffix_gap) <= 6:
                    return True
                continue

            if cls._is_negation_connector_gap(suffix_gap):
                return True

        return False

    @classmethod
    def _contains_keyword(cls, text: str, keyword: str) -> bool:
        """Check whether *keyword* exists in text with intent-aware boundaries."""
        if not text or not keyword:
            return False
        if bool(re.search(r"[a-z]", keyword)):
            return bool(re.search(rf"(?<![a-zA-Z0-9_]){re.escape(keyword)}(?![a-zA-Z0-9_])", text))
        return keyword in text

    @classmethod
    def _is_negation_connector_gap(cls, gap: str) -> bool:
        """Whether a short Chinese negation gap is still a valid negation bridge."""
        compact = re.sub(r"[\s,，。；;:!?！？]", "", gap).strip()
        if not compact:
            return True
        return compact in cls._NEGATION_CONNECTOR_WORDS

    @classmethod
    def _classify_outcome(
        cls,
        *,
        stock_return_pct: Optional[float],
        direction_expected: str,
        neutral_band_pct: float,
    ) -> tuple[Optional[str], Optional[bool]]:
        if stock_return_pct is None:
            return None, None

        band = abs(float(neutral_band_pct))
        r = float(stock_return_pct)

        if direction_expected == "up":
            if r >= band:
                return "win", True
            if r <= -band:
                return "loss", False
            return "neutral", None

        if direction_expected == "down":
            if r <= -band:
                return "win", True
            if r >= band:
                return "loss", False
            return "neutral", None

        if direction_expected == "not_down":
            if r >= 0:
                return "win", True
            if r <= -band:
                return "loss", False
            return "neutral", None

        # flat
        if abs(r) <= band:
            return "win", True
        return "loss", False

    @classmethod
    def _classify_signal_outcome(
        cls,
        *,
        stock_return_pct: Optional[float],
        direction_expected: str,
        neutral_band_pct: float,
    ) -> tuple[Optional[str], Optional[bool]]:
        if stock_return_pct is None:
            return None, None

        band = abs(float(neutral_band_pct))
        r = float(stock_return_pct)

        if direction_expected == "up":
            if r >= band:
                return "hit", True
            if r <= -band:
                return "miss", False
            return "neutral", None

        if direction_expected == "not_down":
            if r >= 0:
                return "hit", True
            if r <= -band:
                return "miss", False
            return "neutral", None

        if direction_expected == "not_up":
            if r <= band:
                return "hit", True
            return "miss", False

        return None, None

    @staticmethod
    def _finite_optional_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    @classmethod
    def _evaluate_targets(
        cls,
        *,
        position: str,
        stop_loss: Optional[float],
        take_profit: Optional[float],
        window_bars: Sequence[Any],
        end_close: Optional[float],
        gap_aware: bool = False,
    ) -> tuple[
        Optional[bool],
        Optional[bool],
        str,
        Optional[date],
        Optional[int],
        Optional[float],
        str,
    ]:
        if position != "long":
            return (
                None,
                None,
                "not_applicable",
                None,
                None,
                None,
                "cash",
            )

        has_any_target = stop_loss is not None or take_profit is not None
        if not has_any_target:
            return (
                None,
                None,
                "neither",
                None,
                None,
                end_close,
                "window_end",
            )

        hit_sl: Optional[bool] = None if stop_loss is None else False
        hit_tp: Optional[bool] = None if take_profit is None else False
        first_hit = "neither"
        first_hit_date: Optional[date] = None
        first_hit_days: Optional[int] = None
        exit_price: Optional[float] = end_close
        exit_reason = "window_end"

        for idx, bar in enumerate(window_bars, start=1):
            low = bar.low
            high = bar.high
            stop_hit = stop_loss is not None and low is not None and low <= stop_loss
            tp_hit = take_profit is not None and high is not None and high >= take_profit

            if stop_hit:
                hit_sl = True
            if tp_hit:
                hit_tp = True

            fill = resolve_long_exit(
                bar_open=getattr(bar, "open", None) if gap_aware else None,
                stop_loss=stop_loss,
                take_profit=take_profit,
                stop_hit=stop_hit,
                tp_hit=tp_hit,
            )
            if fill is None:
                continue

            first_hit_date = bar.date
            first_hit_days = idx
            exit_price, exit_reason = fill
            first_hit = "ambiguous" if exit_reason == "ambiguous_stop_loss" else exit_reason
            break

        return (
            hit_sl,
            hit_tp,
            first_hit,
            first_hit_date,
            first_hit_days,
            exit_price,
            exit_reason,
        )

    @staticmethod
    def _average(values: Iterable[Optional[float]]) -> Optional[float]:
        items = [float(v) for v in values if v is not None]
        if not items:
            return None
        return round(sum(items) / len(items), 4)

    @staticmethod
    def _compute_advice_breakdown(results: List[BacktestResultLike]) -> Dict[str, Any]:
        breakdown: Dict[str, Dict[str, int]] = {}
        for row in results:
            raw_advice = row.operation_advice
            advice = (raw_advice if isinstance(raw_advice, str) else str(raw_advice or "")).strip() or "(unknown)"
            bucket = breakdown.setdefault(advice, {"total": 0, "win": 0, "loss": 0, "neutral": 0})
            bucket["total"] += 1
            outcome = (row.outcome or "").strip()
            if outcome in ("win", "loss", "neutral"):
                bucket[outcome] += 1

        enriched: Dict[str, Any] = {}
        for advice, bucket in breakdown.items():
            win = bucket["win"]
            loss = bucket["loss"]
            denom = win + loss
            win_rate = round(win / denom * 100, 2) if denom else None
            enriched[advice] = {**bucket, "win_rate_pct": win_rate}
        return enriched

    @staticmethod
    def _compute_diagnostics(results: List[BacktestResultLike]) -> Dict[str, Any]:
        status_counts: Dict[str, int] = {}
        first_hit_counts: Dict[str, int] = {}
        for row in results:
            status = (row.eval_status or "").strip() or "(unknown)"
            status_counts[status] = status_counts.get(status, 0) + 1
            first_hit = (row.first_hit or "").strip() or "(none)"
            first_hit_counts[first_hit] = first_hit_counts.get(first_hit, 0) + 1
        return {
            "eval_status": status_counts,
            "first_hit": first_hit_counts,
        }
