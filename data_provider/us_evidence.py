"""美股補充證據的正規化與提示詞；純資訊，不參與評分。"""
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from .yfinance_fundamental_adapter import _safe_float, _ratio_to_pct, _epoch_to_date


def info_evidence(info: dict) -> dict:
    evidence = {}
    short = {}
    for source, field in (("sharesShort", "shares_short"), ("shortRatio", "days_to_cover")):
        value = _safe_float(info.get(source))
        if value is not None:
            short[field] = value
    value = _ratio_to_pct(info.get("shortPercentOfFloat"))
    if value is not None:
        short["float_pct"] = value
    if short:
        as_of = _epoch_to_date(info.get("dateShortInterest"))
        if as_of is not None:
            short["as_of"] = as_of
        evidence["short_interest"] = short
    for source, field in (("heldPercentInstitutions", "institutions_pct"), ("heldPercentInsiders", "insiders_pct")):
        value = _ratio_to_pct(info.get(source))
        if value is not None:
            evidence[field] = value
    timestamp = _safe_float(info.get("earningsTimestamp"))
    if timestamp is not None and timestamp > datetime.now(timezone.utc).timestamp():
        try:
            evidence["next_earnings_at"] = datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            pass
    return evidence


def summarize_activity(frame: Any, kind: str, *, now=None) -> dict:
    """只統計日期有效的窗口內資料；未辨識的內部人交易不當成買賣。"""
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return {}
    now = now or datetime.now(timezone.utc)
    days = 90 if kind == "insider" else 30
    dates = pd.to_datetime(frame["Start Date"] if kind == "insider" else frame.index, utc=True, errors="coerce")
    recent = frame[(dates >= now - timedelta(days=days)) & (dates <= now)]
    if recent.empty:
        return {}
    if kind == "insider":
        buys, sells, ignored = [], [], 0
        for _, row in recent.iterrows():
            shares = _safe_float(row.get("Shares"))
            text = str(row.get("Text", "")).strip().lower()
            if shares is not None and shares >= 0 and text.startswith("purchase"):
                buys.append(shares)
            elif shares is not None and shares >= 0 and text.startswith("sale"):
                sells.append(shares)
            else:
                ignored += 1
        if not buys and not sells:
            return {}
        return {"window_days": days, "as_of": now.date().isoformat(), "buy_shares": sum(buys),
                "sell_shares": sum(sells), "net_shares": sum(buys) - sum(sells),
                "classified_count": len(buys) + len(sells), "excluded_count": ignored}
    entries = []
    for date, row in recent.sort_index(ascending=False).iterrows():
        entry = {k: str(row[field]) for field, k in (("Firm", "firm"), ("Action", "action"),
                 ("FromGrade", "from_grade"), ("ToGrade", "to_grade")) if pd.notna(row.get(field))}
        if entry:
            entries.append({"date": pd.Timestamp(date).date().isoformat(), **entry})
    if not entries:
        return {}
    return {"window_days": days, "as_of": now.date().isoformat(), "count": len(entries), "entries": entries[:20]}


def format_us_evidence(fundamental_context: dict) -> str:
    """繁中來源標籤保留資料口徑，缺值不生成佔位數字。"""
    import json

    if not isinstance(fundamental_context, dict):
        return ""
    evidence = fundamental_context.get("us_evidence", {})
    valuation = fundamental_context.get("valuation", {}).get("data", {})
    rows = []
    if valuation.get("forward_pe") is not None:
        rows.append(f"預期本益比（yfinance forwardPE，預估盈餘口徑）：{valuation['forward_pe']}")
    short = evidence.get("short_interest")
    if short:
        rows.append(f"放空資料（資料日：{short.get('as_of') or '來源未提供'}；非即時）：" + json.dumps(short, ensure_ascii=False))
    for key, label in (("institutions_pct", "機構持股（%）"), ("insiders_pct", "內部人持股（%）"),
                       ("next_earnings_at", "下次財報時間（UTC，來源預估）"),
                       ("insider_90d", "近 90 天內部人淨買賣（股；僅可辨識買賣，非完整申報）"),
                       ("ratings_30d", "近 30 天評等調整摘要；評等可能尚未反映最新事件")):
        if key in evidence:
            rows.append(label + "：" + json.dumps(evidence[key], ensure_ascii=False))
    if evidence.get("futu"):
        rows.append("富途資金流（僅正常交易時段、未經回測、不計入評分；幣別 USD）：" + json.dumps(evidence["futu"], ensure_ascii=False))
    return "\n\n### 美股補充證據（純資訊）\n" + "\n".join(rows) + "\n" if rows else ""


def supplement_realtime(context: dict) -> None:
    fundamental = context.get("fundamental_context") or {}
    snapshot = fundamental.get("us_evidence", {}).get("futu", {}).get("snapshot", {})
    realtime = context.get("realtime") or context.get("realtime_quote")
    if isinstance(realtime, dict):
        for field in ("volume_ratio", "turnover_rate"):
            if realtime.get(field) is None and snapshot.get(field) is not None:
                realtime[field] = snapshot[field]
                if field == "volume_ratio" and "volume_ratio_desc" in realtime:
                    realtime["volume_ratio_desc"] = ""
