"""Smart Money Concepts（SMC）價格結構：擺動點、BOS／ChoCH、Order Block、FVG、流動性、Fib 位階。

純函式，不碰 DB 與網路。輸入**前復權**的日 K（升序，欄位 date/open/high/low/close）——
用未還原價的話，除權息跳空會被當成結構破位。

定義（SMC 沒有統一標準，這裡寫死一種，報告引用時照這些定義解讀）：

- **擺動點**：``high[i]`` 嚴格高於前 ``n`` 根、且不低於後 ``n`` 根的最高價（低點對稱）。
  需要右側 ``n`` 根確認，所以最後 ``n`` 根不會出現擺動點。
- **結構事件**：收盤價突破「最近一個尚未被突破的」擺動高（低）點。突破方向與前一次事件
  相同 = BOS（延續）；相反或第一次 = ChoCH（轉折）。
- **Order Block**：多方事件前、從最近擺動低點到突破日之間的最後一根黑 K（close < open），
  區間取該 K 的 low~high；之後收盤跌破 low 即失效。空方對稱（最後一根紅 K）。
- **FVG**：三根 K 的缺口——``low[i] > high[i-2]`` 為多方 FVG（區間 high[i-2]~low[i]）；
  之後最低價觸及區間下緣即視為回補完畢。空方對稱。
- **流動性**：現價上方仍未被突破的擺動高點（BSL）、下方仍未被跌破的擺動低點（SSL）。
- **Fib 位階**：取最後一次事件所在的區間——多方事件用「突破前最近的擺動低點 ~ 之後最高價」，
  空方用「突破前最近的擺動高點 ~ 之後最低價」。``position`` = (現價 − 區間低) / 區間寬；
  > 50% 為 Premium、< 50% 為 Discount。OTE 為該區間 62%~79% 的回檔帶（多方從高點往下量、
  空方從低點往上量）。
"""

from __future__ import annotations

from typing import Optional

import pandas as pd


def swing_points(df: pd.DataFrame, n: int = 3) -> tuple[list[int], list[int]]:
    """回傳 (擺動高點的列位置, 擺動低點的列位置)。"""
    hi, lo = df["high"].to_numpy(float), df["low"].to_numpy(float)
    highs, lows = [], []
    for i in range(n, len(df) - n):
        if hi[i] > hi[i - n:i].max() and hi[i] >= hi[i + 1:i + n + 1].max():
            highs.append(i)
        if lo[i] < lo[i - n:i].min() and lo[i] <= lo[i + 1:i + n + 1].min():
            lows.append(i)
    return highs, lows


def structure_events(df: pd.DataFrame, n: int = 3, swings=None) -> list[dict]:
    """依時間序列出 BOS／ChoCH：``{"i", "date", "kind", "direction", "level", "swing_i"}``。

    ``swings`` 可傳入已算好的 ``swing_points(df, n)``，省一次重算。"""
    highs, lows = swings or swing_points(df, n)
    # 擺動點要等右側 n 根才確認：確認日 j + n -> 擺動點 j
    high_at = {j + n: j for j in highs}
    low_at = {j + n: j for j in lows}
    close = df["close"].to_numpy(float)
    hi, lo = df["high"].to_numpy(float), df["low"].to_numpy(float)
    events, trend = [], None
    last_high = last_low = None          # 最近一個已確認、尚未被突破的擺動點（列位置）
    for i in range(len(df)):
        last_high = high_at.get(i, last_high)
        last_low = low_at.get(i, last_low)
        if last_high is not None and close[i] > hi[last_high]:
            kind = "BOS" if trend == "bullish" else "CHOCH"
            events.append({"i": i, "date": df["date"].iloc[i], "kind": kind,
                           "direction": "bullish", "level": hi[last_high], "swing_i": last_high})
            trend, last_high = "bullish", None
        elif last_low is not None and close[i] < lo[last_low]:
            kind = "BOS" if trend == "bearish" else "CHOCH"
            events.append({"i": i, "date": df["date"].iloc[i], "kind": kind,
                           "direction": "bearish", "level": lo[last_low], "swing_i": last_low})
            trend, last_low = "bearish", None
    return events


def _last_anchor(ev: dict, lows: list[int], highs: list[int], n: int) -> Optional[int]:
    """事件發生時**已確認**（j + n <= 事件日）的最近反向擺動點：多方取低點、空方取高點。

    不加確認條件的話，事件前一兩根才形成、要到事件之後才確認的擺動點會被拿來當錨，
    歷史上的 OB 與 Fib 區間就用到了未來資訊（之後多幾根 K 棒，舊事件的錨會變）。"""
    anchors = [j for j in (lows if ev["direction"] == "bullish" else highs) if j + n <= ev["i"]]
    return anchors[-1] if anchors else None


def _order_block(df: pd.DataFrame, ev: dict, lows: list[int], highs: list[int], n: int) -> Optional[dict]:
    """事件的 Order Block；找不到或之後已被收盤破掉回 None。"""
    o, c = df["open"].to_numpy(float), df["close"].to_numpy(float)
    bullish = ev["direction"] == "bullish"
    anchor = _last_anchor(ev, lows, highs, n)
    start = anchor if anchor is not None else max(0, ev["i"] - 20)
    for k in range(ev["i"] - 1, start - 1, -1):
        if (c[k] < o[k]) if bullish else (c[k] > o[k]):
            low, high = float(df["low"].iloc[k]), float(df["high"].iloc[k])
            after = c[k + 1:]
            if (after < low).any() if bullish else (after > high).any():
                return None
            return {"date": df["date"].iloc[k], "direction": ev["direction"], "low": low, "high": high}
    return None


def fair_value_gaps(df: pd.DataFrame) -> list[dict]:
    """尚未回補完畢的 FVG（時間升序）。"""
    hi, lo = df["high"].to_numpy(float), df["low"].to_numpy(float)
    out = []
    for i in range(2, len(df)):
        if lo[i] > hi[i - 2]:
            bottom, top, d = hi[i - 2], lo[i], "bullish"
            filled = (lo[i + 1:] <= bottom).any()
        elif hi[i] < lo[i - 2]:
            bottom, top, d = hi[i], lo[i - 2], "bearish"
            filled = (hi[i + 1:] >= top).any()
        else:
            continue
        if not filled:
            out.append({"date": df["date"].iloc[i], "direction": d,
                        "low": float(bottom), "high": float(top)})
    return out


def analyze(df: pd.DataFrame, n: int = 3, recent_events: int = 6) -> Optional[dict]:
    """整合輸出。資料少於 ``4n+3`` 根回 None。"""
    df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    if len(df) < 4 * n + 3:
        return None
    highs, lows = swing_points(df, n)
    events = structure_events(df, n, swings=(highs, lows))
    price = float(df["close"].iloc[-1])
    hi, lo = df["high"].to_numpy(float), df["low"].to_numpy(float)

    # 流動性：之後沒有任何最高價超過它的擺動高點（低點對稱）
    bsl = sorted({float(hi[j]) for j in highs if hi[j] > price and not (hi[j + 1:] > hi[j]).any()})
    ssl = sorted({float(lo[j]) for j in lows if lo[j] < price and not (lo[j + 1:] < lo[j]).any()},
                 reverse=True)

    out = {"price": price, "as_of": df["date"].iloc[-1], "swing_n": n,
           "events": events[-recent_events:], "last_event": events[-1] if events else None,
           "order_blocks": [], "fvgs": fair_value_gaps(df)[-5:], "bsl": bsl[:3], "ssl": ssl[:3],
           "fib": None}
    out["order_blocks"] = [ob for ev in events[-recent_events:]
                           if (ob := _order_block(df, ev, lows, highs, n))]

    last = out["last_event"]
    a = _last_anchor(last, lows, highs, n) if last else None
    if a is None:
        return out
    bullish = last["direction"] == "bullish"
    if bullish:
        r_low, r_high = float(lo[a]), float(hi[a:].max())
    else:
        r_high, r_low = float(hi[a]), float(lo[a:].min())
    width = r_high - r_low
    if width > 0:
        pos = (price - r_low) / width
        if bullish:
            ote = (r_high - 0.79 * width, r_high - 0.62 * width)
        else:
            ote = (r_low + 0.62 * width, r_low + 0.79 * width)
        out["fib"] = {"range_low": r_low, "range_high": r_high, "position": pos,
                      "zone": "premium" if pos > 0.5 else "discount",
                      "ote_low": ote[0], "ote_high": ote[1],
                      "in_ote": ote[0] <= price <= ote[1]}
    return out
