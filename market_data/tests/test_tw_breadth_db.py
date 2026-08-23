"""`tw_breadth.closing_breadth` 的 DB 接線。

純計數語意在 `tests/test_tw_breadth_counting.py`（無 DB，主套件跑）。這裡守三件
只有接上 DB 才驗得到的事：**上市普通股口徑**、**前復權**、以及
**`market.price` 停更時拒絕拿舊資料當今天**。

自種資料（隨 `pg_conn` rollback 清除），不依賴庫內既有資料——CI 的 ephemeral
Postgres 是空庫，而開發機是有 16 年真實資料的庫，兩邊都要能過。種子日期刻意放到
2099：`closing_breadth` 的視窗是 `max(date) - 30 days`，把種子放成全庫最新，
真實資料（到 2026）就落在視窗外，計數才會是確定值。
"""

from sqlalchemy import text

from data_provider.tw_breadth import closing_breadth

PREV = "2099-01-04"
TODAY = "2099-01-05"


def _seed(conn, *, rows, info, adjustments=()):
    for stock_id, name in info:
        # 開發機的 stock_info 已有這些上市代碼（CI 空庫沒有），兩邊都要能種。
        conn.execute(text(
            "INSERT INTO market.stock_info (stock_id, name) VALUES (:s, :n) "
            "ON CONFLICT (stock_id) DO NOTHING"),
            {"s": stock_id, "n": name})
    for stock_id, date, close in rows:
        conn.execute(text(
            "INSERT INTO market.price (stock_id, date, close) VALUES (:s, :d, :c)"),
            {"s": stock_id, "d": date, "c": close})
    for stock_id, date, factor in adjustments:
        conn.execute(text(
            "INSERT INTO market.price_adjustment (stock_id, date, factor, kind, source) "
            "VALUES (:s, :d, :f, 'test', 'test')"),
            {"s": stock_id, "d": date, "f": factor})


def _date(s):
    import datetime

    y, m, d = (int(x) for x in s.split("-"))
    return datetime.date(y, m, d)


def test_counts_only_listed_common_stocks(pg_conn):
    """ETF（`00` 前綴）與不在 `stock_info` 的上櫃碼都不得計入。"""
    _seed(
        pg_conn,
        info=[("2330", "台積電"), ("2317", "鴻海"), ("2454", "聯發科"),
              ("2412", "中華電"), ("0050", "元大台灣50")],
        rows=[
            ("2330", PREV, 100), ("2330", TODAY, 110),   # 漲
            ("2317", PREV, 200), ("2317", TODAY, 190),   # 跌
            ("2454", PREV, 300), ("2454", TODAY, 300),   # 平
            ("2412", PREV, 120),                          # 今日無成交 ⇒ 無比價
            ("0050", PREV, 50), ("0050", TODAY, 60),      # ETF，is_common_stock 排除
            ("6488", PREV, 800), ("6488", TODAY, 900),    # 上櫃，不在 stock_info
        ],
    )
    out = closing_breadth(_date(TODAY), engine=pg_conn)
    assert out == {"up_count": 1, "down_count": 1, "flat_count": 1}
    # 反向守門：漏掉 stock_info join 會多算 6488（up 變 2）；
    # 漏掉 is_common_stock 會多算 0050（up 變 2 或 3）。
    assert sum(out.values()) == 3
    assert "limit_up_count" not in out and "limit_down_count" not in out


def test_ex_dividend_day_uses_the_reference_price_not_the_raw_close(pg_conn):
    """前復權必須真的被套上去。

    2330 原始價 100 -> 95 是下跌；但當日有 factor 0.5 的公司行動，
    前復權後昨收變 50、今收 95 ⇒ 官方口徑是**上漲**。沒套因子就會數成下跌。
    """
    _seed(
        pg_conn,
        info=[("2330", "台積電")],
        rows=[("2330", PREV, 100), ("2330", TODAY, 95)],
        adjustments=[("2330", TODAY, 0.5)],
    )
    assert closing_breadth(_date(TODAY), engine=pg_conn) == {
        "up_count": 1, "down_count": 0, "flat_count": 0}


def test_without_an_adjustment_the_same_prices_count_as_a_decline(pg_conn):
    """上一個測試的對照組：同樣的價格、沒有公司行動 ⇒ 就是下跌。

    兩個一起看才證明「因子有被乘上去」而不是「計數方向剛好反了」。
    """
    _seed(
        pg_conn,
        info=[("2330", "台積電")],
        rows=[("2330", PREV, 100), ("2330", TODAY, 95)],
    )
    assert closing_breadth(_date(TODAY), engine=pg_conn) == {
        "up_count": 0, "down_count": 1, "flat_count": 0}


def test_stale_db_is_refused_instead_of_passed_off_as_today(pg_conn):
    """`market.price` 停更（cron 掛掉／TWSE 封 IP，都是靜默的）不能重犯 twtazu_od 那個錯。"""
    _seed(
        pg_conn,
        info=[("2330", "台積電")],
        rows=[("2330", PREV, 100), ("2330", TODAY, 110)],
    )
    assert closing_breadth(_date("2099-01-06"), engine=pg_conn) is None
    # 反向守門：日期相符時必須回得出數字，否則上面那條會因為別的理由而通過
    assert closing_breadth(_date(TODAY), engine=pg_conn) is not None


def test_single_session_cannot_produce_a_comparison(pg_conn):
    _seed(pg_conn, info=[("2330", "台積電")], rows=[("2330", TODAY, 110)])
    assert closing_breadth(_date(TODAY), engine=pg_conn) is None
