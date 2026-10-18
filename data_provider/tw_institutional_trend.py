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


def _nets(row: dict) -> dict:
    """單列四個法人的淨買賣超。total_net 缺值但三分項齊全時用三者之和；
    任一分項缺值就維持 None（不拿不完整的和冒充合計）。"""
    nets = {a: _to_int(row.get(_NET_KEY[a])) for a in _ACTORS}
    if nets["total"] is None and all(nets[a] is not None for a in ("foreign", "trust", "dealer")):
        nets["total"] = nets["foreign"] + nets["trust"] + nets["dealer"]
    return nets


def compute_institutional_trend(
    history_rows: Any,
    today_record: Optional[dict],
    shares_outstanding: Any,
    expected_prev_session: Any = None,
) -> dict:
    """Build one date-ordered series (history up to prev day + today authoritative),
    compute per-actor streak / cum_5d / cum_20d and total pct_of_shares.
    Return {} if no usable series. Never raises.

    - cum_5d / cum_20d 只在最近 w 列「每一列都有值」時才給，否則 None：
      樣本不足時把 1 天當「近 20 日累計」會被 LLM 讀成 20 天（上櫃股歷史是空的，只有當日一列）。
      內部歷史缺洞（例如 DB 缺 01-22、01-30）會讓 w 列窗口跨更長的曆日，可接受。
    - expected_prev_session（今天之前的最後一個交易日）有給、且歷史最後一天比它早，代表本地歷史
      停更：丟掉歷史、只留今天一列，並回 history_gap 讓呼叫端明講；沒給就不做連續性檢查。
    - history_sessions：實際用到的歷史場次數（不含今天）。"""
    today_date = _norm_date((today_record or {}).get("date"))

    series: list[tuple[date, dict]] = []
    for row in (history_rows or []):
        d = _norm_date(row.get("date"))
        if d is None:
            continue
        if today_date is not None and d >= today_date:
            continue  # drop rows on/after today; today comes from the authoritative record
        series.append((d, _nets(row)))
    series.sort(key=lambda x: x[0])

    history_gap: Optional[dict] = None
    expected = _norm_date(expected_prev_session)
    if (
        expected is not None
        and today_record is not None
        and today_date is not None
        and series
        and series[-1][0] < expected
    ):
        history_gap = {
            "last_history": series[-1][0].isoformat(),
            "expected": expected.isoformat(),
        }
        series = []  # 歷史停更：中間缺的場次不明，算連續買賣超或累計都會失真
    history_sessions = len(series)

    if today_record is not None and today_date is not None:
        series.append((today_date, _nets(today_record)))
    if not series:
        return {}
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
        tail = [d[1][actor] for d in series[-window:]]
        if len(tail) < window or any(v is None for v in tail):
            return None
        return sum(tail)

    out: dict[str, Any] = {
        "as_of": series[-1][0].isoformat(),
        "sessions": n,
        "history_sessions": history_sessions,
    }
    if history_gap is not None:
        out["history_gap"] = history_gap
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
