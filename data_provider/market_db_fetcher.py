"""Local Postgres (market schema) as the preferred TW daily-history source.

Reads finlab-crawled history from market.* instead of hitting yfinance for
Taiwan stocks. Falls through (raises) when the DB has no data / is unreachable,
so the existing yfinance chain still serves as fallback.
"""

import pandas as pd

from .base import BaseFetcher, DataSourceUnavailableError


def _stock_id(code: str) -> str:
    # '2330.TW' / '6505.TWO' -> '2330' / '6505'
    return str(code).split(".")[0]


def _is_tw(code: str) -> bool:
    # only serve Taiwan suffix codes; bare 6-digit codes stay CN semantics and
    # must not be answered from market.* (which is TW-only).
    return str(code).upper().endswith((".TW", ".TWO"))


class MarketDBFetcher(BaseFetcher):
    name = "MarketDBFetcher"
    priority = 1  # prefer local history over yfinance (priority 4) for TW

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        from market_data import market_repo

        if not _is_tw(stock_code):
            raise DataSourceUnavailableError(
                f"MarketDBFetcher serves TW only, not {stock_code}")
        try:
            df = market_repo.price_history(_stock_id(stock_code),
                                           start=start_date, end=end_date)
        except Exception as e:  # missing DATABASE_URL / DB down -> let chain fall back
            raise DataSourceUnavailableError(f"market DB unavailable: {e}") from e
        if df is None or df.empty:
            raise DataSourceUnavailableError(
                f"market DB has no price for {stock_code}")
        return df

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        from market_data import market_repo

        try:
            # 除權息日的 pct_chg 必須是還原後報酬（價格斷崖不是真實跌幅）；
            # 沒有因子的日期乘 1，行為與未還原完全一致。見 market_repo.to_daily_frame。
            # sessions：颱風休市日公告的事件要移到下一個交易日，否則那天的 pct_chg 是假跌幅。
            factors = market_repo.adjustment_multipliers(
                _stock_id(stock_code), sessions=pd.to_datetime(df["date"]))
        except Exception as e:  # 因子查詢失敗視同 DB 不可用 -> 讓鏈 fallback
            raise DataSourceUnavailableError(f"market DB unavailable: {e}") from e
        return market_repo.to_daily_frame(df, event_factors=factors)
