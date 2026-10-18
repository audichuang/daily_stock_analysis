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
    # adjustments 的元素是 (stock_id, date, factor) 或 (stock_id, date, factor, source)
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
    for stock_id, date, factor, *rest in adjustments:
        source = rest[0] if rest else "test"
        conn.execute(text(
            "INSERT INTO market.price_adjustment (stock_id, date, factor, kind, source) "
            "VALUES (:s, :d, :f, 'test', :src)"),
            {"s": stock_id, "d": date, "f": factor, "src": source})


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


def test_factor_read_failure_returns_none_instead_of_raising(pg_conn, monkeypatch):
    """因子讀取失敗（含 statement timeout）要降級回 None，不能穿過呼叫端。

    穿出去的話 `TwseFetcher.get_market_stats` 會整包失敗，連已抓好的成交額與法人一起丟。
    """
    from market_data import adjust

    _seed(pg_conn, info=[("2330", "台積電")],
          rows=[("2330", PREV, 100), ("2330", TODAY, 110)])

    def boom(*args, **kwargs):
        raise RuntimeError("canceling statement due to statement timeout")

    monkeypatch.setattr(adjust, "load_factors", boom)
    assert closing_breadth(_date(TODAY), engine=pg_conn) is None
    # 反向守門：沒壞時同一份資料算得出來，上面的 None 才是因為因子讀取失敗
    monkeypatch.undo()
    assert closing_breadth(_date(TODAY), engine=pg_conn) == {
        "up_count": 1, "down_count": 0, "flat_count": 0}


def test_snapped_official_and_inferred_events_apply_once(pg_conn):
    """休市日的官方事件搬到下一個交易日後，與當天的 inferred 撞日：只乘官方那筆。

    交易日只有 01-02、01-05；官方事件記在休市的 01-03（snap 到 01-05），inferred 記在 01-05。
    兩筆都乘（0.5 × 0.5）會還原兩次。2330 100 -> 55、2317 100 -> 49：
    乘一次，昨收 50 ⇒ 2330 漲、2317 跌；乘兩次，昨收 25 ⇒ 兩檔都漲。
    """
    prev, today = "2099-01-02", "2099-01-05"
    _seed(
        pg_conn,
        info=[("2330", "台積電"), ("2317", "鴻海")],
        rows=[("2330", prev, 100), ("2330", today, 55),
              ("2317", prev, 100), ("2317", today, 49)],
        adjustments=[("2330", "2099-01-03", 0.5, "twse_twt49u"),
                     ("2330", today, 0.5, "inferred_price"),
                     ("2317", "2099-01-03", 0.5, "twse_twt49u"),
                     ("2317", today, 0.5, "inferred_price")],
    )
    assert closing_breadth(_date(today), engine=pg_conn) == {
        "up_count": 1, "down_count": 1, "flat_count": 0}


def test_default_engine_carries_statement_timeout(pg_conn, monkeypatch):
    """不傳 engine 時，預設連線必須帶 statement_timeout，DB 被鎖才會逾時降級。"""
    from data_provider import tw_breadth
    from market_data import db

    calls = []

    def fake_get_engine(url=None, statement_timeout_ms=None):
        calls.append(statement_timeout_ms)
        return pg_conn

    monkeypatch.setattr(db, "get_engine", fake_get_engine)
    _seed(pg_conn, info=[("2330", "台積電")],
          rows=[("2330", PREV, 100), ("2330", TODAY, 110)])
    assert closing_breadth(_date(TODAY)) is not None
    assert calls == [tw_breadth._STATEMENT_TIMEOUT_MS]
    assert tw_breadth._STATEMENT_TIMEOUT_MS == 5000
