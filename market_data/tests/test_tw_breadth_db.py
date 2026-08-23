"""`tw_breadth.closing_breadth` 的 DB 接線（需要 `DATABASE_URL`，CI 會 skip）。

純計數語意在 `tests/test_tw_breadth_counting.py`（無 DB，CI 跑得到）。這裡只守
三件 DB 相關的事：上市口徑、前復權、以及「market.price 停更時拒絕拿舊資料當今天」。
"""

import pandas as pd
from sqlalchemy import text

from data_provider.tw_breadth import closing_breadth


def _latest(conn):
    return conn.execute(text("select max(date) from market.price")).scalar()


def test_returns_counts_for_the_latest_session(pg_conn):
    d = _latest(pg_conn)
    out = closing_breadth(d, engine=pg_conn)
    assert out is not None
    assert set(out) == {"up_count", "down_count", "flat_count"}
    # 上市普通股約 1,000 出頭；若不小心把上櫃或權證放進來會遠超這個量級
    assert 500 < sum(out.values()) < 1300
    # **不得**出現漲跌停家數（本地來源沒有官方參考價與 ±10% 規則）
    assert "limit_up_count" not in out and "limit_down_count" not in out


def test_stale_db_is_refused_instead_of_passed_off_as_today(pg_conn):
    """market.price 停更（cron 掛掉／TWSE 封 IP，都是靜默的）不能重犯 twtazu_od 那個錯。"""
    d = _latest(pg_conn)
    assert closing_breadth(d + pd.Timedelta(days=1), engine=pg_conn) is None


def test_universe_is_listed_common_stock_only(pg_conn):
    """上櫃不在 stock_info、ETF/權證被 is_common_stock 擋掉——用計數量級反證。

    若 join 掉了（變成全市場），分母會從 ~1,000 跳到 ~1,800。
    """
    d = _latest(pg_conn)
    listed_common = pg_conn.execute(text(
        "select count(*) from market.price p "
        "join market.stock_info s on s.stock_id = p.stock_id "
        "where p.date = :d and length(p.stock_id) = 4 and p.stock_id ~ '^[0-9]+$' "
        "  and p.stock_id not like '00%' and p.stock_id not like '91%'"
    ), {"d": d}).scalar()
    out = closing_breadth(d, engine=pg_conn)
    # 分母 = 可比價檔數 ≤ 當日有報價的上市普通股數
    assert sum(out.values()) <= listed_common
    assert sum(out.values()) >= listed_common - 60


def test_adjustment_panel_is_actually_applied(pg_conn, monkeypatch):
    """守住「前復權有被套上去」這條接線。

    除權息事件落在**視窗最後一天**才會改變計數，那種日子很稀少，所以不能靠實資料
    守門。這裡改用假因子面板：把最後一列整體壓到 0.5，若因子真的被乘上去，
    當日就會從「大量上漲」翻成「幾乎全跌」。
    """
    import data_provider.tw_breadth as mod
    from market_data import adjust

    d = _latest(pg_conn)
    baseline = closing_breadth(d, engine=pg_conn)
    assert baseline is not None

    real = adjust.factors_to_panel

    def half_last_row(adj, index, columns):
        fac = real(adj, index, columns)
        fac.iloc[-1] = fac.iloc[-1] * 0.5
        return fac

    monkeypatch.setattr(adjust, "factors_to_panel", half_last_row)
    skewed = closing_breadth(d, engine=pg_conn)
    assert skewed is not None
    # 反向守門：若 closing_breadth 沒有乘上因子，skewed 會等於 baseline
    assert skewed != baseline
    assert skewed["down_count"] > baseline["down_count"]
    assert mod  # 明示本測試針對的模組
