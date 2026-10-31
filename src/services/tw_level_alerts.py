"""台股 SMC 價位警報：把看板上最近的支撐／壓力建成 price_cross 規則，觸發時送 Markdown 訊息。

預設關閉（`TW_LEVEL_ALERTS_ENABLED`），設計與啟用前檢查清單見 `docs/tw-level-alerts.md`。
「最近的支撐／壓力」只在前端算一次（`utils/dossierLevels.ts`，用即時價）；這裡只驗證前端送來的
價位確實是這檔今天的 SMC 價位，不接受任意價格。
"""

from __future__ import annotations

import logging
import math
import threading
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from src.services.alert_messages import quote_source_line

logger = logging.getLogger(__name__)

# 同一檔的重建要排隊：兩個 POST 交錯會互刪對方剛建的規則
# ponytail: 單一行程內的鎖；多個 worker 行程同時寫要改成資料庫層的鎖
_LOCKS: Dict[str, threading.Lock] = {}

SOURCE = "tw_levels"
# 價格在價位附近來回時一天只推一次
COOLDOWN_POLICY = {"cooldown_seconds": 86400}
_SIDES = {"support": ("below", "low", "跌破"), "resistance": ("above", "high", "站上")}


class LevelAlertError(ValueError):
    """前端送來的價位不在今天的 SMC 價位清單裡。"""


def _same(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    return (a.get("kind") == b.get("kind") and abs(float(a.get("low", -1)) - float(b["low"])) < 1e-6
            and abs(float(a.get("high", -1)) - float(b["high"])) < 1e-6)


def plan_rules(code: str, picks: Dict[str, Optional[Dict[str, Any]]], summary: Dict[str, Any],
               name: Optional[str] = None) -> List[Dict[str, Any]]:
    """picks = {"support": level|None, "resistance": level|None} -> AlertService.create_rule 的 payload。"""
    rules = []
    for side, level in picks.items():
        if side not in _SIDES or not level:
            continue
        match = next((x for x in summary.get("levels") or [] if _same(level, x)), None)
        if match is None:
            raise LevelAlertError(f"{code} 今天的 SMC 價位沒有 {level.get('label')} {level.get('low')}~{level.get('high')}")
        direction, edge, verb = _SIDES[side]
        price = float(match[edge])
        rules.append({
            "target_scope": "single_symbol", "target": code, "alert_type": "price_cross",
            "parameters": {"direction": direction, "price": price},
            "name": f"{name or code} {verb}{match['label']} {price:,.2f}"[:64],
            "cooldown_policy": dict(COOLDOWN_POLICY),
            "notification_policy": {"tw_level": {
                "code": code, "name": name, "side": side, "as_of": summary.get("as_of"),
                **{k: match[k] for k in ("label", "low", "high", "kind", "bias")}}},
        })
    return rules


def replace_rules(code: str, rules: List[Dict[str, Any]], service=None) -> List[Dict[str, Any]]:
    """把這檔的價位警報整組換成新的（價位每天會變，舊規則比沒有更糟）。會寫應用庫。

    刪舊與建新在同一個資料庫交易裡完成：任何一步失敗就整組回滾，舊規則原封不動、也不會有半套新規則
    被警報輪詢看到；同一檔的呼叫另外用鎖串行。
    """
    from src.services.alert_service import AlertService

    service = service or AlertService()
    with _LOCKS.setdefault(code, threading.Lock()):
        return service.replace_source_rules(code, rules, source=SOURCE)


def _fmt(v: float) -> str:
    return f"{v:,.2f}".rstrip("0").rstrip(".")


def format_level_alert_markdown(meta: Dict[str, Any], price: Optional[float],
                                summary: Optional[Dict[str, Any]] = None, adjusted: bool = False,
                                quote_source: Optional[str] = None) -> str:
    """觸發訊息（標準 Markdown；Telegram 由 TelegramSender 轉成它的格式，其他渠道照樣可讀）。"""
    side, edge = meta["side"], meta["low"] if meta["side"] == "support" else meta["high"]
    verb, arrow = ("跌破", "🔻") if side == "support" else ("站上", "🔺")
    zone = _fmt(meta["low"]) if meta["low"] == meta["high"] else f"{_fmt(meta['low'])}~{_fmt(meta['high'])}"
    who = f"{meta.get('name') or ''} {meta['code']}".strip()
    lines = [f"**{arrow} {who} {verb}{meta['label']}**", ""]
    if adjusted:
        lines[:0] = [f"⚠️ 價位建立後（{meta.get('as_of')}）有除權息，價位基準已變動，請等盤後資料更新後在盯盤看板重建警報", ""]
    if price:
        lines.append(f"現價 **{_fmt(price)}**（觸發價 {_fmt(edge)}，{(price / edge - 1) * 100:+.1f}%）")
    lines.append(f"- 價位：{meta['label']} {zone}（{meta.get('as_of') or '—'} 的 SMC 價位）")
    s = (summary or {}).get("structure")
    if s:
        lines.append(f"- 結構：{s['date'][5:]} {s['kind']} {'多' if s['bias'] == 'bull' else '空'}（{_fmt(s['level'])}）")
    nxt = _next_level(summary, meta, price or edge)
    if nxt:
        lines.append(f"- 下一個{'支撐' if side == 'support' else '壓力'}：{nxt['label']} "
                     f"{_fmt(nxt['low'])}~{_fmt(nxt['high'])}（{nxt['dist']:+.1f}%）")
    for c in (summary or {}).get("changes") or []:
        lines.append(f"- {c['text']}")
    if quote_source:
        lines.append(f"- {quote_source_line(quote_source)}")
    lines += ["", "_SMC 價位是結構參考，不是買賣訊號；完整分析在盯盤看板的「四維度分析」。_"]
    return "\n".join(lines)


def _next_level(summary, meta, price):
    """觸發後同方向的下一個價位，語意與前端 `dossierLevels.ts` 的 nearestLevels 一致：
    區間完全在現價之下是支撐、之上是壓力；現價在區間裡時多頭區算支撐、空頭區算壓力（距離 0）；
    距離量到近端邊。剛觸發的那個價位本身排除。"""
    side, best = meta["side"], None
    for x in (summary or {}).get("levels") or []:
        if _same(x, meta):
            continue
        inside = x["low"] <= price <= x["high"] and x["low"] != x["high"]
        if side == "support" and ((x.get("bias") == "bull") if inside else x["high"] <= price):
            dist = (min(x["high"], price) / price - 1) * 100
            if best is None or dist > best["dist"]:
                best = {**x, "dist": dist}
        elif side == "resistance" and ((x.get("bias") == "bear") if inside else x["low"] > price):
            dist = (max(x["low"], price) / price - 1) * 100
            if best is None or dist < best["dist"]:
                best = {**x, "dist": dist}
    return best


def valid_level_meta(meta: Any) -> bool:
    """notification_policy.tw_level 是規則裡存的 JSON，用 Markdown 版型前先確認欄位齊全且合理。"""
    from src.services.market_symbol_utils import is_tw_suffix_symbol

    try:
        if not isinstance(meta.get("label"), str) or meta.get("side") not in _SIDES:
            return False
        low, high = meta["low"], meta["high"]
        # 只收真正的數字：字串／bool 過得了 float()，但版型的格式化會丟例外，連通用訊息都送不出
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (low, high)):
            return False
        return (math.isfinite(low) and math.isfinite(high) and 0 < low <= high
                and is_tw_suffix_symbol(str(meta["code"])))
    except (AttributeError, KeyError, TypeError, ValueError):
        return False


def _adjusted_after(code: str, as_of: str) -> bool:
    """as_of 之後（到今天）這檔有沒有除權息／分割／減資事件；查不到一律當沒有（fail-open）。

    用 `market.price_adjustment` 而不是 `ex_dividend`：後者只有上市，缺上櫃與分割、減資。
    """
    try:
        from market_data.market_repo import adjustment_multipliers

        start = date.fromisoformat(str(as_of)[:10]) + timedelta(days=1)
        return not adjustment_multipliers(code.split(".")[0], start=start, end=date.today()).empty
    except Exception as exc:
        logger.warning("[tw_level_alerts] adjustment lookup failed for %s: %s", code, exc)
        return False


def build_level_alert_message(meta: Dict[str, Any], result: Dict[str, Any],
                              quote_source: Optional[str] = None) -> str:
    """alert_worker 的掛鉤：補上最新的結構與下一個價位；摘要讀不到時只送價位本身。"""
    summary = None
    try:
        from src.services.tw_stock_watch import _one

        summary = _one(meta["code"])
    except Exception as exc:
        logger.warning("[tw_level_alerts] summary unavailable for %s: %s", meta.get("code"), exc)
    observed = result.get("observed_value")
    adjusted = bool(meta.get("as_of")) and _adjusted_after(meta["code"], meta["as_of"])
    return format_level_alert_markdown(meta, float(observed) if observed else None, summary, adjusted=adjusted,
                                       quote_source=quote_source)
