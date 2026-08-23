"""`scripts/backfill_price_change_sign.py` 的 SQL 守門。

這支腳本原本**零覆蓋**，於是逐年切窗的 `lag()` 漏掉「每檔每年的第一個交易日」
一直沒被發現——實測漏 6,526 列（2013-01 ~ 2026-01，幾乎全部落在一月頭幾天）。
`market_data/AGENTS.md` 早就記過同一個坑（`infer_rows` 要多讀 60 天歷史）。

自種資料、種在 2099（不受本機實庫干擾），只測 SQL 常數而不跑 main()——
main() 會從 2013 迭代到 max(date) 的年份，對 740 萬列的實庫太慢。
"""

import datetime
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.backfill_price_change_sign import EPS, LOOKBACK_DAYS, _SELECT  # noqa: E402

# 跨年：前一年最後一個交易日 + 新年第一個交易日
PREV_YEAR_LAST = datetime.date(2098, 12, 31)
NEW_YEAR_FIRST = datetime.date(2099, 1, 2)


def _seed(conn, rows):
    for stock_id, d, close, change in rows:
        conn.execute(text(
            "INSERT INTO market.price (stock_id, date, close, change) "
            "VALUES (:s, :d, :c, :ch)"),
            {"s": stock_id, "d": d, "c": close, "ch": change})


def _select(conn, year):
    start = datetime.date(year, 1, 1)
    return conn.execute(text(_SELECT), {
        "start": start,
        "lookback_start": start - datetime.timedelta(days=LOOKBACK_DAYS),
        "end": datetime.date(year + 1, 1, 1),
        "eps": EPS,
    }).fetchall()


def test_first_trading_day_of_the_year_is_not_skipped(pg_conn):
    """回看視窗讓 lag() 拿得到去年最後一根；沒有它這一列會被靜默跳過。"""
    _seed(pg_conn, [
        ("T001", PREV_YEAR_LAST, 100, 5),
        ("T001", NEW_YEAR_FIRST, 95, 5),   # 跌 5，但 change 是 +5 ⇒ 應被選出
    ])
    found = _select(pg_conn, 2099)
    assert (("T001", NEW_YEAR_FIRST)) in [(r[0], r[1]) for r in found]


def test_rows_before_the_target_year_are_not_updated(pg_conn):
    """回看只為了算 lag，**不得**把去年的列也選進來——否則會重複處理已完成的年份。"""
    _seed(pg_conn, [
        ("T002", datetime.date(2098, 12, 29), 100, 5),
        ("T002", PREV_YEAR_LAST, 95, 5),   # 這列本身也「應為負」，但屬 2098
        ("T002", NEW_YEAR_FIRST, 90, 5),
    ])
    dates = [r[1] for r in _select(pg_conn, 2099) if r[0] == "T002"]
    assert NEW_YEAR_FIRST in dates
    assert PREV_YEAR_LAST not in dates


def test_up_days_and_flat_days_are_left_alone(pg_conn):
    """反向守門：只挑「參考價說跌、而 change 是正的」那些列。"""
    _seed(pg_conn, [
        ("T003", PREV_YEAR_LAST, 100, 5),
        ("T003", NEW_YEAR_FIRST, 110, 10),   # 漲
        ("T004", PREV_YEAR_LAST, 100, 0),
        ("T004", NEW_YEAR_FIRST, 100, 0),    # 平
    ])
    picked = {r[0] for r in _select(pg_conn, 2099)}
    assert "T003" not in picked
    assert "T004" not in picked


def test_already_negative_rows_are_left_alone(pg_conn):
    """上櫃列本來就帶號，`change > eps` 天然把它們排除；重跑不得再動它們。"""
    _seed(pg_conn, [
        ("T005", PREV_YEAR_LAST, 100, 5),
        ("T005", NEW_YEAR_FIRST, 95, -5),   # 已經是負的
    ])
    assert [r for r in _select(pg_conn, 2099) if r[0] == "T005"] == []


def test_reference_price_beats_the_raw_close_diff(pg_conn):
    """除權息日：原始收盤下跌，但參考價(prev × factor)說上漲 ⇒ 不該被選出。"""
    _seed(pg_conn, [
        ("T006", PREV_YEAR_LAST, 100, 5),
        ("T006", NEW_YEAR_FIRST, 95, 5),
    ])
    pg_conn.execute(text(
        "INSERT INTO market.price_adjustment (stock_id, date, factor, kind, source) "
        "VALUES ('T006', :d, 0.5, 'test', 'test')"), {"d": NEW_YEAR_FIRST})
    assert [r for r in _select(pg_conn, 2099) if r[0] == "T006"] == []
