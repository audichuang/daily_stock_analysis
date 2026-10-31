"""事件展望：提示詞契約、依證據收斂 LLM 輸出、讀取端投影。只當證據，不改評分。"""
import logging
from typing import Any, Dict, Optional

from src.report_language import normalize_report_language
from src.schemas.report_schema import EventOutlook

logger = logging.getLogger(__name__)

_SKELETON = (
    '{"event", "event_type": "earnings|investor_conference|other", "event_date": "YYYY-MM-DD|null", '
    '"consensus": {"eps", "revenue", "analysts"}, "track_record", "revision_trend", '
    '"expectation": "beat|inline|miss|insufficient_data", "confidence": "high|medium|low", "reasoning", '
    '"scenarios": [{"case": "beat|inline|miss", "expected_reaction", "action_if_holding", "action_if_flat"}], '
    '"news_impact", "verify_after"}'
)

_TEXT = {
    "zh-TW": {
        "title": "事件展望（輸出 dashboard.event_outlook）",
        "body": (
            "只告訴使用者有事件沒有意義，要回答「那然後咧」。請在 dashboard 加上 `event_outlook`，結構：{skeleton}\n"
            "- 未來 30 天內沒有財報、法說或其他可能明顯影響股價的事件時，整個 `event_outlook` 填 null，不要硬湊。\n"
            "- `event_type` 財報填 earnings、法說會填 investor_conference、其他事件（新品、訴訟、監管等）填 other。\n"
            "- 財報與法說的 `event_date` 只能用上方「下次財報／法說日」的日期，日期未定就填 null，不可推算。\n"
            "- `expectation` 判斷這次實際 EPS 相對法人預估：beat 超預期、inline 符合（差距約 ±2% 內）、miss 不及；"
            "要依預估、近四季實績、修正方向與新聞自己下判斷，並在 `reasoning` 寫出理由。別把歷史上常超預期直接當結論。\n"
            "- 沒有法人預估時，`expectation` 必須是 insufficient_data、`consensus` 填 null，不可猜數字；財報以外的事件同樣如此。\n"
            "- `scenarios` 列出 beat、inline、miss 三種情境各自的預期反應、持有者與空手者怎麼做；沒有預估時仍要寫。\n"
            "- `news_impact` 回答「近期這些新聞對接下來有什麼影響」，不要只重述新聞；沒有相關新聞就直接說沒有。\n"
            "- `verify_after` 寫事件後要看什麼來驗證這次判斷。\n"
            "- 這些內容只當證據，不得據此調整 sentiment_score、action 或 decision_type。"
        ),
        "have": "資料狀態：上方美股補充證據有法人預估（estimates）。",
        "missing": "資料狀態：這檔沒有可靠的法人預估，缺資料（台股目前沒有這項來源）；expectation 必須是 insufficient_data。",
    },
    "zh": {
        "title": "事件展望（输出 dashboard.event_outlook）",
        "body": (
            "只告诉用户有事件没有意义，要回答“那然后呢”。请在 dashboard 加上 `event_outlook`，结构：{skeleton}\n"
            "- 未来 30 天内没有财报、法说或其他可能明显影响股价的事件时，整个 `event_outlook` 填 null，不要硬凑。\n"
            "- `event_type` 财报填 earnings、法说会填 investor_conference、其他事件（新品、诉讼、监管等）填 other。\n"
            "- 财报与法说的 `event_date` 只能用上方“下次财报日”的日期，日期未定就填 null，不可推算。\n"
            "- `expectation` 判断这次实际 EPS 相对机构预估：beat 超预期、inline 符合（差距约 ±2% 内）、miss 不及；"
            "要依预估、近四季实绩、修正方向与新闻自己下判断，并在 `reasoning` 写出理由。别把历史上常超预期直接当结论。\n"
            "- 没有机构预估时，`expectation` 必须是 insufficient_data、`consensus` 填 null，不可猜数字；财报以外的事件同样如此。\n"
            "- `scenarios` 列出 beat、inline、miss 三种情境各自的预期反应、持有者与空仓者怎么做；没有预估时仍要写。\n"
            "- `news_impact` 回答“近期这些新闻对接下来有什么影响”，不要只复述新闻；没有相关新闻就直接说没有。\n"
            "- `verify_after` 写事件后要看什么来验证这次判断。\n"
            "- 这些内容只当证据，不得据此调整 sentiment_score、action 或 decision_type。"
        ),
        "have": "数据状态：上方美股补充证据有机构预估（estimates）。",
        "missing": "数据状态：这只股票没有可靠的机构预估，缺数据；expectation 必须是 insufficient_data。",
    },
    "en": {
        "title": "Event outlook (output dashboard.event_outlook)",
        "body": (
            "Merely saying an event exists is useless; answer \"so what?\". Add `event_outlook` to dashboard with this shape: {skeleton}\n"
            "- If no earnings, investor conference or other likely price-moving event falls within the next 30 days, set the whole `event_outlook` to null.\n"
            "- `event_type`: earnings, investor_conference, or other (product launch, litigation, regulation, etc.).\n"
            "- For earnings and conferences, `event_date` must come from the next-earnings evidence above; if undetermined use null, never infer it.\n"
            "- `expectation` is your call on actual EPS versus the analyst estimate: beat, inline (within roughly +/-2%), or miss. "
            "Judge from estimates, the last four quarters, revision direction and news, and explain in `reasoning`. A history of beats alone is not a conclusion.\n"
            "- Without analyst estimates, `expectation` must be insufficient_data and `consensus` null; never guess numbers. The same applies to non-earnings events.\n"
            "- `scenarios`: for beat, inline and miss, give the expected reaction and what holders and non-holders should do, even without estimates.\n"
            "- `news_impact` answers what recent news means for what comes next, not a recap; say so plainly if nothing is relevant.\n"
            "- `verify_after`: what to check after the event to test this call.\n"
            "- This is evidence only; do not change sentiment_score, action or decision_type because of it."
        ),
        "have": "Data status: analyst estimates (estimates) are present in the US evidence above.",
        "missing": "Data status: no reliable analyst estimates for this stock; expectation must be insufficient_data.",
    },
    "ko": {
        "title": "이벤트 전망 (dashboard.event_outlook 출력)",
        "body": (
            "이벤트가 있다는 사실만으로는 의미가 없습니다. \"그래서 어떻게 되는가\"에 답하세요. dashboard에 `event_outlook`을 추가하세요. 구조: {skeleton}\n"
            "- 향후 30일 내 실적 발표, 기업설명회 또는 주가에 뚜렷한 영향을 줄 이벤트가 없으면 `event_outlook` 전체를 null로 두세요.\n"
            "- `event_type`: earnings, investor_conference, other(신제품, 소송, 규제 등).\n"
            "- 실적과 설명회의 `event_date`는 위의 다음 실적 발표일 근거만 사용하고, 미정이면 null로 두며 추정하지 마세요.\n"
            "- `expectation`은 실제 EPS와 애널리스트 추정치 비교 판단입니다: beat, inline(약 ±2% 이내), miss. "
            "추정치, 최근 4개 분기 실적, 수정 방향, 뉴스로 직접 판단하고 `reasoning`에 이유를 쓰세요. 과거에 자주 상회했다는 사실만으로 결론 내리지 마세요.\n"
            "- 애널리스트 추정치가 없으면 `expectation`은 반드시 insufficient_data, `consensus`는 null이며 숫자를 추측하지 마세요. 실적 외 이벤트도 동일합니다.\n"
            "- `scenarios`: beat, inline, miss 각각의 예상 반응과 보유자, 미보유자의 대응을 쓰세요. 추정치가 없어도 작성합니다.\n"
            "- `news_impact`: 최근 뉴스가 앞으로 미칠 영향을 답하세요. 단순 요약은 안 되며 관련 뉴스가 없으면 없다고 쓰세요.\n"
            "- `verify_after`: 이벤트 후 이 판단을 검증할 항목을 쓰세요.\n"
            "- 근거로만 사용하며 sentiment_score, action, decision_type을 변경하지 마세요."
        ),
        "have": "데이터 상태: 위 미국 주식 보충 근거에 애널리스트 추정치(estimates)가 있습니다.",
        "missing": "데이터 상태: 이 종목은 신뢰할 수 있는 애널리스트 추정치가 없습니다. expectation은 반드시 insufficient_data입니다.",
    },
}


def _estimates(fundamental_context: Any) -> Dict[str, Any]:
    if not isinstance(fundamental_context, dict):
        return {}
    evidence = fundamental_context.get("us_evidence")
    estimates = evidence.get("estimates") if isinstance(evidence, dict) else None
    return estimates if isinstance(estimates, dict) else {}


def _evidence_consensus(estimates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    eps, revenue = estimates.get("eps") or {}, estimates.get("revenue") or {}
    if eps.get("avg") is None and revenue.get("avg") is None:
        return None
    return {"eps": eps.get("avg"), "revenue": revenue.get("avg"),
            "analysts": eps.get("analysts", revenue.get("analysts")), "currency": estimates.get("currency")}


def event_outlook_prompt(fundamental_context: Any, report_language: str = "zh-TW") -> str:
    language = normalize_report_language(report_language)
    text = _TEXT.get(language, _TEXT["zh"])
    status = text["have"] if _evidence_consensus(_estimates(fundamental_context)) else text["missing"]
    return f"\n### {text['title']}\n{status}\n{text['body'].replace('{skeleton}', _SKELETON)}\n"


def _parse(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    try:
        outlook = EventOutlook.model_validate(value)
    except ValueError as exc:
        logger.warning("event_outlook 結構不合法，視為沒有: %s", type(exc).__name__)
        return None
    return outlook.model_dump() if outlook.event else None


def normalize_event_outlook(value: Any, fundamental_context: Any, next_earnings: Any) -> Optional[Dict[str, Any]]:
    """數字與日期以實際餵給模型的證據為準；語意判斷仍是模型給的值，這裡不解析文字。"""
    outlook = _parse(value)
    if outlook is None:
        return None
    event_type = outlook["event_type"] or "other"
    outlook["event_type"] = event_type
    consensus = _evidence_consensus(_estimates(fundamental_context)) if event_type == "earnings" else None
    outlook["consensus"] = consensus
    if consensus is None or outlook["expectation"] is None:
        outlook["expectation"] = "insufficient_data"
    if outlook["expectation"] == "insufficient_data":
        outlook["confidence"] = "low"
    if event_type != "other":
        known = next_earnings if isinstance(next_earnings, dict) and next_earnings.get("type") == event_type else {}
        outlook["event_date"] = known.get("date")
    return outlook


def apply_event_outlook_guard(result: Any, fundamental_context: Any, next_earnings: Any, *, enabled: bool) -> None:
    """掛在歷史寫入前，傳統與 agent 路徑共用；只動 event_outlook，不碰評分與動作。"""
    dashboard = getattr(result, "dashboard", None)
    if not isinstance(dashboard, dict):
        return
    if not enabled:
        dashboard.pop("event_outlook", None)
        return
    dashboard["event_outlook"] = normalize_event_outlook(dashboard.get("event_outlook"), fundamental_context, next_earnings)


def extract_event_outlook(raw_result: Any) -> Optional[Dict[str, Any]]:
    """讀取端：舊報告或壞資料回 None，不讓單筆資料拖垮報告 API。"""
    dashboard = raw_result.get("dashboard") if isinstance(raw_result, dict) else None
    return _parse(dashboard.get("event_outlook")) if isinstance(dashboard, dict) else None
