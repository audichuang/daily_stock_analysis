"""台股個股 prompt 的「總經背景」資訊區塊（A/B 實驗用，預設關）。

讀本地 ``market.macro_series`` 的日線序列（``market_data.macro.SERIES``，美債殖利率、美元、
原油、黃金、費半、VIX…），每個序列給最新值、資料日、5 日／20 日變化與過期旗標。

只當資訊：區塊固定寫「只當資訊，不得據此調整分數或動作；未經回測」。它不進
``context["daily_market_context"]``，所以大盤環境護欄的文字比對看不到它。

任何失敗都回 None／''（fail-open）；資料日比今天舊太多的序列標過期、不隱藏。
"""

import logging
import math
from datetime import date, timedelta
from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import text

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 60       # 20 個觀測值需要約 30 個日曆日，多抓以涵蓋連假
STALE_DAYS = 5           # 最新資料日距今超過這麼多日曆日就標過期
SHORT_WINDOW = 5
LONG_WINDOW = 20

# 區塊標題（各語言）；analyzer 依「送出的 prompt 裡有沒有這個標題」決定實驗標籤
_HEADINGS = {
    "zh-TW": "### 總經背景（本地資料；僅資訊）",
    "zh": "### 总经背景（本地数据；仅资讯）",
    "en": "### Macro Backdrop (local data; information only)",
}
MACRO_BLOCK_HEADINGS = tuple(_HEADINGS.values())


def has_macro_block(prompt: str) -> bool:
    return any(h in prompt for h in MACRO_BLOCK_HEADINGS)


def _tr(language: str):
    english = language in ("en", "ko")

    def T(zh_tw: str, zh: str, en: str) -> str:
        if english:
            return en
        return zh_tw if language == "zh-TW" else zh

    return T


# ---------------------------------------------------------------- 純計算

def summarize_series(series_id: str, name: str, kind: str,
                     rows: Sequence[Tuple[date, Any]], today: date) -> Optional[Dict[str, Any]]:
    """單一序列（日期升冪）→ 最新值、資料日、5／20 日變化、過期旗標；沒有有限值的列回 None。

    殖利率（kind=="yield"）的變化用 bp，其餘用百分比；回看不足就是 None，不拿 0 充數。"""
    clean = []
    for d, v in rows:
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(fv):
            clean.append((d, fv))
    if not clean:
        return None
    last_d, last_v = clean[-1]

    def change(window: int) -> Optional[float]:
        if len(clean) <= window:
            return None
        base = clean[-1 - window][1]
        if kind == "yield":
            return (last_v - base) * 100.0
        if base == 0:
            return None
        return (last_v / base - 1.0) * 100.0

    return {
        "id": series_id,
        "name": name,
        "kind": kind,
        "as_of": last_d,
        "value": last_v,
        "chg5": change(SHORT_WINDOW),
        "chg20": change(LONG_WINDOW),
        "stale": (today - last_d).days > STALE_DAYS,
    }


# ---------------------------------------------------------------- 讀本地 market schema

def _daily_series():
    from market_data.macro import SERIES

    # 目前 SERIES 都是日線；T-macro 加 freq 欄位後只取 daily
    return [s for s in SERIES if getattr(s, "freq", "daily") == "daily"]


@lru_cache(maxsize=4)
def _load_cached(today_iso: str) -> Optional[Tuple[Dict[str, Any], ...]]:
    # 每個執行期每天只讀一次（失敗也快取 None，避免每檔股票重打一次查詢）
    try:
        from market_data.db import get_engine

        today = date.fromisoformat(today_iso)
        series = _daily_series()
        ids = [s.id for s in series]
        with get_engine(statement_timeout_ms=5000).connect() as conn:
            fetched = conn.execute(text(
                "SELECT series_id, date, value::float8 FROM market.macro_series "
                "WHERE series_id = ANY(:ids) AND date >= :s AND date <= :e ORDER BY series_id, date"),
                {"ids": ids, "s": today - timedelta(days=LOOKBACK_DAYS), "e": today}).fetchall()
        by_id: Dict[str, List[Tuple[date, Any]]] = {}
        for sid, d, v in fetched:
            by_id.setdefault(sid, []).append((d, v))
        out = []
        for s in series:
            row = summarize_series(s.id, s.name, s.kind, by_id.get(s.id, []), today)
            if row:
                out.append(row)
        return tuple(out) or None
    except Exception as exc:  # noqa: BLE001 - prompt enrichment is strictly fail-open
        logger.warning("[tw-macro-context] fail-open: %s", exc)
        return None


def load_macro_context(today: Optional[date] = None) -> Optional[List[Dict[str, Any]]]:
    rows = _load_cached((today or date.today()).isoformat())
    return list(rows) if rows else None


# ---------------------------------------------------------------- prompt 文案

def format_macro_context_block(rows: Optional[Sequence[Dict[str, Any]]], language: str) -> str:
    if not rows:
        return ""
    T = _tr(language)
    heading_key = "en" if language in ("en", "ko") else ("zh-TW" if language == "zh-TW" else "zh")

    def num(v: Optional[float], unit: str) -> str:
        return "N/A" if v is None else f"{v:+.2f}{unit}"

    lines = [
        "\n" + _HEADINGS[heading_key],
        T(
            "只當資訊，不得據此調整分數或動作；未經回測。",
            "只当资讯，不得据此调整分数或动作；未经回测。",
            "Information only: do not adjust the score or the action based on it; not backtested.",
        ),
        T(
            "| 序列 | 最新值 | 資料日 | 5日變化 | 20日變化 | 備註 |",
            "| 序列 | 最新值 | 数据日 | 5日变化 | 20日变化 | 备注 |",
            "| Series | Latest | As of | 5d chg | 20d chg | Note |",
        ),
        "|------|------|------|------|------|------|",
    ]
    for r in rows:
        unit = "bp" if r["kind"] == "yield" else "%"
        note = T("資料過期", "数据过期", "stale") if r.get("stale") else ""
        lines.append(
            f"| {r['name']} | {r['value']:.2f} | {r['as_of']} | "
            f"{num(r['chg5'], unit)} | {num(r['chg20'], unit)} | {note} |"
        )
    return "\n".join(lines) + "\n"
