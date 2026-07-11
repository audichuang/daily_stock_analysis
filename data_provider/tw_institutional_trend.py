"""Pure functions computing Taiwan 三大法人 (institutional) history trend.

No DB / no network / no I/O — fully unit-testable. Consumers (the analyzer
prompt layer) read history + today's record and pass them here. Output is used
ONLY to build LLM prompt lines; it is never persisted.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

_ACTORS = ("foreign", "trust", "dealer", "total")
_NET_KEY = {
    "foreign": "foreign_net",
    "trust": "trust_net",
    "dealer": "dealer_net",
    "total": "total_net",
}


def _norm_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip().replace("-", "").replace("/", "")
    if len(s) == 8 and s.isdigit():
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    try:
        return datetime.fromisoformat(str(value)).date()
    except (ValueError, TypeError):
        return None


def _to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def compute_institutional_trend(
    history_rows: Any,
    today_record: Optional[dict],
    shares_outstanding: Any,
) -> dict:
    """Build one date-ordered series (history up to prev day + today authoritative),
    compute per-actor streak / cum_5d / cum_20d and total pct_of_shares.
    Return {} if no usable series. Never raises."""
    today_date = _norm_date((today_record or {}).get("date"))

    series: list[tuple[date, dict]] = []
    for row in (history_rows or []):
        d = _norm_date(row.get("date"))
        if d is None:
            continue
        if today_date is not None and d >= today_date:
            continue  # drop rows on/after today; today comes from the authoritative record
        series.append((d, {a: _to_int(row.get(_NET_KEY[a])) for a in _ACTORS}))
    if today_record is not None and today_date is not None:
        series.append((today_date, {a: _to_int(today_record.get(_NET_KEY[a])) for a in _ACTORS}))
    if not series:
        return {}
    series.sort(key=lambda x: x[0])
    n = len(series)

    def _streak(actor: str) -> dict:
        vals = [d[1][actor] for d in series]
        latest = vals[-1]
        if latest is None or latest == 0:
            return {"days": 0, "direction": "flat", "capped": False}
        sign = 1 if latest > 0 else -1
        days = 0
        for v in reversed(vals):
            if v is None or v == 0 or (1 if v > 0 else -1) != sign:
                break
            days += 1
        return {"days": days, "direction": "buy" if sign > 0 else "sell", "capped": days == n}

    def _cum(actor: str, window: int) -> Optional[int]:
        present = [d[1][actor] for d in series[-window:] if d[1][actor] is not None]
        return sum(present) if present else None

    out: dict[str, Any] = {"as_of": series[-1][0].isoformat(), "sessions": n}
    for a in _ACTORS:
        out[a] = {"streak": _streak(a), "cum_5d": _cum(a, 5), "cum_20d": _cum(a, 20)}
    shares = _to_int(shares_outstanding)
    total_cum20 = out["total"]["cum_20d"]
    out["total"]["pct_of_shares"] = (
        round(total_cum20 / shares * 100, 2)
        if (total_cum20 is not None and shares and shares > 0)
        else None
    )
    return out
