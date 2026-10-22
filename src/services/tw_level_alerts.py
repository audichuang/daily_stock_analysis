"""台股 SMC 價位警報：把看板上最近的支撐／壓力建成 price_cross 規則，觸發時送 Markdown 訊息。

預設關閉（`TW_LEVEL_ALERTS_ENABLED`），設計與啟用前檢查清單見 `docs/tw-level-alerts.md`。
「最近的支撐／壓力」只在前端算一次（`utils/dossierLevels.ts`，用即時價）；這裡只驗證前端送來的
價位確實是這檔今天的 SMC 價位，不接受任意價格。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

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
    """先刪掉這檔既有的價位警報（價位每天會變，舊規則比沒有更糟），再建新的。會寫應用庫。"""
    from src.services.alert_service import AlertService

    service = service or AlertService()
    old = service.list_rules(target=code, source=SOURCE, page=1, page_size=100).get("items") or []
    for row in old:
        service.delete_rule(row["id"])
    return [service.create_rule(r, source=SOURCE) for r in rules]


def _fmt(v: float) -> str:
    return f"{v:,.2f}".rstrip("0").rstrip(".")


def format_level_alert_markdown(meta: Dict[str, Any], price: Optional[float],
                                summary: Optional[Dict[str, Any]] = None) -> str:
    """觸發訊息（標準 Markdown；Telegram 由 TelegramSender 轉成它的格式，其他渠道照樣可讀）。"""
    side, edge = meta["side"], meta["low"] if meta["side"] == "support" else meta["high"]
    verb, arrow = ("跌破", "🔻") if side == "support" else ("站上", "🔺")
    zone = _fmt(meta["low"]) if meta["low"] == meta["high"] else f"{_fmt(meta['low'])}~{_fmt(meta['high'])}"
    who = f"{meta.get('name') or ''} {meta['code']}".strip()
    lines = [f"**{arrow} {who} {verb}{meta['label']}**", ""]
    if price:
        lines.append(f"現價 **{_fmt(price)}**（觸發價 {_fmt(edge)}，{(price / edge - 1) * 100:+.1f}%）")
    lines.append(f"- 價位：{meta['label']} {zone}（{meta.get('as_of') or '—'} 的 SMC 價位）")
    s = (summary or {}).get("structure")
    if s:
        lines.append(f"- 結構：{s['date'][5:]} {s['kind']} {'多' if s['bias'] == 'bull' else '空'}（{_fmt(s['level'])}）")
    nxt = _next_level(summary, side, price or edge)
    if nxt:
        lines.append(f"- 下一個{'支撐' if side == 'support' else '壓力'}：{nxt['label']} "
                     f"{_fmt(nxt['low'])}~{_fmt(nxt['high'])}（{nxt['dist']:+.1f}%）")
    for c in (summary or {}).get("changes") or []:
        lines.append(f"- {c['text']}")
    lines += ["", "_SMC 價位是結構參考，不是買賣訊號；完整分析在盯盤看板的「四維度分析」。_"]
    return "\n".join(lines)


def _next_level(summary, side, price):
    """觸發後往同方向的下一個價位（支撐被跌破就找更低的，壓力被突破就找更高的）。"""
    best = None
    for x in (summary or {}).get("levels") or []:
        if side == "support" and x["high"] < price:
            dist = (x["high"] / price - 1) * 100
            if best is None or dist > best["dist"]:
                best = {**x, "dist": dist}
        elif side == "resistance" and x["low"] > price:
            dist = (x["low"] / price - 1) * 100
            if best is None or dist < best["dist"]:
                best = {**x, "dist": dist}
    return best


def build_level_alert_message(meta: Dict[str, Any], result: Dict[str, Any]) -> str:
    """alert_worker 的掛鉤：補上最新的結構與下一個價位；摘要讀不到時只送價位本身。"""
    summary = None
    try:
        from src.services.tw_stock_watch import _one

        summary = _one(meta["code"])
    except Exception as exc:
        logger.warning("[tw_level_alerts] summary unavailable for %s: %s", meta.get("code"), exc)
    observed = result.get("observed_value")
    return format_level_alert_markdown(meta, float(observed) if observed else None, summary)
