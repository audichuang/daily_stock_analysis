# -*- coding: utf-8 -*-
"""大盤複盤的指數趨勢與類股排行：純計算函式，加上一個讀 `market` schema 的入口。

- 台股類股：`market.price` 兩個場次的未還原收盤，依成交金額加權。當日有 `price_adjustment`
  事件（除權息、分割、減資）的個股整檔不計入，不做還原。`stock_info` 只有上市，上櫃不在排行內。
- 美股類股：11 檔 GICS SPDR ETF 的當日漲跌，由呼叫端傳入取收盤的函式。
- 沒有讀數就回 None，不給 0。
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

INDEX_TREND_SERIES_LENGTH = 20
_TW_DAILY_LIMIT_PCT = 10.5  # 台股漲跌停 10%，超過代表除權息或基準不同，不算當日漲跌
_TW_MIN_SECTOR_MEMBERS = 3

# TWSE t187ap03_L 的「產業別」是代碼。查無對照的代碼不進排行，不把代碼顯示給使用者。
TW_INDUSTRY_NAMES = {
    "01": "水泥工業", "02": "食品工業", "03": "塑膠工業", "04": "紡織纖維",
    "05": "電機機械", "06": "電器電纜", "08": "玻璃陶瓷", "09": "造紙工業",
    "10": "鋼鐵工業", "11": "橡膠工業", "12": "汽車工業", "14": "建材營造",
    "15": "航運業", "16": "觀光餐旅", "17": "金融保險", "18": "貿易百貨",
    "20": "其他", "21": "化學工業", "22": "生技醫療", "23": "油電燃氣",
    "24": "半導體業", "25": "電腦及週邊設備", "26": "光電業", "27": "通信網路",
    "28": "電子零組件", "29": "電子通路", "30": "資訊服務", "31": "其他電子",
    "32": "文化創意", "33": "農業科技", "35": "綠能環保", "36": "數位雲端",
    "37": "運動休閒", "38": "居家生活",
}

US_SECTOR_ETFS = (
    ("XLK", "科技"), ("XLF", "金融"), ("XLV", "醫療保健"), ("XLY", "非必需消費"),
    ("XLP", "必需消費"), ("XLE", "能源"), ("XLI", "工業"), ("XLB", "原物料"),
    ("XLRE", "不動產"), ("XLU", "公用事業"), ("XLC", "通訊服務"),
)


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def compute_index_trend(rows: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """由升序的 {date, close} 算近 20 場序列與距 MA20／MA60 的百分比。

    場次不足時對應的均線為 None，不拿較短的區間冒充。
    """
    clean = []
    for row in rows or []:
        close = _finite(row.get("close"))
        if close is not None and close > 0 and row.get("date") is not None:
            clean.append((str(row["date"])[:10], close))
    if len(clean) < 2:
        return None
    closes = [close for _, close in clean]
    latest = closes[-1]

    def moving(window: int) -> Optional[float]:
        return sum(closes[-window:]) / window if len(closes) >= window else None

    def distance(ma: Optional[float]) -> Optional[float]:
        return round((latest / ma - 1) * 100, 2) if ma else None

    ma20, ma60 = moving(20), moving(60)
    return {
        "as_of": clean[-1][0],
        "series": [{"date": d, "close": c} for d, c in clean[-INDEX_TREND_SERIES_LENGTH:]],
        "ma20": round(ma20, 2) if ma20 else None,
        "ma60": round(ma60, 2) if ma60 else None,
        "distance_ma20_pct": distance(ma20),
        "distance_ma60_pct": distance(ma60),
    }


def rank_tw_sectors(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """每列 {industry, close, prev_close, turnover} → 依加權漲跌幅由高到低的類股清單。"""
    buckets: Dict[str, List[float]] = {}
    for row in rows or []:
        name = TW_INDUSTRY_NAMES.get(str(row.get("industry") or "").strip().zfill(2))
        close = _finite(row.get("close"))
        prev_close = _finite(row.get("prev_close"))
        turnover = _finite(row.get("turnover"))
        if not name or not close or not prev_close or not turnover or turnover <= 0:
            continue
        pct = (close / prev_close - 1) * 100
        if abs(pct) > _TW_DAILY_LIMIT_PCT:
            continue
        bucket = buckets.setdefault(name, [0.0, 0.0, 0.0])
        bucket[0] += pct * turnover
        bucket[1] += turnover
        bucket[2] += 1
    ranked = [
        {
            "name": name,
            "change_pct": round(weighted / total, 2),
            "turnover": total,
            "stock_count": int(count),
        }
        for name, (weighted, total, count) in buckets.items()
        if count >= _TW_MIN_SECTOR_MEMBERS
    ]
    ranked.sort(key=lambda item: item["change_pct"], reverse=True)
    return ranked


def load_tw_sector_rank(session_date: str, *, engine: Any) -> Optional[Dict[str, Any]]:
    """讀 `market` schema 算某一場次的類股排行。該場次還沒入庫時回 None，不拿舊場次充數。"""
    from market_data import market_repo

    df = market_repo._q(
        "SELECT s.industry, p.close, prev.close AS prev_close, p.turnover "
        "FROM market.price p "
        "JOIN market.stock_info s ON s.stock_id = p.stock_id "
        "JOIN market.price prev ON prev.stock_id = p.stock_id AND prev.date = "
        "(SELECT max(date) FROM market.price WHERE date < :d) "
        "WHERE p.date = :d AND s.industry IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM market.price_adjustment a "
        "WHERE a.stock_id = p.stock_id AND a.date = p.date)",
        {"d": str(session_date)[:10]},
        engine,
    )
    items = rank_tw_sectors(df.to_dict("records"))
    if not items:
        return None
    return {
        "session_date": str(session_date)[:10],
        "source": "market_db",
        "basis": "turnover_weighted",
        "items": items,
    }


def rank_us_sector_etfs(
    session_date: str,
    fetch_closes: Callable[[str], Sequence[Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    """fetch_closes(etf) 回升序 {date, close}；只收最新列屬於該場次的 ETF，單檔失敗不拖垮整批。"""
    session = str(session_date)[:10]
    items: List[Dict[str, Any]] = []
    for code, name in US_SECTOR_ETFS:
        try:
            rows = list(fetch_closes(code) or [])
        except Exception:
            continue
        if len(rows) < 2 or str(rows[-1].get("date"))[:10] != session:
            continue
        close, prev_close = _finite(rows[-1].get("close")), _finite(rows[-2].get("close"))
        if not close or not prev_close:
            continue
        items.append({"code": code, "name": name, "change_pct": round((close / prev_close - 1) * 100, 2)})
    if not items:
        return None
    items.sort(key=lambda item: item["change_pct"], reverse=True)
    return {"session_date": session, "source": "yfinance", "basis": "gics_etf", "items": items}


def load_tw_index_rows(index_id: str, *, engine: Any, limit: int = 60) -> List[Dict[str, Any]]:
    """指數最近 limit 場官方收盤，升序。"""
    from market_data import market_repo

    df = market_repo._q(
        "SELECT date, close FROM market.market_index "
        "WHERE index_id = :iid AND close IS NOT NULL ORDER BY date DESC LIMIT :n",
        {"iid": index_id, "n": int(limit)},
        engine,
    )
    return list(reversed(df.to_dict("records")))
