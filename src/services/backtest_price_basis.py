# -*- coding: utf-8 -*-
"""回測／DecisionSignal 後驗的價格基準：T+1 開盤進場、台股還原報酬、台股淨報酬。

`stock_daily` 存的是**未還原**價（與券商 App 一致），窗口內遇到除權息日，原始收盤
直接相減會把「股價持平、只是配息」算成約 -3.5% 的下跌（買進建議被判錯、賣出建議白撿）。
這裡把窗口內每根 K 棒換算到「進場日的價格基準」：

    adjusted_t = raw_t × m_t / m_entry

`m_t` 是 `market_data.market_repo.front_adjust_multipliers` 給的前復權乘數。只有台股
（`.TW`／`.TWO`）查因子；其他市場維持原樣（`as_stored`）。查不到因子時整個窗口退回原始價
並標 `price_basis='raw'`，絕不讓回測失敗；**不做逐根混用**（Yahoo 列已含分割調整、
MarketDB 列沒有，混在同一筆報酬裡兩個基準會互相污染）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import logging
import math
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

from src.services.market_symbol_utils import is_tw_suffix_symbol, split_suffix_symbol
from src.utils.tw_trade_costs import per_share_cost_multipliers

logger = logging.getLogger(__name__)

PRICE_BASIS_ADJUSTED = "adjusted"
PRICE_BASIS_RAW = "raw"
PRICE_BASIS_AS_STORED = "as_stored"

REASON_FACTOR_UNAVAILABLE = "factor_unavailable"
REASON_INVALID_FACTORS = "invalid_factors"
REASON_NON_MARKETDB_BARS = "non_marketdb_bars"

MARKET_DB_SOURCE = "MarketDBFetcher"

# 盤中（含午休、收盤集合競價）分析：錨點 K 棒是前一個交易日，但分析當下已經看得到當天
# 的開盤，若仍以當天開盤進場就是偷看了半個交易日；這幾個 phase 改成分析日之後才進場。
INTRADAY_ENTRY_GUARD_PHASES = frozenset({"intraday", "lunch_break", "closing_auction"})

# 盤前分析：開盤前就已產出，當天開盤可成交，進場就是場次日（session_date）當天的開盤。
PREMARKET_PHASE = "premarket"


def resolve_entry_cutoff(
    *,
    phase: Optional[str],
    anchor_date: date,
    session_date: Optional[date],
    analysis_date: Optional[date] = None,
    minutes_to_open: Any = None,
) -> date:
    """執行截止日：進場 K 棒是第一根 ``date > 截止日`` 的日線（以其開盤進場）。

    回測與 DecisionSignal 後驗共用這一條，兩邊對同一份分析的進場日才會一致。

    - ``anchor_date``：呼叫端原本的錨點（回測是分析當下最近一根完整日線，信號是場次日）。
    - ``session_date``：持久化的市場場次日；只接受真的存下來的值，不要拿分析日頂替
      （即時報價失敗時分析日會停在前一交易日，拿來當盤前場次日會提早一天進場）。
    - ``analysis_date``：盤中類分析的舊紀錄沒有場次日時，退而以分析日當截止日下限。
    - ``minutes_to_open``：持久化的距開盤分鐘數，是「分析真的寫在開盤前」的唯一證據。
      行事曆只在 phase 為盤前且當下早於場次開盤時才給值；手動指定 ``analysis_phase=premarket``
      只覆寫 phase，收盤後覆寫時這欄是空的。回測與信號兩邊的持久化摘要都保留它。

    規則：
    - 盤中／午休／收盤集合競價：分析時已看得到當天開盤，截止日取錨點、分析日、場次日中最晚者。
    - 盤前且有開盤前證據（``minutes_to_open`` 為非負整數）：場次日開盤還沒發生，截止日就是
      場次日前一天（場次日當天開盤進場）：錨點等於場次日時不跳過場次日，錨點落後（中間缺日線）
      時也不提前到場次日之前。
    - 盤前但沒有開盤前證據（盤中或收盤後手動覆寫成盤前、行事曆失效、舊紀錄）：截止日取錨點與
      場次日較晚者，寧可晚一天進場也不回溯吃到已發生的開盤；沒有場次日沿用錨點。
    - 盤後、非交易日與未知 phase：沿用錨點。
    """
    normalized = str(phase or "").strip().lower()
    if normalized in INTRADAY_ENTRY_GUARD_PHASES:
        return max(d for d in (anchor_date, analysis_date, session_date) if d is not None)
    if normalized == PREMARKET_PHASE and session_date is not None:
        if _is_pre_open_minutes(minutes_to_open):
            return session_date - timedelta(days=1)
        # 沒有開盤前證據：當成場次日開盤已發生（手動覆寫的盤前可能寫在盤中或收盤後），
        # 至少要等場次日之後才進場。
        return max(anchor_date, session_date)
    return anchor_date


def _is_pre_open_minutes(value: Any) -> bool:
    """距開盤分鐘數是否構成開盤前證據：非負整數（容忍持久化後變成的數字字串）。"""
    if value is None or isinstance(value, bool):
        return False
    try:
        return int(value) >= 0
    except (TypeError, ValueError):
        return False


# factor_loader(stock_id, dates) -> {date: m_t}；回傳的 key 必須涵蓋所有輸入日期。
FactorLoader = Callable[[str, Sequence[date]], Mapping[date, float]]


@dataclass(frozen=True)
class EntryBasis:
    """一筆評估的價格基準。`rel_by_date[d]` ＝ m_d / m_entry（進場日為 1）。"""

    price_basis: str
    adjustment_reason: Optional[str]
    entry_date: date
    rel_by_date: Mapping[date, float] = field(default_factory=dict)
    # 停損／停利是錨點日的名目價位，換到進場基準要乘 m_anchor / m_entry。
    level_factor: float = 1.0
    # 台股 (買進乘數, 賣出乘數)；非台股為 None（不算淨報酬）。
    cost_multipliers: Optional[Tuple[float, float]] = None

    def rel(self, day: Any) -> float:
        key = _as_date(day)
        if key is None:
            return 1.0
        return float(self.rel_by_date.get(key, 1.0))


def tw_stock_id(code: Optional[str]) -> Optional[str]:
    """`2330.TW` → `2330`、`00631L.TWO` → `00631L`；非台股後綴（含裸 `2330`）回 None。"""
    text = str(code or "").strip()
    if not text or not is_tw_suffix_symbol(text):
        return None
    parts = split_suffix_symbol(text)
    return parts[0] if parts else None


def default_factor_loader(stock_id: str, dates: Sequence[date]) -> Dict[date, float]:
    """預設因子來源：`market.price_adjustment`，延遲 import、3 秒 statement timeout。"""
    import pandas as pd

    from market_data import market_repo
    from market_data.db import get_engine

    series = market_repo.front_adjust_multipliers(
        stock_id, list(dates), engine=get_engine(statement_timeout_ms=3000)
    )
    out: Dict[date, float] = {}
    for idx, value in series.items():
        out[pd.Timestamp(idx).date()] = float(value)
    return out


def resolve_entry_basis(
    *,
    code: Optional[str],
    anchor_date: date,
    window_bars: Sequence[Any],
    factor_loader: Optional[FactorLoader] = None,
    fee_discount: float = 1.0,
) -> EntryBasis:
    """決定窗口的價格基準。`window_bars[0]` 是進場 K 棒（以其開盤進場）。永不拋例外。"""
    if not window_bars:
        raise ValueError("window_bars must not be empty")
    entry_date = _as_date(getattr(window_bars[0], "date", None))
    if entry_date is None:
        raise ValueError("entry bar has no date")

    stock_id = tw_stock_id(code)
    if stock_id is None:
        return EntryBasis(PRICE_BASIS_AS_STORED, None, entry_date)

    cost_multipliers: Optional[Tuple[float, float]]
    try:
        cost_multipliers = per_share_cost_multipliers(
            is_etf=stock_id.startswith("00"), fee_discount=float(fee_discount)
        )
    except Exception as exc:  # 折扣設定異常不該拖垮回測
        logger.warning("[backtest] 台股成本乘數計算失敗，淨報酬留空: %s", exc)
        cost_multipliers = None

    def _raw(reason: str) -> EntryBasis:
        return EntryBasis(
            PRICE_BASIS_RAW, reason, entry_date, cost_multipliers=cost_multipliers
        )

    if any(getattr(bar, "data_source", None) != MARKET_DB_SOURCE for bar in window_bars):
        return _raw(REASON_NON_MARKETDB_BARS)

    window_dates = [_as_date(getattr(bar, "date", None)) for bar in window_bars]
    if any(d is None for d in window_dates):
        return _raw(REASON_INVALID_FACTORS)
    all_dates = sorted({anchor_date, *window_dates})

    loader = factor_loader or default_factor_loader
    try:
        raw_mult = loader(stock_id, all_dates)
    except Exception as exc:
        logger.debug("[backtest] %s 還原因子讀取失敗，退回原始價: %s", stock_id, exc)
        return _raw(REASON_FACTOR_UNAVAILABLE)

    mult: Dict[date, float] = {}
    try:
        for day, value in dict(raw_mult or {}).items():
            key = _as_date(day)
            if key is not None:
                mult[key] = float(value)
    except (TypeError, ValueError):
        return _raw(REASON_INVALID_FACTORS)
    if any(
        d not in mult or not math.isfinite(mult[d]) or mult[d] <= 0 for d in all_dates
    ):
        return _raw(REASON_INVALID_FACTORS)

    m_entry = mult[entry_date]
    return EntryBasis(
        PRICE_BASIS_ADJUSTED,
        None,
        entry_date,
        rel_by_date={d: mult[d] / m_entry for d in window_dates},
        level_factor=mult[anchor_date] / m_entry,
        cost_multipliers=cost_multipliers,
    )


def compute_tw_net_return_pct(
    gross_pct: Optional[float],
    cost_multipliers: Optional[Tuple[float, float]],
) -> Optional[float]:
    """比例式淨報酬估計：不含最低手續費 20 元與二代健保補充保費。"""
    if gross_pct is None or cost_multipliers is None:
        return None
    buy_mult, sell_mult = cost_multipliers
    return ((1 + float(gross_pct) / 100) * sell_mult / buy_mult - 1) * 100


def is_valid_entry_open(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


def _as_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if hasattr(value, "date") and callable(getattr(value, "date")):
        try:
            result = value.date()
        except Exception:
            return None
        return result if isinstance(result, date) else None
    return None
