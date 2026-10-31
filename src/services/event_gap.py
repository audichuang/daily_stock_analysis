"""重大波動的事件判讀與無新聞護欄；開關關閉時完全不改原結果。"""
from math import isfinite

from data_provider.us_index_mapping import is_us_stock_code
from src.services.market_symbol_utils import get_suffix_market


EVENT_GAP_RULES = """

### 重大波動事件判讀（優先於原有均線準則與評分表）
本次為事件驅動情境：覆蓋「只做多頭排列、空頭排列堅決不碰」與「站回均線才評估」的要求。
1. 先依新聞證據判斷事件性質，說明它是否打壞投資論題；沒有證據不得猜測原因。
2. 再看事件後下修的獲利預估與估值；預期本益比若尚未反映事件，明確揭露限制。
3. 再看止跌：明確列出需幾個交易日不破事件日低點、成交量是否縮減；尚未觀察到就列為待確認。
買進可表達為「分批試單」，但必須列明失效條件（事件日低點、投資論題或估值假設失效）。
重新評估條件不得使用含事件日之前價格的均線；可改用事件後低點、量縮與論題確認。
本規則不預設買進或賣出，也不因技術面空頭排列而跳過事件與估值判讀。
"""


def event_gap_context(code, context, config):
    if getattr(config, "event_gap_decision_enabled", False) is not True:
        return None
    if not (is_us_stock_code(code) or get_suffix_market(code) == "tw"):
        return None
    realtime = context.get("realtime") or context.get("realtime_quote") or {}
    change = realtime.get("change_pct")
    if change is None:
        change = context.get("today", {}).get("pct_chg")
    try:
        change = float(change)
    except (TypeError, ValueError):
        return None
    threshold = getattr(config, "event_gap_threshold_pct", 12.0)
    if not isfinite(change) or abs(change) < threshold:
        return None
    return {"triggered": True, "change_pct": change, "threshold_pct": threshold}


def event_gap_prompt(event):
    return EVENT_GAP_RULES if event and event.get("triggered") else ""


def apply_event_gap_guard(result, event, report_language):
    """只讀結構化新聞證據，最後覆蓋買賣動作並隨結果保存。"""
    if not event:
        return
    from src.report_language import localize_confidence_level, localize_operation_advice

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
        result.dashboard = dashboard
    if not isinstance(result.dashboard, dict):
        result.dashboard = {}
    result.dashboard["event_gap"] = event
