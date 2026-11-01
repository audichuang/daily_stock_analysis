"""財報 AI 導讀：LLM 只挑重點、寫白話說明，數字一律由程式填入。

契約（語意交給 LLM，程式只驗結構，不從文字猜意思）：
- `metric_key`＋`period` 必須是這份回應實際有值的欄位，不是就丟掉那一條。
- 文字裡的數字只能寫佔位符 `{{gross_margin@2026Q2:yoy}}`，由程式換成回應裡的值；
  佔位符對不上、或殘留佔位符以外的阿拉伯數字，就丟掉那一條——模型編不出數字。
- 每份財報期間只生成一次：鍵是（代號、最新期間、來源、提示詞版本、季度數字雜湊），落在應用庫。
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
import unicodedata
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

PROMPT_VERSION = "v2"
MAX_HIGHLIGHTS = 6
_FAILURE_TTL_SECONDS = 600
_MONTHLY_KEY = "monthly_revenue"
_IMPORTANCE = {"high", "medium", "low"}
_TEXT_MAX = 400

_locks: Dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
_failures: Dict[str, float] = {}
# 寫快取失敗時，已付費的結果先留在程序內；否則下次 GET 又是 missing，客戶端會再付一次 LLM。
_UNSAVED_TTL_SECONDS = 3600
_unsaved: Dict[str, tuple] = {}

_TOKEN_RE = re.compile(r"\{\{\s*([a-z_]+)@([0-9A-Za-z-]+)(?::(yoy|qoq|mom))?\s*\}\}", re.ASCII)
# 文字裡合法的非財務數字：期間標籤、申報表名、時間長度與序數。其餘阿拉伯數字一律視為模型自己寫的財務數字。
_ALLOWED_DIGITS_RE = re.compile(
    r"\d{4}\s*(?:年\s*)?(?:Q[1-4]|第?[一二三四1-4]季)|\bQ[1-4]\b|\b10-[QK]\b|\b20-F\b|\d{4}\s*年(?:\s*\d{1,2}\s*月)?|"
    r"\d{4}-\d{2}|\d{1,2}\s*月|\d+\s*(?:個月|個季度|季|年|天|日)", re.ASCII)
# 中文數字接財務單位才算金額或比率；「連續兩季」「第二季」「八季」沒有財務單位，不受影響。
_CN_NUM = "零〇一二兩三四五六七八九十百千萬億兆壹貳參肆伍陸柒捌玖拾佰仟"
_CN_FINANCIAL_RE = re.compile(
    rf"[{_CN_NUM}]+(?:(?:新?台幣|美金|美元|人民幣|日圓|塊錢|元|倍|%)|個?百分點|成(?!不變|長|本|功|為|交|立|員|分|績))"
    rf"|百分之[{_CN_NUM}]+"
    rf"|[{_CN_NUM}]+分之[{_CN_NUM}]+"
    rf"|[{_CN_NUM}]*[{_CN_NUM[:-3]}][萬億兆](?![不別])"
)
_EN_FINANCIAL_RE = re.compile(r"\b(?:hundred|thousand|million|billion|trillion|percent)\b", re.IGNORECASE | re.ASCII)
# 教學比喻不是公司數字：「每賣一百元」「每一塊錢」。「每股」後面的金額不算比喻。
_TEACHING_UNIT_RE = re.compile(r"每(?!股)[^，。、；]{0,4}?(?:一百|一)(?:元|塊錢)")

RULES = """你是替完全不會看財報的人寫導讀的老師。下面是一家公司的季度財報數字（全部由程式從官方資料算好）。
請挑出這份財報最值得看的欄位，說清楚哪裡怎麼了、為什麼重要，並順便教讀者怎麼看這個指標。只輸出一個 JSON 物件，不要其他文字。

格式：
{"headline": "一句話講這家公司這季最重要的變化",
 "highlights": [{"metric_key": "欄位 key", "period": "期間 key", "importance": "high|medium|low",
                 "what_happened": "發生什麼事", "why_it_matters": "為什麼重要", "how_to_read": "這個指標怎麼看（教學一句）"}]}

規則：
- highlights 挑 3~5 條，依重要度排序。只挑真的有變化或有矛盾的欄位；平穩的不要硬湊。
- metric_key、period 只能用資料包列出的值；月營收用 metric_key "monthly_revenue"、period 用月份（如 2026-09）。
- **文字裡不准自己寫財務數值，阿拉伯數字、全形數字、中文金額（如八百元、三成、兩倍）都不行**，程式會整條丟掉。要引用數字時寫佔位符，程式會換成正確數字：
  {{metric_key@period}} 是該期數值；{{metric_key@period:yoy}} 是年增（比率欄位是年變化幾個百分點）；{{metric_key@period:qoq}} 是季增；
  月營收另有 {{monthly_revenue@月份:mom}} 是月增。例：「毛利率來到 {{gross_margin@2026Q2}}，比去年同季 {{gross_margin@2026Q2:yoy}}」。
  資料包的 tokens 列出每一格可用的佔位符；值是 null 的那一格不能用。
  佔位符換出來會自帶正負號與單位（如 +36.1%、−18.3%、27.25 元），所以前面不要再寫「年增」「年減」「成長」這種方向字，寫成「比去年同季 {{...:yoy}}」「季變化 {{...:qoq}}」，免得變成「年減 −18.3%」。
- 「最高」「最低」「連續幾季」只能照抄每個欄位的 trend（程式算好的），trend 沒寫的就不要自己數；範圍只有資料包這幾季，不要寫成歷史新高。
- 只能根據這些數字推論。數字看不出原因時，就說「財報數字本身看不出原因」並點出該去查什麼（例如法說會、附註），不准編公司事件、產品、客戶或新聞。
- what_happened 要把相關欄位連起來講（例如營收成長但毛利率下滑、獲利成長但現金流沒跟上、淨利跳升但營業利益沒動可能來自業外），不要只複述一個數字。
- how_to_read 要教得具體：這個比率怎麼算出來、往上往下分別代表什麼、常見陷阱，並扣回這家公司這次的情況。不要寫「需持續關注」「值得留意」「宜審慎評估」這類空話。
- 用繁體中文，白話、短句，寫給第一次看財報的人；專有名詞第一次出現時順手解釋。每個欄位不超過 80 字。
- 金融業模板（template=financial）不要用一般公司的標準評論負債比、現金流。
- 不做買賣建議，不寫「建議買進／賣出／加碼／減碼」，也不預測股價。
"""


def _sign(value: float) -> str:
    return "+" if value > 0 else "−" if value < 0 else ""


def format_amount(value: float, currency: Optional[str]) -> str:
    """金額轉中文大單位；貨幣照財報幣別標，避免把台幣標成美元。"""
    unit = {"TWD": "元", "USD": "美元"}.get(currency or "", f" {currency or ''}".rstrip())
    magnitude = abs(value)
    sign = "−" if value < 0 else ""
    if magnitude >= 1e12:
        return f"{sign}{magnitude / 1e12:.2f} 兆{unit}"
    if magnitude >= 1e8:
        return f"{sign}{magnitude / 1e8:,.1f} 億{unit}"
    if magnitude >= 1e4:
        return f"{sign}{magnitude / 1e4:,.0f} 萬{unit}"
    return f"{sign}{magnitude:,.0f} {unit}".strip()


def _format_value(value: Optional[float], kind: str, currency: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if kind == "ratio":
        return f"{_sign(value) if value < 0 else ''}{abs(value):.1f}%"
    if kind == "per_share":
        unit = {"TWD": "元", "USD": "美元"}.get(currency or "", currency or "")
        return f"{_sign(value) if value < 0 else ''}{abs(value):.2f} {unit}".strip()
    return format_amount(value, currency)


def _format_change(value: Optional[float], *, points: bool) -> Optional[str]:
    if value is None:
        return None
    return f"{_sign(value)}{abs(value):.1f}{' 個百分點' if points else '%'}"


def _token_table(payload: dict) -> Dict[str, Optional[str]]:
    """佔位符 -> 顯示字串。LLM 只能引用這張表；None 代表那一格沒有數字。"""
    table: Dict[str, Optional[str]] = {}
    for metric in payload.get("metrics") or []:
        points = metric["kind"] == "ratio"
        for point in metric["points"]:
            base = f"{metric['key']}@{point['period']}"
            table[base] = _format_value(point["value"], metric["kind"], payload.get("currency"))
            # ADR 的 EPS 和原股不同基準，文字裡也要帶口徑，和欄位顯示一致。
            if table[base] and str(metric.get("unit", "")).endswith("/ADR"):
                table[base] += "／ADR"
            table[f"{base}:yoy"] = _format_change(point.get("yoy_pp") if points else point.get("yoy_pct"), points=points)
            table[f"{base}:qoq"] = _format_change(point.get("qoq_pp") if points else point.get("qoq_pct"), points=points)
    for month in payload.get("monthly_revenue") or []:
        base = f"{_MONTHLY_KEY}@{month['month']}"
        table[base] = _format_value(month.get("revenue"), "amount", payload.get("currency"))
        table[f"{base}:yoy"] = _format_change(month.get("yoy_pct"), points=False)
        table[f"{base}:mom"] = _format_change(month.get("mom_pct"), points=False)
    return table


def _valid_targets(payload: dict) -> set:
    targets = {(metric["key"], point["period"]) for metric in payload.get("metrics") or []
               for point in metric["points"] if point["value"] is not None}
    targets |= {(_MONTHLY_KEY, month["month"]) for month in payload.get("monthly_revenue") or []
                if month.get("revenue") is not None}
    return targets


def has_self_written_number(text: str) -> bool:
    """佔位符以外的數值表示：先 NFKC 收斂全形，再看任何 Unicode 數字與中文金額、比率。"""
    normalized = unicodedata.normalize("NFKC", text)
    without_labels = _ALLOWED_DIGITS_RE.sub("", normalized)
    if re.search(r"\d", without_labels):
        return True
    without_teaching = _TEACHING_UNIT_RE.sub("", without_labels)
    return bool(_CN_FINANCIAL_RE.search(without_teaching) or _EN_FINANCIAL_RE.search(without_teaching))


def render_text(text: Any, tokens: Dict[str, Optional[str]], used: Optional[Dict[str, str]] = None) -> Optional[str]:
    """換掉佔位符；對不上佔位符或文字裡自己寫了數值就回 None。`used` 收集實際引用的佔位符與當下的值。"""
    if not isinstance(text, str) or not text.strip():
        return None
    missing = False
    seen: Dict[str, str] = {}

    def replace(match: re.Match) -> str:
        nonlocal missing
        key = f"{match.group(1)}@{match.group(2)}"
        if match.group(3):
            key += f":{match.group(3)}"
        value = tokens.get(key)
        if value is None:
            missing = True
            return ""
        seen[key] = value
        return f"\x00{value}\x00"

    replaced = _TOKEN_RE.sub(replace, text.strip().replace("\x00", ""))
    if missing or "{{" in unicodedata.normalize("NFKC", replaced):
        return None
    outside = "".join(part for index, part in enumerate(replaced.split("\x00")) if index % 2 == 0)
    if has_self_written_number(outside):
        return None
    if used is not None:
        used.update(seen)
    return replaced.replace("\x00", "")[:_TEXT_MAX]


def normalize_commentary(parsed: Any, payload: dict) -> Optional[dict]:
    """把 LLM 輸出收斂成契約；一條不合法只丟那一條，一條都不剩才算失敗。"""
    if not isinstance(parsed, dict):
        return None
    tokens = _token_table(payload)
    targets = _valid_targets(payload)
    highlights: List[dict] = []
    seen = set()
    used: Dict[str, str] = {}
    raw_items = parsed.get("highlights")
    for item in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(item, dict) or len(highlights) >= MAX_HIGHLIGHTS:
            continue
        metric_key, period, importance = item.get("metric_key"), item.get("period"), item.get("importance")
        # 模型可能回陣列或物件；不可雜湊的值不能讓整份導讀變成失敗。
        if not all(isinstance(value, str) for value in (metric_key, period, importance)):
            continue
        target = (metric_key, period)
        if target not in targets or target in seen or importance not in _IMPORTANCE:
            logger.info("[financial_commentary] 丟棄不存在或不合法的欄位: %s", target)
            continue
        item_used: Dict[str, str] = {}
        rendered = {field: render_text(item.get(field), tokens, item_used)
                    for field in ("what_happened", "why_it_matters", "how_to_read")}
        if not all(rendered.values()):
            logger.info("[financial_commentary] 丟棄含無法核對數字的條目: %s", target)
            continue
        seen.add(target)
        used.update(item_used)
        highlights.append({"metric_key": metric_key, "period": period, "importance": importance, **rendered})
    if not highlights:
        return None
    headline = render_text(parsed.get("headline"), tokens, used)
    return {"headline": headline, "highlights": highlights, "used_tokens": used}


def filter_for_payload(content: Any, payload: dict) -> Optional[dict]:
    """快取讀回也驗一次：欄位消失的標記不丟給客戶端；文字引用的數字已變（月營收更正）就當沒有快取。"""
    if not isinstance(content, dict):
        return None
    tokens = _token_table(payload)
    used = content.get("used_tokens")
    if not isinstance(used, dict) or any(tokens.get(key) != value for key, value in used.items()):
        return None
    targets = _valid_targets(payload)
    raw_items = content.get("highlights")
    highlights = [item for item in (raw_items if isinstance(raw_items, list) else [])
                  if isinstance(item, dict) and (item.get("metric_key"), item.get("period")) in targets]
    if not highlights:
        return None
    return {**content, "highlights": highlights}


def latest_period(payload: dict) -> Optional[str]:
    periods = payload.get("periods") or []
    return periods[-1]["key"] if periods else None


def data_hash(payload: dict) -> str:
    """雜湊佔位符依賴的全部季度欄位：畫面外基期重編時值沒變、年增率卻變了，敘述也可能反轉，所以要重生成。

    月營收不算：每月更新不該讓同一季的導讀重生成；已引用的月份改由 `used_tokens` 在讀取時比對。
    """
    basis = [payload.get("currency"), payload.get("template"),
             [(metric["key"], metric.get("kind"), metric.get("unit"),
               [(point["period"], point["value"], point.get("yoy_pct"), point.get("qoq_pct"),
                 point.get("yoy_pp"), point.get("qoq_pp")) for point in metric["points"]])
              for metric in payload.get("metrics") or []]]
    return hashlib.sha256(json.dumps(basis, sort_keys=True).encode("utf-8")).hexdigest()[:32]


def trend_facts(points: List[dict]) -> Optional[str]:
    """排名與連續幾季由程式算：模型自己數實測會錯（2881、6488 的「連續下滑」與資料不符）。"""
    values = [point["value"] for point in points]
    run: List[float] = []
    for value in reversed(values):
        if value is None:
            break
        run.append(value)
    if len(run) < 2:
        return None
    direction = 1 if run[0] > run[1] else -1 if run[0] < run[1] else 0
    streak = 0
    for newer, older in zip(run, run[1:]):
        if direction and (newer - older) * direction > 0:
            streak += 1
        else:
            break
    facts = []
    if streak:
        facts.append(f"最新一季連續 {streak} 季{'上升' if direction > 0 else '下降'}")
    else:
        facts.append("最新一季與上一季持平")
    if run[0] == max(run):
        facts.append(f"是這 {len(run)} 季最高")
    elif run[0] == min(run):
        facts.append(f"是這 {len(run)} 季最低")
    return "，".join(facts)


def build_prompt(payload: dict) -> str:
    tokens = _token_table(payload)
    metrics = []
    for metric in payload.get("metrics") or []:
        rows = []
        for point in metric["points"]:
            base = f"{metric['key']}@{point['period']}"
            rows.append({"period": point["period"], "value": tokens.get(base),
                         "yoy": tokens.get(f"{base}:yoy"), "qoq": tokens.get(f"{base}:qoq"),
                         "tokens": [name for name in (base, f"{base}:yoy", f"{base}:qoq") if tokens.get(name) is not None]})
        metrics.append({"metric_key": metric["key"], "label": metric["label"], "definition": metric["definition"],
                        "trend": trend_facts(metric["points"]), "points": rows})
    months = []
    for month in (payload.get("monthly_revenue") or [])[-6:]:
        base = f"{_MONTHLY_KEY}@{month['month']}"
        months.append({"period": month["month"], "value": tokens.get(base), "yoy": tokens.get(f"{base}:yoy"),
                       "mom": tokens.get(f"{base}:mom"),
                       "tokens": [name for name in (base, f"{base}:yoy", f"{base}:mom") if tokens.get(name) is not None]})
    data = {
        "stock_code": payload.get("stock_code"), "stock_name": payload.get("stock_name"),
        "template": payload.get("template"), "currency": payload.get("currency"),
        "latest_period": latest_period(payload),
        "periods": [{"key": item["key"], "period_end": item["period_end"]} for item in payload.get("periods") or []],
        "metrics": metrics, "monthly_revenue": months,
        "not_applicable": [item["label"] for item in payload.get("not_applicable") or []],
        "data_notes": payload.get("limitations") or [],
    }
    return f"{RULES}\n資料包：\n{json.dumps(data, ensure_ascii=False)}"


def parse_response(text: Optional[str]) -> Optional[dict]:
    """刻意不用 json_repair：截斷的回應修得回來但最後一句是斷的，當失敗處理。"""
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _llm_generate(prompt: str) -> tuple:
    from src.analyzer import GeminiAnalyzer
    from src.config import get_config

    analyzer = GeminiAnalyzer(config=get_config())
    if not analyzer.is_available():
        raise RuntimeError("LLM 未設定或不可用")
    # Sonnet 5.5 的 thinking 算在額度內，4096 在 NAS 實測會回空（見 tw_stock_report._llm_generate）。
    text = analyzer.generate_text(prompt, max_tokens=16384, temperature=0.3, call_type="financial_commentary")
    return text, str(getattr(get_config(), "litellm_model", "") or getattr(get_config(), "generation_backend", "") or "")


def is_enabled() -> bool:
    from src.config import get_config

    return getattr(get_config(), "financial_commentary_enabled", False) is True


def _cache_key(payload: dict) -> Dict[str, str]:
    source = (payload.get("source") or {}).get("id") or ""
    return {"stock_code": payload["stock_code"], "period_key": latest_period(payload) or "", "source": source,
            "prompt_version": PROMPT_VERSION, "data_hash": data_hash(payload)}


def _view(status: str, payload: dict, *, content: Optional[dict] = None, model: Optional[str] = None,
          generated_at: Optional[str] = None, message: Optional[str] = None) -> dict:
    content = content or {}
    return {"status": status, "period": latest_period(payload), "generated_at": generated_at, "model": model,
            "headline": content.get("headline"), "highlights": content.get("highlights") or [], "message": message}


def cached_view(payload: dict) -> dict:
    """開頁路徑：只讀快取，絕不呼叫 LLM。"""
    if payload.get("status") != "ok":
        return _view("not_applicable", payload)
    if not is_enabled():
        return _view("disabled", payload)
    key = _cache_key(payload)
    unsaved = _unsaved.get("|".join(key.values()))
    if unsaved and time.monotonic() < unsaved[0]:
        content = filter_for_payload(unsaved[1], payload)
        if content is not None:
            return _view("ready", payload, content=content, model=unsaved[2])
    try:
        from src.storage import get_db

        record = get_db().get_financial_commentary(**key)
    except Exception as exc:
        logger.warning("[financial_commentary] 讀快取失敗: %s", exc)
        return _view("failed", payload, message="AI 導讀暫時讀不到，數字不受影響。")
    if record is None:
        return _view("missing", payload)
    content = filter_for_payload(record["content"], payload)
    if content is None:
        return _view("missing", payload)
    return _view("ready", payload, content=content, model=record.get("model"), generated_at=record.get("created_at"))


def ensure_commentary(payload: dict, *, generate: Optional[Callable[[str], tuple]] = None) -> dict:
    """使用者開頁時觸發：有快取直接回，沒有才打 LLM。同鍵併發只付一次，失敗短暫記住以免每次開頁都花錢。"""
    view = cached_view(payload)
    if view["status"] != "missing":
        return view
    key = _cache_key(payload)
    identity = "|".join(key.values())
    with _locks_guard:
        lock = _locks.setdefault(identity, threading.Lock())
    with lock:
        view = cached_view(payload)
        if view["status"] != "missing":
            return view
        failed_until = _failures.get(identity, 0.0)
        if time.monotonic() < failed_until:
            return _view("failed", payload, message="AI 導讀剛才產生失敗，數字不受影響；稍後重新開啟可再試一次。")
        try:
            text, model = (generate or _llm_generate)(build_prompt(payload))
            content = normalize_commentary(parse_response(text), payload)
        except Exception as exc:
            logger.warning("[financial_commentary] %s 生成失敗: %s", key["stock_code"], exc)
            content, model = None, None
        if content is None:
            _failures[identity] = time.monotonic() + _FAILURE_TTL_SECONDS
            return _view("failed", payload, message="AI 導讀產生失敗，數字不受影響；稍後重新開啟可再試一次。")
        _failures.pop(identity, None)
        try:
            from src.storage import get_db

            get_db().save_financial_commentary(**key, content=content, model=model)
            _unsaved.pop(identity, None)
        except Exception as exc:
            logger.warning("[financial_commentary] 寫快取失敗，結果暫存程序內: %s", exc)
            now = time.monotonic()
            for stale_key in [k for k, v in _unsaved.items() if now >= v[0]]:
                del _unsaved[stale_key]
            _unsaved[identity] = (now + _UNSAVED_TTL_SECONDS, content, model)
        return _view("ready", payload, content=content, model=model)
