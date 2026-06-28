#!/usr/bin/env python3
"""把 value-research 的投資論題轉成 DecisionSignal + 價格告警規則（研究 → 監控閉環，Phase 2）。

完全重用既有結構，不改 schema、不改契約：
- DecisionSignalRecord 既有欄位：invalidation(論題逆轉條件)、watch_conditions、target_price、stop_loss、reason。
- 告警用既有 price_cross：target_price → 向上達標(info)；stop_loss → 向下逆轉/停損(warning)。
- source_type="manual"、action ∈ {buy/add/hold/reduce/sell/watch/avoid/alert} 皆為既有允許值。

預設 dry-run（只印 payload，不碰 DB，可離線驗證）；加 --apply 才透過既有 service 落庫。
被 .claude/skills/value-research 的 Step 5 呼叫。

用法：
    uv run python scripts/value_thesis_to_monitoring.py --thesis thesis.json
    uv run python scripts/value_thesis_to_monitoring.py --thesis thesis.json --apply
    echo '{"code":"2330.TW","market":"tw","action":"buy","target_price":900,"stop_loss":520}' \
        | uv run python scripts/value_thesis_to_monitoring.py --thesis -
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from typing import Any, Dict, List


def _finite(value: Any) -> float:
    """轉 float 並拒絕 NaN/Inf（json.loads 預設接受 NaN/Infinity，屬外部輸入須擋）。"""
    f = float(value)
    if not math.isfinite(f):
        raise ValueError(f"numeric value must be finite (got {value!r})")
    return f

# 與 DecisionSignalService._normalize_action 的 DECISION_ACTIONS 對齊（值得買→buy / 觀察→watch / 不碰→avoid）。
VALID_ACTIONS = {"buy", "add", "hold", "reduce", "sell", "watch", "avoid", "alert"}
# 與 DecisionSignalService VALID_MARKETS 對齊（缺失或不合法時 service 會 raise）。
VALID_MARKETS = {"cn", "hk", "us", "jp", "kr", "tw"}


def _clamp_confidence(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return max(0.0, min(1.0, _finite(value)))


def _clamp_score(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return max(0, min(100, int(round(_finite(value)))))


def _positive_float(value: Any) -> float | None:
    """轉 float 並要求 > 0（service 對 price/target 一律要求正數），否則視為無。"""
    if value in (None, ""):
        return None
    f = _finite(value)
    return f if f > 0 else None


def _bullets(items: Any) -> str | None:
    if not items:
        return None
    if isinstance(items, str):
        items = [items]
    lines = [f"- {str(x).strip()}" for x in items if str(x).strip()]
    return "\n".join(lines) or None


def build_signal_payload(thesis: Dict[str, Any]) -> Dict[str, Any]:
    """論題 → DecisionSignalService.create_signal 的 payload（mirror decision_signal_extractor）。"""
    code = str(thesis.get("code") or "").strip()
    if not code:
        raise ValueError("thesis.code is required")
    action = str(thesis.get("action") or "").strip().lower()
    if action not in VALID_ACTIONS:
        raise ValueError(f"action must be one of {sorted(VALID_ACTIONS)} (got {action!r})")

    market = str(thesis.get("market") or "").strip().lower()
    if market not in VALID_MARKETS:
        raise ValueError(f"market must be one of {sorted(VALID_MARKETS)} (got {market!r})")

    breakers = thesis.get("thesis_breakers") or []
    payload: Dict[str, Any] = {
        "stock_code": code,
        "stock_name": thesis.get("name"),
        "market": market,
        "source_type": "manual",
        "trigger_source": "value_research",
        "action": action,
        "confidence": _clamp_confidence(thesis.get("confidence")),
        "score": _clamp_score(thesis.get("score")),
        "horizon": thesis.get("horizon"),
        "entry_low": _positive_float(thesis.get("entry_low")),
        "entry_high": _positive_float(thesis.get("entry_high")),
        "target_price": _positive_float(thesis.get("target_price")),
        "stop_loss": _positive_float(thesis.get("stop_loss")),
        "reason": thesis.get("reason"),
        "invalidation": _bullets(breakers),
        "watch_conditions": _bullets(thesis.get("watch_conditions")),
        "metadata": {"source_skill": "value-research", "thesis_breakers": list(breakers)},
    }
    return {k: v for k, v in payload.items() if v not in (None, "", [], {})}


def build_alert_payloads(thesis: Dict[str, Any]) -> List[Dict[str, Any]]:
    """論題的達標價/停損 → 既有 price_cross 告警規則 payload。"""
    code = str(thesis.get("code") or "").strip()
    if not code:
        raise ValueError("thesis.code is required")
    rules: List[Dict[str, Any]] = []
    tp = _positive_float(thesis.get("target_price"))  # service 要求 price > 0
    sl = _positive_float(thesis.get("stop_loss"))
    if tp is not None:
        rules.append({
            "target_scope": "single_symbol",
            "target": code,
            "alert_type": "price_cross",
            "parameters": {"direction": "above", "price": tp},
            "severity": "info",
            "name": f"{code} 達標 {tp:g}"[:64],
        })
    if sl is not None:
        rules.append({
            "target_scope": "single_symbol",
            "target": code,
            "alert_type": "price_cross",
            "parameters": {"direction": "below", "price": sl},
            "severity": "warning",
            "name": f"{code} 逆轉/停損 {sl:g}"[:64],
        })
    return rules


def _apply(signal_payload: Dict[str, Any], alert_payloads: List[Dict[str, Any]]) -> Dict[str, Any]:
    """透過既有 service 落庫（需 DB / 套件，故只在 --apply 時 import）。"""
    try:
        from src.services.decision_signal_service import DecisionSignalService
        from src.services.alert_service import AlertService

        signal_service = DecisionSignalService()  # 建構即連 DB / 跑 migration
        alert_service = AlertService()
    except Exception as exc:  # DB 未配置 / 套件缺失：給明確指引，不要丟原始 traceback
        raise SystemExit(
            f"--apply 需要可用的 DB（與服務同一套設定，通常經 .env / doppler 注入）。"
            f"初始化失敗：{exc}\n先用 dry-run（不加 --apply）確認 payload 正確。"
        ) from exc

    signal = signal_service.create_signal(signal_payload)
    alerts = [alert_service.create_rule(rule) for rule in alert_payloads]
    return {"signal": signal, "alerts": alerts}


def main() -> int:
    parser = argparse.ArgumentParser(description="value-research 論題 → DecisionSignal + 價格告警")
    parser.add_argument("--thesis", required=True, help="論題 JSON 檔路徑，或 '-' 從 stdin 讀")
    parser.add_argument("--apply", action="store_true", help="實際落庫（預設只 dry-run 印 payload）")
    args = parser.parse_args()

    raw = sys.stdin.read() if args.thesis == "-" else open(args.thesis, encoding="utf-8").read()
    thesis = json.loads(raw)

    signal_payload = build_signal_payload(thesis)
    alert_payloads = build_alert_payloads(thesis)

    if not args.apply:
        print("=== DRY-RUN（加 --apply 才落庫）===")
        print("# DecisionSignal payload")
        print(json.dumps(signal_payload, ensure_ascii=False, indent=2))
        print("\n# Alert rule payloads")
        print(json.dumps(alert_payloads, ensure_ascii=False, indent=2))
        return 0

    result = _apply(signal_payload, alert_payloads)
    sig_id = result["signal"].get("item", {}).get("id")
    print(f"✅ DecisionSignal #{sig_id} 已建立；告警規則 {len(result['alerts'])} 條已建立")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


def _self_check() -> None:
    """ponytail: 純 builder 的最小可跑驗證（不需 DB）。"""
    thesis = {
        "code": "2330.TW", "name": "台積電", "market": "TW", "action": "买",
    }
    # 非法 action 應該擋下
    try:
        build_signal_payload(thesis)
        raise AssertionError("expected invalid action to raise")
    except ValueError:
        pass

    # 非法/缺 market 應該擋下（codex 指出 --apply 會壞）
    try:
        build_signal_payload({"code": "AAPL", "action": "buy"})
        raise AssertionError("expected missing market to raise")
    except ValueError:
        pass

    thesis["action"] = "buy"
    thesis.update({
        "target_price": 900, "stop_loss": 520,
        "confidence": 72,   # 超界輸入應 clamp 到 [0,1]
        "score": 7.6,       # 浮點/超界應 coerce 成 int 0..100
        "entry_low": 0,     # 非正數應被丟棄
        "thesis_breakers": ["先進製程市占跌破 60%", "毛利率連兩季 < 50%"],
        "watch_conditions": ["每季 ROE", "CoWoS 產能"],
        "reason": "護城河深、長期 ROE 高",
    })
    sig = build_signal_payload(thesis)
    assert sig["source_type"] == "manual" and sig["trigger_source"] == "value_research"
    assert sig["action"] == "buy" and sig["market"] == "tw"
    assert sig["confidence"] == 1.0 and sig["score"] == 8  # clamp/coerce 生效
    assert "entry_low" not in sig  # 非正數被丟棄
    assert sig["target_price"] == 900 and sig["stop_loss"] == 520
    assert "先進製程" in sig["invalidation"] and sig["invalidation"].startswith("- ")
    assert "每季 ROE" in sig["watch_conditions"]
    assert sig["metadata"]["thesis_breakers"] == thesis["thesis_breakers"]

    alerts = build_alert_payloads(thesis)
    assert len(alerts) == 2
    above = next(a for a in alerts if a["parameters"]["direction"] == "above")
    below = next(a for a in alerts if a["parameters"]["direction"] == "below")
    assert above["parameters"]["price"] == 900.0 and above["alert_type"] == "price_cross"
    assert below["parameters"]["price"] == 520.0 and below["severity"] == "warning"
    assert all(a["target_scope"] == "single_symbol" and a["target"] == "2330.TW" for a in alerts)

    # 只有結論、無價位時：建 signal 但不建價格告警
    assert build_alert_payloads({"code": "AAPL", "action": "watch"}) == []
    print("self-check OK")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        _self_check()
    else:
        raise SystemExit(main())
