"""重大波動的事件判讀與無新聞護欄；開關關閉時完全不改原結果。"""
from datetime import date
from math import isfinite

from data_provider.us_index_mapping import is_us_stock_code
from src.services.market_symbol_utils import get_suffix_market


EVENT_GAP_RULES = """

### 重大波動事件判讀（優先於原有均線準則與評分表）
本次為事件驅動情境：覆蓋「只做多頭排列、空頭排列堅決不碰」與「站回均線才評估」的要求。
1. 先依新聞證據判斷事件性質，說明它是否打壞投資論題；沒有證據不得猜測原因。
2. 再看事件後下修的獲利預估與估值；預期本益比若尚未反映事件，明確揭露限制。
3. 再看止跌：明確列出需幾個交易日不破事件日低點、成交量是否縮減；尚未觀察到就列為待確認。
若已知事件後收盤已跌破事件日低點，止跌條件必須改用事件後新低重新計算，不得假設事件日低點仍守住。
買進可表達為「分批試單」，但必須列明失效條件（事件日低點、投資論題或估值假設失效）。
重新評估條件不得使用含事件日之前價格的均線；可改用事件後低點、量縮與論題確認。
本規則不預設買進或賣出，也不因技術面空頭排列而跳過事件與估值判讀。
"""


def _finite(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if isfinite(value) else None


def _session_date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _post_event_facts(ordered, index):
    """只使用已知收盤；事件當日不算事件後，缺值不由即時價冒充。"""
    facts = {}
    latest = ordered[-1].get("close")
    if latest is not None:
        facts["latest_close"] = latest
    closes = [row["close"] for row in ordered[index + 1:] if "close" in row]
    if closes:
        facts["post_event_min_close"] = min(closes)
        low = ordered[index].get("low")
        if low is not None:
            facts["event_low_broken"] = min(closes) < low
    return facts


def event_gap_context(code, context, config):
    if getattr(config, "event_gap_decision_enabled", False) is not True:
        return None
    return detect_event_gap(code, context, config)


def detect_event_gap(code, context, config):
    """純偵測，不看決策開關：新聞檢索與結論護欄共用同一套門檻與回看場次。"""
    if not (is_us_stock_code(code) or get_suffix_market(code) == "tw"):
        return None
    threshold = getattr(config, "event_gap_threshold_pct", 12.0)
    lookback = getattr(config, "event_gap_lookback_sessions", 5)
    today = context.get("today") or {}
    current_date = _session_date(today.get("date")) or _session_date(context.get("date"))
    sessions = {}
    # 上下文先提供缺值補充；共用的原始日線最後寫入，同日實際收盤資料優先。
    sources = [(False, context.get("yesterday") or {}), (False, {**today, "date": current_date})]
    sources.extend((True, row) for row in (context.get("event_gap_daily_bars") or []))
    for actual, row in sources:
        if not isinstance(row, dict):
            continue
        session_date = _session_date(row.get("date"))
        if session_date is None or (current_date is not None and session_date > current_date):
            continue
        values = sessions.setdefault(session_date, {"date": session_date.isoformat()})
        if actual and _finite(row.get("close")) is not None and _finite(row.get("pct_chg")) is None:
            # 原始收盤已有值時，缺失幅度由相鄰收盤計算，不沿用同日估算列的幅度。
            values.pop("pct_chg", None)
        for field in ("close", "pct_chg", "low"):
            value = _finite(row.get(field))
            if value is not None:
                values[field] = value
    ordered = [sessions[key] for key in sorted(sessions)]
    current_change = None
    for index in range(len(ordered) - 1, max(-1, len(ordered) - lookback - 1), -1):
        row = ordered[index]
        change = row.get("pct_chg")
        if change is None and index > 0:
            previous = ordered[index - 1].get("close")
            close = row.get("close")
            if previous is not None and previous > 0 and close is not None:
                change = (close / previous - 1) * 100
        if change is not None and abs(change) >= threshold:
            return {"triggered": True, "event_date": row["date"], "change_pct": change,
                    "event_low": row.get("low"), "sessions_since_event": len(ordered) - 1 - index,
                    "threshold_pct": threshold, **_post_event_facts(ordered, index)}
        if index == len(ordered) - 1:
            current_change = change
    # 有當日日線可判定時不拿即時價推翻收盤；歷史不足才沿用原有當日判定。
    if ordered and current_change is not None:
        return None
    realtime = context.get("realtime") or context.get("realtime_quote") or {}
    change = _finite(realtime.get("change_pct"))
    if change is None:
        change = _finite(today.get("pct_chg"))
    if change is None or abs(change) < threshold:
        return None
    low = _finite(today.get("low"))
    if low is None:
        low = _finite(realtime.get("low"))
    event = {"triggered": True, "event_date": current_date.isoformat() if current_date else None,
             "change_pct": change, "event_low": low, "sessions_since_event": 0, "threshold_pct": threshold}
    close = _finite(today.get("close"))
    if close is not None:
        event["latest_close"] = close
    return event


def event_gap_prompt(event):
    if not event or not event.get("triggered"):
        return ""
    facts = ["事件日期：" + str(event.get("event_date") or "未提供")]
    change = _finite(event.get("change_pct"))
    if change is not None:
        facts.append(f"事件日漲跌幅：{change:g}%")
    low = _finite(event.get("event_low"))
    if low is not None:
        facts.append(f"事件日低點：{low:g}")
    if event.get("sessions_since_event") is not None:
        facts.append(f"距事件日交易場次：{event['sessions_since_event']}")
    for field, label in (("post_event_min_close", "事件後最低收盤"), ("latest_close", "最新收盤")):
        value = _finite(event.get(field))
        if value is not None:
            facts.append(f"{label}：{value:g}")
    if low is not None and isinstance(event.get("event_low_broken"), bool):
        value = "是" if event["event_low_broken"] else "否"
        facts.append(f"已跌破事件日低點：{value}（以已知事件後收盤判定）")
    return EVENT_GAP_RULES + "\n事件事實（來源：日線；不足時僅當日報價）：\n" + "\n".join(facts) + "\n"


def apply_event_gap_guard(result, event, report_language):
    """只讀結構化新聞證據，最後覆蓋買賣動作並隨結果保存。"""
    if not event:
        return
    from src.report_language import localize_confidence_level, localize_operation_advice, normalize_report_language

    report_language = normalize_report_language(report_language)

    event = dict(event)
    event["news_evidence_present"] = result.news_evidence_present
    event["blocked_without_news"] = not result.news_evidence_present
    if not result.news_evidence_present:
        messages = {
            "zh-TW": "重大波動但沒有新聞，不下買賣結論",
            "zh": "重大波动但没有新闻，不下买卖结论",
            "en": "Major price move without news evidence; no buy or sell conclusion.",
            "ko": "큰 주가 변동에 대한 뉴스 근거가 없어 매수·매도 결론을 내리지 않습니다.",
        }
        reason = messages[report_language]
        event["reason"] = reason
        result.decision_type = "hold"
        result.action = "watch"
        result.action_label = None
        result.confidence_level = localize_confidence_level("低", report_language)
        result.operation_advice = localize_operation_advice("观望", report_language)
        result.guardrail_reason = reason
        result.analysis_summary = reason
        result.risk_warning = reason
        result.buy_reason = reason
        dashboard = result.dashboard if isinstance(result.dashboard, dict) else {}
        dashboard["core_conclusion"] = {
            "one_sentence": reason, "signal_type": result.operation_advice,
            "position_advice": {"no_position": reason, "has_position": reason},
        }
        # 清掉模型原先的可執行買賣價位，不能在觀望報告裡殘留交易指令。
        dashboard.pop("battle_plan", None)
        phase = dashboard.get("phase_decision")
        if isinstance(phase, dict):
            phase["immediate_action"] = reason
            phase["confidence_reason"] = reason
            phase["watch_conditions"] = [reason]
            # 不下買賣結論時，模型原先寫的進出場條件也是交易指令，不能殘留。
            phase["entry_conditions"] = []
            phase["exit_triggers"] = []
        result.dashboard = dashboard
    if not isinstance(result.dashboard, dict):
        result.dashboard = {}
    result.dashboard["event_gap"] = event
