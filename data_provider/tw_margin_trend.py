"""台股融資融券（market.margin）趨勢的純函式。

不碰 DB、網路或任何 I/O，可完整單測。呼叫端（analyzer 的 prompt 層）讀取歷史列後
傳進來；輸出只用來組 LLM prompt 行，不持久化。

單位是**張**（交易單位，不是股）。資料 T+1 發布，最後一列通常落後最新收盤一天，
所以輸出一律帶 ``as_of``。來源：上市 TWSE MI_MARGN、上櫃 TPEx 融資融券餘額。
"""
from __future__ import annotations

from typing import Any, Optional

from data_provider.tw_institutional_trend import _norm_date

# 需要的場次數：N 場次前的餘額要有，所以「近 5 場次變化」要 ≥6 列、「近 20 場次」要 ≥21 列。
_MIN_SESSIONS_5 = 6
_MIN_SESSIONS_20 = 21


def _to_int(value: Any) -> Optional[int]:
    """None / NaN / pd.NA / 非數字一律回 None（int(nan) 會拋 ValueError）。"""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def compute_margin_trend(rows: Any) -> dict:
    """由升序（或亂序，內部會排）的融資融券列算出最新餘額與 5／20 場次變化。

    每列需有 ``date``、``margin_balance``，``short_balance`` 可缺。融資餘額缺值的列
    直接略過（不拿相鄰日補），日期無法解析的列也略過。回傳 ``{}`` 代表沒有可用資料。

    - ``sessions``：實際用到的列數。
    - ``margin_chg_5`` / ``margin_chg_20``：最新融資餘額減去 5／20 個場次前的餘額，
      列數 <6／<21 時為 ``None``（樣本不足時不拿較短的區間冒充）。
    - ``short_margin_ratio``：融券餘額 / 融資餘額 × 100（%），融資餘額 ≤0 或融券缺值為 ``None``。
    絕不 raise。"""
    try:
        series = []
        for row in (rows or []):
            d = _norm_date(row.get("date"))
            bal = _to_int(row.get("margin_balance"))
            if d is None or bal is None:
                continue
            series.append((d, bal, _to_int(row.get("short_balance"))))
        if not series:
            return {}
        series.sort(key=lambda x: x[0])
        # 同一天重複只留最後一列
        dedup: dict = {}
        for d, bal, short in series:
            dedup[d] = (bal, short)
        days = sorted(dedup)
        balances = [dedup[d][0] for d in days]
        latest_margin = balances[-1]
        latest_short = dedup[days[-1]][1]
        n = len(days)
        ratio = None
        if latest_short is not None and latest_margin > 0:
            ratio = latest_short / latest_margin * 100
        return {
            "as_of": days[-1].isoformat(),
            "sessions": n,
            "margin_balance": latest_margin,
            "margin_chg_5": latest_margin - balances[-6] if n >= _MIN_SESSIONS_5 else None,
            "margin_chg_20": latest_margin - balances[-21] if n >= _MIN_SESSIONS_20 else None,
            "short_balance": latest_short,
            "short_margin_ratio": ratio,
        }
    except Exception:  # noqa: BLE001 - 純函式也不得讓 prompt 組裝失敗
        return {}
