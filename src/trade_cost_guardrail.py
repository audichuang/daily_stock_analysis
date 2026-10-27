# -*- coding: utf-8 -*-
"""台股價位的交易成本檢核：扣掉手續費、證交稅與滑價後，這組狙擊點位還划不划算。

為什麼要有這一層：LLM 給的理想買點／停損／目標價只看技術位置，不知道台股一趟來回
要付多少。實測 2026-07 ~ 09 的 253 份台股報告，目標價距買點中位 +3.69%、停損 -2.14%，
帳面風報比 1.69；扣掉約 0.88% 的來回成本後淨風報比只剩約 0.93——照價位掛單進出，
含成本 -8.50%、不計成本 -0.88%（`scripts/backtest_daily_report_levels.py`）。
上游 prompt 為 A 股寫的，A 股來回成本只有台股的幾分之一，所以這個缺口在台股才會放大。

這一層只做**確定性計算**，不改 LLM 給的價位：

1. 每份台股報告都在 ``dashboard.battle_plan.cost_check`` 寫一份檢核結果（買點掛單的人
   也看得到，不只是「買入」評級）。
2. 買入結論缺任一必要價位、價位順序無效或淨風報比低於門檻時，降級為觀望並揭露原因。

成本費率唯一真源是 ``src/utils/tw_trade_costs.py``（研究腳本共用同一份）。
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from src.report_language import localize_operation_advice, normalize_report_language
from src.schemas.decision_action import build_action_fields
from src.schemas.decision_scale import (
    action_for_score, extract_decision_guardrail_reason, record_guardrail_score_adjustment,
)
from src.services.market_symbol_utils import get_suffix_market
from src.utils.sniper_points import extract_sniper_points
from src.utils.tw_trade_costs import (
    DEFAULT_SLIPPAGE_RATE,
    per_share_cost_multipliers,
    tw_sell_tax_rate,
)

logger = logging.getLogger(__name__)

DEFAULT_MIN_NET_RR = 1.0
_BUY_ACTIONS = {"buy", "add"}
_GUARDRAIL_SENTIMENT_CAP = 59


def is_tw_code(code: Any) -> bool:
    # 後綴是否合法以 market_symbol_utils 為準（src/AGENTS.md），不另寫 endswith
    return get_suffix_market(str(code or "").strip()) == "tw"


def evaluate_levels(
    code: Any,
    *,
    ideal_buy: Optional[float],
    stop_loss: Optional[float],
    take_profit: Optional[float],
    min_net_rr: float = DEFAULT_MIN_NET_RR,
    fee_discount: float = 1.0,
    slippage_rate: float = DEFAULT_SLIPPAGE_RATE,
    atr_pct: Optional[float] = None,
    sale_date: Optional[date] = None,
) -> Dict[str, Any]:
    """回傳一份 cost_check。``status`` 區分「檢核過」與「沒辦法檢核」，缺這份資料
    跟「檢核沒過」是兩件事，讀的人要分得出來。

    ``sale_date`` 是假設的賣出日，決定證交稅率（債券 ETF 停徵有期限）；未給用今天。"""
    base: Dict[str, Any] = {"min_net_rr": min_net_rr}
    if not is_tw_code(code):
        return {**base, "status": "unsupported_market", "passed": None}
    levels = {"ideal_buy": ideal_buy, "stop_loss": stop_loss, "take_profit": take_profit}
    missing = [key for key, value in levels.items() if value is None or value <= 0]
    if missing or not (stop_loss < ideal_buy < take_profit):
        return {**base, "status": "levels_missing", "passed": False, "missing_fields": missing}

    stock_id = str(code).split(".")[0]
    buy_mult, sell_mult = per_share_cost_multipliers(
        tax_rate=tw_sell_tax_rate(stock_id, sale_date or date.today()),
        fee_discount=fee_discount, slippage_rate=slippage_rate)
    paid = ideal_buy * buy_mult
    net_up = take_profit * sell_mult / paid - 1
    net_down = 1 - stop_loss * sell_mult / paid
    gross_rr = (take_profit - ideal_buy) / (ideal_buy - stop_loss)
    net_rr = net_up / net_down if net_down > 0 else None
    passed = net_up > 0 and (net_rr is None or net_rr >= min_net_rr)
    return {
        **base,
        "status": "ok",
        "passed": bool(passed),
        "round_trip_cost_pct": round((1 - sell_mult / buy_mult) * 100, 3),
        "gross_upside_pct": round((take_profit / ideal_buy - 1) * 100, 2),
        "gross_downside_pct": round((1 - stop_loss / ideal_buy) * 100, 2),
        "net_upside_pct": round(net_up * 100, 2),
        "net_downside_pct": round(net_down * 100, 2),
        "gross_rr": round(gross_rr, 2),
        "net_rr": round(net_rr, 2) if net_rr is not None else None,
        # 只提示、不降級：停損比一天正常波動還近，多半會被雜訊掃掉（實測 61 次停損有 89%
        # 落在 1×ATR14 以內）。它是第二個可調參數，沒有樣本外資料前不拿來改結論。
        "atr14_pct": atr_pct,
        "stop_within_atr": (atr_pct is not None and atr_pct > 0
                            and (1 - stop_loss / ideal_buy) * 100 < atr_pct),
    }


def _is_buy(result: Any) -> bool:
    action = str(getattr(result, "action", "") or "").strip().lower()
    decision_type = str(getattr(result, "decision_type", "") or "").strip().lower()
    # 持有但分數落在買入區間時，也要先檢核成本，避免後續分數對齊繞過護欄；sell 不觸發。
    return (action in _BUY_ACTIONS or decision_type == "buy"
            or (decision_type == "hold"
                and action_for_score(getattr(result, "sentiment_score", None)) == "buy"))


def _wording(language: str, check: Dict[str, Any]) -> Dict[str, str]:
    if check.get("status") == "levels_missing":
        labels, invalid, suffix, no_position, has_position = {
            "zh-TW": ({"ideal_buy": "缺進場價", "stop_loss": "缺停損價", "take_profit": "缺目標價"},
                      "進場、停損與目標價順序無效", "無法檢查報酬風險比",
                      "空手先不進場；待價位補齊並通過檢核後再評估。", "持有者依既有風控計畫處理，不因這份報告加碼。"),
            "zh": ({"ideal_buy": "缺进场价", "stop_loss": "缺止损价", "take_profit": "缺目标价"},
                   "进场、止损与目标价顺序无效", "无法检查风险收益比",
                   "空仓先不进场；待价位补齐并通过检查后再评估。", "持仓者按既有风控计划处理，不因这份报告加仓。"),
            "en": ({"ideal_buy": "missing entry price", "stop_loss": "missing stop-loss price",
                    "take_profit": "missing target price"}, "invalid entry, stop and target order",
                   "cannot check reward/risk", "Do not enter until the levels are complete and checked.",
                   "Follow the existing risk plan; do not add on this report."),
            "ko": ({"ideal_buy": "진입가 누락", "stop_loss": "손절가 누락", "take_profit": "목표가 누락"},
                   "진입가, 손절가, 목표가 순서 오류", "손익비를 확인할 수 없습니다",
                   "가격이 완성되고 검증될 때까지 진입하지 마세요.", "기존 위험 관리 계획을 따르고 추가 매수하지 마세요."),
        }[language]
        missing = "／".join(labels[key] for key in check.get("missing_fields", []))
        return {"reason": f"{missing or invalid}，{suffix}",
                "no_position": no_position, "has_position": has_position}
    rr = check.get("net_rr")
    up, down = check.get("net_upside_pct"), check.get("net_downside_pct")
    cost = check.get("round_trip_cost_pct")
    if language == "zh-TW":
        reason = (f"扣掉來回交易成本約 {cost}% 後，目標價淨賺 {up}%、停損淨賠 {down}%，"
                  f"淨風報比 {rr} 低於 {check['min_net_rr']}，這組價位不划算")
        return {"reason": reason,
                "no_position": "空手先不進場；等回檔到更低的買點，或目標價有理由上修後再評估。",
                "has_position": "持有者照原停損控管，不因這份報告加碼。"}
    if language == "zh":
        reason = (f"扣掉来回交易成本约 {cost}% 后，目标价净赚 {up}%、止损净亏 {down}%，"
                  f"净风报比 {rr} 低于 {check['min_net_rr']}，这组价位不划算")
        return {"reason": reason,
                "no_position": "空仓先不进场；等回调到更低的买点，或目标价有理由上修后再评估。",
                "has_position": "持仓者按原止损控制风险，不因这份报告加仓。"}
    if language == "ko":
        reason = (f"왕복 거래비용 약 {cost}%를 빼면 목표가 순수익 {up}%, 손절 순손실 {down}%로 "
                  f"순 손익비 {rr}가 기준 {check['min_net_rr']}보다 낮아 이 가격대는 수지가 맞지 않습니다")
        return {"reason": reason,
                "no_position": "신규 진입하지 말고 더 낮은 매수가나 근거 있는 목표가 상향을 기다리세요.",
                "has_position": "기존 손절선을 유지하고 이 리포트를 근거로 비중을 늘리지 마세요."}
    reason = (f"After a ~{cost}% round-trip cost the target nets {up}% and the stop loses {down}%; "
              f"net reward/risk {rr} is below {check['min_net_rr']}, so these levels do not pay")
    return {"reason": reason,
            "no_position": "Do not enter; wait for a lower entry or a justified higher target.",
            "has_position": "Keep the existing stop; do not add on this report."}


def apply_trade_cost_guardrail(
    result: Any,
    *,
    code: Any,
    report_language: str = "zh",
    min_net_rr: float = DEFAULT_MIN_NET_RR,
    fee_discount: float = 1.0,
    slippage_rate: float = DEFAULT_SLIPPAGE_RATE,
    atr_pct: Optional[float] = None,
) -> List[str]:
    """寫入 cost_check，買入缺必要價位或扣成本後不划算都降為觀望。回傳調整代碼。"""
    if result is None or not is_tw_code(code):
        return []
    dashboard = getattr(result, "dashboard", None)
    if not isinstance(dashboard, dict):
        dashboard = {}
        result.dashboard = dashboard
    battle_plan = dashboard.get("battle_plan")
    if not isinstance(battle_plan, dict):
        battle_plan = {}
        dashboard["battle_plan"] = battle_plan

    # 與寫入 analysis_history 的解析同一支（storage 也走 extract_sniper_points），
    # 報告、DB 與回測看到的是同一組數字
    points = extract_sniper_points(result)
    check = evaluate_levels(
        code,
        ideal_buy=points.get("ideal_buy"),
        stop_loss=points.get("stop_loss"),
        take_profit=points.get("take_profit"),
        min_net_rr=min_net_rr,
        fee_discount=fee_discount,
        slippage_rate=slippage_rate,
        atr_pct=atr_pct,
    )
    battle_plan["cost_check"] = check
    if check.get("passed") is not False or not _is_buy(result):
        return []
    if check.get("status") == "levels_missing":
        fields = build_action_fields(
            operation_advice=getattr(result, "operation_advice", None),
            explicit_action=getattr(result, "action", None),
            sentiment_score=getattr(result, "sentiment_score", None),
            guardrail_reason=extract_decision_guardrail_reason({"dashboard": dashboard}),
            align_with_score=True,
        )
        if fields.get("action") not in _BUY_ACTIONS and getattr(result, "decision_type", None) != "buy":
            # 前面的護欄已保留觀望，或結構化動作是減碼，不因缺價覆寫非買入決策。
            return []

    language = normalize_report_language(report_language or getattr(result, "report_language", "zh"))
    words = _wording(language, check)
    raw_score = getattr(result, "sentiment_score", None)
    raw_decision_type = str(getattr(result, "decision_type", "") or "").lower() or None
    result.decision_type = "hold"
    result.operation_advice = localize_operation_advice("观望", language)
    try:
        result.sentiment_score = min(int(getattr(result, "sentiment_score", 50)), _GUARDRAIL_SENTIMENT_CAP)
    except (TypeError, ValueError):
        result.sentiment_score = 50
    # 將舊動作改成觀望，避免原分數提升的買入動作殘留。
    result.action = "watch"
    result.action_label = None
    dashboard["sentiment_score"] = result.sentiment_score
    # 護欄前的原始分數／動作：落庫給 scripts/shadow_buy_eval.py 回推 LLM 原判
    record_guardrail_score_adjustment(
        dashboard,
        raw_score=raw_score,
        adjusted_score=result.sentiment_score,
        final_action="hold",
        reason=words["reason"],
        raw_decision_type=raw_decision_type,
    )
    dashboard["operation_advice"] = result.operation_advice
    dashboard["decision_type"] = "hold"
    core = dashboard.get("core_conclusion")
    if isinstance(core, dict):
        core["one_sentence"] = f"{result.operation_advice}：{words['reason']}" \
            if language in ("zh", "zh-TW") else f"{result.operation_advice}: {words['reason']}"
        core["position_advice"] = {"no_position": words["no_position"],
                                   "has_position": words["has_position"]}
    sep = "；" if language in ("zh", "zh-TW") else "; "
    warning = str(getattr(result, "risk_warning", "") or "")
    if words["reason"] not in warning:
        result.risk_warning = f"{warning}{sep}{words['reason']}" if warning else words["reason"]
    logger.info("[trade_cost_guardrail] buy downgraded for %s: net_rr=%s", code, check.get("net_rr"))
    return ["trade_cost_buy_softened"]


def format_cost_check(check: Any, language: Any = "zh") -> Optional[str]:
    """報告裡的一行成本檢核；沒有可檢核的價位就不印（不印 ≠ 通過）。"""
    if not isinstance(check, dict) or check.get("status") != "ok":
        return None
    lang = normalize_report_language(language)
    ok = bool(check.get("passed"))
    rr = check.get("net_rr")
    rr_text = "—" if rr is None else f"{rr}"
    atr_note = _atr_note(check, lang)
    if lang == "zh-TW":
        verdict = "划算" if ok else f"⚠️ 不划算（低於 {check['min_net_rr']}）"
        return (f"💸 成本檢核：來回成本約 {check['round_trip_cost_pct']}%｜扣成本後 目標 +{check['net_upside_pct']}%"
                f" / 停損 −{check['net_downside_pct']}%｜淨風報比 {rr_text}（帳面 {check['gross_rr']}）{verdict}" + atr_note)
    if lang == "zh":
        verdict = "划算" if ok else f"⚠️ 不划算（低于 {check['min_net_rr']}）"
        return (f"💸 成本检核：来回成本约 {check['round_trip_cost_pct']}%｜扣成本后 目标 +{check['net_upside_pct']}%"
                f" / 止损 −{check['net_downside_pct']}%｜净风报比 {rr_text}（账面 {check['gross_rr']}）{verdict}" + atr_note)
    if lang == "ko":
        verdict = "수지 맞음" if ok else f"⚠️ 수지 안 맞음 (기준 {check['min_net_rr']} 미만)"
        return (f"💸 비용 점검: 왕복 비용 약 {check['round_trip_cost_pct']}% | 비용 차감 후 목표 +{check['net_upside_pct']}%"
                f" / 손절 −{check['net_downside_pct']}% | 순 손익비 {rr_text} (명목 {check['gross_rr']}) {verdict}" + atr_note)
    verdict = "worth it" if ok else f"⚠️ not worth it (below {check['min_net_rr']})"
    return (f"💸 Cost check: ~{check['round_trip_cost_pct']}% round trip | net target +{check['net_upside_pct']}%"
            f" / stop −{check['net_downside_pct']}% | net R/R {rr_text} (gross {check['gross_rr']}) {verdict}" + atr_note)


def _atr_note(check: Dict[str, Any], lang: str) -> str:
    if not check.get("stop_within_atr"):
        return ""
    dist, atr = check.get("gross_downside_pct"), check.get("atr14_pct")
    if lang == "zh-TW":
        return f"｜⚠️ 停損只離買點 {dist}%，比一天正常波動（ATR14 {atr}%）還近，容易被洗掉"
    if lang == "zh":
        return f"｜⚠️ 止损只离买点 {dist}%，比一天正常波动（ATR14 {atr}%）还近，容易被洗掉"
    if lang == "ko":
        return f" | ⚠️ 손절이 매수가에서 {dist}%로 하루 정상 변동폭(ATR14 {atr}%)보다 가까워 쉽게 털립니다"
    return f" | ⚠️ stop is only {dist}% below entry, inside one day's normal range (ATR14 {atr}%)"
