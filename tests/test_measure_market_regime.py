"""scripts/measure_market_regime.py 的純計算部分：價格中立融資變化、狀態、差異 bootstrap。"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from measure_market_regime import (  # noqa: E402
    bootstrap_diff,
    price_neutral_margin_delta,
    regime_states,
)

IDX = pd.bdate_range("2024-01-01", periods=12)


def _frame(a, b):
    return pd.DataFrame({"A": a, "B": b}, index=IDX, dtype=float)


def test_split_and_price_drop_are_not_margin_change():
    # A：第 7 天 1 拆 4（張數×4、未還原價÷4，前復權價不變）；B：股價腰斬、張數不變
    bal = _frame([100] * 6 + [400] * 6, [50] * 12)
    px = _frame([40] * 6 + [10] * 6, [20] * 6 + [10] * 6)
    adj = _frame([10] * 12, [20] * 6 + [10] * 6)
    d = price_neutral_margin_delta(bal, px, adj)
    assert np.allclose(d.dropna(), 0.0)


def test_real_margin_increase_is_positive():
    bal = _frame([100] * 6 + [130] * 6, [50] * 12)
    px = _frame([10] * 12, [20] * 12)
    d = price_neutral_margin_delta(bal, px, px)
    assert d.iloc[6] > 0 and np.isclose(d.iloc[6], 30 * 10)


def test_new_listing_is_not_margin_increase():
    # B 第 4 天才上市：5 天前沒有資料的股票不能被算成融資增加
    bal = _frame([100] * 12, [np.nan] * 3 + [500] * 9)
    px = _frame([10] * 12, [10] * 12)
    d = price_neutral_margin_delta(bal, px, px)
    assert np.allclose(d.dropna(), 0.0)


def test_proxy_halt_does_not_wipe_ma60_window():
    idx = pd.bdate_range("2024-01-01", periods=140)
    proxy = pd.Series(np.linspace(100, 200, 140), index=idx)
    proxy.iloc[80:85] = np.nan  # 分割停牌
    close = pd.DataFrame({"X": proxy.ffill()}, index=idx)
    liquid = close.notna()
    st, _ = regime_states(proxy, close, liquid, pd.Series(1.0, index=idx))
    assert st["0050>季線"].iloc[85:].notna().all()
    assert st["0050>季線"].iloc[80:85].isna().all()
    assert st["季線上彎"].iloc[90:].eq(1).all()


def test_bootstrap_diff_recovers_known_gap():
    rng = np.random.default_rng(0)
    n = 1200
    state = (np.arange(n) // 100 % 2).astype(float)  # 交替 100 天區段
    r = rng.normal(0, 0.01, n) + 0.005 * state
    ci = bootstrap_diff(r, np.ones(n), state, n=300, block=60)
    assert ci is not None and ci[0] > 0 and ci[0] < 0.005 < ci[1]
    flat = bootstrap_diff(rng.normal(0, 0.01, n), np.ones(n), state, n=300, block=60)
    assert flat[0] < 0 < flat[1]
