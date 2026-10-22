"""盯盤看板用的四維度摘要：從資料包抽出結構、關鍵價位與「最近一個交易日變了什麼」。

全部是確定性規則，不呼叫 LLM；解讀卡的色調只在快取已存在時順帶附上。價位一律回絕對價格，
距離由前端用即時價計算（資料包的 price 是上一個收盤）。
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

_LEVEL_RANGE = 0.3          # 只取現價 ±30% 內的價位
_REVENUE_FRESH_DAYS = 7     # 月營收公告後幾天內算「新公告」
_HOLDER_WOW_PP = 0.5        # 千張大戶週變化超過幾個百分點才提示
_SUMMARY_TTL_SECONDS = 600
_summary_cache: dict = {}   # code -> (monotonic, summary)


def smc_levels(s):
    """SMC 價位清單：label、low、high、kind（bsl/ssl/ob/fvg/ote）、bias（bull/bear/None）。"""
    if not s:
        return []
    lv = [{"label": "BSL 上方流動性", "low": x, "high": x, "kind": "bsl", "bias": "bear"} for x in s["bsl"]]
    lv += [{"label": "SSL 下方流動性", "low": x, "high": x, "kind": "ssl", "bias": "bull"} for x in s["ssl"]]
    lv += [{"label": f'{"多頭" if o["direction"] == "bullish" else "空頭"} OB', "low": o["low"], "high": o["high"],
            "kind": "ob", "bias": "bull" if o["direction"] == "bullish" else "bear"} for o in s["order_blocks"]]
    lv += [{"label": "FVG 未回補", "low": g["low"], "high": g["high"], "kind": "fvg",
            "bias": "bull" if g["direction"] == "bullish" else "bear"} for g in s["fvgs"]]
    if s.get("fib"):
        # OTE 的方向跟著最近一次結構事件：多方回檔進場或空方反彈進場；沒有事件就不標方向
        ev = s.get("last_event")
        bias = None if not ev else ("bull" if ev["direction"] == "bullish" else "bear")
        label = {"bull": "OTE 多方進場區", "bear": "OTE 空方進場區"}.get(bias, "OTE 進場區")
        lv.append({"label": label, "low": s["fib"]["ote_low"], "high": s["fib"]["ote_high"],
                   "kind": "ote", "bias": bias})
    price = s["price"]
    return [x for x in lv
            if abs(x["high"] / price - 1) <= _LEVEL_RANGE or abs(x["low"] / price - 1) <= _LEVEL_RANGE]


def _changes(p):
    """最近一個交易日（資料包 as_of）可以提示的變化；每條都帶日期，不寫「今天」。"""
    out, as_of = [], p["as_of"]
    ev = (p.get("smc") or {}).get("last_event")
    if ev and ev["date"][:10] == as_of:
        kind = "ChoCH" if ev["kind"] == "CHOCH" else ev["kind"]
        side = "多" if ev["direction"] == "bullish" else "空"
        out.append({"kind": "structure", "tone": "pos" if side == "多" else "neg",
                    "text": f"{as_of[5:]} {kind} 轉{side}（{ev['level']:,.1f}）"})
    months = (p.get("fundamentals") or {}).get("monthly_revenue") or []
    if months and months[-1].get("announced") and months[-1].get("yoy_pct") is not None:
        ann = months[-1]["announced"]
        if (date.fromisoformat(as_of) - date.fromisoformat(ann)).days <= _REVENUE_FRESH_DAYS:      # 資料包只取已公告的月份
            yoy = months[-1]["yoy_pct"]
            ann_d, month = date.fromisoformat(ann), int(months[-1]["month"][5:7])
            out.append({"kind": "revenue", "tone": "pos" if yoy > 0 else "neg",
                        "text": f"{ann_d:%m/%d} {month} 月營收 YoY {yoy:+.1f}%"})
    inst = (p.get("chips") or {}).get("institutional") or {}
    f5, f20 = inst.get("foreign_5d_lots"), inst.get("foreign_20d_lots")
    if f5 and f20 and (f5 > 0) != (f20 > 0):
        out.append({"kind": "foreign", "tone": "pos" if f5 > 0 else "neg",
                    "text": f"外資 5 日轉{'買' if f5 > 0 else '賣'} {f5:+,} 張（20 日 {f20:+,}）"})
    h = (p.get("chips") or {}).get("holding") or {}
    wow = h.get("big_holder_pct_wow")
    if wow is not None and abs(wow) >= _HOLDER_WOW_PP:
        out.append({"kind": "holder", "tone": "pos" if wow > 0 else "neg",
                    "text": f"千張大戶 {wow:+.2f}pp（{h['as_of'][5:]}）"})
    if p.get("errors"):
        out.append({"kind": "error", "tone": "watch", "text": "部分資料讀取失敗：" + "、".join(p["errors"])})
    return out


def summarize(p, nar=None):
    from src.services.tw_stock_report import NARRATIVE_CHECK_VERSION

    # 數字核對沒過、或用舊版核對規則寫的解讀都不上看板（報告頁才有警示／會重寫）
    if (nar or {}).get("unverified") or (nar and nar.get("check_version") != NARRATIVE_CHECK_VERSION):
        nar = None
    s = p.get("smc") or {}
    ev = s.get("last_event")
    return {
        "name": p.get("name"),
        "as_of": p["as_of"],
        "close": s.get("price"),
        "structure": None if not ev else {
            "kind": "ChoCH" if ev["kind"] == "CHOCH" else ev["kind"],
            "bias": "bull" if ev["direction"] == "bullish" else "bear",
            "date": ev["date"][:10], "level": ev["level"]},
        "levels": smc_levels(s),
        "changes": _changes(p),
        "verdicts": {k: {"badge": v.get("badge"), "tone": v.get("tone")}
                     for k, v in ((nar or {}).get("verdicts") or {}).items()} or None,
    }


def _cached_verdicts(p):
    from src.services.tw_stock_report import _narrative_cache_dir

    path = Path(_narrative_cache_dir()) / f"{p['stock_id']}_{p['as_of']}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except (OSError, ValueError):
        return None


def _one(code):
    from src.services import tw_stock_dossier

    now = time.monotonic()
    hit = _summary_cache.get(code)
    if hit and now - hit[0] < _SUMMARY_TTL_SECONDS:
        p = hit[1]
    else:
        p = tw_stock_dossier.build(code, branch=False)      # 看板不查分點：每檔省兩個富邦請求
        _summary_cache[code] = (now, p)
    # 解讀卡色調每次都重讀（只是讀一個檔），快取期間新產生的解讀也能立刻反映
    return summarize(p, _cached_verdicts(p))


def summaries(codes):
    """codes 已確認是台股；回傳 [(code, summary|None, error|None)]，單檔失敗不拖垮整批。"""
    def run(code):
        try:
            return code, _one(code), None
        except LookupError:
            return code, None, "no_data"
        except Exception as exc:
            logger.warning("[tw_stock_watch] summary failed for %s: %s", code, exc)
            return code, None, "unavailable"

    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(run, codes))
