"""即時報價屬於哪一個交易場次：分析上下文與新聞事件訊號共用的判定。"""
from datetime import date, datetime
from typing import Any, Callable, Optional

from data_provider.realtime_types import RealtimeSource


def coerce_to_date(value: Any) -> Optional[date]:
    """date／datetime（含 pandas.Timestamp）／ISO 字串（取前 10 碼）統一成 date；無法解析回 None。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


# 不帶報價日期、又可能落後一場的兜底來源：Stooq 的 CSV 日期在建報價時就丟了，DB 缺 T-1 時
# 它也可能同樣停在 T-2（實測 2026-10-22 紐約盤前），盤前不能憑日曆把它當成上一場收盤。
_UNDATED_LAGGING_SOURCES = frozenset({RealtimeSource.STOOQ.value})


def premarket_session_unknown(quote: Any) -> bool:
    """盤前報價沒有自帶日期、來源又可能落後一場時，它屬於哪一場無從得知。"""
    if coerce_to_date(getattr(quote, 'provider_timestamp', None)) is not None:
        return False
    source = getattr(quote, 'source', None)
    return str(getattr(source, 'value', source)) in _UNDATED_LAGGING_SOURCES


def resolve_quote_session(
    quote: Any,
    *,
    market_today: date,
    quote_is_today: bool,
    previous_session: Callable[[], date],
) -> date:
    """provider 時間優先；抓取時間可能是休市日，不能直接當作報價場次。"""
    return coerce_to_date(getattr(quote, 'provider_timestamp', None)) or (
        market_today if quote_is_today else previous_session()
    )
