# -*- coding: utf-8 -*-
"""screen_tw `render`／`to_json` 逐字基準的輸入（測試與產生 fixture 共用）。

`tests/fixtures/screen_tw_baseline/` 下的檔案是**接上即時名單（處置／注意股、事件日曆）
之前**的 `render`／`to_json` 輸出。`live=None`（或不傳）時新版必須與它逐字相同——只斷言
某一行還在擋不住「順手改了別段的字」。改這裡的輸入就要用改動前的程式重新產生 fixture，
不能拿新版輸出回填（那等於把新版釘成正確答案）。
"""

from __future__ import annotations

import pandas as pd

AS_OF = pd.Timestamp("2026-10-16")
FIXTURE_DIR_NAME = "screen_tw_baseline"


def _row(sid, **kw):
    base = {
        "stock_id": sid, "name": "台泥", "industry": "01", "close": 90.0, "break_pct": 0.05,
        "vol_ratio5": 1.5, "vol_ratio": 1.0, "d1": 0.01, "d5": 0.06, "d20": 0.10, "d60": 0.2,
        "bias20": 0.05, "rsi14": 60.0, "turnover20": 5e8, "inst_5": 2000.0, "inst_20": 5000.0,
        "inst_streak": 3.0, "pe_ratio": 15.0, "pb_ratio": 1.2, "dividend_yield": 3.0,
        "yoy": 30.0, "mom": 2.0, "margin_chg5": 0.0, "from_hi60": -0.10, "pos20": 0.8,
        "ma5": 89.0, "ma10": 88.0, "ma20": 87.0, "ma60": 80.0, "atr_pct": 0.02,
        "hi60_prior": 85.0, "is_etf": False,
    }
    return {**base, **kw}


def baseline_pool():
    """涵蓋 §3 標籤、§5 費半連動／量能偏薄／逐檔查各分支、NaN 欄位的候選池。"""
    return pd.DataFrame([
        _row("2330", name="台積電", industry="24", close=1450.0, d1=-0.06, vol_ratio=2.0,
             bias20=0.15, rsi14=80.0, pe_ratio=150.0, inst_streak=5.0),
        _row("6488", name="環球晶", industry="", turnover20=1.5e8, inst_5=float("nan"),
             inst_20=float("nan"), inst_streak=float("nan"), pe_ratio=float("nan"),
             pb_ratio=float("nan"), dividend_yield=float("nan"), yoy=-5.0),
        _row("1101", dividend_yield=5.0, margin_chg5=-0.08),
        _row("00631L", name="元大台灣50正2", industry="", is_etf=True),
        _row("2887A", name="台新特", industry="17", break_pct=float("nan"),
             vol_ratio5=float("nan")),
        _row("3105", name="穩懋", industry="", d20=0.02),
    ])


def baseline_idx():
    return pd.DataFrame({"date": [AS_OF], "close": [23456.78], "change": [-123.45]})


def baseline_freshness():
    return {"inst_last": pd.Timestamp("2026-10-15"), "inst_sessions": 4,
            "margin_last": pd.Timestamp("2026-10-16"), "margin_sessions": 5,
            "val_date": pd.Timestamp("2026-10-15")}


STEPS = {"全市場有報價": 2000, "排除 ETF 與創新板": 1800, "日均額≥2.0億": 600,
         "突破 60 日高(不含近 5 日)": 40, "月營收 YoY≥20%": 6}


def render_baseline(screen_tw):
    pool = baseline_pool()
    return screen_tw.render(AS_OF, pool, pool, STEPS, -0.005, baseline_idx(), 25, 2.0,
                            False, baseline_freshness())


def json_baseline(screen_tw, strategy="breakout"):
    import json

    out = screen_tw.to_json(AS_OF, baseline_pool(), STEPS, -0.005, strategy, 25, False,
                            baseline_freshness())
    return json.dumps(out, ensure_ascii=False, indent=1, default=float)
