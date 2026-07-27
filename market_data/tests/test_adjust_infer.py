"""前復權推導的收錄邊界（用未來日期的合成資料，與真實 price 隔離）。

重點是 ``STALE_GAP_DAYS`` 的例外：減資的停止買賣窗口本來就是 2~3 週，
用 gap 一刀切會把最常見的上櫃減資整批漏掉。
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import text

from market_data import adjust

FUTURE = date(2100, 1, 4)   # 真實 price 表不會有 2100 年的資料


def _insert(conn, stock_id, bars):
    for d, o, c in bars:
        conn.execute(text(
            "INSERT INTO market.price (stock_id, date, open, close) "
            "VALUES (:s, :d, :o, :c)"), {"s": stock_id, "d": d, "o": o, "c": c})


def _bars_then_gap(start, n, price, gap_days, reopen_open):
    """n 根平盤 K，隔 gap_days 後以 reopen_open 開盤。"""
    bars = [(start + timedelta(days=i), price, price) for i in range(n)]
    bars.append((start + timedelta(days=n - 1 + gap_days), reopen_open, reopen_open))
    return bars


@pytest.mark.parametrize("gap", [3, 20])
def test_exact_split_ratio_is_kept_regardless_of_gap(pg_conn, gap):
    # 10.0 → 20.0 = 精確 2 倍（減資後復牌的典型型態）
    _insert(pg_conn, "1234", _bars_then_gap(FUTURE, 8, 10.0, gap, 20.0))
    rows = adjust.infer_rows(pg_conn, set(), FUTURE)
    hit = rows[rows["stock_id"] == "1234"]
    assert len(hit) == 1, f"gap={gap} 的精確 2 倍事件應收錄"
    assert hit.iloc[0]["factor"] == 2.0
    assert hit.iloc[0]["kind"] == "split"


def test_non_split_jump_after_long_gap_is_dropped(pg_conn):
    # 10.0 → 13.7：超過漲跌幅但不是任何 1/N 比例，長停牌後的跳空視為資訊反映
    _insert(pg_conn, "5678", _bars_then_gap(FUTURE, 8, 10.0, 20, 13.7))
    rows = adjust.infer_rows(pg_conn, set(), FUTURE)
    assert rows[rows["stock_id"] == "5678"].empty


def test_non_split_jump_within_gap_window_is_inferred(pg_conn):
    _insert(pg_conn, "5679", _bars_then_gap(FUTURE, 8, 10.0, 3, 13.7))
    rows = adjust.infer_rows(pg_conn, set(), FUTURE)
    hit = rows[rows["stock_id"] == "5679"]
    assert len(hit) == 1 and hit.iloc[0]["kind"] == "inferred"
